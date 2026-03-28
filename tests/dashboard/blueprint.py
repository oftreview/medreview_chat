"""
tests/dashboard/blueprint.py — Test Dashboard Flask Blueprint.

Provides:
  Pages:  /dashboard/tests (main dashboard)
  API:    /dashboard/tests/api/results, /api/history, /api/coverage, /api/run
"""
import json
import os
import uuid
import threading
import logging
from pathlib import Path
from datetime import datetime, timezone

from flask import Blueprint, render_template, jsonify, request

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_RESULTS_DIR = Path(__file__).parent.parent / "results"

bp = Blueprint(
    "test_dashboard",
    __name__,
    url_prefix="/dashboard/tests",
    template_folder=_TEMPLATE_DIR,
    static_folder=_STATIC_DIR,
    static_url_path="/dashboard/tests/static",
)

# In-memory job tracking
_jobs: dict = {}
_jobs_lock = threading.Lock()


def _read_json(filepath: Path) -> dict | list | None:
    """Safely read a JSON file."""
    if not filepath.exists():
        return None
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[Test Dashboard] Error reading {filepath}: {e}")
        return None


# ── Page Routes ──────────────────────────────────────────────────────────────

@bp.route("")
@bp.route("/")
def dashboard_page():
    """Render the test dashboard page."""
    return render_template("test_dashboard.html", active_page="tests")


# ── API Routes ───────────────────────────────────────────────────────────────

@bp.route("/api/results")
def api_results():
    """Return latest test results."""
    data = _read_json(_RESULTS_DIR / "latest.json")
    if data is None:
        return jsonify({
            "status": "no_data",
            "message": "Nenhum resultado de teste encontrado. Execute 'Run Tests Now'.",
        })
    return jsonify(data)


@bp.route("/api/history")
def api_history():
    """Return test run history."""
    data = _read_json(_RESULTS_DIR / "history.json")
    if data is None:
        return jsonify([])
    return jsonify(data)


@bp.route("/api/coverage")
def api_coverage():
    """Return coverage data."""
    data = _read_json(_RESULTS_DIR / "coverage.json")
    if data is None:
        return jsonify({"status": "no_data"})
    return jsonify(data)


@bp.route("/api/run", methods=["POST"])
def api_run():
    """Start a test run in background. Returns job_id."""
    job_id = str(uuid.uuid4())[:8]

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "result": None,
        }

    def _run_in_background():
        try:
            from tests.runner import run_tests
            result = run_tests()
            with _jobs_lock:
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["result"] = result
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = str(e)
            logger.error(f"[Test Dashboard] Run failed: {e}")

    t = threading.Thread(target=_run_in_background, daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "status": "running"})


@bp.route("/api/run/<job_id>")
def api_run_status(job_id):
    """Return status of a running test job."""
    with _jobs_lock:
        job = _jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify({
        "job_id": job_id,
        "status": job["status"],
        "started_at": job.get("started_at"),
        "result": job.get("result") if job["status"] == "completed" else None,
        "error": job.get("error") if job["status"] == "failed" else None,
    })
