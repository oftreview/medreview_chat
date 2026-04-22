# PROMPT DE CONSTRUCAO — Sistema de Testes Automatizados Closi AI

> Use este prompt para construir toda a infraestrutura de testes do Closi AI.
> **IMPORTANTE:** Execute cada etapa completamente antes de passar para a proxima.
> Cada etapa foi projetada para ser segura e nao quebrar o app em producao.

---

## CONTEXTO DO PROJETO

O Closi AI e um agente autonomo de vendas via WhatsApp para a MedReview, construido com:

- **Backend:** Python 3.11+, Flask (app factory em `src/app.py`), Gunicorn + Gevent
- **LLM:** Anthropic Claude API com Prompt Caching (`src/core/llm.py`)
- **Database:** Supabase/PostgreSQL (`src/core/database/` — client.py, conversations.py, leads.py, analytics.py, etc.)
- **WhatsApp:** Z-API via httpx (`src/core/whatsapp.py`)
- **CRM:** HubSpot (`src/core/hubspot.py`)
- **Memoria:** ConversationMemory in-memory + Supabase (`src/core/memory.py`) + Wild Memory Framework (`wild_memory/`)
- **Scheduler:** APScheduler para manutencao diaria (`src/core/scheduler.py`)
- **Dashboard existente:** Wild Memory Dashboard em `/wild-memory` (`dashboard/blueprint.py`)
- **Deploy:** Railway (Dockerfile, Procfile, railway.toml)

**Estrutura atual de arquivos relevante:**
```
src/
  app.py                          # Flask app factory (create_app)
  config.py                       # Todas as env vars centralizadas
  api/
    __init__.py                   # register_blueprints()
    chat.py                       # /chat endpoint com debounce (gevent + threading)
    webhooks.py                   # /webhook/zapi e /webhook/form
    health.py                     # /health, /api/metrics, /api/logs, /api/config
    escalation_api.py             # /escalation/resolve
    analytics_api.py              # Analytics endpoints
    backlog_api.py                # Backlog management
    corrections_api.py            # Corrections management
    hubspot_api.py                # HubSpot endpoints
    dashboard.py                  # Main dashboard UI
  agent/
    sales_agent.py                # SalesAgent class (reply, reset, metadata extraction)
  core/
    llm.py                        # call_claude() com retry + prompt caching
    memory.py                     # ConversationMemory (in-memory + Supabase)
    security.py                   # sanitize_input, check_injection, rate_limiter, filter_output, hash_user_id
    whatsapp.py                   # send_message, parse_incoming, format_phone (via Z-API/httpx)
    escalation.py                 # handle_escalation, resolve_escalation, notify_supervisor
    message_splitter.py           # split_response (quebra msgs longas em partes)
    database.py                   # Legacy wrapper (now proxies to database/)
    database/
      client.py                   # Supabase singleton (_get_client), health_check
      conversations.py            # save_message, load_conversation_history
      leads.py                    # upsert_lead, save_lead_metadata
      analytics.py                # Analytics queries
      escalations.py              # save_escalation, resolve_escalation_record
      corrections.py              # Corrections CRUD
      backlog.py                  # Backlog CRUD
    hubspot.py                    # HubSpot CRM sync
    metrics.py                    # Token/cost tracking
    logger.py                     # Security event logging
    log_buffer.py                 # Stdout/stderr capture ring buffer
    scheduler.py                  # APScheduler init
    wild_memory_shadow.py         # Wild Memory Phase 2
    wild_memory_context.py        # Wild Memory Phase 3
    wild_memory_lifecycle.py      # Wild Memory Phase 4
    wild_memory_adapter.py        # Adapter for Wild Memory Dashboard
wild_memory/
  orchestrator.py                 # Central orchestrator
  layers/                         # observation, reflection, entity_graph, etc.
  retrieval/                      # elephant_recall, briefing_builder, etc.
  processes/                      # ant_decay, bee_distiller, ner_pipeline
  infra/                          # db, embedding_cache, semantic_cache
  audit/                          # citation_logger, memory_audit
tests/
  conftest.py                     # Apenas sys.path setup (sem fixtures reais)
  test_security.py                # UNICO teste completo (~50 test cases)
  test_phase2_shadow.py           # Wild Memory tests
  test_phase3_context.py          # Wild Memory tests
  test_phase4_lifecycle.py        # Wild Memory tests
  test_wild_memory_setup.py       # Wild Memory setup test
```

