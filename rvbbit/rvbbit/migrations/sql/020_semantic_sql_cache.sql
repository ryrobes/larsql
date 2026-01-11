-- Migration: 020_semantic_sql_cache
-- Description: Create semantic_sql_cache table - persistent LLM result cache for semantic SQL
-- Author: RVBBIT
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS semantic_sql_cache (
    -- Identity (cache_key is MD5 hash of function + args)
    cache_key String,
    function_name LowCardinality(String),

    -- Input (for debugging/inspection)
    args_json String CODEC(ZSTD(3)),
    args_preview String DEFAULT '',

    -- Result
    result String CODEC(ZSTD(3)),
    result_type LowCardinality(String),

    -- Timing
    created_at DateTime64(3) DEFAULT now64(),
    expires_at DateTime64(3) DEFAULT toDateTime64('2100-01-01 00:00:00', 3),
    ttl_seconds UInt32 DEFAULT 0,

    -- Analytics
    hit_count UInt64 DEFAULT 1,
    last_hit_at DateTime64(3) DEFAULT now64(),

    -- Size tracking
    result_bytes UInt32 DEFAULT 0,

    -- Source tracking
    first_session_id String DEFAULT '',
    first_caller_id String DEFAULT '',

    -- Indexes for efficient queries
    INDEX idx_function function_name TYPE set(100) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1,
    INDEX idx_expires expires_at TYPE minmax GRANULARITY 1,
    INDEX idx_last_hit last_hit_at TYPE minmax GRANULARITY 1,
    INDEX idx_hit_count hit_count TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(last_hit_at)
ORDER BY (cache_key)
TTL expires_at
SETTINGS index_granularity = 8192;
