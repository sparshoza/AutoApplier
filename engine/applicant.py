import asyncio
import logging
import random
import time
from datetime import datetime

from db.schema import get_db
from browser.manager import BrowserManager
from browser.interceptors import register_interceptors
from ats.base import BaseATSHandler
from ats.handlers.greenhouse import GreenhouseHandler
from ats.handlers.lever import LeverHandler
from ats.handlers.ashby import AshbyHandler
from ats.handlers.workday import WorkdayHandler

logger = logging.getLogger("job_pilot.engine")


class ApplicationEngine:

    def __init__(self, browser: BrowserManager, profile: dict, config: dict):
        self.browser = browser
        self.profile = profile
        self.config = config
        self._hourly_count = 0
        self._hour_start = time.time()
        self._last_ats_apply: dict[str, float] = {}

    def _get_handler(self, ats_type: str) -> BaseATSHandler | None:
        handlers = {
            "greenhouse": GreenhouseHandler,
            "lever": LeverHandler,
            "ashby": AshbyHandler,
            "workday": WorkdayHandler,
        }
        cls = handlers.get(ats_type)
        if cls:
            return cls(self.profile, self.config)
        return None

    def _check_rate_limit(self) -> bool:
        max_per_hour = self.config.get("rate_limits", {}).get("max_per_hour", 15)
        now = time.time()

        if now - self._hour_start > 3600:
            self._hourly_count = 0
            self._hour_start = now

        if self._hourly_count >= max_per_hour:
            logger.info("Hourly rate limit reached (%d). Stopping.", max_per_hour)
            return False
        return True

    async def _wait_rate_delay(self, ats_type: str):
        limits = self.config.get("rate_limits", {})
        min_delay = limits.get("min_delay_seconds", 30)
        jitter = random.randint(-5, 5)
        delay = max(5, min_delay + jitter)

        # Per-ATS cooldown
        cooldown = limits.get("per_ats_cooldown_seconds", 60)
        last = self._last_ats_apply.get(ats_type, 0)
        since_last = time.time() - last
        if since_last < cooldown:
            extra = cooldown - since_last
            delay = max(delay, extra)

        logger.info("Waiting %.0f seconds before next application", delay)
        await asyncio.sleep(delay)

    async def run(self):
        """Process all queued jobs through their ATS handlers."""
        db = await get_db()
        try:
            rows = await db.execute_fetchall(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY scraped_at ASC"
            )
        finally:
            await db.close()

        if not rows:
            logger.info("No queued jobs to process.")
            return

        logger.info("Processing %d queued jobs", len(rows))

        for row in rows:
            if not self._check_rate_limit():
                break

            job_id = row["id"]
            external_id = row["job_id"]
            ats_type = row["ats_type"]
            apply_url = row["apply_url"]

            logger.info("Applying to: %s (%s) via %s", row["title"], row["company"], ats_type)

            # Update status to applying
            db = await get_db()
            try:
                await db.execute("UPDATE jobs SET status = 'applying' WHERE id = ?", (job_id,))
                await db.commit()
            finally:
                await db.close()

            handler = self._get_handler(ats_type)
            if not handler:
                await self._mark_needs_review(
                    job_id, external_id,
                    f"No handler for ATS type: {ats_type}",
                    page=None,
                )
                continue

            page = None
            try:
                page = await self.browser.new_page()

                popup_reason = None

                def on_popup(reason):
                    nonlocal popup_reason
                    popup_reason = reason

                register_interceptors(page, on_popup_during_apply=on_popup)

                result = await handler.apply(page, apply_url)

                if popup_reason and not result.success:
                    result.warning_reason = popup_reason

                if result.success:
                    await self._mark_applied(job_id)
                    await self._sync_jobright_status(page, external_id)
                else:
                    screenshot = await handler.take_failure_screenshot(page, external_id)
                    await self._mark_needs_review(
                        job_id, external_id,
                        result.warning_reason or "Unknown failure",
                        page=None,
                        screenshot_path=screenshot,
                    )

                self._hourly_count += 1
                self._last_ats_apply[ats_type] = time.time()

            except Exception as e:
                logger.error("Unhandled error for job %s: %s", external_id, e, exc_info=True)
                screenshot_path = None
                if page:
                    from ats.base import BaseATSHandler, SCREENSHOTS_DIR
                    try:
                        import os
                        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        fname = f"{external_id}_{ts}.png"
                        path = os.path.join(SCREENSHOTS_DIR, fname)
                        await page.screenshot(path=path, full_page=True)
                        screenshot_path = os.path.join("screenshots", fname)
                    except Exception:
                        pass

                await self._mark_needs_review(
                    job_id, external_id,
                    f"Unhandled error: {str(e)[:200]}",
                    page=None,
                    screenshot_path=screenshot_path,
                )
            finally:
                if page:
                    await self.browser.close_page(page)

            await self._wait_rate_delay(ats_type)

    async def _mark_applied(self, job_id: int):
        db = await get_db()
        try:
            await db.execute(
                "UPDATE jobs SET status = 'applied', applied_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job_id,),
            )
            await db.commit()
        finally:
            await db.close()
        logger.info("Job %d marked as applied.", job_id)

    async def _sync_jobright_status(self, page, external_id: str):
        """Navigate to the job on jobright.ai, click Apply, then confirm 'Yes, I applied!'."""
        if not external_id.startswith("jobright_"):
            return
        jobright_id = external_id[len("jobright_"):]
        info_url = f"https://jobright.ai/jobs/info/{jobright_id}"

        try:
            await page.goto(info_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)

            # Click the Apply button on the jobright page
            apply_btn = page.locator(
                'button:has-text("Apply with Autofill"), button:has-text("APPLY NOW"), '
                'button[class*="apply-button"]'
            ).first
            if await apply_btn.count() > 0:
                context = page.context
                # Catch and immediately close any new tab that opens
                async def close_new_tab(new_page):
                    try:
                        await new_page.close()
                    except Exception:
                        pass

                handler = lambda p: asyncio.ensure_future(close_new_tab(p))
                context.on("page", handler)

                await apply_btn.click(timeout=5000)
                await page.wait_for_timeout(3000)

                try:
                    context.remove_listener("page", handler)
                except Exception:
                    pass

                # Click "Yes, I applied!" on the confirmation modal
                yes_btn = page.locator('button:has-text("Yes, I applied")').first
                if await yes_btn.count() > 0:
                    await yes_btn.click(timeout=3000)
                    await page.wait_for_timeout(1000)
                    logger.info("Synced applied status on jobright.ai for %s", jobright_id)
                else:
                    logger.warning("Could not find 'Yes, I applied' button on jobright for %s", jobright_id)
            else:
                logger.warning("No apply button found on jobright info page for %s", jobright_id)
        except Exception as e:
            logger.warning("Failed to sync jobright status for %s: %s", jobright_id, e)

    async def _mark_needs_review(
        self, job_id: int, external_id: str, reason: str,
        page=None, screenshot_path: str | None = None,
    ):
        db = await get_db()
        try:
            await db.execute(
                "UPDATE jobs SET status = 'needs_review', warning_reason = ?, screenshot_path = ? WHERE id = ?",
                (reason, screenshot_path, job_id),
            )
            await db.commit()
        finally:
            await db.close()
        logger.warning("Job %s needs review: %s", external_id, reason)
