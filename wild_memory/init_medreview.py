"""
Wild Memory — Inicializador para Closi-AI (MedReview).

Este módulo encapsula a criação do WildMemory com configurações
específicas do MedReview, incluindo:
- Carregamento de credenciais das env vars existentes do Closi-AI
- NER configurado para domínio médico
- Fallback seguro se dependências não estiverem instaladas

USO:
    from wild_memory.init_medreview import get_wild_memory
    wild = get_wild_memory()  # retorna None se não disponível
"""

from __future__ import annotations

import os
from typing import Optional

# Singleton global
_wild_memory_instance: Optional[object] = None
_init_attempted: bool = False
_init_error: Optional[str] = None


def get_wild_memory():
    """
    Retorna a instância singleton do WildMemory.
    Se não estiver disponível (dependências faltando, config incorreta),
    retorna None e loga o motivo. Nunca lança exceção.
    """
    global _wild_memory_instance, _init_attempted, _init_error

    if _init_attempted:
        return _wild_memory_instance

    _init_attempted = True

    try:
        # Verifica se as dependências estão disponíveis
        _check_dependencies()

        # Mapeia env vars do Closi-AI para as do Wild Memory
        _setup_env_vars()

        # Importa e configura
        from wild_memory.orchestrator import WildMemory
        from wild_memory.config import WildMemoryConfig

        # Carrega config do YAML
        config = WildMemoryConfig.from_yaml("wild_memory.yaml")

        # Injeta credenciais do Closi-AI se não vieram pelo YAML
        if not config.supabase.url:
            config.supabase.url = os.getenv("SUPABASE_URL", "")
        if not config.supabase.key:
            config.supabase.key = os.getenv("SUPABASE_KEY", "")

        if not config.supabase.url or not config.supabase.key:
            _init_error = "SUPABASE_URL ou SUPABASE_KEY não configurados"
            print(f"[WILD MEMORY] Desabilitado: {_init_error}", flush=True)
            return None

        # Cria instância com NER customizado para MedReview
        _wild_memory_instance = WildMemory(config)

        # Substitui NER padrão pelo customizado do MedReview
        from wild_memory.medreview_domain import create_medreview_ner
        medreview_ner = create_medreview_ner()
        _wild_memory_instance.ner = medreview_ner
        _wild_memory_instance.distiller.ner = medreview_ner
        _wild_memory_instance.distill_gate.ner = medreview_ner
        _wild_memory_instance.goal_cache.ner = medreview_ner

        print("[WILD MEMORY] Inicializado com sucesso (domínio MedReview)", flush=True)
        return _wild_memory_instance

    except ImportError as e:
        _init_error = f"Dependência não instalada: {e}"
        print(f"[WILD MEMORY] Desabilitado: {_init_error}", flush=True)
        return None
    except Exception as e:
        _init_error = str(e)
        print(f"[WILD MEMORY] Erro na inicialização: {_init_error}", flush=True)
        return None


def get_status() -> dict:
    """Retorna status da inicialização do Wild Memory."""
    return {
        "available": _wild_memory_instance is not None,
        "attempted": _init_attempted,
        "error": _init_error,
    }


def _check_dependencies():
    """Verifica se as dependências do Wild Memory estão instaladas."""
    missing = []
    try:
        import pydantic  # noqa: F401
    except ImportError:
        missing.append("pydantic")
    try:
        import yaml  # noqa: F401
    except ImportError:
        missing.append("pyyaml")
    try:
        import openai  # noqa: F401
    except ImportError:
        missing.append("openai")

    if missing:
        raise ImportError(f"Dependências faltando: {', '.join(missing)}")


def _setup_env_vars():
    """
    Mapeia env vars do Closi-AI para as do Wild Memory.
    O Wild Memory espera WILD_MEMORY_SUPABASE_URL, mas o Closi-AI usa SUPABASE_URL.
    """
    mappings = {
        "WILD_MEMORY_SUPABASE_URL": "SUPABASE_URL",
        "WILD_MEMORY_SUPABASE_KEY": "SUPABASE_KEY",
    }
    for wild_var, closi_var in mappings.items():
        if not os.getenv(wild_var):
            val = os.getenv(closi_var)
            if val:
                os.environ[wild_var] = val
