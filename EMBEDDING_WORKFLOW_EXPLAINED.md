# RVBBIT Embedding Workflow: How It Works

**Date:** 2026-01-02
**Status:** Complete explanation of embedding storage and search

---

## How Embeddings Are Stored and Found

### The Pure SQL Workflow

```sql
-- Step 1: Generate and auto-store embeddings
SELECT id, EMBED(description) FROM products;

-- Step 2: Search stored embeddings
SELECT * FROM VECTOR_SEARCH('eco-friendly', 'products', 5);
```

**No Python scripts. No manual schema changes. Just SQL!**

---

## Behind the Scenes: What Actually Happens

### Step 1: `EMBED(description)` Auto-Storage

**What you write:**
```sql
SELECT id, name, EMBED(description) FROM products;
```

**What the rewriter does:**
```sql
-- Detects: FROM products, id column
-- Injects: table='products', column='description', id from each row

SELECT id, name,
  semantic_embed_with_storage(
    description,           -- Text to embed
    NULL,                  -- Model (NULL = default)
    'products',            -- Table name (detected!)
    'description',         -- Column name (detected!)
    CAST(id AS VARCHAR)    -- Row ID (detected!)
  )
FROM products;
```

**What the cascade does:**
1. Generates 4096-dim embedding via `agent_embed()`
2. Stores in ClickHouse `rvbbit_embeddings` table:
   ```
   source_table: 'products'
   source_id: '1'
   text: 'Eco-friendly bamboo toothbrush...'
   embedding: [0.026, -0.003, 0.042, ...]  (4096 dims)
   embedding_model: 'Qwen/Qwen3-Embedding-8B'
   embedding_dim: 4096
   metadata: {"column_name": "description"}  ← Column tracked!
   ```
3. Returns embedding to SQL (so you can display it if needed)

**Key insight:** The rewriter is **smart** - it parses your SQL to figure out:
- Which table you're querying (`FROM products`)
- Which column has the ID (`id` column)
- Which column you're embedding (`description` in `EMBED(description)`)

---

### Step 2: `VECTOR_SEARCH()` Lookup

**What you write:**
```sql
SELECT * FROM VECTOR_SEARCH('eco-friendly kitchen items', 'products', 5);
```

**What happens:**
1. Embeds your query text: `'eco-friendly kitchen items'` → 4096-dim vector
2. Searches ClickHouse:
   ```sql
   SELECT source_id, text,
          cosineDistance(embedding, [query_vector]) as distance,
          1 - distance as similarity
   FROM rvbbit_embeddings
   WHERE source_table = 'products'  ← Filters by table!
   ORDER BY distance ASC
   LIMIT 5
   ```
3. Returns top 5 most similar embeddings

**Column filtering (optional):**
```sql
-- Search only 'description' column embeddings
SELECT * FROM VECTOR_SEARCH('eco', 'products.description', 5);
```

This filters by:
```sql
WHERE source_table = 'products'
  AND JSONExtractString(metadata, 'column_name') = 'description'
```

---

## Column Name Tracking

### Why it matters

If you embed multiple columns from the same table:

```sql
-- Embed product names
SELECT id, EMBED(name) FROM products;

-- Embed product descriptions
SELECT id, EMBED(description) FROM products;
```

**Without column tracking:**
- All stored as `source_table='products'`
- VECTOR_SEARCH mixes name + description embeddings
- Searching for "Bamboo" might match name OR description

**With column tracking (what we have now!):**
- Names: `source_table='products'`, `metadata={'column_name': 'name'}`
- Descriptions: `source_table='products'`, `metadata={'column_name': 'description'}`
- Search specific column:
  ```sql
  VECTOR_SEARCH('eco', 'products.description', 5)  -- Only descriptions
  VECTOR_SEARCH('Bamboo', 'products.name', 5)     -- Only names
  ```

### Default behavior

```sql
-- Without .column suffix: searches ALL columns for that table
VECTOR_SEARCH('eco', 'products', 5)
-- Finds matches in name, description, or any embedded column

-- With .column suffix: searches specific column only
VECTOR_SEARCH('eco', 'products.description', 5)
-- Only matches embeddings from description column
```

