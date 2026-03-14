# Análise Técnica Completa — Criatons

**Data:** 14 de março de 2026
**Escopo:** Diagnóstico, priorização e roadmap para agente de vendas WhatsApp autônomo

---

## SEÇÃO 1 — Diagnóstico Técnico Atual

### 1.1 O que já está funcionando corretamente

**Arquitetura do agente (`agents/sales/agent.py`):**
- O `SalesAgent` carrega o system prompt com todos os contextos (ofertas, objeções, concorrentes, técnicas) no init via `load_context()`, montando um prompt rico e coerente.
- O método `reply()` integra corretamente memória + LLM + detecção de escalação numa pipeline simples e legível.
- O uso de `session_id` (telefone do lead) como chave garante isolamento de conversa entre leads.

**System prompt e knowledge base (`agents/sales/prompts/`, `data/`):**
- O `system_prompt.md` está excelente — etapas de conversa bem definidas (0-6), regras de segurança rigorosas, critérios claros de desqualificação e escalação.
- O `stage_scripts.md` traz tom, exemplos concretos de resposta e anti-patterns por etapa. Isso é raro em POCs e demonstra maturidade no design do prompt.
- Os 5 arquivos JSON (`offers.json`, `product_info.json`, `competitors.json`, `objections.json`, `commercial_rules.json`) formam um knowledge base completo, com 8 produtos, 10 concorrentes mapeados e 7 tipos de objeção com framework de contorno.
- O `sales_techniques.md` traz frameworks reais (SPIN, Hormozi, Voss, Challenger Sale, Cialdini) aplicados ao contexto do produto. Conteúdo de altíssima qualidade.

**Persistência (`core/memory.py` + `core/database.py`):**
- A `ConversationMemory` implementa corretamente cache in-memory + persistência no Supabase com lazy loading (`_ensure_loaded`).
- O fallback gracioso funciona: se o Supabase não estiver configurado, o sistema opera em memória sem erros (`_get_client()` retorna `None`).
- Duas tabelas no Supabase: `messages` (legado) e `conversations` (unificada), com fallback automático entre elas.

**Segurança (`core/security.py` + `core/logger.py`):**
- Rate limiter thread-safe com `threading.Lock`, 20 msgs/min por user.
- 16 padrões de prompt injection compilados (PT-BR + EN), cobrindo jailbreak, extração de prompt, XSS, template injection.
- `filter_output()` redacta tokens de API, JWTs, hashes, telefones, emails, IPs internos e paths do sistema. Se detectar vazamento do system prompt, substitui toda a resposta por fallback.
- Logger de segurança em JSON-lines com hash de user_id (sem PII nos logs).
- Suite de testes adversariais (`tests/test_security.py`) com 30+ cenários.

**Servidor e deploy (`sandbox/app.py`, `start.sh`, `Dockerfile`):**
- Flask + gunicorn com gevent para concorrência não-bloqueante (1 worker, 1000 greenlets).
- Health checks configurados para Railway (`/health`, `/health/db`, `/health/security`).
- Debounce inteligente no endpoint `/chat` — acumula mensagens rápidas do mesmo session_id antes de processar (10s padrão), evitando chamadas redundantes ao Claude.
- Fallback message em caso de erro da LLM, retornando HTTP 200 para não travar o fluxo da Botmaker.
- Autenticação via Bearer token no endpoint `/chat`.

**Integração WhatsApp (`core/whatsapp.py`):**
- `format_phone()` normaliza robustamente (remove @s.whatsapp.net, garante DDI 55).
- `parse_incoming()` trata corretamente payloads Z-API (texto em `body` ou `text.message`), filtra `fromMe` e valida tipo `ReceivedCallback`.
- `send_message()` com timeout de 15s e tratamento de erro.

