"""
tests/fixtures/mock_responses.py — Respostas mockadas de APIs externas.
"""

# ── Claude API Responses ─────────────────────────────────────────────────────

CLAUDE_NORMAL_RESPONSE = (
    "Oi! Que bom que voce tem interesse no R1 intensivo! "
    "Esse curso e ideal para quem quer se preparar de forma completa para a residencia. "
    "Posso te contar mais sobre os modulos e valores?"
)

CLAUDE_RESPONSE_WITH_META = (
    "Otimo! O R1 intensivo cobre todas as grandes areas da medicina. "
    "Posso te enviar mais detalhes sobre os modulos?\n\n"
    "[META] stage=qualificacao | especialidade=clinica_medica | ano_prova=2027 | motivo_escalacao=nenhum"
)

CLAUDE_RESPONSE_WITH_ESCALATION_TAG = (
    "[ESCALAR] Entendo sua situacao. Vou conectar voce com um consultor "
    "especializado que pode te ajudar melhor com essa questao especifica."
)

CLAUDE_RESPONSE_WITH_ESCALATION_FALLBACK = (
    "Vou conectar voce com um consultor humano para tratar dessa questao. "
    "Ele vai poder te ajudar com todos os detalhes."
)

CLAUDE_RESPONSE_LONG = (
    "O curso R1 Intensivo e o mais completo da MedReview. "
    "Ele cobre as seguintes areas:\n\n"
    "1. Clinica Medica - com foco em diagnostico diferencial\n"
    "2. Cirurgia Geral - tecnicas e casos clinicos\n"
    "3. Pediatria - do neonato ao adolescente\n"
    "4. Ginecologia e Obstetricia - ciclo completo\n\n"
    "Alem disso, voce tem acesso ao banco de questoes com mais de 15.000 "
    "questoes comentadas, simulados semanais e mentoria individualizada.\n\n"
    "O investimento para o plano anual e de R$ 4.990 em ate 12x no cartao. "
    "Quer que eu te envie o link de pagamento?"
)

CLAUDE_META_DESCONHECIDO = (
    "Entendi! Vou te ajudar a encontrar o melhor plano.\n\n"
    "[META] stage=descoberta | especialidade=desconhecido | motivo_escalacao=nenhum"
)

# ── Supabase Mock Results ────────────────────────────────────────────────────

SUPABASE_INSERT_SUCCESS = {"data": [{"id": 1}], "count": 1}

SUPABASE_SELECT_CONVERSATION = {
    "data": [
        {"role": "user", "content": "Oi, quero saber sobre o curso"},
        {"role": "assistant", "content": "Ola! Posso te ajudar com informacoes sobre nossos cursos."},
    ]
}

SUPABASE_SELECT_EMPTY = {"data": []}
