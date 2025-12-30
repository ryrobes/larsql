"""
rvbbit_udf() - LLM-powered SQL user-defined function.

This allows you to use LLMs directly in SQL queries for data enrichment:

    SELECT
      product_name,
      rvbbit_udf('Extract brand name', product_name) as brand,
      rvbbit_udf('Classify: electronics/clothing/home', product_name) as category
    FROM products

The UDF:
- Spawns mini LLM calls per row
- Caches results (same input → same output)
- Handles errors gracefully (returns NULL on failure)
- Supports batching for efficiency
"""

import hashlib
import json
from typing import Optional, Dict, Any
import duckdb


# Enhanced UDF cache with TTL support
# Format: Dict[key, Tuple[value, timestamp, ttl_seconds]]
_udf_cache: Dict[str, Tuple[str, float, Optional[float]]] = {}

# Enhanced cascade UDF cache with TTL support
_cascade_udf_cache: Dict[str, Tuple[str, float, Optional[float]]] = {}

# Track which connections have UDF registered (to avoid duplicate registration)
_registered_connections: set = set()


def _make_cache_key(instructions: str, input_value: str, model: str = None) -> str:
    """Create cache key for UDF result."""
    cache_str = f"{instructions}|{input_value}|{model or 'default'}"
    return hashlib.md5(cache_str.encode()).hexdigest()


def _make_cascade_cache_key(cascade_path: str, inputs: dict) -> str:
    """Create cache key for cascade UDF result."""
    # Sort inputs for consistent hashing
    inputs_str = json.dumps(inputs, sort_keys=True)
    cache_str = f"{cascade_path}|{inputs_str}"
    return hashlib.md5(cache_str.encode()).hexdigest()


def _cache_get(cache: dict, key: str) -> Optional[str]:
    """Get from cache, checking TTL expiry."""
    import time

    if key not in cache:
        return None

    value, timestamp, ttl = cache[key]

    # Check if expired
    if ttl is not None and (time.time() - timestamp) > ttl:
        del cache[key]  # Expired, remove
        return None

    return value


def _cache_set(cache: dict, key: str, value: str, ttl: Optional[float] = None):
    """Set in cache with optional TTL."""
    import time
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


