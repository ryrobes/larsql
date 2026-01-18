# pyright: reportArgumentType=false
# Note: DuckDB's type stubs require enums (DuckDBPyType, FunctionNullHandling)
# but the runtime API accepts string literals. Suppressing for this file.
"""
lars_udf() - LLM-powered SQL user-defined function.

This allows you to use LLMs directly in SQL queries for data enrichment:

    SELECT
      product_name,
      lars_udf('Extract brand name', product_name) as brand,
      lars_udf('Classify: electronics/clothing/home', product_name) as category
    FROM products

The UDF:
- Spawns mini LLM calls per row
- Caches results (same input → same output)
- Handles errors gracefully (returns NULL on failure)
- Supports batching for efficiency
"""

import hashlib
import json
from typing import Optional, Dict, Any, Tuple
import duckdb

from ..console_style import S, styled_print


# Track which connections have UDF registered (to avoid duplicate registration)
_registered_connections: set = set()

# Cache type identifiers for the persistent SemanticCache
_CACHE_TYPE_UDF = "_udf_"
_CACHE_TYPE_CASCADE = "_cascade_udf_"
_CACHE_TYPE_AGGREGATE = "_aggregate_"

# Legacy in-memory cache dicts (kept for fallback if ClickHouse unavailable)
# These are populated alongside SemanticCache writes
_udf_cache: Dict[str, Tuple[str, float, Optional[float]]] = {}
_cascade_udf_cache: Dict[str, Tuple[str, float, Optional[float]]] = {}


# =============================================================================
# UDF Registration Utilities
# =============================================================================

def get_registered_functions(conn: duckdb.DuckDBPyConnection) -> set:
    """
    Query DuckDB for all registered scalar function names.

    This allows checking before attempting registration to avoid
    "Function already exists!" errors when multiple sessions share
    a persistent database.

    Returns:
        Set of function names currently registered in the database.
    """
    try:
        result = conn.execute(
            "SELECT function_name FROM duckdb_functions() WHERE function_type = 'scalar'"
        ).fetchall()
        return {row[0] for row in result}
    except Exception:
        # If query fails, return empty set (will attempt registration)
        return set()


def safe_create_function(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    func,
    existing: set,
    **kwargs
) -> bool:
    """
    Register a UDF only if it doesn't already exist.

    Args:
        conn: DuckDB connection
        name: Function name to register
        func: Python function to register
        existing: Pre-fetched set of existing function names
        **kwargs: Additional args passed to create_function (return_type, null_handling, etc.)

    Returns:
        True if function was newly registered, False if already existed.
    """
    if name in existing:
        return False  # Already exists, skip silently

    conn.create_function(name, func, **kwargs)
    existing.add(name)  # Update set for subsequent checks in same batch
    return True


def _make_cache_key(instructions: str, input_value: str, model: str | None = None) -> str:
    """Create cache key for UDF result."""
    cache_str = f"{instructions}|{input_value}|{model or 'default'}"
    return hashlib.md5(cache_str.encode()).hexdigest()


def _make_cascade_cache_key(cascade_path: str, inputs: dict) -> str:
    """Create cache key for cascade UDF result."""
    # Sort inputs for consistent hashing
    inputs_str = json.dumps(inputs, sort_keys=True)
    cache_str = f"{cascade_path}|{inputs_str}"
    return hashlib.md5(cache_str.encode()).hexdigest()


def _get_cache_function_name(cache: dict) -> str:
    """
    Get the function name prefix for a cache dict.

    Maps legacy cache dicts to function names for SemanticCache.
    """
    # Import here to check object identity
    from .llm_aggregates import _agg_cache
    if cache is _udf_cache:
        return _CACHE_TYPE_UDF
    elif cache is _cascade_udf_cache:
        return _CACHE_TYPE_CASCADE
    elif cache is _agg_cache:
        return _CACHE_TYPE_AGGREGATE
    else:
        return "_unknown_"


def _cache_get(cache: dict, key: str, track_sql_trail: bool = True) -> Optional[str]:
    """
    Get from cache, checking TTL expiry.

    Uses persistent SemanticCache (L1 in-memory + L2 ClickHouse).
    Falls back to in-memory cache dict if ClickHouse unavailable.

    If track_sql_trail is True (default), increments cache hit/miss counters
    in sql_query_log for SQL Trail analytics.
    """
    import time

    # Try persistent cache first
    try:
        from .cache_adapter import get_cache
        semantic_cache = get_cache()

        # Get function name for this cache type
        func_name = _get_cache_function_name(cache)

        # SemanticCache uses function_name + args, we use function_name + key_hash
        found, result, _ = semantic_cache.get(func_name, {"key": key}, track_hit=track_sql_trail)
        if found:
            # Track cache hit for SQL Trail
            if track_sql_trail:
                try:
                    from ..caller_context import get_caller_id
                    from ..sql_trail import increment_cache_hit
                    caller_id = get_caller_id()
                    if caller_id:
                        increment_cache_hit(caller_id)
                except Exception:
                    pass
            return result
    except Exception:
        pass  # Fall through to in-memory cache

    # Fallback to in-memory cache
    if key not in cache:
        # Track cache miss for SQL Trail (fire-and-forget)
        if track_sql_trail:
            try:
                from ..caller_context import get_caller_id
                from ..sql_trail import increment_cache_miss
                caller_id = get_caller_id()
                if caller_id:
                    increment_cache_miss(caller_id)
            except Exception:
                pass  # Non-blocking
        return None

    value, timestamp, ttl = cache[key]

    # Check if expired
    if ttl is not None and (time.time() - timestamp) > ttl:
        del cache[key]  # Expired, remove
        # Track as cache miss
        if track_sql_trail:
            try:
                from ..caller_context import get_caller_id
                from ..sql_trail import increment_cache_miss
                caller_id = get_caller_id()
                if caller_id:
                    increment_cache_miss(caller_id)
            except Exception:
                pass
        return None

    # Track cache hit for SQL Trail
    if track_sql_trail:
        try:
            from ..caller_context import get_caller_id
            from ..sql_trail import increment_cache_hit
            caller_id = get_caller_id()
            if caller_id:
                increment_cache_hit(caller_id)
        except Exception:
            pass  # Non-blocking

    return value


def _cache_set(cache: dict, key: str, value: str, ttl: Optional[float] = None):
    """
    Set in cache with optional TTL.

    Writes to both persistent SemanticCache (L1+L2) and in-memory cache dict.
    """
    import time

    # Write to persistent cache (async, non-blocking)
    try:
        from .cache_adapter import get_cache
        semantic_cache = get_cache()
        func_name = _get_cache_function_name(cache)

        # Convert TTL to int seconds
        ttl_seconds = int(ttl) if ttl else None

        semantic_cache.set(
            func_name,
            {"key": key},
            value,
            result_type="VARCHAR",
            ttl_seconds=ttl_seconds
        )
    except Exception:
        pass  # Non-blocking, continue with in-memory

    # Also write to in-memory cache (for immediate availability)
    cache[key] = (value, time.time(), ttl)


def _parse_duration(duration_str: str) -> float:
    """
    Parse duration string to seconds.

    Supports: '1d', '2h', '30m', '60s', or raw seconds as int/float

    Examples:
        >>> _parse_duration('1d')
        86400.0
        >>> _parse_duration('2h')
        7200.0
        >>> _parse_duration(3600)
        3600.0
    """
    if isinstance(duration_str, (int, float)):
        return float(duration_str)

    import re
    match = re.match(r'(\d+)([smhd])', str(duration_str).lower())
    if not match:
        raise ValueError(f"Invalid duration format: {duration_str}. Use '1d', '2h', '30m', '60s', or raw seconds")

    value, unit = int(match.group(1)), match.group(2)

    multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    return value * multipliers[unit]


def lars_udf_impl(
    instructions: str,
    input_value: str,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 500,
    use_cache: bool = True,
    cache_ttl: Optional[str] = None
) -> str:
    """
    Core implementation of lars_udf.

    Uses the bodybuilder tool with request mode, which allows the instructions
    to specify which model to use. The bodybuilder's planner converts natural
    language requests to API bodies and executes them.

    Examples of model-aware instructions:
        - "Use Claude to extract the brand name" -> picks Claude
        - "Ask a cheap Gemini model to classify this" -> picks Gemini Flash Lite
        - "Extract brand name" -> uses planner's default model selection

    Args:
        instructions: What to ask the LLM (e.g., "Extract brand name from this product")
                     Can include model hints like "Use Claude to..." or "Ask a fast model to..."
        input_value: The data to process (e.g., "Apple iPhone 15 Pro")
        model: Optional model override (ignored - use instructions to specify model)
        temperature: LLM temperature (currently not passed to bodybuilder)
        max_tokens: Max tokens in response (currently not passed to bodybuilder)
        use_cache: Whether to use cache (default: True)
        cache_ttl: Cache TTL (e.g., '1d', '2h', '30m') or None for infinite

    Returns:
        LLM response as string (or error message on failure)
    """
    # Check cache first (TTL-aware)
    # Note: Cache key now ignores model param since model is determined by bodybuilder
    if use_cache:
        cache_key = _make_cache_key(instructions, input_value, model)
        cached_value = _cache_get(_udf_cache, cache_key)
        if cached_value is not None:
            # Log cache hit for SQL Trail analytics
            from ..sql_trail import increment_cache_hit
            from ..caller_context import get_caller_id
            caller_id = get_caller_id()
            if caller_id:
                increment_cache_hit(caller_id)
            return cached_value

    try:
        # Import bodybuilder tool and session naming
        from ..skills.bodybuilder import bodybuilder
        from ..session_naming import generate_woodland_id
        from rich.console import Console

        console = Console()

        # Generate proper session_id using woodland naming system
        woodland_id = generate_woodland_id()
        session_id = f"sql-udf-{woodland_id}"

        # Generate a unique cell name for logging
        import uuid
        cell_name = f"udf_lars_{uuid.uuid4().hex[:8]}"

        # Consistent cascade_id for all SQL UDF calls
        cascade_id = "sql_udf"

        # Build the request string combining instructions and input
        # The format "instructions - input" allows bodybuilder's planner to:
        # 1. Parse the task description from instructions
        # 2. Select an appropriate model based on hints in instructions
        # 3. Format the actual query to include the input data
        request = f"{instructions} - {input_value}"

        # Add instruction to return only the result (no explanation)
        request = f"{request}\n\nReturn ONLY the result, no explanation or markdown."

        # Console log for visibility
        input_preview = input_value[:50] + "..." if len(input_value) > 50 else input_value
        console.print(f"[dim][CFG] lars()[/dim] [cyan]{session_id}[/cyan] [dim]|[/dim] {instructions[:40]}... [dim]|[/dim] {input_preview}")

        # Call bodybuilder in request mode
        # This executes as a deterministic cell:
        #   - name: udf_lars_<id>
        #     tool: bodybuilder
        #     inputs:
        #       request: <instructions - input>
        response = bodybuilder(
            request=request,
            _session_id=session_id,
            _cell_name=cell_name,
            _cascade_id=cascade_id,
        )

        # Extract result from bodybuilder response
        if response.get("_route") == "error":
            error_msg = response.get("error", "Unknown error")
            console.print(f"[red]✗ lars() error:[/red] {error_msg[:50]}")
            return f"ERROR: {str(error_msg)[:50]}"

        # Get the result content
        result = response.get("result") or response.get("content") or ""

        # Strip whitespace
        result = result.strip()

        # Never return empty string - DuckDB treats it as NULL in some contexts
        if not result:
            result = "N/A"

        # Console log completion
        result_preview = result[:50] + "..." if len(result) > 50 else result
        model_used = response.get("model", "unknown")
        console.print(f"[green][OK][/green] [dim]{model_used}[/dim] → {result_preview}")

        # Log cache miss for SQL Trail analytics (LLM was actually called)
        from ..sql_trail import increment_cache_miss
        from ..caller_context import get_caller_id
        caller_id = get_caller_id()
        if caller_id:
            increment_cache_miss(caller_id)

        # Cache result with TTL
        if use_cache:
            ttl_seconds = _parse_duration(cache_ttl) if cache_ttl else None
            _cache_set(_udf_cache, cache_key, result, ttl_seconds)

        return result

    except Exception as e:
        # Log error with more detail
        import logging
        import traceback
        logging.getLogger(__name__).error(f"lars_udf error for '{instructions}': {e}\n{traceback.format_exc()}")
        return f"ERROR: {str(e)[:50]}"


