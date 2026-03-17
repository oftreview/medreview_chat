"""
Lead management + sessions.
Handles lead creation, status updates, metadata, and session management.
"""
import uuid
from datetime import datetime, timezone
from .client import _get_client


def upsert_lead(phone: str, name: str = None, source: str = "form", status: str = "active") -> bool:
    """Cria ou atualiza um lead pelo telefone. Retorna True se salvou com sucesso."""
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] upsert_lead falhou — DB não conectado", flush=True)
        return False

    try:
        db.table("leads").upsert(
            {"phone": phone, "name": name, "source": source, "status": status},
            on_conflict="phone"
        ).execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] upsert_lead phone={phone[:6]}***: {e}", flush=True)
        return False


def update_lead_status(phone: str, status: str) -> bool:
    """Atualiza o status de um lead (active | escalated | closed). Retorna True se salvou."""
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] update_lead_status falhou — DB não conectado", flush=True)
        return False

    try:
        db.table("leads").update({"status": status}).eq("phone", phone).execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] update_lead_status phone={phone[:6]}***: {e}", flush=True)
        return False


def save_lead_metadata(user_id: str, metadata: dict) -> bool:
    """
    Salva/atualiza metadados do lead (funnel_stage, especialidade, prova, etc).
    Faz upsert na tabela lead_metadata por user_id.
    """
    db = _get_client()
    if db is None:
        return False

    try:
        row = {"user_id": user_id}
        # Mapeia campos conhecidos
        field_map = {
            "stage": "funnel_stage",
            "especialidade": "especialidade",
            "prova": "prova_alvo",
            "ano_prova": "ano_prova",
            "ja_estuda": "ja_estuda",
            "plataforma_atual": "plataforma_atual",
        }
        for meta_key, db_key in field_map.items():
            if meta_key in metadata and metadata[meta_key] is not None:
                row[db_key] = metadata[meta_key]

        db.table("lead_metadata").upsert(row, on_conflict="user_id").execute()
        return True
    except Exception as e:
        print(f"[DB WARN] save_lead_metadata user={user_id[:8]}...: {e}", flush=True)
        return False


def get_lead_metadata(user_id: str) -> dict:
    """Carrega metadados do lead do banco."""
    db = _get_client()
    if db is None:
        return {}

    try:
        result = (
            db.table("lead_metadata")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return {}
    except Exception as e:
        print(f"[DB WARN] get_lead_metadata: {e}", flush=True)
        return {}


def generate_session_id() -> str:
    """Gera um UUID v4 para identificar uma sessão de conversa."""
    return str(uuid.uuid4())


def create_session(user_id: str, channel: str = None) -> str:
    """
    Cria uma nova sessão no banco e retorna o session_id (UUID).
    Se o DB não estiver disponível, retorna o UUID mesmo assim (funciona em memória).
    """
    session_id = generate_session_id()
    db = _get_client()
    if db is None:
        print(f"[DB WARN] create_session — DB não conectado, sessão {session_id[:8]} criada só em memória", flush=True)
        return session_id

    try:
        db.table("sessions").insert({
            "id": session_id,
            "user_id": user_id,
            "channel": channel,
            "status": "active",
        }).execute()
        print(f"[DB] Sessão criada: {session_id[:8]}... user={user_id[:8]}...", flush=True)
    except Exception as e:
        # Tabela sessions pode não existir ainda — não bloqueia
        print(f"[DB WARN] create_session falhou (tabela pode não existir): {e}", flush=True)

    return session_id


def update_session_status(session_id: str, status: str) -> bool:
    """Atualiza status de uma sessão (active | escalated | closed)."""
    db = _get_client()
    if db is None:
        return False

    try:
        db.table("sessions").update({
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session_id).execute()
        return True
    except Exception as e:
        print(f"[DB WARN] update_session_status: {e}", flush=True)
        return False
