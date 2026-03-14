# Integração Botmaker ↔ Criatons

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
  "channel":  "botmaker",
  "metadata": {}
}
```

| Campo        | Tipo   | Obrigatório | Descrição |
|--------------|--------|-------------|-----------|
| `user_id`    | string | ✅ sim      | Telefone do lead (com DDI). Identificador primário — usado como chave de histórico no Supabase e chave de debounce. Na Botmaker, use `contact?.whatsApp` ou `contact?.phone`. |
| `message`    | string | ✅ sim      | Texto da mensagem digitada pelo lead (`user_message` na Botmaker). |
| `channel`    | string | não         | Identificador do canal. Use `"botmaker"`. |
| `session_id` | string | não         | Identificador de sessão (opcional). Se ausente, `user_id` é usado como chave de debounce. Útil quando múltiplas sessões podem existir para o mesmo lead. |
| `metadata`   | objeto | não         | Dados extras opcionais. |

> **Nota:** O endpoint aceita `user_id` sozinho (sem `session_id`). Quando `session_id` não é
> enviado, `user_id` é usado automaticamente como chave de sessão para debounce e histórico.

## Resposta da IA

```json
{
  "response": "Olá! Fico feliz em falar com você...",
  "user_id":  "5531999990000",
  "status":   "success"
}
```

O valor de `response` é o texto que deve ser armazenado em `IA_response` e enviado ao lead.

## Resposta em caso de erro

A IA **sempre retorna HTTP 200** — mesmo em caso de falha interna.
Isso garante que o fluxo da Botmaker nunca trave por erro de status HTTP.

```json
{
  "response": "Estou com uma instabilidade agora, em breve um consultor vai te atender.",
  "user_id":  "5531999990000",
  "status":   "error"
}
```

## Timeout recomendado no código Node.js

```
30.000ms (30 segundos)
```

A IA tem um debounce de 1 segundo + tempo de resposta do Claude (~3-5s).
Tempo total esperado por resposta: **4-7 segundos**.

## Como configurar na Botmaker

1. Crie um nó **"Executar código"** do tipo Node.js no fluxo
2. Cole o conteúdo de `botmaker-integration.js`
3. Substitua `SEU_API_SECRET_TOKEN_AQUI` pelo token configurado no Railway
4. Garanta que `user_message` está disponível no contexto antes deste nó
5. Use `IA_response` nos nós seguintes para enviar a resposta ao lead

## Variável user_id na Botmaker

O `user_id` deve ser o telefone do contato. Na Botmaker, acesse via:
```javascript
contact?.whatsApp   // número WhatsApp do lead
// ou
contact?.phone      // telefone genérico
```

O mesmo `user_id` mantém o histórico completo da conversa no Supabase,
garantindo que o agente lembre o contexto entre mensagens.

## Testando o endpoint antes do deploy

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
