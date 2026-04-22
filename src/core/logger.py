"""
core/logger.py — Logger de segurança e conversas do Closi AI.

Registra eventos de segurança em logs/security.log (formato JSON-lines).
Nunca armazena dados PII diretamente — usa hash do user_id.

Funções:
  log_security_event()  — registra eventos de segurança
  log_conversation()    — registra turno de conversa com flags de segurança
"""

import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

# ── Configuração do diretório de logs ─────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SECURITY_LOG_PATH = os.path.join(LOGS_DIR, "security.log")
CONVERSATION_LOG_PATH = os.path.join(LOGS_DIR, "conversation.log")
CHAT_LOG_PATH = os.path.join(LOGS_DIR, "chat.log")

# Garante que o diretório de logs existe
os.makedirs(LOGS_DIR, exist_ok=True)

# ── Logger de segurança (arquivo JSON-lines) ──────────────────────────────────

_security_logger = logging.getLogger("closi-ai.security")
_security_logger.setLevel(logging.INFO)

if not _security_logger.handlers:
    _sec_handler = logging.FileHandler(SECURITY_LOG_PATH, encoding="utf-8")
    _sec_handler.setFormatter(logging.Formatter("%(message)s"))   # raw JSON
    _security_logger.addHandler(_sec_handler)
    _security_logger.propagate = False   # não duplicar no root logger

# ── Logger de conversas ───────────────────────────────────────────────────────

_conv_logger = logging.getLogger("closi-ai.conversation")
_conv_logger.setLevel(logging.INFO)

if not _conv_logger.handlers:
    _conv_handler = logging.FileHandler(CONVERSATION_LOG_PATH, encoding="utf-8")
    _conv_handler.setFormatter(logging.Formatter("%(message)s"))
    _conv_logger.addHandler(_conv_handler)
    _conv_logger.propagate = False

# ── Logger do pipeline de chat (texto legível, rotação de arquivo) ────────────
# Captura cada etapa do /chat: recv, debounce, flush, llm call/retry, response.
# Usado para depurar timeouts e travamentos sem depender do stdout do processo.

_chat_logger = logging.getLogger("closi-ai.chat")
_chat_logger.setLevel(logging.INFO)

if not _chat_logger.handlers:
    # 10MB × 5 backups = ~50MB max. Suficiente pra debugar semanas de tráfego dev.
    _chat_handler = RotatingFileHandler(
        CHAT_LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    _chat_handler.setFormatter(logging.Formatter("%(message)s"))
    _chat_logger.addHandler(_chat_handler)
    _chat_logger.propagate = False


# ── Funções públicas ──────────────────────────────────────────────────────────


def log_chat(tag: str, msg: str, **context) -> None:
    """
    Registra um evento do pipeline de chat no stdout E em logs/chat.log.

    Args:
        tag: rótulo curto tipo "DEBOUNCE", "FLUSH", "LLM", "LLM_RETRY".
        msg: descrição do evento.
        **context: pares chave=valor anexados ao final da linha.

    O log em arquivo tem timestamp ISO8601 UTC para cruzamento com traces.
    O print stdout mantém compatibilidade com os logs legados.
    """
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    ctx = " ".join(f"{k}={v}" for k, v in context.items())
    suffix = f" {ctx}" if ctx else ""
    line = f"[{tag}] {msg}{suffix}"
    _chat_logger.info(f"{ts} {line}")
    print(line, flush=True)

def log_security_event(
    event_type: str,
    user_id_hash: str,
    details: dict | None = None,
) -> None:
    """
    Registra um evento de segurança no log.

    Args:
        event_type: tipo do evento (ex: "INJECTION_DETECTED", "RATE_LIMIT_EXCEEDED")
        user_id_hash: hash SHA-256 truncado do user_id (não PII)
        details: dados adicionais sobre o evento (sem PII)

    Eventos registrados:
        INJECTION_DETECTED      — padrão de prompt injection encontrado
        INPUT_SANITIZED         — input foi modificado na sanitização
        RATE_LIMIT_EXCEEDED     — user_id excedeu limite de mensagens/min
        OUTPUT_FILTERED         — output do agente continha dados sensíveis
        AUTH_FAILED             — tentativa sem Bearer token válido
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "uid": user_id_hash,   # hash, nunca o ID real
        **(details or {}),
    }
    _security_logger.info(json.dumps(record, ensure_ascii=False))

    # Echo no stdout para Railway logs em tempo real
    print(f"[SECURITY] {event_type} uid={user_id_hash} {json.dumps(details or {})}", flush=True)


def log_conversation(
    user_id_hash: str,
    role: str,
    message_length: int,
    channel: str | None = None,
    flags: list[str] | None = None,
) -> None:
    """
    Registra metadados de um turno de conversa (sem o conteúdo completo).

    Args:
        user_id_hash: hash SHA-256 truncado do user_id
        role: "user" ou "assistant"
        message_length: comprimento da mensagem em caracteres
        channel: canal de origem (whatsapp, botmaker, sandbox, api)
        flags: lista de flags de segurança (ex: ["INJECTION_DETECTED"])
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "uid": user_id_hash,
        "role": role,
        "len": message_length,
        "channel": channel or "unknown",
        "flags": flags or [],
    }
    _conv_logger.info(json.dumps(record, ensure_ascii=False))


def get_security_log_path() -> str:
    """Retorna o caminho absoluto do log de segurança."""
    return SECURITY_LOG_PATH


def get_recent_events(n: int = 50) -> list[dict]:
    """
    Retorna os N eventos de segurança mais recentes do log.
    Útil para health check ou dashboard.
    """
    if not os.path.exists(SECURITY_LOG_PATH):
        return []

    try:
        with open(SECURITY_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

        events = []
        for line in reversed(lines[-n:]):
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events
    except Exception:
        return []
