# Data Cascades: SQL Notebook as Declarative Tools

## Implementation Plan

**Status**: Draft
**Author**: Design Session 2024-12
**Complexity**: Medium

---

## 1. Executive Summary

### Vision

Transform the existing SQL Query IDE into a dual-mode interface that supports both ad-hoc queries AND multi-step "data cascades" - reactive notebooks composed of SQL and Python cells that can be saved as reusable, callable tools.

### Key Insight

**A notebook is just a cascade with only deterministic phases.** Rather than creating a new "notebook" primitive, we leverage existing Windlass infrastructure:

- Deterministic phases already execute tools without LLM mediation
- `{{ outputs.phase_name }}` already references prior phase outputs
- Cascades with `inputs_schema` already become callable tools
- Cascades can already call other cascades

We only need **two new tools** (`sql_data`, `python_data`) and a **specialized UI** for creating data-focused cascades.

### Philosophy Alignment

This design follows core Windlass principles:

1. **Declarative over imperative** - Notebooks are YAML cascades, not procedural scripts
2. **Simple primitives compose** - Two tools + existing cascade infrastructure = full notebook system
3. **Tools all the way down** - A saved notebook IS a tool, callable from any cascade
4. **No new concepts** - Users who understand cascades already understand data notebooks

---

## 2. Current State Analysis

### What Already Exists

| Component | Location | Capabilities |
|-----------|----------|--------------|
| SQL Query UI | `dashboard/frontend/src/sql-query/` | Monaco editor, schema browser, AG-Grid results, query history |
| `smart_sql_run` tool | `windlass/sql_tools/tools.py` | Execute SQL via DuckDB ATTACH, return JSON results |
| Deterministic phases | `windlass/deterministic.py` | Direct tool execution with Jinja2 templating |
| Cascade-as-tool | `windlass/tackle.py:29-80` | Register cascades with `inputs_schema` as callable tools |
| DuckDB connector | `windlass/sql_tools/connector.py` | Multi-database ATTACH, CSV materialization |
| `set_state` tool | `windlass/eddies/state_tools.py` | Modify cascade state |

### What's Missing

| Component | Purpose |
|-----------|---------|
| `sql_data` tool | SQL execution that returns DataFrame AND materializes temp table |
| `python_data` tool | Inline Python with access to prior phase DataFrames |
| Session-scoped DuckDB | Temp tables that persist across phases within a session |
| Context injection | Pass session/phase metadata to data tools |
| Notebook UI mode | Visual editor for creating data cascades |

---

## 3. Design Specification

### 3.1 Data Cascade Format

A "data cascade" is a standard Windlass cascade YAML with only deterministic phases:

```yaml
cascade_id: "customer_cohort_analysis"
description: "Analyze customer purchase patterns by cohort"

# Makes this cascade callable as a tool
inputs_schema:
  date_range: "Date range for analysis (e.g., 'last_30_days')"
  min_purchases: "Minimum purchase threshold"
  cohort_type: "Grouping: 'monthly' or 'weekly'"

# Optional: default connection for sql_data phases
defaults:
  connection: "prod_db"

phases:
  # --- Parameter setup using existing set_state ---
  - name: "params"
    tool: "set_state"
    inputs:
      updates:
        date_start: "{{ parse_date_range(input.date_range).start }}"
        date_end: "{{ parse_date_range(input.date_range).end }}"
        threshold: "{{ input.min_purchases | int }}"

  # --- SQL Phase ---
  - name: "raw_customers"
    tool: "sql_data"
    inputs:
      connection: "prod_db"
      query: |
        SELECT
          customer_id,
          DATE_TRUNC('{{ input.cohort_type }}', first_purchase) AS cohort,
          COUNT(*) AS purchase_count,
          SUM(amount) AS total_spent
        FROM orders
        WHERE order_date BETWEEN '{{ state.date_start }}' AND '{{ state.date_end }}'
        GROUP BY customer_id, cohort
        HAVING COUNT(*) >= {{ state.threshold }}
    # Result stored in: outputs.raw_customers
    # Temp table created: _raw_customers

  # --- Python Phase ---
  - name: "add_tiers"
    tool: "python_data"
    inputs:
      code: |
        import pandas as pd

        # 'data' namespace provides prior phase DataFrames
        df = data.raw_customers

        def assign_tier(row):
            if row['total_spent'] > 1000: return 'platinum'
            elif row['purchase_count'] > 10: return 'gold'
            return 'silver'

        df['tier'] = df.apply(assign_tier, axis=1)
        result = df  # Must set 'result' variable
    # Result stored in: outputs.add_tiers
    # Temp table created: _add_tiers

  # --- SQL referencing Python output ---
  - name: "cohort_summary"
    tool: "sql_data"
    inputs:
      query: |
        SELECT
          cohort,
          tier,
          COUNT(*) AS customer_count,
          AVG(purchase_count) AS avg_purchases,
          SUM(total_spent) AS cohort_revenue
        FROM _add_tiers  -- Direct temp table reference!
        GROUP BY cohort, tier
        ORDER BY cohort, tier

# Which phase output to return when used as tool
output_phase: "cohort_summary"
```

