-- Migration: 033_caller_context_active
-- Description: Create caller_context_active table for cross-thread caller context
-- Author: LARS
-- Date: 2026-01-17

-- ReplacingMergeTree table for active caller contexts during SQL query execution.
-- This replaces complex thread-local/contextvar propagation with a simple
-- ClickHouse-backed store that works reliably across all threads.
--
-- Uses ReplacingMergeTree so:
-- - Same connection_id overwrites previous entry (eventually)
-- - 1-hour TTL auto-cleans stale entries
-- - No explicit DELETE needed (which Memory tables don't support)

CREATE TABLE IF NOT EXISTS caller_context_active (
    -- Connection identifier (postgres session_id)
    connection_id String,

    -- Caller identifier for cost rollup (e.g., 'sql-clever-fox-abc123')
    caller_id String,

    -- Invocation metadata as JSON
    metadata_json String DEFAULT '{}',

    -- When this context was set
    created_at DateTime64(6) DEFAULT now64(6)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY connection_id
TTL toDateTime(created_at) + INTERVAL 1 HOUR;
