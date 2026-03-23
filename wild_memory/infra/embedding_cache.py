"""
🐘 Elephant (economy) — Embedding Cache
Generates an embedding ONCE per text per turn and reuses it
across all modules (cache, recall, distiller, conflict).
Saves ~75% of embedding API calls (UP24).
"""
from __future__ import annotations
import hashlib
from wild_memory.config import EmbeddingConfig


class EmbeddingCache:
    """Per-turn embedding cache. Call clear_turn() after each turn."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._cache: dict[str, list[float]] = {}
        self._client = None
        self._hits = 0
        self._misses = 0

    def embed(self, text: str) -> list[float]:
        """Get or generate embedding for text."""
        key = hashlib.md5(text.strip().lower().encode()).hexdigest()
        if key in self._cache:
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        client = self._get_client()
        response = client.embeddings.create(
            model=self.config.model,
            input=text,
            dimensions=self.config.dimensions,
        )
        emb = response.data[0].embedding
        self._cache[key] = emb
        return emb

    def clear_turn(self):
        """Clear cache at end of turn."""
        self._cache.clear()

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / max(total, 1),
        }

    def _get_client(self):
        if self._client is None:
            if self.config.provider == "openai":
                from openai import OpenAI
                self._client = OpenAI()
        return self._client
