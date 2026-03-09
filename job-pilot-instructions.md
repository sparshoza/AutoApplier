# Job Pilot — Complete Specification

## What This Is

A local desktop application that automates the entire job application pipeline: discovering jobs, filtering them, filling out applications on ATS platforms, handling email verification, and tracking everything in a dashboard. The user's PC remains fully usable while it runs — no stolen focus, no popups, no interruptions.

---

## What This Is NOT

- Not a cloud service. Everything runs locally on the user's machine.
- Not a Chrome extension. It uses its own isolated browser instance.
- Not a credential store. It relies on persistent browser cookies for site logins and OAuth for Gmail.

---

## Core Lifecycle of a Job

```
DISCOVERED → QUEUED → APPLYING → APPLIED
                ↘ SKIPPED    ↘ VERIFY_EMAIL → APPLIED
                              ↘ NEEDS_REVIEW → (user re-queues or skips)
```

1. **Discovered**: Scraper finds the job on a job board (e.g., jobright.ai).
2. **Queued**: Job passes all filters (keywords, date, skip list) and is saved to the database.
3. **Applying**: The application engine has opened the job's ATS page and is filling out the form.
4. **Verify Email**: An OTP or verification link was required. The system is polling Gmail for it.
5. **Applied**: Application was submitted successfully. Confirmed by detecting a "thank you" or "application received" page.
6. **Needs Review**: Something went wrong — unrecognized page, timeout, CAPTCHA, unusual question. A screenshot was saved and the job is flagged in the dashboard for the user to handle manually.
7. **Skipped**: User or filter decided to skip this job.

A job in `needs_review` can be **re-queued** by the user from the dashboard, which sends it back through the application engine.

---

## Hard Constraints — Never Violate These

1. **Never run the automation browser in headless mode.** Some ATS sites behave differently in headless. The browser window must exist but can be minimized.

2. **Never steal OS focus.** The automation browser is an isolated Playwright Chromium instance — not the user's default browser. All JavaScript dialogs (alert, confirm, prompt) are silently dismissed. All unexpected new tabs/popups are closed and logged. File upload dialogs are never triggered — resume files are injected directly into the file input element.

3. **Never crash on an unexpected page.** Every step of every ATS handler is wrapped in error handling. If anything unrecognized happens: take a screenshot, record the reason, mark the job as `needs_review`, close the tab, and move on to the next job.

4. **Never commit sensitive files to git.** The database, user profile, Gmail tokens, browser data directory, and screenshots are all gitignored.

5. **Never apply to the same job twice.** The database enforces uniqueness on the job's external ID. The engine only processes jobs with status `queued`.

---

## User Experience — What Running This Feels Like

### First Run (Setup)

1. User installs dependencies and runs `python main.py --setup`.
2. An isolated Chromium browser window opens. This is the automation browser.
3. User manually logs into jobright.ai (and later LinkedIn, etc.) in that browser. These sessions are saved in a local `browser_data/` folder so they persist across runs.
4. User closes the setup browser when done.
5. User fills out `profile.json` with their personal info, resume path, and standard answers.
6. User fills out `config.yaml` with their keyword filters, schedule preferences, and companies to skip.
7. User runs `python main.py` to start the application.

### Normal Run

1. User runs `python main.py`. A desktop window opens showing the Job Pilot dashboard.
2. In the background, the scraper runs on the configured schedule (e.g., 9am, 1pm, 5pm).
3. After each scrape, the application engine processes any newly queued jobs.
4. The user continues using their PC normally. The automation browser is minimized and never steals focus.
5. The dashboard updates in real time. The user can see jobs flowing through statuses.
6. If a job lands in `needs_review`, the user opens the dashboard, looks at the screenshot and reason, then either re-queues it or skips it.
7. The user can also manually trigger a scrape or apply run from the dashboard at any time.

### The User's PC Is Never Disrupted

- The automation browser is a separate process from the user's daily Chrome.
- All OS-level dialog interception happens before dialogs render.
- Resume uploads use Playwright's file injection — no OS file picker ever opens.
- The dashboard runs inside a native desktop window (PyWebView) that behaves like a normal app — it doesn't hijack the browser.

