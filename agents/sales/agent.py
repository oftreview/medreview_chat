"""
agents/sales/agent.py — Agente de vendas MedReview.

Gerencia contexto, histórico truncado e detecção de escalação.
"""

import json
import os
from core.llm import call_claude
from core.memory import ConversationMemory

# ── Configuração de truncamento de histórico ─────────────────────────────────
# Mantém as primeiras KEEP_FIRST mensagens (contexto de qualificação/abertura)
# + as últimas KEEP_LAST mensagens (conversa recente).
# Isso evita estourar o contexto do Claude em conversas longas.
KEEP_FIRST = 4      # primeiras mensagens (abertura + qualificação inicial)
KEEP_LAST = 26       # mensagens mais recentes
MAX_HISTORY = KEEP_FIRST + KEEP_LAST   # 30 mensagens no total

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PROMPT_PATH         = os.path.join(BASE_DIR, "agents/sales/prompts/system_prompt.md")
STAGE_SCRIPTS_PATH  = os.path.join(BASE_DIR, "agents/sales/prompts/stage_scripts.md")
OFFERS_PATH         = os.path.join(BASE_DIR, "data/offers.json")
RULES_PATH          = os.path.join(BASE_DIR, "data/commercial_rules.json")
PRODUCT_INFO_PATH   = os.path.join(BASE_DIR, "data/product_info.json")
COMPETITORS_PATH    = os.path.join(BASE_DIR, "data/competitors.json")
OBJECTIONS_PATH     = os.path.join(BASE_DIR, "data/objections.json")
CONVERSION_PATH     = os.path.join(BASE_DIR, "data/conversion_bible.json")
CORRECTIONS_PATH    = os.path.join(BASE_DIR, "data/corrections.json")
SALES_TECH_PATH     = os.path.join(BASE_DIR, "data/sales_techniques.md")

# Tag estruturada de escalação — o Claude inclui no início da resposta quando quer escalar.
# É removida antes de enviar ao lead.
ESCALATION_TAG = "[ESCALAR]"

# Fallback: frases de escalação por string matching (caso o Claude não use a tag)
ESCALATION_FALLBACK_PHRASES = [
    "vou conectar você com",
    "consultor humano",
    "vou te passar para um consultor",
    "vou transferir você",
]


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _build_corrections_block(corrections_data: dict) -> str:
    """
    Monta o bloco de correções para injeção no system prompt.
    Filtra apenas correções ativas (ignora status='exemplo').
    Formata cada correção como regra imperativa de alta prioridade.
    """
    active = [
        c for c in corrections_data.get("corrections", [])
        if c.get("status") != "exemplo"
    ]
    if not active:
        return ""

    lines = [
        "# ⚠️ CORREÇÕES OBRIGATÓRIAS (PRIORIDADE MÁXIMA)",
        "",
        "As regras abaixo foram aprendidas de ERROS REAIS em produção.",
        "Você DEVE seguir cada uma delas. NUNCA repita esses erros.",
        "",
    ]
    for c in active:
        sev = c.get("severidade", "alta").upper()
        lines.append(f"## [{sev}] {c['id']} — {c.get('categoria', 'outro')}")
        lines.append(f"Gatilho: {c['gatilho']}")
        lines.append(f"❌ ERRADO: {c['resposta_errada']}")
        lines.append(f"✅ CORRETO: {c['resposta_correta']}")
        lines.append(f"REGRA: {c['regra']}")
        lines.append("")

    return "\n".join(lines)


