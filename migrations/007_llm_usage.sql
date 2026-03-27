-- ============================================================
-- 007 · Persistência de uso LLM (tokens, custos, cache)
-- ============================================================
-- Grava cada chamada à API Anthropic para controle de custos
-- mesmo após restart do servidor.
-- ============================================================

-- ── Tabela principal ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS llm_usage (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    model       TEXT NOT NULL,
    input_tokens   INT NOT NULL DEFAULT 0,
    output_tokens  INT NOT NULL DEFAULT 0,
    cache_read     INT NOT NULL DEFAULT 0,
    cache_write    INT NOT NULL DEFAULT 0,
    cost           NUMERIC(12,8) NOT NULL DEFAULT 0,
    session_id     TEXT,                       -- opcional: agrupar por sessão
    metadata       JSONB DEFAULT '{}'::jsonb   -- dados extras se necessário
);

-- ── Índices ──────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_llm_usage_created
    ON llm_usage (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_model
    ON llm_usage (model);

CREATE INDEX IF NOT EXISTS idx_llm_usage_date
    ON llm_usage (DATE(created_at));

-- ── RPC: Resumo diário de custos (para gráficos) ────────────
CREATE OR REPLACE FUNCTION llm_daily_stats(days_back INT DEFAULT 30)
RETURNS TABLE (
    day        DATE,
    total_calls   BIGINT,
    total_input   BIGINT,
    total_output  BIGINT,
    total_cache_read  BIGINT,
    total_cache_write BIGINT,
    total_cost    NUMERIC,
    models_used   TEXT[]
) LANGUAGE sql STABLE AS $$
    SELECT
        DATE(created_at) AS day,
        COUNT(*)::BIGINT AS total_calls,
        COALESCE(SUM(input_tokens), 0)::BIGINT AS total_input,
        COALESCE(SUM(output_tokens), 0)::BIGINT AS total_output,
        COALESCE(SUM(cache_read), 0)::BIGINT AS total_cache_read,
        COALESCE(SUM(cache_write), 0)::BIGINT AS total_cache_write,
        COALESCE(SUM(cost), 0) AS total_cost,
        ARRAY_AGG(DISTINCT model) AS models_used
    FROM llm_usage
    WHERE created_at >= now() - (days_back || ' days')::INTERVAL
    GROUP BY DATE(created_at)
    ORDER BY day DESC;
$$;

-- ── RPC: Totais acumulados (all-time ou por período) ────────
CREATE OR REPLACE FUNCTION llm_totals(since TIMESTAMPTZ DEFAULT NULL)
RETURNS TABLE (
    total_calls   BIGINT,
    total_input   BIGINT,
    total_output  BIGINT,
    total_cache_read  BIGINT,
    total_cache_write BIGINT,
    total_cost    NUMERIC
) LANGUAGE sql STABLE AS $$
    SELECT
        COUNT(*)::BIGINT,
        COALESCE(SUM(input_tokens), 0)::BIGINT,
        COALESCE(SUM(output_tokens), 0)::BIGINT,
        COALESCE(SUM(cache_read), 0)::BIGINT,
        COALESCE(SUM(cache_write), 0)::BIGINT,
        COALESCE(SUM(cost), 0)
    FROM llm_usage
    WHERE (since IS NULL OR created_at >= since);
$$;

-- ── RLS ──────────────────────────────────────────────────────
ALTER TABLE llm_usage ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_full_access" ON llm_usage
    FOR ALL TO service_role USING (true) WITH CHECK (true);
