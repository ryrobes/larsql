# Session-Scoped Temp Tables - Global System

## Overview

Windlass now provides **session-scoped temporary tables** that work everywhere:
- ✅ CLI cascade runs
- ✅ Studio notebook executions
- ✅ Sub-cascades and nested executions
- ✅ All polyglot tools (SQL, Python, JavaScript, Clojure)

Each cascade execution gets its own DuckDB database where temp tables persist across phases.

## How It Works

### 1. Automatic Materialization

Every data phase automatically creates a temp table named `_<phase_name>`:

```yaml
phases:
  - name: raw_customers
    tool: sql_data
    inputs:
      connection: prod_db
      query: SELECT * FROM customers WHERE active = true
    # Creates temp table: _raw_customers

  - name: enriched_data
    tool: python_data
    inputs:
      code: |
        df = data.raw_customers  # Access as DataFrame in Python
        df['score'] = df['purchases'] * 10
        result = df
    # Creates temp table: _enriched_data

  - name: analysis
    tool: sql_data
    inputs:
      query: |
        -- Query temp tables from prior phases!
        SELECT category, AVG(score) as avg_score
        FROM _enriched_data
        GROUP BY category
```

### 2. Cross-Language Data Flow

Each language has access to prior phase outputs:

**SQL** (`sql_data`):
```sql
SELECT * FROM _prior_phase_name
```

**Python** (`python_data`):
```python
df = data.prior_phase_name  # Returns pandas DataFrame
```

**JavaScript** (`js_data`):
```javascript
const rows = data.prior_phase_name;  // Array of objects
```

**Clojure** (`clojure_data`):
```clojure
(let [rows (:prior-phase-name data)])  ; Vector of maps (kebab-case!)
```

### 3. Session Database Location

Temp tables are stored in: `$WINDLASS_ROOT/session_dbs/<session_id>.duckdb`

**Persistence**:
- ✅ Survives cascade completion (for replay/debugging)
- ✅ Shared across all phases in same session
- ✅ Queryable after execution completes
- ✅ Stored in project directory (not /tmp)
- ✅ Git-ignorable, but can be versioned if desired
- ⚠️  Manually cleanup when done (or Studio auto-cleans on restart)

## Files Modified

### Core System
- `windlass/windlass/deterministic.py:466-479` - Injects `_phase_name` and `_session_id` for ALL data tools
- `windlass/windlass/runner.py:4345-4352` - Changed cleanup to NOT delete files (keep for replay)
- `windlass/windlass/eddies/data_tools.py` - All tools materialize to temp tables when session_db available

### Already Existing (Just Fixed)
- `windlass/sql_tools/session_db.py` - Session-scoped DuckDB management (already existed!)
- All data tools (`sql_data`, `python_data`, `js_data`, `clojure_data`) - Already had materialization code!

## What Was Broken (Now Fixed)

### Before
- ❌ Only `sql_data` and `python_data` got `_phase_name`/`_session_id` injected
- ❌ `js_data` and `clojure_data` couldn't create temp tables
- ❌ Session databases deleted immediately after cascade finished
- ❌ Temp tables only worked in Studio, not CLI

### After
- ✅ ALL data tools get proper parameter injection
- ✅ ALL data tools create temp tables
- ✅ Session databases persist after completion
- ✅ Works globally (CLI, Studio, sub-cascades)

## Testing

### CLI Test
```bash
# Run a polyglot cascade
windlass examples/notebook_polyglot_showcase.yaml --session my_test

# Inspect temp tables after completion
python3 -c "
from windlass.sql_tools.session_db import get_session_db
db = get_session_db('my_test')
tables = db.execute('SHOW TABLES').fetchall()
print('Temp tables created:')
for row in tables: print(f'  - {row[0]}')

# Query a temp table
print('\nQuerying _raw_data:')
print(db.execute('SELECT * FROM _raw_data LIMIT 5').fetchdf())
"
```

### Studio Test
1. Open Studio → Load a cascade
2. Run it → Each phase creates temp table
3. Click "Recent Runs" → Select older run
4. Temp tables from that run are still queryable!

## Cleanup

### Manual Cleanup
```python
from windlass.sql_tools.session_db import cleanup_session_db
cleanup_session_db('session_id', delete_file=True)
```

### Via Studio API
```bash
curl -X POST http://localhost:5001/api/studio/cleanup-session \
  -H "Content-Type: application/json" \
  -d '{"session_id": "my_session"}'
```

### Bulk Cleanup
```bash
# Remove all session DBs older than 7 days
find /tmp/windlass_sessions -name "*.duckdb" -mtime +7 -delete
```

## Benefits

1. **Zero Impedance**: SQL phases can directly query Python/JS/Clojure outputs
2. **Replay Support**: Historical runs preserve intermediate data
3. **Debugging**: Inspect any intermediate step after execution
4. **Composability**: Mix languages freely without serialization overhead
5. **Performance**: DuckDB temp tables are fast (columnar, in-process)

## Example Use Cases

### ETL Pipeline
```yaml
phases:
  - name: extract
    tool: sql_data
    inputs:
      connection: prod_db
      query: SELECT * FROM raw_events

  - name: transform
    tool: python_data
    inputs:
      code: |
        df = data.extract
        # Complex pandas transformations
        result = df

  - name: validate
    tool: sql_data
    inputs:
      query: |
        -- Validate using SQL!
        SELECT COUNT(*) as invalid_count
        FROM _transform
        WHERE amount < 0 OR date IS NULL
```

### Cross-Language Analytics
```yaml
phases:
  - name: fetch_data
    tool: sql_data
    # ...

  - name: ml_predictions
    tool: python_data
    # Use scikit-learn, pandas

  - name: aggregate_results
    tool: sql_data
    inputs:
      query: SELECT category, AVG(prediction) FROM _ml_predictions GROUP BY category
```

This is now a **first-class feature** of Windlass cascades, not just a Studio-only trick!
