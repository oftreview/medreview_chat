# Proposta de Implementação: Wild Memory no Closi-AI

**Data:** 23/03/2026
**Autor:** Análise técnica Claude + Raphael Romie
**Versão Wild Memory:** v3.0.0
**Status do Closi-AI:** Produção ativa

---

## 1. O Problema Central

O agente de vendas do Closi-AI sofre de três problemas de memória que degradam a experiência do lead:

1. **Repete informações** — diz que "as aulas têm no máximo 30 minutos" mais de uma vez na mesma conversa porque não rastreia o que já comunicou
2. **Perde contexto em handoff** — quando escala para humano ou retoma conversa, todo o contexto de qualificação se perde
3. **Não escala** — o sistema atual (dict in-memory + lazy-load de 20 msgs) não foi projetado para 100+ conversas simultâneas

O Wild Memory resolve os três problemas com um framework de memória em camadas inspirado em 6 animais, usando Supabase como backend — a mesma infraestrutura que o Closi-AI já utiliza.

---

## 2. Mapeamento: Wild Memory ↔ Closi-AI

### O que o Wild Memory traz que o Closi-AI não tem hoje

| Capacidade | Closi-AI Atual | Wild Memory |
|-----------|---------------|-------------|
| **Memória de trabalho** | Lista de dicts {role, content} | WorkingMemory com compressão automática, tracking de tokens, restore de checkpoint |
| **Memória de longo prazo** | Nenhuma (cada sessão isolada) | Observations com 5 sinais de retrieval (semântico, entidades, FTS, recência, decay) |
| **Não repetir informações** | Nenhum mecanismo | Briefing estruturado: o agente recebe "FATOS JÁ COMUNICADOS" no contexto |
| **Handoff com contexto** | `get_escalation_brief()` — resumo manual de 10 msgs | CitationTrail + BriefingBuilder geram resumo completo com rastreabilidade |
| **Memória cross-session** | Nenhuma | Observations persistidas + ElephantRecall reconstrói contexto automaticamente |
| **Detecção de contradição** | Nenhuma | ConflictResolver 2 fases (embedding + LLM) |
| **Esquecimento ativo** | TTL de 2h destrói tudo | AntDecay: decay gradual 3 eixos (temporal, frequência, importância) |
| **Sumarização** | Nenhuma | BeeDistiller extrai observations tipadas de cada conversa |
| **Busca semântica** | Nenhuma | pgvector com embeddings + cache semântico |
| **Identidade do agente** | Arquivo system_prompt.md estático | Imprint YAML editável com cache e injection estruturada |
| **Metadados do lead** | `[META]` tags extraídas e salvas mas NUNCA reinjetadas | Observations tipadas (fact, preference, decision, goal) reinjetadas como briefing |
| **Escalabilidade** | 100+ sessões saturariam a memória | Sessões isoladas com cleanup, checkpoint, semantic cache para FAQs |

### O que o Closi-AI já tem que o Wild Memory precisa

| Componente | Status | Ação Necessária |
|-----------|--------|----------------|
| Supabase conectado e funcionando | OK | Reusar credenciais |
| Debounce de mensagens | OK | Manter como está |
| Rate limiting | OK | Manter |
| Prompt Caching no Claude | OK | Compatível com Wild Memory |
| HubSpot sync | OK | Conectar via FeedbackLayer |
| Detecção de escalação ([ESCALAR]) | OK | Manter, adicionar trigger de `end_session()` |
| Corrections (aprendizado contínuo) | OK | Migrar para ObservationType.correction |
| Métricas e analytics | OK | Manter, enriquecer com dados do Wild Memory |

---

## 3. Estratégia: Implementação em 4 Fases (Sem Risco de Quebra)

### Princípio Fundamental: SHADOW MODE

A implementação segue o padrão **shadow mode**: o Wild Memory roda EM PARALELO com o sistema atual. O sistema antigo continua funcionando normalmente enquanto o novo é validado. Só depois de validação completa fazemos o swap.

```
FASE 1: Infraestrutura          → Wild Memory instalado, tabelas criadas, testes passando
FASE 2: Shadow Mode             → Wild Memory processa em paralelo, sem afetar resposta
FASE 3: Context Injection       → Wild Memory alimenta o contexto da LLM (melhoria visível)
FASE 4: Full Takeover           → Wild Memory substitui ConversationMemory
```

---

### FASE 1 — Infraestrutura (Sem risco. Nada muda no agente.)

**Duração estimada:** 1-2 dias
**Risco:** ZERO — não toca no código do agente

**Tarefas:**

1. **Instalar Wild Memory como dependência**
   ```bash
   pip install wild-memory  # ou adicionar ao requirements.txt
   ```

