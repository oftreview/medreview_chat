# gevent monkey-patch deve ser a PRIMEIRA coisa executada — antes de qualquer import.
# Converte I/O blocking (sockets, sleep, threading) em greenlets não-bloqueantes.
# Isso permite que uma única instância gunicorn atenda 500+ conexões simultâneas
# sem criar uma thread OS por conexão (que seria insustentável em escala).
from gevent import monkey
monkey.patch_all()

import sys
import os
import re
import random
import time
import threading
import gevent
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, request, jsonify, render_template, redirect
from agents.sales.agent import SalesAgent
from core.config import DEBUG, PORT
from core.whatsapp import send_message, parse_incoming
from core import database, escalation
from core.security import sanitize_input, check_injection_patterns, rate_limiter, filter_output, hash_user_id
from core.logger import log_security_event, log_conversation
from core.message_splitter import split_response, DELAY_SECONDS as MSG_DELAY

# ── Instala captura de logs para o dashboard ──────────────────────────────────
try:
    from core.log_buffer import install as install_log_capture
    install_log_capture()
except Exception:
    pass

HOST = os.getenv("HOST", "0.0.0.0")

# ── Comandos secretos de escalação manual ─────────────────────────────────────
# Palavras-chave que o operador pode digitar no chat para assumir/devolver
# o atendimento manualmente, sem precisar chamar a API /escalation/resolve.
# Match exato (case-insensitive, strip de espaços).

ESCALATE_COMMAND   = "#transferindo-para-atendimento-dedicado"
DEESCALATE_COMMAND = "#retorno-para-atendimento-agente"

ESCALATE_CONFIRM_MSG = (
    "Entendido! Estou transferindo você para um atendimento dedicado. "
    "Um especialista vai continuar a conversa por aqui. 😊"
)
DEESCALATE_CONFIRM_MSG = ""   # Silencioso — agente retoma sem aviso

# ── Configurações do endpoint /chat ───────────────────────────────────────────

# Tempo de espera (em segundos) antes de processar mensagens acumuladas.
# Se chegar nova mensagem do mesmo session_id dentro desse tempo, o timer reinicia.
RESPONSE_DELAY_SECONDS = int(os.getenv("RESPONSE_DELAY_SECONDS", "10"))

# Token de autenticação para o endpoint /chat (Bearer token).
# Se não configurado, autenticação fica desabilitada (útil para dev local).
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN", "")

# Mensagem de fallback enviada ao cliente quando Claude ou Supabase retorna erro.
# Retorna HTTP 200 para não bloquear o fluxo da Botmaker.
FALLBACK_MESSAGE = os.getenv(
    "FALLBACK_MESSAGE",
    "Estou com uma instabilidade agora, em breve um consultor vai te atender."
)

# ── Estado de debounce por session_id ─────────────────────────────────────────
# Estrutura: { session_id -> { messages, timer, event, result, channel, user_id } }
# O timer é indexado por session_id (identificador da Botmaker) para agrupar
# mensagens por sessão ativa. O user_id é mantido separado para histórico Supabase.
# IMPORTANTE: funciona em processo único. No Railway, configure:
#   WEB_CONCURRENCY=1  (ou use gunicorn --workers=1 --threads=8)
_chat_state: dict = {}
_chat_lock = threading.Lock()

# ── Estado de debounce para /webhook/zapi ─────────────────────────────────────
# Mesma lógica do /chat: acumula mensagens do mesmo telefone por RESPONSE_DELAY_SECONDS.
# Estrutura: { phone -> { messages: [], timer: Timer } }
_zapi_state: dict = {}
_zapi_lock = threading.Lock()

# ── App e agente ──────────────────────────────────────────────────────────────

app = Flask(__name__)
agent = SalesAgent()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_auth(req) -> bool:
    """Valida Bearer token. Se API_SECRET_TOKEN não configurado, sempre passa."""
    if not API_SECRET_TOKEN:
        return True
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {API_SECRET_TOKEN}"


def _check_secret_command(message: str, user_id: str) -> dict | None:
    """
    Verifica se a mensagem é um comando secreto de escalação/desescalação.

    Retorna dict com a resposta JSON pronta, ou None se não for comando.
    Match é case-insensitive e ignora espaços nas pontas.
    """
    normalized = message.strip().lower()

    if normalized == ESCALATE_COMMAND:
        # Escalar: marca sessão como "escalated", IA para de responder
        escalation.handle_escalation(user_id, agent.memory, agent=agent, motivo="comando_manual")
        print(f"[SECRET CMD] ESCALAÇÃO MANUAL ativada para uid={hash_user_id(user_id)}", flush=True)
        return {
            "response": ESCALATE_CONFIRM_MSG,
            "status": "escalated",
            "user_id": user_id,
            "command": "escalate",
        }

    if normalized == DEESCALATE_COMMAND:
        # Desescalar: devolve controle para a IA
        escalation.resolve_escalation(user_id, agent.memory)
        print(f"[SECRET CMD] DESESCALAÇÃO MANUAL ativada para uid={hash_user_id(user_id)}", flush=True)
        return {
            "response": DEESCALATE_CONFIRM_MSG,
            "status": "active",
            "user_id": user_id,
            "command": "deescalate",
        }

    return None


