-- Migration: Create context_shadow_assessments table
-- Date: 2025-12-30
-- Purpose: Shadow assessment of auto-context relevance for all context takes
--
-- Background:
-- When running cascades with explicit context (mode: "explicit"), we still want to
-- understand what auto-context WOULD have done. This table logs per-message relevance
-- assessments from all strategies (heuristic, semantic, LLM) for every cell transition.
--
-- This enables:
-- 1. Comparing explicit vs auto-context decisions visually
-- 2. Understanding potential token savings from auto-context
-- 3. Tuning auto-context parameters before enabling
-- 4. Training/improving the context selection models
--
-- Controlled by: RVBBIT_SHADOW_ASSESSMENT_ENABLED (default: true)

CREATE TABLE IF NOT EXISTS context_shadow_assessments (
    -- ============================================
    -- IDENTITY
    -- ============================================
    assessment_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Session context
    session_id String,
    cascade_id String,
    target_cell_name String,              -- Cell we're assessing context FOR
    target_cell_instructions String,      -- First 500 chars of cell instructions (for debugging)

    -- ============================================
    -- TAKE MESSAGE BEING ASSESSED
    -- ============================================
    source_cell_name String,              -- Cell that produced this message
    content_hash String,                  -- FK to unified_logs.content_hash
    message_role LowCardinality(String),  -- user/assistant/tool
    content_preview String,               -- First 300 chars for quick inspection
    estimated_tokens UInt32,              -- Token count of this message
    message_turn_number Nullable(UInt32), -- Turn within source cell

    -- ============================================
    -- HEURISTIC STRATEGY SCORES
    -- ============================================
    heuristic_score Float32,              -- Composite heuristic score (0-100)
    heuristic_keyword_overlap UInt16,     -- Number of keywords shared with target instructions
    heuristic_recency_score Float32,      -- Recency score (0-1, newer = higher)
    heuristic_callout_boost Float32,      -- Boost from being a callout
    heuristic_role_boost Float32,         -- Boost from role (assistant slightly higher)

    -- ============================================
    -- SEMANTIC STRATEGY SCORES
    -- ============================================
    semantic_score Nullable(Float32),     -- Cosine similarity (0-1), NULL if embeddings unavailable
    semantic_embedding_available Bool DEFAULT false,

    -- ============================================
    -- LLM STRATEGY RESULTS
    -- ============================================
    llm_selected Bool DEFAULT false,      -- Would LLM select this message?
    llm_reasoning String DEFAULT '',      -- LLM's reasoning for selection/rejection
    llm_model String DEFAULT '',          -- Model used for LLM selection
    llm_cost Nullable(Float64),           -- Cost of this LLM assessment call

    -- ============================================
    -- COMPOSITE / FINAL DETERMINATION
    -- ============================================
    composite_score Float32,              -- Weighted combination of all strategies
    would_include_heuristic Bool,         -- Would heuristic strategy include?
    would_include_semantic Bool,          -- Would semantic strategy include?
    would_include_llm Bool,               -- Would LLM strategy include?
    would_include_hybrid Bool,            -- Would hybrid strategy include?

    -- Ranking among all takes for this target cell
    rank_heuristic UInt16,
    rank_semantic Nullable(UInt16),
    rank_composite UInt16,
    total_takes UInt16,

    -- ============================================
    -- BUDGET CONTEXT
    -- ============================================
    budget_total UInt32,                  -- Token budget for this cell
    cumulative_tokens_at_rank UInt32,     -- Running total if selected up to this rank
    would_fit_budget Bool,                -- Would this fit within budget?

    -- ============================================
    -- ACTUAL VS HYPOTHETICAL
    -- ============================================
    was_actually_included Bool,           -- Did explicit mode include this?
    actual_mode LowCardinality(String),   -- 'explicit' or 'auto'

    -- ============================================
    -- ASSESSMENT METADATA
    -- ============================================
    assessment_duration_ms UInt32,        -- Time to assess this message
    assessment_batch_id String,           -- Groups assessments from same cell transition

    -- ============================================
    -- INDEXES
    -- ============================================
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_target_cell target_cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_source_cell source_cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_content_hash content_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_batch assessment_batch_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_would_include_heuristic would_include_heuristic TYPE set(2) GRANULARITY 1,
    INDEX idx_would_include_llm would_include_llm TYPE set(2) GRANULARITY 1,
    INDEX idx_was_included was_actually_included TYPE set(2) GRANULARITY 1,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_composite_score composite_score TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (session_id, target_cell_name, rank_composite)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;

-- ============================================
-- USEFUL QUERIES
-- ============================================
--
-- 1. "What would auto-context have pruned for session X?"
--    SELECT target_cell_name, source_cell_name, content_preview,
--           was_actually_included, would_include_hybrid, estimated_tokens
--    FROM context_shadow_assessments
--    WHERE session_id = 'X' AND was_actually_included AND NOT would_include_hybrid
--    ORDER BY estimated_tokens DESC
--
-- 2. "Potential token savings per session"
--    SELECT session_id,
--           SUM(CASE WHEN was_actually_included AND NOT would_include_hybrid THEN estimated_tokens ELSE 0 END) as tokens_would_save,
--           SUM(CASE WHEN was_actually_included THEN estimated_tokens ELSE 0 END) as tokens_actually_used
--    FROM context_shadow_assessments
--    GROUP BY session_id
--
-- 3. "Which source cells produce low-relevance context?"
--    SELECT source_cell_name,
--           AVG(composite_score) as avg_relevance,
--           SUM(estimated_tokens) as total_tokens,
--           countIf(was_actually_included AND NOT would_include_hybrid) as would_prune_count
--    FROM context_shadow_assessments
--    GROUP BY source_cell_name
--    ORDER BY avg_relevance ASC
--
-- 4. "LLM vs heuristic agreement rate"
--    SELECT countIf(would_include_heuristic = would_include_llm) / count() as agreement_rate
--    FROM context_shadow_assessments
--    WHERE llm_selected IS NOT NULL