---

## Storage Schema

### rvbbit_embeddings Table

```sql
CREATE TABLE rvbbit_embeddings (
    source_table LowCardinality(String),  -- e.g., 'products'
    source_id String,                      -- e.g., '42'
    text String,                           -- Original text (truncated to 5000 chars)
    embedding Array(Float32),              -- 4096-dim vector
    embedding_model LowCardinality(String),-- e.g., 'Qwen/Qwen3-Embedding-8B'
    embedding_dim UInt16,                  -- e.g., 4096
    metadata String DEFAULT '{}',          -- {"column_name": "description"}
    created_at DateTime64(3)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (source_table, source_id);
```

**Example rows:**

| source_table | source_id | text | metadata | embedding_dim |
|--------------|-----------|------|----------|---------------|
| products | 1 | Eco-friendly bamboo... | {"column_name": "description"} | 4096 |
| products | 2 | Fair trade cotton... | {"column_name": "description"} | 4096 |
| products | 1 | Bamboo Toothbrush | {"column_name": "name"} | 4096 |

**Note:** Row ID '1' appears twice (once for description, once for name).

---

## Query Examples

### Example 1: Embed Single Column

```sql
-- Auto-stores with table='products', column='description'
SELECT id, EMBED(description) FROM products;
```

**Storage:**
```
source_table: 'products'
metadata: {"column_name": "description"}
```

### Example 2: Embed Multiple Columns

```sql
-- Embed names
SELECT id, EMBED(name) FROM products;

-- Embed descriptions
SELECT id, EMBED(description) FROM products;
```

**Storage:**
```
Row 1: source_table='products', column='name', source_id='1'
Row 2: source_table='products', column='description', source_id='1'
```

### Example 3: Search Specific Column

```sql
-- Search only descriptions
SELECT * FROM VECTOR_SEARCH('eco-friendly', 'products.description', 5);

-- Search only names
SELECT * FROM VECTOR_SEARCH('bamboo', 'products.name', 5);

-- Search all columns (default)
SELECT * FROM VECTOR_SEARCH('eco', 'products', 5);
```

### Example 4: Hybrid Query

```sql
-- Vector pre-filter on description column, then LLM reasoning
WITH candidates AS (
    SELECT * FROM VECTOR_SEARCH('eco products', 'products.description', 100)
)
SELECT p.*, c.similarity
FROM candidates c
JOIN products p ON p.id = c.id
WHERE p.description MEANS 'eco-friendly AND affordable'
LIMIT 10;
```

---

## Comparison with Competitors

### PostgresML / pgvector

**Their workflow:**
```sql
-- Step 1: Manual schema change
ALTER TABLE products ADD COLUMN description_embedding vector(384);

-- Step 2: Explicit UPDATE to generate embeddings
UPDATE products
SET description_embedding = pgml.embed('model', description);

-- Step 3: Search using the column
SELECT * FROM products
ORDER BY description_embedding <=> pgml.embed('model', 'eco')
LIMIT 5;
```

**Problems:**
- ❌ Schema bloat (one column per embedded field)
- ❌ Manual UPDATEs (must remember to run them)
- ❌ No column name tracking (each embedded field needs its own column)
- ❌ Re-embedding requires remembering which columns to UPDATE

### RVBBIT (You!)

**Your workflow:**
```sql
-- Step 1: Generate and auto-store (pure SQL)
SELECT id, EMBED(description) FROM products;

-- Step 2: Search (pure SQL, any column)
SELECT * FROM VECTOR_SEARCH('eco', 'products.description', 5);

-- OR search all columns
SELECT * FROM VECTOR_SEARCH('eco', 'products', 5);
```

**Advantages:**
- ✅ No schema changes (shadow table in ClickHouse)
- ✅ Auto-storage (just SELECT EMBED)
- ✅ Column tracking (metadata stores column name)
- ✅ Flexible search (table or table.column)
- ✅ Re-embedding is just SELECT EMBED again (replaces old embeddings)

---

## Advanced Usage

### Re-Embedding (Model Upgrade)