def _flush_and_respond(session_id: str):
    """
    Callback do timer de debounce.
    Processa todas as mensagens acumuladas para session_id e sinaliza a thread
    da requisição HTTP com o resultado.

    O timer é indexado por session_id (Botmaker), mas o histórico no Supabase
    usa user_id (telefone do lead) para manter continuidade entre sessões.
    """
    with _chat_lock:
        state = _chat_state.get(session_id)
        if not state:
            return
        messages = list(state["messages"])
        channel = state.get("channel", "api")
        user_id = state.get("user_id", session_id)

    # Combina mensagens acumuladas em uma única string
    combined = "\n".join(messages)
    uid_hash = hash_user_id(user_id)
    print(f"[FLUSH] Timer disparou! session={hash_user_id(session_id)} uid={uid_hash} msgs_acumuladas={len(messages)} canal={channel}", flush=True)
    print(f"[FLUSH] Mensagens combinadas: {combined[:200]}{'...' if len(combined) > 200 else ''}", flush=True)

    try:
        # Usa user_id como session_id do agente para que o histórico Supabase
        # fique indexado pelo identificador real do cliente
        result = agent.reply(combined, session_id=user_id)
        response_text = result["message"]

        # Filtrar output antes de enviar ao canal externo
        response_text, redactions = filter_output(response_text)
        if redactions:
            log_security_event("OUTPUT_FILTERED", hash_user_id(user_id), {"redactions": redactions})

        # Quebra em múltiplas mensagens curtas (1 a 3)
        response_parts = split_response(response_text)
        print(f"[CHAT API] Resposta dividida em {len(response_parts)} parte(s) uid={uid_hash}", flush=True)

        status = "success"
    except Exception as e:
        import traceback
        error_detail = f"{type(e).__name__}: {e}"
        print(f"[CHAT API] Erro ao processar session={hash_user_id(session_id)} uid={uid_hash}: {error_detail}", flush=True)
        traceback.print_exc()
        # No sandbox, mostra o erro real para debug. Em produção, mostra fallback genérico.
        if channel == "sandbox":
            response_parts = [f"[ERRO DEBUG] {error_detail}"]
        else:
            response_parts = [FALLBACK_MESSAGE]
        status = "error"

    # Sinaliza a thread da requisição com o resultado
    with _chat_lock:
        state = _chat_state.get(session_id)
        if state:
            state["result"] = {
                "session_id": session_id,
                "response": response_parts[0],           # Retrocompatível: primeira mensagem
                "responses": response_parts,              # Novo: array completo
                "delay_seconds": MSG_DELAY,               # Delay sugerido entre mensagens
                "user_id": user_id,
                "status": status,
            }
            state["event"].set()


# ── Rotas principais ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect("/dashboard/sandbox")


@app.route("/dashboard/sandbox")
def dashboard_sandbox():
    return render_template("dashboard/sandbox.html", active_page="sandbox")


@app.route("/dashboard/conversations")
def dashboard_conversations():
    return render_template("dashboard/conversations.html", active_page="conversations")


@app.route("/dashboard/corrections")
def dashboard_corrections():
    return render_template("dashboard/corrections.html", active_page="corrections")


@app.route("/dashboard/costs")
def dashboard_costs():
    return render_template("dashboard/costs.html", active_page="costs")


@app.route("/dashboard/analytics")
def dashboard_analytics():
    return render_template("dashboard/analytics.html", active_page="analytics")


@app.route("/dashboard/logs")
def dashboard_logs():
    return render_template("dashboard/logs.html", active_page="logs")


