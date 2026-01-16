# Vector Search & Embedding - User Guide

**Elegant SQL syntax for semantic search powered by embeddings.**

---

## Quick Start

### 1. Embed Your Data

```sql
-- ClickHouse backend (fastest, pure semantic):
LARS EMBED articles.content
USING (SELECT id::VARCHAR AS id, content AS text FROM articles);

-- Elasticsearch backend (hybrid semantic + keyword support):
LARS EMBED articles.content
USING (SELECT id::VARCHAR AS id, content AS text FROM articles)
WITH (backend='elastic', index='articles_idx');
```

### 2. Search Your Data (Pick Your Backend & Mode)

```sql
-- VECTOR_SEARCH → ClickHouse (pure semantic, fastest):
SELECT * FROM VECTOR_SEARCH('climate change policy', articles.content, 10);

-- ELASTIC_SEARCH → Elastic (pure semantic):
SELECT * FROM ELASTIC_SEARCH('climate change policy', articles.content, 10);

-- HYBRID_SEARCH → Elastic (semantic + keyword mix):
SELECT * FROM HYBRID_SEARCH('Venezuela crisis', bird_line.text, 20, 0.5, 0.7, 0.3);

-- KEYWORD_SEARCH → Elastic (pure BM25 keyword):
SELECT * FROM KEYWORD_SEARCH('MacBook Pro M3 16-inch', products.name, 10);
```

**That's it!** Natural syntax with field references (`table.column`), automatic backend routing, clean results.

---

## Four Search Functions - Which to Use?

| Function | Backend | Mode | Use When |
|----------|---------|------|----------|
| **VECTOR_SEARCH** | ClickHouse | Pure semantic | Fast concept search (default choice) |
| **ELASTIC_SEARCH** | Elastic | Pure semantic | Need Elastic features (aggregations, etc.) |
| **HYBRID_SEARCH** | Elastic | Semantic + keyword | Balance concepts AND exact terms |
| **KEYWORD_SEARCH** | Elastic | Pure BM25 | Exact term matching (SKUs, names, codes) |

### Decision Tree

```
Need exact term matching? (SKUs, product codes, names)
  → KEYWORD_SEARCH

Need concept understanding + term matching?
  → HYBRID_SEARCH (tune weights to your needs)

Need pure concept understanding?
  ├─ Want fastest? → VECTOR_SEARCH (ClickHouse)
  └─ Need Elastic? → ELASTIC_SEARCH

Not sure? → Start with VECTOR_SEARCH (fastest, works great)
```

---

## LARS EMBED Statement

### Syntax

```sql
LARS EMBED <table>.<column>
USING (<select_query>)
[WITH (<options>)]
```

### Required Components

**Field Reference:** `table.column` identifier
- Example: `bird_line.text`, `articles.content`, `products.description`
- Must be valid SQL identifier (no quotes, special chars)

**USING Clause:** Must return exactly these columns:
- `id`: VARCHAR (primary key, must be unique)
- `text`: VARCHAR (content to embed)

**Optional: `metadata` column** (JSON) for additional fields

### WITH Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `backend` | String | `'clickhouse'` | Backend: `'clickhouse'` or `'elastic'` |
| `batch_size` | Integer | `100` | Rows per batch |
| `index` | String | `'lars_embeddings'` | Elastic index name (elastic only) |

### Examples

**Basic (ClickHouse):**
```sql
LARS EMBED bird_line.text
USING (SELECT id::VARCHAR AS id, text FROM bird_line);
```

**With Batch Size:**
```sql
LARS EMBED articles.content
USING (SELECT id::VARCHAR AS id, content AS text FROM articles LIMIT 10000)
WITH (backend='clickhouse', batch_size=50);
```

**Elasticsearch:**
```sql
LARS EMBED products.description
USING (SELECT id::VARCHAR AS id, description AS text FROM products)
WITH (backend='elastic', batch_size=200, index='products_idx');
```

**With Metadata:**
```sql
LARS EMBED documents.body
USING (
  SELECT
    id::VARCHAR AS id,
    body AS text,
    to_json({'title': title, 'author': author, 'date': published_at}) AS metadata
  FROM documents
);
```

