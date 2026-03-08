import json
import os
from core.llm import call_claude
from core.memory import ConversationMemory

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PROMPT_PATH = os.path.join(BASE_DIR, "agents/sales/prompts/system_prompt.md")
OFFERS_PATH = os.path.join(BASE_DIR, "data/offers.json")
RULES_PATH = os.path.join(BASE_DIR, "data/commercial_rules.json")
PRODUCT_INFO_PATH = os.path.join(BASE_DIR, "data/product_info.json")

def load_context() -> str:
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        prompt = f.read()
    with open(OFFERS_PATH, "r", encoding="utf-8") as f:
        offers = json.load(f)
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        rules = json.load(f)
    with open(PRODUCT_INFO_PATH, "r", encoding="utf-8") as f:
        product_info = json.load(f)
    return (
        f"{prompt}\n\n"
        f"# OFERTAS (preços e planos)\n{json.dumps(offers, ensure_ascii=False, indent=2)}\n\n"
        f"# INFORMAÇÕES DE PRODUTO (descrições e FAQ para perguntas do lead)\n{json.dumps(product_info, ensure_ascii=False, indent=2)}\n\n"
        f"# REGRAS COMERCIAIS\n{json.dumps(rules, ensure_ascii=False, indent=2)}"
    )

class SalesAgent:
    def __init__(self):
        self.memory = ConversationMemory()
        self.system_prompt = load_context()

    def reply(self, user_message: str, session_id: str = "default") -> dict:
        self.memory.add(session_id, "user", user_message)
        response_text = call_claude(self.system_prompt, self.memory.get(session_id))
        self.memory.add(session_id, "assistant", response_text)

        escalate = any(t in response_text.lower() for t in ["vou conectar você com", "consultor humano"])
        if escalate:
            self.memory.set_status(session_id, "escalated")

        status = self.memory.get_status(session_id)
        return {"message": response_text, "status": status, "escalate": escalate}

    def reset(self, session_id: str = None):
        self.memory.reset(session_id)