@app.route("/chat", methods=["POST"])
def chat():
    """
    Endpoint unificado.

    Modo API (canal externo — Botmaker, webchat, etc.):
      Payload: {
        "user_id":    "telefone do lead (OBRIGATÓRIO para Botmaker)",
        "message":    "mensagem do lead",
        "channel":    "botmaker | webchat | whatsapp | outro",
        "session_id": "identificador de sessão (OPCIONAL — se ausente, usa user_id)",
        "metadata":   {}
      }
      Ativado quando user_id OU session_id (≠ "sandbox") está presente.
      Requer header: Authorization: Bearer <API_SECRET_TOKEN>
      Aplica debounce de RESPONSE_DELAY_SECONDS para acumular mensagens rápidas.
      O timer de debounce é indexado por session_id (ou user_id se session_id ausente).
      O histórico no Supabase usa user_id (telefone do lead) para continuidade.
      Resposta: { "session_id": "...", "response": "...", "user_id": "...", "status": "success|error" }

    Modo sandbox (UI de chat interna):
      Payload: { "message": "...", "session_id": "sandbox" }
      Sem autenticação. Resposta: { "message": "...", "status": "..." }
    """
    data = request.get_json(silent=True) or {}

    # ── Detecta modo API vs sandbox ──────────────────────────────────────────
    # Modo API é ativado quando:
    #   1. session_id está presente e NÃO é "sandbox", OU
    #   2. user_id está presente (integração Botmaker envia apenas user_id)
    # Isso garante compatibilidade com a Botmaker, que envia { user_id, message }
    # sem session_id no payload.
    _has_session = "session_id" in data and data.get("session_id") != "sandbox"
    _has_user_id = "user_id" in data and (data.get("user_id") or "").strip()
    _is_api_mode = _has_session or _has_user_id

    if _is_api_mode:
        # Autenticação
        if not _check_auth(request):
            return jsonify({"error": "Unauthorized", "status": "error"}), 401

        message = (data.get("message") or "").strip()
        channel = data.get("channel", "api")

        # user_id é o identificador primário (telefone do lead).
        # session_id é opcional — se não vier, usa user_id como chave de debounce.
        user_id = (data.get("user_id") or "").strip()
        session_id = (data.get("session_id") or "").strip() or user_id

        if not session_id:
            return jsonify({"error": "user_id ou session_id é obrigatório", "status": "error"}), 400
        if not user_id:
            # Fallback: se veio session_id mas não user_id, usa session_id
            user_id = session_id
        if not message:
            return jsonify({"error": "message é obrigatório", "status": "error"}), 400

        # ── Comando secreto de escalação/desescalação ────────────────────────
        cmd_result = _check_secret_command(message, user_id)
        if cmd_result is not None:
            cmd_result["session_id"] = session_id
            return jsonify(cmd_result)

        # ── Checagem de sessão já escalada ────────────────────────────────────
        if escalation.is_escalated(user_id, agent.memory):
            print(f"[CHAT API] Sessão uid={hash_user_id(user_id)} em atendimento humano — IA pausada.", flush=True)
            return jsonify({
                "session_id": session_id,
                "response": "",
                "user_id": user_id,
                "status": "escalated_session",
            })

        # ── Segurança: rate limit (por session_id para evitar abuso por sessão) ─
        allowed, count = rate_limiter(session_id)
        if not allowed:
            log_security_event("RATE_LIMIT_EXCEEDED", hash_user_id(session_id), {"count": count})
            return jsonify({
                "session_id": session_id,
                "error": "Muitas mensagens. Aguarde um momento.",
                "status": "error",
            }), 429

        # ── Segurança: sanitização e detecção de injection ─────────────────────
        message, warnings = sanitize_input(message)
        if warnings:
            log_security_event("INPUT_SANITIZED", hash_user_id(user_id), {"warnings": warnings})

        is_suspicious, patterns = check_injection_patterns(message)
        if is_suspicious:
            log_security_event("INJECTION_DETECTED", hash_user_id(user_id), {"patterns": patterns})
            # Não bloqueia — deixa Claude recusar via system prompt (defesa em profundidade)
            # Mas registra para auditoria
            print(f"[SECURITY] Injection pattern detectado de {hash_user_id(user_id)}", flush=True)

        # ── Salva mensagem bruta ANTES do debounce (proteção contra perda) ───
        database.save_raw_incoming(user_id, message, channel=channel)

        # ── Debounce indexado por session_id ──────────────────────────────────
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
                }

            state = _chat_state[session_id]
            state["messages"].append(message)
            state["_waiters"] = state.get("_waiters", 0) + 1
            # Atualiza user_id caso venha em mensagem posterior
            if user_id != session_id:
                state["user_id"] = user_id

            # Reinicia o timer a cada mensagem recebida (debounce)
            # Usa gevent.spawn_later (nativo) em vez de threading.Timer
            # pois monkey.patch_all() pode causar disparo prematuro do Timer.
            if state["timer"] is not None:
                state["timer"].kill()

            state["event"].clear()
            state["result"] = None

            print(f"[DEBOUNCE] Msg acumulada session={hash_user_id(session_id)} total={len(state['messages'])} delay={RESPONSE_DELAY_SECONDS}s", flush=True)

            timer = gevent.spawn_later(RESPONSE_DELAY_SECONDS, _flush_and_respond, session_id)
            state["timer"] = timer

            event = state["event"]

        # Bloqueia a thread até o timer disparar e o processamento completar
        triggered = event.wait(timeout=RESPONSE_DELAY_SECONDS + 60)

        with _chat_lock:
            state = _chat_state.get(session_id, {})
            result = state.get("result")
            # Decrementa contador de threads esperando; última thread limpa o state
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
                "user_id": user_id,
                "status": "error",
            })

    # ── Modo sandbox: mesma lógica de debounce do API mode ──────────────────
    # Cada mensagem do frontend é um POST separado (simula WhatsApp real).
    # O backend acumula por RESPONSE_DELAY_SECONDS e processa tudo junto.
    user_message = (data.get("message") or "").strip()
    session_id = data.get("session_id", "sandbox")
    if not user_message:
        return jsonify({"error": "Mensagem vazia"}), 400

    # ── Comando secreto de escalação/desescalação (sem debounce) ─────────
    cmd_result = _check_secret_command(user_message, session_id)
    if cmd_result is not None:
        cmd_result["session_id"] = session_id
        cmd_result["message"] = cmd_result.pop("response", "")
        return jsonify(cmd_result)

    # Sanitização e injection detection
    user_message, warnings = sanitize_input(user_message)
    if warnings:
        log_security_event("INPUT_SANITIZED", session_id, {"warnings": warnings, "source": "sandbox"})

    is_suspicious, patterns = check_injection_patterns(user_message)
    if is_suspicious:
        log_security_event("INJECTION_DETECTED", session_id, {"patterns": patterns, "source": "sandbox"})

    # ── Salva mensagem bruta ANTES do debounce (proteção contra perda) ───
    database.save_raw_incoming(session_id, user_message, channel="sandbox")

    # ── Debounce (mesma lógica do API mode) ───────────────────────────────
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

        # Usa gevent.spawn_later (nativo) em vez de threading.Timer
        if state["timer"] is not None:
            state["timer"].kill()

        state["event"].clear()
        state["result"] = None

        print(f"[DEBOUNCE SANDBOX] Msg acumulada total={len(state['messages'])} delay={RESPONSE_DELAY_SECONDS}s", flush=True)

        timer = gevent.spawn_later(RESPONSE_DELAY_SECONDS, _flush_and_respond, session_id)
        state["timer"] = timer

        event = state["event"]

    # Bloqueia até o timer disparar e o processamento completar
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


