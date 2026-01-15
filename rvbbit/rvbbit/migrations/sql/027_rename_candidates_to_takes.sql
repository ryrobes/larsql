-- Migration: 027_rename_candidates_to_takes
-- Description: Renames all candidate-related fields and enum values to use "takes" terminology
-- Date: 2026-01-14
--
-- Background:
-- The parallel execution feature was originally called "takes" (nautical term),
-- then renamed to "candidates" (clinical, bureaucratic feel). After brainstorming,
-- "takes" (film industry metaphor) was chosen:
--   - Single syllable, punchy, easy to say
--   - Universally understood: "Take 1, Take 2, Take 3..."
--   - Director (evaluator) picks the best take
--   - Works naturally: "Run 6 takes using 3 different models"
--
-- This migration renames all database fields from candidate_* to take_*.
-- For aggregate mode, we use "composite" (film/VFX term for combining elements).
--
-- IMPORTANT: ClickHouse doesn't support column renames directly.
-- Strategy: Add new columns, copy data, drop old columns (or leave deprecated).

-- =============================================================================
-- UNIFIED_LOGS TABLE
-- =============================================================================

-- Add new columns
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS take_index Nullable(Int32);

ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS winning_take_index Nullable(Int32);

-- Copy existing data from old columns to new columns
ALTER TABLE unified_logs
UPDATE take_index = candidate_index
WHERE candidate_index IS NOT NULL;

ALTER TABLE unified_logs
UPDATE winning_take_index = winning_candidate_index
WHERE winning_candidate_index IS NOT NULL;

-- Add index for new column
ALTER TABLE unified_logs
ADD INDEX IF NOT EXISTS idx_take_index take_index TYPE set(100) GRANULARITY 1;

-- Note: Old columns (candidate_index, winning_candidate_index) left in place for backwards compatibility
-- They can be dropped in a future migration after code is fully migrated

-- =============================================================================
-- CHECKPOINTS TABLE
-- =============================================================================

-- Add new columns for take_outputs and take_metadata
ALTER TABLE checkpoints
ADD COLUMN IF NOT EXISTS take_outputs Nullable(String);

ALTER TABLE checkpoints
ADD COLUMN IF NOT EXISTS take_metadata Nullable(String);

-- Copy existing data from old columns to new columns
ALTER TABLE checkpoints
UPDATE take_outputs = candidate_outputs
WHERE candidate_outputs IS NOT NULL;

ALTER TABLE checkpoints
UPDATE take_metadata = candidate_metadata
WHERE candidate_metadata IS NOT NULL;

-- Note: checkpoint_type enum has 'candidate_eval' = 2
-- ClickHouse doesn't allow modifying enum values easily.
-- We'll add a new value and deprecate the old one.
-- For now, code should handle both 'candidate_eval' and 'take_eval' (value 10)
ALTER TABLE checkpoints
MODIFY COLUMN checkpoint_type Enum8(
    'cell_input' = 1,
    'candidate_eval' = 2,  -- DEPRECATED: Use 'take_eval' for new records
    'free_text' = 3,
    'choice' = 4,
    'multi_choice' = 5,
    'confirmation' = 6,
    'rating' = 7,
    'audible' = 8,
    'decision' = 9,
    'take_eval' = 10       -- NEW: Replaces 'candidate_eval'
);

-- =============================================================================
-- EVALUATIONS TABLE
-- =============================================================================

-- Add new column
ALTER TABLE evaluations
ADD COLUMN IF NOT EXISTS take_index Int32 DEFAULT 0;

-- Copy existing data from old column to new column
ALTER TABLE evaluations
UPDATE take_index = candidate_index
WHERE 1 = 1;

-- =============================================================================
-- CONTEXT_SHADOW_ASSESSMENTS TABLE
-- =============================================================================

-- Add new column
ALTER TABLE context_shadow_assessments
ADD COLUMN IF NOT EXISTS total_takes UInt16 DEFAULT 0;

-- Copy existing data from old column to new column
ALTER TABLE context_shadow_assessments
UPDATE total_takes = total_candidates
WHERE 1 = 1;

-- =============================================================================
-- INTRA_CONTEXT_SHADOW_ASSESSMENTS TABLE
-- =============================================================================

-- Add new column
ALTER TABLE intra_context_shadow_assessments
ADD COLUMN IF NOT EXISTS take_index Nullable(Int16);

-- Copy existing data from old column to new column
ALTER TABLE intra_context_shadow_assessments
UPDATE take_index = candidate_index
WHERE candidate_index IS NOT NULL;

-- Add index for new column
ALTER TABLE intra_context_shadow_assessments
ADD INDEX IF NOT EXISTS idx_take take_index TYPE set(100) GRANULARITY 1;

-- =============================================================================
-- CELL_ANALYTICS TABLE
-- =============================================================================

-- Add new column
ALTER TABLE cell_analytics
ADD COLUMN IF NOT EXISTS take_count UInt8 DEFAULT 0;

-- Copy existing data from old column to new column
ALTER TABLE cell_analytics
UPDATE take_count = candidate_count
WHERE 1 = 1;

-- =============================================================================
-- CASCADE_ANALYTICS TABLE
-- =============================================================================

-- Add new columns
ALTER TABLE cascade_analytics
ADD COLUMN IF NOT EXISTS take_count UInt8 DEFAULT 0;

