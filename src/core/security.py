"""
core/security.py — Camada de segurança do Closi AI.

Funções:
  sanitize_input()           — limpa e valida a entrada do usuário
  check_injection_patterns() — detecta tentativas de prompt injection
  check_media_attachment()   — detecta/bloqueia anexos maliciosos
  filter_output()            — remove dados sensíveis da resposta do agente
  check_data_extraction()    — detecta tentativas de extração de dados sensíveis
  rate_limiter               — controla abuso por user_id (em memória)
  injection_tracker          — rastreia reincidência de injection por user_id
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

# Número máximo de tentativas de injection antes de bloquear o user_id
MAX_INJECTION_STRIKES = 3
INJECTION_STRIKE_WINDOW = 300   # 5 minutos

# Resposta padrão ao bloquear mensagem suspeita
INJECTION_BLOCK_RESPONSE = (
    "Posso te ajudar com informações sobre os preparatórios da MedReview. "
    "Como posso te ajudar?"
)

# ── Rate limiter em memória ───────────────────────────────────────────────────
_rate_store: dict = defaultdict(list)
_rate_lock = threading.Lock()

# ── Injection strike tracker ─────────────────────────────────────────────────
# { user_id -> [timestamp1, timestamp2, ...] }
_injection_strikes: dict = defaultdict(list)
_injection_lock = threading.Lock()


# ── Padrões de injeção de prompt ──────────────────────────────────────────────
# Lista de regex que indicam tentativa de manipulação do sistema
INJECTION_PATTERNS = [
    # ── Tentativas de redefinir o sistema ────────────────────────────────────
    r"ignore\s+(all\s+)?((your|previous|prior|above)\s+)?instructions?",
    r"(esqueça?|ignore|desconsider[ae]).{0,30}(instruções?|regras?|prompt|sistema)",
    r"novo\s+contexto\s*[:\-]\s*",   # "novo contexto:" mas não "novo contexto de estudo"
    r"new\s+context\s*[:\-]\s*",
    r"\bsystem\s*:\s*",
    r"\bassistant\s*:\s*",
    r"\buser\s*:\s*(?!.*medreview)",

    # ── Tentativas de jailbreak ──────────────────────────────────────────────
    r"\bDAN\b",
    r"do\s+anything\s+now",
    r"jailbreak",
    r"modo?\s+(developer|dev|deus|god|admin|root)",
    r"you\s+are\s+now\s+(?!a\s+(consultant|sales))",
    r"(agora\s+)?você\s+(é|age\s+como|deve\s+ser)\s+(uma?\s+)?(IA|bot|robô|GPT|Claude|ChatGPT)",
    r"(pretend|imagine|fingir?|simul[ae]).{0,30}(no\s+restrictions?|without\s+limits?|sem\s+restrições?|unrestricted)",

    # ── Tentativas de extração de prompt ─────────────────────────────────────
    r"(repita?|repeat|mostre?|show|diga|tell\s+me|print|output)\s+.{0,30}(prompt|instruções?|instructions?|system\s+message)",
    r"what('s|\s+is|\s+are)\s+your\s+(instructions?|system\s+prompt|rules?|guidelines?)",
    r"quais?\s+(são\s+)?(suas?\s+)?(instruções?|regras?|prompt)",
    r"(cole|copie|transcreva|paste|copy).{0,30}(prompt|instruções?|instructions?)",
    r"(diga|fale|tell).{0,20}(palavra\s+por\s+palavra|verbatim|exatamente)",

    # ── Tentativas de roleplay malicioso ─────────────────────────────────────
    r"(pretend|imagine|finja|fingir|simul[ae])\s+.{0,30}(you\s+are|que\s+(você\s+é|vc\s+é))\s+(?!.*medreview|.*consultor)",
    r"act\s+as\s+(?!.*consultant)",
    r"aja\s+como\s+.{0,50}(outra\s+empresa|hacker|sem\s+filtro|sem\s+restrição|sem\s+limite)",
    r"(responda|respond)\s+como\s+(?!.*consultor|.*medreview)",

    # ── Injeções de comandos técnicos ────────────────────────────────────────
    r"<\s*(script|iframe|img|svg|object|embed|link)",
    r"javascript\s*:",
    r"data\s*:\s*text",
    r"\$\{.+\}",
    r"\{\{.+\}\}",

    # ── Tentativas de manipulação de contexto ────────────────────────────────
    r"(a\s+partir\s+de\s+agora|from\s+now\s+on).{0,40}(ignore|esqueça|forget|novo|new)",
    r"(override|sobrescrever?|substituir?).{0,30}(regras?|rules?|config|system)",
    r"(admin|root|sudo|superuser)\s+(mode|modo|access|acesso)",
    r"(debug|developer|dev)\s+(mode|modo|console|tools)",
    r"(token|api.?key|senha|password|secret)\s*[:=]",

    # ── Encoding/ofuscação ───────────────────────────────────────────────────
    r"base64[:\s]",
    r"\\x[0-9a-fA-F]{2}",     # hex escape sequences
    r"\\u[0-9a-fA-F]{4}",     # unicode escape sequences
    r"rot13",
    r"(decode|decodificar?|decrypt|descriptograf)",
]

# Pré-compila os padrões para performance
_compiled_patterns = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in INJECTION_PATTERNS
]


# ── Padrões de extração de dados sensíveis ───────────────────────────────────
# Detectam quando alguém tenta extrair informações de outros clientes ou do sistema
DATA_EXTRACTION_PATTERNS = [
    # Pedidos de dados de outros clientes/leads
    r"(dados?|informaç[õo]es?|histórico|conversa[s]?)\s+d[eoa]s?\s+(outros?|demais|próximo|anterior)\s+(clientes?|leads?|alunos?|usuários?|contatos?|pessoas?)",
    r"(quantos?|quais?|liste?|mostre?|quem)\s+.{0,30}(clientes?|leads?|alunos?|sessões?|usuários?|contatos?)",
    r"(lista|banco|base)\s+de\s+(clientes?|leads?|dados?|contatos?|alunos?|e-?mails?|telefones?)",
    r"(todos?\s+os?|all\s+the?)\s+(clientes?|leads?|alunos?|dados?|sessões?|sessions?|users?)",
    r"(me\s+)?pass[ae]\s+.{0,20}(dados?|lista|contatos?|telefones?|emails?)",

    # Pedidos de informação do sistema/infra
    r"(qual|what).{0,20}(banco\s+de\s+dados|database|servidor|server|infra|arquitetura)",
    r"(mostre?|show|liste?|list|diga|tell).{0,20}(endpoints?|api\s+routes?|rotas?|urls?)",
    r"(qual|quais?|what).{0,20}(modelo|model|versão|version).{0,20}(IA|AI|claude|gpt|llm)",
    r"(supabase|railway|anthropic|openai|api)\s*(url|key|token|secret|endpoint)",
    r"(variáveis?|variables?|variavel)\s+de\s+(ambiente|environment|env)",
    r"(variável|variáveis|variavel)\s+.{0,20}(banco|database|servidor|server|api|supabase|railway)",

    # Pedidos de preço/dados comerciais internos
    r"(margem|comissão|custo\s+real|markup|margem\s+de\s+lucro)",
    r"(quanto\s+custa|cost)\s+.{0,20}(pra\s+vocês?|for\s+you|internamente|internally)",
    r"(tabela|planilha|spreadsheet).{0,20}(intern[ao]|segred[ao]|confidencial|internal)",

    # Tentativas de dump/export de dados
    r"(export[ae]r?|dump|baixar|download).{0,30}(dados?|data|banco|database|histórico|conversas?)",
    r"(SQL|query|consulta).{0,20}(banco|database|tabela|table)",
    r"SELECT\s+.+\s+FROM",
    r"(INSERT|UPDATE|DELETE|DROP|ALTER)\s+",
]

_compiled_data_extraction = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in DATA_EXTRACTION_PATTERNS
]


# ── Detecção de mídia/anexos maliciosos ──────────────────────────────────────

# Extensões de arquivo que devem ser bloqueadas se detectadas em mensagens
BLOCKED_FILE_EXTENSIONS = {
    # Executáveis
    ".exe", ".bat", ".cmd", ".com", ".scr", ".pif", ".msi", ".msp",
    ".ps1", ".vbs", ".vbe", ".js", ".jse", ".ws", ".wsf", ".wsc",
    ".sh", ".bash", ".csh", ".ksh",
    # Scripts/macros
    ".hta", ".inf", ".reg", ".rgs", ".sct",
    ".docm", ".xlsm", ".pptm",  # Office com macros
    # Comprimidos (podem conter executáveis)
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2",
    # Outros perigosos
    ".iso", ".img", ".dmg",
    ".apk", ".ipa",  # apps mobile
    ".dll", ".sys", ".drv",
    ".lnk", ".url",  # atalhos
    ".svg",  # pode conter scripts
}

# Extensões de mídia permitidas (áudio, imagem, vídeo comuns do WhatsApp)
ALLOWED_MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",  # imagens
    ".mp3", ".ogg", ".opus", ".m4a", ".aac", ".wav",   # áudio
    ".mp4", ".3gp", ".mov", ".avi", ".webm", ".mkv",   # vídeo
    ".pdf",                                              # documentos
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", # Office sem macro
    ".txt", ".csv",                                      # texto
}

# Padrões de URL/link maliciosos
MALICIOUS_URL_PATTERNS = [
    r"https?://[^\s]*\.(exe|bat|cmd|scr|ps1|vbs|hta|msi)\b",
    r"https?://bit\.ly/[^\s]+",     # encurtadores (podem esconder malware)
    r"https?://tinyurl\.com/[^\s]+",
    r"https?://t\.co/[^\s]+",
    r"https?://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}",  # IPs diretos
    r"https?://[^\s]*@[^\s]+",       # URLs com credentials embutidas
]

_compiled_malicious_urls = [
    re.compile(p, re.IGNORECASE)
    for p in MALICIOUS_URL_PATTERNS
]


# ── Padrões para filtro de saída ──────────────────────────────────────────────
# Dados sensíveis que nunca devem aparecer na resposta ao lead
OUTPUT_REDACTION_PATTERNS = [
    # Tokens e chaves de API
    (re.compile(r'(sk-[a-zA-Z0-9_-]{20,})'), "[TOKEN_REDACTED]"),
    (re.compile(r'\b(eyJ[a-zA-Z0-9_-]{20,})\b'), "[JWT_REDACTED]"),
    (re.compile(r'\b([a-f0-9]{32,64})\b'), "[HASH_REDACTED]"),

    # Números de telefone completos (não fragmentos)
    (re.compile(r'\b55\d{10,11}\b'), "[PHONE_REDACTED]"),

    # E-mails não relacionados ao domínio MedReview
    (re.compile(r'\b[a-zA-Z0-9._%+-]+@(?!medreview|grupomedreview)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'), "[EMAIL_REDACTED]"),

    # IPs internos
    (re.compile(r'\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b'), "[IP_REDACTED]"),

    # Caminhos de sistema que nunca devem vazar
    (re.compile(r'/agents/sales/prompts/[^\s]+'), "[PATH_REDACTED]"),
    (re.compile(r'/data/[^\s]+\.json'), "[PATH_REDACTED]"),
    (re.compile(r'src/[^\s]+\.py'), "[PATH_REDACTED]"),
    (re.compile(r'ANTHROPIC_API_KEY\s*=?\s*[^\s]+'), "[KEY_REDACTED]"),
    (re.compile(r'OPENROUTER_API_KEY\s*=?\s*[^\s]+'), "[KEY_REDACTED]"),
    (re.compile(r'SUPABASE_KEY\s*=?\s*[^\s]+'), "[KEY_REDACTED]"),
    (re.compile(r'SUPABASE_URL\s*=?\s*[^\s]+'), "[KEY_REDACTED]"),
    (re.compile(r'API_SECRET_TOKEN\s*=?\s*[^\s]+'), "[KEY_REDACTED]"),
    (re.compile(r'HUBSPOT_[A-Z_]*\s*=?\s*[^\s]+'), "[KEY_REDACTED]"),

    # UUIDs que podem ser session_ids de outros leads
    (re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b'), "[ID_REDACTED]"),

    # Conexão Supabase / PostgreSQL
    (re.compile(r'postgres(ql)?://[^\s]+'), "[DB_CONN_REDACTED]"),
    (re.compile(r'(connection\s*string|dsn|database\s*url)\s*[:=]\s*[^\s]+', re.IGNORECASE), "[DB_CONN_REDACTED]"),
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
    "REGRA SUPREMA DE COMUNICAÇÃO",
    "CORREÇÕES OBRIGATÓRIAS",
    "DESQUALIFICAÇÃO",
    "Desqualifique com respeito",
    "wild_memory",
    "async_bridge",
    "call_claude",
    "SalesAgent",
    "ConversationMemory",
    "filter_output",
    "sanitize_input",
    "_flush_and_respond",
    "PROMPT_LEAK_PHRASES",
    "OUTPUT_REDACTION",
    "cache_control",
    "ephemeral",
    "BÍBLIA DE CONVERSÃO",
    "TÉCNICAS DE VENDAS",
    "conversion_bible",
    "sales_techniques",
    "commercial_rules",
]

# Frases que indicam que o agente está vazando sua estrutura interna
STRUCTURAL_LEAK_PATTERNS = [
    re.compile(r"(meu|my)\s+(system\s+)?prompt\s+(diz|says|instrui|instructs|contém|contains)", re.IGNORECASE),
    re.compile(r"(fui|sou|I\s+am|I\s+was)\s+(programad|instruíd|configurad|designed|built|trained)\s+(para|to)", re.IGNORECASE),
    re.compile(r"(minhas|my)\s+(instruções|instructions|regras|rules)\s+(dizem|say|incluem|include)", re.IGNORECASE),
    re.compile(r"(segundo|according\s+to)\s+(meu|my)\s+(prompt|instruções|instructions|treinamento|training)", re.IGNORECASE),
    re.compile(r"(eu\s+uso|I\s+use|utilizo)\s+(Claude|GPT|Anthropic|OpenAI|LLM|modelo)", re.IGNORECASE),
    re.compile(r"(estou\s+rodando|I\s+run)\s+(em|on)\s+(Railway|Supabase|Heroku|AWS|server)", re.IGNORECASE),
]


def sanitize_input(text: str) -> tuple[str, list[str]]:
    """
    Limpa e valida a entrada do usuário.

    Returns:
        (texto_limpo, lista_de_warnings)
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
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    text = re.sub(r'[ \t]{5,}', '    ', text)

    # 4. Remover tags HTML/script (detectar script/iframe ANTES de limpar)
    if re.search(r'<\s*(script|iframe|object|embed|svg|img\s+[^>]*onerror)', text, re.IGNORECASE):
        warnings.append("DANGEROUS_HTML_TAG")
    html_removed = re.sub(r'<[^>]{0,200}>', '', text)
    if html_removed != text:
        warnings.append("HTML_TAGS_REMOVED")
        text = html_removed

    # 5. Detectar e neutralizar caracteres Unicode suspeitos (homoglyphs, zero-width)
    # Zero-width chars usados para esconder texto
    zwc_removed = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]', '', text)
    if zwc_removed != text:
        warnings.append("ZERO_WIDTH_CHARS_REMOVED")
        text = zwc_removed

    return text.strip(), warnings


