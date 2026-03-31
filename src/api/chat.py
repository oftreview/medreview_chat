"""
src/api/chat.py — Chat endpoint with debounce logic.
Handles both API mode (Botmaker, webhooks) and sandbox mode (internal UI).
Uses gevent for non-blocking timers with debounce accumulation.
"""
import os
import threading
import gevent
from flask import Blueprint, request, jsonify

from src.config import (
    API_SECRET_TOKEN,
    RESPONSE_DELAY_SECONDS,
    FALLBACK_MESSAGE,
    ESCALATE_COMMAND,
    DEESCALATE_COMMAND,
    ESCALATE_CONFIRM_MSG,
    DEESCALATE_CONFIRM_MSG,
)
from src.core import database, escalation
from src.core.security import (
    sanitize_input,
    check_injection_patterns,
    check_data_extraction,
    check_media_attachment,
    rate_limiter,
    filter_output,
    hash_user_id,
    record_injection_strike,
    is_user_blocked,
    INJECTION_BLOCK_RESPONSE,
)
from src.core.logger import log_security_event
from src.core.message_splitter import split_response, DELAY_SECONDS as MSG_DELAY

bp = Blueprint("chat", __name__)

# ── Lazy singleton agent ──────────────────────────────────────────────────────
_agent = None


def _get_agent():
    """Get or create the SalesAgent singleton."""
    global _agent
    if _agent is None:
        from src.agent.sales_agent import SalesAgent
        _agent = SalesAgent()
    return _agent


# ── Debounce state for /chat and /reset ──────────────────────────────────────
# Indexed by session_id. Stores accumulated messages, timers, and results.
_chat_state: dict = {}
_chat_lock = threading.Lock()


def _check_auth(req) -> bool:
    """
    Validate Bearer token. If API_SECRET_TOKEN not configured, always passes.
    """
    if not API_SECRET_TOKEN:
        return True
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {API_SECRET_TOKEN}"


def _check_secret_command(message: str, user_id: str) -> dict | None:
    """
    Check if message is a secret escalation/deescalation command.
    Returns response dict or None if not a command.
    Match is case-insensitive and ignores whitespace.
    """
    agent = _get_agent()
    normalized = message.strip().lower()

    if normalized == ESCALATE_COMMAND:
        # Escalate: mark session as escalated, AI stops responding
        escalation.handle_escalation(
            user_id, agent.memory, agent=agent, motivo="comando_manual"
        )
        print(
            f"[SECRET CMD] ESCALAÇÃO MANUAL ativada para uid={hash_user_id(user_id)}",
            flush=True,
        )
        return {
            "response": ESCALATE_CONFIRM_MSG,
            "status": "escalated",
            "user_id": user_id,
            "command": "escalate",
        }

    if normalized == DEESCALATE_COMMAND:
        # Deescalate: return control to AI
        escalation.resolve_escalation(user_id, agent.memory)
        print(
            f"[SECRET CMD] DESESCALAÇÃO MANUAL ativada para uid={hash_user_id(user_id)}",
            flush=True,
        )
        return {
            "response": DEESCALATE_CONFIRM_MSG,
            "status": "active",
            "user_id": user_id,
            "command": "deescalate",
        }

    return None


