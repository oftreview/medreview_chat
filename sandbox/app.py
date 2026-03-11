# gevent monkey-patch deve ser a PRIMEIRA coisa executada — antes de qualquer import.
# Converte I/O blocking (sockets, sleep, threading) em greenlets não-bloqueantes.
# Isso permite que uma única instância gunicorn atenda 500+ conexões simultâneas
# sem criar uma thread OS por conexão (que seria insustentável em escala).
from gevent import monkey
monkey.patch_all()

import sys
import os
import random
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, request, jsonify, render_template
from agents.sales.agent import SalesAgent
from core.config import DEBUG, PORT
from core.whatsapp import send_message, parse_incoming
from core import database, escalation
from core.security import sanitize_input, check_injection_patterns, rate_limiter, filter_output, hash_user_id
from core.logger import log_security_event, log_conversation
from core import followup as followup_manager

HOST = os.getenv("HOST", "0.0.0.0")

# ── Configurações do endpoint /chat ───────────────────────────────────────────

# Tempo de espera (em segundos) antes de processar mensagens acumuladas.
# Se chegar nova mensagem do mesmo user_id dentro desse tempo, o timer reinicia.
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

# ── Estado de debounce por user_id ────────────────────────────────────────────
# Estrutura: { user_id -> { messages, timer, event, result, channel } }
# IMPORTANTE: funciona em processo único. No Railway, configure:
#   WEB_CONCURRENCY=1  (ou use gunicorn --workers=1 --threads=8)
_chat_state: dict = {}
_chat_lock = threading.Lock()

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


def _flush_and_respond(user_id: str):
    """
    Callback do timer de debounce.
    Processa todas as mensagens acumuladas para user_id e sinaliza a thread
    da requisição HTTP com o resultado.
    """
    with _chat_lock:
        state = _chat_state.get(user_id)
        if not state:
            return
        messages = list(state["messages"])
        channel = state.get("channel", "api")

    # Combina mensagens acumuladas em uma única string
    combined = "\n".join(messages)
    print(f"[CHAT API] Processando {user_id} ({len(messages)} msg) canal={channel}", flush=True)

    try:
        result = agent.reply(combined, session_id=user_id)
        response_text = result["message"]

        # Filtrar output antes de enviar ao canal externo
        response_text, redactions = filter_output(response_text)
        if redactions:
            log_security_event("OUTPUT_FILTERED", hash_user_id(user_id), {"redactions": redactions})

        status = "success"
    except Exception as e:
        print(f"[CHAT API] Erro ao processar {user_id}: {e}", flush=True)
        response_text = FALLBACK_MESSAGE
        status = "error"

    # Sinaliza a thread da requisição com o resultado
    with _chat_lock:
        state = _chat_state.get(user_id)
        if state:
            state["result"] = {
                "response": response_text,
                "user_id": user_id,
                "status": status,
            }
            state["event"].set()


# ── Rotas principais ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("chat.html")


