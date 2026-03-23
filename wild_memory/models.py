"""
Wild Memory — Data Models
Pydantic schemas for all memory objects.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ObservationType(str, Enum):
    DECISION = "decision"
    PREFERENCE = "preference"
    FACT = "fact"
    INSIGHT = "insight"
    CORRECTION = "correction"
    GOAL = "goal"
    FEEDBACK = "feedback"


class EmotionalValence(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    URGENT = "urgent"


class PrivacyMode(str, Enum):
    PERSONAL = "personal"
    PATTERN = "pattern"


class ObservationStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    PURGED = "purged"


class ConflictAction(str, Enum):
    ADD = "ADD"
    UPDATE = "UPDATE"
    SUPERSEDE = "SUPERSEDE"
    NOOP = "NOOP"


class FeedbackSignalType(str, Enum):
    CONVERSION = "conversion"
    ABANDONMENT = "abandonment"
    HANDOFF_REQUEST = "handoff_request"
    OBJECTION = "objection"
    SATISFACTION = "satisfaction"
    DISSATISFACTION = "dissatisfaction"
    CORRECTION = "correction"
    TASK_COMPLETION = "task_completion"
    TASK_FAILURE = "task_failure"


# ── Core Memory Objects ──


class Observation(BaseModel):
    """🐝 Abelha: A distilled unit of knowledge."""

    id: Optional[str] = None
    agent_id: str
    user_id: str
    content: str
    obs_type: ObservationType
    entities: list[str] = Field(default_factory=list)
    importance: int = Field(default=5, ge=1, le=10)
    decay_score: float = Field(default=1.0, ge=0.0, le=1.0)
    ttl_days: int = Field(default=90)
    status: ObservationStatus = ObservationStatus.ACTIVE

    # 🐝 Emotional tagging
    emotional_valence: EmotionalValence = EmotionalValence.NEUTRAL
    emotional_intensity: int = Field(default=0, ge=0, le=5)

    # 🐜 Bi-temporal (Upgrade 16)
    event_time: Optional[datetime] = None
    created_at: Optional[datetime] = None
    last_accessed: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    invalidated_by: Optional[str] = None

    # Privacy (Upgrade 6)
    privacy_mode: PrivacyMode = PrivacyMode.PERSONAL
    anonymized_user_hash: Optional[str] = None

    # Frequency tracking (Upgrade 5)
    topic_fingerprint: Optional[str] = None
    occurrence_count: int = Field(default=1)

    # Linking
    superseded_by: Optional[str] = None
    source_session: Optional[str] = None
    embedding: Optional[list[float]] = None


class EntityNode(BaseModel):
    """🐬 Golfinho: An entity with a unique signature."""

    id: str
    entity_type: str  # person, project, tool, concept, organization, product, event
    display_name: str
    attributes: dict = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EntityEdge(BaseModel):
    """🐬 Golfinho: A typed relationship between entities."""

    id: Optional[str] = None
    subject_id: str
    predicate: str
    object_id: str
    properties: dict = Field(default_factory=dict)
    confidence: float = Field(default=1.0)
    source_observation: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Reflection(BaseModel):
    """🐜 Formiga + meta: A pattern, insight, or conflict resolution."""

    id: Optional[str] = None
    agent_id: str
    user_id: str
    reflection_type: str  # pattern, conflict_resolution, insight, summary, frequency_pattern
    content: str
    source_observations: list[str] = Field(default_factory=list)
    importance: int = Field(default=7)
    frequency_data: Optional[dict] = None
    embedding: Optional[list[float]] = None
    created_at: Optional[datetime] = None


class FeedbackSignal(BaseModel):
    """🦎 Camaleão: An outcome signal from the environment."""

    id: Optional[str] = None
    agent_id: str
    user_id: str
    session_id: str
    signal_type: FeedbackSignalType
    reward_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    action_taken: Optional[str] = None
    procedure_id: Optional[str] = None
    procedure_step: Optional[str] = None
    source: str = Field(default="implicit")  # explicit, implicit, system
    external_ref: Optional[str] = None
    context_snapshot: Optional[dict] = None
    created_at: Optional[datetime] = None


class ProcedureStep(BaseModel):
    """🦎 Camaleão: A step in a workflow procedure."""

    step_id: str
    action: str
    conditions: list[dict] = Field(default_factory=list)
    fallback: Optional[str] = None
    success_rate: Optional[float] = None
    total_attempts: int = 0
    successes: int = 0


class Procedure(BaseModel):
    """🦎 Camaleão: A versioned workflow."""

    id: Optional[str] = None
    agent_id: str
    procedure_name: str
    description: str = ""
    version: int = 1
    status: str = "active"  # active, draft, deprecated
    steps: list[ProcedureStep] = Field(default_factory=list)
    trigger_entities: list[str] = Field(default_factory=list)
    performance_score: float = Field(default=0.5)
    total_executions: int = 0
    successful_executions: int = 0
    created_by: str = "human"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CitationTrail(BaseModel):
    """🐘 Elefante: Record of which memories informed a response."""

    id: Optional[str] = None
    agent_id: str
    user_id: str
    session_id: str
    message_index: int
    used_observation_ids: list[str] = Field(default_factory=list)
    used_reflection_ids: list[str] = Field(default_factory=list)
    active_procedure_id: Optional[str] = None
    active_procedure_step: Optional[str] = None
    briefing_snapshot: Optional[str] = None
    n_sources: int = 0
    avg_combined_score: Optional[float] = None
    avg_decay_score: Optional[float] = None
    created_at: Optional[datetime] = None


class AgentImprint(BaseModel):
    """🐟 Salmão: The permanent identity of an agent."""

    agent_id: str
    role: str
    values: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    org_context: dict = Field(default_factory=dict)
    tone_of_voice: str = ""
    permissions: dict = Field(default_factory=dict)
    version: int = 1


class ConflictResult(BaseModel):
    """🐜 Formiga: Result of a conflict check."""

    action: ConflictAction
    existing_id: Optional[str] = None
    reason: str = ""
    llm_called: bool = False


class NEREntity(BaseModel):
    """🐝 Abelha (NER): A named entity extracted from text."""

    text: str
    label: str  # PERSON, EXAM, INSTITUTION, PRODUCT, SPECIALTY, DATE, MONEY
    confidence: float
    start: int = 0
    end: int = 0