**Escalação (`core/escalation.py`):**
- Fluxo completo: marca sessão como "escalated" → envia resumo ao supervisor via WhatsApp → IA para de responder → endpoint `/escalation/resolve` para devolver controle.
- Detecção de escalação no `agent.py` por keywords na resposta ("vou conectar você com", "consultor humano").
- Endpoint `/leads/escalated` para listar sessões em atendimento humano.

**Pipeline de análise (`botmaker_pipeline/`):**
- Extrator de conversas da API Botmaker com paginação, retry e rate limiting.
- Analisador que classifica conversas (compra, objeção, dúvida), extrai padrões e gera exemplos few-shot.
- Útil para alimentar o prompt com dados reais de vendas.

### 1.2 O que está incompleto, frágil ou com débito técnico

**1. System prompt com tamanho excessivo (`agent.py:load_context()`):**
- O `load_context()` concatena TUDO numa única string: prompt + stage_scripts + sales_techniques + 5 JSONs. Isso gera um system prompt de ~15.000-20.000 tokens.
- Impacto: custo elevado por chamada ao Claude (system prompt é cobrado em toda mensagem), latência desnecessária e risco de ultrapassar limites de contexto com históricos longos.
- O prompt não é cacheado — é recarregado do disco a cada init do `SalesAgent`, que é criado uma vez na inicialização do app (aceitável, mas frágil se o agent fosse recriado por request).

**2. Escalação por string matching frágil (`agent.py:reply()`, linhas 58-60):**
```python
escalate = any(t in response_text.lower() for t in ["vou conectar você com", "consultor humano"])
```
- Se o Claude variar minimamente a frase ("vou te conectar com", "um consultor vai te atender"), a escalação não é detectada.
- Não há mecanismo estruturado (ex: tag JSON na resposta, tool use) para o agente sinalizar escalação de forma confiável.

**3. Debounce complexo com estado in-memory (`sandbox/app.py`, linhas 42-48, 66-237):**
- O mecanismo de debounce usa `threading.Timer` + `threading.Event` + dicionário compartilhado — funciona, mas é complexo e frágil.
- Depende de `WEB_CONCURRENCY=1`. Se alguém escalar para 2+ workers, o debounce quebra silenciosamente (estados em processos separados).
- O `event.wait(timeout=RESPONSE_DELAY_SECONDS + 15)` bloqueia a thread HTTP por até 25s. Com múltiplas requisições, isso pode esgotar greenlets.
- Não há limpeza de estados "órfãos" (se o timer falhar ou a request for cancelada, `_chat_state` acumula entradas mortas).

**4. Histórico sem limite de crescimento (`core/memory.py`):**
- O `ConversationMemory.get()` retorna todo o histórico in-memory da sessão, sem truncamento.
- O `_ensure_loaded()` carrega 20 mensagens do Supabase, mas depois de carregadas, TODAS as novas mensagens são adicionadas ao cache sem poda.
- Após 50+ trocas, o histórico inteiro é enviado ao Claude — explodindo tokens e custo.

**5. Dois caminhos de persistência parcialmente redundantes:**
- `database.save_message()` (tabela `messages`) e `database.save_conversation_message()` (tabela `conversations`) coexistem.
- O webhook Z-API usa `agent.reply()` que chama `memory.add()` que chama `save_conversation_message()`. Mas o webhook Z-API NÃO chama `save_message()` diretamente — porém o `load_messages()` tenta carregar da tabela `messages` como fallback.
- Isso funciona, mas é confuso e pode gerar dados duplicados ou inconsistentes.

**6. Endpoint `/chat` com inconsistência de campo:**
- A documentação (`botmaker-integration-guide.md`) mostra payload com `user_id` como campo principal.
- Mas o código do endpoint `/chat` rota API exige `session_id` como campo obrigatório e `user_id` é opcional/fallback.
- O arquivo `docs/botmaker-integration-guide.md` não menciona `session_id` — potencial de confusão na integração.

