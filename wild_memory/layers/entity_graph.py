"""
🐬 Dolphin — Entity Graph
Maps relationships between entities (people, projects, products).
"""
from __future__ import annotations


class EntityGraph:
    def __init__(self, db):
        self.db = db

    async def upsert_entity(self, entity_id: str, entity_type: str, display_name: str, attributes: dict = {}):
        self.db.table("entity_nodes").upsert({
            "id": entity_id, "entity_type": entity_type,
            "display_name": display_name, "attributes": attributes,
        }).execute()

    async def add_edge(self, subject: str, predicate: str, obj: str, source_obs: str = None, properties: dict = {}):
        self.db.table("entity_edges").upsert({
            "subject_id": subject, "predicate": predicate,
            "object_id": obj, "source_observation": source_obs, "properties": properties,
        }).execute()

    async def traverse(self, start_entity: str, max_depth: int = 2) -> dict:
        visited, queue = set(), [(start_entity, 0)]
        subgraph = {"nodes": {}, "edges": []}
        while queue:
            eid, depth = queue.pop(0)
            if eid in visited or depth > max_depth:
                continue
            visited.add(eid)
            node = self.db.table("entity_nodes").select("*").eq("id", eid).maybe_single().execute()
            if node.data:
                subgraph["nodes"][eid] = node.data
            edges = self.db.table("entity_edges").select("*").or_(f"subject_id.eq.{eid},object_id.eq.{eid}").execute()
            for e in (edges.data or []):
                subgraph["edges"].append(e)
                next_id = e["object_id"] if e["subject_id"] == eid else e["subject_id"]
                queue.append((next_id, depth + 1))
        return subgraph

    async def update_attribute(self, entity_id: str, attribute: str, value: str):
        node = self.db.table("entity_nodes").select("attributes").eq("id", entity_id).maybe_single().execute()
        if node.data:
            attrs = node.data.get("attributes", {})
            attrs[attribute] = value
            self.db.table("entity_nodes").update({"attributes": attrs}).eq("id", entity_id).execute()
