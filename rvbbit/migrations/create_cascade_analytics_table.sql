-- Migration: Create cascade_analytics table
-- Date: 2025-12-27
-- Purpose: Pre-computed context-aware analytics for cascade executions
--
-- Background:
-- Replaces naive global averages with sophisticated, context-aware comparisons:
-- - Input clustering (small vs large inputs have different baselines)
-- - Statistical anomaly detection (Z-scores, not just percentages)
-- - Multi-tier baselines (global, cluster, genus)
-- - Efficiency metrics (cost per message, cost per token)
--
-- This enables:
-- - "Compare apples to apples" (same input category)
-- - Outlier detection (cost 3σ above expected)
-- - Regression detection (recent vs historical)
-- - Cost forecasting (genus-level trends)
--
-- Computed by analytics_worker.py after each cascade execution.

CREATE TABLE IF NOT EXISTS cascade_analytics (
    -- ============================================
    -- IDENTITY & CONTEXT
    -- ============================================
    session_id String,
    cascade_id String,
    genus_hash String,                      -- Cascade invocation identity (for trending)
    created_at DateTime DEFAULT now(),

    -- ============================================
    -- INPUT CONTEXT (for clustering)
    -- ============================================
    input_complexity_score Float32,         -- 0-1 composite score (size, nesting, arrays)
    input_category LowCardinality(String),  -- 'tiny', 'small', 'medium', 'large', 'huge'
    input_fingerprint String,               -- Hash of input structure (keys + types)
    input_char_count UInt32,                -- Raw character count
    input_estimated_tokens UInt32,          -- Estimated tokens (char_count / 4)

    -- ============================================
    -- RAW METRICS (aggregated from unified_logs)
    -- ============================================
    total_cost Float64,
    total_duration_ms Float64,
    total_tokens_in UInt32,
    total_tokens_out UInt32,
    total_tokens UInt32,                    -- in + out
    message_count UInt16,                   -- Count of LLM messages
    cell_count UInt8,                       -- Count of cells executed
    error_count UInt8,                      -- Count of errors
    candidate_count UInt8 DEFAULT 0,        -- Total candidates used
    winner_candidate_index Nullable(Int8),  -- Which candidate won (if candidates)

    -- ============================================
    -- CONTEXT-AWARE BASELINES
    -- ============================================
    -- Global: All historical runs for this cascade
    global_avg_cost Float64,
    global_avg_duration Float64,
    global_avg_tokens Float64,
    global_run_count UInt32,

    -- Cluster: Same input_category (apples to apples!)
    cluster_avg_cost Float64,
    cluster_stddev_cost Float64,            -- For Z-score calculation
    cluster_avg_duration Float64,
    cluster_stddev_duration Float64,
    cluster_avg_tokens Float64,
    cluster_stddev_tokens Float64,
    cluster_run_count UInt32,

    -- Genus: Same genus_hash (most specific!)
    genus_avg_cost Nullable(Float64),
    genus_avg_duration Nullable(Float64),
    genus_run_count UInt16,

    -- ============================================
    -- ANOMALY SCORES (Statistical!)
    -- ============================================
    cost_z_score Float32,                   -- (cost - cluster_avg) / cluster_stddev
    duration_z_score Float32,
    tokens_z_score Float32,

    -- Anomaly flags (|z| > 2 = top/bottom 5%)
    is_cost_outlier Bool,                   -- |cost_z_score| > 2
    is_duration_outlier Bool,
    is_tokens_outlier Bool,

    -- ============================================
    -- EFFICIENCY METRICS
    -- ============================================
    cost_per_message Float32,               -- total_cost / message_count
    cost_per_token Float32,                 -- total_cost / total_tokens
    duration_per_message Float32,           -- duration_ms / message_count
    tokens_per_message Float32,             -- total_tokens / message_count

    -- ============================================
    -- MODEL ANALYSIS
    -- ============================================
    models_used Array(String),              -- Unique models in this run
    primary_model String,                   -- Most-used model
    model_switches UInt8,                   -- Count of model changes

    -- ============================================
    -- TEMPORAL CONTEXT (for time-of-day patterns)
    -- ============================================
    hour_of_day UInt8,                      -- 0-23
    day_of_week UInt8,                      -- 0-6 (Monday=0)
    is_weekend Bool,

    -- ============================================
    -- METADATA
    -- ============================================
    analyzed_at DateTime DEFAULT now(),
    analysis_version UInt8 DEFAULT 1        -- Schema version for future changes
)
ENGINE = MergeTree()
ORDER BY (cascade_id, created_at, session_id)
PARTITION BY toYYYYMM(created_at);  -- Monthly partitions for fast time-range queries

-- ============================================
-- INDEXES for fast queries
-- ============================================

-- Genus hash (trending queries)
ALTER TABLE cascade_analytics ADD INDEX IF NOT EXISTS idx_genus genus_hash TYPE bloom_filter GRANULARITY 1;

-- Input category (cluster comparisons)
ALTER TABLE cascade_analytics ADD INDEX IF NOT EXISTS idx_input_category input_category TYPE set(0) GRANULARITY 1;

-- Outlier flags (anomaly queries)
ALTER TABLE cascade_analytics ADD INDEX IF NOT EXISTS idx_cost_outlier is_cost_outlier TYPE set(0) GRANULARITY 1;
ALTER TABLE cascade_analytics ADD INDEX IF NOT EXISTS idx_duration_outlier is_duration_outlier TYPE set(0) GRANULARITY 1;

-- Cascade ID (per-cascade analytics)
ALTER TABLE cascade_analytics ADD INDEX IF NOT EXISTS idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1;