**Configuracao atual do pyproject.toml:**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 120
target-version = "py311"
```

**Dashboard existente registrado em `src/app.py`:**
O app ja tem pattern de blueprints Flask com dashboards. O Wild Memory dashboard esta em `dashboard/blueprint.py` com templates em `dashboard/templates/` e static em `dashboard/static/`. O main dashboard esta em `src/api/dashboard.py`. Todos endpoints de health/metrics estao em `src/api/health.py`.

---

## BUGS CRITICOS IDENTIFICADOS (devem ser cobertos por testes)

1. **Race Condition no Timer de Debounce** (`src/api/webhooks.py:158-174`) — `_zapi_state` dict com timer gevent; kill() do timer pode perder msgs acumuladas
2. **Race na Eleicao do Primary Waiter** (`src/api/chat.py:309-345`) — `_chat_state` com `_primary_waiter`; requests concorrentes podem perder mensagens
3. **Race no Cleanup de Memoria** (`src/core/memory.py:57-76`) — `_cleanup_expired()` remove sessao enquanto `add()` esta sendo chamado
4. **Overlap na Truncagem de Historico** (`src/agent/sales_agent.py:158-163`) — `KEEP_FIRST=4, KEEP_LAST=26` perde msg do meio com 31 msgs
5. **Bypass na Validacao de Telefone** (`src/api/webhooks.py:204-210`) — normaliza antes de validar
6. **Bypass Unicode em Injection Detection** (`src/core/security.py`) — regex ASCII nao pega homoglifos
7. **Rate Limit do Form nao Atomico** (`src/api/webhooks.py:189-201`) — race entre limpeza e checagem
8. **Retry-After Header Parsing Incompleto** (`src/core/llm.py:161-179`) — so trata decimal-seconds

---

# ETAPA 1 DE 4 — FUNDACAO (Infraestrutura de Testes)

## Objetivo
Criar a base da infraestrutura de testes SEM modificar nenhum codigo de producao. Apenas adicionar arquivos novos.

## Regras de Seguranca
- NAO modifique nenhum arquivo existente em `src/`, `core/`, `wild_memory/`, `dashboard/`
- Apenas ADICIONE novos arquivos em `tests/` e atualize `pyproject.toml` (apenas a secao dev dependencies e pytest config)
- NAO crie arquivos `.github/` ainda (sera na Etapa 4)
- Todos os testes devem funcionar com `TEST_MODE=true` e NUNCA fazer chamadas reais a APIs externas

## Entregas

### 1.1 — Atualizar `pyproject.toml` (APENAS secoes de dev e pytest)

Adicionar ao `pyproject.toml` existente:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-flask>=1.3",
    "pytest-mock>=3.14",
    "pytest-xdist>=3.5",
    "responses>=0.25",
    "pytest-httpx>=0.30",
    "ruff>=0.4.0",
    "coverage[toml]>=7.4",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "critical: Testes de bugs criticos (race conditions, perda de dados)",
    "slow: Testes que demoram > 5 segundos",
    "integration: Testes com mocks de servicos externos",
    "e2e: Testes end-to-end (fluxo completo)",
    "load: Testes de carga/stress",
    "dashboard: Testes do dashboard de testes",
]
filterwarnings = ["ignore::DeprecationWarning"]
addopts = "-v --tb=short --strict-markers"

[tool.coverage.run]
source = ["src", "core", "wild_memory"]
omit = ["*/tests/*", "*/__pycache__/*", "*/migrations/*"]

[tool.coverage.report]
fail_under = 50
show_missing = true
exclude_lines = ["pragma: no cover", "if __name__", "pass"]
```

### 1.2 — Criar `tests/conftest.py` (substituir o existente)

Construir conftest.py com fixtures completas:

