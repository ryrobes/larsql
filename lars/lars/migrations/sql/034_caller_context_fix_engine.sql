-- Migration: 034_caller_context_fix_engine
-- Description: Recreate caller_context_active with ReplacingMergeTree (Memory doesn't support DELETE)
-- Author: LARS
-- Date: 2026-01-17

-- Drop the Memory table (doesn't support DELETE which we need for cleanup)
DROP TABLE IF EXISTS caller_context_active;

-- Recreate with ReplacingMergeTree:
-- - Same connection_id overwrites previous entry (eventually merged)
-- - 1-hour TTL auto-cleans stale entries
-- - No explicit DELETE needed
CREATE TABLE caller_context_active (
    connection_id String,
    caller_id String,
    metadata_json String DEFAULT '{}',
    created_at DateTime64(6) DEFAULT now64(6)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY connection_id
TTL toDateTime(created_at) + INTERVAL 1 HOUR;