**From CSV File:**
```sql
LARS EMBED docs.content
USING (
  SELECT
    row_number::VARCHAR AS id,
    content AS text
  FROM read_csv('documents.csv')
);
```

**Background Embedding (async):**
```sql
BACKGROUND
LARS EMBED large_corpus.text
USING (SELECT id::VARCHAR AS id, text FROM large_corpus)
WITH (batch_size=500);
```

---

## VECTOR_SEARCH Function

### Signature

```sql
VECTOR_SEARCH(
  query: VARCHAR,           -- Search query
  field: table.column,      -- Field reference (identifier, not string!)
  limit: INTEGER,           -- Max results
  [min_score: DOUBLE]       -- Optional: score threshold (0.0-1.0)
)
RETURNS TABLE (
  id VARCHAR,
  score DOUBLE,
  chunk_text VARCHAR,
  metadata JSON
)
```

### Arguments

1. **query** (required): Search query text
   - Example: `'climate change'`, `'renewable energy'`

2. **field** (required): Field reference as **identifier**
   - Example: `articles.content`, `bird_line.text`
   - **Not** a string: ~~`'articles.content'`~~

3. **limit** (required): Maximum results to return
   - Example: `10`, `50`, `100`

4. **min_score** (optional): Minimum similarity score (0.0-1.0)
   - Example: `0.5` (only results with score ≥ 0.5)
   - Default: `0.0` (all results)

### Return Columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Document/chunk ID |
| `score` | DOUBLE | Similarity score (0.0-1.0) |
| `chunk_text` | VARCHAR | Matched text content |
| `metadata` | JSON | Additional fields (column_name, table_name, etc.) |

### Examples

**Basic Search:**
```sql
SELECT * FROM VECTOR_SEARCH('climate change', articles.content, 10);
```

**With Score Threshold:**
```sql
SELECT * FROM VECTOR_SEARCH('renewable energy', articles.content, 20, 0.6);
-- Only results with score >= 0.6
```

**Select Specific Columns:**
```sql
SELECT id, score, chunk_text
FROM VECTOR_SEARCH('machine learning', papers.abstract, 5);
```

**Join with Source Table:**
```sql
SELECT
  a.title,
  a.author,
  vs.score,
  vs.chunk_text
FROM articles a
JOIN VECTOR_SEARCH('climate policy', articles.content, 10) vs
  ON vs.id = a.id::VARCHAR
WHERE vs.score > 0.7
ORDER BY vs.score DESC;
```

**Filter and Re-rank:**
```sql
SELECT *
FROM VECTOR_SEARCH('sustainable products', products.description, 100, 0.5)
WHERE json_extract_string(metadata, '$.category') = 'electronics'
ORDER BY score DESC
LIMIT 10;
```

---

## HYBRID_SEARCH Function

### Signature

```sql
HYBRID_SEARCH(
  query: VARCHAR,                   -- Search query
  field: table.column,              -- Field reference
  limit: INTEGER,                   -- Max results
  [min_score: DOUBLE],             -- Optional: score threshold
  [semantic_weight: DOUBLE],       -- Optional: semantic score weight (default 0.7)
  [keyword_weight: DOUBLE]         -- Optional: keyword score weight (default 0.3)
)
RETURNS TABLE (
  id VARCHAR,
  score DOUBLE,
  semantic_score DOUBLE,
  keyword_score DOUBLE,
  chunk_text VARCHAR,
  metadata JSON
)
```

**Backend:** Elasticsearch with BM25 + vector hybrid scoring

### Arguments

1-3: Same as VECTOR_SEARCH

4. **min_score** (optional): Combined score threshold
   - Default: `0.0`

5. **semantic_weight** (optional): Weight for vector similarity score
   - Default: `0.7` (70% semantic)
   - Range: `0.0` to `1.0`

6. **keyword_weight** (optional): Weight for BM25 keyword score
   - Default: `0.3` (30% keyword)
   - Range: `0.0` to `1.0`

**Note:** `semantic_weight + keyword_weight` should equal `1.0`

### Return Columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Document/chunk ID |
| `score` | DOUBLE | Combined hybrid score |
| `semantic_score` | DOUBLE | Vector similarity component |
| `keyword_score` | DOUBLE | BM25 keyword component |
| `chunk_text` | VARCHAR | Matched text content |
| `metadata` | JSON | Additional fields |

