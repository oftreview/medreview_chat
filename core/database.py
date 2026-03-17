"""
Módulo de persistência com Supabase.
Se as variáveis SUPABASE_URL / SUPABASE_KEY não estiverem configuradas,
o módulo opera em modo desabilitado (sem erros) e o app continua funcionando.

FASE 1 — Erros visíveis + tabela unificada (conversations)
- Todas as funções retornam status (True/False ou dados/None) para que o caller saiba se deu certo.
- Erros são logados com tag [DB ERROR] para aparecer no dashboard de logs.
- Tabela `messages` está deprecada — tudo usa `conversations`.
"""
import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_client = None
_connection_error = None


def _get_client():
    """Inicializa o cliente Supabase (lazy, singleton)."""
    global _client, _connection_error
    if _client is not None:
        return _client

    if not SUPABASE_URL or not SUPABASE_KEY:
        _connection_error = "SUPABASE_URL ou SUPABASE_KEY não configurados"
        return None

    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        _connection_error = None
        print("[DB] Supabase conectado.", flush=True)
    except Exception as e:
        _connection_error = str(e)
        print(f"[DB ERROR] Falha ao conectar Supabase: {e}", flush=True)
        _client = None

    return _client


def get_connection_status() -> dict:
    """Retorna status da conexão para health checks."""
    return {
        "enabled": is_enabled(),
        "connected": _client is not None,
        "error": _connection_error,
    }


# ── Leads ─────────────────────────────────────────────────────────────────────

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


# ── Conversations (tabela unificada) ──────────────────────────────────────────
# Todas as mensagens (API, sandbox, WhatsApp) são salvas aqui.
# Campos: id, user_id, session_id, role, content, channel, message_type, created_at

def save_message(user_id: str, role: str, content: str,
                 channel: str = None, session_id: str = None,
                 message_type: str = "conversation") -> bool:
    """
    Salva uma mensagem na tabela conversations.
    Retorna True se salvou com sucesso, False se falhou.

    Params:
        user_id: identificador do lead (telefone ou sandbox ID)
        role: "user" ou "assistant"
        content: texto da mensagem
        channel: "whatsapp" | "sandbox" | "api" | "botmaker"
        session_id: UUID da sessão (agrupa mensagens de uma mesma conversa)
        message_type: "conversation" | "incoming_raw" | "system"
    """
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] save_message falhou — DB não conectado (user={user_id[:8]}...)", flush=True)
        return False

    try:
        row = {
            "user_id": user_id,
            "role": role,
            "content": content,
            "channel": channel,
            "message_type": message_type,
        }
        if session_id:
            row["session_id"] = session_id

        db.table("conversations").insert(row).execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] save_message user={user_id[:8]}... role={role}: {e}", flush=True)
        return False


def save_raw_incoming(user_id: str, content: str, channel: str = None,
                      session_id: str = None) -> bool:
    """
    Salva mensagem bruta do lead ANTES do debounce.
    Garante que nenhuma mensagem seja perdida mesmo se o servidor cair
    durante o período de debounce.
    """
    return save_message(
        user_id=user_id,
        role="user",
        content=content,
        channel=channel,
        session_id=session_id,
        message_type="incoming_raw",
    )


def load_conversation_history(user_id: str, limit: int = 20,
                              session_id: str = None) -> list:
    """
    Carrega as últimas `limit` mensagens de um user_id.
    Filtra apenas message_type='conversation' (ignora incoming_raw).
    Retorna lista cronológica: [{"role": "...", "content": "..."}].
    """
    db = _get_client()
    if db is None:
        print(f"[DB ERROR] load_conversation_history falhou — DB não conectado", flush=True)
        return []

    try:
        query = (
            db.table("conversations")
            .select("role, content")
            .eq("user_id", user_id)
            .eq("message_type", "conversation")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if session_id:
            query = query.eq("session_id", session_id)

        result = query.execute()
        return list(reversed(result.data or []))
    except Exception as e:
        print(f"[DB ERROR] load_conversation_history user={user_id[:8]}...: {e}", flush=True)
        return []


# ── Sessões ───────────────────────────────────────────────────────────────────

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


# ── Legado (deprecado — usar save_message) ────────────────────────────────────

def save_message_legacy(phone: str, role: str, content: str) -> bool:
    """DEPRECADO: Salva na tabela messages (legada). Use save_message()."""
    db = _get_client()
    if db is None:
        return False

    try:
        db.table("messages").insert(
            {"phone": phone, "role": role, "content": content}
        ).execute()
        return True
    except Exception as e:
        print(f"[DB ERROR] save_message_legacy phone={phone[:6]}***: {e}", flush=True)
        return False


def load_messages_legacy(phone: str) -> list:
    """DEPRECADO: Carrega da tabela messages (legada). Use load_conversation_history()."""
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
        print(f"[DB ERROR] load_messages_legacy phone={phone[:6]}***: {e}", flush=True)
        return []


# ── Health Check ──────────────────────────────────────────────────────────────

def health_check() -> dict:
    """
    Testa conexão real com o Supabase: leitura + escrita + delete.
    Retorna dict com status detalhado.
    """
    result = {
        "enabled": is_enabled(),
        "connected": False,
        "read": False,
        "write": False,
        "delete": False,
        "error": None,
        "latency_ms": None,
    }

    if not is_enabled():
        result["error"] = "SUPABASE_URL ou SUPABASE_KEY não configurados"
        return result

    db = _get_client()
    if db is None:
        result["error"] = _connection_error or "Cliente não inicializado"
        return result

    import time
    start = time.time()

    # Teste de escrita
    test_id = f"_healthcheck_{uuid.uuid4().hex[:8]}"
    try:
        db.table("conversations").insert({
            "user_id": test_id,
            "role": "system",
            "content": "health_check_probe",
            "message_type": "system",
            "channel": "healthcheck",
        }).execute()
        result["write"] = True
    except Exception as e:
        result["error"] = f"Write failed: {e}"
        result["latency_ms"] = round((time.time() - start) * 1000)
        return result

    # Teste de leitura
    try:
        read_result = (
            db.table("conversations")
            .select("user_id")
            .eq("user_id", test_id)
            .limit(1)
            .execute()
        )
        result["read"] = len(read_result.data or []) > 0
    except Exception as e:
        result["error"] = f"Read failed: {e}"

    # Cleanup — remove o registro de teste
    try:
        db.table("conversations").delete().eq("user_id", test_id).execute()
        result["delete"] = True
    except Exception as e:
        result["error"] = f"Delete failed: {e}"

    result["connected"] = result["read"] and result["write"]
    result["latency_ms"] = round((time.time() - start) * 1000)

    return result


def is_enabled() -> bool:
    """Retorna True se o Supabase está configurado."""
    return bool(SUPABASE_URL and SUPABASE_KEY)