def lars_cascade_udf_impl(
    cascade_path: str,
    inputs_json: str,
    use_cache: bool = True,
    return_field: Optional[str] = None
) -> str:
    """
    Run a complete cascade as a SQL UDF.

    This enables multi-cell LLM workflows per database row with full validation,
    takes, wards, and all cascade features. Particularly powerful for:
    - Complex multi-step reasoning per row
    - Validated outputs (wards + output_schema)
    - Takes per row (best-of-N selection)
    - Tool usage per row (query other data, call APIs)

    Args:
        cascade_path: Path to cascade file (e.g., "skills/fraud_check.yaml")
        inputs_json: JSON string of cascade inputs (e.g., '{"customer_id": 123}')
        use_cache: Whether to use cache (default: True)
        return_field: Optional field to extract from result (e.g., "risk_score")
                     If None, returns full result as JSON string

    Returns:
        JSON string with cascade outputs, or specific field value if return_field specified

    Example SQL:
        SELECT
          customer_id,
          lars_cascade_udf(
            'skills/fraud_check.yaml',
            json_object('customer_id', customer_id)
          ) as fraud_analysis
        FROM transactions;

    With field extraction:
        SELECT
          customer_id,
          lars_cascade_udf(
            'skills/fraud_check.yaml',
            json_object('customer_id', customer_id),
            'risk_score'
          ) as risk_score
        FROM transactions;
    """
    import uuid
    import os

    try:
        # Parse inputs (might be JSON string from SQL)
        if isinstance(inputs_json, str):
            inputs = json.loads(inputs_json)
        else:
            inputs = inputs_json

        # Extract source lineage context from inputs (special _lars_* keys)
        source_column = None
        source_row_index = None
        source_table = None
        cleaned_inputs = {}

        for key, value in inputs.items():
            if key == '_lars_source_column':
                source_column = str(value) if value is not None else None
            elif key == '_lars_source_row':
                try:
                    source_row_index = int(value) if value is not None else None
                except (ValueError, TypeError):
                    pass
            elif key == '_lars_source_table':
                source_table = str(value) if value is not None else None
            else:
                cleaned_inputs[key] = value

        # Use cleaned inputs (without _lars_* keys) for cascade and caching
        inputs = cleaned_inputs

        # Create cache key
        cache_key = _make_cascade_cache_key(cascade_path, inputs)

        # Check cache (TTL-aware)
        if use_cache:
            cached_result = _cache_get(_cascade_udf_cache, cache_key)
            if cached_result is not None:
                # Log cache hit for SQL Trail analytics
                from ..sql_trail import increment_cache_hit
                from ..caller_context import get_caller_id
                caller_id = get_caller_id()
                if caller_id:
                    increment_cache_hit(caller_id)

                # If return_field specified, extract it
                if return_field:
                    result_obj = json.loads(cached_result)
                    # Try to extract from outputs first, then state
                    for cell_output in result_obj.get("outputs", {}).values():
                        if isinstance(cell_output, dict) and return_field in cell_output:
                            return str(cell_output[return_field])
                    # Fallback: search in state
                    if return_field in result_obj.get("state", {}):
                        return str(result_obj["state"][return_field])

                return cached_result

        # Resolve cascade path
        resolved_path = cascade_path
        if not os.path.isabs(cascade_path):
            resolved_path = os.path.join(os.getcwd(), cascade_path)

        # Add extension if needed
        if not os.path.exists(resolved_path):
            for ext in [".yaml", ".yml", ".json"]:
                if os.path.exists(resolved_path + ext):
                    resolved_path = resolved_path + ext
                    break

        if not os.path.exists(resolved_path):
            return json.dumps({"error": f"Cascade not found: {cascade_path}", "status": "failed"})

        # Generate unique session ID using woodland naming system
        from ..session_naming import generate_woodland_id
        woodland_id = generate_woodland_id()
        session_id = f"udf-{woodland_id}"  # Prefix with 'udf-' to indicate UDF origin

        # Debug: Print each UDF invocation
        print(f"[CFG] [UDF] Calling lars_run: session={session_id}, input={str(inputs)[:50]}...")

        # Get caller context (set by SQL server before UDF was called)
        from ..caller_context import get_caller_context
        caller_id, invocation_metadata = get_caller_context()

        # Enrich invocation_metadata with source lineage context
        enriched_metadata = invocation_metadata.copy() if invocation_metadata else {}
        if source_column is not None or source_row_index is not None or source_table is not None:
            if 'source' not in enriched_metadata:
                enriched_metadata['source'] = {}
            if source_column is not None:
                enriched_metadata['source']['column'] = source_column
            if source_row_index is not None:
                enriched_metadata['source']['row_index'] = source_row_index
            if source_table is not None:
                enriched_metadata['source']['table'] = source_table

        # Run cascade with caller tracking
        from ..runner import run_cascade

        result = run_cascade(
            resolved_path,
            inputs,
            session_id=session_id,
            caller_id=caller_id,
            invocation_metadata=enriched_metadata if enriched_metadata else None
        )

        # Serialize relevant outputs as JSON
        # We want to return something useful for SQL queries
        outputs = {}
        for cell_item in result.get("lineage", []):
            cell_name = cell_item.get("cell")
            cell_output = cell_item.get("output")
            if cell_name:
                outputs[cell_name] = cell_output

        json_result = json.dumps({
            "outputs": outputs,
            "state": result.get("state", {}),
            "status": result.get("status", "unknown"),
            "session_id": session_id,
            "has_errors": result.get("has_errors", False)
        })

        # Debug: Print completion
        state_output = result.get("state", {}).get("output_extract", "N/A")
        print(f"[OK] [UDF] Completed: session={session_id}, output={str(state_output)[:30]}...")

        # Log cache miss for SQL Trail analytics (cascade was actually run)
        from ..sql_trail import increment_cache_miss
        # caller_id already retrieved above at line 343
        if caller_id:
            increment_cache_miss(caller_id)

        # Cache result (with infinite TTL for backward compatibility)
        if use_cache:
            _cache_set(_cascade_udf_cache, cache_key, json_result, ttl=None)

        # Extract specific field if requested
        if return_field:
            result_obj = json.loads(json_result)
            for cell_output in result_obj.get("outputs", {}).values():
                if isinstance(cell_output, dict) and return_field in cell_output:
                    return str(cell_output[return_field])
            if return_field in result_obj.get("state", {}):
                return str(result_obj["state"][return_field])
            # Field not found, return NULL
            return "NULL"

        return json_result

    except Exception as e:
        # Log error with detail
        import logging
        import traceback
        logging.getLogger(__name__).error(f"lars_cascade_udf error for '{cascade_path}': {e}\n{traceback.format_exc()}")
        return json.dumps({"error": str(e), "status": "failed"})


def lars_run_batch(
    cascade_path: str,
    rows_json_array: str,
    table_name: str,
    conn: duckdb.DuckDBPyConnection
) -> str:
    """
    Execute cascade once over batch of rows (LARS RUN implementation).

    Creates temp table from rows, runs cascade with table reference.

    Args:
        cascade_path: Path to cascade file
        rows_json_array: JSON array of all rows
        table_name: Desired temp table name (e.g., 'batch_data')
        conn: DuckDB connection for temp table creation

    Returns:
        JSON metadata: {status, session_id, table_created, row_count}

    Example:
        result = lars_run_batch(
            'cascades/fraud_batch.yaml',
            '[{"id":1},{"id":2}]',
            'batch_txns',
            conn
        )
        # Creates table: batch_txns
        # Runs cascade with input: {"data_table": "batch_txns"}
        # Returns: '{"status":"success","session_id":"...","row_count":2}'
    """
    import json as json_module
    import uuid

    try:
        # Parse rows
        rows = json_module.loads(rows_json_array)
        if not isinstance(rows, list):
            raise ValueError("Expected JSON array")

        # Create temp table from rows
        if rows:
            # Infer schema from first row
            first_row = rows[0]
            columns = []
            for key, val in first_row.items():
                if isinstance(val, bool):
                    col_type = 'BOOLEAN'
                elif isinstance(val, int):
                    col_type = 'BIGINT'
                elif isinstance(val, float):
                    col_type = 'DOUBLE'
                else:
                    col_type = 'VARCHAR'
                columns.append(f"{key} {col_type}")

            # Create table
            create_sql = f"CREATE TEMP TABLE {table_name} ({', '.join(columns)})"
            conn.execute(create_sql)

            # Insert rows
            for row in rows:
                placeholders = ', '.join(['?' for _ in row])
                insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
                conn.execute(insert_sql, list(row.values()))

        # Generate session ID
        from ..session_naming import generate_woodland_id
        session_id = f"batch-{generate_woodland_id()}"

        print(f"[CFG] [RUN] Starting batch: session={session_id}, table={table_name}, rows={len(rows)}")

        # Get caller context (set by SQL server before UDF was called)
        from ..caller_context import get_caller_context
        caller_id, invocation_metadata = get_caller_context()

        # Run cascade with table reference
        import os
        resolved_path = cascade_path
        if not os.path.isabs(cascade_path):
            resolved_path = os.path.join(os.getcwd(), cascade_path)

        if not os.path.exists(resolved_path):
            for ext in [".yaml", ".yml", ".json"]:
                if os.path.exists(resolved_path + ext):
                    resolved_path = resolved_path + ext
                    break

        if not os.path.exists(resolved_path):
            return json_module.dumps({"error": f"Cascade not found: {cascade_path}", "status": "failed"})

        from ..runner import run_cascade

        # Pass table name as input
        cascade_inputs = {
            "data_table": table_name,
            "row_count": len(rows)
        }

        result = run_cascade(
            resolved_path,
            cascade_inputs,
            session_id=session_id,
            caller_id=caller_id,
            invocation_metadata=invocation_metadata
        )

        print(f"[OK] [RUN] Completed: session={session_id}, status={result.get('status')}")

        # Return metadata
        return json_module.dumps({
            "status": result.get("status", "unknown"),
            "session_id": session_id,
            "table_created": table_name,
            "row_count": len(rows),
            "has_errors": result.get("has_errors", False),
            "outputs": result.get("outputs", {})
        })

    except Exception as e:
        import logging
        import traceback
        logging.getLogger(__name__).error(f"lars_run_batch error: {e}\n{traceback.format_exc()}")
        return json_module.dumps({"error": str(e), "status": "failed"})


