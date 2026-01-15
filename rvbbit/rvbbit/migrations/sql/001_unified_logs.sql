-- Migration: 001_unified_logs
-- Description: Create unified_logs table - main execution logging
-- Author: RVBBIT
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS unified_logs (
    -- Core Identification
    message_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),
    timestamp_iso String,
    session_id String,
    trace_id String,
    parent_id Nullable(String),
    parent_session_id Nullable(String),
    parent_message_id Nullable(String),

    -- Caller Tracking (for cost rollup and debugging)
    caller_id String DEFAULT '',
    invocation_metadata_json String DEFAULT '{}' CODEC(ZSTD(3)),

    -- SQL UDF Tracking (for SQL Trail analytics)
    is_sql_udf Bool DEFAULT false,
    udf_type LowCardinality(Nullable(String)),
    cache_hit Bool DEFAULT false,
    input_hash Nullable(String),

    -- SQL Source Lineage (for row/column tracking in semantic SQL)
    source_column_name Nullable(String),
    source_row_index Nullable(Int64),
    source_table_name Nullable(String),

    -- Classification
    node_type LowCardinality(String),
    role LowCardinality(String),
    depth UInt8 DEFAULT 0,

    -- Semantic Classification (human-readable for debugging)
    semantic_actor LowCardinality(Nullable(String)),
    semantic_purpose LowCardinality(Nullable(String)),

    -- Execution Context (Takes/Reforge)
    take_index Nullable(Int32),
    is_winner Nullable(Bool),
    reforge_step Nullable(Int32),
    winning_take_index Nullable(Int32),
    attempt_number Nullable(Int32),
    turn_number Nullable(Int32),
    mutation_applied Nullable(String),
    mutation_type LowCardinality(Nullable(String)),
    mutation_template Nullable(String),

    -- Cascade Context
    cascade_id Nullable(String),
    cascade_file Nullable(String),
    cascade_json Nullable(String) CODEC(ZSTD(3)),
    cell_name Nullable(String),
    cell_json Nullable(String) CODEC(ZSTD(3)),
    species_hash Nullable(String),

    -- LLM Provider
    model Nullable(String),
    model_requested Nullable(String),
    request_id Nullable(String),
    provider LowCardinality(Nullable(String)),

    -- Performance Metrics
    duration_ms Nullable(Float64),
    tokens_in Nullable(Int32),
    tokens_out Nullable(Int32),
    total_tokens Nullable(Int32),
    cost Nullable(Float64),

    -- Reasoning Tokens (OpenRouter extended thinking)
    reasoning_enabled Nullable(Bool),
    reasoning_effort LowCardinality(Nullable(String)),
    reasoning_max_tokens Nullable(Int32),
    tokens_reasoning Nullable(Int32),

    -- Token Budget Enforcement
    budget_strategy LowCardinality(Nullable(String)),
    budget_tokens_before Nullable(Int32),
    budget_tokens_after Nullable(Int32),
    budget_tokens_limit Nullable(Int32),
    budget_tokens_pruned Nullable(Int32),
    budget_percentage Nullable(Float32),

    -- Content (stored as JSON strings for flexibility)
    content_json Nullable(String),
    full_request_json Nullable(String) CODEC(ZSTD(3)),
    full_response_json Nullable(String) CODEC(ZSTD(3)),
    tool_calls_json Nullable(String),

    -- Binary Artifact References
    images_json Nullable(String),
    has_images Bool DEFAULT false,
    has_base64 Bool DEFAULT false,
    has_base64_stripped Bool DEFAULT false,
    videos_json Nullable(String),
    has_videos Bool DEFAULT false,
    audio_json Nullable(String),
    has_audio Bool DEFAULT false,

    -- Mermaid Diagram State
    mermaid_content Nullable(String),

    -- Content Identity & Context Tracking
    content_hash Nullable(String),
    context_hashes Array(String) DEFAULT [],
    estimated_tokens Nullable(Int32),

    -- Vector Embeddings (optional - populated on demand)
    content_embedding Array(Float32) DEFAULT [],
    request_embedding Array(Float32) DEFAULT [],
    embedding_model LowCardinality(Nullable(String)),
    embedding_dim Nullable(UInt16),

    -- Callouts (semantic message tagging for UIs/queries)
    is_callout Bool DEFAULT false,
    callout_name Nullable(String),

    -- Metadata
    metadata_json Nullable(String),

    -- Indexes for common query patterns
    INDEX idx_session_id session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_caller_id caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell_name cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_species_hash species_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_trace_id trace_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_node_type node_type TYPE set(100) GRANULARITY 1,
    INDEX idx_role role TYPE set(10) GRANULARITY 1,
    INDEX idx_is_winner is_winner TYPE set(2) GRANULARITY 1,
    INDEX idx_is_callout is_callout TYPE set(2) GRANULARITY 1,
    INDEX idx_cost cost TYPE minmax GRANULARITY 4,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_is_sql_udf is_sql_udf TYPE set(2) GRANULARITY 1,
    INDEX idx_udf_type udf_type TYPE set(10) GRANULARITY 1,
    INDEX idx_cache_hit cache_hit TYPE set(2) GRANULARITY 1,
    INDEX idx_source_column source_column_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_source_row source_row_index TYPE minmax GRANULARITY 4
)
ENGINE = MergeTree()
ORDER BY (session_id, timestamp, trace_id)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 1 YEAR
SETTINGS index_granularity = 8192;
