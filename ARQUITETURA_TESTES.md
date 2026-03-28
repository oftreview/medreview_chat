# Arquitetura de Testes — Closi AI

> Documento de planejamento e arquitetura para a estrutura de testes automatizados do Closi AI.
> Data: 2026-03-28 | Versao: 1.0

---

## 1. Diagnostico Atual

### Stack Tecnologica
- **Backend:** Python 3.11+, Flask, Gunicorn, Gevent
- **LLM:** Anthropic Claude API (com Prompt Caching)
- **Database:** Supabase (PostgreSQL)
- **Integracao:** Z-API (WhatsApp), HubSpot CRM
- **Memoria:** Wild Memory Framework (custom)
- **Scheduler:** APScheduler (background jobs)

### Estado Atual dos Testes
- **Cobertura estimada:** ~30% (apenas modulo security)
- **Testes existentes:** 6 arquivos em `tests/`
  - `test_security.py` — testes de sanitizacao, injection, rate limit (UNICO COMPLETO)
  - `test_phase2_shadow.py` — testes Wild Memory shadow
  - `test_phase3_context.py` — testes Wild Memory context
  - `test_phase4_lifecycle.py` — testes Wild Memory lifecycle
  - `test_wild_memory_setup.py` — setup Wild Memory
  - `conftest.py` — apenas path setup (sem fixtures reais)
- **CI/CD:** Nenhum configurado
- **Linting:** Ruff configurado mas sem enforcement automatico

### Gap Critico
| Metrica | Atual | Meta | Gap |
|---------|-------|------|-----|
| Cobertura de codigo | ~30% | 85%+ | -55% |
| Testes CRITICOS | 0 | 4 | -4 |
| Testes HIGH | 0 | 8+ | -8 |
| Total de test cases | ~6 | 70+ | -64 |
| CI/CD pipeline | Nenhum | Completo | Total |

---

## 2. Bugs Criticos Identificados

### CRITICO — Perda de dados / Crash em producao

**BUG 1: Race Condition no Timer de Debounce (webhooks.py:166-174)**
- Mensagens do WhatsApp podem ser perdidas quando timer e cancelado durante acumulacao
- Cenario: 3 msgs rapidas do mesmo telefone > timer resetado > msg anterior perdida
- Impacto: Perda silenciosa de mensagens do cliente

**BUG 2: Race na Eleicao do Primary Waiter (chat.py:325-328)**
- Em requests concorrentes de /chat, o ultimo request reseta o timer
- Mensagens de requests anteriores podem ser descartadas
- Impacto: Perda de contexto em conversas multi-request

**BUG 3: Race no Cleanup de Memoria (memory.py:63-76)**
- Daemon de cleanup pode remover sessao durante atualizacao ativa
- Dict `_last_access` limpo enquanto nova mensagem esta sendo processada
- Impacto: Corrupcao de estado da sessao

**BUG 4: Overlap na Truncagem de Historico (sales_agent.py:158-163)**
- Com 31 mensagens: mantém primeiras 4 + ultimas 26 = perde mensagem do meio
- Impacto: Agente perde contexto critico da conversa

### HIGH — Quebra de funcionalidades

**BUG 5: Bypass na Validacao de Telefone (webhooks.py:204-210)**
- Normalizacao ANTES de validacao permite inputs invalidos passarem
- Ex: "x1999999999" > "1999999999" > valido!

**BUG 6: Bypass Unicode em Injection Detection (security.py:31-66)**
- Regex usa apenas ASCII, Unicode confusables passam
- Ex: "ignore All your instructions" com homoglifos nao detectado

**BUG 7: Rate Limit do Form nao e Atomico (webhooks.py:194-201)**
- Limpeza de lista e checagem nao sao operacao unica
- Dois requests no limite podem ambos ver count=4 e incrementar

**BUG 8: Retry-After Header Parsing Incompleto (llm.py:169-177)**
- So trata formato decimal-seconds, nao HTTP-date
- Fallback para 1s/2s/4s mesmo se API pede espera maior

---

## 3. Arquitetura de Testes Proposta

### Piramide de Testes

```
         /\
        /E2E\          <- 5-10 testes (fluxo completo webhook>agent>response)
       /------\
      /Integracao\     <- 20-30 testes (API endpoints, DB, mocks de servicos)
     /------------\
    / Unit Tests   \   <- 40-50 testes (funcoes isoladas, logica de negocio)
   /________________\
```

### Estrutura de Diretorios

