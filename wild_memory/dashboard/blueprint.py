"""
Wild Memory Dashboard — Flask Blueprint

All routes for the Wild Memory dashboard: page rendering + JSON API.
Self-contained — no dependencies on the host application except through
the Adapter interface.

Routes:
  Pages:  /wild-memory, /wild-memory/salmon, /wild-memory/bee, ...
  API:    /wild-memory/api/status, /wild-memory/api/observations, ...
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps
from typing import Any, Optional

from flask import (
    Blueprint, render_template, jsonify, request, abort, current_app
)

logger = logging.getLogger(__name__)

# Template folder is relative to this file
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

bp = Blueprint(
    "wild_memory_dashboard",
    __name__,
    url_prefix="/wild-memory",
    template_folder=_TEMPLATE_DIR,
    static_folder=_STATIC_DIR,
    static_url_path="static",
)


# ════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════

def _get_adapter():
    """Retrieve the adapter stored on the app by register_dashboard()."""
    return current_app.config.get("WILD_MEMORY_ADAPTER")


def _get_supabase():
    """Get Supabase client from adapter, or None."""
    adapter = _get_adapter()
    if adapter:
        try:
            return adapter.get_supabase_client()
        except Exception as e:
            logger.warning(f"[WM Dashboard] Supabase client error: {e}")
    return None


def _check_access(f):
    """Decorator: check dashboard access via adapter."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        adapter = _get_adapter()
        if adapter and not adapter.check_dashboard_access(request):
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def _safe_query(table: str, query_fn, default=None):
    """Execute a Supabase query safely, return default on error."""
    sb = _get_supabase()
    if not sb:
        return default if default is not None else []
    try:
        return query_fn(sb)
    except Exception as e:
        logger.warning(f"[WM Dashboard] Query error ({table}): {e}")
        return default if default is not None else []


def _safe_rpc(fn_name: str, params: dict, default=None):
    """Execute a Supabase RPC safely."""
    sb = _get_supabase()
    if not sb:
        return default
    try:
        result = sb.rpc(fn_name, params).execute()
        return result.data
    except Exception as e:
        logger.warning(f"[WM Dashboard] RPC error ({fn_name}): {e}")
        return default


# ════════════════════════════════════════════════════════════════
# Page Routes (render HTML)
# ════════════════════════════════════════════════════════════════

@bp.route("")
@bp.route("/")
@_check_access
def overview():
    return render_template("overview.html", active_page="overview")


@bp.route("/salmon")
@_check_access
def salmon():
    return render_template("salmon.html", active_page="salmon")


@bp.route("/bee")
@_check_access
def bee():
    return render_template("bee.html", active_page="bee")


@bp.route("/elephant")
@_check_access
def elephant():
    return render_template("elephant.html", active_page="elephant")


@bp.route("/dolphin")
@_check_access
def dolphin():
    return render_template("dolphin.html", active_page="dolphin")


@bp.route("/ant")
@_check_access
def ant():
    return render_template("ant.html", active_page="ant")


@bp.route("/chameleon")
@_check_access
def chameleon():
    return render_template("chameleon.html", active_page="chameleon")


@bp.route("/setup")
@_check_access
def setup():
    return render_template("setup.html", active_page="setup")


# ════════════════════════════════════════════════════════════════
# API Routes (return JSON)
# ════════════════════════════════════════════════════════════════

# ── Status ───────────────────────────────────────────────────

