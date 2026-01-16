-- Migration: 011_research_sessions
-- Description: Create research_sessions table - temporal versioning for research cockpit
-- Author: LARS
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS research_sessions (
    -- Identity
    id String,
    original_session_id String,
    cascade_id String,

    -- Metadata
    title String,
    description String,
    created_at DateTime,
    frozen_at DateTime,
    status String,

    -- Context for Resumption (JSON blobs)
    context_snapshot String,
    checkpoints_data String,
    entries_snapshot String,

    -- Visual Artifacts
    mermaid_graph String,
    screenshots String,

    -- Metrics (for display in browser)
    total_cost Float64,
    total_turns UInt32,
    total_input_tokens UInt64,
    total_output_tokens UInt64,
    duration_seconds Float64,
    cells_visited String,
    tools_used String,

    -- Taxonomy
    tags String,

    -- Branching/Resumption
    parent_session_id Nullable(String),
    branch_point_checkpoint_id Nullable(String),

    -- Timestamps
    updated_at DateTime,

    -- Indexes
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_original_session original_session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_frozen frozen_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (cascade_id, frozen_at, id)
PARTITION BY toYYYYMM(frozen_at);
