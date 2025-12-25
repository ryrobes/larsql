-- Migration: Add prompt_lineage table for prompt evolution tracking
-- Date: 2025-12-10
-- Description: Phase 3 of Sextant evolution - tracks prompt lineage across generations
--
-- This table enables:
-- - Tracking prompt "family trees" (base → mutation → reforge)
-- - N-gram fingerprinting for pattern analysis
-- - Cross-session comparisons within the same species
-- - ELO-style tournament rankings (future)

CREATE TABLE IF NOT EXISTS prompt_lineage (
    -- Identity
    lineage_id UUID DEFAULT generateUUIDv4(),
    session_id String,
    cascade_id String,
    cell_name String,
    trace_id String,                -- Links to unified_logs.trace_id

    -- Species (what makes prompts comparable)
    species_hash String,

    -- Evolution tracking
    candidate_index Int32,
    generation Int32 DEFAULT 0,     -- 0 = base, 1+ = mutations/reforges
    parent_lineage_id Nullable(UUID),
    mutation_type LowCardinality(Nullable(String)),  -- 'rewrite', 'augment', 'approach'
    mutation_template Nullable(String),

    -- The prompt content
    full_prompt_text String CODEC(ZSTD(3)),
    prompt_hash String,             -- For deduplication

    -- Vector embedding (populated async)
    prompt_embedding Array(Float32) DEFAULT [],
    embedding_model LowCardinality(Nullable(String)),
    embedding_dim Nullable(UInt16),

    -- N-gram fingerprint (top distinctive patterns)
    bigrams Array(String) DEFAULT [],
    trigrams Array(String) DEFAULT [],
    quadgrams Array(String) DEFAULT [],
    fingerprint Array(String) DEFAULT [],  -- Top 20 most distinctive across all n-grams

    -- Battle results
    is_winner Bool DEFAULT false,
    evaluator_score Nullable(Float32),
    cost Nullable(Float64),
    duration_ms Nullable(Float64),
    tokens_in Nullable(Int32),
    tokens_out Nullable(Int32),

    -- Model (filterable, not part of species)
    model LowCardinality(Nullable(String)),

    -- Timestamps
    created_at DateTime64(3) DEFAULT now64(3),

    -- Indexes
    INDEX idx_species species_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_trace trace_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_is_winner is_winner TYPE set(2) GRANULARITY 1,
    INDEX idx_generation generation TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (species_hash, cascade_id, cell_name, created_at)
PARTITION BY toYYYYMM(created_at)
TTL created_at + INTERVAL 1 YEAR
SETTINGS index_granularity = 8192;

-- Verify the table was created
SELECT
    name,
    engine,
    total_rows
FROM system.tables
WHERE name = 'prompt_lineage';
