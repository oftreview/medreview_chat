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
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "test-key"),
        "COVERAGE_FILE": coverage_data_file,
    }

    exit_code = -2
    for attempt, cmd in enumerate([base_cmd + cov_args, base_cmd]):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                cwd=str(PROJECT_ROOT),
                env=env,
                timeout=120,
            )
            exit_code = result.returncode
            # If json report was generated, we're good
            if Path(json_report_file).exists():
                break
            # If coverage caused PermissionError, retry without
            if "PermissionError" in (result.stderr or "") and attempt == 0:
                print("[TEST RUNNER] Coverage PermissionError, retrying without coverage...", flush=True)
                continue
            break
        except subprocess.TimeoutExpired:
            exit_code = -1
            break
        except Exception as e:
            print(f"[TEST RUNNER] Error: {e}", flush=True)
            exit_code = -2
            break

    duration = round(time.time() - start_time, 2)

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
