"""
core/log_buffer.py — Ring buffer para logs ao vivo no dashboard.

Captura prints do sistema via logging handler customizado.
O dashboard faz polling em /api/logs para receber logs novos.
"""
import threading
import time
import re
from collections import deque
from datetime import datetime, timezone, timedelta

# Fuso horário de Brasília (UTC-3)
_BRT = timezone(timedelta(hours=-3))

_lock = threading.Lock()
_buffer = deque(maxlen=2000)
_counter = 0

# Regex para classificar logs por tag
_TAG_PATTERNS = [
    (re.compile(r"\[ERRO|Traceback|Exception|Error", re.I), "error"),
    (re.compile(r"\[SECURITY|INJECTION|RATE_LIMIT|SANITIZ", re.I), "security"),
    (re.compile(r"\[FLUSH\]"), "flush"),
    (re.compile(r"\[DEBOUNCE"), "debounce"),
    (re.compile(r"\[LLM\]|Cache:"), "system"),
    (re.compile(r"\[CONFIG\]"), "system"),
    (re.compile(r"\[CHAT API\]|\[ZAPI\]|\[FORM\]"), "system"),
]


def _classify(msg: str) -> str:
    for pattern, tag in _TAG_PATTERNS:
        if pattern.search(msg):
            return tag
    return "debug"


def add_log(message: str):
    """Adiciona uma entrada de log ao buffer."""
    global _counter
    now = datetime.now(_BRT).strftime("%H:%M:%S")
    tag = _classify(message)

    with _lock:
        _counter += 1
        _buffer.append({
            "id": _counter,
            "time": now,
            "tag": tag,
            "msg": message.strip(),
        })


def get_logs(since: int = 0, limit: int = 200) -> list:
    """Retorna logs com id > since."""
    with _lock:
        result = [entry for entry in _buffer if entry["id"] > since]
    return result[-limit:]


# ── Hook de captura de print/stdout ──────────────────────────────────────────
# Redireciona stdout para capturar prints do sistema automaticamente.

import sys
import io


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
