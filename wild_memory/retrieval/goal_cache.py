"""
🐘 Elephant (economy) — Goal Cache (UP22)
Persists detected goal between turns, only re-detects when
the topic changes. Saves ~60% of goal detection calls.
"""
from __future__ import annotations
from typing import Optional
from wild_memory.config import GoalCacheConfig


class GoalCache:
    def __init__(self, ner, config: GoalCacheConfig):
        self.ner = ner
        self._current: Optional[str] = None
        self._turns: int = 0
        self._last_entities: set = set()
        self._max_turns = config.max_turns
        self._change_signals = config.change_signals

    def should_redetect(self, user_msg: str) -> bool:
        self._turns += 1
        if self._current is None:
            return True
        if self._turns >= self._max_turns:
            return True
        new_ents = set(self.ner.to_entity_ids(self.ner.extract(user_msg)))
        if new_ents and not new_ents.intersection(self._last_entities):
            return True
        if any(s in user_msg.lower() for s in self._change_signals):
            return True
        return False

    def update(self, goal: str, entities: set):
        self._current = goal
        self._last_entities = entities
        self._turns = 0

    def get_current(self) -> Optional[str]:
        return self._current
