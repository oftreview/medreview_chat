"""Prompts for 🐜 Ant Reflection Engine."""

REFLECT_PROMPT = """You are the reflection module for agent {agent_id}.
Analyze the observations below (last 48h) and:

1. PATTERNS: Identify recurring behavior, preference, or decision patterns.
2. CONFLICTS: Identify contradictory observations. For each, indicate which should prevail.
3. ACTIONABLE INSIGHTS: Generate insights the agent can use proactively.

Return JSON:
{{"patterns": [{{"content": "...", "importance": N}}],
  "conflicts": [{{"old_id": "...", "new_id": "...", "resolution": "..."}}],
  "insights": [{{"content": "...", "importance": N}}]}}

OBSERVATIONS:
{observations_json}"""
