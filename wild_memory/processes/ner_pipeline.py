"""
🐝 Bee (precision) — NER Pipeline
Deterministic named entity recognition using spaCy + custom rules.
Runs BEFORE LLM distillation for higher precision (UP14).
"""
from __future__ import annotations
import re
from typing import Optional
from wild_memory.models import NEREntity


class NERPipeline:
    """Hybrid NER: spaCy base + domain-specific rules."""

    # Override these for your domain
    DOMAIN_ENTITIES: dict[str, set[str]] = {
        "EXAM": set(),
        "PRODUCT": set(),
        "SPECIALTY": set(),
    }

    def __init__(self):
        self._nlp = None

    def _get_nlp(self):
        if self._nlp is None:
            try:
                import spacy
                self._nlp = spacy.load("pt_core_news_sm")
            except (ImportError, OSError):
                self._nlp = "unavailable"
        return self._nlp

    def extract(self, text: str) -> list[NEREntity]:
        """Extract entities with hybrid pipeline."""
        entities = []

        # spaCy NER (if available)
        nlp = self._get_nlp()
        if nlp != "unavailable":
            doc = nlp(text)
            label_map = {"PER": "PERSON", "ORG": "ORGANIZATION", "LOC": "LOCATION", "DATE": "DATE", "MONEY": "MONEY"}
            for ent in doc.ents:
                mapped = label_map.get(ent.label_)
                if mapped:
                    entities.append(NEREntity(
                        text=ent.text, label=mapped,
                        confidence=0.85, start=ent.start_char, end=ent.end_char,
                    ))

        # Domain-specific rules
        text_lower = text.lower()
        for label, terms in self.DOMAIN_ENTITIES.items():
            for term in terms:
                if term in text_lower:
                    idx = text_lower.index(term)
                    entities.append(NEREntity(
                        text=term.upper() if len(term) <= 5 else term.title(),
                        label=label, confidence=0.95,
                        start=idx, end=idx + len(term),
                    ))

        return self._deduplicate(entities)

    def to_entity_ids(self, entities: list[NEREntity]) -> list[str]:
        """Convert NER entities to entity IDs for observations."""
        ids = set()
        for e in entities:
            slug = re.sub(r"[^a-z0-9]+", "_", e.text.lower()).strip("_")
            ids.add(f"{e.label.lower()}_{slug}")
        return list(ids)

    @classmethod
    def with_domain(cls, domain_entities: dict[str, list[str]]) -> "NERPipeline":
        """Create NER with custom domain entities."""
        instance = cls()
        for label, terms in domain_entities.items():
            instance.DOMAIN_ENTITIES[label.upper()] = set(t.lower() for t in terms)
        return instance

    def _deduplicate(self, entities: list[NEREntity]) -> list[NEREntity]:
        seen = set()
        unique = []
        for e in entities:
            key = (e.text.lower(), e.label)
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique
