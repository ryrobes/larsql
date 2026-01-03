# Parallel Execution for Semantic SQL Operators - Research & Design

**Date:** 2026-01-02
**Status:** 📋 Research Complete - Ready for Planning Discussion
**Complexity:** Medium-High (~1150 lines, 6-8 weeks)
**Expected Benefit:** 3-5x speedup for semantic operators

## TL;DR

**Can we do it?** ✅ YES

**How?** Extend existing `-- @` annotation system with `parallel: N` parameter

**Approach:** Collect rows at SQL query level, batch to parallel UDF using existing ThreadPoolExecutor pattern (proven in `rvbbit_map_parallel_exec`)

**Syntax:**
```sql
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'sustainable' LIMIT 1000
```

**Performance:** 5x speedup (1000 rows in 6 minutes vs 33 minutes)

---

## THE PROBLEM

### Current Execution: Sequential Row-by-Row

```
Query: WHERE description MEANS 'sustainable' LIMIT 1000

DuckDB Execution:
  Row 1: matches('sustainable', description) → LLM call (2s)
  Row 2: matches('sustainable', description) → LLM call (2s)
  Row 3: matches('sustainable', description) → LLM call (2s)
  ...
  Row 1000: matches('sustainable', description) → LLM call (2s)

Total: 2000 seconds (33 minutes) 😱
```

**Root Cause:** DuckDB calls UDFs **sequentially**, one row at a time. No built-in parallelism for user-defined functions.

### What We Want

```
Query:
-- @ parallel: 5
WHERE description MEANS 'sustainable' LIMIT 1000

Parallel Execution:
  Batch 1 (rows 1-200): Process in parallel → 2s
  Batch 2 (rows 201-400): Process in parallel → 2s
  Batch 3 (rows 401-600): Process in parallel → 2s
  Batch 4 (rows 601-800): Process in parallel → 2s
  Batch 5 (rows 801-1000): Process in parallel → 2s

Total: 400 seconds (6.6 minutes) ✅ 5x faster!
```

---

## EXISTING PARALLEL INFRASTRUCTURE

### You Already Have This Working! ✅

**File:** `rvbbit/sql_tools/udf.py`

#### 1. rvbbit_run_parallel_batch() (Lines 572-640)

```python
def rvbbit_run_parallel_batch(cascade_path, rows_json_array, max_workers):
    """Execute cascade on multiple rows in parallel using ThreadPoolExecutor."""

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_row, i, row): i for i, row in enumerate(rows)}
        for future in as_completed(futures):
            index, result = future.result()
            results[index] = result  # ✅ Preserves order!

    return '\n'.join(ndjson_lines)
```

**Key Features:**
- ✅ ThreadPoolExecutor with configurable max_workers
- ✅ Order preservation via indexed results array
- ✅ Error handling per row
- ✅ Returns NDJSON (newline-delimited JSON)

#### 2. rvbbit_map_parallel_exec() (Lines 643-741)

```python
def rvbbit_map_parallel_exec(cascade_path, rows_json_array, max_workers, result_column):
    """Execute cascade on rows in parallel, return JSON array."""

    def process_row(index, row):
        row_json = json.dumps(row)
        result_json = rvbbit_cascade_udf_impl(cascade_path, row_json, use_cache=True)
        # Extract result, enrich row
        return index, {**row, result_column: extracted}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_row, i, row): i for i, row in enumerate(rows)}
        for future in as_completed(futures):
            index, enriched_row = future.result()
            results[index] = enriched_row

    return json.dumps(results)
```

**Key Features:**
- ✅ Same ThreadPoolExecutor pattern
- ✅ Calls `rvbbit_cascade_udf_impl()` (same as semantic operators!)
- ✅ Order preservation
- ✅ Returns JSON array

### Pattern Already Proven

```
RVBBIT MAP PARALLEL 5 'cascade.yaml' USING (SELECT * FROM t LIMIT 1000)

Current handling (sql_rewriter.py:614):
  if stmt.parallel is not None:
      max_workers = stmt.parallel
      # TODO: Actually implement parallelism
      # For now falls back to sequential
```

