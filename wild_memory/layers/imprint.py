"""
🐟 Salmon — Imprint Layer
The agent's permanent identity. Loaded first, always.
Only humans edit this. The system reads, never writes.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

import yaml

from wild_memory.models import AgentImprint


class ImprintLayer:
    """Loads and caches the agent's identity from YAML."""

    def __init__(self, db, config_path: str):
        self.db = db
        self.config_path = Path(config_path)
        self._cache: Optional[AgentImprint] = None

    def load(self) -> AgentImprint:
        if self._cache:
            return self._cache
        if self.config_path.exists():
            with open(self.config_path) as f:
                data = yaml.safe_load(f)
            self._cache = AgentImprint(**data)
        else:
            self._cache = AgentImprint(
                agent_id="default", role="AI Assistant",
                values=[], constraints=[], org_context={}, tone_of_voice=""
            )
        return self._cache

    def to_system_prompt(self) -> str:
        imp = self.load()
        values = "\n".join(f"- {v}" for v in imp.values)
        constraints = "\n".join(f"- {c}" for c in imp.constraints)
        return (
            f"## IDENTITY (IMMUTABLE)\n"
            f"Role: {imp.role}\n"
            f"Values:\n{values}\n"
            f"Constraints:\n{constraints}\n"
            f"Context: {imp.org_context}\n"
            f"Tone: {imp.tone_of_voice}"
        )

    def invalidate_cache(self):
        self._cache = None
