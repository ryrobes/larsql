-- Migration: 002_checkpoints
-- Description: Create checkpoints table - Human-in-the-Loop tracking
-- Author: RVBBIT
-- Date: 2026-01-10

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
        'take_eval' = 2,
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

    -- For take evaluation
    take_outputs Nullable(String),
    take_metadata Nullable(String),

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
