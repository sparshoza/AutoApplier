import logging
from playwright.async_api import Page

from ats.base import BaseATSHandler, HandlerResult

logger = logging.getLogger("job_pilot.ats.lever")


class LeverHandler(BaseATSHandler):

    async def apply(self, page: Page, job_url: str) -> HandlerResult:
        try:
            # Lever apply URLs typically end with /apply
            if not job_url.rstrip("/").endswith("/apply"):
                job_url = job_url.rstrip("/") + "/apply"

            await page.goto(job_url, wait_until="networkidle", timeout=30000)
            await self.human_delay(page)

            personal = self.profile.get("personal", {})
            loc = personal.get("location", {})

            # Lever uses specific field names
            await self.safe_fill(page, '[name="name"]', f"{personal.get('first_name', '')} {personal.get('last_name', '')}")
            await self.human_delay(page, 500, 1500)

            await self.safe_fill(page, '[name="email"]', personal.get("email", ""))
            await self.human_delay(page, 500, 1500)

            await self.safe_fill(page, '[name="phone"]', personal.get("phone", ""))
            await self.human_delay(page, 500, 1500)

            await self.safe_fill(page, '[name="org"], [name*="company"], [name*="current"]', self._current_company())
            await self.human_delay(page, 500, 1000)

            location_str = f"{loc.get('city', '')}, {loc.get('state', '')}"
            await self.safe_fill(page, '[name*="location"]', location_str)

            await self.safe_fill(page, '[name*="linkedin"], [name="urls[LinkedIn]"]', personal.get("linkedin_url", ""))
            await self.safe_fill(page, '[name*="github"], [name="urls[GitHub]"]', personal.get("github_url", ""))
            await self.safe_fill(page, '[name*="portfolio"], [name="urls[Portfolio]"], [name*="website"]', personal.get("portfolio_url", ""))

            await self.upload_resume(page)
            await self.human_delay(page)

            # Fill custom questions
            await self._fill_custom_fields(page)

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
            logger.error("Lever handler error: %s", e, exc_info=True)
            return HandlerResult(False, "needs_review", f"Handler error: {str(e)[:200]}")

    def _current_company(self) -> str:
        history = self.profile.get("employment_history", [])
        if history:
            return history[0].get("company", "")
        return ""

    async def _click_submit(self, page: Page) -> bool:
        selectors = [
            'button[type="submit"]',
            'button:has-text("Submit application")',
            'button:has-text("Submit")',
            'button:has-text("Apply")',
            'a.postings-btn',
        ]
        for sel in selectors:
            if await self.safe_click(page, sel):
                return True
        return False

    async def _fill_custom_fields(self, page: Page):
        answers = self.profile.get("standard_answers", {})
        work_auth = self.profile.get("work_authorization", {})

        # Common Lever custom question fields
        textareas = page.locator("textarea")
        count = await textareas.count()
        for i in range(count):
            ta = textareas.nth(i)
            current_val = await ta.input_value()
            if not current_val.strip():
                label = await self._get_field_label(page, ta)
                answer = self._match_answer(label, answers, work_auth)
                if answer:
                    try:
                        await ta.fill(answer)
                        await self.human_delay(page, 300, 800)
                    except Exception:
                        pass

    async def _get_field_label(self, page: Page, element) -> str:
        try:
            parent = element.locator("xpath=..")
            label = parent.locator("label, .application-label, .field-label").first
            if await label.count() > 0:
                return (await label.inner_text()).lower()
        except Exception:
            pass
        return ""

    def _match_answer(self, label: str, answers: dict, work_auth: dict) -> str:
        if not label:
            return ""
        if "salary" in label or "compensation" in label:
            return answers.get("salary_expectation", "")
        if "notice" in label:
            return answers.get("notice_period", "")
        if "relocat" in label:
            return answers.get("willing_to_relocate", "")
        if "remote" in label:
            return answers.get("remote_preference", "")
        if "interest" in label or "why" in label:
            return answers.get("why_interested", "")
        if "sponsor" in label:
            return "No" if not work_auth.get("requires_sponsorship") else "Yes"
        if "authorized" in label or "authoris" in label or "legally" in label:
            return "Yes" if work_auth.get("authorized_us") else "No"
        return ""