### 3.2 Temp Table Convention

Each `sql_data` or `python_data` phase automatically creates a temp table:

- **Naming**: `_<phase_name>` (e.g., `_raw_customers`, `_add_tiers`)
- **Location**: Session-scoped DuckDB file at `/tmp/windlass_session_<session_id>.duckdb`
- **Lifecycle**: Created/updated on phase execution, cleaned up on cascade completion
- **Reference**: Downstream SQL phases can reference directly (no Jinja2 needed)

This separates concerns:
- **Jinja2** for parameter substitution: `WHERE date >= '{{ state.date_start }}'`
- **Direct table names** for data references: `FROM _add_tiers`

### 3.3 Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     Cascade Execution                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Phase: raw_customers                                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ sql_data(query="SELECT...")                              │   │
│  │   ↓                                                      │   │
│  │ 1. Render Jinja2 ({{ state.* }}, {{ input.* }})         │   │
│  │ 2. Execute via DuckDB ATTACH                            │   │
│  │ 3. Store result in outputs.raw_customers                │   │
│  │ 4. Materialize to _raw_customers temp table             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  Phase: add_tiers                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ python_data(code="df = data.raw_customers...")           │   │
│  │   ↓                                                      │   │
│  │ 1. Build 'data' namespace from prior outputs            │   │
│  │ 2. Execute Python code                                   │   │
│  │ 3. Store result in outputs.add_tiers                    │   │
│  │ 4. Materialize DataFrame to _add_tiers temp table       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  Phase: cohort_summary                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ sql_data(query="SELECT ... FROM _add_tiers")             │   │
│  │   ↓                                                      │   │
│  │ 1. Query references _add_tiers temp table directly       │   │
│  │ 2. No Jinja2 needed for data references                 │   │
│  │ 3. Store result in outputs.cohort_summary               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Technical Specification

### 4.1 `sql_data` Tool

**File**: `windlass/eddies/data_tools.py` (new file)

```python
"""
Data-focused tools for SQL notebooks / data cascades.

These tools support the "notebook" pattern where phases produce DataFrames
that can be referenced by downstream phases via temp tables.
"""

import pandas as pd
from typing import Optional, Dict, Any
from ..tackle import register_tackle
from ..sql_tools.tools import run_sql
from .base import simple_eddy


def get_session_duckdb(session_id: str):
    """Get or create session-scoped DuckDB for temp tables."""
    from ..sql_tools.session_db import get_session_db
    return get_session_db(session_id)


@simple_eddy
def sql_data(
    query: str,
    connection: str = None,
    limit: int = 10000,
    materialize: bool = True,
    _phase_name: str = None,
    _session_id: str = None
) -> Dict[str, Any]:
    """
    Execute SQL query and return results as DataFrame.

    Optionally materializes result as a temp table named '_<phase_name>'
    for downstream SQL phases to reference directly.

    Args:
        query: SQL query to execute (Jinja2 already rendered by deterministic executor)
        connection: Database connection name. If None, uses session DuckDB only.
        limit: Maximum rows to return (default 10000)
        materialize: If True, create temp table for downstream references
        _phase_name: Injected by runner - used for temp table naming
        _session_id: Injected by runner - used for session DuckDB

    Returns:
        {
            "dataframe": pd.DataFrame,
            "rows": List[Dict],  # For JSON serialization
            "columns": List[str],
            "row_count": int,
            "_route": "success" | "error"
        }

    Example cascade usage:
        phases:
          - name: "customers"
            tool: "sql_data"
            inputs:
              connection: "prod_db"
              query: |
                SELECT * FROM users WHERE created_at > '{{ state.start_date }}'

          - name: "orders"
            tool: "sql_data"
            inputs:
              query: |
                SELECT o.* FROM orders o
                JOIN _customers c ON o.user_id = c.id  -- Reference temp table!
    """
    try:
        # Get session DuckDB for temp table operations
        session_db = None
        if _session_id:
            session_db = get_session_duckdb(_session_id)

        # If we have a connection, use the standard run_sql
        if connection:
            result = run_sql(query, connection, limit)

            if "error" in result and result["error"]:
                return {
                    "_route": "error",
                    "error": result["error"]
                }

            # Convert to DataFrame
            df = pd.DataFrame(result.get("results", []))
        else:
            # Query directly against session DuckDB (for temp table queries)
            if not session_db:
                return {
                    "_route": "error",
                    "error": "No connection specified and no session DuckDB available"
                }
            df = session_db.execute(query).fetchdf()
            if limit:
                df = df.head(limit)

        # Materialize as temp table for downstream phases
        if materialize and _phase_name and session_db:
            table_name = f"_{_phase_name}"
            # Register DataFrame and create table
            session_db.register("_temp_df", df)
            session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
            session_db.unregister("_temp_df")

        return {
            "dataframe": df,
            "rows": df.to_dict('records'),
            "columns": list(df.columns),
            "row_count": len(df),
            "_route": "success"
        }

    except Exception as e:
        return {
            "_route": "error",
            "error": str(e)
        }


# Register the tool
register_tackle("sql_data", sql_data)
```

### 4.2 `python_data` Tool