def _flush_and_respond(session_id: str):
    """
    Debounce timer callback.
    Processes accumulated messages and signals HTTP thread with result.
    Uses agent.reply() and splits response into multiple parts.
    """
    agent = _get_agent()

    with _chat_lock:
        state = _chat_state.get(session_id)
        if not state:
            return
        messages = list(state["messages"])
        channel = state.get("channel", "api")
        user_id = state.get("user_id", session_id)

    # Combine all accumulated messages
    combined = "\n".join(messages)
    uid_hash = hash_user_id(user_id)
    print(
        f"[FLUSH] Timer disparou! session={hash_user_id(session_id)} uid={uid_hash} msgs_acumuladas={len(messages)} canal={channel}",
        flush=True,
    )
    print(
        f"[FLUSH] Mensagens combinadas: {combined[:200]}{'...' if len(combined) > 200 else ''}",
        flush=True,
    )

    try:
        # Use user_id as agent session_id for Supabase history continuity
        result = agent.reply(combined, session_id=user_id)
        response_text = result["message"]

        # Filter output before sending to external channel
        response_text, redactions = filter_output(response_text)
        if redactions:
            log_security_event("OUTPUT_FILTERED", hash_user_id(user_id), {"redactions": redactions})

        # Split into multiple short messages (1-3 parts)
        response_parts = split_response(response_text)
        print(
            f"[CHAT API] Resposta dividida em {len(response_parts)} parte(s) uid={uid_hash}",
            flush=True,
        )

        status = "success"
    except Exception as e:
        import traceback
        error_detail = f"{type(e).__name__}: {e}"
        print(
            f"[CHAT API] Erro ao processar session={hash_user_id(session_id)} uid={uid_hash}: {error_detail}",
            flush=True,
        )
        traceback.print_exc()
        # In sandbox, show real error. In production, show fallback.
        if channel == "sandbox":
            response_parts = [f"[ERRO DEBUG] {error_detail}"]
        else:
            response_parts = [FALLBACK_MESSAGE]
        status = "error"

    # Signal the HTTP thread with result
    with _chat_lock:
        state = _chat_state.get(session_id)
        if state:
            state["result"] = {
                "session_id": session_id,
                "response": response_parts[0],  # Backwards compat: first message
                "responses": response_parts,  # New: full array
                "delay_seconds": MSG_DELAY,
                "user_id": user_id,
                "status": status,
            }
            state["event"].set()


