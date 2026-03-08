import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, request, jsonify, render_template
from agents.sales.agent import SalesAgent
from core.config import DEBUG, PORT, HOST

app = Flask(__name__)
agent = SalesAgent()

@app.route("/")
def index():
    return render_template("chat.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Mensagem vazia"}), 400

    result = agent.reply(user_message)
    return jsonify(result)

@app.route("/reset", methods=["POST"])
def reset():
    agent.reset()
    return jsonify({"status": "ok", "message": "Conversa reiniciada."})

@app.route("/history", methods=["GET"])
def history():
    return jsonify({"history": agent.memory.get()})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    print(f"\n🟣 Criatons rodando em http://{HOST}:{PORT}\n")
    app.run(host=HOST, debug=DEBUG, port=PORT)
