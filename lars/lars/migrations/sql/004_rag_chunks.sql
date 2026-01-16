-- Migration: 004_rag_chunks
-- Description: Create rag_chunks table - RAG vector storage
-- Author: LARS
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id UUID DEFAULT generateUUIDv4(),
    rag_id String,
    doc_id String,
    rel_path String,
    chunk_index UInt32,

    -- Content
    text String,
    char_start UInt32,
    char_end UInt32,
    start_line UInt32,
    end_line UInt32,

    -- Metadata
    file_hash String,
    created_at DateTime64(3) DEFAULT now64(3),

    -- Vector Embedding
    embedding Array(Float32),
    embedding_model LowCardinality(String),
    embedding_dim UInt16,

    -- Indexes
    INDEX idx_rag_id rag_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_doc_id doc_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_rel_path rel_path TYPE bloom_filter GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (rag_id, doc_id, chunk_index)
PARTITION BY rag_id;
