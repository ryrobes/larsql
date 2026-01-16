# LARS SQL Features Reference

Complete guide to LARS's SQL enhancements for LLM-powered data processing.

---

## Overview

LARS extends SQL with native LLM integration through custom syntax and UDFs:

| Feature | Status | Description |
|---------|--------|-------------|
| **Schema-Aware Outputs** | ✅ Stable | Typed column extraction from LLM results |
| **EXPLAIN LARS MAP** | ✅ Stable | Cost estimation before execution |
| **MAP DISTINCT** | ✅ Stable | SQL-native deduplication |
| **Cache TTL** | ✅ Stable | Time-based cache expiry |
| **MAP PARALLEL** | ⏸️ Deferred | True concurrency (DuckDB limitation) |
| **Table Materialization** | 🚧 Coming | CREATE TABLE AS support |

---

## 1. Schema-Aware Outputs

### Problem
**Before**: UDFs returned single VARCHAR column with JSON string
```sql
-- Returns: product_name | result
--          "iPhone 15"  | '{"brand":"Apple","confidence":0.95}'
```

**After**: Extract typed columns directly
```sql
-- Returns: product_name | brand  | confidence
--          "iPhone 15"  | "Apple" | 0.95
```

### Syntax

#### Option A: Explicit Schema (Recommended)
```sql
LARS MAP 'cascade.yaml' AS (
    column1 TYPE1,
    column2 TYPE2,
    column3 TYPE3
)
USING (SELECT * FROM table);
```

#### Option B: Inferred from Cascade
```sql
LARS MAP 'cascade.yaml'
USING (SELECT * FROM table)
WITH (infer_schema = true);
```

### Supported SQL Types

| SQL Type | JSON Schema Type | Notes |
|----------|------------------|-------|
| `VARCHAR`, `TEXT`, `STRING` | `string` | Text data |
| `BIGINT`, `INTEGER`, `INT` | `integer` | Whole numbers |
| `DOUBLE`, `FLOAT`, `REAL` | `number` | Decimals |
| `BOOLEAN`, `BOOL` | `boolean` | true/false |
| `JSON` | `array`, `object` | Nested structures |
| `TIMESTAMP`, `DATE`, `TIME` | - | Temporal types |

### Complete Example

**Cascade** (`traits/extract_product_info.yaml`):
```yaml
cascade_id: extract_product_info
cells:
- name: extract
  instructions: |
    Extract product information from: {{ input.product_name }}
    Return JSON with: brand, category, price_tier, confidence, is_luxury
  traits: []
  output_schema:
    type: object
    properties:
      brand: {type: string}
      category: {type: string}
      price_tier: {type: string, enum: ["Budget", "Mid-range", "Premium"]}
      confidence: {type: number, minimum: 0, maximum: 1}
      is_luxury: {type: boolean}
    required: [brand, category, price_tier, confidence, is_luxury]
```

**SQL Query**:
```sql
-- Explicit schema
LARS MAP 'traits/extract_product_info.yaml' AS (
    brand VARCHAR,
    category VARCHAR,
    price_tier VARCHAR,
    confidence DOUBLE,
    is_luxury BOOLEAN
)
USING (
    SELECT product_id, product_name
    FROM products
    LIMIT 100
);

-- Result columns: product_id, product_name, brand, category, price_tier, confidence, is_luxury
-- All properly typed!
```

**Inferred Schema**:
```sql
-- Automatically reads output_schema from YAML
LARS MAP 'traits/extract_product_info.yaml'
USING (SELECT product_name FROM products LIMIT 100)
WITH (infer_schema = true);
```

### How It Works

1. **LLM returns JSON**: `{"brand": "Apple", "category": "Electronics", "confidence": 0.95, "is_luxury": true}`
2. **Validated against output_schema**: Ensures structure matches
3. **Stored in state**: `state.validated_output.*`
4. **SQL extracts fields**: `json_extract_string(_raw_result, '$.state.validated_output.brand')`
5. **Type casting applied**: `CAST(... AS DOUBLE)` for numbers, booleans

---

## 2. EXPLAIN LARS MAP

### Purpose
Analyze queries and estimate costs **before** execution.

