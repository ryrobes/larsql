-- Migration: 013_context_shadow_assessments
-- Description: Create context_shadow_assessments table - auto-context analysis
-- Author: LARS
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS context_shadow_assessments (
    -- Identity
    assessment_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Session context
    session_id String,
    cascade_id String,
    target_cell_name String,
    target_cell_instructions String,

    -- Take message being assessed
    source_cell_name String,
    content_hash String,
    message_role LowCardinality(String),
    content_preview String,
    estimated_tokens UInt32,
    message_turn_number Nullable(UInt32),

    -- Heuristic strategy scores
    heuristic_score Float32,
    heuristic_keyword_overlap UInt16,
    heuristic_recency_score Float32,
    heuristic_callout_boost Float32,
    heuristic_role_boost Float32,

    -- Semantic strategy scores
    semantic_score Nullable(Float32),
    semantic_embedding_available Bool DEFAULT false,

    -- LLM strategy results
    llm_selected Bool DEFAULT false,
    llm_reasoning String DEFAULT '',
    llm_model String DEFAULT '',
    llm_cost Nullable(Float64),

    -- Composite determination
    composite_score Float32,
    would_include_heuristic Bool,
    would_include_semantic Bool,
    would_include_llm Bool,
    would_include_hybrid Bool,

    -- Rankings
    rank_heuristic UInt16,
    rank_semantic Nullable(UInt16),
    rank_composite UInt16,
    total_takes UInt16,

    -- Budget context
    budget_total UInt32,
    cumulative_tokens_at_rank UInt32,
    would_fit_budget Bool,

    -- Actual vs hypothetical
    was_actually_included Bool,
    actual_mode LowCardinality(String),

    -- Assessment metadata
    assessment_duration_ms UInt32,
    assessment_batch_id String,

    -- Indexes
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
