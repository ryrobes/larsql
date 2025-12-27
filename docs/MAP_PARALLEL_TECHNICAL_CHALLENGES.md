# MAP PARALLEL - Technical Challenges and DuckDB Limitations

**Date**: 2025-12-27
**Status**: Deferred due to DuckDB architectural constraints
**Attempts**: 8 different approaches tried, all failed

---

## Goal

Enable true concurrent execution for `RVBBIT MAP PARALLEL N`:

```sql
RVBBIT MAP PARALLEL 10 'cascade.yaml'
USING (SELECT * FROM products LIMIT 100);
```

**Expected behavior**: Execute cascade on 10 rows concurrently using ThreadPoolExecutor, completing ~10x faster than sequential.

**Actual behavior**: Syntax parsed correctly, but executes sequentially (same as regular MAP).

---

## The Core Problem

**Challenge**: Return tabular results from a Python UDF that executes in parallel.

**DuckDB Constraints**:
1. **Table functions can't accept subqueries** - `SELECT * FROM udf((SELECT ...))`  fails
2. **Temp tables created during query execution aren't visible to same query** - Parse-time vs execution-time
3. **JSON → Table conversion is limited** - Various unnest/transform functions have restrictions

---

## Attempted Approaches (All Failed)

### Attempt 1: Return JSON Array, Use `unnest(CAST(... AS JSON))`

**Code**:
```sql
SELECT unnest(
  CAST(rvbbit_map_parallel(...) AS JSON)
) as row_data
FROM rvbbit_result
```

**Error**: `UNNEST() can only be applied to lists, structs and NULL, not JSON`

**Why it failed**: DuckDB's JSON type is not a LIST type. UNNEST requires native LIST/STRUCT, not JSON strings.

**File**: `sql_rewriter.py:400` (first attempt)

---

### Attempt 2: Use `read_json_auto()` Table Function

**Code**:
```sql
SELECT * FROM read_json_auto([
  (SELECT rvbbit_map_parallel(...))
])
```

**Error**: `Table function cannot contain subqueries`

**Why it failed**: DuckDB table functions (read_json_auto, read_json, read_csv, etc.) cannot accept subqueries as arguments. They require literal strings or file paths.

**File**: `sql_rewriter.py:391` (second attempt)

---

### Attempt 3: Use `unnest(json_transform_strict())`

**Code**:
```sql
SELECT unnest(
  json_transform_strict(result_json_array, '[]')
) as row_data
FROM rvbbit_result
```

**Error**: `Too many values in array of JSON structure` or `Empty object in JSON structure`

**Why it failed**: `json_transform_strict` requires an explicit schema definition `[{}]`, but DuckDB couldn't infer the struct schema from empty pattern or got confused by varying row structures.

**File**: `sql_rewriter.py:400` (third attempt)

---

### Attempt 4: Manual Iteration with `generate_series`

**Code**:
```sql
SELECT
  json_extract(result_json_array, '$[' || idx || ']') as row_json
FROM rvbbit_result,
LATERAL (
  SELECT unnest(generate_series(0, json_array_length(...) - 1)) as idx
)
```

**Error**: Type mismatch (`UBIGINT` vs `BIGINT`), then `Cannot extract field from "row_json.*" because it is not a struct`

**Why it failed**:
- First: Type system issues with array length
- After fixing: `json_extract` returns JSON type, not STRUCT, so `.` operator doesn't work

**File**: `sql_rewriter.py:400-406` (fourth attempt)

---

### Attempt 5: Use `unnest(..., recursive := true)`

**Code**:
```sql
SELECT unnest(result_json_array::JSON, recursive := true)
FROM rvbbit_result
```

**Error**: `UNNEST() can only be applied to lists, structs and NULL, not JSON`

**Why it failed**: Same as Attempt 1 - casting to JSON type doesn't create a LIST type.

**File**: `sql_rewriter.py:399` (fifth attempt)

---

### Attempt 6: Use `list_transform` + Lambda

**Code**:
```sql
SELECT list_transform(
  range(json_array_length(result_json_array)),
  idx -> json_extract(result_json_array, '$[' || idx || ']')
) as rows_list
FROM rvbbit_result
```

