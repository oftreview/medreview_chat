# Wild Memory v3.0 — Relatório de Instalação & Guia de Integração

**Projeto:** Closi-AI (MedReview Sales Agent)
**Data da instalação:** Março 2026
**Instalador:** Claude (AI) com supervisão de Raphael
**Duração total:** ~4 sessões de trabalho

---

## 1. BUGS E CORREÇÕES NECESSÁRIAS DURANTE A INSTALAÇÃO

Estes são problemas encontrados no código original do Wild Memory ou no SQL de migração que precisaram ser corrigidos durante a instalação. Corrigir esses itens no repositório original do Wild Memory vai tornar a próxima instalação significativamente mais lisa.

### 1.1 — `search_vector` com GENERATED ALWAYS AS (SQL)

**Arquivo:** `002_wild_memory_schema.sql`
**Severidade:** Bloqueante — impede a criação da tabela

**Problema:** A coluna `search_vector` da tabela `observations` usava `GENERATED ALWAYS AS (to_tsvector('portuguese', ...))`, mas `to_tsvector('portuguese', ...)` não é uma função imutável no PostgreSQL. Funções com locale-dependent behavior são `STABLE`, não `IMMUTABLE`, então o PostgreSQL recusa a criação da coluna gerada.

**Correção aplicada:** Substituir a coluna gerada por uma coluna `tsvector` simples + trigger `BEFORE INSERT OR UPDATE`:

```sql
-- ANTES (quebra)
search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('portuguese', COALESCE(content, '')), 'A')
    || setweight(to_tsvector('simple', array_to_string(COALESCE(entities, '{}'), ' ')), 'B')
) STORED,

-- DEPOIS (funciona)
search_vector tsvector,

CREATE OR REPLACE FUNCTION observations_search_vector_update()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('portuguese', COALESCE(NEW.content, '')), 'A')
        || setweight(to_tsvector('simple', array_to_string(COALESCE(NEW.entities, '{}'), ' ')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_observations_search_vector
    BEFORE INSERT OR UPDATE OF content, entities
    ON observations
    FOR EACH ROW
    EXECUTE FUNCTION observations_search_vector_update();
```

**Recomendação para o framework:** Já entregar o SQL com o padrão trigger-based em vez de GENERATED ALWAYS AS. Isso é compatível com todas as versões do PostgreSQL 12+ e com Supabase.

---

### 1.2 — Tipo de retorno `combined_score` na RPC `retrieve_observations` (SQL)

**Arquivo:** `002_wild_memory_schema.sql`
**Severidade:** Bloqueante — faz a RPC falhar em runtime

**Problema:** A função `retrieve_observations` declarava `combined_score REAL` no `RETURNS TABLE(...)`, mas a expressão de cálculo do score (soma de multiplicações de float8) retorna `double precision`. O PostgreSQL é strict com tipos de retorno: "Returned type double precision does not match expected type real in column 11".

**Correção aplicada:**

```sql
-- ANTES
RETURNS TABLE (
    ...
    combined_score REAL
)

-- DEPOIS
RETURNS TABLE (
    ...
    combined_score DOUBLE PRECISION
)
```

**Recomendação para o framework:** Alterar para `DOUBLE PRECISION` no SQL original. Ou alternativamente, fazer `CAST(... AS REAL)` explícito dentro da query. A primeira opção é mais segura.

---

### 1.3 — Conflito asyncio + gevent (Runtime)

**Arquivo:** `wild_memory/orchestrator.py` (impacto em qualquer integração com gevent)
**Severidade:** Bloqueante em ambientes com gevent (Railway, Gunicorn gevent worker)

**Problema:** O Wild Memory usa `asyncio` extensivamente. Quando integrado com apps que usam gevent (que faz monkey-patching de threading), `asyncio.get_event_loop().run_until_complete()` gera: "Cannot run the event loop while another loop is running". Isso porque o gevent já tem seu próprio event loop rodando.

**Correção aplicada nos wrappers de integração:**

