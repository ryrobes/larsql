# Why Batching is Necessary for Parallel Semantic SQL

**Question:** Can we just run multiple UDF calls in parallel without batching/indexing/reassembling?

**Answer:** ❌ No - DuckDB's execution model prevents this

**Tested:** Confirmed with actual DuckDB code (see below)

## The Fundamental Constraint

### DuckDB's UDF Execution Model

**DuckDB calls UDFs sequentially and BLOCKS on each call:**

```python
# Inside DuckDB's query execution (conceptual):
for row in table:
    result = udf_function(row.column)  # ← BLOCKS HERE
    # Won't call udf_function for next row until this returns!
    if result:
        include_in_results(row)
```

**This means:**
- Row 1: Call matches(), wait for return, check result
- Row 2: Call matches(), wait for return, check result
- Row 3: Call matches(), wait for return, check result
- **All sequential, no overlap**

### Test Proof

I ran an actual test:

```python
# UDF that submits work to ThreadPoolExecutor and waits
def matches_parallel(criteria, text):
    future = executor.submit(do_work, criteria, text)
    return future.result()  # Block waiting

# Query: 10 rows, each should take 0.1s
SELECT COUNT(*) FROM test WHERE matches_parallel('test', text)

# Results:
# Expected if parallel (5 workers): 0.20s
# Expected if sequential: 1.00s
# ACTUAL: 1.16s ❌ SEQUENTIAL!
```

**Even with ThreadPoolExecutor INSIDE the UDF, it's still sequential** because DuckDB blocks on each UDF return.

---

## Why Your Idea Makes Sense (But Can't Work)

### What You're Thinking (I think)

```
Just make each UDF call spawn a thread:

Row 1: matches() → spawn thread → wait → return ✓
Row 2: matches() → spawn thread → wait → return ✓
Row 3: matches() → spawn thread → wait → return ✓
All threads running concurrently!
```

**This would be great! But...**

### The Problem

DuckDB's execution timeline:

```
Time 0.0s: Call matches(row1) → spawns thread T1 → blocks waiting
Time 0.1s: T1 completes, matches(row1) returns
Time 0.1s: Call matches(row2) → spawns thread T2 → blocks waiting
Time 0.2s: T2 completes, matches(row2) returns
Time 0.2s: Call matches(row3) → spawns thread T3 → blocks waiting
...

Total time: Still sequential! ❌
```

**DuckDB doesn't call the next UDF until the previous one returns.** The thread pool doesn't help because there's no concurrency - only one UDF call is active at a time.

---

## The Only Way: Collect Rows First

To get parallel execution, we MUST collect rows before they reach the UDF:

### Approach: Query-Level Collection

```sql
-- Original query (what user writes):
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'eco' LIMIT 100

-- What we need (conceptual):
step1 = collect_all_rows()  # Get all 100 rows
step2 = process_in_parallel(step1, workers=5)  # Process 5 at a time
step3 = filter_results(step2)  # Return only matching rows
```

**In SQL, this becomes:**

```sql
WITH collected AS (
  SELECT id, description FROM products LIMIT 100
)
SELECT * FROM products
WHERE id IN (
  SELECT id FROM semantic_batch_matches('eco', collected, 5)
  WHERE result = true
)
```

---

## But Wait... Is There A Simpler Way?

### Option: Cooperative Batching (Stateful UDF)

**What if the UDF collects rows in a queue?**

```python
_global_queue = {}  # Queue per (operator, criteria)
_global_results = {}

def matches(criteria, text):
    queue_key = f"matches:{criteria}"

    # Add to queue
    if queue_key not in _global_queue:
        _global_queue[queue_key] = []
    _global_queue[queue_key].append(text)

    # If queue full, process batch in parallel
    if len(_global_queue[queue_key]) >= BATCH_SIZE:
        texts = _global_queue[queue_key]
        _global_queue[queue_key] = []

        # Process in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(cascade_call, criteria, t) for t in texts]
            for i, future in enumerate(futures):
                _global_results[f"{queue_key}:{texts[i]}"] = future.result()

    # Return result if available
    result_key = f"{queue_key}:{text}"
    if result_key in _global_results:
        return _global_results[result_key]

    # Not processed yet - fallback to sequential
    return cascade_call_sync(criteria, text)
```

**Advantages:**
- ✅ No query transformation needed
- ✅ Transparent to user
- ✅ Simple annotation: `-- @ parallel: 5`

