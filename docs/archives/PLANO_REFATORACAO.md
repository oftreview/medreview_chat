# Closi AI — Plano de Refatoração Completa

> **STATUS: CONCLUÍDO** — Todos os 5 steps executados em 17/03/2026.
> Código legado (`sandbox/`, `core/`, `agents/`) ainda existe para referência mas não é mais usado.
> O entrypoint de produção é `src.app:app` via `gunicorn.conf.py`.

## Diagnóstico: Problemas Atuais

### 1. `sandbox/app.py` é um monolito (1.124 linhas)
O arquivo concentra **tudo**: rotas do dashboard, endpoints de API, lógica de debounce, webhooks WhatsApp, webhook de formulário, escalação, correções com dual-write, analytics, métricas, configuração, health checks. Isso dificulta onboarding de devs, testes e manutenção.

### 2. Nomenclatura confusa
- A pasta `sandbox/` sugere um ambiente de teste, mas contém o **app principal de produção**.
- `agents/sales/agent.py` é o único agent — a hierarquia `agents/sales/` cria profundidade desnecessária.
- `data/` mistura configuração de produto (ofertas, objections) com cache local (corrections.json).

### 3. Ausência de padrões Python profissionais
- Sem `__init__.py` em nenhum pacote.
- Sem type hints consistentes.
- Imports com `sys.path.insert(0, ...)` em vez de pacotes Python instaláveis.
- Testes manuais (`python tests/test_security.py`) em vez de pytest.
- Sem linting/formatting configurado (ruff, black).
- Sem `.env.example` para documentar variáveis de ambiente.

### 4. `core/database.py` acumula responsabilidades demais (927 linhas)
Mistura: conexão Supabase, CRUD de conversas, lead metadata, escalações, correções, analytics de funil, keywords, qualidade — tudo no mesmo arquivo.

### 5. Configuração fragmentada
- `core/config.py` tem só variáveis base, mas `sandbox/app.py` define mais 10+ configs inline (`RESPONSE_DELAY_SECONDS`, `API_SECRET_TOKEN`, `FALLBACK_MESSAGE`, etc.).
- Dual-write das correções (JSON + Supabase) está implementado dentro do `app.py` em vez de estar no módulo de dados.

### 6. Sem documentação de API
- 25+ endpoints sem documentação padronizada (OpenAPI/Swagger).
- Devs precisam ler o código para entender os endpoints.

### 7. Frontend acoplado
- Templates HTML com CSS/JS inline (centenas de linhas de estilo por página).
- CSS repetido entre páginas (cards, tabelas, etc.).

---

## Estrutura Final Proposta

