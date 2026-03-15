"""
Coletor de métricas de uso da API Anthropic.

Singleton thread-safe que acumula tokens, custos e cache hits.
Alimentado por core/llm.py após cada chamada à API.
"""
import threading
import time
from collections import deque

# Preços por milhão de tokens (input, output)
MODEL_PRICES = {
    "claude-haiku-4-5-20251001":  {"input": 1.0, "output": 5.0},
    "claude-sonnet-4-20250514":   {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-6":          {"input": 3.0, "output": 15.0},
    "claude-opus-4-6":            {"input": 5.0, "output": 25.0},
}

_lock = threading.Lock()

# Acumuladores globais
_totals = {
    "total_calls": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_cache_read": 0,
    "total_cache_write": 0,
    "total_cost": 0.0,
}

# Últimas N chamadas para histórico
_recent_calls = deque(maxlen=50)


def record_call(model: str, input_tokens: int, output_tokens: int,
                cache_read: int = 0, cache_write: int = 0):
    """Registra uma chamada à API com seus tokens e cache."""
    prices = MODEL_PRICES.get(model, {"input": 3.0, "output": 15.0})
    cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

    now = time.strftime("%H:%M:%S")

    with _lock:
        _totals["total_calls"] += 1
        _totals["total_input_tokens"] += input_tokens
        _totals["total_output_tokens"] += output_tokens
        _totals["total_cache_read"] += cache_read
        _totals["total_cache_write"] += cache_write
        _totals["total_cost"] += cost

        _recent_calls.append({
            "time": now,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read": cache_read,
            "cache_write": cache_write,
            "cost": round(cost, 6),
            "model": model,
        })


def get_metrics() -> dict:
    """Retorna snapshot das métricas atuais."""
    from core.config import CLAUDE_MODEL, MAX_TOKENS

    with _lock:
        return {
            "model": CLAUDE_MODEL,
            "max_tokens": MAX_TOKENS,
            **dict(_totals),
            "total_cost": round(_totals["total_cost"], 6),
            "recent_calls": list(_recent_calls),
        }
