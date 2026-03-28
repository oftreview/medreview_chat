"""
Test runner que gera resultados em JSON para o dashboard.

Uso: python -m tests.runner
Gera: tests/results/latest.json e tests/results/history.json

Pode ser chamado programaticamente via run_tests() ou via CLI.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Diretorio de resultados
RESULTS_DIR = Path(__file__).parent / "results"
LATEST_FILE = RESULTS_DIR / "latest.json"
HISTORY_FILE = RESULTS_DIR / "history.json"
COVERAGE_FILE = RESULTS_DIR / "coverage.json"
PROJECT_ROOT = Path(__file__).parent.parent


def _ensure_results_dir():
    """Cria diretorio de resultados se nao existir."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def run_tests() -> dict:
    """
    Executa pytest com json-report e coverage, salva resultados.
    Retorna dict com status do run.
    """
    _ensure_results_dir()

    start_time = time.time()
    timestamp = datetime.now(timezone.utc).isoformat()

    # Roda pytest com json-report
    json_report_file = str(RESULTS_DIR / "_raw_report.json")
    coverage_data_file = str(RESULTS_DIR / ".coverage")

    # Base command (always includes json-report)
    base_cmd = [
        sys.executable, "-m", "pytest",
        "tests/unit/", "tests/critical/", "tests/integration/",
        "-v", "--tb=short", "-q",
        "--json-report", f"--json-report-file={json_report_file}",
    ]

    # Try with coverage first, fall back to without if PermissionError
    cov_args = [f"--cov=src", f"--cov-report=json:{COVERAGE_FILE}"]

    env = {
        **os.environ,
        # ── Test-mode env vars (must match conftest.py) ──
        "TEST_MODE": "true",
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "test-key"),
        "SUPABASE_URL": os.environ.get("SUPABASE_URL", "http://localhost:54321"),
        "SUPABASE_KEY": os.environ.get("SUPABASE_KEY", "test-key-not-real"),
        "ZAPI_INSTANCE_ID": os.environ.get("ZAPI_INSTANCE_ID", ""),
        "ZAPI_TOKEN": os.environ.get("ZAPI_TOKEN", ""),
        "ZAPI_CLIENT_TOKEN": os.environ.get("ZAPI_CLIENT_TOKEN", ""),
        "HUBSPOT_ACCESS_TOKEN": os.environ.get("HUBSPOT_ACCESS_TOKEN", ""),
        "HUBSPOT_ENABLED": "false",
        "SUPERVISOR_PHONE": "",
        "API_SECRET_TOKEN": os.environ.get("API_SECRET_TOKEN", "test-secret-token"),
        "RESPONSE_DELAY_SECONDS": "1",
        "COVERAGE_FILE": coverage_data_file,
    }

    exit_code = -2
    last_stdout = ""
    last_stderr = ""
    for attempt, cmd in enumerate([base_cmd + cov_args, base_cmd]):
        try:
            print(f"[TEST RUNNER] Attempt {attempt+1}, cmd: {' '.join(cmd[:6])}...", flush=True)
            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                cwd=str(PROJECT_ROOT),
                env=env,
                timeout=180,
            )
            exit_code = result.returncode
            last_stdout = result.stdout or ""
            last_stderr = result.stderr or ""

            # Log output for debugging
            if last_stderr:
                # Limit to last 2000 chars to avoid flooding logs
                stderr_tail = last_stderr[-2000:] if len(last_stderr) > 2000 else last_stderr
                print(f"[TEST RUNNER] stderr (attempt {attempt+1}):\n{stderr_tail}", flush=True)
            if exit_code != 0:
                stdout_tail = last_stdout[-1000:] if len(last_stdout) > 1000 else last_stdout
                print(f"[TEST RUNNER] stdout (attempt {attempt+1}, exit={exit_code}):\n{stdout_tail}", flush=True)

            # If json report was generated, we're good
            if Path(json_report_file).exists():
                break
            # If coverage caused PermissionError, retry without
            if "PermissionError" in last_stderr and attempt == 0:
                print("[TEST RUNNER] Coverage PermissionError, retrying without coverage...", flush=True)
                continue
            # If no report generated, log the issue
            print(f"[TEST RUNNER] No JSON report generated on attempt {attempt+1}", flush=True)
            break
        except subprocess.TimeoutExpired:
            print("[TEST RUNNER] Timeout expired (180s)", flush=True)
            exit_code = -1
            break
        except Exception as e:
            print(f"[TEST RUNNER] Exception: {e}", flush=True)
            exit_code = -2
            break

    duration = round(time.time() - start_time, 2)

    # If no report generated at all, create a minimal error report
    if not Path(json_report_file).exists():
        error_msg = last_stderr[-1000:] if last_stderr else "No output from pytest"
        print(f"[TEST RUNNER] FATAL: No json report. stderr: {error_msg}", flush=True)
        # Create a minimal latest.json with error info so dashboard shows something
        latest = {
            "timestamp": timestamp,
            "duration": round(time.time() - start_time, 2),
            "exit_code": exit_code,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 1,
            "categories": {"unit": [], "critical": [], "integration": [], "e2e": []},
            "critical_bugs": {},
            "coverage": {"total_percent": 0, "files": {}},
            "runner_error": error_msg,
        }
        with open(LATEST_FILE, "w") as f:
            json.dump(latest, f, indent=2)
        _append_history(latest)
        return latest

    # Parse json-report
    report = {}
    if Path(json_report_file).exists():
        try:
            with open(json_report_file, "r") as f:
                report = json.load(f)
            os.remove(json_report_file)
        except Exception:
            pass

    # Parse coverage
    coverage_data = {}
    if COVERAGE_FILE.exists():
        try:
            with open(COVERAGE_FILE, "r") as f:
                coverage_data = json.load(f)
        except Exception:
            pass

    # Build latest.json
    summary = report.get("summary", {})
    tests = report.get("tests", [])

    # Classify tests by category
    categories = {"unit": [], "critical": [], "integration": [], "e2e": []}
    critical_tests = {}

    for test in tests:
        node_id = test.get("nodeid", "")
        test_info = {
            "nodeid": node_id,
            "outcome": test.get("outcome", "unknown"),
            "duration": round(test.get("duration", 0), 4),
            "message": "",
        }

        # Extract error message if failed
        if test.get("outcome") == "failed":
            call_info = test.get("call", {})
            test_info["message"] = call_info.get("longrepr", "")[:500]

        # Categorize
        if "/critical/" in node_id:
            categories["critical"].append(test_info)
        elif "/integration/" in node_id:
            categories["integration"].append(test_info)
        elif "/e2e/" in node_id:
            categories["e2e"].append(test_info)
        else:
            categories["unit"].append(test_info)

        # Track critical bug tests
        if "test_debounce_race" in node_id or "test_concurrent_messages" in node_id:
            critical_tests["BUG1_debounce_race"] = test_info["outcome"]
        elif "test_primary_waiter" in node_id or "test_last_request_becomes" in node_id:
            critical_tests["BUG2_primary_waiter"] = test_info["outcome"]
        elif "test_memory_cleanup" in node_id or "test_concurrent_add_and_cleanup" in node_id:
            critical_tests["BUG3_memory_cleanup"] = test_info["outcome"]
        elif "test_history_truncation" in node_id or "test_31_messages" in node_id:
            critical_tests["BUG4_history_truncation"] = test_info["outcome"]

    # Coverage summary
    coverage_summary = {}
    if coverage_data.get("files"):
        for filepath, file_data in coverage_data["files"].items():
            coverage_summary[filepath] = {
                "statements": file_data.get("summary", {}).get("num_statements", 0),
                "missing": file_data.get("summary", {}).get("missing_lines", 0),
                "coverage": file_data.get("summary", {}).get("percent_covered", 0),
            }

    total_coverage = coverage_data.get("totals", {}).get("percent_covered", 0)

    latest = {
        "timestamp": timestamp,
        "duration": duration,
        "exit_code": exit_code,
        "total": summary.get("total", 0),
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "skipped": summary.get("skipped", 0),
        "errors": summary.get("error", 0),
        "categories": categories,
        "critical_bugs": critical_tests,
        "coverage": {
            "total_percent": round(total_coverage, 1),
            "files": coverage_summary,
        },
    }

    # Save latest.json
    with open(LATEST_FILE, "w") as f:
        json.dump(latest, f, indent=2)

    # Append to history.json
    _append_history(latest)

    print(
        f"[TEST RUNNER] Concluido: {latest['passed']}/{latest['total']} passed, "
        f"{latest['failed']} failed, coverage={latest['coverage']['total_percent']}%, "
        f"duracao={duration}s",
        flush=True,
    )

    return latest


def _append_history(run_data: dict):
    """Adiciona run ao historico (maximo 100 entradas)."""
    history = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = []

    entry = {
        "timestamp": run_data["timestamp"],
        "duration": run_data["duration"],
        "total": run_data["total"],
        "passed": run_data["passed"],
        "failed": run_data["failed"],
        "skipped": run_data["skipped"],
        "coverage": run_data["coverage"]["total_percent"],
    }

    history.append(entry)
    history = history[-100:]  # Keep last 100

    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


if __name__ == "__main__":
    print("[TEST RUNNER] Iniciando test run...", flush=True)
    result = run_tests()
    sys.exit(0 if result["failed"] == 0 else 1)
