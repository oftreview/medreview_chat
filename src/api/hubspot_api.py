"""
src/api/hubspot_api.py — HubSpot integration endpoints.
Syncs leads and manages stage mapping with HubSpot.
"""
from flask import Blueprint, request, jsonify

from src.core import hubspot
from src.core import database
from src.api.chat import _get_agent

bp = Blueprint("hubspot_api", __name__)


@bp.route("/api/hubspot/status", methods=["GET"])
def api_hubspot_status():
    """Get HubSpot integration status (enabled, connected, mapping)."""
    return jsonify(hubspot.get_status()), 200


@bp.route("/api/hubspot/sync/<user_id>", methods=["POST"])
def api_hubspot_sync(user_id):
    """
    Manual sync of a lead to HubSpot.
    Useful for reprocessing failed leads or forcing update.
    """
    if not hubspot.is_enabled():
        return (
            jsonify({"error": "HubSpot não habilitado", "status": "error"}),
            400,
        )

    agent = _get_agent()

    # Get lead data
    lead_data = agent.get_lead_data(user_id)
    if not lead_data:
        lead_data = database.get_lead_metadata(user_id) or {}

    funnel_stage = lead_data.get("stage", lead_data.get("funnel_stage", "abertura"))

    result = hubspot.sync_lead(
        phone=user_id,
        funnel_stage=funnel_stage,
        lead_data=lead_data,
    )
    return jsonify({"status": "ok", "hubspot": result}), 200


@bp.route("/api/hubspot/mapping", methods=["GET", "POST"])
def api_hubspot_mapping():
    """
    GET: Return current stage mapping (Criatons → HubSpot).
    POST: Update custom mapping.
    Payload: { "abertura": "qualifiedtobuy", "fechamento": "closedwon", ... }
    """
    if request.method == "GET":
        return jsonify({"mapping": hubspot._get_stage_map()}), 200

    data = request.get_json(silent=True) or {}
    hubspot.set_stage_mapping(data)
    return jsonify({"status": "ok", "mapping": hubspot._get_stage_map()}), 200