### Examples

**Basic Hybrid Search:**
```sql
SELECT * FROM HYBRID_SEARCH('Venezuela political crisis', bird_line.text, 10);
-- Default: 70% semantic, 30% keyword
```

**Semantic-Heavy (90% semantic, 10% keyword):**
```sql
SELECT * FROM HYBRID_SEARCH('climate action', articles.content, 20, 0.5, 0.9, 0.1);
```

**Keyword-Heavy (30% semantic, 70% keyword):**
```sql
SELECT * FROM HYBRID_SEARCH('exact product model', products.description, 50, 0.6, 0.3, 0.7);
```

---

## ELASTIC_SEARCH Function

### Signature

```sql
ELASTIC_SEARCH(
  query: VARCHAR,           -- Search query
  field: table.column,      -- Field reference
  limit: INTEGER,           -- Max results
  [min_score: DOUBLE]       -- Optional: score threshold
)
RETURNS TABLE (
  id VARCHAR,
  score DOUBLE,
  semantic_score DOUBLE,
  keyword_score DOUBLE,
  chunk_text VARCHAR,
  metadata JSON
)
```

**Backend:** Elasticsearch pure semantic (100% vector, 0% keyword)

**When to Use:**
- You specifically need Elasticsearch (not ClickHouse)
- You want Elastic features (aggregations, facets)
- You're already on Elastic and want pure semantic

**Comparison to VECTOR_SEARCH:**
- VECTOR_SEARCH → ClickHouse (faster)
- ELASTIC_SEARCH → Elastic (more features)
- Both are pure semantic

### Examples

**Basic Elastic Search:**
```sql
SELECT * FROM ELASTIC_SEARCH('climate adaptation strategies', articles.content, 10);
```

**With Score Threshold:**
```sql
SELECT * FROM ELASTIC_SEARCH('renewable energy', articles.content, 20, 0.65);
```

**Use Elastic Aggregations:**
```sql
-- Search + aggregate by metadata:
SELECT
  json_extract_string(metadata, '$.category') AS category,
  COUNT(*) AS count,
  AVG(score) AS avg_score
FROM ELASTIC_SEARCH('sustainability', products.description, 100, 0.5)
GROUP BY category
ORDER BY avg_score DESC;
```

---

## KEYWORD_SEARCH Function

### Signature

```sql
KEYWORD_SEARCH(
  query: VARCHAR,           -- Search query
  field: table.column,      -- Field reference
  limit: INTEGER,           -- Max results
  [min_score: DOUBLE]       -- Optional: BM25 score threshold
)
RETURNS TABLE (
  id VARCHAR,
  score DOUBLE,
  semantic_score DOUBLE,    -- Will be 0.0 (no semantic)
  keyword_score DOUBLE,     -- BM25 score
  chunk_text VARCHAR,
  metadata JSON
)
```

**Backend:** Elasticsearch pure BM25 keyword search (0% vector, 100% keyword)

**When to Use:**
- Exact term matching (product codes, SKUs, model numbers)
- Known terminology search (technical terms, abbreviations)
- When semantics don't matter, exact words do

**Examples:**

**Product Code Search:**
```sql
-- Find exact SKU matches:
SELECT * FROM KEYWORD_SEARCH('SKU-12345-ABC', products.sku, 10);
```

**Model Number Search:**
```sql
-- Exact model matching:
SELECT * FROM KEYWORD_SEARCH('MacBook Pro M3 16-inch', products.name, 20);
```

**Technical Term Search:**
```sql
-- Find exact terminology (no semantic expansion):
SELECT * FROM KEYWORD_SEARCH('HTTP 502 Bad Gateway', error_logs.message, 50);
```

**Abbreviation Search:**
```sql
-- Find specific abbreviations:
SELECT * FROM KEYWORD_SEARCH('GDPR compliance', legal_docs.content, 10, 0.5);
```

---

## Comparison: All Four Functions

### Same Query, Different Backends

