# Job Pilot

A local desktop application that automates the entire job application pipeline: discovering jobs, filtering them, filling out applications on ATS platforms, handling email verification, and tracking everything in a dashboard.

Your PC remains fully usable while it runs — no stolen focus, no popups, no interruptions.

## How It Works

```
DISCOVERED → QUEUED → APPLYING → APPLIED
                ↘ SKIPPED    ↘ VERIFY_EMAIL → APPLIED
                              ↘ NEEDS_REVIEW → (user re-queues or skips)
```

1. **Scraper** finds jobs on job boards (jobright.ai) on a schedule
2. **Filters** remove unwanted jobs based on keywords, date, and company skip list
3. **ATS Detection** identifies the application platform (Greenhouse, Lever, Ashby, Workday)
4. **Application Engine** fills out and submits forms automatically using your profile data
5. **Email Handler** polls Gmail for OTP verification codes during Greenhouse applications
6. **Dashboard** shows real-time status of all jobs and lets you manage exceptions

## Supported ATS Platforms

| Platform | Status |
|----------|--------|
| Greenhouse | Full support (including OTP email verification) |
| Lever | Full support |
| Ashby | Full support |
| Workday | Best-effort (multi-step wizard, may require manual review) |
| LinkedIn | Skipped (aggressive bot detection) — flagged for manual apply |
| Unknown | Flagged for manual apply |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Edit your profile
# Open profile.json and fill in your personal data, resume path, etc.

# 3. Configure settings
# Open config.yaml and set your keyword filters, schedule, and preferences

# 4. First run — log into job sites
python main.py --setup

# 5. Normal run
python main.py
```

See [INSTALL_AND_TEST.md](INSTALL_AND_TEST.md) for detailed setup instructions.

## Project Structure

```
job-pilot/
├── main.py                     # Entry point
├── config.yaml                 # User config: keywords, schedule, filters
├── profile.json                # Your personal data for form filling
├── db/schema.py                # Database initialization
├── scraper/                    # Job board scrapers
│   ├── base.py                 # Abstract scraper interface
│   ├── runner.py               # Scrape-and-store orchestrator
│   └── sites/jobright.py       # Jobright.ai scraper
├── filters/rules.py            # Keyword, date, company filtering
├── browser/                    # Isolated browser management
│   ├── manager.py              # Playwright persistent context
│   └── interceptors.py         # Dialog/popup/file chooser interception
├── ats/                        # ATS form handlers
│   ├── base.py                 # Abstract handler + utilities
│   ├── detector.py             # URL-based ATS detection
│   └── handlers/               # Per-platform handlers
├── email_handler/gmail.py      # Gmail OTP polling
├── engine/applicant.py         # Application orchestrator
└── dashboard/                  # Flask + vanilla JS dashboard
    ├── app.py
    ├── templates/index.html
    └── static/
```

## Configuration

### config.yaml

- **keywords.include/exclude** — filter job titles
- **date_cutoff_days** — only jobs posted within N days
- **skip_companies** — never apply to these
- **scrape_schedule / apply_schedule** — cron-style timing
- **rate_limits** — delay between applications, hourly cap
- **otp_timeout_seconds** — how long to wait for verification emails

### profile.json

- Personal info, resume path, work authorization
- Education and employment history
- Standard answers for screening questions
- Demographics for EEO questions (default: "Prefer not to say")

## Dashboard

Dark-themed, information-dense UI running in a native desktop window (PyWebView).

- Real-time job status tracking with color-coded badges
- Filter by status: All, Queued, Applying, Applied, Needs Review, Skipped
- One-click actions: Scrape Now, Apply Now, Re-authenticate Browser
- Screenshot viewer for failed applications
- Auto-refresh every 30 seconds

## Architecture

- **PyWebView** on main thread (native window)
- **Flask** in daemon thread (dashboard API)
- **Persistent asyncio loop** in background thread (browser, scraper, engine)
- **APScheduler** for cron-style job scheduling

The persistent event loop is critical: Playwright's browser context is bound to a single loop and reused across all scheduled runs.
