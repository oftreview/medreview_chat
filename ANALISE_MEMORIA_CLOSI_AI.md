# Análise do Sistema de Memória — Closi-AI

**Data:** 23/03/2026
**Objetivo:** Mapear o estágio atual do framework de memória para definir ponto de partida da evolução

---

## 1. Arquitetura Atual (Visão Geral)

O sistema de memória do Closi-AI opera em **duas camadas**:

```
┌─────────────────────────────────────────────────────────┐
│                    SalesAgent                           │
│  ┌──────────────┐    ┌──────────────┐                  │
│  │  _lead_data   │    │ system_prompt │ (~30K tokens)   │
│  │  (dict in-mem)│    │ (cacheado)    │                 │
│  └──────┬───────┘    └──────────────┘                  │
│         │                                               │
│  ┌──────▼──────────────────────────────────┐           │
│  │       ConversationMemory                 │           │
│  │  ┌────────────┐  ┌───────────────────┐  │           │
│  │  │  sessions   │  │  _session_ids     │  │           │
│  │  │  (dict)     │  │  (user→UUID)      │  │           │
│  │  ├────────────┤  ├───────────────────┤  │           │
│  │  │  statuses   │  │  _loaded_from_db  │  │           │
│  │  │  (dict)     │  │  (set)            │  │           │
│  │  ├────────────┤  ├───────────────────┤  │           │
│  │  │  _last_acc. │  │  _db_failures/    │  │           │
│  │  │  (dict+TTL) │  │  _db_successes    │  │           │
│  │  └────────┬───┘  └───────────────────┘  │           │
│  └───────────┼─────────────────────────────┘           │
└──────────────┼──────────────────────────────────────────┘
               │
    ┌──────────▼──────────┐
    │    database.py       │
    │  (Supabase Client)   │
    │                      │
    │  Tabelas:            │
    │  - conversations     │
    │  - sessions          │
    │  - leads             │
    │  - lead_metadata     │
    │  - escalations       │
    │  - corrections       │
    │  - backlog_items     │
    └──────────────────────┘
```

---

## 2. Componentes de Memória Detalhados

### 2.1 ConversationMemory (`core/memory.py`)

**Tipo:** Classe singleton instanciada dentro do `SalesAgent`

**Estruturas in-memory:**

| Estrutura | Tipo | Função |
|-----------|------|--------|
| `sessions` | `dict[str, list[dict]]` | Cache principal: user_id → lista de mensagens `{role, content}` |
| `statuses` | `dict[str, str]` | Status por sessão: "active", "escalated" |
| `_session_ids` | `dict[str, str]` | Mapeamento user_id → UUID de sessão |
| `_loaded_from_db` | `set[str]` | Controle de quais sessões já carregaram do Supabase |
| `_last_access` | `dict[str, float]` | Timestamp do último acesso (para TTL) |
| `_lock` | `threading.Lock` | Thread-safety para cleanup |

**Mecanismos:**

- **TTL:** 2 horas de inatividade → sessão removida do cache (não do DB)
- **Cleanup:** Thread daemon a cada 10 minutos varre sessões expiradas
- **Lazy-load:** Na primeira leitura, carrega últimas 20 mensagens do Supabase
- **Fallback:** Se Supabase indisponível, opera só em memória
- **Proteção de escalação:** Sessões "escalated" NÃO são removidas pelo cleanup

### 2.2 Persistência no Supabase (`core/database.py`)

**Cliente:** Singleton lazy (`_get_client()`), inicializado na primeira chamada.

**Tabelas utilizadas:**

| Tabela | Finalidade | Campos-chave |
|--------|-----------|--------------|
| `conversations` | Histórico de mensagens (tabela principal) | user_id, session_id, role, content, channel, message_type, created_at |
| `sessions` | Agrupamento de conversas por sessão UUID | id(UUID), user_id, channel, status |
| `leads` | Registro de leads por telefone | phone, name, source, status |
| `lead_metadata` | Dados estruturados coletados pela IA | user_id, funnel_stage, especialidade, prova_alvo, ano_prova, ja_estuda, plataforma_atual |
| `escalations` | Registro de escalações para humanos | user_id, session_id, motivo, brief(JSONB), status, resolution |
| `corrections` | Aprendizado contínuo (erros corrigidos) | correction_id, categoria, severidade, gatilho, regra, reincidencia |
| `messages` | **LEGADA/DEPRECADA** — fallback somente leitura | phone, role, content |
| `backlog_items` | Gestão de backlog do produto | item_id, title, status, rice_score |

