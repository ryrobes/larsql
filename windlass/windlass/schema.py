"""
ClickHouse schema definitions for Windlass logging system.

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

    -- Classification
    node_type LowCardinality(String),
    role LowCardinality(String),
    depth UInt8 DEFAULT 0,

    -- Semantic Classification (human-readable for debugging)
    semantic_actor LowCardinality(Nullable(String)),
    semantic_purpose LowCardinality(Nullable(String)),

    -- Execution Context (Soundings/Reforge)
    sounding_index Nullable(Int32),
    is_winner Nullable(Bool),
    reforge_step Nullable(Int32),
    winning_sounding_index Nullable(Int32),
    attempt_number Nullable(Int32),
    turn_number Nullable(Int32),
    mutation_applied Nullable(String),
    mutation_type LowCardinality(Nullable(String)),
    mutation_template Nullable(String),

    -- Cascade Context
    cascade_id Nullable(String),
    cascade_file Nullable(String),
    cascade_json Nullable(String) CODEC(ZSTD(3)),
    phase_name Nullable(String),
    phase_json Nullable(String) CODEC(ZSTD(3)),

    -- LLM Provider
    model Nullable(String),
    request_id Nullable(String),
    provider LowCardinality(Nullable(String)),

    -- Performance Metrics
    duration_ms Nullable(Float64),
    tokens_in Nullable(Int32),
    tokens_out Nullable(Int32),
    total_tokens Nullable(Int32),
    cost Nullable(Float64),

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

    -- Metadata
    metadata_json Nullable(String),

    -- Indexes for common query patterns
    INDEX idx_session_id session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_phase_name phase_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_trace_id trace_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_node_type node_type TYPE set(100) GRANULARITY 1,
    INDEX idx_role role TYPE set(10) GRANULARITY 1,
    INDEX idx_is_winner is_winner TYPE set(2) GRANULARITY 1,
    INDEX idx_cost cost TYPE minmax GRANULARITY 4,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1
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
    phase_name String,

    -- Status tracking
    status Enum8('pending' = 1, 'responded' = 2, 'timeout' = 3, 'cancelled' = 4),
    created_at DateTime64(3) DEFAULT now64(3),
    responded_at Nullable(DateTime64(3)),
    timeout_at Nullable(DateTime64(3)),

    -- Type classification
    checkpoint_type Enum8('phase_input' = 1, 'sounding_eval' = 2),

    -- UI specification (generated or configured)
    ui_spec String DEFAULT '{}',

    -- Context for resume
    echo_snapshot String DEFAULT '{}',
    phase_output Nullable(String),
    trace_context Nullable(String),

    -- For sounding evaluation
    sounding_outputs Nullable(String),
    sounding_metadata Nullable(String),

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
    phase_name String,
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
    phase_name String,
    sounding_index Int32,

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
    phase_count UInt8,

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
# SESSION SUMMARY MATERIALIZED VIEW (Optional - for performance)
# =============================================================================
# Auto-aggregates session metrics for fast dashboard queries

SESSION_SUMMARY_MV_SCHEMA = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_session_summary
ENGINE = SummingMergeTree()
ORDER BY (session_id, cascade_id)
AS SELECT
    session_id,
    cascade_id,
    min(timestamp) as start_time,
    max(timestamp) as end_time,
    sum(cost) as total_cost,
    sum(tokens_in) as total_tokens_in,
    sum(tokens_out) as total_tokens_out,
    count() as message_count,
    countIf(role = 'assistant') as assistant_messages,
    countIf(node_type = 'tool_call') as tool_calls
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