ALTER TABLE cascade_analytics
ADD COLUMN IF NOT EXISTS winner_take_index Nullable(Int8);

-- Copy existing data from old columns to new columns
ALTER TABLE cascade_analytics
UPDATE take_count = candidate_count
WHERE 1 = 1;

ALTER TABLE cascade_analytics
UPDATE winner_take_index = winner_candidate_index
WHERE winner_candidate_index IS NOT NULL;

-- =============================================================================
-- PROMPT_LINEAGE TABLE
-- =============================================================================

-- Add new column
ALTER TABLE prompt_lineage
ADD COLUMN IF NOT EXISTS take_index Int32 DEFAULT 0;

-- Copy existing data from old column to new column
ALTER TABLE prompt_lineage
UPDATE take_index = candidate_index
WHERE 1 = 1;

-- =============================================================================
-- CELL_CONTEXT_BREAKDOWN TABLE
-- =============================================================================

-- Add new column (if table exists)
ALTER TABLE cell_context_breakdown
ADD COLUMN IF NOT EXISTS take_index Nullable(Int32);

-- Copy existing data from old column to new column
ALTER TABLE cell_context_breakdown
UPDATE take_index = candidate_index
WHERE candidate_index IS NOT NULL;

-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================

-- Verify unified_logs columns
SELECT 'unified_logs' as table_name, name, type
FROM system.columns
WHERE table = 'unified_logs'
  AND database = currentDatabase()
  AND name IN ('take_index', 'winning_take_index', 'candidate_index', 'winning_candidate_index')
ORDER BY name;

-- Verify checkpoints columns
SELECT 'checkpoints' as table_name, name, type
FROM system.columns
WHERE table = 'checkpoints'
  AND database = currentDatabase()
  AND name IN ('take_outputs', 'take_metadata', 'candidate_outputs', 'candidate_metadata', 'checkpoint_type')
ORDER BY name;

-- Verify evaluations columns
SELECT 'evaluations' as table_name, name, type
FROM system.columns
WHERE table = 'evaluations'
  AND database = currentDatabase()
  AND name IN ('take_index', 'candidate_index')
ORDER BY name;

-- Verify cascade_analytics columns
SELECT 'cascade_analytics' as table_name, name, type
FROM system.columns
WHERE table = 'cascade_analytics'
  AND database = currentDatabase()
  AND name IN ('take_count', 'winner_take_index', 'candidate_count', 'winner_candidate_index')
ORDER BY name;

-- Count migrated records (compare old vs new columns)
SELECT 'unified_logs' as table_name,
       countIf(take_index IS NOT NULL) as records_with_take_index,
       countIf(candidate_index IS NOT NULL) as records_with_candidate_index
FROM unified_logs;

-- =============================================================================
-- DEPRECATION NOTES
-- =============================================================================
--
-- The following columns are DEPRECATED but left in place for backwards compatibility:
--
-- unified_logs:
--   - candidate_index (use take_index)
--   - winning_candidate_index (use winning_take_index)
--
-- checkpoints:
--   - candidate_outputs (use take_outputs)
--   - candidate_metadata (use take_metadata)
--   - checkpoint_type = 'candidate_eval' (use 'take_eval')
--
-- evaluations:
--   - candidate_index (use take_index)
--
-- context_shadow_assessments:
--   - total_candidates (use total_takes)
--
-- intra_context_shadow_assessments:
--   - candidate_index (use take_index)
--
-- cell_analytics:
--   - candidate_count (use take_count)
--
-- cascade_analytics:
--   - candidate_count (use take_count)
--   - winner_candidate_index (use winner_take_index)
--
-- prompt_lineage:
--   - candidate_index (use take_index)
--
-- cell_context_breakdown:
--   - candidate_index (use take_index)
--
-- These deprecated columns can be dropped in a future migration (e.g., v2.0)
-- after all code paths have been updated to use the new column names.
--
-- =============================================================================
-- FUTURE CLEANUP MIGRATION (DO NOT RUN YET)
-- =============================================================================
-- -- Run this ONLY after all code is migrated to use take_* columns
--
-- ALTER TABLE unified_logs DROP COLUMN IF EXISTS candidate_index;
-- ALTER TABLE unified_logs DROP COLUMN IF EXISTS winning_candidate_index;
-- ALTER TABLE checkpoints DROP COLUMN IF EXISTS candidate_outputs;
-- ALTER TABLE checkpoints DROP COLUMN IF EXISTS candidate_metadata;
-- ALTER TABLE evaluations DROP COLUMN IF EXISTS candidate_index;
-- ALTER TABLE context_shadow_assessments DROP COLUMN IF EXISTS total_candidates;
-- ALTER TABLE intra_context_shadow_assessments DROP COLUMN IF EXISTS candidate_index;
-- ALTER TABLE cell_analytics DROP COLUMN IF EXISTS candidate_count;
-- ALTER TABLE cascade_analytics DROP COLUMN IF EXISTS candidate_count;
-- ALTER TABLE cascade_analytics DROP COLUMN IF EXISTS winner_candidate_index;
-- ALTER TABLE prompt_lineage DROP COLUMN IF EXISTS candidate_index;
-- ALTER TABLE cell_context_breakdown DROP COLUMN IF EXISTS candidate_index;