2. **Habilitar pgvector no Supabase**
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

3. **Rodar migration do Wild Memory**
   - Executar `migrations/001_initial_schema.sql` no Supabase SQL Editor
   - Isso cria 14 novas tabelas e 9 RPCs — NÃO toca nas tabelas existentes
   - Tabelas: `observations`, `entity_nodes`, `entity_edges`, `reflections`, `feedback_signals`, `procedures`, `agent_checkpoints`, `semantic_cache`, `citation_trails`, `session_logs`, `broadcast_events`, `agent_imprints`

4. **Criar arquivo de configuração**
   ```yaml
   # wild_memory.yaml (na raiz do Closi-AI)
   supabase:
     url: "${SUPABASE_URL}"     # reusar do .env
     key: "${SUPABASE_KEY}"

   models:
     premium:
       model: claude-sonnet-4-20250514
     economy:
       model: claude-haiku-4-5-20251001

   embedding:
     provider: openai
     model: text-embedding-3-small

   imprint_path: memory/imprint.yaml
   procedures_path: memory/procedures/
   ```

5. **Criar imprint do agente**
   ```yaml
   # memory/imprint.yaml
   role: "Consultor de vendas da MedReview"
   values:
     - "Ajudar médicos a se preparar para provas de residência"
     - "Ser consultivo, não agressivo"
     - "Nunca inventar informações sobre preços ou módulos"
   constraints:
     - "Nunca repetir informações já comunicadas ao lead"
     - "Escalar para humano quando solicitado"
   context:
     empresa: "MedReview"
     produto: "Plataforma de estudo para residência médica"
   tone: "Amigável, consultivo, objetivo"
   ```

6. **Configurar NER para domínio MedReview**
   ```python
   ner = NERPipeline.with_domain({
       "EXAM": ["ENARE", "USP", "UNIFESP", "SUS", "HCFMUSP", "EINSTEIN"],
       "PRODUCT": ["R1", "AnestReview", "MedReview", "Módulo"],
       "SPECIALTY": ["anestesiologia", "ortopedia", "cardiologia", "cirurgia geral"],
       "PLAN": ["Premium", "Basic", "Essencial"],
   })
   ```

**Validação:** Rodar script de teste que cria WildMemory, processa 3 mensagens de teste, verifica se observations foram salvas no Supabase.

---

### FASE 2 — Shadow Mode (Risco mínimo. Sistema antigo continua respondendo.)

**Duração estimada:** 3-5 dias
**Risco:** BAIXO — Wild Memory processa em background via asyncio

**Alterações no código:**

1. **Inicializar Wild Memory no SalesAgent (sem substituir nada)**

   ```python
   # agents/sales/agent.py — adicionar ao __init__
   class SalesAgent:
       def __init__(self):
           self.memory = ConversationMemory()          # MANTÉM o antigo
           self.system_prompt = load_context()

           # Wild Memory (shadow mode)
           self._wild_memory = None
           try:
               from wild_memory import WildMemory
               self._wild_memory = WildMemory.from_config("wild_memory.yaml")
               print("[AGENT] Wild Memory inicializado (shadow mode)", flush=True)
           except Exception as e:
               print(f"[AGENT WARN] Wild Memory não disponível: {e}", flush=True)
   ```

2. **Shadow processing no reply() — não afeta a resposta**

   ```python
   # Após gerar resposta normalmente, alimenta Wild Memory em background
   if self._wild_memory:
       import asyncio
       try:
           loop = asyncio.get_event_loop()
           loop.create_task(
               self._wild_memory.process_message(
                   agent_id="closi-sales",
                   user_id=session_id,
                   message=user_message,
                   session_id=session_id,
               )
           )
       except Exception as e:
           print(f"[WILD MEMORY SHADOW] Erro (não afeta resposta): {e}", flush=True)
   ```

3. **Trigger end_session na escalação**

   ```python
   if escalate and self._wild_memory:
       asyncio.create_task(
           self._wild_memory.end_session("closi-sales", session_id, session_id)
       )
   ```

**Validação:**
- Monitorar logs `[WILD MEMORY SHADOW]` por 48h
- Verificar no Supabase: observations sendo criadas? Entidades extraídas? Conflitos detectados?
- Comparar: briefing gerado pelo Wild Memory vs `get_escalation_brief()` atual
- Verificar que NENHUMA resposta ao lead foi afetada

---

### FASE 3 — Context Injection (Risco moderado. Melhoria visível.)

**Duração estimada:** 3-5 dias
**Risco:** MODERADO — a qualidade da resposta muda (para melhor), mas precisa de validação

Esta é a fase que resolve diretamente o problema de "não repetir informações". O Wild Memory passa a ALIMENTAR o contexto da LLM com um briefing estruturado do lead.

