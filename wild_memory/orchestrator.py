"""
Wild Memory — Orchestrator
The main entry point that connects all 6 animal layers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from wild_memory.config import WildMemoryConfig
from wild_memory.models import AgentImprint

# Layer imports
from wild_memory.layers.imprint import ImprintLayer
from wild_memory.layers.working import WorkingMemory
from wild_memory.layers.observation import ObservationLayer
from wild_memory.layers.procedural import ProceduralMemory
from wild_memory.layers.entity_graph import EntityGraph
from wild_memory.layers.reflection import ReflectionLayer
from wild_memory.layers.feedback import FeedbackLayer

# Retrieval imports
from wild_memory.retrieval.elephant_recall import ElephantRecall
from wild_memory.retrieval.briefing_builder import BriefingBuilder
from wild_memory.retrieval.briefing_cache import BriefingCache
from wild_memory.retrieval.goal_cache import GoalCache
from wild_memory.retrieval.conflict_resolver import ConflictResolver
from wild_memory.retrieval.dynamic_recall import DynamicRecall

# Process imports
from wild_memory.processes.bee_distiller import BeeDistiller
from wild_memory.processes.distillation_gate import DistillationGate
from wild_memory.processes.ant_decay import AntDecay
from wild_memory.processes.session_logger import SessionLogger
from wild_memory.processes.ner_pipeline import NERPipeline

# Infrastructure imports
from wild_memory.infra.model_router import ModelRouter
from wild_memory.infra.embedding_cache import EmbeddingCache
from wild_memory.infra.semantic_cache import SemanticCache
from wild_memory.infra.checkpoint import CheckpointManager
from wild_memory.infra.db import create_supabase_client

# Audit
from wild_memory.audit.memory_audit import MemoryAudit
from wild_memory.audit.citation_logger import CitationLogger

# Tool definitions
from wild_memory.tools import MEMORY_TOOLS


class WildMemory:
    """
    🌿 Wild Memory — The main orchestrator.

    Connects all 6 animal-inspired layers into a unified
    memory system for AI agents.

    Usage:
        memory = WildMemory.from_config("wild_memory.yaml")
        reply = await memory.process_message(
            agent_id="my_agent",
            user_id="user_123",
            message="Hello!",
            session_id="session_abc"
        )
    """

    def __init__(self, config: WildMemoryConfig):
        self.config = config

        # Infrastructure
        self.db = create_supabase_client(config.supabase)
        self.router = ModelRouter(config.models)
        self.embedding_cache = EmbeddingCache(config.embedding)
        self.ner = NERPipeline()

        # 🐟 Salmon — Identity
        self.imprint = ImprintLayer(self.db, config.imprint_path)

        # 🐝 Bee — Distillation
        self.observations = ObservationLayer(
            self.db, self.embedding_cache, self.router, self.ner, config
        )
        self.distiller = BeeDistiller(
            self.observations, self.router, self.ner, config
        )
        self.distill_gate = DistillationGate(self.ner, config.gate)
        self.session_logger = SessionLogger(self.db, config.session_log)

        # 🐘 Elephant — Retrieval
        self.briefing_builder = BriefingBuilder()
        self.briefing_cache = BriefingCache(config.briefing_cache)
        self.goal_cache = GoalCache(self.ner, config.goal_cache)
        self.recall = ElephantRecall(
            imprint=self.imprint,
            observations=self.observations,
            graph=None,  # set after entity_graph init
            reflection=None,  # set after reflection init
            briefing_builder=self.briefing_builder,
            briefing_cache=self.briefing_cache,
            goal_cache=self.goal_cache,
            router=self.router,
            embedding_cache=self.embedding_cache,
            ner=self.ner,
            config=config,
        )
        self.dynamic_recall = DynamicRecall(
            self.observations, None, self.session_logger,
            self.embedding_cache, config
        )

        # 🐬 Dolphin — Connection
        self.entity_graph = EntityGraph(self.db)
        self.recall.graph = self.entity_graph
        self.dynamic_recall.graph = self.entity_graph

        # 🐜 Ant — Forgetting
        self.conflict_resolver = ConflictResolver(
            self.db, self.router, self.embedding_cache, config.conflict
        )
        self.decay = AntDecay(self.db, config.decay)
        self.reflection = ReflectionLayer(self.db, self.router, config)
        self.recall.reflection = self.reflection

        # 🦎 Chameleon — Adaptation
        self.feedback = FeedbackLayer(self.db, config)
        self.procedural = ProceduralMemory(self.db)
        self.semantic_cache = SemanticCache(
            self.db, self.embedding_cache, config.cache
        )
        self.checkpoint = CheckpointManager(self.db, config.checkpoint)
        self.citation = CitationLogger(self.db)
        self.audit = MemoryAudit(self.db)

        # Working memory (per-session, created on demand)
        self._sessions: dict[str, WorkingMemory] = {}

    @classmethod
    def from_config(cls, path: str | Path = "wild_memory.yaml") -> "WildMemory":
        """Create WildMemory from a YAML config file."""
        config = WildMemoryConfig.from_yaml(path)
        return cls(config)

    @classmethod
    def default(cls) -> "WildMemory":
        """Create WildMemory with default config (requires env vars)."""
        config = WildMemoryConfig.default()
        return cls(config)

    def _get_working(self, session_id: str) -> WorkingMemory:
        """Get or create working memory for a session."""
        if session_id not in self._sessions:
            self._sessions[session_id] = WorkingMemory(self.config)
        return self._sessions[session_id]

    async def process_message(
        self,
        agent_id: str,
        user_id: str,
        message: str,
        session_id: str,
    ) -> str:
        """
        Process a message through the full Wild Memory pipeline.

        This is the main entry point. It:
        1. Checks semantic cache (economy)
        2. Builds context with Elephant Recall (retrieval)
        3. Calls LLM with memory tools (conversation)
        4. Logs citation trail (auditability)
        5. Distills observations if warranted (distillation)
        6. Checkpoints state (resilience)

        Returns the agent's reply text.
        """
        working = self._get_working(session_id)

        # Generate embedding ONCE for this turn (UP24)
        msg_emb = self.embedding_cache.embed(message)

        # ── Step 0: Semantic Cache (UP12) ──
        if self.config.cache.enabled:
            cached = await self.semantic_cache.check_with_embedding(
                agent_id, msg_emb
            )
            if cached:
                working.add_message("user", message)
                working.add_message("assistant", cached)
                self.embedding_cache.clear_turn()
                return cached

        working.add_message("user", message)

        # ── Step 1: Restore checkpoint if needed (UP15) ──
        if len(working.messages) == 1:
            cp = await self.checkpoint.restore(agent_id, session_id)
            if cp:
                working.restore_from(cp)

        # ── Step 2: Build context — Elephant Recall (UP10, 20, 22) ──
        context, used_ids = await self.recall.build_context(
            agent_id, user_id, message, msg_emb
        )

        # ── Step 3: Call LLM with memory tools ──
        response = await self.router.call(
            task="lead_conversation",
            system=context,
            messages=working.get_llm_messages(),
            tools=MEMORY_TOOLS,
        )

        # ── Step 3b: Handle tool calls (UP7, UP17) ──
        reply = await self._handle_response(
            response, agent_id, user_id, session_id, working, context
        )

        working.add_message("assistant", reply)

        # ── Step 4: Citation Trail (UP11) ──
        await self.citation.log(
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            message_index=len(working.messages),
            used_observation_ids=used_ids.get("obs", []),
            used_reflection_ids=used_ids.get("ref", []),
            active_procedure_id=used_ids.get("proc_id"),
            active_procedure_step=used_ids.get("proc_step"),
            n_sources=len(used_ids.get("obs", [])),
            avg_decay_score=used_ids.get("avg_decay"),
        )

        # ── Step 5: Distillation Gate + Bee Distiller (UP21, UP8) ──
        if self.distill_gate.should_distill(message, reply):
            asyncio.create_task(
                self.distiller.distill_and_save(
                    agent_id=agent_id,
                    user_id=user_id,
                    conversation=working.messages[-4:],
                    session_id=session_id,
                    conflict_resolver=self.conflict_resolver,
                )
            )

        # ── Step 6: Cache response (UP12) ──
        if self.config.cache.enabled:
            await self.semantic_cache.store(agent_id, message, reply)

        # ── Step 7: Checkpoint (UP15) ──
        if self.checkpoint.should_checkpoint(len(working.messages)):
            await self.checkpoint.save(
                agent_id=agent_id,
                session_id=session_id,
                working=working,
                procedure=used_ids.get("procedure"),
                last_obs_ids=used_ids.get("obs", []),
            )

        # ── Step 8: Session log (UP9) ──
        await self.session_logger.append(
            session_id, working.messages[-2:]
        )

        # Clear embedding cache for this turn
        self.embedding_cache.clear_turn()

        return reply

    async def end_session(
        self, agent_id: str, user_id: str, session_id: str
    ):
        """
        End a session: full distillation + reflection.
        Call when session is considered complete.
        """
        working = self._get_working(session_id)

        # Full distillation of remaining messages
        await self.distiller.distill_and_save(
            agent_id=agent_id,
            user_id=user_id,
            conversation=working.messages,
            session_id=session_id,
            conflict_resolver=self.conflict_resolver,
            flush_mode=True,
        )

        # Run reflection
        await self.reflection.run_reflection(agent_id, user_id)

        # Clean up
        del self._sessions[session_id]

    async def _handle_response(
        self, response, agent_id, user_id, session_id, working, context
    ) -> str:
        """Handle LLM response, processing any tool calls."""
        # Simple case: text response
        if not hasattr(response, "stop_reason") or response.stop_reason != "tool_use":
            return self._extract_text(response)

        # Tool call loop
        max_iterations = 5
        for _ in range(max_iterations):
            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue

                if block.name == "recall_memory":
                    result = await self.dynamic_recall.handle_recall(
                        agent_id, user_id, **block.input
                    )
                elif block.name == "save_observation":
                    result = await self._handle_save_observation(
                        agent_id, user_id, session_id, block.input
                    )
                    self.briefing_cache.invalidate("write_tool_used")
                elif block.name == "update_entity":
                    result = await self._handle_update_entity(block.input)
                    self.briefing_cache.invalidate("entity_updated")
                else:
                    result = f"Unknown tool: {block.name}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            # Re-call LLM with tool results
            working.add_tool_results(tool_results)
            response = await self.router.call(
                task="lead_conversation",
                system=context,
                messages=working.get_llm_messages(),
                tools=MEMORY_TOOLS,
            )

            if not hasattr(response, "stop_reason") or response.stop_reason != "tool_use":
                break

        return self._extract_text(response)

    async def _handle_save_observation(
        self, agent_id: str, user_id: str, session_id: str, params: dict
    ) -> str:
        """Handle save_observation tool call (UP17)."""
        from wild_memory.models import Observation, ObservationType

        ner_entities = self.ner.extract(params["content"])
        entity_ids = self.ner.to_entity_ids(ner_entities)
        emb = self.embedding_cache.embed(params["content"])

        # Conflict check (UP19 + UP23)
        conflict = await self.conflict_resolver.check(
            agent_id, user_id, emb,
            {"content": params["content"], "obs_type": params["obs_type"]}
        )

        if conflict.action.value == "NOOP":
            return "Already known. No action taken."

        obs = Observation(
            agent_id=agent_id,
            user_id=user_id,
            content=params["content"],
            obs_type=ObservationType(params["obs_type"]),
            entities=entity_ids,
            importance=params.get("importance", 7),
            event_time=params.get("event_time"),
            source_session=session_id,
            embedding=emb,
        )

        result = await self.observations.save(obs, conflict)
        return f"Saved ({conflict.action.value}): {result[:8]}"

    async def _handle_update_entity(self, params: dict) -> str:
        """Handle update_entity tool call (UP17)."""
        await self.entity_graph.update_attribute(
            params["entity_id"],
            params["attribute"],
            params["new_value"],
        )
        return f"Entity {params['entity_id']} updated."

    def _extract_text(self, response) -> str:
        """Extract text from LLM response."""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return ""

    # ── Cron jobs (call from scheduler) ──

    async def run_daily_decay(self):
        """🐜 Ant Decay: run daily forgetting cycle."""
        await self.decay.run_daily()

    async def run_daily_reflection(self, agent_id: str):
        """🐜 Reflection: run nightly pattern detection."""
        await self.reflection.run_all_users(agent_id)

    async def run_daily_feedback_analysis(self, agent_id: str):
        """🦎 Chameleon: analyze feedback signals."""
        await self.feedback.generate_insights(agent_id)

    async def run_cache_cleanup(self):
        """Clean expired semantic cache entries."""
        await self.semantic_cache.cleanup_expired()

    async def run_session_cleanup(self):
        """Clean expired session logs."""
        await self.session_logger.cleanup_expired()

    async def run_checkpoint_cleanup(self):
        """Clean old checkpoints."""
        await self.checkpoint.cleanup_old()
