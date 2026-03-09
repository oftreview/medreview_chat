import sys
import os
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, request, jsonify, render_template
from agents.sales.agent import SalesAgent
from core.config import DEBUG, PORT
from core.whatsapp import send_message, parse_incoming
from core import database

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

    result = agent.reply(message, session_id=phone)
    ok = send_message(phone, result["message"])

    print(f"[ZAPI WEBHOOK] Resposta enviada={ok} — {result['message'][:80]}", flush=True)

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

    # Trigger com copy exata de abertura e nome do agente
    first_name = name.split()[0] if name and name != "Lead" else "tudo bem"
    trigger = (
        f"[NOVO LEAD VIA FORMULÁRIO] [AGENT_NAME: {agent_name}] Nome do lead: {name}.\n"
        f"Use EXATAMENTE esta mensagem de abertura (sem alterar nada):\n"
        f"Olá, {first_name}, tudo bem? Aqui é {agent_name}, do time comercial da Med-Review! "
        f"Vi que preencheu nosso formulário para saber mais sobre os preparatórios, certo?\n\n"
        f"Posso te enviar as informações por aqui? ☺️"
    )
    result = agent.reply(trigger, session_id=phone)
    send_message(phone, result["message"])

    return jsonify({"status": "ok", "phone": phone}), 200


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
