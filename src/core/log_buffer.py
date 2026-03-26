"""
core/log_buffer.py — Ring buffer para logs ao vivo + persistência no Supabase.

Captura prints do sistema via logging handler customizado.
O dashboard faz polling em /api/logs para receber logs novos (tempo real).
Logs também são salvos no Supabase em batch para consulta histórica.
"""
import threading
import time
import re
import sys
import io
from collections import deque
from datetime import datetime, timezone, timedelta

# Fuso horário de Brasília (UTC-3)
_BRT = timezone(timedelta(hours=-3))

_lock = threading.Lock()
_buffer = deque(maxlen=2000)
_counter = 0

# ── Batch para Supabase ──
_persist_buffer = []
_persist_lock = threading.Lock()
_BATCH_SIZE = 20        # Envia a cada N logs
_FLUSH_INTERVAL = 10    # Ou a cada N segundos
_last_flush = time.time()
_persist_enabled = None  # Lazy init

# Regex para classificar logs por tag
_TAG_PATTERNS = [
    (re.compile(r"\[ERRO|Traceback|Exception|Error", re.I), "error"),
    (re.compile(r"\[SECURITY|INJECTION|RATE_LIMIT|SANITIZ", re.I), "security"),
    (re.compile(r"\[FLUSH\]"), "flush"),
    (re.compile(r"\[DEBOUNCE"), "debounce"),
    (re.compile(r"\[LLM\]|Cache:"), "system"),
    (re.compile(r"\[CONFIG\]"), "system"),
    (re.compile(r"\[CHAT API\]|\[ZAPI\]|\[FORM\]"), "system"),
    (re.compile(r"\[DB\]|\[WM\]|\[SHADOW\]|\[CONTEXT\]|\[LIFECYCLE\]"), "system"),
    (re.compile(r"\[SCHEDULER\]|\[CRON\]|\[MAINTENANCE\]"), "system"),
]

# Regex para extrair source
_SOURCE_PATTERNS = [
    (re.compile(r"\[DB\]"), "database"),
    (re.compile(r"\[LLM\]"), "llm"),
    (re.compile(r"\[CHAT API\]"), "chat"),
    (re.compile(r"\[ZAPI\]"), "zapi"),
    (re.compile(r"\[FORM\]"), "form"),
    (re.compile(r"\[CONFIG\]"), "config"),
    (re.compile(r"\[SECURITY|INJECTION|RATE_LIMIT|SANITIZ"), "security"),
    (re.compile(r"\[SHADOW\]|\[WM\]"), "wild_memory"),
    (re.compile(r"\[CONTEXT\]"), "context"),
    (re.compile(r"\[LIFECYCLE\]|\[MAINTENANCE\]"), "lifecycle"),
    (re.compile(r"\[SCHEDULER\]|\[CRON\]"), "scheduler"),
    (re.compile(r"\[FLUSH\]"), "flush"),
    (re.compile(r"\[DEBOUNCE"), "debounce"),
]


def _classify(msg: str) -> str:
    for pattern, tag in _TAG_PATTERNS:
        if pattern.search(msg):
            return tag
    return "debug"


def _extract_source(msg: str) -> str:
    for pattern, source in _SOURCE_PATTERNS:
        if pattern.search(msg):
            return source
    return "app"


def add_log(message: str):
    """Adiciona uma entrada de log ao buffer em memória e ao batch de persistência."""
    global _counter
    msg = message.strip()
    if not msg:
        return

    now_brt = datetime.now(_BRT)
    time_str = now_brt.strftime("%H:%M:%S")
    tag = _classify(msg)
    source = _extract_source(msg)

    with _lock:
        _counter += 1
        _buffer.append({
            "id": _counter,
            "time": time_str,
            "tag": tag,
            "msg": msg,
        })

    # Adicionar ao batch de persistência
    _enqueue_persist(tag, source, msg, now_brt)


