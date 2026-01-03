# Parallel Execution Still Sequential - Debug Analysis

**Issue:** Query splits correctly into UNION ALL branches, but execution appears sequential.

**User Report:**
```sql
-- @ parallel: 5
SELECT id, text ALIGNS 'SQL is good for AI' as score2
FROM (select * from tweets.tweets limit 10);
```

**Status:**
- ✅ Query splits into 5 UNION ALL branches
- ✅ Uses `hash(id) % 5` (type-safe)
- ✅ Operators rewrite correctly
- ❌ But execution is still sequential (based on user observation)

---

## Hypothesis: Registry Locks Serialize Execution

### Discovery

**File:** `rvbbit/semantic_sql/registry.py`

**Lines 24, 29:**
```python
_registry_lock = Lock()
_cache_lock = Lock()
```

**Lines 275-278:**
```python
def get_cached_result(name: str, args: dict):
    # ...
    with _cache_lock:  # ← GLOBAL LOCK!
        if key in _result_cache:
            return True, _result_cache[key]
```

**Lines 288-289:**
```python
def set_cached_result(name: str, args: dict, result: Any):
    # ...
    with _cache_lock:  # ← GLOBAL LOCK!
        _result_cache[key] = result
```

### The Problem

**Each cascade execution hits these locks:**

```
Thread 1 (Branch 0):
  call semantic_aligns() → execute_cascade_udf()
    → get_cached_result() → acquires _cache_lock ⏸️
    → Cache miss
    → releases _cache_lock ✓
    → _run_cascade_sync() → RVBBITRunner.run() (2 seconds) ⏱️
    → set_cached_result() → acquires _cache_lock ⏸️
    → Store result
    → releases _cache_lock ✓

Thread 2 (Branch 1):
  call semantic_aligns() → execute_cascade_udf()
    → get_cached_result() → WAITS for _cache_lock if Thread 1 holds it ⏸️
    → ...
```

**Impact:**
- Cache locks are brief (microseconds for dict lookup)
- But if DuckDB starts all branches quickly, they might queue at the lock
- Main bottleneck is `_run_cascade_sync()` which runs outside the lock
- **Locks shouldn't block parallel execution significantly**

---

## More Likely: DuckDB Parallelization Conditions

### Hypothesis: DuckDB Only Parallelizes Simple UNION ALL

DuckDB might not parallelize UNION ALL when:
1. ❌ Branches contain UDFs (unpredictable execution time)
2. ❌ Branches are "too simple" (overhead > benefit)
3. ❌ Connection is in a special mode (transaction, etc.)
4. ❌ Query optimizer decides sequential is better

### Test This

**Our original test** (which showed parallelism):
```python
# Simple UDF with sleep(0.05)
SELECT slow_udf(id) FROM test
→ Saw 3 threads used
```

**But that was a different query structure!** We didn't test:
```python
# UNION ALL with UDFs
(SELECT slow_udf(id) FROM test WHERE id % 3 = 0)
UNION ALL
(SELECT slow_udf(id) FROM test WHERE id % 3 = 1)
UNION ALL
(SELECT slow_udf(id) FROM test WHERE id % 3 = 2)
```

**We need to retest with this exact structure!**

---

## Possible Causes (Ordered by Likelihood)

### 1. DuckDB Doesn't Parallelize UDF-Heavy UNION ALL (Most Likely)

**Test:**
```python
# Test UNION ALL with expensive UDFs
def slow_udf(x):
    time.sleep(0.5)
    return x

# Query:
(SELECT slow_udf(id) FROM test WHERE hash(id) % 3 = 0)
UNION ALL
(SELECT slow_udf(id) FROM test WHERE hash(id) % 3 = 1)
UNION ALL
(SELECT slow_udf(id) FROM test WHERE hash(id) % 3 = 2)

# If sequential: ~9s (6 rows × 3 branches × 0.5s)
# If parallel: ~1.5s (3 branches × 2 rows × 0.5s)
```

**If this is sequential:** DuckDB doesn't parallelize UDF-heavy UNION ALL

### 2. Cache Hits (Medium Likelihood)

