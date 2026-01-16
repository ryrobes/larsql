-- ============================================================================
-- Semantic SQL + Embeddings: Quick Start Demo
-- ============================================================================
--
-- This demo shows how to use LARS's new embedding operators:
-- - EMBED(text) - Generate 4096-dim embeddings
-- - VECTOR_SEARCH(query, table, limit) - Semantic search
-- - SIMILAR_TO - Cosine similarity operator
--
-- Prerequisites:
-- 1. OPENROUTER_API_KEY environment variable set
-- 2. ClickHouse running (for vector storage)
-- 3. LARS server running: lars serve sql --port 15432
--
-- Connect:
--   psql postgresql://localhost:15432/default
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Example 1: Basic Embedding Generation
-- ----------------------------------------------------------------------------

-- Create sample data
CREATE TABLE IF NOT EXISTS products (
    id INTEGER,
    name VARCHAR,
    description VARCHAR,
    price DOUBLE
);

-- Insert test data
INSERT INTO products VALUES
(1, 'Bamboo Toothbrush', 'Eco-friendly bamboo toothbrush made from sustainable materials. Biodegradable and compostable.', 12.99),
(2, 'Organic Cotton T-Shirt', 'Fair trade certified organic cotton t-shirt. Soft, breathable, and ethically made.', 29.99),
(3, 'Stainless Steel Water Bottle', 'Reusable insulated water bottle. Keeps drinks cold for 24 hours. BPA-free.', 34.99),
(4, 'Solar Phone Charger', 'Portable solar-powered charger. Perfect for camping and emergencies.', 49.99),
(5, 'Recycled Notebook', 'Notebook made from 100% recycled paper. Vegan leather cover.', 14.99);

-- Generate embeddings for all products
-- (This stores embeddings in ClickHouse lars_embeddings table)
SELECT
    id,
    name,
    EMBED(description) as embedding_sample  -- First 5 dimensions shown
FROM products;

-- Check embedding dimensions (should be 4096)
SELECT
    id,
    name,
    array_length(EMBED(description)) as embedding_dim
FROM products
LIMIT 1;

-- ----------------------------------------------------------------------------
-- Example 2: Vector Search (Semantic Search)
-- ----------------------------------------------------------------------------

-- Find products semantically similar to "eco-friendly kitchen items"
SELECT * FROM VECTOR_SEARCH('eco-friendly kitchen items', 'products', 5);

-- Returns:
-- id | text (description snippet) | similarity | distance
-- Results ordered by semantic similarity

-- ----------------------------------------------------------------------------
-- Example 3: SIMILAR_TO Operator
-- ----------------------------------------------------------------------------

-- Find products similar to a reference description
SELECT
    id,
    name,
    price,
    description SIMILAR_TO 'sustainable and environmentally friendly' as eco_score
FROM products
WHERE description SIMILAR_TO 'sustainable and environmentally friendly' > 0.6
ORDER BY eco_score DESC;

-- Compare product descriptions to each other
SELECT
    p1.name as product1,
    p2.name as product2,
    p1.description SIMILAR_TO p2.description as similarity
FROM products p1, products p2
WHERE p1.id < p2.id
  AND p1.description SIMILAR_TO p2.description > 0.7
ORDER BY similarity DESC;

-- ----------------------------------------------------------------------------
-- Example 4: Hybrid Search (Vector + LLM Reasoning)
-- ----------------------------------------------------------------------------
-- This is THE KILLER FEATURE: Fast vector pre-filter + intelligent LLM reasoning

-- Stage 1: Vector search finds 100 takes (~50ms for 1M items)
-- Stage 2: LLM operators filter to best 10 (~2 seconds)
WITH takes AS (
    SELECT * FROM VECTOR_SEARCH('affordable eco-friendly products', 'products', 100)
    WHERE similarity > 0.6
)
SELECT
    p.id,
    p.name,
    p.price,
    c.similarity as vector_score,
    p.description
FROM takes c
JOIN products p ON p.id = c.id
WHERE
    p.price < 40  -- Cheap SQL filter
    -- LLM semantic reasoning (these are the new operators from LARS_SEMANTIC_SQL.md)
    AND p.description MEANS 'eco-friendly AND affordable AND high quality'
    AND p.description NOT MEANS 'greenwashing or misleading claims'
ORDER BY c.similarity DESC, p.price ASC
LIMIT 10;