### Syntax
```sql
EXPLAIN LARS MAP 'cascade.yaml'
USING (SELECT * FROM table LIMIT N);
```

### What You Get

```
→ Query Plan:
  ├─ Input Rows: 100
  ├─ Cascade: examples/test_schema_output.yaml
  │  ├─ Phases: 1 (extract_product_info)
  │  ├─ Model: google/gemini-2.5-flash-lite
  │  ├─ Candidates: 1
  │  └─ Cost Estimate: $0.000704 per row → $0.07 total
  ├─ Cache Hit Rate: 0% (first run, all rows will call LLM)
  └─ Rewritten SQL:
      WITH lars_input AS (
        SELECT product_name FROM products LIMIT 100
      ),
      lars_raw AS (
        SELECT i.*, lars_run(...) AS _raw_result FROM lars_input i
      )
      ...
```

### Use Cases

1. **Budget control**: Check cost before running expensive queries
2. **Debugging**: See the exact SQL that will be executed
3. **Cache analysis**: Understand how many LLM calls will actually happen
4. **Query planning**: Compare different cascade approaches

### Examples

```sql
-- Estimate cost for large batch
EXPLAIN LARS MAP 'traits/classify_sentiment.yaml'
USING (SELECT review_text FROM reviews LIMIT 10000);

-- With schema inference
EXPLAIN LARS MAP 'traits/extract_brand.yaml'
USING (SELECT product_name FROM products)
WITH (infer_schema = true);

-- With DISTINCT (shows dedupe impact)
EXPLAIN LARS MAP DISTINCT 'cascade.yaml'
USING (SELECT text FROM documents);
```

### Cost Estimation Details

**Model Pricing** (hardcoded, should query OpenRouter API):
- `google/gemini-2.5-flash-lite`: $0.001/M input, $0.002/M output
- `anthropic/claude-sonnet-4.5`: $0.003/M input, $0.015/M output
- `anthropic/claude-opus-4.5`: $0.015/M input, $0.075/M output

**Token Estimates**:
- Prompt: ~500 tokens per row (conservative)
- Completion: ~200 tokens per row (varies by task)

**Formula**:
```
cost_per_row = (prompt_tokens × input_price + completion_tokens × output_price) × phases × candidates
total_cost = cost_per_row × input_rows × (1 - cache_hit_rate)
```

**Cache Hit Rate**: Samples first 10 rows and checks `_cascade_udf_cache`

---

## 3. MAP DISTINCT - Deduplication

### Purpose
Eliminate duplicate inputs before LLM processing to save costs.

### Syntax

#### Option A: DISTINCT Keyword
```sql
LARS MAP DISTINCT 'cascade.yaml'
USING (SELECT * FROM table);
```
Deduplicates on **all columns** in USING query.

#### Option B: Dedupe by Specific Column(s)
```sql
LARS MAP 'cascade.yaml'
USING (SELECT * FROM table)
WITH (dedupe_by='column_name');
```
Deduplicates using `DISTINCT ON (column_name)`.

### How It Works

**Rewrite Strategy**: Wraps USING query with DISTINCT clause at SQL level

**Before**:
```sql
USING (SELECT product_name FROM products)
```

**After (DISTINCT)**:
```sql
USING (SELECT DISTINCT product_name FROM products)
```

**After (DISTINCT ON)**:
```sql
USING (SELECT DISTINCT ON (product_name) * FROM (
  SELECT product_name FROM products
) AS t)
```

### Examples

```sql
-- Dedupe all columns
LARS MAP DISTINCT 'traits/extract_brand.yaml'
USING (
    SELECT product_name, category
    FROM products
);
-- Only processes unique (product_name, category) combinations

-- Dedupe by specific column
LARS MAP 'traits/analyze_customer.yaml'
USING (
    SELECT customer_id, email, purchase_date
    FROM transactions
)
WITH (dedupe_by='customer_id');
-- Only processes each customer once (keeps first occurrence)

-- Combine with schema
LARS MAP DISTINCT 'cascade.yaml' AS (
    result VARCHAR,
    score DOUBLE
)
USING (SELECT text FROM reviews);
```

### Performance Impact

