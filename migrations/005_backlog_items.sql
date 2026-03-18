-- ═══════════════════════════════════════════════════════════════════
-- Migration 005: Backlog Items
-- Tabela para gerenciamento de backlog de produto com priorização RICE
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS backlog_items (
    id              BIGSERIAL PRIMARY KEY,
    item_id         TEXT UNIQUE NOT NULL,           -- ex: CLO-001
    title           TEXT NOT NULL,
    description     TEXT DEFAULT '',
    item_type       TEXT DEFAULT 'feature'
        CHECK (item_type IN ('feature','enhancement','bugfix','tech-debt','infra','research')),
    module          TEXT DEFAULT 'core'
        CHECK (module IN ('agent','api','core','database','dashboard','integrations','data','devops')),
    status          TEXT DEFAULT 'backlog'
        CHECK (status IN ('backlog','next','in-progress','review','done','blocked','cancelled')),
    phase           TEXT DEFAULT 'Phase 2'
        CHECK (phase IN ('MVP','Phase 2','Phase 3','Phase 4')),

    -- RICE scoring
    reach           INTEGER DEFAULT 100,
    impact          REAL DEFAULT 1.0,
    confidence      REAL DEFAULT 0.8,
    effort          REAL DEFAULT 2.0,
    rice_score      REAL GENERATED ALWAYS AS (
        CASE WHEN effort > 0 THEN (reach * impact * confidence) / effort ELSE 0 END
    ) STORED,

    -- Detalhes
    estimate        TEXT DEFAULT '',                 -- ex: "2d", "1w"
    dependencies    TEXT DEFAULT '',                 -- ex: "CLO-003, CLO-005"
    notes           TEXT DEFAULT '',
    sort_order      INTEGER DEFAULT 0,              -- para drag & drop

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para queries comuns
CREATE INDEX IF NOT EXISTS idx_backlog_status ON backlog_items(status);
CREATE INDEX IF NOT EXISTS idx_backlog_phase ON backlog_items(phase);
CREATE INDEX IF NOT EXISTS idx_backlog_rice ON backlog_items(rice_score DESC);
CREATE INDEX IF NOT EXISTS idx_backlog_sort ON backlog_items(sort_order);

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_backlog_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_backlog_updated_at ON backlog_items;
CREATE TRIGGER trg_backlog_updated_at
    BEFORE UPDATE ON backlog_items
    FOR EACH ROW
    EXECUTE FUNCTION update_backlog_updated_at();