**7. Webhook `/webhook/form` sem autenticação:**
- O endpoint que recebe leads de formulário está aberto (sem Bearer token, sem validação de origem).
- Qualquer pessoa pode chamar `POST /webhook/form` com um telefone e disparar mensagem de abertura no WhatsApp — potencial de abuso.

**8. Instância única do SalesAgent como variável global:**
- `agent = SalesAgent()` é instanciado uma vez no módulo `sandbox/app.py` (linha 53).
- O system prompt é carregado uma vez e nunca atualizado. Se os JSONs de produto/preço forem alterados, é necessário reiniciar o servidor.

### 1.3 Gaps críticos para operar em produção

**GAP 1 — Sem follow-up automático:**
- O prompt descreve uma sequência de follow-up (24h, 3-5 dias, 7-10 dias), mas não há NENHUMA implementação de scheduler/cron para disparar mensagens de follow-up.
- Sem isso, leads que somem após proposta são perdidos — isso é crítico para conversão.

**GAP 2 — Sem rastreamento de estágio da conversa:**
- O prompt define 7 etapas (0-6), mas o código não rastreia em qual etapa cada lead está.
- Sem isso: não há como gerar relatórios de funil, não há como forçar transições, não há como medir onde leads desistem.

**GAP 3 — Sem integração HubSpot:**
- O CRM é gerenciado por outro dev, mas não existe nenhum hook ou evento no código que notifique o HubSpot sobre novos leads, mudanças de status ou vendas.
- Sem isso, a equipe comercial opera às cegas sobre o que o agente está fazendo.

**GAP 4 — Sem confirmação de pagamento:**
- O agente envia links Hotmart, mas não há webhook para receber confirmação de pagamento.
- Sem isso, o agente não sabe se o lead comprou — não pode executar a Etapa 6 (pós-venda).

**GAP 5 — Sem métricas de conversão:**
- Não existe tracking de: taxa de resposta, taxa de conversão, tempo médio de conversa, motivos de desqualificação, objeções mais frequentes.
- Sem isso, é impossível otimizar o agente de forma data-driven.

### 1.4 Riscos imediatos

**RISCO 1 — Memory leak no cache in-memory:**
- `ConversationMemory.sessions` cresce indefinidamente. Cada lead adiciona uma entrada que nunca é removida.
- Em produção com 100+ leads/dia, após algumas semanas o processo pode consumir GBs de RAM e crashar.

**RISCO 2 — Sem retry na chamada ao Claude (`core/llm.py`):**
- `call_claude()` faz uma única chamada sem retry, sem timeout explícito, sem tratamento de exceção.
- Se a API Anthropic retornar 429 (rate limit), 500 ou timeout, o erro propaga até o Flask e o lead recebe o fallback genérico — mas sem retry, mesmo erros transitórios viram falhas.

**RISCO 3 — Logs de payload completo no webhook (`app.py`, linha 290):**
```python
print(f"[ZAPI WEBHOOK] Payload recebido: {data}", flush=True)
```
- Imprime o payload inteiro (incluindo telefone, nome, mensagem) nos logs do Railway — violação de LGPD.

**RISCO 4 — Rate limiter em memória reseta no restart:**
- O rate limiter usa dicionário in-memory. Quando o Railway reinicia o container (deploy, healthcheck fail, etc.), todos os contadores resetam.
- Um abusador pode simplesmente esperar o próximo restart para burlar o rate limit.

**RISCO 5 — Debounce de 10 segundos bloqueia thread HTTP:**
- Cada request ao `/chat` fica bloqueada por pelo menos 10 segundos (debounce) + tempo do Claude (~5s) = ~15s.
- A Botmaker pode ter timeout de 30s. Se 50+ leads mandarem mensagem ao mesmo tempo, as greenlets ficam bloqueadas esperando e novas requests começam a falhar.

---

## SEÇÃO 2 — Próximos Passos Priorizados

