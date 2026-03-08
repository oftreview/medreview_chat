"""
Módulo de persistência com Supabase.
Se as variáveis SUPABASE_URL / SUPABASE_KEY não estiverem configuradas,
o módulo opera em modo desabilitado (sem erros) e o app continua funcionando.
"""
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_client = None


def _get_client():
    """Inicializa o cliente Supabase (lazy, singleton)."""
    global _client
    if _client is not None:
        return _client

    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[DB] Supabase conectado.", flush=True)
    except Exception as e:
        print(f"[DB] Erro ao conectar Supabase: {e}", flush=True)
        _client = None

    return _client


# ── Leads ─────────────────────────────────────────────────────────────────────

def upsert_lead(phone: str, name: str = None, source: str = "form", status: str = "active"):
    """Cria ou atualiza um lead pelo telefone."""
    db = _get_client()
    if db is None:
        return

    try:
        db.table("leads").upsert(
            {"phone": phone, "name": name, "source": source, "status": status},
            on_conflict="phone"
        ).execute()
    except Exception as e:
        print(f"[DB] Erro ao salvar lead {phone}: {e}", flush=True)


def update_lead_status(phone: str, status: str):
    """Atualiza o status de um lead (active | escalated | closed)."""
    db = _get_client()
    if db is None:
        return

    try:
        db.table("leads").update({"status": status}).eq("phone", phone).execute()
    except Exception as e:
        print(f"[DB] Erro ao atualizar status do lead {phone}: {e}", flush=True)


# ── Mensagens ─────────────────────────────────────────────────────────────────

def save_message(phone: str, role: str, content: str):
    """Salva uma mensagem no histórico."""
    db = _get_client()
    if db is None:
        return

    try:
        db.table("messages").insert(
            {"phone": phone, "role": role, "content": content}
        ).execute()
    except Exception as e:
        print(f"[DB] Erro ao salvar mensagem de {phone}: {e}", flush=True)


def load_messages(phone: str) -> list:
    """
    Carrega o histórico de mensagens de um lead do Supabase.
    Retorna lista no formato [{"role": "user"/"assistant", "content": "..."}].
    """
    db = _get_client()
    if db is None:
        return []

    try:
        result = (
            db.table("messages")
            .select("role, content")
            .eq("phone", phone)
            .order("created_at", desc=False)
            .execute()
        )
        return result.data or []
    except Exception as e:
        print(f"[DB] Erro ao carregar mensagens de {phone}: {e}", flush=True)
        return []


def is_enabled() -> bool:
    """Retorna True se o Supabase está configurado."""
    return bool(SUPABASE_URL and SUPABASE_KEY)
