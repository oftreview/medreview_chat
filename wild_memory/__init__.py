"""
🌿 Wild Memory — Biomimetic Memory Framework for AI Agents

Created by Raphael Romie (Brazil)
https://youtube.com/@raphaelromie

Inspired by 6 animals with extraordinary memory:
  🐟 Salmon  — Identity (who I am)
  🐝 Bee     — Distillation (what matters)
  🐘 Elephant — Retrieval (the right thing, at the right time)
  🐬 Dolphin  — Connection (who relates to whom)
  🐜 Ant      — Forgetting (what to release)
  🦎 Chameleon — Adaptation (how to improve)

Usage:
    from wild_memory import WildMemory

    memory = WildMemory.from_config("wild_memory.yaml")
    reply = await memory.process_message(
        agent_id="my_agent",
        user_id="user_123",
        message="Hello!",
        session_id="session_abc"
    )
"""

__version__ = "3.0.0"
__author__ = "Raphael Romie"
__license__ = "MIT"
__all__ = ["WildMemory", "WildMemoryConfig"]

from wild_memory.config import WildMemoryConfig
from wild_memory.orchestrator import WildMemory
