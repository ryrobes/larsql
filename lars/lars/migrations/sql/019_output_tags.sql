-- Migration: 019_output_tags
-- Description: Create output_tags table - cross-walk table linking tags to outputs
-- Author: LARS
-- Date: 2026-01-10

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