```
closi-ai/
├── README.md                       # Overview profissional
├── .env.example                    # Todas as env vars documentadas
├── .gitignore
├── .dockerignore
├── Dockerfile
├── Procfile
├── railway.toml
├── pyproject.toml                  # Substitui requirements.txt (PEP 621)
├── start.sh
│
├── src/                            # ← Código-fonte principal (pacote Python)
│   ├── __init__.py
│   │
│   ├── config.py                   # TODA configuração centralizada
│   │
│   ├── app.py                      # Factory: create_app() — só wiring
│   │
│   ├── agent/                      # Agente de vendas
│   │   ├── __init__.py
│   │   ├── sales_agent.py          # Classe SalesAgent
│   │   └── prompts/
│   │       ├── system_prompt.md
│   │       └── stage_scripts.md
│   │
│   ├── api/                        # Blueprints Flask (cada um < 150 linhas)
│   │   ├── __init__.py             # register_blueprints(app)
│   │   ├── chat.py                 # /chat + debounce
│   │   ├── webhooks.py             # /webhook/zapi + /webhook/form
│   │   ├── dashboard.py            # /dashboard/* (render_template)
│   │   ├── escalation.py           # /escalation/* + /api/escalations
│   │   ├── corrections.py          # /api/corrections/*
│   │   ├── analytics.py            # /api/analytics/*
│   │   ├── hubspot_api.py          # /api/hubspot/*
│   │   └── health.py               # /health/* + /api/metrics + /api/config
│   │
│   ├── core/                       # Lógica de negócio (sem Flask)
│   │   ├── __init__.py
│   │   ├── database/               # ← database.py splitado
│   │   │   ├── __init__.py         # Re-exports (backward compat)
│   │   │   ├── client.py           # Conexão Supabase (singleton)
│   │   │   ├── conversations.py    # CRUD conversations + raw_incoming
│   │   │   ├── leads.py            # lead_metadata + sessions
│   │   │   ├── escalations.py      # Tabela escalations
│   │   │   ├── corrections.py      # Corrections + dual-write
│   │   │   └── analytics.py        # Funnel, keywords, quality, time
│   │   │
│   │   ├── debounce.py             # DebounceManager reutilizável
│   │   ├── escalation.py           # Lógica de escalação (handle, resolve)
│   │   ├── hubspot.py              # Integração HubSpot
│   │   ├── llm.py                  # Wrapper Anthropic API
│   │   ├── memory.py               # Gerenciamento de memória
│   │   ├── message_splitter.py     # Split de mensagens longas
│   │   ├── whatsapp.py             # Z-API client
│   │   ├── security.py             # Sanitização, injection, rate limit
│   │   ├── logger.py               # Logging estruturado
│   │   ├── log_buffer.py           # Buffer de logs para dashboard
│   │   └── metrics.py              # Métricas de uso da API
│   │
│   └── templates/                  # Templates Jinja2
│       ├── base.html
│       ├── components/             # ← CSS/JS compartilhados
│       │   ├── cards.css
│       │   ├── tables.css
│       │   └── charts.js
│       └── dashboard/
│           ├── sandbox.html
│           ├── conversations.html
│           ├── corrections.html
│           ├── costs.html
│           ├── analytics.html
│           └── logs.html
│
├── data/                           # Dados estáticos do produto
│   ├── product_info.json
│   ├── commercial_rules.json
│   ├── competitors.json
│   ├── objections.json
│   ├── offers.json
│   ├── conversion_bible.json
│   └── sales_techniques.md
│
├── migrations/                     # SQL migrations (Supabase)
│   ├── 001_sessions_and_conversations.sql
│   ├── 002_lead_metadata_and_escalations.sql
│   ├── 003_corrections.sql
│   └── 004_analytics_indexes.sql
│
├── tests/                          # Testes com pytest
│   ├── conftest.py                 # Fixtures compartilhadas
│   ├── test_security.py
│   ├── test_agent.py
│   ├── test_database.py
│   └── test_api.py
│
├── docs/                           # Documentação técnica
│   ├── architecture.md             # Diagrama de arquitetura
│   ├── api-reference.md            # Endpoints documentados
│   ├── botmaker-integration.md
│   └── deploy-guide.md
│
└── local_cache/                    # Cache local (gitignored)
    └── corrections.json
```

---

## Os 5 Steps da Refatoração

Cada step é independente, commitável, e mantém o app funcionando no final.
Pensado para começar hoje e terminar amanhã.

---

### STEP 1 — Fundação: Estrutura `src/` e Configuração ✅
**Tempo estimado: 20 min · Risco: Baixo**

O alicerce. Cria a nova estrutura de pastas e centraliza toda a configuração que hoje está espalhada.

| # | Tarefa | Detalhe |
|---|--------|---------|
| 1.1 | Criar `src/` com `__init__.py` | Pacote Python raiz |
| 1.2 | Mover `core/` → `src/core/` | Adicionar `__init__.py` |
| 1.3 | Mover `agents/sales/` → `src/agent/` | Renomear `agent.py` → `sales_agent.py`, adicionar `__init__.py` |
| 1.4 | Criar `src/config.py` centralizado | Juntar `core/config.py` + variáveis inline do `app.py` (API_SECRET_TOKEN, RESPONSE_DELAY_SECONDS, FALLBACK_MESSAGE, ESCALATE_COMMAND, etc.) |
| 1.5 | Criar `.env.example` | Documentar todas as env vars |
| 1.6 | Criar `pyproject.toml` | Substituir `requirements.txt`, configurar ruff + pytest |

