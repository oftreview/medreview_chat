"""
🐘 Elephant (economy) — Semantic Cache
Caches responses for semantically similar queries.
Saves 30-50% of tokens on frequently asked questions (UP12).
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from wild_memory.config import CacheConfig


class SemanticCache:
    """Semantic response cache backed by Supabase + pgvector."""

    def __init__(self, db, embedding_cache, config: CacheConfig):
        self.db = db
        self.embedding_cache = embedding_cache
        self.config = config

    async def check(self, agent_id: str, query: str) -> Optional[str]:
        """Check if a similar query was already answered."""
        if not self.config.enabled:
            return None
        if self._is_personal(query):
            return None
        emb = self.embedding_cache.embed(query)
        return await self.check_with_embedding(agent_id, emb)

    async def check_with_embedding(self, agent_id: str, emb: list) -> Optional[str]:
        """Check cache with pre-computed embedding."""
        if not self.config.enabled:
            return None
        result = self.db.rpc("search_semantic_cache", {
            "p_agent_id": agent_id,
            "p_embedding": emb,
            "p_threshold": self.config.similarity_threshold,
        }).execute()
        if result.data and len(result.data) > 0:
            hit = result.data[0]
            self.db.table("semantic_cache").update({
                "hit_count": hit["hit_count"] + 1,
                "last_hit": datetime.now(timezone.utc).isoformat(),
            }).eq("id", hit["id"]).execute()
            return hit["response_text"]
        return None

    async def store(self, agent_id: str, query: str, response: str):
        """Cache a new response."""
        if not self.config.enabled or self._is_personal(query):
            return
        emb = self.embedding_cache.embed(query)
        self.db.table("semantic_cache").insert({
            "agent_id": agent_id,
            "query_embedding": emb,
            "query_text": query,
            "response_text": response,
            "ttl_hours": self.config.ttl_hours,
        }).execute()

    async def cleanup_expired(self):
        """Remove expired cache entries."""
        self.db.table("semantic_cache").delete().lt(
            "expires_at", datetime.now(timezone.utc).isoformat()
        ).execute()

    def _is_personal(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in self.config.personal_keywords)
