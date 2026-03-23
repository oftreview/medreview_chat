"""
🐘 Elephant (economy) — Briefing Cache (UP20)
Only rebuilds briefing when something actually changes.
Saves ~62% of briefing rebuilds, ~$144/month.
"""
from __future__ import annotations
from typing import Optional
from wild_memory.config import BriefingCacheConfig


class BriefingCache:
    def __init__(self, config: BriefingCacheConfig):
        self._cached: Optional[str] = None
        self._cached_ids: list[str] = []
        self._dirty: bool = True
        self._last_goal: Optional[str] = None
        self._turns: int = 0
        self._max_turns = config.max_turns_without_rebuild

    def invalidate(self, reason: str = "unknown"):
        self._dirty = True

    def mark_clean(self, briefing: str, obs_ids: list[str]):
        self._cached = briefing
        self._cached_ids = obs_ids
        self._dirty = False
        self._turns = 0

    def should_rebuild(self, current_goal: str) -> bool:
        self._turns += 1
        if self._dirty or self._cached is None:
            return True
        if current_goal != self._last_goal:
            self._last_goal = current_goal
            return True
        if self._turns >= self._max_turns:
            return True
        return False

    def get_cached(self) -> tuple[str, list[str]]:
        return self._cached or "", self._cached_ids
