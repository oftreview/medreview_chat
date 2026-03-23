"""
🐘 Elephant — Recall (Progressive Loading)
Builds the context for each LLM call by assembling the briefing
from all memory layers in a fixed, intentional order.
"""
from __future__ import annotations
from typing import Optional


class ElephantRecall:
    """Orchestrates retrieval across all memory layers."""

    def __init__(self, imprint, observations, graph, reflection,
                 briefing_builder, briefing_cache, goal_cache,
                 router, embedding_cache, ner, config):
        self.imprint = imprint
        self.obs = observations
        self.graph = graph
        self.reflection = reflection
        self.briefing_builder = briefing_builder
        self.briefing_cache = briefing_cache
        self.goal_cache = goal_cache
        self.router = router
        self.embedding_cache = embedding_cache
        self.ner = ner
        self.config = config

    async def build_context(
        self, agent_id: str, user_id: str,
        message: str, msg_embedding: list,
    ) -> tuple[str, dict]:
        """Build complete context for the LLM call."""

        # 1. Imprint (always)
        imprint_block = self.imprint.to_system_prompt()

        # 2. Goal detection (cached, UP22)
        goal = await self._detect_goal_smart(message)

        # 3. Briefing (cached, UP20)
        if self.briefing_cache.should_rebuild(goal):
            ner_entities = self.ner.extract(message)
            entity_ids = self.ner.to_entity_ids(ner_entities)

            obs = await self.obs.retrieve(
                agent_id, user_id, goal=goal,
                entities=entity_ids, search_query=message,
                limit=10, min_decay=0.3,
            )
            insights = []
            if self.reflection:
                insights = await self.reflection.get_relevant(
                    agent_id, user_id, goal, limit=3
                )
            entity_context = {}
            if self.graph and entity_ids:
                for eid in entity_ids[:3]:
                    try:
                        sg = await self.graph.traverse(eid, max_depth=2)
                        entity_context[eid] = sg
                    except Exception:
                        pass

            briefing, used_obs_ids = self.briefing_builder.build(
                observations=obs,
                insights=insights,
                entity_context=entity_context,
            )
            self.briefing_cache.mark_clean(briefing, used_obs_ids)
        else:
            briefing, used_obs_ids = self.briefing_cache.get_cached()

        # Assemble final context
        context = f"{imprint_block}\n\n---\n\n{briefing}"

        used_ids = {
            "obs": used_obs_ids,
            "ref": [],
            "avg_decay": self._avg_decay(used_obs_ids),
        }
        return context, used_ids

    async def _detect_goal_smart(self, message: str) -> str:
        """Goal detection with caching (UP22)."""
        if self.goal_cache.should_redetect(message):
            from wild_memory.prompts.detect_goal import GOAL_DETECT_PROMPT
            result = await self.router.call(
                task="goal_detection",
                system=GOAL_DETECT_PROMPT,
                messages=[{"role": "user", "content": message}],
                max_tokens=200,
            )
            goal = result.content[0].text if hasattr(result, "content") else str(result)
            ner_ents = set(self.ner.to_entity_ids(self.ner.extract(message)))
            self.goal_cache.update(goal.strip(), ner_ents)
        return self.goal_cache.get_current() or "general"

    def _avg_decay(self, obs_ids: list) -> Optional[float]:
        return None  # Computed from retrieved obs in production
