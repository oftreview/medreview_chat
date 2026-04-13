-- ═══════════════════════════════════════════════════════════════════
-- Migration 009: Add priority and assigned_agent to backlog_items
-- Replace RICE scoring with simple priority levels
-- ═══════════════════════════════════════════════════════════════════

-- Step 1: Add priority column
ALTER TABLE backlog_items ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'media'
    CHECK (priority IN ('baixa','media','alta','critica'));

-- Step 2: Add assigned_agent column
ALTER TABLE backlog_items ADD COLUMN IF NOT EXISTS assigned_agent TEXT DEFAULT 'humano';

-- Step 3: Create indexes
CREATE INDEX IF NOT EXISTS idx_backlog_priority ON backlog_items(priority);
CREATE INDEX IF NOT EXISTS idx_backlog_agent ON backlog_items(assigned_agent);

-- Step 4: Migrate existing RICE scores to priority levels
-- RICE >= 30 → critica, >= 25 → alta, >= 15 → media, < 15 → baixa
UPDATE backlog_items SET priority =
    CASE
        WHEN rice_score >= 30 THEN 'critica'
        WHEN rice_score >= 25 THEN 'alta'
        WHEN rice_score >= 15 THEN 'media'
        ELSE 'baixa'
    END
WHERE priority IS NULL OR priority = 'media';

-- Step 5: Set default agent
UPDATE backlog_items SET assigned_agent = 'claude-code' WHERE assigned_agent IS NULL;
