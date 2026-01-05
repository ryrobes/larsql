# Vector Search Backends - Complete Reference

**All 5 backends with consistent syntax.**

---

## Quick Reference

### Embedding (Pick Your Backend)

```sql
-- ClickHouse (fastest, analytics-friendly):
RVBBIT EMBED table.column
USING (SELECT id::VARCHAR AS id, column AS text FROM table)
WITH (backend='clickhouse');

-- Elasticsearch (hybrid search support):
RVBBIT EMBED table.column
USING (SELECT id::VARCHAR AS id, column AS text FROM table)
WITH (backend='elastic', index='custom_idx');

-- Pinecone (managed, scalable):
RVBBIT EMBED table.column
USING (SELECT id::VARCHAR AS id, column AS text FROM table)
WITH (backend='pinecone', namespace='custom_ns');
```

### Search (Pick Your Function)

```sql
-- ClickHouse - Fastest:
SELECT * FROM VECTOR_SEARCH('query', table.column, 10);

-- Elastic - Pure semantic:
SELECT * FROM ELASTIC_SEARCH('query', table.column, 10);

-- Elastic - Hybrid (semantic + keyword):
SELECT * FROM HYBRID_SEARCH('query', table.column, 10, 0.5, 0.7, 0.3);

-- Elastic - Pure keyword:
SELECT * FROM KEYWORD_SEARCH('exact terms', table.column, 10);

-- Pinecone - Managed:
SELECT * FROM PINECONE_SEARCH('query', table.column, 10, 0.6, 'namespace');
```

---

## Backend Details

### 1. ClickHouse (VECTOR_SEARCH)

**Type:** Pure semantic vector search
**Backend:** ClickHouse (self-hosted)

**Embed:**
```sql
WITH (backend='clickhouse', batch_size=100)
```

**Search:**
```sql
VECTOR_SEARCH(query, field, limit[, min_score])
```

**Pros:**
- ⚡ Fastest queries (optimized ANN index)
- 📊 Integrates with ClickHouse analytics
- 💰 Free (self-hosted)

**Cons:**
- 🔧 Requires ClickHouse setup
- ❌ No hybrid (semantic + keyword)

**Use for:** Fast concept search, analytical queries

---

### 2. Elasticsearch (ELASTIC_SEARCH)

**Type:** Pure semantic vector search
**Backend:** Elasticsearch (self-hosted)

**Embed:**
```sql
WITH (backend='elastic', index='custom_idx', batch_size=200)
```

**Search:**
```sql
ELASTIC_SEARCH(query, field, limit[, min_score, index])
```

**Pros:**
- 🔍 Elasticsearch features (aggregations, facets)
- 🏗️ Use existing Elastic infrastructure
- 💰 Free (self-hosted)

**Cons:**
- 🔧 Requires Elasticsearch setup
- 🐌 Slower than ClickHouse pure semantic

**Use for:** When you're already on Elastic, need aggregations

---

### 3. Elasticsearch (HYBRID_SEARCH)

**Type:** Semantic + keyword hybrid
**Backend:** Elasticsearch (self-hosted)

**Embed:**
```sql
WITH (backend='elastic', index='custom_idx')
```

**Search:**
```sql
HYBRID_SEARCH(query, field, limit[, min_score, sem_weight, kw_weight, index])
```

**Pros:**
- 🎯 Best of both worlds (concepts + exact terms)
- ⚙️ Tunable weights (adjust balance)
- 🎓 Handles ambiguous queries well

**Cons:**
- 🔧 Requires Elasticsearch
- 🐌 Slower than pure semantic

**Use for:** Product search, mixed precision/recall needs

---

### 4. Elasticsearch (KEYWORD_SEARCH)

**Type:** Pure BM25 keyword matching
**Backend:** Elasticsearch (self-hosted)

**Embed:**
```sql
WITH (backend='elastic', index='custom_idx')
```

**Search:**
```sql
KEYWORD_SEARCH(query, field, limit[, min_score, index])
```

**Pros:**
- 🎯 Exact term matching
- 🏷️ Great for SKUs, codes, names
- 💨 Fast

**Cons:**
- ❌ No semantic understanding
- 🔧 Requires Elasticsearch

**Use for:** SKU/code search, technical terms, exact phrases

---

### 5. Pinecone (PINECONE_SEARCH)

**Type:** Pure semantic vector search
**Backend:** Pinecone (managed cloud)

**Embed:**
```sql
WITH (backend='pinecone', namespace='custom_ns', batch_size=100)
```

**Search:**
```sql
PINECONE_SEARCH(query, field, limit[, min_score, namespace])
```