**File**: `windlass/eddies/data_tools.py` (same file, continued)

```python
class DataNamespace:
    """
    Namespace object that provides access to prior phase DataFrames.

    Usage in python_data code:
        df = data.raw_customers      # Get DataFrame from prior phase
        df = data['raw_customers']   # Alternative dict-style access
    """

    def __init__(self, outputs: Dict[str, Any], session_db=None):
        self._outputs = outputs
        self._session_db = session_db
        self._cache = {}

    def __getattr__(self, name: str) -> pd.DataFrame:
        if name.startswith('_'):
            raise AttributeError(name)
        return self._get_dataframe(name)

    def __getitem__(self, name: str) -> pd.DataFrame:
        return self._get_dataframe(name)

    def _get_dataframe(self, name: str) -> pd.DataFrame:
        # Check cache first
        if name in self._cache:
            return self._cache[name]

        # Try to get from outputs
        output = self._outputs.get(name)

        if output is None:
            # Try loading from temp table if session_db available
            if self._session_db:
                try:
                    df = self._session_db.execute(f"SELECT * FROM _{name}").fetchdf()
                    self._cache[name] = df
                    return df
                except:
                    pass
            raise AttributeError(f"No data found for phase '{name}'")

        # Extract DataFrame from various output formats
        if isinstance(output, pd.DataFrame):
            df = output
        elif isinstance(output, dict):
            if 'dataframe' in output:
                df = output['dataframe']
            elif 'rows' in output:
                df = pd.DataFrame(output['rows'])
            elif 'result' in output and isinstance(output['result'], pd.DataFrame):
                df = output['result']
            else:
                # Assume dict is the data itself
                df = pd.DataFrame([output]) if not isinstance(output, list) else pd.DataFrame(output)
        elif isinstance(output, list):
            df = pd.DataFrame(output)
        else:
            raise TypeError(f"Cannot convert output of phase '{name}' to DataFrame")

        self._cache[name] = df
        return df

    def list_available(self) -> list:
        """List all available phase names."""
        return list(self._outputs.keys())


@simple_eddy
def python_data(
    code: str,
    _outputs: Dict[str, Any] = None,
    _state: Dict[str, Any] = None,
    _input: Dict[str, Any] = None,
    _phase_name: str = None,
    _session_id: str = None
) -> Dict[str, Any]:
    """
    Execute inline Python code with access to prior phase DataFrames.

    The code environment includes:
        - data.<phase_name>: DataFrame from prior sql_data/python_data phases
        - data['phase_name']: Alternative dict-style access
        - state: Current cascade state dict (read-only recommended)
        - input: Original cascade input dict
        - pd: pandas module
        - np: numpy module
        - json: json module

    The code MUST set a 'result' variable as its output.
    If result is a DataFrame, it will be materialized as a temp table.

    Args:
        code: Python code to execute
        _outputs: Injected by runner - all prior phase outputs
        _state: Injected by runner - current cascade state
        _input: Injected by runner - original cascade input
        _phase_name: Injected by runner - current phase name
        _session_id: Injected by runner - session ID for temp tables

    Returns:
        {
            "result": <the result value>,
            "dataframe": pd.DataFrame (if result is DataFrame),
            "rows": List[Dict] (if result is DataFrame),
            "type": "dataframe" | "dict" | "list" | "scalar",
            "_route": "success" | "error"
        }

    Example cascade usage:
        phases:
          - name: "transform"
            tool: "python_data"
            inputs:
              code: |
                df = data.raw_customers
                df['tier'] = df['spend'].apply(lambda x: 'gold' if x > 1000 else 'silver')
                result = df
    """
    import numpy as np
    import json as json_module

    try:
        # Get session DuckDB
        session_db = None
        if _session_id:
            session_db = get_session_duckdb(_session_id)

        # Build data namespace
        data = DataNamespace(_outputs or {}, session_db)

        # Build execution environment
        exec_globals = {
            'data': data,
            'state': _state or {},
            'input': _input or {},
            'pd': pd,
            'np': np,
            'json': json_module,
            # Common utilities
            'print': print,  # Allow debugging
        }
        exec_locals = {}

        # Execute the code
        exec(code, exec_globals, exec_locals)

        # Extract result
        if 'result' not in exec_locals:
            return {
                "_route": "error",
                "error": "Code must set a 'result' variable. Example: result = df"
            }

        result = exec_locals['result']

        # Determine result type and format response
        if isinstance(result, pd.DataFrame):
            # Materialize as temp table
            if _phase_name and session_db:
                table_name = f"_{_phase_name}"
                session_db.register("_temp_df", result)
                session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
                session_db.unregister("_temp_df")

            return {
                "result": result,
                "dataframe": result,
                "rows": result.to_dict('records'),
                "columns": list(result.columns),
                "row_count": len(result),
                "type": "dataframe",
                "_route": "success"
            }

        elif isinstance(result, dict):
            return {
                "result": result,
                "type": "dict",
                "_route": "success"
            }

        elif isinstance(result, list):
            return {
                "result": result,
                "type": "list",
                "_route": "success"
            }

        else:
            return {
                "result": result,
                "type": "scalar",
                "_route": "success"
            }

    except Exception as e:
        import traceback
        return {
            "_route": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


# Register the tool
register_tackle("python_data", python_data)
```

