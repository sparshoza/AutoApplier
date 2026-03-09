import os
import sqlite3
import logging
from flask import Flask, jsonify, request, render_template, send_file

logger = logging.getLogger("job_pilot.dashboard")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "jobs.db")

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# Will be set by main.py so the dashboard can trigger async work
_trigger_scrape = None
_trigger_apply = None
_trigger_reauth = None
_get_platforms = None
_get_schedules = None
_update_schedules = None


def set_triggers(scrape_fn=None, apply_fn=None, reauth_fn=None,
                 get_platforms_fn=None, get_schedules_fn=None,
                 update_schedules_fn=None):
    global _trigger_scrape, _trigger_apply, _trigger_reauth
    global _get_platforms, _get_schedules, _update_schedules
    _trigger_scrape = scrape_fn
    _trigger_apply = apply_fn
    _trigger_reauth = reauth_fn
    _get_platforms = get_platforms_fn
    _get_schedules = get_schedules_fn
    _update_schedules = update_schedules_fn


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/jobs")
def api_jobs():
    status = request.args.get("status", "all")
    conn = _get_db()
    try:
        if status == "all" or not status:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY scraped_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY scraped_at DESC",
                (status,),
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route("/api/stats")
def api_stats():
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
        ).fetchall()
        stats = {r["status"]: r["count"] for r in rows}
        stats["total"] = sum(stats.values())
        return jsonify(stats)
    finally:
        conn.close()


@app.route("/api/jobs/<int:job_id>/status", methods=["POST"])
def api_update_status(job_id):
    data = request.get_json()
    new_status = data.get("status")
    if new_status not in ("applied", "skipped", "queued"):
        return jsonify({"error": "Invalid status"}), 400

    conn = _get_db()
    try:
        conn.execute(
            "UPDATE jobs SET status = ?, warning_reason = NULL WHERE id = ?",
            (new_status, job_id),
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/jobs/<int:job_id>/screenshot")
def api_screenshot(job_id):
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT screenshot_path FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not row or not row["screenshot_path"]:
            return jsonify({"error": "No screenshot"}), 404
        path = row["screenshot_path"]
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), path)
        if not os.path.exists(path):
            return jsonify({"error": "Screenshot file not found"}), 404
        return send_file(path, mimetype="image/png")
    finally:
        conn.close()


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    if _trigger_scrape:
        _trigger_scrape()
        return jsonify({"ok": True, "message": "Scrape started"})
    return jsonify({"error": "Scrape trigger not configured"}), 503


@app.route("/api/apply", methods=["POST"])
def api_apply():
    if _trigger_apply:
        _trigger_apply()
        return jsonify({"ok": True, "message": "Apply run started"})
    return jsonify({"error": "Apply trigger not configured"}), 503


@app.route("/api/platforms")
def api_platforms():
    if _get_platforms:
        return jsonify(_get_platforms())
    return jsonify([])


@app.route("/api/reauth", methods=["POST"])
def api_reauth():
    if not _trigger_reauth:
        return jsonify({"error": "Not configured"}), 503
    data = request.get_json()
    platform = data.get("platform")
    if not platform:
        return jsonify({"error": "Missing platform"}), 400
    if _trigger_reauth(platform):
        return jsonify({"ok": True, "message": f"Login page opened for {platform}"})
    return jsonify({"error": f"Unknown platform: {platform}"}), 400


@app.route("/api/schedules")
def api_get_schedules():
    if _get_schedules:
        return jsonify(_get_schedules())
    return jsonify({"error": "Not configured"}), 503


@app.route("/api/schedules", methods=["POST"])
def api_update_schedules():
    if not _update_schedules:
        return jsonify({"error": "Not configured"}), 503

    data = request.get_json()
    scrape = data.get("scrape")
    apply = data.get("apply")
    if not scrape or not apply:
        return jsonify({"error": "Both scrape and apply configs required"}), 400

    _update_schedules(scrape, apply)
    return jsonify({"ok": True})