def check_injection_patterns(text: str) -> tuple[bool, list[str]]:
    """
    Verifica se o texto contém padrões de prompt injection.

    Returns:
        (is_suspicious, matched_patterns)
    """
    matched = []
    for i, pattern in enumerate(_compiled_patterns):
        if pattern.search(text):
            matched.append(INJECTION_PATTERNS[i][:50])

    return len(matched) > 0, matched


def check_data_extraction(text: str) -> tuple[bool, list[str]]:
    """
    Verifica se o texto tenta extrair dados sensíveis de outros clientes,
    do sistema ou do banco de dados.

    Returns:
        (is_extraction_attempt, matched_patterns)
    """
    matched = []
    for i, pattern in enumerate(_compiled_data_extraction):
        if pattern.search(text):
            matched.append(DATA_EXTRACTION_PATTERNS[i][:50])

    return len(matched) > 0, matched


def check_media_attachment(text: str) -> tuple[bool, str, list[str]]:
    """
    Analisa a mensagem em busca de referências a arquivos ou mídias maliciosas.

    No WhatsApp via Botmaker, anexos chegam como URLs ou referências de mídia.
    Esta função verifica:
      1. URLs com extensões perigosas
      2. URLs maliciosas (IPs diretos, encurtadores, credentials embutidas)
      3. Menções a tipos de arquivo bloqueados

    Returns:
        (is_blocked, block_reason, warnings)

    Se is_blocked=True, a mensagem deve ser rejeitada.
    """
    warnings = []
    text_lower = text.lower()

    # 1. Verificar URLs maliciosas
    for pattern in _compiled_malicious_urls:
        match = pattern.search(text)
        if match:
            url = match.group(0)[:60]
            warnings.append(f"MALICIOUS_URL:{url}")
            return True, f"URL suspeita detectada", warnings

    # 2. Verificar extensões de arquivo em URLs ou menções
    # Exclui TLDs comuns para evitar falsos positivos com URLs normais
    _COMMON_TLDS = {".com", ".net", ".org", ".io", ".br", ".gov", ".edu", ".co", ".me", ".app", ".dev", ".ai"}
    # Captura nomes de arquivo com extensão (ignora domain parts de URLs)
    file_refs = re.findall(r'(?:^|[\s/\\])[\w.-]+\.(\w{2,5})\b', text_lower)
    for ext in file_refs:
        full_ext = f".{ext}"
        if full_ext in _COMMON_TLDS:
            continue
        if full_ext in BLOCKED_FILE_EXTENSIONS:
            warnings.append(f"BLOCKED_FILE_EXT:{full_ext}")
            return True, f"Tipo de arquivo bloqueado: {full_ext}", warnings

    # 3. Verificar se há tentativa de enviar código/payload como texto
    code_indicators = [
        (r'<script[\s>]', "SCRIPT_TAG"),
        (r'eval\s*\(', "EVAL_CALL"),
        (r'exec\s*\(', "EXEC_CALL"),
        (r'import\s+os\b', "IMPORT_OS"),
        (r'__import__', "DUNDER_IMPORT"),
        (r'subprocess', "SUBPROCESS"),
        (r'os\.system', "OS_SYSTEM"),
        (r'curl\s+', "CURL_CMD"),
        (r'wget\s+', "WGET_CMD"),
    ]
    for pattern, label in code_indicators:
        if re.search(pattern, text, re.IGNORECASE):
            warnings.append(f"CODE_PAYLOAD:{label}")

    if warnings:
        return False, "", warnings  # não bloqueia, mas loga

    return False, "", []


