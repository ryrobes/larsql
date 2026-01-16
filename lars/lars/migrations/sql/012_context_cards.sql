-- Migration: 012_context_cards
-- Description: Create context_cards table - auto-context summaries for intelligent context management
-- Author: LARS
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS context_cards (
    -- Identity (composite key - joins with unified_logs)
    session_id String,
    content_hash String,

    -- Summary content
    summary String,
    keywords Array(String) DEFAULT [],

    -- Embedding for semantic search
    embedding Array(Float32) DEFAULT [],
    embedding_model LowCardinality(Nullable(String)),
    embedding_dim Nullable(UInt16),

    -- Metadata for selection
    estimated_tokens UInt32 DEFAULT 0,
    role LowCardinality(String),
    cell_name Nullable(String),
    turn_number Nullable(UInt32),

    -- Importance markers
    is_anchor Bool DEFAULT false,
    is_callout Bool DEFAULT false,
    callout_name Nullable(String),

    -- Generation metadata
    generated_at DateTime64(3) DEFAULT now64(3),
    generator_model LowCardinality(Nullable(String)),

    -- Message timestamp (for recency scoring)
    message_timestamp DateTime64(3) DEFAULT now64(3),

    -- Cascade context
    cascade_id Nullable(String),

    -- Indexes for common query patterns
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_content_hash content_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_is_anchor is_anchor TYPE set(2) GRANULARITY 1,
    INDEX idx_is_callout is_callout TYPE set(2) GRANULARITY 1,
    INDEX idx_keywords keywords TYPE bloom_filter GRANULARITY 1,
    INDEX idx_timestamp message_timestamp TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(generated_at)
ORDER BY (session_id, content_hash)
PARTITION BY toYYYYMM(message_timestamp)
TTL message_timestamp + INTERVAL 90 DAY;
