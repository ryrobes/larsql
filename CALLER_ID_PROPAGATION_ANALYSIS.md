# Caller ID Propagation Issue - Analysis & Solution

**Date:** 2026-01-02
**Issue:** Meta cascades don't inherit caller_id from parent sessions
**Impact:** Cost rollup breaks for SQL queries that spawn meta cascades
**Status:** ✅ Root cause identified, solution designed

## The Problem

### Current Behavior

When a SQL query runs semantic operators, the call chain looks like:

```
SQL Query (caller_id: sql-fox-abc123)
  └─> semantic_matches() cascade
       ├─> evaluate cell (✅ has caller_id)
       └─> Meta Cascade: assess_training_confidence
            ├─> assess cell (❌ NO caller_id!)
            └─> Logs recorded WITHOUT caller_id
```

**Result:** The meta cascade's costs can't be rolled up to the original SQL query.

### What Gets Lost

**Meta cascades that lose caller_id:**
1. `assess_training_confidence` - Scores assistant message quality for training
2. `analyze_context_relevance` - Scores which context messages were useful
3. Any future meta-analysis cascades

**Impact on observability:**
- ✅ Can track: SQL query → semantic_matches → LLM call
- ❌ Can't track: SQL query → semantic_matches → assess_confidence → LLM call
- Result: Cost rollup incomplete, analytics incomplete

## Root Cause Analysis

### Issue #1: _fetch_session_data() Doesn't Select caller_id

**Location:** `analytics_worker.py:358-367`

```python
session_query = f"""
    SELECT
        cascade_id,
        input_data,
        genus_hash,
        created_at
    FROM cascade_sessions
    WHERE session_id = '{session_id}'
"""
```

**Problem:** The table HAS `caller_id` and `invocation_metadata_json` columns (see `create_cascade_sessions_table.sql:13-14`), but the query doesn't SELECT them!

**Return value (line 377-395):**
```python
return {
    'session_id': session_id,
    'cascade_id': session_info['cascade_id'],
    'genus_hash': session_info.get('genus_hash', ''),
    'created_at': session_info['created_at'],
    'input_data': session_info.get('input_data', ''),
    # ... metrics ...
    # ❌ NO caller_id!
    # ❌ NO invocation_metadata!
}
```

### Issue #2: Meta Cascades Don't Pass caller_id to RVBBITRunner

**Location 1:** `confidence_worker.py:123-126`

```python
runner = RVBBITRunner(
    'cascades/semantic_sql/assess_confidence.cascade.yaml',
    session_id=f"confidence_assess_{uuid.uuid4().hex[:8]}"
    # ❌ NO caller_id parameter!
)
```

**Location 2:** `analytics_worker.py:1389-1393`

```python
runner = RVBBITRunner(
    config_path='traits/analyze_context_relevance.yaml',
    session_id=analysis_session_id,
    depth=1
    # ❌ NO caller_id parameter!
)
```

**RVBBITRunner signature (runner.py:151-154):**
```python
def __init__(self, config_path: str | dict, session_id: str = "default",
             overrides: dict = None, depth: int = 0, parent_trace: TraceNode = None,
             hooks: RVBBITHooks = None, candidate_index: int = None,
             parent_session_id: str = None,
             caller_id: str = None,  # ✅ Parameter exists!
             invocation_metadata: dict = None):  # ✅ Parameter exists!
```

The parameter exists but is never passed!

## The Solution

### Fix #1: Retrieve caller_id from Parent Session

**File:** `analytics_worker.py:358-367`

**Change:**
```python
# BEFORE:
session_query = f"""
    SELECT
        cascade_id,
        input_data,
        genus_hash,
        created_at
    FROM cascade_sessions
    WHERE session_id = '{session_id}'
"""

# AFTER:
session_query = f"""
    SELECT
        cascade_id,
        input_data,
        genus_hash,
        created_at,
        caller_id,                    -- ✅ ADD THIS
        invocation_metadata_json       -- ✅ ADD THIS
    FROM cascade_sessions
    WHERE session_id = '{session_id}'
"""
```

**And update return dict (line 377-395):**
```python
return {
    # ... existing fields ...
    'caller_id': session_info.get('caller_id', ''),              # ✅ ADD THIS
    'invocation_metadata': session_info.get('invocation_metadata_json', '{}'),  # ✅ ADD THIS
}
```

### Fix #2: Pass caller_id to assess_training_confidence

**File:** `confidence_worker.py:123-126`