**Resultado:** Estrutura de pastas final criada. Config unificada. Imports ainda podem estar quebrados — tudo bem, o Step 2 resolve.

**Commit:** `refactor: create src/ structure and centralize config`

---

### STEP 2 — Backend: Quebrar os Dois Monolitos ✅
**Tempo estimado: 60 min · Risco: Alto (maior concentração de mudanças)**

O coração da refatoração. Quebra os dois arquivos gigantes (`app.py` e `database.py`) em módulos menores.

| # | Tarefa | Detalhe |
|---|--------|---------|
| 2.1 | Quebrar `database.py` (927 linhas) em 6 sub-módulos | `client.py`, `conversations.py`, `leads.py`, `escalations.py`, `corrections.py`, `analytics.py` |
| 2.2 | Criar `src/core/database/__init__.py` com re-exports | Backward compat: `from src.core.database import save_message` continua funcionando |
| 2.3 | Extrair `DebounceManager` em `src/core/debounce.py` | Unifica lógica duplicada entre modo API e sandbox |
| 2.4 | Criar `src/app.py` com Application Factory | `create_app()` — só wiring, ~40 linhas |
| 2.5 | Criar 8 blueprints em `src/api/` | `chat.py`, `webhooks.py`, `dashboard.py`, `escalation.py`, `corrections.py`, `analytics.py`, `hubspot_api.py`, `health.py` |
| 2.6 | Criar `src/api/__init__.py` com `register_blueprints()` | Cola os blueprints no app |
| 2.7 | Mover dual-write de correções (JSON+Supabase) | De inline no `app.py` → `src/core/database/corrections.py` |

**Resultado:** `app.py` eliminado como monolito. Cada blueprint tem < 150 linhas. `database.py` eliminado como monolito. Cada sub-módulo com responsabilidade única.

**Commit:** `refactor: split app.py into blueprints and database.py into modules`

---

### STEP 3 — Frontend: Templates e CSS ✅
**Tempo estimado: 20 min · Risco: Baixo**

Organiza o frontend e elimina repetição de CSS entre as páginas.

| # | Tarefa | Detalhe |
|---|--------|---------|
| 3.1 | Mover templates | `sandbox/templates/` → `src/templates/` |
| 3.2 | Extrair CSS compartilhado | Cards, tabelas e botões que se repetem entre páginas → `src/templates/components/cards.css`, `tables.css` |
| 3.3 | Atualizar `base.html` | `{% include "components/cards.css" %}` dentro do `<style>` |
| 3.4 | Limpar CSS duplicado das páginas | Remover das páginas individuais o CSS que agora está em `components/` |

**Resultado:** Templates no lugar certo. CSS DRY — mudar estilo de card em 1 lugar, reflete em todas as páginas.

**Commit:** `refactor: move templates to src/ and extract shared CSS`

---

### STEP 4 — Infraestrutura: Deploy e Testes ✅
**Tempo estimado: 20 min · Risco: Médio**

Atualiza tudo que faz o app rodar (Docker, start.sh) e moderniza os testes.

| # | Tarefa | Detalhe |
|---|--------|---------|
| 4.1 | Atualizar `Dockerfile` | Usar `pyproject.toml` em vez de `requirements.txt` |
| 4.2 | Atualizar `start.sh` | Apontar para `src.app:create_app()` |
| 4.3 | Atualizar `Procfile` | Mesmo path novo |
| 4.4 | Converter testes para pytest | `conftest.py` com fixtures, adapter o `test_security.py` existente |
| 4.5 | Adicionar `tests/test_api.py` | Testes básicos de health, chat vazio, 401 sem auth |
| 4.6 | Remover `requirements.txt` | Substituído por `pyproject.toml` |
| 4.7 | Atualizar `.gitignore` | Adicionar `local_cache/`, `__pycache__/`, `.ruff_cache/` |