@bp.route("/chat", methods=["POST"])
def chat():
    """
    Unified chat endpoint supporting both API and sandbox modes.

    API mode (external channels — Botmaker, webchat):
      - Payload: { "user_id": "...", "message": "...", "channel": "...", "session_id": "..." }
      - Requires: Authorization: Bearer <API_SECRET_TOKEN>
      - Uses debounce with timer indexed by session_id
      - Applies security checks: rate limit, sanitization, injection detection
      - Response: { "session_id": "...", "response": "...", "responses": [...], "user_id": "...", "status": "..." }

    Sandbox mode (internal UI):
      - Payload: { "message": "...", "session_id": "sandbox" }
      - No auth required
      - Response: { "session_id": "...", "response": "...", "responses": [...], "status": "..." }
    """
    data = request.get_json(silent=True) or {}

    # ── Detect API mode vs sandbox mode ───────────────────────────────────────
    # Channels that indicate external API requests (never fall to sandbox)
    _EXTERNAL_CHANNELS = {"botmaker", "api", "webchat", "whatsapp", "zapi"}

    _has_session = "session_id" in data and data.get("session_id") != "sandbox"
    _has_user_id = "user_id" in data and (data.get("user_id") or "").strip()
    _raw_channel = (data.get("channel") or "").strip().lower()
    _has_external_channel = _raw_channel in _EXTERNAL_CHANNELS
    _is_api_mode = _has_session or _has_user_id or _has_external_channel

    # ── Diagnostic logging for integration debugging ──────────────────────────
    if _has_external_channel or _has_user_id:
        print(
            f"[CHAT RECV] channel={_raw_channel} "
            f"has_user_id={_has_user_id} "
            f"has_session={_has_session} "
            f"has_ext_channel={_has_external_channel} "
            f"api_mode={_is_api_mode} "
            f"user_id_raw={(data.get('user_id') or '')[:20]}...",
            flush=True,
        )

    if _is_api_mode:
        # ── API mode with authentication ─────────────────────────────────────
        if not _check_auth(request):
            return jsonify({"error": "Unauthorized", "status": "error"}), 401

        message = (data.get("message") or "").strip()
        channel = data.get("channel", "api")
        user_id = (data.get("user_id") or "").strip()
        session_id = (data.get("session_id") or "").strip() or user_id

        if not session_id:
            # ── Guard: external channel without any identifier → reject ────
            # This prevents Botmaker requests with empty user_id from
            # silently falling through and sharing a single session.
            if _has_external_channel:
                print(
                    f"[CHAT API] BLOQUEADO: canal externo '{channel}' sem user_id. "
                    f"Payload keys: {list(data.keys())}",
                    flush=True,
                )
                return (
                    jsonify({
                        "error": (
                            f"user_id é obrigatório para canal '{channel}'. "
                            "Verifique se o campo user_id está sendo enviado no payload. "
                            "Use contact.platformContactId ou contact.whatsApp como user_id."
                        ),
                        "status": "error",
                        "debug_hint": "MISSING_USER_ID",
                    }),
                    400,
                )
            return (
                jsonify({"error": "user_id ou session_id é obrigatório", "status": "error"}),
                400,
            )
        if not user_id:
            user_id = session_id
        if not message:
            return jsonify({"error": "message é obrigatório", "status": "error"}), 400

        # ── Check for secret escalation commands ──────────────────────────────
        agent = _get_agent()
        cmd_result = _check_secret_command(message, user_id)
        if cmd_result is not None:
            cmd_result["session_id"] = session_id
            return jsonify(cmd_result)

        # ── Check if session already escalated ────────────────────────────────
        if escalation.is_escalated(user_id, agent.memory):
            print(
                f"[CHAT API] Sessão uid={hash_user_id(user_id)} em atendimento humano — IA pausada.",
                flush=True,
            )
            return jsonify({
                "session_id": session_id,
                "response": "",
                "user_id": user_id,
                "status": "escalated_session",
            })

        # ── Security: check if user is blocked (injection strikes) ──────────
        if is_user_blocked(user_id):
            uid_hash = hash_user_id(user_id)
            log_security_event("USER_BLOCKED", uid_hash, {"reason": "injection_strikes"})
            print(f"[SECURITY] Usuário BLOQUEADO por injection strikes uid={uid_hash}", flush=True)
            return jsonify({
                "session_id": session_id,
                "response": INJECTION_BLOCK_RESPONSE,
                "responses": [INJECTION_BLOCK_RESPONSE],
                "user_id": user_id,
                "status": "success",
            })

        # ── Security: rate limit ─────────────────────────────────────────────
        allowed, count = rate_limiter(session_id)
        if not allowed:
            log_security_event("RATE_LIMIT_EXCEEDED", hash_user_id(session_id), {"count": count})
            return (
                jsonify({
                    "session_id": session_id,
                    "error": "Muitas mensagens. Aguarde um momento.",
                    "status": "error",
                }),
                429,
            )

        # ── Security: sanitization ───────────────────────────────────────────
        message, warnings = sanitize_input(message)
        if warnings:
            log_security_event("INPUT_SANITIZED", hash_user_id(user_id), {"warnings": warnings})

        # Block dangerous HTML tags (script, iframe, etc.)
        if "DANGEROUS_HTML_TAG" in warnings:
            uid_hash = hash_user_id(user_id)
            log_security_event("DANGEROUS_HTML_BLOCKED", uid_hash, {"warnings": warnings})
            record_injection_strike(user_id)
            print(f"[SECURITY] HTML perigoso BLOQUEADO uid={uid_hash}", flush=True)
            return jsonify({
                "session_id": session_id,
                "response": INJECTION_BLOCK_RESPONSE,
                "responses": [INJECTION_BLOCK_RESPONSE],
                "user_id": user_id,
                "status": "success",
            })

        # ── Security: injection detection (BLOCK, not just log) ──────────────
        is_suspicious, patterns = check_injection_patterns(message)
        if is_suspicious:
            uid_hash = hash_user_id(user_id)
            log_security_event("INJECTION_DETECTED", uid_hash, {"patterns": patterns})
            blocked, strikes = record_injection_strike(user_id)
            print(
                f"[SECURITY] Injection BLOQUEADO uid={uid_hash} "
                f"patterns={patterns[:3]} strikes={strikes}",
                flush=True,
            )
            return jsonify({
                "session_id": session_id,
                "response": INJECTION_BLOCK_RESPONSE,
                "responses": [INJECTION_BLOCK_RESPONSE],
                "user_id": user_id,
                "status": "success",
            })

        # ── Security: data extraction detection ──────────────────────────────
        is_extraction, extraction_patterns = check_data_extraction(message)
        if is_extraction:
            uid_hash = hash_user_id(user_id)
            log_security_event("DATA_EXTRACTION_ATTEMPT", uid_hash, {"patterns": extraction_patterns})
            record_injection_strike(user_id)
            print(
                f"[SECURITY] Tentativa de extração de dados BLOQUEADA uid={uid_hash} "
                f"patterns={extraction_patterns[:3]}",
                flush=True,
            )
            return jsonify({
                "session_id": session_id,
                "response": INJECTION_BLOCK_RESPONSE,
                "responses": [INJECTION_BLOCK_RESPONSE],
                "user_id": user_id,
                "status": "success",
            })

        # ── Security: malicious media/file detection ─────────────────────────
        is_blocked_media, block_reason, media_warnings = check_media_attachment(message)
        if is_blocked_media:
            uid_hash = hash_user_id(user_id)
            log_security_event("MALICIOUS_MEDIA_BLOCKED", uid_hash, {"reason": block_reason, "warnings": media_warnings})
            print(f"[SECURITY] Mídia maliciosa BLOQUEADA uid={uid_hash}: {block_reason}", flush=True)
            return jsonify({
                "session_id": session_id,
                "response": INJECTION_BLOCK_RESPONSE,
                "responses": [INJECTION_BLOCK_RESPONSE],
                "user_id": user_id,
                "status": "success",
            })
        if media_warnings:
            log_security_event("MEDIA_WARNING", hash_user_id(user_id), {"warnings": media_warnings})

        # ── Save raw message before debounce ─────────────────────────────────
        database.save_raw_incoming(user_id, message, channel=channel)

        # ── Debounce indexed by session_id ────────────────────────────────────
        with _chat_lock:
            if session_id not in _chat_state:
                _chat_state[session_id] = {
                    "messages": [],
                    "timer": None,
                    "event": threading.Event(),
                    "result": None,
                    "channel": channel,
                    "user_id": user_id,
                    "_waiters": 0,
                    "_waiter_seq": 0,       # Sequência incremental de waiters
                    "_primary_waiter": 0,   # Qual waiter é o primário (último a resetar timer)
                }

            state = _chat_state[session_id]
            state["messages"].append(message)
            state["_waiters"] = state.get("_waiters", 0) + 1
            state["_waiter_seq"] = state.get("_waiter_seq", 0) + 1
            my_waiter_id = state["_waiter_seq"]
            state["_primary_waiter"] = my_waiter_id  # Último a entrar é o primário
            if user_id != session_id:
                state["user_id"] = user_id

            # Restart timer (gevent.spawn_later for non-blocking)
            if state["timer"] is not None:
                state["timer"].kill()

            state["event"].clear()
            state["result"] = None

            print(
                f"[DEBOUNCE] Msg acumulada session={hash_user_id(session_id)} total={len(state['messages'])} delay={RESPONSE_DELAY_SECONDS}s",
                flush=True,
            )

            timer = gevent.spawn_later(RESPONSE_DELAY_SECONDS, _flush_and_respond, session_id)
            state["timer"] = timer

            event = state["event"]

        # Block until timer fires and processing completes
        triggered = event.wait(timeout=RESPONSE_DELAY_SECONDS + 60)

        with _chat_lock:
            state = _chat_state.get(session_id, {})
            result = state.get("result")
            is_primary = (my_waiter_id == state.get("_primary_waiter", 0))
            # Decrement waiters and cleanup when last one exits
            if state:
                state["_waiters"] = state.get("_waiters", 1) - 1
                if state["_waiters"] <= 0:
                    _chat_state.pop(session_id, None)

        # Only the primary waiter (last request that reset the timer) gets the real response.
        # Earlier waiters get a "debounced" status so Botmaker ignores them.
        if not is_primary:
            print(
                f"[DEBOUNCE] Waiter secundário descartado session={hash_user_id(session_id)} waiter={my_waiter_id}",
                flush=True,
            )
            return jsonify({
                "session_id": session_id,
                "response": "",
                "responses": [],
                "user_id": user_id,
                "status": "debounced",
            })

        if triggered and result:
            return jsonify(result)
        else:
            return jsonify({
                "session_id": session_id,
                "response": FALLBACK_MESSAGE,
                "user_id": user_id,
                "status": "error",
            })

    # ── Sandbox mode (no auth, same debounce logic) ──────────────────────────
    user_message = (data.get("message") or "").strip()
    session_id = data.get("session_id", "sandbox")
    if not user_message:
        return jsonify({"error": "Mensagem vazia"}), 400

    # Check for secret commands (no debounce)
    cmd_result = _check_secret_command(user_message, session_id)
    if cmd_result is not None:
        cmd_result["session_id"] = session_id
        cmd_result["message"] = cmd_result.pop("response", "")
        return jsonify(cmd_result)

    # Sanitization and security checks (sandbox mode — log but don't block)
    user_message, warnings = sanitize_input(user_message)
    if warnings:
        log_security_event("INPUT_SANITIZED", session_id, {"warnings": warnings, "source": "sandbox"})

    is_suspicious, patterns = check_injection_patterns(user_message)
    if is_suspicious:
        log_security_event("INJECTION_DETECTED", session_id, {"patterns": patterns, "source": "sandbox"})
        print(f"[SECURITY SANDBOX] Injection detectado (não bloqueado em sandbox): {patterns[:3]}", flush=True)

    # Save raw message before debounce
    database.save_raw_incoming(session_id, user_message, channel="sandbox")

    # ── Debounce (same logic as API mode) ────────────────────────────────────
    with _chat_lock:
        if session_id not in _chat_state:
            _chat_state[session_id] = {
                "messages": [],
                "timer": None,
                "event": threading.Event(),
                "result": None,
                "channel": "sandbox",
                "user_id": session_id,
                "_waiters": 0,
            }

        state = _chat_state[session_id]
        state["messages"].append(user_message)
        state["_waiters"] = state.get("_waiters", 0) + 1

        if state["timer"] is not None:
            state["timer"].kill()

        state["event"].clear()
        state["result"] = None

        print(
            f"[DEBOUNCE SANDBOX] Msg acumulada total={len(state['messages'])} delay={RESPONSE_DELAY_SECONDS}s",
            flush=True,
        )

        timer = gevent.spawn_later(RESPONSE_DELAY_SECONDS, _flush_and_respond, session_id)
        state["timer"] = timer

        event = state["event"]

    triggered = event.wait(timeout=RESPONSE_DELAY_SECONDS + 60)

    with _chat_lock:
        state = _chat_state.get(session_id, {})
        result = state.get("result")
        if result:
            state["_waiters"] = state.get("_waiters", 1) - 1
            if state["_waiters"] <= 0:
                _chat_state.pop(session_id, None)

    if triggered and result:
        return jsonify(result)
    else:
        return jsonify({
            "session_id": session_id,
            "response": FALLBACK_MESSAGE,
            "status": "error",
        })


