"""
🐜 Ant — Reflection Layer
Analyzes observations to extract patterns, resolve conflicts,
and generate insights. Runs in nightly cron.
"""
from __future__ import annotations


class ReflectionLayer:
    def __init__(self, db, router, config):
        self.db = db
        self.router = router
        self.config = config

    async def run_reflection(self, agent_id: str, user_id: str):
        """Run reflection for a specific user."""
        # Get recent observations
        obs = self.db.table("observations").select("*").eq(
            "agent_id", agent_id
        ).eq("user_id", user_id).eq("status", "active").order(
            "created_at", desc=True
        ).limit(50).execute()
        if not obs.data:
            return
        # Call economy LLM for reflection
        from wild_memory.prompts.reflect import REFLECT_PROMPT
        import json
        result = await self.router.call(
            task="reflection",
            system=REFLECT_PROMPT.format(
                agent_id=agent_id,
                observations_json=json.dumps(obs.data, default=str)
            ),
            messages=[{"role": "user", "content": "Analyze."}],
        )
        # Parse and store reflections
        try:
            data = json.loads(result)
            for pattern in data.get("patterns", []):
                self.db.table("reflections").insert({
                    "agent_id": agent_id, "user_id": user_id,
                    "reflection_type": "pattern",
                    "content": pattern["content"],
                    "importance": pattern.get("importance", 7),
                }).execute()
            for insight in data.get("insights", []):
                self.db.table("reflections").insert({
                    "agent_id": agent_id, "user_id": user_id,
                    "reflection_type": "insight",
                    "content": insight["content"],
                    "importance": insight.get("importance", 7),
                }).execute()
        except (json.JSONDecodeError, KeyError):
            pass

    async def run_all_users(self, agent_id: str):
        """Run reflection for all users who had activity."""
        users = self.db.table("observations").select("user_id").eq(
            "agent_id", agent_id
        ).eq("status", "active").execute()
        seen = set()
        for row in (users.data or []):
            uid = row["user_id"]
            if uid not in seen:
                seen.add(uid)
                await self.run_reflection(agent_id, uid)

    async def get_relevant(self, agent_id: str, user_id: str, goal: str, limit: int = 3) -> list[dict]:
        result = self.db.table("reflections").select("*").eq(
            "agent_id", agent_id
        ).eq("user_id", user_id).order("created_at", desc=True).limit(limit).execute()
        return result.data or []
