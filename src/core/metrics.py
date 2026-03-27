"""
Coletor de métricas de uso da API Anthropic.

Singleton thread-safe que acumula tokens, custos e cache hits.
Dual-write: memória (live) + Supabase (persistente).
Alimentado por core/llm.py após cada chamada à API.
"""
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta

# Fuso horário de Brasília (UTC-3)
_BRT = timezone(timedelta(hours=-3))

# Preços por milhão de tokens (input, output)
MODEL_PRICES = {
    "claude-haiku-4-5-20251001":  {"input": 1.0, "output": 5.0},
    "claude-sonnet-4-20250514":   {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-6":          {"input": 3.0, "output": 15.0},
    "claude-opus-4-6":            {"input": 5.0, "output": 25.0},
}

_lock = threading.Lock()

# Acumuladores globais (sessão atual — live)
_totals = {
    "total_calls": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_cache_read": 0,
    "total_cache_write": 0,
    "total_cost": 0.0,
}

# Últimas N chamadas para histórico em memória
_recent_calls = deque(maxlen=50)

# ── Batch para Supabase ──
_persist_buffer = []
_persist_lock = threading.Lock()
_BATCH_SIZE = 10
_FLUSH_INTERVAL = 15  # segundos
_last_flush = time.time()
_persist_enabled = None  # Lazy init


def record_call(model: str, input_tokens: int, output_tokens: int,
                cache_read: int = 0, cache_write: int = 0):
    """Registra uma chamada à API com seus tokens e cache."""
    prices = MODEL_PRICES.get(model, {"input": 3.0, "output": 15.0})
    cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

    now_brt = datetime.now(_BRT)
    time_str = now_brt.strftime("%H:%M:%S")

    with _lock:
        _totals["total_calls"] += 1
        _totals["total_input_tokens"] += input_tokens
        _totals["total_output_tokens"] += output_tokens
        _totals["total_cache_read"] += cache_read
        _totals["total_cache_write"] += cache_write
        _totals["total_cost"] += cost

        _recent_calls.append({
            "time": time_str,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read": cache_read,
            "cache_write": cache_write,
            "cost": round(cost, 6),
            "model": model,
        })

    # Persistir no Supabase
    _enqueue_persist(model, input_tokens, output_tokens,
                     cache_read, cache_write, cost, now_brt)


def get_metrics() -> dict:
    """Retorna snapshot das métricas da sessão atual (memória)."""
    from src.config import CLAUDE_MODEL, MAX_TOKENS

    with _lock:
        return {
            "model": CLAUDE_MODEL,
            "max_tokens": MAX_TOKENS,
            **dict(_totals),
            "total_cost": round(_totals["total_cost"], 6),
            "recent_calls": list(_recent_calls),
        }


# ── Persistência Supabase ────────────────────────────────────

def _enqueue_persist(model, inp, out, cr, cw, cost, ts):
    """Adiciona chamada ao buffer e faz flush se necessário."""
    global _last_flush

    with _persist_lock:
        _persist_buffer.append({
            "model": model,
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read": cr,
            "cache_write": cw,
            "cost": round(cost, 8),
            "created_at": ts.isoformat(),
        })

        should_flush = (
            len(_persist_buffer) >= _BATCH_SIZE
            or (time.time() - _last_flush) >= _FLUSH_INTERVAL
        )

    if should_flush:
        _flush_to_supabase()


def _flush_to_supabase():
    """Envia batch para Supabase (non-blocking)."""
    global _last_flush, _persist_enabled

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

    with _persist_lock:
        if not _persist_buffer:
            return
        batch = list(_persist_buffer)
        _persist_buffer.clear()
        _last_flush = time.time()

    t = threading.Thread(target=_do_insert, args=(batch,), daemon=True)
    t.start()


def _do_insert(batch: list):
    """Insere batch no Supabase (roda em thread)."""
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if db and batch:
            db.table("llm_usage").insert(batch).execute()
    except Exception:
        pass  # Silenciar — não travar o sistema por falha de persistência


# ── Consultas históricas (Supabase) ──────────────────────────

def get_history(
    model: str = None,
    date_from: str = None,
    date_to: str = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Consulta uso LLM persistido no Supabase."""
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if not db:
            return {"calls": [], "total": 0, "page": 1, "pages": 0}

        query = db.table("llm_usage").select("*", count="exact")

        if model and model != "all":
            query = query.eq("model", model)
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lt("created_at", date_to + "T23:59:59+00:00")

        offset = (page - 1) * per_page
        query = query.order("created_at", desc=True).range(offset, offset + per_page - 1)

        result = query.execute()
        total = result.count if result.count is not None else len(result.data or [])

        return {
            "calls": result.data or [],
            "total": total,
            "page": page,
            "pages": max(1, -(-total // per_page)),
        }
    except Exception as e:
        return {"calls": [], "total": 0, "page": 1, "pages": 0, "error": str(e)}


def get_daily_stats(days_back: int = 30) -> list:
    """Retorna estatísticas diárias para gráficos."""
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if not db:
            return []
        result = db.rpc("llm_daily_stats", {"days_back": days_back}).execute()
        return result.data or []
    except Exception:
        return []


def get_totals(since: str = None) -> dict:
    """Retorna totais acumulados (all-time ou desde uma data)."""
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if not db:
            return {}
        params = {"since": since} if since else {"since": None}
        result = db.rpc("llm_totals", params).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return {}
    except Exception:
        return {}
