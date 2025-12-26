# ✅ Phase 3 Complete: RVBBIT RUN - Batch Processing

**Date**: 2025-12-25
**Status**: Implementation Complete - Ready for Testing

---

## 🎯 What's New: RVBBIT RUN

**Purpose**: Execute cascade **ONCE** over an entire dataset (vs MAP = once per row)

**Syntax:**
```sql
RVBBIT RUN 'cascade.yaml'
USING (SELECT * FROM data LIMIT 500)
WITH (as_table = 'batch_data');
```

**Returns**: Single metadata row with:
- `status` - success/failed
- `session_id` - batch-woodland-name
- `table_created` - temp table name
- `row_count` - number of rows processed
- `outputs` - cascade outputs (JSON)

---

## 🔄 MAP vs RUN Comparison

### RVBBIT MAP (Row-Wise)

```sql
RVBBIT MAP 'enrich.yaml' AS brand
USING (SELECT * FROM products LIMIT 100);

-- Behavior:
-- - Runs cascade 100 times (once per row)
-- - Returns: 100 rows with enriched data
-- - Cost: 100 × cascade cost
-- - Session IDs: udf-clever-fox-001, udf-misty-owl-002, ...
```

**Use When:**
- Need per-row enrichment
- Different output for each row
- Cost scales with row count

---

### RVBBIT RUN (Batch)

```sql
RVBBIT RUN 'analyze_batch.yaml'
USING (SELECT * FROM products LIMIT 100)
WITH (as_table = 'products_batch');

-- Behavior:
-- - Runs cascade 1 time (over entire dataset)
-- - Returns: 1 row with metadata
-- - Cost: 1 × cascade cost (regardless of row count!)
-- - Session ID: batch-clever-fox-abc123
-- - Cascade sees: temp table 'products_batch' with 100 rows
```

**Use When:**
- Aggregate analysis (summarize entire dataset)
- Multi-table outputs (create summary + details + alerts tables)
- Cost savings (1 cascade run vs N row runs)
- Complex multi-phase workflows over batches

---

## 🏗️ How RVBBIT RUN Works

### Step-by-Step

**1. User Query:**
```sql
RVBBIT RUN 'traits/analyze_batch.yaml'
USING (SELECT * FROM products LIMIT 100)
WITH (as_table = 'batch_products');
```

**2. Rewrites To:**
```sql
SELECT rvbbit_run_batch(
  'traits/analyze_batch.yaml',
  (SELECT json_group_array(to_json(i)) FROM (
    SELECT * FROM products LIMIT 100
  ) AS i),
  'batch_products'
) AS result
```

**3. UDF Execution:**
- Collects all rows into JSON array
- Creates temp table `batch_products` from rows
- Runs cascade with inputs: `{data_table: 'batch_products', row_count: 100}`
- Returns metadata JSON

**4. Inside Cascade:**
```yaml
# traits/analyze_batch.yaml
cells:
  - name: load
    tool: sql_data
    inputs:
      query: "SELECT * FROM {{ input.data_table }}"
      # Accesses temp table created by RUN!

  - name: analyze
    instructions: "Analyze {{ input.row_count }} products..."
```

**5. Returns:**
```json
{
  "status": "success",
  "session_id": "batch-clever-fox-abc123",
  "table_created": "batch_products",
  "row_count": 100,
  "outputs": {
    "analyze": {...}
  }
}
```

---

## 📊 Implementation Details

### New Components

**1. Rewriter Function** (`sql_rewriter.py`)
- `_rewrite_run()` - Converts RUN syntax to UDF call
- `_ensure_limit_run()` - Auto-limit to 10,000 rows (vs 1,000 for MAP)
- Handles `as_table` option

**2. Batch UDF** (`sql_tools/udf.py`)
- `rvbbit_run_batch(cascade, rows_json, table_name, conn)` - Main implementation
- Creates temp table from JSON array
- Runs cascade with table reference
- Returns JSON metadata
- Session ID format: `batch-<woodland-name>`

**3. UDF Registration**
- Registered as `rvbbit_run_batch` in DuckDB
- Captures connection for temp table creation
- Returns VARCHAR (JSON metadata string)

---

## 🧪 Examples

### Example 1: Basic Batch Analysis

```sql
RVBBIT RUN 'traits/analyze_batch.yaml'
USING (
  SELECT * FROM products
  WHERE category = 'electronics'
  LIMIT 500
)
WITH (as_table = 'electronics_batch');
```

### Example 2: Multi-Phase Batch Processing

```sql
-- Cascade can create multiple output tables!
RVBBIT RUN 'cascades/fraud_batch_analysis.yaml'
USING (
  SELECT * FROM transactions
  WHERE date >= current_date - INTERVAL '1 day'
  LIMIT 1000
)
WITH (as_table = 'daily_txns');

-- Inside cascade:
-- - Creates: _summary_stats table
-- - Creates: _high_risk_txns table
-- - Creates: _customer_profiles table
-- Returns: Metadata pointing to these tables
```

