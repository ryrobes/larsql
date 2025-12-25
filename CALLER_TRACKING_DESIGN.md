# Caller Tracking Design: caller_id & Invocation Metadata

**Goal**: Track SQL queries (and other invocation sources) that spawn multiple cascade sessions for cost rollup and debugging.

---

## Problem Statement

**Current Situation:**
- SQL query with 100 rows → 100 separate cascade sessions with unique session_ids
- No way to link these 100 sessions back to the original SQL query
- No tracking of invocation source (DBeaver SQL vs CLI vs Dashboard UI)
- Cost reporting is per-session, not per-query
- Debugging: Can't see "what SQL query caused these 100 sessions?"

**Examples:**

```sql
-- This ONE query spawns 5 cascade sessions:
RVBBIT MAP 'extract_brand' USING (SELECT * FROM products LIMIT 5);

-- Currently: 5 disconnected session_ids
-- udf-clever-fox-abc123  ($0.01)
-- udf-misty-owl-def456   ($0.01)
-- udf-quick-rabbit-ghi789 ($0.01)
-- udf-silver-hare-jkl012 ($0.01)
-- udf-fuzzy-shrew-mno345 ($0.01)
-- Total: $0.05 - but NO way to group/sum these!

-- Desired: All linked to caller_id="sql-query-xyz"
-- Query: "SELECT * FROM all_data WHERE caller_id = 'sql-query-xyz'"
-- Returns: All 5 sessions, total cost = $0.05
```

---

## Proposed Solution

### 1. Add `caller_id` Field

**Definition**: Parent identifier that groups related sessions

**Generation Strategy:**
- **SQL invocations**: Generate once per query execution
  - Format: `sql-<woodland-id>` (e.g., `sql-clever-fox-abc123`)
  - Generated in PostgreSQL server or HTTP API before query execution
- **UI invocations**: Use playground/notebook execution ID
  - Format: `ui-<woodland-id>` or reuse existing UI session ID
- **CLI invocations**: Use top-level cascade session_id
  - Format: Just the session_id itself (no parent needed for direct CLI runs)
- **UDF sub-cascades**: Inherit caller_id from parent cascade

**Hierarchy:**
```
caller_id: sql-quick-rabbit-xyz   (SQL query that started it all)
  ├─ session_id: udf-clever-fox-row1
  ├─ session_id: udf-misty-owl-row2
  ├─ session_id: udf-silver-hare-row3
  └─ session_id: udf-fuzzy-shrew-row4
```

---

### 2. Add `invocation_metadata` Field (JSON)

**Purpose**: Capture context about how the cascade was triggered

**Schema:**
```python
{
  "origin": "sql" | "ui" | "cli" | "api" | "udf",
  "sql_query": "RVBBIT MAP 'x' USING (SELECT ...)",  # For SQL origin
  "ui_component": "playground" | "notebook" | "sessions",  # For UI origin
  "cli_command": "rvbbit run cascade.yaml --input ...",  # For CLI origin
  "api_endpoint": "/api/run-cascade",  # For API origin
  "triggered_by": "postgres_server" | "http_api" | "cli" | "dashboard",
  "client_info": {
    "tool": "DBeaver" | "psql" | "Python" | "curl",  # For SQL
    "user_agent": "...",  # For HTTP
    "ip_address": "..."  # Optional
  },
  "parent_cascade": {  # For UDF-spawned cascades
    "session_id": "parent-session-abc",
    "cascade_id": "parent_cascade"
  }
}
```

---

## Implementation Plan

### Phase 1: Data Collection Points

#### A. SQL Invocations (PostgreSQL Server)

**File**: `rvbbit/rvbbit/server/postgres_server.py`

**Where**: In `handle_query()` before rewrite