def lars_run_parallel_batch(
    cascade_path: str,
    rows_json_array: str,
    max_workers: int
) -> str:
    """
    Execute cascade on multiple rows in parallel.

    Returns NDJSON (newline-delimited JSON) for easy parsing.

    Args:
        cascade_path: Path to cascade file
        rows_json_array: JSON array of row objects
        max_workers: Max concurrent executions

    Returns:
        NDJSON string (one JSON object per line)

    Example:
        result = lars_run_parallel_batch('x.yaml', '[{"id":1},{"id":2}]', 5)
        # Returns: '{"id":1,"result":"..."}\n{"id":2,"result":"..."}'
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import json as json_module

    try:
        # Parse input rows
        rows = json_module.loads(rows_json_array)
        if not isinstance(rows, list):
            raise ValueError("Expected JSON array of rows")

        # Process rows in parallel
        results = [None] * len(rows)  # Preserve order

        def process_row(index, row):
            """Process single row, return (index, enriched_row)."""
            try:
                row_json = json_module.dumps(row)
                result_json = lars_cascade_udf_impl(cascade_path, row_json, use_cache=True)
                result_obj = json_module.loads(result_json)

                # Extract useful value
                extracted = (
                    result_obj.get("state", {}).get("output_extract") or
                    result_obj.get("outputs", {}) or
                    result_json
                )

                return index, {**row, "result": extracted}
            except Exception as e:
                return index, {**row, "result": f"ERROR: {str(e)}"}

        # Execute in parallel with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_row, i, row): i for i, row in enumerate(rows)}
            for future in as_completed(futures):
                index, result = future.result()
                results[index] = result

        # Return as NDJSON (one JSON object per line)
        ndjson_lines = [json_module.dumps(row) for row in results]
        return '\n'.join(ndjson_lines)

    except Exception as e:
        import logging
        import traceback
        logging.getLogger(__name__).error(f"lars_run_parallel_batch error: {e}\n{traceback.format_exc()}")
        # Return error as NDJSON
        return json_module.dumps({"error": str(e)})


def lars_map_parallel_exec(
    cascade_path: str,
    rows_json_array: str,
    max_workers: int,
    result_column: str
) -> str:
    """
    Execute cascade on multiple rows in parallel, return JSON array.

    Used by LARS MAP PARALLEL syntax. Each row becomes a cascade input,
    results are joined back to original columns in order.

    Args:
        cascade_path: Path to cascade file
        rows_json_array: JSON array of input rows from USING query
        max_workers: Max concurrent cascade executions
        result_column: Name for result column

    Returns:
        JSON array string with enriched rows (use read_json() to convert to table)

    Example:
        Input:  [{"id": 1, "text": "foo"}, {"id": 2, "text": "bar"}]
        Output: '[{"id": 1, "text": "foo", "result": "..."}, ...]'
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import json as json_module

    try:
        # Parse input rows
        rows = json_module.loads(rows_json_array)
        if not isinstance(rows, list):
            raise ValueError("Expected JSON array of rows")
        if len(rows) == 0:
            return "[]"  # Empty JSON array

        # Process rows in parallel with order preservation
        results = [None] * len(rows)

        def process_row(index, row):
            """Process single row, return (index, enriched_row)."""
            try:
                # Convert row to JSON for cascade input
                row_json = json_module.dumps(row)

                # Run cascade via lars_cascade_udf_impl (handles context vars properly)
                result_json = lars_cascade_udf_impl(cascade_path, row_json, use_cache=True)
                result_obj = json_module.loads(result_json)

                # Extract meaningful result
                # Priority: state.output_extract > last cell output > full result
                state = result_obj.get("state", {})
                outputs = result_obj.get("outputs", {})

                # Try to extract in order of preference
                if "output_extract" in state and state["output_extract"]:
                    # Has output_extract and it's not None/empty
                    extracted = state["output_extract"]
                elif outputs and len(outputs) > 0:
                    # Has outputs dict with at least one entry
                    extracted = list(outputs.values())[-1]
                else:
                    # Fallback to full result
                    extracted = result_json

                # Return enriched row with result column
                return index, {**row, result_column: extracted}

            except Exception as e:
                # On error, return row with error message in result column
                return index, {**row, result_column: f"ERROR: {str(e)[:100]}"}

        # Execute in parallel with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            futures = {
                executor.submit(process_row, i, row): i
                for i, row in enumerate(rows)
            }

            # Collect results as they complete
            for future in as_completed(futures):
                index, enriched_row = future.result()
                results[index] = enriched_row  # Preserve original order

        # Return as JSON array (caller uses read_json() to convert to table)
        return json_module.dumps(results, default=str)

    except Exception as e:
        import logging
        import traceback
        logging.getLogger(__name__).error(
            f"lars_map_parallel_exec error: {e}\n{traceback.format_exc()}"
        )
        # Return error as JSON array
        return json_module.dumps([{
            "error": str(e),
            "hint": "Check cascade path and input data format"
        }])


def lars_materialize_table(
    table_name: str,
    rows_json_array: str,
    conn: duckdb.DuckDBPyConnection
) -> str:
    """
    Materialize query results to a temp table.

    Args:
        table_name: Name for the table to create
        rows_json_array: JSON array of rows to materialize
        conn: DuckDB connection

    Returns:
        Metadata JSON
    """
    import json as json_module
    import pandas as pd

    try:
        rows = json_module.loads(rows_json_array)
        if not isinstance(rows, list):
            raise ValueError("Expected JSON array")

        if len(rows) == 0:
            # Create empty table
            conn.execute(f"CREATE OR REPLACE TEMP TABLE {table_name} (empty VARCHAR)")
            return json_module.dumps({"status": "success", "row_count": 0})

        # Convert to DataFrame
        df = pd.DataFrame(rows)

        # Materialize to temp table
        conn.register("_temp_materialize", df)
        conn.execute(f"CREATE OR REPLACE TEMP TABLE {table_name} AS SELECT * FROM _temp_materialize")
        conn.unregister("_temp_materialize")

        return json_module.dumps({
            "status": "success",
            "table_created": table_name,
            "row_count": len(df),
            "columns": list(df.columns)
        })

    except Exception as e:
        import logging
        import traceback
        logging.getLogger(__name__).error(f"lars_materialize_table error: {e}\n{traceback.format_exc()}")
        return json_module.dumps({"error": str(e), "status": "failed"})