```sql
-- 1. VECTOR_SEARCH (ClickHouse, pure semantic)
SELECT * FROM VECTOR_SEARCH('climate change policy', articles.content, 10);
-- → Fast, conceptual understanding, ClickHouse backend

-- 2. ELASTIC_SEARCH (Elastic, pure semantic)
SELECT * FROM ELASTIC_SEARCH('climate change policy', articles.content, 10);
-- → Same as VECTOR but on Elastic (for Elastic features)

-- 3. HYBRID_SEARCH (Elastic, balanced)
SELECT * FROM HYBRID_SEARCH('climate change policy', articles.content, 10, 0.5, 0.7, 0.3);
-- → Finds conceptually similar AND exact "policy" mentions

-- 4. KEYWORD_SEARCH (Elastic, pure keyword)
SELECT * FROM KEYWORD_SEARCH('climate change policy', articles.content, 10);
-- → Only finds exact phrase "climate change policy"
```

### Results Comparison

For query **"renewable energy"**:

| Function | Finds | Backend |
|----------|-------|---------|
| VECTOR_SEARCH | "solar power", "wind turbines", "clean electricity" | CH |
| ELASTIC_SEARCH | "solar power", "wind turbines", "clean electricity" | Elastic |
| HYBRID_SEARCH | Both semantic matches AND exact "renewable energy" | Elastic |
| KEYWORD_SEARCH | Only exact "renewable energy" mentions | Elastic |

**Semantic-Only (100% semantic):**
```sql
SELECT * FROM HYBRID_SEARCH('sustainability concepts', docs.text, 30, 0.5, 1.0, 0.0);
```

**Compare Scores:**
```sql
SELECT
  chunk_text,
  score AS combined,
  semantic_score,
  keyword_score,
  (semantic_score - keyword_score) AS semantic_advantage
FROM HYBRID_SEARCH('renewable energy policy', articles.content, 20)
ORDER BY score DESC;
```

---

## Comparison: Old vs New Syntax

### Embedding

**Before (clunky):**
```sql
SELECT embed_batch(
  'bird_line',
  'text',
  (SELECT to_json(list({'id': CAST(id AS VARCHAR), 'text': text})) FROM bird_line LIMIT 100)
);
```

**After (elegant):**
```sql
LARS EMBED bird_line.text
USING (SELECT id::VARCHAR AS id, text FROM bird_line LIMIT 100);
```

**Improvement:** 70% less boilerplate, clearer intent

### Vector Search

**Before:**
```sql
SELECT * FROM read_json_auto(
  vector_search_json_3('Venezuela', 'bird_line', 10)
);
```

**After:**
```sql
SELECT * FROM VECTOR_SEARCH('Venezuela', bird_line.text, 10);
```

**Improvement:** Natural field syntax, automatic metadata filtering

### Hybrid Search

**Before (unclear multi-arity):**
```sql
SELECT * FROM vector_search_elastic('Venezuela', 'bird_line', 10, 0.5, 0.8, 0.2);
-- Wait, is this 4, 5, 6, or 7 args? Which is which?
```

**After (clear named positions):**
```sql
SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 10, 0.5, 0.8, 0.2);
--                          ^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^  ^^  ^^^  ^^^  ^^^
--                          query         field             lim min  sem  kw
```

---

## Automatic Metadata Filtering

When a table has multiple embedded columns, VECTOR_SEARCH automatically filters by column:

```sql
-- Embed multiple columns:
LARS EMBED articles.title USING (...);
LARS EMBED articles.content USING (...);
LARS EMBED articles.summary USING (...);

-- Search specific column:
SELECT * FROM VECTOR_SEARCH('climate', articles.content, 10);
-- Auto-adds: WHERE metadata.column_name = 'content'
-- Only searches content column, not title or summary!
```

**Why This Matters:** Without filtering, you'd get mixed results from all three columns.

---

## BACKGROUND Integration

Run expensive embedding/search operations asynchronously:

```sql
-- Embed large dataset in background:
BACKGROUND
LARS EMBED large_corpus.text
USING (SELECT id::VARCHAR AS id, text FROM large_corpus)
WITH (batch_size=500);

-- Returns immediately with job ID:
-- job-swift-fox-abc123

-- Check status:
SELECT * FROM job('job-swift-fox-abc123');

-- Search while embedding runs:
SELECT * FROM VECTOR_SEARCH('query', already_embedded.text, 10);
```