---

## Tech Stack

| Concern | Tool | Why |
|---|---|---|
| Language | Python 3.11+ | Playwright and async ecosystem are mature |
| Async runtime | asyncio | Browser automation and Gmail polling are I/O-bound |
| Browser automation | Playwright (async API) | Best Chromium automation library, supports persistent contexts |
| Scheduling | APScheduler | Cron-style scheduling without external services |
| Database | aiosqlite (async SQLite) | Zero-config, file-based, perfect for local tool |
| Gmail integration | Google API Python Client + OAuth | Official API, reliable, no App Password needed |
| Dashboard backend | Flask | Simple, well-known, serves the dashboard UI |
| Desktop window | PyWebView | Wraps the Flask dashboard in a native OS window |
| Screenshots | Playwright built-in | Captures page state on failure for debugging |
| Config | PyYAML | Human-readable config files |
| Profile data | JSON file | Flat structure, easy to edit by hand |

### SQLite Configuration

Enable WAL (Write-Ahead Logging) mode when creating the database. This allows the dashboard to read data while the engine is writing, preventing "database is locked" errors during concurrent access.

---

## Project Structure

```
job-pilot/
├── main.py                        # Entry point: persistent async loop, scheduler, Flask, PyWebView
├── config.yaml                    # User config: keywords, schedule, filters
├── profile.json                   # User's personal data for form filling
│
├── db/
│   ├── schema.py                  # DB initialization, table creation, WAL mode
│   └── jobs.db                    # Auto-generated at first run, gitignored
│
├── scraper/
│   ├── base.py                    # Abstract base class all scrapers implement
│   └── sites/
│       └── jobright.py            # Jobright.ai scraper (first implementation)
│
├── filters/
│   └── rules.py                   # Keyword, date, skip-list filtering
│
├── browser/
│   ├── manager.py                 # Manages the isolated Playwright browser lifecycle
│   └── interceptors.py            # Dialog, popup, and file chooser interception
│
├── ats/
│   ├── base.py                    # Abstract base class all ATS handlers implement
│   ├── detector.py                # URL pattern matching to identify which ATS a job uses
│   └── handlers/
│       ├── greenhouse.py          # Greenhouse form handler (includes OTP flow)
│       ├── lever.py               # Lever form handler
│       ├── ashby.py               # Ashby form handler
│       └── workday.py             # Workday form handler
│
├── email_handler/
│   ├── gmail.py                   # Gmail API: OAuth setup, OTP polling, link extraction
│   ├── credentials.json           # Google Cloud OAuth credentials (user provides, gitignored)
│   └── token.json                 # Auto-generated after first OAuth consent, gitignored
│
├── engine/
│   └── applicant.py               # Orchestrates: pick job → detect ATS → run handler → update status
│
├── dashboard/
│   ├── app.py                     # Flask routes (API + page serving)
│   ├── static/
│   │   ├── style.css              # Dashboard styles
│   │   └── app.js                 # Dashboard client-side logic
│   └── templates/
│       └── index.html             # Dashboard HTML
│
├── screenshots/                   # Auto-saved PNGs on needs_review, gitignored
├── browser_data/                  # Persistent browser cookies/session, gitignored
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Configuration Files

### config.yaml

Contains all user-configurable settings. No code changes needed for normal use.

**Sections:**

- **keywords.include**: List of strings. A job title must contain at least one of these (case-insensitive) to pass filtering.
- **keywords.exclude**: List of strings. A job title containing any of these is rejected.
- **date_cutoff_days**: Integer. Only jobs posted within this many days are kept.
- **skip_companies**: List of company names to never apply to.
- **scrape_schedule**: Cron-style schedule for when to run scrapers. Uses APScheduler's hour/minute format (e.g., hour: "9,13,17", minute: "0" means 9am, 1pm, 5pm).
- **apply_schedule**: Cron-style schedule for when to run the application engine. Should be offset from scrape schedule (e.g., 15 minutes after) to give scraping time to finish.
- **rate_limits.min_delay_seconds**: Minimum seconds to wait between individual applications. Prevents rapid-fire submissions that trigger bot detection.
- **rate_limits.max_per_hour**: Maximum number of applications to submit in a single hour across all ATS platforms.
- **otp_timeout_seconds**: How long to poll Gmail for a verification email before giving up and marking the job as `needs_review`.
- **dashboard_port**: Port for the Flask server (default 5000).

### profile.json

Single source of truth for all form filling. The user fills this out once.

**Sections:**

- **personal**: First name, last name, email, phone, LinkedIn URL, GitHub URL, portfolio URL, and a location object (city, state, country, zip).
- **work_authorization**: Whether authorized to work in US, whether sponsorship is required, visa status string.
- **resume_path**: Absolute path to the user's resume PDF on disk.
- **experience_years**: Integer, total years of experience.
- **education**: Degree, major, university, graduation year, GPA.
- **employment_history**: Array of objects, each with company, title, start date, end date, and description.
- **standard_answers**: Key-value pairs for common screening questions — salary expectation, notice period, willingness to relocate, remote preference, "why are you interested" default answer.
- **demographics**: Gender, ethnicity, veteran status, disability status. All default to "Prefer not to say" variants. These are for EEO (Equal Employment Opportunity) questions that most ATS platforms ask.

---

## Database Schema

One table called `jobs` with these columns:

| Column | Type | Description |
|---|---|---|
| id | Integer, auto-increment | Internal primary key |
| job_id | Text, unique | External ID from the job board (prevents duplicate applications) |
| source | Text | Which scraper found this job (e.g., "jobright") |
| title | Text | Job title |
| company | Text | Company name |
| location | Text | Job location |
| date_posted | Text | When the job was posted (ISO format) |
| apply_url | Text | Direct URL to the application page |
| ats_type | Text | Detected ATS platform (greenhouse, lever, ashby, workday, unknown) |
| status | Text, default "queued" | Current lifecycle status |
| warning_reason | Text, nullable | Human-readable explanation if status is needs_review |
| screenshot_path | Text, nullable | Path to failure screenshot if status is needs_review |
| scraped_at | Timestamp | When the scraper first found this job |
| applied_at | Timestamp, nullable | When the application was successfully submitted |
| updated_at | Timestamp | Last time this row was modified |

**Important:** Enable WAL mode (`PRAGMA journal_mode=WAL`) immediately after creating the database. This is critical for concurrent access from the Flask dashboard and the async engine.

---

## Browser Manager

### Isolation Model

The application uses its own Playwright Chromium instance, completely separate from the user's personal Chrome. Browser state (cookies, local storage, sessions) persists in a `browser_data/` directory so the user doesn't have to re-login every run.

### Lifecycle

- On startup, the browser manager launches a persistent Chromium context pointing at `browser_data/`.
- The context stays alive for the entire duration of the application.
- Individual pages (tabs) are opened and closed per job application.
- On shutdown, the browser context is closed gracefully.

### Anti-Detection

- The `navigator.webdriver` property is overridden to `undefined` via an init script injected on every new page.
- The `--disable-blink-features=AutomationControlled` flag is passed at launch.
- Human-like delays (1-3 seconds) are added between form interactions.
- The browser is never headless.

### Setup Mode

When run with `--setup`, the application launches the browser and opens a blank tab. The user navigates to whatever sites they need (jobright.ai, LinkedIn, etc.) and logs in manually. Once done, they close the browser, and all sessions are saved in `browser_data/`. The dashboard should also have a "Re-authenticate" button that reopens this setup browser at any time for when sessions expire.

---

## Interceptors

Registered on every new page **before any navigation occurs**. Three interceptors:

### Dialog Interceptor
Catches all JavaScript dialogs — `alert()`, `confirm()`, `prompt()`, and `beforeunload`. Silently dismisses all of them. The user never sees an OS-level dialog box.

### Popup/Tab Interceptor
Catches any new tab or popup window that the page tries to open. Immediately closes it and logs a warning. If this happens during an active application, the job is marked `needs_review` with the reason "Unexpected popup blocked."

### File Chooser Interceptor
Catches the OS file picker dialog that would normally appear when a page triggers a file input click. This is a safety net — the ATS handlers should always use Playwright's direct file injection method for resume uploads, which bypasses the OS dialog entirely. If this interceptor fires, it means something unexpected happened.

---

## Scraper System

### Base Scraper (Abstract)

All site-specific scrapers implement a common interface:

- **name**: Returns the site name (e.g., "jobright").
- **start_url**: Returns the URL to begin scraping from.
- **login_check**: Verifies the browser is logged in to the site. Returns true/false. If false, the job is marked as needing re-authentication and the scraper aborts gracefully.
- **extract_jobs**: Given a loaded page, extracts all visible job cards and returns a list of standardized job dictionaries (job_id, title, company, location, date_posted, apply_url).
- **has_next_page / go_next_page**: Handles pagination — whether that's clicking a "Next" button or scrolling to trigger infinite loading.

### Adding a New Scraper

To support a new job site, create a new file in `scraper/sites/` that implements the base scraper interface. Register it in the scraper runner. No changes needed to the database, filters, engine, or dashboard — they all work with the standardized job dictionary.

### Jobright.ai Scraper (First Implementation)

This is the first scraper to build. Implementation approach:

1. Navigate to the jobright.ai jobs page.
2. Verify login by checking for a user-specific element (profile avatar, saved filters, etc.). If not logged in, abort and notify the user via the dashboard.
3. The user's saved search filters on jobright.ai will already be active from their last session.
4. Identify the DOM structure of job cards using browser DevTools. **The CSS selectors for job cards, titles, company names, dates, and URLs must be reverse-engineered from the live site.** This is the scraper's first real task — open the site, inspect the DOM, and determine the correct selectors.
5. Extract each card's data into the standard job dictionary format.
6. Handle pagination: scroll down or click "next" until no new jobs load.
7. Parse relative date strings ("2 days ago", "Posted today") into absolute ISO dates.
8. Return the full list of job dictionaries.

### Scrape-and-Store Function

A convenience function that:
1. Runs the scraper to get raw job listings.
2. Passes each job through the filter rules.
3. Runs ATS detection on each surviving job's apply URL.
4. Inserts new jobs into the database (skipping duplicates via the unique job_id constraint).
5. Returns a count of newly added jobs.

---

## Filter Rules

Four filters applied in sequence. A job must pass all four to be queued.

1. **Include Keywords**: The job title must contain at least one keyword from the include list (case-insensitive substring match).
2. **Exclude Keywords**: The job title must not contain any keyword from the exclude list.
3. **Date Cutoff**: The job must have been posted within the configured number of days. If the date can't be parsed, the job passes this filter (don't reject on ambiguity).
4. **Skip List**: The job's company name must not appear in the skip list (case-insensitive exact match).

---

## ATS Detection

A simple URL-pattern-based detector that examines the apply URL and returns the ATS type:

| URL Pattern | ATS Type |
|---|---|
| Contains "greenhouse.io" or "boards.greenhouse.io" | greenhouse |
| Contains "lever.co" or "jobs.lever.co" | lever |
| Contains "ashbyhq.com" | ashby |
| Contains "myworkdayjobs.com" or "workday.com" | workday |
| Contains "linkedin.com/jobs" | linkedin |
| Anything else | unknown |

Jobs with ATS type "unknown" or "linkedin" are automatically set to `needs_review` with the reason "No automated handler for this ATS — apply manually." The user can open the URL from the dashboard and apply by hand. LinkedIn is excluded from automation because it has aggressive bot detection that risks account suspension.

---

## ATS Handler System

### Base Handler (Abstract)

All ATS-specific handlers implement a common interface:

- **apply(job_url)**: Navigates to the URL, fills out the application form using profile data, handles OTP if needed, submits, and returns a result object indicating success or failure.

The base class also provides shared utility methods:
- **safe_fill**: Fills a form field only if it exists on the page. Never throws an error if the field is missing.
- **safe_click**: Clicks an element only if it exists. Never throws.
- **safe_select**: Selects a dropdown option only if the dropdown exists. Never throws.
- **upload_resume**: Injects the resume file directly into a file input element using Playwright's file injection — never triggers an OS file dialog.
- **take_failure_screenshot**: Captures the current page state and saves it to `screenshots/`.

### Handler Result

Every handler returns a result dictionary with:
- **success**: Boolean.
- **status**: The status to set on the job ("applied" or "needs_review").
- **warning_reason**: Human-readable string explaining what went wrong (null if successful).

### Greenhouse Handler (Priority — Build First)

Greenhouse is the most common ATS and the one that requires OTP email verification. Flow:

1. Navigate to the job application page.
2. Fill personal info fields: first name, last name, email, phone, location.
3. Upload resume via file injection.
4. Submit the initial form.
5. **OTP Gate Detection**: After submission, check if the page contains text like "verify your email" or "check your email." If detected:
   a. Call the Gmail poller to wait for a verification email from Greenhouse's sender address.
   b. If an OTP code is received, type it into the verification field and submit.
   c. If a verification link is received, navigate to it.
   d. If neither arrives within the timeout, mark as `needs_review` with reason "OTP email not received."
6. Fill any additional fields (work authorization, demographics, custom questions) using profile data and standard answers.
7. Final submit.
8. Confirm success by detecting "thank you" or "application submitted" text on the resulting page.
9. If confirmation text is not found, mark as `needs_review` with reason "Could not confirm submission."

### Lever Handler

Simpler than Greenhouse. Usually a single-page form.

1. Navigate to the application page.
2. Fill personal info fields.
3. Upload resume.
4. Fill any additional custom fields.
5. Submit.
6. Confirm success.

### Ashby Handler

Similar to Lever but with Ashby-specific field names and selectors.

### Workday Handler

Workday is multi-step and the most complex. Each step has its own page load. The handler must:
1. Navigate through the "Sign In" or "Apply" entry point.
2. Handle account creation or login if required (this may need to be a `needs_review` trigger initially).
3. Step through the multi-page wizard, filling fields on each page.
4. Submit and confirm.

Workday should be the last handler built due to its complexity.

### Adding a New ATS Handler

To support a new ATS platform:
1. Create a new file in `ats/handlers/` that implements the base handler interface.
2. Add the URL pattern to the ATS detector.
3. Register the handler class in the application engine's handler map.

No changes to the database, dashboard, scraper, or filters are needed.

---

## Email Handler (Gmail OTP)

### Purpose

Polls the user's Gmail inbox for OTP codes and verification links sent by ATS platforms during the application process.

### Authentication

Uses Google's official OAuth2 flow:
1. The user creates a Google Cloud project, enables the Gmail API, and downloads OAuth credentials as `credentials.json` into the `email_handler/` directory.
2. On first run, a browser window opens for the user to grant read-only Gmail access.
3. An access token is saved as `token.json` and reused automatically. Refreshed when expired.
4. Only the `gmail.readonly` scope is requested — the application never sends, deletes, or modifies emails.

### Polling Logic

When an ATS handler detects an OTP gate:
1. Record the current time as the search start.
2. Query Gmail for recent unread emails from the known ATS sender address (using `newer_than:2m` to limit scope).
3. If a matching email is found, extract the body and look for:
   - A 4-8 digit numeric OTP code.
   - A URL containing "verify" or "confirm."
4. Return whichever is found (OTP string or URL string).
5. If nothing is found, wait 3 seconds and poll again.
6. If the configured timeout is exceeded, return null (handler will mark job as `needs_review`).

### Known ATS Sender Addresses

Configured in `config.yaml` under `otp_email_patterns`. Common ones:
- Greenhouse: `no-reply@greenhouse.io`
- Lever: `no-reply@lever.co`
- Ashby: `verify@ashbyhq.com`
- Workday: `noreply@myworkday.com`

---

## Application Engine

### Purpose

The core orchestrator that picks queued jobs and runs them through the appropriate ATS handler.

### Flow

1. Query the database for all jobs with status `queued`, ordered by scrape time (oldest first).
2. For each job:
   a. Check rate limits. If the hourly cap has been reached, stop processing.
   b. Update the job's status to `applying`.
   c. Open a new page (tab) in the automation browser.
   d. Register all interceptors on the page before any navigation.
   e. Look up the appropriate ATS handler based on the job's `ats_type` field.
   f. If no handler exists for this ATS type, take a screenshot, mark as `needs_review`, close the tab, continue.
   g. Run the handler's `apply()` method.
   h. Based on the result: update the job to `applied` (with timestamp) or `needs_review` (with reason and screenshot).
   i. Close the tab.
   j. Wait the configured delay before the next application.

### Rate Limiting

Two rate limit controls:
- **min_delay_seconds**: Enforced between every application. Prevents rapid-fire submissions.
- **max_per_hour**: Tracked with a simple counter that resets hourly. When reached, the engine stops processing and waits for the next scheduled run.

### Error Handling Philosophy

The engine never crashes. If a single job application fails for any reason:
1. Take a screenshot of whatever page state exists.
2. Record the exception or reason as the `warning_reason`.
3. Set the job to `needs_review`.
4. Close the tab.
5. Continue to the next job.

---

## Threading and Async Architecture

This is critical to get right. The application has four concurrent concerns:

1. **PyWebView** — must run on the main thread (OS requirement for native windows).
2. **Flask** — serves the dashboard; runs in a background daemon thread.
3. **Async event loop** — runs the scraper, engine, and Gmail poller; lives in its own dedicated background thread.
4. **APScheduler** — triggers scrape and apply jobs; runs in its own background thread.

### The Event Loop Problem

APScheduler runs each job in a thread. The scraper and engine are async (they use Playwright's async API). The Playwright browser context is bound to a specific event loop. If you create a new event loop for each scheduled job (e.g., using `asyncio.run()`), the browser context from a previous run becomes invalid because it's attached to a dead loop.

### The Solution

Create **one persistent event loop** that runs forever in a dedicated background thread. All async work (scraping, applying, Gmail polling) is submitted to this single loop using `asyncio.run_coroutine_threadsafe()`. The browser context is created once on this loop and reused across all scheduled runs.

**Startup sequence:**
1. Initialize the database.
2. Start the persistent async event loop thread.
3. Start Flask in a daemon thread.
4. Configure APScheduler: scrape and apply jobs submit coroutines to the persistent loop.
5. Start APScheduler.
6. Create the PyWebView window pointing at `localhost:{dashboard_port}`.
7. Call `webview.start()` on the main thread (blocks until window is closed).
8. On window close: shut down scheduler, close browser, stop event loop.

---

## Dashboard

### Architecture

The dashboard is a Flask web app rendered inside a PyWebView native desktop window. It communicates with the backend entirely through JSON API endpoints. The frontend is vanilla HTML, CSS, and JavaScript — no frameworks or CDN dependencies.

### API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serves the dashboard HTML page |
| GET | `/api/jobs?status=X` | Returns jobs, optionally filtered by status. Returns all if status is "all" or omitted. |
| GET | `/api/stats` | Returns count of jobs per status category |
| POST | `/api/jobs/{id}/status` | Updates a job's status. Body: `{"status": "applied|skipped|queued"}`. Setting to "queued" is the re-queue action. |
| GET | `/api/jobs/{id}/screenshot` | Returns the screenshot PNG for a needs_review job |
| POST | `/api/scrape` | Triggers an immediate scrape run (submits to the async loop). Returns immediately with acknowledgment. |
| POST | `/api/apply` | Triggers an immediate apply run. Returns immediately with acknowledgment. |
| POST | `/api/setup` | Launches the setup browser for re-authentication. |

### Visual Design

- **Dark theme.** Background #0f1117, cards slightly lighter. Easy on the eyes for a tool that's open all day.
- **Minimal and information-dense.** No decorative elements. Every pixel communicates state.
- **Color-coded status badges:**
  - Yellow: queued
  - Blue: applying
  - Green: applied
  - Red: needs_review
  - Gray: skipped

### Layout

**Top Bar:**
- App title "Job Pilot" on the left.
- Live stats in the center: "X queued · Y applied · Z need review"
- Three action buttons on the right: "Scrape Now", "Apply Now", "Re-authenticate Browser"
- Auto-refresh toggle (when on, job list refreshes every 30 seconds)

**Sidebar:**
- Filter buttons: All | Queued | Applying | Applied | Needs Review | Skipped
- Each shows a count badge
- Clicking a filter fetches jobs for that status and re-renders the main area without a page reload

**Main Area — Job Cards:**

Each job is a card showing:
- **Title** (bold) + **Company**
- **Location** · **Date posted** · **Source** (which scraper found it)
- **ATS type badge** (e.g., "Greenhouse", "Lever")
- **Status badge** (color-coded)

Additional elements depending on status:
- **Queued**: "Skip" button
- **Applying**: Spinner or "In progress" indicator
- **Applied**: Green checkmark, applied timestamp
- **Needs Review**: Warning reason in red text, "View Screenshot" button, "Open Job URL" button, "Re-queue" button, "Skip" button
- **Skipped**: "Re-queue" button (to undo a skip)

**Screenshot Modal:**
When "View Screenshot" is clicked, a full-screen overlay shows the screenshot image with a close button. The screenshot helps the user understand what went wrong without having to reproduce the state.

### Client-Side Behavior

- On page load: fetch `/api/jobs` and `/api/stats`, render everything.
- Filter tabs: call `/api/jobs?status=X` and re-render cards. No page reload.
- Status buttons: call `/api/jobs/{id}/status` via POST, update the card in place. No page reload.
- "Scrape Now" / "Apply Now": call the respective endpoint, show a brief toast notification ("Scrape started"), refresh stats after a few seconds.
- Auto-refresh: `setInterval` that re-fetches jobs and stats every 30 seconds when the toggle is on.
- No page reloads for any user action.

---

## Rate Limiting and Politeness

The application should not behave like a bot flooding ATS platforms.

- **Between applications**: Wait at least `rate_limits.min_delay_seconds` (recommend default: 30 seconds). This includes a small random jitter (±5 seconds) to avoid mechanical timing patterns.
- **Per hour cap**: Never exceed `rate_limits.max_per_hour` (recommend default: 15). When the cap is hit, the engine stops and resumes at the next scheduled run.
- **Per-ATS cooldown**: If multiple jobs use the same ATS, add extra delay (e.g., 60 seconds between two Greenhouse applications) to avoid triggering per-IP rate limits on the ATS side.
- **Page load waits**: After every navigation, wait for the page to reach network idle state before interacting with elements. Add a small human-like delay (1-3 seconds) before filling each field.

---

## Error Handling Strategy

### Principle: Degrade Gracefully, Never Crash

Every component follows the same pattern:
1. Attempt the action.
2. If it fails, record what happened (screenshot if applicable, text reason always).
3. Mark the job as `needs_review` so the user can investigate.
4. Move on to the next job.

### Specific Failure Modes

| Failure | Response |
|---|---|
| Scraper can't find job cards (DOM changed) | Log warning, return empty list, notify via dashboard |
| Scraper not logged in | Abort scrape, set dashboard warning "Re-authentication needed" |
| ATS handler encounters unknown form field | Skip the field, continue filling others, submit anyway |
| ATS handler can't find the submit button | Screenshot, mark needs_review |
| OTP email never arrives | Mark needs_review with "OTP timeout" |
| CAPTCHA detected | Screenshot, mark needs_review with "CAPTCHA detected" |
| Page loads an error/404 | Screenshot, mark needs_review |
| Network timeout | Retry once, then mark needs_review |
| Any unhandled exception | Catch at engine level, screenshot, mark needs_review, continue |

---

## Scalability Points

The architecture is designed so that adding new job boards and ATS platforms requires **no changes** to the core system.

### To add a new job board scraper:
1. Create a new file in `scraper/sites/`.
2. Implement the base scraper interface (start URL, login check, extract jobs, pagination).
3. Register it in the scraper runner.
4. The filters, database, engine, and dashboard handle it automatically because they work with standardized job dictionaries.

### To add a new ATS handler:
1. Create a new file in `ats/handlers/`.
2. Implement the base handler interface (apply method that fills forms and returns a result).
3. Add the URL pattern to `ats/detector.py`.
4. Register the handler in the engine's handler map.
5. The dashboard, database, and scraper are unaffected.

### To modify form-filling behavior:
1. Update `profile.json` with new fields or answers.
2. The ATS handler reads from this file — no code changes for data changes.

---

## Build Order

Execute strictly in this sequence. Each phase is independently testable before moving to the next.

### Phase 1 — Foundation
1. Create the full project directory structure with empty files.
2. Write `requirements.txt` with all dependencies.
3. Implement `db/schema.py` — database creation with WAL mode. Run it and verify `jobs.db` is created with the correct table.
4. Create `profile.json` with placeholder/example values.
5. Create `config.yaml` with sensible defaults.
6. Implement `filters/rules.py`. Test all four filter rules with hardcoded mock job dictionaries to verify they work correctly.

### Phase 2 — Browser Safety Layer
7. Implement `browser/manager.py` — launch isolated Chromium with persistent context, anti-detection flags, and the setup mode.
8. Implement `browser/interceptors.py` — dialog, popup, and file chooser interception.
9. Test: run the browser manager, navigate to a page with JavaScript `alert()`, confirm it is dismissed silently without any OS popup. Test popup interception. Test that `--setup` mode lets the user interact with the browser manually.

### Phase 3 — Scraper
10. Implement `scraper/base.py` — define the abstract base class.
11. Implement `scraper/sites/jobright.py`:
    - First: open the browser, navigate to jobright.ai, and inspect the DOM to identify correct CSS selectors for job cards.
    - Then: implement the full extraction logic using those selectors.
12. Implement the `scrape_and_store` convenience function that runs the scraper, filters results, detects ATS types, and inserts into the database.
13. Test: run a full scrape, verify jobs appear in the database with all fields populated.

### Phase 4 — Dashboard
14. Implement `dashboard/app.py` with all API endpoints.
15. Seed the database with 10-15 fake jobs spread across all status types for testing.
16. Build `dashboard/templates/index.html`, `static/style.css`, and `static/app.js` per the dashboard spec.
17. Test: all filter tabs work, status updates work without reload, screenshot modal works, stats update correctly, "Scrape Now" and "Apply Now" buttons call their endpoints.

### Phase 5 — Email Handler
18. Implement `email_handler/gmail.py` — OAuth flow, token persistence, OTP polling.
19. Test: send yourself a test email with a 6-digit code, verify the poller finds and returns it.

### Phase 6 — ATS Handlers
20. Implement `ats/base.py` and `ats/detector.py`.
21. Implement `ats/handlers/greenhouse.py` — the priority handler since it's the most common and requires OTP.
22. Test with a real Greenhouse job posting. Verify the full flow: navigate, fill, OTP, submit.
23. Implement `ats/handlers/lever.py`.
24. Implement `ats/handlers/ashby.py`.
25. Implement `ats/handlers/workday.py` (most complex, do last).

### Phase 7 — Engine and Wiring
26. Implement `engine/applicant.py` — the orchestrator with rate limiting and error handling.
27. Implement `main.py` — persistent async loop, threading, scheduler, Flask, PyWebView.
28. End-to-end test: full flow from scrape → filter → queue → apply → OTP → dashboard update.

### Phase 8 — Polish
29. Implement `.gitignore`.
30. Write `README.md` with complete setup instructions including Google Cloud project setup for Gmail API.
31. Test the complete application startup and shutdown sequence.
32. Verify the user's PC remains fully usable (no focus steal, no popups) while the engine is processing applications.

---

## README Requirements

The README must include step-by-step instructions for:

1. Installing Python 3.11+.
2. Installing dependencies from `requirements.txt` and running `playwright install chromium`.
3. Gmail API setup: creating a Google Cloud project, enabling the Gmail API, creating OAuth2 credentials, and downloading them as `email_handler/credentials.json`.
4. Filling out `profile.json` with personal data.
5. Configuring `config.yaml` with keywords, schedule, and preferences.
6. First run with `--setup` to log into job sites in the automation browser.
7. Normal run with `python main.py`.
8. How to trigger manual scrapes and applies from the dashboard.
9. How to handle `needs_review` jobs.
10. How to re-authenticate when sessions expire.

---

## .gitignore Requirements

Must exclude:
- `db/jobs.db`
- `profile.json`
- `email_handler/token.json`
- `email_handler/credentials.json`
- `screenshots/`
- `browser_data/`
- `__pycache__/`
- `*.pyc`
- `.env`
