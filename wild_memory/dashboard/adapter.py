"""
Wild Memory Dashboard — Adapter Base Class

The adapter is the bridge between Wild Memory's dashboard and the host
application. Each client implements a subclass that tells the dashboard
how to access Supabase, where the config files live, and how to get
live metrics from the running shadow/context/lifecycle instances.

Usage:
    from wild_memory.dashboard.adapter import WildMemoryAdapter

    class MyAdapter(WildMemoryAdapter):
        def get_supabase_client(self):
            from myapp.db import supabase
            return supabase

        def get_agent_id(self):
            return "my-sales-agent"
        ...

    # Then pass to register_dashboard:
    from wild_memory.dashboard import register_dashboard
    register_dashboard(app, adapter=MyAdapter())
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional


class WildMemoryAdapter:
    """
    Base adapter. Override methods to connect Wild Memory Dashboard
    to your application's data layer and runtime instances.

    All methods have safe defaults — the dashboard degrades gracefully
    if a method is not implemented (shows "not configured" in the UI).
    """

    # ── Database ─────────────────────────────────────────────────

    def get_supabase_client(self) -> Any:
        """
        Return the Supabase client instance used by your application.
        This is the primary data source for the dashboard.

        Returns:
            supabase.Client or None
        """
        return None

    # ── Identity ─────────────────────────────────────────────────

    def get_agent_id(self) -> str:
        """Return the agent_id used in observations, feedback, etc."""
        return os.getenv("WILD_MEMORY_AGENT_ID", "default")

    def get_imprint_path(self) -> str:
        """Path to the imprint.yaml file (agent identity)."""
        return str(Path("memory") / "imprint.yaml")

    def get_config_path(self) -> str:
        """Path to wild_memory.yaml (framework configuration)."""
        return "wild_memory.yaml"

    def get_domain_config(self) -> Optional[dict]:
        """
        Return the domain NER entities config (if any).
        Format: {"EXAM": ["enare", "usp", ...], "PRODUCT": [...], ...}
        """
        return None

    # ── Runtime Instances (for live metrics) ─────────────────────

    def get_shadow_instance(self) -> Any:
        """
        Return the ShadowObserver singleton for live metrics.
        Expected interface: .get_status() -> dict
        """
        return None

    def get_context_instance(self) -> Any:
        """
        Return the ContextInjector singleton for live metrics.
        Expected interface: .get_status() -> dict
        """
        return None

    def get_lifecycle_instance(self) -> Any:
        """
        Return the LifecycleManager singleton for live metrics.
        Expected interface: .get_status() -> dict
        """
        return None

    def get_scheduler_status(self) -> Optional[dict]:
        """
        Return scheduler status dict, or None if not configured.
        Expected keys: enabled, running, next_maintenance_run, schedule
        """
        return None

    # ── Auth (optional) ──────────────────────────────────────────

    def check_dashboard_access(self, request) -> bool:
        """
        Return True if the current request is allowed to view the dashboard.
        Override to add authentication (e.g., check session, API key, etc.).

        By default, allows all access (suitable for internal dashboards).
        """
        return True

    def get_api_auth_header(self) -> Optional[str]:
        """
        Return the expected Authorization header value for API endpoints.
        If None, API endpoints are unprotected (default).
        """
        return None

    # ── Env Vars ─────────────────────────────────────────────────

    def get_env_status(self) -> dict:
        """
        Return status of all relevant environment variables.
        Used by the Setup page to validate configuration.
        """
        return {
            "WILD_MEMORY_SHADOW": {
                "set": bool(os.getenv("WILD_MEMORY_SHADOW")),
                "value": os.getenv("WILD_MEMORY_SHADOW", ""),
                "description": "Enables shadow mode (observation + lifecycle)",
            },
            "WILD_MEMORY_CONTEXT": {
                "set": bool(os.getenv("WILD_MEMORY_CONTEXT")),
                "value": os.getenv("WILD_MEMORY_CONTEXT", ""),
                "description": "Enables context injection into LLM prompts",
            },
            "OPENAI_API_KEY": {
                "set": bool(os.getenv("OPENAI_API_KEY")),
                "value": "***" if os.getenv("OPENAI_API_KEY") else "",
                "description": "OpenAI API key for embeddings",
            },
            "SUPABASE_URL": {
                "set": bool(os.getenv("SUPABASE_URL")),
                "value": os.getenv("SUPABASE_URL", "")[:40] + "..." if os.getenv("SUPABASE_URL") else "",
                "description": "Supabase project URL",
            },
            "SUPABASE_KEY": {
                "set": bool(os.getenv("SUPABASE_KEY")),
                "value": "***" if os.getenv("SUPABASE_KEY") else "",
                "description": "Supabase service role key",
            },
        }


class AutoDetectAdapter(WildMemoryAdapter):
    """
    Adapter that auto-detects common patterns in the host application.
    Tries standard import paths and env vars before falling back to defaults.

    Use this if you don't want to write a custom adapter — it covers
    ~80% of Flask + Supabase setups out of the box.
    """

    def get_supabase_client(self) -> Any:
        # Try common Supabase import patterns
        for module_path, attr in [
            ("src.core.database", "get_client"),
            ("app.database", "get_client"),
            ("database", "get_client"),
            ("db", "supabase"),
        ]:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                client_or_fn = getattr(mod, attr, None)
                if callable(client_or_fn):
                    return client_or_fn()
                return client_or_fn
            except (ImportError, AttributeError):
                continue

        # Try creating from env vars
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if url and key:
            try:
                from supabase import create_client
                return create_client(url, key)
            except ImportError:
                pass

        return None

    def get_shadow_instance(self) -> Any:
        try:
            from src.core.wild_memory_shadow import shadow
            return shadow
        except ImportError:
            return None

    def get_context_instance(self) -> Any:
        try:
            from src.core.wild_memory_context import context_injector
            return context_injector
        except ImportError:
            return None

    def get_lifecycle_instance(self) -> Any:
        try:
            from src.core.wild_memory_lifecycle import lifecycle
            return lifecycle
        except ImportError:
            return None

    def get_scheduler_status(self) -> Optional[dict]:
        try:
            from src.core.scheduler import get_status
            return get_status()
        except ImportError:
            return None
