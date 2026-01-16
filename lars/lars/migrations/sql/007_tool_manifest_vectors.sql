-- Migration: 007_tool_manifest_vectors
-- Description: Create tool_manifest_vectors table - semantic tool discovery
-- Author: LARS
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS tool_manifest_vectors (
    tool_name String,
    tool_type Enum8('function' = 0, 'cascade' = 1, 'memory' = 2, 'validator' = 3),
    tool_description String,
    schema_json Nullable(String),
    source_path Nullable(String),

    -- Vector Embedding
    embedding Array(Float32),
    embedding_model LowCardinality(String),
    embedding_dim UInt16,

    -- Metadata
    last_updated DateTime64(3) DEFAULT now64(3),

    -- Indexes
    INDEX idx_tool_type tool_type TYPE set(10) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY tool_name;