### 4.3 Session-Scoped DuckDB Manager

**File**: `windlass/sql_tools/session_db.py` (new file)

```python
"""
Session-scoped DuckDB instances for data cascade temp tables.

Each cascade execution gets its own DuckDB instance where temp tables
persist across phases. Tables are named _<phase_name> by convention.
"""

import os
import duckdb
import atexit
from typing import Dict, Optional
from threading import Lock

# Global registry of session databases
_session_dbs: Dict[str, duckdb.DuckDBPyConnection] = {}
_session_db_lock = Lock()

# Directory for session database files
SESSION_DB_DIR = "/tmp/windlass_sessions"


def get_session_db(session_id: str) -> duckdb.DuckDBPyConnection:
    """
    Get or create a DuckDB connection for the given session.

    The database file persists at /tmp/windlass_sessions/<session_id>.duckdb
    and contains all temp tables created during the cascade execution.

    Args:
        session_id: Unique session identifier

    Returns:
        DuckDB connection for this session
    """
    with _session_db_lock:
        if session_id not in _session_dbs:
            # Ensure directory exists
            os.makedirs(SESSION_DB_DIR, exist_ok=True)

            # Create or open session database
            db_path = os.path.join(SESSION_DB_DIR, f"{session_id}.duckdb")
            conn = duckdb.connect(db_path)

            # Configure for our use case
            conn.execute("SET threads TO 4")

            _session_dbs[session_id] = conn

        return _session_dbs[session_id]


def cleanup_session_db(session_id: str, delete_file: bool = True):
    """
    Clean up a session's DuckDB resources.

    Called when a cascade completes to free resources.

    Args:
        session_id: Session to clean up
        delete_file: If True, delete the database file
    """
    with _session_db_lock:
        if session_id in _session_dbs:
            conn = _session_dbs.pop(session_id)
            try:
                conn.close()
            except:
                pass

            if delete_file:
                db_path = os.path.join(SESSION_DB_DIR, f"{session_id}.duckdb")
                try:
                    if os.path.exists(db_path):
                        os.remove(db_path)
                    # Also remove WAL file if present
                    wal_path = db_path + ".wal"
                    if os.path.exists(wal_path):
                        os.remove(wal_path)
                except:
                    pass


def list_session_tables(session_id: str) -> list:
    """
    List all tables in a session's DuckDB.

    Useful for debugging and introspection.

    Args:
        session_id: Session to inspect

    Returns:
        List of table names
    """
    try:
        conn = get_session_db(session_id)
        result = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
        return [row[0] for row in result]
    except:
        return []


def get_session_table(session_id: str, table_name: str):
    """
    Get a DataFrame from a session temp table.

    Args:
        session_id: Session ID
        table_name: Table name (with or without _ prefix)

    Returns:
        pandas DataFrame
    """
    conn = get_session_db(session_id)
    # Normalize table name
    if not table_name.startswith('_'):
        table_name = f"_{table_name}"
    return conn.execute(f"SELECT * FROM {table_name}").fetchdf()


# Cleanup on process exit
@atexit.register
def _cleanup_all_sessions():
    """Clean up all session databases on process exit."""
    with _session_db_lock:
        for session_id in list(_session_dbs.keys()):
            cleanup_session_db(session_id, delete_file=True)
```

### 4.4 Deterministic Executor Enhancement

**File**: `windlass/deterministic.py`

**Changes needed** in `execute_deterministic_phase()` function:

```python
# After line 449 (after rendering inputs), add context injection for data tools:

def execute_deterministic_phase(
    phase: PhaseConfig,
    input_data: Dict[str, Any],
    echo: Any,
    config_path: str = None,
    depth: int = 0
) -> Tuple[Any, Optional[str]]:
    # ... existing code up to line 449 ...

    # Render inputs
    try:
        rendered_inputs = render_inputs(phase.tool_inputs, render_context)
        console.print(f"{indent}  [dim]Inputs: {list(rendered_inputs.keys())}[/dim]")
    except Exception as e:
        # ... existing error handling ...

    # === NEW: Inject context for data tools ===
    if phase.tool in ("sql_data", "python_data"):
        # Inject session and phase metadata
        rendered_inputs["_phase_name"] = phase.name
        rendered_inputs["_session_id"] = echo.session_id

        # python_data needs access to outputs and state
        if phase.tool == "python_data":
            rendered_inputs["_outputs"] = outputs  # Dict of phase_name -> output
            rendered_inputs["_state"] = echo.state
            rendered_inputs["_input"] = input_data
    # === END NEW ===

    # Parse timeout
    timeout_seconds = parse_timeout(phase.timeout)

    # ... rest of existing function ...
```

### 4.5 Runner Cleanup Hook

**File**: `windlass/runner.py`

Add cleanup call at end of cascade execution:

```python
# In WindlassRunner.run() or run_cascade(), after execution completes:

def run_cascade(...):
    # ... existing execution code ...

    try:
        result = runner.run()
    finally:
        # Clean up session DuckDB
        from .sql_tools.session_db import cleanup_session_db
        cleanup_session_db(session_id, delete_file=True)

    return result
```

