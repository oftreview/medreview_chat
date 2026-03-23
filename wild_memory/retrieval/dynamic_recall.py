"""
🐘 Elephant — Dynamic Recall (UP7)
In-process retrieval: the agent can search memory mid-conversation.
"""
from __future__ import annotations


class DynamicRecall:
    def __init__(self, observations, graph, session_logger, embedding_cache, config):
        self.obs = observations
        self.graph = graph
        self.session_logger = session_logger
        self.embedding_cache = embedding_cache
        self.config = config

    async def handle_recall(
        self, agent_id: str, user_id: str,
        query: str, search_type: str, entity_id: str = None,
    ) -> str:
        """Process a recall_memory tool call."""
        if search_type == "semantic":
            results = await self.obs.retrieve(
                agent_id, user_id, goal=query,
                entities=[], search_query=query, limit=5, min_decay=0.2,
            )
            if not results:
                return "No relevant memories found."
            lines = [f"- [{r['obs_type']}] {r['content']}" for r in results]
            return "Memories found:\n" + "\n".join(lines)

        elif search_type == "entity" and entity_id and self.graph:
            sg = await self.graph.traverse(entity_id, max_depth=2)
            if not sg["nodes"]:
                return f"No information about entity '{entity_id}'."
            parts = [f"Entity: {n.get('display_name', k)}" for k, n in sg["nodes"].items()]
            for e in sg["edges"][:10]:
                parts.append(f"  {e['subject_id']} --{e['predicate']}--> {e['object_id']}")
            return "\n".join(parts)

        elif search_type == "temporal":
            results = await self.obs.retrieve(
                agent_id, user_id, goal=query,
                entities=[], limit=5, min_decay=0.1,
            )
            if not results:
                return "No recent memories found."
            lines = [f"- [{r.get('created_at', '?')[:10]}] {r['content']}" for r in results]
            return "Recent memories:\n" + "\n".join(lines)

        return "Unknown search type."