```python
def handle_query(self, query: str):
    # ... existing code ...

    # Check if RVBBIT syntax
    from rvbbit.sql_rewriter import rewrite_rvbbit_syntax, _is_rvbbit_statement

    if _is_rvbbit_statement(query):
        # Generate caller_id for this SQL query
        from rvbbit.session_naming import generate_woodland_id
        caller_id = f"sql-{generate_woodland_id()}"

        # Build invocation metadata
        invocation_metadata = {
            "origin": "sql",
            "sql_query": query[:1000],  # Truncate long queries
            "triggered_by": "postgres_server",
            "client_info": {
                "protocol": "postgresql_wire",
                "session_id": self.session_id  # PostgreSQL session, not cascade session
            }
        }

        # Store in context variable for UDF access
        from rvbbit.context import set_caller_context
        set_caller_context(caller_id, invocation_metadata)

    # Rewrite and execute
    query = rewrite_rvbbit_syntax(query)
    result_df = self.duckdb_conn.execute(query).fetchdf()
    # ...
```

#### B. HTTP SQL API

**File**: `dashboard/backend/sql_server_api.py`

```python
def execute_sql():
    # ... existing code ...

    from rvbbit.sql_rewriter import _is_rvbbit_statement

    if _is_rvbbit_statement(query):
        from rvbbit.session_naming import generate_woodland_id
        caller_id = f"http-{generate_woodland_id()}"

        invocation_metadata = {
            "origin": "sql",
            "sql_query": query[:1000],
            "triggered_by": "http_api",
            "client_info": {
                "user_agent": request.headers.get('User-Agent'),
                "client_session": session_id  # HTTP session
            }
        }

        from rvbbit.context import set_caller_context
        set_caller_context(caller_id, invocation_metadata)

    # ... execute query ...
```

#### C. CLI Invocations

**File**: `rvbbit/rvbbit/cli.py`

```python
def cmd_run(...):
    # ... existing code ...

    # For CLI, caller_id = session_id (top-level run)
    caller_id = session_id

    invocation_metadata = {
        "origin": "cli",
        "cli_command": ' '.join(sys.argv),
        "cascade_file": config_path,
        "input_file": input_file or "inline"
    }

    # Pass to run_cascade
    result = run_cascade(
        config_path,
        input_data,
        session_id=session_id,
        caller_id=caller_id,
        invocation_metadata=invocation_metadata
    )
```

#### D. Dashboard UI

**File**: `dashboard/backend/app.py` or playground/notebook APIs

```python
@app.route('/api/run-cascade', methods=['POST'])
def run_cascade_api():
    # ... existing code ...

    caller_id = f"ui-{generate_woodland_id()}"

    invocation_metadata = {
        "origin": "ui",
        "ui_component": request.json.get('source'),  # 'playground', 'notebook', etc.
        "triggered_by": "dashboard_ui"
    }

    result = run_cascade(
        cascade_path,
        inputs,
        caller_id=caller_id,
        invocation_metadata=invocation_metadata
    )
```

---

### Phase 2: Context Propagation

#### A. Create Context Variable System

**New File**: `rvbbit/rvbbit/context.py` (or add to existing)

```python
from contextvars import ContextVar
from typing import Optional, Dict, Any

# Context variables for caller tracking
_caller_id: ContextVar[Optional[str]] = ContextVar('caller_id', default=None)
_invocation_metadata: ContextVar[Optional[Dict]] = ContextVar('invocation_metadata', default=None)


def set_caller_context(caller_id: str, metadata: Dict[str, Any]):
    """Set caller context for current thread/async context."""
    _caller_id.set(caller_id)
    _invocation_metadata.set(metadata)


def get_caller_id() -> Optional[str]:
    """Get current caller_id from context."""
    return _caller_id.get()


def get_invocation_metadata() -> Optional[Dict]:
    """Get current invocation metadata from context."""
    return _invocation_metadata.get()


def clear_caller_context():
    """Clear caller context."""
    _caller_id.set(None)
    _invocation_metadata.set(None)
```

#### B. Update UDF to Use Context

**File**: `rvbbit/rvbbit/sql_tools/udf.py`

```python
def rvbbit_cascade_udf_impl(...):
    # ... existing code ...

    # Get caller context from thread-local storage
    from ..context import get_caller_id, get_invocation_metadata
    caller_id = get_caller_id()
    invocation_metadata = get_invocation_metadata()

    # Pass to run_cascade
    result = run_cascade(
        resolved_path,
        inputs,
        session_id=session_id,
        caller_id=caller_id,
        invocation_metadata=invocation_metadata
    )
```

#### C. Update run_cascade Signature

**File**: `rvbbit/rvbbit/runner.py`

