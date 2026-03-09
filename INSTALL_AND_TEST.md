# Installation and Testing Guide

Complete step-by-step instructions for setting up and testing Job Pilot.

---

## Prerequisites

- **Python 3.11+** — [Download](https://www.python.org/downloads/)
- **pip** — comes with Python
- A **Gmail account** (for OTP verification)
- A **jobright.ai account** (or other supported job board)

---

## Step 1: Install Python Dependencies

```bash
cd path/to/AutoApplier
pip install -r requirements.txt
```

This installs:
- `playwright` — browser automation
- `Flask` — dashboard backend
- `pywebview` — native desktop window
- `APScheduler` — scheduled tasks
- `aiosqlite` — async SQLite
- `PyYAML` — configuration files
- `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` — Gmail API

## Step 2: Install Playwright Browser

```bash
playwright install chromium
```

This downloads an isolated Chromium browser (~150 MB). It is completely separate from your personal Chrome installation.

## Step 3: Gmail API Setup (for OTP Verification)

The Gmail handler needs read-only access to detect OTP codes sent by ATS platforms during applications.

### 3a. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Name it something like "Job Pilot" and create it

### 3b. Enable the Gmail API

1. In your project, go to **APIs & Services** → **Library**
2. Search for "Gmail API"
3. Click "Enable"

### 3c. Create OAuth2 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click "Create Credentials" → "OAuth client ID"
3. If prompted, configure the OAuth consent screen:
   - User type: **External**
   - App name: "Job Pilot"
   - Add your email as a test user
4. Application type: **Desktop app**
5. Name: "Job Pilot"
6. Click "Create"
7. Download the JSON file

### 3d. Place the Credentials File

Rename the downloaded file to `credentials.json` and place it in:

```
email_handler/credentials.json
```

### 3e. First-Time Authorization

On the first run that requires Gmail access (when an OTP gate is encountered), a browser window will open asking you to grant read-only Gmail access. After granting access, a `token.json` file is created automatically and reused for future runs.

**Note:** Only the `gmail.readonly` scope is requested. Job Pilot never sends, deletes, or modifies your emails.

---

## Step 4: Configure Your Profile

Edit `profile.json` with your actual data:

```json
{
  "personal": {
    "first_name": "Your Name",
    "last_name": "Your Last Name",
    "email": "your.email@gmail.com",
    "phone": "+1-555-123-4567",
    "linkedin_url": "https://linkedin.com/in/yourprofile",
    "github_url": "https://github.com/yourhandle",
    "portfolio_url": "",
    "location": {
      "city": "San Francisco",
      "state": "CA",
      "country": "United States",
      "zip": "94105"
    }
  },
  "resume_path": "C:/Users/you/Documents/resume.pdf",
  "experience_years": 3,
  ...
}
```

**Important:** Set `resume_path` to the absolute path of your resume PDF file.

---

## Step 5: Configure Settings

Edit `config.yaml`:

```yaml
keywords:
  include:
    - "software engineer"
    - "backend engineer"
  exclude:
    - "senior"
    - "intern"

date_cutoff_days: 7

skip_companies:
  - "Company You Don't Want"

scrape_schedule:
  hour: "9,13,17"
  minute: "0"

apply_schedule:
  hour: "9,13,17"
  minute: "15"
```

---

## Step 6: First Run — Browser Login

```bash
python main.py --setup
```

This opens an isolated Chromium browser. In this browser:

1. Navigate to **jobright.ai** and log in
2. Set up your saved search filters on jobright.ai
3. (Optional) Log into any other job boards you plan to add later
4. Close the browser when done

Your sessions are saved in `browser_data/` and persist across runs.

---

## Step 7: Normal Run

```bash
python main.py
```

This starts:
- The dashboard in a native desktop window
- The scraper on your configured schedule
- The application engine 15 minutes after each scrape

### Running Without the Desktop Window

If PyWebView is not available or you prefer browser access:

```bash
python main.py --no-gui
```

Then open `http://127.0.0.1:5000` in your browser.

---

## Testing

### Test 1: Database Initialization

```bash
python -c "import asyncio; from db.schema import init_db; asyncio.run(init_db()); print('DB created successfully')"
```

Verify `db/jobs.db` exists.

### Test 2: Filter Rules

```bash
python -c "
from filters.rules import apply_all_filters
import yaml

config = yaml.safe_load(open('config.yaml'))

good_job = {'title': 'Software Engineer', 'company': 'Acme', 'date_posted': '2026-03-05'}
bad_title = {'title': 'Senior Staff Engineer', 'company': 'Acme', 'date_posted': '2026-03-05'}
bad_company = {'title': 'Software Engineer', 'company': 'Example Corp', 'date_posted': '2026-03-05'}

print('Good job passes:', apply_all_filters(good_job, config))      # True
print('Bad title passes:', apply_all_filters(bad_title, config))     # False
print('Bad company passes:', apply_all_filters(bad_company, config)) # False
"
```

### Test 3: ATS Detection

```bash
python -c "
from ats.detector import detect_ats

print(detect_ats('https://boards.greenhouse.io/company/jobs/123'))  # greenhouse
print(detect_ats('https://jobs.lever.co/company/abc'))              # lever
print(detect_ats('https://jobs.ashbyhq.com/company'))               # ashby
print(detect_ats('https://company.myworkdayjobs.com/en-US/123'))   # workday
print(detect_ats('https://linkedin.com/jobs/view/123'))             # linkedin
print(detect_ats('https://randomsite.com/apply'))                   # unknown
"
```

### Test 4: Dashboard with Seed Data

Seed the database with test jobs, then verify the dashboard:

```bash
python -c "
import asyncio, random
from db.schema import init_db, get_db

async def seed():
    await init_db()
    db = await get_db()
    statuses = ['queued', 'queued', 'queued', 'applying', 'applied', 'applied',
                'applied', 'needs_review', 'needs_review', 'skipped', 'skipped',
                'queued', 'applied', 'needs_review', 'queued']
    ats_types = ['greenhouse', 'lever', 'ashby', 'workday', 'unknown']
    companies = ['Acme Corp', 'TechStart', 'MegaCloud', 'DataFlow', 'CodeBase']

    for i, status in enumerate(statuses):
        ats = ats_types[i % len(ats_types)]
        company = companies[i % len(companies)]
        warning = 'Could not confirm submission' if status == 'needs_review' else None
        try:
            await db.execute(
                '''INSERT INTO jobs (job_id, source, title, company, location,
                   date_posted, apply_url, ats_type, status, warning_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (f'test_{i}', 'test', f'Software Engineer #{i+1}', company,
                 'San Francisco, CA', '2026-03-05',
                 f'https://boards.greenhouse.io/test/jobs/{i}', ats, status, warning)
            )
        except Exception:
            pass
    await db.commit()
    await db.close()
    print(f'Seeded {len(statuses)} test jobs')

asyncio.run(seed())
"
```

Then start the dashboard:

```bash
python main.py --no-gui
```

Open `http://127.0.0.1:5000` and verify:
- [ ] All filter tabs show correct counts
- [ ] Clicking a filter loads the right jobs (no page reload)
- [ ] "Skip" button on queued jobs changes status to skipped
- [ ] "Re-queue" button on skipped/needs_review jobs changes status to queued
- [ ] Stats bar updates after actions
- [ ] "Scrape Now" and "Apply Now" buttons show a toast notification
- [ ] Screenshot modal opens (will show error for test data since no real screenshots)
- [ ] Dark theme renders correctly
- [ ] Auto-refresh toggle works

### Test 5: Browser Manager

```bash
python -c "
import asyncio
from browser.manager import BrowserManager

async def test():
    bm = BrowserManager()
    await bm.launch()
    page = await bm.new_page()
    await page.goto('https://example.com')
    title = await page.title()
    print(f'Page title: {title}')
    
    # Verify anti-detection
    is_webdriver = await page.evaluate('() => navigator.webdriver')
    print(f'navigator.webdriver: {is_webdriver}')  # Should be None/undefined
    
    await bm.close_page(page)
    await bm.shutdown()
    print('Browser test passed')

asyncio.run(test())
"
```

### Test 6: Interceptors

```bash
python -c "
import asyncio
from browser.manager import BrowserManager
from browser.interceptors import register_interceptors

async def test():
    bm = BrowserManager()
    await bm.launch()
    page = await bm.new_page()
    register_interceptors(page)
    
    await page.goto('https://example.com')
    
    # Trigger a dialog — should be silently dismissed
    dismissed = await page.evaluate('''() => {
        return new Promise(resolve => {
            window.addEventListener('beforeunload', () => resolve(true));
            alert('This should be dismissed');
            resolve(true);
        });
    }''')
    print(f'Dialog dismissed silently: {dismissed}')
    
    await bm.close_page(page)
    await bm.shutdown()
    print('Interceptor test passed')

asyncio.run(test())
"
```

### Test 7: Gmail OTP (Manual)

If you have set up Gmail API credentials:

```bash
python -c "
from email_handler.gmail import GmailHandler
gh = GmailHandler()
if gh.authenticate():
    print('Gmail authentication successful')
else:
    print('Gmail authentication failed — check credentials.json')
"
```

To test OTP polling, send yourself an email with a 6-digit code, then:

```bash
python -c "
import asyncio
from email_handler.gmail import GmailHandler

async def test():
    gh = GmailHandler()
    gh.authenticate()
    result = await gh.poll_for_otp('your.other.email@gmail.com', timeout_seconds=30)
    print('Result:', result)

asyncio.run(test())
"
```

---

## Troubleshooting

### "Database is locked"

This should not happen because WAL mode is enabled. If it does, ensure no other process has a write lock on `db/jobs.db`.

### Sessions expired / "Re-authentication needed"

Run `python main.py --setup` or click "Re-authenticate" in the dashboard to re-login to job sites.

### OTP emails not arriving

- Verify `email_handler/credentials.json` exists and is valid
- Check that Gmail API is enabled in your Google Cloud project
- Ensure the sender address in `config.yaml` matches the actual sender
- Check your Gmail spam folder

### Browser crashes or behaves unexpectedly

Delete the `browser_data/` directory to start with a fresh browser profile, then run `--setup` again.

### PyWebView not installing

On Windows, PyWebView requires `pythonnet` or `cefpython3`. If installation fails, use `--no-gui` mode and access the dashboard at `http://127.0.0.1:5000`.

---

## File Safety

These files are gitignored and should never be committed:

- `db/jobs.db` — your job database
- `profile.json` — your personal information
- `email_handler/credentials.json` — Google OAuth credentials
- `email_handler/token.json` — Google OAuth token
- `browser_data/` — saved browser sessions
- `screenshots/` — failure screenshots
