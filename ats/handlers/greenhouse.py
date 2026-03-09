import logging
from playwright.async_api import Page

from ats.base import BaseATSHandler, HandlerResult
from email_handler.gmail import GmailHandler

logger = logging.getLogger("job_pilot.ats.greenhouse")


class GreenhouseHandler(BaseATSHandler):

    async def apply(self, page: Page, job_url: str) -> HandlerResult:
        try:
            await page.goto(job_url, wait_until="networkidle", timeout=30000)
            await self.human_delay(page)

            personal = self.profile.get("personal", {})

            await self.safe_fill(page, '#first_name, [name*="first_name"], [autocomplete="given-name"]', personal.get("first_name", ""))
            await self.human_delay(page, 500, 1500)

            await self.safe_fill(page, '#last_name, [name*="last_name"], [autocomplete="family-name"]', personal.get("last_name", ""))
            await self.human_delay(page, 500, 1500)

            await self.safe_fill(page, '#email, [name*="email"], [type="email"]', personal.get("email", ""))
            await self.human_delay(page, 500, 1500)

            await self.safe_fill(page, '#phone, [name*="phone"], [type="tel"]', personal.get("phone", ""))
            await self.human_delay(page, 500, 1500)

            loc = personal.get("location", {})
            location_str = f"{loc.get('city', '')}, {loc.get('state', '')}"
            await self.safe_fill(page, '[name*="location"], [id*="location"]', location_str)
            await self.human_delay(page, 500, 1500)

            await self.safe_fill(page, '[name*="linkedin"], [id*="linkedin"]', personal.get("linkedin_url", ""))
            await self.safe_fill(page, '[name*="github"], [id*="github"]', personal.get("github_url", ""))
            await self.safe_fill(page, '[name*="portfolio"], [name*="website"], [id*="website"]', personal.get("portfolio_url", ""))

            await self.upload_resume(page)
            await self.human_delay(page)

            # Submit initial form
            submitted = await self._click_submit(page)
            if not submitted:
                return HandlerResult(False, "needs_review", "Could not find submit button")

            await page.wait_for_load_state("networkidle")
            await self.human_delay(page)

            # Check for OTP gate
            otp_result = await self._handle_otp_gate(page)
            if otp_result and not otp_result.success:
                return otp_result

            # Fill additional fields (work auth, demographics, custom questions)
            await self._fill_additional_fields(page)
            await self.human_delay(page)

            # Check if there's another submit button (multi-step)
            has_more_submit = await page.locator(
                'button[type="submit"], input[type="submit"], button:has-text("Submit")'
            ).count()
            if has_more_submit > 0:
                await self._click_submit(page)
                await page.wait_for_load_state("networkidle")
                await self.human_delay(page)

            if await self.detect_success(page):
                return HandlerResult(True, "applied")

            return HandlerResult(False, "needs_review", "Could not confirm submission")

        except Exception as e:
            logger.error("Greenhouse handler error: %s", e, exc_info=True)
            return HandlerResult(False, "needs_review", f"Handler error: {str(e)[:200]}")

    async def _click_submit(self, page: Page) -> bool:
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Submit")',
            'button:has-text("Apply")',
            'button:has-text("Submit Application")',
            '#submit_app',
        ]
        for sel in submit_selectors:
            if await self.safe_click(page, sel):
                return True
        return False

    async def _handle_otp_gate(self, page: Page) -> HandlerResult | None:
        """Detect and handle email verification (OTP) gates."""
        try:
            body_text = (await page.inner_text("body")).lower()
        except Exception:
            return None

        otp_phrases = ["verify your email", "check your email", "verification code", "enter the code"]
        if not any(p in body_text for p in otp_phrases):
            return None

        logger.info("OTP gate detected. Polling Gmail...")

        gmail = GmailHandler()
        sender = self.config.get("otp_email_patterns", {}).get("greenhouse", "no-reply@greenhouse.io")
        timeout = self.config.get("otp_timeout_seconds", 120)

        result = await gmail.poll_for_otp(sender, timeout_seconds=timeout)

        if not result:
            return HandlerResult(False, "needs_review", "OTP email not received")

        if "otp" in result:
            otp_selectors = [
                'input[name*="code"]',
                'input[name*="otp"]',
                'input[name*="verification"]',
                'input[type="text"][maxlength]',
                'input[aria-label*="code"]',
            ]
            for sel in otp_selectors:
                if await self.safe_fill(page, sel, result["otp"]):
                    await self.human_delay(page, 500, 1000)
                    await self._click_submit(page)
                    await page.wait_for_load_state("networkidle")
                    return None
            return HandlerResult(False, "needs_review", "OTP received but could not find input field")

        if "link" in result:
            await page.goto(result["link"], wait_until="networkidle", timeout=30000)
            await self.human_delay(page)
            return None

        return None

    async def _fill_additional_fields(self, page: Page):
        """Fill work authorization, demographics, and custom questions."""
        work_auth = self.profile.get("work_authorization", {})
        answers = self.profile.get("standard_answers", {})
        demographics = self.profile.get("demographics", {})

        # Work authorization
        if work_auth.get("authorized_us"):
            await self._select_yes_no(page, "authorized", True)
        if not work_auth.get("requires_sponsorship"):
            await self._select_yes_no(page, "sponsorship", False)

        # Salary
        await self.safe_fill(page, '[name*="salary"], [id*="salary"]', answers.get("salary_expectation", ""))

        # Demographics / EEO
        await self.safe_select(page, '[name*="gender"], [id*="gender"]', demographics.get("gender", "Prefer not to say"))
        await self.safe_select(page, '[name*="race"], [name*="ethnicity"], [id*="ethnicity"]', demographics.get("ethnicity", "Prefer not to say"))
        await self.safe_select(page, '[name*="veteran"], [id*="veteran"]', demographics.get("veteran_status", "I am not a protected veteran"))
        await self.safe_select(page, '[name*="disability"], [id*="disability"]', demographics.get("disability_status", "Prefer not to say"))

        # Experience years
        exp = str(self.profile.get("experience_years", ""))
        await self.safe_fill(page, '[name*="experience"], [id*="experience"]', exp)

    async def _select_yes_no(self, page: Page, field_hint: str, yes: bool):
        """Try to select Yes/No for a field matching the hint."""
        value = "Yes" if yes else "No"
        selectors = [
            f'select[name*="{field_hint}"]',
            f'select[id*="{field_hint}"]',
        ]
        for sel in selectors:
            if await self.safe_select(page, sel, value):
                return

        label_text = f'label:has-text("{value}")'
        radio = page.locator(f'fieldset:has([name*="{field_hint}"]) >> {label_text}').first
        try:
            if await radio.count() > 0:
                await radio.click()
        except Exception:
            pass
