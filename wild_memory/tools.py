"""
Wild Memory — Tool Definitions
Memory tools that the agent can use during conversation.
"""

RECALL_MEMORY_TOOL = {
    "name": "recall_memory",
    "description": (
        "Search your long-term memory for relevant information. "
        "Use when you need context not available in the current conversation: "
        "history with this lead, past decisions, preferences, or entity details."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What you want to remember",
            },
            "search_type": {
                "type": "string",
                "enum": ["semantic", "entity", "temporal"],
                "description": "Type of search: semantic (meaning), entity (specific person/thing), temporal (recent events)",
            },
            "entity_id": {
                "type": "string",
                "description": "Entity ID for entity search (e.g., 'person_joao')",
            },
        },
        "required": ["query", "search_type"],
    },
}

SAVE_OBSERVATION_TOOL = {
    "name": "save_observation",
    "description": (
        "Save an important fact to long-term memory IMMEDIATELY. "
        "Use when the lead: makes a decision, reveals critical info, "
        "changes their mind, or expresses a strong objection. "
        "Do NOT use for trivial or repeated information."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The fact to save (self-descriptive, standalone)",
            },
            "obs_type": {
                "type": "string",
                "enum": ["decision", "preference", "fact", "goal", "correction", "feedback"],
                "description": "Type of observation",
            },
            "importance": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "How important is this (1=trivial, 10=critical)",
            },
            "event_time": {
                "type": "string",
                "description": "When did this happen (ISO 8601), if different from now",
            },
        },
        "required": ["content", "obs_type", "importance"],
    },
}

UPDATE_ENTITY_TOOL = {
    "name": "update_entity",
    "description": (
        "Update information about a known entity (person, project, product). "
        "Use when the lead corrects or updates something: "
        "'My name is actually João', 'I changed specialty', etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "ID of the entity to update",
            },
            "attribute": {
                "type": "string",
                "description": "Which attribute to update",
            },
            "new_value": {
                "type": "string",
                "description": "New value for the attribute",
            },
        },
        "required": ["entity_id", "attribute", "new_value"],
    },
}

MEMORY_TOOLS = [
    RECALL_MEMORY_TOOL,
    SAVE_OBSERVATION_TOOL,
    UPDATE_ENTITY_TOOL,
]
