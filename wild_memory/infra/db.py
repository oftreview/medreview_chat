"""
Wild Memory — Database client factory.
"""
from __future__ import annotations
from wild_memory.config import SupabaseConfig


def create_supabase_client(config: SupabaseConfig):
    """Create a Supabase client from config."""
    from supabase import create_client
    return create_client(config.url, config.key)