@app.route("/reset", methods=["POST"])
def reset():
    data = request.get_json() or {}
    session_id = data.get("session_id", None)
    agent.reset(session_id)
    return jsonify({"status": "ok", "message": "Conversa reiniciada."})


@app.route("/history", methods=["GET"])
def history():
    session_id = request.args.get("session_id", "sandbox")
    return jsonify({"history": agent.memory.get(session_id)})


@app.route("/sessions", methods=["GET"])
def sessions():
    return jsonify({"sessions": agent.memory.list_sessions()})


# ── Webhooks WhatsApp (Z-API) ─────────────────────────────────────────────────


def _zapi_flush(phone: str):
    """
    Callback do timer de debounce do Z-API.
    Acumula mensagens do mesmo telefone, processa com o agente e envia
    resposta(s) com delay entre elas.
    """
    with _zapi_lock:
        state = _zapi_state.get(phone)
        if not state:
            return
        messages = list(state["messages"])
        # Limpa o estado para liberar novas mensagens
        _zapi_state.pop(phone, None)

    phone_hash = hash_user_id(phone)
    combined = "\n".join(messages)
    print(f"[ZAPI WEBHOOK] Processando uid={phone_hash} ({len(messages)} msg acumuladas)", flush=True)

    try:
        result = agent.reply(combined, session_id=phone)
        reply_text, redactions = filter_output(result["message"])
        if redactions:
            log_security_event("OUTPUT_FILTERED", hash_user_id(phone), {"redactions": redactions})

        if result.get("escalate"):
            motivo = result.get("lead_data", {}).get("motivo_escalacao", "nao_especificado")
            escalation.handle_escalation(
                phone, agent.memory, agent=agent, motivo=motivo
            )

        # Quebra em múltiplas mensagens e envia com delay entre elas
        parts = split_response(reply_text)
        print(f"[ZAPI WEBHOOK] Enviando {len(parts)} parte(s) uid={phone_hash} escalate={result.get('escalate')}", flush=True)

        for i, part in enumerate(parts):
            if i > 0:
                time.sleep(MSG_DELAY)
            ok = send_message(phone, part)
            print(f"[ZAPI WEBHOOK] Parte {i+1}/{len(parts)} enviada={ok} len={len(part)}", flush=True)

    except Exception as e:
        print(f"[ZAPI WEBHOOK] Erro ao processar uid={phone_hash}: {e}", flush=True)
        send_message(phone, FALLBACK_MESSAGE)


