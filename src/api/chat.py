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
    rate_limiter,
    filter_output,
    hash_user_id,
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

        # ── Security: sanitization and injection detection ────────────────────
        message, warnings = sanitize_input(message)
        if warnings:
            log_security_event("INPUT_SANITIZED", hash_user_id(user_id), {"warnings": warnings})

        is_suspicious, patterns = check_injection_patterns(message)
        if is_suspicious:
            log_security_event("INJECTION_DETECTED", hash_user_id(user_id), {"patterns": patterns})
            print(f"[SECURITY] Injection pattern detectado de {hash_user_id(user_id)}", flush=True)

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

    # Sanitization and injection detection
    user_message, warnings = sanitize_input(user_message)
    if warnings:
        log_security_event("INPUT_SANITIZED", session_id, {"warnings": warnings, "source": "sandbox"})

    is_suspicious, patterns = check_injection_patterns(user_message)
    if is_suspicious:
        log_security_event("INJECTION_DETECTED", session_id, {"patterns": patterns, "source": "sandbox"})

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
    """Get conversation history for a session."""
    agent = _get_agent()
    session_id = request.args.get("session_id", "sandbox")
    return jsonify({"history": agent.memory.get(session_id)})


@bp.route("/sessions", methods=["GET"])
def sessions():
    """List all active sessions."""
    agent = _get_agent()
    return jsonify({"sessions": agent.memory.list_sessions()})