```python
try:
    loop = asyncio.get_running_loop()
    # Se já tem loop rodando (gevent), executa em thread separada de verdade
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(self._run_async_in_new_loop, coroutine).result(timeout=30)
except RuntimeError:
    # Se não tem loop rodando, cria um novo
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coroutine())
    finally:
        loop.close()
```

**Recomendação para o framework:** Criar um módulo utilitário `wild_memory/infra/async_compat.py` que encapsula esse padrão. Algo como:

```python
def run_async_safe(coro):
    """Run async coroutine safely, even under gevent monkey-patching."""
    ...
```

Isso evitaria que cada integrador precise descobrir e resolver esse conflito por conta própria.

---

### 1.4 — spaCy não instalado (Runtime — não bloqueante)

**Arquivo:** `wild_memory/processes/ner_pipeline.py`
**Severidade:** Baixa — degrada graciosamente

**Problema:** O NER Pipeline tenta carregar `spacy` e o modelo `pt_core_news_sm`. Em muitos ambientes de deploy (Railway, containers leves), spaCy não está instalado e o modelo de 15MB não está baixado. O código já trata isso (`self._nlp = "unavailable"`), mas silenciosamente.

**Recomendação para o framework:** Duas opções:
1. Documentar claramente que spaCy é opcional e que sem ele o NER usa apenas domain rules
2. Incluir `spacy` e download do modelo no setup script (`wild_memory init`), mas como dependência opcional

---

### 1.5 — Domínio hardcoded no arquivo principal

**Arquivo:** `wild_memory/medreview_domain.py`
**Severidade:** Design — não é bug

**Problema:** O arquivo de domínio MedReview (`medreview_domain.py`) está dentro do pacote `wild_memory/`. Isso mistura lógica do framework com configuração específica do cliente.

**Recomendação para o framework:** Mover para fora do pacote principal. Exemplo:

```
wild_memory/           # framework (genérico)
config/
  domains/
    medreview.py       # configuração do domínio específico
    example_domain.py  # template para novos domínios
```

---

## 2. MELHORIAS PARA FACILITAR PRÓXIMAS INSTALAÇÕES

### 2.1 — Criar um instalador/CLI robusto (`wild-memory init`)

Atualmente o `cli.py` existe mas é básico. O ideal seria:

```bash
# Instalação completa em poucos comandos
pip install wild-memory
wild-memory init --project-dir ./my-agent
wild-memory migrate --supabase-url $URL --supabase-key $KEY
wild-memory verify  # testa conexão, tabelas, embeddings
```

O `init` deveria:
- Criar `wild_memory.yaml` com prompts interativos (ou defaults sensatos)
- Criar `memory/imprint.yaml` com template preenchível
- Criar `domains/my_domain.py` com template
- Gerar os 3 wrappers de integração (shadow, context, lifecycle) adaptados ao framework do agente (Flask, FastAPI, etc.)
- Verificar dependências opcionais (spaCy, etc.)

---

### 2.2 — Wrappers de integração como parte do pacote

Os 3 arquivos criados durante a instalação (`wild_memory_shadow.py`, `wild_memory_context.py`, `wild_memory_lifecycle.py`) seguem um padrão extremamente consistente e poderiam ser gerados automaticamente ou fornecidos como módulos do próprio framework:

```python
from wild_memory.integrations import ShadowObserver, ContextInjector, LifecycleManager

# Já prontos para uso, com env var control, metrics, try/except, fire-and-forget
shadow = ShadowObserver(env_var="WILD_MEMORY_SHADOW")
context = ContextInjector(env_var="WILD_MEMORY_CONTEXT", timeout=5.0)
lifecycle = LifecycleManager(env_var="WILD_MEMORY_SHADOW")
```

Isso eliminaria a necessidade de escrever ~300 linhas de código de integração em cada instalação.

---

### 2.3 — Adapter pattern para diferentes frameworks

A instalação no Closi-AI exigiu entender exatamente onde injetar no Flask/Gunicorn. O framework poderia oferecer adapters:

```python
from wild_memory.adapters.flask import WildMemoryFlask

# Uma linha no create_app()
wild = WildMemoryFlask(app, config_path="wild_memory.yaml")

# Automaticamente:
# - Registra health endpoint
# - Inicia scheduler
# - Injeta context no sistema de LLM
# - Observa mensagens em shadow mode
```

