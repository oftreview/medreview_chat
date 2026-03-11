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
    result = agent.reply(user_message, session_id=session_id)
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

    if escalation.is_escalated(phone, agent.memory):
        print(f"[ZAPI WEBHOOK] Sessão {phone} em atendimento humano — IA pausada.", flush=True)
        return jsonify({"status": "escalated_session"}), 200

    result = agent.reply(message, session_id=phone)

    if result.get("escalate"):
        lead_name = agent.memory.get(phone)[0].get("content", "Lead") if agent.memory.get(phone) else "Lead"
        escalation.handle_escalation(phone, agent.memory, lead_name)

    ok = send_message(phone, result["message"])
    print(f"[ZAPI WEBHOOK] Resposta enviada={ok} escalate={result.get('escalate')} — {result['message'][:80]}", flush=True)

    return jsonify({"status": "ok"}), 200


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


# ── Health checks ─────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.0"})


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
