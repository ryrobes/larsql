# Vector Search - Four Functions Summary

**Complete backend routing with clear functional intent.**

---

## The Four Functions

| Function | Backend | Semantic | Keyword | Use Case |
|----------|---------|----------|---------|----------|
| **VECTOR_SEARCH** | ClickHouse | 100% | 0% | Fast concept search (default) |
| **ELASTIC_SEARCH** | Elastic | 100% | 0% | Semantic on Elastic |
| **HYBRID_SEARCH** | Elastic | Tunable | Tunable | Balance concepts + terms |
| **KEYWORD_SEARCH** | Elastic | 0% | 100% | Exact term matching |

---

## Quick Reference

### VECTOR_SEARCH (ClickHouse Pure Semantic)

```sql
-- Fastest, pure semantic understanding:
SELECT * FROM VECTOR_SEARCH('climate change', articles.content, 10);
SELECT * FROM VECTOR_SEARCH('AI ethics', papers.abstract, 20, 0.7);
```

**Rewrites to:**
```sql
read_json_auto(vector_search_json_3/4(...))
WHERE metadata.column_name = 'content'
```

**Use for:** Fast concept search, finding similar content

---

### ELASTIC_SEARCH (Elastic Pure Semantic)

```sql
-- Same as VECTOR_SEARCH but on Elastic:
SELECT * FROM ELASTIC_SEARCH('climate change', articles.content, 10);
SELECT * FROM ELASTIC_SEARCH('policy', docs.text, 20, 0.6);
```

**Rewrites to:**
```sql
vector_search_elastic_7('query', 'table', 'column', limit, min_score, 1.0, 0.0)
--                                                                     ^^^  ^^^
--                                                                     100% 0%
--                                                                     sem  kw
```

**Use for:** Semantic search on Elastic (when you need Elastic features)

---

### HYBRID_SEARCH (Elastic Semantic + Keyword)

```sql
-- Default (70% semantic, 30% keyword):
SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 10);

-- Custom weights:
SELECT * FROM HYBRID_SEARCH('climate', articles.content, 20, 0.5, 0.8, 0.2);
--                                                              ^^^  ^^^  ^^^
--                                                              min  sem  kw
```

**Rewrites to:**
```sql
vector_search_elastic_4/7('query', 'table', 'column', limit, ...)
-- Weights determine how much semantic vs keyword matters
```

**Use for:** Balance between concept understanding and exact term matches

---

### KEYWORD_SEARCH (Elastic Pure BM25)

```sql
-- Pure keyword matching (no semantics):
SELECT * FROM KEYWORD_SEARCH('MacBook Pro M3', products.name, 10);
SELECT * FROM KEYWORD_SEARCH('SKU-12345', products.sku, 5, 0.8);
```

**Rewrites to:**
```sql
vector_search_elastic_7('query', 'table', 'column', limit, min_score, 0.0, 1.0)
--                                                                     ^^^  ^^^
--                                                                     0%   100%
--                                                                     sem  kw
```

**Use for:** Exact term matching (SKUs, codes, specific phrases)

---

## When to Use Which?

### Decision Flow

```
START: What are you searching for?

  ├─ Exact terms (SKU, product code, model number)
  │  → KEYWORD_SEARCH
  │
  ├─ Concepts + exact terms (product names with specs)
  │  → HYBRID_SEARCH (tune weights)
  │     ├─ More semantic (vague concepts) → 0.9, 0.1
  │     └─ More keyword (specific terms) → 0.3, 0.7
  │
  └─ Pure concepts (ideas, themes, similar content)
     ├─ Want fastest? → VECTOR_SEARCH (ClickHouse)
     └─ Need Elastic? → ELASTIC_SEARCH
```

### Real-World Examples

**Use Case 1: Product Search**
```sql
-- User searches "eco-friendly water bottle"
-- Wants: Both concept (eco-friendly) AND specific term (water bottle)
SELECT * FROM HYBRID_SEARCH('eco-friendly water bottle', products.description, 20, 0.5, 0.6, 0.4);
```

**Use Case 2: Research Paper Discovery**
```sql
-- Finding papers on "neural network interpretability"
-- Wants: Conceptual similarity (other papers on same topic, even with different wording)
SELECT * FROM VECTOR_SEARCH('neural network interpretability', papers.abstract, 30, 0.65);
```

**Use Case 3: Error Log Search**
```sql
-- Finding specific error code "HTTP 502"
-- Wants: Exact error code mentions
SELECT * FROM KEYWORD_SEARCH('HTTP 502', error_logs.message, 100);
```

**Use Case 4: Legal Document Search**
```sql
-- Finding GDPR compliance mentions
-- Wants: Exact regulation name + related concepts
SELECT * FROM HYBRID_SEARCH('GDPR compliance', legal_docs.content, 50, 0.6, 0.5, 0.5);
```

---

## Backend Routing Summary

### Embedding