### Example 3: Cost Comparison

```sql
-- MAP: Expensive (100 cascade runs)
RVBBIT MAP 'analyze.yaml' AS analysis
USING (SELECT * FROM products LIMIT 100);
-- Cost: 100 × $0.01 = $1.00

-- RUN: Cheap (1 cascade run)
RVBBIT RUN 'analyze_batch.yaml'
USING (SELECT * FROM products LIMIT 100)
WITH (as_table = 'products_batch');
-- Cost: 1 × $0.05 = $0.05 (20x cheaper!)
```

---

## 🔒 Safety Features

### Auto-LIMIT Injection

```sql
-- No LIMIT specified
RVBBIT RUN 'batch.yaml'
USING (SELECT * FROM huge_table);

-- Auto-adds: LIMIT 10000 (higher than MAP's 1000)
```

**Limits:**
- MAP: 1,000 rows (default)
- RUN: 10,000 rows (default)

**Override:**
```sql
-- Explicit LIMIT respected
RVBBIT RUN 'batch.yaml'
USING (SELECT * FROM t LIMIT 50000);  -- Uses 50,000 if safe
```

---

## 🧪 Testing

**Tests**: 42/42 passing ✅

**New RUN Tests (6 tests):**
- `test_parse_basic_run` - Parse RUN statement
- `test_parse_run_with_as_table` - Parse WITH (as_table = '...')
- `test_rewrite_run_basic` - Rewrite to rvbbit_run_batch()
- `test_rewrite_run_auto_table_name` - Auto-generate table name
- `test_rewrite_rvbbit_syntax_run` - End-to-end RUN rewrite
- Plus existing detection test

```bash
cd /home/ryanr/repos/rvbbit/rvbbit
python -m pytest tests/test_sql_rewriter.py -v
# ✅ 42 passed in 1.62s
```

---

## 🚀 Try It Now!

### Step 1: Restart Server

```bash
pkill -f "rvbbit server"
cd /home/ryanr/repos/rvbbit
rvbbit server --port 15432
```

### Step 2: Test in DBeaver

```sql
RVBBIT RUN 'traits/analyze_batch.yaml'
USING (
  SELECT * FROM (VALUES
    ('Apple iPhone 15', 1199.99),
    ('Samsung Galaxy S24', 1299.99),
    ('Sony WH-1000XM5', 399.99)
  ) AS t(product_name, price)
)
WITH (as_table = 'products_batch');
```

**Expected Result:**
```
result
------
{"status":"success","session_id":"batch-clever-fox-abc123","table_created":"products_batch","row_count":3,"outputs":{...}}
```

**Single row** with full metadata!

---

## 📁 Files Modified/Created

**Modified:**
1. `rvbbit/rvbbit/sql_rewriter.py` - Added `_rewrite_run()`, `_ensure_limit_run()`
2. `rvbbit/rvbbit/sql_tools/udf.py` - Added `rvbbit_run_batch()`, registered UDF
3. `rvbbit/tests/test_sql_rewriter.py` - Added 6 RUN tests
4. `examples/sql_syntax_examples.sql` - Added RUN examples

**Created:**
5. `traits/analyze_batch.yaml` - Example batch cascade
6. `PHASE3_RUN_COMPLETE.md` - This document

---

## ✅ Complete Feature Set (Phase 1-3)

### Row-Wise Processing

```sql
-- Sequential
RVBBIT MAP 'enrich.yaml' AS enriched
USING (SELECT * FROM products LIMIT 100);

-- Parallel (syntax accepted, threading TBD)
RVBBIT MAP PARALLEL 10 'enrich.yaml' AS enriched
USING (SELECT * FROM products LIMIT 100);
```

### Batch Processing

```sql
-- Batch analysis
RVBBIT RUN 'analyze.yaml'
USING (SELECT * FROM products LIMIT 1000)
WITH (as_table = 'batch');
```

### Common Features

- ✅ Auto-LIMIT injection
- ✅ AS alias (MAP only)
- ✅ WITH options
- ✅ Clean value extraction
- ✅ Woodland session IDs
- ✅ Editor-friendly USING clause

---

## 🔮 What's Next

**Phase 2B** (Threading Optimization):
- Add real ThreadPoolExecutor to MAP PARALLEL
- 5-50x speedup for row-wise processing

**Phase 4** (Advanced Features):
- `RETURNING (...)` clause for field extraction
- `RETURNING TABLES` for multi-table batch outputs
- `RUN ASYNC` for background execution
- `MAP BATCH <n>` for chunked processing

**Caller Tracking** (Observability):
- Add `caller_id` to group related sessions
- Track invocation source (SQL query, UI, CLI)
- Cost rollup by caller

---

## 🎁 Summary

**Phase 3 Delivers:**
- ✅ RVBBIT RUN syntax
- ✅ Batch cascade execution
- ✅ Temp table creation
- ✅ 42/42 tests passing
- ✅ Example cascades
- ✅ Documentation

**Ready to test!** Restart server and try RUN queries in DBeaver! 🚀⚓