---

## 5. UI Specification

### 5.1 Mode Toggle

Add a mode toggle to the SQL Query page header:

```jsx
// In SqlQueryPage.js header
<div className="mode-toggle">
  <button
    className={mode === 'query' ? 'active' : ''}
    onClick={() => setMode('query')}
  >
    Query
  </button>
  <button
    className={mode === 'notebook' ? 'active' : ''}
    onClick={() => setMode('notebook')}
  >
    Notebook
  </button>
</div>
```

### 5.2 Notebook Mode Layout

```
┌────────────────────────────────────────────────────────────────────────┐
│ SQL Query IDE                         [Query] [Notebook ●]  [+ Cell]  │
├────────────────────────────────────────────────────────────────────────┤
│ Schema    │  notebook_name.yaml                            [▶ Run All]│
│ Browser   │ ┌────────────────────────────────────────────────────────┐│
│           │ │ Inputs                                                 ││
│ ├─prod_db │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    ││
│ │ ├─orders│ │ │ date_range   │ │ min_purchases│ │ cohort_type  │    ││
│ │ └─users │ │ │ [last_30d  ▾]│ │ [5         ] │ │ [monthly   ▾]│    ││
│           │ │ └──────────────┘ └──────────────┘ └──────────────┘    ││
│           │ └────────────────────────────────────────────────────────┘│
│           │                                                           │
│           │ ┌────────────────────────────────────────────────────────┐│
│           │ │ ┌─[SQL]─────────────────────────────────────┐ [▶] ✓   ││
│           │ │ │ raw_customers                              │ 1,234   ││
│           │ │ │ ─────────────────────────────────────────  │         ││
│           │ │ │ SELECT customer_id, COUNT(*) as purchases  │         ││
│           │ │ │ FROM orders                                │         ││
│           │ │ │ WHERE date >= '{{ state.date_start }}'     │         ││
│           │ │ │ GROUP BY customer_id                       │         ││
│           │ │ └────────────────────────────────────────────┘         ││
│           │ │                      │                                  ││
│           │ │                      ▼                                  ││
│           │ │ ┌─[Python]───────────────────────────────────┐ [▶] ✓   ││
│           │ │ │ add_tiers                                  │ 1,234   ││
│           │ │ │ ─────────────────────────────────────────  │         ││
│           │ │ │ df = data.raw_customers                    │         ││
│           │ │ │ df['tier'] = df['purchases'].apply(...)    │         ││
│           │ │ │ result = df                                │         ││
│           │ │ └────────────────────────────────────────────┘         ││
│           │ │                      │                                  ││
│           │ │                      ▼                                  ││
│           │ │ ┌─[SQL]─────────────────────────────────────┐ [▶] ●    ││
│           │ │ │ cohort_summary                             │ running ││
│           │ │ │ ─────────────────────────────────────────  │         ││
│           │ │ │ SELECT tier, COUNT(*) FROM _add_tiers      │         ││
│           │ │ │ GROUP BY tier                              │         ││
│           │ │ └────────────────────────────────────────────┘         ││
│           │ └────────────────────────────────────────────────────────┘│
├───────────┼───────────────────────────────────────────────────────────┤
│ [+ SQL]   │ Results: cohort_summary                                   │
│ [+ Python]│ ┌────────────────────────────────────────────────────────┐│
│           │ │ tier     │ count │ avg_purchases │ total_revenue       ││
│           │ │ platinum │    12 │         18.3 │       $15,420        ││
│           │ │ gold     │    45 │         12.1 │       $28,350        ││
│           │ │ silver   │   156 │          3.2 │        $8,900        ││
│           │ └────────────────────────────────────────────────────────┘│
│           │                                                           │
│           │ [Save as Tool] [Export YAML] [Export CSV] [Copy Results]  │
└───────────┴───────────────────────────────────────────────────────────┘
```

### 5.3 New Components

| Component | File | Purpose |
|-----------|------|---------|
| `NotebookEditor` | `sql-query/components/NotebookEditor.js` | Container for notebook mode |
| `NotebookCell` | `sql-query/components/NotebookCell.js` | Individual SQL/Python cell |
| `CellEditor` | `sql-query/components/CellEditor.js` | Monaco editor wrapper with type toggle |
| `InputsForm` | `sql-query/components/InputsForm.js` | Dynamic form from inputs_schema |
| `CellResultPreview` | `sql-query/components/CellResultPreview.js` | Inline result preview |

### 5.4 Zustand Store Extensions

