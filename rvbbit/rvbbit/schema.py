"""
ClickHouse schema definitions for RVBBIT logging system.

This module defines all table schemas for the pure ClickHouse implementation.
Tables are auto-created on startup by ClickHouseAdapter._ensure_tables().

Tables:
- unified_logs: Main execution logs (messages, tool calls, etc.)
- checkpoints: Human-in-the-loop checkpoints
- training_preferences: DPO/RLHF training data
- rag_chunks: RAG vector storage
- rag_manifests: RAG document metadata
- evaluations: Hot-or-not ratings
"""

# =============================================================================
# UNIFIED LOGS TABLE - Main execution logging
# =============================================================================
# This is the core table that captures all logging data with complete context
# for analytics, debugging, and reconstruction of execution flows.

UNIFIED_LOGS_SCHEMA = """
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

    -- Caller Tracking (NEW - for cost rollup and debugging)
    caller_id String DEFAULT '',
    invocation_metadata_json String DEFAULT '{}' CODEC(ZSTD(3)),

    -- SQL UDF Tracking (for SQL Trail analytics)
    is_sql_udf Bool DEFAULT false,
    udf_type LowCardinality(Nullable(String)),  -- 'rvbbit_udf', 'rvbbit_cascade_udf', 'llm_aggregate', 'semantic_op'
    cache_hit Bool DEFAULT false,
    input_hash Nullable(String),  -- Hash of UDF input for cache correlation

    -- SQL Source Lineage (for row/column tracking in semantic SQL)
    source_column_name Nullable(String),        -- Column name being processed (e.g., 'description')
    source_row_index Nullable(Int64),           -- Row index in source query (0-based)
    source_table_name Nullable(String),         -- Table name if extractable from query

    -- Classification
    node_type LowCardinality(String),
    role LowCardinality(String),
    depth UInt8 DEFAULT 0,

    -- Semantic Classification (human-readable for debugging)
    semantic_actor LowCardinality(Nullable(String)),
    semantic_purpose LowCardinality(Nullable(String)),

    -- Execution Context (Candidates/Reforge)
    candidate_index Nullable(Int32),
    is_winner Nullable(Bool),
    reforge_step Nullable(Int32),
    winning_candidate_index Nullable(Int32),
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
    species_hash Nullable(String),  -- Hash of cell template DNA for prompt evolution tracking

    -- LLM Provider
    model Nullable(String),                        -- Resolved model name (from API response, e.g. "openai/gpt-4.1-2025-04-14")
    model_requested Nullable(String),              -- Originally requested model (from config, e.g. "openai/gpt-4.1")
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

    -- Token Budget Enforcement (when context is pruned to stay within limits)
    budget_strategy LowCardinality(Nullable(String)),  -- 'sliding_window', 'prune_oldest', 'summarize', 'fail'
    budget_tokens_before Nullable(Int32),               -- Context size before enforcement
    budget_tokens_after Nullable(Int32),                -- Context size after enforcement
    budget_tokens_limit Nullable(Int32),                -- The configured budget limit
    budget_tokens_pruned Nullable(Int32),               -- Calculated: before - after
    budget_percentage Nullable(Float32),                -- before / limit (for threshold tracking)

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
"""


# =============================================================================
# CHECKPOINTS TABLE - Human-in-the-Loop
# =============================================================================
# Stores suspended cascade checkpoints waiting for human input

CHECKPOINTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    -- Core identification
    id String,
    session_id String,
    cascade_id String,
    cell_name String,

    -- Status tracking
    status Enum8('pending' = 1, 'responded' = 2, 'timeout' = 3, 'cancelled' = 4),
    created_at DateTime64(3) DEFAULT now64(3),
    responded_at Nullable(DateTime64(3)),
    timeout_at Nullable(DateTime64(3)),

    -- Type classification
    checkpoint_type Enum8(
        'cell_input' = 1,
        'candidate_eval' = 2,
        'free_text' = 3,
        'choice' = 4,
        'multi_choice' = 5,
        'confirmation' = 6,
        'rating' = 7,
        'audible' = 8,
        'decision' = 9
    ),

    -- UI specification (generated or configured)
    ui_spec String DEFAULT '{}',

    -- Context for resume
    echo_snapshot String DEFAULT '{}',
    cell_output Nullable(String),
    trace_context Nullable(String),

    -- For candidate evaluation
    candidate_outputs Nullable(String),
    candidate_metadata Nullable(String),

    -- Human response
    response Nullable(String),
    response_reasoning Nullable(String),
    response_confidence Nullable(Float32),

    -- Training data fields
    winner_index Nullable(Int32),
    rankings Nullable(String),
    ratings Nullable(String),

    -- Indexes
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (created_at, session_id)
PARTITION BY toYYYYMM(created_at);
"""


# =============================================================================
# TRAINING PREFERENCES TABLE - DPO/RLHF Data
# =============================================================================
# Stores expanded pairwise preferences for ML training

TRAINING_PREFERENCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS training_preferences (
    -- Identity
    id String,
    created_at DateTime64(3) DEFAULT now64(3),

    -- Source tracking (for deduplication and provenance)
    session_id String,
    cascade_id String,
    cell_name String,
    checkpoint_id String,

    -- Prompt context (reconstructed for training)
    prompt_text String,
    prompt_messages String,
    system_prompt String,

    -- Preference type
    preference_type Enum8('pairwise' = 1, 'ranking' = 2, 'rating' = 3),

    -- Pairwise preferences (most common, used by DPO)
    chosen_response String,
    rejected_response String,
    chosen_model Nullable(String),
    rejected_model Nullable(String),
    chosen_cost Nullable(Float64),
    rejected_cost Nullable(Float64),
    chosen_tokens Nullable(Int32),
    rejected_tokens Nullable(Int32),
    margin Float32 DEFAULT 1.0,

    -- Ranking preferences (full ordering)
    all_responses Nullable(String),
    ranking_order Nullable(String),
    num_responses Nullable(Int32),

    -- Rating preferences (scored)
    ratings_json Nullable(String),
    rating_scale_max Nullable(Int32),

    -- Human signal
    human_reasoning Nullable(String),
    human_confidence Nullable(Float32),

    -- Mutation/model metadata
    chosen_mutation Nullable(String),
    rejected_mutation Nullable(String),
    model_comparison Bool DEFAULT false,

    -- Quality flags
    reasoning_quality Nullable(Float32),
    is_tie Bool DEFAULT false,
    is_rejection Bool DEFAULT false,

    -- Indexes
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_pref_type preference_type TYPE set(10) GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (created_at, session_id, preference_type)
PARTITION BY toYYYYMM(created_at);
"""


# =============================================================================
# RAG CHUNKS TABLE - Vector Storage
# =============================================================================
# Stores chunked document content with embeddings for semantic search

RAG_CHUNKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id UUID DEFAULT generateUUIDv4(),
    rag_id String,
    doc_id String,
    rel_path String,
    chunk_index UInt32,

    -- Content
    text String,
    char_start UInt32,
    char_end UInt32,
    start_line UInt32,
    end_line UInt32,

    -- Metadata
    file_hash String,
    created_at DateTime64(3) DEFAULT now64(3),

    -- Vector Embedding
    embedding Array(Float32),
    embedding_model LowCardinality(String),
    embedding_dim UInt16,

    -- Indexes
    INDEX idx_rag_id rag_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_doc_id doc_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_rel_path rel_path TYPE bloom_filter GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (rag_id, doc_id, chunk_index)
PARTITION BY rag_id;
"""


# =============================================================================
# RAG MANIFESTS TABLE - Document Metadata
# =============================================================================
# Stores metadata about indexed documents for incremental updates

RAG_MANIFESTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_manifests (
    doc_id String,
    rag_id String,
    rel_path String,
    abs_path String,
    file_hash String,
    file_size UInt64,
    mtime Float64,
    chunk_count UInt32,
    content_hash String,
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Indexes
    INDEX idx_rag_id rag_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_rel_path rel_path TYPE bloom_filter GRANULARITY 1,
    INDEX idx_file_hash file_hash TYPE bloom_filter GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (rag_id, rel_path);
"""


# =============================================================================
# EVALUATIONS TABLE - Hot-or-Not System
# =============================================================================
# Stores human/model evaluations for quality tracking

EVALUATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    id UUID DEFAULT generateUUIDv4(),
    created_at DateTime64(3) DEFAULT now64(3),

    -- Source context
    session_id String,
    cell_name String,
    candidate_index Int32,

    -- Evaluation
    evaluation_type Enum8('rating' = 0, 'preference' = 1, 'flag' = 2),
    rating Nullable(Float32),
    preferred_index Nullable(Int32),
    flag_reason Nullable(String),

    -- Evaluator
    evaluator_id Nullable(String),
    evaluator_type Enum8('human' = 0, 'model' = 1) DEFAULT 'human',

    -- Indexes
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (created_at, session_id)
PARTITION BY toYYYYMM(created_at);
"""


# =============================================================================
# TOOL MANIFEST VECTORS TABLE - Tool Discovery
# =============================================================================
# Stores tool definitions with embeddings for semantic tool discovery

TOOL_MANIFEST_VECTORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_manifest_vectors (
    tool_name String,
    tool_type Enum8('function' = 0, 'cascade' = 1, 'memory' = 2, 'validator' = 3),
    tool_description String,
    schema_json Nullable(String),
    source_path Nullable(String),

    -- Vector Embedding
    embedding Array(Float32),
    embedding_model LowCardinality(String),
    embedding_dim UInt16,

    -- Metadata
    last_updated DateTime64(3) DEFAULT now64(3),

    -- Indexes
    INDEX idx_tool_type tool_type TYPE set(10) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY tool_name;
"""


