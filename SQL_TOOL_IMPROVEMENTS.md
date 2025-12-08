# SQL Tool Improvements: Token-Efficient Query Results

## Problem Statement

The current SQL tool (`smart_sql_run`) has two issues that cause token bloat:

1. **Unbounded row counts** - Agents can pull unlimited rows, causing massive token usage
2. **Verbose JSON format** - Column names repeated for every row: `[{"col": "val"}, {"col": "val"}, ...]`

This compounds across turns and phases due to Windlass' snowball architecture.

## Solution Overview

1. **Compact output format** - Schema + array-of-arrays (40% token reduction)
2. **Automatic row limiting** - Safe defaults with transparent truncation metadata
3. **sqlglot-based query rewriting** - Safe LIMIT injection without breaking queries
4. **Two-tool design** - Bounded (default) + unbounded (opt-in) for flexibility

---

## Dependencies

Add to `windlass/setup.py` or `pyproject.toml`:

```
sqlglot>=20.0.0
```

sqlglot provides:
- SQL parsing and AST manipulation
- DuckDB dialect support
- Safe LIMIT injection without regex hacks
- Query analysis (detect existing LIMIT, CTEs, etc.)

---

## Output Format Specification

### Current Format (Verbose)

```json
[
  {"id": 1, "name": "Alice", "email": "alice@example.com", "bio": "Software engineer..."},
  {"id": 2, "name": "Bob", "email": "bob@example.com", "bio": "Product manager..."},
  {"id": 3, "name": "Carol", "email": "carol@example.com", "bio": "Designer..."}
]
```

**Tokens:** ~120 for 3 rows × 4 columns

### New Format (Compact)

```json
{
  "columns": ["id", "name", "email", "bio"],
  "rows": [
    [1, "Alice", "alice@example.com", "Software engineer..."],
    [2, "Bob", "bob@example.com", "Product manager..."],
    [3, "Carol", "carol@example.com", "Designer..."]
  ],
  "row_count": 3,
  "total_available": 1523,
  "truncated": true,
  "limit_injected": true,
  "note": "Showing 3 of 1523 rows. Refine query with WHERE/LIMIT for specific data."
}
```

**Tokens:** ~85 for same data (~30% reduction)

### Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `columns` | `string[]` | Column names in order |
| `rows` | `any[][]` | Data rows as arrays (matches column order) |
| `row_count` | `int` | Number of rows returned |
| `total_available` | `int \| string` | Total rows available, or `"100+"` if unknown |
| `truncated` | `bool` | Whether results were truncated |
| `limit_injected` | `bool` | Whether LIMIT was auto-added to query |
| `note` | `string \| null` | Guidance for agent (only when truncated) |

---

## Tool Specifications

### 1. `smart_sql_run` (Default, Bounded)

```python
def smart_sql_run(
    query: str,
    max_rows: int = 100,
    max_cell_chars: int = 500
) -> str:
    """
    Execute SQL query with automatic row limiting and compact output.

    Behavior:
    - If query has no LIMIT, automatically injects LIMIT {max_rows + 1}
    - Returns at most {max_rows} rows in compact format
    - Truncates cell values longer than {max_cell_chars} characters
    - Includes metadata about truncation for query refinement

    Use sql_query_unbounded() if you explicitly need all rows.

    Args:
        query: DuckDB-compatible SQL query
        max_rows: Maximum rows to return (default: 100)
        max_cell_chars: Truncate cell values beyond this length (default: 500)

    Returns:
        JSON string with compact format:
        {
          "columns": [...],
          "rows": [[...], ...],
          "row_count": N,
          "total_available": M or "N+",
          "truncated": true/false,
          "limit_injected": true/false
        }
    """
```

### 2. `sql_query_unbounded` (Opt-in, Full Power)

```python
def sql_query_unbounded(query: str) -> str:
    """
    Execute SQL query WITHOUT row limits. Returns ALL matching rows.

    ⚠️  WARNING: Large results will consume many tokens. Use with caution.

    Prefer smart_sql_run() for exploratory queries. Only use this when you
    explicitly need all rows for comprehensive analysis.

    Still uses compact output format (columns + rows) for token efficiency.

    Args:
        query: DuckDB-compatible SQL query

    Returns:
        JSON string with compact format (no truncation metadata)
    """
```

---

## Implementation Details

### File: `windlass/windlass/eddies/sql.py`