**Test Case**: 1000 products, 500 unique product names

- **Without DISTINCT**: 1000 LLM calls
- **With DISTINCT**: 500 LLM calls (50% cost savings!)

**Cache vs DISTINCT**:
- Cache: Saves on repeated queries (session-scoped)
- DISTINCT: Saves within single query (query-scoped)
- **Use both** for maximum savings!

---

## 4. Cache TTL - Time-Based Expiry

### Purpose
Control cache lifetime to balance cost savings with data freshness.

### Syntax
```sql
LARS MAP 'cascade.yaml'
USING (SELECT * FROM table)
WITH (cache='duration');
```

### Duration Formats

| Format | Seconds | Example Use Case |
|--------|---------|------------------|
| `'60s'` | 60 | Real-time data |
| `'30m'` | 1,800 | Session-length tasks |
| `'2h'` | 7,200 | Batch processing |
| `'1d'` | 86,400 | Daily refreshes |
| `3600` | 3,600 | Raw seconds (2h) |

### Examples

```sql
-- Short-lived cache for real-time data
LARS MAP 'traits/sentiment_analysis.yaml'
USING (SELECT tweet_text FROM tweets_realtime)
WITH (cache='5m');

-- Daily cache for stable reference data
LARS MAP 'traits/extract_brand.yaml'
USING (SELECT product_name FROM products)
WITH (cache='1d');

-- No cache (always call LLM)
LARS MAP 'cascade.yaml'
USING (SELECT * FROM data)
WITH (cache='0s');
```

### Cache Behavior

**Default**: Infinite TTL (same as before, backward compatible)

**With TTL**:
1. Result cached with timestamp and TTL
2. On cache hit: Check `current_time - timestamp > ttl`
3. If expired: Delete from cache, call LLM
4. If fresh: Return cached value

**Storage**: In-memory Python dict, cleared on server restart

**Scope**: Per DuckDB connection (session-scoped)

### Combine with DISTINCT

```sql
-- Dedupe inputs + cache results for 1 day
LARS MAP DISTINCT 'cascade.yaml'
USING (SELECT product FROM catalog)
WITH (dedupe_by='product', cache='1d');
```

**Result**: Minimum LLM calls + cached for 24 hours!

---

## 5. Complete Feature Matrix

### Syntax Combinations

```sql
-- 1. Basic MAP
LARS MAP 'cascade.yaml'
USING (SELECT * FROM t);

-- 2. With alias
LARS MAP 'cascade.yaml' AS result_col
USING (SELECT * FROM t);

-- 3. With typed schema
LARS MAP 'cascade.yaml' AS (col1 VARCHAR, col2 DOUBLE)
USING (SELECT * FROM t);

-- 4. With inferred schema
LARS MAP 'cascade.yaml'
USING (SELECT * FROM t)
WITH (infer_schema = true);

-- 5. With DISTINCT
LARS MAP DISTINCT 'cascade.yaml'
USING (SELECT * FROM t);

-- 6. With dedupe_by
LARS MAP 'cascade.yaml'
USING (SELECT * FROM t)
WITH (dedupe_by='col_name');

-- 7. With cache TTL
LARS MAP 'cascade.yaml'
USING (SELECT * FROM t)
WITH (cache='1d');

-- 8. EXPLAIN (no execution)
EXPLAIN LARS MAP 'cascade.yaml'
USING (SELECT * FROM t LIMIT 100);

-- 9. EVERYTHING COMBINED
EXPLAIN LARS MAP DISTINCT 'cascade.yaml' AS (
    brand VARCHAR,
    confidence DOUBLE
)
USING (SELECT product FROM products)
WITH (dedupe_by='product', cache='1d', infer_schema=false);
```

### WITH Options Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `infer_schema` | boolean | false | Read output_schema from cascade YAML |
| `distinct` | boolean | false | Enable DISTINCT (also via DISTINCT keyword) |
| `dedupe_by` | string | null | Column(s) for DISTINCT ON |
| `cache` | string | null | Cache TTL ('1d', '2h', '30m', '60s') |
| `result_column` | string | 'result' | Name for result column (alternative to AS) |

---

## 6. UDF Reference