Adapters possíveis: Flask, FastAPI, LangChain, CrewAI, bare Python.

---

### 2.4 — Schema de migração com versionamento automático

Em vez de um único SQL monolítico, ter migrações numeradas com controle de versão:

```
migrations/
  001_core_tables.sql
  002_indexes.sql
  003_rpc_functions.sql
  004_triggers.sql
```

Com um comando: `wild-memory migrate --target latest` que aplica apenas as migrações pendentes.

---

### 2.5 — Testes prontos no pacote

Os testes que foram escritos (Phase 2, 3, 4) seguem um padrão reusável. O framework poderia incluir um test suite genérico:

```bash
wild-memory test --integration  # testa conexão real com Supabase
wild-memory test --unit          # testa lógica sem deps externas
wild-memory test --smoke         # testa que nada quebra no agente host
```

---

### 2.6 — Sync wrapper nativo

O maior atrito técnico foi o async/await. O framework é 100% async, mas muitos agentes em produção são sync (Flask, Django, etc.). Oferecer uma API sync nativa eliminaria toda a complexidade de bridging:

```python
# Atualmente (async only)
await wm.process_message(...)

# Proposto (dual API)
wm.process_message_sync(...)  # wrapper com async_compat embutido
await wm.process_message(...)  # para quem já é async (FastAPI, etc.)
```

---

## 3. METODOLOGIA DE INSTALAÇÃO EM 4 FASES

Esta é a metodologia completa usada para integrar o Wild Memory no Closi-AI. Ela foi desenhada com um princípio central: **zero risco de quebrar o agente existente**.

### Princípios

1. **Cada fase é independente** — controlada por env vars separadas
2. **Fire-and-forget** — Wild Memory nunca bloqueia o fluxo principal
3. **Try/except em tudo** — qualquer erro do WM é logado e ignorado
4. **Validação antes de ativar** — cada fase roda em shadow antes de afetar respostas
5. **Rollback instantâneo** — desligar a env var volta ao comportamento original

---

### FASE 1 — Infraestrutura (Fundação)

**Objetivo:** Preparar tudo sem tocar no agente.

**O que fazer:**

1. Instalar o pacote `wild_memory` no projeto (copiar diretório ou pip install)
2. Adicionar dependências ao `requirements.txt`:
   - `openai>=1.0.0` (embeddings)
   - `pydantic>=2.0.0` (modelos)
   - `pyyaml>=6.0` (configuração)
3. Criar `wild_memory.yaml` com credenciais do Supabase e configurações
4. Criar `memory/imprint.yaml` com a identidade do agente
5. Criar o arquivo de domínio NER (entidades específicas do negócio)
6. Executar o SQL de migração no Supabase:
   - Habilitar extensões `vector` e `pg_trgm`
   - Criar todas as tabelas, indexes, triggers e RPCs
7. Rodar testes de infraestrutura (conexão, schema, NER)

**Env vars necessárias:**
- `SUPABASE_URL` e `SUPABASE_KEY` (já devem existir)
- `OPENAI_API_KEY` (para embeddings)

**Validação:**
- Testes unitários passam
- Supabase dashboard mostra as tabelas criadas
- NER extrai entidades de texto de exemplo

**Impacto no agente:** ZERO. Nenhum arquivo do agente é tocado.

---

### FASE 2 — Shadow Mode (Observação)

**Objetivo:** Wild Memory observa conversas em background sem afetar respostas.

**O que fazer:**

1. Criar `src/core/wild_memory_shadow.py`:
   - Singleton com lazy init
   - Método `observe(session_id, user_msg, assistant_msg)` que retorna imediatamente
   - Thread daemon para processamento (distillation gate → NER → distill → save)
   - Métricas thread-safe (observed, distilled, skipped, errors)
   - Try/except em tudo — nunca propaga exceções

2. Modificar o agente (2 linhas apenas):
   - Import: `from src.core.wild_memory_shadow import shadow as _wild_shadow`
   - Chamada: `_wild_shadow.observe(session_id, user_message, response_text)` após gerar resposta

