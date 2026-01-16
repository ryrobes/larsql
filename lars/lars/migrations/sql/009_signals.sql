-- Migration: 009_signals
-- Description: Create signals table - cross-cascade communication
-- Author: LARS
-- Date: 2026-01-10

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
