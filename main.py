"""
Job Pilot — Automated Job Application Pipeline
Entry point: persistent async loop, scheduler, Flask dashboard, PyWebView.
"""

import sys
import os
import json
import asyncio
import logging
import threading
import argparse
import atexit
import signal

import yaml
from apscheduler.schedulers.background import BackgroundScheduler

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

from db.schema import init_db, DB_PATH
from browser.manager import BrowserManager
from scraper.runner import scrape_and_store
from engine.applicant import ApplicationEngine
from dashboard.app import app as flask_app, set_triggers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("job_pilot")

# ── Globals ──
_loop: asyncio.AbstractEventLoop | None = None
_browser: BrowserManager | None = None
_config: dict = {}
_profile: dict = {}
_scheduler: BackgroundScheduler | None = None
_shutdown_done = False


def _cleanup():
    """Shut down scheduler, browser, and event loop. Safe to call multiple times."""
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True

    logger.info("Shutting down...")

    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass

    if _browser and _loop and _loop.is_running():
        try:
            future = asyncio.run_coroutine_threadsafe(_browser.shutdown(), _loop)
            future.result(timeout=10)
        except Exception:
            pass

    if _loop:
        _loop.call_soon_threadsafe(_loop.stop)

    logger.info("Goodbye.")


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def save_config(config: dict):
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def load_profile() -> dict:
    profile_path = os.path.join(os.path.dirname(__file__), "profile.json")
    with open(profile_path, "r") as f:
        return json.load(f)


# ── Schedule Management ──

def _apply_cron_job(job_id: str, func, sched_cfg: dict):
    """Add or remove a cron job based on schedule config."""
    global _scheduler
    if not _scheduler:
        return

    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass

    if not sched_cfg.get("enabled", True):
        return

    start_time = sched_cfg.get("start_time", "09:00")
    end_time = sched_cfg.get("end_time", "23:59")
    interval = sched_cfg.get("interval_minutes", 30)

    start_h = int(start_time.split(":")[0])
    end_h = int(end_time.split(":")[0])

    _scheduler.add_job(
        func, "cron",
        hour=f"{start_h}-{end_h}" if start_h != end_h else str(start_h),
        minute=f"*/{interval}" if interval < 60 else "0",
        id=job_id,
        replace_existing=True,
    )


def get_schedules() -> dict:
    scrape = _config.get("scrape_schedule", {})
    apply = _config.get("apply_schedule", {})
    return {
        "scrape": {
            "enabled": scrape.get("enabled", True),
            "start_time": scrape.get("start_time", "09:00"),
            "end_time": scrape.get("end_time", "17:00"),
            "interval_minutes": scrape.get("interval_minutes", 60),
        },
        "apply": {
            "enabled": apply.get("enabled", True),
            "start_time": apply.get("start_time", "21:00"),
            "end_time": apply.get("end_time", "23:59"),
            "interval_minutes": apply.get("interval_minutes", 15),
        },
    }


def update_schedules(scrape_cfg: dict, apply_cfg: dict):
    global _config
    _config["scrape_schedule"] = scrape_cfg
    _config["apply_schedule"] = apply_cfg
    save_config(_config)

    _apply_cron_job("scrape_job", scheduled_scrape, scrape_cfg)
    _apply_cron_job("apply_job", scheduled_apply, apply_cfg)
    logger.info(
        "Schedules updated — scrape %s, apply %s",
        "ON" if scrape_cfg.get("enabled") else "OFF",
        "ON" if apply_cfg.get("enabled") else "OFF",
    )


# ── Persistent Event Loop ──

def _run_event_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def submit_to_loop(coro):
    """Submit a coroutine to the persistent event loop from any thread."""
    if _loop and _loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, _loop)

        def _on_done(f):
            try:
                f.result()
            except Exception as exc:
                logger.error("Async task failed: %s", exc, exc_info=True)

        future.add_done_callback(_on_done)
        return future
    else:
        logger.error("Event loop is not running. _loop=%s", _loop)
        return None


# ── Scheduled Tasks ──

async def _scrape_task():
    global _browser, _config
    logger.info("Starting scheduled scrape...")
    try:
        page = await _browser.new_page()
        try:
            count = await scrape_and_store(page, _config)
            logger.info("Scrape complete: %d new jobs", count)
        finally:
            await _browser.close_page(page)
    except Exception as e:
        logger.error("Scrape task failed: %s", e, exc_info=True)


async def _apply_task():
    global _browser, _config, _profile
    logger.info("Starting scheduled apply run...")
    try:
        engine = ApplicationEngine(_browser, _profile, _config)
        await engine.run()
        logger.info("Apply run complete.")
    except Exception as e:
        logger.error("Apply task failed: %s", e, exc_info=True)