**Pros:**
- ☁️ Fully managed (zero ops)
- 📈 Auto-scaling
- 🏢 Multi-tenancy (namespaces)
- 🛡️ Production-ready

**Cons:**
- 💵 Paid service
- 🔒 Vendor lock-in
- ❌ No hybrid search

**Use for:** Production apps, teams wanting "just works"

---

## Decision Matrix

```
START: What's your situation?

Already have infrastructure?
  ├─ Have ClickHouse? → VECTOR_SEARCH (fastest)
  ├─ Have Elasticsearch?
  │   ├─ Need hybrid? → HYBRID_SEARCH
  │   ├─ Need keyword? → KEYWORD_SEARCH
  │   └─ Pure semantic? → ELASTIC_SEARCH
  └─ Neither? → Continue below

Building new system?
  ├─ Want managed (zero ops)? → PINECONE_SEARCH
  ├─ Want free + fast? → VECTOR_SEARCH (setup ClickHouse)
  └─ Need hybrid? → HYBRID_SEARCH (setup Elastic)

Cost-sensitive?
  ├─ Yes → VECTOR_SEARCH or HYBRID_SEARCH (self-host)
  └─ No → PINECONE_SEARCH (managed)

Need to scale massively?
  ├─ Yes → PINECONE_SEARCH (auto-scales)
  └─ No → Any backend works
```

---

## Configuration Files

### ClickHouse
Uses existing ClickHouse config (via `RVBBIT_CLICKHOUSE_*` env vars)

### Elasticsearch
Uses `ELASTICSEARCH_URL` env var

### Pinecone
Uses `config/pinecone.yaml`:
```yaml
connection:
  api_key_env: PINECONE_API_KEY
  host: https://rvbbit-roiw3h8.svc.aped-4627-b74a.pinecone.io
  index_name: rvbbit
  dimension: 4096
  metric: cosine
```

---

## Complete Example: All 5 Functions

```sql
-- Embed to all backends:
RVBBIT EMBED articles.content USING (...) WITH (backend='clickhouse');
RVBBIT EMBED articles.content USING (...) WITH (backend='elastic');
RVBBIT EMBED articles.content USING (...) WITH (backend='pinecone', namespace='articles');

-- Compare all 5 search types:
WITH
ch_results AS (
  SELECT 'ClickHouse Vector' AS type, * FROM VECTOR_SEARCH('climate', articles.content, 10)
),
es_semantic AS (
  SELECT 'Elastic Semantic' AS type, * FROM ELASTIC_SEARCH('climate', articles.content, 10)
),
es_hybrid AS (
  SELECT 'Elastic Hybrid' AS type, * FROM HYBRID_SEARCH('climate', articles.content, 10, 0.5, 0.7, 0.3)
),
es_keyword AS (
  SELECT 'Elastic Keyword' AS type, * FROM KEYWORD_SEARCH('climate', articles.content, 10)
),
pinecone_results AS (
  SELECT 'Pinecone' AS type, * FROM PINECONE_SEARCH('climate', articles.content, 10, 0.0, 'articles')
)

SELECT * FROM ch_results
UNION ALL SELECT * FROM es_semantic
UNION ALL SELECT * FROM es_hybrid
UNION ALL SELECT * FROM es_keyword
UNION ALL SELECT * FROM pinecone_results
ORDER BY type, score DESC;

-- See which backend/mode gives the best results for your query!
```

---

## Summary

**5 backends, consistent syntax:**
- All use `RVBBIT EMBED table.column USING (...) WITH (backend='...')`
- All use `*_SEARCH('query', table.column, limit, ...)`
- All return nice tables (id, text, similarity, score)
- All integrate with semantic operators
- All work with BACKGROUND async

**Adding more backends:**
- Weaviate: ~90 minutes
- Qdrant: ~90 minutes
- Chroma: ~90 minutes

**The architecture is proven extensible!** 🚀

---

## Your Complete System

```sql
-- Unified operators (custom in YAML):
SELECT * FROM products WHERE description CUSTOM_OP 'criteria';

-- Vector search (5 backends):
SELECT * FROM PINECONE_SEARCH('query', table.column, 10);

-- Semantic operators:
WHERE chunk_text MEANS 'policy' AND chunk_text EXTRACTS 'recommendations'

-- All together:
BACKGROUND
SELECT
  ps.text EXTRACTS 'key findings' AS findings,
  ps.score
FROM PINECONE_SEARCH('climate adaptation', articles.content, 50, 0.7, 'research') ps
WHERE ps.text MEANS 'actionable strategies'
ORDER BY ps.score DESC;
```

**Everything works together!** 🔥
