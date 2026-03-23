"""
🐝 Bee (economy) — Distillation Gate
Filters trivial turns BEFORE calling the Bee Distiller.
Saves ~35% of distillation calls (UP21). Zero tokens consumed.
"""
from __future__ import annotations
import re
from wild_memory.config import GateConfig


class DistillationGate:
    def __init__(self, ner, config: GateConfig):
        self.ner = ner
        self.config = config
        self._patterns = [re.compile(p, re.IGNORECASE) for p in config.trivial_patterns]

    def should_distill(self, user_msg: str, assistant_msg: str) -> bool:
        """Returns True if the turn deserves distillation."""
        combined = f"{user_msg} {assistant_msg}"

        # Reject very short messages (unless they have signals)
        if len(user_msg.strip()) < self.config.min_chars:
            if not self._has_signal(user_msg):
                return False

        # Reject trivial patterns
        for pat in self._patterns:
            if pat.match(user_msg.strip()):
                return False

        # Accept if NER finds entities
        if self.ner.extract(combined):
            return True

        # Accept if signal keywords present
        if self._has_signal(combined):
            return True

        # Accept long messages
        if len(user_msg) > 150:
            return True

        return False

    def _has_signal(self, text: str) -> bool:
        t = text.lower()
        return any(kw in t for kw in self.config.signal_keywords)