@bp.route("/api/status")
@_check_access
def api_status():
    """Complete status of all Wild Memory layers."""
    adapter = _get_adapter()
    status = {
        "wild_memory_dashboard": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Shadow metrics
    shadow = adapter.get_shadow_instance() if adapter else None
    status["shadow"] = shadow.get_status() if shadow and hasattr(shadow, "get_status") else {"enabled": False}

    # Context injection metrics
    context = adapter.get_context_instance() if adapter else None
    status["context_injection"] = context.get_status() if context and hasattr(context, "get_status") else {"enabled": False}

    # Lifecycle metrics
    lifecycle = adapter.get_lifecycle_instance() if adapter else None
    status["lifecycle"] = lifecycle.get_status() if lifecycle and hasattr(lifecycle, "get_status") else {"enabled": False}

    # Scheduler
    scheduler = adapter.get_scheduler_status() if adapter else None
    status["scheduler"] = scheduler or {"enabled": False}

    # Database counts
    sb = _get_supabase()
    if sb:
        try:
            obs = sb.table("observations").select("id", count="exact").execute()
            status["total_observations"] = obs.count or 0
        except Exception:
            status["total_observations"] = 0
        try:
            ent = sb.table("entity_nodes").select("id", count="exact").execute()
            status["total_entities"] = ent.count or 0
        except Exception:
            status["total_entities"] = 0
        try:
            fb = sb.table("feedback_signals").select("id", count="exact").execute()
            status["total_feedback"] = fb.count or 0
        except Exception:
            status["total_feedback"] = 0
        try:
            ref = sb.table("reflections").select("id", count="exact").execute()
            status["total_reflections"] = ref.count or 0
        except Exception:
            status["total_reflections"] = 0
    else:
        status["total_observations"] = 0
        status["total_entities"] = 0
        status["total_feedback"] = 0
        status["total_reflections"] = 0

    return jsonify(status)


# ── Observations (Bee) ───────────────────────────────────────

@bp.route("/api/observations")
@_check_access
def api_observations():
    """List observations with filters."""
    obs_type = request.args.get("type")
    status_filter = request.args.get("status", "active")
    user_id = request.args.get("user_id")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    def query(sb):
        q = sb.table("observations").select(
            "id, content, obs_type, entities, importance, decay_score, "
            "status, emotional_valence, emotional_intensity, "
            "source_session, created_at, last_accessed"
        )
        if obs_type:
            q = q.eq("obs_type", obs_type)
        if status_filter:
            q = q.eq("status", status_filter)
        if user_id:
            q = q.eq("user_id", user_id)
        q = q.order("created_at", desc=True).range(offset, offset + limit - 1)
        return q.execute().data

    data = _safe_query("observations", query)
    return jsonify({"observations": data, "count": len(data)})


@bp.route("/api/observations/<obs_id>")
@_check_access
def api_observation_detail(obs_id):
    """Single observation detail."""
    def query(sb):
        return sb.table("observations").select("*").eq("id", obs_id).execute().data

    data = _safe_query("observations", query)
    if not data:
        return jsonify({"error": "Not found"}), 404
    return jsonify(data[0])


@bp.route("/api/observations/stats")
@_check_access
def api_observations_stats():
    """Observation statistics by type and status."""
    def query_by_type(sb):
        return sb.rpc("get_observations_by_type", {}).execute().data

    # Fallback: query directly
    def query_counts(sb):
        result = {}
        for obs_type in ["decision", "preference", "fact", "goal", "correction", "feedback", "insight"]:
            r = sb.table("observations").select("id", count="exact").eq("obs_type", obs_type).eq("status", "active").execute()
            result[obs_type] = r.count or 0
        return result

    # Try RPC first, fallback to manual counts
    stats = _safe_rpc("get_observations_by_type", {})
    if stats is None:
        stats = _safe_query("observations", query_counts, default={})

    # Status counts
    status_counts = {}
    for s in ["active", "stale", "archived"]:
        def q(sb, st=s):
            return sb.table("observations").select("id", count="exact").eq("status", st).execute().count or 0
        status_counts[s] = _safe_query("observations", q, default=0)

    return jsonify({"by_type": stats, "by_status": status_counts})


# ── Entities (Dolphin) ───────────────────────────────────────

@bp.route("/api/entities")
@_check_access
def api_entities():
    """List entity nodes with optional type filter."""
    entity_type = request.args.get("type")
    limit = min(int(request.args.get("limit", 100)), 500)

    def query(sb):
        q = sb.table("entity_nodes").select("*")
        if entity_type:
            q = q.eq("entity_type", entity_type)
        q = q.order("updated_at", desc=True).limit(limit)
        return q.execute().data

    return jsonify({"entities": _safe_query("entity_nodes", query)})


@bp.route("/api/entities/<entity_id>")
@_check_access
def api_entity_detail(entity_id):
    """Entity detail with edges and related observations."""
    def query_node(sb):
        return sb.table("entity_nodes").select("*").eq("id", entity_id).execute().data

    def query_edges(sb):
        edges_out = sb.table("entity_edges").select("*").eq("subject_id", entity_id).execute().data or []
        edges_in = sb.table("entity_edges").select("*").eq("object_id", entity_id).execute().data or []
        return edges_out + edges_in

    def query_observations(sb):
        return sb.table("observations").select(
            "id, content, obs_type, entities, importance, created_at"
        ).contains("entities", [entity_id]).eq("status", "active").order(
            "created_at", desc=True
        ).limit(20).execute().data

    node = _safe_query("entity_nodes", query_node)
    if not node:
        return jsonify({"error": "Not found"}), 404

    return jsonify({
        "entity": node[0],
        "edges": _safe_query("entity_edges", query_edges),
        "observations": _safe_query("observations", query_observations),
    })


@bp.route("/api/edges")
@_check_access
def api_edges():
    """List entity edges."""
    limit = min(int(request.args.get("limit", 200)), 500)

    def query(sb):
        return sb.table("entity_edges").select("*").order("created_at", desc=True).limit(limit).execute().data

    return jsonify({"edges": _safe_query("entity_edges", query)})


# ── Reflections (Ant) ────────────────────────────────────────

@bp.route("/api/reflections")
@_check_access
def api_reflections():
    """List reflections."""
    user_id = request.args.get("user_id")
    limit = min(int(request.args.get("limit", 50)), 200)

    def query(sb):
        q = sb.table("reflections").select(
            "id, agent_id, user_id, reflection_type, content, importance, created_at"
        )
        if user_id:
            q = q.eq("user_id", user_id)
        q = q.order("created_at", desc=True).limit(limit)
        return q.execute().data

    return jsonify({"reflections": _safe_query("reflections", query)})


# ── Feedback (Chameleon) ─────────────────────────────────────

@bp.route("/api/feedback")
@_check_access
def api_feedback():
    """List feedback signals with filters."""
    signal_type = request.args.get("type")
    days = int(request.args.get("days", 30))
    limit = min(int(request.args.get("limit", 50)), 200)

    def query(sb):
        q = sb.table("feedback_signals").select("*")
        if signal_type:
            q = q.eq("signal_type", signal_type)
        q = q.order("created_at", desc=True).limit(limit)
        return q.execute().data

    return jsonify({"feedback": _safe_query("feedback_signals", query)})


@bp.route("/api/feedback/summary")
@_check_access
def api_feedback_summary():
    """Feedback summary via RPC."""
    adapter = _get_adapter()
    agent_id = adapter.get_agent_id() if adapter else "default"
    days = int(request.args.get("days", 7))

    data = _safe_rpc("get_feedback_summary", {"p_agent_id": agent_id, "p_days": days})
    return jsonify({"summary": data or []})


# ── Citations (Elephant) ─────────────────────────────────────

@bp.route("/api/citations")
@_check_access
def api_citations():
    """List citation trails."""
    session_id = request.args.get("session_id")
    limit = min(int(request.args.get("limit", 50)), 200)

    def query(sb):
        q = sb.table("citation_trails").select("*")
        if session_id:
            q = q.eq("session_id", session_id)
        q = q.order("created_at", desc=True).limit(limit)
        return q.execute().data

    return jsonify({"citations": _safe_query("citation_trails", query)})


# ── Semantic Cache (Elephant) ────────────────────────────────

@bp.route("/api/cache")
@_check_access
def api_cache():
    """Semantic cache statistics."""
    def query(sb):
        total = sb.table("semantic_cache").select("id", count="exact").execute().count or 0
        active = sb.table("semantic_cache").select("id", count="exact").gte(
            "expires_at", datetime.now(timezone.utc).isoformat()
        ).execute().count or 0
        hits = sb.table("semantic_cache").select("hit_count").execute().data or []
        total_hits = sum(r.get("hit_count", 0) for r in hits)
        return {"total_entries": total, "active_entries": active, "total_hits": total_hits}

    return jsonify(_safe_query("semantic_cache", query, default={
        "total_entries": 0, "active_entries": 0, "total_hits": 0
    }))


# ── Session Logs ─────────────────────────────────────────────

@bp.route("/api/sessions")
@_check_access
def api_sessions():
    """List active session logs."""
    limit = min(int(request.args.get("limit", 20)), 50)

    def query(sb):
        return sb.table("session_logs").select(
            "id, agent_id, user_id, session_id, token_count, created_at, expires_at"
        ).order("created_at", desc=True).limit(limit).execute().data

    return jsonify({"sessions": _safe_query("session_logs", query)})


# ── Decay Distribution (Ant) ────────────────────────────────

@bp.route("/api/decay-distribution")
@_check_access
def api_decay_distribution():
    """Histogram of decay scores for active observations."""
    def query(sb):
        data = sb.table("observations").select(
            "decay_score"
        ).eq("status", "active").execute().data or []

        # Build histogram buckets: 0.0-0.1, 0.1-0.2, ..., 0.9-1.0
        buckets = {f"{i/10:.1f}-{(i+1)/10:.1f}": 0 for i in range(10)}
        for row in data:
            score = row.get("decay_score", 0)
            bucket_idx = min(int(score * 10), 9)
            key = f"{bucket_idx/10:.1f}-{(bucket_idx+1)/10:.1f}"
            buckets[key] += 1
        return buckets

    return jsonify({"distribution": _safe_query("observations", query, default={})})


# ── Activity Feed ────────────────────────────────────────────

@bp.route("/api/activity")
@_check_access
def api_activity():
    """Unified activity feed — last 50 events from all tables."""
    events = []

    # Recent observations
    def q_obs(sb):
        return sb.table("observations").select(
            "id, content, obs_type, user_id, created_at"
        ).order("created_at", desc=True).limit(15).execute().data or []

    for obs in _safe_query("observations", q_obs):
        events.append({
            "type": "observation",
            "icon": "bee",
            "summary": f"[{obs.get('obs_type', '?')}] {(obs.get('content', '')[:80])}...",
            "user_id": obs.get("user_id", ""),
            "timestamp": obs.get("created_at", ""),
        })

    # Recent feedback
    def q_fb(sb):
        return sb.table("feedback_signals").select(
            "id, signal_type, reward_score, user_id, created_at"
        ).order("created_at", desc=True).limit(10).execute().data or []

    for fb in _safe_query("feedback_signals", q_fb):
        events.append({
            "type": "feedback",
            "icon": "chameleon",
            "summary": f"{fb.get('signal_type', '?')} (reward: {fb.get('reward_score', 0):.2f})",
            "user_id": fb.get("user_id", ""),
            "timestamp": fb.get("created_at", ""),
        })

    # Recent reflections
    def q_ref(sb):
        return sb.table("reflections").select(
            "id, reflection_type, content, user_id, created_at"
        ).order("created_at", desc=True).limit(5).execute().data or []

    for ref in _safe_query("reflections", q_ref):
        events.append({
            "type": "reflection",
            "icon": "ant",
            "summary": f"[{ref.get('reflection_type', '?')}] {(ref.get('content', '')[:80])}...",
            "user_id": ref.get("user_id", ""),
            "timestamp": ref.get("created_at", ""),
        })

    # Sort by timestamp descending
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return jsonify({"events": events[:50]})


# ── Imprint (Salmon) ────────────────────────────────────────

@bp.route("/api/imprint")
@_check_access
def api_imprint_get():
    """Read the current imprint.yaml."""
    adapter = _get_adapter()
    if not adapter:
        return jsonify({"error": "No adapter configured"}), 500

    try:
        import yaml
        path = adapter.get_imprint_path()
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return jsonify({"imprint": data, "path": path})
    except FileNotFoundError:
        return jsonify({"error": f"Imprint file not found", "path": adapter.get_imprint_path()}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/imprint", methods=["PUT"])
@_check_access
def api_imprint_save():
    """Save updated imprint.yaml."""
    adapter = _get_adapter()
    if not adapter:
        return jsonify({"error": "No adapter configured"}), 500

    try:
        import yaml
        data = request.get_json()
        path = adapter.get_imprint_path()

        if data and "imprint_yaml" in data:
            # Raw YAML string from the editor — validate then write directly
            raw_yaml = data["imprint_yaml"]
            parsed = yaml.safe_load(raw_yaml)  # validate syntax
            if not isinstance(parsed, dict):
                return jsonify({"error": "YAML inválido: deve ser um dicionário"}), 400
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw_yaml)
            return jsonify({"status": "saved", "path": path})

        if not data or "imprint" not in data:
            return jsonify({"error": "Missing 'imprint' or 'imprint_yaml' in body"}), 400

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data["imprint"], f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        return jsonify({"status": "saved", "path": path})
    except yaml.YAMLError as ye:
        return jsonify({"error": f"YAML inválido: {ye}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── NER Domain Categories (Salmon) ──────────────────────────

@bp.route("/api/ner")
@_check_access
def api_ner_get():
    """Return configured NER domain entity categories."""
    adapter = _get_adapter()
    if not adapter:
        return jsonify({"error": "No adapter configured"}), 500

    try:
        domain_config = adapter.get_domain_config()
        if domain_config:
            return jsonify({"categories": domain_config})
        else:
            return jsonify({"categories": None, "message": "No domain NER configured"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Maintenance (Manual Trigger) ─────────────────────────────

@bp.route("/api/maintenance", methods=["POST"])
@_check_access
def api_maintenance():
    """Trigger daily maintenance manually."""
    adapter = _get_adapter()
    lifecycle = adapter.get_lifecycle_instance() if adapter else None
    if not lifecycle or not hasattr(lifecycle, "run_daily_maintenance"):
        return jsonify({"error": "Lifecycle not available"}), 503

    try:
        results = lifecycle.run_daily_maintenance()
        return jsonify({"status": "completed", "results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Playground (Retrieval Simulation) ────────────────────────

@bp.route("/api/playground/retrieve")
@_check_access
def api_playground_retrieve():
    """Simulate a retrieval for a given query text."""
    query_text = request.args.get("query", "")
    user_id = request.args.get("user_id", "")
    if not query_text:
        return jsonify({"error": "Missing 'query' parameter"}), 400

    adapter = _get_adapter()
    agent_id = adapter.get_agent_id() if adapter else "default"

    # Generate embedding
    try:
        import openai
        client = openai.OpenAI()
        resp = client.embeddings.create(model="text-embedding-3-small", input=query_text)
        embedding = resp.data[0].embedding
    except Exception as e:
        return jsonify({"error": f"Embedding failed: {e}"}), 500

    # Call retrieve_observations RPC
    params = {
        "p_agent_id": agent_id,
        "p_user_id": user_id,
        "p_embedding": str(embedding),
        "p_entities": [],
        "p_search_query": query_text,
        "p_limit": 10,
        "p_min_decay": 0.2,
    }
    results = _safe_rpc("retrieve_observations", params, default=[])
    return jsonify({"query": query_text, "results": results or []})


# ── Health Check (Setup) ─────────────────────────────────────

@bp.route("/api/health-check")
@_check_access
def api_health_check():
    """Validate all connections and schema."""
    checks = {}

    # Supabase connection
    sb = _get_supabase()
    checks["supabase_connected"] = sb is not None

    # Required tables
    required_tables = [
        "observations", "entity_nodes", "entity_edges",
        "reflections", "feedback_signals", "procedures",
        "citation_trails", "session_logs", "semantic_cache",
        "agent_checkpoints", "agent_imprints",
    ]
    checks["tables"] = {}
    if sb:
        for table in required_tables:
            try:
                sb.table(table).select("id").limit(1).execute()
                checks["tables"][table] = True
            except Exception:
                checks["tables"][table] = False
    else:
        for table in required_tables:
            checks["tables"][table] = False

    # Required RPCs
    required_rpcs = [
        "retrieve_observations", "apply_daily_decay",
        "mark_stale_observations", "reinforce_observation",
    ]
    checks["rpcs"] = {}
    # We can't easily test RPCs without params, so just mark as "present" if tables work
    for rpc in required_rpcs:
        checks["rpcs"][rpc] = checks["supabase_connected"]

    # OpenAI API
    try:
        import openai
        client = openai.OpenAI()
        client.models.list()
        checks["openai_connected"] = True
    except Exception:
        checks["openai_connected"] = False

    # Env vars
    adapter = _get_adapter()
    checks["env_vars"] = adapter.get_env_status() if adapter else {}

    # Imprint file
    if adapter:
        checks["imprint_exists"] = Path(adapter.get_imprint_path()).exists()
        checks["config_exists"] = Path(adapter.get_config_path()).exists()
    else:
        checks["imprint_exists"] = False
        checks["config_exists"] = False

    # Domain NER
    checks["domain_configured"] = bool(adapter.get_domain_config()) if adapter else False

    # Overall health
    checks["healthy"] = (
        checks["supabase_connected"]
        and all(checks["tables"].values())
        and checks["openai_connected"]
    )

    return jsonify(checks)


# ── Users List (for filters) ────────────────────────────────

@bp.route("/api/users")
@_check_access
def api_users():
    """List distinct user_ids from observations."""
    def query(sb):
        # Get distinct user_ids with observation count
        data = sb.table("observations").select("user_id").eq("status", "active").execute().data or []
        user_counts = {}
        for row in data:
            uid = row.get("user_id", "")
            user_counts[uid] = user_counts.get(uid, 0) + 1
        return [{"user_id": uid, "observation_count": count} for uid, count in sorted(
            user_counts.items(), key=lambda x: x[1], reverse=True
        )]

    return jsonify({"users": _safe_query("observations", query)})


# ── Procedures (Chameleon) ───────────────────────────────────

@bp.route("/api/procedures")
@_check_access
def api_procedures():
    """List procedures with performance metrics."""
    def query(sb):
        return sb.table("procedures").select("*").order("updated_at", desc=True).execute().data

    return jsonify({"procedures": _safe_query("procedures", query)})