def register_embedding_udfs(connection: duckdb.DuckDBPyConnection, existing: set | None = None):
    """
    Register embedding-based UDFs for Semantic SQL.

    Registers:
        - semantic_embed(text, model?) → DOUBLE[]
        - vector_search_json(query, table, limit?, threshold?) → VARCHAR (JSON)
        - similar_to(text1, text2) → DOUBLE

    Args:
        connection: DuckDB connection to register with
        existing: Pre-fetched set of existing function names (for batch efficiency)

    Note:
        These UDFs are backed by cascades in cascades/semantic_sql/:
        - embed.cascade.yaml
        - vector_search.cascade.yaml
        - similar_to.cascade.yaml
    """
    # Get existing functions if not provided
    if existing is None:
        existing = get_registered_functions(connection)
    import logging
    import json as json_module

    logger = logging.getLogger(__name__)

    # Import cascade execution
    try:
        from lars.semantic_sql.registry import execute_sql_function_sync
    except ImportError:
        logger.warning("semantic_sql.registry not available - embedding UDFs not registered")
        return

    # Import embedding tools to ensure they're registered
    # This MUST happen before UDF registration so tools are available to cascades
    try:
        import lars  # Force full initialization
        import lars.skills.embedding_storage  # noqa: F401

        # Verify tools are registered
        from lars.skill_registry import get_skill
        tool = get_skill("agent_embed")
        if tool:
            logger.debug(f"[OK] agent_embed tool found: {tool}")
        else:
            logger.warning("[WARN]  agent_embed tool not found in registry!")
            return

        logger.debug("Loaded embedding_storage tools")
    except ImportError as e:
        logger.warning(f"Could not load embedding_storage tools: {e}")
        return
    except Exception as e:
        logger.warning(f"Error verifying embedding tools: {e}")
        return

    # =========================================================================
    # UDF 1: semantic_embed(text, model?) → DOUBLE[]
    # =========================================================================

    def semantic_embed_udf_1(text: str):
        """Generate 4096-dim embedding via cascade (1-arg version)."""
        if text is None or text.strip() == "":
            logger.warning("semantic_embed called with empty text, returning NULL")
            return None

        try:
            logger.debug(f"Calling semantic_embed cascade for text: {text[:50]}...")

            result = execute_sql_function_sync(
                "semantic_embed",
                {"text": text, "model": None}
            )

            logger.debug(f"Cascade result type: {type(result)}, value: {str(result)[:100]}...")

            # Handle both dict result (from tool output) and list result (from python_data)
            if isinstance(result, dict):
                # Check if error
                if result.get('_route') == 'error':
                    logger.error(f"Cascade error: {result.get('error')}")
                    return None

                # Extract embedding from tool result
                if 'embedding' in result:
                    embedding = result['embedding']
                    if isinstance(embedding, list):
                        result = embedding
                    else:
                        logger.error(f"embedding field is not a list: {type(embedding)}")
                        return None
                else:
                    logger.error(f"No 'embedding' field in result: {result.keys()}")
                    return None

            # Result should be list of floats (4096 dims)
            if not isinstance(result, list):
                logger.error(f"semantic_embed returned non-list: {type(result)}, value: {result}")
                return None

            if len(result) != 4096:
                logger.warning(f"Unexpected embedding dimension: {len(result)} (expected 4096)")

            return result

        except Exception as e:
            logger.error(f"semantic_embed failed with exception: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def semantic_embed_udf_2(text: str, model: str):
        """Generate 4096-dim embedding via cascade (2-arg version with model)."""
        if text is None or text.strip() == "":
            return None

        try:
            result = execute_sql_function_sync(
                "semantic_embed",
                {"text": text, "model": model}
            )

            # Result is list of floats (4096 dims)
            if not isinstance(result, list):
                logger.error(f"semantic_embed returned non-list: {type(result)}")
                return None

            return result

        except Exception as e:
            logger.error(f"semantic_embed failed: {e}")
            return None

    def semantic_embed_with_storage_udf(text: str, model: str, source_table: str, column_name: str, source_id: str):
        """Generate embedding with table/column/ID tracking (5-arg version for auto-storage)."""
        if text is None or text.strip() == "":
            logger.warning("semantic_embed_with_storage called with empty text")
            return None

        try:
            logger.debug(f"Calling semantic_embed_with_storage for {source_table}.{column_name}:{source_id}")

            result = execute_sql_function_sync(
                "semantic_embed_with_storage",
                {
                    "text": text,
                    "model": model,
                    "source_table": source_table,
                    "column_name": column_name,
                    "source_id": source_id
                }
            )

            logger.debug(f"Result type: {type(result)}")

            # Handle dict or list result
            if isinstance(result, dict):
                if result.get('_route') == 'error':
                    logger.error(f"Cascade error: {result.get('error')}")
                    return None
                if 'embedding' in result:
                    result = result['embedding']

            if not isinstance(result, list):
                logger.error(f"semantic_embed_with_storage returned non-list: {type(result)}")
                return None

            return result

        except Exception as e:
            logger.error(f"semantic_embed_with_storage failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    # Register 1-arg version (default model, no storage)
    if safe_create_function(connection, "semantic_embed", semantic_embed_udf_1, existing,
                            return_type="DOUBLE[]", null_handling="special"):
        logger.debug("Registered semantic_embed UDF (1-arg version)")

    # Register 4-arg version (with table/ID for auto-storage)
    if safe_create_function(connection, "semantic_embed_with_storage", semantic_embed_with_storage_udf, existing,
                            return_type="DOUBLE[]", null_handling="special"):
        logger.debug("Registered semantic_embed_with_storage UDF (4-arg version)")

    # =========================================================================
    # UDF 2: vector_search_json(query, table, limit?, threshold?) → VARCHAR
    # =========================================================================

    def vector_search_json_udf_2(query: str, source_table: str):
        """Vector search (2-arg: query, table)."""
        import tempfile

        try:
            result = execute_sql_function_sync(
                "vector_search",  # SQL function name (not cascade_id!)
                {
                    "query": query,
                    "source_table": source_table,
                    "limit": 10,
                    "threshold": None
                }
            )

            # Write JSON to temp file and return path
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json_module.dump(result if result else [], f)
                return f.name

        except Exception as e:
            logger.error(f"vector_search_json failed: {e}")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write('[]')
                return f.name

    def vector_search_json_udf_3(query: str, source_table: str, limit: int):
        """Vector search (3-arg: query, table, limit)."""
        import tempfile
        import os as os_module

        try:
            result = execute_sql_function_sync(
                "vector_search",  # SQL function name (not cascade_id!)
                {
                    "query": query,
                    "source_table": source_table,
                    "limit": limit,
                    "threshold": None
                }
            )

            # Write JSON to temp file and return path
            # DuckDB's read_json_auto works reliably with files
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json_module.dump(result if result else [], f)
                temp_path = f.name

            return temp_path

        except Exception as e:
            logger.error(f"vector_search_json failed: {e}")
            # Return empty JSON file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write('[]')
                return f.name

    def vector_search_json_udf_4(query: str, source_table: str, limit: int, threshold: float):
        """Vector search (4-arg: query, table, limit, threshold)."""
        import tempfile

        try:
            result = execute_sql_function_sync(
                "vector_search",  # SQL function name (not cascade_id!)
                {
                    "query": query,
                    "source_table": source_table,
                    "limit": limit,
                    "threshold": threshold
                }
            )

            # Write JSON to temp file and return path
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json_module.dump(result if result else [], f)
                return f.name

        except Exception as e:
            logger.error(f"vector_search_json failed: {e}")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write('[]')
                return f.name

    # Register all arity versions with suffixes (DuckDB doesn't support overloading)
    # Like llm_aggregates, we use _N suffix for N arguments
    safe_create_function(connection, "vector_search_json_2", vector_search_json_udf_2, existing, return_type="VARCHAR", null_handling="special")
    safe_create_function(connection, "vector_search_json_3", vector_search_json_udf_3, existing, return_type="VARCHAR", null_handling="special")
    safe_create_function(connection, "vector_search_json_4", vector_search_json_udf_4, existing, return_type="VARCHAR", null_handling="special")
    logger.debug("Registered vector_search_json UDFs")

    # =========================================================================
    # UDF 3: similar_to(text1, text2) → DOUBLE
    # =========================================================================

    def similar_to_udf(text1: str, text2: str):
        """Cosine similarity between two texts (0.0 to 1.0)."""
        if not text1 or not text2:
            return None

        try:
            result = execute_sql_function_sync(
                "similar_to",  # SQL function name (not cascade_id!)
                {"text1": text1, "text2": text2}
            )

            # Result is float (similarity score)
            return float(result)

        except Exception as e:
            logger.error(f"similar_to failed: {e}")
            return None

    if safe_create_function(connection, "similar_to", similar_to_udf, existing,
                            return_type="DOUBLE", null_handling="special"):
        logger.debug("Registered similar_to UDF")

    # =========================================================================
    # UDF 4: vector_search_elastic(query, table?, limit?) → VARCHAR (file path)
    # Elasticsearch hybrid search (vector + BM25 keywords)
    # Usage: SELECT * FROM read_json_auto(vector_search_elastic_2('query', 'table'))
    # =========================================================================

    def vector_search_elastic_udf_1(query: str):
        """Elasticsearch hybrid search (1-arg: query only, all tables)."""
        import tempfile
        import json

        try:
            result = execute_sql_function_sync(
                "vector_search_elastic",
                {"query": query}
            )
            # Result is already a list of dicts from the cascade
            rows = result if isinstance(result, list) else []

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(rows, f)
                return f.name

        except Exception as e:
            logger.error(f"vector_search_elastic failed: {e}")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write('[]')
                return f.name

    def vector_search_elastic_udf_2(query: str, source_table: str):
        """Elasticsearch hybrid search (2-arg: query, table)."""
        import tempfile
        import json

        try:
            result = execute_sql_function_sync(
                "vector_search_elastic",
                {"query": query, "source_table": source_table}
            )
            rows = result if isinstance(result, list) else []

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(rows, f)
                return f.name

        except Exception as e:
            logger.error(f"vector_search_elastic failed: {e}")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write('[]')
                return f.name

    def vector_search_elastic_udf_3(query: str, source_table: str, limit: int):
        """Elasticsearch hybrid search (3-arg: query, table, limit)."""
        import tempfile
        import json

        try:
            result = execute_sql_function_sync(
                "vector_search_elastic",
                {"query": query, "source_table": source_table, "limit_": limit}
            )
            rows = result if isinstance(result, list) else []

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(rows, f)
                return f.name

        except Exception as e:
            logger.error(f"vector_search_elastic failed: {e}")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write('[]')
                return f.name

    safe_create_function(connection, "vector_search_elastic_1", vector_search_elastic_udf_1, existing, return_type="VARCHAR", null_handling="special")
    safe_create_function(connection, "vector_search_elastic_2", vector_search_elastic_udf_2, existing, return_type="VARCHAR", null_handling="special")
    safe_create_function(connection, "vector_search_elastic_3", vector_search_elastic_udf_3, existing, return_type="VARCHAR", null_handling="special")
    logger.debug("Registered vector_search_elastic UDFs")

    # =========================================================================
    # UDF 5: skill(name, args) → VARCHAR (file path to JSON)
    # Universal skill/tool caller - returns file path for read_json_auto()
    # Usage: SELECT * FROM read_json_auto(skill('say', json_object('text', 'Hello')))
    # =========================================================================

    def skill_udf(skill_name: str, args_json: str | None = None) -> str:
        """
        Call any registered skill and return path to JSON result file.

        This UDF is the backend for the skill() SQL operator. It:
        1. Calls the skill via the cascade system (for observability)
        2. Writes result to a temp JSON file
        3. Returns the file path for read_json_auto()

        Args:
            skill_name: Name of skill to call (e.g., 'say', 'brave_web_search')
            args_json: JSON string of arguments (e.g., '{"text": "Hello"}')

        Returns:
            Path to temp JSON file containing the result
        """
        import tempfile
        import json

        try:
            # Parse args
            args = json.loads(args_json) if args_json else {}

            # Call via cascade system for observability
            result = execute_sql_function_sync(
                "skill",
                {"skill_name": skill_name, "args": json.dumps(args)}
            )

            # Normalize result to list for table output
            if result is None:
                rows = [{"_skill": skill_name, "result": None}]
            elif isinstance(result, dict):
                rows = [result]
            elif isinstance(result, list):
                rows = result
            elif isinstance(result, str):
                # Try to parse as JSON
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, dict):
                        rows = [parsed]
                    elif isinstance(parsed, list):
                        rows = parsed
                    else:
                        rows = [{"_skill": skill_name, "result": parsed}]
                except json.JSONDecodeError:
                    rows = [{"_skill": skill_name, "result": result}]
            else:
                rows = [{"_skill": skill_name, "result": result}]

            # Write to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(rows, f)
                return f.name

        except Exception as e:
            logger.error(f"skill UDF failed: {e}")
            # Return error as JSON file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump([{"_skill": skill_name, "error": str(e)}], f)
                return f.name

    if safe_create_function(connection, "skill", skill_udf, existing, return_type="VARCHAR", null_handling="special"):
        logger.debug("Registered skill UDF")

    # =========================================================================
    # UDF 6: skill_json(name, args) → VARCHAR (JSON content directly)
    # For scalar extraction with json_extract_string()
    # Usage: SELECT json_extract_string(skill_json('fn', '{}'), '$.label') FROM t
    # =========================================================================

    def skill_json_udf(skill_name: str, args_json: str | None = None) -> str:
        """
        Call any registered skill and return JSON content directly.

        Unlike skill() which returns a file path for read_json_auto(),
        this UDF returns the JSON string directly for use with
        json_extract_string() in scalar extraction scenarios.

        Args:
            skill_name: Name of skill to call (e.g., 'local_sentiment')
            args_json: JSON string of arguments (e.g., '{"text": "Hello"}')

        Returns:
            JSON string containing the result (for json_extract_string)
        """
        import json

        try:
            # Parse args
            args = json.loads(args_json) if args_json else {}

            # Call via cascade system for observability
            result = execute_sql_function_sync(
                "skill",
                {"skill_name": skill_name, "args": json.dumps(args)}
            )

            # Normalize result to list for consistent structure
            if result is None:
                rows = [{"_skill": skill_name, "result": None}]
            elif isinstance(result, dict):
                rows = [result]
            elif isinstance(result, list):
                rows = result
            elif isinstance(result, str):
                # Try to parse as JSON
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, dict):
                        rows = [parsed]
                    elif isinstance(parsed, list):
                        rows = parsed
                    else:
                        rows = [{"_skill": skill_name, "result": parsed}]
                except json.JSONDecodeError:
                    rows = [{"_skill": skill_name, "result": result}]
            else:
                rows = [{"_skill": skill_name, "result": result}]

            # Return JSON string directly (not file path)
            return json.dumps(rows)

        except Exception as e:
            logger.error(f"skill_json UDF failed: {e}")
            return json.dumps([{"_skill": skill_name, "error": str(e)}])

    if safe_create_function(connection, "skill_json", skill_json_udf, existing, return_type="VARCHAR", null_handling="special"):
        logger.debug("Registered skill_json UDF")

    logger.info("Registered 8 embedding/skill UDFs for Semantic SQL")