- `app` — Flask app factory com `TESTING=True` e env vars de teste
- `client` — Flask test client
- `mock_claude` — Mock de `src.core.llm.client.messages.create` com resposta deterministica (TextBlock com text, Usage com tokens)
- `mock_zapi` — Mock de `src.core.whatsapp.send_message` retornando True
- `mock_supabase` — Mock de `src.core.database.client._get_client`
- `mock_database` — Mock completo do modulo `src.core.database` (save_message, load_conversation_history, etc.)
- `sample_zapi_payload` — dict com type=ReceivedCallback, fromMe=False, phone=5511999999999, body="Quero saber mais"
- `sample_form_payload` — dict com name="Joao Silva", phone="11999999999"
- `clean_debounce_state` — fixture que limpa `_zapi_state` e `_chat_state` antes de cada teste
- Garantir que `os.environ["TEST_MODE"] = "true"` e todas as env vars de servicos apontem para mocks

### 1.3 — Criar `tests/fixtures/` com dados de teste

- `tests/fixtures/__init__.py`
- `tests/fixtures/payloads.py` — Payloads de webhook (Z-API valido, Z-API invalido, Z-API fromMe, Form valido, Form sem phone, Form phone invalido)
- `tests/fixtures/mock_responses.py` — Respostas mockadas do Claude (normal, com [META], com [ESCALAR], com escalation fallback phrases), respostas do Supabase (insert success, select result)
- `tests/fixtures/test_data.py` — Phones validos/invalidos, messages de teste, conversation histories com 5, 30, 31 mensagens

### 1.4 — Criar estrutura de diretorios de teste

```
tests/
  conftest.py
  fixtures/
    __init__.py
    payloads.py
    mock_responses.py
    test_data.py
  unit/
    __init__.py
    test_security.py              # Mover/expandir teste existente
    test_message_splitter.py
    test_phone_validation.py
    test_llm_retry.py
    test_memory_logic.py
    test_sales_agent_logic.py
    test_escalation_logic.py
    test_metadata_extraction.py
  integration/
    __init__.py
  critical/
    __init__.py
  e2e/
    __init__.py
  dashboard/
    __init__.py
```

### 1.5 — Implementar testes unitarios basicos (NAO-destrutivos)

Estes testes NAO fazem I/O, NAO precisam de Flask app, NAO precisam de mocks complexos:

**`tests/unit/test_message_splitter.py`:**
- test_short_text_returns_single_message (< MAX_CHARS)
- test_long_text_splits_at_sentence_boundary
- test_max_messages_limit_respected (MAX_MESSAGES=3)
- test_empty_text_returns_list
- test_paragraph_splitting_preserves_context
- test_overflow_join_respects_max_chars
- test_single_giant_word_force_split

**`tests/unit/test_phone_validation.py`:**
- test_format_phone_with_ddi (5511999999999 -> 5511999999999)
- test_format_phone_without_ddi (11999999999 -> 5511999999999)
- test_format_phone_with_whatsapp_suffix (5511999999999@s.whatsapp.net -> 5511999999999)
- test_normalize_phone_removes_non_digits
- test_normalize_phone_strips_leading_zero
- test_phone_regex_valid_patterns
- test_phone_regex_rejects_invalid (curto, longo, alfanumerico)

**`tests/unit/test_llm_retry.py`:**
- test_retry_delay_exponential_backoff (1s, 2s, 4s)
- test_retry_delay_respects_retry_after_header
- test_retryable_status_codes_set
- test_max_retries_constant

**`tests/unit/test_sales_agent_logic.py`:**
- test_truncate_history_under_max_returns_all
- test_truncate_history_at_max_returns_all
- test_truncate_history_over_max_keeps_first_and_last
- test_truncate_31_messages_no_overlap (BUG 4 — verificar que KEEP_FIRST + KEEP_LAST nao perde msgs)
- test_extract_metadata_with_valid_meta_tag
- test_extract_metadata_without_meta_tag
- test_extract_metadata_with_desconhecido_values
- test_escalation_tag_detection
- test_escalation_fallback_phrases_in_first_200_chars

**`tests/unit/test_metadata_extraction.py`:**
- test_extract_meta_line_parsing
- test_extract_meta_pipe_separated
- test_extract_meta_clean_text_returned
- test_extract_meta_preserves_response_before_meta

**`tests/unit/test_escalation_logic.py`:**
- test_format_brief_whatsapp_with_full_data
- test_format_brief_whatsapp_with_empty_data
- test_is_escalated_returns_true
- test_is_escalated_returns_false

### 1.6 — Verificacao

Apos implementar, rode:
```bash
pip install -e ".[dev]"
pytest tests/unit/ -v --tb=short
```

