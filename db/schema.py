import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "jobs.db")

CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT    UNIQUE NOT NULL,
    source      TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    company     TEXT    NOT NULL,
    location    TEXT,
    date_posted TEXT,
    apply_url   TEXT    NOT NULL,
    ats_type    TEXT    DEFAULT 'unknown',
    status      TEXT    DEFAULT 'queued',
    warning_reason  TEXT,
    screenshot_path TEXT,
    scraped_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    applied_at  TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_UPDATED_AT_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS update_jobs_updated_at
AFTER UPDATE ON jobs
BEGIN
    UPDATE jobs SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""


async def init_db():
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute(CREATE_JOBS_TABLE)
    await db.execute(CREATE_UPDATED_AT_TRIGGER)
    await db.commit()
    await db.close()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db
