-- ============================================
-- Wild Memory v3.0 — Complete Database Schema
-- Run against Supabase PostgreSQL
-- ============================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- 🐟 SALMON — Identity
-- ============================================

CREATE TABLE IF NOT EXISTS agent_imprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL,
    "values" JSONB NOT NULL DEFAULT '[]',
    constraints JSONB NOT NULL DEFAULT '[]',
    org_context JSONB NOT NULL DEFAULT '{}',
    tone_of_voice TEXT DEFAULT '',
    permissions JSONB NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    updated_by TEXT NOT NULL DEFAULT 'human',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- 🐝 BEE — Observations (Distilled Knowledge)
-- ============================================

CREATE TABLE IF NOT EXISTS observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    obs_type TEXT NOT NULL CHECK (obs_type IN (
        'decision', 'preference', 'fact', 'insight',
        'correction', 'goal', 'feedback'
    )),
    entities TEXT[] NOT NULL DEFAULT '{}',
    importance SMALLINT NOT NULL DEFAULT 5
        CHECK (importance BETWEEN 1 AND 10),
    decay_score REAL NOT NULL DEFAULT 1.0
        CHECK (decay_score BETWEEN 0.0 AND 1.0),
    ttl_days INTEGER NOT NULL DEFAULT 90,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'stale', 'archived', 'purged')),
    superseded_by UUID REFERENCES observations(id),
    source_session TEXT,
    embedding vector(1536),

    -- Emotional tagging
    emotional_valence TEXT DEFAULT 'neutral'
        CHECK (emotional_valence IN ('positive', 'negative', 'neutral', 'urgent')),
    emotional_intensity SMALLINT DEFAULT 0
        CHECK (emotional_intensity BETWEEN 0 AND 5),

    -- Privacy
    privacy_mode TEXT NOT NULL DEFAULT 'personal'
        CHECK (privacy_mode IN ('personal', 'pattern')),
    anonymized_user_hash TEXT,

    -- Frequency tracking
    topic_fingerprint TEXT,
    occurrence_count INTEGER DEFAULT 1,

    -- Bi-temporal (UP16)
    event_time TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    invalidated_by UUID REFERENCES observations(id),

    -- Full-text search (UP18)
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('portuguese', content), 'A')
        || setweight(to_tsvector('simple', array_to_string(entities, ' ')), 'B')
    ) STORED,

    created_at TIMESTAMPTZ DEFAULT now(),
    last_accessed TIMESTAMPTZ DEFAULT now()
);

-- Indexes for observations
CREATE INDEX IF NOT EXISTS idx_obs_agent_user ON observations(agent_id, user_id);
CREATE INDEX IF NOT EXISTS idx_obs_status ON observations(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_obs_entities ON observations USING GIN(entities);
CREATE INDEX IF NOT EXISTS idx_obs_type ON observations(obs_type);
CREATE INDEX IF NOT EXISTS idx_obs_embedding ON observations
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_obs_emotion ON observations(emotional_valence)
    WHERE emotional_intensity >= 3;
CREATE INDEX IF NOT EXISTS idx_obs_privacy ON observations(privacy_mode, user_id);
CREATE INDEX IF NOT EXISTS idx_obs_topic ON observations(topic_fingerprint)
    WHERE topic_fingerprint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_obs_event_time ON observations(event_time)
    WHERE event_time IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_obs_valid ON observations(invalidated_at)
    WHERE invalidated_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_obs_fts ON observations USING GIN(search_vector);

-- ============================================
-- 🐬 DOLPHIN — Entity Graph
-- ============================================

CREATE TABLE IF NOT EXISTS entity_nodes (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'person', 'project', 'tool', 'concept',
        'organization', 'product', 'event'
    )),
    display_name TEXT NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entity_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id TEXT NOT NULL REFERENCES entity_nodes(id),
    predicate TEXT NOT NULL,
    object_id TEXT NOT NULL REFERENCES entity_nodes(id),
    properties JSONB NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 1.0,
    source_observation UUID REFERENCES observations(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(subject_id, predicate, object_id)
);

CREATE INDEX IF NOT EXISTS idx_edges_subject ON entity_edges(subject_id);
CREATE INDEX IF NOT EXISTS idx_edges_object ON entity_edges(object_id);
CREATE INDEX IF NOT EXISTS idx_edges_predicate ON entity_edges(predicate);

