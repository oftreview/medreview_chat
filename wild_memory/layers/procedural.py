"""
🦎 Chameleon — Procedural Memory
Versioned workflows with per-step success tracking.
Editable via markdown (Dual Interface).
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional


class ProceduralMemory:
    def __init__(self, db):
        self.db = db

    async def get_active_procedure(
        self, agent_id: str, entities: list[str],
    ) -> Optional[dict]:
        """Find the best matching active procedure for current context."""
        result = self.db.table("procedures").select("*").eq(
            "agent_id", agent_id
        ).eq("status", "active").execute()

        if not result.data:
            return None

        # Score by entity overlap
        best, best_score = None, -1
        for proc in result.data:
            trigger = set(proc.get("trigger_entities", []))
            overlap = len(trigger.intersection(set(entities)))
            if overlap > best_score:
                best, best_score = proc, overlap

        return best if best_score > 0 else None

    async def record_step_outcome(
        self, procedure_id: str, step_id: str, success: bool,
    ):
        """Update success rate for a specific step."""
        proc = self.db.table("procedures").select(
            "steps, total_executions, successful_executions"
        ).eq("id", procedure_id).single().execute()

        steps = proc.data["steps"]
        for step in steps:
            if step.get("step_id") == step_id:
                total = step.get("total_attempts", 0) + 1
                wins = step.get("successes", 0) + (1 if success else 0)
                step["total_attempts"] = total
                step["successes"] = wins
                step["success_rate"] = round(wins / total, 3)

        total_exec = proc.data["total_executions"] + 1
        succ_exec = proc.data["successful_executions"] + (1 if success else 0)

        self.db.table("procedures").update({
            "steps": steps,
            "total_executions": total_exec,
            "successful_executions": succ_exec,
            "performance_score": round(succ_exec / total_exec, 3),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", procedure_id).execute()

    async def get_weak_steps(
        self, procedure_id: str, threshold: float = 0.4,
    ) -> list[dict]:
        """Find steps with low success rate (for review suggestions)."""
        proc = self.db.table("procedures").select("steps").eq(
            "id", procedure_id
        ).single().execute()
        return [
            s for s in proc.data["steps"]
            if s.get("success_rate", 1.0) < threshold
            and s.get("total_attempts", 0) >= 10
        ]