def _enqueue_persist(tag: str, source: str, message: str, ts: datetime):
    """Adiciona log ao buffer de persistência e faz flush se necessário."""
    global _last_flush

    with _persist_lock:
        _persist_buffer.append({
            "tag": tag,
            "source": source,
            "message": message[:2000],  # Limitar tamanho
            "created_at": ts.isoformat(),
        })

        should_flush = (
            len(_persist_buffer) >= _BATCH_SIZE
            or (time.time() - _last_flush) >= _FLUSH_INTERVAL
        )

    if should_flush:
        _flush_to_supabase()


def _flush_to_supabase():
    """Envia batch de logs para o Supabase (non-blocking)."""
    global _last_flush, _persist_enabled

    # Lazy check se persistência está habilitada
    if _persist_enabled is None:
        try:
            from src.core.database.client import is_enabled
            _persist_enabled = is_enabled()
        except Exception:
            _persist_enabled = False

    if not _persist_enabled:
        with _persist_lock:
            _persist_buffer.clear()
            _last_flush = time.time()
        return

    # Pegar batch atual
    with _persist_lock:
        if not _persist_buffer:
            return
        batch = list(_persist_buffer)
        _persist_buffer.clear()
        _last_flush = time.time()

    # Enviar em thread separada para não bloquear
    t = threading.Thread(target=_do_insert, args=(batch,), daemon=True)
    t.start()


def _do_insert(batch: list):
    """Insere batch no Supabase (roda em thread)."""
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if db and batch:
            db.table("system_logs").insert(batch).execute()
    except Exception:
        # Silenciar erros de persistência para não travar o sistema
        pass


def get_logs(since: int = 0, limit: int = 200) -> list:
    """Retorna logs em memória com id > since."""
    with _lock:
        result = [entry for entry in _buffer if entry["id"] > since]
    return result[-limit:]


def get_history(
    tag: str = None,
    source: str = None,
    search: str = None,
    date_from: str = None,
    date_to: str = None,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    """
    Consulta logs persistidos no Supabase com filtros.
    Retorna: { logs: [...], total: int, page: int, pages: int }
    """
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if not db:
            return {"logs": [], "total": 0, "page": 1, "pages": 0}

        # Query com filtros
        query = db.table("system_logs").select("*", count="exact")

        if tag and tag != "all":
            query = query.eq("tag", tag)
        if source and source != "all":
            query = query.eq("source", source)
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            # Adicionar 1 dia para incluir o dia inteiro
            query = query.lt("created_at", date_to + "T23:59:59+00:00")
        if search:
            query = query.ilike("message", f"%{search}%")

        # Paginação
        offset = (page - 1) * per_page
        query = query.order("created_at", desc=True).range(offset, offset + per_page - 1)

        result = query.execute()
        total = result.count if result.count is not None else len(result.data or [])

        return {
            "logs": result.data or [],
            "total": total,
            "page": page,
            "pages": max(1, -(-total // per_page)),  # ceil division
        }
    except Exception as e:
        return {"logs": [], "total": 0, "page": 1, "pages": 0, "error": str(e)}


def get_daily_stats(days_back: int = 30) -> list:
    """Retorna estatísticas diárias de logs para o calendário."""
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if not db:
            return []
        result = db.rpc("logs_daily_stats", {"days_back": days_back}).execute()
        return result.data or []
    except Exception:
        return []


def get_sources() -> list:
    """Retorna lista distinta de sources para o filtro."""
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if not db:
            return []
        result = db.table("system_logs").select("source").limit(500).execute()
        sources = list(set(r["source"] for r in (result.data or []) if r.get("source")))
        sources.sort()
        return sources
    except Exception:
        return []


# ── Hook de captura de print/stdout ──────────────────────────────────────────

class _LogCapture(io.TextIOBase):
    """Wrapper de stdout que intercepta writes e os salva no buffer."""

    def __init__(self, original):
        self._original = original

    def write(self, text):
        if text and text.strip():
            add_log(text)
        return self._original.write(text)

    def flush(self):
        return self._original.flush()

    def fileno(self):
        return self._original.fileno()

    def isatty(self):
        return self._original.isatty()


def install():
    """Instala o hook de captura. Chamar uma vez na inicialização."""
    if not isinstance(sys.stdout, _LogCapture):
        sys.stdout = _LogCapture(sys.stdout)
        sys.stderr = _LogCapture(sys.stderr)
