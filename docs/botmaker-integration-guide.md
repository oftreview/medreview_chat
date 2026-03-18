# Integração Botmaker ↔ Closi AI (v3)

> Última atualização: 2026-03-18
> Versão do código JS: v3

---

## Visão geral

A Botmaker é a camada de canal (WhatsApp). O Closi AI é a camada de inteligência.
A integração é uma chamada HTTP simples: Botmaker envia a mensagem do lead, Closi AI devolve a resposta da IA.

O endpoint já está em produção e funcionando. Este guia documenta tudo que o dev precisa saber para configurar na Botmaker.

---

## Endpoint

```
POST https://web-production-63ae4.up.railway.app/chat
```

## Headers obrigatórios

```
Content-Type:  application/json
Authorization: Bearer SEU_API_SECRET_TOKEN
```

---

## Payload (request)

```json
{
  "user_id":  "5531999990000",
  "message":  "Olá, quero saber sobre o Extensive",
  "channel":  "botmaker"
}
```

| Campo        | Tipo   | Obrigatório | Descrição |
|--------------|--------|-------------|-----------|
| `user_id`    | string | sim         | Telefone do lead com DDI (ex: `5531999990000`). Na Botmaker: `contact?.whatsApp` ou `contact?.phone`. É a chave primária de identificação — toda a memória da conversa e funil de vendas fica indexada por este campo. |
| `message`    | string | sim         | Texto da mensagem do lead. Na Botmaker: `user_message`. |
| `channel`    | string | não         | Use `"botmaker"`. Registra a origem da mensagem no banco. |
| `session_id` | string | não         | Identificador de sessão. Se ausente, `user_id` é usado automaticamente. Útil se múltiplas sessões coexistirem para o mesmo lead. |

> **Importante:** O nome do campo é `message`, não `user_message`. O `user_message` é a variável da Botmaker; ao montar o payload, ela é mapeada para `message`.

---

## Resposta (response)

### Sucesso normal

```json
{
  "response":      "Olá! Fico feliz em falar com você...",
  "responses":     ["Olá! Fico feliz em falar com você...", "Me conta: qual especialidade médica te interessa?"],
  "delay_seconds": 1.5,
  "user_id":       "5531999990000",
  "session_id":    "5531999990000",
  "status":        "success"
}
```

| Campo           | Tipo     | Descrição |
|-----------------|----------|-----------|
| `response`      | string   | Primeira parte da resposta (retrocompatível com v2). |
| `responses`     | string[] | Array com todas as partes da resposta. Pode ter 1, 2 ou 3 itens. Usar este campo garante que o lead receba a resposta completa. |
| `delay_seconds` | number   | Delay recomendado (em segundos) entre envio de cada parte. Atualmente ~3s. Simula digitação natural. |
| `user_id`       | string   | Mesmo `user_id` enviado no request. |
| `session_id`    | string   | Sessão utilizada. |
| `status`        | string   | `"success"` — tudo OK. |

### Sessão escalada (lead em atendimento humano)

Quando a IA detecta que precisa transferir para um humano (ou quando um supervisor escala manualmente), a sessão é marcada como "escalated". A partir daí, a IA para de responder:

```json
{
  "response":   "",
  "user_id":    "5531999990000",
  "session_id": "5531999990000",
  "status":     "escalated_session"
}
```

O `response` vem vazio. O código JS (v3) substitui automaticamente por uma mensagem amigável ao lead.

Na Botmaker, use `IA_status === "escalated"` para desviar o fluxo para atendimento humano.

> **Nota técnica:** A API retorna `status: "escalated_session"` mas o código JS (v3) normaliza isso para `"escalated"` na variável `IA_status` para simplificar o fluxo na Botmaker.

### Erro interno (Claude falhou, banco off, etc.)

```json
{
  "response":   "Estou com uma instabilidade agora, em breve um consultor vai te atender.",
  "user_id":    "5531999990000",
  "session_id": "5531999990000",
  "status":     "error"
}
```

HTTP 200 mesmo em falha interna, para não travar o fluxo da Botmaker. O `response` contém uma mensagem fallback amigável que pode ser enviada ao lead.

### Erros HTTP

| HTTP | Causa | Ação |
|------|-------|------|
| 401  | Token inválido ou ausente | Verifique `CLOSI_AI_TOKEN` |
| 400  | `user_id` ou `message` vazio | Verifique variáveis do fluxo |
| 429  | Rate limit (20 msgs/min por lead) | Aguarde e reenvie |

---

## Timeout

```
30.000 ms (30 segundos)
```

Composição do tempo: debounce de 10s (acumula mensagens rápidas) + processamento Claude ~3-5s + margem.
Tempo típico de resposta: **13-17 segundos**.

---

## Variáveis disponíveis no nó Botmaker