### Prioridade 1 — Robustez da chamada LLM
- **Por que agora:** Sem retry, qualquer instabilidade da API Anthropic = lead sem resposta. É o ponto de falha mais crítico.
- **O que implementar:** Retry com backoff exponencial (3 tentativas, 1s/2s/4s), timeout explícito (30s), fallback message se todas as tentativas falharem, logging do erro.
- **Arquivo:** `core/llm.py`
- **Complexidade:** Baixa

### Prioridade 2 — Truncamento de histórico no envio ao Claude
- **Por que agora:** Sem isso, conversas longas estouram o contexto e geram erros ou custos explosivos.
- **O que implementar:** Antes de chamar `call_claude()`, truncar o histórico para as últimas N mensagens (ex: 30) ou N tokens (ex: 8000). Manter sempre as primeiras 2-3 mensagens (contexto de qualificação) + últimas N.
- **Arquivo:** `agents/sales/agent.py` (método `reply()`)
- **Complexidade:** Baixa

### Prioridade 3 — Evitar log de PII nos webhooks
- **Por que agora:** LGPD — telefones e mensagens de leads estão sendo impressos nos logs do Railway.
- **O que implementar:** Substituir `print(data)` por log estruturado usando `hash_user_id()` para o telefone e truncar mensagem a 20 chars nos logs.
- **Arquivo:** `sandbox/app.py` (linhas 290, 294, 300)
- **Complexidade:** Baixa

### Prioridade 4 — Escalação estruturada (substituir string matching)
- **Por que agora:** A escalação é um fluxo crítico que depende de string matching frágil — se o Claude mudar a frase, o lead fica preso.
- **O que implementar:** Duas opções: (a) Adicionar uma instrução no system prompt pedindo ao Claude que inclua uma tag `[ESCALAR]` na resposta quando quiser escalar, e detectar essa tag no código antes de enviar ao lead; (b) Usar o recurso de tool_use do Claude para escalar como chamada de ferramenta.
- **Arquivo:** `agents/sales/prompts/system_prompt.md` + `agents/sales/agent.py`
- **Complexidade:** Média

### Prioridade 5 — Autenticação no webhook de formulário
- **Por que agora:** Endpoint aberto = qualquer pessoa pode disparar mensagens de abertura para qualquer telefone.
- **O que implementar:** Validar um token secreto (header ou query param) ou validar IP de origem do Quill Forms. No mínimo, rate limit agressivo (5 leads/minuto).
- **Arquivo:** `sandbox/app.py` (função `webhook_form`)
- **Complexidade:** Baixa

### Prioridade 6 — TTL e limpeza do cache in-memory
- **Por que agora:** Memory leak — sessões nunca são removidas da memória.
- **O que implementar:** LRU cache com TTL de 2 horas para sessões inativas. Após o TTL, a sessão é removida da memória (o histórico permanece no Supabase e será recarregado sob demanda).
- **Arquivo:** `core/memory.py`
- **Complexidade:** Média

### Prioridade 7 — Rastreamento de estágio da conversa
- **Por que agora:** Sem isso, não há visibilidade de funil e o agente não tem memória estruturada de onde está.
- **O que implementar:** Adicionar campo `stage` no estado da sessão (0-6). Pedir ao Claude que retorne o estágio atual numa tag estruturada junto à resposta. Persistir no Supabase (coluna `stage` na tabela `leads`).
- **Arquivo:** `core/memory.py` + `agents/sales/agent.py` + `agents/sales/prompts/system_prompt.md` + `supabase_schema.sql`
- **Complexidade:** Média

### Prioridade 8 — Follow-up scheduler
- **Por que agora:** Leads que somem = conversão perdida. É o maior impacto em receita.
- **O que implementar:** Um job periódico (cron ou thread separada) que verifica sessões sem resposta do lead há 24h/72h/7d e dispara a mensagem de follow-up apropriada via WhatsApp. Marcar sessões que já receberam follow-up para não duplicar.
- **Arquivo:** Novo arquivo `core/scheduler.py` + integração no `sandbox/app.py`
- **Complexidade:** Alta