### lars_udf()

**Simple LLM extraction** - Single LLM call per row

```sql
SELECT
    product_name,
    lars_udf('Extract brand', product_name) as brand
FROM products;
```

**Signature**:
```python
lars_udf(
    instructions: str,      # What to ask the LLM
    input_value: str,       # Data to process
    model: str = None,      # Optional model override
    temperature: float = 0.0,
    max_tokens: int = 500,
    use_cache: bool = True,
    cache_ttl: str = None   # NEW: '1d', '2h', etc.
) -> str
```

**Returns**: VARCHAR (LLM response as string)

### lars_cascade_udf() / lars_run()

**Full cascade execution** - Multi-phase workflows with validation, soundings, tools

```sql
SELECT
    customer_id,
    lars_run(
        'cascades/fraud_check.yaml',
        json_object('customer_id', customer_id)
    ) as fraud_result
FROM transactions;
```

**Signature**:
```python
lars_cascade_udf(
    cascade_path: str,       # Path to cascade YAML
    inputs_json: str,        # JSON string of inputs
    use_cache: bool = True,
    return_field: str = None # Extract specific field
) -> str
```

**Returns**: JSON string with full cascade outputs

**With field extraction**:
```sql
SELECT
    customer_id,
    lars_run(
        'cascades/fraud_check.yaml',
        json_object('customer_id', customer_id),
        'risk_score'  -- Extract just this field
    ) as risk_score
FROM transactions;
```

---

## 7. Real-World Examples

### E-commerce Product Enrichment

```sql
-- Create enriched product catalog with typed outputs
LARS MAP 'traits/extract_product_info.yaml' AS (
    brand VARCHAR,
    category VARCHAR,
    price_tier VARCHAR,
    confidence DOUBLE,
    is_luxury BOOLEAN
)
USING (
    SELECT
        product_id,
        product_name,
        price
    FROM products
    WHERE price > 100  -- Only expensive products
    LIMIT 1000
)
WITH (cache='1d');  -- Cache for 24 hours

-- Result: product_id | product_name | price | brand | category | price_tier | confidence | is_luxury
```

### Customer Sentiment Analysis

```sql
-- Dedupe customers before analysis
LARS MAP DISTINCT 'cascades/customer_satisfaction.yaml' AS (
    sentiment VARCHAR,
    satisfaction_score DOUBLE,
    likely_to_churn BOOLEAN
)
USING (
    SELECT
        c.customer_id,
        c.email,
        COUNT(t.ticket_id) as support_tickets,
        AVG(t.rating) as avg_rating
    FROM customers c
    LEFT JOIN support_tickets t ON c.customer_id = t.customer_id
    GROUP BY c.customer_id, c.email
)
WITH (dedupe_by='customer_id', cache='12h');
```

### Cost-Conscious Data Cleaning

```sql
-- Check cost first
EXPLAIN LARS MAP 'cascades/clean_address.yaml'
USING (SELECT address FROM contacts LIMIT 50000);

-- If acceptable, run with deduplication
LARS MAP DISTINCT 'cascades/clean_address.yaml' AS (
    street VARCHAR,
    city VARCHAR,
    state VARCHAR,
    zip VARCHAR,
    is_valid BOOLEAN
)
USING (SELECT address FROM contacts)
WITH (dedupe_by='address', cache='7d');
```

---

## 8. Performance Best Practices

### 1. Always Use LIMIT
```sql
-- GOOD: Explicit limit
LARS MAP 'cascade.yaml'
USING (SELECT * FROM huge_table LIMIT 100);

-- AUTO: Limit added automatically if missing (default: 1000)
LARS MAP 'cascade.yaml'
USING (SELECT * FROM huge_table);
-- Becomes: ... LIMIT 1000
```

### 2. Dedupe Before Processing
```sql
-- GOOD: 10K products → 2K unique brands → 2K LLM calls
LARS MAP DISTINCT 'extract_brand.yaml'
USING (SELECT product_name FROM products)
WITH (dedupe_by='product_name');

-- BAD: 10K LLM calls
LARS MAP 'extract_brand.yaml'
USING (SELECT product_name FROM products);
```