**Error**: `Cannot extract field from "unnest(rows_list).*" because it is not a struct`

**Why it failed**: `list_transform` creates a LIST of JSON objects, but those JSON objects aren't STRUCTs, so `.` expansion doesn't work.

**File**: `sql_rewriter.py:400-406` (sixth attempt)

---

### Attempt 7: Create Temp Table Inside UDF

**Code**:
```python
def rvbbit_map_parallel_exec(..., conn):
    # Execute in parallel
    results_df = pd.DataFrame(results)

    # Create temp table
    conn.execute(f"CREATE TEMP TABLE {table_name} AS ...")

    return json.dumps({"table_created": table_name})
```

```sql
SELECT rvbbit_map_parallel_exec(..., '_temp_results_abc123') as metadata;
SELECT * FROM _temp_results_abc123;
```

**Error**: `Table with name _temp_results_abc123 does not exist!`

**Why it failed**: **Parse-time vs Execution-time issue**
- DuckDB parses entire query before executing
- At parse time, table doesn't exist yet
- UDF hasn't run to create the table
- Parser fails on `SELECT * FROM non_existent_table`

**This is the fundamental blocker!**

**File**: `sql_rewriter.py:417`, `udf.py:592-594` (seventh attempt)

---

### Attempt 8: Return DataFrame Directly

**Code**:
```python
def rvbbit_map_parallel_exec(...):
    results = [...]  # Parallel execution
    return pd.DataFrame(results)  # Return DataFrame

# Register as table-valued function
connection.create_function("rvbbit_map_parallel_exec", func)
```

```sql
SELECT * FROM rvbbit_map_parallel_exec(
  'cascade.yaml',
  (SELECT json_group_array(...) FROM ...),
  10,
  'result'
)
```

**Error**: `Table function cannot contain subqueries`

**Why it failed**: Even though the function returns a DataFrame (which DuckDB can handle), the function *arguments* contain a subquery `(SELECT json_group_array(...)`, which violates DuckDB's table function rules.

**File**: `sql_rewriter.py:391-403`, `udf.py:500-591` (eighth attempt)

---

## Root Cause Analysis

### DuckDB's Query Execution Model

DuckDB uses a **multi-phase query execution pipeline**:

1. **Parse**: SQL → AST (all table/column names must be resolvable)
2. **Bind**: Resolve names, check types
3. **Optimize**: Query optimization
4. **Execute**: Actually run the query

**The Problem**: Phases 1-2 happen before Phase 4.

**Our Need**: Create table during execution (Phase 4), reference it in same query (requires Phase 1-2).

**Conflict**: Parse phase (1) fails because table doesn't exist yet, but it won't exist until execute phase (4).

### Table Function Restrictions

DuckDB table functions have specific restrictions:

1. **No subqueries in arguments**: `read_json((SELECT ...))`  ❌
2. **Must return relation**: Can't return scalar that becomes table later
3. **Schema must be known at parse time**: Can't dynamically create columns

**Why these restrictions exist**:
- Query optimizer needs schema information before execution
- Binder needs to resolve column references
- Prevents circular dependencies

---

## What Would Be Needed

### Option A: Server-Side Interception (Recommended)

**Approach**: Handle MAP PARALLEL specially in `postgres_server.py` **before** DuckDB sees the query.

**Implementation**:
```python
# In postgres_server.py:handle_query()

if _is_rvbbit_statement(query):
    stmt = _parse_rvbbit_statement(query)

    if stmt.mode == 'MAP' and stmt.parallel:
        # SPECIAL HANDLING for MAP PARALLEL

        # 1. Execute USING query to get input rows
        input_query = stmt.using_query
        input_rows = self.duckdb_conn.execute(input_query).fetchdf()

        # 2. Call parallel execution function directly (Python-side)
        results_df = execute_map_parallel_python(
            cascade_path=stmt.cascade_path,
            input_rows=input_rows,
            max_workers=stmt.parallel,
            result_column=stmt.result_alias or 'result'
        )

        # 3. Register DataFrame and return directly
        self.duckdb_conn.register("_parallel_results", results_df)
        final_query = "SELECT * FROM _parallel_results"

        # 4. Execute final query and send results
        result_df = self.duckdb_conn.execute(final_query).fetchdf()
        send_query_results(self.sock, result_df, self.transaction_status)

        # 5. Cleanup
        self.duckdb_conn.unregister("_parallel_results")
        return  # Skip normal query execution
```

