"""
src/api/backlog_api.py — Product backlog management endpoints.
CRUD + analytics + reorder for backlog items with RICE prioritization.
"""
from flask import Blueprint, request, jsonify

from src.core.database.backlog import (
    load_backlog,
    save_backlog_item,
    delete_backlog_item,
    get_next_item_id,
    reorder_backlog,
    backlog_analytics,
    seed_backlog_if_empty,
)

bp = Blueprint("backlog_api", __name__)


@bp.route("/api/backlog", methods=["GET"])
def api_backlog_list():
    """
    Lista itens do backlog.
    Query params: status, phase
    """
    # Seed on first access if empty
    seed_backlog_if_empty()

    status = request.args.get("status")
    phase = request.args.get("phase")
    items = load_backlog(status=status, phase=phase)
    return jsonify({"items": items, "total": len(items)})


@bp.route("/api/backlog", methods=["POST"])
def api_backlog_save():
    """
    Cria ou atualiza um item do backlog.
    Se item_id não for enviado, gera um novo automaticamente.
    """
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()

    if not title:
        return jsonify({"error": "title é obrigatório"}), 400

    if not data.get("item_id"):
        data["item_id"] = get_next_item_id()

    item = {
        "item_id": data["item_id"],
        "title": title,
        "description": data.get("description", ""),
        "item_type": data.get("item_type", "feature"),
        "module": data.get("module", "core"),
        "status": data.get("status", "backlog"),
        "phase": data.get("phase", "Phase 2"),
        "reach": int(data.get("reach", 100)),
        "impact": float(data.get("impact", 1.0)),
        "confidence": float(data.get("confidence", 0.8)),
        "effort": float(data.get("effort", 2.0)),
        "estimate": data.get("estimate", ""),
        "dependencies": data.get("dependencies", ""),
        "notes": data.get("notes", ""),
        "sort_order": int(data.get("sort_order", 0)),
    }

    ok = save_backlog_item(item)
    return jsonify({"status": "ok", "item": item, "supabase_synced": ok})


@bp.route("/api/backlog/<item_id>", methods=["PUT"])
def api_backlog_update(item_id):
    """Atualiza campos específicos de um item."""
    data = request.get_json(silent=True) or {}

    # Carrega item atual
    items = load_backlog()
    current = next((i for i in items if i.get("item_id") == item_id), None)
    if not current:
        return jsonify({"error": "Item não encontrado"}), 404

    # Merge com dados novos
    for key in ["title", "description", "item_type", "module", "status",
                "phase", "estimate", "dependencies", "notes"]:
        if key in data:
            current[key] = data[key]

    for key in ["reach", "sort_order"]:
        if key in data:
            current[key] = int(data[key])

    for key in ["impact", "confidence", "effort"]:
        if key in data:
            current[key] = float(data[key])

    current["item_id"] = item_id
    ok = save_backlog_item(current)
    return jsonify({"status": "ok", "item": current, "supabase_synced": ok})


@bp.route("/api/backlog/<item_id>", methods=["DELETE"])
def api_backlog_delete(item_id):
    """Remove um item do backlog."""
    ok = delete_backlog_item(item_id)
    return jsonify({"status": "ok" if ok else "error", "item_id": item_id})


@bp.route("/api/backlog/reorder", methods=["POST"])
def api_backlog_reorder():
    """
    Reordena itens do backlog.
    Payload: { "ordered_ids": ["CRI-003", "CRI-001", ...] }
    """
    data = request.get_json(silent=True) or {}
    ordered_ids = data.get("ordered_ids", [])
    if not ordered_ids:
        return jsonify({"error": "ordered_ids obrigatório"}), 400

    ok = reorder_backlog(ordered_ids)
    return jsonify({"status": "ok" if ok else "error"})


@bp.route("/api/backlog/analytics", methods=["GET"])
def api_backlog_analytics():
    """Retorna resumo analítico do backlog."""
    return jsonify(backlog_analytics())


@bp.route("/api/backlog/next-id", methods=["GET"])
def api_backlog_next_id():
    """Retorna próximo ID disponível."""
    return jsonify({"next_id": get_next_item_id()})
