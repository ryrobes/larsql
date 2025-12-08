"""
ClickHouse schema definitions for Windlass logging system.

This module defines the table schema for the unified logging system.
The schema is designed to work with both chDB (embedded) and ClickHouse server.
"""

# Unified logs table schema
# This schema captures all logging data with complete context for analytics and reconstruction
UNIFIED_LOGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS unified_logs (
    -- Core identification
    timestamp Float64,
    timestamp_iso String,
    session_id String,
    trace_id String,
    parent_id Nullable(String),
    parent_session_id Nullable(String),
    parent_message_id Nullable(String),

    -- Message classification
    node_type String,
    role Nullable(String),
    depth Int32,

    -- Execution context - special indexes for soundings/reforge
    sounding_index Nullable(Int32),
    is_winner Nullable(Bool),
    reforge_step Nullable(Int32),
    attempt_number Nullable(Int32),
    turn_number Nullable(Int32),
    mutation_applied Nullable(String),  -- The actual mutation text (augment prefix OR rewritten prompt)
    mutation_type Nullable(String),     -- Type of mutation: 'augment', 'rewrite', or null for baseline
    mutation_template Nullable(String), -- For rewrite: the template/instruction used to generate the mutation

    -- Cascade context
    cascade_id Nullable(String),
    cascade_file Nullable(String),
    cascade_json Nullable(String),  -- JSON blob
    phase_name Nullable(String),
    phase_json Nullable(String),    -- JSON blob

    -- LLM provider data
    model Nullable(String),
    request_id Nullable(String),
    provider Nullable(String),

    -- Performance metrics
    duration_ms Nullable(Float64),
    tokens_in Nullable(Int32),
    tokens_out Nullable(Int32),
    total_tokens Nullable(Int32),
    cost Nullable(Float64),

    -- Content (JSON blobs for complete reconstruction)
    content_json Nullable(String),
    full_request_json Nullable(String),
    full_response_json Nullable(String),
    tool_calls_json Nullable(String),

    -- Images
    images_json Nullable(String),
    has_images Bool DEFAULT false,
    has_base64 Bool DEFAULT false,

    -- Audio
    audio_json Nullable(String),
    has_audio Bool DEFAULT false,

    -- Mermaid diagram state
    mermaid_content Nullable(String),

    -- Metadata
    metadata_json Nullable(String)
)
ENGINE = MergeTree()
ORDER BY (session_id, timestamp)
PARTITION BY toYYYYMM(toDateTime(timestamp))
SETTINGS index_granularity = 8192;
"""

# Index definitions for common queries
# These are optional but recommended for ClickHouse server deployments
UNIFIED_LOGS_INDEXES = """
-- Index for cascade queries
ALTER TABLE unified_logs ADD INDEX idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1;

-- Index for phase queries
ALTER TABLE unified_logs ADD INDEX idx_phase_name phase_name TYPE bloom_filter GRANULARITY 1;

-- Index for sounding winners
ALTER TABLE unified_logs ADD INDEX idx_is_winner is_winner TYPE set(0) GRANULARITY 1;

-- Index for cost analysis
ALTER TABLE unified_logs ADD INDEX idx_cost cost TYPE minmax GRANULARITY 4;
"""


# ===== Human-in-the-Loop (HITL) Checkpoints Table =====
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
    created_at DateTime64(3),
    responded_at Nullable(DateTime64(3)),
    timeout_at Nullable(DateTime64(3)),

    -- Type classification
    checkpoint_type Enum8('phase_input' = 1, 'sounding_eval' = 2),

    -- UI specification (generated or configured)
    ui_spec String,  -- JSON blob

    -- Context for resume
    echo_snapshot String,  -- JSON blob - full Echo state
    phase_output String,  -- What the phase produced

    -- Trace context for proper resume linkage (connects resumed execution to original trace hierarchy)
    trace_context Nullable(String),  -- JSON blob: {trace_id, parent_id, cascade_trace_id, phase_trace_id, depth, node_type, name}

    -- For sounding evaluation
    sounding_outputs Nullable(String),  -- JSON array of all attempts
    sounding_metadata Nullable(String),  -- JSON - costs, models, mutations per attempt

    -- Human response
    response Nullable(String),  -- JSON blob
    response_reasoning Nullable(String),
    response_confidence Nullable(Float32),

    -- Training data fields (for sounding_eval checkpoints)
    winner_index Nullable(Int32),
    rankings Nullable(String),  -- JSON array for rank_all mode
    ratings Nullable(String)    -- JSON object for rate_each mode
)
ENGINE = MergeTree()
ORDER BY (created_at, session_id)
PARTITION BY toYYYYMM(created_at);
"""


