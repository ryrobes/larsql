-- Migration: Add genus_hash for cascade-level identity
-- Date: 2025-12-27
-- Purpose: Enable cascade-level analytics, trending, and regression detection
--
-- Background:
-- While species_hash identifies individual cell executions (prompt template + inputs),
-- genus_hash identifies CASCADE INVOCATIONS (cascade structure + top-level inputs).
--
-- This enables:
-- - Trending: "How has extract_brand performance changed over time?"
-- - Regression detection: "Cost up 30% for this invocation pattern"
-- - Input clustering: "Small products cost $0.01, large products cost $0.05"
-- - Forecasting: "Expected weekly cost for this cascade: $15 ± $3"
--
-- Taxonomy:
--   Kingdom → RVBBIT Framework
--     Class → Cascade Type (extract_brand, analyze_data)
--       Genus → Cascade Invocation (same cascade + inputs) ← NEW!
--         Species → Cell Execution (same cell + config)

-- Add genus_hash to cascade_sessions (primary storage location)
ALTER TABLE cascade_sessions
ADD COLUMN IF NOT EXISTS genus_hash String DEFAULT '' CODEC(ZSTD(1));

-- Add index for fast filtering
ALTER TABLE cascade_sessions
ADD INDEX IF NOT EXISTS idx_genus_hash genus_hash TYPE bloom_filter GRANULARITY 1;

-- Add genus_hash to unified_logs (for cascade-level log entries)
-- This allows filtering cascade_start/cascade_complete logs by genus
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS genus_hash Nullable(String) AFTER species_hash;

-- Add index for unified_logs
ALTER TABLE unified_logs
ADD INDEX IF NOT EXISTS idx_genus_unified genus_hash TYPE bloom_filter GRANULARITY 1;

-- Backward compatibility: Existing rows will have genus_hash = '' or NULL
-- Historical data can be backfilled if needed via:
--   1. SELECT session_id, cascade_id, input_data FROM cascade_sessions
--   2. FOR EACH: compute_genus_hash() from cascade definition + input
--   3. UPDATE cascade_sessions SET genus_hash = ? WHERE session_id = ?
--
-- Or simply start fresh (genus_hash = '' for historical sessions is fine)
