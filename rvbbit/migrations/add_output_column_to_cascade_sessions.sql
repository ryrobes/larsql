-- Migration: Add Output Column to cascade_sessions
-- Purpose: Store final cascade output for quick access in Console UI
-- Date: 2025-12-27
--
-- Background:
-- Console view needs to show cascade outputs without expensive joins to unified_logs.
-- Denormalized storage is acceptable for ClickHouse - it's optimized for this pattern.
--
-- The output column stores:
-- - Final output from the last executed cell in cascade
-- - Full output (no truncation) - frontend queries can truncate as needed
-- - Stored as-is without mutation (preserves original format)
--
-- Benefits:
-- - Fast Console queries (no joins to large unified_logs table)
-- - Historical output visibility
-- - Debugging aid for cascade runs
-- - ClickHouse compression handles large strings efficiently

-- Add output column with aggressive compression (outputs can be large)
ALTER TABLE cascade_sessions
ADD COLUMN IF NOT EXISTS output String DEFAULT '' CODEC(ZSTD(3));

-- Add index for fast full-text search on output
ALTER TABLE cascade_sessions
ADD INDEX IF NOT EXISTS idx_output_bloom output TYPE bloom_filter(0.01) GRANULARITY 1;

-- Backward compatibility: Existing rows will have output = ''
-- This correctly represents "no output captured" for historical sessions.
--
-- Frontend queries can truncate for display:
--   SELECT LEFT(output, 300) as output_truncated FROM cascade_sessions
