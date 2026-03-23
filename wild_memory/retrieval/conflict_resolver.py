"""
🐜 Ant — Conflict Resolver (UP19 + UP23)
Two-phase conflict detection: embedding search first (no LLM),
LLM classification only when similar observations found.
Saves ~70% of LLM calls.
"""
from __future__ import annotations
import json
from wild_memory.models import ConflictResult, ConflictAction
from wild_memory.config import ConflictConfig
from wild_memory.prompts.conflict import CONFLICT_PROMPT


class ConflictResolver:
    def __init__(self, db, router, embedding_cache, config: ConflictConfig):
        self.db = db
        self.router = router
        self.embedding_cache = embedding_cache
        self.threshold = config.similarity_threshold

    async def check(
        self, agent_id: str, user_id: str,
        embedding: list, obs_data: dict,
    ) -> ConflictResult:
        """Two-phase conflict check."""
        # Phase 1: embedding search (no LLM)
        similar = self.db.rpc("find_similar_observations", {
            "p_agent_id": agent_id, "p_user_id": user_id,
            "p_embedding": embedding,
            "p_threshold": self.threshold, "p_limit": 3,
        }).execute()

        if not similar.data:
            return ConflictResult(action=ConflictAction.ADD, reason="no_similar_found", llm_called=False)

        # Phase 2: LLM classification (only when similar found)
        result = await self.router.call(
            task="conflict_resolution",
            system=CONFLICT_PROMPT.format(
                new_observation=json.dumps(obs_data, default=str),
                existing_observations=json.dumps(similar.data, default=str),
            ),
            messages=[{"role": "user", "content": "Classify."}],
            max_tokens=200,
        )
        try:
            text = result.content[0].text if hasattr(result, "content") else str(result)
            data = json.loads(text.strip().strip("`").strip("json").strip())
            return ConflictResult(
                action=ConflictAction(data.get("action", "ADD")),
                existing_id=data.get("existing_id"),
                reason=data.get("reason", ""),
                llm_called=True,
            )
        except (json.JSONDecodeError, ValueError):
            return ConflictResult(action=ConflictAction.ADD, reason="parse_error", llm_called=True)
