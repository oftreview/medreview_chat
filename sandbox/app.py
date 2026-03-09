import sys
import os
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, request, jsonify, render_template
from agents.sales.agent import SalesAgent
from core.config import DEBUG, PORT
from core.whatsapp import send_message, parse_incoming
from core import database, escalation

HOST = os.getenv("HOST", "0.0.0.0")

app = Flask(__name__)
agent = SalesAgent()

# ── UI de chat (sandbox) ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("chat.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
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

    # LOG COMPLETO para debug — aparece nos logs do Railway
    print(f"[ZAPI WEBHOOK] Payload recebido: {data}", flush=True)

    incoming = parse_incoming(data)
    if not incoming:
        print(f"[ZAPI WEBHOOK] Ignorado — type={data.get('type')} fromMe={data.get('fromMe')} phone={data.get('phone')} body={data.get('body')}", flush=True)
        return jsonify({"status": "ignored"}), 200

    phone = incoming["phone"]
    message = incoming["message"]

    print(f"[ZAPI WEBHOOK] Processando — phone={phone} msg={message[:80]}", flush=True)

    # Se sessão já foi escalada para humano: IA não responde
    if escalation.is_escalated(phone, agent.memory):
        print(f"[ZAPI WEBHOOK] Sessão {phone} em atendimento humano — IA pausada.", flush=True)
        return jsonify({"status": "escalated_session"}), 200

    result = agent.reply(message, session_id=phone)

    # Verifica se a resposta aciona escalação
    if result.get("escalate"):
        lead_name = agent.memory.get(phone)[0].get("content", "Lead") if agent.memory.get(phone) else "Lead"
        escalation.handle_escalation(phone, agent.memory, lead_name)

    ok = send_message(phone, result["message"])
    print(f"[ZAPI WEBHOOK] Resposta enviada={ok} escalate={result.get('escalate')} — {result['message'][:80]}", flush=True)

    return jsonify({"status": "ok"}), 200


@app.route("/webhook/form", methods=["POST"])
def webhook_form():
    """
    Recebe lead do Quill Forms e inicia conversa no WhatsApp.
    Espera payload com campo 'phone' (ou 'celular'/'telefone') e 'name' (ou 'nome').
    """
    data = request.get_json(silent=True) or {}

    # Tentar extrair telefone e nome com nomes de campo flexíveis
    phone = (
        data.get("phone") or
        data.get("celular") or
        data.get("telefone") or
        data.get("whatsapp") or
        ""
    ).strip()

    name = (
        data.get("name") or
        data.get("nome") or
        data.get("primeiro_nome") or
        "Lead"
    ).strip()

    if not phone:
        return jsonify({"error": "Campo 'phone' não encontrado no payload"}), 400

    # Persiste o lead no Supabase
    database.upsert_lead(phone=phone, name=name, source="form")

    # Escolhe nome do agente aleatoriamente
    agent_name = random.choice(["Pedro", "Sofia"])
    first_name = name.split()[0] if name and name != "Lead" else ""

    # Mensagem de abertura fixa — não passa pelo LLM para garantir copy exata
    opening = (
        f"Olá, {first_name}, tudo bem? "
        f"Aqui é {agent_name}, do time comercial da Med-Review! "
        f"Vi que preencheu nosso formulário para saber mais sobre os preparatórios, certo?\n\n"
        f"Posso te enviar as informações por aqui? ☺️"
    )

    # Salva contexto na memória para que o agente saiba o histórico nas próximas mensagens
    agent.memory.add(phone, "user", f"[NOVO LEAD] Nome: {name}. Agente: {agent_name}.")
    agent.memory.add(phone, "assistant", opening)

    # Envia direto, sem LLM
    send_message(phone, opening)

    return jsonify({"status": "ok", "phone": phone}), 200


# ── Escalação humana ──────────────────────────────────────────────────────────

@app.route("/escalation/resolve", methods=["POST"])
def escalation_resolve():
    """
    Devolve o controle da conversa para a IA após atendimento humano.
    Payload: { "phone": "5531999990000" }
    """
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    if not phone:
        return jsonify({"error": "Campo 'phone' obrigatório"}), 400

    escalation.resolve_escalation(phone, agent.memory)
    return jsonify({"status": "ok", "message": f"Sessão {phone} retornada para IA."}), 200


@app.route("/leads/escalated", methods=["GET"])
def leads_escalated():
    """Lista sessões atualmente em atendimento humano (escalated)."""
    escalated = [
        s for s in agent.memory.list_sessions()
        if agent.memory.get_status(s) == "escalated"
    ]
    return jsonify({"escalated": escalated, "count": len(escalated)}), 200


# ── Utilitários ───────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/health/db", methods=["GET"])
def health_db():
    """Testa conexão com o Supabase."""
    if not database.is_enabled():
        return jsonify({"status": "disabled", "message": "SUPABASE_URL/KEY não configurados"}), 200
    try:
        from supabase import create_client
        import os
        db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        result = db.table("leads").select("id").limit(1).execute()
        return jsonify({"status": "ok", "message": "Supabase conectado ✅", "leads_count": len(result.data)}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    print(f"\n🟣 Criatons rodando em http://{HOST}:{PORT}\n")
    app.run(host=HOST, debug=DEBUG, port=PORT)
