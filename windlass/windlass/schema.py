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

def get_schema(table_name: str = "unified_logs") -> str:
    """
    Get the CREATE TABLE statement for a table.

    Args:
        table_name: Name of the table (default: unified_logs)

    Returns:
        CREATE TABLE SQL statement
    """
    if table_name == "unified_logs":
        return UNIFIED_LOGS_SCHEMA
    else:
        raise ValueError(f"Unknown table: {table_name}")

def get_indexes(table_name: str = "unified_logs") -> str:
    """
    Get the index creation statements for a table.

    Args:
        table_name: Name of the table (default: unified_logs)

    Returns:
        ALTER TABLE SQL statements for indexes
    """
    if table_name == "unified_logs":
        return UNIFIED_LOGS_INDEXES
    else:
        raise ValueError(f"Unknown table: {table_name}")
