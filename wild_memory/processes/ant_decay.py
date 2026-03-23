"""
🐜 Ant — Decay System
Active forgetting: memories not accessed lose strength.
Three axes: temporal, frequency-based, importance-driven.
"""
from __future__ import annotations
from wild_memory.config import DecayConfig


class AntDecay:
    def __init__(self, db, config: DecayConfig):
        self.db = db
        self.config = config

    async def run_daily(self):
        """Run the full daily decay cycle."""
        # 1. Apply decay
        self.db.rpc("apply_daily_decay", {"decay_rate": self.config.daily_rate}).execute()
        # 2. Mark stale
        self.db.rpc("mark_stale_observations", {"decay_threshold": self.config.stale_threshold}).execute()
        # 3. Archive low-decay (except protected)
        self.db.table("observations").update({"status": "archived"}).lt(
            "decay_score", self.config.archive_threshold
        ).eq("status", "active").not_.in_(
            "obs_type", self.config.protected_types
        ).execute()
