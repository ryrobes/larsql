-- Migration: 035_bi_intent
-- Description: Create BI of Intent tables - understandings, usage tracking, and promoted metrics
-- Author: LARS
-- Date: 2026-01-19

-- =============================================================================
-- bi_understandings: Stores investigation results as reusable understanding docs
-- =============================================================================
-- Each understanding captures:
-- - What the question means (semantic definition)
-- - How to compute it (data sources, query patterns)
-- - Why it's defined this way (reasoning, change history)
-- - The understanding doc serves as the "prompt" for future queries

CREATE TABLE IF NOT EXISTS bi_understandings (
    -- Identity
    understanding_id String,

    -- The canonical question this understanding answers
    question String,
    question_embedding Array(Float32),

    -- The full understanding document (markdown)
    -- This is verbose - captures reasoning, not just SQL
    understanding_doc String CODEC(ZSTD(3)),

    -- Version tracking (understandings evolve)
    version UInt32 DEFAULT 1,
    parent_version_id Nullable(String),

    -- Data lineage
    source_tables Array(String),
    key_columns Array(String),
    join_patterns Array(String),

    -- The generated query pattern (not the query itself - that's ephemeral)
    query_pattern String CODEC(ZSTD(3)),

    -- Classification
    answer_type LowCardinality(String),  -- scalar, breakdown, timeseries, finding, insight

    -- Confidence and quality
    confidence Float32 DEFAULT 0.0,
    validation_status LowCardinality(String) DEFAULT 'unvalidated',  -- unvalidated, validated, stale

    -- Timestamps
    created_at DateTime64(3) DEFAULT now64(),
    updated_at DateTime64(3) DEFAULT now64(),
    last_used_at DateTime64(3) DEFAULT now64(),

    -- Creator tracking
    created_by String DEFAULT '',

    -- Indexes
    INDEX idx_question question TYPE tokenbf_v1(10240, 3, 0) GRANULARITY 1,
    INDEX idx_answer_type answer_type TYPE set(20) GRANULARITY 1,
    INDEX idx_source_tables source_tables TYPE bloom_filter() GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1,
    INDEX idx_last_used last_used_at TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (understanding_id)
SETTINGS index_granularity = 8192;


-- =============================================================================
-- bi_understanding_usage: Tracks how understandings are invoked
-- =============================================================================
-- This captures usage patterns to:
-- 1. Detect emergence (frequently used = promote to metric)
-- 2. Discover polymorphic modes (BY region, OVER time, TREND, etc.)
-- 3. Track which users rely on which understandings

CREATE TABLE IF NOT EXISTS bi_understanding_usage (
    -- Identity
    usage_id String,
    understanding_id String,

    -- The actual query that triggered this usage
    original_question String,

    -- Mode detection: what modifiers/context were used?
    -- e.g., "BY region", "OVER last_30_days", "TREND", "COMPARED TO last_year"
    detected_mode LowCardinality(String) DEFAULT 'scalar',
    mode_modifiers Array(String),  -- ['BY', 'region'], ['OVER', 'last_30_days']

    -- Did we reuse existing understanding or was this a new match?
    match_type LowCardinality(String),  -- exact, semantic, new
    similarity_score Float32 DEFAULT 1.0,

    -- Context from the query
    time_range_requested String DEFAULT '',
    dimensions_requested Array(String),
    filters_requested Array(String),

    -- What was returned
    output_type LowCardinality(String),  -- scalar, array, timeseries, viz_spec

    -- Session tracking
    session_id String DEFAULT '',
    user_id String DEFAULT '',

    -- Timestamp
    created_at DateTime64(3) DEFAULT now64(),

    -- Indexes
    INDEX idx_understanding understanding_id TYPE set(1000) GRANULARITY 1,
    INDEX idx_mode detected_mode TYPE set(50) GRANULARITY 1,
    INDEX idx_user user_id TYPE set(1000) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (understanding_id, created_at)
SETTINGS index_granularity = 8192;


-- =============================================================================
-- promoted_metrics: Understandings promoted to first-class SQL operators
-- =============================================================================
-- When an understanding is used frequently enough, it can be "promoted"
-- to become a named SQL operator (e.g., SELECT REVENUE BY region)

CREATE TABLE IF NOT EXISTS promoted_metrics (
    -- Identity - this becomes the SQL function name
    metric_name String,

    -- Link to source understanding
    understanding_id String,

    -- Denormalized for fast lookup during query execution
    understanding_doc String CODEC(ZSTD(3)),

    -- Discovered modes from usage patterns
    -- Each mode is: {pattern, output_type, usage_count, first_seen, example_queries}
    modes String CODEC(ZSTD(3)),  -- JSON array

    -- Data lineage (denormalized from understanding)
    source_tables Array(String),
    key_columns Array(String),

    -- Promotion metadata
    promoted_at DateTime64(3) DEFAULT now64(),
    promoted_by String DEFAULT '',
    promotion_reason String DEFAULT '',  -- e.g., "50 uses by 8 users over 7 days"

    -- Usage stats (updated periodically)
    total_usage_count UInt64 DEFAULT 0,
    unique_users UInt32 DEFAULT 0,
    last_used_at DateTime64(3) DEFAULT now64(),

    -- Status
    status LowCardinality(String) DEFAULT 'active',  -- active, deprecated, archived

    -- Indexes
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_promoted promoted_at TYPE minmax GRANULARITY 1,
    INDEX idx_source_tables source_tables TYPE bloom_filter() GRANULARITY 1
)
ENGINE = ReplacingMergeTree(last_used_at)
ORDER BY (metric_name)
SETTINGS index_granularity = 8192;


-- =============================================================================
-- bi_metric_modes: Discovered polymorphic modes for metrics
-- =============================================================================
-- Tracks the different ways a metric can be invoked
-- Modes emerge from usage patterns and can be added over time

CREATE TABLE IF NOT EXISTS bi_metric_modes (
    -- Identity
    mode_id String,
    metric_name String,

    -- The mode pattern (regex or template)
    -- e.g., "{{ metric }} BY {{ dimension }}"
    pattern String,
    pattern_type LowCardinality(String) DEFAULT 'template',  -- template, regex

    -- What this mode produces
    output_type LowCardinality(String),  -- scalar, breakdown, timeseries, comparison, finding

    -- Example queries that created/used this mode
    example_queries Array(String),

    -- Usage tracking
    usage_count UInt64 DEFAULT 0,
    first_seen DateTime64(3) DEFAULT now64(),
    last_used_at DateTime64(3) DEFAULT now64(),

    -- Indexes
    INDEX idx_metric metric_name TYPE set(1000) GRANULARITY 1,
    INDEX idx_output output_type TYPE set(20) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(last_used_at)
ORDER BY (metric_name, mode_id)
SETTINGS index_granularity = 8192;