---

## Real-World Workflows

### Workflow 1: Document Q&A System

```sql
-- Step 1: Embed documents
LARS EMBED documents.content
USING (
  SELECT
    id::VARCHAR AS id,
    content AS text,
    to_json({'title': title, 'author': author}) AS metadata
  FROM documents
);

-- Step 2: Search with natural language
SELECT
  json_extract_string(metadata, '$.title') AS title,
  json_extract_string(metadata, '$.author') AS author,
  score,
  chunk_text
FROM VECTOR_SEARCH('What are the latest findings on climate adaptation?', documents.content, 10, 0.6)
ORDER BY score DESC;
```

### Workflow 2: Product Recommendation

```sql
-- Embed product descriptions:
LARS EMBED products.description
USING (SELECT id::VARCHAR AS id, description AS text FROM products WHERE active = true);

-- Find similar products:
SELECT
  p.product_name,
  p.price,
  vs.score AS similarity
FROM products p
JOIN VECTOR_SEARCH('eco-friendly sustainable materials', products.description, 20, 0.5) vs
  ON vs.id = p.id::VARCHAR
ORDER BY vs.score DESC;
```

### Workflow 3: Multi-Language Search

```sql
-- Embed articles in multiple languages:
LARS EMBED articles.content
USING (
  SELECT
    id::VARCHAR AS id,
    content AS text,
    to_json({'language': language, 'country': country}) AS metadata
  FROM articles
);

-- Search across languages (embeddings are multilingual):
SELECT
  json_extract_string(metadata, '$.language') AS lang,
  chunk_text,
  score
FROM VECTOR_SEARCH('renewable energy policy', articles.content, 30, 0.6)
WHERE json_extract_string(metadata, '$.country') = 'Brazil'
ORDER BY score DESC;
```

### Workflow 4: Hybrid Search for Precision

```sql
-- Embed with Elastic for hybrid search:
LARS EMBED products.description
USING (SELECT id::VARCHAR AS id, description AS text FROM products)
WITH (backend='elastic');

-- Hybrid search: combine semantic understanding + exact matches
SELECT *
FROM HYBRID_SEARCH('MacBook Pro M3 16-inch', products.description, 20, 0.5, 0.6, 0.4)
--                ^^^^^^^^^^^^^^^^^^^^^^      Finds semantically similar AND keyword matches
ORDER BY score DESC;
```

---

## Backends Comparison

### ClickHouse (vector_search_json_*)

**Pros:**
- Fast vector similarity (ANN index)
- Great for pure semantic search
- Integrates with existing ClickHouse analytics

**Cons:**
- No keyword search (semantic only)
- Requires ClickHouse running

**Use When:**
- You want pure semantic search
- You're already using ClickHouse
- You need fast analytical queries on results

### Elasticsearch (vector_search_elastic_*)

**Pros:**
- Hybrid search (semantic + BM25 keyword)
- Tunable weighting (adjust semantic vs keyword)
- Great for mixed precision/recall needs

**Cons:**
- Requires Elasticsearch running
- Slightly slower than ClickHouse pure vector

**Use When:**
- You need hybrid semantic + keyword search
- Exact keyword matches matter (product names, codes)
- You want to tune precision/recall balance

---

## Common Patterns

### Pattern 1: Incremental Embedding

```sql
-- Embed only new/updated rows:
LARS EMBED articles.content
USING (
  SELECT id::VARCHAR AS id, content AS text
  FROM articles
  WHERE embedded_at IS NULL
     OR updated_at > embedded_at
);

-- Update embedded_at timestamp after:
UPDATE articles
SET embedded_at = NOW()
WHERE embedded_at IS NULL OR updated_at > embedded_at;
```

### Pattern 2: Multi-Column Search

