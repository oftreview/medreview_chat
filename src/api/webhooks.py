"""
src/api/webhooks.py — WhatsApp and Form webhooks.
Handles Z-API WhatsApp messages and Quill Forms submissions.
Uses gevent debounce to batch rapid messages.
"""
import os
import re
import random
import time
import threading
import gevent
from flask import Blueprint, request, jsonify

from src.config import (
    RESPONSE_DELAY_SECONDS,
    FALLBACK_MESSAGE,
    FORM_RATE_LIMIT,
)
from src.core.whatsapp import send_message, parse_incoming
from src.core.security import (
    sanitize_input,
    check_injection_patterns,
    rate_limiter,
    filter_output,
    hash_user_id,
)
from src.core.logger import log_security_event
from src.core.message_splitter import split_response, DELAY_SECONDS as MSG_DELAY
from src.core import database, escalation
from src.api.chat import _get_agent

bp = Blueprint("webhooks", __name__)

# ── Z-API WhatsApp debounce state ────────────────────────────────────────────
_zapi_state: dict = {}
_zapi_lock = threading.Lock()


def _zapi_flush(phone: str):
    """
    Z-API debounce timer callback.
    Accumulates messages from same phone, processes with agent, sends responses with delay.
    """
    agent = _get_agent()

    with _zapi_lock:
        state = _zapi_state.get(phone)
        if not state:
            return
        messages = list(state["messages"])
        _zapi_state.pop(phone, None)

    phone_hash = hash_user_id(phone)
    combined = "\n".join(messages)
    print(
        f"[ZAPI WEBHOOK] Processando uid={phone_hash} ({len(messages)} msg acumuladas)",
        flush=True,
    )

    try:
        result = agent.reply(combined, session_id=phone)
        reply_text, redactions = filter_output(result["message"])
        if redactions:
            log_security_event("OUTPUT_FILTERED", hash_user_id(phone), {"redactions": redactions})

        if result.get("escalate"):
            motivo = result.get("lead_data", {}).get("motivo_escalacao", "nao_especificado")
            escalation.handle_escalation(phone, agent.memory, agent=agent, motivo=motivo)

        # Split and send with delay between parts
        parts = split_response(reply_text)
        print(
            f"[ZAPI WEBHOOK] Enviando {len(parts)} parte(s) uid={phone_hash} escalate={result.get('escalate')}",
            flush=True,
        )

        for i, part in enumerate(parts):
            if i > 0:
                time.sleep(MSG_DELAY)
            ok = send_message(phone, part)
            print(
                f"[ZAPI WEBHOOK] Parte {i+1}/{len(parts)} enviada={ok} len={len(part)}",
                flush=True,
            )

    except Exception as e:
        print(f"[ZAPI WEBHOOK] Erro ao processar uid={phone_hash}: {e}", flush=True)
        send_message(phone, FALLBACK_MESSAGE)


@bp.route("/webhook/zapi", methods=["POST"])
def webhook_zapi():
    """
    WhatsApp webhook via Z-API.
    Receives messages and responds using debounce to batch rapid messages.
    """
    agent = _get_agent()
    data = request.get_json(silent=True) or {}

    # Log without PII
    print(
        f"[ZAPI WEBHOOK] Payload recebido — type={data.get('type')} fromMe={data.get('fromMe')}",
        flush=True,
    )

    incoming = parse_incoming(data)
    if not incoming:
        print(
            f"[ZAPI WEBHOOK] Ignorado — type={data.get('type')} fromMe={data.get('fromMe')}",
            flush=True,
        )
        return jsonify({"status": "ignored"}), 200

    phone = incoming["phone"]
    message = incoming["message"]
    phone_hash = hash_user_id(phone)

    print(f"[ZAPI WEBHOOK] Recebido — uid={phone_hash} len={len(message)}", flush=True)

    # ── Security: rate limit ─────────────────────────────────────────────────
    allowed, _ = rate_limiter(phone)
    if not allowed:
        log_security_event("RATE_LIMIT_EXCEEDED", hash_user_id(phone), {"source": "zapi"})
        return jsonify({"status": "rate_limited"}), 200

    # ── Security: sanitization and injection detection ────────────────────────
    message, warnings = sanitize_input(message)
    if warnings:
        log_security_event("INPUT_SANITIZED", hash_user_id(phone), {"warnings": warnings})

    is_suspicious, patterns = check_injection_patterns(message)
    if is_suspicious:
        log_security_event("INJECTION_DETECTED", hash_user_id(phone), {"patterns": patterns, "source": "zapi"})
        print(f"[SECURITY] Injection detectado no WhatsApp de {hash_user_id(phone)}", flush=True)

    # ── Check for secret commands (no debounce) ──────────────────────────────
    from src.api.chat import _check_secret_command
    cmd_result = _check_secret_command(message, phone)
    if cmd_result is not None:
        confirm_msg = cmd_result.get("response", "")
        if confirm_msg:
            send_message(phone, confirm_msg)
        print(f"[ZAPI WEBHOOK] Comando secreto '{cmd_result['command']}' uid={phone_hash}", flush=True)
        return jsonify({"status": cmd_result["status"]}), 200

    # ── Check if session escalated ───────────────────────────────────────────
    if escalation.is_escalated(phone, agent.memory):
        print(
            f"[ZAPI WEBHOOK] Sessão uid={phone_hash} em atendimento humano — IA pausada.",
            flush=True,
        )
        return jsonify({"status": "escalated_session"}), 200

    # ── Save raw message before debounce ─────────────────────────────────────
    database.save_raw_incoming(phone, message, channel="whatsapp")

    # ── Debounce: accumulate messages ────────────────────────────────────────
    with _zapi_lock:
        if phone not in _zapi_state:
            _zapi_state[phone] = {"messages": [], "timer": None}

        state = _zapi_state[phone]
        state["messages"].append(message)

        if state["timer"] is not None:
            state["timer"].kill()

        print(
            f"[DEBOUNCE ZAPI] Msg acumulada uid={phone_hash} total={len(state['messages'])} delay={RESPONSE_DELAY_SECONDS}s",
            flush=True,
        )

        timer = gevent.spawn_later(RESPONSE_DELAY_SECONDS, _zapi_flush, phone)
        state["timer"] = timer

    # Return immediately — response sent by _zapi_flush
    return jsonify({"status": "queued"}), 200