def register_lars_udf(connection: duckdb.DuckDBPyConnection, config: Dict[str, Any] | None = None):
    """
    Register lars_udf as a DuckDB user-defined function.

    Args:
        connection: DuckDB connection to register with
        config: Optional UDF configuration:
            - model: Default model for UDF calls
            - temperature: Default temperature
            - max_tokens: Default max tokens
            - cache_enabled: Whether to use cache

    Example:
        conn = duckdb.connect()
        register_lars_udf(conn, {"model": "anthropic/claude-haiku-4.5"})

        # Now you can use it in SQL:
        result = conn.execute('''
            SELECT
              product_name,
              lars_udf('Extract brand', product_name) as brand
            FROM products
        ''').fetchdf()
    """
    # Check if already registered for this connection (Python-side optimization)
    conn_id = id(connection)
    if conn_id in _registered_connections:
        return  # Already registered in this Python session, skip

    config = config or {}

    # Get existing functions from DuckDB (handles multi-session case for persistent DBs)
    existing = get_registered_functions(connection)

    # Default config
    default_model = config.get("model")
    default_temperature = config.get("temperature", 0.0)
    default_max_tokens = config.get("max_tokens", 500)
    cache_enabled = config.get("cache_enabled", True)

    # Create wrapper with defaults
    def udf_wrapper(instructions: str, input_value: str) -> str:
        """Simple wrapper for SQL - takes 2 string arguments."""
        return lars_udf_impl(
            instructions=instructions,
            input_value=input_value,
            model=default_model,
            temperature=default_temperature,
            max_tokens=default_max_tokens,
            use_cache=cache_enabled
        )

    # Register core UDFs
    safe_create_function(connection, "lars", udf_wrapper, existing)
    safe_create_function(connection, "lars_udf", udf_wrapper, existing)

    # Cascade UDF wrapper
    def cascade_udf_wrapper(cascade_path: str, inputs_json: str) -> str:
        """Wrapper for cascade UDF - explicit return type."""
        return lars_cascade_udf_impl(cascade_path, inputs_json)

    safe_create_function(connection, "lars_run", cascade_udf_wrapper, existing, return_type="VARCHAR")
    safe_create_function(connection, "lars_cascade_udf", cascade_udf_wrapper, existing, return_type="VARCHAR")

    # Batch RUN UDF wrapper
    def run_batch_wrapper(cascade_path: str, rows_json: str, table_name: str) -> str:
        """Wrapper for batch RUN - creates temp table and runs cascade."""
        return lars_run_batch(cascade_path, rows_json, table_name, connection)

    safe_create_function(connection, "lars_run_batch", run_batch_wrapper, existing, return_type="VARCHAR")

    # Parallel MAP UDF (returns JSON, caller uses read_json() to convert to table)
    safe_create_function(connection, "lars_map_parallel_exec", lars_map_parallel_exec, existing, return_type="VARCHAR")

    # Table materialization UDF wrapper
    def materialize_wrapper(table_name: str, rows_json: str) -> str:
        """Wrapper for table materialization."""
        return lars_materialize_table(table_name, rows_json, connection)

    safe_create_function(connection, "lars_materialize_table", materialize_wrapper, existing, return_type="VARCHAR")

    # Mark this Python connection as registered
    _registered_connections.add(conn_id)

    # Register embedding operators (EMBED, VECTOR_SEARCH, SIMILAR_TO)
    # Pass existing set for consistent checking
    register_embedding_udfs(connection, existing)

    # Register LLM aggregate implementation functions
    try:
        from .llm_aggregates import register_llm_aggregates
        register_llm_aggregates(connection, config, existing)
    except ImportError:
        pass  # Module not available yet

    # Register dimension compute UDFs for GROUP BY dimension functions
    try:
        from .llm_aggregates import register_dimension_compute_udfs
        register_dimension_compute_udfs(connection, existing)
    except ImportError:
        pass  # Module not available yet

    # Register background job status UDFs
    _register_job_status_udfs(connection, existing)


