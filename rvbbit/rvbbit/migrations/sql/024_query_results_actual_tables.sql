-- Migration: 024_query_results_actual_tables
-- Description: Evolve query_results to be a log/index pointing to actual materialized tables
-- Author: RVBBIT
-- Date: 2026-01-10
--
-- Architecture change:
-- Before: query_results stored JSON-serialized rows (defeats ClickHouse columnar benefits)
-- After:  query_results is a LOG/INDEX table pointing to actual result tables
--
-- Result tables: rvbbit_results.r_<sanitized_caller_id>
-- Benefits:
-- - Full columnar storage benefits (compression, vectorized queries)
-- - Results queryable with SQL JOINs, aggregations, etc.
-- - Proper data types preserved
-- - No JSON parsing overhead

-- Drop old table and recreate with new schema
DROP TABLE IF EXISTS rvbbit_results.query_results;

-- Create the query results LOG table (no actual data, just metadata)
CREATE TABLE IF NOT EXISTS rvbbit_results.query_results (
    -- Identity (matches sql_query_log)
    caller_id String,
    query_id String,

    -- Reference to actual result table
    result_table String,  -- e.g., "r_abc123def456"

    -- Timestamps
    created_at DateTime64(6) DEFAULT now64(6),
    expire_date Date DEFAULT today() + INTERVAL 30 DAY,

    -- Schema information (for quick lookup without querying result table)
    columns Array(String),           -- Column names: ["name", "age", "email"]
    column_types Array(String),      -- Column types: ["String", "Int64", "String"]

    -- Metrics
    row_count UInt64,
    column_count UInt16,

    -- Source info (for debugging/provenance)
    source_database String DEFAULT '',    -- Original database name from connection
    source_query String CODEC(ZSTD(3)),   -- The SQL query that produced these results

    -- Cleanup tracking
    is_dropped Bool DEFAULT false,        -- True if result table has been dropped

    -- Indexes for fast lookup
    INDEX idx_caller caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_query_id query_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_result_table result_table TYPE bloom_filter GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1,
    INDEX idx_expire expire_date TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (caller_id, created_at)
PARTITION BY toYYYYMM(created_at)
TTL expire_date
SETTINGS index_granularity = 8192;
