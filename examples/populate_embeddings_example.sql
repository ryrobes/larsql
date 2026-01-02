-- ============================================================================
-- Populating Embeddings for VECTOR_SEARCH
-- ============================================================================
--
-- VECTOR_SEARCH requires embeddings to be stored in the rvbbit_embeddings
-- table in ClickHouse. This example shows how to populate embeddings for
-- your tables.
--
-- Note: EMBED() generates embeddings but doesn't automatically store them
-- with table/row associations. You need to explicitly store them.
-- ============================================================================

-- Example: Products table
CREATE TABLE products (
    id INTEGER,
    name VARCHAR,
    description VARCHAR,
    price DOUBLE
);

INSERT INTO products VALUES
(1, 'Bamboo Toothbrush', 'Eco-friendly bamboo toothbrush made from sustainable materials', 12.99),
(2, 'Cotton T-Shirt', 'Organic cotton t-shirt, fair trade certified', 29.99),
(3, 'Water Bottle', 'Reusable stainless steel water bottle, BPA-free', 34.99),
(4, 'Solar Charger', 'Portable solar-powered phone charger', 49.99),
(5, 'Recycled Notebook', 'Notebook made from 100% recycled paper', 14.99);

-- ============================================================================
-- Step 1: Generate embeddings and store them
-- ============================================================================

-- Currently, we need to store embeddings via a Python script or custom function
-- This is a known limitation - we're working on a simpler SQL-only approach

-- For now, use this Python script to populate embeddings:

/*
from rvbbit.traits.embedding_storage import agent_embed, clickhouse_store_embedding
import duckdb

# Connect to your database
conn = duckdb.connect('your_database.duckdb')

# Get all products
products = conn.execute("SELECT id, description FROM products").fetchall()

# Generate and store embeddings
for product_id, description in products:
    # Generate embedding
    result = agent_embed(description)
    embedding = result['embedding']

    # Store in ClickHouse
    clickhouse_store_embedding(
        source_table='products',
        source_id=str(product_id),
        text=description,
        embedding=embedding,
        model=result['model']
    )

print(f"Stored {len(products)} embeddings")
*/

-- ============================================================================
-- Step 2: Verify embeddings are stored
-- ============================================================================

-- After running the Python script, verify in ClickHouse:
-- (Run this in ClickHouse client, not via PostgreSQL wire protocol)
/*
SELECT
    source_table,
    COUNT(*) as embedding_count,
    embedding_model,
    embedding_dim
FROM rvbbit_embeddings
GROUP BY source_table, embedding_model, embedding_dim;
*/

-- ============================================================================
-- Step 3: Use VECTOR_SEARCH
-- ============================================================================

-- Now VECTOR_SEARCH will work!
SELECT * FROM VECTOR_SEARCH('eco-friendly products', 'products', 5);

-- Should return:
-- id | text | similarity | distance
-- "1" | "Eco-friendly bamboo toothbrush..." | 0.89 | 0.11
-- "5" | "Notebook made from recycled paper..." | 0.78 | 0.22
-- ...

-- ============================================================================
-- FUTURE: Simplified embedding storage (coming soon!)
-- ============================================================================

-- In the future, we'll add a STORE_EMBEDDINGS() function:
/*
-- Generate and store embeddings in one step
SELECT STORE_EMBEDDINGS('products', id, description)
FROM products;

-- Or auto-store with EMBED:
SELECT id, EMBED(description, store_as='products') FROM products;
*/

-- For now, use the Python script approach above.

-- ============================================================================