```sql
-- Embed both title and content:
LARS EMBED articles.title
USING (SELECT id::VARCHAR AS id, title AS text FROM articles);

LARS EMBED articles.content
USING (SELECT id::VARCHAR AS id, content AS text FROM articles);

-- Search title only:
SELECT * FROM VECTOR_SEARCH('climate policy', articles.title, 10);

-- Search content only:
SELECT * FROM VECTOR_SEARCH('climate policy', articles.content, 10);

-- Search both (union):
SELECT * FROM VECTOR_SEARCH('climate policy', articles.title, 5)
UNION ALL
SELECT * FROM VECTOR_SEARCH('climate policy', articles.content, 5);
```

### Pattern 3: Weighted Hybrid Search

```sql
-- For product search: exact model numbers matter more than semantics
SELECT * FROM HYBRID_SEARCH('MacBook Pro', products.description, 20, 0.5, 0.3, 0.7);
--                                                                        ^^^  ^^^
--                                                                        30%  70%
--                                                                        sem  keyword

-- For concept search: semantics matter more
SELECT * FROM HYBRID_SEARCH('eco-friendly sustainable', products.description, 20, 0.5, 0.9, 0.1);
--                                                                                    ^^^  ^^^
--                                                                                    90%  10%
```

### Pattern 4: Re-ranking with Additional Filters

```sql
-- Broad semantic search, then filter and re-rank:
WITH search_results AS (
  SELECT * FROM VECTOR_SEARCH('sustainability', products.description, 100, 0.4)
)
SELECT
  sr.*,
  p.price,
  p.category
FROM search_results sr
JOIN products p ON sr.id = p.id::VARCHAR
WHERE p.price < 1000
  AND p.in_stock = true
ORDER BY sr.score DESC
LIMIT 10;
```

---

## Troubleshooting

### Error: "USING query must return columns: id, text"

**Problem:**
```sql
LARS EMBED articles.content
USING (SELECT content FROM articles)  -- Missing 'id'!
```

**Fix:**
```sql
LARS EMBED articles.content
USING (SELECT id::VARCHAR AS id, content AS text FROM articles)
--             ^^^^^^^^^^^^^^^ required    ^^^^^^^^^^^^^^^^^^^^ required
```

### Error: "Invalid field reference"

**Problem:**
```sql
SELECT * FROM VECTOR_SEARCH('query', 'articles.content', 10)
--                                   ^^^^^^^^^^^^^^^^^^
--                                   String, not identifier!
```

**Fix:**
```sql
SELECT * FROM VECTOR_SEARCH('query', articles.content, 10)
--                                   ^^^^^^^^^^^^^^^^^
--                                   Identifier (no quotes)
```

### Error: "No function matches... vector_search_elastic_*"

**Problem:** Elasticsearch UDFs not registered (backend not configured)

**Fix:**
```bash
# Set Elasticsearch URL:
export ELASTICSEARCH_URL=http://localhost:9200

# Restart SQL server:
lars serve sql
```

### Search Returns No Results

**Check:**
1. Was data embedded? `SELECT COUNT(*) FROM embed_status('articles');`
2. Is score threshold too high? Try without `min_score`
3. Is column filter too restrictive? Check `metadata.column_name`

**Debug:**
```sql
-- See all embeddings for a table:
SELECT * FROM embed_status('articles');

-- See raw search results (no filtering):
SELECT * FROM read_json_auto(
  vector_search_json_3('query', 'articles.content', 10)
);
```

---

## Performance Tips

### 1. Embedding Performance

**Batch Size:** Larger batches = faster embedding but more memory

```sql
-- Small batches (safer, slower):
WITH (batch_size=50)

-- Large batches (faster, more memory):
WITH (batch_size=500)
```

**Background Processing:**
```sql
-- Don't wait for embedding to finish:
BACKGROUND
LARS EMBED large_table.text
USING (SELECT id::VARCHAR AS id, text FROM large_table);
```

### 2. Search Performance

**Limit Results:** Smaller limit = faster search

```sql
-- Fast (10 results):
VECTOR_SEARCH('query', table.col, 10)

-- Slower (1000 results):
VECTOR_SEARCH('query', table.col, 1000)
```

**Score Threshold:** Higher threshold = fewer results = faster

```sql
-- More selective (faster):
VECTOR_SEARCH('query', table.col, 10, 0.7)

-- Less selective (slower):
VECTOR_SEARCH('query', table.col, 10, 0.1)
```

### 3. Hybrid Search Tuning

