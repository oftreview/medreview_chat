"""
🦎 Chameleon — Checkpoint Manager
Periodically saves agent state for crash recovery (UP15).
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional

from wild_memory.config import CheckpointConfig


class CheckpointManager:
    def __init__(self, db, config: CheckpointConfig):
        self.db = db
        self.interval = config.interval_messages

    def should_checkpoint(self, message_count: int) -> bool:
        return message_count > 0 and message_count % self.interval == 0

    async def save(self, agent_id: str, session_id: str, working, procedure=None, last_obs_ids=None):
        self.db.table("agent_checkpoints").upsert({
            "agent_id": agent_id,
            "session_id": session_id,
            "working_memory": {
                "messages": working.messages,
                "token_count": working.token_count,
                "current_goal": working.current_goal,
                "module_states": working.module_states,
            },
            "active_procedure": procedure,
            "last_used_obs_ids": last_obs_ids or [],
            "message_count": len(working.messages),
        }).execute()

    async def restore(self, agent_id: str, session_id: str) -> Optional[dict]:
        result = self.db.table("agent_checkpoints").select("*").eq(
            "agent_id", agent_id
        ).eq("session_id", session_id).maybe_single().execute()
        return result.data if result.data else None

    async def cleanup_old(self, hours: int = 24):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        self.db.table("agent_checkpoints").delete().lt("created_at", cutoff).execute()