**Fatal Flaws:**
1. ❌ **First N-1 rows block forever** (waiting for queue to fill)
2. ❌ **Last partial batch never processes** (if total rows % BATCH_SIZE != 0)
3. ❌ **No flush mechanism** (when does queue process?)
4. ❌ **Race conditions** (multi-threaded state access)
5. ❌ **DuckDB might call UDFs out of order** (in subqueries, CTEs)
6. ❌ **Breaks with caching** (cache check happens before queue check)

**Verdict:** Too brittle and complex to be reliable.

---

## The Simplest Viable Approach

### Option: Parallel Execution at Registry Level (NEW IDEA!)

What if we intercept at the **cascade execution** level, not the UDF level?

**Current flow:**
```
matches(criteria, text)
  ↓
execute_cascade_udf("semantic_matches", {text, criterion})
  ↓
_run_cascade_sync(cascade_path, session_id, inputs)
  ↓
RVBBITRunner.run()
```

**Modified flow with parallel annotation:**
```
-- @ parallel: 5
WHERE description MEANS 'eco'
  ↓
Rewriter detects parallel annotation
  ↓
Rewrites to: matches_parallel_5(criteria, text, __row_batch_id)
  ↓
matches_parallel_5():
  - Adds (text, __row_batch_id) to shared queue
  - If queue >= batch_size OR __row_batch_id indicates last row:
      Process queue in parallel via ThreadPoolExecutor
  - Return cached result for this text
```

**Still has problems:**
- How does UDF know it's the "last row"?
- Still requires row ID for result caching
- Still need queue flushing mechanism

---

## Why Batching/Transformation IS the Answer

After exploring all options, **query-level transformation is the only reliable approach** because:

1. ✅ **No state management** - Each batch is self-contained
2. ✅ **Clear semantics** - Query explicitly collects rows
3. ✅ **Order preservation** - Indexed results array
4. ✅ **Flush guaranteed** - All rows collected before processing
5. ✅ **Cache-friendly** - Batch cache is separate from row cache
6. ✅ **Proven pattern** - Your rvbbit_map_parallel_exec already works this way

**The transformation complexity is worth it** for reliability and performance.

---

## Simplified Transformation (Less Complex Than I Showed)

Here's a simpler version of the query transformation:

### User Query
```sql
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'eco-friendly' LIMIT 100
```

### Rewritten Query
```sql
SELECT p.*
FROM products p
WHERE id IN (
  SELECT json_extract(value, '$.id')::INT
  FROM read_json_auto([
    semantic_batch_matches(
      'eco-friendly',
      (SELECT json_group_array(json_object('id', id, 'text', description))
       FROM products LIMIT 100),
      5
    )
  ])
  WHERE json_extract(value, '$.result')::BOOLEAN = true
)
```

**Not as scary as my first example!** This is basically:
1. Collect rows as JSON array
2. Pass to batch UDF
3. Parse results
4. Filter with IN clause

---

## Alternative: What If We FORCE Parallel Execution?

### Crazy Idea: UNION ALL Hack

What if we split the query ourselves and UNION the results?

```sql
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'eco' LIMIT 100

-- Rewrite to (split into 5 subqueries):
(SELECT * FROM products WHERE id % 5 = 0 AND description MEANS 'eco' LIMIT 20)
UNION ALL
(SELECT * FROM products WHERE id % 5 = 1 AND description MEANS 'eco' LIMIT 20)
UNION ALL
(SELECT * FROM products WHERE id % 5 = 2 AND description MEANS 'eco' LIMIT 20)
UNION ALL
(SELECT * FROM products WHERE id % 5 = 3 AND description MEANS 'eco' LIMIT 20)
UNION ALL
(SELECT * FROM products WHERE id % 5 = 4 AND description MEANS 'eco' LIMIT 20)
```

**Would DuckDB parallelize the UNION branches?**

Let me test...

---

## Bottom Line

**Your question:** Can we skip batching and just run calls in parallel?

**Answer:** ❌ Not without query transformation

**Why:** DuckDB's execution model is fundamentally sequential for UDFs. It blocks on each return.

**The batching approach I proposed:**
- ✅ IS about running multiple cascade calls in parallel (ThreadPoolExecutor)
- ✅ Keeps cascade calls small (one per row)
- ✅ Just collects rows first so they CAN run in parallel

**The complexity is in:**
- Collecting rows at SQL level (query transformation)
- Not in the parallel execution itself (that's proven and works)

**Would it help if I showed a MUCH simpler transformation approach?** I can make the query rewriting less scary than my initial example.