TODOS os testes devem passar. Se algum falhar, corrija o TESTE (nao o codigo de producao).

**Criterio de sucesso:** 100% dos unit tests passando, 0 erros, 0 modificacoes em src/.

---

# ETAPA 2 DE 4 — TESTES CRITICOS E DE INTEGRACAO

## Objetivo
Testar os bugs criticos identificados e os endpoints da API usando Flask test client + mocks.

## Regras de Seguranca
- NAO modifique arquivos em `src/` EXCETO para adicionar `TEST_MODE` check no `src/config.py` (uma unica linha: `TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"`)
- Todos os testes usam mocks para servicos externos (Claude, Supabase, Z-API, HubSpot)
- Testes de race condition usam threading controlado, NAO gevent real

## Entregas

### 2.1 — Adicionar TEST_MODE ao `src/config.py`

Uma unica linha apos as importacoes existentes:
```python
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
```

### 2.2 — Testes Criticos (`tests/critical/`)

**`tests/critical/test_debounce_race.py`:**
- test_concurrent_messages_accumulated_before_flush — 3 msgs rapidas do mesmo phone, verificar que todas chegam ao agent.reply()
- test_timer_reset_preserves_previous_messages — timer quase disparando + nova msg chega
- test_concurrent_phones_independent — 2 phones diferentes nao interferem

**`tests/critical/test_primary_waiter_race.py`:**
- test_last_request_becomes_primary_waiter — verificar que `_primary_waiter` = ultimo waiter_id
- test_secondary_waiters_get_debounced_status — requests anteriores retornam status="debounced"
- test_all_messages_included_in_primary_response — msgs de todos os requests estao no combined

**`tests/critical/test_memory_cleanup_race.py`:**
- test_cleanup_does_not_remove_active_session — sessao com acesso recente nao e removida
- test_cleanup_removes_expired_session — sessao sem acesso > TTL e removida
- test_cleanup_preserves_escalated_sessions — sessoes escalated nao sao removidas
- test_concurrent_add_and_cleanup — add() e _cleanup_expired() simultaneos nao corrompem estado

**`tests/critical/test_history_truncation.py`:**
- test_30_messages_no_truncation — exatamente MAX_HISTORY retorna tudo
- test_31_messages_truncation — verifica first 4 + last 26, checa se overlap ou gap existe
- test_50_messages_truncation — verifica integridade
- test_truncation_preserves_order — primeira msg e primeira, ultima e ultima

### 2.3 — Testes de Integracao (`tests/integration/`)

**`tests/integration/test_webhook_zapi.py`** (usar Flask test client):
- test_valid_zapi_message_returns_200_queued — POST valido retorna {"status": "queued"}
- test_fromMe_ignored — payload com fromMe=True retorna {"status": "ignored"}
- test_non_text_type_ignored — type != ReceivedCallback
- test_rate_limited_returns_200 — rate limit excedido
- test_injection_detected_still_processes — msg com injection pattern e processada mas logada
- test_escalated_session_returns_200 — sessao escalated retorna {"status": "escalated_session"}
- test_secret_command_escalate — msg com comando secreto
- test_secret_command_deescalate — msg com comando de desescalacao

**`tests/integration/test_webhook_form.py`** (usar Flask test client):
- test_valid_form_returns_200 — form valido retorna {"status": "ok"}
- test_missing_phone_returns_400
- test_invalid_phone_returns_400
- test_form_rate_limit_returns_429 — 6+ requests do mesmo IP
- test_phone_normalization — "11999999999" -> "5511999999999"

**`tests/integration/test_chat_api.py`** (usar Flask test client):
- test_sandbox_mode_basic — POST sem auth, session_id=sandbox
- test_api_mode_with_auth — POST com Bearer token, channel=botmaker
- test_api_mode_without_auth_returns_401
- test_missing_message_returns_400
- test_missing_user_id_for_external_channel_returns_400
- test_escalated_session_returns_escalated_status
- test_secret_commands_work_via_chat

**`tests/integration/test_health_api.py`** (usar Flask test client):
- test_health_returns_ok
- test_health_db_without_supabase
- test_health_memory_returns_stats
- test_metrics_returns_structure

### 2.4 — Verificacao

```bash
pytest tests/critical/ tests/integration/ -v --tb=short
```

