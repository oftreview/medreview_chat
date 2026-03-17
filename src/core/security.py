"""
core/security.py — Camada de segurança do Criatons.

Funções:
  sanitize_input()          — limpa e valida a entrada do usuário
  check_injection_patterns() — detecta tentativas de prompt injection
  filter_output()           — remove dados sensíveis da resposta do agente
  rate_limiter              — controla abuso por user_id (em memória)
"""

import re
import time
import hashlib
import threading
from collections import defaultdict

# ── Constantes ────────────────────────────────────────────────────────────────

MAX_INPUT_LENGTH = 2000          # Caracteres máximos por mensagem
MAX_MESSAGES_PER_MINUTE = 20    # Limite de mensagens por user_id por minuto
RATE_WINDOW_SECONDS = 60        # Janela de tempo do rate limit

# ── Rate limiter em memória ───────────────────────────────────────────────────
# Estrutura: { user_id -> [(timestamp1, timestamp2, ...) ] }
_rate_store: dict = defaultdict(list)
_rate_lock = threading.Lock()


# ── Padrões de injeção de prompt ──────────────────────────────────────────────
# Lista de regex que indicam tentativa de manipulação do sistema
INJECTION_PATTERNS = [
    # Tentativas de redefinir o sistema
    r"ignore\s+(all\s+)?((your|previous|prior|above)\s+)?instructions?",
    r"(esqueça?|ignore|desconsider[ae]).{0,30}(instruções?|regras?|prompt|sistema)",
    r"novo\s+contexto[:\s]",
    r"new\s+context[:\s]",
    r"\bsystem\s*:\s*",
    r"\bassistant\s*:\s*",
    r"\buser\s*:\s*(?!.*medreview)",  # "user:" fora de contexto natural

    # Tentativas de jailbreak
    r"\bDAN\b",
    r"do\s+anything\s+now",
    r"jailbreak",
    r"modo?\s+(developer|dev|deus|god|admin|root)",
    r"you\s+are\s+now\s+(?!a\s+(consultant|sales))",
    r"(agora\s+)?você\s+(é|age\s+como|deve\s+ser)\s+(uma?\s+)?(IA|bot|robô|GPT|Claude|ChatGPT)",
    r"(pretend|imagine|fingir?|simul[ae]).{0,30}(no\s+restrictions?|without\s+limits?|sem\s+restrições?|unrestricted)",

    # Tentativas de extração de prompt
    r"(repita?|repeat|mostre?|show|diga|tell\s+me|print|output)\s+.{0,30}(prompt|instruções?|instructions?|system\s+message)",
    r"what('s|\s+is|\s+are)\s+your\s+(instructions?|system\s+prompt|rules?|guidelines?)",
    r"quais?\s+(são\s+)?(suas?\s+)?(instruções?|regras?|prompt)",

    # Tentativas de roleplay malicioso
    r"(pretend|imagine|fingir?|simul[ae])\s+.{0,20}(you\s+are|que\s+você\s+é)\s+(?!.*medreview)",
    r"act\s+as\s+(?!.*consultant)",
    r"aja\s+como\s+(?!.*consultor)",

    # Injeções de comandos técnicos
    r"<\s*(script|iframe|img|svg|object|embed|link)",
    r"javascript\s*:",
    r"data\s*:\s*text",
    r"\$\{.+\}",          # Template injection
    r"\{\{.+\}\}",        # Jinja/Handlebars injection
]

# Pré-compila os padrões para performance
_compiled_patterns = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in INJECTION_PATTERNS
]

# ── Padrões para filtro de saída ──────────────────────────────────────────────
# Dados sensíveis que nunca devem aparecer na resposta ao lead
OUTPUT_REDACTION_PATTERNS = [
    # Tokens e chaves de API (inclui hifens e underscores que aparecem em tokens reais)
    (re.compile(r'(sk-[a-zA-Z0-9_-]{20,})'), "[TOKEN_REDACTED]"),
    (re.compile(r'\b(eyJ[a-zA-Z0-9_-]{20,})\b'), "[JWT_REDACTED]"),
    (re.compile(r'\b([a-f0-9]{32,64})\b'), "[HASH_REDACTED]"),

    # Números de telefone completos (não fragmentos)
    (re.compile(r'\b55\d{10,11}\b'), "[PHONE_REDACTED]"),

    # E-mails não relacionados ao domínio MedReview
    (re.compile(r'\b[a-zA-Z0-9._%+-]+@(?!medreview)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'), "[EMAIL_REDACTED]"),

    # IPs internos
    (re.compile(r'\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b'), "[IP_REDACTED]"),

    # Caminhos de sistema que nunca devem vazar
    (re.compile(r'/agents/sales/prompts/[^\s]+'), "[PATH_REDACTED]"),
    (re.compile(r'/data/[^\s]+\.json'), "[PATH_REDACTED]"),
    (re.compile(r'ANTHROPIC_API_KEY\s*=?\s*[^\s]+'), "[KEY_REDACTED]"),
    (re.compile(r'SUPABASE_KEY\s*=?\s*[^\s]+'), "[KEY_REDACTED]"),
]

