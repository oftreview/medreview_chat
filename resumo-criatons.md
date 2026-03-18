# CLOSI AI — Resumo Executivo do Projeto

## O que é

Agente de vendas autônomo por WhatsApp para a MedReview (preparatório para Residência Médica R1). Usa Claude (Anthropic) para conduzir conversas completas de vendas: qualificação, diagnóstico, apresentação de oferta, contorno de objeções, negociação e fechamento.

---

## Arquitetura

```
Lead (WhatsApp) → Botmaker → POST /chat → Closi AI (Flask + Claude) → resposta → Botmaker → Lead
```

**Stack:** Python 3 + Flask + Gunicorn (gevent) | Deploy: Railway | DB: Supabase (opcional)

---

## Endpoints da API

| Endpoint | Método | Função |
|---|---|---|
| `/chat` | POST | Endpoint principal — recebe mensagem do lead, processa com Claude, retorna resposta |
| `/webhook/form` | POST | Recebe leads de formulários (Quill Forms → HubSpot → Botmaker) |
| `/webhook/zapi` | POST | Recebe mensagens do WhatsApp via Z-API |
| `/escalation/resolve` | POST | Resolve escalação manual e reativa o agente na sessão |
| `/health` | GET | Health check (status, uptime, sessões ativas) |

---

## Funcionalidades Core

### 1. Conversa Inteligente (Claude)
- 6 estágios de conversa: abertura → qualificação → diagnóstico → oferta → objeção → fechamento
- Tom empático, consultivo, nunca revela que é IA
- Máximo 1 pergunta por mensagem

### 2. Base de Conhecimento Completa (8 arquivos em `data/`)
- **product_info.json** — 8 produtos + 5 módulos detalhados (Aulas, Flow, Banco de Questões, Trending Topics, Flashcards)
- **offers.json** — Preços, planos e links Hotmart de pagamento
- **objections.json** — 23 objeções mapeadas com scripts de contorno
- **competitors.json** — 11 concorrentes com argumentos + 4 comparativos por módulo
- **conversion_bible.json** — 100 dores do mercado vs soluções MedReview + 25 scripts IA
- **commercial_rules.json** — Regras de desconto (até 10% auto, 10-15% verificar, >15% escalar)
- **sales_techniques.md** — Metodologia SPIN, Hormozi, Chris Voss, Cialdini, CNV + storytelling
- **corrections.json** — Correções de erros reais em produção (aprendizado contínuo)

### 3. Debounce de Mensagens
- Acumula mensagens por 10 segundos antes de processar
- Evita respostas fragmentadas quando lead manda várias mensagens seguidas
- Reduz chamadas à API do Claude

### 4. Segurança
- Sanitização de input (XSS, controle de chars, truncamento)
- Detecção de injeção de prompt (66+ patterns)
- Rate limiting por sessão (20 msg/min) e por IP (formulários)
- Filtragem de output (redação de tokens, telefones, paths internos)
- Detecção de vazamento de prompt
- Logs de auditoria sem PII (user_id hasheado)

### 5. Escalação para Humano
- Tag estruturada `[ESCALAR]` detectada automaticamente
- Fallback por string matching (4 frases)
- Notifica supervisor via WhatsApp
- Pausa o agente naquela sessão até resolução manual

### 6. Resiliência
- Retry com backoff exponencial no Claude (3 tentativas)
- Fallback gracioso se Supabase indisponível (funciona in-memory)
- Mensagem de fallback configurável se Claude falhar

### 7. Correções em Produção
- Arquivo `corrections.json` para erros reais
- Injetado com prioridade máxima no prompt do Claude
- Fluxo: time testa → encontra erro → adiciona correção → agente aprende

---

## Integração com Botmaker

### Como funciona
1. Botmaker recebe mensagem do lead no WhatsApp
2. Nó "Executar código" roda o script `botmaker-integration.js`
3. Script faz POST para `https://web-production-63ae4.up.railway.app/chat`
4. Closi AI processa e retorna resposta
5. Botmaker envia resposta ao lead

### Payload de entrada
```json
{
  "user_id": "5531999990000",
  "message": "Olá, quero saber sobre o Extensive",
  "channel": "botmaker"
}
```

### Headers
```
Authorization: Bearer {CLOSI_AI_TOKEN}
Content-Type: application/json
```

### Resposta
```json
{
  "response": "Texto da resposta do agente",
  "user_id": "5531999990000",
  "session_id": "5531999990000",
  "status": "success"
}
```

### Variáveis de saída no Botmaker
- `IA_response` — texto da resposta para enviar ao lead
- `IA_status` — "success" ou "error"

### Timing esperado
- Debounce: 10s + Claude: ~3-5s = **13-17 segundos** de resposta

---

## Arquivos do Projeto

```
closi-ai/
├── sandbox/app.py              ← Servidor Flask (API principal)
├── agents/sales/agent.py       ← Classe do agente de vendas
├── agents/sales/prompts/       ← Prompts do Claude (system + stages)
├── core/
│   ├── llm.py                  ← Cliente Claude com retry
│   ├── memory.py               ← Memória de conversas (RAM + Supabase)
│   ├── security.py             ← Sanitização, injeção, rate limit
│   ├── escalation.py           ← Fluxo de escalação humana
│   ├── database.py             ← Integração Supabase
│   ├── whatsapp.py             ← Integração Z-API
│   ├── config.py               ← Variáveis de ambiente
│   └── logger.py               ← Logs de auditoria
├── data/                       ← Base de conhecimento (8 arquivos)
├── docs/
│   ├── botmaker-integration.js ← Código para o nó Botmaker
│   └── botmaker-integration-guide.md
├── tests/test_security.py      ← Testes de segurança
├── requirements.txt
├── Dockerfile
└── Procfile
```

---

## Variáveis de Ambiente (Railway)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `ANTHROPIC_API_KEY` | Sim | Chave da API Claude |
| `API_SECRET_TOKEN` | Sim (prod) | Bearer token para autenticação |
| `SUPABASE_URL` | Não | URL do Supabase |
| `SUPABASE_KEY` | Não | Chave do Supabase |
| `SUPERVISOR_PHONE` | Não | WhatsApp do supervisor (escalações) |
| `ZAPI_INSTANCE_ID` | Não | Instância Z-API |
| `ZAPI_TOKEN` | Não | Token Z-API |
| `RESPONSE_DELAY_SECONDS` | Não | Debounce (padrão: 10) |
| `CLAUDE_MODEL` | Não | Modelo (padrão: claude-sonnet-4) |

---

## Status Atual

- **API funcionando** em Railway (testada com 11 cenários)
- **Base de conhecimento completa** com todo o conteúdo do Cérebro do Produto
- **Código Botmaker** pronto (`botmaker-integration.js`)
- **Pendente:** Configuração real no painel Botmaker (nó "Executar código" + variáveis)
