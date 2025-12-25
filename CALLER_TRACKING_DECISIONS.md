# Caller Tracking - Design Decisions

**Date**: 2025-12-25
**Status**: Approved - Implement After Phase 3 (RVBBIT RUN)

---

## ✅ Finalized Decisions

### 1. Hierarchical caller_id for Nested Cascades
**Decision**: All sub-cascades share top-level caller_id (Option A)

**Rationale:**
- Simpler implementation
- Easy cost rollup by caller
- Clear ownership hierarchy

**Example:**
```
SQL Query: RVBBIT MAP 'parent.yaml' USING (...)
  caller_id: sql-clever-fox-abc123
    ├─ session: udf-quick-rabbit-001 (row 1)
    │    └─ spawns sub-cascade → inherits caller_id: sql-clever-fox-abc123
    ├─ session: udf-misty-owl-002 (row 2)
    │    └─ spawns sub-cascade → inherits caller_id: sql-clever-fox-abc123
    └─ session: udf-silver-hare-003 (row 3)

Cost Query: SELECT SUM(cost) WHERE caller_id = 'sql-clever-fox-abc123'
→ Returns total for SQL query + all spawned sessions
```

---

### 2. SQL Query Text Storage
**Decision**: Store full query (no truncation)

**Rationale:**
- ClickHouse columnar storage handles large text efficiently
- Compression eliminates redundancy
- Full query needed for debugging/replay
- Text column only stored once per caller_id effectively (columnar + compression)

**Storage impact:** Minimal (queries compress ~10:1 with LZ4)

---

### 3. CLI Invocations Get caller_id
**Decision**: Yes, generate caller_id for CLI runs

**Format:** `cli-<woodland-id>`

**Rationale:**
- Consistency across all entry points
- Distinguishes CLI vs SQL vs UI
- Enables uniform analytics
- Future-proof for multi-session CLI workflows

**Example:**
```bash
# CLI run
rvbbit run cascade.yaml --input data.json

# Gets:
caller_id: cli-fuzzy-shrew-xyz789
session_id: cli-fuzzy-shrew-xyz789  (same for top-level CLI)
invocation_metadata: {
  "origin": "cli",
  "cli_command": "rvbbit run cascade.yaml --input data.json"
}
```

---

## Implementation Priority

**Status**: ⏸️ **Deferred Until After Phase 3**

**Sequence:**
1. ✅ Phase 1-2: RVBBIT MAP + PARALLEL (DONE)
2. ⏳ **Phase 3: RVBBIT RUN** (NEXT)
3. ⏳ **Phase 2B: Real Threading for PARALLEL** (optional optimization)
4. ⏳ **Caller Tracking Implementation** (3 hours)

**Why this order:**
- RVBBIT RUN also spawns multiple sessions (benefits from caller tracking)
- Design caller tracking for both MAP and RUN together
- Complete core syntax features first, add observability after

---

## Approved Schema

### New Columns in unified_logs

```sql
caller_id String DEFAULT ''
invocation_metadata_json String DEFAULT '{}'
```

### invocation_metadata Structure

```json
{
  "origin": "sql|ui|cli|api",
  "sql_query": "RVBBIT MAP ...",  // Full query for SQL
  "triggered_by": "postgres_server|http_api|cli|dashboard",
  "row_count": 100,
  "parallel_workers": 5
}
```

---

**Decisions captured! Proceeding with Phase 3: RVBBIT RUN** 🚀
