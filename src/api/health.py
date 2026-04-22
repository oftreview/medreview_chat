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
    """Wild Memory complete status: shadow + context + lifecycle."""
    from src.core.wild_memory_shadow import shadow
    from src.core.wild_memory_context import context_injector
    from src.core.wild_memory_lifecycle import lifecycle
    status = shadow.get_status()
    status["context_injection"] = context_injector.get_status()
    status["lifecycle"] = lifecycle.get_status()
    try:
        from src.core.scheduler import get_status as scheduler_status
        status["scheduler"] = scheduler_status()
    except Exception:
        status["scheduler"] = {"enabled": False, "reason": "import_error"}
    return jsonify(status), 200


@bp.route("/api/wild-memory/cron", methods=["POST"])
def wild_memory_cron():
    """
    Manutenção diária do Wild Memory.
    Roda: decay → stale marking → cache cleanup → session cleanup.
    Chamar via Railway cron job ou manualmente.
    Requer auth (mesmo token da API).
    """
    from src.core.wild_memory_lifecycle import lifecycle
    from src.config import API_SECRET_TOKEN

    # Auth check
    if API_SECRET_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {API_SECRET_TOKEN}":
            return jsonify({"error": "Unauthorized"}), 401

    results = lifecycle.run_daily_maintenance()
    return jsonify(results), 200


@bp.route("/api/metrics", methods=["GET"])
def api_metrics():
    """Return API usage metrics (tokens, costs, cache)."""
    try:
        from src.core.metrics import get_metrics
        metrics = get_metrics()
    except ImportError:
        from src.config import OPENROUTER_MODEL, MAX_TOKENS
        metrics = {
            "model": OPENROUTER_MODEL,
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
        cfg.OPENROUTER_MODEL = data["model"]
        print(f"[CONFIG] Modelo alterado para: {cfg.OPENROUTER_MODEL}", flush=True)

    if "max_tokens" in data:
        cfg.MAX_TOKENS = int(data["max_tokens"])
        print(f"[CONFIG] Max tokens alterado para: {cfg.MAX_TOKENS}", flush=True)

    return jsonify({
        "status": "ok",
        "model": cfg.OPENROUTER_MODEL,
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


@bp.route("/api/logs/history", methods=["GET"])
def api_logs_history():
    """Return persistent logs from Supabase with filters."""
    from src.core.log_buffer import get_history

    result = get_history(
        tag=request.args.get("tag"),
        source=request.args.get("source"),
        search=request.args.get("search"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 100)),
    )
    return jsonify(result)


@bp.route("/api/logs/stats", methods=["GET"])
def api_logs_stats():
    """Return daily log volume stats for the calendar heatmap."""
    from src.core.log_buffer import get_daily_stats

    days = int(request.args.get("days", 30))
    stats = get_daily_stats(days_back=days)
    return jsonify({"stats": stats})


@bp.route("/api/logs/sources", methods=["GET"])
def api_logs_sources():
    """Return distinct log sources for filter dropdown."""
    from src.core.log_buffer import get_sources
    return jsonify({"sources": get_sources()})


@bp.route("/api/logs/cleanup", methods=["POST"])
def api_logs_cleanup():
    """Trigger cleanup of old logs (default 30 days retention)."""
    from src.config import API_SECRET_TOKEN

    if API_SECRET_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {API_SECRET_TOKEN}":
            return jsonify({"error": "Unauthorized"}), 401

    days = int(request.args.get("days", 30))
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if db:
            result = db.rpc("cleanup_old_logs", {"retention_days": days}).execute()
            deleted = result.data if result.data else 0
            return jsonify({"status": "ok", "deleted": deleted, "retention_days": days})
        return jsonify({"error": "Database not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── LLM Usage / Costs History ────────────────────────────────

@bp.route("/api/metrics/history", methods=["GET"])
def api_metrics_history():
    """Return persistent LLM usage history from Supabase."""
    from src.core.metrics import get_history

    result = get_history(
        model=request.args.get("model"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 50)),
    )
    return jsonify(result)


@bp.route("/api/metrics/daily", methods=["GET"])
def api_metrics_daily():
    """Return daily cost stats for charts."""
    from src.core.metrics import get_daily_stats

    days = int(request.args.get("days", 30))
    stats = get_daily_stats(days_back=days)

    # Se retornou erro (dict em vez de list), envia com campo error
    if isinstance(stats, dict) and "error" in stats:
        return jsonify({"stats": [], "error": stats.get("message", stats["error"])})

    return jsonify({"stats": stats})


@bp.route("/api/metrics/totals", methods=["GET"])
def api_metrics_totals():
    """Return all-time accumulated totals from Supabase."""
    from src.core.metrics import get_totals

    since = request.args.get("since")
    totals = get_totals(since=since)

    # Se retornou erro, envia com campo error para o frontend
    if isinstance(totals, dict) and "error" in totals:
        return jsonify({"totals": {}, "error": totals.get("message", totals["error"])})

    return jsonify({"totals": totals})


@bp.route("/api/metrics/status", methods=["GET"])
def api_metrics_status():
    """Diagnostic endpoint: check if llm_usage table exists and is accessible."""
    from src.core.metrics import check_table_status

    status = check_table_status()
    return jsonify(status)
