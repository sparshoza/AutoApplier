import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from playwright.async_api import Page

logger = logging.getLogger("job_pilot.ats")

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "screenshots")


class HandlerResult:
    def __init__(self, success: bool, status: str, warning_reason: str | None = None):
        self.success = success
        self.status = status
        self.warning_reason = warning_reason

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "status": self.status,
            "warning_reason": self.warning_reason,
        }


class BaseATSHandler(ABC):

    def __init__(self, profile: dict, config: dict):
        self.profile = profile
        self.config = config

    @abstractmethod
    async def apply(self, page: Page, job_url: str) -> HandlerResult:
        """Navigate to job_url, fill out the application, and return a result."""

    # ── Shared utility methods ──

    async def safe_fill(self, page: Page, selector: str, value: str, timeout: int = 3000):
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                await el.click(timeout=timeout)
                await el.fill(value, timeout=timeout)
                return True
        except Exception:
            pass
        return False

    async def safe_click(self, page: Page, selector: str, timeout: int = 3000) -> bool:
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                await el.click(timeout=timeout)
                return True
        except Exception:
            pass
        return False

    async def safe_select(self, page: Page, selector: str, value: str, timeout: int = 3000) -> bool:
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                await el.select_option(value=value, timeout=timeout)
                return True
        except Exception:
            pass
        return False

    async def upload_resume(self, page: Page, selector: str = 'input[type="file"]') -> bool:
        resume_path = self.profile.get("resume_path", "")
        if not resume_path or not os.path.exists(resume_path):
            logger.warning("Resume file not found: %s", resume_path)
            return False
        try:
            file_input = page.locator(selector).first
            if await file_input.count() > 0:
                await file_input.set_input_files(resume_path)
                return True
        except Exception as e:
            logger.warning("Resume upload failed: %s", e)
        return False

    async def take_failure_screenshot(self, page: Page, job_id: str) -> str | None:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{job_id}_{ts}.png"
        path = os.path.join(SCREENSHOTS_DIR, filename)
        try:
            await page.screenshot(path=path, full_page=True)
            return os.path.join("screenshots", filename)
        except Exception as e:
            logger.warning("Screenshot failed: %s", e)
            return None

    async def detect_success(self, page: Page) -> bool:
        """Check if the page shows a success/confirmation message."""
        success_patterns = [
            "thank you",
            "application submitted",
            "application received",
            "successfully submitted",
            "we have received your application",
            "you have applied",
            "application complete",
        ]
        try:
            text = (await page.inner_text("body")).lower()
            return any(p in text for p in success_patterns)
        except Exception:
            return False

    async def human_delay(self, page: Page, min_ms: int = 1000, max_ms: int = 3000):
        import random
        delay = random.randint(min_ms, max_ms)
        await page.wait_for_timeout(delay)