If all results are already cached, execution appears instant (and sequential doesn't matter).

**Test:** Clear cache before query
```sql
-- Clear cache somehow, then run parallel query
```

### 3. Small Dataset (Medium Likelihood)

With only 10 rows, parallel overhead might dominate:
- Thread spawn: ~10ms × 5 = 50ms
- Lock contention: ~5ms
- Result merging: ~10ms
- Total overhead: ~65ms

If each LLM call is 2s:
- Sequential: 10 × 2s = 20s
- Parallel (5 workers): (10 / 5) × 2s + 0.065s = 4.065s

**Still 5x speedup, but user might not notice on such small dataset.**

### 4. Postgres Server Connection Locking (Low Likelihood)

**File:** `rvbbit/server/postgres_server.py`

Each client connection has a `db_lock`:
```python
self.db_lock = threading.Lock()  # Line ~90
```

Queries acquire this lock:
```python
with self.db_lock:  # Line ~1300
    result = self.duckdb_conn.execute(query)
```

**But:** This lock is per-CONNECTION, not global. Shouldn't affect UNION ALL parallelism within a single query.

---

## Debugging Steps for User

### Step 1: Verify Query Splits

```sql
-- Check what SQL actually executes
SELECT id, text ALIGNS 'x' as score
FROM tweets
LIMIT 10;

-- Add logging in postgres_server.py to see rewritten query
```

### Step 2: Monitor CPU Usage

```bash
# Terminal 1: Start server
rvbbit serve sql --port 15432

# Terminal 2: Monitor CPU
htop  # or: top -H

# Terminal 3: Run query
psql postgresql://localhost:15432/default
> -- @ parallel: 8
> SELECT id, text ALIGNS 'x' FROM tweets LIMIT 100;

# Watch htop:
# Sequential: 1 CPU core at 100%, others idle
# Parallel: Multiple cores active
```

### Step 3: Test with Artificial Delay

```sql
-- Create simple test to isolate issue
CREATE TABLE test (id INT, text VARCHAR);
INSERT INTO test SELECT i, 'text' || i FROM range(20);

-- Test without LLM (just check splitting)
-- @ parallel: 5
SELECT id FROM test WHERE id < 20 LIMIT 20;
```

### Step 4: Check Logs

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Look for:
- "Splitting query into N UNION ALL branches"
- Thread names in logs
- Lock acquisition messages

---

## Quick Diagnostic Query

**Run this to check if parallelism is working:**

```sql
-- Check unified_logs for timing
SELECT
    session_id,
    cascade_id,
    timestamp,
    duration_ms,
    model
FROM rvbbit.unified_logs
WHERE session_id LIKE '%semantic_aligns%'
ORDER BY timestamp
LIMIT 20;
```

**If parallel:**
- Multiple sessions with overlapping timestamps
- Different session_ids start within milliseconds

**If sequential:**
- Sessions start one after another (no overlap)
- Clear time gaps between starts

---

## Likely Root Cause & Next Steps

**My suspicion:** DuckDB doesn't actually parallelize UNION ALL when branches contain expensive UDFs.

**Why our test showed parallelism:**
- Test had simple sleep(), not complex cascade execution
- Test query structure was different
- Small dataset, overhead dominates

**What to do:**

1. **Confirm with htop/top** - Watch CPU cores during query
2. **Test with 100+ rows** - Small datasets hide parallelism
3. **Check DuckDB version/config** - Might need specific settings
4. **Alternative: AsyncIO approach** - If UNION doesn't parallelize, use async cascade execution

**If UNION ALL doesn't parallelize UDFs:**
- Fall back to batching approach (my original proposal)
- OR: Implement async parallel execution in cascade executor
- OR: Document limitation, use for simple cases only

---

## Next Debug Session

**I need more info to diagnose:**
1. How are you measuring "sequential"? (timing? CPU monitor? logs?)
2. What's the actual execution time? (10 rows should be ~4s parallel vs ~20s sequential)
3. Are results cached? (second run might be instant)
4. Can you run htop while query executes?

**Once we know what's actually happening, I can fix it!**