**Resultado:** Deploy funciona com a nova estrutura. `pytest` roda sem erros. CI-ready.

**Commit:** `refactor: update deploy config and modernize tests`

---

### STEP 5 — Documentação: README e API Reference ✅
**Tempo estimado: 20 min · Risco: Zero**

A camada de polimento para a apresentação. Nenhum código muda.

| # | Tarefa | Detalhe |
|---|--------|---------|
| 5.1 | Reescrever `README.md` | Overview profissional: o que é, stack, arquitetura (diagrama ASCII), como rodar, como deployar |
| 5.2 | Criar `docs/architecture.md` | Diagrama de fluxo: Lead → WhatsApp → Z-API → Closi AI → Claude → resposta |
| 5.3 | Criar `docs/api-reference.md` | Tabela com todos os 25+ endpoints: método, path, descrição, auth, payload |
| 5.4 | Mover `docs/botmaker-integration-guide.md` → `docs/botmaker-integration.md` | Nome mais limpo |
| 5.5 | Criar `docs/deploy-guide.md` | Substituir o `.docx` antigo por markdown |
| 5.6 | Limpar arquivos legados | Remover `ANALISE_TECNICA_CLOSI_AI.md`, `resumo-closi-ai.md`, `guia-deploy-railway.docx`, `supabase_schema.sql` (substituído pelas migrations), `PLANO_REFATORACAO.md` |

**Resultado:** Repo limpo. Qualquer dev abre o README e entende o projeto em 2 minutos. Endpoints documentados. Arquivos legados removidos.

**Commit:** `docs: professional README, API reference, and architecture`

---

## Resumo Visual

```
 STEP 1          STEP 2             STEP 3          STEP 4           STEP 5
 Fundação        Backend            Frontend        Infraestrutura   Documentação
 ─────────       ──────────         ─────────       ──────────────   ────────────
 src/            app.py → 8 BPs    templates/      Dockerfile       README.md
 config.py       database → 6 mod  CSS components  start.sh         architecture
 .env.example    debounce.py       base.html       pytest           api-reference
 pyproject.toml  factory pattern                   .gitignore       cleanup legados

 [20 min]        [60 min]          [20 min]        [20 min]         [20 min]
 Risco: Baixo    Risco: Alto       Risco: Baixo    Risco: Médio     Risco: Zero
```

**Sugestão para hoje/amanhã:**
- **Hoje:** Steps 1 + 2 (a parte pesada — estrutura + monolitos)
- **Amanhã:** Steps 3 + 4 + 5 (frontend, deploy, docs — mais leve)

---

## O que NÃO muda

- **Lógica de negócio:** Nenhuma regra de qualificação, escalação ou oferta é alterada.
- **Endpoints:** Todas as URLs permanecem idênticas (`/chat`, `/webhook/zapi`, `/dashboard/*`, `/api/*`).
- **Banco de dados:** Nenhuma migration nova necessária.
- **Deploy:** Railway continua funcionando com os mesmos env vars.
- **Prompts:** `system_prompt.md` e `stage_scripts.md` ficam intactos.

---

## Resultado Esperado para a Apresentação

Ao abrir o repo amanhã, o time verá:
1. **Estrutura clara em `src/`** — qualquer dev entende onde fica o quê em 30 segundos.
2. **Blueprints Flask** — padrão da indústria, facilita PR reviews.
3. **Config centralizada** — `.env.example` explica todas as variáveis.
4. **`pyproject.toml`** — setup profissional com linting e testes.
5. **Testes com pytest** — roda com `pytest` (sem scripts manuais).
6. **README atualizado** — overview de arquitetura, stack, como rodar.