def load_context() -> str:
    prompt        = _load_text(PROMPT_PATH)
    stage_scripts = _load_text(STAGE_SCRIPTS_PATH)
    sales_tech    = _load_text(SALES_TECH_PATH)
    offers        = _load_json(OFFERS_PATH)
    rules         = _load_json(RULES_PATH)
    product_info  = _load_json(PRODUCT_INFO_PATH)
    competitors   = _load_json(COMPETITORS_PATH)
    objections    = _load_json(OBJECTIONS_PATH)
    conversion    = _load_json(CONVERSION_PATH)
    corrections   = _load_json(CORRECTIONS_PATH)

    # Bloco de correções — injetado LOGO APÓS o prompt base (prioridade máxima)
    corrections_block = _build_corrections_block(corrections)

    return (
        f"{prompt}\n\n"
        f"{corrections_block}"
        f"# SCRIPTS POR ETAPA (tom, exemplos, transições)\n{stage_scripts}\n\n"
        f"# TÉCNICAS DE VENDAS\n{sales_tech}\n\n"
        f"# OFERTAS (preços, planos e links de pagamento)\n{json.dumps(offers, ensure_ascii=False, indent=2)}\n\n"
        f"# INFORMAÇÕES DE PRODUTO (descrições detalhadas, módulos e FAQ)\n{json.dumps(product_info, ensure_ascii=False, indent=2)}\n\n"
        f"# CONCORRENTES (argumentos e abordagem por plataforma + comparativos por módulo)\n{json.dumps(competitors, ensure_ascii=False, indent=2)}\n\n"
        f"# OBJEÇÕES (framework de contorno por tipo de objeção — geral + por módulo)\n{json.dumps(objections, ensure_ascii=False, indent=2)}\n\n"
        f"# BÍBLIA DE CONVERSÃO (100 dores do mercado vs soluções MED-Review + scripts IA)\n{json.dumps(conversion, ensure_ascii=False, indent=2)}\n\n"
        f"# REGRAS COMERCIAIS\n{json.dumps(rules, ensure_ascii=False, indent=2)}"
    )

def _truncate_history(messages: list) -> list:
    """
    Trunca o histórico mantendo contexto inicial + mensagens recentes.

    Estratégia: manter as primeiras KEEP_FIRST mensagens (abertura, nome do
    agente, qualificação inicial — contexto que o Claude precisa) e as últimas
    KEEP_LAST mensagens (conversa recente para continuidade).

    Se o histórico for menor que MAX_HISTORY, retorna sem alteração.
    """
    if len(messages) <= MAX_HISTORY:
        return messages

    head = messages[:KEEP_FIRST]
    tail = messages[-KEEP_LAST:]
    return head + tail


class SalesAgent:
    def __init__(self):
        self.memory = ConversationMemory()
        self.system_prompt = load_context()

    def reply(self, user_message: str, session_id: str = "default") -> dict:
        self.memory.add(session_id, "user", user_message)

        # Trunca histórico antes de enviar ao Claude para controlar custo/contexto
        full_history = self.memory.get(session_id)
        truncated = _truncate_history(full_history)

        response_text = call_claude(self.system_prompt, truncated)

        # ── Detecção de escalação ────────────────────────────────────────────
        # Prioridade 1: tag estruturada [ESCALAR] no início da resposta
        escalate = response_text.strip().startswith(ESCALATION_TAG)

        if escalate:
            # Remove a tag — o lead nunca deve vê-la
            response_text = response_text.strip()[len(ESCALATION_TAG):].strip()
            print(f"[AGENT] Escalação detectada via tag [ESCALAR]", flush=True)
        else:
            # Prioridade 2: fallback por string matching (caso Claude não use a tag)
            escalate = any(
                phrase in response_text.lower()
                for phrase in ESCALATION_FALLBACK_PHRASES
            )
            if escalate:
                print(f"[AGENT] Escalação detectada via fallback (string match)", flush=True)

        # Salva a resposta LIMPA (sem tag) no histórico
        self.memory.add(session_id, "assistant", response_text)

        if escalate:
            self.memory.set_status(session_id, "escalated")

        status = self.memory.get_status(session_id)
        return {"message": response_text, "status": status, "escalate": escalate}

    def reset(self, session_id: str = None):
        self.memory.reset(session_id)