**Alterações:**

1. **Injetar briefing do Wild Memory no contexto da LLM**

   ```python
   # agents/sales/agent.py — no reply()
   async def _get_wild_context(self, session_id: str, user_message: str) -> str:
       """Gera briefing do Wild Memory para injetar no contexto."""
       if not self._wild_memory:
           return ""

       try:
           msg_emb = self._wild_memory.embedding_cache.embed(user_message)
           context, used_ids = await self._wild_memory.recall.build_context(
               agent_id="closi-sales",
               user_id=session_id,
               message=user_message,
               msg_emb=msg_emb,
           )
           # Retorna apenas a seção de briefing (não o imprint, que já está no system_prompt)
           return context  # O BriefingBuilder já formata com seções tipadas
       except Exception as e:
           print(f"[WILD CONTEXT] Erro ao gerar briefing: {e}", flush=True)
           return ""
   ```

2. **Adicionar o briefing ao system prompt antes de chamar o Claude**

   ```python
   # No reply(), antes do call_claude():
   wild_context = await self._get_wild_context(session_id, user_message)

   # Injeta entre o system prompt e o histórico
   enriched_prompt = self.system_prompt
   if wild_context:
       enriched_prompt += f"\n\n# MEMÓRIA DO LEAD (não repita estas informações)\n{wild_context}"

   response_text = call_claude(enriched_prompt, truncated)
   ```

3. **Resultado esperado no contexto da LLM:**

   ```
   [System Prompt MedReview — ~30K tokens]

   # MEMÓRIA DO LEAD (não repita estas informações)

   ## Fatos conhecidos
   - Lead é cardiologista (obs_abc123)
   - Prova alvo: ENARE 2027 (obs_def456)
   - Já estuda pela plataforma X (obs_ghi789)

   ## Preferências
   - Prefere aulas curtas, já foi informado que aulas têm max 30min (obs_jkl012)

   ## Decisões
   - Demonstrou interesse no plano Premium (obs_mno345)

   ## Última objeção
   - Achou o preço alto comparado com concorrente Y (obs_pqr678)

   [Histórico truncado — 30 mensagens]
   ```

**Validação:**
- Testar com 10 conversas reais em sandbox
- Verificar que o agente NÃO repete informações marcadas no briefing
- Verificar que o handoff inclui contexto completo
- Comparar qualidade de resposta antes vs depois
- Monitorar custo adicional de tokens (briefing adiciona ~500-1000 tokens ao contexto)

---

### FASE 4 — Full Takeover (Risco calculado. Wild Memory substitui o antigo.)

**Duração estimada:** 5-7 dias
**Risco:** MODERADO-ALTO — substituição efetiva do sistema de memória

**Pré-requisitos:**
- Fase 3 rodando há pelo menos 1 semana sem problemas
- Métricas de qualidade mostrando melhoria
- Zero erros críticos nos logs do Wild Memory

**Alterações:**

1. **Criar WildMemoryAdapter** — wrapper que expõe a mesma interface que `ConversationMemory`

   ```python
   class WildMemoryAdapter:
       """
       Adapter que expõe a interface de ConversationMemory
       mas usa Wild Memory por baixo.

       Isso permite trocar sem alterar o resto do código.
       """
       def __init__(self, wild: WildMemory):
           self.wild = wild
           self._statuses = {}

       def add(self, user_id, role, content, channel=None):
           # Wild Memory gerencia via process_message no agent.reply()
           pass  # Já processado pelo orchestrator

       def get(self, user_id) -> list:
           working = self.wild._get_working(user_id)
           return working.messages

       def get_status(self, user_id) -> str:
           return self._statuses.get(user_id, "active")

       def set_status(self, user_id, status):
           self._statuses[user_id] = status

       def reset(self, user_id=None):
           if user_id:
               self.wild._sessions.pop(user_id, None)
           else:
               self.wild._sessions.clear()
   ```

2. **Swap no SalesAgent.__init__()**

   ```python
   # self.memory = ConversationMemory()            # DESATIVADO
   self.memory = WildMemoryAdapter(self._wild_memory)  # ATIVADO
   ```

3. **Refatorar reply() para usar pipeline completo do Wild Memory**

   O `process_message()` do Wild Memory já faz:
   - Working memory management
   - Semantic cache check
   - Context building (ElephantRecall)
   - LLM call com memory tools
   - Distillation
   - Conflict resolution
   - Checkpointing
   - Session logging

4. **Configurar cron jobs**

   ```python
   # Adicionar ao scheduler do Closi-AI (ou usar APScheduler)
   # 3am: AntDecay (esquecimento ativo)
   # 4am: Reflection (padrões e insights)
   # 5am: Feedback analysis
   ```