### 2.3 Lead Data no Agente (`SalesAgent._lead_data`)

**Tipo:** `dict[str, dict]` — session_id → dados coletados

**Mecanismo:** A cada resposta da Claude, o agente extrai tags `[META]` e faz merge incremental:
```
[META] stage=qualificacao | especialidade=cardiologia | prova=USP
```

**Campos extraídos:** stage, especialidade, prova, ano_prova, ja_estuda, plataforma_atual

**Destinos:**
- Salvo no `lead_metadata` do Supabase via `database.save_lead_metadata()`
- Sincronizado com HubSpot (se configurado)

---

## 3. Fluxo de Memória por Mensagem

```
Lead envia mensagem
        │
        ▼
  [chat.py] POST /chat
        │
        ├── Sanitização + Detecção de injection
        ├── Rate limiting
        ├── database.save_raw_incoming()  ← salva mensagem BRUTA (pre-debounce)
        │
        ▼
  [Debounce] Acumula msgs por N segundos
        │
        ▼
  [_flush_and_respond]
        │
        ├── Combina mensagens acumuladas
        ▼
  [agent.reply()]
        │
        ├── memory.add(user_id, "user", combined)
        │     ├── Append no cache in-memory
        │     └── database.save_message() → Supabase conversations
        │
        ├── memory.get(session_id) → Retorna histórico
        │     └── _ensure_loaded() → Lazy-load do Supabase (1ª vez)
        │
        ├── _truncate_history()
        │     └── Mantém PRIMEIRAS 4 + ÚLTIMAS 26 msgs = max 30
        │
        ├── call_claude(system_prompt, truncated_history)
        │     └── System prompt ~30K tokens com Prompt Caching
        │
        ├── _extract_metadata() → Extrai tags [META]
        │     └── database.save_lead_metadata()
        │
        ├── Detecção de escalação ([ESCALAR] ou fallback)
        │
        └── memory.add(user_id, "assistant", response_text)
              ├── Append no cache in-memory
              └── database.save_message() → Supabase conversations
```

---

## 4. Diagnóstico: Problemas e Limitações

### 4.1 CRÍTICO — Memória Volátil e Sem Contexto Semântico

| Problema | Impacto | Severidade |
|----------|---------|------------|
| **Memória é puramente sequencial** — só armazena pares `{role, content}` | O agente não tem acesso a "resumo da conversa", "intenção do lead", ou "última objeção" — depende 100% da janela de contexto da LLM | CRÍTICO |
| **Truncamento por posição, não por relevância** — mantém 4 primeiras + 26 últimas | Informações cruciais do meio da conversa (ex: objeção principal, dado de qualificação) podem ser cortadas | ALTO |
| **TTL de 2 horas destrói contexto** — após cleanup, sessão some do cache | Lead que volta após 3h perde todo o contexto em memória; lazy-load só recupera 20 msgs do DB | ALTO |
| **Sem memória de longo prazo entre sessões** — cada sessão UUID é independente | Se o mesmo lead volta dias depois, o agente não sabe quem é ele, o que já conversaram, nem em que estágio estava | CRÍTICO |
| **Lead_data é dict simples, não histórico** — sobrescreve dados anteriores | Se o lead muda de ideia (ex: troca prova de USP para UNIFESP), o histórico de evolução é perdido | MÉDIO |

### 4.2 ALTO — Gaps de Persistência

| Problema | Impacto | Severidade |
|----------|---------|------------|
| **Nenhuma sumarização automática** — conversas longas viram blocos de texto crú no DB | Impossível buscar padrões, gerar insights, ou fazer handoff inteligente | ALTO |
| **Sem embedding/busca semântica** — não existe vetorização de mensagens | O agente não pode recuperar informação relevante de conversas passadas por similaridade | ALTO |
| **Tabela `conversations` cresce infinitamente** — sem particionamento ou archiving | Performance de queries degrada com volume; sem política de retenção | MÉDIO |
| **Health check insere/deleta dados reais** — probe poluindo a tabela conversations | Pode interferir com analytics; row IDs são consumidos | BAIXO |

### 4.3 MÉDIO — Limitações Estruturais