def scheduled_scrape():
    submit_to_loop(_scrape_task())


def scheduled_apply():
    submit_to_loop(_apply_task())


# ── Platforms ──

PLATFORMS = {
    "jobright": {
        "name": "Jobright",
        "login_url": "https://jobright.ai/login",
    },
}


def get_platforms() -> list[dict]:
    return [{"id": k, "name": v["name"]} for k, v in PLATFORMS.items()]


def trigger_reauth(platform_id: str) -> bool:
    info = PLATFORMS.get(platform_id)
    if not info:
        return False

    async def _reauth():
        url = info["login_url"]
        logger.info("Opening %s login page: %s", info["name"], url)
        page = await _browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("Could not navigate to %s: %s", url, e)

    submit_to_loop(_reauth())
    return True


# ── Dashboard Triggers ──

def trigger_scrape():
    submit_to_loop(_scrape_task())


def trigger_apply():
    submit_to_loop(_apply_task())


# ── Flask Thread ──

def run_flask(port: int):
    flask_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


# ── Setup Mode ──

async def run_setup():
    bm = BrowserManager()
    await bm.setup_mode()


# ── Main ──

def main():
    global _loop, _browser, _config, _profile, _scheduler

    parser = argparse.ArgumentParser(description="Job Pilot — Automated Job Applications")
    parser.add_argument("--setup", action="store_true", help="Launch browser for manual login")
    parser.add_argument("--no-gui", action="store_true", help="Run without PyWebView (dashboard in browser only)")
    args = parser.parse_args()

    _config = load_config()
    _profile = load_profile()
    port = _config.get("dashboard_port", 5000)

    # Initialize database
    asyncio.run(init_db())
    logger.info("Database initialized at %s", DB_PATH)

    if args.setup:
        logger.info("Running setup mode — log into your job sites in the browser.")
        asyncio.run(run_setup())
        logger.info("Setup complete. Sessions saved. Run `python main.py` to start.")
        return

    # 1. Create persistent event loop in background thread
    _loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=_run_event_loop, args=(_loop,), daemon=True)
    loop_thread.start()

    # 2. Launch browser on the persistent loop
    future = asyncio.run_coroutine_threadsafe(_launch_browser(), _loop)
    future.result(timeout=30)

    # 3. Set up dashboard triggers
    set_triggers(
        scrape_fn=trigger_scrape,
        apply_fn=trigger_apply,
        reauth_fn=trigger_reauth,
        get_platforms_fn=get_platforms,
        get_schedules_fn=get_schedules,
        update_schedules_fn=update_schedules,
    )

    # 4. Start Flask in daemon thread
    flask_thread = threading.Thread(target=run_flask, args=(port,), daemon=True)
    flask_thread.start()
    logger.info("Dashboard running at http://127.0.0.1:%d", port)

    # 5. Configure and start APScheduler
    _scheduler = BackgroundScheduler()
    _scheduler.start()

    schedules = get_schedules()
    _apply_cron_job("scrape_job", scheduled_scrape, schedules["scrape"])
    _apply_cron_job("apply_job", scheduled_apply, schedules["apply"])
    logger.info(
        "Scheduler started — scrape %s, apply %s",
        "ON" if schedules["scrape"]["enabled"] else "OFF",
        "ON" if schedules["apply"]["enabled"] else "OFF",
    )

    # 6. Register cleanup so it runs on any exit path
    atexit.register(_cleanup)

    def _signal_handler(sig, frame):
        _cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _signal_handler)

    # 7. Launch PyWebView (blocks on main thread)
    if args.no_gui:
        logger.info("Running without GUI. Press Ctrl+C to exit.")
        try:
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            pass
    else:
        try:
            import webview
            window = webview.create_window(
                "Job Pilot",
                f"http://127.0.0.1:{port}",
                width=1280,
                height=860,
                min_size=(900, 600),
            )
            webview.start()
        except ImportError:
            logger.warning(
                "PyWebView not available. Opening dashboard in browser mode. "
                "Install pywebview for native window: pip install pywebview"
            )
            logger.info("Dashboard at http://127.0.0.1:%d — Press Ctrl+C to exit.", port)
            try:
                while True:
                    threading.Event().wait(1)
            except KeyboardInterrupt:
                pass

    _cleanup()
    loop_thread.join(timeout=5)


async def _launch_browser():
    global _browser
    _browser = BrowserManager()
    await _browser.launch()


if __name__ == "__main__":
    main()