-- ============================================
-- 🐜 ANT — Reflections
-- ============================================

CREATE TABLE IF NOT EXISTS reflections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    reflection_type TEXT NOT NULL CHECK (reflection_type IN (
        'pattern', 'conflict_resolution', 'insight',
        'summary', 'frequency_pattern'
    )),
    content TEXT NOT NULL,
    source_observations UUID[] NOT NULL DEFAULT '{}',
    importance SMALLINT NOT NULL DEFAULT 7,
    frequency_data JSONB,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- 🦎 CHAMELEON — Feedback Signals
-- ============================================

CREATE TABLE IF NOT EXISTS feedback_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    signal_type TEXT NOT NULL CHECK (signal_type IN (
        'conversion', 'abandonment', 'handoff_request',
        'objection', 'satisfaction', 'dissatisfaction',
        'correction', 'task_completion', 'task_failure'
    )),
    reward_score REAL NOT NULL DEFAULT 0.0
        CHECK (reward_score BETWEEN -1.0 AND 1.0),
    context_snapshot JSONB,
    action_taken TEXT,
    procedure_id UUID,
    procedure_step TEXT,
    source TEXT DEFAULT 'implicit'
        CHECK (source IN ('explicit', 'implicit', 'system')),
    external_ref TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_session ON feedback_signals(agent_id, session_id);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback_signals(signal_type);

-- ============================================
-- 🦎 CHAMELEON — Procedures
-- ============================================

CREATE TABLE IF NOT EXISTS procedures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    procedure_name TEXT NOT NULL,
    description TEXT DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'draft', 'deprecated')),
    steps JSONB NOT NULL,
    trigger_entities TEXT[] DEFAULT '{}',
    performance_score REAL DEFAULT 0.5,
    total_executions INTEGER DEFAULT 0,
    successful_executions INTEGER DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT 'human',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(agent_id, procedure_name, version)
);

CREATE INDEX IF NOT EXISTS idx_proc_agent ON procedures(agent_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_proc_entities ON procedures USING GIN(trigger_entities);

-- ============================================
-- 🐘 ELEPHANT — Citation Trails
-- ============================================

CREATE TABLE IF NOT EXISTS citation_trails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    message_index INTEGER NOT NULL,
    used_observation_ids UUID[] NOT NULL DEFAULT '{}',
    used_reflection_ids UUID[] NOT NULL DEFAULT '{}',
    active_procedure_id UUID,
    active_procedure_step TEXT,
    briefing_hash TEXT,
    n_sources INTEGER NOT NULL DEFAULT 0,
    avg_combined_score REAL,
    avg_decay_score REAL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_citation_session ON citation_trails(session_id, message_index);
CREATE INDEX IF NOT EXISTS idx_citation_obs ON citation_trails USING GIN(used_observation_ids);

-- ============================================
-- 🐝 BEE — Session Logs (Raw Capture)
-- ============================================

CREATE TABLE IF NOT EXISTS session_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    messages JSONB NOT NULL,
    token_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ DEFAULT now() + INTERVAL '14 days'
);

CREATE INDEX IF NOT EXISTS idx_session_logs_expires ON session_logs(expires_at);
CREATE INDEX IF NOT EXISTS idx_session_logs_session ON session_logs(session_id);

-- ============================================
-- 🐘 ELEPHANT — Semantic Cache
-- ============================================

CREATE TABLE IF NOT EXISTS semantic_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    query_embedding vector(1536) NOT NULL,
    query_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    hit_count INTEGER DEFAULT 1,
    ttl_hours INTEGER DEFAULT 72,
    is_personal BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_hit TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ DEFAULT now() + INTERVAL '72 hours'
);

CREATE INDEX IF NOT EXISTS idx_cache_embedding ON semantic_cache
    USING ivfflat (query_embedding vector_cosine_ops) WITH (lists = 50);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON semantic_cache(expires_at);

-- ============================================
-- 🦎 CHAMELEON — Agent Checkpoints
-- ============================================

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    working_memory JSONB NOT NULL,
    active_procedure JSONB,
    last_briefing_hash TEXT,
    last_used_obs_ids TEXT[],
    message_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(agent_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_checkpoint_session ON agent_checkpoints(agent_id, session_id);

-- ============================================
-- 🐬 DOLPHIN — Broadcast Events (Multi-Agent)
-- ============================================

CREATE TABLE IF NOT EXISTS broadcast_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_agent TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'entity_update', 'correction', 'critical_insight',
        'preference_change'
    )),
    payload JSONB NOT NULL,
    target_agents TEXT[] DEFAULT NULL,
    consumed_by TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- RPC FUNCTIONS