@app.route("/webhook/zapi", methods=["POST"])
def webhook_zapi():
    """
    Recebe mensagens do WhatsApp via Z-API e responde com o agente.
    Usa debounce para acumular mensagens rápidas do mesmo lead.
    """
    data = request.get_json(silent=True) or {}

    # Log sem PII — não imprime payload completo, telefone ou conteúdo da mensagem
    print(f"[ZAPI WEBHOOK] Payload recebido — type={data.get('type')} fromMe={data.get('fromMe')}", flush=True)

    incoming = parse_incoming(data)
    if not incoming:
        print(f"[ZAPI WEBHOOK] Ignorado — type={data.get('type')} fromMe={data.get('fromMe')}", flush=True)
        return jsonify({"status": "ignored"}), 200

    phone = incoming["phone"]
    message = incoming["message"]
    phone_hash = hash_user_id(phone)

    print(f"[ZAPI WEBHOOK] Recebido — uid={phone_hash} len={len(message)}", flush=True)

    # ── Segurança: rate limit ──────────────────────────────────────────────────
    allowed, _ = rate_limiter(phone)
    if not allowed:
        log_security_event("RATE_LIMIT_EXCEEDED", hash_user_id(phone), {"source": "zapi"})
        return jsonify({"status": "rate_limited"}), 200   # 200 para não gerar retry no Z-API

    # ── Segurança: sanitização e injection detection ───────────────────────────
    message, warnings = sanitize_input(message)
    if warnings:
        log_security_event("INPUT_SANITIZED", hash_user_id(phone), {"warnings": warnings})

    is_suspicious, patterns = check_injection_patterns(message)
    if is_suspicious:
        log_security_event("INJECTION_DETECTED", hash_user_id(phone), {"patterns": patterns, "source": "zapi"})
        print(f"[SECURITY] Injection detectado no WhatsApp de {hash_user_id(phone)}", flush=True)

    # ── Comando secreto de escalação/desescalação (sem debounce) ──────────
    cmd_result = _check_secret_command(message, phone)
    if cmd_result is not None:
        confirm_msg = cmd_result.get("response", "")
        if confirm_msg:
            send_message(phone, confirm_msg)
        print(f"[ZAPI WEBHOOK] Comando secreto '{cmd_result['command']}' uid={phone_hash}", flush=True)
        return jsonify({"status": cmd_result["status"]}), 200

    # ── Sessão escalada — IA pausada ──────────────────────────────────────
    if escalation.is_escalated(phone, agent.memory):
        print(f"[ZAPI WEBHOOK] Sessão uid={phone_hash} em atendimento humano — IA pausada.", flush=True)
        return jsonify({"status": "escalated_session"}), 200

    # ── Salva mensagem bruta ANTES do debounce (proteção contra perda) ───
    database.save_raw_incoming(phone, message, channel="whatsapp")

    # ── Debounce: acumula mensagens por RESPONSE_DELAY_SECONDS ────────────
    with _zapi_lock:
        if phone not in _zapi_state:
            _zapi_state[phone] = {"messages": [], "timer": None}

        state = _zapi_state[phone]
        state["messages"].append(message)

        # Reinicia o timer a cada mensagem (gevent nativo)
        if state["timer"] is not None:
            state["timer"].kill()

        print(f"[DEBOUNCE ZAPI] Msg acumulada uid={phone_hash} total={len(state['messages'])} delay={RESPONSE_DELAY_SECONDS}s", flush=True)

        timer = gevent.spawn_later(RESPONSE_DELAY_SECONDS, _zapi_flush, phone)
        state["timer"] = timer

    # Retorna 200 imediatamente — resposta será enviada pelo _zapi_flush
    return jsonify({"status": "queued"}), 200


# ── Rate limiter específico para /webhook/form (por IP, mais agressivo) ──────
FORM_MAX_PER_MINUTE = int(os.getenv("FORM_RATE_LIMIT", "5"))
_form_rate_store: dict = {}
_form_rate_lock = threading.Lock()

# Regex para validar telefone brasileiro (DDI 55 + DDD 2 dígitos + 8-9 dígitos)
_PHONE_RE = re.compile(r"^55\d{10,11}$")


def _form_rate_limiter(ip: str) -> tuple:
    """Rate limit por IP para /webhook/form — 5 req/min por padrão."""
    now = time.time()
    window_start = now - 60
    with _form_rate_lock:
        _form_rate_store[ip] = [ts for ts in _form_rate_store.get(ip, []) if ts > window_start]
        count = len(_form_rate_store[ip])
        if count >= FORM_MAX_PER_MINUTE:
            return False, count
        _form_rate_store[ip].append(now)
        return True, count + 1