def _register_job_status_udfs(connection: duckdb.DuckDBPyConnection, existing: set | None = None):
    """
    Register table-valued UDFs for checking background job status and logs.

    These query sql_query_log and unified_logs in ClickHouse, plus
    local _analysis table for ANALYZE query results.
    All functions return proper table results (can be used in FROM clause).

    Implementation: Python scalar functions return JSON, SQL TABLE macros
    wrap them with from_json+unnest to produce proper table output.

    Args:
        connection: DuckDB connection to register with
        existing: Pre-fetched set of existing function names (for batch efficiency)

    UDFs:
        job(job_id) - Get status of a single job (table function)
        jobs() - List recent jobs (last 24 hours, table function)
        await_job(job_id, timeout_seconds) - Wait for job completion (table function)
        messages(caller_id) - Get all unified_logs entries for a caller_id
        analysis(job_id) - Get analysis result for an ANALYZE job
        analyses() - List recent analyses

    Usage:
        SELECT * FROM job('job-swift-fox-abc123')
        SELECT * FROM jobs()
        SELECT * FROM await_job('job-swift-fox-abc123', 60)
        SELECT * FROM messages('job-swift-fox-abc123')
        SELECT * FROM analysis('analysis-swift-fox-abc123')
        SELECT * FROM analyses()
    """
    # Get existing functions if not provided
    if existing is None:
        existing = get_registered_functions(connection)
    import json

    def _safe_value(v):
        """Convert value to JSON-serializable type."""
        if v is None:
            return None
        if hasattr(v, 'isoformat'):  # datetime
            return v.isoformat()
        if hasattr(v, 'hex'):  # UUID
            return str(v)
        return v

    def _query_job(job_id: str) -> dict:
        """Query a job by job_id (caller_id) from sql_query_log, with stats from unified_logs."""
        from ..db_adapter import get_db
        db = get_db()

        # Query by caller_id (the woodland job ID)
        # Join with unified_logs to get:
        #   - total_cost: sum of all LLM costs
        #   - messages: count of all log entries
        #   - requests: count of actual LLM API calls (has request_id or cost)
        result = db.query(f"""
            SELECT
                q.caller_id as job_id,
                q.status,
                toString(q.started_at) as started_at,
                toString(q.completed_at) as completed_at,
                q.duration_ms,
                q.rows_output,
                COALESCE(agg.total_cost, 0) as total_cost,
                COALESCE(agg.messages, 0) as messages,
                COALESCE(agg.requests, 0) as requests,
                q.result_db_name,
                q.result_schema,
                q.result_table,
                q.error_message,
                q.query_raw
            FROM sql_query_log q
            LEFT JOIN (
                SELECT
                    caller_id,
                    SUM(cost) as total_cost,
                    COUNT(*) as messages,
                    countIf(request_id IS NOT NULL AND request_id != '' OR cost > 0) as requests
                FROM unified_logs
                WHERE caller_id = '{job_id}'
                GROUP BY caller_id
            ) agg ON agg.caller_id = q.caller_id
            WHERE q.caller_id = '{job_id}'
            ORDER BY q.started_at DESC
            LIMIT 1
        """)

        if not result:
            return {
                "job_id": job_id, "status": "not_found", "error_message": f"Job '{job_id}' not found",
                "started_at": None, "completed_at": None, "duration_ms": None,
                "rows_output": None, "total_cost": None, "messages": None, "requests": None,
                "result_db_name": None, "result_table": None, "query_preview": None
            }

        row = result[0]
        # Build result table path
        result_table_full = None
        if row.get('result_schema') and row.get('result_table'):
            result_table_full = f"{row['result_schema']}.{row['result_table']}"

        return {
            "job_id": _safe_value(row.get('job_id')),
            "status": _safe_value(row.get('status')),
            "started_at": _safe_value(row.get('started_at')),
            "completed_at": _safe_value(row.get('completed_at')),
            "duration_ms": _safe_value(row.get('duration_ms')),
            "rows_output": _safe_value(row.get('rows_output')),
            "total_cost": _safe_value(row.get('total_cost')),
            "messages": _safe_value(row.get('messages')),
            "requests": _safe_value(row.get('requests')),
            "result_db_name": _safe_value(row.get('result_db_name')),
            "result_table": result_table_full,
            "error_message": _safe_value(row.get('error_message')),
            "query_preview": (str(row.get('query_raw') or ''))[:200]
        }

    # Schema for job status result (used in from_json)
    JOB_SCHEMA = '''[{
        "job_id": "VARCHAR",
        "status": "VARCHAR",
        "started_at": "VARCHAR",
        "completed_at": "VARCHAR",
        "duration_ms": "DOUBLE",
        "rows_output": "BIGINT",
        "total_cost": "DOUBLE",
        "messages": "BIGINT",
        "requests": "BIGINT",
        "result_db_name": "VARCHAR",
        "result_table": "VARCHAR",
        "error_message": "VARCHAR",
        "query_preview": "VARCHAR"
    }]'''

    # --- Scalar functions that return JSON ---

    def job_json(job_id: str) -> str:
        """Get job status as JSON array (internal, use job() table function)."""
        try:
            row = _query_job(job_id)
            return json.dumps([row])
        except Exception as e:
            return json.dumps([{
                "job_id": job_id, "status": "error", "error_message": str(e),
                "started_at": None, "completed_at": None, "duration_ms": None,
                "rows_output": None, "total_cost": None, "messages": None, "requests": None,
                "result_db_name": None, "result_table": None, "query_preview": None
            }])

    def jobs_json() -> str:
        """List recent jobs as JSON array (internal, use jobs() table function)."""
        try:
            from ..db_adapter import get_db
            db = get_db()

            # Join with unified_logs to get stats per job:
            #   - total_cost: sum of all LLM costs
            #   - messages: count of all log entries
            #   - requests: count of actual LLM API calls (has request_id or cost)
            result = db.query("""
                SELECT
                    q.caller_id as job_id,
                    q.status,
                    toString(q.started_at) as started_at,
                    toString(q.completed_at) as completed_at,
                    q.duration_ms,
                    q.rows_output,
                    COALESCE(agg.total_cost, 0) as total_cost,
                    COALESCE(agg.messages, 0) as messages,
                    COALESCE(agg.requests, 0) as requests,
                    q.result_db_name,
                    q.result_schema,
                    q.result_table,
                    substring(q.query_raw, 1, 100) as query_preview
                FROM sql_query_log q
                LEFT JOIN (
                    SELECT
                        caller_id,
                        SUM(cost) as total_cost,
                        COUNT(*) as messages,
                        countIf(request_id IS NOT NULL AND request_id != '' OR cost > 0) as requests
                    FROM unified_logs
                    WHERE caller_id IN (
                        SELECT caller_id FROM sql_query_log
                        WHERE protocol = 'postgresql_wire_background'
                          AND started_at > now() - INTERVAL 24 HOUR
                    )
                    GROUP BY caller_id
                ) agg ON agg.caller_id = q.caller_id
                WHERE q.protocol = 'postgresql_wire_background'
                  AND q.started_at > now() - INTERVAL 24 HOUR
                ORDER BY q.started_at DESC
                LIMIT 100
            """)

            jobs = []
            for row in result:
                result_table_full = None
                if row.get('result_schema') and row.get('result_table'):
                    result_table_full = f"{row['result_schema']}.{row['result_table']}"

                jobs.append({
                    "job_id": _safe_value(row.get('job_id')),
                    "status": _safe_value(row.get('status')),
                    "started_at": _safe_value(row.get('started_at')),
                    "completed_at": _safe_value(row.get('completed_at')),
                    "duration_ms": _safe_value(row.get('duration_ms')),
                    "rows_output": _safe_value(row.get('rows_output')),
                    "total_cost": _safe_value(row.get('total_cost')),
                    "messages": _safe_value(row.get('messages')),
                    "requests": _safe_value(row.get('requests')),
                    "result_db_name": _safe_value(row.get('result_db_name')),
                    "result_table": result_table_full,
                    "error_message": None,
                    "query_preview": str(row.get('query_preview') or '')
                })

            # Return at least one row with nulls if empty (for schema consistency)
            if not jobs:
                jobs = [{
                    "job_id": None, "status": "no_jobs", "started_at": None,
                    "completed_at": None, "duration_ms": None, "rows_output": None,
                    "total_cost": None, "messages": None, "requests": None,
                    "result_db_name": None, "result_table": None, "error_message": None,
                    "query_preview": "No background jobs in last 24 hours"
                }]

            return json.dumps(jobs)

        except Exception as e:
            return json.dumps([{
                "job_id": None, "status": "error", "error_message": str(e),
                "started_at": None, "completed_at": None, "duration_ms": None,
                "rows_output": None, "total_cost": None, "messages": None, "requests": None,
                "result_db_name": None, "result_table": None, "query_preview": None
            }])

    def await_job_json(job_id: str, timeout_seconds: float = 300.0) -> str:
        """Wait for job completion and return status as JSON (internal)."""
        import time
        start = time.time()
        poll_interval = 0.5  # Start with 500ms

        while time.time() - start < timeout_seconds:
            row = _query_job(job_id)

            if row.get('status') == 'not_found':
                return json.dumps([row])

            status = row.get('status')
            if status in ('completed', 'error'):
                return json.dumps([row])

            # Exponential backoff up to 5 seconds
            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 5.0)

        return json.dumps([{
            "job_id": job_id, "status": "timeout",
            "error_message": f"Timeout waiting for job '{job_id}' after {timeout_seconds}s",
            "started_at": None, "completed_at": None, "duration_ms": None,
            "rows_output": None, "total_cost": None, "messages": None, "requests": None,
            "result_db_name": None, "result_table": None, "query_preview": None
        }])

    # Schema for messages result (unified_logs rows)
    MESSAGES_SCHEMA = '''[{
        "message_id": "VARCHAR",
        "timestamp": "VARCHAR",
        "session_id": "VARCHAR",
        "trace_id": "VARCHAR",
        "caller_id": "VARCHAR",
        "node_type": "VARCHAR",
        "role": "VARCHAR",
        "semantic_actor": "VARCHAR",
        "semantic_purpose": "VARCHAR",
        "cascade_id": "VARCHAR",
        "cell_name": "VARCHAR",
        "model": "VARCHAR",
        "provider": "VARCHAR",
        "request_id": "VARCHAR",
        "duration_ms": "DOUBLE",
        "tokens_in": "BIGINT",
        "tokens_out": "BIGINT",
        "total_tokens": "BIGINT",
        "cost": "DOUBLE",
        "is_sql_udf": "BOOLEAN",
        "udf_type": "VARCHAR",
        "cache_hit": "BOOLEAN",
        "content_preview": "VARCHAR",
        "tool_name": "VARCHAR",
        "error_message": "VARCHAR"
    }]'''

    def messages_json(caller_id: str) -> str:
        """Get all unified_logs entries for a caller_id (internal, use messages() table function)."""
        try:
            from ..db_adapter import get_db
            db = get_db()

            result = db.query(f"""
                SELECT
                    toString(message_id) as message_id,
                    toString(timestamp) as timestamp,
                    session_id,
                    trace_id,
                    caller_id,
                    node_type,
                    role,
                    semantic_actor,
                    semantic_purpose,
                    cascade_id,
                    cell_name,
                    model,
                    provider,
                    request_id,
                    duration_ms,
                    tokens_in,
                    tokens_out,
                    total_tokens,
                    cost,
                    is_sql_udf,
                    udf_type,
                    cache_hit,
                    substring(content, 1, 500) as content_preview,
                    JSONExtractString(tool_calls, '$[0].function.name') as tool_name,
                    error_message
                FROM unified_logs
                WHERE caller_id = '{caller_id}'
                ORDER BY timestamp DESC
                LIMIT 1000
            """)

            messages = []
            for row in result:
                messages.append({
                    "message_id": _safe_value(row.get('message_id')),
                    "timestamp": _safe_value(row.get('timestamp')),
                    "session_id": _safe_value(row.get('session_id')),
                    "trace_id": _safe_value(row.get('trace_id')),
                    "caller_id": _safe_value(row.get('caller_id')),
                    "node_type": _safe_value(row.get('node_type')),
                    "role": _safe_value(row.get('role')),
                    "semantic_actor": _safe_value(row.get('semantic_actor')),
                    "semantic_purpose": _safe_value(row.get('semantic_purpose')),
                    "cascade_id": _safe_value(row.get('cascade_id')),
                    "cell_name": _safe_value(row.get('cell_name')),
                    "model": _safe_value(row.get('model')),
                    "provider": _safe_value(row.get('provider')),
                    "request_id": _safe_value(row.get('request_id')),
                    "duration_ms": _safe_value(row.get('duration_ms')),
                    "tokens_in": _safe_value(row.get('tokens_in')),
                    "tokens_out": _safe_value(row.get('tokens_out')),
                    "total_tokens": _safe_value(row.get('total_tokens')),
                    "cost": _safe_value(row.get('cost')),
                    "is_sql_udf": _safe_value(row.get('is_sql_udf')),
                    "udf_type": _safe_value(row.get('udf_type')),
                    "cache_hit": _safe_value(row.get('cache_hit')),
                    "content_preview": _safe_value(row.get('content_preview')),
                    "tool_name": _safe_value(row.get('tool_name')),
                    "error_message": _safe_value(row.get('error_message'))
                })

            if not messages:
                messages = [{
                    "message_id": None, "timestamp": None, "session_id": None,
                    "trace_id": None, "caller_id": caller_id, "node_type": None,
                    "role": None, "semantic_actor": None, "semantic_purpose": None,
                    "cascade_id": None, "cell_name": None, "model": None,
                    "provider": None, "request_id": None, "duration_ms": None,
                    "tokens_in": None, "tokens_out": None, "total_tokens": None,
                    "cost": None, "is_sql_udf": None, "udf_type": None,
                    "cache_hit": None, "content_preview": f"No messages found for caller_id '{caller_id}'",
                    "tool_name": None, "error_message": None
                }]

            return json.dumps(messages)

        except Exception as e:
            return json.dumps([{
                "message_id": None, "timestamp": None, "session_id": None,
                "trace_id": None, "caller_id": caller_id, "node_type": None,
                "role": None, "semantic_actor": None, "semantic_purpose": None,
                "cascade_id": None, "cell_name": None, "model": None,
                "provider": None, "request_id": None, "duration_ms": None,
                "tokens_in": None, "tokens_out": None, "total_tokens": None,
                "cost": None, "is_sql_udf": None, "udf_type": None,
                "cache_hit": None, "content_preview": None,
                "tool_name": None, "error_message": str(e)
            }])

    # Register scalar JSON functions (internal use)
    safe_create_function(connection, "_job_json", job_json, existing, parameters=[str], return_type=str)
    safe_create_function(connection, "_jobs_json", jobs_json, existing, parameters=[], return_type=str)
    safe_create_function(connection, "_await_job_json", await_job_json, existing, parameters=[str, float], return_type=str)
    safe_create_function(connection, "_messages_json", messages_json, existing, parameters=[str], return_type=str)

    # Create TABLE macros that wrap the JSON functions
    # These allow: SELECT * FROM job('id')
    connection.execute(f'''
        CREATE OR REPLACE MACRO job(jid) AS TABLE
        SELECT item.* FROM (
            SELECT UNNEST(from_json(_job_json(jid), '{JOB_SCHEMA}')) as item
        )
    ''')

    connection.execute(f'''
        CREATE OR REPLACE MACRO jobs() AS TABLE
        SELECT item.* FROM (
            SELECT UNNEST(from_json(_jobs_json(), '{JOB_SCHEMA}')) as item
        )
    ''')

    connection.execute(f'''
        CREATE OR REPLACE MACRO await_job(jid, timeout_secs := 300.0) AS TABLE
        SELECT item.* FROM (
            SELECT UNNEST(from_json(_await_job_json(jid, timeout_secs), '{JOB_SCHEMA}')) as item
        )
    ''')

    # Aliases for compatibility
    connection.execute(f'''
        CREATE OR REPLACE MACRO job_status(jid) AS TABLE
        SELECT item.* FROM (
            SELECT UNNEST(from_json(_job_json(jid), '{JOB_SCHEMA}')) as item
        )
    ''')

    connection.execute(f'''
        CREATE OR REPLACE MACRO list_jobs() AS TABLE
        SELECT item.* FROM (
            SELECT UNNEST(from_json(_jobs_json(), '{JOB_SCHEMA}')) as item
        )
    ''')

    # messages() - get all unified_logs entries for a caller_id
    connection.execute(f'''
        CREATE OR REPLACE MACRO messages(cid) AS TABLE
        SELECT item.* FROM (
            SELECT UNNEST(from_json(_messages_json(cid), '{MESSAGES_SCHEMA}')) as item
        )
    ''')

    # analysis() and analyses() - query the local _analysis table
    # Create _analysis table if it doesn't exist (so macros work immediately)
    connection.execute('''
        CREATE TABLE IF NOT EXISTS _analysis (
            job_id VARCHAR PRIMARY KEY,
            prompt VARCHAR,
            analysis TEXT,
            query_sql VARCHAR,
            row_count INTEGER,
            column_count INTEGER,
            columns VARCHAR,
            result_table VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    ''')

    connection.execute('''
        CREATE OR REPLACE MACRO analysis(jid) AS TABLE
        SELECT * FROM _analysis WHERE job_id = jid
    ''')

    connection.execute('''
        CREATE OR REPLACE MACRO analyses() AS TABLE
        SELECT * FROM _analysis ORDER BY created_at DESC LIMIT 100
    ''')


