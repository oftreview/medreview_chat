/**
 * CRIATONS — Integração Botmaker ↔ IA
 * =====================================
 * Cole este código no nó "Executar código" (Node.js) da Botmaker.
 *
 * VARIÁVEIS DE ENTRADA (configurar no nó antes deste):
 *   user_message  — mensagem digitada pelo lead (string)
 *   user_id       — identificador único do contato (use o telefone: {{contact.whatsApp}})
 *
 * VARIÁVEL DE SAÍDA (disponível nos nós seguintes):
 *   IA_response   — resposta gerada pelo agente Criatons (string)
 *
 * CONFIGURAÇÃO:
 *   Substitua CRIATONS_URL e CRIATONS_TOKEN pelos valores reais
 *   (ou configure como variáveis de ambiente na Botmaker).
 */

// ── Configuração ──────────────────────────────────────────────────────────────

const CRIATONS_URL   = "https://web-production-63ae4.up.railway.app/chat";
const CRIATONS_TOKEN = process.env.CRIATONS_TOKEN || "SEU_API_SECRET_TOKEN_AQUI";
const TIMEOUT_MS     = 30000; // 30 segundos — suficiente para debounce + Claude

// ── Envio para a IA ───────────────────────────────────────────────────────────

async function askCriatons(userId, message) {
  const https = require("https");
  const url   = new URL(CRIATONS_URL);

  const body = JSON.stringify({
    user_id:  String(userId),
    message:  String(message),
    channel:  "botmaker",
    metadata: {}
  });

  return new Promise((resolve, reject) => {
    const options = {
      hostname: url.hostname,
      path:     url.pathname,
      method:   "POST",
      headers: {
        "Content-Type":  "application/json",
        "Authorization": `Bearer ${CRIATONS_TOKEN}`,
        "Content-Length": Buffer.byteLength(body)
      },
      timeout: TIMEOUT_MS
    };

    const req = https.request(options, (res) => {
      let data = "";
      res.on("data", chunk => { data += chunk; });
      res.on("end", () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.status === "error" || !parsed.response) {
            reject(new Error(parsed.response || "Resposta inválida da IA"));
          } else {
            resolve(parsed.response);
          }
        } catch (e) {
          reject(new Error("Falha ao parsear resposta da IA: " + data));
        }
      });
    });

    req.on("timeout", () => {
      req.destroy();
      reject(new Error("Timeout: IA demorou mais de " + TIMEOUT_MS + "ms"));
    });

    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

// ── Execução principal ────────────────────────────────────────────────────────

// A Botmaker disponibiliza as variáveis do contexto diretamente no escopo.
// Ajuste os nomes abaixo se a sua configuração usar nomes diferentes.
const mensagem = user_message;                    // variável setada pela Botmaker
const contato  = contact?.whatsApp || user_id;    // telefone do lead como user_id

try {
  IA_response = await askCriatons(contato, mensagem);
} catch (err) {
  // Em caso de falha: passa uma mensagem de fallback para o fluxo continuar
  console.error("[Criatons] Erro:", err.message);
  IA_response = "Estou com uma instabilidade agora, em breve um consultor vai te atender.";
}