**Change:**
```python
# BEFORE:
runner = RVBBITRunner(
    'cascades/semantic_sql/assess_confidence.cascade.yaml',
    session_id=f"confidence_assess_{uuid.uuid4().hex[:8]}"
)

# AFTER:
runner = RVBBITRunner(
    'cascades/semantic_sql/assess_confidence.cascade.yaml',
    session_id=f"confidence_assess_{uuid.uuid4().hex[:8]}",
    caller_id=parent_caller_id,           # ✅ ADD THIS
    invocation_metadata=parent_metadata    # ✅ ADD THIS
)
```

**Where to get parent_caller_id from:**
- It's in `session_id` parameter (the session being assessed)
- Need to look it up from database before spawning runner
- Add before line 122:
  ```python
  # Look up parent caller_id from session being assessed
  parent_session_data = _get_session_caller_context(session_id, db)
  parent_caller_id = parent_session_data.get('caller_id') if parent_session_data else None
  parent_metadata = parent_session_data.get('invocation_metadata') if parent_session_data else None
  ```

### Fix #3: Pass caller_id to analyze_context_relevance

**File:** `analytics_worker.py:1389-1393`

**Change:**
```python
# BEFORE:
runner = RVBBITRunner(
    config_path='traits/analyze_context_relevance.yaml',
    session_id=analysis_session_id,
    depth=1
)

# AFTER:
runner = RVBBITRunner(
    config_path='traits/analyze_context_relevance.yaml',
    session_id=analysis_session_id,
    depth=1,
    caller_id=session_caller_id,          # ✅ ADD THIS
    invocation_metadata=session_metadata   # ✅ ADD THIS
)
```

**Where to get it from:**
- The function already receives `session_id` parameter (line 1292)
- `session_id` is the PARENT session being analyzed
- Need to look it up from database
- Add at top of `_analyze_context_relevance()`:
  ```python
  # Look up parent session's caller context
  parent_data = _get_session_caller_context(session_id, db)
  session_caller_id = parent_data.get('caller_id') if parent_data else None
  session_metadata = parent_data.get('invocation_metadata') if parent_data else None
  ```

### Fix #4: Helper Function for Caller Context Lookup

**File:** `analytics_worker.py` (add new function)

**Add this helper function:**
```python
def _get_session_caller_context(session_id: str, db) -> Optional[Dict]:
    """
    Retrieve caller_id and invocation_metadata from a session.

    Args:
        session_id: Session to look up
        db: Database connection

    Returns:
        Dict with 'caller_id' and 'invocation_metadata', or None if not found
    """
    try:
        query = f"""
            SELECT caller_id, invocation_metadata_json
            FROM cascade_sessions
            WHERE session_id = '{session_id}'
            LIMIT 1
        """
        result = db.query(query)

        if not result or not result[0]:
            return None

        return {
            'caller_id': result[0].get('caller_id', ''),
            'invocation_metadata': result[0].get('invocation_metadata_json', '{}')
        }

    except Exception as e:
        logger.warning(f"Could not fetch caller context for {session_id}: {e}")
        return None
```

## Implementation Checklist

### Changes Required

- [ ] **analytics_worker.py**
  - [ ] Add `_get_session_caller_context()` helper function
  - [ ] Update `_fetch_session_data()` to SELECT caller_id + invocation_metadata_json
  - [ ] Update return dict to include caller_id and invocation_metadata
  - [ ] Update `_analyze_context_relevance()` to look up parent caller context
  - [ ] Pass caller_id + invocation_metadata to analyze_context_relevance RVBBITRunner

- [ ] **confidence_worker.py**
  - [ ] Update `assess_training_confidence()` to look up parent caller context
  - [ ] Pass caller_id + invocation_metadata to assess_confidence RVBBITRunner

### Testing Strategy

**Before fix:**
```sql
-- Query ClickHouse
SELECT caller_id, session_id, cascade_id, phase_name
FROM all_data
WHERE caller_id LIKE 'sql-%'
ORDER BY timestamp;
```

**Expected (broken):**
```
caller_id         | session_id                     | cascade_id
──────────────────|────────────────────────────────|─────────────────────────
sql-fox-abc123    | pg_client_xyz_001             | semantic_matches
sql-fox-abc123    | pg_client_xyz_001_eval        | semantic_matches
(empty)           | confidence_assess_xyz789      | assess_training_confidence  ❌ Lost!
(empty)           | pg_client_xyz_001_relevance_x | analyze_context_relevance   ❌ Lost!
```

**After fix:**
```
caller_id         | session_id                     | cascade_id
──────────────────|────────────────────────────────|─────────────────────────
sql-fox-abc123    | pg_client_xyz_001             | semantic_matches
sql-fox-abc123    | pg_client_xyz_001_eval        | semantic_matches
sql-fox-abc123    | confidence_assess_xyz789      | assess_training_confidence  ✅ Inherited!
sql-fox-abc123    | pg_client_xyz_001_relevance_x | analyze_context_relevance   ✅ Inherited!
```