```
tests/
  conftest.py                    # Fixtures globais (app, client, mocks)
  pytest.ini                     # Configuracao pytest

  unit/                          # Testes unitarios (rapidos, sem I/O)
    test_security.py             # Sanitizacao, injection, rate limit
    test_message_splitter.py     # Split de mensagens
    test_memory.py               # Logica de memoria
    test_llm_retry.py            # Retry logic (sem chamadas reais)
    test_phone_validation.py     # Normalizacao e validacao de telefone
    test_escalation_logic.py     # Logica de escalacao
    test_sales_agent_logic.py    # Truncagem de historico, formatacao
    test_wild_memory_layers.py   # Camadas do Wild Memory

  integration/                   # Testes de integracao (com mocks de servicos)
    test_webhook_zapi.py         # Endpoint /webhook/zapi completo
    test_webhook_form.py         # Endpoint /webhook/form completo
    test_chat_api.py             # Endpoint /chat completo
    test_health_api.py           # Health checks
    test_database_ops.py         # Operacoes Supabase (mockadas)
    test_hubspot_sync.py         # Integracao HubSpot (mockada)
    test_whatsapp_send.py        # Envio Z-API (mockado)

  critical/                      # Testes de bugs criticos (race conditions)
    test_debounce_race.py        # Timer race no webhook
    test_primary_waiter_race.py  # Race no chat debounce
    test_memory_cleanup_race.py  # Race no cleanup
    test_history_truncation.py   # Truncagem de historico

  e2e/                           # Testes end-to-end (fluxo completo)
    test_full_conversation.py    # Webhook > agent > response > DB
    test_escalation_flow.py      # Fluxo completo de escalacao
    test_form_to_whatsapp.py     # Formulario > primeira mensagem

  load/                          # Testes de carga
    test_concurrent_webhooks.py  # 100 webhooks simultaneos
    locustfile.py                # Locust load testing

  fixtures/                      # Dados de teste reutilizaveis
    payloads.py                  # Payloads de webhook (Z-API, Form)
    mock_responses.py            # Respostas mockadas (Claude, Supabase)
    test_data.py                 # Dados de teste (phones, messages)
```

---

## 4. Ferramentas e Dependencias

### Dependencias de Teste (adicionar ao pyproject.toml)

```toml
[project.optional-dependencies]
dev = [
    # Core
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-flask>=1.3",
    "pytest-mock>=3.14",
    "pytest-xdist>=3.5",        # Execucao paralela

    # Mocking HTTP
    "responses>=0.25",           # Mock de requests HTTP
    "pytest-httpx>=0.30",        # Mock de httpx (usado pelo Supabase client)

    # Qualidade
    "ruff>=0.4.0",              # Linting + formatting

    # Coverage
    "coverage[toml]>=7.4",

    # Load testing
    "locust>=2.20",
]
```

### Ferramentas Escolhidas

| Categoria | Ferramenta | Motivo |
|-----------|-----------|--------|
| Framework de testes | **pytest** | Ja em uso, melhor ecossistema Python |
| Flask testing | **pytest-flask** | Fixtures nativas para Flask (client, app) |
| Mocking HTTP | **responses** | Mock de requests, ideal para Z-API e HubSpot |
| Mocking HTTPX | **pytest-httpx** | Supabase client usa httpx internamente |
| Mock geral | **pytest-mock** | Wrapper elegante do unittest.mock |
| Cobertura | **pytest-cov** | Integrado ao pytest, threshold enforcement |
| Paralelismo | **pytest-xdist** | Roda testes em paralelo (-n auto) |
| CI/CD | **GitHub Actions** | Nativo do GitHub, free tier generoso |
| Load testing | **Locust** | Python-native, facil de configurar |
| Linting | **Ruff** | Ja configurado, rapido |

### Repos de Referencia (Melhores Praticas)

| Repo | Link | Relevancia |
|------|------|-----------|
| **pytest-flask** | github.com/pytest-dev/pytest-flask | Fixtures e patterns para Flask |
| **responses** | github.com/getsentry/responses | Mock HTTP para APIs externas |
| **MockLLM** | github.com/StacklokLabs/mockllm | Mock determinístico de LLM APIs |
| **DeepEval** | github.com/confident-ai/deepeval | Avaliacao de qualidade de prompts LLM |
| **flask-api-example** | github.com/apryor6/flask_api_example | Estrutura de projeto Flask com testes |
| **pgmock** | github.com/stack-auth/pgmock | Mock in-memory de PostgreSQL |

---

## 5. Configuracao do conftest.py

