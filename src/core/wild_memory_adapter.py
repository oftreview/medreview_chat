"""
Closi-AI Adapter for Wild Memory Dashboard.

Connects the portable Wild Memory Dashboard to Closi-AI's specific
infrastructure: Supabase client, shadow/context/lifecycle singletons,
and the internal APScheduler.

Usage (in src/app.py):
    from src.core.wild_memory_adapter import ClosiAdapter
    from wild_memory.dashboard import register_dashboard
    register_dashboard(app, adapter=ClosiAdapter())
"""

import os
from wild_memory.dashboard.adapter import WildMemoryAdapter


class ClosiAdapter(WildMemoryAdapter):
    """
    Adapter that wires Wild Memory Dashboard to Closi-AI internals.
    All methods are lazy — they import on first call to avoid circular imports.
    """

    # ── Database ──────────────────────────────────────────────────

    def get_supabase_client(self):
        try:
            from src.core.database.client import _get_client
            return _get_client()
        except Exception:
            return None

    # ── Identity ──────────────────────────────────────────────────

    def get_agent_id(self) -> str:
        return os.getenv("WILD_MEMORY_AGENT_ID", "closi-sales")

    def get_imprint_path(self) -> str:
        return os.path.join("memory", "imprint.yaml")

    def get_config_path(self) -> str:
        return "wild_memory.yaml"

    def get_domain_config(self):
        try:
            from wild_memory.medreview_domain import MEDREVIEW_DOMAIN_ENTITIES
            return MEDREVIEW_DOMAIN_ENTITIES
        except Exception:
            return None

    # ── Runtime Instances ─────────────────────────────────────────

    def get_shadow_instance(self):
        try:
            from src.core.wild_memory_shadow import shadow
            return shadow
        except Exception:
            return None

    def get_context_instance(self):
        try:
            from src.core.wild_memory_context import context_injector
            return context_injector
        except Exception:
            return None

    def get_lifecycle_instance(self):
        try:
            from src.core.wild_memory_lifecycle import lifecycle
            return lifecycle
        except Exception:
            return None

    def get_scheduler_status(self):
        try:
            from src.core.scheduler import get_status
            return get_status()
        except Exception:
            return None

    # ── Auth ──────────────────────────────────────────────────────

    def check_dashboard_access(self, request) -> bool:
        """
        For now, allow all access (internal dashboard).
        Override this to add authentication if needed.
        """
        return True

    def get_api_auth_header(self):
        """Use API_SECRET_TOKEN if set."""
        token = os.getenv("API_SECRET_TOKEN")
        if token:
            return f"Bearer {token}"
        return None
