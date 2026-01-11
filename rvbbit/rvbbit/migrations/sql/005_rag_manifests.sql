-- Migration: 005_rag_manifests
-- Description: Create rag_manifests table - RAG document metadata
-- Author: RVBBIT
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS rag_manifests (
    doc_id String,
    rag_id String,
    rel_path String,
    abs_path String,
    file_hash String,
    file_size UInt64,
    mtime Float64,
    chunk_count UInt32,
    content_hash String,
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Indexes
    INDEX idx_rag_id rag_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_rel_path rel_path TYPE bloom_filter GRANULARITY 1,
    INDEX idx_file_hash file_hash TYPE bloom_filter GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (rag_id, rel_path);
