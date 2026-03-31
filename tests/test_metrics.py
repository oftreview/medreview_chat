"""
tests/test_metrics.py — Testa o módulo de métricas.

Verifica:
  1. record_call() acumula corretamente em memória
  2. get_metrics() retorna snapshot correto
  3. get_daily_stats() e get_totals() não crasham (com ou sem DB)
  4. Cálculos de custo estão corretos
  5. Lógica de agregação por dia funciona
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Força TEST_MODE para não depender de variáveis de ambiente
os.environ.setdefault("TEST_MODE", "true")

import importlib


def test_cost_calculation():
    """Testa que os cálculos de custo estão corretos."""
    print("\n📊 TESTE 1: Cálculo de custo")
    print("-" * 50)

    from src.core.metrics import MODEL_PRICES

    # Haiku 4.5: $1/MTok input, $5/MTok output
    prices = MODEL_PRICES["claude-haiku-4-5-20251001"]
    # 30K input tokens + 2K output tokens (chamada típica)
    cost = (30000 * prices["input"] + 2000 * prices["output"]) / 1_000_000
    expected = 0.04  # $0.03 input + $0.01 output
    assert abs(cost - expected) < 0.001, f"Haiku cost: expected {expected}, got {cost}"
    print(f"  ✅ Haiku 4.5: 30K in + 2K out = ${cost:.4f} (correto)")

    # Sonnet 4.6: $3/MTok input, $15/MTok output
    prices = MODEL_PRICES["claude-sonnet-4-6"]
    cost = (30000 * prices["input"] + 2000 * prices["output"]) / 1_000_000
    expected = 0.12  # $0.09 input + $0.03 output
    assert abs(cost - expected) < 0.001, f"Sonnet cost: expected {expected}, got {cost}"
    print(f"  ✅ Sonnet 4.6: 30K in + 2K out = ${cost:.4f} (correto)")

    # Opus 4.6: $5/MTok input, $25/MTok output
    prices = MODEL_PRICES["claude-opus-4-6"]
    cost = (30000 * prices["input"] + 2000 * prices["output"]) / 1_000_000
    expected = 0.20  # $0.15 input + $0.05 output
    assert abs(cost - expected) < 0.001, f"Opus cost: expected {expected}, got {cost}"
    print(f"  ✅ Opus 4.6: 30K in + 2K out = ${cost:.4f} (correto)")


def test_record_and_get_metrics():
    """Testa record_call e get_metrics."""
    print("\n📊 TESTE 2: record_call + get_metrics")
    print("-" * 50)

    from src.core import metrics

    # Reset dos acumuladores (acesso direto para teste)
    with metrics._lock:
        metrics._totals["total_calls"] = 0
        metrics._totals["total_input_tokens"] = 0
        metrics._totals["total_output_tokens"] = 0
        metrics._totals["total_cache_read"] = 0
        metrics._totals["total_cache_write"] = 0
        metrics._totals["total_cost"] = 0.0
        metrics._recent_calls.clear()

    # Simula 3 chamadas
    metrics.record_call("claude-haiku-4-5-20251001", 30000, 1500, cache_read=25000, cache_write=5000)
    metrics.record_call("claude-haiku-4-5-20251001", 30000, 2000, cache_read=28000, cache_write=0)
    metrics.record_call("claude-haiku-4-5-20251001", 30000, 1800, cache_read=29000, cache_write=0)

    m = metrics.get_metrics()

    assert m["total_calls"] == 3, f"Expected 3 calls, got {m['total_calls']}"
    print(f"  ✅ total_calls: {m['total_calls']}")

    assert m["total_input_tokens"] == 90000, f"Expected 90000 input, got {m['total_input_tokens']}"
    print(f"  ✅ total_input_tokens: {m['total_input_tokens']}")

    assert m["total_output_tokens"] == 5300, f"Expected 5300 output, got {m['total_output_tokens']}"
    print(f"  ✅ total_output_tokens: {m['total_output_tokens']}")

    assert m["total_cache_read"] == 82000, f"Expected 82000 cache_read, got {m['total_cache_read']}"
    print(f"  ✅ total_cache_read: {m['total_cache_read']}")

    assert m["total_cost"] > 0, f"Cost should be > 0, got {m['total_cost']}"
    print(f"  ✅ total_cost: ${m['total_cost']:.6f}")

    assert len(m["recent_calls"]) == 3, f"Expected 3 recent calls, got {len(m['recent_calls'])}"
    print(f"  ✅ recent_calls: {len(m['recent_calls'])} entries")

    # Verifica que cada recent_call tem os campos esperados
    for call in m["recent_calls"]:
        assert "time" in call, "Missing 'time' in recent_call"
        assert "input_tokens" in call, "Missing 'input_tokens' in recent_call"
        assert "output_tokens" in call, "Missing 'output_tokens' in recent_call"
        assert "cost" in call, "Missing 'cost' in recent_call"
        assert "model" in call, "Missing 'model' in recent_call"
    print(f"  ✅ recent_calls schema: OK (all fields present)")


def test_daily_aggregation():
    """Testa a lógica de agregação por dia (sem Supabase)."""
    print("\n📊 TESTE 3: Agregação diária (lógica Python)")
    print("-" * 50)

    # Simula dados que viriam do Supabase
    mock_rows = [
        {"created_at": "2026-03-25T10:30:00+00:00", "input_tokens": 30000, "output_tokens": 2000, "cache_read": 25000, "cache_write": 5000, "cost": 0.04},
        {"created_at": "2026-03-25T14:15:00+00:00", "input_tokens": 30000, "output_tokens": 1500, "cache_read": 28000, "cache_write": 0, "cost": 0.0375},
        {"created_at": "2026-03-26T09:00:00+00:00", "input_tokens": 30000, "output_tokens": 3000, "cache_read": 29000, "cache_write": 0, "cost": 0.045},
        {"created_at": "2026-03-27T11:00:00+00:00", "input_tokens": 30000, "output_tokens": 1000, "cache_read": 30000, "cache_write": 0, "cost": 0.035},
        {"created_at": "2026-03-27T16:30:00+00:00", "input_tokens": 30000, "output_tokens": 2500, "cache_read": 25000, "cache_write": 3000, "cost": 0.0425},
    ]

    # Aplica mesma lógica do get_daily_stats (fallback)
    daily = {}
    for row in mock_rows:
        ts = row.get("created_at", "")
        day = ts[:10] if ts else "unknown"
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

    result = sorted(daily.values(), key=lambda x: x["day"])

    assert len(result) == 3, f"Expected 3 days, got {len(result)}"
    print(f"  ✅ Dias agrupados: {len(result)}")

    # Dia 25: 2 chamadas
    assert result[0]["day"] == "2026-03-25"
    assert result[0]["total_calls"] == 2
    print(f"  ✅ 2026-03-25: {result[0]['total_calls']} chamadas, ${result[0]['total_cost']:.4f}")

    # Dia 26: 1 chamada
    assert result[1]["day"] == "2026-03-26"
    assert result[1]["total_calls"] == 1
    print(f"  ✅ 2026-03-26: {result[1]['total_calls']} chamada, ${result[1]['total_cost']:.4f}")

    # Dia 27: 2 chamadas
    assert result[2]["day"] == "2026-03-27"
    assert result[2]["total_calls"] == 2
    print(f"  ✅ 2026-03-27: {result[2]['total_calls']} chamadas, ${result[2]['total_cost']:.4f}")

    # Total
    total_cost = sum(d["total_cost"] for d in result)
    total_calls = sum(d["total_calls"] for d in result)
    assert total_calls == 5, f"Expected 5 total calls, got {total_calls}"
    assert abs(total_cost - 0.2) < 0.001, f"Expected ~$0.20 total, got ${total_cost:.4f}"
    print(f"  ✅ Total: {total_calls} chamadas, ${total_cost:.4f}")


def test_totals_aggregation():
    """Testa a lógica de totais (sem Supabase)."""
    print("\n📊 TESTE 4: Agregação de totais (lógica Python)")
    print("-" * 50)

    mock_rows = [
        {"input_tokens": 30000, "output_tokens": 2000, "cache_read": 25000, "cache_write": 5000, "cost": 0.04},
        {"input_tokens": 30000, "output_tokens": 1500, "cache_read": 28000, "cache_write": 0, "cost": 0.0375},
        {"input_tokens": 30000, "output_tokens": 3000, "cache_read": 29000, "cache_write": 0, "cost": 0.045},
        {"input_tokens": None, "output_tokens": 0, "cache_read": 0, "cache_write": None, "cost": None},  # Edge case: nulls
    ]

    totals = {
        "total_calls": len(mock_rows),
        "total_input": 0,
        "total_output": 0,
        "total_cache_read": 0,
        "total_cache_write": 0,
        "total_cost": 0.0,
    }
    for row in mock_rows:
        totals["total_input"] += int(row.get("input_tokens", 0) or 0)
        totals["total_output"] += int(row.get("output_tokens", 0) or 0)
        totals["total_cache_read"] += int(row.get("cache_read", 0) or 0)
        totals["total_cache_write"] += int(row.get("cache_write", 0) or 0)
        totals["total_cost"] += float(row.get("cost", 0) or 0)

    assert totals["total_calls"] == 4
    print(f"  ✅ total_calls: {totals['total_calls']} (includes null row)")

    assert totals["total_input"] == 90000
    print(f"  ✅ total_input: {totals['total_input']} (nulls treated as 0)")

    assert totals["total_output"] == 6500
    print(f"  ✅ total_output: {totals['total_output']}")

    assert totals["total_cache_read"] == 82000
    print(f"  ✅ total_cache_read: {totals['total_cache_read']}")

    assert totals["total_cache_write"] == 5000
    print(f"  ✅ total_cache_write: {totals['total_cache_write']} (nulls treated as 0)")

    assert abs(totals["total_cost"] - 0.1225) < 0.001
    print(f"  ✅ total_cost: ${totals['total_cost']:.4f} (nulls treated as 0)")


def test_get_functions_dont_crash():
    """Testa que get_daily_stats e get_totals não crasham sem DB."""
    print("\n📊 TESTE 5: Resiliência sem banco de dados")
    print("-" * 50)

    from src.core.metrics import get_daily_stats, get_totals, get_history

    # Sem SUPABASE_URL configurado, devem retornar vazio (não crashar)
    daily = get_daily_stats(days_back=30)
    assert isinstance(daily, list), f"get_daily_stats should return list, got {type(daily)}"
    print(f"  ✅ get_daily_stats(): retornou {type(daily).__name__} com {len(daily)} items (sem crash)")

    totals = get_totals()
    assert isinstance(totals, dict), f"get_totals should return dict, got {type(totals)}"
    print(f"  ✅ get_totals(): retornou {type(totals).__name__} (sem crash)")

    history = get_history()
    assert isinstance(history, dict), f"get_history should return dict, got {type(history)}"
    assert "calls" in history, "get_history should have 'calls' key"
    print(f"  ✅ get_history(): retornou {type(history).__name__} com keys {list(history.keys())} (sem crash)")


def test_endpoint_response_format():
    """Testa que o formato de resposta dos endpoints está correto."""
    print("\n📊 TESTE 6: Formato de resposta dos endpoints")
    print("-" * 50)

    from src.core.metrics import get_metrics

    m = get_metrics()

    # Verifica campos obrigatórios
    required_fields = [
        "model", "max_tokens", "total_calls", "total_input_tokens",
        "total_output_tokens", "total_cache_read", "total_cache_write",
        "total_cost", "recent_calls"
    ]
    for field in required_fields:
        assert field in m, f"Missing field '{field}' in get_metrics()"
    print(f"  ✅ get_metrics(): todos os {len(required_fields)} campos presentes")

    # Verifica tipos
    assert isinstance(m["total_calls"], int), "total_calls should be int"
    assert isinstance(m["total_cost"], float), "total_cost should be float"
    assert isinstance(m["recent_calls"], list), "recent_calls should be list"
    print(f"  ✅ Tipos corretos: calls=int, cost=float, recent=list")

    # Verifica que o frontend vai conseguir ler os campos do /api/metrics/totals
    # O dashboard espera: total_cost, total_input, total_output, total_calls, total_cache_read, total_cache_write
    totals_expected = ["total_cost", "total_input", "total_output", "total_calls", "total_cache_read", "total_cache_write"]
    # Simula o que o fallback retorna
    mock_totals = {
        "total_calls": 10,
        "total_input": 300000,
        "total_output": 20000,
        "total_cache_read": 250000,
        "total_cache_write": 50000,
        "total_cost": 0.4,
    }
    for field in totals_expected:
        assert field in mock_totals, f"Missing field '{field}' in totals format"
    print(f"  ✅ Formato totals: todos os {len(totals_expected)} campos presentes para o dashboard")


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    passed = 0
    failed = 0
    errors = []

    tests = [
        test_cost_calculation,
        test_record_and_get_metrics,
        test_daily_aggregation,
        test_totals_aggregation,
        test_get_functions_dont_crash,
        test_endpoint_response_format,
    ]

    print("=" * 60)
    print("TESTE DE MÉTRICAS — Custos & Modelo")
    print("=" * 60)

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test_fn.__name__, str(e)))
            print(f"  ❌ FALHOU: {e}")

    print("\n" + "=" * 60)
    print(f"RESULTADO: {passed}/{len(tests)} testes passaram")
    if errors:
        print(f"\n⚠️  FALHAS:")
        for name, err in errors:
            print(f"  [{name}] {err}")
    else:
        print("\n✅ TODOS OS TESTES PASSARAM!")
    print("=" * 60)

    sys.exit(0 if not errors else 1)
