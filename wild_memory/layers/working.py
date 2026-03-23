"""
Working Memory — In-context session buffer.
Manages the conversation within the LLM's context window.
Triggers compression when threshold is reached.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional


class WorkingMemory:
    """Session-scoped working memory with auto-compression."""

    def __init__(self, config):
        self.max_tokens = config.max_context_tokens
        self.compress_threshold = config.compress_threshold
        self.messages: list[dict] = []
        self.module_states: dict[str, str] = {}
        self.current_goal: Optional[str] = None
        self.token_count: int = 0

    def add_message(self, role: str, content: str):
        tokens = self._estimate_tokens(content)
        self.messages.append({
            "role": role,
            "content": content,
            "tokens": tokens,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.token_count += tokens

    def add_tool_results(self, results: list[dict]):
        for r in results:
            self.messages.append(r)

    def get_llm_messages(self) -> list[dict]:
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self.messages
            if "role" in m and "content" in m
        ]

    def get_context_block(self) -> str:
        parts = []
        if self.current_goal:
            parts.append(f"## CURRENT GOAL: {self.current_goal}")
        if self.module_states:
            parts.append("## MODULE STATES")
            for mod, state in self.module_states.items():
                parts.append(f"- {mod}: {state}")
        return "\n".join(parts)

    def needs_compression(self) -> bool:
        return self.token_count > self.max_tokens * self.compress_threshold

    def get_messages_to_compress(self) -> tuple[list[dict], list[dict]]:
        """Returns (to_compress, to_keep). Keeps last 5 messages."""
        keep = self.messages[-5:]
        compress = self.messages[:-5]
        return compress, keep

    def apply_compression(self, summary: str, keep_messages: list[dict]):
        self.messages = [
            {
                "role": "system",
                "content": f"[COMPRESSED HISTORY]\n{summary}",
                "tokens": self._estimate_tokens(summary),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ] + keep_messages
        self.token_count = sum(m.get("tokens", 0) for m in self.messages)

    def restore_from(self, checkpoint: dict):
        wm = checkpoint.get("working_memory", {})
        self.messages = wm.get("messages", [])
        self.token_count = wm.get("token_count", 0)
        self.current_goal = wm.get("current_goal")
        self.module_states = wm.get("module_states", {})

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4 + 1
