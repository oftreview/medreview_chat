"""
Escalation records.
Handles escalation registration, resolution, and listing.
"""
import json
from datetime import datetime, timezone
from .client import _get_client


def save_escalation(user_id: str, motivo: str, brief: dict,
                    session_id: str = None) -> bool:
    """
    Registra uma escalação na tabela escalations.
    O brief contém o resumo da conversa + dados do lead para o vendedor.
    """
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] save_escalation — DB não conectado", flush=True)
        return False

    try:
        db.table("escalations").insert({
            "user_id": user_id,
            "session_id": session_id,
            "motivo": motivo,
            "brief": json.dumps(brief, ensure_ascii=False),
            "status": "pending",
        }).execute()
        print(f"[DB] Escalação registrada: user={user_id[:8]}... motivo={motivo}", flush=True)
        return True
    except Exception as e:
        print(f"[DB ERROR] save_escalation: {e}", flush=True)
        return False


def resolve_escalation_record(user_id: str, resolution: str = None) -> bool:
    """Marca a escalação mais recente como resolvida."""
    db = _get_client()
    if db is None:
        return False

    try:
        db.table("escalations").update({
            "status": "resolved",
            "resolution": resolution,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", user_id).eq("status", "pending").execute()
        return True
    except Exception as e:
        print(f"[DB WARN] resolve_escalation_record: {e}", flush=True)
        return False


def list_escalations(status: str = None, limit: int = 50) -> list:
    """Lista escalações. Se status fornecido, filtra por status."""
    db = _get_client()
    if db is None:
        return []

    try:
        query = (
            db.table("escalations")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if status:
            query = query.eq("status", status)
        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"[DB WARN] list_escalations: {e}", flush=True)
        return []