**The scaffolding exists, just needs wiring up to semantic operators!**

---

## ANNOTATION SYSTEM (Already Exists!)

### Current Capabilities

**File:** `rvbbit/sql_tools/semantic_operators.py:117-204`

```python
@dataclass
class SemanticAnnotation:
    prompt: Optional[str] = None          # Model hints
    model: Optional[str] = None           # Model override
    threshold: Optional[float] = None     # ABOUT threshold
    # ... positional fields ...
```

**Parsing** handles:
```sql
-- @ use a fast model             (free-form prompt)
-- @ model: google/gemini-flash   (key: value)
-- @ threshold: 0.8                (key: value)
```

**Already integrated** into semantic operator rewriting (semantic_operators.py:295-301).

### Easy Extension

Add new fields:
```python
@dataclass
class SemanticAnnotation:
    # ... existing ...
    parallel: Optional[int] = None        # Number of workers
    batch_size: Optional[int] = None      # Rows per batch
```

Update parser (lines 162-182):
```python
if key == 'parallel':
    try:
        current_annotation.parallel = int(value) if value else os.cpu_count()
    except ValueError:
        current_annotation.parallel = os.cpu_count()
elif key == 'batch_size':
    current_annotation.batch_size = int(value)
```

**Estimated LOC:** ~20 lines to add parallel annotation support

---

## THE CHALLENGE: DuckDB's Execution Model

### Why It's Tricky

```
SQL: SELECT col, matches(criteria, col) FROM table

DuckDB execution:
  1. Scan table row-by-row
  2. For each row, evaluate: matches(criteria, row.col)
  3. UDF receives ONE row at a time
  4. No way to "collect" rows from within UDF
```

**We can't control batching from inside the UDF** because each call is independent.

### The Solution: Row Collection at Query Level

Transform the query to **collect rows first, then batch process**:

```sql
-- Original (with annotation):
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'sustainable' LIMIT 1000

-- Rewritten to:
WITH collected_rows AS (
  SELECT
    id,
    description,
    ROW_NUMBER() OVER (ORDER BY id) as row_num
  FROM products
  LIMIT 1000
),
batch_results AS (
  SELECT semantic_batch_matches(
    'sustainable',
    json_array_agg(json_object('id', id, 'text', description) ORDER BY row_num),
    5
  ) as results_json
  FROM collected_rows
)
SELECT p.*
FROM products p
JOIN (
  SELECT id, json_extract(value, '$.result')::BOOLEAN as matches_result
  FROM batch_results,
  LATERAL unnest(json_parse(results_json)) as t(value)
) br ON p.id = br.id
WHERE br.matches_result = true
```

**This is similar to how MAP PARALLEL works!**

---

## RECOMMENDED IMPLEMENTATION: OPTION A

### Architecture

**4 Components:**

1. **Annotation Extension** (semantic_operators.py)
   - Add `parallel` and `batch_size` fields to SemanticAnnotation
   - Update `_parse_annotations()` to handle new keys

2. **Batch UDFs** (udf.py)
   - `semantic_batch_matches(criteria, rows_json, max_workers) → JSON`
   - `semantic_batch_score(criteria, rows_json, max_workers) → JSON`
   - `semantic_batch_implies(premises_json, conclusions_json, max_workers) → JSON`
   - Pattern: Reuse rvbbit_map_parallel_exec (lines 643-741)

3. **Query Rewriter** (semantic_operators.py)
   - Detect: parallel annotation + simple WHERE semantic operator
   - Transform: Collect rows → batch UDF → unnest results
   - Start with: MEANS operator only (simplest)
   - Expand to: ABOUT, IMPLIES, CONTRADICTS, ASK, EXTRACTS, CONDENSE

4. **Caching Layer** (udf.py)
   - Cache batch results (not just individual rows)
   - Key: `md5(cascade_id|criteria|row_ids_sorted)`
   - Benefit: Subsequent queries with same criteria on same data = instant

