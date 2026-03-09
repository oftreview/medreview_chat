# Guia de Uso — Extração e Análise de Conversas Botmaker

## Visão Geral

Você tem 2 scripts que trabalham em sequência:

```
[Botmaker API] → botmaker_extractor.py → conversas_botmaker/
                                               ↓
                                    botmaker_analyzer.py
                                               ↓
                                    analise_conversas/
                                      ├── exemplos_para_prompt.txt  ← cola no agente
                                      ├── padroes_vendas.json
                                      └── relatorio_padroes.md
```

---

## PASSO 1 — Pegar suas credenciais da Botmaker

1. Acesse **https://go.botmaker.com/#/api**
2. Vá em **Configurações → API Botmaker → Credenciais**
3. Copie seu **access-token**

---

## PASSO 2 — Confirmar os endpoints na documentação

1. Acesse **https://go.botmaker.com/apidocs/**
2. Na barra lateral, procure pelas seções:
   - `customers` ou `contacts` → endpoint para listar clientes
   - `messages` → endpoint para buscar mensagens por cliente
   - `conversations` → endpoint alternativo (se existir)
3. Anote os nomes exatos e ajuste no `CONFIG` do extractor

---

## PASSO 3 — Configurar o extractor

Abra o arquivo `botmaker_extractor.py` e edite o bloco `CONFIG`:

```python
CONFIG = {
    "ACCESS_TOKEN": "cole_seu_token_aqui",

    "ENDPOINTS": {
        "customers": "/customers",    # confirme no apidocs
        "messages":  "/messages",     # confirme no apidocs
        "conversations": "/conversations",
    },

    # Opcional: filtrar por período
    "DATA_INICIO": "2024-01-01T00:00:00.000Z",
    "DATA_FIM":    "2026-03-09T23:59:59.000Z",
}
```

---

## PASSO 4 — Instalar dependências e rodar

```bash
# Instalar dependências (só na primeira vez)
pip install requests

# 1º: Extrair as conversas
python botmaker_extractor.py

# 2º: Analisar e gerar os padrões
python botmaker_analyzer.py
```

---

## PASSO 5 — Usar os resultados no seu agente

Após rodar os dois scripts, você terá:

### `analise_conversas/exemplos_para_prompt.txt`
Exemplos de conversas reais formatados para **colar direto no prompt** do seu agente.
Use assim no seu system prompt:

```
Você é um agente de vendas especializado em [produto/serviço].

Abaixo estão exemplos reais de conversas de venda bem-sucedidas.
Use esses padrões como referência para tom, linguagem e abordagem:

[cole aqui o conteúdo do exemplos_para_prompt.txt]

---
Agora responda ao cliente abaixo seguindo esses padrões:
```

### `analise_conversas/relatorio_padroes.md`
Relatório com:
- Taxa de conversão atual
- Objeções mais comuns e frequência
- Perguntas frequentes dos clientes

### `analise_conversas/padroes_vendas.json`
Todos os dados estruturados — útil para análises mais avançadas.

---

## Ajustes Comuns

### Se a extração retornar vazio:
- Verifique se o token está correto
- Confirme os nomes dos endpoints no apidocs
- Tente reduzir o período (`DATA_INICIO` / `DATA_FIM`)

### Se os remetentes das mensagens aparecerem errados:
Ajuste no `botmaker_analyzer.py`:
```python
"SENDER_FIELD": "sender",         # campo real no seu JSON
"SENDER_BOT_VALUE": "bot",        # valor quando é o bot
"SENDER_CUSTOMER_VALUE": "user",  # valor quando é o cliente
```

### Se quiser extrair só um período específico:
```python
"DATA_INICIO": "2025-01-01T00:00:00.000Z",
"DATA_FIM":    "2025-12-31T23:59:59.000Z",
```

---

## Estrutura de Arquivos Gerados

```
conversas_botmaker/
  ├── conversas_completas.json    ← todas as conversas brutas
  ├── resumo_extracao.json        ← estatísticas da extração
  └── por_cliente/
        ├── cliente_001.json
        ├── cliente_002.json
        └── ...

analise_conversas/
  ├── exemplos_para_prompt.txt   ← USE ESSE NO SEU AGENTE
  ├── padroes_vendas.json
  └── relatorio_padroes.md
```
