"""
Testes de validação da Fase 1 — Wild Memory Setup.

Verifica que:
1. Todas as dependências estão instaladas
2. Config YAML carrega corretamente
3. NER MedReview reconhece entidades do domínio
4. Imprint YAML é válido

Rodar com: python -m pytest tests/test_wild_memory_setup.py -v
"""

import os
import sys

# Adiciona raiz do projeto ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ══════════════════════════════════════════════════════════════════════════════
# 1. Dependências
# ══════════════════════════════════════════════════════════════════════════════

def test_pydantic_installed():
    """Pydantic v2+ deve estar disponível."""
    import pydantic
    assert int(pydantic.__version__.split(".")[0]) >= 2


def test_pyyaml_installed():
    """PyYAML deve estar disponível."""
    import yaml  # noqa: F401


def test_openai_installed():
    """OpenAI SDK deve estar disponível (para embeddings)."""
    import openai  # noqa: F401


def test_supabase_installed():
    """Supabase SDK deve estar disponível (já existia)."""
    import supabase  # noqa: F401


def test_anthropic_installed():
    """Anthropic SDK deve estar disponível (já existia)."""
    import anthropic  # noqa: F401


# ══════════════════════════════════════════════════════════════════════════════
# 2. Configuração
# ══════════════════════════════════════════════════════════════════════════════

def test_config_yaml_exists():
    """wild_memory.yaml deve existir na raiz do projeto."""
    assert os.path.isfile("wild_memory.yaml"), "wild_memory.yaml não encontrado"


def test_config_yaml_loads():
    """Config YAML deve carregar sem erros."""
    from wild_memory.config import WildMemoryConfig
    config = WildMemoryConfig.from_yaml("wild_memory.yaml")
    assert config is not None
    assert config.models.premium.model is not None
    assert config.models.economy.model is not None
    assert config.embedding.model == "text-embedding-3-small"


def test_config_defaults_are_sane():
    """Valores default do config devem ser razoáveis."""
    from wild_memory.config import WildMemoryConfig
    config = WildMemoryConfig.from_yaml("wild_memory.yaml")

    assert config.decay.daily_rate == 0.02
    assert config.cache.similarity_threshold >= 0.9
    assert config.gate.min_chars >= 20
    assert config.checkpoint.interval_messages >= 3
    assert config.max_context_tokens >= 100_000


# ══════════════════════════════════════════════════════════════════════════════
# 3. NER Pipeline MedReview
# ══════════════════════════════════════════════════════════════════════════════

def test_ner_medreview_domain_loaded():
    """Domínio MedReview deve ter entidades configuradas."""
    from wild_memory.medreview_domain import MEDREVIEW_DOMAIN_ENTITIES
    assert "EXAM" in MEDREVIEW_DOMAIN_ENTITIES
    assert "PRODUCT" in MEDREVIEW_DOMAIN_ENTITIES
    assert "SPECIALTY" in MEDREVIEW_DOMAIN_ENTITIES
    assert "COMPETITOR" in MEDREVIEW_DOMAIN_ENTITIES
    assert len(MEDREVIEW_DOMAIN_ENTITIES["EXAM"]) >= 10
    assert len(MEDREVIEW_DOMAIN_ENTITIES["SPECIALTY"]) >= 20


def test_ner_extracts_exams():
    """NER deve reconhecer provas de residência."""
    from wild_memory.medreview_domain import create_medreview_ner
    ner = create_medreview_ner()
    entities = ner.extract("Estou me preparando para a prova da USP e UNIFESP")
    labels = [e.label for e in entities]
    texts = [e.text.lower() for e in entities]
    assert "EXAM" in labels
    assert any("usp" in t for t in texts)


def test_ner_extracts_products():
    """NER deve reconhecer produtos MedReview."""
    from wild_memory.medreview_domain import create_medreview_ner
    ner = create_medreview_ner()
    entities = ner.extract("Quero saber mais sobre o Extensive 2026 e o LUX")
    labels = [e.label for e in entities]
    assert "PRODUCT" in labels


def test_ner_extracts_specialties():
    """NER deve reconhecer especialidades médicas."""
    from wild_memory.medreview_domain import create_medreview_ner
    ner = create_medreview_ner()
    entities = ner.extract("Sou médico e quero fazer cardiologia")
    labels = [e.label for e in entities]
    assert "SPECIALTY" in labels


def test_ner_extracts_competitors():
    """NER deve reconhecer concorrentes."""
    from wild_memory.medreview_domain import create_medreview_ner
    ner = create_medreview_ner()
    entities = ner.extract("Hoje uso a Sanar mas estou considerando trocar")
    labels = [e.label for e in entities]
    assert "COMPETITOR" in labels


def test_ner_entity_ids_format():
    """Entity IDs devem ter formato slug: tipo_nome."""
    from wild_memory.medreview_domain import create_medreview_ner
    ner = create_medreview_ner()
    entities = ner.extract("Prova da USP de anestesiologia")
    ids = ner.to_entity_ids(entities)
    assert len(ids) > 0
    for eid in ids:
        assert "_" in eid, f"ID '{eid}' deveria ter formato tipo_nome"