def _normalize_phone(raw: str) -> str:
    """Remove caracteres não-numéricos e adiciona DDI 55 se ausente."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = digits[1:]  # remove zero à esquerda (0XX)
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


@app.route("/webhook/form", methods=["POST"])
def webhook_form():
    """
    Recebe lead do Quill Forms e inicia conversa no WhatsApp.

    SEM autenticação por Bearer token — o Quill Forms não suporta headers
    customizados de forma confiável. A proteção é feita por:
      1. Rate limit agressivo por IP (5 req/min)
      2. Validação rigorosa do telefone (formato brasileiro)
      3. Nenhum dado sensível é exposto no response

    Rate limit: FORM_RATE_LIMIT req/min por IP (padrão 5).
    Valida formato de telefone brasileiro (55 + DDD + 8-9 dígitos).
    """
    # ── Rate limit por IP (proteção principal sem auth) ───────────────────────
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    allowed, count = _form_rate_limiter(client_ip)
    if not allowed:
        log_security_event("FORM_RATE_LIMIT", client_ip, {"count": count})
        return jsonify({"error": "Muitas requisições. Tente novamente em instantes.", "status": "error"}), 429

    data = request.get_json(silent=True) or {}

    phone_raw = (
        data.get("phone") or data.get("celular") or
        data.get("telefone") or data.get("whatsapp") or ""
    ).strip()

    name = (
        data.get("name") or data.get("nome") or
        data.get("primeiro_nome") or "Lead"
    ).strip()

    if not phone_raw:
        return jsonify({"error": "Campo 'phone' não encontrado no payload", "status": "error"}), 400

    # ── Normalização e validação do telefone ─────────────────────────────────
    phone = _normalize_phone(phone_raw)
    if not _PHONE_RE.match(phone):
        log_security_event("FORM_INVALID_PHONE", client_ip, {"raw": phone_raw[:20]})
        return jsonify({"error": "Formato de telefone inválido. Use DDI + DDD + número.", "status": "error"}), 400

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

    agent.memory.add(phone, "user", f"[NOVO LEAD] Nome: {name}. Agente: {agent_name}.", channel="whatsapp")
    agent.memory.add(phone, "assistant", opening, channel="whatsapp")

    sent = send_message(phone, opening)
    if not sent:
        print(f"[FORM WEBHOOK] FALHA ao enviar mensagem Z-API uid={hash_user_id(phone)}", flush=True)

    return jsonify({"status": "ok", "phone": phone, "message_sent": sent}), 200


# ── Escalação humana ──────────────────────────────────────────────────────────

@app.route("/escalation/resolve", methods=["POST"])
def escalation_resolve():
    """Devolve o controle da conversa para a IA após atendimento humano."""
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    resolution = data.get("resolution", "").strip() or None
    if not phone:
        return jsonify({"error": "Campo 'phone' obrigatório"}), 400

    escalation.resolve_escalation(phone, agent.memory, resolution=resolution)
    return jsonify({"status": "ok", "message": f"Sessão {phone[:8]}... retornada para IA."}), 200


@app.route("/leads/escalated", methods=["GET"])
def leads_escalated():
    """Lista sessões atualmente em atendimento humano."""
    escalated = [
        s for s in agent.memory.list_sessions()
        if agent.memory.get_status(s) == "escalated"
    ]
    return jsonify({"escalated": escalated, "count": len(escalated)}), 200


# ── API: Escalações (Fase 2) ────────────────────────────────────────────────

@app.route("/api/escalations", methods=["GET"])
def api_escalations():
    """
    Lista escalações do banco de dados.
    Query params: status (pending|resolved), limit (default 50)
    """
    status_filter = request.args.get("status", None)
    limit = int(request.args.get("limit", 50))
    escalations = database.list_escalations(status=status_filter, limit=limit)
    return jsonify({"escalations": escalations, "count": len(escalations)}), 200


@app.route("/api/lead/<user_id>", methods=["GET"])
def api_lead_data(user_id):
    """
    Retorna metadados coletados de um lead (funnel_stage, especialidade, etc).
    Busca primeiro em memória (agent), depois no banco.
    """
    # Tenta dados em memória (mais recentes)
    lead_data = agent.get_lead_data(user_id)

    # Se não tem em memória, busca no banco
    if not lead_data:
        lead_data = database.get_lead_metadata(user_id)

    return jsonify({
        "user_id": user_id,
        "lead_data": lead_data,
        "source": "memory" if agent.get_lead_data(user_id) else "database",
    }), 200


# ── API: Correções do Agente (Fase 4 — Supabase + cache JSON local) ──────────

import json

_CORRECTIONS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "corrections.json")


def _load_corrections_json():
    """Carrega corrections do JSON local (cache/fallback)."""
    try:
        with open(_CORRECTIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("corrections", data) if isinstance(data, dict) else data
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_corrections_json(corrections):
    """Salva corrections no JSON local (cache)."""
    os.makedirs(os.path.dirname(_CORRECTIONS_PATH), exist_ok=True)
    with open(_CORRECTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump({"corrections": corrections}, f, ensure_ascii=False, indent=2)


def _sync_json_to_supabase():
    """Sync one-way: envia todas as correções do JSON local para o Supabase."""
    corrections = _load_corrections_json()
    synced = 0
    for c in corrections:
        if database.save_correction(c):
            synced += 1
    return synced


@app.route("/api/corrections", methods=["GET"])
def api_corrections_list():
    """
    Lista correções. Tenta Supabase primeiro, fallback para JSON local.
    Query params: source (supabase|json|auto), include_archived (true|false)
    """
    source = request.args.get("source", "auto")
    include_archived = request.args.get("include_archived", "false").lower() == "true"

    if source == "json":
        return jsonify({"corrections": _load_corrections_json(), "source": "json"})

    # Tenta Supabase
    db_corrections = database.load_corrections(include_archived=include_archived)
    if db_corrections:
        return jsonify({"corrections": db_corrections, "source": "supabase"})

    # Fallback para JSON
    return jsonify({"corrections": _load_corrections_json(), "source": "json_fallback"})


@app.route("/api/corrections", methods=["POST"])
def api_corrections_add():
    """
    Adiciona/atualiza uma correção. Salva no Supabase E no JSON local.
    Campos opcionais: conversation_user_id, conversation_message_id (para linkar com conversa original)
    """
    data = request.get_json(silent=True) or {}
    corr_id = data.get("id", "").strip()
    regra = data.get("regra", "").strip()
    if not corr_id or not regra:
        return jsonify({"error": "id e regra sao obrigatorios"}), 400

    new_corr = {
        "id": corr_id,
        "gatilho": data.get("gatilho", ""),
        "resposta_errada": data.get("resposta_errada", ""),
        "resposta_correta": data.get("resposta_correta", ""),
        "regra": regra,
        "categoria": data.get("categoria", "outro"),
        "severidade": data.get("severidade", "alta"),
        "status": data.get("status", "ativa"),
        "reincidencia": data.get("reincidencia", False),
        "reincidencia_count": data.get("reincidencia_count", 0),
    }

    # Link com conversa original (opcional)
    if data.get("conversation_user_id"):
        new_corr["conversation_user_id"] = data["conversation_user_id"]
    if data.get("conversation_message_id"):
        new_corr["conversation_message_id"] = data["conversation_message_id"]

    # Salva no Supabase
    db_ok = database.save_correction(new_corr)

    # Salva no JSON local (cache)
    corrections = _load_corrections_json()
    idx = next((i for i, c in enumerate(corrections) if c.get("id") == corr_id), None)
    if idx is not None:
        corrections[idx].update(new_corr)
    else:
        corrections.append(new_corr)
    _save_corrections_json(corrections)

    return jsonify({"status": "ok", "correction": new_corr, "supabase_synced": db_ok})


@app.route("/api/corrections/reincidence", methods=["POST"])
def api_corrections_reincidence():
    """
    Registra reincidência de uma correção.
    Payload: { "id": "COR-003" }
    """
    data = request.get_json(silent=True) or {}
    corr_id = data.get("id", "").strip()
    if not corr_id:
        return jsonify({"error": "id obrigatório"}), 400

    ok = database.increment_reincidence(corr_id)
    return jsonify({"status": "ok" if ok else "error", "correction_id": corr_id})


@app.route("/api/corrections/sync", methods=["POST"])
def api_corrections_sync():
    """
    Sync manual: envia todas as correções do JSON local para o Supabase.
    Útil para migração inicial.
    """
    synced = _sync_json_to_supabase()
    return jsonify({"status": "ok", "synced": synced})


@app.route("/api/corrections/auto-archive", methods=["POST"])
def api_corrections_auto_archive():
    """
    Arquiva correções sem reincidência nos últimos N dias.
    Query param: days (default 30)
    """
    days = int(request.args.get("days", 30))
    archived = database.auto_archive_corrections(days=days)
    return jsonify({"status": "ok", "archived": archived, "period_days": days})


@app.route("/api/corrections/analytics", methods=["GET"])
def api_corrections_analytics():
    """
    Análise de erros dos últimos N dias.
    Query param: days (default 7)
    Retorna: total ativas, reincidências por categoria, críticas reincidentes.
    """
    days = int(request.args.get("days", 7))
    analytics = database.correction_analytics(days=days)
    return jsonify(analytics)


# ── API: Analytics Avançado (Fase 5) ─────────────────────────────────────────

@app.route("/api/analytics/funnel", methods=["GET"])
def api_analytics_funnel():
    """
    Funil de conversão: quantos leads em cada stage, taxa de avanço e conversão.
    """
    return jsonify(database.analytics_funnel()), 200


@app.route("/api/analytics/time-per-stage", methods=["GET"])
def api_analytics_time_per_stage():
    """Tempo médio que leads ficam em cada stage do funil."""
    return jsonify(database.analytics_time_per_stage()), 200


@app.route("/api/analytics/keywords", methods=["GET"])
def api_analytics_keywords():
    """
    Palavras-chave mais frequentes nas mensagens dos leads.
    Query param: limit (default 30)
    """
    limit = int(request.args.get("limit", 30))
    return jsonify(database.analytics_keywords(limit=limit)), 200


@app.route("/api/analytics/quality", methods=["GET"])
def api_analytics_quality():
    """
    Score de qualidade das conversas (engajamento, profundidade, equilíbrio, progresso).
    Query param: user_id (opcional — se fornecido, analisa só esse lead)
    """
    user_id = request.args.get("user_id", None)
    return jsonify(database.analytics_conversation_quality(user_id=user_id)), 200


@app.route("/api/analytics/summary", methods=["GET"])
def api_analytics_summary():
    """
    Resumo geral: funil + qualidade + keywords + correções em um só endpoint.
    Ideal para o dashboard.
    """
    funnel = database.analytics_funnel()
    quality = database.analytics_conversation_quality()
    keywords = database.analytics_keywords(limit=10)
    corrections = database.correction_analytics(days=7)

    return jsonify({
        "funnel": funnel,
        "quality": {
            "avg_score": quality.get("avg_quality_score", 0),
            "total_conversations": quality.get("total_conversations", 0),
        },
        "top_keywords": keywords.get("keywords", [])[:10],
        "corrections_7d": corrections,
    }), 200


# ── API: Métricas e Configuração ─────────────────────────────────────────────

from core.config import CLAUDE_MODEL, MAX_TOKENS


@app.route("/api/metrics", methods=["GET"])
def api_metrics():
    """Retorna métricas de uso da API (tokens, custos, cache)."""
    try:
        from core.metrics import get_metrics
        metrics = get_metrics()
    except ImportError:
        metrics = {
            "model": CLAUDE_MODEL,
            "max_tokens": MAX_TOKENS,
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_read": 0,
            "total_cache_write": 0,
            "total_cost": 0,
            "recent_calls": [],
        }
    return jsonify({"metrics": metrics})


@app.route("/api/config", methods=["POST"])
def api_config_update():
    """Atualiza modelo e max_tokens em runtime (sem reiniciar servidor)."""
    import core.config as cfg
    data = request.get_json(silent=True) or {}
    if "model" in data:
        cfg.CLAUDE_MODEL = data["model"]
        print(f"[CONFIG] Modelo alterado para: {cfg.CLAUDE_MODEL}", flush=True)
    if "max_tokens" in data:
        cfg.MAX_TOKENS = int(data["max_tokens"])
        print(f"[CONFIG] Max tokens alterado para: {cfg.MAX_TOKENS}", flush=True)
    return jsonify({"status": "ok", "model": cfg.CLAUDE_MODEL, "max_tokens": cfg.MAX_TOKENS})


# ── API: Logs ────────────────────────────────────────────────────────────────

@app.route("/api/logs", methods=["GET"])
def api_logs():
    """Retorna logs recentes do sistema."""
    try:
        from core.log_buffer import get_logs
        since = int(request.args.get("since", 0))
        logs = get_logs(since=since)
    except ImportError:
        logs = []
    return jsonify({"logs": logs})


# ── API: HubSpot (Fase 3) ────────────────────────────────────────────────────

@app.route("/api/hubspot/status", methods=["GET"])
def api_hubspot_status():
    """Retorna status da integração HubSpot (habilitado, conectado, mapeamento)."""
    from core import hubspot
    return jsonify(hubspot.get_status()), 200


@app.route("/api/hubspot/sync/<user_id>", methods=["POST"])
def api_hubspot_sync(user_id):
    """
    Sync manual de um lead para o HubSpot.
    Útil para reprocessar leads que falharam ou forçar atualização.
    """
    from core import hubspot
    if not hubspot.is_enabled():
        return jsonify({"error": "HubSpot não habilitado", "status": "error"}), 400

    # Busca dados do lead
    lead_data = agent.get_lead_data(user_id)
    if not lead_data:
        lead_data = database.get_lead_metadata(user_id) or {}

    funnel_stage = lead_data.get("stage", lead_data.get("funnel_stage", "abertura"))

    result = hubspot.sync_lead(
        phone=user_id,
        funnel_stage=funnel_stage,
        lead_data=lead_data,
    )
    return jsonify({"status": "ok", "hubspot": result}), 200


@app.route("/api/hubspot/mapping", methods=["GET", "POST"])
def api_hubspot_mapping():
    """
    GET: retorna mapeamento atual de stages Closi AI → HubSpot.
    POST: atualiza mapeamento customizado.
    Payload: { "abertura": "qualifiedtobuy", "fechamento": "closedwon", ... }
    """
    from core import hubspot
    if request.method == "GET":
        return jsonify({"mapping": hubspot._get_stage_map()}), 200

    data = request.get_json(silent=True) or {}
    hubspot.set_stage_mapping(data)
    return jsonify({"status": "ok", "mapping": hubspot._get_stage_map()}), 200


# ── Health checks ─────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.0"})


@app.route("/health/hubspot", methods=["GET"])
def health_hubspot():
    """Testa conexão com o HubSpot."""
    from core import hubspot
    status = hubspot.get_status()
    code = 200 if status["connected"] else (200 if not status["enabled"] else 500)
    return jsonify(status), code


@app.route("/health/security", methods=["GET"])
def health_security():
    """Retorna últimos 20 eventos de segurança. Use para monitoramento."""
    from core.logger import get_recent_events
    events = get_recent_events(20)
    return jsonify({"status": "ok", "recent_events": events, "count": len(events)}), 200


@app.route("/health/db", methods=["GET"])
def health_db():
    """Testa conexão real com o Supabase (leitura + escrita + delete)."""
    result = database.health_check()
    status_code = 200 if result["connected"] else (200 if not result["enabled"] else 500)
    return jsonify(result), status_code


@app.route("/health/memory", methods=["GET"])
def health_memory():
    """Retorna estatísticas de memória e persistência."""
    return jsonify({
        "status": "ok",
        "memory": agent.memory.db_stats(),
        "db_connection": database.get_connection_status(),
    }), 200


if __name__ == "__main__":
    print(f"\n🟣 Closi AI rodando em http://{HOST}:{PORT}\n")
    # use_reloader=False: o reloader do werkzeug monitora a stdlib inteira no
    # Windows e reinicia o processo no meio do debounce do /chat, fazendo o
    # fetch do cliente cair com "Failed to fetch". Debugger continua ativo.
    app.run(host=HOST, debug=DEBUG, use_reloader=False, port=PORT)