```python
import json
import duckdb
import sqlglot
from sqlglot import exp
from .base import simple_eddy

# ============================================================================
# Configuration (can be overridden via environment variables)
# ============================================================================

import os

DEFAULT_MAX_ROWS = int(os.getenv("WINDLASS_SQL_MAX_ROWS", "100"))
DEFAULT_MAX_CELL_CHARS = int(os.getenv("WINDLASS_SQL_MAX_CELL_CHARS", "500"))

# ============================================================================
# Query Rewriting with sqlglot
# ============================================================================

def has_limit(query: str) -> bool:
    """Check if query already has a LIMIT clause."""
    try:
        parsed = sqlglot.parse_one(query, dialect='duckdb')
        return parsed.find(exp.Limit) is not None
    except Exception:
        # If parsing fails, assume no LIMIT (will wrap in subquery)
        return False


def inject_limit(query: str, limit: int) -> tuple[str, bool]:
    """
    Inject LIMIT into query if not already present.

    Returns:
        (modified_query, was_injected)
    """
    try:
        parsed = sqlglot.parse_one(query, dialect='duckdb')

        if parsed.find(exp.Limit):
            return query, False

        # Add LIMIT clause
        limited = parsed.limit(limit)
        return limited.sql(dialect='duckdb'), True

    except Exception:
        # Fallback: wrap in subquery (handles edge cases)
        wrapped = f"SELECT * FROM ({query}) AS _windlass_limit LIMIT {limit}"
        return wrapped, True


def get_total_count(query: str, con: duckdb.DuckDBPyConnection) -> int | None:
    """
    Get total row count for a query.
    Returns None if count query fails or is too expensive.
    """
    try:
        # Wrap original query and count
        count_query = f"SELECT COUNT(*) AS cnt FROM ({query}) AS _windlass_count"
        result = con.execute(count_query).fetchone()
        return result[0] if result else None
    except Exception:
        return None

# ============================================================================
# Output Formatting
# ============================================================================

def truncate_cell(value, max_chars: int) -> any:
    """Truncate string values that exceed max_chars."""
    if isinstance(value, str) and len(value) > max_chars:
        return f"{value[:max_chars]}... [truncated, {len(value)} chars total]"
    return value


def format_compact(
    df,
    max_rows: int | None = None,
    max_cell_chars: int | None = None,
    total_available: int | None = None,
    limit_injected: bool = False
) -> dict:
    """
    Convert DataFrame to compact format with optional truncation.

    Args:
        df: pandas DataFrame
        max_rows: If set, truncate to this many rows
        max_cell_chars: If set, truncate cell values
        total_available: Total rows available (for metadata)
        limit_injected: Whether LIMIT was auto-added

    Returns:
        Compact format dict
    """
    actual_total = len(df)
    truncated = False

    # Row truncation
    if max_rows and actual_total > max_rows:
        df = df.head(max_rows)
        truncated = True

    # Cell truncation
    if max_cell_chars:
        for col in df.columns:
            df[col] = df[col].apply(lambda x: truncate_cell(x, max_cell_chars))

    # Build result
    result = {
        "columns": df.columns.tolist(),
        "rows": df.values.tolist(),
        "row_count": len(df)
    }

    # Add truncation metadata
    if total_available is not None:
        result["total_available"] = total_available
    elif truncated:
        result["total_available"] = f"{max_rows}+"
    else:
        result["total_available"] = actual_total

    result["truncated"] = truncated
    result["limit_injected"] = limit_injected

    if truncated:
        result["note"] = (
            f"Showing {len(df)} of {result['total_available']} rows. "
            "Refine query with WHERE/GROUP BY for specific data, "
            "or use sql_query_unbounded() if you need all rows."
        )

    return result

# ============================================================================
# Tool Implementations
# ============================================================================

@simple_eddy
def smart_sql_run(
    query: str,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cell_chars: int = DEFAULT_MAX_CELL_CHARS
) -> str:
    """
    Execute SQL query with automatic row limiting and compact output.

    Automatically injects LIMIT if not present. Returns compact format:
    {
      "columns": ["col1", "col2", ...],
      "rows": [[val1, val2, ...], ...],
      "row_count": 100,
      "total_available": 5000 or "100+",
      "truncated": true/false
    }

    Use sql_query_unbounded() if you explicitly need all rows.

    Args:
        query: DuckDB-compatible SQL query
        max_rows: Maximum rows to return (default: 100)
        max_cell_chars: Truncate cell values beyond this (default: 500)
    """
    con = duckdb.connect(":memory:")

    try:
        # Check if we need to inject LIMIT
        modified_query, limit_injected = inject_limit(query, max_rows + 1)

        # Execute query
        df = con.execute(modified_query).df()

        # Determine total available
        total_available = None
        if len(df) > max_rows:
            # We got more than max_rows, so there's definitely more
            # Try to get exact count (skip for complex queries)
            total_available = get_total_count(query, con)
        else:
            # We got all rows
            total_available = len(df)

        # Format and return
        result = format_compact(
            df,
            max_rows=max_rows,
            max_cell_chars=max_cell_chars,
            total_available=total_available,
            limit_injected=limit_injected
        )

        return json.dumps(result, default=str)

    finally:
        con.close()


@simple_eddy
def sql_query_unbounded(query: str) -> str:
    """
    Execute SQL query WITHOUT row limits. Returns ALL matching rows.

    ⚠️  WARNING: Large results consume many tokens. Use with caution.

    Prefer smart_sql_run() for exploratory queries. Only use this when
    you explicitly need all rows for comprehensive analysis.

    Returns compact format (columns + rows) for token efficiency.

    Args:
        query: DuckDB-compatible SQL query
    """
    con = duckdb.connect(":memory:")

    try:
        df = con.execute(query).df()

        result = {
            "columns": df.columns.tolist(),
            "rows": df.values.tolist(),
            "row_count": len(df),
            "total_available": len(df),
            "truncated": False,
            "limit_injected": False
        }

        return json.dumps(result, default=str)

    finally:
        con.close()


# Backward compatibility alias (deprecated)
run_sql = smart_sql_run
```