```sql
-- ClickHouse (for VECTOR_SEARCH):
RVBBIT EMBED table.col USING (...) WITH (backend='clickhouse');

-- Elastic (for ELASTIC_SEARCH, HYBRID_SEARCH, KEYWORD_SEARCH):
RVBBIT EMBED table.col USING (...) WITH (backend='elastic');
```

**You can embed to BOTH backends:**
```sql
-- Embed to ClickHouse for fast semantic:
RVBBIT EMBED articles.content USING (...) WITH (backend='clickhouse');

-- Also embed to Elastic for hybrid/keyword:
RVBBIT EMBED articles.content USING (...) WITH (backend='elastic');

-- Now you can use any search function!
```

### Search Routing

**Automatic based on function name:**

- `VECTOR_SEARCH('q', field, 10)` → `vector_search_json_3(...)` (ClickHouse)
- `ELASTIC_SEARCH('q', field, 10)` → `vector_search_elastic_7(..., 1.0, 0.0)` (Elastic 100% sem)
- `HYBRID_SEARCH('q', field, 10, 0.5, 0.7, 0.3)` → `vector_search_elastic_7(..., 0.7, 0.3)` (Elastic custom)
- `KEYWORD_SEARCH('q', field, 10)` → `vector_search_elastic_7(..., 0.0, 1.0)` (Elastic 100% kw)

---

## Weight Tuning Guide (HYBRID_SEARCH)

### Presets

**Balanced (default):**
```sql
HYBRID_SEARCH('query', field, 10, 0.5, 0.7, 0.3)  -- 70% semantic, 30% keyword
```

**Semantic-Heavy:**
```sql
HYBRID_SEARCH('query', field, 10, 0.5, 0.9, 0.1)  -- 90% semantic, 10% keyword
-- Use for: Concept searches, research, exploration
```

**Keyword-Heavy:**
```sql
HYBRID_SEARCH('query', field, 10, 0.5, 0.3, 0.7)  -- 30% semantic, 70% keyword
-- Use for: Product search, known terminology, names
```

**Equal Mix:**
```sql
HYBRID_SEARCH('query', field, 10, 0.5, 0.5, 0.5)  -- 50% semantic, 50% keyword
```

### When to Adjust

**Increase Semantic Weight:**
- Queries are conceptual ("sustainable practices")
- Users use varied terminology
- Finding related topics matters more than exact matches

**Increase Keyword Weight:**
- Queries contain specific terms ("MacBook Pro M3")
- Exact phrases matter (product codes, model numbers)
- Technical terminology (abbreviations, jargon)

---

## Complete Workflow Example

```sql
-- Step 1: Embed to BOTH backends
RVBBIT EMBED products.description
USING (SELECT id::VARCHAR AS id, description AS text FROM products)
WITH (backend='clickhouse');

RVBBIT EMBED products.description
USING (SELECT id::VARCHAR AS id, description AS text FROM products)
WITH (backend='elastic');

-- Step 2: Compare all 4 search methods
WITH
vector_results AS (
  SELECT 'VECTOR' AS method, * FROM VECTOR_SEARCH('eco-friendly', products.description, 10)
),
elastic_results AS (
  SELECT 'ELASTIC' AS method, * FROM ELASTIC_SEARCH('eco-friendly', products.description, 10)
),
hybrid_results AS (
  SELECT 'HYBRID' AS method, * FROM HYBRID_SEARCH('eco-friendly', products.description, 10, 0.5, 0.7, 0.3)
),
keyword_results AS (
  SELECT 'KEYWORD' AS method, * FROM KEYWORD_SEARCH('eco-friendly', products.description, 10)
)

SELECT * FROM vector_results
UNION ALL SELECT * FROM elastic_results
UNION ALL SELECT * FROM hybrid_results
UNION ALL SELECT * FROM keyword_results
ORDER BY method, score DESC;

-- Compare which methods found what!
```

---

## Summary Table

| Metric | VECTOR | ELASTIC | HYBRID | KEYWORD |
|--------|--------|---------|--------|---------|
| **Backend** | ClickHouse | Elastic | Elastic | Elastic |
| **Speed** | Fastest | Fast | Fast | Fast |
| **Semantic** | ✅ 100% | ✅ 100% | ⚙️ Tunable | ❌ 0% |
| **Keyword** | ❌ 0% | ❌ 0% | ⚙️ Tunable | ✅ 100% |
| **Use Case** | Concept search | Elastic semantic | Balanced search | Exact terms |
| **Example Query** | "sustainability" | "climate policy" | "MacBook Pro" | "SKU-12345" |

---

## Key Takeaways

✅ **VECTOR_SEARCH** - Your default (fastest pure semantic)
✅ **ELASTIC_SEARCH** - Same as VECTOR but on Elastic
✅ **HYBRID_SEARCH** - Best of both worlds (tune to taste)
✅ **KEYWORD_SEARCH** - Exact term matching when semantics don't matter

**Clear functional intent from the function name!** 🎉

**All support:**
- Field reference syntax (`table.column`)
- BACKGROUND async execution
- Score thresholds
- Natural SQL

**No ambiguity - function name tells you the backend and mode!** 🚀