@app.route("/chat", methods=["POST"])
def chat():
    """
    Endpoint unificado.

    Modo API (canal externo — Botmaker, webchat, etc.):
      Payload: { "user_id": "...", "message": "...", "channel": "botmaker", "metadata": {} }
      Requer header: Authorization: Bearer <API_SECRET_TOKEN>
      Aplica debounce de RESPONSE_DELAY_SECONDS para acumular mensagens rápidas.
      Resposta: { "response": "...", "user_id": "...", "status": "success|error" }

    Modo sandbox (UI de chat interna):
      Payload: { "message": "...", "session_id": "sandbox" }
      Sem autenticação. Resposta: { "message": "...", "status": "..." }
    """
    data = request.get_json(silent=True) or {}

    # ── Modo API: payload tem user_id ─────────────────────────────────────────
    if "user_id" in data:
        # Autenticação
        if not _check_auth(request):
            return jsonify({"error": "Unauthorized", "status": "error"}), 401

        user_id = (data.get("user_id") or "").strip()
        message = (data.get("message") or "").strip()
        channel = data.get("channel", "api")

        if not user_id:
            return jsonify({"error": "user_id é obrigatório", "status": "error"}), 400
        if not message:
            return jsonify({"error": "message é obrigatório", "status": "error"}), 400

        # ── Segurança: rate limit ──────────────────────────────────────────────
        allowed, count = rate_limiter(user_id)
        if not allowed:
            log_security_event("RATE_LIMIT_EXCEEDED", hash_user_id(user_id), {"count": count})
            return jsonify({"error": "Muitas mensagens. Aguarde um momento.", "status": "error"}), 429

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

        with _chat_lock:
            if user_id not in _chat_state:
                _chat_state[user_id] = {
                    "messages": [],
                    "timer": None,
                    "event": threading.Event(),
                    "result": None,
                    "channel": channel,
                }

            state = _chat_state[user_id]
            state["messages"].append(message)

            # Reinicia o timer a cada mensagem recebida (debounce)
            if state["timer"] is not None:
                state["timer"].cancel()

            state["event"].clear()
            state["result"] = None

            timer = threading.Timer(RESPONSE_DELAY_SECONDS, _flush_and_respond, args=[user_id])
            timer.daemon = True
            state["timer"] = timer
            timer.start()

            event = state["event"]

        # Bloqueia a thread até o timer disparar e o processamento completar
        triggered = event.wait(timeout=RESPONSE_DELAY_SECONDS + 15)

        with _chat_lock:
            result = _chat_state.get(user_id, {}).get("result")
            if result:
                _chat_state.pop(user_id, None)

        if triggered and result:
            return jsonify(result)
        else:
            return jsonify({
                "response": FALLBACK_MESSAGE,
                "user_id": user_id,
                "status": "error",
            })

    # ── Modo sandbox: payload tem session_id (ou nenhum user_id) ─────────────
    user_message = (data.get("message") or "").strip()
    session_id = data.get("session_id", "sandbox")
    if not user_message:
        return jsonify({"error": "Mensagem vazia"}), 400

    # Sanitização e injection detection mesmo no sandbox
    user_message, warnings = sanitize_input(user_message)
    if warnings:
        log_security_event("INPUT_SANITIZED", session_id, {"warnings": warnings, "source": "sandbox"})

    is_suspicious, patterns = check_injection_patterns(user_message)
    if is_suspicious:
        log_security_event("INJECTION_DETECTED", session_id, {"patterns": patterns, "source": "sandbox"})

    result = agent.reply(user_message, session_id=session_id)

    # Filtrar output
    result["message"], redactions = filter_output(result["message"])
    if redactions:
        log_security_event("OUTPUT_FILTERED", session_id, {"redactions": redactions})

    return jsonify(result)


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

@app.route("/webhook/zapi", methods=["POST"])
def webhook_zapi():
    """Recebe mensagens do WhatsApp via Z-API e responde com o agente."""
    data = request.get_json(silent=True) or {}

    print(f"[ZAPI WEBHOOK] Payload recebido: {data}", flush=True)

    incoming = parse_incoming(data)
    if not incoming:
        print(f"[ZAPI WEBHOOK] Ignorado — type={data.get('type')} fromMe={data.get('fromMe')} phone={data.get('phone')} body={data.get('body')}", flush=True)
        return jsonify({"status": "ignored"}), 200

    phone = incoming["phone"]
    message = incoming["message"]

    print(f"[ZAPI WEBHOOK] Processando — phone={phone} msg={message[:80]}", flush=True)

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

    if escalation.is_escalated(phone, agent.memory):
        print(f"[ZAPI WEBHOOK] Sessão {phone} em atendimento humano — IA pausada.", flush=True)
        return jsonify({"status": "escalated_session"}), 200

    # Se o lead voltou a responder, cancela follow-ups frios pendentes
    followup_manager.cancel_pending_followups(phone)
    followup_manager.mark_responded(phone)

    result = agent.reply(message, session_id=phone)

    # Filtrar output antes de enviar ao lead
    reply_text, redactions = filter_output(result["message"])
    if redactions:
        log_security_event("OUTPUT_FILTERED", hash_user_id(phone), {"redactions": redactions})

    if result.get("escalate"):
        lead_name = agent.memory.get(phone)[0].get("content", "Lead") if agent.memory.get(phone) else "Lead"
        escalation.handle_escalation(phone, agent.memory, lead_name)

    # ── Detecção de finalização ────────────────────────────────────────────────
    _detect_and_handle_finalization(phone, message, reply_text, result)

    ok = send_message(phone, reply_text)
    print(f"[ZAPI WEBHOOK] Resposta enviada={ok} escalate={result.get('escalate')} — {reply_text[:80]}", flush=True)

    return jsonify({"status": "ok"}), 200


