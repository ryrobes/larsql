-- Migration: 021_sql_query_log
-- Description: Create sql_query_log table - SQL Trail analytics for UDF cost tracking
-- Author: LARS
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS sql_query_log (
    -- Identity
    query_id UUID DEFAULT generateUUIDv4(),
    caller_id String,

    -- Query Content
    query_raw String CODEC(ZSTD(3)),
    query_fingerprint String,
    query_template String CODEC(ZSTD(3)),
    query_type LowCardinality(String),

    -- UDF Detection
    udf_types Array(String) DEFAULT [],
    udf_count UInt16 DEFAULT 0,
    cascade_paths Array(String) DEFAULT [],
    cascade_count UInt16 DEFAULT 0,

    -- Execution
    started_at DateTime64(6),
    completed_at Nullable(DateTime64(6)),
    duration_ms Nullable(Float64),
    status LowCardinality(String),

    -- Row Metrics
    rows_input Nullable(Int32),
    rows_output Nullable(Int32),

    -- Cost (aggregated from spawned sessions via caller_id)
    total_cost Nullable(Float64),
    total_tokens_in Nullable(Int64),
    total_tokens_out Nullable(Int64),
    llm_calls_count UInt32 DEFAULT 0,

    -- Cache Metrics
    cache_hits UInt32 DEFAULT 0,
    cache_misses UInt32 DEFAULT 0,

    -- Error Info
    error_message Nullable(String),

    -- Protocol
    protocol LowCardinality(String),
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Indexes
    INDEX idx_caller caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_fingerprint query_fingerprint TYPE bloom_filter GRANULARITY 1,
    INDEX idx_query_type query_type TYPE set(20) GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_duration duration_ms TYPE minmax GRANULARITY 1,
    INDEX idx_cost total_cost TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (timestamp, caller_id)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