```python
def run_cascade(
    config_path: str | dict,
    input_data: dict = None,
    session_id: str = "default",
    overrides: dict = None,
    depth: int = 0,
    parent_trace: TraceNode = None,
    hooks: RVBBITHooks = None,
    parent_session_id: str = None,
    candidate_index: int = None,
    caller_id: str = None,  # NEW
    invocation_metadata: dict = None  # NEW
) -> dict:
    runner = RVBBITRunner(
        config_path,
        session_id,
        overrides,
        depth,
        parent_trace,
        hooks,
        candidate_index,
        parent_session_id,
        caller_id,  # NEW
        invocation_metadata  # NEW
    )
    # ...
```

#### D. Store in Echo

**File**: `rvbbit/rvbbit/echo.py`

```python
class Echo:
    def __init__(self, ...):
        # ... existing fields ...
        self.caller_id = caller_id
        self.invocation_metadata = invocation_metadata
```

---

### Phase 3: Schema Changes

#### A. Add Columns to unified_logs

**File**: `rvbbit/rvbbit/unified_logs.py`

**In log() function signature:**
```python
def log(
    self,
    # ... existing params ...

    # NEW: Caller tracking
    caller_id: str = None,
    invocation_metadata: Dict = None,

    # ... rest of params ...
):
```

**In row dict:**
```python
row = {
    # ... existing fields ...

    # NEW: Caller tracking
    "caller_id": caller_id,
    "invocation_metadata_json": safe_json(invocation_metadata),
}
```

#### B. ClickHouse Schema

**Migration**: ClickHouse will auto-add columns when new fields appear in INSERT

**Manual creation (optional):**
```sql
ALTER TABLE unified_logs
ADD COLUMN caller_id String DEFAULT '',
ADD COLUMN invocation_metadata_json String DEFAULT '';
```

**Indexes for fast queries:**
```sql
-- For cost rollup by caller
CREATE INDEX idx_caller_id ON unified_logs(caller_id) TYPE minmax;

-- For filtering by origin
CREATE INDEX idx_origin ON unified_logs((JSONExtractString(invocation_metadata_json, 'origin'))) TYPE set(10);
```

---

## Data We Can Gather

### ✅ **Definitely Available**

1. **From PostgreSQL Server**:
   - ✅ SQL query text (full or truncated)
   - ✅ Protocol type (postgresql_wire vs http)
   - ✅ PostgreSQL session_id (connection identifier)
   - ⚠️ Client tool name (LIMITED - would need pg_stat_activity parsing)

2. **From HTTP API**:
   - ✅ SQL query text
   - ✅ User-Agent header (Python client, curl, etc.)
   - ✅ HTTP session_id
   - ✅ Request timestamp

3. **From CLI**:
   - ✅ Full command line (sys.argv)
   - ✅ Cascade file path
   - ✅ Input file vs inline input
   - ✅ Working directory

4. **From Dashboard UI**:
   - ✅ UI component (playground, notebook, sessions)
   - ✅ Cascade source (trait, cascade, example)
   - ✅ User actions (run, re-run, fork)
   - ✅ Browser session ID

### ❌ **Not Available (Without Extra Work)**

1. **DBeaver/psql client identification**:
   - Would need to parse PostgreSQL application_name
   - Not sent by default in current implementation
   - Could add via connection parameters

2. **User identity**:
   - No authentication system currently
   - Could add in future

3. **Remote IP address**:
   - Not captured in PostgreSQL wire protocol handler
   - Available in HTTP API (request.remote_addr)

---

## Proposed Schema

### New Columns

```python
# In unified_logs table:
caller_id: String  # Parent identifier grouping related sessions
invocation_metadata_json: String  # JSON with origin, query, etc.
```

### invocation_metadata Structure

