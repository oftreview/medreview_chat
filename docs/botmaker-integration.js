/**
 * CLOSI AI — Integração Botmaker ↔ IA (v3)
 * ==========================================
 * Cole este código no nó "Executar código" (Node.js) da Botmaker.
 *
 * VARIÁVEIS DE ENTRADA (disponíveis automaticamente no contexto Botmaker):
 *   user_message  — mensagem digitada pelo lead (string, setada pelo nó anterior)
 *   contact       — objeto do contato Botmaker (contém whatsApp, phone, name, etc.)
 *
 * VARIÁVEIS DE SAÍDA (disponíveis nos nós seguintes):
 *   IA_response       — resposta principal da IA (string)
 *   IA_responses      — array com todas as partes da resposta (array de strings)
 *   IA_status         — "success" | "error" | "escalated" (string)
 *   IA_has_multipart  — true se a resposta tem mais de 1 parte (boolean)
 *   IA_delay_seconds  — delay recomendado entre partes, em segundos (number)
 *
 * CONFIGURAÇÃO:
 *   1. No Railway do Closi AI, a variável API_SECRET_TOKEN já está configurada
 *   2. Substitua CLOSI_AI_TOKEN abaixo pelo mesmo token
 *      (ou configure como variável de ambiente na Botmaker se disponível)
 *   3. Ajuste CLOSI_AI_URL se o domínio do Railway mudar
 *
 * CHANGELOG v3 (2026-03):
 *   - Tratamento de sessão escalada (handoff para humano)
 *   - Suporte a respostas multi-part (responses[])
 *   - Variável IA_status agora inclui "escalated"
 *   - Novas variáveis de saída: IA_responses, IA_has_multipart, IA_delay_seconds
 *   - Log estruturado com prefixo [Closi AI]
 */

// ── Configuração ──────────────────────────────────────────────────────────────

const CLOSI_AI_URL   = "https://web-production-63ae4.up.railway.app/chat";
const CLOSI_AI_TOKEN = process.env.CLOSI_AI_TOKEN || "SEU_API_SECRET_TOKEN_AQUI";

// Timeout: debounce (10s) + Claude (~5s) + margem (15s) = 30s
const TIMEOUT_MS = 30000;

// Mensagem exibida ao lead quando a IA falha
const FALLBACK_MSG = "Estou com uma instabilidade agora, em breve um consultor vai te atender.";

// Mensagem exibida quando a sessão está em atendimento humano
const ESCALATED_MSG = "Você está sendo atendido por um de nossos consultores. Aguarde, por favor!";

// ── Função principal: envia mensagem para o Closi AI ─────────────────────────

async function askClosiAI(userId, message) {
  const https = require("https");
  const url   = new URL(CLOSI_AI_URL);

  const payload = {
    user_id:  String(userId),
    message:  String(message),
    channel:  "botmaker",
  };

  const body = JSON.stringify(payload);

  return new Promise((resolve, reject) => {
    const options = {
      hostname: url.hostname,
      path:     url.pathname,
      method:   "POST",
      headers: {
        "Content-Type":  "application/json",
        "Authorization": `Bearer ${CLOSI_AI_TOKEN}`,
        "Content-Length": Buffer.byteLength(body),
      },
      timeout: TIMEOUT_MS,
    };

    const req = https.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        // ── Tratar erros HTTP antes de parsear ────────────────────────
        if (res.statusCode === 401) {
          reject(new Error("[AUTH] Token inválido — verifique CLOSI_AI_TOKEN"));
          return;
        }
        if (res.statusCode === 429) {
          reject(new Error("[RATE_LIMIT] Muitas requisições — aguarde"));
          return;
        }
        if (res.statusCode >= 400) {
          reject(new Error(`[HTTP ${res.statusCode}] ${data.substring(0, 200)}`));
          return;
        }

        // ── Parsear resposta JSON ─────────────────────────────────────
        try {
          const parsed = JSON.parse(data);

          // Requisição duplicada (debounce): outra req já levou a resposta
          if (parsed.status === "debounced") {
            resolve({
              response:      "",
              responses:     [],
              status:        "debounced",
              delaySeconds:  0,
            });
            return;
          }

          // Sessão escalada: lead está em atendimento humano, IA pausada
          if (parsed.status === "escalated_session") {
            resolve({
              response:      ESCALATED_MSG,
              responses:     [ESCALATED_MSG],
              status:        "escalated",
              delaySeconds:  0,
            });
            return;
          }

          // Comandos de escalação/desescalação executados
          if (parsed.command === "escalate" || parsed.command === "deescalate") {
            resolve({
              response:      parsed.response || "",
              responses:     [parsed.response || ""],
              status:        parsed.status || "success",
              delaySeconds:  0,
            });
            return;
          }

          // Resposta normal (sucesso ou erro interno com fallback)
          const mainResponse = parsed.response || FALLBACK_MSG;
          const allResponses = parsed.responses || [mainResponse];
          const delaySeconds = parsed.delay_seconds || 0;

          resolve({
            response:      mainResponse,
            responses:     allResponses,
            status:        parsed.status === "error" ? "error" : "success",
            delaySeconds:  delaySeconds,
          });

        } catch (e) {
          reject(new Error("[PARSE] Resposta inválida da IA: " + data.substring(0, 200)));
        }
      });
    });

    req.on("timeout", () => {
      req.destroy();
      reject(new Error("[TIMEOUT] IA demorou mais de " + (TIMEOUT_MS / 1000) + "s"));
    });

    req.on("error", (err) => {
      reject(new Error("[NETWORK] " + err.message));
    });

    req.write(body);
    req.end();
  });
}

// ── Execução ──────────────────────────────────────────────────────────────────

// Resolução do identificador do contato.
// A Botmaker disponibiliza o objeto `contact` no escopo do nó.
// Prioridade: whatsApp > phone > platformContactId > contactId > customerId
// IMPORTANTE: `user_id` não é variável padrão da Botmaker — use campos do contact.
const contato = contact?.whatsApp
  || contact?.phone
  || contact?.platformContactId
  || contact?.contactId
  || (typeof platformContactId !== 'undefined' ? platformContactId : "")
  || (typeof customerId !== 'undefined' ? customerId : "")
  || (typeof user_id !== 'undefined' ? user_id : "")
  || "";
const mensagem = user_message || "";

// ── Debug: remover após confirmar que contato está sendo resolvido ────────
console.log("[Closi AI DEBUG] Resolução de contato:", JSON.stringify({
  whatsApp: contact?.whatsApp || null,
  phone: contact?.phone || null,
  platformContactId: contact?.platformContactId || null,
  contactId: contact?.contactId || null,
  contato_resolvido: contato ? contato.substring(0, 10) + "..." : "VAZIO",
}));

if (!contato) {
  console.error("[Closi AI] Erro: não foi possível identificar o contato (sem whatsApp/phone/user_id)");
  IA_response      = FALLBACK_MSG;
  IA_responses     = [FALLBACK_MSG];
  IA_status        = "error";
  IA_has_multipart = false;
  IA_delay_seconds = 0;
} else if (!mensagem) {
  console.error("[Closi AI] Erro: mensagem vazia (user_message não definido)");
  IA_response      = FALLBACK_MSG;
  IA_responses     = [FALLBACK_MSG];
  IA_status        = "error";
  IA_has_multipart = false;
  IA_delay_seconds = 0;
} else {
  try {
    const result = await askClosiAI(contato, mensagem);

    IA_response      = result.response;
    IA_responses     = result.responses;
    IA_status        = result.status;
    IA_has_multipart = result.responses.length > 1;
    IA_delay_seconds = result.delaySeconds;

    // Requisição debounced: não enviar nada ao lead
    if (result.status === "debounced") {
      console.log("[Closi AI] DEBOUNCED | contato:", contato.substring(0, 6) + "*** | ignorando resposta duplicada");
    } else {
      console.log(
        "[Closi AI] OK |",
        "contato:", contato.substring(0, 6) + "***",
        "| status:", result.status,
        "| partes:", result.responses.length,
        "| delay:", result.delaySeconds + "s"
      );
    }
  } catch (err) {
    console.error("[Closi AI] Erro:", err.message);
    IA_response      = FALLBACK_MSG;
    IA_responses     = [FALLBACK_MSG];
    IA_status        = "error";
    IA_has_multipart = false;
    IA_delay_seconds = 0;
  }
}
