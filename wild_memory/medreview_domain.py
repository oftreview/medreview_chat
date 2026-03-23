"""
Wild Memory — Configuração de domínio MedReview.
Define entidades NER específicas do mercado de residência médica.
"""

# Entidades de domínio para o NER Pipeline
# Cada chave é um tipo de entidade, cada valor é uma lista de termos reconhecidos.
# O NER faz matching case-insensitive.

MEDREVIEW_DOMAIN_ENTITIES = {
    # ── Provas de Residência ──────────────────────────────────────────────
    "EXAM": [
        "enare", "usp", "unifesp", "sus", "sus-sp",
        "hcfmusp", "einstein", "santa casa", "unicamp",
        "unesp", "uerj", "ufmg", "ufpr", "ufsc", "ufrgs",
        "amrigs", "psu", "revalida",
    ],

    # ── Produtos MedReview ────────────────────────────────────────────────
    "PRODUCT": [
        "extensive", "extensive 2026", "extensive 2026/2027",
        "lux", "banco lux", "anest review", "anestreview",
        "medreview", "med review",
        "flashcard", "flashcards",
        "simulado", "simulados",
        "minicurso",
    ],

    # ── Especialidades Médicas ────────────────────────────────────────────
    "SPECIALTY": [
        "anestesiologia", "anestesio",
        "cardiologia", "cardio",
        "cirurgia geral", "cirurgia",
        "clínica médica", "clinica medica", "clínica",
        "dermatologia", "dermato",
        "endocrinologia", "endocrino",
        "gastroenterologia", "gastro",
        "ginecologia", "gineco", "go",
        "infectologia", "infecto",
        "nefrologia", "nefro",
        "neurologia", "neuro",
        "obstetrícia", "obstetricia",
        "oftalmologia", "oftalmo",
        "oncologia", "onco",
        "ortopedia", "orto",
        "otorrinolaringologia", "otorrino",
        "pediatria", "pedia",
        "pneumologia", "pneumo",
        "psiquiatria", "psiq",
        "radiologia", "radio",
        "reumatologia", "reumato",
        "saúde pública", "saude publica",
        "urologia", "uro",
    ],

    # ── Planos / Ofertas ──────────────────────────────────────────────────
    "PLAN": [
        "premium", "basic", "essencial",
        "parcelado", "à vista", "a vista",
        "12x", "6x", "desconto",
    ],

    # ── Concorrentes ──────────────────────────────────────────────────────
    "COMPETITOR": [
        "medcel", "sanar", "estratégia med", "estrategia med",
        "medway", "medcof", "aristo", "eu médico residente",
    ],

    # ── Termos de Funil de Vendas ─────────────────────────────────────────
    "FUNNEL_SIGNAL": [
        "quero comprar", "quero assinar", "como faço pra comprar",
        "link de pagamento", "pix", "cartão", "cartao",
        "vou pensar", "preciso pensar", "caro", "barato",
        "garantia", "reembolso", "cancelar",
    ],
}


def create_medreview_ner():
    """Cria NER Pipeline configurado para o domínio MedReview."""
    from wild_memory.processes.ner_pipeline import NERPipeline
    return NERPipeline.with_domain(MEDREVIEW_DOMAIN_ENTITIES)