### Detailed Flow

```
-- @ parallel: 5
WHERE description MEANS 'sustainable'
              ↓
[semantic_operators.py:_rewrite_semantic_operators()]
  • Parse annotation: parallel=5
  • Detect MEANS operator
  • Check if parallelizable (simple WHERE clause, no NOT, no complex logic)
              ↓
[Transform query to batch pattern]
  WITH collected_rows AS (...)
  SELECT * FROM batch_execute(...) WHERE result = true
              ↓
[DuckDB executes transformed query]
  • Collects all rows
  • Calls semantic_batch_matches(criteria, rows_json, 5)
              ↓
[semantic_batch_matches() in udf.py]
  • Parse rows JSON
  • Create thread pool (5 workers)
  • Submit tasks: executor.submit(run_cascade, row)
  • Wait for all: as_completed(futures)
  • Preserve order: results[index] = result
  • Return: JSON {"row_1_id": true, "row_2_id": false, ...}
              ↓
[DuckDB continues]
  • Parse JSON result
  • Join back to original rows
  • Filter where result = true
  • Return final result set
```

### Example Transformation

**Before:**
```sql
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'eco-friendly' LIMIT 100
```

**After (rewritten by semantic_operators.py):**
```sql
WITH __semantic_collect_0 AS (
  SELECT id, description, ROW_NUMBER() OVER (ORDER BY id) as __row_num
  FROM products
  LIMIT 100
),
__semantic_batch_0 AS (
  SELECT semantic_batch_matches(
    'eco-friendly',
    json_group_array(json_object('__row_num', __row_num, 'id', id, 'text', description)),
    5
  ) as __results
  FROM __semantic_collect_0
)
SELECT p.*
FROM products p
JOIN (
  SELECT
    json_extract(value, '$.__row_num')::INTEGER as __row_num,
    json_extract(value, '$.result')::BOOLEAN as __result
  FROM __semantic_batch_0,
  LATERAL read_json_auto(array_to_string([__results], ''))
) r ON p.id = r.id
WHERE r.__result = true
ORDER BY r.__row_num
```

(This is simplified - actual implementation would be more robust)

---

## PROPOSED ANNOTATION SYNTAX

### Minimal (Defaults)

```sql
-- @ parallel
SELECT * FROM table WHERE col MEANS 'pattern'
-- Uses default: CPU count workers (8), batch_size 100
```

### Explicit Workers

```sql
-- @ parallel: 10
SELECT * FROM table WHERE col MEANS 'pattern'
-- Uses: 10 workers
```

### With Batch Size

```sql
-- @ parallel: 5
-- @ batch_size: 50
SELECT * FROM table WHERE col MEANS 'pattern'
-- Processes 50 rows per batch with 5 workers
```

### Combined with Other Annotations

```sql
-- @ use fast and cheap model
-- @ parallel: 8
-- @ threshold: 0.7
SELECT * FROM docs WHERE content ABOUT 'machine learning'
```

### Multiple Operators (Scope Control)

```sql
-- @ parallel_scope: query
-- @ parallel: 10
SELECT
  id,
  description MEANS 'eco-friendly' as is_eco,      -- Parallel
  description EXTRACTS 'price' as price,            -- Parallel
  description ASK 'urgency 1-10' as urgency        -- Parallel
FROM products
WHERE description MEANS 'sustainable'               -- Parallel
```

All operators use same parallel settings (query-scope).

---

## IMPLEMENTATION COMPLEXITY

### Phase 1: Foundation (~400 LOC, 2 weeks)

**Files to Modify:**

1. `semantic_operators.py:117-125` - Extend SemanticAnnotation
   ```python
   @dataclass
   class SemanticAnnotation:
       # ... existing ...
       parallel: Optional[int] = None
       batch_size: Optional[int] = None
       parallel_scope: str = "operator"  # or "query"
   ```

2. `semantic_operators.py:163-182` - Update _parse_annotations()
   ```python
   elif key == 'parallel':
       current_annotation.parallel = int(value) if value else os.cpu_count()
   elif key == 'batch_size':
       current_annotation.batch_size = int(value)
   elif key == 'parallel_scope':
       current_annotation.parallel_scope = value
   ```

