"""
src/core/scheduler.py — Internal cron scheduler for Wild Memory maintenance.

Uses APScheduler (BackgroundScheduler) to run daily maintenance tasks
(decay, stale marking, cache cleanup) without needing an external cron service.

The scheduler starts automatically when init_scheduler(app) is called from the
app factory. It runs in a background thread, completely independent of request
handling.

Safety:
  - Only starts if WILD_MEMORY_SHADOW=true (same gate as lifecycle)
  - Wrapped in try/except — never crashes the app
  - Skips duplicate init if called multiple times (idempotent)
  - Uses gevent-compatible BackgroundScheduler (thread-based, not asyncio)
"""

import os
import logging
import atexit

logger = logging.getLogger(__name__)

_scheduler = None
_initialized = False

# ── Configuration ────────────────────────────────────────────────────
# Default: run at 04:00 AM (server time) every day
MAINTENANCE_HOUR = int(os.getenv("WILD_MEMORY_CRON_HOUR", "4"))
MAINTENANCE_MINUTE = int(os.getenv("WILD_MEMORY_CRON_MINUTE", "0"))


def _run_maintenance():
    """Execute daily Wild Memory maintenance. Runs in background thread."""
    try:
        from src.core.wild_memory_lifecycle import lifecycle
        results = lifecycle.run_daily_maintenance()
        logger.info(f"[SCHEDULER] Wild Memory maintenance completed: {results}")
    except Exception as e:
        logger.warning(f"[SCHEDULER] Maintenance error (non-fatal): {e}")


def init_scheduler(app=None):
    """
    Initialize and start the background scheduler.

    Call once during app startup. Safe to call multiple times (idempotent).
    Only activates if WILD_MEMORY_SHADOW=true.

    Args:
        app: Flask app instance (optional, for logging context)
    """
    global _scheduler, _initialized

    if _initialized:
        return

    _initialized = True

    # Same gate as lifecycle — only run if Wild Memory is active
    if os.getenv("WILD_MEMORY_SHADOW", "").lower() != "true":
        logger.info("[SCHEDULER] Disabled (WILD_MEMORY_SHADOW != true)")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        _scheduler = BackgroundScheduler(daemon=True)

        _scheduler.add_job(
            func=_run_maintenance,
            trigger=CronTrigger(hour=MAINTENANCE_HOUR, minute=MAINTENANCE_MINUTE),
            id="wild_memory_daily_maintenance",
            name="Wild Memory Daily Maintenance",
            replace_existing=True,
        )

        _scheduler.start()
        logger.info(
            f"[SCHEDULER] Started — maintenance runs daily at "
            f"{MAINTENANCE_HOUR:02d}:{MAINTENANCE_MINUTE:02d}"
        )

        # Graceful shutdown when the process exits
        atexit.register(lambda: _scheduler.shutdown(wait=False))

    except ImportError:
        logger.warning("[SCHEDULER] apscheduler not installed — skipping cron setup")
    except Exception as e:
        logger.warning(f"[SCHEDULER] Failed to start (non-fatal): {e}")


def get_status() -> dict:
    """Return scheduler status for health endpoint."""
    if not _initialized:
        return {"enabled": False, "reason": "not_initialized"}

    if _scheduler is None:
        enabled = os.getenv("WILD_MEMORY_SHADOW", "").lower() == "true"
        if not enabled:
            return {"enabled": False, "reason": "WILD_MEMORY_SHADOW != true"}
        return {"enabled": True, "running": False, "reason": "scheduler_not_created"}

    job = _scheduler.get_job("wild_memory_daily_maintenance")
    next_run = str(job.next_run_time) if job and job.next_run_time else None

    return {
        "enabled": True,
        "running": _scheduler.running,
        "next_maintenance_run": next_run,
        "schedule": f"{MAINTENANCE_HOUR:02d}:{MAINTENANCE_MINUTE:02d} daily",
    }
