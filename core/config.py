import os
from dotenv import load_dotenv

load_dotenv()

# --- Claude ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4000"))

# --- Servidor ---
DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
PORT = int(os.getenv("PORT", "5000"))

# --- Z-API (WhatsApp) ---
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "")

# --- HubSpot ---
HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
HUBSPOT_PIPELINE_ID = os.getenv("HUBSPOT_PIPELINE_ID", "default")
HUBSPOT_ENABLED = os.getenv("HUBSPOT_ENABLED", "false").lower() in ("true", "1", "yes")
