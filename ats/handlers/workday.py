import logging
from playwright.async_api import Page

from ats.base import BaseATSHandler, HandlerResult

logger = logging.getLogger("job_pilot.ats.workday")


class WorkdayHandler(BaseATSHandler):
    """
    Workday is multi-step and the most complex ATS. Each step has its own
    page load and the wizard must be navigated sequentially.
    
    Due to the extreme variability of Workday implementations across companies,
    this handler attempts a best-effort approach but frequently falls back to
    needs_review for manual completion.
    """

    async def apply(self, page: Page, job_url: str) -> HandlerResult:
        try:
            await page.goto(job_url, wait_until="networkidle", timeout=45000)
            await self.human_delay(page, 2000, 4000)

            # Detect if we need to sign in or create an account
            if await self._needs_account(page):
                return HandlerResult(
                    False, "needs_review",
                    "Workday requires account creation/login — complete manually"
                )

            # Click the initial "Apply" button if present
            await self._click_apply_entry(page)
            await self.human_delay(page, 2000, 4000)

            # Try the autofill approach: upload resume first, which may pre-fill fields
            await self._try_resume_upload(page)
            await self.human_delay(page)

            # Navigate through wizard steps
            max_steps = 10
            for step in range(max_steps):
                logger.info("Workday wizard step %d", step + 1)

                await self._fill_current_step(page)
                await self.human_delay(page)

                # Check for submission confirmation
                if await self.detect_success(page):
                    return HandlerResult(True, "applied")

                # Try to advance
                if await self._has_next_button(page):
                    await self._click_next(page)
                    await page.wait_for_load_state("networkidle")
                    await self.human_delay(page, 1500, 3000)
                elif await self._has_submit_button(page):
                    await self._click_final_submit(page)
                    await page.wait_for_load_state("networkidle")
                    await self.human_delay(page, 2000, 4000)

                    if await self.detect_success(page):
                        return HandlerResult(True, "applied")
                    break
                else:
                    break

            if await self.detect_success(page):
                return HandlerResult(True, "applied")

            return HandlerResult(False, "needs_review", "Could not confirm Workday submission — review manually")

        except Exception as e:
            logger.error("Workday handler error: %s", e, exc_info=True)
            return HandlerResult(False, "needs_review", f"Handler error: {str(e)[:200]}")

    async def _needs_account(self, page: Page) -> bool:
        body = ""
        try:
            body = (await page.inner_text("body")).lower()
        except Exception:
            return False
        account_hints = ["sign in", "create account", "create an account", "sign up"]
        return any(h in body for h in account_hints)

    async def _click_apply_entry(self, page: Page):
        selectors = [
            'a:has-text("Apply")',
            'button:has-text("Apply")',
            '[data-automation-id="jobPostingApplyButton"]',
            'a[data-automation-id*="apply"]',
        ]
        for sel in selectors:
            if await self.safe_click(page, sel):
                await page.wait_for_load_state("networkidle")
                return

    async def _try_resume_upload(self, page: Page):
        resume_selectors = [
            'input[type="file"]',
            '[data-automation-id="file-upload-input-ref"]',
            'input[data-automation-id*="resume"]',
        ]
        for sel in resume_selectors:
            if await self.upload_resume(page, sel):
                await page.wait_for_timeout(3000)
                return

    async def _fill_current_step(self, page: Page):
        personal = self.profile.get("personal", {})
        loc = personal.get("location", {})
        work_auth = self.profile.get("work_authorization", {})
        answers = self.profile.get("standard_answers", {})
        demographics = self.profile.get("demographics", {})
        education = self.profile.get("education", {})

        # Personal info (Workday uses data-automation-id attributes)
        field_map = {
            "legalNameSection_firstName": personal.get("first_name", ""),
            "legalNameSection_lastName": personal.get("last_name", ""),
            "email": personal.get("email", ""),
            "phone-number": personal.get("phone", ""),
            "addressSection_city": loc.get("city", ""),
            "addressSection_postalCode": loc.get("zip", ""),
        }
        for auto_id, value in field_map.items():
            if value:
                await self.safe_fill(page, f'[data-automation-id="{auto_id}"], [data-automation-id*="{auto_id}"]', value)
                await self.human_delay(page, 300, 800)

        # Generic fill for standard input fields
        inputs = page.locator('input[type="text"]:visible, input:not([type]):visible')
        count = await inputs.count()
        for i in range(count):
            inp = inputs.nth(i)
            try:
                current = await inp.input_value()
                if current.strip():
                    continue
                auto_id = (await inp.get_attribute("data-automation-id") or "").lower()
                placeholder = (await inp.get_attribute("placeholder") or "").lower()
                label_hint = auto_id + " " + placeholder

                value = self._match_input(label_hint, personal, loc, work_auth, answers, education)
                if value:
                    await inp.fill(value)
                    await self.human_delay(page, 200, 600)
            except Exception:
                pass

        # Dropdowns
        selects = page.locator("select:visible")
        sel_count = await selects.count()
        for i in range(sel_count):
            sel_el = selects.nth(i)
            try:
                auto_id = (await sel_el.get_attribute("data-automation-id") or "").lower()
                name = (await sel_el.get_attribute("name") or "").lower()
                hint = auto_id + " " + name

                if "country" in hint:
                    await sel_el.select_option(label=loc.get("country", "United States"))
                elif "state" in hint:
                    await sel_el.select_option(label=loc.get("state", ""))
                elif "gender" in hint:
                    await sel_el.select_option(label=demographics.get("gender", "Prefer not to say"))
                elif "ethnicity" in hint or "race" in hint:
                    await sel_el.select_option(label=demographics.get("ethnicity", "Prefer not to say"))
                elif "veteran" in hint:
                    await sel_el.select_option(label=demographics.get("veteran_status", "I am not a protected veteran"))
                elif "disability" in hint:
                    await sel_el.select_option(label=demographics.get("disability_status", "Prefer not to say"))
            except Exception:
                pass

    def _match_input(self, hint: str, personal: dict, loc: dict, work_auth: dict, answers: dict, education: dict) -> str:
        if "first" in hint and "name" in hint:
            return personal.get("first_name", "")
        if "last" in hint and "name" in hint:
            return personal.get("last_name", "")
        if "email" in hint:
            return personal.get("email", "")
        if "phone" in hint:
            return personal.get("phone", "")
        if "city" in hint:
            return loc.get("city", "")
        if "state" in hint:
            return loc.get("state", "")
        if "zip" in hint or "postal" in hint:
            return loc.get("zip", "")
        if "linkedin" in hint:
            return personal.get("linkedin_url", "")
        if "github" in hint:
            return personal.get("github_url", "")
        if "school" in hint or "university" in hint:
            return education.get("university", "")
        if "degree" in hint:
            return education.get("degree", "")
        if "gpa" in hint:
            return education.get("gpa", "")
        if "salary" in hint or "compensation" in hint:
            return answers.get("salary_expectation", "")
        return ""

    async def _has_next_button(self, page: Page) -> bool:
        selectors = [
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button:has-text("Save and Continue")',
            '[data-automation-id="bottom-navigation-next-button"]',
        ]
        for sel in selectors:
            if await page.locator(sel).count() > 0:
                return True
        return False

    async def _click_next(self, page: Page):
        selectors = [
            '[data-automation-id="bottom-navigation-next-button"]',
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button:has-text("Save and Continue")',
        ]
        for sel in selectors:
            if await self.safe_click(page, sel):
                return

    async def _has_submit_button(self, page: Page) -> bool:
        selectors = [
            'button:has-text("Submit")',
            '[data-automation-id="bottom-navigation-next-button"]:has-text("Submit")',
        ]
        for sel in selectors:
            if await page.locator(sel).count() > 0:
                return True
        return False

    async def _click_final_submit(self, page: Page):
        selectors = [
            'button:has-text("Submit")',
            '[data-automation-id="bottom-navigation-next-button"]',
        ]
        for sel in selectors:
            if await self.safe_click(page, sel):
                return