### Prioridade 9 — Webhook de confirmação Hotmart
- **Por que agora:** Sem saber se o lead pagou, o pós-venda não funciona.
- **O que implementar:** Endpoint `POST /webhook/hotmart` que recebe o webhook de confirmação de pagamento, associa ao telefone do lead e dispara a Etapa 6 (mensagem de boas-vindas pós-compra).
- **Arquivo:** Novo endpoint no `sandbox/app.py` + novo handler
- **Complexidade:** Média

### Prioridade 10 — Integração HubSpot (eventos básicos)
- **Por que agora:** A equipe comercial precisa de visibilidade.
- **O que implementar:** Evento de criação/atualização de contato no HubSpot quando: lead entra (form), lead é escalado, lead fecha venda. Usar a API HubSpot v3. Implementar como módulo separado, chamado via hooks nos pontos relevantes.
- **Arquivo:** Novo `core/hubspot.py` + hooks no `sandbox/app.py`
- **Complexidade:** Alta

---

## SEÇÃO 3 — Roadmap de Implementação em 3 Fases

### Fase 1 — Prova de Conceito Validada (2-3 semanas)

**Meta:** Agente estável recebendo leads reais, respondendo coerentemente, fazendo handoff quando necessário, sem riscos de segurança ou compliance.

**O que precisa estar 100% pronto:**

1. Retry + timeout na chamada ao Claude (`core/llm.py`)
2. Truncamento de histórico antes de enviar ao Claude
3. Remoção de PII dos logs (LGPD)
4. Escalação estruturada (tag `[ESCALAR]` ou mecanismo equivalente)
5. Autenticação no `/webhook/form`
6. TTL no cache in-memory para evitar memory leak
7. Documentação atualizada do endpoint `/chat` (resolver inconsistência session_id vs user_id)

**Critério de conclusão:**
- Agente responde consistentemente a 50+ leads de teste sem erros.
- Escalação funciona em 100% dos cenários definidos (lead pede humano, desconto acima de 15%, etc.).
- Nenhuma PII nos logs do Railway.
- Memory permanece estável após 48h de operação contínua.

**Dependências:** Nenhuma externa. Tudo é refatoração interna.

**O que NÃO fazer nesta fase:**
- Integração HubSpot
- Follow-up automático
- Webhook Hotmart
- Dashboard de métricas
- Personalização por perfil de lead
- A/B testing de prompts

---

### Fase 2 — MVP que Gera Resultado de Venda (4-6 semanas acumuladas)

**Meta:** Agente capaz de qualificar leads, contornar objeções básicas, enviar link de pagamento, registrar no HubSpot e detectar pagamento.

**Features incrementais:**

1. Rastreamento de estágio da conversa (0-6) com persistência
2. Follow-up scheduler (3 mensagens programadas para leads inativos)
3. Webhook de confirmação Hotmart com pós-venda automático
4. Integração HubSpot básica (criar contato, atualizar status, registrar venda)
5. Dashboard simples de métricas (total leads, conversão, escalações, estágio do funil) — endpoint JSON + HTML básico
6. Unificação das tabelas `messages` e `conversations` (eliminar redundância)
7. Prompt caching (Anthropic prompt caching) para reduzir custo do system prompt

**Critério de conclusão:**
- Pipeline completo funcionando: formulário → abertura → qualificação → oferta → pagamento → pós-venda.
- Follow-up dispara automaticamente para leads inativos.
- HubSpot reflete o estado atual de cada lead.
- Taxa de conversão mensurável (mesmo que baixa).

**Dependências:**
- Fase 1 completa.
- Credenciais da API Hotmart (webhook postback).
- Credenciais da API HubSpot (fornecidas pelo dev de infra).