3. Adicionar ao health endpoint para monitoramento

4. Escrever testes:
   - Shadow desabilitado = noop
   - Shadow nunca bloqueia (timeout test)
   - Shadow nunca propaga exceções
   - Agente continua idêntico sem a env var

**Env var:** `WILD_MEMORY_SHADOW=true`

**Validação:**
- Deploy com env var desligada → agente funciona igual
- Liga env var → health endpoint mostra `total_distilled` subindo
- `total_errors: 0` por pelo menos 24h
- Verificar no Supabase que observações estão sendo gravadas

**Impacto no agente:** ZERO nas respostas. Shadow roda em thread separada após a resposta já ter sido enviada.

---

### FASE 3 — Context Injection (Memória Ativa)

**Objetivo:** Wild Memory influencia as respostas injetando contexto do lead.

**O que fazer:**

1. Criar `src/core/wild_memory_context.py`:
   - Singleton com lazy init
   - Método `get_context(session_id, user_msg)` com timeout de 5s
   - Chama retrieval → briefing builder → formata em português
   - Retorna string ou None (nunca exceção)
   - Métricas: hits, misses, timeouts, avg_retrieval_ms

2. Modificar `call_claude()` (ou equivalente do LLM):
   - Adicionar parâmetro `memory_context: str = None`
   - Se presente, injetar como 2º bloco de system (preserva cache do 1º)

3. Modificar o agente (2 linhas):
   - `memory_briefing = _wild_context.get_context(session_id, user_message)`
   - Passar `memory_context=memory_briefing` para call_claude

**Env var:** `WILD_MEMORY_CONTEXT=true` (separada da shadow)

**Validação:**
- Deploy com env var desligada → sem mudança
- Liga → health mostra `total_hits` subindo
- Conversar como lead, sair, voltar → agente lembra sem repetir
- Verificar que prompt cache continua funcionando (métricas de cache_read)

**Impacto no agente:** Agora afeta respostas, mas com fallback seguro (se WM falhar, resposta é gerada sem contexto, como antes).

**IMPORTANTE sobre Prompt Caching:** O system prompt original do agente deve ser o 1º bloco com `cache_control: ephemeral`. O briefing do Wild Memory entra como 2º bloco SEM cache_control. Isso preserva o cache do prompt principal (~30K tokens).

---

### FASE 4 — Lifecycle Hooks + Manutenção (Consolidação)

**Objetivo:** Wild Memory reage a eventos do ciclo de vida e se auto-mantém.

**O que fazer:**

1. Criar `src/core/wild_memory_lifecycle.py`:
   - `on_escalation(session_id, user_id, metadata)` — grava feedback negativo + distila conversa completa
   - `on_session_end(session_id, user_id, reason, messages)` — distila últimas mensagens antes de limpar
   - `run_daily_maintenance()` — decay, stale marking, cache cleanup, session cleanup

2. Integrar nos hooks existentes:
   - Escalation handler: chamar `on_escalation()` após processar escalação
   - Reset/session end: chamar `on_session_end()` antes de limpar memória

3. Configurar manutenção diária:
   - **Opção A (recomendada):** APScheduler interno ao app
   - **Opção B:** Endpoint POST + cron externo (cron-job.org, Railway cron)

4. Adicionar ao health endpoint

**Env var:** Usa a mesma `WILD_MEMORY_SHADOW=true`

**Validação:**
- Forçar um reset → health mostra `total_session_ends: 1`
- Esperar o cron rodar → `total_maintenance_runs: 1`
- Verificar no Supabase que decay scores estão diminuindo em observações antigas

**Impacto no agente:** Mínimo. Lifecycle hooks rodam em threads separadas e nunca bloqueiam.

---

## 4. CHECKLIST DE INSTALAÇÃO (QUICK REFERENCE)

Para copiar e usar na próxima instalação:

