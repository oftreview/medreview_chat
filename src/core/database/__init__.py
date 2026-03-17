"""
src/core/database — Módulo de persistência (Supabase).
Re-exports para backward compatibility.
"""
from .client import _get_client, get_connection_status, health_check, is_enabled
from .conversations import save_message, save_raw_incoming, load_conversation_history
from .conversations import save_message_legacy, load_messages_legacy
from .leads import (upsert_lead, update_lead_status, save_lead_metadata, get_lead_metadata,
                    generate_session_id, create_session, update_session_status)
from .escalations import save_escalation, resolve_escalation_record, list_escalations
from .corrections import (save_correction, load_corrections, increment_reincidence,
                          auto_archive_corrections, correction_analytics,
                          _load_corrections_json, _save_corrections_json, _sync_json_to_supabase)
from .analytics import (analytics_funnel, analytics_time_per_stage,
                        analytics_keywords, analytics_conversation_quality)

__all__ = [
    # client
    "_get_client",
    "get_connection_status",
    "health_check",
    "is_enabled",
    # conversations
    "save_message",
    "save_raw_incoming",
    "load_conversation_history",
    "save_message_legacy",
    "load_messages_legacy",
    # leads
    "upsert_lead",
    "update_lead_status",
    "save_lead_metadata",
    "get_lead_metadata",
    "generate_session_id",
    "create_session",
    "update_session_status",
    # escalations
    "save_escalation",
    "resolve_escalation_record",
    "list_escalations",
    # corrections
    "save_correction",
    "load_corrections",
    "increment_reincidence",
    "auto_archive_corrections",
    "correction_analytics",
    "_load_corrections_json",
    "_save_corrections_json",
    "_sync_json_to_supabase",
    # analytics
    "analytics_funnel",
    "analytics_time_per_stage",
    "analytics_keywords",
    "analytics_conversation_quality",
]
