-- Migration: 010_session_state
-- Description: Create session_state table - durable execution coordination
-- Author: LARS
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS session_state (
    -- Identity
    session_id String,
    cascade_id String,
    parent_session_id Nullable(String),

    -- Caller Tracking (for grouping related sessions)
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
    blocked_on Nullable(String),
    blocked_description Nullable(String),
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