**Pros**:
- Clean separation: Python handles parallelism, DuckDB handles SQL
- No DuckDB limitations (we control the flow)
- Can apply schema transformations in Python
- Full ThreadPoolExecutor power

**Cons**:
- Breaks single-query model (query is decomposed)
- More complex control flow
- Different code path than regular MAP

**Estimated effort**: 2-3 hours

---

### Option B: DuckDB Extension (Advanced)

**Approach**: Write a C++ DuckDB extension that implements a proper table-valued function with internal parallelism.

**Implementation**: Would require:
1. C++ DuckDB extension development
2. Table function that spawns threads internally
3. Bind to RVBBIT's Python runner

**Pros**:
- True native DuckDB integration
- Elegant from SQL perspective
- Could be contributed back to DuckDB

**Cons**:
- Requires C++ expertise
- Complex development (weeks, not hours)
- Deployment complexity (need to compile extension)

**Estimated effort**: 2-3 weeks

---

### Option C: Two-Query Pattern (User-Facing)

**Approach**: Require users to execute in two steps.

**Implementation**:
```sql
-- Step 1: Execute and materialize
RVBBIT MAP PARALLEL 10 'cascade.yaml'
USING (SELECT * FROM products LIMIT 100)
WITH (as_table='results');

-- Step 2: Query the table
SELECT * FROM results;
```

Behind the scenes, Step 1:
1. Executes USING query
2. Runs parallel execution
3. Creates temp table
4. Returns metadata

**Pros**:
- Sidesteps all DuckDB limitations
- Simple implementation
- Works with existing table materialization code

**Cons**:
- Requires two queries (not one)
- Less elegant UX
- Breaks SQL transaction semantics

**Estimated effort**: 30 minutes (mostly docs)

---

### Option D: Python Client-Side API

**Approach**: Expose parallel execution via Python API, not SQL.

**Implementation**:
```python
from rvbbit.client import RVBBITClient

client = RVBBITClient('http://localhost:5001')

# Execute in parallel (Python-side)
df = client.map_parallel(
    cascade='cascade.yaml',
    using_query='SELECT * FROM products',
    max_workers=10,
    result_column='result'
)

# Now use DataFrame in pandas/polars
print(df.head())
```

**Pros**:
- Full control over execution
- Can use pandas/polars ecosystem
- No DuckDB limitations

**Cons**:
- Not SQL (loses SQL narrative)
- Requires Python code
- Separate API surface

**Estimated effort**: 1-2 hours

---

## Lessons Learned

### 1. DuckDB Table Functions Are Restrictive

**Rule**: Table functions need **static, parse-time-resolvable** inputs.

**Won't work**:
- Subqueries as arguments
- Dynamic table names
- Schema unknown until execution

**Will work**:
- Literal file paths: `read_csv('file.csv')`
- Literal JSON: `read_json_auto('[...]')`
- Functions returning DataFrames called as **scalar** (not table) functions

### 2. Parse-Time vs Execution-Time

**DuckDB's multi-phase execution** is a fundamental constraint:

```
Parse → Bind → Optimize → Execute
 ^                           ^
 |                           |
 Need table name here        Table created here
```

**Workarounds**:
1. Pre-create all tables before query (server-side)
2. Use two queries (table creation, then selection)
3. Bypass DuckDB parser (server-side interception)

### 3. JSON ≠ STRUCT in DuckDB

**Key insight**: JSON type and STRUCT type are different!

```sql
-- JSON type (string with metadata)
SELECT '{"a": 1}'::JSON

-- STRUCT type (native columns)
SELECT {'a': 1}  -- No quotes!
```