### 3. Use EXPLAIN for Cost Control
```sql
-- Always EXPLAIN large batches first
EXPLAIN LARS MAP 'expensive_cascade.yaml'
USING (SELECT * FROM massive_table LIMIT 10000);
-- Check: "Cost Estimate: $X.XX total"
-- Decide if acceptable before running
```

### 4. Leverage Cache with Appropriate TTL
```sql
-- Static reference data: Long TTL
LARS MAP 'extract_brand.yaml'
USING (SELECT product FROM catalog)
WITH (cache='7d');

-- Real-time data: Short TTL
LARS MAP 'sentiment.yaml'
USING (SELECT tweet FROM twitter_stream)
WITH (cache='5m');

-- One-off analysis: No cache
LARS MAP 'analyze.yaml'
USING (SELECT * FROM temp_data)
WITH (cache='0s');
```

### 5. Choose Right Granularity
```sql
-- Fine-grained: lars_udf for simple extraction
SELECT
    product_name,
    lars_udf('Extract brand', product_name) as brand,
    lars_udf('Classify category', product_name) as category
FROM products;

-- Coarse-grained: lars_run for complex multi-step
SELECT
    product_name,
    lars_run('cascades/full_analysis.yaml', json_object('product', product_name))
FROM products;

-- Structured: LARS MAP with schema for typed outputs
LARS MAP 'cascades/full_analysis.yaml' AS (
    brand VARCHAR,
    category VARCHAR,
    sentiment DOUBLE
)
USING (SELECT product_name FROM products);
```

---

## 9. Troubleshooting

### NULL Results

**Problem**: Schema-aware outputs return NULL

**Solution**: Check JSON path
- Data must be at `$.state.validated_output.{column}`
- Cascade must have `output_schema` defined
- LLM must return valid JSON matching schema

**Debug query**:
```sql
-- See raw JSON structure
LARS MAP 'cascade.yaml'
USING (SELECT * FROM table LIMIT 1);
-- Inspect the 'result' column to see actual JSON structure
```

### Cache Not Working

**Problem**: Same query calls LLM every time

**Solution**: Check cache key components
- UDF cache: Hash of `instructions|input|model`
- Cascade cache: Hash of `cascade_path|inputs`
- Inputs must be **exactly** the same (case-sensitive!)

**Clear cache**:
```python
from lars.sql_tools.udf import clear_udf_cache
clear_udf_cache()
```

### Type Mismatch Errors

**Problem**: `CAST failed: cannot cast "abc" to DOUBLE`

**Solution**: Ensure LLM output matches declared types
- Add validation to cascade `output_schema`
- Use string types for unreliable data
- Add error handling in cascade

---

## 10. Migration Guide

### From Simple UDF to Schema-Aware

**Before**:
```sql
SELECT
    product,
    lars_udf('Extract brand and category', product) as result
FROM products;

-- Result: product | result
--         "iPhone" | '{"brand":"Apple","category":"Electronics"}'

-- Manual parsing:
SELECT
    product,
    json_extract_string(result, '$.brand') as brand,
    json_extract_string(result, '$.category') as category
FROM (/* above query */) t;
```

**After**:
```sql
LARS MAP 'traits/extract_brand_category.yaml' AS (
    brand VARCHAR,
    category VARCHAR
)
USING (SELECT product FROM products);

-- Result: product | brand | category
--         "iPhone" | "Apple" | "Electronics"
-- No manual parsing needed!
```

### From Manual Dedupe to MAP DISTINCT

**Before**:
```sql
WITH unique_products AS (
    SELECT DISTINCT product_name FROM products
)
SELECT
    product_name,
    lars_udf('Extract brand', product_name) as brand
FROM unique_products;
```

**After**:
```sql
LARS MAP DISTINCT 'traits/extract_brand.yaml' AS brand
USING (SELECT product_name FROM products);
-- Deduplication happens automatically!
```

---

## 11. Advanced Patterns

### Fan-Out with Downstream Aggregation

