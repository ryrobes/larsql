-- Migration: SQL Cascade Executions Tracking Table
-- Date: 2026-01-02
-- Issue: Cascade registry uses in-memory dict (won't survive multi-worker deployments)
-- Solution: Store cascade execution records in ClickHouse

CREATE TABLE IF NOT EXISTS rvbbit.sql_cascade_executions (
    -- Foreign keys
    caller_id String,           -- FK to sql_query_log
    session_id String,          -- FK to unified_logs
    
    -- Cascade info
    cascade_id String,
    cascade_path String,
    
    -- Metadata
    inputs_summary String DEFAULT '',
    timestamp DateTime64(3) DEFAULT now64(3),
    
    -- Indexes for fast queries
    INDEX idx_caller caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (caller_id, timestamp)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 90 DAY;

-- Verify table exists
-- Run: clickhouse-client --database rvbbit --query "SHOW TABLES LIKE 'sql_cascade_executions'"
