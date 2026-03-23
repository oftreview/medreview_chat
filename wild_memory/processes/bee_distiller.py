"""
🐝 Bee — Distiller
Compresses conversations into distilled observation units.
Runs after each turn (if gate passes) and before compression (flush mode).
"""
from __future__ import annotations
import json
from typing import Optional

from wild_memory.prompts.distill import DISTILL_PROMPT, FLUSH_DISTILL_PROMPT
from wild_memory.models import Observation, ObservationType, EmotionalValence


class BeeDistiller:
    def __init__(self, observations, router, ner, config):
        self.obs = observations
        self.router = router
        self.ner = ner
        self.config = config

    async def distill_and_save(
        self, agent_id: str, user_id: str,
        conversation: list[dict], session_id: str,
        conflict_resolver=None, flush_mode: bool = False,
    ) -> list[str]:
        """Distill conversation into observations and save them."""
        conv_text = "\n".join(
            f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}"
            for m in conversation if isinstance(m, dict) and "content" in m
        )

        # NER extraction first (deterministic, UP14)
        ner_entities = self.ner.extract(conv_text)
        entity_ids = self.ner.to_entity_ids(ner_entities)

        # Choose prompt
        prompt = FLUSH_DISTILL_PROMPT if flush_mode else DISTILL_PROMPT
        today = __import__("datetime").date.today().isoformat()

        result = await self.router.call(
            task="flush_distill" if flush_mode else "bee_distill",
            system=prompt.format(
                conversation=conv_text,
                pre_extracted_entities=json.dumps([
                    {"text": e.text, "label": e.label, "confidence": e.confidence}
                    for e in ner_entities
                ]),
                today=today,
            ),
            messages=[{"role": "user", "content": "Extract observations."}],
            max_tokens=2000,
        )

        try:
            raw_text = result.content[0].text if hasattr(result, "content") else str(result)
            raw_obs = json.loads(raw_text.strip().strip("`").strip("json").strip())
        except (json.JSONDecodeError, AttributeError, IndexError):
            return []

        saved_ids = []
        for obs_data in raw_obs:
            emb = self.obs.embedding_cache.embed(obs_data.get("content", ""))
            merged_entities = list(set(obs_data.get("entities", []) + entity_ids))

            # Conflict check (UP19 + UP23)
            conflict = None
            if conflict_resolver:
                conflict = await conflict_resolver.check(
                    agent_id, user_id, emb, obs_data
                )
                if conflict.action.value == "NOOP":
                    continue
                if conflict.action.value == "UPDATE" and conflict.existing_id:
                    self.obs.db.table("observations").update({
                        "content": obs_data["content"],
                        "decay_score": 1.0,
                        "last_accessed": __import__("datetime").datetime.now(
                            __import__("datetime").timezone.utc).isoformat(),
                    }).eq("id", conflict.existing_id).execute()
                    continue

            obs = Observation(
                agent_id=agent_id,
                user_id=user_id,
                content=obs_data.get("content", ""),
                obs_type=ObservationType(obs_data.get("obs_type", "fact")),
                entities=merged_entities,
                importance=obs_data.get("importance", 5),
                emotional_valence=EmotionalValence(
                    obs_data.get("emotional_valence", "neutral")),
                emotional_intensity=obs_data.get("emotional_intensity", 0),
                event_time=obs_data.get("event_time"),
                source_session=session_id,
                embedding=emb,
            )
            new_id = await self.obs.save(obs, conflict)
            saved_ids.append(new_id)

        return saved_ids
