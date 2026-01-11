-- Migration: 008_cascade_template_vectors
-- Description: Create cascade_template_vectors table - semantic cascade discovery
-- Author: RVBBIT
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS cascade_template_vectors (
    cascade_id String,
    cascade_file String,
    description String,
    cell_count UInt8,

    -- Aggregated Metrics
    run_count UInt32 DEFAULT 0,
    avg_cost Nullable(Float64),
    avg_duration_seconds Nullable(Float64),
    success_rate Nullable(Float32),

    -- Vector Embeddings
    description_embedding Array(Float32),
    instructions_embedding Array(Float32),
    embedding_model LowCardinality(String),
    embedding_dim UInt16,

    -- Metadata
    last_updated DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY cascade_id;
