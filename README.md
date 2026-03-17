# Criatons

Agente autônomo de vendas no WhatsApp para a **MedReview** — plataforma de preparação para provas de residência médica.

O Criatons recebe mensagens de leads via WhatsApp (Z-API) e formulários web, conduz conversas de vendas consultivas usando Claude (Anthropic) e sincroniza dados com HubSpot CRM.

## Arquitetura

```
src/
├── app.py              # Application factory (Flask)
├── config.py           # Todas as env vars centralizadas
├── agent/              # SalesAgent + prompts
├── api/                # 8 Flask Blueprints (< 150 linhas cada)
├── core/               # Lógica de negócio (sem Flask)
│   ├── database/       # 6 sub-módulos Supabase
│   ├── llm.py          # Wrapper Anthropic API
│   ├── whatsapp.py     # Z-API client
│   ├── hubspot.py      # HubSpot CRM
│   ├── escalation.py   # Transferência para humanos
│   ├── memory.py       # Gestão de contexto
│   └── security.py     # Sanitização, rate limit, filtros
├── templates/          # Jinja2 (dashboard)
└── static/css/         # CSS compartilhado
```

Para mais detalhes, veja `docs/architecture.md`.

## Stack

- **Backend**: Python 3.12, Flask, Gunicorn + gevent
- **LLM**: Anthropic Claude (prompt caching, extração de metadata via `[META]`)
- **Database**: Supabase (PostgreSQL)
- **WhatsApp**: Z-API
- **CRM**: HubSpot API v3
- **Deploy**: Railway

## Setup Local

```bash
# 1. Clone e entre no diretório
git clone <repo-url> && cd criatons

# 2. Crie o virtualenv
python3.12 -m venv .venv && source .venv/bin/activate

# 3. Instale dependências
pip install -r requirements.txt

# 4. Configure o ambiente
cp .env.example .env
# Edite .env com suas chaves (Anthropic, Supabase, Z-API, HubSpot)

# 5. Rode
python -m flask --app src.app run --debug --port 5000
```

Para produção:

```bash
sh start.sh
```

## Testes

```bash
pytest tests/ -v
```

## Endpoints Principais

| Grupo | Path | Descrição |
|-------|------|-----------|
| Chat | `POST /chat` | Mensagem do sandbox (teste) |
| Webhooks | `POST /webhook/zapi` | Webhook WhatsApp (Z-API) |
| Webhooks | `POST /webhook/form` | Webhook formulário web |
| Dashboard | `GET /dashboard/*` | 6 páginas (sandbox, conversas, correções, analytics, custos, logs) |
| Analytics | `GET /api/analytics/*` | Funil, keywords, qualidade, tempo por estágio |
| Corrections | `GET/POST /api/corrections` | CRUD de correções do agente |
| Escalation | `POST /escalation/resolve` | Resolver escalação |
| HubSpot | `GET /api/hubspot/status` | Status da integração |
| Health | `GET /health` | Health check (Railway) |

Referência completa: `docs/api-reference.md`

## Variáveis de Ambiente

Veja `.env.example` para a lista completa com descrições. As principais:

- `ANTHROPIC_API_KEY` — Chave da API Anthropic (obrigatória)
- `SUPABASE_URL` / `SUPABASE_KEY` — Conexão Supabase
- `ZAPI_INSTANCE_ID` / `ZAPI_TOKEN` — Integração WhatsApp
- `HUBSPOT_ACCESS_TOKEN` — CRM (opcional, `HUBSPOT_ENABLED=true`)

## Estrutura do Projeto

```
criatons/
├── src/                  # Código-fonte principal
├── data/                 # Dados estáticos do produto (JSON)
├── tests/                # Testes pytest
├── docs/                 # Documentação técnica
├── migrations/           # SQL migrations (Supabase)
├── pyproject.toml        # Metadata e config de ferramentas
├── requirements.txt      # Dependências (pip)
├── Dockerfile            # Build de produção
├── gunicorn.conf.py      # Config do servidor
├── start.sh              # Entrypoint de produção
└── railway.toml          # Config Railway
```

## Licença

Projeto proprietário — MedReview / Criatons.
