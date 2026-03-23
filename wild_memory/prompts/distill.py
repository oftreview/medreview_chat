"""Prompts for 🐝 Bee Distiller."""

DISTILL_PROMPT = """Analyze the conversation below and extract OBSERVATIONS.
Each observation must be:
- A single unit of information
- Self-descriptive (makes sense without additional context)
- Classified by type: decision | preference | fact | insight | correction | goal | feedback
- With list of entities mentioned
- With importance score (1-10)
- With TTL in days (decision:180, preference:90, fact:365, goal:30, correction:365, feedback:60)
- With emotional analysis: emotional_valence (positive|negative|neutral|urgent), emotional_intensity (0-5)
- With event_time if identifiable (ISO 8601, calculate from today: {today})

Pre-extracted entities (NER): {pre_extracted_entities}

Return ONLY a JSON array. Example:
[{{"content": "Lead decided to take ENARE exam", "obs_type": "decision", "entities": ["exam_enare"], "importance": 8, "ttl_days": 180, "emotional_valence": "positive", "emotional_intensity": 2, "event_time": null}}]

CONVERSATION:
{conversation}"""

FLUSH_DISTILL_PROMPT = """ATTENTION: The messages below will be PERMANENTLY discarded after this extraction.
Extract EVERYTHING of value. This is the last chance to save information.

Extract in 5 categories:
1. DECISIONS made (what and why)
2. STATE CHANGES (configured, installed, activated)
3. LESSONS (what worked, what didn't)
4. BLOCKERS (waiting for input or action)
5. KEY FACTS (about projects, people, systems)

Pre-extracted entities (NER): {pre_extracted_entities}
Today: {today}

Return ONLY a JSON array with all observations.
When in doubt, EXTRACT. Better one extra observation than lost information.

CONVERSATION (will be discarded after extraction):
{conversation}"""