# Frases do system prompt que NUNCA devem aparecer na saída
PROMPT_LEAK_PHRASES = [
    "SEGURANÇA — REGRAS ABSOLUTAS",
    "REGRAS INVIOLÁVEIS",
    "ETAPAS DA CONVERSA",
    "load_context",
    "system_prompt",
    "stage_scripts",
    "INJECTION_PATTERNS",
    "ESCALAÇÃO PARA HUMANO",
    "[SECURITY BLOCK]",
]


def sanitize_input(text: str) -> tuple[str, list[str]]:
    """
    Limpa e valida a entrada do usuário.

    Returns:
        (texto_limpo, lista_de_warnings)

    Warnings são strings descrevendo o que foi encontrado/removido.
    Se retornar warnings críticos, o chamador deve bloquear ou logar.
    """
    warnings = []

    if not text or not isinstance(text, str):
        return "", ["INPUT_EMPTY_OR_INVALID"]

    # 1. Truncar se muito longa
    if len(text) > MAX_INPUT_LENGTH:
        warnings.append(f"INPUT_TRUNCATED:{len(text)}")
        text = text[:MAX_INPUT_LENGTH]

    # 2. Remover caracteres de controle (exceto \n, \t)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # 3. Normalizar espaços múltiplos
    text = re.sub(r'\n{4,}', '\n\n\n', text)   # máx 3 quebras de linha
    text = re.sub(r'[ \t]{5,}', '    ', text)   # máx 4 espaços seguidos

    # 4. Remover tags HTML/script (básico — camada extra antes do Claude)
    html_removed = re.sub(r'<[^>]{0,200}>', '', text)
    if html_removed != text:
        warnings.append("HTML_TAGS_REMOVED")
        text = html_removed

    return text.strip(), warnings


def check_injection_patterns(text: str) -> tuple[bool, list[str]]:
    """
    Verifica se o texto contém padrões de prompt injection.

    Returns:
        (is_suspicious, matched_patterns)

    Se is_suspicious=True, a mensagem deve ser bloqueada ou logada.
    """
    matched = []
    for i, pattern in enumerate(_compiled_patterns):
        if pattern.search(text):
            matched.append(INJECTION_PATTERNS[i][:50])  # log só os primeiros 50 chars do pattern

    return len(matched) > 0, matched


def rate_limiter(user_id: str) -> tuple[bool, int]:
    """
    Verifica se user_id está dentro do limite de mensagens por minuto.

    Returns:
        (allowed, current_count)

    Se allowed=False, a mensagem deve ser rejeitada com HTTP 429.
    """
    now = time.time()
    window_start = now - RATE_WINDOW_SECONDS

    with _rate_lock:
        # Remove timestamps fora da janela
        _rate_store[user_id] = [
            ts for ts in _rate_store[user_id]
            if ts > window_start
        ]
        count = len(_rate_store[user_id])

        if count >= MAX_MESSAGES_PER_MINUTE:
            return False, count

        _rate_store[user_id].append(now)
        return True, count + 1


def filter_output(text: str) -> tuple[str, list[str]]:
    """
    Remove dados sensíveis e fragmentos do system prompt da resposta do agente.

    Returns:
        (texto_filtrado, lista_de_redacoes)

    Redações são registradas para auditoria.
    """
    redactions = []

    # 1. Verificar se o output vaza frases do system prompt
    for phrase in PROMPT_LEAK_PHRASES:
        if phrase.lower() in text.lower():
            redactions.append(f"PROMPT_LEAK:{phrase[:40]}")
            # Substitui pelo fallback seguro
            text = "[Desculpe, ocorreu um erro interno. Em breve um consultor vai te ajudar.]"
            return text, redactions  # para imediatamente — output corrompido

    # 2. Aplicar redações de dados sensíveis
    for pattern, replacement in OUTPUT_REDACTION_PATTERNS:
        new_text, n = pattern.subn(replacement, text)
        if n > 0:
            redactions.append(f"REDACTED:{replacement}(x{n})")
            text = new_text

    return text, redactions


def hash_user_id(user_id: str) -> str:
    """Retorna hash SHA-256 do user_id para logs anônimos."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]
