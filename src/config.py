"""
src/config.py — Configuração centralizada do Closi AI.

Todas as variáveis de ambiente são lidas aqui e exportadas como constantes.
Nenhum outro módulo deve chamar os.getenv() diretamente.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Modo de Teste ──────────────────────────────────────────────────────────────
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"

# ── OpenRouter / LLM ─────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-4-5")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://closi.ai")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Closi AI")
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

# ── Login do Dashboard (Supabase Auth) ───────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "")
SESSION_LIFETIME_HOURS = int(os.getenv("SESSION_LIFETIME_HOURS", "2"))
LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
LOGIN_RATE_LIMIT_WINDOW_MINUTES = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_MINUTES", "5"))
# ⚠️ APENAS PARA DESENVOLVIMENTO LOCAL. Se "true", pula o login e libera o dashboard.
# NUNCA ativar em produção — qualquer pessoa acessaria o dashboard sem autenticação.
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() in ("true", "1", "yes")

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
