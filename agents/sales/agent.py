"""
agents/sales/agent.py — Agente de vendas MedReview.

Gerencia contexto, histórico truncado, detecção de escalação
e extração de metadados estruturados (funnel_stage + qualification_data).
"""

import json
import os
import re
from core.llm import call_claude
from core.memory import ConversationMemory

# ── Configuração de truncamento de histórico ─────────────────────────────────
KEEP_FIRST = 4
KEEP_LAST = 26
MAX_HISTORY = KEEP_FIRST + KEEP_LAST

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
AMBASSADORS_PATH    = os.path.join(BASE_DIR, "data/ambassadors.json")
SALES_TECH_PATH     = os.path.join(BASE_DIR, "data/sales_techniques.md")
RESIDENCIA_PATH     = os.path.join(BASE_DIR, "data/residencia_provas.json")

# Tag estruturada de escalação
ESCALATION_TAG = "[ESCALAR]"

# Tag de metadados estruturados
META_TAG = "[META]"
META_PATTERN = re.compile(r"\[META\]\s*(.+)$", re.MULTILINE)

# Fallback: frases de escalação por string matching
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


def _extract_metadata(response_text: str) -> tuple:
    """
    Extrai metadados [META] da resposta do Claude.
    Retorna (clean_text, metadata_dict).
    O clean_text é a resposta sem o bloco [META].
    """
    match = META_PATTERN.search(response_text)
    if not match:
        return response_text, {}

    meta_line = match.group(1).strip()
    clean_text = response_text[:match.start()].rstrip()

    metadata = {}
    for pair in meta_line.split("|"):
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            key = key.strip()
            value = value.strip()
            if value and value != "desconhecido":
                metadata[key] = value
            elif value == "desconhecido":
                metadata[key] = None

    return clean_text, metadata


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
    ambassadors   = _load_json(AMBASSADORS_PATH)
    residencia    = _load_json(RESIDENCIA_PATH)

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
        f"# REGRAS COMERCIAIS\n{json.dumps(rules, ensure_ascii=False, indent=2)}\n\n"
        f"# PROGRAMA DE EMBAIXADORES (regras de comunicação + conhecimento + FAQ)\n{json.dumps(ambassadors, ensure_ascii=False, indent=2)}\n\n"
        f"# PROVAS E CONCURSOS DE RESIDÊNCIA MÉDICA (atualizado em {residencia.get('_meta', {}).get('ultima_atualizacao', '27/03/2026')})\n{json.dumps(residencia, ensure_ascii=False, indent=2)}"
    )

def _truncate_history(messages: list) -> list:
    if len(messages) <= MAX_HISTORY:
        return messages
    head = messages[:KEEP_FIRST]
    tail = messages[-KEEP_LAST:]
    return head + tail


class SalesAgent:
    def __init__(self):
        self.memory = ConversationMemory()
        self.system_prompt = load_context()
        # Armazena metadados mais recentes por session: { session_id -> dict }
        self._lead_data: dict = {}

    def reply(self, user_message: str, session_id: str = "default") -> dict:
        self.memory.add(session_id, "user", user_message)

        full_history = self.memory.get(session_id)
        truncated = _truncate_history(full_history)

        response_text = call_claude(self.system_prompt, truncated)

        # ── Extrair metadados [META] ───────────────────────────────────────
        response_text, metadata = _extract_metadata(response_text)

        if metadata:
            # Merge com dados existentes (preserva dados já coletados)
            if session_id not in self._lead_data:
                self._lead_data[session_id] = {}
            for key, value in metadata.items():
                if value is not None:  # Só sobrescreve se não for "desconhecido"
                    self._lead_data[session_id][key] = value
                elif key not in self._lead_data[session_id]:
                    self._lead_data[session_id][key] = None

            stage = metadata.get("stage", "desconhecido")
            print(f"[AGENT META] session={session_id[:8]}... stage={stage} dados={metadata}", flush=True)

            # Salva metadados no banco de dados
            from core import database
            database.save_lead_metadata(session_id, self._lead_data[session_id])

            # Sync para HubSpot (assíncrono, não bloqueia a resposta)
            try:
                from core import hubspot
                if hubspot.is_enabled():
                    hubspot.sync_lead(
                        phone=session_id,
                        funnel_stage=metadata.get("stage", "desconhecido"),
                        lead_data=self._lead_data[session_id],
                    )
            except Exception as e:
                print(f"[AGENT HUBSPOT WARN] Sync falhou: {e}", flush=True)

        # ── Detecção de escalação ──────────────────────────────────────────
        escalate = response_text.strip().startswith(ESCALATION_TAG)

        if escalate:
            response_text = response_text.strip()[len(ESCALATION_TAG):].strip()
            print(f"[AGENT] Escalação detectada via tag [ESCALAR]", flush=True)
        else:
            escalate = any(
                phrase in response_text.lower()
                for phrase in ESCALATION_FALLBACK_PHRASES
            )
            if escalate:
                print(f"[AGENT] Escalação detectada via fallback (string match)", flush=True)

        # Salva a resposta LIMPA (sem tag e sem [META]) no histórico
        self.memory.add(session_id, "assistant", response_text)

        if escalate:
            self.memory.set_status(session_id, "escalated")

        status = self.memory.get_status(session_id)

        result = {
            "message": response_text,
            "status": status,
            "escalate": escalate,
        }

        # Inclui metadados no resultado (para uso interno — não vai pro lead)
        if session_id in self._lead_data:
            result["lead_data"] = self._lead_data[session_id]
            result["funnel_stage"] = self._lead_data[session_id].get("stage", "desconhecido")

        return result

    def get_lead_data(self, session_id: str) -> dict:
        """Retorna os metadados coletados de um lead."""
        return self._lead_data.get(session_id, {})

    def get_escalation_brief(self, session_id: str) -> dict:
        """
        Gera um brief completo para o vendedor quando uma sessão é escalada.
        Inclui: dados do lead, motivo da escalação, resumo da conversa e contexto.
        """
        lead_data = self._lead_data.get(session_id, {})
        history = self.memory.get(session_id)

        # Resumo: últimas 10 mensagens (contexto imediato para o vendedor)
        recent = history[-10:] if len(history) > 10 else history
        summary_lines = []
        for msg in recent:
            prefix = "Lead" if msg["role"] == "user" else "Agente"
            summary_lines.append(f"{prefix}: {msg['content'][:150]}")

        return {
            "session_id": session_id,
            "lead_data": {
                "stage": lead_data.get("stage", "desconhecido"),
                "especialidade": lead_data.get("especialidade"),
                "prova": lead_data.get("prova"),
                "ano_prova": lead_data.get("ano_prova"),
                "ja_estuda": lead_data.get("ja_estuda"),
                "plataforma_atual": lead_data.get("plataforma_atual"),
                "motivo_escalacao": lead_data.get("motivo_escalacao", "nao_especificado"),
            },
            "total_messages": len(history),
            "summary": "\n".join(summary_lines),
        }

    def reset(self, session_id: str = None):
        if session_id:
            self._lead_data.pop(session_id, None)
        else:
            self._lead_data = {}
        self.memory.reset(session_id)
