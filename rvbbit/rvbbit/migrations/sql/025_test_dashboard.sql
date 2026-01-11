-- Migration: 025_test_dashboard
-- Description: Create tables for test dashboard - tracks test runs and individual results
-- Author: RVBBIT
-- Date: 2026-01-11

-- ============================================================================
-- test_runs: Batch execution metadata (one row per test run)
-- ============================================================================
CREATE TABLE IF NOT EXISTS test_runs (
    -- Identity
    run_id String,

    -- Run classification
    run_type Enum8('semantic_sql' = 1, 'cascade_snapshot' = 2, 'mixed' = 3),

    -- Timing
    started_at DateTime64(3) DEFAULT now64(3),
    completed_at Nullable(DateTime64(3)),
    duration_ms Float64 DEFAULT 0,

    -- Status
    status Enum8('running' = 1, 'passed' = 2, 'failed' = 3, 'error' = 4, 'cancelled' = 5),

    -- Counts
    total_tests UInt32 DEFAULT 0,
    passed_tests UInt32 DEFAULT 0,
    failed_tests UInt32 DEFAULT 0,
    skipped_tests UInt32 DEFAULT 0,
    error_tests UInt32 DEFAULT 0,

    -- Trigger info
    trigger Enum8('manual' = 1, 'ci' = 2, 'scheduled' = 3, 'hook' = 4, 'api' = 5) DEFAULT 'manual',
    trigger_source String DEFAULT '',  -- CI job ID, cron expression, hook name, etc.

    -- Environment
    git_commit String DEFAULT '',
    git_branch String DEFAULT '',
    git_dirty UInt8 DEFAULT 0,

    -- Configuration
    test_filter String DEFAULT '',     -- e.g., "semantic_sql/*" or "snapshots/routing*"
    run_options String DEFAULT '',     -- JSON of options used (verbose, mode, etc.)

    -- Error info (for status=error)
    error_message String DEFAULT '',
    error_traceback String DEFAULT '' CODEC(ZSTD(3)),

    -- Indexes
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_run_type run_type TYPE set(10) GRANULARITY 1,
    INDEX idx_trigger trigger TYPE set(10) GRANULARITY 1,
    INDEX idx_git_commit git_commit TYPE bloom_filter GRANULARITY 1,
    INDEX idx_started_at started_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (started_at, run_id)
PARTITION BY toYYYYMM(started_at);


-- ============================================================================
-- test_results: Individual test outcomes (many rows per test run)
-- ============================================================================
CREATE TABLE IF NOT EXISTS test_results (
    -- Link to run
    run_id String,

    -- Test identity
    test_id String,                    -- Unique test identifier
    test_type Enum8('semantic_sql' = 1, 'cascade_snapshot' = 2),
    test_group String,                 -- e.g., "semantic_sql/implies" or "snapshots"
    test_name String,                  -- Human-readable name
    test_description String DEFAULT '',

    -- Source file info
    source_file String DEFAULT '',     -- Path to cascade file or snapshot
    source_line UInt32 DEFAULT 0,      -- Line number in source (for SQL tests)

    -- Timing
    started_at DateTime64(3) DEFAULT now64(3),
    completed_at Nullable(DateTime64(3)),
    duration_ms Float64 DEFAULT 0,

    -- Result
    status Enum8('pending' = 0, 'running' = 1, 'passed' = 2, 'failed' = 3, 'error' = 4, 'skipped' = 5),

    -- For semantic SQL tests
    sql_query String DEFAULT '' CODEC(ZSTD(3)),
    expected_value String DEFAULT '' CODEC(ZSTD(3)),
    actual_value String DEFAULT '' CODEC(ZSTD(3)),
    expect_type String DEFAULT '',     -- "exact", "contains", "regex", "true/false"

    -- For cascade snapshot tests
    validation_mode String DEFAULT '', -- "structure", "contracts", "anchors", "deterministic", "full"
    cells_validated UInt32 DEFAULT 0,
    contracts_checked UInt32 DEFAULT 0,
    contracts_passed UInt32 DEFAULT 0,
    anchors_checked UInt32 DEFAULT 0,
    anchors_passed UInt32 DEFAULT 0,

    -- LLM Judge results (for anchors mode)
    judge_score Nullable(Float32),
    judge_reasoning String DEFAULT '' CODEC(ZSTD(3)),

    -- Failure details
    failure_type String DEFAULT '',    -- "assertion", "timeout", "exception", "contract", "anchor"
    failure_message String DEFAULT '' CODEC(ZSTD(3)),
    failure_diff String DEFAULT '' CODEC(ZSTD(3)),  -- For showing expected vs actual

    -- Exception info (for error status)
    error_type String DEFAULT '',
    error_message String DEFAULT '' CODEC(ZSTD(3)),
    error_traceback String DEFAULT '' CODEC(ZSTD(3)),

    -- Indexes
    INDEX idx_run_id run_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_test_type test_type TYPE set(10) GRANULARITY 1,
    INDEX idx_test_group test_group TYPE bloom_filter GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_source_file source_file TYPE bloom_filter GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (run_id, test_type, test_group, test_id)
PARTITION BY toYYYYMM(started_at);


-- ============================================================================
-- test_summary_mv: Materialized view for dashboard stats
-- ============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_test_summary
ENGINE = SummingMergeTree()
ORDER BY (date, test_type, test_group)
AS SELECT
    toDate(started_at) AS date,
    test_type,
    test_group,
    status,
    count() AS test_count,
    sum(duration_ms) AS total_duration_ms,
    avg(duration_ms) AS avg_duration_ms
FROM test_results
GROUP BY date, test_type, test_group, status;


-- ============================================================================
-- test_flaky_detection: Track flaky tests over time
-- ============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_test_flaky_detection
ENGINE = AggregatingMergeTree()
ORDER BY (test_id, test_type)
AS SELECT
    test_id,
    test_type,
    test_group,
    test_name,
    count() AS total_runs,
    countIf(status = 'passed') AS pass_count,
    countIf(status = 'failed') AS fail_count,
    countIf(status = 'error') AS error_count,
    -- Flakiness score: tests that sometimes pass and sometimes fail
    -- Higher score = more flaky
    if(
        countIf(status = 'passed') > 0 AND countIf(status IN ('failed', 'error')) > 0,
        least(countIf(status = 'passed'), countIf(status IN ('failed', 'error'))) * 2.0 / count(),
        0
    ) AS flakiness_score,
    min(started_at) AS first_seen,
    max(started_at) AS last_seen,
    avgIf(duration_ms, status = 'passed') AS avg_pass_duration_ms,
    avgIf(duration_ms, status = 'failed') AS avg_fail_duration_ms
FROM test_results
GROUP BY test_id, test_type, test_group, test_name;