**Functions**:
- `json_extract()` → Returns JSON (not STRUCT)
- `unnest()` → Requires LIST<STRUCT>, not LIST<JSON>
- `.*` operator → Only works on STRUCT, not JSON

**To convert JSON → STRUCT**: Use `from_json()` with explicit schema, which we can't know at parse time for dynamic results.

### 4. Table Function Argument Restrictions

**DuckDB documentation** (not explicit, learned through testing):

```sql
-- ❌ FAILS: Subquery in table function
SELECT * FROM read_json((SELECT data FROM t))

-- ❌ FAILS: Dynamic file path
SELECT * FROM read_csv((SELECT filename FROM config))

-- ✅ WORKS: Literal value
SELECT * FROM read_json('[{"a":1}]')

-- ✅ WORKS: Column reference (but schema must be known!)
SELECT * FROM my_table_function(column_value)
```

**Reason**: Optimizer needs to know schema before execution. Subqueries aren't materialized until execution time.

---

## Why Option A (Server Interception) Is Best

### Architecture

```
User Query: RVBBIT MAP PARALLEL 10 'cascade.yaml' USING (...)
    ↓
postgres_server.py:handle_query()
    ↓
Detect: stmt.mode == 'MAP' and stmt.parallel
    ↓
Python Execution Path:
  1. Execute USING query → DataFrame A
  2. Call rvbbit_map_parallel_exec(A, workers=10) → DataFrame B
  3. Register DataFrame B in DuckDB
  4. Return results to client
    ↓
Skip DuckDB query execution
```

### Implementation Sketch

```python
# In postgres_server.py:handle_query(), around line 683

# Rewrite RVBBIT syntax
from rvbbit.sql_rewriter import rewrite_rvbbit_syntax, _is_rvbbit_statement, _parse_rvbbit_statement

if _is_rvbbit_statement(query):
    stmt = _parse_rvbbit_statement(query)

    # SPECIAL PATH: MAP PARALLEL
    if stmt.mode == 'MAP' and stmt.parallel:
        try:
            # 1. Execute USING query to materialize inputs
            using_query = stmt.using_query
            if not re.search(r'\bLIMIT\s+\d+', using_query, re.IGNORECASE):
                using_query += ' LIMIT 1000'  # Safety

            input_df = self.duckdb_conn.execute(using_query).fetchdf()

            # 2. Convert to JSON array for parallel processing
            import json
            rows_json = json.dumps(input_df.to_dict('records'))

            # 3. Execute in parallel (Python-side)
            from rvbbit.sql_tools.udf import rvbbit_map_parallel_exec
            result_df = rvbbit_map_parallel_exec(
                cascade_path=stmt.cascade_path,
                rows_json_array=rows_json,
                max_workers=stmt.parallel,
                result_column=stmt.result_alias or 'result'
            )

            # 4. Apply schema extraction if specified
            if stmt.output_columns:
                # Apply typed column extraction to result_df
                for col_name, col_type in stmt.output_columns:
                    # Extract and cast columns from JSON results
                    pass  # Implementation details

            # 5. Send results to client
            send_query_results(self.sock, result_df, self.transaction_status)
            print(f"[{self.session_id}]   ✓ MAP PARALLEL executed ({len(result_df)} rows, {stmt.parallel} workers)")
            return  # Skip normal execution path

        except Exception as e:
            # Log error and fall back to sequential
            print(f"[{self.session_id}]   ⚠️  MAP PARALLEL failed, falling back to sequential: {e}")
            # Fall through to normal rewrite_rvbbit_syntax

    # NORMAL PATH: All other RVBBIT queries
    query = rewrite_rvbbit_syntax(query, duckdb_conn=self.duckdb_conn)
```

### Why This Works

1. **No DuckDB parsing of temp table names** - We handle everything in Python
2. **No table functions with subqueries** - We execute the subquery ourselves
3. **Full control over DataFrame** - Can apply transformations in Python before returning
4. **Maintains transaction semantics** - Still within same query execution

### Tradeoffs

**Benefits**:
- Solves all DuckDB limitations
- True parallel execution
- Clean from user perspective (single SQL query)

