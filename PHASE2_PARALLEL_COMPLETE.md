# ✅ Phase 2 Complete: PARALLEL Support

**Date**: 2025-12-25
**Status**: Implementation Complete - Restart Server to Test

---

## What Was Built

### 🚀 New Feature: MAP PARALLEL

**Syntax:**
```sql
RVBBIT MAP PARALLEL <max_workers> 'cascade.yaml'
USING (SELECT ...)
```

**Purpose**: Control concurrent LLM execution for rate-limited APIs, cost management, and performance optimization.

---

## Implementation Details

### 1. New UDF Function

**File**: `rvbbit/rvbbit/sql_tools/udf.py`

**Function**: `rvbbit_map_parallel_impl(cascade_path, rows_json_array, max_workers)`
- Takes array of rows as JSON
- Executes cascades in parallel using `ThreadPoolExecutor`
- Maintains result order (critical!)
- Extracts useful values (same logic as sequential MAP)
- Returns JSON array of results

**Registered as**: `rvbbit_map_parallel()`

### 2. Parser Enhancement

**File**: `rvbbit/rvbbit/sql_rewriter.py`

**Changes:**
- Parses `PARALLEL <n>` after `RVBBIT MAP`
- Stores parallel count in `RVBBITStatement.parallel`
- Added `DEFAULT_PARALLEL = 10` constant

### 3. Rewrite Logic

**Sequential** (no PARALLEL):
```sql
RVBBIT MAP 'x' USING (SELECT a FROM t LIMIT 10)

-- Rewrites to row-by-row:
WITH rvbbit_input AS (SELECT a FROM t LIMIT 10)
SELECT i.*, rvbbit_run('x', to_json(i)) AS result
FROM rvbbit_input i
```

**Parallel** (with PARALLEL 5):
```sql
RVBBIT MAP PARALLEL 5 'x' USING (SELECT a FROM t LIMIT 10)

-- Rewrites to batch + unnest:
WITH rvbbit_input AS (SELECT a FROM t LIMIT 10)
SELECT unnest(json_extract(results, '$[*]'), recursive := true)
FROM (
  SELECT rvbbit_map_parallel(
    'x',
    (SELECT json_group_array(to_json(i)) FROM rvbbit_input i),
    5
  ) AS results
)
```

---

## Usage Examples

### Conservative (Rate-Limited API)

```sql
-- Only 3 concurrent calls to expensive/rate-limited endpoint
RVBBIT MAP PARALLEL 3 'cascades/gpt4_analysis.yaml' AS analysis
USING (
  SELECT * FROM high_value_customers LIMIT 50
);
```

### Moderate (Default APIs)

```sql
-- 10 concurrent calls (reasonable for most APIs)
RVBBIT MAP PARALLEL 10 'traits/extract_brand.yaml' AS brand
USING (
  SELECT * FROM products LIMIT 200
);
```

### Aggressive (Fast/Cheap Models)

```sql
-- 50 concurrent calls for fast classification
RVBBIT MAP PARALLEL 50 'traits/classify_sentiment.yaml' AS sentiment
USING (
  SELECT review_text FROM reviews LIMIT 1000
);
```

---

## Performance Comparison

### Sequential (Original)

```sql
RVBBIT MAP 'x' USING (SELECT * FROM t LIMIT 100);

-- Execution: Row 1 → Row 2 → Row 3 → ... → Row 100
-- Time: 100 rows × 2s = ~200 seconds
-- Concurrency: 1 LLM call at a time
```

### Parallel (New!)

```sql
RVBBIT MAP PARALLEL 10 'x' USING (SELECT * FROM t LIMIT 100);

-- Execution: Batches of 10 running concurrently
-- Time: 100 rows ÷ 10 workers × 2s = ~20 seconds
-- Concurrency: 10 LLM calls at a time
-- Speedup: 10x faster!
```

---

## When to Use PARALLEL

### ✅ Use PARALLEL When:

1. **Rate Limits** - API has requests/second limits
   ```sql
   -- OpenRouter limits: 200 req/min = ~3 req/sec
   RVBBIT MAP PARALLEL 3 'expensive' USING (...)
   ```

2. **Cost Control** - Limit concurrent expensive calls
   ```sql
   -- Don't want 100 concurrent $0.10 calls
   RVBBIT MAP PARALLEL 5 'costly' USING (...)
   ```

3. **GPU Limits** - Local model has limited compute
   ```sql
   -- Single GPU can handle ~10 concurrent
   RVBBIT MAP PARALLEL 10 'local_llama' USING (...)
   ```

4. **Performance** - Speed up large batches
   ```sql
   -- 1000 rows 50x faster with parallelism
   RVBBIT MAP PARALLEL 50 'fast' USING (SELECT * FROM t LIMIT 1000)
   ```

### ❌ Skip PARALLEL When:

1. **Small row counts** - Overhead not worth it (<10 rows)
2. **Very slow cascades** - If each takes 30+ seconds, parallelism less beneficial
3. **Strict ordering required** - Results maintain order but execution doesn't

---

## Tests

**File**: `tests/test_sql_rewriter.py`

**New Tests** (38/38 passing ✅):
- `test_parse_map_with_parallel` - Parse PARALLEL clause
- `test_parse_map_parallel_with_alias` - PARALLEL + AS alias
- `test_rewrite_map_with_parallel` - Rewrite to parallel UDF

```bash
cd /home/ryanr/repos/rvbbit/rvbbit
python -m pytest tests/test_sql_rewriter.py -v

# ✅ 38 passed in 1.45s
```

---

## Restart Required!

**IMPORTANT**: The server must be restarted to load:
1. New `rvbbit_map_parallel()` UDF
2. Updated rewriter with PARALLEL parsing
3. Updated UDF registration

```bash
# Kill existing server
pkill -f "rvbbit server"

# Restart
cd /home/ryanr/repos/rvbbit
rvbbit server --port 15432
```

---

## Try It Now!

### Test Query for DBeaver

```sql
-- Sequential (slow)
RVBBIT MAP 'traits/extract_brand.yaml' AS brand
USING (
  SELECT * FROM (VALUES
    ('Apple iPhone 15'),
    ('Samsung Galaxy S24'),
    ('Sony WH-1000XM5'),
    ('Google Pixel 8'),
    ('OnePlus 12')
  ) AS t(product_name)
);

-- Parallel (5 concurrent - faster!)
RVBBIT MAP PARALLEL 5 'traits/extract_brand.yaml' AS brand
USING (
  SELECT * FROM (VALUES
    ('Apple iPhone 15'),
    ('Samsung Galaxy S24'),
    ('Sony WH-1000XM5'),
    ('Google Pixel 8'),
    ('OnePlus 12')
  ) AS t(product_name)
);
```

---

## What's Next?

**Phase 3** (Batch Processing):
- `RVBBIT RUN` for dataset-level operations
- Temp table support (`as_table` option)
- Multi-table outputs

**Phase 4** (Advanced):
- `MAP BATCH <n>` for chunked processing
- `RETURNING (...)` clause
- Async execution (`RUN ASYNC`)

---

## Summary

**Phase 2 Adds:**
- ✅ `RVBBIT MAP PARALLEL <n>` syntax
- ✅ `rvbbit_map_parallel()` UDF with ThreadPoolExecutor
- ✅ Concurrent execution with order preservation
- ✅ 3 new tests (38/38 total passing)
- ✅ Updated documentation & examples

**To Use:**
1. Restart server (load new UDF)
2. Use `PARALLEL <n>` after `MAP`
3. Enjoy faster, controlled concurrent execution!

🚀⚓