**Criterio de sucesso:** 100% passando. Unica modificacao em src/ foi adicionar TEST_MODE ao config.py.

---

# ETAPA 3 DE 4 — DASHBOARD DE TESTES

## Objetivo
Criar uma aba/pagina no dashboard existente que mostra o status completo dos testes: cobertura, ultimos resultados, historico de runs, bugs conhecidos.

## Regras de Seguranca
- Criar um blueprint Flask SEPARADO para o test dashboard (nao modificar blueprints existentes)
- Registrar o blueprint em `src/app.py` dentro de um bloco try/except (como ja e feito com Wild Memory Dashboard)
- O dashboard NAO executa testes — apenas le resultados de arquivos JSON gerados por pytest
- Usar o mesmo pattern de CSS/JS que o dashboard existente

## Entregas

### 3.1 — Criar runner de testes com output JSON

Criar `tests/runner.py`:
```python
"""
Test runner que gera resultados em JSON para o dashboard.
Uso: python -m tests.runner
Gera: tests/results/latest.json e tests/results/history.json
"""
```

O runner deve:
1. Rodar `pytest tests/ --tb=short -q --json-report --json-report-file=tests/results/latest.json` (usar pytest-json-report)
2. Append resultado em `tests/results/history.json` (array de runs com timestamp)
3. Gerar `tests/results/coverage.json` a partir do coverage.py
4. Ser chamavel via CLI: `python -m tests.runner`

Adicionar `pytest-json-report` ao pyproject.toml dev dependencies.

### 3.2 — Criar Blueprint do Test Dashboard

Criar `tests/dashboard/__init__.py`, `tests/dashboard/blueprint.py`:

O blueprint deve ter:
- **URL prefix:** `/dashboard/tests`
- **Pagina principal:** Overview com cards mostrando:
  - Total de testes, passando, falhando, skipped
  - Cobertura de codigo (%) com barra de progresso
  - Ultimo run (timestamp, duracao)
  - Status dos testes CRITICOS (4 bugs com indicador vermelho/verde)
- **API endpoints:**
  - `GET /dashboard/tests/api/results` — ultimo resultado do pytest (le tests/results/latest.json)
  - `GET /dashboard/tests/api/history` — historico de runs (le tests/results/history.json)
  - `GET /dashboard/tests/api/coverage` — dados de cobertura (le tests/results/coverage.json)
  - `POST /dashboard/tests/api/run` — dispara um test run (chama tests/runner.py em background, retorna job_id)
  - `GET /dashboard/tests/api/run/<job_id>` — status do run em andamento

### 3.3 — Criar Template HTML do Dashboard

Criar `tests/dashboard/templates/test_dashboard.html`:

O dashboard deve ter as seguintes secoes:

**Header:** "Closi AI — Test Suite" com timestamp do ultimo run

**Cards superiores (4 cards):**
1. Total Tests: numero + tendencia (up/down vs run anterior)
2. Passing: numero + % em verde
3. Failing: numero + % em vermelho (0 = verde)
4. Coverage: % com barra de progresso (verde >80%, amarelo 50-80%, vermelho <50%)

**Secao "Testes Criticos":**
Tabela com 4 linhas (um por bug critico):
- Nome do teste
- Status (PASS/FAIL/NOT_RUN) com indicador colorido
- Ultima execucao
- Descricao do bug

**Secao "Resultados por Categoria":**
Tabs: Unit | Integration | Critical | E2E
Cada tab mostra lista de testes com status, duracao, e mensagem de erro se falhou.

**Secao "Historico de Runs":**
Grafico de linha (ultimos 30 runs) mostrando: total passando vs falhando ao longo do tempo.
Abaixo do grafico: tabela com ultimas 10 runs (timestamp, total, pass, fail, duracao).

**Secao "Cobertura por Modulo":**
Tabela com colunas: Modulo | Linhas | Cobertura (%) | Barra visual
Modulos: src/core/security.py, src/core/llm.py, src/api/webhooks.py, src/api/chat.py, src/core/memory.py, src/agent/sales_agent.py, etc.

**Botao "Run Tests Now":**
Botao que dispara POST /dashboard/tests/api/run e mostra spinner ate completar. Ao completar, recarrega a pagina com novos resultados.