```json
{
  "origin": "sql|ui|cli|api|udf",
  "triggered_by": "postgres_server|http_api|cli|dashboard|parent_cascade",

  // For SQL origin:
  "sql": {
    "query": "RVBBIT MAP 'x' USING (SELECT * FROM products LIMIT 100)",
    "query_hash": "a3f2e1b9...",  // For deduplication
    "rewritten_query": "WITH rvbbit_input AS ...",  // After rewrite
    "protocol": "postgresql_wire|http",
    "row_count": 100,  // Expected rows to process
    "parallel_workers": 5  // If PARALLEL specified
  },

  // For UI origin:
  "ui": {
    "component": "playground|notebook|sessions",
    "action": "run|re-run|fork|auto-fix",
    "cascade_source": "trait|cascade|example|scratch"
  },

  // For CLI origin:
  "cli": {
    "command": "rvbbit run cascade.yaml --input data.json",
    "cascade_file": "cascade.yaml",
    "input_source": "file|inline|stdin"
  },

  // For UDF-spawned cascades:
  "parent": {
    "session_id": "udf-parent-session",
    "cascade_id": "parent_cascade_name",
    "cell_name": "cell_that_spawned_this"
  },

  // Timing
  "invocation_timestamp": "2025-12-25T15:40:01.123Z",
  "caller_created_at": "2025-12-25T15:40:00.000Z"  // When caller_id was generated
}
```

---

## Implementation Strategy

### Step 1: Add Context System (30 min)

Create `rvbbit/rvbbit/caller_context.py`:

```python
from contextvars import ContextVar
from typing import Optional, Dict

_caller_id = ContextVar('caller_id', default=None)
_invocation_metadata = ContextVar('invocation_metadata', default=None)

def set_caller_context(caller_id: str, metadata: Dict):
    _caller_id.set(caller_id)
    _invocation_metadata.set(metadata)

def get_caller_context() -> tuple[Optional[str], Optional[Dict]]:
    return _caller_id.get(), _invocation_metadata.get()
```

---

### Step 2: Update unified_logs Schema (15 min)

Add to `log()` signature and row dict:

```python
def log(
    self,
    # ... existing params ...
    caller_id: str = None,
    invocation_metadata: Dict = None,
):
    row = {
        # ... existing fields ...
        "caller_id": caller_id or "",
        "invocation_metadata_json": safe_json(invocation_metadata) or "{}",
    }
```

---

### Step 3: Update Runner to Propagate (30 min)

**A. Update run_cascade signature:**
```python
def run_cascade(
    # ... existing params ...
    caller_id: str = None,
    invocation_metadata: Dict = None
):
    # If not provided, try to get from context
    if caller_id is None:
        from .caller_context import get_caller_context
        caller_id, invocation_metadata = get_caller_context()

    # Pass to runner
    runner = RVBBITRunner(
        # ... existing params ...
        caller_id=caller_id,
        invocation_metadata=invocation_metadata
    )
```

**B. Update RVBBITRunner.__init__:**
```python
class RVBBITRunner:
    def __init__(
        self,
        # ... existing params ...
        caller_id: str = None,
        invocation_metadata: Dict = None
    ):
        # ... existing code ...
        self.caller_id = caller_id
        self.invocation_metadata = invocation_metadata
```

**C. Pass to Echo:**
```python
self.echo = Echo(
    # ... existing params ...
    caller_id=self.caller_id,
    invocation_metadata=self.invocation_metadata
)
```

**D. Pass to log() calls:**

Throughout runner.py, add to log() calls:
```python
unified_log.log(
    session_id=self.session_id,
    # ... existing params ...
    caller_id=self.caller_id,
    invocation_metadata=self.invocation_metadata
)
```

---

### Step 4: Update UDF to Set Context (15 min)

**File**: `rvbbit/rvbbit/sql_tools/udf.py`

```python
def rvbbit_cascade_udf_impl(...):
    # ... existing code ...

    # Get caller context (set by SQL server before UDF calls)
    from ..caller_context import get_caller_context
    caller_id, invocation_metadata = get_caller_context()

    # Pass to run_cascade
    result = run_cascade(
        resolved_path,
        inputs,
        session_id=session_id,
        caller_id=caller_id,
        invocation_metadata=invocation_metadata
    )
```

---

### Step 5: Update SQL Server to Set Context (15 min)

**File**: `rvbbit/rvbbit/server/postgres_server.py`