**Cost rollup query (after fix should include ALL cascades):**
```sql
SELECT
    caller_id,
    COUNT(DISTINCT session_id) as cascades_spawned,
    SUM(cost) as total_cost,
    SUM(tokens_in + tokens_out) as total_tokens
FROM all_data
WHERE caller_id = 'sql-fox-abc123'
GROUP BY caller_id;
```

Should now include costs from `assess_training_confidence` and `analyze_context_relevance`!

## Why This Matters

### Observability & Cost Tracking

**Scenario:** User runs complex semantic SQL query:

```sql
SELECT
    state,
    title MEANS 'visual contact' as has_contact,
    SUMMARIZE(observed) as summary,
    THEMES(title, 3) as topics
FROM bigfoot
WHERE title MEANS 'visual contact'
GROUP BY state
LIMIT 10;
```

**This spawns:**
1. Main query execution (caller_id: sql-clever-fox-abc123)
2. `semantic_matches` cascade (2x for WHERE and SELECT)
3. `semantic_summarize` cascade (aggregate)
4. `semantic_themes` cascade (aggregate)
5. **Meta:** `assess_training_confidence` (for each cascade above) ← LOST!
6. **Meta:** `analyze_context_relevance` (for each cell) ← LOST!

**Without fix:**
- User sees cost rollup: $0.05
- Actual cost (including meta): $0.08
- Missing: $0.03 from meta cascades ❌

**With fix:**
- User sees complete cost rollup: $0.08
- Perfect attribution to original SQL query ✅

### Analytics & Debugging

**Query:** "What's the total cost of all semantic SQL queries today?"

```sql
SELECT
    caller_id,
    extractAll(JSONExtractString(invocation_metadata_json, 'sql.query'), '\\w+') as query_keywords,
    COUNT(DISTINCT session_id) as total_cascades,
    SUM(cost) as total_cost
FROM all_data
WHERE caller_id LIKE 'sql-%'
  AND toDate(timestamp) = today()
GROUP BY caller_id, invocation_metadata_json
ORDER BY total_cost DESC;
```

**Without fix:** Undercounts by 20-40% (meta cascades missing)
**With fix:** Accurate complete cost tracking ✅

## Edge Cases Handled

### 1. Background Threads

**Problem:** `assess_training_confidence` runs in background thread (analytics_worker.py:273)

```python
thread = threading.Thread(target=run_confidence_assessment, daemon=True)
thread.start()
```

**Solution:** caller_id is passed as parameter to RVBBITRunner, stored in Echo, and propagated via contextvars + thread-local + global registry (all 3 layers).

### 2. Nested Meta Cascades

**Scenario:** What if meta cascades spawn their own sub-cascades?

```
SQL Query (caller_id: sql-abc)
  └─> semantic_ask
       └─> apply_prompt cell (uses manifest/Quartermaster)
            └─> Meta: assess_training_confidence
                 └─> assess cell
                      └─> Sub-meta: another analysis cascade?
```

**Solution:** Once caller_id is passed to the first meta cascade, it propagates automatically to all descendants (RVBBITRunner already handles this via Echo).

### 3. Multiple Parallel Meta Cascades

**Scenario:** One SQL query → 10 semantic operators → 10 meta cascades spawned in parallel

**Solution:** Each gets the same caller_id (from parent session lookup), all log to same caller_id, cost rolls up correctly.

### 4. Session Not Found

**Scenario:** Meta cascade tries to look up caller_id but parent session doesn't exist in cascade_sessions

**Solution:** Helper function returns None, meta cascade runs with caller_id=None (same as current behavior, no regression).

## Performance Impact

**Additional database queries:**
- 1x SELECT per meta cascade spawn (2 columns, indexed by session_id)
- Negligible: ~1-2ms per meta cascade
- Already doing database queries in these code paths, one more is fine

**Memory impact:**
- Adding 2 fields to session_data dict: ~100 bytes
- Negligible

## Migration Required?

**No migration needed!** ✅

- `cascade_sessions` already has `caller_id` column (from `add_caller_tracking_columns.sql`)
- Existing rows have `caller_id = ''` (default)
- After fix, new sessions will populate it correctly
- Historical sessions with `caller_id = ''` are fine (represents "no tracking")

## Testing Plan

### 1. Unit Test: Helper Function

```python
def test_get_session_caller_context():
    """Test caller context retrieval from session."""
    # Create session with caller_id
    db = get_db()
    db.insert_rows('cascade_sessions', [{
        'session_id': 'test_session_123',
        'caller_id': 'sql-test-fox-abc',
        'invocation_metadata_json': '{"origin": "sql"}',
        # ... other fields
    }])

    # Retrieve it
    context = _get_session_caller_context('test_session_123', db)

    assert context['caller_id'] == 'sql-test-fox-abc'
    assert 'origin' in context['invocation_metadata']
```

