# Integração Botmaker ↔ Closi AI

## Endpoint

```
POST https://web-production-63ae4.up.railway.app/chat
```

## Headers obrigatórios

```
Content-Type:  application/json
Authorization: Bearer SEU_API_SECRET_TOKEN
```

## Payload enviado pela Botmaker

```json
{
  "user_id":  "5531999990000",
  "message":  "Olá, quero saber sobre o Extensive",
  "channel":  "botmaker"
}
```

| Campo        | Tipo   | Obrigatório | Descrição |
|--------------|--------|-------------|-----------|
| `user_id`    | string | ✅ sim      | Telefone do lead (com DDI). Identificador primário — usado como chave de histórico no Supabase e chave de debounce. Na Botmaker, use `contact?.whatsApp` ou `contact?.phone`. |
| `message`    | string | ✅ sim      | Texto da mensagem digitada pelo lead (`user_message` na Botmaker). |
| `channel`    | string | não         | Identificador do canal. Use `"botmaker"`. |
| `session_id` | string | não         | Identificador de sessão (opcional). Se ausente, `user_id` é usado como chave de debounce. Útil quando múltiplas sessões podem existir para o mesmo lead. |

> **Nota:** O endpoint aceita `user_id` sozinho (sem `session_id`). Quando `session_id` não é
> enviado, `user_id` é usado automaticamente como chave de sessão para debounce e histórico.

## Resposta da IA

```json
{
  "response":   "Olá! Fico feliz em falar com você...",
  "user_id":    "5531999990000",
  "session_id": "5531999990000",
  "status":     "success"
}
```

O valor de `response` é o texto que o código armazena em `IA_response` e que será enviado ao lead pelo nó seguinte.

## Respostas de erro

**Erro interno (Claude falhou, Supabase off, etc.) — HTTP 200:**

```json
{
  "response":   "Estou com uma instabilidade agora, em breve um consultor vai te atender.",
  "user_id":    "5531999990000",
  "session_id": "5531999990000",
  "status":     "error"
}
```

A IA retorna HTTP 200 mesmo em falha interna para não travar o fluxo da Botmaker.

**Erros HTTP que o código Node.js deve tratar:**

| HTTP | Causa | Ação |
|------|-------|------|
| 401  | Token inválido ou ausente | Verifique `CLOSI_AI_TOKEN` |
| 400  | `user_id` ou `message` vazio | Verifique variáveis do fluxo |
| 429  | Rate limit excedido | Aguarde e reenvie |

## Timeout recomendado

```
30.000ms (30 segundos)
```

A IA tem debounce de 10 segundos + tempo de resposta do Claude (~3-5s).
Tempo total esperado por resposta: **13-17 segundos**.

## Como configurar na Botmaker

1. Crie um nó **"Executar código"** do tipo Node.js no fluxo
2. Cole o conteúdo de `botmaker-integration.js` (v2)
3. Substitua `SEU_API_SECRET_TOKEN_AQUI` pelo token configurado no Railway (`API_SECRET_TOKEN`)
4. Garanta que `user_message` está disponível no contexto antes deste nó
5. Use `IA_response` nos nós seguintes para enviar a resposta ao lead
6. (Opcional) Use `IA_status` para criar um nó condicional de fallback

## Variáveis disponíveis no nó

**Entrada (automática da Botmaker):**
```javascript
contact?.whatsApp   // número WhatsApp do lead (prioridade)
contact?.phone      // telefone genérico (fallback)
user_message        // mensagem digitada pelo lead
```

**Saída (disponível nos nós seguintes):**
```javascript
IA_response   // texto da resposta da IA (string)
IA_status     // "success" ou "error" (string)
```

O `user_id` (telefone) mantém o histórico completo da conversa no Supabase,
garantindo que o agente lembre o contexto entre mensagens.

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