### File: `windlass/windlass/__init__.py`

Add registration for the new tool:

```python
from windlass.eddies.sql import smart_sql_run, sql_query_unbounded

# ... existing registrations ...

register_tackle("smart_sql_run", smart_sql_run)
register_tackle("sql_query_unbounded", sql_query_unbounded)
```

---

## Usage Examples

### Cascade with Bounded SQL (Default)

```json
{
  "cascade_id": "analyze_sales",
  "phases": [
    {
      "name": "explore_data",
      "instructions": "Explore the sales data to understand its structure and key patterns.",
      "tackle": ["smart_sql_run"]
    }
  ]
}
```

Agent sees:
```json
{
  "columns": ["date", "product", "revenue", "quantity"],
  "rows": [
    ["2024-01-01", "Widget A", 1500.00, 30],
    ["2024-01-01", "Widget B", 2300.00, 45],
    ...
  ],
  "row_count": 100,
  "total_available": 45892,
  "truncated": true,
  "note": "Showing 100 of 45892 rows. Refine query with WHERE/GROUP BY..."
}
```

Agent can then:
- Use `GROUP BY` for aggregations
- Add `WHERE` clauses to filter
- Use `ORDER BY ... LIMIT` to get specific slices

### Cascade with Unbounded SQL (Explicit)

```json
{
  "cascade_id": "full_export",
  "phases": [
    {
      "name": "export_all",
      "instructions": "Export all user data for the compliance report.",
      "tackle": ["sql_query_unbounded"]
    }
  ]
}
```

---

## Testing Plan

### Unit Tests

```python
# tests/test_sql_tools.py

def test_compact_format_structure():
    """Verify compact format has required fields."""
    result = smart_sql_run("SELECT 1 as a, 2 as b")
    data = json.loads(result)

    assert "columns" in data
    assert "rows" in data
    assert "row_count" in data
    assert "truncated" in data
    assert data["columns"] == ["a", "b"]
    assert data["rows"] == [[1, 2]]


def test_limit_injection():
    """Verify LIMIT is injected when not present."""
    # Create table with 200 rows
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t AS SELECT i FROM range(200) t(i)")

    result = smart_sql_run("SELECT * FROM t", max_rows=50)
    data = json.loads(result)

    assert data["row_count"] == 50
    assert data["truncated"] == True
    assert data["limit_injected"] == True


def test_existing_limit_preserved():
    """Verify existing LIMIT is not modified."""
    result = smart_sql_run("SELECT 1 LIMIT 5")
    data = json.loads(result)

    assert data["limit_injected"] == False


def test_cell_truncation():
    """Verify long cell values are truncated."""
    long_text = "x" * 1000
    con = duckdb.connect(":memory:")
    con.execute(f"CREATE TABLE t AS SELECT '{long_text}' as text")

    result = smart_sql_run("SELECT * FROM t", max_cell_chars=100)
    data = json.loads(result)

    cell = data["rows"][0][0]
    assert len(cell) < 200  # Truncated + suffix
    assert "truncated" in cell


def test_unbounded_returns_all():
    """Verify unbounded tool returns all rows."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t AS SELECT i FROM range(500) t(i)")

    result = sql_query_unbounded("SELECT * FROM t")
    data = json.loads(result)

    assert data["row_count"] == 500
    assert data["truncated"] == False


def test_sqlglot_handles_cte():
    """Verify CTE queries are handled correctly."""
    query = """
    WITH ranked AS (
        SELECT *, ROW_NUMBER() OVER () as rn
        FROM (SELECT 1 as x)
    )
    SELECT * FROM ranked
    """
    result = smart_sql_run(query)
    data = json.loads(result)

    assert data["row_count"] == 1
```