-- ============================================

-- 🐜 Reinforce observation (Ant: strengthen pheromone)
CREATE OR REPLACE FUNCTION reinforce_observation(
    obs_id UUID, boost REAL DEFAULT 0.15
) RETURNS VOID AS $$
BEGIN
    UPDATE observations SET
        decay_score = LEAST(1.0, decay_score + boost),
        last_accessed = now()
    WHERE id = obs_id;
END; $$ LANGUAGE plpgsql;

-- 🐜 Daily decay (Ant: pheromone evaporation)
CREATE OR REPLACE FUNCTION apply_daily_decay(
    decay_rate REAL DEFAULT 0.02
) RETURNS INTEGER AS $$
DECLARE affected INTEGER;
BEGIN
    UPDATE observations
    SET decay_score = GREATEST(0.0, decay_score - decay_rate)
    WHERE status = 'active';
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END; $$ LANGUAGE plpgsql;

-- 🐜 Mark stale observations
CREATE OR REPLACE FUNCTION mark_stale_observations(
    decay_threshold REAL DEFAULT 0.3
) RETURNS INTEGER AS $$
DECLARE affected INTEGER;
BEGIN
    UPDATE observations SET status = 'stale'
    WHERE status = 'active'
        AND (decay_score < decay_threshold
            OR (created_at + (ttl_days || ' days')::INTERVAL) < now());
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END; $$ LANGUAGE plpgsql;

