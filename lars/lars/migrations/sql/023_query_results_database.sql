-- Migration: 023_query_results_database
-- Description: Create separate lars_results database for query result storage
-- Author: LARS
-- Date: 2026-01-10
--
-- This creates a separate database for storing materialized query results.
-- Benefits over previous DuckDB/Parquet approach:
-- - No file locking issues (ClickHouse handles concurrency natively)
-- - No is_persistent_db gate (all queries can have results saved)
-- - Built-in TTL for automatic cleanup
-- - Simpler API code (single query vs complex fallback logic)
-- - Results accessible from any machine with ClickHouse access

-- Create the separate database
CREATE DATABASE IF NOT EXISTS lars_results;

-- Create the query results table
CREATE TABLE IF NOT EXISTS lars_results.query_results (
    -- Identity (matches sql_query_log)
    caller_id String,
    query_id String,

    -- Timestamps
    created_at DateTime64(6) DEFAULT now64(6),
    expire_date Date DEFAULT today() + INTERVAL 30 DAY,

    -- Schema information (flexible - each query can have different columns)
    columns Array(String),           -- Column names: ["name", "age", "email"]
    column_types Array(String),      -- Column types: ["VARCHAR", "INT64", "VARCHAR"]

    -- Result data (JSON-encoded for flexibility)
    -- Format: [[val1, val2, ...], [val1, val2, ...], ...]
    rows_json String CODEC(ZSTD(3)),

    -- Metrics
    row_count UInt64,
    column_count UInt16,

    -- Source info (for debugging/provenance)
    source_database String DEFAULT '',    -- Original database name from connection
    source_query String CODEC(ZSTD(3)),   -- The SQL query that produced these results

    -- Indexes for fast lookup
    INDEX idx_caller caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_query_id query_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (caller_id, created_at)
PARTITION BY toYYYYMM(created_at)
TTL expire_date
SETTINGS index_granularity = 8192;
