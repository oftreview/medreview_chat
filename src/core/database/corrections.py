"""
Corrections + dual-write + analytics.
Handles correction records, archiving, analytics, and JSON persistence.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from .client import _get_client


# ── JSON Dual-Write Helpers ────────────────────────────────────────────────────


def _get_corrections_json_path() -> str:
    """Determina o caminho padrão para o arquivo de correções JSON."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "data",
        "corrections.json"
    )


def _load_corrections_json(path: str = None) -> list:
    """Carrega correções do arquivo JSON local."""
    if path is None:
        path = _get_corrections_json_path()

    if not os.path.exists(path):
        return []

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f) or []
    except Exception as e:
        print(f"[DB WARN] _load_corrections_json: {e}", flush=True)
        return []


def _save_corrections_json(path: str = None, corrections: list = None) -> bool:
    """Salva correções no arquivo JSON local."""
    if path is None:
        path = _get_corrections_json_path()
    if corrections is None:
        corrections = []

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(corrections, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[DB WARN] _save_corrections_json: {e}", flush=True)
        return False


def _sync_json_to_supabase(path: str = None) -> bool:
    """Sincroniza correções do JSON para Supabase."""
    corrections = _load_corrections_json(path)
    if not corrections:
        return True

    db = _get_client()
    if db is None:
        return False

    try:
        for correction in corrections:
            save_correction(correction)
        return True
    except Exception as e:
        print(f"[DB WARN] _sync_json_to_supabase: {e}", flush=True)
        return False


# ── Corrections CRUD ───────────────────────────────────────────────────────────


def save_correction(correction: dict) -> bool:
    """
    Salva ou atualiza uma correção no Supabase (upsert por correction_id).
    O JSON local continua como cache — Supabase é a fonte de verdade.
    """
    db = _get_client()
    if db is None:
        return False

    try:
        row = {
            "correction_id": correction["id"],
            "categoria": correction.get("categoria", "outro"),
            "severidade": correction.get("severidade", "alta"),
            "gatilho": correction.get("gatilho", ""),
            "resposta_errada": correction.get("resposta_errada", ""),
            "resposta_correta": correction.get("resposta_correta", ""),
            "regra": correction.get("regra", ""),
            "status": correction.get("status", "ativa"),
            "reincidencia": correction.get("reincidencia", False),
            "reincidencia_count": correction.get("reincidencia_count", 0),
        }
        # Link para conversa original (se disponível)
        if correction.get("conversation_user_id"):
            row["conversation_user_id"] = correction["conversation_user_id"]
        if correction.get("conversation_message_id"):
            row["conversation_message_id"] = correction["conversation_message_id"]

        db.table("corrections").upsert(row, on_conflict="correction_id").execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] save_correction {correction.get('id')}: {e}", flush=True)
        return False


def load_corrections(status: str = None, include_archived: bool = False) -> list:
    """
    Carrega correções do Supabase.
    Por padrão exclui arquivadas (status='arquivada').
    """
    db = _get_client()
    if db is None:
        return []

    try:
        query = (
            db.table("corrections")
            .select("*")
            .order("created_at", desc=True)
        )
        if status:
            query = query.eq("status", status)
        elif not include_archived:
            query = query.neq("status", "arquivada")

        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"[DB WARN] load_corrections: {e}", flush=True)
        return []


def increment_reincidence(correction_id: str) -> bool:
    """Incrementa contador de reincidência de uma correção."""
    db = _get_client()
    if db is None:
        return False

    try:
        # Busca valor atual
        result = (
            db.table("corrections")
            .select("reincidencia_count")
            .eq("correction_id", correction_id)
            .limit(1)
            .execute()
        )
        current = 0
        if result.data:
            current = result.data[0].get("reincidencia_count", 0) or 0

        db.table("corrections").update({
            "reincidencia": True,
            "reincidencia_count": current + 1,
            "last_reincidence_at": datetime.now(timezone.utc).isoformat(),
        }).eq("correction_id", correction_id).execute()
        print(f"[DB] Reincidência incrementada: {correction_id} → {current + 1}", flush=True)
        return True
    except Exception as e:
        print(f"[DB WARN] increment_reincidence: {e}", flush=True)
        return False


def auto_archive_corrections(days: int = 30) -> int:
    """
    Arquiva correções sem reincidência nos últimos N dias.
    Retorna quantidade de correções arquivadas.
    """
    db = _get_client()
    if db is None:
        return 0

    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Busca correções ativas sem reincidência recente
        result = (
            db.table("corrections")
            .select("correction_id, last_reincidence_at, created_at")
            .eq("status", "ativa")
            .execute()
        )

        to_archive = []
        for row in (result.data or []):
            last_event = row.get("last_reincidence_at") or row.get("created_at")
            if last_event and last_event < cutoff:
                to_archive.append(row["correction_id"])

        if not to_archive:
            return 0

        for cid in to_archive:
            db.table("corrections").update({
                "status": "arquivada",
            }).eq("correction_id", cid).execute()

        print(f"[DB] Auto-archive: {len(to_archive)} correções arquivadas (>{days} dias sem reincidência)", flush=True)
        return len(to_archive)
    except Exception as e:
        print(f"[DB WARN] auto_archive_corrections: {e}", flush=True)
        return 0


def correction_analytics(days: int = 7) -> dict:
    """
    Retorna análise de erros dos últimos N dias:
    - Total de correções ativas
    - Reincidências por categoria
    - Categorias mais frequentes
    - Correções críticas reincidentes
    """
    db = _get_client()
    if db is None:
        return {"error": "DB não conectado"}

    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Todas as ativas
        active = (
            db.table("corrections")
            .select("*")
            .eq("status", "ativa")
            .execute()
        )
        corrections = active.data or []

        # Reincidências recentes (últimos N dias)
        recent_reincidences = [
            c for c in corrections
            if c.get("last_reincidence_at") and c["last_reincidence_at"] > cutoff
        ]

        # Agrupar por categoria
        by_category = {}
        for c in corrections:
            cat = c.get("categoria", "outro")
            by_category[cat] = by_category.get(cat, 0) + 1

        # Críticas reincidentes
        critical_reincident = [
            {
                "id": c["correction_id"],
                "categoria": c.get("categoria"),
                "reincidencia_count": c.get("reincidencia_count", 0),
                "regra": c.get("regra", "")[:100],
            }
            for c in corrections
            if c.get("severidade") == "critica" and c.get("reincidencia")
        ]

        return {
            "period_days": days,
            "total_active": len(corrections),
            "reincidences_last_period": len(recent_reincidences),
            "by_category": by_category,
            "critical_reincident": critical_reincident,
        }
    except Exception as e:
        print(f"[DB WARN] correction_analytics: {e}", flush=True)
        return {"error": str(e)}