```python
"""
tests/conftest.py — Fixtures compartilhadas do Closi AI test suite.

Fornece:
- app: Flask app configurada para testes
- client: Flask test client
- mock_agent: SalesAgent mockado (sem Claude/Supabase)
- mock_zapi: Z-API send_message mockado
- mock_supabase: Cliente Supabase mockado
- mock_claude: Respostas Claude deterministicas
"""
import os
import sys
import pytest

# Garante imports de src.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Modo de teste: delays curtos, sem chamadas externas
os.environ["TEST_MODE"] = "true"
os.environ["SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_KEY"] = "test-key"
os.environ["ANTHROPIC_API_KEY"] = "test-key"


@pytest.fixture
def app():
    """Flask app configurada para testes."""
    from src.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def mock_claude(mocker):
    """Mock da API Claude com respostas deterministicas."""
    mock = mocker.patch("src.core.llm.client.messages.create")
    mock.return_value.content = [
        type("TextBlock", (), {"text": "Resposta padrao do agente para testes."})()
    ]
    mock.return_value.usage = type("Usage", (), {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 100,
    })()
    return mock


@pytest.fixture
def mock_zapi(mocker):
    """Mock do Z-API send_message."""
    return mocker.patch("src.core.whatsapp.send_message", return_value=True)


@pytest.fixture
def mock_supabase(mocker):
    """Mock do cliente Supabase."""
    mock_client = mocker.MagicMock()
    mocker.patch("src.core.database.client._get_client", return_value=mock_client)
    return mock_client


@pytest.fixture
def sample_zapi_payload():
    """Payload tipico de webhook Z-API."""
    return {
        "type": "ReceivedCallback",
        "fromMe": False,
        "phone": "5511999999999",
        "body": "Quero saber mais sobre o curso R1",
    }


@pytest.fixture
def sample_form_payload():
    """Payload tipico de webhook do Quill Forms."""
    return {
        "name": "Joao Silva",
        "phone": "11999999999",
    }
```

---

## 6. CI/CD Pipeline — GitHub Actions

### Arquivo: `.github/workflows/test.yml`

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
  SUPABASE_KEY: "test-key"
  ANTHROPIC_API_KEY: "test-key"

jobs:
  # ── Lint & Format Check ──────────────────────────────────────────
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

  # ── Unit Tests ───────────────────────────────────────────────────
  unit-tests:
    name: Unit Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-flask pytest-mock responses pytest-httpx

      - name: Run unit tests with coverage
        run: |
          pytest tests/unit/ tests/critical/ \
            --cov=src --cov=core --cov=wild_memory \
            --cov-report=xml:coverage.xml \
            --cov-report=html:htmlcov \
            --cov-fail-under=70 \
            -v --tb=short -x

      - name: Upload coverage to Codecov
        if: always()
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml
          flags: unittests

      - name: Upload coverage HTML artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-html
          path: htmlcov/

  # ── Integration Tests ────────────────────────────────────────────
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

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-flask pytest-mock responses pytest-httpx

      - name: Run integration tests
        run: |
          pytest tests/integration/ \
            -v --tb=short \
            --timeout=60

  # ── Security Scan ────────────────────────────────────────────────
  security:
    name: Security Scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install bandit safety
      - run: bandit -r src/ -f json -o bandit-report.json || true
      - run: safety check --json || true

  # ── Quality Gate ─────────────────────────────────────────────────
  quality-gate:
    name: Quality Gate
    runs-on: ubuntu-latest
    needs: [lint, unit-tests, integration-tests, security]
    if: always()
    steps:
      - name: Check all jobs passed
        run: |
          if [ "${{ needs.lint.result }}" != "success" ] || \
             [ "${{ needs.unit-tests.result }}" != "success" ] || \
             [ "${{ needs.integration-tests.result }}" != "success" ]; then
            echo "Quality gate FAILED"
            exit 1
          fi
          echo "Quality gate PASSED"
```

### Arquivo: `.github/workflows/critical-tests.yml`

```yaml
name: Critical Tests (Fast)

on:
  push:
    paths:
      - "src/api/webhooks.py"
      - "src/api/chat.py"
      - "src/core/memory.py"
      - "src/agent/sales_agent.py"

jobs:
  critical:
    name: Critical Bug Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt && pip install pytest pytest-mock responses
      - run: pytest tests/critical/ -v --tb=long -x
