-- Migration: SQL Trail Tables and Columns
-- Purpose: Track SQL queries that use LARS UDFs for query-level analytics
--
-- Background:
-- SQL semantic queries have different patterns than traditional cascades:
-- - One SQL query spawns hundreds/thousands of LLM calls
-- - Cache hit rate is critical for cost optimization
-- - Pattern analysis matters more than individual outliers
-- - caller_id groups all calls from a single SQL query
--
-- New table: sql_query_log
-- - Tracks individual SQL queries with UDF calls
-- - Stores fingerprint (AST-normalized hash) for pattern grouping
-- - Aggregates cache hits/misses and cost metrics
--
-- New unified_logs columns:
-- - is_sql_udf: Flag for SQL UDF-originated sessions
-- - udf_type: Which UDF function was called
-- - cache_hit: Whether this call was a cache hit
-- - input_hash: Hash of UDF input for cache correlation

-- ============================================
-- Create sql_query_log table
-- ============================================

CREATE TABLE IF NOT EXISTS sql_query_log (
    -- Identity
    query_id UUID DEFAULT generateUUIDv4(),
    caller_id String,

    -- Query Content
    query_raw String CODEC(ZSTD(3)),
    query_fingerprint String,  -- AST-normalized hash
    query_template String CODEC(ZSTD(3)),  -- Parameterized SQL
    query_type LowCardinality(String),  -- 'lars_udf', 'lars_cascade_udf', etc.

    -- UDF Detection
    udf_types Array(String) DEFAULT [],
    udf_count UInt16 DEFAULT 0,
    cascade_paths Array(String) DEFAULT [],

    -- Execution
    started_at DateTime64(6),
    completed_at Nullable(DateTime64(6)),
    duration_ms Nullable(Float64),
    status LowCardinality(String),  -- 'running', 'completed', 'error'

    -- Row Metrics
    rows_input Nullable(Int32),
    rows_output Nullable(Int32),

    -- Cost (aggregated from spawned sessions)
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

    INDEX idx_caller caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_fingerprint query_fingerprint TYPE bloom_filter GRANULARITY 1,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (timestamp, caller_id)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 90 DAY;

-- ============================================
-- Add SQL Trail columns to unified_logs
-- ============================================

-- Flag to identify sessions spawned from SQL UDFs
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS is_sql_udf Bool DEFAULT false AFTER caller_id;

-- Which UDF type was called
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS udf_type LowCardinality(Nullable(String)) AFTER is_sql_udf;

-- Whether this specific call was a cache hit
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS cache_hit Bool DEFAULT false AFTER udf_type;

-- Hash of UDF input for cache correlation analysis
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS input_hash Nullable(String) AFTER cache_hit;

-- For backward compatibility: existing rows will have is_sql_udf = false, cache_hit = false
-- This correctly represents "not tracked" for historical sessions.

-- ============================================
-- Add Result Location columns to sql_query_log
-- ============================================
-- For auto-materialized LARS query results, we track where the data is stored
-- so it can be retrieved and displayed in the SQL Trail UI.

-- Database name used in pgwire connection (e.g., 'myproject', 'analytics')
ALTER TABLE sql_query_log ADD COLUMN IF NOT EXISTS result_db_name Nullable(String) AFTER error_message;

-- Full path to the DuckDB file (e.g., '/home/user/lars/session_dbs/myproject.duckdb')
ALTER TABLE sql_query_log ADD COLUMN IF NOT EXISTS result_db_path Nullable(String) AFTER result_db_name;

-- Schema name within DuckDB (e.g., '_results_20260103')
ALTER TABLE sql_query_log ADD COLUMN IF NOT EXISTS result_schema Nullable(String) AFTER result_db_path;

-- Table name within the schema (e.g., 'q_abc12345')
ALTER TABLE sql_query_log ADD COLUMN IF NOT EXISTS result_table Nullable(String) AFTER result_schema;
