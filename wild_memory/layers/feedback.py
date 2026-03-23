"""
🦎 Chameleon — Feedback Layer
Captures outcome signals and generates performance insights.
Integrates with CRM (HubSpot) via webhooks.
"""
from __future__ import annotations
import json
from wild_memory.models import FeedbackSignalType


REWARD_MAP = {
    "conversion": 1.0,
    "satisfaction": 0.7,
    "task_completion": 0.5,
    "objection": -0.2,
    "handoff_request": -0.3,
    "dissatisfaction": -0.5,
    "correction": -0.4,
    "abandonment": -0.6,
    "task_failure": -0.8,
}


class FeedbackLayer:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    async def record_signal(
        self, agent_id: str, user_id: str, session_id: str,
        signal_type: str, action_taken: str = None,
        procedure_id: str = None, procedure_step: str = None,
        source: str = "implicit", external_ref: str = None,
    ):
        """Record a feedback signal from the environment."""
        reward = REWARD_MAP.get(signal_type, 0.0)
        self.db.table("feedback_signals").insert({
            "agent_id": agent_id, "user_id": user_id,
            "session_id": session_id, "signal_type": signal_type,
            "reward_score": reward, "action_taken": action_taken,
            "procedure_id": procedure_id, "procedure_step": procedure_step,
            "source": source, "external_ref": external_ref,
        }).execute()

    async def get_session_reward(self, session_id: str) -> float:
        """Get aggregate reward for a session."""
        signals = self.db.table("feedback_signals").select(
            "reward_score"
        ).eq("session_id", session_id).execute()
        if not signals.data:
            return 0.0
        return sum(s["reward_score"] for s in signals.data) / len(signals.data)

    async def generate_insights(self, agent_id: str, days: int = 7):
        """Generate feedback insights (cron job)."""
        summary = self.db.rpc("get_feedback_summary", {
            "p_agent_id": agent_id, "p_days": days,
        }).execute()
        if not summary.data:
            return
        # Store as reflection
        content = "Feedback summary (last {}d): ".format(days)
        for row in summary.data:
            content += "{}={} (avg_reward:{:.2f}), ".format(
                row["signal_type"], row["count"], row["avg_reward"]
            )
        self.db.table("reflections").insert({
            "agent_id": agent_id, "user_id": "system",
            "reflection_type": "insight", "content": content.strip(", "),
            "importance": 6,
        }).execute()
