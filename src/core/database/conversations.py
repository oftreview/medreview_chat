"""
CRUD messages + legacy functions.
Handles conversations, incoming raw messages, and conversation history.
"""
from .client import _get_client


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


def list_sessions_from_db(limit: int = 100, date_from: str = None, date_to: str = None) -> list:
    """
    Lista sessões únicas do banco de dados com metadados.
    Retorna sessões ordenadas pela última atividade (mais recente primeiro).

    Args:
        limit: máximo de sessões a retornar
        date_from: filtro de data início (ISO format, ex: "2026-03-01")
        date_to: filtro de data fim (ISO format, ex: "2026-03-31")

    Cada item: {
        "session_id": user_id,
        "channel": str,
        "last_message": str (preview),
        "last_activity": str (ISO timestamp),
        "message_count": int,
    }
    """
    db = _get_client()
    if db is None:
        print("[DB ERROR] list_sessions_from_db — DB não conectado", flush=True)
        return []

    try:
        # Busca mensagens recentes — NÃO filtra por message_type para não perder
        # dados antigos que podem não ter esse campo preenchido
        query = (
            db.table("conversations")
            .select("user_id, channel, content, role, created_at, message_type")
            .order("created_at", desc=True)
            .limit(5000)
        )

        # Filtros de data
        if date_from:
            query = query.gte("created_at", f"{date_from}T00:00:00")
        if date_to:
            query = query.lte("created_at", f"{date_to}T23:59:59")

        result = query.execute()

        if not result.data:
            print(f"[DB] list_sessions_from_db: 0 mensagens encontradas", flush=True)
            return []

        print(f"[DB] list_sessions_from_db: {len(result.data)} mensagens carregadas", flush=True)

        # Agrupa por user_id
        sessions_map = {}
        for row in result.data:
            uid = row.get("user_id", "")
            if not uid:
                continue
            # Ignora healthcheck probes
            if uid.startswith("_healthcheck_"):
                continue

            if uid not in sessions_map:
                sessions_map[uid] = {
                    "session_id": uid,
                    "channel": row.get("channel") or "api",
                    "last_message": "",
                    "last_activity": row.get("created_at", ""),
                    "message_count": 0,
                    "is_sandbox": uid == "sandbox",
                }
            # Conta apenas mensagens de conversa (não incoming_raw que são duplicatas)
            msg_type = row.get("message_type", "conversation")
            if msg_type != "incoming_raw":
                sessions_map[uid]["message_count"] += 1

            # A primeira ocorrência de mensagem do lead (mais recente) = preview
            if not sessions_map[uid]["last_message"] and row.get("role") == "user":
                content = row.get("content", "")
                sessions_map[uid]["last_message"] = content[:80] if content else ""

        # Ordena por última atividade (mais recente primeiro)
        sessions_list = sorted(
            sessions_map.values(),
            key=lambda s: s.get("last_activity", ""),
            reverse=True,
        )

        print(f"[DB] list_sessions_from_db: {len(sessions_list)} sessões únicas", flush=True)
        return sessions_list[:limit]

    except Exception as e:
        print(f"[DB ERROR] list_sessions_from_db: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return []


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