# =============================================================================
# CASCADE TEMPLATE VECTORS TABLE - Cascade Discovery
# =============================================================================
# Stores cascade templates with embeddings for semantic cascade discovery

CASCADE_TEMPLATE_VECTORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS cascade_template_vectors (
    cascade_id String,
    cascade_file String,
    description String,
    cell_count UInt8,

    -- Aggregated Metrics
    run_count UInt32 DEFAULT 0,
    avg_cost Nullable(Float64),
    avg_duration_seconds Nullable(Float64),
    success_rate Nullable(Float32),

    -- Vector Embeddings
    description_embedding Array(Float32),
    instructions_embedding Array(Float32),
    embedding_model LowCardinality(String),
    embedding_dim UInt16,

    -- Metadata
    last_updated DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY cascade_id;
"""


# =============================================================================
# SIGNALS TABLE - Cross-Cascade Communication
# =============================================================================
# Stores signals for cascades waiting on external events (webhooks, sensors, etc.)
# Uses HTTP callbacks for reactive wake-up with ClickHouse as durable store

SIGNALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    -- Core Identification
    signal_id String,
    signal_name String,

    -- Status tracking
    status Enum8('waiting' = 1, 'fired' = 2, 'timeout' = 3, 'cancelled' = 4),
    created_at DateTime64(3) DEFAULT now64(3),
    fired_at Nullable(DateTime64(3)),
    timeout_at Nullable(DateTime64(3)),

    -- Cascade context (who is waiting)
    session_id String,
    cascade_id String,
    cell_name Nullable(String),

    -- HTTP callback for reactive wake (the waiting cascade's listener)
    callback_host Nullable(String),
    callback_port Nullable(UInt16),
    callback_token Nullable(String),

    -- Signal payload (data passed when signal fires)
    payload_json Nullable(String),

    -- Routing info (where to go after signal fires)
    target_cell Nullable(String),
    inputs_json Nullable(String),

    -- Metadata
    description Nullable(String),
    source Nullable(String),
    metadata_json Nullable(String),

    -- Indexes
    INDEX idx_signal_name signal_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (signal_id)
PARTITION BY toYYYYMM(created_at);
"""


# =============================================================================
# SESSION STATE TABLE - Durable Execution Coordination
# =============================================================================
# Central source of truth for cascade execution state. Replaces JSON file-based
# state tracking with ClickHouse-native coordination for:
# - Cross-process visibility (any CLI can see any session's state)
# - Zombie detection via heartbeat expiry
# - Cancellation support
# - Blocked state surfacing (signal/HITL waits)

SESSION_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_state (
    -- Identity
    session_id String,
    cascade_id String,
    parent_session_id Nullable(String),

    -- Caller Tracking (NEW - for grouping related sessions)
    caller_id String DEFAULT '',
    invocation_metadata_json String DEFAULT '{}' CODEC(ZSTD(3)),

    -- Execution status
    status Enum8(
        'starting' = 1,
        'running' = 2,
        'blocked' = 3,
        'completed' = 4,
        'error' = 5,
        'cancelled' = 6,
        'orphaned' = 7
    ),
    current_cell Nullable(String),
    depth UInt8 DEFAULT 0,

    -- Blocked state details (populated when status = 'blocked')
    blocked_type Nullable(Enum8(
        'signal' = 1,
        'hitl' = 2,
        'sensor' = 3,
        'approval' = 4,
        'checkpoint' = 5,
        'decision' = 6
    )),
    blocked_on Nullable(String),           -- signal_name, checkpoint_id, etc.
    blocked_description Nullable(String),  -- Human-readable description
    blocked_timeout_at Nullable(DateTime64(3)),

    -- Heartbeat for zombie detection
    heartbeat_at DateTime64(3) DEFAULT now64(3),
    heartbeat_lease_seconds UInt16 DEFAULT 60,

    -- Cancellation
    cancel_requested Bool DEFAULT false,
    cancel_reason Nullable(String),
    cancelled_at Nullable(DateTime64(3)),

    -- Error details (populated when status = 'error')
    error_message Nullable(String),
    error_cell Nullable(String),

    -- Recovery/Resume
    last_checkpoint_id Nullable(String),
    resumable Bool DEFAULT false,

    -- Timing
    started_at DateTime64(3) DEFAULT now64(3),
    completed_at Nullable(DateTime64(3)),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Extensible metadata
    metadata_json String DEFAULT '{}',

    -- Indexes for common query patterns
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_parent parent_session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_caller_id caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_heartbeat heartbeat_at TYPE minmax GRANULARITY 1,
    INDEX idx_started started_at TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (session_id)
PARTITION BY toYYYYMM(started_at);
"""


# =============================================================================
# RESEARCH SESSIONS TABLE - Temporal Versioning
# =============================================================================
# Stores frozen snapshots of interactive research cascades for the Research Cockpit.
# Enables browsing, resumption, and branching of research sessions.

RESEARCH_SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_sessions (
    -- Identity
    id String,  -- research_session_{uuid}
    original_session_id String,  -- The live session this was saved from
    cascade_id String,

    -- Metadata
    title String,  -- User-provided or auto-generated title
    description String,  -- Summary of what was researched
    created_at DateTime,  -- When the live session started
    frozen_at DateTime,  -- When this snapshot was saved
    status String,  -- 'completed', 'paused', 'active'

    -- Context for Resumption (JSON blobs)
    context_snapshot String,  -- Echo state: {state, history, lineage}
    checkpoints_data String,  -- Array of checkpoint interactions with branch metadata
    entries_snapshot String,  -- Full unified_logs entries for this session

    -- Visual Artifacts
    mermaid_graph String,  -- Latest mermaid graph content
    screenshots String,  -- JSON array of screenshot paths

    -- Metrics (for display in browser)
    total_cost Float64,
    total_turns UInt32,
    total_input_tokens UInt64,
    total_output_tokens UInt64,
    duration_seconds Float64,
    cells_visited String,  -- JSON array of cell names
    tools_used String,  -- JSON array of tool names

    -- Taxonomy
    tags String,  -- JSON array of tags for filtering

    -- Branching/Resumption
    parent_session_id Nullable(String),  -- If this was branched from another session
    branch_point_checkpoint_id Nullable(String),  -- Which checkpoint was the branch point

    -- Timestamps
    updated_at DateTime,  -- Last modification

    -- Indexes
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_original_session original_session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_frozen frozen_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (cascade_id, frozen_at, id)
PARTITION BY toYYYYMM(frozen_at);
"""


# =============================================================================
# CONTEXT CARDS TABLE - Auto-Context Summaries
# =============================================================================
# Stores message summaries and embeddings for intelligent context management.
# Joined with unified_logs via (session_id, content_hash) for original content retrieval.
# Used by the auto-context system for intra-cell and inter-cell context selection.

CONTEXT_CARDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS context_cards (
    -- Identity (composite key - joins with unified_logs)
    session_id String,
    content_hash String,  -- FK to unified_logs.content_hash (16-char SHA256 prefix)

    -- Summary content
    summary String,                         -- 1-2 sentence summary of the message
    keywords Array(String) DEFAULT [],      -- Extracted keywords for heuristic matching

    -- Embedding for semantic search
    embedding Array(Float32) DEFAULT [],    -- 768-1536 dimensions
    embedding_model LowCardinality(Nullable(String)),
    embedding_dim Nullable(UInt16),

    -- Metadata for selection
    estimated_tokens UInt32 DEFAULT 0,      -- Token count of original message
    role LowCardinality(String),            -- user/assistant/tool/system
    cell_name Nullable(String),            -- Cell this message belongs to
    turn_number Nullable(UInt32),           -- Turn within cell

    -- Importance markers
    is_anchor Bool DEFAULT false,           -- Always include in context
    is_callout Bool DEFAULT false,          -- User-marked as important
    callout_name Nullable(String),

    -- Generation metadata
    generated_at DateTime64(3) DEFAULT now64(3),
    generator_model LowCardinality(Nullable(String)),  -- Model used for summarization

    -- Message timestamp (for recency scoring)
    message_timestamp DateTime64(3) DEFAULT now64(3),

    -- Cascade context
    cascade_id Nullable(String),

    -- Indexes for common query patterns
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_content_hash content_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_is_anchor is_anchor TYPE set(2) GRANULARITY 1,
    INDEX idx_is_callout is_callout TYPE set(2) GRANULARITY 1,
    INDEX idx_keywords keywords TYPE bloom_filter GRANULARITY 1,
    INDEX idx_timestamp message_timestamp TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(generated_at)
ORDER BY (session_id, content_hash)
PARTITION BY toYYYYMM(message_timestamp)
TTL message_timestamp + INTERVAL 90 DAY;
"""


# =============================================================================
# CONTEXT SHADOW ASSESSMENTS TABLE - Auto-Context Analysis
# =============================================================================
# Shadow assessment of auto-context relevance for all context candidates.
# When running cascades with explicit context, we still assess what auto-context
# WOULD have done. This enables comparing explicit vs auto decisions.
#
# Controlled by: RVBBIT_SHADOW_ASSESSMENT_ENABLED (default: true)

CONTEXT_SHADOW_ASSESSMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS context_shadow_assessments (
    -- Identity
    assessment_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Session context
    session_id String,
    cascade_id String,
    target_cell_name String,
    target_cell_instructions String,

    -- Candidate message being assessed
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
    total_candidates UInt16,

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
"""


# =============================================================================
# UI SQL LOG TABLE - Query Performance Tracking
# =============================================================================
# Stores all SQL queries made by the UI backend for performance analysis.
# Uses fire-and-forget async inserts to avoid slowing down the main query path.
# Short TTL (7 days) to keep table small - just for debugging/optimization.

UI_SQL_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS ui_sql_log (
    -- Timing
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Query info
    query_type LowCardinality(String),  -- 'query', 'execute', 'insert_rows', 'insert_df', 'update', 'vector_search'
    sql_preview String,                  -- First 500 chars of SQL (or table name for inserts)
    sql_hash String,                     -- MD5 hash for grouping similar queries

    -- Metrics
    duration_ms Float64,
    rows_returned Nullable(Int32),       -- NULL for write operations
    rows_affected Nullable(Int32),       -- For insert/update operations

    -- Context
    source LowCardinality(String) DEFAULT 'unknown',  -- 'ui_backend', 'rvbbit_core', etc.
    caller Nullable(String),             -- Function/endpoint that made the call
    request_path Nullable(String),       -- API path (e.g., /api/sextant/species/abc123)
    page_ref Nullable(String),           -- Browser page from Referer header (e.g., /#/cascade_id/session_id)

    -- Error tracking
    success Bool DEFAULT true,
    error_message Nullable(String),

    -- Indexes for analysis queries
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_duration duration_ms TYPE minmax GRANULARITY 1,
    INDEX idx_query_type query_type TYPE set(20) GRANULARITY 1,
    INDEX idx_sql_hash sql_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_source source TYPE set(20) GRANULARITY 1,
    INDEX idx_success success TYPE set(2) GRANULARITY 1,
    INDEX idx_page_ref page_ref TYPE bloom_filter GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (timestamp, query_type)
PARTITION BY toYYYYMMDD(timestamp)
TTL timestamp + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;
"""


# =============================================================================
# OPENROUTER MODELS TABLE - Model Verification & Caching
# =============================================================================
# Stores OpenRouter models with verification status. Replaces file-based cache
# with ClickHouse-backed storage for model availability tracking.

OPENROUTER_MODELS_SCHEMA = """
CREATE TABLE IF NOT EXISTS openrouter_models (
    -- Core Identity
    model_id String,
    model_name String,
    provider String,

    -- Metadata
    description String DEFAULT '',
    context_length UInt32 DEFAULT 0,

    -- Classification
    tier LowCardinality(String),  -- 'flagship', 'standard', 'fast', 'open'
    popular Bool DEFAULT false,
    model_type LowCardinality(String),  -- 'text', 'image'

    -- Capabilities (from architecture.modality)
    input_modalities Array(String) DEFAULT [],
    output_modalities Array(String) DEFAULT [],

    -- Pricing (per token)
    prompt_price Float64 DEFAULT 0,
    completion_price Float64 DEFAULT 0,

    -- Availability
    is_active Bool DEFAULT true,
    last_verified DateTime64(3) DEFAULT now64(3),
    verification_error Nullable(String),

    -- Timestamps
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Additional metadata (JSON blob for extensibility)
    metadata_json String DEFAULT '{}',

    -- Indexes
    INDEX idx_provider provider TYPE bloom_filter GRANULARITY 1,
    INDEX idx_tier tier TYPE set(10) GRANULARITY 1,
    INDEX idx_model_type model_type TYPE set(10) GRANULARITY 1,
    INDEX idx_is_active is_active TYPE set(2) GRANULARITY 1,
    INDEX idx_popular popular TYPE set(2) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (model_id)
PARTITION BY model_type;
"""


# =============================================================================
# HUGGINGFACE SPACES TABLE - Harbor System Cache
# =============================================================================
# Stores user's HuggingFace Spaces with status/cost tracking.
# Replaces in-memory cache with ClickHouse-backed persistence.

HF_SPACES_SCHEMA = """
CREATE TABLE IF NOT EXISTS hf_spaces (
    -- Core Identity
    space_id String,                    -- e.g., "ryrobes/Qwen-Image-Layered"
    author String,                      -- e.g., "ryrobes"
    space_name String,                  -- e.g., "Qwen-Image-Layered"

    -- Status & Runtime
    status LowCardinality(String),      -- RUNNING, SLEEPING, BUILDING, PAUSED, STOPPED, RUNTIME_ERROR
    hardware LowCardinality(Nullable(String)),  -- t4-medium, a100-large, cpu-basic, etc.
    sdk LowCardinality(Nullable(String)),       -- gradio, streamlit, docker, static

    -- Cost Information
    hourly_cost Nullable(Float64),      -- Computed from hardware tier
    is_billable Bool DEFAULT false,     -- True if RUNNING and costs > 0
    is_callable Bool DEFAULT false,     -- True if Gradio + RUNNING

    -- API Schema (cached introspection)
    endpoints_json Nullable(String),    -- Gradio API endpoints and parameters

    -- Metadata
    private Bool DEFAULT false,
    space_url String DEFAULT '',
    sleep_time Nullable(Int32),         -- Seconds until auto-sleep
    requested_hardware Nullable(String),

    -- Tracking Timestamps
    first_seen DateTime64(3) DEFAULT now64(3),
    last_seen DateTime64(3) DEFAULT now64(3),
    last_refreshed DateTime64(3) DEFAULT now64(3),

    -- Usage Stats (computed from unified_logs)
    total_invocations Nullable(UInt64) DEFAULT 0,
    last_invocation Nullable(DateTime64(3)),

    -- Indexes
    INDEX idx_space_id space_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_author author TYPE bloom_filter GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_hardware hardware TYPE set(50) GRANULARITY 1,
    INDEX idx_sdk sdk TYPE set(10) GRANULARITY 1,
    INDEX idx_is_billable is_billable TYPE set(2) GRANULARITY 1,
    INDEX idx_is_callable is_callable TYPE set(2) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(last_refreshed)
ORDER BY (space_id);
"""


# =============================================================================
# TAG DEFINITIONS TABLE - Tag Metadata
# =============================================================================
# Stores tag metadata (name, color, description) for the output tagging system.
# Uses ReplacingMergeTree for upsert semantics when updating tag properties.

TAG_DEFINITIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tag_definitions (
    tag_name String,
    tag_color String DEFAULT '#a78bfa',
    description Nullable(String),
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Indexes
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY tag_name;
"""


# =============================================================================
# OUTPUT TAGS TABLE - Output Tagging Cross-Walk
# =============================================================================
# Cross-walk table linking tags to outputs with support for two modes:
# - instance: Tags a specific message_id (frozen snapshot)
# - dynamic: Tags latest output from cascade+cell combo (auto-updates)
#
# This enables filtering outputs by tags in the UI, marking outputs for
# review/approval/production, and creating dynamic dashboards.

OUTPUT_TAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS output_tags (
    -- Identity
    tag_id UUID DEFAULT generateUUIDv4(),
    tag_name String,

    -- Tag Mode: instance = specific message, dynamic = latest from cascade+cell
    tag_mode Enum8('instance' = 1, 'dynamic' = 2),

    -- Instance Mode: points to specific message
    message_id Nullable(UUID),

    -- Dynamic Mode: points to latest output from cascade+cell
    cascade_id Nullable(String),
    cell_name Nullable(String),

    -- Metadata
    created_at DateTime64(3) DEFAULT now64(3),
    created_by Nullable(String),
    note Nullable(String),

    -- Indexes for common query patterns
    INDEX idx_tag_name tag_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_message_id message_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell_name cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_tag_mode tag_mode TYPE set(2) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (tag_name, created_at)
PARTITION BY toYYYYMM(created_at);
"""


# =============================================================================
# INTRA-CONTEXT SHADOW ASSESSMENTS TABLE - Intra-Cell Context Analysis
# =============================================================================
# Shadow assessment of intra-cell context management across multiple config scenarios.
# Intra-cell context management controls HOW messages within a cell's turn loop are
# compressed/masked. This is purely local computation (no LLM calls), so we can cheaply
# evaluate many config scenarios to suggest optimal settings.
#
# Config parameters we vary:
#   - window: [3, 5, 7, 10, 15] - turns to keep in full fidelity
#   - mask_observations_after: [2, 3, 5, 7] - when to start masking tool results
#   - min_masked_size: [100, 200, 500] - minimum chars before masking
#
# Controlled by: RVBBIT_SHADOW_ASSESSMENT_ENABLED (same as inter-cell)

INTRA_CONTEXT_SHADOW_ASSESSMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS intra_context_shadow_assessments (
    -- Identity
    assessment_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Session context
    session_id String,
    cascade_id String,
    cell_name String,
    candidate_index Nullable(Int16),       -- NULL if not in candidates, else 0, 1, 2...
    turn_number UInt16,                    -- Turn within this cell (0-indexed)
    is_loop_retry Bool DEFAULT false,      -- Is this a loop_until retry turn?

    -- Config scenario being evaluated
    config_window UInt8,                   -- window parameter value
    config_mask_after UInt8,               -- mask_observations_after parameter value
    config_min_masked_size UInt16,         -- min_masked_size parameter value
    config_compress_loops Bool,            -- compress_loops parameter value
    config_preserve_reasoning Bool,        -- preserve_reasoning parameter value
    config_preserve_errors Bool,           -- preserve_errors parameter value

    -- Turn-level aggregate metrics
    full_history_size UInt16,              -- Total messages before context building
    context_size UInt16,                   -- Messages after context building
    tokens_before UInt32,                  -- Estimated tokens before
    tokens_after UInt32,                   -- Estimated tokens after
    tokens_saved UInt32,                   -- tokens_before - tokens_after
    compression_ratio Float32,             -- tokens_after / tokens_before
    messages_masked UInt16,                -- Count of masked messages
    messages_preserved UInt16,             -- Count of preserved messages
    messages_truncated UInt16,             -- Count of truncated messages

    -- Per-message breakdown (JSON array)
    -- Each entry: {msg_index, role, original_tokens, action, result_tokens, reason}
    message_breakdown String DEFAULT '[]',

    -- Comparison flags (vs baseline/actual)
    tokens_vs_baseline_saved UInt32,       -- How much this config saves vs disabled
    tokens_vs_baseline_pct Float32,        -- Percentage saved vs disabled

    -- Actual vs shadow comparison
    actual_config_enabled Bool,            -- Was intra-context enabled for this turn?
    actual_tokens_after Nullable(UInt32),  -- What tokens_after was in actual execution
    differs_from_actual Bool,              -- Would this config produce different result?

    -- Assessment metadata
    assessment_batch_id String,            -- Groups assessments from same turn

    -- Indexes
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_candidate candidate_index TYPE set(100) GRANULARITY 1,
    INDEX idx_turn turn_number TYPE set(100) GRANULARITY 1,
    INDEX idx_batch assessment_batch_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_compression compression_ratio TYPE minmax GRANULARITY 1,
    INDEX idx_window config_window TYPE set(20) GRANULARITY 1,
    INDEX idx_mask_after config_mask_after TYPE set(20) GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (session_id, cell_name, turn_number, config_window, config_mask_after)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;
"""


# =============================================================================
# SEMANTIC SQL CACHE TABLE - Persistent LLM result cache
# =============================================================================
# Caches results from semantic SQL operations (MEANS, SUMMARIZE, CLASSIFY, etc.)
# to avoid redundant LLM calls. Supports:
# - Cross-query cache hits (same semantic call in different queries)
# - Browseable cache contents (inspect inputs/outputs)
# - Selective pruning (by function, age, pattern)
# - TTL-based expiration

SEMANTIC_SQL_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_sql_cache (
    -- Identity (cache_key is MD5 hash of function + args)
    cache_key String,
    function_name LowCardinality(String),          -- e.g., 'semantic_matches', 'semantic_summarize'

    -- Input (for debugging/inspection)
    args_json String CODEC(ZSTD(3)),               -- Full args as JSON (for inspection)
    args_preview String DEFAULT '',                 -- First 200 chars for quick view

    -- Result
    result String CODEC(ZSTD(3)),                  -- Cached output value
    result_type LowCardinality(String),            -- 'BOOLEAN', 'DOUBLE', 'VARCHAR', 'JSON'

    -- Timing
    created_at DateTime64(3) DEFAULT now64(),
    expires_at DateTime64(3) DEFAULT toDateTime64('2100-01-01 00:00:00', 3),  -- Far future = never expires
    ttl_seconds UInt32 DEFAULT 0,                  -- 0 = infinite

    -- Analytics
    hit_count UInt64 DEFAULT 1,                    -- Starts at 1 (the initial set)
    last_hit_at DateTime64(3) DEFAULT now64(),

    -- Size tracking
    result_bytes UInt32 DEFAULT 0,

    -- Source tracking
    first_session_id String DEFAULT '',
    first_caller_id String DEFAULT '',

    -- Indexes for efficient queries
    INDEX idx_function function_name TYPE set(100) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1,
    INDEX idx_expires expires_at TYPE minmax GRANULARITY 1,
    INDEX idx_last_hit last_hit_at TYPE minmax GRANULARITY 1,
    INDEX idx_hit_count hit_count TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(last_hit_at)           -- Dedupe by cache_key, keep row with latest hit
ORDER BY (cache_key)
TTL expires_at
SETTINGS index_granularity = 8192;
"""


# =============================================================================
# SQL QUERY LOG TABLE - SQL Trail Analytics
# =============================================================================
# Tracks SQL queries that invoke RVBBIT UDFs for cost attribution and pattern analysis.
# The unit of work is the SQL query (via caller_id), not individual LLM sessions.
# Enables cache analytics, query fingerprinting, and batch economics.

SQL_QUERY_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS sql_query_log (
    -- Identity
    query_id UUID DEFAULT generateUUIDv4(),
    caller_id String,

    -- Query Content
    query_raw String CODEC(ZSTD(3)),
    query_fingerprint String,  -- AST-normalized hash via sqlglot
    query_template String CODEC(ZSTD(3)),  -- Parameterized SQL (literals replaced with ?)
    query_type LowCardinality(String),  -- 'rvbbit_udf', 'rvbbit_cascade_udf', 'rvbbit_map', 'llm_aggregate', 'semantic_op'

    -- UDF Detection
    udf_types Array(String) DEFAULT [],
    udf_count UInt16 DEFAULT 0,
    cascade_paths Array(String) DEFAULT [],
    cascade_count UInt16 DEFAULT 0,

    -- Execution
    started_at DateTime64(6),
    completed_at Nullable(DateTime64(6)),
    duration_ms Nullable(Float64),
    status LowCardinality(String),  -- 'running', 'completed', 'error'

    -- Row Metrics
    rows_input Nullable(Int32),
    rows_output Nullable(Int32),

    -- Cost (aggregated from spawned sessions via caller_id)
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
    protocol LowCardinality(String),  -- 'postgresql_wire', 'http', 'notebook'
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Indexes
    INDEX idx_caller caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_fingerprint query_fingerprint TYPE bloom_filter GRANULARITY 1,
    INDEX idx_query_type query_type TYPE set(20) GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_duration duration_ms TYPE minmax GRANULARITY 1,
    INDEX idx_cost total_cost TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (timestamp, caller_id)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
"""


# =============================================================================
# SESSION SUMMARY MATERIALIZED VIEW (Optional - for performance)
# =============================================================================
# Auto-aggregates session metrics for fast dashboard queries

SESSION_SUMMARY_MV_SCHEMA = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_session_summary
ENGINE = SummingMergeTree()
ORDER BY (session_id, cascade_id_key)
AS SELECT
    session_id,
    coalesce(cascade_id, '') as cascade_id_key,
    cascade_id,
    min(timestamp) as start_time,
    max(timestamp) as end_time,
    sum(cost) as total_cost,
    sum(tokens_in) as total_tokens_in,
    sum(tokens_out) as total_tokens_out,
    sum(tokens_reasoning) as total_tokens_reasoning,
    count() as message_count,
    countIf(role = 'assistant') as assistant_messages,
    countIf(node_type = 'tool_call') as tool_calls,
    countIf(reasoning_enabled = true) as reasoning_calls
FROM unified_logs
GROUP BY session_id, cascade_id;
"""


# =============================================================================
# Schema Registry Functions
# =============================================================================

def get_schema(table_name: str) -> str:
    """
    Get the CREATE TABLE statement for a table.

    Args:
        table_name: Name of the table

    Returns:
        CREATE TABLE SQL statement

    Raises:
        ValueError: If table_name is not found
    """
    schemas = get_all_schemas()
    if table_name in schemas:
        return schemas[table_name]
    raise ValueError(f"Unknown table: {table_name}. Available: {list(schemas.keys())}")


def get_all_schemas() -> dict:
    """
    Get all table schemas as a dictionary.

    Returns:
        Dict mapping table names to CREATE TABLE statements
    """
    return {
        "unified_logs": UNIFIED_LOGS_SCHEMA,
        "checkpoints": CHECKPOINTS_SCHEMA,
        "training_preferences": TRAINING_PREFERENCES_SCHEMA,
        "rag_chunks": RAG_CHUNKS_SCHEMA,
        "rag_manifests": RAG_MANIFESTS_SCHEMA,
        "evaluations": EVALUATIONS_SCHEMA,
        "tool_manifest_vectors": TOOL_MANIFEST_VECTORS_SCHEMA,
        "cascade_template_vectors": CASCADE_TEMPLATE_VECTORS_SCHEMA,
        "signals": SIGNALS_SCHEMA,
        "session_state": SESSION_STATE_SCHEMA,
        "research_sessions": RESEARCH_SESSIONS_SCHEMA,
        "context_cards": CONTEXT_CARDS_SCHEMA,
        "context_shadow_assessments": CONTEXT_SHADOW_ASSESSMENTS_SCHEMA,
        "intra_context_shadow_assessments": INTRA_CONTEXT_SHADOW_ASSESSMENTS_SCHEMA,
        "ui_sql_log": UI_SQL_LOG_SCHEMA,
        "openrouter_models": OPENROUTER_MODELS_SCHEMA,
        "hf_spaces": HF_SPACES_SCHEMA,
        "tag_definitions": TAG_DEFINITIONS_SCHEMA,
        "output_tags": OUTPUT_TAGS_SCHEMA,
        "sql_query_log": SQL_QUERY_LOG_SCHEMA,
        "semantic_sql_cache": SEMANTIC_SQL_CACHE_SCHEMA,
    }


def get_materialized_views() -> dict:
    """
    Get all materialized view schemas.

    Returns:
        Dict mapping view names to CREATE statements
    """
    return {
        "mv_session_summary": SESSION_SUMMARY_MV_SCHEMA,
    }


def get_all_ddl() -> list:
    """
    Get all DDL statements in order (tables first, then MVs).

    Returns:
        List of DDL statements
    """
    ddl = list(get_all_schemas().values())
    ddl.extend(get_materialized_views().values())
    return ddl