5. **Migrar dados históricos**
   - Script que lê `conversations` existentes e distila em observations
   - Script que migra `lead_metadata` para entity_nodes
   - Script que migra `corrections` para observations tipo correction

**Validação:**
- A/B test: 50% das conversas com Wild Memory, 50% com sistema antigo
- Monitorar: taxa de repetição de informações, NPS do lead, tempo no funil
- Rollback instantâneo: basta trocar `self.memory` de volta para `ConversationMemory()`

---

## 4. Dependências Técnicas

### Novas dependências (requirements.txt)

```
wild-memory>=3.0.0
anthropic>=0.40.0        # já existe
openai>=1.0.0            # para embeddings
spacy>=3.0.0             # para NER
pydantic>=2.0.0          # para modelos
pyyaml>=6.0              # para config
```

### Modelo spaCy

```bash
python -m spacy download pt_core_news_sm
```

### Supabase Extensions

```sql
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector para embeddings
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- trigram para FTS
```

### Variáveis de ambiente adicionais

```
OPENAI_API_KEY=sk-...                         # para embeddings
```

---

## 5. Custos Estimados

### Custo adicional mensal (100 conversas/dia)

| Componente | Custo Estimado |
|-----------|---------------|
| Embeddings (OpenAI text-embedding-3-small) | ~$15/mês |
| Distillation (Claude Haiku) | ~$45/mês |
| Conflict resolution (Claude Haiku) | ~$20/mês |
| Reflection + Goal detection (Claude Haiku) | ~$25/mês |
| **Total adicional** | **~$105/mês** |

### O que economiza

| Economia | Valor Estimado |
|---------|---------------|
| Menos tokens no prompt principal (briefing focado vs histórico bruto) | -15% do custo principal |
| Semantic cache para FAQs repetidas | -30% das chamadas ao Claude |
| Redução de conversas com repetição → menos msgs por conversa | -10% das mensagens |

**ROI estimado:** O custo do Wild Memory (~$105/mês) se paga pela redução de chamadas à API e pela melhoria na taxa de conversão (leads atendidos com mais qualidade convertem mais).

---

## 6. Pontos de Atenção e Mitigação de Riscos

| Risco | Probabilidade | Impacto | Mitigação |
|-------|-------------|---------|-----------|
| Wild Memory falha em produção | Média | Alto | Shadow mode + fallback automático para ConversationMemory |
| Custo de embeddings dispara | Baixa | Médio | EmbeddingCache (1 embed por turn) + SemanticCache (evita chamadas repetidas) |
| pgvector não disponível no plano Supabase | Baixa | Alto | Verificar plano antes de começar; todos os planos pagos suportam |
| spaCy aumenta consumo de memória do servidor | Baixa | Médio | Modelo `sm` (~15MB); monitorar RSS no Railway |
| Briefing muito grande estoura contexto | Baixa | Médio | BriefingBuilder já limita top_k observations; configurável |
| Dados históricos inconsistentes pós-migração | Média | Médio | Migração idempotente + validação antes do swap |

---

## 7. Ordem de Execução Recomendada

```
Semana 1:
  ├── Dia 1: FASE 1 — Instalar, criar tabelas, configurar
  ├── Dia 2: FASE 1 — Testes unitários, validar NER com dados MedReview
  └── Dia 3: FASE 2 — Ativar shadow mode em produção

Semana 2:
  ├── Dia 4-5: FASE 2 — Monitorar shadow mode, ajustar configs
  ├── Dia 6-7: FASE 3 — Implementar context injection
  └── Dia 7: FASE 3 — Testes com conversas reais

Semana 3:
  ├── Dia 8-10: FASE 3 — Validação em produção com injection ativo
  └── Dia 10: Decisão de ir para FASE 4

Semana 4:
  ├── Dia 11-13: FASE 4 — Adapter, swap, migração de dados
  ├── Dia 14: FASE 4 — A/B test
  └── Dia 15: Go/No-go final
```

---

## 8. Resumo: Por Que Esta Abordagem é Segura

1. **Nada quebra** — cada fase é independente. Se qualquer fase falhar, o sistema antigo continua funcionando exatamente como hoje.

2. **Shadow mode primeiro** — o Wild Memory roda em paralelo por dias antes de influenciar qualquer resposta. Validamos tudo antes de ativar.

3. **Rollback instantâneo** — trocar de `WildMemoryAdapter` para `ConversationMemory()` é uma linha de código.

4. **Mesmo banco** — Supabase já é o backend do Closi-AI. O Wild Memory cria tabelas NOVAS, não modifica as existentes.

5. **Incremental** — a Fase 3 (context injection) já resolve 80% do problema sem trocar o sistema de memória. Se necessário, podemos parar aí.
