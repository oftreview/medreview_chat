"""
🦎 Chameleon (economy) — Model Router
Routes LLM calls to the appropriate model tier.
Premium for lead conversation, economy for internal ops.
Saves ~73% on internal operations (UP13).
"""
from __future__ import annotations
from typing import Optional

from wild_memory.config import ModelsConfig


TASK_TIER_MAP = {
    # Premium: direct lead interaction
    "lead_conversation": "premium",
    "complex_objection_handling": "premium",
    # Economy: internal operations
    "bee_distill": "economy",
    "goal_detection": "economy",
    "reflection": "economy",
    "feedback_analysis": "economy",
    "flush_distill": "economy",
    "entity_extraction": "economy",
    "summary_compression": "economy",
    "conflict_resolution": "economy",
}


class ModelRouter:
    """Routes LLM calls to premium or economy models."""

    def __init__(self, config: ModelsConfig):
        self.config = config
        self._clients = {}

    def get_model_config(self, task: str) -> dict:
        tier = TASK_TIER_MAP.get(task, "economy")
        model_cfg = getattr(self.config, tier)
        return {"provider": model_cfg.provider, "model": model_cfg.model}

    async def call(
        self, task: str, system: str, messages: list,
        max_tokens: int = 4096, tools: Optional[list] = None,
    ):
        """Call the appropriate model for the task."""
        cfg = self.get_model_config(task)
        client = self._get_client(cfg["provider"])

        kwargs = {
            "model": cfg["model"],
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = client.messages.create(**kwargs)
        return response

    def _get_client(self, provider: str):
        if provider not in self._clients:
            if provider == "anthropic":
                from anthropic import Anthropic
                self._clients[provider] = Anthropic()
            elif provider == "openai":
                from openai import OpenAI
                self._clients[provider] = OpenAI()
        return self._clients[provider]
