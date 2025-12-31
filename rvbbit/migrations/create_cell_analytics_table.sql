-- Migration: Create cell_analytics table
-- Date: 2025-12-27
-- Purpose: Per-cell analytics for bottleneck detection and optimization
--
-- Background:
-- While cascade_analytics tracks whole cascade runs, cell_analytics tracks
-- individual cell executions. This is critical because:
-- - Metrics don't roll up naturally (which cell is slow? which cell is expensive?)
-- - Cell-level anomalies indicate specific problems (not just "cascade is slow")
-- - Enables per-cell optimization (target the bottleneck, not everything)
--
-- Example insights:
-- - "Cell 'extract' is 3x slower than usual for medium inputs"
-- - "Cell 'validate' costs spiked 200% this week"
-- - "Cell 'enrich' uses 90% of cascade tokens"

CREATE TABLE IF NOT EXISTS cell_analytics (
    -- ============================================
    -- IDENTITY & CONTEXT
    -- ============================================
    session_id String,
    cascade_id String,
    cell_name String,
    species_hash String,                    -- Cell execution identity
    genus_hash String,                      -- Parent cascade identity
    created_at DateTime DEFAULT now(),

    -- ============================================
    -- CELL TYPE & CONFIG
    -- ============================================
    cell_type LowCardinality(String),       -- 'llm', 'deterministic', 'image_gen', etc.
    tool Nullable(String),                  -- For deterministic cells
    model Nullable(String),                 -- For LLM cells

    -- ============================================
    -- RAW METRICS
    -- ============================================
    cell_cost Float64,
    cell_duration_ms Float64,               -- Wall time for this cell
    cell_tokens_in UInt32,
    cell_tokens_out UInt32,
    cell_tokens UInt32,
    message_count UInt16,                   -- Messages within this cell
    turn_count UInt8,                       -- Conversation turns
    candidate_count UInt8 DEFAULT 0,        -- Candidates used
    error_occurred Bool DEFAULT false,

    -- ============================================
    -- CONTEXT-AWARE BASELINES (Cell-Specific!)
    -- ============================================
    -- Global: All historical runs of THIS CELL
    global_cell_avg_cost Float64,
    global_cell_avg_duration Float64,
    global_cell_run_count UInt32,

    -- Species: Same species_hash (exact cell config)
    species_avg_cost Float64,
    species_stddev_cost Float64,
    species_avg_duration Float64,
    species_stddev_duration Float64,
    species_run_count UInt32,

    -- ============================================
    -- ANOMALY SCORES (Cell-Level!)
    -- ============================================
    cost_z_score Float32,
    duration_z_score Float32,
    is_cost_outlier Bool,
    is_duration_outlier Bool,

    -- ============================================
    -- EFFICIENCY METRICS
    -- ============================================
    cost_per_turn Float32,
    cost_per_token Float32,
    tokens_per_turn Float32,
    duration_per_turn Float32,

    -- ============================================
    -- CASCADE CONTEXT (for filtering)
    -- ============================================
    cascade_total_cost Float64,             -- Total cascade cost (for % contribution)
    cascade_total_duration Float64,         -- Total cascade duration
    cell_cost_pct Float32,                  -- This cell's % of total cascade cost
    cell_duration_pct Float32,              -- This cell's % of total cascade duration

    -- ============================================
    -- POSITION IN CASCADE
    -- ============================================
    cell_index UInt8,                       -- Position in cascade (0, 1, 2...)
    is_first_cell Bool,
    is_last_cell Bool,

    -- ============================================
    -- METADATA
    -- ============================================
    analyzed_at DateTime DEFAULT now(),
    analysis_version UInt8 DEFAULT 1
)
ENGINE = MergeTree()
ORDER BY (cascade_id, cell_name, created_at, session_id)
PARTITION BY toYYYYMM(created_at);

-- ============================================
-- INDEXES
-- ============================================

-- Species hash (cell config comparison)
ALTER TABLE cell_analytics ADD INDEX IF NOT EXISTS idx_species species_hash TYPE bloom_filter GRANULARITY 1;

-- Genus hash (filter by cascade invocation)
ALTER TABLE cell_analytics ADD INDEX IF NOT EXISTS idx_genus genus_hash TYPE bloom_filter GRANULARITY 1;

-- Cell name (per-cell queries)
ALTER TABLE cell_analytics ADD INDEX IF NOT EXISTS idx_cell_name cell_name TYPE bloom_filter GRANULARITY 1;

-- Outlier flags (anomaly detection)
ALTER TABLE cell_analytics ADD INDEX IF NOT EXISTS idx_cell_cost_outlier is_cost_outlier TYPE set(0) GRANULARITY 1;
ALTER TABLE cell_analytics ADD INDEX IF NOT EXISTS idx_cell_duration_outlier is_duration_outlier TYPE set(0) GRANULARITY 1;

-- Cascade ID (per-cascade cell analysis)
ALTER TABLE cell_analytics ADD INDEX IF NOT EXISTS idx_cell_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1;
