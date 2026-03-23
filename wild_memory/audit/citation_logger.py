"""
🐘 Elephant — Citation Logger (UP11)
Records which observations informed each response.
Enables forward and reverse auditability.
"""
from __future__ import annotations
from typing import Optional


class CitationLogger:
    def __init__(self, db):
        self.db = db

    async def log(
        self, agent_id: str, user_id: str, session_id: str,
        message_index: int, used_observation_ids: list[str] = None,
        used_reflection_ids: list[str] = None,
        active_procedure_id: str = None,
        active_procedure_step: str = None,
        n_sources: int = 0, avg_decay_score: float = None,
    ):
        """Log citation trail for a response."""
        self.db.table("citation_trails").insert({
            "agent_id": agent_id, "user_id": user_id,
            "session_id": session_id, "message_index": message_index,
            "used_observation_ids": used_observation_ids or [],
            "used_reflection_ids": used_reflection_ids or [],
            "active_procedure_id": active_procedure_id,
            "active_procedure_step": active_procedure_step,
            "n_sources": n_sources, "avg_decay_score": avg_decay_score,
        }).execute()

    async def get_trail(self, session_id: str) -> list[dict]:
        """Get full citation trail for a session."""
        result = self.db.table("citation_trails").select("*").eq(
            "session_id", session_id
        ).order("message_index").execute()
        return result.data or []

    async def find_impact(self, obs_id: str) -> list[dict]:
        """Reverse lookup: which responses used this observation?"""
        result = self.db.table("citation_trails").select(
            "session_id, message_index, created_at"
        ).filter(
            "used_observation_ids", "cs", "{" + obs_id + "}"
        ).order("created_at", desc=True).execute()
        return result.data or []
