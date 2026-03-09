import logging
from playwright.async_api import Page

from db.schema import get_db
from filters.rules import apply_all_filters
from ats.detector import detect_ats
from scraper.base import BaseScraper
from scraper.sites.jobright import JobrightScraper

logger = logging.getLogger("job_pilot.scraper.runner")

SCRAPERS: list[BaseScraper] = [
    JobrightScraper(),
]


async def scrape_and_store(page: Page, config: dict) -> int:
    """
    Run all registered scrapers, filter results, detect ATS types,
    and insert new jobs into the database. Returns count of newly added jobs.
    """
    total_added = 0

    for scraper in SCRAPERS:
        try:
            added = await _run_single_scraper(scraper, page, config)
            total_added += added
        except Exception as e:
            logger.error("Scraper '%s' failed: %s", scraper.name, e, exc_info=True)

    logger.info("Scrape complete. %d new jobs added.", total_added)
    return total_added


async def _run_single_scraper(scraper: BaseScraper, page: Page, config: dict) -> int:
    logger.info("Running scraper: %s", scraper.name)

    if not await scraper.login_check(page):
        logger.warning("Scraper '%s': not logged in. Aborting.", scraper.name)
        return 0

    all_jobs: list[dict] = []

    page_num = 1
    while True:
        logger.info("Scraping page %d", page_num)
        jobs = await scraper.extract_jobs(page)
        all_jobs.extend(jobs)

        if await scraper.has_next_page(page):
            await scraper.go_next_page(page)
            page_num += 1
        else:
            break

        if page_num > 50:
            logger.warning("Safety limit: stopped after 50 pages")
            break

    logger.info("Raw jobs extracted: %d", len(all_jobs))

    filtered = [j for j in all_jobs if apply_all_filters(j, config)]
    logger.info("Jobs after filtering: %d", len(filtered))

    added = 0
    db = await get_db()
    try:
        for job in filtered:
            ats_type = detect_ats(job["apply_url"])
            status = "queued"
            warning_reason = None

            if ats_type in ("unknown", "linkedin"):
                status = "needs_review"
                warning_reason = "No automated handler for this ATS — apply manually."

            try:
                await db.execute(
                    """INSERT INTO jobs (job_id, source, title, company, location,
                       date_posted, apply_url, ats_type, status, warning_reason)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job["job_id"],
                        scraper.name,
                        job["title"],
                        job["company"],
                        job.get("location", ""),
                        job.get("date_posted", ""),
                        job["apply_url"],
                        ats_type,
                        status,
                        warning_reason,
                    ),
                )
                added += 1
            except Exception:
                pass  # duplicate job_id — silently skip

        await db.commit()
    finally:
        await db.close()

    logger.info("Scraper '%s': %d new jobs stored.", scraper.name, added)
    return added