def _detect_and_handle_finalization(phone: str, user_msg: str, reply_text: str, result: dict):
    """
    Detecta sinais de compra, rejeição ou desqualificação na conversa
    e aciona o agendamento automático de follow-up/CSAT.
    """
    try:
        import json, os
        kb_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data/finalization.json")
        with open(kb_path, "r", encoding="utf-8") as f:
            fin_kb = json.load(f)

        triggers = fin_kb.get("triggers_de_finalizacao", {})
        lower_msg = (user_msg + " " + reply_text).lower()

        # Verificar compra confirmada
        if any(t in lower_msg for t in triggers.get("compra_confirmada", [])):
            print(f"[FINALIZATION] Compra detectada para {hash_user_id(phone)}", flush=True)
            database.update_lead_status(phone, "purchased")
            # Agenda CSAT para 48h
            history = agent.memory.get(phone) or []
            name = next((m["content"].split("Nome:")[1].split(".")[0].strip()
                        for m in history if "NOVO LEAD" in m.get("content", "")), "")
            followup_manager.schedule_csat(phone, name=name)
            return

        # Verificar rejeição explícita
        if any(t in lower_msg for t in triggers.get("rejeicao_explicita", [])):
            print(f"[FINALIZATION] Rejeição detectada para {hash_user_id(phone)}", flush=True)
            database.update_lead_status(phone, "rejected")
            followup_manager.cancel_pending_followups(phone)
            return

        # Verificar desqualificação
        if any(t in lower_msg for t in triggers.get("desqualificacao", [])):
            print(f"[FINALIZATION] Desqualificação detectada para {hash_user_id(phone)}", flush=True)
            database.update_lead_status(phone, "disqualified")
            followup_manager.cancel_pending_followups(phone)
            return

    except Exception as e:
        print(f"[FINALIZATION] Erro na detecção: {e}", flush=True)


@app.route("/webhook/form", methods=["POST"])
def webhook_form():
    """Recebe lead do Quill Forms e inicia conversa no WhatsApp."""
    data = request.get_json(silent=True) or {}

    phone = (
        data.get("phone") or data.get("celular") or
        data.get("telefone") or data.get("whatsapp") or ""
    ).strip()

    name = (
        data.get("name") or data.get("nome") or
        data.get("primeiro_nome") or "Lead"
    ).strip()

    if not phone:
        return jsonify({"error": "Campo 'phone' não encontrado no payload"}), 400

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

    send_message(phone, opening)

    return jsonify({"status": "ok", "phone": phone}), 200


# ── Escalação humana ──────────────────────────────────────────────────────────

@app.route("/escalation/resolve", methods=["POST"])
def escalation_resolve():
    """Devolve o controle da conversa para a IA após atendimento humano."""
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    if not phone:
        return jsonify({"error": "Campo 'phone' obrigatório"}), 400

    escalation.resolve_escalation(phone, agent.memory)
    return jsonify({"status": "ok", "message": f"Sessão {phone} retornada para IA."}), 200


@app.route("/leads/escalated", methods=["GET"])
def leads_escalated():
    """Lista sessões atualmente em atendimento humano."""
    escalated = [
        s for s in agent.memory.list_sessions()
        if agent.memory.get_status(s) == "escalated"
    ]
    return jsonify({"escalated": escalated, "count": len(escalated)}), 200


# ── Follow-up e Finalização ───────────────────────────────────────────────────

