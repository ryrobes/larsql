-- Migration: 014_intra_context_shadow_assessments
-- Description: Create intra_context_shadow_assessments table - intra-cell context analysis
-- Author: RVBBIT
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS intra_context_shadow_assessments (
    -- Identity
    assessment_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Session context
    session_id String,
    cascade_id String,
    cell_name String,
    take_index Nullable(Int16),
    turn_number UInt16,
    is_loop_retry Bool DEFAULT false,

    -- Config scenario being evaluated
    config_window UInt8,
    config_mask_after UInt8,
    config_min_masked_size UInt16,
    config_compress_loops Bool,
    config_preserve_reasoning Bool,
    config_preserve_errors Bool,

    -- Turn-level aggregate metrics
    full_history_size UInt16,
    context_size UInt16,
    tokens_before UInt32,
    tokens_after UInt32,
    tokens_saved UInt32,
    compression_ratio Float32,
    messages_masked UInt16,
    messages_preserved UInt16,
    messages_truncated UInt16,

    -- Per-message breakdown (JSON array)
    message_breakdown String DEFAULT '[]',

    -- Comparison flags (vs baseline/actual)
    tokens_vs_baseline_saved UInt32,
    tokens_vs_baseline_pct Float32,

    -- Actual vs shadow comparison
    actual_config_enabled Bool,
    actual_tokens_after Nullable(UInt32),
    differs_from_actual Bool,

    -- Assessment metadata
    assessment_batch_id String,

    -- Indexes
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_take take_index TYPE set(100) GRANULARITY 1,
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
