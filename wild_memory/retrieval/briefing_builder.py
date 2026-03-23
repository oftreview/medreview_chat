"""
🐘 Elephant — Briefing Builder
Assembles a structured briefing from observations.
Template-based (zero LLM), every line has obs_id for traceability.
"""
from __future__ import annotations


class BriefingBuilder:
    def build(self, observations: list[dict], insights: list[dict] = None,
              entity_context: dict = None, procedure: dict = None,
              feedback: dict = None) -> tuple[str, list[str]]:
        """Build structured briefing. Returns (text, used_obs_ids)."""
        used_ids = []
        sections = []

        # Group observations by type
        by_type = {}
        for o in observations:
            t = o.get("obs_type", "fact")
            by_type.setdefault(t, []).append(o)

        type_labels = {
            "fact": "PROFILE", "preference": "PROFILE",
            "decision": "ACTIVE DECISIONS", "goal": "GOALS",
            "correction": "CORRECTIONS", "feedback": "FEEDBACK",
        }

        for obs_type, label in type_labels.items():
            items = by_type.get(obs_type, [])
            if not items:
                continue
            lines = []
            for o in items:
                oid = o.get("id", "?")[:8]
                lines.append(f"- {o['content']} [obs:{oid}, imp:{o.get('importance', 5)}]")
                used_ids.append(o.get("id", ""))
            sections.append(f"### {label}\n" + "\n".join(lines))

        # Emotional context
        emotional = [o for o in observations if o.get("emotional_intensity", 0) >= 2]
        if emotional:
            lines = []
            for o in emotional:
                lines.append(
                    f"- {o.get('emotional_valence', 'neutral')}: "
                    f"{o['content']} [obs:{o.get('id', '?')[:8]}, intensity:{o.get('emotional_intensity', 0)}]"
                )
            sections.append("### EMOTIONAL CONTEXT\n" + "\n".join(lines))

        # Insights
        if insights:
            lines = []
            for i in insights:
                lines.append(f"- {i['content']} [ref:{i.get('id', '?')[:8]}]")
                used_ids.append(i.get("id", ""))
            sections.append("### APPLICABLE INSIGHTS\n" + "\n".join(lines))

        n = len(set(used_ids))
        header = f"## LEAD BRIEFING [{n} sources]"
        briefing = header + "\n\n" + "\n\n".join(sections) if sections else header + "\n\nNo prior context available."
        return briefing, list(set(uid for uid in used_ids if uid))