**Semantic-Heavy (concept search):**
```sql
-- 90% semantic, 10% keyword:
HYBRID_SEARCH('query', table.col, 20, 0.5, 0.9, 0.1)
```

**Keyword-Heavy (exact term search):**
```sql
-- 20% semantic, 80% keyword:
HYBRID_SEARCH('product SKU 12345', products.desc, 20, 0.5, 0.2, 0.8)
```

---

## Advanced: Metadata Filtering

### Using Metadata JSON

Embed extra fields as metadata:

```sql
LARS EMBED articles.content
USING (
  SELECT
    id::VARCHAR AS id,
    content AS text,
    to_json({
      'title': title,
      'author': author,
      'published': published_at,
      'category': category,
      'tags': tags
    }) AS metadata
  FROM articles
);
```

Search and filter by metadata:

```sql
SELECT
  json_extract_string(metadata, '$.title') AS title,
  json_extract_string(metadata, '$.author') AS author,
  score,
  chunk_text
FROM VECTOR_SEARCH('climate policy', articles.content, 50, 0.6)
WHERE json_extract_string(metadata, '$.category') = 'environment'
  AND json_extract_string(metadata, '$.author') LIKE '%Smith%'
ORDER BY score DESC
LIMIT 10;
```

---

## Migration from Old Syntax

### Old Embedding Syntax

```sql
-- Old (manual JSON construction):
SELECT embed_batch(
  'bird_line',
  'text',
  (SELECT to_json(list({'id': CAST(id AS VARCHAR), 'text': text})) FROM bird_line)
);
```

### New Embedding Syntax

```sql
-- New (declarative):
LARS EMBED bird_line.text
USING (SELECT id::VARCHAR AS id, text FROM bird_line);
```

### Old Search Syntax

```sql
-- Old (wrapped):
SELECT * FROM read_json_auto(
  vector_search_json_3('query', 'bird_line', 10)
);
```

### New Search Syntax

```sql
-- New (table-valued function):
SELECT * FROM VECTOR_SEARCH('query', bird_line.text, 10);
```

**Both syntaxes work!** New syntax is sugar over the old plumbing.

---

## Summary

**LARS EMBED:**
- Natural `table.column` syntax
- Consistent with LARS MAP/RUN
- Explicit `id` and `text` columns (no ambiguity)
- Backend selection (ClickHouse or Elastic)

**VECTOR_SEARCH:**
- Table-valued function (use in FROM clause)
- Field-aware (`table.column` identifier)
- Automatic metadata filtering
- Optional score threshold

**HYBRID_SEARCH:**
- Semantic + keyword hybrid scoring
- Tunable weights
- Elasticsearch backend
- Returns score breakdown

**All integrate with:**
- ✅ BACKGROUND (async execution)
- ✅ ANALYZE (LLM analysis of results)
- ✅ Semantic operators (MEANS, ABOUT, etc.)

**No breaking changes!** Old syntax still works, new syntax is sugar.

---

## Next Steps

1. **Embed your data:**
   ```sql
   LARS EMBED your_table.your_column
   USING (SELECT id::VARCHAR AS id, your_column AS text FROM your_table);
   ```

2. **Search:**
   ```sql
   SELECT * FROM VECTOR_SEARCH('your query', your_table.your_column, 10);
   ```

3. **Enjoy natural SQL!** 🚀

---

## Technical Details

### Rewriting Pipeline

```
User SQL: VECTOR_SEARCH('q', table.col, 10)
  ↓
vector_search_rewriter.py
  ├─ Parse field reference: table.col → (table='table', col='col')
  ├─ Count args: 3
  ├─ Generate inner call: vector_search_json_3('q', 'table.col', 10)
  ├─ Wrap: read_json_auto(...)
  └─ Filter: WHERE metadata.column_name = 'col'
  ↓
DuckDB executes rewritten SQL
```

### Why Field References?

**Identifier syntax** (`table.column`) instead of **string syntax** (`'table.column'`) gives:
- ✅ IDE autocomplete
- ✅ Syntax highlighting
- ✅ Typo detection
- ✅ Refactoring support
- ✅ Natural SQL feel

**It's just better UX!** 🎉