| Problema | Impacto | Severidade |
|----------|---------|------------|
| **Duplicação de código** — `core/memory.py` e `src/core/memory.py` são idênticos (exceto imports) | Manutenção dupla, risco de divergência | MÉDIO |
| **`_lead_data` vive só em memória** — se o processo reinicia, perde-se o estado parcial | `lead_metadata` no Supabase é atualizado, mas o dict local some | MÉDIO |
| **Sem versionamento de metadados** — `lead_metadata` faz upsert direto | Impossível rastrear evolução do lead pelo funil ao longo do tempo | MÉDIO |
| **Corrections carregado de JSON estático** — `data/corrections.json` é lido no boot | Tabela `corrections` no Supabase existe mas o agente usa o arquivo local | MÉDIO |

### 4.4 BAIXO — Melhorias Desejáveis

| Problema | Impacto | Severidade |
|----------|---------|------------|
| **Sem compressão de histórico** — msgs muito longas do lead ocupam contexto sem necessidade | Desperdício de tokens; custo desnecessário | BAIXO |
| **Analytics rodam queries brutas no app** — sem views materialized ou cache | Cada chamada de analytics faz N queries ao Supabase | BAIXO |
| **Sem separação de memória episódica vs semântica** — tudo é "conversa" | Fatos aprendidos (ex: "lead é cardiologista") misturados com diálogo transitório | BAIXO |

---

## 5. Schema Supabase — Estado Atual

### Tabelas existentes (7):

```sql
-- 1. leads (legada, por phone)
-- 2. messages (DEPRECADA)
-- 3. conversations (principal: mensagens multi-canal)
-- 4. sessions (agrupamento por UUID)
-- 5. lead_metadata (dados estruturados do lead)
-- 6. escalations (registros de escalação)
-- 7. corrections (aprendizado contínuo)
-- 8. backlog_items (gestão de produto)
```

### Índices existentes (17):

Concentrados em `user_id`, `created_at`, `status`, `message_type`. Não há índices para busca por conteúdo semântico, full-text search, ou trigram.

### O que NÃO existe (gaps para o framework avançado):

- Tabela de **memory_summaries** (resumos automáticos de conversas)
- Tabela de **memory_embeddings** (vetorização para busca semântica)
- Tabela de **lead_events** ou **lead_timeline** (log de transições de estado)
- Tabela de **agent_knowledge** (fatos aprendidos sobre cada lead)
- Tabela de **conversation_topics** (tópicos extraídos por conversa)
- **pgvector** extension (necessário para embeddings)
- **Full-text search** (GIN indexes)
- **Particionamento** temporal na conversations

---

## 6. Métricas de Contexto para a LLM

| Métrica | Valor Atual |
|---------|-------------|
| System prompt | ~30K tokens (cacheado via Prompt Caching) |
| Histórico máximo por chamada | 30 mensagens (4 first + 26 last) |
| Dados de lead injetados no contexto | NÃO — metadata existe mas não é injetado no prompt |
| Resumo de conversa no contexto | NÃO — não existe sumarização |
| Fatos do lead no contexto | NÃO — apenas o histórico raw |
| Memória cross-session | NÃO — cada sessão é isolada |

---

## 7. Resumo Executivo

O sistema atual é funcional para conversas curtas e sessões únicas, mas tem **5 limitações fundamentais** que impactam a qualidade do agente de vendas:

1. **Sem memória de longo prazo** — leads que voltam são tratados como desconhecidos
2. **Sem sumarização** — conversas longas perdem informações cruciais no truncamento
3. **Sem busca semântica** — impossível recuperar informação relevante de conversas passadas
4. **Sem contexto enriquecido** — a LLM não recebe os metadados coletados como contexto estruturado
5. **Sem rastreamento de evolução** — não há timeline de como o lead evoluiu pelo funil

O framework de memória complexo baseado em Supabase que você construiu pode endereçar todos esses pontos. O ponto de partida é **sólido em termos de infraestrutura** (Supabase conectado, schema básico rodando, persistência funcionando), mas **fraco em termos de inteligência de memória** (sem camadas semânticas, sem sumarização, sem memória cross-session).

---

## 8. Recomendação de Próximos Passos

Para implementar o framework avançado sobre a base atual, a sequência natural seria:

1. **Memory Summaries** — Sumarização automática ao fim de cada sessão
2. **Lead Knowledge Store** — Fatos estruturados extraídos e persistidos como "memória semântica"
3. **Context Injection** — Injetar resumo + fatos + metadata no system prompt antes de cada chamada
4. **Cross-Session Continuity** — Ao detectar lead recorrente, carregar memória de longo prazo
5. **Embeddings + pgvector** — Busca semântica para recuperar trechos relevantes de conversas passadas
6. **Lead Timeline** — Log de transições para rastreabilidade do funil
