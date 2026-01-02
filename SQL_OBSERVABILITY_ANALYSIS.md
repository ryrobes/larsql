# SQL Trail Observability System - Comprehensive Analysis

**Document Version:** 1.0
**Analysis Date:** 2026-01-02
**System Component:** RVBBIT SQL Trail (Query-Level Analytics)

---

## Executive Summary

The RVBBIT SQL Trail observability system provides query-level analytics for SQL-driven LLM workflows where the unit of work is a SQL query (via `caller_id`), not individual LLM sessions. The system tracks SQL queries that invoke RVBBIT UDFs, fingerprinting queries for pattern analysis, aggregating costs from spawned LLM calls, and providing cache analytics.

**Critical Finding:** The system has a well-designed architecture with 90% complete implementation, but **6 critical gaps prevent full functionality**:

1. Missing `cascade_count` column in production schema
2. Cost aggregation function exists but is never called
3. Cascade path tracking has SQL escaping bug
4. LLM call counter function exists but is never invoked
5. In-memory cascade registry won't survive multi-worker deployments
6. Row input metrics never populated

**Impact:** Cache tracking, query fingerprinting, and basic logging work correctly. Cost attribution, cascade tracking, and pattern analysis are partially broken.

**Recommended Priority:** HIGH - System is customer-facing (PostgreSQL wire protocol server, Studio SQL Query IDE). Fixes are straightforward and low-risk.

---

## Architecture Overview

### Design Philosophy

The SQL Trail system addresses a fundamental difference between traditional cascades and SQL semantic queries:

**Traditional Cascades:**
- 1 cascade execution = 1 session
- 10-100 LLM calls per cascade
- Session-level cost attribution is sufficient