```
FASE 1 — INFRAESTRUTURA
[ ] Copiar pacote wild_memory/ para o projeto
[ ] Adicionar deps ao requirements.txt (openai, pydantic, pyyaml)
[ ] Criar wild_memory.yaml
[ ] Criar memory/imprint.yaml
[ ] Criar arquivo de domínio NER
[ ] Executar SQL de migração (USAR VERSÃO COM TRIGGER, NÃO GENERATED)
[ ] Rodar testes de infra
[ ] Verificar tabelas no Supabase

FASE 2 — SHADOW MODE
[ ] Criar wild_memory_shadow.py (copiar template)
[ ] Adicionar import + observe() no agente (2 linhas)
[ ] Adicionar health endpoint
[ ] Escrever testes
[ ] Deploy com WILD_MEMORY_SHADOW=false (validar que nada muda)
[ ] Ligar WILD_MEMORY_SHADOW=true
[ ] Monitorar por 24h: total_errors deve ser 0

FASE 3 — CONTEXT INJECTION
[ ] Criar wild_memory_context.py (copiar template)
[ ] Modificar call_claude() para aceitar memory_context
[ ] Adicionar get_context() + passagem no agente (2 linhas)
[ ] Escrever testes
[ ] Deploy com WILD_MEMORY_CONTEXT=false
[ ] Ligar WILD_MEMORY_CONTEXT=true
[ ] Testar continuidade conversacional

FASE 4 — LIFECYCLE + MANUTENÇÃO
[ ] Criar wild_memory_lifecycle.py (copiar template)
[ ] Hookear em escalation e session end
[ ] Configurar scheduler (APScheduler ou cron externo)
[ ] Escrever testes
[ ] Deploy
[ ] Monitorar primeiro cron run
```

---

## 5. VISÃO PARA "INSTALAÇÃO DE POUCOS CLIQUES"

Para tornar o Wild Memory instalável em minutos (vs. dias), o framework precisaria evoluir nestes eixos:

### Curto prazo (próximas 2-3 instalações)

1. **Corrigir os bugs do SQL** (search_vector trigger, combined_score DOUBLE PRECISION)
2. **Extrair domínio para fora do pacote** (template genérico + arquivo de domínio externo)
3. **Incluir wrappers de integração prontos** (shadow, context, lifecycle como módulos do framework)
4. **Criar `async_compat.py`** para resolver conflito asyncio/gevent automaticamente
5. **Documentar a metodologia de 4 fases** (este documento)

### Médio prazo (framework maduro)

1. **CLI robusto**: `wild-memory init`, `wild-memory migrate`, `wild-memory verify`, `wild-memory test`
2. **Adapters por framework**: Flask, FastAPI, LangChain, CrewAI
3. **Dual API sync/async**: Para quem não quer lidar com asyncio
4. **Dashboard de monitoramento**: UI web simples para ver métricas, observações, entidades

### Longo prazo (produto)

1. **PyPI package**: `pip install wild-memory`
2. **One-command install**: `wild-memory install --framework flask --db supabase --domain my_config.yaml`
3. **Auto-detect**: Detectar framework, LLM provider, DB automaticamente do projeto
4. **Plugin system**: Wild Memory como plugin que se conecta a qualquer agente
5. **SaaS option**: API hospedada onde o agente só manda mensagens e recebe briefings (zero infra local)

---

## 6. ARQUITETURA FINAL (CLOSI-AI)

```
Request → Flask → SalesAgent.reply()
                      │
                      ├─ [1] _wild_context.get_context()     ← FASE 3
                      │       └─ Supabase → retrieve → briefing
                      │
                      ├─ [2] call_claude(system_prompt,
                      │       messages, memory_context)        ← prompt com briefing
                      │
                      ├─ [3] Escalation check
                      │       └─ _wild_lifecycle.on_escalation() ← FASE 4
                      │
                      ├─ [4] memory.add() (short-term)
                      │
                      └─ [5] _wild_shadow.observe()           ← FASE 2
                              └─ Thread: gate → NER → distill → Supabase

Reset → _wild_lifecycle.on_session_end()                      ← FASE 4
         └─ Thread: distill últimas msgs → Supabase

Daily → APScheduler 04:00                                     ← FASE 4
         └─ decay → stale → cleanup
```

---

*Este documento serve como referência para futuras instalações do Wild Memory em outros agentes. Os bugs listados na Seção 1 devem ser corrigidos no repositório original antes da próxima instalação.*
