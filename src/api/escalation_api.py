"""
src/api/escalation_api.py — Escalation endpoints.
Manages human escalation and lead queries.
"""
from flask import Blueprint, request, jsonify

from src.core import database, escalation
from src.api.chat import _get_agent

bp = Blueprint("escalation_api", __name__)


@bp.route("/escalation/resolve", methods=["POST"])
def escalation_resolve():
    """
    Resolve an escalation (return control to AI after human handoff).
    Payload: { "phone": "...", "resolution": "..." }
    """
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    resolution = data.get("resolution", "").strip() or None

    if not phone:
        return jsonify({"error": "Campo 'phone' obrigatório"}), 400

    agent = _get_agent()
    escalation.resolve_escalation(phone, agent.memory, resolution=resolution)
    return (
        jsonify({"status": "ok", "message": f"Sessão {phone[:8]}... retornada para IA."}),
        200,
    )


@bp.route("/leads/escalated", methods=["GET"])
def leads_escalated():
    """List all sessions currently in human escalation."""
    agent = _get_agent()
    escalated = [
        s
        for s in agent.memory.list_sessions()
        if agent.memory.get_status(s) == "escalated"
    ]
    return jsonify({"escalated": escalated, "count": len(escalated)}), 200


@bp.route("/api/escalations", methods=["GET"])
def api_escalations():
    """
    List escalations from database.
    Query params: status (pending|resolved), limit (default 50)
    """
    status_filter = request.args.get("status", None)
    limit = int(request.args.get("limit", 50))
    escalations = database.list_escalations(status=status_filter, limit=limit)
    return jsonify({"escalations": escalations, "count": len(escalations)}), 200


@bp.route("/api/lead/<user_id>", methods=["GET"])
def api_lead_data(user_id):
    """
    Get lead metadata (funnel_stage, especialidade, etc).
    Tries memory first, then database.
    """
    agent = _get_agent()

    # Try memory (more recent)
    lead_data = agent.get_lead_data(user_id)

    # Fallback to database
    if not lead_data:
        lead_data = database.get_lead_metadata(user_id)

    return (
        jsonify({
            "user_id": user_id,
            "lead_data": lead_data,
            "source": "memory" if agent.get_lead_data(user_id) else "database",
        }),
        200,
    )