```sql
-- Step 1: Enrich all products
CREATE TEMP TABLE enriched_products AS
LARS MAP 'traits/classify.yaml' AS (
    category VARCHAR,
    subcategory VARCHAR,
    confidence DOUBLE
)
USING (SELECT product_id, product_name FROM products);

-- Step 2: Aggregate by category
SELECT
    category,
    COUNT(*) as product_count,
    AVG(confidence) as avg_confidence
FROM enriched_products
WHERE confidence > 0.8
GROUP BY category
ORDER BY product_count DESC;
```

### Conditional Processing

```sql
-- Only process high-value transactions
LARS MAP 'cascades/fraud_check.yaml' AS (
    risk_score DOUBLE,
    is_suspicious BOOLEAN,
    explanation VARCHAR
)
USING (
    SELECT
        transaction_id,
        amount,
        merchant,
        customer_id
    FROM transactions
    WHERE amount > 1000  -- Pre-filter before LLM
    LIMIT 500
)
WITH (cache='1h');
```

### Multi-Model Comparison (Future)

```sql
-- When PARALLEL is fully implemented:
LARS MAP PARALLEL 5 'cascade_with_soundings.yaml' AS (
    best_answer VARCHAR,
    confidence DOUBLE
)
USING (SELECT question FROM support_tickets LIMIT 100);
-- Will run 5 candidates per row, pick best!
```

---

## 12. Roadmap

### ✅ Implemented (Available Now)
- Schema-aware outputs with type safety
- EXPLAIN for cost estimation
- MAP DISTINCT for deduplication
- Cache TTL for time-based expiry

### 🚧 In Progress
- Table materialization: `CREATE TABLE AS LARS MAP`
- Enhanced EXPLAIN with query optimization hints

### 🔮 Future
- **MAP PARALLEL**: True ThreadPoolExecutor concurrency (requires postgres_server redesign)
- **MAP BATCH**: Chunked processing for memory efficiency
- **RETURNING clause**: Multi-column extraction from nested JSON
- **Query optimizer**: Automatic DISTINCT detection and caching strategies
- **Cost-based planning**: Auto-select best cascade based on budget
- **Incremental MAP**: Process only new rows since last run

---

## 13. FAQ

**Q: What's the difference between LARS MAP and lars_udf?**

A: `lars_udf()` is a simple scalar function (one LLM call per row). LARS MAP syntax provides:
- Cleaner SQL syntax
- Auto-LIMIT safety
- Schema-aware outputs
- DISTINCT deduplication
- EXPLAIN support

**Q: Does cache persist across sessions?**

A: No, cache is in-memory per DuckDB connection. Cleared on server restart.

**Q: Can I use multiple WITH options?**

A: Yes! `WITH (cache='1d', dedupe_by='id', infer_schema=true)`

**Q: What happens if LLM returns invalid JSON?**

A: With `output_schema`: Validation fails, cascade retries or errors. Without: Returns raw string.

**Q: Can I EXPLAIN a query with schema inference?**

A: Yes! EXPLAIN will load the cascade and show inferred schema in the plan.

---

## 14. Quick Reference Card

```sql
-- Template
[EXPLAIN] LARS MAP [DISTINCT] [PARALLEL N] 'cascade.yaml'
  [AS identifier | AS (col TYPE, ...)]
  USING (SELECT ...)
  [WITH (option=value, ...)];

-- Examples
EXPLAIN                           -- Cost estimate only
LARS MAP                        -- Execute cascade
DISTINCT                          -- Dedupe all columns
PARALLEL 10                       -- Concurrency (deferred)
'traits/extract.yaml'             -- Cascade path
AS brand                          -- Single result column name
AS (brand VARCHAR, conf DOUBLE)   -- Typed output schema
USING (SELECT * FROM t LIMIT 100) -- Input data
WITH (                            -- Options
    cache='1d',                   -- Cache for 1 day
    dedupe_by='name',             -- Dedupe by column
    infer_schema=true             -- Read schema from YAML
);
```

---

**See Also**:
- `examples/sql_syntax_examples.sql` - Complete syntax examples
- `examples/test_schema_output.yaml` - Example cascade with output_schema
- `LARS_MAP_QUICKSTART.md` - Original MAP syntax guide
- `TRAIT_SQL_SYNTAX.md` - trait:: namespace syntax with dot accessors
