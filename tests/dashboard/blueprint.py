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


@bp.route("/api/debug")
def api_debug():
    """Diagnostic endpoint: check test infrastructure health."""
    import sys
    import subprocess
    diag = {
        "python": sys.executable,
        "version": sys.version,
        "cwd": os.getcwd(),
        "project_root": str(Path(__file__).parent.parent.parent),
        "results_dir": str(_RESULTS_DIR),
        "results_dir_exists": _RESULTS_DIR.exists(),
    }

    # Check test directories exist
    project_root = Path(__file__).parent.parent.parent
    for d in ["tests/unit", "tests/critical", "tests/integration", "tests/dashboard"]:
        full = project_root / d
        diag[f"dir_{d.replace('/', '_')}"] = full.exists()
        if full.exists():
            diag[f"files_{d.replace('/', '_')}"] = len(list(full.glob("*.py")))

    # Check key files
    for f in ["tests/conftest.py", "tests/__init__.py", "tests/runner.py"]:
        diag[f"file_{f.replace('/', '_').replace('.', '_')}"] = (project_root / f).exists()

    # Check pytest is importable
    try:
        import pytest as _pt
        diag["pytest_version"] = _pt.__version__
    except ImportError as e:
        diag["pytest_error"] = str(e)

    # Quick dry-run: collect only (no execution)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit/", "--collect-only", "-q"],
            capture_output=True, text=True,
            cwd=str(project_root),
            env={**os.environ, "TEST_MODE": "true",
                 "SUPABASE_URL": "http://localhost:54321",
                 "SUPABASE_KEY": "test-key",
                 "ANTHROPIC_API_KEY": "test-key"},
            timeout=30,
        )
        diag["collect_exit_code"] = r.returncode
        # Last 500 chars of stdout/stderr
        diag["collect_stdout"] = (r.stdout or "")[-500:]
        diag["collect_stderr"] = (r.stderr or "")[-500:]
    except Exception as e:
        diag["collect_error"] = str(e)

    return jsonify(diag)


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
