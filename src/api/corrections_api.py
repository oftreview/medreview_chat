"""
src/api/corrections_api.py — Agent corrections management endpoints.
Manages correction rules with dual-write to Supabase and JSON cache.
"""
import os
import json
from flask import Blueprint, request, jsonify

from src.core import database
from src.core.database.corrections import (
    _load_corrections_json,
    _save_corrections_json,
    _sync_json_to_supabase,
)

bp = Blueprint("corrections_api", __name__)


@bp.route("/api/corrections", methods=["GET"])
def api_corrections_list():
    """
    List corrections. Tries Supabase first, fallback to JSON.
    Query params: source (supabase|json|auto), include_archived (true|false)
    """
    source = request.args.get("source", "auto")
    include_archived = request.args.get("include_archived", "false").lower() == "true"

    if source == "json":
        return jsonify({"corrections": _load_corrections_json(), "source": "json"})

    # Try Supabase
    db_corrections = database.load_corrections(include_archived=include_archived)
    if db_corrections:
        return jsonify({"corrections": db_corrections, "source": "supabase"})

    # Fallback to JSON
    return jsonify({"corrections": _load_corrections_json(), "source": "json_fallback"})


@bp.route("/api/corrections", methods=["POST"])
def api_corrections_add():
    """
    Add/update a correction. Saves to both Supabase and JSON cache.
    Fields: id (required), regra (required), gatilho, resposta_errada, resposta_correta, categoria, severidade, status
    Optional: conversation_user_id, conversation_message_id
    """
    data = request.get_json(silent=True) or {}
    corr_id = data.get("id", "").strip()
    regra = data.get("regra", "").strip()

    if not corr_id or not regra:
        return jsonify({"error": "id e regra sao obrigatorios"}), 400

    new_corr = {
        "id": corr_id,
        "gatilho": data.get("gatilho", ""),
        "resposta_errada": data.get("resposta_errada", ""),
        "resposta_correta": data.get("resposta_correta", ""),
        "regra": regra,
        "categoria": data.get("categoria", "outro"),
        "severidade": data.get("severidade", "alta"),
        "status": data.get("status", "ativa"),
        "reincidencia": data.get("reincidencia", False),
        "reincidencia_count": data.get("reincidencia_count", 0),
    }

    # Link with original conversation (optional)
    if data.get("conversation_user_id"):
        new_corr["conversation_user_id"] = data["conversation_user_id"]
    if data.get("conversation_message_id"):
        new_corr["conversation_message_id"] = data["conversation_message_id"]

    # Save to Supabase
    db_ok = database.save_correction(new_corr)

    # Save to JSON cache
    corrections = _load_corrections_json()
    idx = next((i for i, c in enumerate(corrections) if c.get("id") == corr_id), None)
    if idx is not None:
        corrections[idx].update(new_corr)
    else:
        corrections.append(new_corr)
    _save_corrections_json(corrections)

    return jsonify({"status": "ok", "correction": new_corr, "supabase_synced": db_ok})


@bp.route("/api/corrections/reincidence", methods=["POST"])
def api_corrections_reincidence():
    """
    Record reincurrence of a correction.
    Payload: { "id": "COR-003" }
    """
    data = request.get_json(silent=True) or {}
    corr_id = data.get("id", "").strip()

    if not corr_id:
        return jsonify({"error": "id obrigatório"}), 400

    ok = database.increment_reincidence(corr_id)
    return jsonify({"status": "ok" if ok else "error", "correction_id": corr_id})


@bp.route("/api/corrections/sync", methods=["POST"])
def api_corrections_sync():
    """
    Manual sync: push all corrections from JSON to Supabase.
    Useful for initial migration.
    """
    synced = _sync_json_to_supabase()
    return jsonify({"status": "ok", "synced": synced})


@bp.route("/api/corrections/auto-archive", methods=["POST"])
def api_corrections_auto_archive():
    """
    Archive corrections without reincurrence in last N days.
    Query param: days (default 30)
    """
    days = int(request.args.get("days", 30))
    archived = database.auto_archive_corrections(days=days)
    return jsonify({"status": "ok", "archived": archived, "period_days": days})


@bp.route("/api/corrections/analytics", methods=["GET"])
def api_corrections_analytics():
    """
    Analytics for corrections in last N days.
    Query param: days (default 7)
    Returns: total active, reincurrences by category, critical recurrent.
    """
    days = int(request.args.get("days", 7))
    analytics = database.correction_analytics(days=days)
    return jsonify(analytics)