-- 🐘 Retrieve observations with 5-signal combined score
CREATE OR REPLACE FUNCTION retrieve_observations(
    p_agent_id TEXT,
    p_user_id TEXT,
    p_embedding vector(1536),
    p_entities TEXT[] DEFAULT '{}',
    p_search_query TEXT DEFAULT '',
    p_limit INTEGER DEFAULT 10,
    p_min_decay REAL DEFAULT 0.3
) RETURNS TABLE (
    id UUID, content TEXT, obs_type TEXT,
    entities TEXT[], importance SMALLINT,
    decay_score REAL, event_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    emotional_valence TEXT,
    emotional_intensity SMALLINT,
    combined_score REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        o.id, o.content, o.obs_type,
        o.entities, o.importance, o.decay_score,
        o.event_time, o.created_at,
        o.emotional_valence, o.emotional_intensity,
        (
            -- 1. Semantic similarity (30%)
            (1 - (o.embedding <=> p_embedding)) * 0.30
            -- 2. Entity match (20%)
            + CASE WHEN o.entities && p_entities THEN 0.20 ELSE 0.0 END
            -- 3. Full-text search (15%)
            + CASE WHEN p_search_query != '' AND
                o.search_vector @@ plainto_tsquery('portuguese', p_search_query)
                THEN ts_rank(o.search_vector,
                    plainto_tsquery('portuguese', p_search_query)) * 0.15
                ELSE 0.0 END
            -- 4. Recency with event_time (15%)
            + (1.0 / (1.0 + EXTRACT(EPOCH FROM
                (now() - COALESCE(o.event_time, o.created_at)) / 86400))) * 0.15
            -- 5. Decay + Emotional (20%)
            + o.decay_score * 0.12
            + (COALESCE(o.emotional_intensity, 0)::REAL / 5.0) * 0.08
        ) AS combined_score
    FROM observations o
    WHERE o.agent_id = p_agent_id
        AND o.user_id = p_user_id
        AND o.status = 'active'
        AND o.decay_score >= p_min_decay
        AND o.invalidated_at IS NULL
    ORDER BY combined_score DESC
    LIMIT p_limit;
END; $$ LANGUAGE plpgsql;

-- 🐘 Semantic cache search
CREATE OR REPLACE FUNCTION search_semantic_cache(
    p_agent_id TEXT,
    p_embedding vector(1536),
    p_threshold REAL DEFAULT 0.93
) RETURNS TABLE (
    id UUID, response_text TEXT, hit_count INTEGER,
    similarity REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        sc.id, sc.response_text, sc.hit_count,
        (1 - (sc.query_embedding <=> p_embedding))::REAL AS similarity
    FROM semantic_cache sc
    WHERE sc.agent_id = p_agent_id
        AND sc.expires_at > now()
        AND (1 - (sc.query_embedding <=> p_embedding)) >= p_threshold
    ORDER BY similarity DESC
    LIMIT 1;
END; $$ LANGUAGE plpgsql;

-- 🐜 Find similar observations (for conflict resolution)
CREATE OR REPLACE FUNCTION find_similar_observations(
    p_agent_id TEXT,
    p_user_id TEXT,
    p_embedding vector(1536),
    p_threshold REAL DEFAULT 0.85,
    p_limit INTEGER DEFAULT 3
) RETURNS TABLE (
    id UUID, content TEXT, obs_type TEXT,
    importance SMALLINT, similarity REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        o.id, o.content, o.obs_type, o.importance,
        (1 - (o.embedding <=> p_embedding))::REAL AS similarity
    FROM observations o
    WHERE o.agent_id = p_agent_id
        AND o.user_id = p_user_id
        AND o.status = 'active'
        AND o.invalidated_at IS NULL
        AND (1 - (o.embedding <=> p_embedding)) >= p_threshold
    ORDER BY similarity DESC
    LIMIT p_limit;
END; $$ LANGUAGE plpgsql;

-- 🐜 Get lead state at a point in time (bi-temporal query)
CREATE OR REPLACE FUNCTION get_lead_state_at(
    p_agent_id TEXT,
    p_user_id TEXT,
    p_at_time TIMESTAMPTZ
) RETURNS TABLE (
    id UUID, content TEXT, obs_type TEXT,
    event_time TIMESTAMPTZ, created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT o.id, o.content, o.obs_type,
        o.event_time, o.created_at
    FROM observations o
    WHERE o.agent_id = p_agent_id
        AND o.user_id = p_user_id
        AND o.created_at <= p_at_time
        AND (o.invalidated_at IS NULL OR o.invalidated_at > p_at_time)
        AND o.status != 'purged'
    ORDER BY o.event_time DESC NULLS LAST, o.created_at DESC;
END; $$ LANGUAGE plpgsql;

-- 🦎 Feedback summary
CREATE OR REPLACE FUNCTION get_feedback_summary(
    p_agent_id TEXT, p_days INTEGER DEFAULT 7
) RETURNS TABLE (
    signal_type TEXT, count BIGINT,
    avg_reward REAL, top_action TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        fs.signal_type,
        COUNT(*) as count,
        AVG(fs.reward_score)::REAL as avg_reward,
        MODE() WITHIN GROUP (ORDER BY fs.action_taken) as top_action
    FROM feedback_signals fs
    WHERE fs.agent_id = p_agent_id
        AND fs.created_at > now() - (p_days || ' days')::INTERVAL
    GROUP BY fs.signal_type
    ORDER BY count DESC;
END; $$ LANGUAGE plpgsql;

-- 🐜 Frequency analysis
CREATE OR REPLACE FUNCTION analyze_topic_frequency(
    p_agent_id TEXT, p_user_id TEXT, p_days INTEGER DEFAULT 30
) RETURNS TABLE (
    topic TEXT, session_count BIGINT,
    total_sessions BIGINT, frequency_ratio REAL
) AS $$
BEGIN
    RETURN QUERY
    WITH sessions AS (
        SELECT DISTINCT source_session
        FROM observations
        WHERE agent_id = p_agent_id AND user_id = p_user_id
            AND created_at > now() - (p_days || ' days')::INTERVAL
            AND source_session IS NOT NULL
    ),
    topic_sessions AS (
        SELECT topic_fingerprint as topic,
            COUNT(DISTINCT source_session) as session_count
        FROM observations
        WHERE agent_id = p_agent_id AND user_id = p_user_id
            AND topic_fingerprint IS NOT NULL
            AND created_at > now() - (p_days || ' days')::INTERVAL
        GROUP BY topic_fingerprint
    )
    SELECT ts.topic, ts.session_count,
        (SELECT COUNT(*) FROM sessions) as total_sessions,
        (ts.session_count::REAL / NULLIF((SELECT COUNT(*) FROM sessions), 0))
            as frequency_ratio
    FROM topic_sessions ts
    ORDER BY frequency_ratio DESC;
END; $$ LANGUAGE plpgsql;