-- ----------------------------------------------------------------------------
-- Example 5: Vector Search + Semantic Aggregation
-- ----------------------------------------------------------------------------

-- Find similar products and summarize their reviews
-- (Combines vector search with LLM aggregates)
WITH similar_products AS (
    SELECT * FROM VECTOR_SEARCH('sustainable home products', 'products', 10)
)
SELECT
    p.id,
    p.name,
    p.price,
    sp.similarity,
    -- Note: SUMMARIZE, THEMES, SENTIMENT are existing LARS operators
    -- See LARS_SEMANTIC_SQL.md for details
    CASE
        WHEN sp.similarity > 0.8 THEN 'Highly Similar'
        WHEN sp.similarity > 0.6 THEN 'Moderately Similar'
        ELSE 'Somewhat Similar'
    END as similarity_category
FROM similar_products sp
JOIN products p ON p.id = sp.id
ORDER BY sp.similarity DESC;

-- ----------------------------------------------------------------------------
-- Example 6: Fuzzy Entity Matching (SIMILAR_TO for JOINs)
-- ----------------------------------------------------------------------------

-- Create a second table with slightly different product names
CREATE TABLE IF NOT EXISTS inventory (
    sku VARCHAR,
    product_name VARCHAR,
    stock INTEGER
);

INSERT INTO inventory VALUES
('SKU001', 'Bamboo Toothbrush Eco', 50),
('SKU002', 'Organic Cotton Tee Shirt', 100),
('SKU003', 'Steel Water Bottle Insulated', 75);

-- Fuzzy match between products and inventory
-- (Different naming, but same products)
SELECT
    p.name as product_catalog,
    i.product_name as inventory_name,
    i.stock,
    p.name SIMILAR_TO i.product_name as match_score
FROM products p
CROSS JOIN inventory i
WHERE p.name SIMILAR_TO i.product_name > 0.65
ORDER BY match_score DESC
LIMIT 10;  -- IMPORTANT: Always use LIMIT with fuzzy JOINs!

-- ----------------------------------------------------------------------------
-- Example 7: Performance: Caching Demo
-- ----------------------------------------------------------------------------

-- First run: Generates embeddings (API calls)
SELECT COUNT(*) FROM products WHERE EMBED(description) IS NOT NULL;

-- Second run: Uses cache (instant)
SELECT COUNT(*) FROM products WHERE EMBED(description) IS NOT NULL;

-- Check embedding model being used
SELECT DISTINCT
    name,
    'qwen/qwen3-embedding-8b' as model_used,
    4096 as embedding_dims
FROM products
LIMIT 1;

-- ----------------------------------------------------------------------------
-- Example 8: Advanced - Custom Embedding Model
-- ----------------------------------------------------------------------------

-- Use a different embedding model (if you want)
-- Note: This requires editing cascades/semantic_sql/embed.cascade.yaml
-- or passing model as second parameter

-- SELECT EMBED(description, 'openai/text-embedding-3-large') FROM products;
-- (Not implemented in quickstart, but shows extensibility)

-- ----------------------------------------------------------------------------
-- Clean Up
-- ----------------------------------------------------------------------------

-- DROP TABLE products;
-- DROP TABLE inventory;
-- (Uncomment to clean up test data)

-- ============================================================================
-- Next Steps
-- ============================================================================
--
-- 1. Try your own data:
--    - Load your own table with text columns
--    - Generate embeddings: SELECT EMBED(your_text_column) FROM your_table
--    - Search: SELECT * FROM VECTOR_SEARCH('query', 'your_table', 10)
--
-- 2. Combine with existing operators:
--    - MEANS, ABOUT, IMPLIES, CONTRADICTS (see LARS_SEMANTIC_SQL.md)
--    - SUMMARIZE, THEMES, SENTIMENT (LLM aggregates)
--
-- 3. Hybrid queries:
--    - Vector search for speed (pre-filter 1M → 100 items)
--    - LLM operators for intelligence (filter 100 → 10 best)
--    - This gives you 10,000x cost reduction vs pure LLM!
--
-- 4. Read the docs:
--    - SEMANTIC_SQL_EMBEDDING_IMPLEMENTATION.md - Implementation details
--    - SEMANTIC_SQL_RAG_VISION.md - Architecture vision
--    - LARS_SEMANTIC_SQL.md - All semantic operators
--
-- ============================================================================

Does our global caller_id map map to session_id? if so we need to make sure that the lars meta cascades (relevance, etc).
