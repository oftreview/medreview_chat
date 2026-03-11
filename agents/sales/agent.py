import json
import os
from core.llm import call_claude
from core.memory import ConversationMemory

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PROMPT_PATH         = os.path.join(BASE_DIR, "agents/sales/prompts/system_prompt.md")
STAGE_SCRIPTS_PATH  = os.path.join(BASE_DIR, "agents/sales/prompts/stage_scripts.md")
OFFERS_PATH         = os.path.join(BASE_DIR, "data/offers.json")
RULES_PATH          = os.path.join(BASE_DIR, "data/commercial_rules.json")
PRODUCT_INFO_PATH   = os.path.join(BASE_DIR, "data/product_info.json")
COMPETITORS_PATH    = os.path.join(BASE_DIR, "data/competitors.json")
OBJECTIONS_PATH     = os.path.join(BASE_DIR, "data/objections.json")
SALES_TECH_PATH     = os.path.join(BASE_DIR, "data/sales_techniques.md")
FINALIZATION_PATH   = os.path.join(BASE_DIR, "data/finalization.json")


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_context() -> str:
    prompt        = _load_text(PROMPT_PATH)
    stage_scripts = _load_text(STAGE_SCRIPTS_PATH)
    sales_tech    = _load_text(SALES_TECH_PATH)
    offers        = _load_json(OFFERS_PATH)
    rules         = _load_json(RULES_PATH)
    product_info  = _load_json(PRODUCT_INFO_PATH)
    competitors   = _load_json(COMPETITORS_PATH)
    objections    = _load_json(OBJECTIONS_PATH)
    finalization  = _load_json(FINALIZATION_PATH)

    return (
        f"{prompt}\n\n"
        f"# SCRIPTS POR ETAPA (tom, exemplos, transições)\n{stage_scripts}\n\n"
        f"# TÉCNICAS DE VENDAS\n{sales_tech}\n\n"
        f"# OFERTAS (preços, planos e links de pagamento)\n{json.dumps(offers, ensure_ascii=False, indent=2)}\n\n"
        f"# INFORMAÇÕES DE PRODUTO (descrições detalhadas e FAQ)\n{json.dumps(product_info, ensure_ascii=False, indent=2)}\n\n"
        f"# CONCORRENTES (argumentos e abordagem por plataforma)\n{json.dumps(competitors, ensure_ascii=False, indent=2)}\n\n"
        f"# OBJEÇÕES (framework de contorno por tipo de objeção)\n{json.dumps(objections, ensure_ascii=False, indent=2)}\n\n"
        f"# REGRAS COMERCIAIS\n{json.dumps(rules, ensure_ascii=False, indent=2)}\n\n"
        f"# FINALIZAÇÃO, RE-ENGAJAMENTO E CSAT (scripts de despedida, follow-up e pesquisa)\n{json.dumps(finalization, ensure_ascii=False, indent=2)}"
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