@app.route("/followup/schedule", methods=["POST"])
def followup_schedule():
    """
    Agenda follow-up manual para um lead.
    Body: { "phone": "...", "trigger": "cold_d3|cold_d7|cold_d14|csat_48h",
            "name": "...", "specialty": "...", "prova": "..." }
    """
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    trigger = data.get("trigger", "cold_d3")
    if not phone:
        return jsonify({"error": "Campo 'phone' obrigatório"}), 400
    metadata = {
        "name": data.get("name", ""),
        "specialty": data.get("specialty", ""),
        "prova": data.get("prova", ""),
    }
    ok = followup_manager.schedule_followup(phone, trigger, metadata=metadata)
    return jsonify({"status": "ok" if ok else "error", "phone": phone, "trigger": trigger}), 200


@app.route("/followup/schedule_cold_sequence", methods=["POST"])
def followup_schedule_cold():
    """
    Agenda a sequência completa de re-engajamento (d3+d7+d14) para um lead frio.
    Body: { "phone": "...", "name": "...", "specialty": "...", "prova": "..." }
    """
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    if not phone:
        return jsonify({"error": "Campo 'phone' obrigatório"}), 400
    ok = followup_manager.schedule_cold_sequence(
        phone,
        name=data.get("name", ""),
        specialty=data.get("specialty", ""),
        prova=data.get("prova", ""),
    )
    database.update_lead_status(phone, "cold")
    return jsonify({"status": "ok" if ok else "error", "phone": phone, "sequence": "cold_d3+d7+d14"}), 200


@app.route("/followup/process", methods=["POST"])
def followup_process():
    """
    Worker endpoint — processa e envia todos os follow-ups pendentes agora.
    Chamar via cron externo (Railway Cron, Supabase pg_cron, etc.) a cada 15-30min.
    Protegido por Bearer token.
    """
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    report = followup_manager.process_pending_followups(agent)
    print(f"[FOLLOWUP] Processamento concluído: {report}", flush=True)
    return jsonify({"status": "ok", **report}), 200


@app.route("/followup/pending", methods=["GET"])
def followup_pending():
    """Lista follow-ups pendentes (para monitoramento)."""
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    pending = followup_manager.get_pending_followups(limit=100)
    return jsonify({"pending": pending, "count": len(pending)}), 200


@app.route("/followup/csat_response", methods=["POST"])
def followup_csat_response():
    """
    Registra a nota CSAT e devolve a mensagem de resposta ao lead.
    Body: { "phone": "...", "score": 8, "name": "..." }
    Quando score <= 6, aciona escalação para humano automaticamente.
    """
    if not _check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    score = data.get("score")
    name = data.get("name", "")
    if not phone or score is None:
        return jsonify({"error": "Campos 'phone' e 'score' obrigatórios"}), 400
    try:
        score = int(score)
        assert 0 <= score <= 10
    except Exception:
        return jsonify({"error": "Score deve ser número de 0 a 10"}), 400

    followup_manager.save_csat_score(phone, score)
    database.update_lead_status(phone, "csat_pending" if score <= 6 else "closed_won")

    reply = followup_manager.build_csat_reply(score, name)

    if score <= 6:
        escalation.handle_escalation(phone, agent.memory, name or "Lead (CSAT crítico)")

    category = "promotor" if score >= 9 else ("neutro" if score >= 7 else "critico")
    return jsonify({
        "status": "ok",
        "score": score,
        "category": category,
        "reply_message": reply,
        "escalated": score <= 6,
    }), 200


# ── Health checks ─────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.0"})


@app.route("/health/security", methods=["GET"])
def health_security():
    """Retorna últimos 20 eventos de segurança. Use para monitoramento."""
    from core.logger import get_recent_events
    events = get_recent_events(20)
    return jsonify({"status": "ok", "recent_events": events, "count": len(events)}), 200


@app.route("/health/db", methods=["GET"])
def health_db():
    """Testa conexão com o Supabase."""
    if not database.is_enabled():
        return jsonify({"status": "disabled", "message": "SUPABASE_URL/KEY não configurados"}), 200
    try:
        from supabase import create_client
        db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        result = db.table("leads").select("id").limit(1).execute()
        return jsonify({"status": "ok", "message": "Supabase conectado ✅", "leads_count": len(result.data)}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    print(f"\n🟣 Criatons rodando em http://{HOST}:{PORT}\n")
    app.run(host=HOST, debug=DEBUG, port=PORT)
