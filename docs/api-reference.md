# API Reference — Closi AI

Base URL: `https://web-production-63ae4.up.railway.app`

## Autenticação

Webhooks Z-API e form usam `API_SECRET_TOKEN` via header ou query param.
Endpoints do dashboard e API interna não requerem autenticação (acesso interno).

---

## Chat & Webhooks

### `POST /chat`

Envia mensagem pelo sandbox (teste interativo).

**Body:**
```json
{ "message": "Quero saber sobre o curso", "session_id": "sandbox_abc123" }
```

**Response:**
```json
{
  "response": "Oi! O MedReview é a plataforma...",
  "metadata": { "funnel_stage": "discovery", "interest_score": 7 }
}
```

### `POST /webhook/zapi`

Webhook do Z-API (WhatsApp). Processa mensagens recebidas com debounce.

**Body:** Payload padrão Z-API (phone, message, etc.)

### `POST /webhook/form`

Webhook de formulário web. Cria lead e inicia conversa proativamente.

**Body:**
```json
{ "name": "João", "phone": "5531999999999", "source": "landing-page" }
```

---

## Dashboard

Todas as rotas renderizam templates HTML.

| Route | Página |
|-------|--------|
| `GET /dashboard/sandbox` | Chat de teste interativo |
| `GET /dashboard/conversations` | Histórico de conversas |
| `GET /dashboard/corrections` | Gestão de correções do agente |
| `GET /dashboard/analytics` | Analytics avançado |
| `GET /dashboard/costs` | Custos e uso de tokens |
| `GET /dashboard/logs` | Logs do sistema em tempo real |

---

## Analytics

### `GET /api/analytics/funnel`

Funil de conversão: leads por estágio, taxa de avanço, taxa de conversão.

### `GET /api/analytics/time-per-stage`

Tempo médio que leads permanecem em cada estágio do funil.

### `GET /api/analytics/keywords`

Keywords mais frequentes nas mensagens de leads.

**Query params:** `limit` (default: 30)

### `GET /api/analytics/quality`

Score de qualidade das conversas (engagement, depth, balance, progress).

**Query params:** `user_id` (opcional — analisar apenas um lead)

### `GET /api/analytics/summary`

Dashboard consolidado: funil + qualidade + keywords + correções dos últimos 7 dias.

---

## Corrections

### `GET /api/corrections`

Lista todas as correções cadastradas.

### `POST /api/corrections`

Adiciona nova correção. Dual-write: salva no Supabase e JSON local.

**Body:**
```json
{
  "trigger": "Quando perguntam sobre desconto",
  "wrong_behavior": "Oferece 50% de desconto",
  "correct_behavior": "Explicar que não há descontos, apenas parcelamento",
  "severity": "alta"
}
```

### `POST /api/corrections/reincidence`

Incrementa contador de reincidência de uma correção.

**Body:** `{ "id": "correction_uuid" }`

### `POST /api/corrections/sync`

Força sincronização do JSON local com Supabase.

### `POST /api/corrections/auto-archive`

Arquiva correções resolvidas com 0 reincidências nos últimos 30 dias.

### `GET /api/corrections/analytics`

Analytics de correções (total, por severidade, reincidência média).

**Query params:** `days` (default: 30)

---

## Escalation

### `POST /escalation/resolve`

Resolve escalação (retorna controle para IA após atendimento humano).

**Body:** `{ "phone": "5531999999999", "resolution": "Cliente satisfeito" }`

### `GET /leads/escalated`

Lista sessões atualmente em escalação humana.

### `GET /api/escalations`

Lista escalações do banco de dados.

**Query params:** `status` (pending|resolved), `limit` (default: 50)

### `GET /api/lead/<user_id>`

Retorna metadata do lead (estágio, especialidade, etc). Busca primeiro na memória, depois no Supabase.

---

## HubSpot

### `GET /api/hubspot/status`

Status da integração HubSpot (enabled, connected).

### `POST /api/hubspot/sync/<user_id>`

Força sincronização de um lead com HubSpot (contato + deal + nota).

### `GET/POST /api/hubspot/mapping`

GET: retorna mapeamento atual de estágios. POST: atualiza mapeamento.

---

## Health & Monitoring

### `GET /health`

Health check principal (usado pelo Railway).

**Response:** `{ "status": "ok", "version": "1.0" }`

### `GET /health/db`

Testa conexão Supabase (read + write + delete).

### `GET /health/hubspot`

Testa conexão HubSpot.

### `GET /health/security`

Últimos 20 eventos de segurança.

### `GET /health/memory`

Estatísticas de memória e persistência.

### `GET /api/metrics`

Métricas de uso da API Claude (tokens, custo, cache).

### `POST /api/config`

Atualiza model e max_tokens em runtime (sem restart).

**Body:** `{ "model": "claude-sonnet-4-20250514", "max_tokens": 6000 }`

### `GET /api/logs`

Logs recentes do sistema.

**Query params:** `since` (timestamp, default: 0)

---

## Session Management

### `POST /reset`

Reseta a sessão sandbox.

### `GET /history`

Histórico de mensagens da sessão sandbox.

### `GET /sessions`

Lista todas as sessões ativas.
