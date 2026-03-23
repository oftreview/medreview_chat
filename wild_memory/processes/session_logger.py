"""
🐝 Bee (safety) — Session Logger
Raw capture of conversations. Safety net for re-distillation.
TTL-based auto-cleanup (UP9).
"""
from __future__ import annotations
from datetime import datetime, timezone
from wild_memory.config import SessionLogConfig


class SessionLogger:
    def __init__(self, db, config: SessionLogConfig):
        self.db = db
        self.ttl_days = config.ttl_days

    async def append(self, session_id: str, messages: list[dict]):
        """Append messages to session log."""
        clean = [
            {"role": m.get("role", "unknown"), "content": m.get("content", ""),
             "timestamp": m.get("timestamp", datetime.now(timezone.utc).isoformat())}
            for m in messages if isinstance(m, dict) and "content" in m
        ]
        existing = self.db.table("session_logs").select("id, messages").eq(
            "session_id", session_id
        ).maybe_single().execute()
        if existing.data:
            merged = existing.data["messages"] + clean
            self.db.table("session_logs").update({"messages": merged}).eq(
                "id", existing.data["id"]
            ).execute()
        else:
            self.db.table("session_logs").insert({
                "session_id": session_id,
                "agent_id": "", "user_id": "",
                "messages": clean,
            }).execute()

    async def cleanup_expired(self):
        self.db.table("session_logs").delete().lt(
            "expires_at", datetime.now(timezone.utc).isoformat()
        ).execute()