def test_ner_handles_empty_input():
    """NER não deve falhar com input vazio."""
    from wild_memory.medreview_domain import create_medreview_ner
    ner = create_medreview_ner()
    entities = ner.extract("")
    assert entities == []


def test_ner_deduplicates():
    """NER não deve retornar entidades duplicadas."""
    from wild_memory.medreview_domain import create_medreview_ner
    ner = create_medreview_ner()
    entities = ner.extract("USP USP USP, prova da USP")
    usp_entities = [e for e in entities if "usp" in e.text.lower()]
    assert len(usp_entities) == 1, "USP deveria aparecer apenas uma vez"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Imprint
# ══════════════════════════════════════════════════════════════════════════════

def test_imprint_yaml_exists():
    """Arquivo de identidade do agente deve existir."""
    assert os.path.isfile("memory/imprint.yaml"), "memory/imprint.yaml não encontrado"


def test_imprint_yaml_valid():
    """Imprint YAML deve ter campos obrigatórios."""
    import yaml
    with open("memory/imprint.yaml") as f:
        data = yaml.safe_load(f)
    assert "agent_id" in data
    assert data["agent_id"] == "closi-sales"
    assert "role" in data
    assert "values" in data
    assert "constraints" in data
    assert len(data["values"]) >= 3
    assert len(data["constraints"]) >= 3


def test_procedure_file_exists():
    """Arquivo de procedure de qualificação deve existir."""
    assert os.path.isfile("memory/procedures/lead_qualification.md")


# ══════════════════════════════════════════════════════════════════════════════
# 5. Models
# ══════════════════════════════════════════════════════════════════════════════

def test_models_importable():
    """Todos os modelos de dados devem ser importáveis."""
    from wild_memory.models import (
        Observation, ObservationType, ObservationStatus,
        EmotionalValence, ConflictAction,
        EntityNode, EntityEdge,
        Reflection, FeedbackSignal,
        AgentImprint, CitationTrail,
        NEREntity,
    )
    # Verifica que são classes/enums válidos
    assert ObservationType.FACT.value == "fact"
    assert ObservationStatus.ACTIVE.value == "active"
    assert ConflictAction.ADD.value == "ADD"


def test_observation_creation():
    """Deve ser possível criar Observation com campos mínimos."""
    from wild_memory.models import Observation, ObservationType
    obs = Observation(
        agent_id="closi-sales",
        user_id="test_user",
        content="Lead é cardiologista, prova alvo USP 2026",
        obs_type=ObservationType.FACT,
        importance=8,
    )
    assert obs.decay_score == 1.0
    assert obs.status.value == "active"
    assert obs.emotional_valence.value == "neutral"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Migration SQL
# ══════════════════════════════════════════════════════════════════════════════

def test_migration_file_exists():
    """SQL de migration do Wild Memory deve existir."""
    assert os.path.isfile("migrations/002_wild_memory_schema.sql")


def test_migration_has_required_tables():
    """Migration deve criar todas as tabelas necessárias."""
    with open("migrations/002_wild_memory_schema.sql") as f:
        sql = f.read()

    required_tables = [
        "observations", "entity_nodes", "entity_edges",
        "reflections", "feedback_signals", "procedures",
        "citation_trails", "session_logs", "semantic_cache",
        "agent_checkpoints", "agent_imprints", "broadcast_events",
    ]
    for table in required_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql, \
            f"Tabela '{table}' não encontrada no migration"


def test_migration_has_pgvector():
    """Migration deve habilitar pgvector."""
    with open("migrations/002_wild_memory_schema.sql") as f:
        sql = f.read()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql


def test_migration_has_rpc_functions():
    """Migration deve criar funções RPC essenciais."""
    with open("migrations/002_wild_memory_schema.sql") as f:
        sql = f.read()

    required_rpcs = [
        "reinforce_observation",
        "apply_daily_decay",
        "mark_stale_observations",
        "retrieve_observations",
        "search_semantic_cache",
        "find_similar_observations",
    ]
    for rpc in required_rpcs:
        assert rpc in sql, f"RPC '{rpc}' não encontrada no migration"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Distillation Gate
# ══════════════════════════════════════════════════════════════════════════════

def test_gate_rejects_trivial():
    """Gate deve rejeitar mensagens triviais."""
    from wild_memory.processes.distillation_gate import DistillationGate
    from wild_memory.config import GateConfig
    from wild_memory.medreview_domain import create_medreview_ner

    gate = DistillationGate(create_medreview_ner(), GateConfig())
    assert gate.should_distill("ok", "Tudo bem!") is False
    assert gate.should_distill("sim", "Ótimo!") is False
    assert gate.should_distill("valeu", "De nada!") is False


def test_gate_accepts_meaningful():
    """Gate deve aceitar mensagens com conteúdo relevante."""
    from wild_memory.processes.distillation_gate import DistillationGate
    from wild_memory.config import GateConfig
    from wild_memory.medreview_domain import create_medreview_ner

    gate = DistillationGate(create_medreview_ner(), GateConfig())
    assert gate.should_distill(
        "Quero saber sobre o Extensive 2026, faço prova da USP em novembro",
        "Ótima escolha! A USP é uma das mais concorridas."
    ) is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
