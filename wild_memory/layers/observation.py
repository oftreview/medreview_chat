"""
🐝 Bee — Observation Layer
Core storage and retrieval for distilled knowledge units.
Each observation is a compact, self-descriptive fact with
metadata: type, importance, emotion, temporal, entities.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from wild_memory.models import Observation, ConflictResult, ConflictAction


class ObservationLayer:
    """CRUD operations for observations in Supabase."""

    def __init__(self, db, embedding_cache, router, ner, config):
        self.db = db
        self.embedding_cache = embedding_cache
        self.router = router
        self.ner = ner
        self.config = config

    async def save(self, obs: Observation, conflict: Optional[ConflictResult] = None) -> str:
        """Save an observation to Supabase. Returns the new ID."""
        data = {
            "agent_id": obs.agent_id,
            "user_id": obs.user_id,
            "content": obs.content,
            "obs_type": obs.obs_type.value,
            "entities": obs.entities,
            "importance": obs.importance,
            "decay_score": obs.decay_score,
            "ttl_days": self._get_ttl(obs.obs_type.value),
            "emotional_valence": obs.emotional_valence.value,
            "emotional_intensity": obs.emotional_intensity,
            "privacy_mode": obs.privacy_mode.value,
            "event_time": obs.event_time.isoformat() if obs.event_time else None,
            "source_session": obs.source_session,
            "embedding": obs.embedding,
        }
        result = self.db.table("observations").insert(data).execute()
        new_id = result.data[0]["id"]

        # If superseding, invalidate the old one
        if conflict and conflict.action == ConflictAction.SUPERSEDE and conflict.existing_id:
            self.db.table("observations").update({
                "invalidated_at": datetime.now(timezone.utc).isoformat(),
                "invalidated_by": new_id,
            }).eq("id", conflict.existing_id).execute()

        return new_id

    async def retrieve(
        self, agent_id: str, user_id: str,
        goal: str, entities: list[str],
        search_query: str = "",
        limit: int = 10, min_decay: float = 0.3,
    ) -> list[dict]:
        """Retrieve observations using 5-signal combined score."""
        emb = self.embedding_cache.embed(goal)
        result = self.db.rpc("retrieve_observations", {
            "p_agent_id": agent_id,
            "p_user_id": user_id,
            "p_embedding": emb,
            "p_entities": entities,
            "p_search_query": search_query,
            "p_limit": limit,
            "p_min_decay": min_decay,
        }).execute()

        # Reinforce accessed observations
        for obs in result.data:
            self.db.rpc("reinforce_observation", {"obs_id": obs["id"]}).execute()

        return result.data

    async def find_similar(
        self, agent_id: str, user_id: str,
        embedding: list, threshold: float = 0.85, limit: int = 3,
    ) -> list[dict]:
        """Find similar observations for conflict detection."""
        result = self.db.rpc("find_similar_observations", {
            "p_agent_id": agent_id,
            "p_user_id": user_id,
            "p_embedding": embedding,
            "p_threshold": threshold,
            "p_limit": limit,
        }).execute()
        return result.data

    def _get_ttl(self, obs_type: str) -> int:
        defaults = self.config.ttl_defaults
        return getattr(defaults, obs_type, 90)
