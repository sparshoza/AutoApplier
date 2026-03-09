from abc import ABC, abstractmethod
from playwright.async_api import Page


class BaseScraper(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Site identifier, e.g. 'jobright'."""

    @property
    @abstractmethod
    def start_url(self) -> str:
        """URL to begin scraping from."""

    @abstractmethod
    async def login_check(self, page: Page) -> bool:
        """Return True if the browser is authenticated on this site."""

    @abstractmethod
    async def extract_jobs(self, page: Page) -> list[dict]:
        """
        Extract visible job cards from the current page state.
        Each dict must contain:
            job_id, title, company, location, date_posted, apply_url
        """

    @abstractmethod
    async def has_next_page(self, page: Page) -> bool:
        """Return True if there are more pages of results."""

    @abstractmethod
    async def go_next_page(self, page: Page) -> None:
        """Navigate to the next page of results (click button or scroll)."""