### Integration Tests

```python
def test_token_reduction():
    """Measure actual token reduction from compact format."""
    # Generate test data
    con = duckdb.connect(":memory:")
    con.execute("""
        CREATE TABLE users AS
        SELECT
            i as id,
            'user_' || i as name,
            'user' || i || '@example.com' as email,
            'Bio text for user ' || i as bio
        FROM range(100) t(i)
    """)

    # Old format
    old_result = con.execute("SELECT * FROM users").df().to_json(orient='records')

    # New format
    new_result = smart_sql_run("SELECT * FROM users")

    # Compare sizes (proxy for tokens)
    old_size = len(old_result)
    new_size = len(new_result)

    reduction = (old_size - new_size) / old_size * 100
    print(f"Size reduction: {reduction:.1f}%")

    assert reduction > 30  # Expect at least 30% reduction
```

---

## Migration Notes

### Breaking Changes

1. **Output format changed** - Tools now return compact format instead of `[{...}, {...}]`
   - Existing cascades that parse SQL output will need updates
   - The structure is more explicit, so updates should be straightforward

2. **Automatic LIMIT injection** - Queries without LIMIT now get one
   - Use `sql_query_unbounded` if you need all rows
   - Or add explicit `LIMIT` to your queries

### Backward Compatibility

- `run_sql` alias maintained (deprecated, points to `smart_sql_run`)
- Agents are informed about format in tool descriptions
- Truncation metadata helps agents adapt their queries

---

## Future Enhancements

### Phase 2: Token Budget Awareness

```python
def smart_sql_run(
    query: str,
    max_rows: int = 100,
    max_cell_chars: int = 500,
    token_budget: int = None  # Future: dynamic row limit based on budget
) -> str:
```

### Phase 3: Query Suggestions

When results are truncated, suggest optimized queries:

```json
{
  "truncated": true,
  "suggestions": [
    "SELECT product, SUM(revenue) FROM sales GROUP BY product",
    "SELECT * FROM sales WHERE date > '2024-01-01' LIMIT 100",
    "SELECT COUNT(*), AVG(revenue) FROM sales"
  ]
}
```

### Phase 4: Semantic Compression

For text-heavy results, use LLM to summarize cell contents:

```json
{
  "columns": ["id", "description_summary"],
  "rows": [
    [1, "Product launch announcement (847 chars summarized)"],
    [2, "Q4 financial report highlights (2.3k chars summarized)"]
  ]
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WINDLASS_SQL_MAX_ROWS` | `100` | Default row limit for `smart_sql_run` |
| `WINDLASS_SQL_MAX_CELL_CHARS` | `500` | Default cell truncation length |

---

## Observability

All SQL operations are logged via Windlass' unified logging:

```sql
-- Find truncated queries
SELECT
    session_id,
    phase_name,
    JSONExtractInt(content_json, 'row_count') as returned,
    JSONExtractRaw(content_json, 'total_available') as available
FROM unified_logs
WHERE JSONExtractBool(content_json, 'truncated') = true
ORDER BY timestamp DESC
```

---

## Summary

| Before | After |
|--------|-------|
| Unbounded rows | 100 row default limit |
| Verbose JSON (`[{col: val}, ...]`) | Compact format (`{columns: [], rows: [[]]}`) |
| Single tool | Two tools: bounded (default) + unbounded (opt-in) |
| Regex query manipulation | sqlglot-based safe rewriting |
| No truncation metadata | Full transparency on limits |

**Token savings: ~40% on typical queries**
**Safety: Prevents accidental token explosions**
**Flexibility: Unbounded tool available when needed**
