# Arquitetura — Closi AI

## Visão Geral

O Closi AI é um agente de vendas autônomo que opera no WhatsApp. Ele recebe mensagens de leads, gera respostas usando Claude (Anthropic), e gerencia o pipeline de vendas no HubSpot.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  WhatsApp    │────▶│   Closi AI   │────▶│   Supabase   │
│  (Z-API)     │◀────│   (Flask)    │     │  (PostgreSQL)│
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
┌──────────────┐     ┌──────┴───────┐     ┌──────────────┐
│  Formulário  │────▶│  SalesAgent  │────▶│   HubSpot    │
│  Web         │     │  (Claude)    │     │   CRM        │
└──────────────┘     └──────────────┘     └──────────────┘
```

## Fluxo de Mensagem

1. Lead envia mensagem no WhatsApp (ou formulário web)
2. Z-API envia webhook para `POST /webhook/zapi`
3. Debounce agrupa mensagens rápidas (10s) em uma só
4. `SalesAgent` processa com Claude (system prompt + contexto + histórico)
5. Claude responde com texto + metadata `[META]` (estágio, score, etc.)
6. Resposta é filtrada (segurança), splitada em mensagens curtas, e enviada
7. Tudo é salvo no Supabase (conversas, leads, sessions)
8. HubSpot é atualizado (contato, deal, notas)

## Camadas

### `src/api/` — Flask Blueprints

8 blueprints com responsabilidades isoladas. Nenhum contém lógica de negócio — apenas validação de request, chamada ao core, e formatação de response.

| Blueprint | Responsabilidade |
|-----------|-----------------|
| `chat.py` | Endpoint sandbox + debounce |
| `webhooks.py` | Webhooks Z-API e formulário |
| `dashboard.py` | Render de templates (6 páginas) |
| `analytics_api.py` | Dados de analytics (funil, keywords, qualidade) |
| `corrections_api.py` | CRUD correções + dual-write |
| `escalation_api.py` | Gestão de escalações |
| `hubspot_api.py` | Integração HubSpot |
| `health.py` | Health checks, métricas, config, logs |

### `src/core/` — Lógica de Negócio

Módulos puros Python (sem dependência do Flask). Podem ser testados isoladamente.

| Módulo | Responsabilidade |
|--------|-----------------|
| `database/` | 6 sub-módulos Supabase (client, conversations, leads, escalations, corrections, analytics) |
| `llm.py` | Wrapper Anthropic API com prompt caching |
| `whatsapp.py` | Client Z-API (send_message, send_typing) |
| `hubspot.py` | HubSpot API v3 (contacts, deals, notes) |
| `escalation.py` | Lógica de escalar/desescalar para humano |
| `memory.py` | ConversationMemory (histórico + context window) |
| `security.py` | Sanitização, detecção de injection, rate limiter, filtro de output |
| `message_splitter.py` | Quebra respostas longas em mensagens curtas de WhatsApp |
| `metrics.py` | Métricas de uso da API Claude |
| `logger.py` | Logging estruturado |
| `log_buffer.py` | Buffer circular para dashboard de logs |

### `src/agent/` — SalesAgent

O agente de vendas encapsula a lógica conversacional: carrega system prompt, gerencia memória, chama Claude, extrai metadata, e decide ações (responder, escalar, sincronizar CRM).

O system prompt vive em `src/agent/prompts/system_prompt.md` e define o persona, regras de vendas, e formato de resposta com tags `[META]` e `[ESCALAR]`.

### `src/core/database/` — Sub-módulos

O antigo monolito `database.py` (927 linhas) foi dividido em 6 módulos com responsabilidades claras. O `__init__.py` re-exporta todas as 31 funções para manter backward compatibility.

| Módulo | Funções |
|--------|---------|
| `client.py` | Conexão singleton, health_check, is_enabled |
| `conversations.py` | save_message, load_conversation_history, save_raw_incoming |
| `leads.py` | upsert_lead, update_lead_status, save/get_lead_metadata |
| `escalations.py` | save_escalation, resolve_escalation_record, list_escalations |
| `corrections.py` | CRUD corrections + dual-write (Supabase + JSON local) |
| `analytics.py` | Funil, keywords, qualidade, tempo por estágio |

## Padrões de Design

### Application Factory

`create_app()` em `src/app.py` cria o Flask app, configura paths de templates/static, e registra todos os blueprints. Isso permite criar múltiplas instâncias (produção, teste) com configs diferentes.

### Debounce

Leads costumam enviar várias mensagens rápidas. O `DebounceManager` agrupa mensagens recebidas em uma janela de N segundos antes de processar, evitando múltiplas chamadas ao Claude.

### Dual-Write (Corrections)

Correções são salvas simultaneamente no Supabase e em um JSON local (`local_cache/corrections.json`). Isso garante que correções não se percam se o Supabase estiver fora do ar.

### Lazy Singleton (SalesAgent)

O agente é instanciado sob demanda (`_get_agent()`) no primeiro request, evitando imports circulares durante o startup.

### Metadata via `[META]`

O Claude retorna metadata estruturada no fim da resposta usando tags `[META]`. Isso permite extrair estágio do funil, score de interesse, e dados do lead sem uma chamada extra ao LLM.

## Deploy

Railway com Dockerfile. Gunicorn + gevent (1 worker, 1000 greenlets). Health check em `/health`.

```bash
# Produção
sh start.sh

# Desenvolvimento
python -m flask --app src.app run --debug
```