```javascript
// In sqlQueryStore.js, add notebook state:

const useNotebookStore = create((set, get) => ({
  // Existing query state...

  // Notebook mode
  mode: 'query',  // 'query' | 'notebook'
  setMode: (mode) => set({ mode }),

  // Current notebook
  notebook: null,  // { cascade_id, description, inputs_schema, phases, ... }
  notebookPath: null,
  notebookDirty: false,

  // Notebook inputs (filled by user)
  notebookInputs: {},
  setNotebookInput: (key, value) => set(state => ({
    notebookInputs: { ...state.notebookInputs, [key]: value }
  })),

  // Cell execution state
  cellStates: {},  // { [phaseName]: { status, result, error, duration } }
  setCellState: (phaseName, cellState) => set(state => ({
    cellStates: { ...state.cellStates, [phaseName]: cellState }
  })),

  // Actions
  loadNotebook: async (path) => { /* Load YAML, parse, set state */ },
  saveNotebook: async (path) => { /* Serialize to YAML, save */ },
  addCell: (type, afterIndex) => { /* Add SQL or Python cell */ },
  removeCell: (index) => { /* Remove cell */ },
  moveCell: (fromIndex, toIndex) => { /* Reorder */ },
  updateCell: (index, updates) => { /* Update cell content */ },

  // Execution
  runCell: async (phaseName) => { /* Execute single cell via API */ },
  runAllCells: async () => { /* Execute full cascade via API */ },
  runFromCell: async (phaseName) => { /* Execute from cell onwards */ },
}));
```

### 5.5 Backend API Endpoints

```python
# In dashboard/backend/artifacts_api.py, add:

@artifacts_bp.route('/api/notebook/run', methods=['POST'])
def run_notebook():
    """Execute a data cascade and return results."""
    data = request.json
    notebook_yaml = data.get('notebook')  # YAML string or path
    inputs = data.get('inputs', {})
    from_phase = data.get('from_phase')  # Optional: start from specific phase

    # Save to temp file if YAML string
    # Execute via windlass.run_cascade()
    # Return { phases: { [name]: { result, duration, error } }, output: ... }


@artifacts_bp.route('/api/notebook/run-cell', methods=['POST'])
def run_notebook_cell():
    """Execute a single cell in isolation (for interactive editing)."""
    data = request.json
    cell = data.get('cell')  # { type, name, query/code, connection }
    inputs = data.get('inputs', {})
    prior_outputs = data.get('prior_outputs', {})  # Serialized DataFrames
    session_id = data.get('session_id')

    # Execute single tool call with injected context
    # Return { result, rows, columns, error }


@artifacts_bp.route('/api/notebook/save', methods=['POST'])
def save_notebook():
    """Save notebook as YAML to tackle/ directory."""
    data = request.json
    notebook = data.get('notebook')
    path = data.get('path')  # e.g., 'tackle/my_analysis.yaml'

    # Validate and save
    # Return { success, path }


@artifacts_bp.route('/api/notebook/list', methods=['GET'])
def list_notebooks():
    """List all data cascades (cascades with only deterministic phases)."""
    # Scan tackle/ and cascades/ for data-only cascades
    # Return [{ cascade_id, description, path, inputs_schema }]
```

---

## 6. Implementation Phases

### Phase 1: Core Tools (Backend)

**Goal**: `sql_data` and `python_data` tools working via CLI

**Tasks**:
1. Create `windlass/sql_tools/session_db.py` - session DuckDB manager
2. Create `windlass/eddies/data_tools.py` - both tools
3. Modify `windlass/deterministic.py` - context injection
4. Modify `windlass/runner.py` - cleanup hook
5. Add `from .eddies.data_tools import *` to `windlass/__init__.py`
6. Test via CLI: `windlass run examples/data_cascade_test.yaml --input '{}'`

**Validation**:
```bash
# Create test cascade
cat > examples/data_cascade_test.yaml << 'EOF'
cascade_id: "data_test"
description: "Test data cascade tools"
inputs_schema:
  threshold: "Minimum value"

phases:
  - name: "generate"
    tool: "sql_data"
    inputs:
      query: |
        SELECT * FROM (VALUES (1, 'a'), (2, 'b'), (3, 'c')) AS t(id, name)
        WHERE id >= {{ input.threshold | int }}

  - name: "transform"
    tool: "python_data"
    inputs:
      code: |
        df = data.generate
        df['upper_name'] = df['name'].str.upper()
        result = df

  - name: "final"
    tool: "sql_data"
    inputs:
      query: |
        SELECT * FROM _transform ORDER BY id DESC
EOF

# Run it
windlass run examples/data_cascade_test.yaml --input '{"threshold": "2"}'
```

### Phase 2: CLI Enhancements

**Goal**: Better CLI support for data cascades

**Tasks**:
1. Add `--output-format` flag (json, csv, parquet, table)
2. Add `--from-phase` flag for partial execution
3. Add `windlass notebook` subcommand for notebook-specific operations
4. Add `--save-outputs` to persist intermediate DataFrames

**Commands**:
```bash
# Run with CSV output
windlass run analysis.yaml --input '{}' --output-format csv > results.csv

# Run from specific phase (uses cached prior outputs)
windlass run analysis.yaml --input '{}' --from-phase transform

# List data cascades
windlass notebook list

# Validate a data cascade
windlass notebook validate analysis.yaml
```

### Phase 3: UI - Basic Notebook Mode

**Goal**: Notebook UI that can load, edit, and run data cascades