def clear_udf_cache():
    """Clear all UDF result caches (simple, cascade, and aggregate)."""
    global _udf_cache, _cascade_udf_cache

    # Clear in-memory caches
    _udf_cache.clear()
    _cascade_udf_cache.clear()

    # Clear persistent cache (by function type)
    try:
        from .cache_adapter import get_cache
        cache = get_cache()
        cache.clear(function_name=_CACHE_TYPE_UDF)
        cache.clear(function_name=_CACHE_TYPE_CASCADE)
        cache.clear(function_name=_CACHE_TYPE_AGGREGATE)
    except Exception:
        pass

    # Also clear aggregate cache (in-memory)
    try:
        from .llm_aggregates import clear_agg_cache
        clear_agg_cache()
    except ImportError:
        pass


def get_udf_cache_stats() -> Dict[str, Any]:
    """
    Get UDF cache statistics.

    Combines stats from:
    - Persistent SemanticCache (L1 + L2)
    - Legacy in-memory caches (fallback)
    """
    # Get persistent cache stats
    try:
        from .cache_adapter import get_cache
        persistent_stats = get_cache().get_stats()
    except Exception:
        persistent_stats = None

    # Build stats from in-memory caches (legacy view)
    stats = {
        "simple_udf": {
            "cached_entries": len(_udf_cache),
            "cache_size_bytes": sum(len(k) + len(v[0]) for k, v in _udf_cache.items())
        },
        "cascade_udf": {
            "cached_entries": len(_cascade_udf_cache),
            "cache_size_bytes": sum(len(k) + len(v[0]) for k, v in _cascade_udf_cache.items())
        },
        "total_entries": len(_udf_cache) + len(_cascade_udf_cache)
    }

    # Include aggregate cache stats (in-memory)
    try:
        from .llm_aggregates import get_agg_cache_stats
        stats["aggregate_udf"] = get_agg_cache_stats()
        stats["total_entries"] += stats["aggregate_udf"]["cached_entries"]
    except ImportError:
        pass

    # Add persistent cache stats if available
    if persistent_stats:
        stats["persistent"] = persistent_stats

    return stats


# =============================================================================
# Arrow Vectorized UDF Support
# =============================================================================

import threading
import atexit

# Global shutdown event for graceful termination of parallel UDF execution
_shutdown_event = threading.Event()

def request_shutdown():
    """Signal all parallel UDF executors to stop."""
    _shutdown_event.set()

def is_shutdown_requested() -> bool:
    """Check if shutdown has been requested."""
    return _shutdown_event.is_set()

def reset_shutdown():
    """Reset shutdown flag (for testing)."""
    _shutdown_event.clear()

# Register cleanup on interpreter exit
atexit.register(request_shutdown)


def make_vectorized_wrapper(
    func_name: str,
    fn_entry,
    execute_fn,
):
    """
    Create an Arrow vectorized UDF wrapper for parallel batch execution.

    DuckDB's Arrow UDFs receive entire columns as PyArrow arrays in a single call,
    enabling internal parallelization with ThreadPoolExecutor. This provides
    automatic parallelism for semantic SQL operators without requiring explicit
    SQL annotations.

    Args:
        func_name: The function name (for cache keys and logging)
        fn_entry: The SQL function registry entry with args, returns, etc.
        execute_fn: The function to call for each row (execute_cascade_udf)

    Returns:
        A wrapper function compatible with DuckDB's Arrow UDF interface
    """
    import logging
    log = logging.getLogger(__name__)

    def vectorized_udf(*arrow_arrays):
        import pyarrow as pa
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from ..config import get_config
        from .cache_adapter import get_cache, SemanticCache
        from ..caller_context import get_caller_id

        # Helper to coerce result to expected type
        def coerce_result(result, return_type):
            """Coerce a result value to the expected return type."""
            try:
                if return_type == "BOOLEAN":
                    if isinstance(result, bool):
                        return result
                    elif isinstance(result, str):
                        lowered = result.strip().lower()
                        if lowered in ("true", "yes", "1"):
                            return True
                        elif lowered in ("false", "no", "0"):
                            return False
                        else:
                            return bool(result)
                    else:
                        return bool(result) if result is not None else False
                elif return_type == "DOUBLE":
                    if isinstance(result, (int, float)):
                        return float(result)
                    elif result is None:
                        return 0.0
                    else:
                        return float(str(result).strip())
                elif return_type == "INTEGER":
                    if isinstance(result, int):
                        return result
                    elif result is None:
                        return 0
                    else:
                        return int(float(str(result).strip()))
                else:
                    return str(result) if result is not None else ""
            except Exception:
                # If coercion fails, return safe default
                if return_type == "BOOLEAN":
                    return False
                elif return_type in ("DOUBLE", "INTEGER"):
                    return 0
                else:
                    return str(result) if result is not None else ""

        # Check if shutdown requested before starting work
        if is_shutdown_requested():
            log.warning(f"[VectorizedUDF] Shutdown requested, skipping {func_name}")
            return pa.array([], type=pa.string())

        config = get_config()
        max_workers = config.parallel_workers

        # Get caller_id ONCE at the start - this will read from ClickHouse
        # which works reliably across threads. We pass it explicitly to workers.
        caller_id = get_caller_id()
        if not caller_id:
            log.warning(f"[VectorizedUDF] {func_name}: No caller_id available for SQL trail tracking")

        # Handle empty input
        if not arrow_arrays or len(arrow_arrays[0]) == 0:
            return_type = fn_entry.returns
            if return_type == "BOOLEAN":
                return pa.array([], type=pa.bool_())
            elif return_type == "DOUBLE":
                return pa.array([], type=pa.float64())
            elif return_type == "INTEGER":
                return pa.array([], type=pa.int64())
            else:
                return pa.array([], type=pa.string())

        n_rows = len(arrow_arrays[0])
        arg_names = [a['name'] for a in fn_entry.args]

        # Build list of arg dicts for each row
        rows = []
        for i in range(n_rows):
            row_args = {}
            for j, name in enumerate(arg_names):
                if j < len(arrow_arrays):
                    val = arrow_arrays[j][i]
                    # Convert PyArrow scalar to Python value
                    row_args[name] = val.as_py() if hasattr(val, 'as_py') else val
            rows.append(row_args)

        # Compute cache keys for all rows
        cache = get_cache()
        cache_keys = [SemanticCache.make_cache_key(func_name, args) for args in rows]

        # Batch cache lookup
        cached_results = cache.get_batch(func_name, rows, track_hit=True)

        # Identify cache misses and coerce cache hits
        misses = []
        results = [None] * n_rows
        return_type = fn_entry.returns
        cache_hit_count = 0
        for i, (args, cache_key) in enumerate(zip(rows, cache_keys)):
            found, result, _ = cached_results.get(cache_key, (False, None, ""))
            if found:
                # Coerce cached result to expected type
                results[i] = coerce_result(result, return_type)
                cache_hit_count += 1
            else:
                misses.append((i, args, cache_key))

        # Track cache hits in SQL trail (execute_cascade_udf only handles misses)
        if cache_hit_count > 0 and caller_id:
            try:
                from ..sql_trail import increment_cache_hit
                for _ in range(cache_hit_count):
                    increment_cache_hit(caller_id)
            except Exception as e:
                log.debug(f"[VectorizedUDF] Failed to track cache hits: {e}")

        # Log cache stats for debugging
        if cache_hit_count > 0 or len(misses) > 0:
            log.debug(f"[VectorizedUDF] {func_name}: {cache_hit_count} cache hits, {len(misses)} to execute")

        # Execute cache misses in parallel
        if misses and not is_shutdown_requested():
            new_cache_items = []

            # Use thread_name_prefix for easier debugging
            executor = ThreadPoolExecutor(
                max_workers=min(max_workers, len(misses)),
                thread_name_prefix=f"UDF-{func_name}"
            )
            try:
                futures = {}
                for i, args, cache_key in misses:
                    # Check shutdown before submitting each task
                    if is_shutdown_requested():
                        log.info(f"[VectorizedUDF] Shutdown requested, stopping submission")
                        break
                    import json
                    # Pass caller_id explicitly to ensure cost tracking works in worker threads
                    future = executor.submit(execute_fn, func_name, json.dumps(args), True, caller_id)
                    futures[future] = (i, args, cache_key)

                for future in as_completed(futures, timeout=300):  # 5 min timeout per batch
                    # Check shutdown during result collection
                    if is_shutdown_requested():
                        log.info(f"[VectorizedUDF] Shutdown requested, cancelling remaining futures")
                        for f in futures:
                            f.cancel()
                        break

                    i, args, cache_key = futures[future]
                    try:
                        result = future.result(timeout=60)  # 60s timeout per result

                        # Coerce result using helper
                        coerced = coerce_result(result, return_type)
                        results[i] = coerced

                        # Queue for batch cache write (store raw result, coerce on read)
                        result_type_str = return_type if return_type in ("BOOLEAN", "DOUBLE", "INTEGER") else "VARCHAR"
                        new_cache_items.append((args, result, result_type_str))

                    except Exception as e:
                        log.warning(f"[VectorizedUDF] Error processing row {i}: {e}")
                        # Return error indicator based on type
                        results[i] = coerce_result(f"ERROR: {e}", return_type)

            finally:
                # Shutdown executor - use wait=False if shutdown requested for faster exit
                executor.shutdown(wait=not is_shutdown_requested(), cancel_futures=is_shutdown_requested())

            # Batch store new results
            if new_cache_items and not is_shutdown_requested():
                try:
                    cache.set_batch(func_name, new_cache_items)
                except Exception as e:
                    log.debug(f"[VectorizedUDF] Cache batch set error: {e}")

        # Final safety coercion - ensure all results have correct type for PyArrow
        # This handles any None values or unexpected types that slipped through
        return_type = fn_entry.returns
        coerced_results = [coerce_result(r, return_type) for r in results]

        # Convert to PyArrow array based on return type
        if return_type == "BOOLEAN":
            return pa.array(coerced_results, type=pa.bool_())
        elif return_type == "DOUBLE":
            return pa.array(coerced_results, type=pa.float64())
        elif return_type == "INTEGER":
            return pa.array(coerced_results, type=pa.int64())
        else:
            return pa.array(coerced_results, type=pa.string())

    return vectorized_udf


