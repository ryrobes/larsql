-- Migration: 044_param_store
-- Description: Create param_store table - user-scoped parameter storage for @param_get/@param_set
-- Author: LARS
-- Date: 2026-01-26

CREATE TABLE IF NOT EXISTS param_store (
    -- Composite key: user + database + param name
    user_id String,
    database_name String,
    param_name String,

    -- Value (supports strings, JSON, arrays)
    param_value String CODEC(ZSTD(3)),
    param_type LowCardinality(String) DEFAULT 'string',

    -- For array params (@params_set multi-select)
    param_values Array(String) DEFAULT [],

    -- Timing
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Optional expiration (for manual cleanup, not auto-TTL)
    expires_at Nullable(DateTime64(3)),

    -- Indexes
    INDEX idx_user user_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_database database_name TYPE set(100) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_id, database_name, param_name)
SETTINGS index_granularity = 8192;
