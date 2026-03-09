import asyncio
import logging
import re
from datetime import datetime, timedelta
from playwright.async_api import Page, BrowserContext

from scraper.base import BaseScraper

logger = logging.getLogger("job_pilot.scraper.jobright")


class JobrightScraper(BaseScraper):
    """
    Scraper for jobright.ai.
    Selectors reverse-engineered from the live DOM (March 2026).

    Card structure:
      div.job-card-flag-classname[id=<jobright_id>]
        h2[class*="job-title"]          → title
        div[class*="company-name"]      → company
        span[class*="publish-time"]     → relative date
        img[alt="position"] sibling span → location
        button "Apply with Autofill" / "APPLY NOW"  → opens ATS in new tab
    """

    @property
    def name(self) -> str:
        return "jobright"

    @property
    def start_url(self) -> str:
        return "https://jobright.ai/jobs/recommended"

    async def login_check(self, page: Page) -> bool:
        try:
            await page.goto(self.start_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            if "/login" in page.url or "/signin" in page.url:
                return False

            cards = await page.locator(".job-card-flag-classname").count()
            if cards > 0:
                logger.info("Login OK — found %d job cards", cards)
                return True

            return False
        except Exception as e:
            logger.error("Login check failed: %s", e)
            return False

    async def extract_jobs(self, page: Page) -> list[dict]:
        """
        Fast extraction: pull all metadata from the DOM in one JavaScript call.
        The apply URL is resolved per-card by clicking 'Apply with Autofill'
        and capturing the new tab URL.
        """
        await page.wait_for_timeout(3000)

        # Batch-extract all card metadata via JS (instant, no per-card overhead)
        raw_jobs = await page.evaluate("""() => {
            const cards = document.querySelectorAll('.job-card-flag-classname');
            return Array.from(cards).map(card => {
                const titleEl = card.querySelector('h2[class*="job-title"]');
                const companyEl = card.querySelector('[class*="company-name"]');
                const dateEl = card.querySelector('[class*="publish-time"]');

                let location = '';
                const posImg = card.querySelector('img[alt="position"]');
                if (posImg) {
                    const item = posImg.closest('[class*="job-metadata-item"]');
                    const span = item ? item.querySelector('span') : null;
                    location = span ? span.textContent.trim() : '';
                }

                return {
                    card_id: card.id || '',
                    title: titleEl ? titleEl.textContent.trim() : '',
                    company: companyEl ? companyEl.textContent.trim() : '',
                    date_posted_raw: dateEl ? dateEl.textContent.trim() : '',
                    location: location,
                };
            });
        }""")

        logger.info("Found %d job cards on page", len(raw_jobs))

        # Now resolve apply URLs by clicking buttons (the slow part)
        context = page.context
        jobs = []

        for i, raw in enumerate(raw_jobs):
            if not raw.get("card_id") or not raw.get("title"):
                continue

            card_id = raw["card_id"]
            date_posted = self._parse_relative_date(raw.get("date_posted_raw", ""))

            # Resolve the real ATS apply URL
            apply_url = await self._resolve_apply_url(page, context, i)

            if not apply_url:
                apply_url = f"https://jobright.ai/jobs/info/{card_id}"

            jobs.append({
                "job_id": f"jobright_{card_id}",
                "title": raw["title"],
                "company": raw.get("company") or "Unknown",
                "location": raw.get("location", ""),
                "date_posted": date_posted,
                "apply_url": apply_url,
            })

        logger.info("Extracted %d jobs with apply URLs", len(jobs))
        return jobs

    async def _resolve_apply_url(self, page: Page, context: BrowserContext, card_index: int) -> str:
        """Click the apply button on a specific card, capture the new tab URL."""
        cards = page.locator(".job-card-flag-classname")
        if card_index >= await cards.count():
            return ""

        card = cards.nth(card_index)
        apply_btn = card.locator(
            'button[class*="apply-button"]'
        ).first

        if await apply_btn.count() == 0:
            return ""

        captured_url = ""
        url_event = asyncio.Event()

        async def on_new_page(new_page):
            nonlocal captured_url
            try:
                await new_page.wait_for_load_state("commit", timeout=8000)
            except Exception:
                pass
            captured_url = new_page.url
            try:
                await new_page.close()
            except Exception:
                pass
            url_event.set()

        handler = lambda p: asyncio.ensure_future(on_new_page(p))
        context.on("page", handler)

        try:
            await card.scroll_into_view_if_needed()
            await apply_btn.click(timeout=5000)

            # Wait up to 8s for the new tab to open
            try:
                await asyncio.wait_for(url_event.wait(), timeout=8)
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for new tab on card %d", card_index)
        except Exception as e:
            logger.warning("Click failed on card %d: %s", card_index, e)
        finally:
            try:
                context.remove_listener("page", handler)
            except Exception:
                pass

        # Dismiss the "Did you apply?" modal
        await self._dismiss_modal(page)

        return captured_url

    async def _dismiss_modal(self, page: Page):
        try:
            no_btn = page.locator('button:has-text("No, I didn\'t apply")').first
            if await no_btn.count() > 0:
                await no_btn.click(timeout=2000)
                await page.wait_for_timeout(500)
                return
            close_btn = page.locator(".ant-modal-close").first
            if await close_btn.count() > 0:
                await close_btn.click(timeout=2000)
                await page.wait_for_timeout(500)
        except Exception:
            pass

    def _parse_relative_date(self, text: str) -> str:
        text = text.lower().strip()
        now = datetime.now()

        if not text:
            return ""
        if "today" in text or "just now" in text or "just posted" in text:
            return now.strftime("%Y-%m-%d")
        if "yesterday" in text:
            return (now - timedelta(days=1)).strftime("%Y-%m-%d")

        match = re.search(r"(\d+)\s*(minute|hour|day|week|month)", text)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            delta_map = {
                "minute": timedelta(minutes=amount),
                "hour": timedelta(hours=amount),
                "day": timedelta(days=amount),
                "week": timedelta(weeks=amount),
                "month": timedelta(days=amount * 30),
            }
            delta = delta_map.get(unit, timedelta())
            return (now - delta).strftime("%Y-%m-%d")

        try:
            return datetime.fromisoformat(text).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return ""

    async def has_next_page(self, page: Page) -> bool:
        before_count = await page.locator(".job-card-flag-classname").count()
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(3000)
        after_count = await page.locator(".job-card-flag-classname").count()
        return after_count > before_count

    async def go_next_page(self, page: Page) -> None:
        # Scrolling already happened in has_next_page
        pass
