# RVBBIT MAP - Quick Start Guide

**Phase 1-2: Row-Wise LLM Processing with Parallel Execution**

---

## What is RVBBIT MAP?

`RVBBIT MAP` is SQL syntax sugar that makes it easy to apply cascades to each row of a query result.

### Before (UDF syntax):
```sql
SELECT
  product,
  rvbbit_run('enrich.yaml', to_json(row)) AS result
FROM products;
```

### After (MAP syntax):
```sql
RVBBIT MAP 'enrich.yaml'
USING (SELECT * FROM products LIMIT 100);
```

**Benefits:**
- ✅ Cleaner, more SQL-like syntax
- ✅ Automatic safety limits (auto-LIMIT injection)
- ✅ Editor-friendly (USING clause is standard SQL)
- ✅ Less boilerplate (no manual to_json(), CTE wrapping)

---

## Basic Syntax

```sql
RVBBIT MAP 'cascade_path.yaml' [AS result_alias]
USING (
  <your SQL query>
)
[WITH (option = value, ...)];
```

**Components:**
- **cascade_path**: Path to cascade file (e.g., `'traits/extract_brand.yaml'`)
- **AS alias**: Optional result column name (default: `result`)
- **USING (...)**: Any SQL query (standard SQL, fully highlighted by editors)
- **WITH (...)**: Optional configuration (cache, budget, etc.)

---

## Quick Examples

### 1. Simple Enrichment

```sql
RVBBIT MAP 'traits/extract_brand.yaml'
USING (
  SELECT product_name FROM products LIMIT 10
);
```

**Returns:**
| product_name | result |
|--------------|--------|
| Apple iPhone 15 | {"brand": "Apple", ...} |
| Samsung Galaxy S24 | {"brand": "Samsung", ...} |

---

### 2. With Custom Alias

```sql
RVBBIT MAP 'traits/extract_brand.yaml' AS brand_info
USING (
  SELECT product_name FROM products LIMIT 10
);
```

**Returns:**
| product_name | brand_info |
|--------------|------------|
| Apple iPhone 15 | {"brand": "Apple", ...} |

---

### 3. With Options

```sql
RVBBIT MAP 'cascades/fraud_assess.yaml' AS risk
USING (SELECT * FROM charges WHERE flagged = true LIMIT 50)
WITH (cache = true, budget_dollars = 5.0);
```

**Available Options:**
- `cache` (boolean): Enable result caching (default: true)
- `budget_dollars` (float): Max spend limit
- `key` (string): Primary key column for tracking
- `result_column` (string): Alternative to AS alias

---

## Parallel Processing (NEW!)

**Control concurrent LLM calls** for rate-limited APIs:

```sql
-- Only 5 concurrent calls (great for rate-limited endpoints!)
RVBBIT MAP PARALLEL 5 'expensive_model.yaml' AS result
USING (SELECT * FROM products LIMIT 100);

-- High concurrency for fast/cheap models
RVBBIT MAP PARALLEL 50 'fast_classification.yaml'
USING (SELECT * FROM reviews LIMIT 1000);

-- Conservative for expensive analysis
RVBBIT MAP PARALLEL 3 'deep_analysis.yaml'
USING (SELECT * FROM customers LIMIT 20);
```

**When to use PARALLEL:**
- 🔥 Rate-limited APIs (OpenRouter, Anthropic)
- 🔥 GPU-limited local models
- 🔥 Cost control (limit concurrent expensive calls)
- 🔥 Faster processing (vs sequential)

**Default**: Sequential execution (no parallelism)

---

## Safety Features

### Auto-LIMIT Injection

```sql
-- ⚠️ This query has NO explicit LIMIT
RVBBIT MAP 'enrich.yaml'
USING (SELECT * FROM huge_table);

-- ✅ Auto-rewrites to:
-- ... FROM huge_table LIMIT 1000
```

**Default limits:**
- `MAP` without `LIMIT`: Auto-adds `LIMIT 1000`
- `PARALLEL` default: 10 concurrent workers

---

## How It Works

### What Happens Behind the Scenes

**Your Query:**
```sql
RVBBIT MAP 'enrich.yaml' AS enriched
USING (SELECT a, b FROM t LIMIT 10);
```

**Rewrites To:**
```sql
WITH rvbbit_input AS (
  SELECT a, b FROM t LIMIT 10
)
SELECT
  i.*,
  rvbbit_run('enrich.yaml', to_json(i)) AS enriched
FROM rvbbit_input i;
```

---

## Connection Setup

### PostgreSQL Wire Protocol (DBeaver, psql, etc.)

```bash
# Start server
rvbbit server --port 15432

# Connect from DBeaver:
# Host: localhost
# Port: 15432
# Database: default
# Username: rvbbit
# Password: (leave empty)
```

### Python Client

```python
from rvbbit.client import RVBBITClient

client = RVBBITClient('http://localhost:5001')

df = client.execute("""
    RVBBIT MAP 'enrich.yaml' AS enriched
    USING (SELECT * FROM products LIMIT 10)
""")

print(df)
```

---

## Best Practices

### 1. Always Include LIMIT

```sql
-- ✅ Good: Explicit limit
RVBBIT MAP 'x' USING (SELECT * FROM t LIMIT 100);

-- ⚠️ Auto-limited: Will add LIMIT 1000
RVBBIT MAP 'x' USING (SELECT * FROM t);
```

### 2. Use AS for Clarity

```sql
-- ✅ Good: Clear column name
RVBBIT MAP 'enrich' AS enriched_data USING (...);

-- 😐 Okay: Generic 'result' column
RVBBIT MAP 'enrich' USING (...);
```

### 3. Filter Before Enrichment

```sql
-- ✅ Good: Filter first, enrich subset
RVBBIT MAP 'expensive_analysis.yaml'
USING (
  SELECT * FROM customers
  WHERE tier = 'premium'  -- Only process premium customers
  LIMIT 50
);
```

---

## Troubleshooting

### Error: "Expected USING after cascade path"

**Problem:**
```sql
RVBBIT MAP 'x.yaml';  -- Missing USING clause
```

**Solution:**
```sql
RVBBIT MAP 'x.yaml' USING (SELECT 1);
```

---

### Error: "Cascade not found"

**Problem:**
```sql
RVBBIT MAP 'nonexistent.yaml' USING (SELECT 1);
```

**Solution:**
- Check cascade path is correct
- Use relative paths from RVBBIT_ROOT
- Example: `traits/extract_brand.yaml` or `cascades/fraud.yaml`

---

## What's Coming Next

**Phase 2** (Options & Safety):
- Budget validation
- Receipt tracking
- Advanced error handling

**Phase 3** (Batch Processing):
- `RVBBIT RUN` for batch operations
- Temp table support

**Phase 4** (Advanced):
- `MAP BATCH <n>` for chunked processing
- `PARALLEL <n>` for concurrency control
- `RETURNING (...)` clause

---

**Happy enriching! 🚀⚓**