3. `udf.py` - Add semantic_batch_matches() (~150 lines)
   ```python
   def semantic_batch_matches(criteria: str, rows_json: str, max_workers: int) -> str:
       """
       Execute matches() on multiple rows in parallel.

       Pattern copied from rvbbit_map_parallel_exec (line 643).
       Returns JSON: [{"id": 1, "result": true}, {"id": 2, "result": false}, ...]
       """
       # ThreadPoolExecutor pattern
       # Order preservation via indexed results
       # Error handling per row
   ```

4. `semantic_operators.py` - Add _rewrite_with_parallel() (~150 lines)
   ```python
   def _rewrite_with_parallel(query: str, annotation: SemanticAnnotation) -> str:
       """
       Transform query to use batch execution.

       Steps:
       1. Detect WHERE clause with semantic operator
       2. Extract table name and columns
       3. Wrap in CTE for row collection
       4. Call batch UDF
       5. Unnest results and join back
       """
   ```

5. Register batch UDF (udf.py:1122)

### Phase 2: More Operators (~300 LOC, 2 weeks)

- semantic_batch_score() for ABOUT
- semantic_batch_implies() for IMPLIES
- semantic_batch_extract() for EXTRACTS
- semantic_batch_ask() for ASK
- semantic_batch_condense() for CONDENSE

### Phase 3: Advanced (~250 LOC, 2-3 weeks)

- Aggregate operators (SUMMARIZE with map-reduce)
- Complex WHERE clauses (AND/OR/NOT)
- Multiple operators per query
- Query-scope annotations

### Phase 4: Testing & Docs (~200 LOC, 1-2 weeks)

- Unit tests for batch UDFs
- Integration tests (parallel vs sequential same results)
- Performance benchmarks
- Documentation

**Total:** ~1150 lines, 6-8 weeks

---

## KEY DESIGN DECISIONS

### 1. When to Activate Parallel Execution?

**Recommended:** Explicit opt-in via annotation

```sql
-- Explicitly parallel:
-- @ parallel: 5
WHERE col MEANS 'x'

-- Sequential (default):
WHERE col MEANS 'x'
```

**Why?**
- Clear user intent
- No surprise behavior changes
- Can optimize for single-row vs batch use cases

**Alternative (rejected):** Auto-parallel above threshold
```sql
-- REJECTED: Too magical
SELECT * FROM big_table WHERE col MEANS 'x'
-- Automatically goes parallel if > 1000 rows?
-- Problem: User doesn't know when parallel kicks in, harder to debug
```

### 2. Annotation Scope

**Per-Operator (Default):**
```sql
-- @ parallel: 5
WHERE description MEANS 'eco'   -- Parallel
  AND description EXTRACTS 'price'  -- Sequential (no annotation)
```

**Query-Wide:**
```sql
-- @ parallel_scope: query
-- @ parallel: 10
SELECT
  id,
  description MEANS 'eco' as eco,      -- Parallel
  description EXTRACTS 'price' as price  -- Parallel (inherited)
FROM products
WHERE description MEANS 'sustainable'    -- Parallel (inherited)
```

**Recommended:** Start with per-operator, add query-scope later.

### 3. Row Collection Strategy

**Option A: Collect WHERE rows only** (Simple)
```sql
WITH collected AS (
  SELECT * FROM table WHERE {non-semantic conditions}  -- Fast filters
  LIMIT {annotation.batch_size or 1000}
)
SELECT * FROM batch_execute(collected)
```

**Option B: Collect all rows, filter after** (More compatible)
```sql
WITH all_rows AS (
  SELECT * FROM table LIMIT {annotation.batch_size}
),
batch_results AS (
  SELECT semantic_batch_matches(...) FROM all_rows
)
SELECT * FROM all_rows WHERE batch_results[id] = true
```

**Recommended:** Start with Option A (simpler), add Option B if needed.

