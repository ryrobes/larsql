-- Migration: 015_ui_sql_log
-- Description: Create ui_sql_log table - query performance tracking
-- Author: RVBBIT
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS ui_sql_log (
    -- Timing
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Query info
    query_type LowCardinality(String),
    sql_preview String,
    sql_hash String,

    -- Metrics
    duration_ms Float64,
    rows_returned Nullable(Int32),
    rows_affected Nullable(Int32),

    -- Context
    source LowCardinality(String) DEFAULT 'unknown',
    caller Nullable(String),
    request_path Nullable(String),
    page_ref Nullable(String),

    -- Error tracking
    success Bool DEFAULT true,
    error_message Nullable(String),

    -- Indexes for analysis queries
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_duration duration_ms TYPE minmax GRANULARITY 1,
    INDEX idx_query_type query_type TYPE set(20) GRANULARITY 1,
    INDEX idx_sql_hash sql_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_source source TYPE set(20) GRANULARITY 1,
    INDEX idx_success success TYPE set(2) GRANULARITY 1,
    INDEX idx_page_ref page_ref TYPE bloom_filter GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (timestamp, query_type)
PARTITION BY toYYYYMMDD(timestamp)
TTL timestamp + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;
