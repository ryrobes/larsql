-- Migration: 047_runtime_event_log
-- Description: Create runtime_event_log table for append-only operational logs (pgwire, etc.)
-- Author: LARS
-- Date: 2026-01-29

CREATE TABLE IF NOT EXISTS runtime_event_log (
    event_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),
    timestamp_iso String,

    -- Classification
    source LowCardinality(String),              -- e.g. 'pgwire', 'studio_backend', 'runner'
    level LowCardinality(String),               -- DEBUG/INFO/WARN/ERROR
    event LowCardinality(String) DEFAULT '',    -- short machine-readable event name

    -- Message
    message String CODEC(ZSTD(3)),
    extra_json String DEFAULT '{}' CODEC(ZSTD(3)),

    -- Common context
    session_id Nullable(String),
    query_id Nullable(String),
    caller_id Nullable(String),

    -- Auth / client context
    user_name Nullable(String),
    auth_user_id Nullable(String),
    database_name Nullable(String),
    results_db Nullable(String),
    application_name Nullable(String),
    client_addr Nullable(String),
    thread_id UInt64 DEFAULT 0,

    -- Indexes
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_source source TYPE set(20) GRANULARITY 1,
    INDEX idx_level level TYPE set(10) GRANULARITY 1,
    INDEX idx_event event TYPE bloom_filter GRANULARITY 1,
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_query query_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_caller caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_db database_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_auth auth_user_id TYPE bloom_filter GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (timestamp, source, level)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;

