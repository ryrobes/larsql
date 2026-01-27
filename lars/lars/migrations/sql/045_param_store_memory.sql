-- Migration: 045_param_store_memory
-- Description: Switch param_store to Memory engine for instant reads/writes
-- Author: LARS
-- Date: 2026-01-27
--
-- The ReplacingMergeTree engine was causing significant latency for param operations
-- because of merge overhead and deduplication delays. Since params are session-scoped
-- and transient, Memory engine is more appropriate:
-- - Instant reads and writes (no merge, no disk I/O)
-- - Queries don't need FINAL keyword
-- - Data is lost on ClickHouse restart (acceptable for session params)
--
-- Strategy for key-value semantics with append-only Memory table:
-- - DELETE before INSERT for updates (Memory supports lightweight DELETE)
-- - Use ORDER BY updated_at DESC LIMIT 1 for reads as fallback
-- - L1 cache handles 99% of reads anyway

-- Drop the old table (params are transient, no need to migrate data)
DROP TABLE IF EXISTS param_store;

-- Recreate with Memory engine
CREATE TABLE param_store (
    -- Composite key: user + database + param name
    user_id String,
    database_name String,
    param_name String,

    -- Value (supports strings, JSON, arrays)
    param_value String,
    param_type LowCardinality(String) DEFAULT 'string',

    -- For array params (@params_set multi-select)
    param_values Array(String) DEFAULT [],

    -- Timing (for ordering when multiple rows exist)
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3)
)
ENGINE = Memory;
