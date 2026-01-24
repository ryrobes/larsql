-- Migration: 039_perf_metrics
-- Description: Performance metrics table for cascade execution profiling
-- Author: LARS
-- Date: 2026-01-23

CREATE TABLE IF NOT EXISTS perf_metrics (
    -- Core Identification
    metric_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Metric Classification
    label LowCardinality(String),  -- e.g., "config_load", "agent_call", "tool_execution"

    -- Timing (stored in both nanoseconds and milliseconds for convenience)
    duration_ns UInt64,  -- High precision for aggregation
    duration_ms Float64, -- Human-readable, pre-computed

    -- Execution Context
    session_id String DEFAULT '',
    cascade_id String DEFAULT '',
    cell_name String DEFAULT '',

    -- Additional Metadata (JSON for flexibility)
    metadata_json String DEFAULT '{}' CODEC(ZSTD(3)),

    -- Exception Tracking
    exception_occurred UInt8 DEFAULT 0,  -- 0 = success, 1 = exception
    exception_type LowCardinality(String) DEFAULT '',

    -- Indexes for common query patterns
    INDEX idx_label label TYPE set(100) GRANULARITY 1,
    INDEX idx_session_id session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell_name cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_duration_ms duration_ms TYPE minmax GRANULARITY 4,
    INDEX idx_exception exception_occurred TYPE set(2) GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (label, timestamp)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 6 MONTH  -- Keep metrics for 6 months (can be extended if needed)
SETTINGS index_granularity = 8192;