### 2. Integration Test: Meta Cascade Inheritance

```python
def test_meta_cascade_inherits_caller_id():
    """Test that assess_training_confidence inherits caller_id."""
    import os
    os.environ['OPENROUTER_API_KEY'] = 'test_key'

    # 1. Run a semantic SQL query with known caller_id
    from rvbbit.caller_context import set_caller_context, build_sql_metadata
    from rvbbit.server.postgres_server import ClientConnection

    caller_id = 'sql-test-inheritance-123'
    metadata = build_sql_metadata(
        sql_query="SELECT * FROM t WHERE x MEANS 'test'",
        protocol='test',
        triggered_by='test'
    )

    set_caller_context(caller_id, metadata)

    # 2. Execute query (triggers semantic_matches cascade)
    # ... execution code ...

    # 3. Wait for analytics worker to spawn assess_training_confidence
    time.sleep(2)

    # 4. Check that meta cascade has same caller_id
    db = get_db()
    result = db.query(f"""
        SELECT DISTINCT caller_id, cascade_id
        FROM all_data
        WHERE caller_id = '{caller_id}'
    """)

    cascade_ids = [r['cascade_id'] for r in result]

    assert 'semantic_matches' in cascade_ids  # Parent
    assert 'assess_training_confidence' in cascade_ids  # Meta (should inherit!)
```

### 3. E2E Test: Cost Rollup Completeness

```sql
-- Run semantic SQL query
SELECT * FROM products WHERE description MEANS 'eco-friendly' LIMIT 10;

-- Wait for meta cascades to complete
-- (in real test, wait for analytics worker)

-- Query cost rollup
SELECT
    caller_id,
    cascade_id,
    SUM(cost) as cost
FROM all_data
WHERE caller_id LIKE 'sql-%'
GROUP BY caller_id, cascade_id
ORDER BY caller_id, cost DESC;

-- Expected results should include:
-- - semantic_matches (main cascade)
-- - assess_training_confidence (meta cascade)
```

## Implementation Priority

**High Priority** - Impacts core observability

**Affected Users:**
- Anyone using Semantic SQL with training enabled
- Anyone analyzing cost by SQL query
- Anyone debugging cascade chains

**Benefits:**
- ✅ Complete cost rollup (no hidden costs)
- ✅ Full debugging visibility (trace meta cascades)
- ✅ Accurate analytics (don't undercount resources)
- ✅ Better training system (know which SQL queries produced training data)

## Additional Improvements (Future)

### 1. Caller ID Validation

Add validation to ensure caller_id is always propagated:

```python
# In RVBBITRunner.__init__
if depth > 0 and not caller_id:
    logger.warning(f"Sub-cascade {config_path} created without caller_id! "
                   f"This may break cost rollup. session_id={session_id}")
```

### 2. Caller ID Audit Query

Create a view to find orphaned sessions:

```sql
CREATE VIEW orphaned_meta_cascades AS
SELECT
    session_id,
    cascade_id,
    parent_session_id,
    created_at
FROM cascade_sessions
WHERE parent_session_id != ''  -- Is a sub-cascade
  AND caller_id = ''            -- But has no caller_id
  AND cascade_id IN ('assess_training_confidence', 'analyze_context_relevance');
```

### 3. Automatic Backfill

For existing sessions, backfill caller_id from parent:

```sql
-- Update meta cascades to inherit parent's caller_id
UPDATE cascade_sessions cs1
SET caller_id = (
    SELECT caller_id
    FROM cascade_sessions cs2
    WHERE cs2.session_id = cs1.parent_session_id
    LIMIT 1
)
WHERE cs1.caller_id = ''
  AND cs1.parent_session_id != ''
  AND cs1.cascade_id IN ('assess_training_confidence', 'analyze_context_relevance');
```

## Summary

### Root Cause

Meta cascades (`assess_training_confidence`, `analyze_context_relevance`) don't receive caller_id from parent sessions because:
1. Session data query doesn't retrieve it from database
2. RVBBITRunner invocations don't pass it as parameter

### Solution

Two simple changes:
1. **SELECT** `caller_id` and `invocation_metadata_json` when fetching session data
2. **Pass** them to RVBBITRunner when spawning meta cascades

### Impact

- ✅ Complete cost rollup for SQL queries
- ✅ Full cascade chain visibility
- ✅ Accurate analytics
- ✅ Better training data attribution

### Effort

- 4 locations to change
- ~20 lines of code
- 1 helper function to add
- No migrations needed
- Low risk (graceful degradation if lookup fails)

---

**Ready to implement when you are!** The fix is straightforward and high-value. 🚀