**Estilo:**
- Usar o MESMO CSS base do dashboard principal (ou wild memory dashboard)
- Cores: verde (#22c55e) para pass, vermelho (#ef4444) para fail, amarelo (#eab308) para warning, azul (#3b82f6) para info
- Layout responsivo com grid CSS
- Sem frameworks JS externos (vanilla JS puro, como os outros dashboards)
- Dark mode se o dashboard principal usa dark mode

### 3.4 — Registrar blueprint em `src/app.py`

Adicionar ao final de `create_app()`, ANTES do return:
```python
# Register Test Dashboard
try:
    from tests.dashboard.blueprint import bp as test_dashboard_bp
    app.register_blueprint(test_dashboard_bp)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"[Test Dashboard] Failed to register: {e}")
```

### 3.5 — Criar static files

- `tests/dashboard/static/test_dashboard.css` — estilos do dashboard
- `tests/dashboard/static/test_dashboard.js` — logica de interacao (fetch API, render charts, botao run)

### 3.6 — Verificacao

1. Rodar `python -m tests.runner` — deve gerar os JSONs
2. Iniciar o app (`flask run`) e acessar `/dashboard/tests` — deve renderizar o dashboard
3. Clicar "Run Tests Now" — deve disparar testes e atualizar resultados

**Criterio de sucesso:** Dashboard funcional, acessivel via navegador, mostrando resultados reais dos testes.

---

# ETAPA 4 DE 4 — CI/CD + E2E + POLISH

## Objetivo
Configurar GitHub Actions para rodar testes automaticamente em push/PR, adicionar testes E2E, e garantir cobertura minima.

## Regras de Seguranca
- Workflow de CI NUNCA faz deploy automatico
- Secrets de producao NUNCA sao usados nos testes (apenas test keys)
- Pipeline roda em ambiente isolado (ubuntu-latest)
- Testes E2E usam APENAS mocks (nao chamam APIs reais)

## Entregas

### 4.1 — GitHub Actions Workflow Principal

Criar `.github/workflows/test.yml`:

```yaml
name: Closi AI — Test Suite

on:
  push:
    branches: [main, develop, "feature/**"]
  pull_request:
    branches: [main, develop]

env:
  PYTHON_VERSION: "3.11"
  TEST_MODE: "true"
  SUPABASE_URL: "http://localhost:54321"
  SUPABASE_KEY: "test-key-not-real"
  ANTHROPIC_API_KEY: "test-key-not-real"
  ZAPI_INSTANCE_ID: ""
  ZAPI_TOKEN: ""
  HUBSPOT_ACCESS_TOKEN: ""

jobs:
  lint:
    name: Lint (Ruff)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install ruff
      - run: ruff check src/ tests/ --output-format=github
      - run: ruff format --check src/ tests/

  unit-tests:
    name: Unit Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -r requirements.txt && pip install -e ".[dev]"
      - name: Run unit + critical tests with coverage
        run: |
          pytest tests/unit/ tests/critical/ \
            --cov=src --cov-report=xml:coverage.xml \
            --cov-report=html:htmlcov \
            --cov-fail-under=50 \
            -v --tb=short -x
      - uses: codecov/codecov-action@v4
        if: always()
        with:
          file: coverage.xml
          flags: unittests
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: coverage-html
          path: htmlcov/

  integration-tests:
    name: Integration Tests
    runs-on: ubuntu-latest
    needs: unit-tests
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -r requirements.txt && pip install -e ".[dev]"
      - run: pytest tests/integration/ -v --tb=short --timeout=60

  e2e-tests:
    name: E2E Tests
    runs-on: ubuntu-latest
    needs: integration-tests
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -r requirements.txt && pip install -e ".[dev]"
      - run: pytest tests/e2e/ -v --tb=short --timeout=120

  quality-gate:
    name: Quality Gate
    runs-on: ubuntu-latest
    needs: [lint, unit-tests, integration-tests, e2e-tests]
    if: always()
    steps:
      - name: Check all jobs passed
        run: |
          if [ "${{ needs.lint.result }}" != "success" ] || \
             [ "${{ needs.unit-tests.result }}" != "success" ] || \
             [ "${{ needs.integration-tests.result }}" != "success" ]; then
            echo "::error::Quality gate FAILED"
            exit 1
          fi
          echo "Quality gate PASSED"
```

### 4.2 — Workflow de Testes Criticos (Fast Path)

Criar `.github/workflows/critical-tests.yml`:
- Trigger: push em arquivos criticos (webhooks.py, chat.py, memory.py, sales_agent.py)
- Roda APENAS `pytest tests/critical/ -v --tb=long -x`
- Tempo alvo: < 30 segundos

### 4.3 — Testes E2E

Criar `tests/e2e/test_full_conversation.py`:
- test_form_submission_triggers_first_message — POST /webhook/form > verifica send_message chamado
- test_whatsapp_message_triggers_agent_reply — POST /webhook/zapi > verifica agent.reply chamado com msg correta
- test_multi_message_conversation_flow — 3 msgs sequenciais > verifica historico acumulado
- test_escalation_full_flow — msg > agent detecta [ESCALAR] > sessao marcada > supervisor notificado > resolve via API > sessao ativa

Criar `tests/e2e/test_escalation_flow.py`:
- test_manual_escalation_via_secret_command
- test_auto_escalation_via_tag
- test_deescalation_restores_ai
- test_escalation_brief_contains_lead_data

### 4.4 — Expandir Security Tests

Mover/expandir `tests/test_security.py` para `tests/unit/test_security.py`:
- Manter todos os testes existentes
- Adicionar: test_unicode_homoglyph_bypass (BUG 6)
- Adicionar: test_rate_limiter_thread_safety
- Adicionar: test_filter_output_preserves_legitimate_content
- Adicionar: test_hash_user_id_consistent

### 4.5 — Adicionar badge de status ao README

No topo do README.md, adicionar badge do GitHub Actions e coverage:
```markdown
![Tests](https://github.com/SEU_USER/closi-ai/actions/workflows/test.yml/badge.svg)
![Coverage](https://codecov.io/gh/SEU_USER/closi-ai/branch/main/graph/badge.svg)
```

### 4.6 — Verificacao Final

```bash
# Rodar suite completa
pytest tests/ -v --cov=src --cov-report=term

# Verificar que nenhum teste faz chamada real
grep -r "httpx.post\|httpx.get\|requests.post\|requests.get" tests/ --include="*.py"
# Deve retornar vazio (todos mockados)

# Verificar que app inicia normalmente
TEST_MODE=true python -c "from src.app import create_app; app = create_app(); print('OK')"
```

**Criterio de sucesso final:**
- [ ] 70+ testes passando
- [ ] 0 testes fazendo chamadas reais a APIs
- [ ] Coverage >= 50% (meta para subir progressivamente)
- [ ] 4 testes criticos passando
- [ ] Dashboard acessivel em /dashboard/tests com dados reais
- [ ] GitHub Actions workflow rodando em push/PR
- [ ] App inicia normalmente com e sem TEST_MODE

---

## NOTAS PARA O DESENVOLVEDOR

### Ordem de execucao obrigatoria
```
ETAPA 1 (fundacao) → verificar → ETAPA 2 (criticos) → verificar → ETAPA 3 (dashboard) → verificar → ETAPA 4 (CI/CD)
```

### Principio fundamental
**NUNCA modifique codigo de producao para fazer testes passarem.** Se um teste nao passa, o teste esta errado OU voce encontrou um bug real. Bugs reais devem ser documentados como `@pytest.mark.xfail(reason="BUG: descricao")` e corrigidos em PR separada.

### Mocking strategy
- `responses` library para mock de httpx/requests (Z-API, HubSpot)
- `pytest-mock` (mocker fixture) para mock de funcoes internas
- NUNCA use `unittest.mock.patch` no escopo global do modulo — sempre dentro de fixtures ou decorators
- Gevent greenlets nos testes devem ser substituidos por `threading.Thread` para evitar conflito com pytest

### Pattern para testar endpoints Flask
```python
def test_example(client, mock_claude, mock_zapi, mock_supabase):
    response = client.post("/webhook/zapi", json={"type": "ReceivedCallback", ...})
    assert response.status_code == 200
    assert response.get_json()["status"] == "queued"
```

### Como lidar com imports que fazem I/O no import time
Alguns modulos (como `src/core/llm.py`) criam clientes de API no import time. Use `TEST_MODE` para criar clientes dummy ou mock antes de importar.
