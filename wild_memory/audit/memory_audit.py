"""
🦎 Chameleon — Memory Audit
Human-facing inspection, correction, and LGPD compliance.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from typing import Optional


class MemoryAudit:
    def __init__(self, db):
        self.db = db

    async def get_user_memory(self, agent_id: str, user_id: str) -> dict:
        """Get everything the agent knows about a user."""
        obs = self.db.table("observations").select("*").eq(
            "agent_id", agent_id
        ).eq("user_id", user_id).eq("status", "active").order(
            "created_at", desc=True
        ).execute()

        reflections = self.db.table("reflections").select("*").eq(
            "agent_id", agent_id
        ).eq("user_id", user_id).order("created_at", desc=True).execute()

        return {
            "user_id": user_id,
            "observations": obs.data or [],
            "reflections": reflections.data or [],
            "stats": {
                "total_observations": len(obs.data or []),
                "by_type": self._count_by_type(obs.data or []),
            },
        }

    async def correct_observation(
        self, obs_id: str, correction: str, auditor: str,
    ) -> str:
        """Correct an observation (creates new, archives old)."""
        old = self.db.table("observations").select("*").eq(
            "id", obs_id
        ).single().execute()

        if not old.data:
            return "Not found"

        # Create corrected version
        new_data = {**old.data}
        del new_data["id"]
        new_data["content"] = correction
        new_data["obs_type"] = "correction"
        new_data["importance"] = max(old.data.get("importance", 5), 7)
        new_data["decay_score"] = 1.0
        new_data["source_session"] = f"audit_{auditor}"
        result = self.db.table("observations").insert(new_data).execute()
        new_id = result.data[0]["id"]

        # Invalidate old
        self.db.table("observations").update({
            "invalidated_at": datetime.now(timezone.utc).isoformat(),
            "invalidated_by": new_id,
            "status": "archived",
        }).eq("id", obs_id).execute()

        return new_id

    async def purge_user_data(
        self, user_id: str, keep_patterns: bool = True,
    ):
        """LGPD: right to be forgotten."""
        if keep_patterns:
            user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]
            self.db.table("observations").update({
                "privacy_mode": "pattern",
                "user_id": "anonymized",
                "anonymized_user_hash": user_hash,
                "entities": [],
            }).eq("user_id", user_id).eq("privacy_mode", "personal").execute()
        else:
            self.db.table("observations").update({
                "status": "purged"
            }).eq("user_id", user_id).execute()

        self.db.table("feedback_signals").delete().eq("user_id", user_id).execute()
        self.db.table("reflections").delete().eq("user_id", user_id).execute()

    def _count_by_type(self, obs: list[dict]) -> dict:
        counts = {}
        for o in obs:
            t = o.get("obs_type", "unknown")
            counts[t] = counts.get(t, 0) + 1
        return counts
