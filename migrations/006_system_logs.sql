-- ═══════════════════════════════════════════════════════════════════
-- Migration 006: System Logs Persistentes
-- Armazena logs do sistema no Supabase para consulta histórica.
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS system_logs (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT now() NOT NULL,
    tag             TEXT NOT NULL DEFAULT 'debug'
        CHECK (tag IN ('debug','system','security','error','flush','debounce')),
    source          TEXT DEFAULT 'app',
    message         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}'::jsonb
);

-- ── Índices para filtros rápidos ──
CREATE INDEX IF NOT EXISTS idx_system_logs_created_at ON system_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_logs_tag        ON system_logs (tag);
CREATE INDEX IF NOT EXISTS idx_system_logs_source     ON system_logs (source);
CREATE INDEX IF NOT EXISTS idx_system_logs_tag_date   ON system_logs (tag, created_at DESC);

-- ── Full-text search no campo message ──
CREATE INDEX IF NOT EXISTS idx_system_logs_message_search
    ON system_logs USING gin (to_tsvector('portuguese', message));

-- ── RPC: Limpar logs antigos (retenção padrão 30 dias) ──
CREATE OR REPLACE FUNCTION cleanup_old_logs(retention_days INTEGER DEFAULT 30)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM system_logs
    WHERE created_at < now() - (retention_days || ' days')::INTERVAL;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

-- ── RPC: Estatísticas de volume por dia (para calendário) ──
CREATE OR REPLACE FUNCTION logs_daily_stats(days_back INTEGER DEFAULT 30)
RETURNS TABLE(log_date DATE, total BIGINT, errors BIGINT, security BIGINT, system BIGINT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        (sl.created_at AT TIME ZONE 'America/Sao_Paulo')::DATE AS log_date,
        COUNT(*)::BIGINT AS total,
        COUNT(*) FILTER (WHERE sl.tag = 'error')::BIGINT AS errors,
        COUNT(*) FILTER (WHERE sl.tag = 'security')::BIGINT AS security,
        COUNT(*) FILTER (WHERE sl.tag = 'system')::BIGINT AS system
    FROM system_logs sl
    WHERE sl.created_at >= now() - (days_back || ' days')::INTERVAL
    GROUP BY 1
    ORDER BY 1 DESC;
END;
$$;

-- ── Habilitar RLS (Row Level Security) ──
ALTER TABLE system_logs ENABLE ROW LEVEL SECURITY;

-- Política: acesso total para service_role (backend)
CREATE POLICY "service_role_full_access" ON system_logs
    FOR ALL
    USING (true)
    WITH CHECK (true);
