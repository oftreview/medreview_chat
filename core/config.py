import os
from dotenv import load_dotenv

load_dotenv()

# --- Claude ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4000"))

# --- Servidor ---
DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
PORT = int(os.getenv("PORT", "5000"))

# --- Z-API (WhatsApp) ---
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "")
