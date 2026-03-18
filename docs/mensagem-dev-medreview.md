# Mensagem para o Dev MedReview — Integração Botmaker ↔ Closi AI

---

Fala! Segue atualização dos arquivos da integração Botmaker ↔ Closi AI. Desde a última versão que mandei, o backend evoluiu bastante, então atualizei tudo pra refletir o estado atual.

---

## Arquivos que estou enviando

### 1. `botmaker-integration.js` (v3)
**O que é:** Código Node.js pronto pra colar no nó "Executar código" da Botmaker.

**O que faz:** Recebe a mensagem do lead, manda pro endpoint do Closi AI via HTTP POST com autenticação Bearer Token, e salva a resposta da IA nas variáveis da Botmaker.

**O que mudou da v2 pra v3:**
- Agora trata sessão escalada (quando a IA transfere pra atendimento humano, o lead recebe uma mensagem amigável em vez de mensagem vazia)
- Suporte a respostas em múltiplas partes (a IA pode responder em até 3 mensagens curtas pra simular digitação natural)
- Novas variáveis de saída: `IA_responses` (array), `IA_has_multipart` (boolean), `IA_delay_seconds` (number)
- Log estruturado com prefixo `[Closi AI]`

**O que o dev precisa fazer:** Trocar `SEU_API_SECRET_TOKEN_AQUI` pelo token que vou fornecer separadamente.

---

### 2. `botmaker-integration-guide.md` (v3)
**O que é:** Guia completo de integração com contrato de API, exemplos de request/response, fluxo visual sugerido na Botmaker, e checklist de configuração.

**O que tem dentro:**
- Endpoint exato com URL de produção
- Payload de entrada (quais campos mandar, quais são obrigatórios)
- Todos os formatos de resposta possíveis (sucesso, erro, sessão escalada)
- Códigos HTTP de erro (401, 400, 429) e o que cada um significa
- Mapeamento de variáveis Botmaker → payload → variáveis de saída
- Fluxo visual sugerido com nós condicionais por status
- Comandos especiais de escalação/desescalação
- Curl de teste pronto pra copiar e rodar
- Checklist de configuração passo a passo
- Limitações e pontos de atenção (latência, rate limit, tamanho máximo)

---

## Sobre o que foi pedido anteriormente

**Endpoint backend:** Já existe e está em produção. É o `POST /chat` — não precisa criar nada novo. Aceita JSON com `user_id`, `message` e `channel`, valida Bearer Token, processa com a IA e devolve a resposta.

**Código Node.js pra Botmaker:** Atualizado na v3 (arquivo acima).

**Exemplos de request/response:** Estão no guia, com 3 cenários: sucesso, escalação e erro.

**Instruções de configuração:** Checklist completo no final do guia.

**Tratamento de erros:** Implementado no JS — timeout (30s), erro de rede, resposta inválida, token inválido, rate limit. Tudo cai em fallback amigável pro lead.

---

## Pontos de atenção

1. **Timeout:** Configure o timeout do nó de código da Botmaker pra no mínimo 30 segundos. O Closi AI tem debounce de 10s + processamento da IA (~5s).

2. **Token:** Vou enviar o `API_SECRET_TOKEN` por canal separado (não está nos arquivos por segurança).

3. **Transfer direto pra fila humana via API Botmaker:** Ainda não implementado do nosso lado. Hoje a escalação notifica o supervisor por WhatsApp. Se quiserem que a gente faça transfer automático pra fila da Botmaker, preciso da documentação da API de vocês pra isso.

4. **Teste:** O curl no guia funciona direto — é só trocar o token. Recomendo testar antes de montar o fluxo na Botmaker.

---

Qualquer dúvida, só chamar.
