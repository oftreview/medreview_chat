"""
Coletor de métricas de uso da API LLM (via OpenRouter).

Singleton thread-safe que acumula tokens e custos.
Dual-write: memória (live) + Supabase (persistente).
Alimentado por core/llm.py após cada chamada à API.

Nota: campos cache_read/cache_write permanecem na estrutura (compat com schema
e dashboards legados) mas serão sempre 0 — OpenRouter é chamado sem caching.
"""
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta

# Fuso horário de Brasília (UTC-3)
_BRT = timezone(timedelta(hours=-3))

# Preços por milhão de tokens (input, output) — slugs do OpenRouter
MODEL_PRICES = {
    "anthropic/claude-haiku-4-5":  {"input": 1.0, "output": 5.0},
    "anthropic/claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "anthropic/claude-opus-4":     {"input": 15.0, "output": 75.0},
    "openai/gpt-4o-mini":          {"input": 0.15, "output": 0.6},
    "openai/gpt-4o":               {"input": 2.5, "output": 10.0},
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
_BATCH_SIZE = 1   # Flush a cada chamada (garante persistência imediata)
_FLUSH_INTERVAL = 5  # segundos
_last_flush = time.time()
_persist_enabled = None  # Lazy init
_persist_failures = 0     # Contador de falhas consecutivas
_MAX_PERSIST_FAILURES = 5  # Depois de N falhas, pausa temporariamente
_persist_retry_after = 0   # Timestamp para tentar novamente


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
    from src.config import OPENROUTER_MODEL, MAX_TOKENS

    with _lock:
        return {
            "model": OPENROUTER_MODEL,
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
    global _last_flush, _persist_enabled, _persist_failures, _persist_retry_after

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

    # Se muitas falhas consecutivas, pausa temporariamente (retry a cada 60s)
    if _persist_failures >= _MAX_PERSIST_FAILURES:
        if time.time() < _persist_retry_after:
            return  # Mantém buffer — não descarta
        # Tempo de retry chegou — reseta contador e tenta de novo
        _persist_failures = 0
        print("[METRICS] Retentando persistência após pausa...", flush=True)

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
    global _persist_failures, _persist_retry_after
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if db and batch:
            db.table("llm_usage").insert(batch).execute()
            _persist_failures = 0  # Reset no sucesso
            print(f"[METRICS] Persistido {len(batch)} registro(s) na tabela llm_usage", flush=True)
    except Exception as e:
        err = str(e)
        _persist_failures += 1
        _persist_retry_after = time.time() + 60  # Retry em 60s após muitas falhas
        print(f"[METRICS WARN] Falha ao persistir llm_usage ({_persist_failures}x): {err}", flush=True)
        if "does not exist" in err or "relation" in err:
            print("[METRICS] Tabela llm_usage não encontrada! Execute a migration 007 no Supabase SQL Editor.", flush=True)


# ── Diagnóstico ────────────────────────────────────────────────

def check_table_status() -> dict:
    """Verifica se a tabela llm_usage existe e está acessível."""
    result = {
        "table_exists": False,
        "row_count": 0,
        "rpc_available": False,
        "error": None,
        "supabase_enabled": False,
    }

    try:
        from src.core.database.client import is_enabled, _get_client
        result["supabase_enabled"] = is_enabled()

        if not is_enabled():
            result["error"] = "SUPABASE_URL ou SUPABASE_KEY não configurados"
            return result

        db = _get_client()
        if not db:
            result["error"] = "Cliente Supabase não inicializado"
            return result

        # Testa se a tabela existe fazendo um SELECT simples
        try:
            test = db.table("llm_usage").select("id", count="exact").limit(1).execute()
            result["table_exists"] = True
            result["row_count"] = test.count if test.count is not None else len(test.data or [])
        except Exception as e:
            err = str(e)
            if "does not exist" in err or "relation" in err:
                result["error"] = "Tabela llm_usage não existe. Execute a migration 007_llm_usage.sql no Supabase SQL Editor."
            else:
                result["error"] = f"Erro ao acessar llm_usage: {err}"
            return result

        # Testa se as RPCs existem
        try:
            db.rpc("llm_totals", {"since": None}).execute()
            result["rpc_available"] = True
        except Exception:
            result["rpc_available"] = False  # Funciona sem RPC (usa fallback)

    except Exception as e:
        result["error"] = f"Erro inesperado: {str(e)}"

    return result


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
    """
    Retorna estatísticas diárias para gráficos.
    Consulta diretamente a tabela llm_usage (sem depender de RPC).
    """
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if not db:
            return []

        # Tenta RPC primeiro (mais eficiente se existir)
        try:
            result = db.rpc("llm_daily_stats", {"days_back": days_back}).execute()
            if result.data:
                # Normaliza tipos (NUMERIC vira string em alguns drivers)
                normalized = []
                for row in result.data:
                    normalized.append({
                        "day": str(row.get("day", "")),
                        "total_calls": int(row.get("total_calls", 0) or 0),
                        "total_input": int(row.get("total_input", 0) or 0),
                        "total_output": int(row.get("total_output", 0) or 0),
                        "total_cache_read": int(row.get("total_cache_read", 0) or 0),
                        "total_cache_write": int(row.get("total_cache_write", 0) or 0),
                        "total_cost": float(row.get("total_cost", 0) or 0),
                    })
                print(f"[METRICS] get_daily_stats via RPC: {len(normalized)} dias, cost_sum=${sum(r['total_cost'] for r in normalized):.4f}", flush=True)
                return normalized
        except Exception as e:
            print(f"[METRICS] RPC llm_daily_stats falhou: {e}, usando fallback", flush=True)

        # Fallback: busca registros e agrupa no Python
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

        result = (
            db.table("llm_usage")
            .select("created_at, input_tokens, output_tokens, cache_read, cache_write, cost")
            .gte("created_at", cutoff)
            .order("created_at", desc=False)
            .limit(5000)
            .execute()
        )

        if not result.data:
            print("[METRICS] get_daily_stats fallback: 0 registros encontrados", flush=True)
            return []

        # Debug: mostra primeiro registro para diagnosticar tipos
        first = result.data[0]
        print(f"[METRICS] Fallback sample row: cost={first.get('cost')!r} (type={type(first.get('cost')).__name__})", flush=True)

        # Agrupa por dia
        daily = {}
        for row in result.data:
            ts = row.get("created_at", "")
            day = ts[:10] if ts else "unknown"  # "2026-03-25"
            if day not in daily:
                daily[day] = {
                    "day": day,
                    "total_calls": 0,
                    "total_input": 0,
                    "total_output": 0,
                    "total_cache_read": 0,
                    "total_cache_write": 0,
                    "total_cost": 0.0,
                }
            d = daily[day]
            d["total_calls"] += 1
            d["total_input"] += int(row.get("input_tokens", 0) or 0)
            d["total_output"] += int(row.get("output_tokens", 0) or 0)
            d["total_cache_read"] += int(row.get("cache_read", 0) or 0)
            d["total_cache_write"] += int(row.get("cache_write", 0) or 0)
            d["total_cost"] += float(row.get("cost", 0) or 0)

        stats = sorted(daily.values(), key=lambda x: x["day"])
        print(f"[METRICS] get_daily_stats fallback: {len(stats)} dias, cost_sum=${sum(r['total_cost'] for r in stats):.4f}", flush=True)
        return stats

    except Exception as e:
        err = str(e)
        print(f"[METRICS] get_daily_stats error: {err}", flush=True)
        if "does not exist" in err or "relation" in err:
            return {"error": "table_missing", "message": "Tabela llm_usage não existe. Execute a migration 007."}
        return {"error": "query_failed", "message": err}


def get_totals(since: str = None) -> dict:
    """
    Retorna totais acumulados (all-time ou desde uma data).
    Consulta diretamente a tabela llm_usage (sem depender de RPC).
    """
    try:
        from src.core.database.client import _get_client
        db = _get_client()
        if not db:
            return {}

        # Tenta RPC primeiro
        try:
            params = {"since": since} if since else {"since": None}
            result = db.rpc("llm_totals", params).execute()
            if result.data and len(result.data) > 0:
                row = result.data[0]
                normalized = {
                    "total_calls": int(row.get("total_calls", 0) or 0),
                    "total_input": int(row.get("total_input", 0) or 0),
                    "total_output": int(row.get("total_output", 0) or 0),
                    "total_cache_read": int(row.get("total_cache_read", 0) or 0),
                    "total_cache_write": int(row.get("total_cache_write", 0) or 0),
                    "total_cost": float(row.get("total_cost", 0) or 0),
                }
                print(f"[METRICS] get_totals via RPC: {normalized['total_calls']} calls, ${normalized['total_cost']:.4f}", flush=True)
                return normalized
        except Exception as e:
            print(f"[METRICS] RPC llm_totals falhou: {e}, usando fallback", flush=True)

        # Fallback: busca todos os registros e soma no Python
        query = (
            db.table("llm_usage")
            .select("input_tokens, output_tokens, cache_read, cache_write, cost")
        )
        if since:
            query = query.gte("created_at", since)

        # Paginação para lidar com muitos registros
        all_rows = []
        page_size = 1000
        offset = 0
        while True:
            result = query.range(offset, offset + page_size - 1).execute()
            rows = result.data or []
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            offset += page_size

        if not all_rows:
            return {}

        totals = {
            "total_calls": len(all_rows),
            "total_input": 0,
            "total_output": 0,
            "total_cache_read": 0,
            "total_cache_write": 0,
            "total_cost": 0.0,
        }
        for row in all_rows:
            totals["total_input"] += int(row.get("input_tokens", 0) or 0)
            totals["total_output"] += int(row.get("output_tokens", 0) or 0)
            totals["total_cache_read"] += int(row.get("cache_read", 0) or 0)
            totals["total_cache_write"] += int(row.get("cache_write", 0) or 0)
            totals["total_cost"] += float(row.get("cost", 0) or 0)

        totals["total_cost"] = round(totals["total_cost"], 6)
        return totals

    except Exception as e:
        err = str(e)
        print(f"[METRICS] get_totals error: {err}", flush=True)
        if "does not exist" in err or "relation" in err:
            return {"error": "table_missing", "message": "Tabela llm_usage não existe. Execute a migration 007."}
        return {"error": "query_failed", "message": err}
