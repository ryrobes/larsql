-- Context Cards table for auto-context system
-- Stores message summaries and embeddings for intelligent context management
-- Joined with unified_logs via (session_id, content_hash) for original content retrieval

CREATE TABLE IF NOT EXISTS context_cards (
    -- Identity (composite key - joins with unified_logs)
    session_id String,
    content_hash String,  -- FK to unified_logs.content_hash (16-char SHA256 prefix)

    -- Summary content
    summary String,                         -- 1-2 sentence summary of the message
    keywords Array(String) DEFAULT [],      -- Extracted keywords for heuristic matching

    -- Embedding for semantic search
    embedding Array(Float32) DEFAULT [],    -- 768-1536 dimensions
    embedding_model LowCardinality(Nullable(String)),
    embedding_dim Nullable(UInt16),

    -- Metadata for selection
    estimated_tokens UInt32 DEFAULT 0,      -- Token count of original message
    role LowCardinality(String),            -- user/assistant/tool/system
    phase_name Nullable(String),            -- Phase this message belongs to
    turn_number Nullable(UInt32),           -- Turn within phase

    -- Importance markers
    is_anchor Bool DEFAULT false,           -- Always include in context
    is_callout Bool DEFAULT false,          -- User-marked as important
    callout_name Nullable(String),

    -- Generation metadata
    generated_at DateTime64(3) DEFAULT now64(3),
    generator_model LowCardinality(Nullable(String)),  -- Model used for summarization

    -- Message timestamp (for recency scoring)
    message_timestamp DateTime64(3) DEFAULT now64(3),

    -- Cascade context
    cascade_id Nullable(String),

    -- Indexes for common query patterns
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_phase phase_name TYPE bloom_filter GRANULARITY 1,
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