def record_injection_strike(user_id: str) -> tuple[bool, int]:
    """
    Registra uma tentativa de injection para o user_id.
    Retorna (is_blocked, total_strikes).

    Se o user_id acumulou >= MAX_INJECTION_STRIKES em INJECTION_STRIKE_WINDOW,
    ele fica bloqueado (todas as mensagens são rejeitadas até a janela expirar).
    """
    now = time.time()
    window_start = now - INJECTION_STRIKE_WINDOW

    with _injection_lock:
        # Limpa strikes antigos
        _injection_strikes[user_id] = [
            ts for ts in _injection_strikes[user_id]
            if ts > window_start
        ]
        _injection_strikes[user_id].append(now)
        count = len(_injection_strikes[user_id])

    return count >= MAX_INJECTION_STRIKES, count


def is_user_blocked(user_id: str) -> bool:
    """
    Verifica se um user_id está bloqueado por excesso de tentativas de injection.
    """
    now = time.time()
    window_start = now - INJECTION_STRIKE_WINDOW

    with _injection_lock:
        strikes = [
            ts for ts in _injection_strikes.get(user_id, [])
            if ts > window_start
        ]

    return len(strikes) >= MAX_INJECTION_STRIKES


def rate_limiter(user_id: str) -> tuple[bool, int]:
    """
    Verifica se user_id está dentro do limite de mensagens por minuto.

    Returns:
        (allowed, current_count)
    """
    now = time.time()
    window_start = now - RATE_WINDOW_SECONDS

    with _rate_lock:
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
    """
    redactions = []

    # 1. Verificar se o output vaza frases do system prompt
    text_lower = text.lower()
    for phrase in PROMPT_LEAK_PHRASES:
        if phrase.lower() in text_lower:
            redactions.append(f"PROMPT_LEAK:{phrase[:40]}")
            text = "[Desculpe, ocorreu um erro interno. Em breve um consultor vai te ajudar.]"
            return text, redactions

    # 2. Verificar se o agente está revelando sua estrutura interna
    for pattern in STRUCTURAL_LEAK_PATTERNS:
        if pattern.search(text):
            redactions.append(f"STRUCTURAL_LEAK:{pattern.pattern[:40]}")
            text = "[Desculpe, ocorreu um erro interno. Em breve um consultor vai te ajudar.]"
            return text, redactions

    # 3. Aplicar redações de dados sensíveis
    for pattern, replacement in OUTPUT_REDACTION_PATTERNS:
        new_text, n = pattern.subn(replacement, text)
        if n > 0:
            redactions.append(f"REDACTED:{replacement}(x{n})")
            text = new_text

    return text, redactions


def hash_user_id(user_id: str) -> str:
    """Retorna hash SHA-256 do user_id para logs anônimos."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]