**Costs**:
- Code complexity (special case in server)
- Different code path than regular MAP
- Harder to debug (more moving parts)
- Can't use in prepared statements easily

---

## Alternative: Document as Known Limitation

### Current Approach

**What we ship**:
1. Syntax **accepted**: `RVBBIT MAP PARALLEL N` parses correctly
2. Behavior: Falls back to sequential execution
3. Documentation: Clear about limitation

**Benefits**:
- Users can write PARALLEL queries today
- When we implement (server interception or DuckDB improvement), their queries just get faster
- No breaking changes

**Messaging**:
```sql
-- ⚠️  NOTE: MAP PARALLEL syntax is accepted but currently executes sequentially
--     due to DuckDB architectural limitations. True parallelism coming soon!

RVBBIT MAP PARALLEL 10 'cascade.yaml'
USING (SELECT * FROM products LIMIT 100);
-- Works, but executes sequentially (same speed as MAP without PARALLEL)
```

---

## Recommended Path Forward

### Short Term (Now)
1. ✅ Ship features that work (Schema, EXPLAIN, DISTINCT, Cache, Materialization)
2. ✅ Document MAP PARALLEL as "accepted but sequential"
3. ✅ Add this technical document for future implementers

### Medium Term (Next Sprint)
Implement **Option A** (Server Interception):
- ~2-3 hours work
- Solves problem cleanly
- Maintains SQL UX

### Long Term (Future)
Consider **Option B** (DuckDB Extension):
- If MAP PARALLEL becomes critical performance bottleneck
- If we want to contribute back to DuckDB
- If we have C++ resources

---

## Code Artifacts

All attempted code is preserved in git history:

**Key commits**:
- First attempts: sql_rewriter.py lines 386-410 (multiple revisions)
- UDF attempts: udf.py lines 500-647
- Server integration: postgres_server.py line 683

**Search for**:
- `rvbbit_map_parallel` - Multiple implementations tried
- `unnest` - Various unnest attempts
- `json_transform` - JSON parsing attempts
- `CREATE TEMP TABLE` - Temp table timing issues

---

## Testing Notes

### What We Know Works

```python
# Python-side parallel execution (proven pattern from system.py:224-298)
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(process_row, i, row): i for i, row in enumerate(rows)}
    for future in as_completed(futures):
        index, enriched_row = future.result()
        results[index] = enriched_row  # Order preservation
```

This code **works perfectly** when called from Python. The challenge is purely about **returning results to SQL**.

### Parallel Execution is Already Implemented

The parallel execution logic exists and works:
- `sql_tools/udf.py:rvbbit_map_parallel_exec()` - ThreadPoolExecutor implementation
- `traits/system.py:map_cascade()` - Reference pattern
- Proven in production for array-based mapping

**Only missing**: The DuckDB result-gathering mechanism.

---

## Future DuckDB Improvements That Would Help

1. **Table functions accept subqueries** - Unlikely (architectural constraint)
2. **JSON type unnests directly** - Possible, would need DuckDB patch
3. **Temp tables visible during same query** - Very unlikely (breaks optimizer)
4. **Dynamic schema inference** - Would require major optimizer changes

**Most likely**: DuckDB won't change. **We should implement Option A.**

---

## Summary

**Problem**: DuckDB's parse → execute separation prevents dynamic table creation and querying in one SQL statement.

**Attempts**: 8 different approaches tried, all hit DuckDB limitations.

**Solution**: Server-side interception (Option A) is cleanest path forward.

**Timeline**: 2-3 hours to implement when prioritized.

**Current State**: Syntax accepted, falls back to sequential (safe, documented).

---

## References

- DuckDB Documentation: https://duckdb.org/docs/sql/functions/overview
- ThreadPoolExecutor Pattern: `rvbbit/traits/system.py:224-298`
- ContextVar Handling: `rvbbit/traits/state_tools.py:1-40`
- Failed Implementations: This file's commit history

**Last Updated**: 2025-12-27
**Next Steps**: Implement Option A (server interception) when MAP PARALLEL becomes priority