**O que NÃO fazer nesta fase:**
- Transferência direta para Botmaker (manter notificação via WhatsApp)
- A/B testing de prompts
- Personalização avançada por perfil
- Multi-idioma
- Voice messages

---

### Fase 3 — V1 com Vendas Autônomas (8-12 semanas acumuladas)

**Meta:** Agente opera de forma autônoma com inbound, faz follow-up inteligente, personaliza abordagem por perfil de lead e tem métricas para otimização contínua.

**Features:**

1. Detecção automática de perfil de lead (early-stage, high-urgency, indeciso, comparador, preço-sensível) com base nas respostas da qualificação
2. Seleção dinâmica de oferta baseada no perfil (ao invés de depender 100% do Claude)
3. Follow-up inteligente com personalização (referência à especialidade, timing da prova)
4. A/B testing de variações do prompt (abertura, fechamento, contorno de objeções)
5. Dashboard completo: funil por estágio, taxa de conversão por oferta, tempo médio por etapa, objeções mais frequentes, performance do follow-up
6. Integração Botmaker para transferência direta (quando API estiver disponível)
7. Few-shot examples reais no prompt (usando output do `botmaker_analyzer.py` com dados de conversas reais)
8. Desconto dinâmico dentro das regras comerciais (o agente calcula e aplica até 10% sem escalar)
9. Detecção de áudio/imagem no WhatsApp com resposta adequada ("Vi que mandou um áudio, pode me escrever por texto?")
10. Rate limiting persistente (Redis ou Supabase) para sobreviver a restarts

**Critério de conclusão:**
- Agente gera vendas de forma autônoma com taxa de conversão mensurável e crescente.
- Dashboard permite otimização semanal baseada em dados.
- Follow-up recupera pelo menos 10% dos leads inativos.
- A/B tests mostram diferença estatística entre variações de prompt.

**Dependências:**
- Fase 2 completa.
- Dados reais de conversas para alimentar o analyzer (mínimo 100 conversas).
- API Botmaker documentada para transferência.

**O que NÃO fazer nesta fase:**
- Outbound proativo (cold outreach)
- Multi-canal (Instagram, Telegram)
- Vídeo/voz do agente
- Integração com sistema de aulas da MedReview

---

## Primeiros 3 Commits

### Commit 1: `fix: adicionar retry e timeout na chamada ao Claude`

**O que faz:**
- Refatora `core/llm.py` para incluir retry com backoff exponencial (3 tentativas: 1s, 2s, 4s).
- Adiciona timeout de 30s na chamada.
- Loga erros com contagem de tentativas.
- Se todas falharem, levanta exceção com mensagem clara para o caller tratar.

**Arquivos:** `core/llm.py`

### Commit 2: `fix: truncar histórico e remover PII dos logs`

**O que faz:**
- Em `agents/sales/agent.py`, trunca o histórico a 30 mensagens antes de enviar ao Claude (mantém as 3 primeiras + últimas 27).
- Em `sandbox/app.py`, substitui `print(data)` no webhook por log sem PII (usa `hash_user_id` e trunca mensagem).
- Adiciona TTL de 2h no `core/memory.py` com limpeza periódica de sessões inativas.

**Arquivos:** `agents/sales/agent.py`, `sandbox/app.py`, `core/memory.py`

### Commit 3: `feat: escalação estruturada via tag no prompt`

**O que faz:**
- Adiciona instrução no `system_prompt.md`: quando o agente decidir escalar, deve incluir `[ESCALAR]` no início da resposta.
- Em `agent.py`, detecta e remove a tag `[ESCALAR]` da resposta antes de enviar ao lead.
- Se `[ESCALAR]` for detectado, executa o fluxo de escalação (notifica supervisor, marca sessão).
- Mantém o string matching atual como fallback, mas prioriza a tag.

**Arquivos:** `agents/sales/prompts/system_prompt.md`, `agents/sales/agent.py`