**Tasks**:
1. Add mode toggle to SqlQueryPage header
2. Create NotebookEditor container component
3. Create NotebookCell component with type badge and run button
4. Create InputsForm for dynamic input rendering
5. Add notebook state to Zustand store
6. Add `/api/notebook/run` endpoint
7. Add `/api/notebook/list` endpoint
8. Integrate AG-Grid for cell results

### Phase 4: UI - Full Features

**Goal**: Complete notebook experience

**Tasks**:
1. Cell CRUD (add, remove, reorder via drag-drop)
2. Save/load notebooks from filesystem
3. "Save as Tool" button (saves to `tackle/`)
4. Cell status indicators (pending, running, success, error, stale)
5. Inline result previews (collapsible)
6. Monaco autocomplete for `data.<phase>` and `_<phase>` references
7. DAG visualization mini-map
8. "Run from here" context action
9. Export results (CSV, Parquet, JSON)

### Phase 5: Polish & Advanced Features

**Goal**: Production-ready experience

**Tasks**:
1. Stale detection (mark downstream cells when upstream changes)
2. Cell-level caching (skip re-execution if inputs unchanged)
3. Keyboard shortcuts (Ctrl+Enter to run cell, etc.)
4. Undo/redo for cell edits
5. Cell templates (common patterns)
6. Import existing SQL queries as cells
7. Documentation/help panel

---

## 7. File Structure

```
windlass/
├── eddies/
│   ├── data_tools.py          # NEW: sql_data, python_data tools
│   └── ...
├── sql_tools/
│   ├── session_db.py          # NEW: session-scoped DuckDB
│   ├── connector.py           # Existing (no changes)
│   └── tools.py               # Existing (no changes)
├── deterministic.py           # MODIFY: context injection
├── runner.py                  # MODIFY: cleanup hook
└── __init__.py                # MODIFY: import data_tools

dashboard/
├── backend/
│   └── artifacts_api.py       # MODIFY: add notebook endpoints
└── frontend/
    └── src/
        └── sql-query/
            ├── SqlQueryPage.js           # MODIFY: add mode toggle
            ├── stores/
            │   └── sqlQueryStore.js      # MODIFY: add notebook state
            └── components/
                ├── NotebookEditor.js     # NEW
                ├── NotebookCell.js       # NEW
                ├── CellEditor.js         # NEW
                ├── InputsForm.js         # NEW
                └── CellResultPreview.js  # NEW

examples/
└── data_cascade_test.yaml     # NEW: test cascade
```

---

## 8. Testing Strategy

### Unit Tests

```python
# tests/test_data_tools.py

def test_sql_data_basic():
    """sql_data executes query and returns DataFrame."""
    result = sql_data(
        query="SELECT 1 as a, 2 as b",
        _phase_name="test",
        _session_id="test_session"
    )
    assert result["_route"] == "success"
    assert result["row_count"] == 1
    assert list(result["dataframe"].columns) == ["a", "b"]


def test_sql_data_creates_temp_table():
    """sql_data materializes result as temp table."""
    sql_data(
        query="SELECT 1 as x",
        _phase_name="source",
        _session_id="test_session"
    )

    # Query the temp table
    result = sql_data(
        query="SELECT * FROM _source",
        _phase_name="downstream",
        _session_id="test_session"
    )
    assert result["row_count"] == 1


def test_python_data_basic():
    """python_data executes code and returns result."""
    result = python_data(
        code="result = {'key': 'value'}",
        _outputs={},
        _phase_name="test",
        _session_id="test_session"
    )
    assert result["_route"] == "success"
    assert result["result"] == {"key": "value"}
    assert result["type"] == "dict"


def test_python_data_accesses_prior_outputs():
    """python_data can access prior phase DataFrames via data namespace."""
    import pandas as pd

    prior_df = pd.DataFrame({"a": [1, 2, 3]})
    result = python_data(
        code="result = len(data.prior_phase)",
        _outputs={"prior_phase": {"dataframe": prior_df}},
        _phase_name="test",
        _session_id="test_session"
    )
    assert result["result"] == 3


def test_python_data_creates_temp_table():
    """python_data materializes DataFrame result as temp table."""
    python_data(
        code="import pandas as pd; result = pd.DataFrame({'x': [1,2,3]})",
        _outputs={},
        _phase_name="py_source",
        _session_id="test_session"
    )

    # Query the temp table from SQL
    result = sql_data(
        query="SELECT * FROM _py_source",
        _phase_name="downstream",
        _session_id="test_session"
    )
    assert result["row_count"] == 3
```

### Integration Tests

```python
# tests/test_data_cascade.py

def test_full_data_cascade():
    """Full data cascade executes and produces expected output."""
    from windlass import run_cascade

    result = run_cascade(
        "examples/data_cascade_test.yaml",
        {"threshold": "2"},
        session_id="integration_test"
    )

    # Check final output
    assert "lineage" in result
    final_output = result["lineage"][-1]["output"]
    assert final_output["row_count"] == 2  # Only rows >= 2
```

### UI Tests