---

## RISKS & MITIGATIONS

### Risk 1: Row Order Changes

**Problem:** Parallel execution may return results in different order

**Mitigation:**
- Store original row number in batch
- Sort by row number after batch execution
- Add stable ORDER BY to final SELECT
- Test extensively for order preservation

**Code Pattern:**
```python
# From rvbbit_map_parallel_exec line 726
results[index] = enriched_row  # Index preserves order
```

### Risk 2: Cache Invalidation

**Problem:** Batch cache vs individual row cache may conflict

**Mitigation:**
- Use separate cache namespace: `_batch_cache`
- Cache key includes: `md5(cascade_id|criteria|row_ids_sorted|max_workers)`
- Don't mix batch and individual caches

### Risk 3: Thread Safety

**Problem:** DuckDB connections not thread-safe

**Mitigation:**
- Each thread gets its own DuckDB connection (if needed)
- Or: Don't use DuckDB within parallel workers (just call cascades)
- Pattern already proven in rvbbit_map_parallel_exec (line 688):
  - `result_json = rvbbit_cascade_udf_impl(...)` - cascade calls don't touch DuckDB

### Risk 4: Memory Exhaustion

**Problem:** Collecting 1M rows in memory for batching

**Mitigation:**
- Enforce `batch_size` limit (default 100, max 1000)
- Warn if LIMIT > batch_size
- Process in chunks if needed
- Add memory monitoring

### Risk 5: Results Don't Match Sequential

**Problem:** Parallel and sequential produce different results

**Mitigation:**
- Extensive test suite comparing outputs
- Same cache, same inputs should get same results
- Run side-by-side for initial rollout
- Feature flag to disable if issues

---

## PERFORMANCE ESTIMATES

### Scenario 1: Simple WHERE with MEANS

```sql
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'eco-friendly' LIMIT 1000
```

**Current (sequential):**
- 1000 rows × 2s per LLM call = 2000s (33 min)
- Cost: 1000 × $0.0001 = $0.10

**With parallel:**
- 1000 rows ÷ 5 workers = 200 calls in parallel
- 200 calls × 2s = 400s (6.6 min)
- Cost: Same ($0.10)
- **Speedup: 5x** ⚡

### Scenario 2: Multiple Operators

```sql
-- @ parallel: 10
SELECT
  description MEANS 'eco' as eco,
  description EXTRACTS 'price' as price,
  description ASK 'urgency 1-10' as urgency
FROM products LIMIT 500
```

**Current:**
- 500 rows × 3 operators × 2s = 3000s (50 min)
- Cost: 1500 × $0.0001 = $0.15

**With parallel (if batching multiple operators):**
- 500 rows × 3 operators = 1500 calls
- 1500 ÷ 10 workers = 150 parallel batches
- 150 × 2s = 300s (5 min)
- **Speedup: 10x** ⚡

### Scenario 3: Aggregate with Map-Reduce

```sql
-- @ parallel: 8
SELECT state, SUMMARIZE(observed) as summary
FROM bigfoot
GROUP BY state
HAVING COUNT(*) > 100
```

**Current:**
- Each group serializes all texts → single LLM call
- 50 states × 3s per call = 150s

**With parallel map-reduce:**
- Each group's texts split into chunks
- Chunks processed in parallel
- Reduced to final summary
- 50 states × 1s (parallel chunks) = 50s
- **Speedup: 3x** ⚡

---

## PROPOSED ANNOTATION SYNTAX (Final Recommendation)

### Basic Usage

```sql
-- @ parallel: 5
-- Enable parallel execution with 5 workers
```

### With Configuration

```sql
-- @ parallel: 10
-- @ batch_size: 100
-- Use 10 workers, collect up to 100 rows per batch
```

### Combined with Model Hints

```sql
-- @ use a fast and cheap model
-- @ parallel: 8
-- @ threshold: 0.7
-- All annotations apply to next semantic operator
```

### Query-Wide (Future)