def _get_arrow_return_type(duckdb_type: str):
    """Map DuckDB return type to PyArrow type for Arrow UDF registration."""
    type_map = {
        "BOOLEAN": "BOOLEAN",
        "DOUBLE": "DOUBLE",
        "FLOAT": "FLOAT",
        "INTEGER": "INTEGER",
        "BIGINT": "BIGINT",
        "VARCHAR": "VARCHAR",
        "JSON": "VARCHAR",
        "TABLE": "VARCHAR",
    }
    return type_map.get(duckdb_type.upper(), "VARCHAR")


def register_dynamic_sql_functions(connection, existing: set | None = None):
    """
    Dynamically register all SQL functions from cascade registry.

    This discovers cascades in cascades/semantic_sql/*.yaml and registers
    them as DuckDB UDFs. Enables user-defined operators without code changes!

    Called once per DuckDB connection during postgres_server startup.

    Args:
        connection: DuckDB connection to register with
        existing: Pre-fetched set of existing function names (for batch efficiency)
    """
    try:
        from ..semantic_sql.registry import initialize_registry, get_sql_function_registry
        from ..semantic_sql.executor import execute_cascade_udf

        # Initialize registry to discover all cascades
        initialize_registry(force=True)
        registry = get_sql_function_registry()

        # Use provided existing set or query DuckDB for registered functions
        if existing is not None:
            existing_names = {name.lower() for name in existing}
        else:
            existing_names = {name.lower() for name in get_registered_functions(connection)}
        
        registered_count = 0
        skipped_count = 0

        for name, entry in registry.items():
            # Skip AGGREGATE-shaped functions UNLESS they return TABLE
            # TABLE-returning aggregates (like vector_search_elastic) should be registered
            # Only skip scalar aggregates (like llm_consensus) that have numbered UDFs
            if entry.shape.upper() == 'AGGREGATE' and entry.returns.upper() != 'TABLE':
                skipped_count += 1
                continue

            # Skip any function name that already exists in DuckDB (built-in or previously registered).
            # This replaces prior hardcoded skip lists and keeps us aligned with "cascades all the way down".
            if str(name).lower() in existing_names:
                skipped_count += 1
                continue

            # Create wrapper that calls execute_cascade_udf
            def make_wrapper(fn_name, fn_entry):
                def wrapper(*args):
                    # Convert args to inputs dict
                    arg_names = [a['name'] for a in fn_entry.args]
                    inputs = {arg_names[i]: args[i] if i < len(args) else None 
                             for i in range(len(arg_names))}
                    
                    # Remove None values
                    inputs = {k: v for k, v in inputs.items() if v is not None}
                    
                    # Call cascade via executor
                    import json
                    result = execute_cascade_udf(fn_name, json.dumps(inputs))

                    # DuckDB expects native Python types for scalar return types.
                    # `execute_cascade_udf()` returns a string (or JSON string) so we coerce
                    # to match the declared return type where needed.
                    try:
                        if fn_entry.returns == "BOOLEAN":
                            if isinstance(result, bool):
                                return result
                            if isinstance(result, str):
                                lowered = result.strip().lower()
                                if lowered in ("true", "yes", "1"):
                                    return True
                                if lowered in ("false", "no", "0"):
                                    return False
                            return bool(result)
                        if fn_entry.returns == "DOUBLE":
                            if isinstance(result, (int, float)):
                                return float(result)
                            return float(str(result).strip())
                        if fn_entry.returns == "INTEGER":
                            if isinstance(result, int):
                                return result
                            return int(float(str(result).strip()))
                    except Exception:
                        # If coercion fails, fall back to returning the raw result and let
                        # DuckDB attempt to coerce (or error).
                        return result

                    return result
                return wrapper
            
            # Register function with DuckDB
            try:
                # Map DuckDB types
                return_type = entry.returns
                if return_type == 'JSON':
                    return_type = 'VARCHAR'  # DuckDB doesn't have JSON type, use VARCHAR
                elif return_type == 'TABLE':
                    # Table-valued functions return JSON arrays that get parsed by read_json_auto
                    # Register as VARCHAR (returns JSON string)
                    return_type = 'VARCHAR'

                # Special handling for sql_statement mode: register as TABLE function
                # sql_statement functions return temp file paths, wrap with read_json_auto()
                if entry.output_mode == 'sql_statement':
                    # sql_statement uses scalar wrapper (returns file path)
                    udf_func = make_wrapper(name, entry)

                    # Register internal scalar function with _file suffix
                    internal_name = f"_{name}_file"

                    # Skip if internal function already exists
                    if internal_name.lower() in existing_names:
                        skipped_count += 1
                        continue

                    connection.create_function(
                        internal_name,
                        udf_func,
                        return_type='VARCHAR'  # Returns file path
                    )
                    existing_names.add(internal_name.lower())

                    # Build arg list for macro (e.g., "question" for ask_data)
                    arg_names = [a['name'] for a in entry.args]
                    macro_args = ', '.join(arg_names)
                    internal_call_args = ', '.join(arg_names)

                    # Create TABLE macro: SELECT * FROM ask_data('question')
                    # Uses read_json_auto to parse the temp file and return proper table results
                    connection.execute(f'''
                        CREATE OR REPLACE MACRO {name}({macro_args}) AS TABLE
                        SELECT * FROM read_json_auto({internal_name}({internal_call_args}))
                    ''')
                    existing_names.add(str(name).lower())
                    registered_count += 1
                    continue  # Skip normal registration

                # Determine whether to use Arrow vectorized UDF or scalar UDF
                # SCALAR shape functions benefit from parallel batch execution
                use_arrow = entry.shape.upper() == 'SCALAR'

                if use_arrow:
                    # Create Arrow vectorized wrapper for parallel execution
                    udf_func = make_vectorized_wrapper(name, entry, execute_cascade_udf)

                    # Register as Arrow UDF
                    connection.create_function(
                        name,
                        udf_func,
                        return_type=return_type,
                        type='arrow'  # Arrow vectorized UDF for batch parallelism
                    )
                else:
                    # Use standard scalar wrapper for non-SCALAR functions
                    udf_func = make_wrapper(name, entry)
                    connection.create_function(
                        name,
                        udf_func,
                        return_type=return_type
                    )

                existing_names.add(str(name).lower())
                registered_count += 1

                # ALSO register without "semantic_" prefix for SQL convenience
                if name.startswith('semantic_'):
                    short_name = name.replace('semantic_', '')
                    if short_name.lower() not in existing_names:
                        try:
                            if use_arrow:
                                connection.create_function(
                                    short_name, udf_func, return_type=return_type, type='arrow'
                                )
                            else:
                                connection.create_function(short_name, udf_func, return_type=return_type)
                            existing_names.add(short_name.lower())
                            registered_count += 1
                        except Exception:
                            pass  # Might conflict with hardcoded functions, that's OK

                # ALSO register additional aliases from operator patterns
                # Extract function names from patterns like "TLDR({{ text }})" or "CONDENSE(...)"
                import re
                for operator_pattern in entry.operators:
                    # Match function-style operators: FUNCNAME(...)
                    func_match = re.match(r'^([A-Z_]+)\s*\(', operator_pattern)
                    if func_match:
                        alias_name = func_match.group(1).lower()
                        # Only register if different from main function name and short_name
                        if alias_name != name and (not name.startswith('semantic_') or alias_name != short_name):
                            if alias_name not in existing_names:
                                try:
                                    if use_arrow:
                                        connection.create_function(
                                            alias_name, udf_func, return_type=return_type, type='arrow'
                                        )
                                    else:
                                        connection.create_function(alias_name, udf_func, return_type=return_type)
                                    existing_names.add(alias_name)
                                    registered_count += 1
                                except Exception:
                                    pass  # Might conflict, that's OK

            except Exception as e:
                # Only log unexpected errors (not "already exists")
                if "already exists" not in str(e).lower():
                    import logging
                    logging.getLogger(__name__).debug(f"[DynamicUDF] Could not register {name}: {e}")
                skipped_count += 1

        # Only print summary if we actually registered something new
        if registered_count > 0:
            print(f"[DynamicUDF] Registered {registered_count} new SQL functions")
        
    except Exception as e:
        print(f"[DynamicUDF] ERROR: Dynamic registration failed: {e}")
        import traceback
        traceback.print_exc()
