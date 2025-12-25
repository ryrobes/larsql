-- Research Sessions - Frozen snapshots of interactive research cascades
-- Enables temporal versioning, resumption, and branching

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
    phases_visited String,  -- JSON array of phase names
    tools_used String,  -- JSON array of tool names

    -- Taxonomy
    tags String,  -- JSON array of tags for filtering

    -- Branching/Resumption (for future)
    parent_session_id Nullable(String),  -- If this was branched from another session
    branch_point_checkpoint_id Nullable(String),  -- Which checkpoint was the branch point

    -- Timestamps
    updated_at DateTime  -- Last modification
)
ENGINE = MergeTree()
ORDER BY (cascade_id, frozen_at, id)
SETTINGS index_granularity = 8192;

-- Index for fast lookups
-- CREATE INDEX IF NOT EXISTS idx_cascade_id ON research_sessions (cascade_id);
-- CREATE INDEX IF NOT EXISTS idx_original_session ON research_sessions (original_session_id);