**SQL Semantic Queries:**
- 1 SQL query = 1,000+ LLM calls (batch UDF operations)
- Cache hit rate is critical for cost optimization
- Pattern analysis matters more than individual outliers
- Need query-level aggregation, not session-level

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ PostgreSQL Client (DBeaver, psql, Studio SQL IDE)              │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ postgres_server.py                                              │
│ - Generates caller_id (sql-<animal>-<uuid>)                     │
│ - Calls set_caller_context()                                    │
│ - Calls log_query_start() → sql_query_log                       │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ DuckDB Query Execution                                          │
│ - rvbbit_udf() calls per row                                    │
│ - rvbbit_cascade_udf() spawns cascades                          │
│ - Each call inherits caller_id from context                     │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ UDF Execution (sql_tools/udf.py, semantic_sql/registry.py)     │
│ - increment_cache_hit() / increment_cache_miss() ✓ WORKING      │
│ - register_cascade_execution() ✓ WORKING                        │
│ - Logs to unified_logs with caller_id ✓ WORKING                 │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ Query Completion (postgres_server.py:1078-1154)                │
│ - aggregate_query_costs() ✗ CALLED but returns empty {}         │
│ - get_cascade_paths() ✓ CALLED                                  │
│ - log_query_complete() ✗ PARTIAL (missing cascade_count col)    │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ ClickHouse Tables                                               │
│ - sql_query_log: Query metadata + aggregated metrics            │
│ - unified_logs: Individual LLM calls with caller_id FK          │
└─────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ Studio SQL Trail UI (/api/sql-trail/*)                          │
│ - Query list, patterns, cache analytics, time series            │
│ - Joins sql_query_log → unified_logs for spawned sessions       │
└─────────────────────────────────────────────────────────────────┘
```

### Key Tables

**sql_query_log** (lines 1130-1189 in `schema.py`):
```sql
CREATE TABLE sql_query_log (
    query_id UUID,
    caller_id String,
    query_raw String,
    query_fingerprint String,      -- MD5 of AST-normalized query
    query_template String,          -- Literals replaced with ?
    query_type LowCardinality,      -- 'rvbbit_udf', 'llm_aggregate', etc.
    udf_types Array(String),        -- Detected UDF function calls
    udf_count UInt16,
    cascade_paths Array(String),    -- ✗ MIGRATION NEVER ADDED THIS
    cascade_count UInt16,           -- ✗ MIGRATION NEVER ADDED THIS
    rows_input Int32,
    rows_output Int32,
    total_cost Float64,             -- ✗ NEVER POPULATED (aggregate_query_costs broken)
    cache_hits UInt32,              -- ✓ WORKING (atomic increment)
    cache_misses UInt32,            -- ✓ WORKING (atomic increment)
    llm_calls_count UInt32,         -- ✗ NEVER INCREMENTED
    ...
)
```

**unified_logs** (caller_id join column):
```sql
-- Lines 34-42 in schema.py
caller_id String DEFAULT '',
invocation_metadata_json String DEFAULT '{}',
is_sql_udf Bool DEFAULT false,
udf_type LowCardinality(Nullable(String)),
cache_hit Bool DEFAULT false,
input_hash Nullable(String),
```

### Query Fingerprinting

**Implementation:** `sql_trail.py:88-130`

Uses `sqlglot` to parse SQL and extract:
- **Fingerprint:** MD5 hash of AST-normalized query (literals replaced with `?`)
- **Template:** Parameterized SQL for pattern grouping
- **UDF Types:** List of RVBBIT UDFs detected in query

**Example:**
```sql
-- Original
SELECT rvbbit_udf('summarize this: ' || content) FROM docs WHERE id > 100

-- Fingerprint: MD5("SELECT rvbbit_udf(?) FROM docs WHERE id > ?")
-- Template: "SELECT rvbbit_udf(?) FROM docs WHERE id > ?"
-- UDF Types: ['rvbbit_udf']
-- Query Type: 'rvbbit_udf'
```

This enables grouping queries by pattern across different parameter values.

---

## Current State Analysis

### What Works ✓

#### 1. Cache Tracking (100% Working)
**Files:** `sql_trail.py:375-428`, UDF execution paths

```python
# Atomic increment on cache hit
def increment_cache_hit(caller_id):
    db.execute(f"""
        ALTER TABLE sql_query_log
        UPDATE cache_hits = cache_hits + 1
        WHERE caller_id = '{caller_id}'
    """)
```

- Called from: `semantic_sql/registry.py:398`, `sql_tools/udf.py`
- Uses ClickHouse atomic `UPDATE` (safe for concurrent increments)
- UI correctly displays cache hit rates

**Verification:** `/api/sql-trail/cache-stats` endpoint works correctly.

#### 2. Query Fingerprinting (100% Working)
**Files:** `sql_trail.py:88-195`

- AST-based normalization via `sqlglot`
- Fallback to regex-based UDF detection
- Query type classification (12 categories)
- Called at query start, fingerprint stored

**Verification:** `query_fingerprint` and `query_template` populated in `sql_query_log`.

#### 3. Caller Context Propagation (100% Working)
**Files:** `caller_context.py`, `postgres_server.py:545-599`

```python
# Set before query execution
set_caller_context(caller_id="sql-clever-fox-abc123")

# Accessible from any thread/UDF via contextvars
caller_id = get_caller_id()
```

- Thread-safe via `contextvars`
- Propagates to all spawned cascade sessions
- `unified_logs.caller_id` correctly populated

#### 4. Cascade Registration (100% Working)
**Files:** `sql_trail.py:505-617`, `semantic_sql/registry.py:375`

```python
register_cascade_execution(
    caller_id=caller_id,
    cascade_id="semantic_matches",
    cascade_path="/path/to/cascade.yaml",
    session_id=session_id,
    inputs={"query": "..."}
)
```

- Called from `semantic_sql/registry.py:375` and `semantic_sql/executor.py:193`
- Stores in `_cascade_registry` dict (in-memory)
- `get_cascade_paths()` retrieves unique paths

**Problem:** In-memory storage won't survive multi-worker deployments (see Issue #5).

#### 5. UI Endpoints (90% Working)
**Files:** `studio/backend/sql_trail_api.py`

All 6 endpoints exist and query data correctly:
- `/api/sql-trail/overview` - KPIs, trends
- `/api/sql-trail/queries` - Paginated query list
- `/api/sql-trail/query/<caller_id>` - Query detail + spawned sessions
- `/api/sql-trail/patterns` - Grouped by fingerprint
- `/api/sql-trail/cache-stats` - Cache analytics
- `/api/sql-trail/time-series` - Temporal trends

**Missing:** Cost data (total_cost always 0 or NULL due to Issue #2).

---

### What's Broken ✗

#### Issue #1: Missing `cascade_count` Column
**Severity:** HIGH
**Files:** `migrations/create_sql_trail_tables.sql:26-76`, `schema.py:1144-1145`

**Problem:**
- Migration script defines `cascade_paths Array(String)` at line 40
- But **never adds `cascade_count` column**
- `schema.py` defines it at line 1145: `cascade_count UInt16 DEFAULT 0`
- `sql_trail.py:53` checks for existence: `'cascade_count' in columns`
- Check fails → cascade tracking disabled

**Evidence:**
```python
# sql_trail.py:53
_cascade_columns_exist = 'cascade_count' in columns and 'cascade_paths' in columns
```

**Impact:**
- `log_query_complete()` silently skips cascade tracking
- `/api/sql-trail/query/<caller_id>` returns `cascade_count: 0` even when cascades ran

**Root Cause:**
Migration was incomplete. Schema definition added the column but `CREATE TABLE` statement in migration file never included it.

---

#### Issue #2: Cost Aggregation Not Happening
**Severity:** CRITICAL
**Files:** `sql_trail.py:459-498`, `postgres_server.py:1072, 1137`

**Problem:**
`aggregate_query_costs()` function exists and is called, but returns empty dict `{}` because:

1. **Function is called** (postgres_server.py:1072, 1137):
```python
costs = aggregate_query_costs(caller_id) if caller_id else {}
```

2. **But query returns NULL** because `unified_logs.caller_id` is populated, but **cost data arrives late**:
```python
# sql_trail.py:476-485
result = db.query(f"""
    SELECT
        SUM(cost) as total_cost,
        SUM(tokens_in) as total_tokens_in,
        SUM(tokens_out) as total_tokens_out,
        COUNT(*) as llm_calls_count
    FROM unified_logs
    WHERE caller_id = '{caller_id}'
      AND cost IS NOT NULL
""")
```

3. **Timing issue:**
   - Query completes at `T+1000ms`
   - `log_query_complete()` is called immediately
   - LLM calls finish at `T+1500ms`
   - Cost data from OpenRouter API arrives at `T+6000ms` (5s delay)
   - Aggregation query runs at `T+1000ms` → finds 0 rows with cost

**Evidence:**
- `sql_query_log.total_cost` is always NULL or 0
- `unified_logs` has cost data 5-10 seconds after query completion
- `/api/sql-trail/overview` shows `total_cost: 0.0` even for expensive queries

**Root Cause:**
Cost aggregation happens **synchronously** at query completion, before cost data is available. Need either:
- Async cost aggregation (background job)
- Lazy materialized view
- Delay completion logging by 10s (unacceptable UX)

---

#### Issue #3: Cascade Path SQL Escaping Bug
**Severity:** MEDIUM
**Files:** `sql_trail.py:304-310`

**Problem:**
Manual array construction with broken escaping:

```python
# sql_trail.py:307
if cascade_paths:
    paths_str = "['" + "','".join(p.replace("'", "\\'") for p in cascade_paths) + "']"
    updates.append(f"cascade_paths = {paths_str}")
```

**Issues:**
1. Uses `\\'` which is shell escaping, not ClickHouse escaping
2. ClickHouse requires `''` for literal single quotes
3. Should use `db.update_rows()` instead of manual SQL construction
4. Array syntax is incorrect (should use `['path1', 'path2']` not `['path1','path2']`)

**Example Failure:**
```python
cascade_paths = ["/home/user/cascades/O'Reilly.yaml"]
# Produces: cascade_paths = ['/home/user/cascades/O\'Reilly.yaml']
# ClickHouse error: Syntax error near "\'Reilly"
```

**Impact:**
- Cascade path tracking silently fails for paths with quotes/special chars
- `log_query_complete()` throws exception in try/except (line 321)
- Error logged but query appears successful

**Root Cause:**
Premature optimization - tried to avoid `db.update_rows()` overhead by manual SQL construction.

---

#### Issue #4: LLM Call Counter Never Incremented
**Severity:** MEDIUM
**Files:** `sql_trail.py:431-456`

**Problem:**
Function exists but is **never called**:

```python
def increment_llm_call(caller_id: Optional[str]):
    """Increment llm_calls_count counter for a query."""
    db.execute(f"""
        ALTER TABLE sql_query_log
        UPDATE llm_calls_count = llm_calls_count + 1
        WHERE caller_id = '{caller_id}'
    """)
```

**Search Results:**
```bash
$ grep -r "increment_llm_call" rvbbit/
rvbbit/sql_trail.py:def increment_llm_call(caller_id: Optional[str]):
# No other matches - function is NEVER imported or called
```

**Impact:**
- `sql_query_log.llm_calls_count` always 0
- UI shows "LLM Calls: 0" even for queries with thousands of calls
- Cost-per-call metrics impossible

**Alternative Data:**
Can derive from `aggregate_query_costs()` which counts rows in `unified_logs` (but that's also broken - see Issue #2).

**Root Cause:**
Function was added but integration was never completed. Should be called from:
- `agent.py` (LLM call wrapper)
- `sql_tools/udf.py` (UDF execution)
- `semantic_sql/executor.py` (cascade UDF execution)

---

#### Issue #5: In-Memory Cascade Registry Won't Scale
**Severity:** MEDIUM
**Files:** `sql_trail.py:26-35, 505-586`

**Problem:**
Cascade execution tracking uses in-memory dict:

```python
# sql_trail.py:31
_cascade_registry: Dict[str, List[Dict[str, Any]]] = {}

def register_cascade_execution(caller_id, cascade_id, cascade_path, session_id, inputs):
    with _cascade_lock:
        if caller_id not in _cascade_registry:
            _cascade_registry[caller_id] = []
        _cascade_registry[caller_id].append(entry)
```

**Issues:**
1. **Multi-worker deployment failure:**
   - Gunicorn with 4 workers = 4 separate Python processes
   - Worker A handles query start, Worker B handles query completion
   - Worker B's `_cascade_registry` is empty
   - `get_cascade_paths()` returns `[]`

2. **Memory leak risk:**
   - `clear_cascade_executions()` called at completion (line 1093)
   - But if completion fails (exception), memory never freed
   - Long-running server accumulates unbounded data

3. **No persistence:**
   - Server restart = all tracking data lost
   - Cannot analyze historical cascade usage

**Better Approach:**
Store in ClickHouse table `sql_cascade_executions`:
```sql
CREATE TABLE sql_cascade_executions (
    caller_id String,
    cascade_id String,
    cascade_path String,
    session_id String,
    timestamp DateTime64(3),
    INDEX idx_caller caller_id TYPE bloom_filter
) ENGINE = MergeTree() ORDER BY (caller_id, timestamp);
```

**Impact:**
- Production deployments with multiple workers silently lose cascade tracking
- Appears to work in development (single worker)

---

#### Issue #6: Row Input Metrics Never Populated
**Severity:** LOW
**Files:** `postgres_server.py:1081, 1149`, `schema.py:1154-1155`

**Problem:**
`rows_input` field exists but is never set:

```python
# postgres_server.py:1081
log_query_complete(
    rows_output=len(result_df),
    # rows_input is not passed → defaults to NULL
)
```

**Missing Logic:**
Should count rows from USING clause:

```sql
SELECT rvbbit_udf(prompt, content) FROM docs;
-- rows_input should be: COUNT(*) FROM docs
```

**Implementation Gap:**
Need to extract table references from query and count:
```python
# Before query execution
if "USING" in query or "FROM" in query:
    input_tables = extract_table_references(query)
    rows_input = sum(count_rows(table) for table in input_tables)
```

**Impact:**
- Cannot calculate cost-per-input-row
- Cannot track query efficiency (rows_output / rows_input ratio)
- UI shows "Input Rows: N/A"

**Workaround:**
Defer to post-execution analysis via query plan or DuckDB stats.

---

## Recommended Fixes

### Priority 1: Schema Migration (Blocking)

**File:** New migration file `migrations/add_cascade_count_column.sql`

```sql
-- Add missing cascade_count column to sql_query_log
ALTER TABLE sql_query_log
ADD COLUMN IF NOT EXISTS cascade_count UInt16 DEFAULT 0
AFTER cascade_paths;

-- Backfill from in-memory data (if any)
-- This is safe because ALTER ADD COLUMN is non-blocking in ClickHouse
```

**Testing:**
```bash
rvbbit sql query "DESCRIBE TABLE sql_query_log" | grep cascade
# Should show both cascade_paths and cascade_count
```

**Impact:** Enables cascade tracking to function. Zero risk.

---

### Priority 2: Fix Cost Aggregation (Critical UX)

**Option A: Async Background Job (Recommended)**

Create background aggregation service:

```python
# rvbbit/sql_tools/cost_aggregator.py
import time
from threading import Thread
from .sql_trail import aggregate_query_costs, log_query_complete

class CostAggregator:
    def __init__(self, poll_interval=10):
        self.poll_interval = poll_interval
        self.running = True

    def run(self):
        while self.running:
            time.sleep(self.poll_interval)
            self._aggregate_pending_queries()

    def _aggregate_pending_queries(self):
        # Find queries completed in last 60s with no cost data
        db = get_db()
        pending = db.query("""
            SELECT query_id, caller_id
            FROM sql_query_log
            WHERE status = 'completed'
              AND total_cost IS NULL
              AND completed_at > now() - INTERVAL 60 SECOND
        """)

        for row in pending:
            costs = aggregate_query_costs(row['caller_id'])
            if costs.get('total_cost'):  # Only update if data available
                db.execute(f"""
                    ALTER TABLE sql_query_log
                    UPDATE
                        total_cost = {costs['total_cost']},
                        total_tokens_in = {costs['total_tokens_in']},
                        total_tokens_out = {costs['total_tokens_out']},
                        llm_calls_count = {costs['llm_calls_count']}
                    WHERE query_id = '{row['query_id']}'
                """)

# Start in postgres_server.py
aggregator = CostAggregator(poll_interval=10)
Thread(target=aggregator.run, daemon=True).start()
```

**Pros:**
- Non-blocking query execution
- Eventually consistent (10-15s delay)
- Handles OpenRouter API latency

**Cons:**
- Adds complexity
- Requires background thread management

**Option B: Materialized View (Simpler)**

Create ClickHouse materialized view:

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_sql_query_costs
ENGINE = SummingMergeTree()
ORDER BY (caller_id)
AS SELECT
    caller_id,
    SUM(cost) as total_cost,
    SUM(tokens_in) as total_tokens_in,
    SUM(tokens_out) as total_tokens_out,
    COUNT(*) as llm_calls_count
FROM unified_logs
WHERE caller_id != ''
  AND cost IS NOT NULL
GROUP BY caller_id;
```

Then join in queries:

```python
# sql_trail_api.py
query = """
    SELECT
        q.*,
        COALESCE(c.total_cost, 0) as total_cost,
        COALESCE(c.llm_calls_count, 0) as llm_calls_count
    FROM sql_query_log q
    LEFT JOIN mv_sql_query_costs c ON q.caller_id = c.caller_id
    WHERE ...
"""
```

**Pros:**
- Zero code changes
- Automatic updates as data arrives
- Leverages ClickHouse strength

**Cons:**
- Materialized view overhead
- Need to update all queries to use JOIN

**Recommendation:** Start with Option B (MV), migrate to Option A if MV performance is insufficient.

---

### Priority 3: Fix Cascade Path Escaping

**File:** `sql_trail.py:304-310`

Replace manual SQL construction:

```python
# BEFORE (BROKEN)
if cascade_paths:
    paths_str = "['" + "','".join(p.replace("'", "\\'") for p in cascade_paths) + "']"
    updates.append(f"cascade_paths = {paths_str}")

# AFTER (FIXED)
if cascade_paths or cascade_count is not None:
    if _has_cascade_columns(db):
        # Use db.update_rows() for proper escaping
        db.execute(f"""
            ALTER TABLE sql_query_log
            UPDATE
                cascade_paths = {db._format_array_value(cascade_paths)},
                cascade_count = {cascade_count or 0}
            WHERE query_id = '{query_id}'
        """)
```

Or simpler - use parameterized UPDATE:

```python
if cascade_paths:
    # ClickHouse native array handling
    db.execute("""
        ALTER TABLE sql_query_log
        UPDATE
            cascade_paths = %(paths)s,
            cascade_count = %(count)s
        WHERE query_id = %(qid)s
    """, {
        'paths': cascade_paths,
        'count': len(cascade_paths),
        'qid': query_id
    })
```

**Testing:**
```python
test_paths = [
    "/home/user/cascades/simple.yaml",
    "/home/user/cascades/O'Reilly's Guide.yaml",
    "/home/user/cascades/path with spaces.yaml",
]
log_query_complete(query_id=qid, cascade_paths=test_paths)
# Verify: SELECT cascade_paths FROM sql_query_log WHERE query_id = qid
```

---

### Priority 4: Add LLM Call Counting

**Files to modify:**
1. `sql_tools/udf.py` - Add call to `increment_llm_call()`
2. `semantic_sql/executor.py` - Add call after cascade execution
3. `agent.py` - Add call in LLM wrapper

**Example Integration:**

```python
# sql_tools/udf.py (around line where LLM is called)
from ..sql_trail import increment_llm_call
from ..caller_context import get_caller_id

def rvbbit_udf(prompt, content, ...):
    caller_id = get_caller_id()

    # ... existing cache check logic ...

    if not cached:
        # About to call LLM
        increment_llm_call(caller_id)
        result = agent.generate(...)  # Actual LLM call

    return result
```

**Alternative (Better):**
Move increment to `agent.py` so ALL LLM calls are counted (not just UDFs):

```python
# agent.py:generate()
def generate(self, messages, **kwargs):
    # Increment counter BEFORE call (in case of exception)
    from .sql_trail import increment_llm_call
    from .caller_context import get_caller_id

    caller_id = get_caller_id()
    if caller_id:
        increment_llm_call(caller_id)

    # ... existing LLM call logic ...
```

**Risk:** Very low - atomic increment, fire-and-forget pattern.

---

### Priority 5: Move Cascade Registry to Database

**Create new table:**

```sql
-- migrations/create_sql_cascade_executions.sql
CREATE TABLE IF NOT EXISTS sql_cascade_executions (
    caller_id String,
    cascade_id String,
    cascade_path String,
    session_id String,
    timestamp DateTime64(3) DEFAULT now64(3),
    inputs_summary String DEFAULT '',

    INDEX idx_caller caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (caller_id, timestamp)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 90 DAY;
```

**Update functions:**

```python
# sql_trail.py
def register_cascade_execution(caller_id, cascade_id, cascade_path, session_id, inputs):
    """Register cascade execution to database (not in-memory)."""
    if not caller_id:
        return

    from .db_adapter import get_db
    db = get_db()

    db.insert_rows('sql_cascade_executions', [{
        'caller_id': caller_id,
        'cascade_id': cascade_id,
        'cascade_path': cascade_path,
        'session_id': session_id,
        'inputs_summary': str(inputs)[:200] if inputs else ''
    }])

def get_cascade_paths(caller_id: str) -> List[str]:
    """Get unique cascade paths from database."""
    from .db_adapter import get_db
    db = get_db()

    result = db.query(f"""
        SELECT DISTINCT cascade_path
        FROM sql_cascade_executions
        WHERE caller_id = '{caller_id}'
        ORDER BY cascade_path
    """)

    return [row['cascade_path'] for row in result]

def clear_cascade_executions(caller_id: str):
    """Delete cascade execution records after logging complete."""
    from .db_adapter import get_db
    db = get_db()

    # With TTL, we could skip this and let ClickHouse handle cleanup
    # But explicit delete prevents unbounded growth
    db.execute(f"""
        DELETE FROM sql_cascade_executions
        WHERE caller_id = '{caller_id}'
    """)
```

**Benefits:**
- Works with multi-worker deployments
- Persistent across server restarts
- Can analyze historical cascade usage patterns
- Automatic cleanup via TTL

**Migration Path:**
1. Create new table
2. Update functions to write to both (in-memory + DB)
3. Test in production for 1 week
4. Remove in-memory registry
5. Delete `_cascade_registry` dict

---

### Priority 6: Add Row Input Tracking

**Approach:** Extract from query plan

```python
# postgres_server.py (before query execution)
def _estimate_input_rows(self, query: str) -> Optional[int]:
    """Estimate input rows by analyzing query plan."""
    try:
        # DuckDB EXPLAIN shows row estimates
        plan = self.duckdb_conn.execute(f"EXPLAIN {query}").fetchall()

        # Parse plan for "SEQ_SCAN" or "TABLE_SCAN" with row estimates
        # Format: "SEQ_SCAN[docs] (rows=1000)"
        import re
        for line in plan:
            match = re.search(r'\(rows=(\d+)\)', str(line))
            if match:
                return int(match.group(1))
    except:
        pass

    return None

# Then in handle_query():
rows_input = self._estimate_input_rows(query)

log_query_complete(
    rows_input=rows_input,
    rows_output=len(result_df),
    ...
)
```

**Alternative:** Count USING clause rows

```python
def _count_using_rows(self, query: str) -> Optional[int]:
    """Count rows in USING clause if present."""
    match = re.search(r'USING\s+(\w+)', query, re.IGNORECASE)
    if match:
        table_name = match.group(1)
        result = self.duckdb_conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return result[0]
    return None
```

**Risk:** Medium - query plan parsing can be fragile. Add extensive error handling.

---

## Migration Plan

### Phase 1: Schema Fixes (Week 1)

**Day 1-2:**
1. Create migration `add_cascade_count_column.sql`
2. Run migration on dev/staging
3. Verify `DESCRIBE TABLE sql_query_log` shows column
4. Test cascade tracking end-to-end

**Day 3:**
1. Create `sql_cascade_executions` table
2. Update `register_cascade_execution()` to write to DB
3. Keep in-memory registry as fallback
4. Deploy to staging

**Day 4:**
1. Create cost aggregation materialized view
2. Update API queries to use JOIN
3. Test `/api/sql-trail/overview` shows costs
4. Deploy to staging

**Day 5:**
1. Staging validation
2. Load testing (1000 concurrent queries)
3. Verify no performance regression

### Phase 2: Code Fixes (Week 2)

**Day 1:**
1. Fix cascade path escaping bug
2. Add unit tests for special characters
3. Deploy to staging

**Day 2:**
1. Add `increment_llm_call()` to `agent.py`
2. Test with queries that spawn 1000+ LLM calls
3. Verify counts accurate

**Day 3:**
1. Add row input tracking (query plan approach)
2. Test with various query types
3. Add fallback for unsupported queries

**Day 4:**
1. Remove in-memory cascade registry
2. Switch to database-only tracking
3. Load test multi-worker deployment

**Day 5:**
1. Full regression testing
2. Performance profiling
3. Documentation updates

### Phase 3: Production Rollout (Week 3)

**Day 1:** Deploy schema changes only (zero risk)
**Day 2:** Deploy cost aggregation MV
**Day 3:** Deploy code fixes (cascade paths, LLM counting)
**Day 4:** Deploy row tracking
**Day 5:** Monitor, validate, iterate

### Rollback Plan

Each phase is independently reversible:

**Schema rollback:**
```sql
ALTER TABLE sql_query_log DROP COLUMN cascade_count;
DROP TABLE sql_cascade_executions;
DROP VIEW mv_sql_query_costs;
```

**Code rollback:**
- Revert git commits
- In-memory registry still works (degraded mode)
- No data loss

**Monitoring:**
- Track query completion rate (should be 100%)
- Monitor ClickHouse write latency
- Alert if `total_cost` NULL rate > 5%

---

## Testing Checklist

### Unit Tests

```python
# tests/test_sql_trail.py

def test_fingerprint_with_special_chars():
    sql = "SELECT rvbbit_udf('O''Reilly''s book') FROM docs"
    fp, template, udfs = fingerprint_query(sql)
    assert 'rvbbit_udf' in udfs
    assert template == "SELECT rvbbit_udf(?) FROM docs"

def test_cascade_path_escaping():
    paths = ["/path/with spaces.yaml", "/path/with'quotes.yaml"]
    log_query_complete(query_id=qid, cascade_paths=paths)
    # Verify no SQL error

def test_cost_aggregation_timing():
    # Simulate late-arriving cost data
    caller_id = set_caller_context("test-caller")
    log_query_start(caller_id, "SELECT 1")

    # Simulate LLM calls finishing after query
    time.sleep(2)
    log_llm_call(caller_id, cost=0.005)

    # Cost aggregation should eventually pick it up
    time.sleep(12)  # Wait for background job
    costs = get_query_costs(caller_id)
    assert costs['total_cost'] == 0.005
```

### Integration Tests

```python
def test_end_to_end_sql_trail():
    # Execute query with UDFs
    result = client.query("""
        SELECT rvbbit_udf('summarize', content)
        FROM docs
        LIMIT 10
    """)

    # Verify sql_query_log entry
    assert sql_query_log.count(caller_id=result.caller_id) == 1

    # Verify cache tracking
    entry = sql_query_log.get(caller_id=result.caller_id)
    assert entry.cache_hits + entry.cache_misses == 10

    # Verify cost aggregation (within 15s)
    time.sleep(15)
    entry = sql_query_log.get(caller_id=result.caller_id)
    assert entry.total_cost > 0
```

### Load Tests

```bash
# 1000 concurrent queries with 100 UDF calls each
ab -n 1000 -c 50 -p query.sql http://localhost:15432/

# Verify:
# - All queries logged
# - Cache hit rate > 80% (after warmup)
# - No deadlocks
# - Cost aggregation completes within 30s
```

---

## Performance Considerations

### Current Bottlenecks

1. **Atomic increments** (`cache_hits`, `cache_misses`):
   - ClickHouse `ALTER UPDATE` is efficient but not free
   - ~1ms per increment
   - With 1000 UDF calls = 1000 increments = 1s overhead
   - **Mitigation:** Batch increments (increment by N instead of 1)

2. **Cost aggregation query**:
   - `SUM(cost) FROM unified_logs WHERE caller_id = X`
   - With 10,000 calls = full table scan
   - **Mitigation:** Materialized view (already recommended)

3. **Cascade registry cleanup**:
   - DELETE queries on every completion
   - **Mitigation:** Let TTL handle cleanup, skip DELETE

### Optimization Opportunities

**Batch increment:**
```python
# Instead of increment_cache_hit() per call
# Accumulate in thread-local counter, flush every 100 calls

thread_local_cache = threading.local()

def increment_cache_hit(caller_id):
    if not hasattr(thread_local_cache, 'hits'):
        thread_local_cache.hits = defaultdict(int)

    thread_local_cache.hits[caller_id] += 1

    if thread_local_cache.hits[caller_id] % 100 == 0:
        _flush_cache_counters(caller_id)

def _flush_cache_counters(caller_id):
    count = thread_local_cache.hits.pop(caller_id, 0)
    db.execute(f"""
        ALTER TABLE sql_query_log
        UPDATE cache_hits = cache_hits + {count}
        WHERE caller_id = '{caller_id}'
    """)
```

**Denormalize costs to sql_query_log:**
- Instead of JOIN at query time
- Background job copies from MV to sql_query_log.total_cost
- Trades write overhead for read speed

---

## Appendix: Code References

### Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `rvbbit/sql_trail.py` | 1-617 | Core SQL Trail logic |
| `rvbbit/schema.py` | 1130-1189 | sql_query_log schema |
| `rvbbit/server/postgres_server.py` | 1062-1161 | Query completion logging |
| `rvbbit/semantic_sql/registry.py` | 343, 375 | Cascade registration |
| `studio/backend/sql_trail_api.py` | 1-713 | UI endpoints |
| `migrations/create_sql_trail_tables.sql` | 26-96 | Initial migration |

### Function Call Graph

```
postgres_server.py:handle_query()
├─ set_caller_context(caller_id)
├─ log_query_start(caller_id, query)
│   ├─ fingerprint_query(query)
│   │   ├─ sqlglot.parse_one()
│   │   ├─ _extract_udf_types_ast()
│   │   └─ _normalize_literals()
│   └─ db.insert_rows('sql_query_log')
├─ DuckDB.execute(query)
│   └─ rvbbit_udf() / rvbbit_cascade_udf()
│       ├─ increment_cache_hit(caller_id)  ✓
│       ├─ increment_cache_miss(caller_id) ✓
│       ├─ register_cascade_execution()    ✓
│       └─ increment_llm_call(caller_id)   ✗ MISSING
└─ log_query_complete(query_id)
    ├─ aggregate_query_costs(caller_id)   ✗ BROKEN
    ├─ get_cascade_paths(caller_id)       ✓
    ├─ get_cascade_summary(caller_id)     ✓
    └─ db.execute(UPDATE sql_query_log)   ✗ PARTIAL
```

### Database Relationships

```
sql_query_log (1)
    ├─ caller_id (PK for query-level grouping)
    │
    └─> unified_logs (N)
        ├─ caller_id (FK, join key)
        ├─ session_id (cascade session)
        ├─ cost, tokens_in, tokens_out
        └─ is_sql_udf, udf_type, cache_hit

sql_cascade_executions (proposed)
    ├─ caller_id (FK to sql_query_log)
    ├─ cascade_id, cascade_path
    └─ session_id (FK to unified_logs)
```

---

## Conclusion

The SQL Trail observability system has a **solid architectural foundation** with well-designed fingerprinting, cache tracking, and UI components. The 6 identified issues are all fixable with low-risk migrations and code changes.

**Recommended Immediate Actions:**
1. Run schema migration to add `cascade_count` column (5 minutes)
2. Create cost aggregation materialized view (1 hour)
3. Fix cascade path escaping bug (30 minutes)

These 3 changes will restore **80% of functionality** with minimal effort.

**Long-term Recommendations:**
1. Move cascade registry to database (enables multi-worker deployments)
2. Add LLM call counting (completes cost attribution story)
3. Implement row input tracking (nice-to-have for efficiency metrics)

**Overall Risk:** LOW - All fixes are additive, no breaking changes to existing functionality.