# ── Form webhook rate limiting ──────────────────────────────────────────────
FORM_MAX_PER_MINUTE = int(os.getenv("FORM_RATE_LIMIT", "5"))
_form_rate_store: dict = {}
_form_rate_lock = threading.Lock()

# Regex for Brazilian phone validation (DDI 55 + DDD 2 digits + 8-9 digits)
_PHONE_RE = re.compile(r"^55\d{10,11}$")


def _form_rate_limiter(ip: str) -> tuple:
    """Rate limit per IP for /webhook/form — default 5 req/min."""
    now = time.time()
    window_start = now - 60
    with _form_rate_lock:
        _form_rate_store[ip] = [
            ts for ts in _form_rate_store.get(ip, []) if ts > window_start
        ]
        count = len(_form_rate_store[ip])
        if count >= FORM_MAX_PER_MINUTE:
            return False, count
        _form_rate_store[ip].append(now)
        return True, count + 1


def _normalize_phone(raw: str) -> str:
    """Remove non-numeric chars and add DDI 55 if absent."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = digits[1:]  # Remove leading zero
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


@bp.route("/webhook/form", methods=["POST"])
def webhook_form():
    """
    Quill Forms webhook.
    Receives lead data and initiates WhatsApp conversation.
    Uses IP-based rate limiting (5 req/min) as main protection.
    """
    agent = _get_agent()

    # ── Rate limit per IP ────────────────────────────────────────────────────
    client_ip = (
        request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
        .split(",")[0]
        .strip()
    )
    allowed, count = _form_rate_limiter(client_ip)
    if not allowed:
        log_security_event("FORM_RATE_LIMIT", client_ip, {"count": count})
        return (
            jsonify({
                "error": "Muitas requisições. Tente novamente em instantes.",
                "status": "error",
            }),
            429,
        )

    data = request.get_json(silent=True) or {}

    phone_raw = (
        data.get("phone")
        or data.get("celular")
        or data.get("telefone")
        or data.get("whatsapp")
        or ""
    ).strip()

    name = (
        data.get("name")
        or data.get("nome")
        or data.get("primeiro_nome")
        or "Lead"
    ).strip()

    if not phone_raw:
        return (
            jsonify({
                "error": "Campo 'phone' não encontrado no payload",
                "status": "error",
            }),
            400,
        )

    # ── Normalize and validate phone ─────────────────────────────────────────
    phone = _normalize_phone(phone_raw)
    if not _PHONE_RE.match(phone):
        log_security_event("FORM_INVALID_PHONE", client_ip, {"raw": phone_raw[:20]})
        return (
            jsonify({
                "error": "Formato de telefone inválido. Use DDI + DDD + número.",
                "status": "error",
            }),
            400,
        )

    print(f"[FORM WEBHOOK] Novo lead uid={hash_user_id(phone)} ip={client_ip}", flush=True)

    database.upsert_lead(phone=phone, name=name, source="form")

    agent_name = random.choice(["Pedro", "Sofia"])
    first_name = name.split()[0] if name and name != "Lead" else ""

    opening = (
        f"Olá, {first_name}, tudo bem? "
        f"Aqui é {agent_name}, do time comercial da Med-Review! "
        f"Vi que preencheu nosso formulário para saber mais sobre os preparatórios, certo?\n\n"
        f"Posso te enviar as informações por aqui? ☺️"
    )

    agent.memory.add(
        phone, "user", f"[NOVO LEAD] Nome: {name}. Agente: {agent_name}.", channel="whatsapp"
    )
    agent.memory.add(phone, "assistant", opening, channel="whatsapp")

    sent = send_message(phone, opening)
    if not sent:
        print(
            f"[FORM WEBHOOK] FALHA ao enviar mensagem Z-API uid={hash_user_id(phone)}",
            flush=True,
        )

    return jsonify({"status": "ok", "phone": phone, "message_sent": sent}), 200