```

---

## 7. Plano de Implementacao (3 Semanas)

### Semana 1 — Fundacao + Testes Criticos

| Dia | Tarefa | Arquivos |
|-----|--------|---------|
| D1 | Setup: conftest.py, fixtures, dependencias | tests/conftest.py, pyproject.toml |
| D1 | CI/CD: GitHub Actions workflow basico | .github/workflows/test.yml |
| D2 | CRITICO: Teste debounce race (webhook) | tests/critical/test_debounce_race.py |
| D2 | CRITICO: Teste primary waiter race (chat) | tests/critical/test_primary_waiter_race.py |
| D3 | CRITICO: Teste memory cleanup race | tests/critical/test_memory_cleanup_race.py |
| D3 | CRITICO: Teste history truncation | tests/critical/test_history_truncation.py |
| D4 | Unit: Testes security.py (expandir existentes) | tests/unit/test_security.py |
| D4 | Unit: Testes message_splitter.py | tests/unit/test_message_splitter.py |
| D5 | Unit: Testes llm.py (retry logic) | tests/unit/test_llm_retry.py |
| D5 | Unit: Testes phone validation | tests/unit/test_phone_validation.py |

### Semana 2 — Integracao + HIGH Priority

| Dia | Tarefa | Arquivos |
|-----|--------|---------|
| D6 | Integration: Webhook Z-API endpoint | tests/integration/test_webhook_zapi.py |
| D6 | Integration: Webhook Form endpoint | tests/integration/test_webhook_form.py |
| D7 | Integration: Chat API endpoint | tests/integration/test_chat_api.py |
| D7 | Integration: Health API | tests/integration/test_health_api.py |
| D8 | HIGH: Rate limit atomicidade | tests/unit/test_rate_limit_atomic.py |
| D8 | HIGH: Unicode injection bypass | tests/unit/test_unicode_bypass.py |
| D9 | Integration: Database operations | tests/integration/test_database_ops.py |
| D9 | Integration: Escalation flow | tests/integration/test_escalation.py |
| D10 | Unit: Wild Memory layers | tests/unit/test_wild_memory_layers.py |

### Semana 3 — E2E + Load + Polish

| Dia | Tarefa | Arquivos |
|-----|--------|---------|
| D11 | E2E: Fluxo completo de conversa | tests/e2e/test_full_conversation.py |
| D11 | E2E: Fluxo formulario > WhatsApp | tests/e2e/test_form_to_whatsapp.py |
| D12 | E2E: Fluxo de escalacao | tests/e2e/test_escalation_flow.py |
| D12 | Load: Locustfile para webhooks | tests/load/locustfile.py |
| D13 | Load: Teste 100 webhooks concorrentes | tests/load/test_concurrent_webhooks.py |
| D13 | Security: Bandit + Safety integration | .github/workflows/test.yml |
| D14 | Coverage: Threshold 80%, Codecov | pyproject.toml, .github/ |
| D15 | Documentacao: README de testes | tests/README.md |

---

## 8. Configuracao pytest

### Adicionar ao `pyproject.toml`

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "critical: Tests for critical bugs (race conditions, data loss)",
    "slow: Tests that take > 5 seconds",
    "integration: Tests requiring mocked external services",
    "e2e: End-to-end tests (full flow)",
    "load: Load/stress tests",
]
filterwarnings = [
    "ignore::DeprecationWarning",
]
addopts = "-v --tb=short --strict-markers"

[tool.coverage.run]
source = ["src", "core", "wild_memory"]
omit = [
    "*/tests/*",
    "*/__pycache__/*",
    "*/migrations/*",
]

[tool.coverage.report]
fail_under = 70
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if __name__",
    "pass",
]
```

---

## 9. Metricas de Sucesso

### Quality Gates para PR Merge

| Gate | Criterio | Bloqueante? |
|------|---------|-------------|
| Lint | Ruff sem erros | Sim |
| Unit Tests | 100% passando | Sim |
| Critical Tests | 100% passando | Sim |
| Integration Tests | 100% passando | Sim |
| Coverage | >= 70% (semana 1), >= 80% (semana 3) | Sim |
| Security Scan | Sem CRITICAL/HIGH | Sim |

### KPIs de Longo Prazo

| KPI | Meta 30 dias | Meta 90 dias |
|-----|-------------|-------------|
| Cobertura de codigo | 80% | 90%+ |
| Tempo de CI pipeline | < 5 min | < 3 min |
| Bugs em producao | -50% | -80% |
| Testes criticos passando | 4/4 | 4/4 |
| Mean Time to Detect (MTD) | < 1h | < 15min |

---

## 10. Comandos Rapidos

```bash
# Instalar dependencias de teste
pip install pytest pytest-cov pytest-flask pytest-mock responses pytest-httpx pytest-xdist

# Rodar todos os testes
pytest tests/ -v

# Rodar apenas testes criticos
pytest tests/critical/ -v --tb=long

# Rodar com cobertura
pytest tests/ --cov=src --cov-report=html --cov-report=term

# Rodar em paralelo (mais rapido)
pytest tests/unit/ -n auto

# Rodar apenas testes marcados
pytest -m critical
pytest -m "not slow"
pytest -m integration

# Gerar report de cobertura HTML
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html
```

---

## Proximos Passos

1. **Aprovar este plano** e priorizar Semana 1
2. **Instalar dependencias** de teste no ambiente de dev
3. **Criar conftest.py** com fixtures completas
4. **Configurar GitHub Actions** workflow basico
5. **Implementar 4 testes CRITICOS** (race conditions)
6. **Iterar** semanas 2-3 conforme plano

---

*Documento gerado automaticamente pela analise do codebase Closi AI.*
*Baseado em pesquisa de melhores praticas e repos de referencia do mercado.*
