"""
Wild Memory — Configuration
Loads settings from wild_memory.yaml or environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class SupabaseConfig(BaseModel):
    url: str = Field(default="", description="Supabase project URL")
    key: str = Field(default="", description="Supabase service role key")


class ModelConfig(BaseModel):
    provider: str = Field(default="anthropic")
    model: str
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0


class ModelsConfig(BaseModel):
    premium: ModelConfig = Field(
        default_factory=lambda: ModelConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            cost_per_1m_input=3.0,
            cost_per_1m_output=15.0,
        )
    )
    economy: ModelConfig = Field(
        default_factory=lambda: ModelConfig(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            cost_per_1m_input=0.80,
            cost_per_1m_output=4.0,
        )
    )


class EmbeddingConfig(BaseModel):
    provider: str = Field(default="openai")
    model: str = Field(default="text-embedding-3-small")
    dimensions: int = Field(default=1536)


class DecayConfig(BaseModel):
    daily_rate: float = Field(default=0.02, description="Daily decay rate")
    stale_threshold: float = Field(default=0.3)
    archive_threshold: float = Field(default=0.1)
    protected_types: list[str] = Field(default_factory=lambda: ["decision", "correction"])
    protected_min_importance: int = Field(default=7)


class TTLDefaults(BaseModel):
    decision: int = 180
    preference: int = 90
    fact: int = 365
    goal: int = 30
    correction: int = 365
    feedback: int = 60
    insight: int = 180


class CacheConfig(BaseModel):
    enabled: bool = Field(default=True)
    similarity_threshold: float = Field(default=0.93)
    ttl_hours: int = Field(default=72)
    personal_keywords: list[str] = Field(
        default_factory=lambda: [
            "meu", "minha", "cancelar", "reembolso", "problema", "erro", "bug",
        ]
    )


class RetrievalWeights(BaseModel):
    semantic: float = Field(default=0.30)
    entity_match: float = Field(default=0.20)
    fts_keyword: float = Field(default=0.15)
    recency: float = Field(default=0.15)
    decay: float = Field(default=0.12)
    emotion: float = Field(default=0.08)


class GateConfig(BaseModel):
    min_chars: int = Field(default=40)
    trivial_patterns: list[str] = Field(
        default_factory=lambda: [
            r"^(ok|ta|sim|nao|não|entendi|beleza|blz|vlw)$",
            r"^(obrigad[oa]|valeu|tmj|show|top|massa)$",
            r"^(pode ser|bora|vamo[s]?|fecho[u]?)$",
            r"^\s*$",
        ]
    )
    signal_keywords: list[str] = Field(
        default_factory=lambda: [
            "decidi", "escolhi", "quero", "prefiro", "mudei",
            "cancelar", "preço", "quanto", "valor", "desconto",
        ]
    )


class BriefingCacheConfig(BaseModel):
    max_turns_without_rebuild: int = Field(default=4)


class GoalCacheConfig(BaseModel):
    max_turns: int = Field(default=4)
    change_signals: list[str] = Field(
        default_factory=lambda: [
            "na verdade", "mudando de", "outra coisa", "sobre outro",
            "aproveitando", "alias", "mudei de ideia",
        ]
    )


class CheckpointConfig(BaseModel):
    interval_messages: int = Field(default=5)


class SessionLogConfig(BaseModel):
    ttl_days: int = Field(default=14)


class ConflictConfig(BaseModel):
    similarity_threshold: float = Field(default=0.85)


class WildMemoryConfig(BaseModel):
    """Root configuration for Wild Memory."""

    # Infrastructure
    supabase: SupabaseConfig = Field(default_factory=SupabaseConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)

    # Agent identity
    imprint_path: str = Field(default="memory/imprint.yaml")
    procedures_dir: str = Field(default="memory/procedures")
    memory_dir: str = Field(default="memory")

    # Memory behavior
    decay: DecayConfig = Field(default_factory=DecayConfig)
    ttl_defaults: TTLDefaults = Field(default_factory=TTLDefaults)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    retrieval_weights: RetrievalWeights = Field(default_factory=RetrievalWeights)
    gate: GateConfig = Field(default_factory=GateConfig)
    briefing_cache: BriefingCacheConfig = Field(default_factory=BriefingCacheConfig)
    goal_cache: GoalCacheConfig = Field(default_factory=GoalCacheConfig)
    checkpoint: CheckpointConfig = Field(default_factory=CheckpointConfig)
    session_log: SessionLogConfig = Field(default_factory=SessionLogConfig)
    conflict: ConflictConfig = Field(default_factory=ConflictConfig)

    # Context window
    max_context_tokens: int = Field(default=150_000)
    compress_threshold: float = Field(default=0.7)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "WildMemoryConfig":
        """Load config from YAML file, with env var overrides."""
        p = Path(path)
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        # Environment variable overrides
        env_map = {
            "WILD_MEMORY_SUPABASE_URL": ("supabase", "url"),
            "WILD_MEMORY_SUPABASE_KEY": ("supabase", "key"),
            "ANTHROPIC_API_KEY": None,  # handled by SDK
            "OPENAI_API_KEY": None,  # handled by SDK
        }
        for env_var, path_tuple in env_map.items():
            val = os.getenv(env_var)
            if val and path_tuple:
                section, key = path_tuple
                data.setdefault(section, {})[key] = val

        return cls(**data)

    @classmethod
    def default(cls) -> "WildMemoryConfig":
        return cls()