```sql
-- @@ parallel: 10
-- Note: Double @@ for query-wide settings
SELECT
  col1 MEANS 'x',    -- Parallel (inherited)
  col2 EXTRACTS 'y'  -- Parallel (inherited)
FROM table
```

---

## IMPLEMENTATION ROADMAP

### Milestone 1: Proof of Concept (Week 1-2)

**Goal:** Get parallel MEANS operator working

**Deliverables:**
- [ ] Extend SemanticAnnotation with `parallel` field
- [ ] Update _parse_annotations() to handle `parallel: N`
- [ ] Implement semantic_batch_matches() UDF
- [ ] Simple query transformation for basic WHERE MEANS
- [ ] Unit tests

**Success Criteria:**
```sql
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'eco' LIMIT 100
-- Executes in parallel, returns same results as sequential
```

### Milestone 2: More Operators (Week 3-4)

**Deliverables:**
- [ ] semantic_batch_score() for ABOUT
- [ ] semantic_batch_extract() for EXTRACTS
- [ ] semantic_batch_ask() for ASK
- [ ] semantic_batch_condense() for CONDENSE
- [ ] Integration tests

### Milestone 3: Complex Queries (Week 5-6)

**Deliverables:**
- [ ] Multiple operators per query
- [ ] Complex WHERE clauses (AND/OR)
- [ ] Query-scope annotations
- [ ] Performance benchmarks

### Milestone 4: Polish & Ship (Week 7-8)

**Deliverables:**
- [ ] Documentation (user guide + examples)
- [ ] Performance tuning
- [ ] Error messages and debugging
- [ ] Feature flag control

---

## COMPARISON TO ALTERNATIVES

| Approach | Complexity | Speedup | Risk | Transparency |
|----------|-----------|---------|------|-------------|
| **Query-Level Batching (Recommended)** | Medium | 3-5x | Medium | High |
| Window Functions | Low | None | Low | High |
| Stateful UDF | High | 5-10x | Very High | Low |
| User-Driven Batching | Low | 3-5x | Low | Low |

**Winner:** Query-Level Batching (Option A) - Best balance of all factors

---

## QUESTIONS TO RESOLVE

Before implementation, discuss:

1. **Annotation Scope:** Per-operator or query-wide default?
2. **Default Batch Size:** 100 rows? 1000 rows? User configurable?
3. **Auto-Parallel Threshold:** Should `-- @ parallel` without number default to CPU count?
4. **Backward Compatibility:** Feature flag enabled by default or opt-in?
5. **Operator Priority:** Which operators to parallelize first? (MEANS, EXTRACTS, ASK?)
6. **Error Handling:** If 1 row fails in batch, fail whole batch or partial results?
7. **Caching Strategy:** Batch-level cache or row-level cache or both?

---

## ARCHITECTURAL INSIGHT

**Key Realization:** You already have all the pieces!

```
✅ ThreadPoolExecutor pattern: rvbbit_map_parallel_exec (line 643)
✅ Annotation parsing: _parse_annotations() (line 128)
✅ Query transformation: _rewrite_semantic_operators() (line 246)
✅ Order preservation: results[index] pattern (line 726)
✅ Cache infrastructure: _cache_get/_cache_set (line 50)
```

**Just needs:**
- Glue code to connect them
- New batch UDFs (copy existing pattern)
- Query transformation logic (extend existing rewriter)

**Est. Implementation:** 1150 lines spread across 6-8 weeks

---

## RECOMMENDATION

**Proceed with implementation?**

**Suggested approach:**
1. **MVP:** Start with MEANS operator + simple WHERE clauses
2. **Validate:** Ensure results match sequential exactly
3. **Benchmark:** Measure actual speedup
4. **Expand:** Add more operators if MVP succeeds
5. **Ship:** Roll out with feature flag, gather user feedback

**Expected ROI:**
- Cost: 6-8 weeks dev time
- Benefit: 3-5x speedup for semantic queries (MASSIVE for production users)
- Risk: Medium (well-contained, feature-flagged)

---

**Ready to proceed with implementation, or do you want to discuss specific design choices first?**
