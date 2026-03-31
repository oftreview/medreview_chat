-- ═══════════════════════════════════════════════════════════════════
-- Migration 008: Fix RICE scoring in backlog_items
-- 1. Fix column defaults to 0-10 scale
-- 2. Fix generated column formula: R + I + C + E (additive, max 40)
-- 3. Clamp existing out-of-range values
-- ═══════════════════════════════════════════════════════════════════

-- Step 1: Fix defaults for RICE columns (0-10 scale, default 5)
ALTER TABLE backlog_items ALTER COLUMN reach SET DEFAULT 5;
ALTER TABLE backlog_items ALTER COLUMN impact SET DEFAULT 5;
ALTER TABLE backlog_items ALTER COLUMN confidence SET DEFAULT 5;
ALTER TABLE backlog_items ALTER COLUMN effort SET DEFAULT 5;

-- Step 2: Clamp any out-of-range values before changing the formula
UPDATE backlog_items SET reach = LEAST(GREATEST(reach, 0), 10) WHERE reach < 0 OR reach > 10;
UPDATE backlog_items SET impact = LEAST(GREATEST(impact, 0), 10) WHERE impact < 0 OR impact > 10;
UPDATE backlog_items SET confidence = LEAST(GREATEST(confidence, 0), 10) WHERE confidence < 0 OR confidence > 10;
UPDATE backlog_items SET effort = LEAST(GREATEST(effort, 0), 10) WHERE effort < 0 OR effort > 10;

-- Step 3: Drop old generated column and recreate with additive formula
ALTER TABLE backlog_items DROP COLUMN rice_score;
ALTER TABLE backlog_items ADD COLUMN rice_score REAL GENERATED ALWAYS AS (
    LEAST(GREATEST(reach, 0), 10) +
    LEAST(GREATEST(impact, 0), 10) +
    LEAST(GREATEST(confidence, 0), 10) +
    LEAST(GREATEST(effort, 0), 10)
) STORED;

-- Step 4: Recreate index
DROP INDEX IF EXISTS idx_backlog_rice;
CREATE INDEX idx_backlog_rice ON backlog_items(rice_score DESC);
