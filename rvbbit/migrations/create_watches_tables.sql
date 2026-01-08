-- SQL Watch System Tables
-- Enables reactive SQL subscriptions that trigger cascades on data changes

-- ============================================================================
-- watches - Subscription definitions
-- ============================================================================
CREATE TABLE IF NOT EXISTS rvbbit.watches
(
    watch_id String,
    name String,

    -- The query to poll (supports full semantic SQL)
    query String,

    -- Action configuration
    action_type Enum8('cascade' = 1, 'signal' = 2, 'sql' = 3),
    action_spec String,  -- Cascade path, signal name, or SQL statement

    -- Polling configuration
    poll_interval_seconds UInt32 DEFAULT 300,  -- 5 minutes default

    -- State
    enabled Bool DEFAULT true,
    last_result_hash Nullable(String),
    last_checked_at Nullable(DateTime64(3)),
    last_triggered_at Nullable(DateTime64(3)),
    trigger_count UInt64 DEFAULT 0,
    consecutive_errors UInt32 DEFAULT 0,
    last_error Nullable(String),

    -- Metadata
    created_at DateTime64(3) DEFAULT now64(),
    updated_at DateTime64(3) DEFAULT now64(),
    created_by String DEFAULT '',
    description String DEFAULT '',

    -- Optional: inputs template for cascade (Jinja2)
    inputs_template String DEFAULT '{"trigger_rows": {{ rows | tojson }}, "watch_name": "{{ watch_name }}"}'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY watch_id
SETTINGS index_granularity = 8192;

-- Index for fast lookups
ALTER TABLE rvbbit.watches ADD INDEX IF NOT EXISTS idx_watch_name name TYPE bloom_filter GRANULARITY 1;
ALTER TABLE rvbbit.watches ADD INDEX IF NOT EXISTS idx_watch_enabled enabled TYPE set(2) GRANULARITY 1;


-- ============================================================================
-- watch_executions - Execution history and audit trail
-- ============================================================================
CREATE TABLE IF NOT EXISTS rvbbit.watch_executions
(
    execution_id String,
    watch_id String,
    watch_name String,

    -- Timing
    triggered_at DateTime64(3),
    completed_at Nullable(DateTime64(3)),
    duration_ms Nullable(UInt32),

    -- Trigger details
    row_count UInt32,
    result_hash String,
    result_preview String,  -- First few rows as TOON or JSON

    -- Action execution
    action_type Enum8('cascade' = 1, 'signal' = 2, 'sql' = 3),
    cascade_session_id Nullable(String),
    signal_fired Nullable(String),

    -- Status
    status Enum8('triggered' = 1, 'running' = 2, 'success' = 3, 'failed' = 4, 'skipped' = 5),
    error_message Nullable(String),

    -- Cost tracking (for cascade actions)
    cost Nullable(Decimal64(6)),
    tokens_in Nullable(UInt32),
    tokens_out Nullable(UInt32)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(triggered_at)
ORDER BY (watch_name, triggered_at)
TTL triggered_at + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;

-- Indexes for common queries
ALTER TABLE rvbbit.watch_executions ADD INDEX IF NOT EXISTS idx_exec_watch_id watch_id TYPE bloom_filter GRANULARITY 1;
ALTER TABLE rvbbit.watch_executions ADD INDEX IF NOT EXISTS idx_exec_status status TYPE set(8) GRANULARITY 1;
ALTER TABLE rvbbit.watch_executions ADD INDEX IF NOT EXISTS idx_exec_cascade_session cascade_session_id TYPE bloom_filter GRANULARITY 1;


-- ============================================================================
-- Materialized View for watch statistics
-- ============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS rvbbit.mv_watch_stats
ENGINE = SummingMergeTree
ORDER BY (watch_name)
AS SELECT
    watch_name,
    count() as execution_count,
    countIf(status = 'success') as success_count,
    countIf(status = 'failed') as failed_count,
    sum(coalesce(cost, 0)) as total_cost,
    sum(coalesce(tokens_in, 0)) as total_tokens_in,
    sum(coalesce(tokens_out, 0)) as total_tokens_out,
    avg(duration_ms) as avg_duration_ms,
    max(triggered_at) as last_triggered_at
FROM rvbbit.watch_executions
GROUP BY watch_name;