```javascript
// frontend/src/sql-query/__tests__/NotebookEditor.test.js

test('notebook mode toggle switches views', () => {
  render(<SqlQueryPage />);

  // Start in query mode
  expect(screen.getByText('Query')).toHaveClass('active');

  // Switch to notebook mode
  fireEvent.click(screen.getByText('Notebook'));
  expect(screen.getByText('Notebook')).toHaveClass('active');
  expect(screen.getByTestId('notebook-editor')).toBeInTheDocument();
});

test('notebook loads cells from YAML', async () => {
  const mockNotebook = {
    cascade_id: 'test',
    phases: [
      { name: 'cell1', tool: 'sql_data', inputs: { query: 'SELECT 1' } }
    ]
  };

  render(<NotebookEditor notebook={mockNotebook} />);

  expect(screen.getByText('cell1')).toBeInTheDocument();
  expect(screen.getByText('SQL')).toBeInTheDocument();
});
```

---

## 9. Future Considerations

### Not in Scope (Future Work)

1. **Python sandboxing** - Currently runs with full system access. Could add RestrictedPython later.

2. **Collaborative editing** - Real-time multi-user notebook editing.

3. **Scheduled execution** - Cron-like scheduling for data pipelines.

4. **Version control integration** - Git-aware notebook diffing.

5. **Data lineage visualization** - Full DAG of data dependencies across cascades.

6. **Caching layer** - Persistent caching of cell outputs across sessions.

7. **Streaming results** - SSE for large query progress.

### Migration Path

Existing `smart_sql_run` users are unaffected. The new `sql_data` tool is additive and can coexist.

For notebooks:
- Export as YAML to `tackle/` directory
- Automatically registered as tools
- Callable from any cascade

---

## 10. Success Criteria

### Phase 1 Complete When:
- [ ] `sql_data` tool executes queries and creates temp tables
- [ ] `python_data` tool executes code with `data.*` namespace
- [ ] Temp tables persist across phases within session
- [ ] Session cleanup happens on cascade completion
- [ ] Test cascade runs successfully via CLI

### Phase 2 Complete When:
- [ ] `--output-format` flag works for csv, json, parquet
- [ ] `--from-phase` flag skips prior phases
- [ ] `windlass notebook list` shows data cascades

### Phase 3 Complete When:
- [ ] Mode toggle switches between Query and Notebook views
- [ ] Notebooks load from YAML files
- [ ] Cells display with type badges and run buttons
- [ ] Inputs form renders from schema
- [ ] "Run All" executes full cascade
- [ ] Results display in AG-Grid

### Phase 4 Complete When:
- [ ] Cells can be added, removed, reordered
- [ ] Save/load works with filesystem
- [ ] "Save as Tool" exports to tackle/
- [ ] Cell status indicators work
- [ ] Inline previews show for each cell

### Full Feature Complete When:
- [ ] Stale detection marks downstream cells
- [ ] Autocomplete works for `data.` and `_` references
- [ ] All keyboard shortcuts functional
- [ ] Documentation complete

---

## Appendix A: Example Data Cascades

### A.1 Simple Analysis

```yaml
cascade_id: "simple_analysis"
description: "Basic customer analysis"
inputs_schema:
  min_orders: "Minimum order count"

phases:
  - name: "customers"
    tool: "sql_data"
    inputs:
      connection: "prod_db"
      query: |
        SELECT customer_id, COUNT(*) as order_count
        FROM orders
        GROUP BY customer_id
        HAVING COUNT(*) >= {{ input.min_orders | int }}

  - name: "summary"
    tool: "python_data"
    inputs:
      code: |
        df = data.customers
        result = {
            "total_customers": len(df),
            "avg_orders": df['order_count'].mean(),
            "max_orders": df['order_count'].max()
        }
```

### A.2 Multi-Source Join

```yaml
cascade_id: "multi_source_join"
description: "Join data from multiple databases"
inputs_schema:
  date: "Analysis date"

phases:
  - name: "users"
    tool: "sql_data"
    inputs:
      connection: "postgres_prod"
      query: |
        SELECT id, email, created_at
        FROM users
        WHERE created_at::date = '{{ input.date }}'

  - name: "events"
    tool: "sql_data"
    inputs:
      connection: "clickhouse_analytics"
      query: |
        SELECT user_id, count() as event_count
        FROM events
        WHERE toDate(timestamp) = '{{ input.date }}'
        GROUP BY user_id

  - name: "joined"
    tool: "sql_data"
    inputs:
      query: |
        SELECT u.*, COALESCE(e.event_count, 0) as events
        FROM _users u
        LEFT JOIN _events e ON u.id = e.user_id
```

### A.3 Chained Cascade Tool

```yaml
cascade_id: "daily_report"
description: "Generate daily business report"
inputs_schema:
  date: "Report date"

phases:
  - name: "user_analysis"
    tool: "simple_analysis"  # Another data cascade!
    inputs:
      min_orders: "1"

  - name: "revenue"
    tool: "sql_data"
    inputs:
      connection: "prod_db"
      query: |
        SELECT SUM(amount) as total_revenue
        FROM orders
        WHERE order_date = '{{ input.date }}'

  - name: "report"
    tool: "python_data"
    inputs:
      code: |
        result = {
            "date": input['date'],
            "user_stats": data.user_analysis,
            "revenue": data.revenue.iloc[0]['total_revenue']
        }
```

---

*End of Implementation Plan*
