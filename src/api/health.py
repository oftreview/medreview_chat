"""
src/api/health.py — Health checks, metrics, config, and logs.
Monitoring and runtime configuration endpoints.
"""
from flask import Blueprint, request, jsonify

from src.core import database, hubspot
from src.api.chat import _get_agent

bp = Blueprint("health", __name__)


@bp.route("/health", methods=["GET"])
def health():
    """Basic health check."""
    return jsonify({"status": "ok", "version": "1.0"})


@bp.route("/health/hubspot", methods=["GET"])
def health_hubspot():
    """Test HubSpot connection."""
    status = hubspot.get_status()
    code = 200 if status["connected"] else (200 if not status["enabled"] else 500)
    return jsonify(status), code


@bp.route("/health/security", methods=["GET"])
def health_security():
    """Return last 20 security events for monitoring."""
    from src.core.logger import get_recent_events

    events = get_recent_events(20)
    return (
        jsonify({"status": "ok", "recent_events": events, "count": len(events)}),
        200,
    )


@bp.route("/health/db", methods=["GET"])
def health_db():
    """Test database connection (read + write + delete)."""
    result = database.health_check()
    status_code = 200 if result["connected"] else (200 if not result["enabled"] else 500)
    return jsonify(result), status_code


@bp.route("/health/memory", methods=["GET"])
def health_memory():
    """Return memory and persistence statistics."""
    agent = _get_agent()
    return (
        jsonify({
            "status": "ok",
            "memory": agent.memory.db_stats(),
            "db_connection": database.get_connection_status(),
        }),
        200,
    )


@bp.route("/health/wild-memory", methods=["GET"])
def health_wild_memory():
    """Wild Memory shadow mode status and metrics."""
    from src.core.wild_memory_shadow import shadow
    status = shadow.get_status()
    return jsonify(status), 200


@bp.route("/api/metrics", methods=["GET"])
def api_metrics():
    """Return API usage metrics (tokens, costs, cache)."""
    try:
        from src.core.metrics import get_metrics
        metrics = get_metrics()
    except ImportError:
        from src.config import CLAUDE_MODEL, MAX_TOKENS
        metrics = {
            "model": CLAUDE_MODEL,
            "max_tokens": MAX_TOKENS,
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_read": 0,
            "total_cache_write": 0,
            "total_cost": 0,
            "recent_calls": [],
        }
    return jsonify({"metrics": metrics})


@bp.route("/api/config", methods=["POST"])
def api_config_update():
    """Update model and max_tokens at runtime (no server restart needed)."""
    import src.config as cfg

    data = request.get_json(silent=True) or {}

    if "model" in data:
        cfg.CLAUDE_MODEL = data["model"]
        print(f"[CONFIG] Modelo alterado para: {cfg.CLAUDE_MODEL}", flush=True)

    if "max_tokens" in data:
        cfg.MAX_TOKENS = int(data["max_tokens"])
        print(f"[CONFIG] Max tokens alterado para: {cfg.MAX_TOKENS}", flush=True)

    return jsonify({
        "status": "ok",
        "model": cfg.CLAUDE_MODEL,
        "max_tokens": cfg.MAX_TOKENS,
    })


@bp.route("/api/logs", methods=["GET"])
def api_logs():
    """Return recent system logs."""
    try:
        from src.core.log_buffer import get_logs

        since = int(request.args.get("since", 0))
        logs = get_logs(since=since)
    except ImportError:
        logs = []

    return jsonify({"logs": logs})
