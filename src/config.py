"""
src/config.py — Configuração centralizada do Criatons.

Todas as variáveis de ambiente são lidas aqui e exportadas como constantes.
Nenhum outro módulo deve chamar os.getenv() diretamente.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Claude / LLM ─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4000"))

# ── Servidor ──────────────────────────────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
PORT = int(os.getenv("PORT", "5000"))
HOST = os.getenv("HOST", "0.0.0.0")

# ── Autenticação & Segurança ─────────────────────────────────────────────────
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN", "")
RESPONSE_DELAY_SECONDS = int(os.getenv("RESPONSE_DELAY_SECONDS", "10"))
FALLBACK_MESSAGE = os.getenv(
    "FALLBACK_MESSAGE",
    "Estou com uma instabilidade agora, em breve um consultor vai te atender.",
)
FORM_RATE_LIMIT = int(os.getenv("FORM_RATE_LIMIT", "5"))

# ── Comandos de escalação ────────────────────────────────────────────────────
ESCALATE_COMMAND = "#transferindo-para-atendimento-dedicado"
DEESCALATE_COMMAND = "#retorno-para-atendimento-agente"
ESCALATE_CONFIRM_MSG = (
    "Entendido! Estou transferindo você para um atendimento dedicado. "
    "Um especialista vai continuar a conversa por aqui. 😊"
)
DEESCALATE_CONFIRM_MSG = ""  # Silencioso — agente retoma sem aviso

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ── Z-API (WhatsApp) ─────────────────────────────────────────────────────────
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "")

# ── HubSpot ───────────────────────────────────────────────────────────────────
HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
HUBSPOT_PIPELINE_ID = os.getenv("HUBSPOT_PIPELINE_ID", "default")
HUBSPOT_ENABLED = os.getenv("HUBSPOT_ENABLED", "false").lower() in ("true", "1", "yes")

# ── Escalação (supervisor + Botmaker futura) ─────────────────────────────────
SUPERVISOR_PHONE = os.getenv("SUPERVISOR_PHONE", "")
BOTMAKER_API_KEY = os.getenv("BOTMAKER_API_KEY", "")
BOTMAKER_TEAM_ID = os.getenv("BOTMAKER_TEAM_ID", "")