@bp.route("/reset", methods=["POST"])
def reset():
    """Reset conversation history for a session."""
    agent = _get_agent()
    data = request.get_json() or {}
    session_id = data.get("session_id", None)
    agent.reset(session_id)
    return jsonify({"status": "ok", "message": "Conversa reiniciada."})


@bp.route("/history", methods=["GET"])
def history():
    """
    Get conversation history for a session.
    Tries multiple sources: DB conversations table, DB messages table (legacy), in-memory.
    """
    session_id = request.args.get("session_id", "sandbox")

    # 1. Tenta tabela conversations (fonte primária, persistente)
    db_history = database.load_conversation_history(session_id, limit=50)
    if db_history:
        return jsonify({"history": db_history})

    # 2. Tenta tabela messages legada
    legacy_history = database.load_messages_legacy(session_id)
    if legacy_history:
        return jsonify({"history": legacy_history})

    # 3. Fallback: memória in-memory (sessões ativas não persistidas)
    agent = _get_agent()
    return jsonify({"history": agent.memory.get(session_id)})


@bp.route("/sessions", methods=["GET"])
def sessions():
    """
    List all sessions — from database (persistent) + in-memory (active).
    Database is the primary source; in-memory adds any sessions not yet in DB.

    Query params:
        date_from: ISO date (e.g., "2026-03-01")
        date_to: ISO date (e.g., "2026-03-31")
        limit: max sessions (default 100)
    """
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    limit = int(request.args.get("limit", 100))

    # Fonte primária: banco de dados (sobrevive a deploys)
    db_sessions = database.list_sessions_from_db(
        limit=limit, date_from=date_from, date_to=date_to
    )

    # Fonte secundária: memória (sessões ativas que podem não estar no DB ainda)
    # Só adiciona se não tiver filtro de data (memória não tem timestamp)
    if not date_from and not date_to:
        agent = _get_agent()
        memory_sessions = set(agent.memory.list_sessions())
        db_ids = {s["session_id"] for s in db_sessions}

        for sid in memory_sessions:
            if sid not in db_ids and sid != "sandbox":
                db_sessions.append({
                    "session_id": sid,
                    "channel": "memory",
                    "last_message": "",
                    "last_activity": "",
                    "message_count": 0,
                    "is_sandbox": False,
                })

    return jsonify({"sessions": db_sessions})
