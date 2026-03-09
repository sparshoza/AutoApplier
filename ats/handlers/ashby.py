import logging
from playwright.async_api import Page

from ats.base import BaseATSHandler, HandlerResult

logger = logging.getLogger("job_pilot.ats.ashby")


class AshbyHandler(BaseATSHandler):

    async def apply(self, page: Page, job_url: str) -> HandlerResult:
        try:
            await page.goto(job_url, wait_until="networkidle", timeout=30000)
            await self.human_delay(page)

            # Ashby sometimes has an "Apply" button to reveal the form
            await self.safe_click(page, 'button:has-text("Apply"), a:has-text("Apply for this job")')
            await page.wait_for_timeout(2000)

            personal = self.profile.get("personal", {})
            loc = personal.get("location", {})

            # Ashby uses _systemfield_ prefixed names and data-testid attributes
            name_selectors = [
                '[name*="name"], [data-testid*="name"]',
                '[name="_systemfield_name"], [placeholder*="Full name"]',
            ]
            for sel in name_selectors:
                filled = await self.safe_fill(page, sel, f"{personal.get('first_name', '')} {personal.get('last_name', '')}")
                if filled:
                    break
            await self.human_delay(page, 500, 1500)

            email_selectors = [
                '[name*="email"], [data-testid*="email"]',
                '[name="_systemfield_email"], [type="email"]',
            ]
            for sel in email_selectors:
                filled = await self.safe_fill(page, sel, personal.get("email", ""))
                if filled:
                    break
            await self.human_delay(page, 500, 1500)

            phone_selectors = [
                '[name*="phone"], [data-testid*="phone"]',
                '[name="_systemfield_phone"], [type="tel"]',
            ]
            for sel in phone_selectors:
                filled = await self.safe_fill(page, sel, personal.get("phone", ""))
                if filled:
                    break
            await self.human_delay(page, 500, 1500)

            location_str = f"{loc.get('city', '')}, {loc.get('state', '')}"
            await self.safe_fill(page, '[name*="location"], [data-testid*="location"]', location_str)

            await self.safe_fill(page, '[name*="linkedin"], [data-testid*="linkedin"]', personal.get("linkedin_url", ""))
            await self.safe_fill(page, '[name*="github"], [data-testid*="github"]', personal.get("github_url", ""))
            await self.safe_fill(page, '[name*="portfolio"], [name*="website"]', personal.get("portfolio_url", ""))

            await self.upload_resume(page)
            await self.human_delay(page)

            # Additional fields
            await self._fill_additional_fields(page)

            # Submit
            submitted = await self._click_submit(page)
            if not submitted:
                return HandlerResult(False, "needs_review", "Could not find submit button")

            await page.wait_for_load_state("networkidle")
            await self.human_delay(page, 2000, 4000)

            if await self.detect_success(page):
                return HandlerResult(True, "applied")

            return HandlerResult(False, "needs_review", "Could not confirm submission")

        except Exception as e:
            logger.error("Ashby handler error: %s", e, exc_info=True)
            return HandlerResult(False, "needs_review", f"Handler error: {str(e)[:200]}")

    async def _click_submit(self, page: Page) -> bool:
        selectors = [
            'button[type="submit"]',
            'button:has-text("Submit")',
            'button:has-text("Submit application")',
            'button:has-text("Apply")',
        ]
        for sel in selectors:
            if await self.safe_click(page, sel):
                return True
        return False

    async def _fill_additional_fields(self, page: Page):
        answers = self.profile.get("standard_answers", {})
        work_auth = self.profile.get("work_authorization", {})
        demographics = self.profile.get("demographics", {})

        # Try common select dropdowns
        select_fields = page.locator("select")
        count = await select_fields.count()
        for i in range(count):
            sel_el = select_fields.nth(i)
            try:
                name = await sel_el.get_attribute("name") or ""
                name_lower = name.lower()

                if "gender" in name_lower:
                    await sel_el.select_option(label=demographics.get("gender", "Prefer not to say"))
                elif "race" in name_lower or "ethnicity" in name_lower:
                    await sel_el.select_option(label=demographics.get("ethnicity", "Prefer not to say"))
                elif "veteran" in name_lower:
                    await sel_el.select_option(label=demographics.get("veteran_status", "I am not a protected veteran"))
                elif "disability" in name_lower:
                    await sel_el.select_option(label=demographics.get("disability_status", "Prefer not to say"))
                elif "authorized" in name_lower:
                    val = "Yes" if work_auth.get("authorized_us") else "No"
                    await sel_el.select_option(label=val)
                elif "sponsor" in name_lower:
                    val = "No" if not work_auth.get("requires_sponsorship") else "Yes"
                    await sel_el.select_option(label=val)
            except Exception:
                pass

        # Fill any empty text inputs or textareas that look like custom questions
        textareas = page.locator("textarea")
        ta_count = await textareas.count()
        for i in range(ta_count):
            ta = textareas.nth(i)
            current = await ta.input_value()
            if not current.strip():
                try:
                    await ta.fill(answers.get("why_interested", ""))
                    await self.human_delay(page, 300, 800)
                except Exception:
                    pass
