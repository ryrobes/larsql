-- LARS Embeddings table for Semantic SQL vector operations
-- Stores text embeddings for EMBED(), VECTOR_SEARCH(), and SIMILAR_TO operators
--
-- Architecture:
--   - Shadow table approach: Stores embeddings separately from source data
--   - Source tracking: Links back to original table + row ID
--   - Model-aware: Stores which embedding model was used
--   - Dimension-flexible: Supports any embedding dimension (4096 default)
--
-- Usage:
--   - EMBED(text) → Generates embedding, stores here automatically
--   - VECTOR_SEARCH('query', 'table', 10) → Searches this table using cosineDistance()
--   - text1 SIMILAR_TO text2 → Computes similarity via embeddings
--
-- Performance:
--   - Vector search: ~50ms for 1M vectors (ClickHouse native cosineDistance)
--   - Indexed by (source_table, source_id) for fast lookups
--   - ReplacingMergeTree: Updates replace old embeddings (re-embedding support)

CREATE TABLE IF NOT EXISTS lars_embeddings (
    -- Source tracking: Which table/row does this embedding belong to?
    source_table LowCardinality(String),  -- e.g., 'products', 'documents'
    source_id String,                      -- e.g., '42', 'doc_abc123'

    -- Original text (truncated to 5000 chars for storage)
    text String,

    -- Embedding vector (4096 dims for qwen/qwen3-embedding-8b)
    embedding Array(Float32),

    -- Embedding metadata
    embedding_model LowCardinality(String),  -- e.g., 'qwen/qwen3-embedding-8b'
    embedding_dim UInt16,                     -- e.g., 4096

    -- Additional metadata (JSON string for extensibility)
    -- Can store: original_length, chunking_info, custom tags, etc.
    metadata String DEFAULT '{}',

    -- Timestamp
    created_at DateTime64(3) DEFAULT now64(3),

    -- Bloom filter indexes for fast filtering
    INDEX idx_source_table source_table TYPE bloom_filter GRANULARITY 1,
    INDEX idx_source_id source_id TYPE bloom_filter GRANULARITY 1
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (source_table, source_id)
SETTINGS index_granularity = 8192;

-- Note on ReplacingMergeTree:
--   - When re-embedding text (e.g., after model upgrade), INSERT with same
--     (source_table, source_id) will mark old row as replaced
--   - FINAL or OPTIMIZE removes old versions
--   - Perfect for keeping embeddings up-to-date

-- Note on ORDER BY (source_table, source_id):
--   - Enables fast lookups by source table + ID
--   - Vector search filters by source_table first, then uses cosineDistance()
--   - Example: WHERE source_table = 'products' AND cosineDistance(...) < 0.3

-- Example Queries:
--
-- 1. Vector similarity search:
--   SELECT source_id, text,
--          cosineDistance(embedding, [0.1, 0.2, ...]) AS distance,
--          1 - cosineDistance(embedding, [0.1, 0.2, ...]) AS similarity
--   FROM lars_embeddings
--   WHERE source_table = 'products'
--   ORDER BY distance ASC
--   LIMIT 10;
--
-- 2. Check embedding coverage:
--   SELECT source_table,
--          COUNT(*) as embedded_count,
--          embedding_model,
--          embedding_dim
--   FROM lars_embeddings
--   GROUP BY source_table, embedding_model, embedding_dim;
--
-- 3. Find outdated embeddings (different model):
--   SELECT source_table, COUNT(*) as count
--   FROM lars_embeddings
--   WHERE embedding_model != 'qwen/qwen3-embedding-8b'
--   GROUP BY source_table;
