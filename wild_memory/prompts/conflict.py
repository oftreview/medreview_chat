"""Prompt for 🐜 Ant Conflict Resolution."""

CONFLICT_PROMPT = """You are a memory conflict classifier.
Given a NEW observation and EXISTING similar observations, classify the action:

- ADD: new complementary info, no conflict
- UPDATE: same info with more detail (enrich existing)
- SUPERSEDE: new info CONTRADICTS existing (invalidate old)
- NOOP: info already recorded, no additional value

NEW OBSERVATION:
{new_observation}

EXISTING SIMILAR OBSERVATIONS:
{existing_observations}

Return ONLY JSON:
{{"action": "ADD|UPDATE|SUPERSEDE|NOOP", "existing_id": "id or null", "reason": "short explanation"}}"""
