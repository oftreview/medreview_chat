/**
 * CRIATONS — Integração Botmaker ↔ IA (v2)
 * ==========================================
 * Cole este código no nó "Executar código" (Node.js) da Botmaker.
 *
 * VARIÁVEIS DE ENTRADA (disponíveis automaticamente no contexto Botmaker):
 *   user_message  — mensagem digitada pelo lead (string, setada pelo nó anterior)
 *   contact       — objeto do contato Botmaker (contém whatsApp, phone, name, etc.)
 *
 * VARIÁVEL DE SAÍDA (disponível nos nós seguintes):
 *   IA_response   — resposta gerada pelo agente Criatons (string)
 *   IA_status     — status da resposta: "success" | "error" (string)
 *
 * CONFIGURAÇÃO:
 *   1. No Railway, defina API_SECRET_TOKEN nas variáveis de ambiente
 *   2. Substitua CRIATONS_TOKEN abaixo pelo mesmo token
 *      (ou configure como variável de ambiente na Botmaker se disponível)
 *   3. Ajuste CRIATONS_URL se o domínio do Railway mudar
 *
 * COMO FUNCIONA:
 *   Botmaker recebe msg do WhatsApp → este nó envia para o Criatons →
 *   Criatons processa com Claude (com debounce de 10s) → retorna resposta →
 *   IA_response fica disponível para o próximo nó enviar ao lead.
 */

// ── Configuração ──────────────────────────────────────────────────────────────

const CRIATONS_URL   = "https://web-production-63ae4.up.railway.app/chat";
const CRIATONS_TOKEN = process.env.CRIATONS_TOKEN || "SEU_API_SECRET_TOKEN_AQUI";

// Timeout: debounce (10s) + Claude (~5s) + margem (10s) = 25s
// Em caso de retry interno do Criatons, pode chegar a 30s
const TIMEOUT_MS = 30000;

// Mensagem exibida ao lead quando a IA falha
const FALLBACK_MSG = "Estou com uma instabilidade agora, em breve um consultor vai te atender.";

// ── Função principal: envia mensagem para o Criatons ─────────────────────────

async function askCriatons(userId, message) {
  const https = require("https");
  const url   = new URL(CRIATONS_URL);

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
        "Authorization": `Bearer ${CRIATONS_TOKEN}`,
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
          reject(new Error("[AUTH] Token inválido — verifique CRIATONS_TOKEN"));
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
          if (parsed.status === "error" || !parsed.response) {
            // IA retornou fallback interno (Claude falhou, Supabase off, etc.)
            // Ainda usa a resposta — é o fallback amigável do Criatons
            resolve(parsed.response || FALLBACK_MSG);
          } else {
            resolve(parsed.response);
          }
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

// Resolução do identificador do contato (telefone).
// A Botmaker disponibiliza o objeto `contact` no escopo do nó.
// Prioridade: whatsApp > phone > user_id (variável manual)
const contato = contact?.whatsApp || contact?.phone || user_id || "";
const mensagem = user_message || "";

if (!contato) {
  console.error("[Criatons] Erro: não foi possível identificar o contato (sem whatsApp/phone/user_id)");
  IA_response = FALLBACK_MSG;
  IA_status = "error";
} else if (!mensagem) {
  console.error("[Criatons] Erro: mensagem vazia (user_message não definido)");
  IA_response = FALLBACK_MSG;
  IA_status = "error";
} else {
  try {
    IA_response = await askCriatons(contato, mensagem);
    IA_status = "success";
    console.log("[Criatons] Resposta recebida para contato:", contato.substring(0, 6) + "***");
  } catch (err) {
    console.error("[Criatons] Erro:", err.message);
    IA_response = FALLBACK_MSG;
    IA_status = "error";
  }
}
