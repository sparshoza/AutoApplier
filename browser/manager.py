import os
import logging
from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger("job_pilot.browser")

BROWSER_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "browser_data")

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""


class BrowserManager:
    def __init__(self):
        self._playwright = None
        self._context: BrowserContext | None = None

    async def launch(self):
        os.makedirs(BROWSER_DATA_DIR, exist_ok=True)
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=BROWSER_DATA_DIR,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 900},
        )
        await self._context.add_init_script(STEALTH_SCRIPT)

        # Close the default blank tab — tasks open their own pages as needed
        for page in self._context.pages:
            try:
                await page.close()
            except Exception:
                pass

        logger.info("Browser launched with persistent context at %s", BROWSER_DATA_DIR)

    async def new_page(self) -> Page:
        if not self._context:
            raise RuntimeError("Browser not launched. Call launch() first.")
        page = await self._context.new_page()
        return page

    async def close_page(self, page: Page):
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            logger.warning("Error closing page", exc_info=True)

    async def setup_mode(self, urls: list[str] | None = None):
        """Open browser with login pages for the user to authenticate manually."""
        if urls is None:
            urls = ["https://jobright.ai/login"]
        await self.launch()

        # Persistent context always opens with one default page — reuse it
        pages = self._context.pages
        first_page = pages[0] if pages else await self._context.new_page()

        # Navigate the first tab to the first URL
        try:
            await first_page.goto(urls[0], wait_until="domcontentloaded", timeout=30000)
        except Exception:
            logger.warning("Could not navigate to %s", urls[0])

        # Open additional URLs in new tabs
        for url in urls[1:]:
            try:
                page = await self._context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                logger.warning("Could not navigate to %s", url)

        logger.info("Setup mode: log into your sites, then close ALL browser tabs when done.")

        # Wait until the browser context disconnects (user closed the window)
        try:
            disconnected = self._context.wait_for_event("close", timeout=600_000)
            await disconnected
        except Exception:
            pass

        await self.shutdown()

    async def shutdown(self):
        if self._context:
            try:
                await self._context.close()
            except Exception:
                logger.warning("Error closing browser context", exc_info=True)
            self._context = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        logger.info("Browser shut down.")

    @property
    def context(self) -> BrowserContext | None:
        return self._context