# ===== Training Preferences Table =====
# Stores expanded pairwise preferences for ML training (DPO/RLHF)
TRAINING_PREFERENCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS training_preferences (
    -- Identity
    id String,
    created_at DateTime64(3),

    -- Source tracking (for deduplication and provenance)
    session_id String,
    cascade_id String,
    phase_name String,
    checkpoint_id String,

    -- The prompt context (reconstructed for training)
    prompt_text String,              -- Full rendered prompt
    prompt_messages String,          -- JSON array if multi-turn
    system_prompt String,            -- System instructions

    -- Preference type
    preference_type Enum8('pairwise' = 1, 'ranking' = 2, 'rating' = 3),

    -- For PAIRWISE preferences (most common, used by DPO)
    chosen_response String,
    rejected_response String,
    chosen_model Nullable(String),
    rejected_model Nullable(String),
    chosen_cost Nullable(Float64),
    rejected_cost Nullable(Float64),
    chosen_tokens Nullable(Int32),
    rejected_tokens Nullable(Int32),
    margin Float32 DEFAULT 1.0,      -- Strength of preference (for weighted training)

    -- For RANKING preferences (full ordering)
    all_responses Nullable(String),  -- JSON array of all responses
    ranking_order Nullable(String),  -- JSON array [best_idx, ..., worst_idx]
    num_responses Nullable(Int32),

    -- For RATING preferences (scored)
    ratings_json Nullable(String),   -- JSON {response_idx: rating}
    rating_scale_max Nullable(Int32), -- e.g., 5 for 1-5 scale

    -- Human signal (gold!)
    human_reasoning Nullable(String), -- Why they chose this
    human_confidence Nullable(Float32), -- How confident (0-1)

    -- Mutation/model metadata (for analysis)
    chosen_mutation Nullable(String),  -- What prompt mutation was used
    rejected_mutation Nullable(String),
    model_comparison Bool DEFAULT false, -- Was this cross-model comparison?

    -- Quality flags
    reasoning_quality Nullable(Float32), -- Auto-scored reasoning quality
    is_tie Bool DEFAULT false,           -- Human said "equal"
    is_rejection Bool DEFAULT false      -- Human rejected all
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (created_at, session_id, preference_type);
"""

def get_schema(table_name: str = "unified_logs") -> str:
    """
    Get the CREATE TABLE statement for a table.

    Args:
        table_name: Name of the table (default: unified_logs)

    Returns:
        CREATE TABLE SQL statement
    """
    schemas = {
        "unified_logs": UNIFIED_LOGS_SCHEMA,
        "checkpoints": CHECKPOINTS_SCHEMA,
        "training_preferences": TRAINING_PREFERENCES_SCHEMA,
    }
    if table_name in schemas:
        return schemas[table_name]
    else:
        raise ValueError(f"Unknown table: {table_name}. Available: {list(schemas.keys())}")


def get_indexes(table_name: str = "unified_logs") -> str:
    """
    Get the index creation statements for a table.

    Args:
        table_name: Name of the table (default: unified_logs)

    Returns:
        ALTER TABLE SQL statements for indexes
    """
    indexes = {
        "unified_logs": UNIFIED_LOGS_INDEXES,
        # Add indexes for other tables as needed
    }
    if table_name in indexes:
        return indexes[table_name]
    else:
        raise ValueError(f"No indexes defined for table: {table_name}")


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
    }