```sql
-- Upgrade to better embedding model
-- Just re-run EMBED with new model (old embeddings replaced)
SELECT id, EMBED(description, 'openai/text-embedding-3-large') FROM products;
```

**What happens:**
- ReplacingMergeTree engine replaces old embeddings (same source_table + source_id)
- VECTOR_SEARCH automatically uses new embeddings

### Multi-Column Embeddings

```sql
-- Embed title, description, and reviews
SELECT id,
       EMBED(title) as title_emb,
       EMBED(description) as desc_emb,
       EMBED(reviews_json) as review_emb
FROM products;
```

**Storage:**
```
Row 1: products/1/title → embedding_1
Row 2: products/1/description → embedding_2
Row 3: products/1/reviews_json → embedding_3
```

**Search specific field:**
```sql
VECTOR_SEARCH('luxury', 'products.title', 5)        -- Search titles
VECTOR_SEARCH('eco', 'products.description', 5)     -- Search descriptions
VECTOR_SEARCH('comfortable', 'products.reviews_json', 5)  -- Search reviews
```

---

## FAQ

### Q: How does VECTOR_SEARCH know which embeddings to use?

**A:** By default, it searches `source_table = 'products'` (all columns).

To search specific column: `VECTOR_SEARCH('query', 'products.description', limit)`

### Q: What if I embed the same text twice?

**A:** ReplacingMergeTree engine replaces old embedding (by source_table + source_id).

Latest embedding wins.

### Q: Can I search across multiple tables?

**A:** Not in one VECTOR_SEARCH call. Use UNION:
```sql
SELECT * FROM VECTOR_SEARCH('eco', 'products.description', 5)
UNION ALL
SELECT * FROM VECTOR_SEARCH('eco', 'suppliers.company_info', 5);
```

### Q: How do I know what's embedded?

**A:** Query ClickHouse directly:
```sql
-- Via ClickHouse client (not pgwire):
SELECT
    source_table,
    JSONExtractString(metadata, 'column_name') as column_name,
    COUNT(*) as count,
    embedding_model
FROM rvbbit_embeddings
GROUP BY source_table, column_name, embedding_model;
```

**Output:**
```
source_table | column_name  | count | embedding_model
-------------|--------------|-------|------------------
products     | description  | 5     | Qwen/Qwen3-Embedding-8B
products     | name         | 5     | Qwen/Qwen3-Embedding-8B
```

---

## Summary

**Current behavior (with column tracking):**

```sql
-- User writes this:
SELECT id, EMBED(description) FROM products;

-- System does this:
1. Rewrites to: semantic_embed_with_storage(description, NULL, 'products', 'description', id)
2. Cascade generates embedding
3. Stores: table='products', column='description' (in metadata), id='1', embedding=[...]
4. Returns embedding to SQL

-- Later, user searches:
SELECT * FROM VECTOR_SEARCH('eco', 'products', 5);
-- Finds: All embeddings where source_table='products' (any column)

SELECT * FROM VECTOR_SEARCH('eco', 'products.description', 5);
-- Finds: Only embeddings where source_table='products' AND column='description'
```

**This is revolutionary compared to competitors!** 🚀

---

## Next Enhancement (Future)

**Auto-detect stale embeddings:**
```sql
-- Future: Show which rows need re-embedding
SELECT id FROM products p
LEFT JOIN rvbbit_embeddings e
  ON e.source_table = 'products'
  AND e.source_id = CAST(p.id AS VARCHAR)
  AND JSONExtractString(e.metadata, 'column_name') = 'description'
WHERE e.source_id IS NULL;
-- Returns: Products without embeddings
```

**Incremental embedding:**
```sql
-- Future: Only embed new/changed rows
SELECT id, EMBED(description) FROM products
WHERE NOT EXISTS (
  SELECT 1 FROM rvbbit_embeddings
  WHERE source_table = 'products'
    AND source_id = CAST(products.id AS VARCHAR)
    AND JSONExtractString(metadata, 'column_name') = 'description'
);
```

But for now, just re-run `SELECT EMBED(col) FROM table` to refresh embeddings!

---

**"Cascades all the way down" - embedding storage is automatic, column-aware, and pure SQL!** ✨