### Entrada (automática da Botmaker)

```javascript
contact?.whatsApp   // número WhatsApp do lead (prioridade)
contact?.phone      // telefone genérico (fallback)
user_message        // mensagem digitada pelo lead
```

### Saída (disponível nos nós seguintes)

```javascript
IA_response       // texto da resposta principal (string)
IA_responses      // array com todas as partes da resposta (array)
IA_status         // "success" | "error" | "escalated" (string)
IA_has_multipart  // true se a resposta tem mais de 1 parte (boolean)
IA_delay_seconds  // delay recomendado entre partes em segundos (number)
```

---

## Como configurar na Botmaker

1. Crie um nó **"Executar código"** do tipo Node.js no fluxo
2. Cole o conteúdo de `botmaker-integration.js` (v3)
3. Substitua `SEU_API_SECRET_TOKEN_AQUI` pelo token fornecido (variável `API_SECRET_TOKEN` no Railway)
4. Garanta que `user_message` está disponível no contexto antes deste nó
5. No nó seguinte, use `IA_response` para enviar a resposta ao lead
6. (Recomendado) Adicione nó condicional baseado em `IA_status`:
   - `"success"` → envia `IA_response` ao lead
   - `"escalated"` → desvia para fila de atendimento humano
   - `"error"` → envia `IA_response` (já contém fallback amigável)

### Fluxo visual sugerido

```
[Lead envia mensagem]
        ↓
[Nó: Executar código — botmaker-integration.js]
        ↓
[Nó condicional: IA_status]
   ├── "success"   → [Enviar IA_response ao lead]
   ├── "escalated" → [Transferir para fila humana]
   └── "error"     → [Enviar IA_response ao lead (fallback)]
```

### Respostas multi-part (opcional)

Se quiser enviar as partes separadamente para simular digitação natural:

```
[Nó condicional: IA_has_multipart]
   ├── true  → [Loop: enviar cada item de IA_responses com delay de IA_delay_seconds]
   └── false → [Enviar IA_response normalmente]
```

---

## Testando o endpoint

```bash
curl -X POST https://web-production-63ae4.up.railway.app/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -d '{
    "user_id": "5531999990000",
    "message": "Olá, quero saber mais sobre os cursos",
    "channel": "botmaker"
  }'
```

---

## Comportamentos importantes

### Debounce
Se o lead enviar 3 mensagens em sequência rápida, o Closi AI acumula tudo em uma janela de 10 segundos e responde uma vez só. Isso evita respostas fragmentadas e economiza tokens.

### Memória
O `user_id` (telefone) é a chave de memória. O agente lembra todo o histórico de conversa automaticamente. Não é necessário enviar contexto anterior — o Closi AI gerencia isso internamente.

### Escalação
Quando a IA detecta que o lead precisa de atendimento humano (pedido explícito, insatisfação, questões contratuais, etc.), ela escala automaticamente. A sessão é marcada como `escalated` e a IA para de responder. O supervisor recebe notificação via WhatsApp com brief completo do lead.

### Comandos especiais (para operadores)
- `#transferindo-para-atendimento-dedicado` → Escala manualmente (IA para)
- `#retorno-para-atendimento-agente` → Devolve controle para a IA

Estes comandos são enviados como mensagem normal pelo payload. Úteis para o time de suporte controlar o fluxo via Botmaker.

---

## Checklist de configuração

- [ ] Token `API_SECRET_TOKEN` obtido da equipe Closi AI
- [ ] Token configurado no código JS (ou variável de ambiente da Botmaker)
- [ ] URL do endpoint confirmada (Railway pode mudar em redeploys)
- [ ] Nó "Executar código" criado com `botmaker-integration.js` v3
- [ ] `user_message` disponível antes do nó de integração
- [ ] Nó condicional por `IA_status` configurado
- [ ] Teste com curl ou Postman validado
- [ ] Timeout da Botmaker configurado para >= 30s

---

## Limitações e pontos de atenção

1. **Latência**: Espere 13-17s por resposta. É o custo do debounce (10s) + IA. Se a Botmaker tem timeout menor que 30s para nós de código, isso precisa ser ajustado.

2. **Rate limit**: 20 mensagens por minuto por lead. Se o lead mandar mais que isso, recebe HTTP 429.

3. **Tamanho máximo da mensagem**: 2.000 caracteres (truncado automaticamente por segurança).

4. **Transfer direto via Botmaker API**: Ainda não implementado no backend. A escalação atual notifica o supervisor por WhatsApp. Transfer automático para fila da Botmaker é item de backlog (CLO-012).

5. **Respostas multi-part**: O array `responses` pode ter até 3 itens. O delay recomendado entre envios vem no campo `delay_seconds` (atualmente ~3s).