def rvbbit_udf_impl(
    instructions: str,
    input_value: str,
    model: str = None,
    temperature: float = 0.0,
    max_tokens: int = 500,
    use_cache: bool = True,
    cache_ttl: Optional[str] = None
) -> str:
    """
    Core implementation of rvbbit_udf.

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
            return cached_value

    try:
        # Import bodybuilder tool and session naming
        from ..traits.bodybuilder import bodybuilder
        from ..session_naming import generate_woodland_id
        from rich.console import Console

        console = Console()

        # Generate proper session_id using woodland naming system
        woodland_id = generate_woodland_id()
        session_id = f"sql-udf-{woodland_id}"

        # Generate a unique cell name for logging
        import uuid
        cell_name = f"udf_rvbbit_{uuid.uuid4().hex[:8]}"

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
        console.print(f"[dim]🔧 rvbbit()[/dim] [cyan]{session_id}[/cyan] [dim]|[/dim] {instructions[:40]}... [dim]|[/dim] {input_preview}")

        # Call bodybuilder in request mode
        # This executes as a deterministic cell:
        #   - name: udf_rvbbit_<id>
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
            console.print(f"[red]✗ rvbbit() error:[/red] {error_msg[:50]}")
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
        console.print(f"[green]✓[/green] [dim]{model_used}[/dim] → {result_preview}")

        # Cache result with TTL
        if use_cache:
            ttl_seconds = _parse_duration(cache_ttl) if cache_ttl else None
            _cache_set(_udf_cache, cache_key, result, ttl_seconds)

        return result

    except Exception as e:
        # Log error with more detail
        import logging
        import traceback
        logging.getLogger(__name__).error(f"rvbbit_udf error for '{instructions}': {e}\n{traceback.format_exc()}")
        return f"ERROR: {str(e)[:50]}"


def rvbbit_cascade_udf_impl(
    cascade_path: str,
    inputs_json: str,
    use_cache: bool = True,
    return_field: Optional[str] = None
) -> str:
    """
    Run a complete cascade as a SQL UDF.

    This enables multi-phase LLM workflows per database row with full validation,
    soundings, wards, and all cascade features. Particularly powerful for:
    - Complex multi-step reasoning per row
    - Validated outputs (wards + output_schema)
    - Soundings per row (best-of-N selection)
    - Tool usage per row (query other data, call APIs)

    Args:
        cascade_path: Path to cascade file (e.g., "tackle/fraud_check.yaml")
        inputs_json: JSON string of cascade inputs (e.g., '{"customer_id": 123}')
        use_cache: Whether to use cache (default: True)
        return_field: Optional field to extract from result (e.g., "risk_score")
                     If None, returns full result as JSON string

    Returns:
        JSON string with cascade outputs, or specific field value if return_field specified

    Example SQL:
        SELECT
          customer_id,
          rvbbit_cascade_udf(
            'tackle/fraud_check.yaml',
            json_object('customer_id', customer_id)
          ) as fraud_analysis
        FROM transactions;

    With field extraction:
        SELECT
          customer_id,
          rvbbit_cascade_udf(
            'tackle/fraud_check.yaml',
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

        # Create cache key
        cache_key = _make_cascade_cache_key(cascade_path, inputs)

        # Check cache (TTL-aware)
        if use_cache:
            cached_result = _cache_get(_cascade_udf_cache, cache_key)
            if cached_result is not None:
                # If return_field specified, extract it
                if return_field:
                    result_obj = json.loads(cached_result)
                    # Try to extract from outputs first, then state
                    for phase_output in result_obj.get("outputs", {}).values():
                        if isinstance(phase_output, dict) and return_field in phase_output:
                            return str(phase_output[return_field])
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
        print(f"🔧 [UDF] Calling rvbbit_run: session={session_id}, input={str(inputs)[:50]}...")

        # Get caller context (set by SQL server before UDF was called)
        from ..caller_context import get_caller_context
        caller_id, invocation_metadata = get_caller_context()

        # Run cascade with caller tracking
        from ..runner import run_cascade

        result = run_cascade(
            resolved_path,
            inputs,
            session_id=session_id,
            caller_id=caller_id,
            invocation_metadata=invocation_metadata
        )

        # Serialize relevant outputs as JSON
        # We want to return something useful for SQL queries
        outputs = {}
        for phase_item in result.get("lineage", []):
            cell_name = phase_item.get("phase")
            phase_output = phase_item.get("output")
            if cell_name:
                outputs[cell_name] = phase_output

        json_result = json.dumps({
            "outputs": outputs,
            "state": result.get("state", {}),
            "status": result.get("status", "unknown"),
            "session_id": session_id,
            "has_errors": result.get("has_errors", False)
        })

        # Debug: Print completion
        state_output = result.get("state", {}).get("output_extract", "N/A")
        print(f"✅ [UDF] Completed: session={session_id}, output={str(state_output)[:30]}...")

        # Cache result (with infinite TTL for backward compatibility)
        if use_cache:
            _cache_set(_cascade_udf_cache, cache_key, json_result, ttl=None)

        # Extract specific field if requested
        if return_field:
            result_obj = json.loads(json_result)
            for phase_output in result_obj.get("outputs", {}).values():
                if isinstance(phase_output, dict) and return_field in phase_output:
                    return str(phase_output[return_field])
            if return_field in result_obj.get("state", {}):
                return str(result_obj["state"][return_field])
            # Field not found, return NULL
            return "NULL"

        return json_result

    except Exception as e:
        # Log error with detail
        import logging
        import traceback
        logging.getLogger(__name__).error(f"rvbbit_cascade_udf error for '{cascade_path}': {e}\n{traceback.format_exc()}")
        return json.dumps({"error": str(e), "status": "failed"})


def rvbbit_run_batch(
    cascade_path: str,
    rows_json_array: str,
    table_name: str,
    conn: duckdb.DuckDBPyConnection
) -> str:
    """
    Execute cascade once over batch of rows (RVBBIT RUN implementation).

    Creates temp table from rows, runs cascade with table reference.

    Args:
        cascade_path: Path to cascade file
        rows_json_array: JSON array of all rows
        table_name: Desired temp table name (e.g., 'batch_data')
        conn: DuckDB connection for temp table creation

    Returns:
        JSON metadata: {status, session_id, table_created, row_count}

    Example:
        result = rvbbit_run_batch(
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

        print(f"🔧 [RUN] Starting batch: session={session_id}, table={table_name}, rows={len(rows)}")

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

        print(f"✅ [RUN] Completed: session={session_id}, status={result.get('status')}")

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
        logging.getLogger(__name__).error(f"rvbbit_run_batch error: {e}\n{traceback.format_exc()}")
        return json_module.dumps({"error": str(e), "status": "failed"})


def rvbbit_run_parallel_batch(
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
        result = rvbbit_run_parallel_batch('x.yaml', '[{"id":1},{"id":2}]', 5)
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
                result_json = rvbbit_cascade_udf_impl(cascade_path, row_json, use_cache=True)
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
        logging.getLogger(__name__).error(f"rvbbit_run_parallel_batch error: {e}\n{traceback.format_exc()}")
        # Return error as NDJSON
        return json_module.dumps({"error": str(e)})


def rvbbit_map_parallel_exec(
    cascade_path: str,
    rows_json_array: str,
    max_workers: int,
    result_column: str
):
    """
    Execute cascade on multiple rows in parallel, return DataFrame.

    Used by RVBBIT MAP PARALLEL syntax. Each row becomes a cascade input,
    results are joined back to original columns in order.

    Args:
        cascade_path: Path to cascade file
        rows_json_array: JSON array of input rows from USING query
        max_workers: Max concurrent cascade executions
        result_column: Name for result column

    Returns:
        pandas DataFrame with enriched rows (DuckDB converts to relation automatically)

    Example:
        Input:  [{"id": 1, "text": "foo"}, {"id": 2, "text": "bar"}]
        Output: DataFrame with columns [id, text, result]
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import json as json_module
    import pandas as pd

    try:
        # Parse input rows
        rows = json_module.loads(rows_json_array)
        if not isinstance(rows, list):
            raise ValueError("Expected JSON array of rows")
        if len(rows) == 0:
            return pd.DataFrame()  # Empty DataFrame

        # Process rows in parallel with order preservation
        results = [None] * len(rows)

        def process_row(index, row):
            """Process single row, return (index, enriched_row)."""
            try:
                # Convert row to JSON for cascade input
                row_json = json_module.dumps(row)

                # Run cascade via rvbbit_cascade_udf_impl (handles context vars properly)
                result_json = rvbbit_cascade_udf_impl(cascade_path, row_json, use_cache=True)
                result_obj = json_module.loads(result_json)

                # Extract meaningful result
                # Priority: state.output_extract > last phase output > full result
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

        # Return as DataFrame (DuckDB converts to relation automatically)
        return pd.DataFrame(results)

    except Exception as e:
        import logging
        import traceback
        logging.getLogger(__name__).error(
            f"rvbbit_map_parallel_exec error: {e}\n{traceback.format_exc()}"
        )
        # Return error as DataFrame
        return pd.DataFrame([{
            "error": str(e),
            "hint": "Check cascade path and input data format"
        }])


def rvbbit_materialize_table(
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
        logging.getLogger(__name__).error(f"rvbbit_materialize_table error: {e}\n{traceback.format_exc()}")
        return json_module.dumps({"error": str(e), "status": "failed"})


def register_rvbbit_udf(connection: duckdb.DuckDBPyConnection, config: Dict[str, Any] = None):
    """
    Register rvbbit_udf as a DuckDB user-defined function.

    Args:
        connection: DuckDB connection to register with
        config: Optional UDF configuration:
            - model: Default model for UDF calls
            - temperature: Default temperature
            - max_tokens: Default max tokens
            - cache_enabled: Whether to use cache

    Example:
        conn = duckdb.connect()
        register_rvbbit_udf(conn, {"model": "anthropic/claude-haiku-4.5"})

        # Now you can use it in SQL:
        result = conn.execute('''
            SELECT
              product_name,
              rvbbit_udf('Extract brand', product_name) as brand
            FROM products
        ''').fetchdf()
    """
    # Check if already registered for this connection
    conn_id = id(connection)
    if conn_id in _registered_connections:
        return  # Already registered, skip

    config = config or {}

    # Default config
    default_model = config.get("model")
    default_temperature = config.get("temperature", 0.0)
    default_max_tokens = config.get("max_tokens", 500)
    cache_enabled = config.get("cache_enabled", True)

    # Create wrapper with defaults
    def udf_wrapper(instructions: str, input_value: str) -> str:
        """Simple wrapper for SQL - takes 2 string arguments."""
        return rvbbit_udf_impl(
            instructions=instructions,
            input_value=input_value,
            model=default_model,
            temperature=default_temperature,
            max_tokens=default_max_tokens,
            use_cache=cache_enabled
        )

    # Register as DuckDB UDF (simple API - DuckDB infers types for simple UDF)
    try:
        connection.create_function(
            "rvbbit",
            udf_wrapper
        )
        # Register alias
        connection.create_function(
            "rvbbit_udf",
            udf_wrapper
        )
        _registered_connections.add(conn_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not register rvbbit: {e}")

    # Register cascade UDF separately (with explicit return type)
    try:
        def cascade_udf_wrapper(cascade_path: str, inputs_json: str) -> str:
            """Wrapper for cascade UDF - explicit return type."""
            return rvbbit_cascade_udf_impl(cascade_path, inputs_json)

        connection.create_function(
            "rvbbit_run",
            cascade_udf_wrapper,
            return_type="VARCHAR"
        )
        # Register alias
        connection.create_function(
            "rvbbit_cascade_udf",
            cascade_udf_wrapper,
            return_type="VARCHAR"
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not register rvbbit_run: {e}")

    # Register batch RUN UDF (for RVBBIT RUN syntax)
    try:
        def run_batch_wrapper(cascade_path: str, rows_json: str, table_name: str) -> str:
            """Wrapper for batch RUN - creates temp table and runs cascade."""
            return rvbbit_run_batch(cascade_path, rows_json, table_name, connection)

        connection.create_function(
            "rvbbit_run_batch",
            run_batch_wrapper,
            return_type="VARCHAR"
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not register rvbbit_run_batch: {e}")

    # Register parallel MAP UDF (for RVBBIT MAP PARALLEL syntax)
    try:
        # Register as table-valued function (no return_type = DuckDB infers from DataFrame)
        connection.create_function(
            "rvbbit_map_parallel_exec",
            rvbbit_map_parallel_exec
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not register rvbbit_map_parallel_exec: {e}")

    # Register table materialization UDF (for CREATE TABLE AS / WITH as_table)
    try:
        def materialize_wrapper(table_name: str, rows_json: str) -> str:
            """Wrapper for table materialization."""
            return rvbbit_materialize_table(table_name, rows_json, connection)

        connection.create_function(
            "rvbbit_materialize_table",
            materialize_wrapper,
            return_type="VARCHAR"
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not register rvbbit_materialize_table: {e}")

    # TODO Phase 2B: Register parallel batch UDF when threading is implemented
    # try:
    #     connection.create_function(
    #         "rvbbit_run_parallel_batch",
    #         rvbbit_run_parallel_batch,
    #         return_type="VARCHAR"
    #     )
    # except Exception as e:
    #     import logging
    #     logging.getLogger(__name__).warning(f"Could not register rvbbit_run_parallel_batch: {e}")



def clear_udf_cache():
    """Clear all UDF result caches (simple and cascade)."""
    global _udf_cache, _cascade_udf_cache
    _udf_cache.clear()
    _cascade_udf_cache.clear()


def get_udf_cache_stats() -> Dict[str, Any]:
    """Get UDF cache statistics."""
    return {
        "simple_udf": {
            "cached_entries": len(_udf_cache),
            "cache_size_bytes": sum(len(k) + len(v) for k, v in _udf_cache.items())
        },
        "cascade_udf": {
            "cached_entries": len(_cascade_udf_cache),
            "cache_size_bytes": sum(len(k) + len(v) for k, v in _cascade_udf_cache.items())
        },
        "total_entries": len(_udf_cache) + len(_cascade_udf_cache)
    }