```python
def handle_query(self, query: str):
    # ... existing code ...

    # Before rewrite: Check if RVBBIT and set context
    from rvbbit.sql_rewriter import rewrite_rvbbit_syntax, _is_rvbbit_statement

    if _is_rvbbit_statement(query):
        from rvbbit.session_naming import generate_woodland_id
        from rvbbit.caller_context import set_caller_context

        caller_id = f"sql-{generate_woodland_id()}"
        metadata = {
            "origin": "sql",
            "sql_query": query,
            "triggered_by": "postgres_server"
        }

        set_caller_context(caller_id, metadata)

    query = rewrite_rvbbit_syntax(query)
    # ... execute ...
```

---

## Querying Examples

### Cost Rollup by SQL Query

```sql
SELECT
  caller_id,
  JSONExtractString(invocation_metadata_json, 'sql.query') as sql_query,
  COUNT(DISTINCT session_id) as session_count,
  SUM(cost) as total_cost,
  AVG(duration_ms) as avg_duration_ms
FROM all_data
WHERE caller_id LIKE 'sql-%'
  AND cost > 0
GROUP BY caller_id, sql_query
ORDER BY total_cost DESC
LIMIT 20;
```

### Find All Sessions from One SQL Query

```sql
SELECT session_id, cascade_id, cost
FROM all_data
WHERE caller_id = 'sql-clever-fox-abc123'
  AND event_type = 'cascade_complete'
ORDER BY session_id;
```

### Origin Breakdown

```sql
SELECT
  JSONExtractString(invocation_metadata_json, 'origin') as origin,
  COUNT(DISTINCT caller_id) as invocation_count,
  COUNT(DISTINCT session_id) as session_count,
  SUM(cost) as total_cost
FROM all_data
WHERE caller_id != ''
GROUP BY origin;
```

### Most Expensive SQL Queries

```sql
SELECT
  caller_id,
  JSONExtractString(invocation_metadata_json, 'sql.query') as query,
  COUNT(DISTINCT session_id) as cascades_spawned,
  SUM(cost) as total_cost
FROM all_data
WHERE JSONExtractString(invocation_metadata_json, 'origin') = 'sql'
  AND cost > 0
GROUP BY caller_id, query
ORDER BY total_cost DESC
LIMIT 10;
```

---

## Backward Compatibility

**Existing sessions:**
- `caller_id` = empty string `''`
- `invocation_metadata_json` = empty object `'{}'`

**New sessions:**
- Populated automatically when context is set
- Old code paths (no context) → empty values (same as before)

**No breaking changes!**

---

## Estimated Implementation Time

| Task | Time | Complexity |
|------|------|------------|
| Create context system | 30 min | Low |
| Update unified_logs schema | 15 min | Low |
| Update run_cascade signature | 30 min | Medium |
| Update Echo | 15 min | Low |
| Update UDF to use context | 15 min | Low |
| Update PostgreSQL server | 15 min | Low |
| Update HTTP API | 15 min | Low |
| Update CLI (optional) | 15 min | Low |
| Testing | 30 min | Medium |
| **Total** | **3 hours** | **Medium** |

---

## Benefits

1. **Cost Tracking**: Roll up costs by SQL query
2. **Debugging**: "What SQL query created this session?"
3. **Analytics**: Usage by origin (SQL vs UI vs CLI)
4. **Optimization**: Find expensive queries
5. **Auditing**: Track who ran what (if we add auth later)

---

## Open Questions

1. **Should caller_id be hierarchical for nested cascades?**
   - Example: `sql-abc → cascade_xyz → sub_cascade_def`
   - Or: All share same top-level caller_id?

2. **How long to keep SQL query text?**
   - Full query (can be 10KB+)
   - Truncated (first 1000 chars)
   - Hash only (for dedup, lose readability)

3. **Should we track DuckDB query stats?**
   - Row counts, execution time of USING clause
   - Might be noisy

4. **UI session vs caller_id?**
   - Dashboard already has session concept
   - Reuse or create separate caller_id?

---

## Next Steps

1. ✅ **Review this design** - does it cover your needs?
2. ⏳ **Answer open questions**
3. ⏳ **Implement Phase 1** (context system)
4. ⏳ **Implement Phase 2** (propagation)
5. ⏳ **Implement Phase 3** (schema)
6. ⏳ **Test with SQL queries**
7. ⏳ **Build cost rollup queries**

---

**Should I proceed with implementation, or do you want to discuss the design first?** 🤔
