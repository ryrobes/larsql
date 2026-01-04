"""
Prewarm Sidecar - Background cache warming for scalar semantic SQL functions.

When a query has `-- @ parallel: N` annotation AND contains eligible scalar
semantic functions, this module launches a background "sidecar" that races
to pre-populate the cache while the main query executes serially.

The sidecar:
1. Extracts distinct values for each scalar semantic function arg
2. Runs the cascade in parallel (N workers) for those values
3. Cache hits accelerate the main query's serial execution

This is a "race to warm the cache" optimization that doesn't change SQL semantics.
If the sidecar fails or is slow, the main query still works (just slower).

Usage:
    -- @ parallel: 5
    SELECT semantic_clean_year(year_field), name
    FROM products
    WHERE status = 'active'

The sidecar will:
1. Run: SELECT DISTINCT year_field FROM products WHERE status = 'active' LIMIT 500
2. For each distinct value, run the clean_year cascade in parallel (5 workers)
3. Cache gets warmed, main query gets cache hits
"""

import threading
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any

log = logging.getLogger(__name__)


def maybe_launch_prewarm_sidecar(
    query: str,
    caller_id: str,
    duckdb_conn,
) -> Optional[threading.Thread]:
    """
    Check if query has `-- @ parallel: N` annotation and launch prewarm sidecar.

    Args:
        query: The SQL query string
        caller_id: The caller/session ID for cost tracking
        duckdb_conn: DuckDB connection for executing distinct queries

    Returns:
        The sidecar thread if launched, None otherwise.
        Caller can optionally join() the thread to wait for completion.
    """
    # 1. Check for -- @ parallel: N annotation
    parallel = _get_parallel_annotation(query)
    if not parallel:
        return None

    log.info(f"[prewarm] Detected parallel annotation: {parallel} workers")
    print(f"🚀 [prewarm] Detected -- @ parallel: {parallel}")

    # 2. Analyze query for prewarm opportunities
    from .prewarm_analyzer import analyze_query_for_prewarm
    specs = analyze_query_for_prewarm(query)

    if not specs:
        print(f"⚠️ [prewarm] No eligible scalar semantic functions found in query")
        log.debug("[prewarm] No eligible scalar semantic functions found")
        return None

    log.info(f"[prewarm] Found {len(specs)} prewarm opportunities: {[s['function'] for s in specs]}")
    print(f"🚀 [prewarm] Found {len(specs)} eligible functions: {[s['function'] for s in specs]}")

    # 3. Execute distinct queries NOW (on main thread, fast SQL only)
    #    This gets us the values before launching the background thread
    prewarm_data = _fetch_distinct_values(specs, duckdb_conn)

    if not prewarm_data:
        log.debug("[prewarm] No values to prewarm")
        return None

    total_values = sum(len(d['values']) for d in prewarm_data)
    log.info(f"[prewarm] Launching sidecar for {total_values} total distinct values")
    print(f"🚀 [prewarm] Launching sidecar: {total_values} distinct values, {parallel} workers")

    # 4. Launch sidecar thread
    sidecar = threading.Thread(
        target=_run_prewarm_sidecar,
        args=(prewarm_data, parallel, caller_id),
        daemon=True,  # Don't block process exit
        name=f"prewarm-{caller_id[:8] if caller_id else 'unknown'}",
    )
    sidecar.start()

    return sidecar


def _get_parallel_annotation(query: str) -> Optional[int]:
    """Extract parallel worker count from query annotation."""
    try:
        from .semantic_operators import _parse_annotations
        annotations = _parse_annotations(query)

        print(f"🔍 [prewarm] Parsed {len(annotations)} annotation blocks from query")
        for i, (line, pos, annotation) in enumerate(annotations):
            print(f"🔍 [prewarm]   [{i}] line={line}, parallel={annotation.parallel}, model={annotation.model}")
            if annotation.parallel:
                return annotation.parallel

    except Exception as e:
        print(f"⚠️ [prewarm] Failed to parse annotations: {e}")
        import traceback
        traceback.print_exc()
        log.debug(f"[prewarm] Failed to parse annotations: {e}")

    return None


def _fetch_distinct_values(
    specs: List[Dict[str, Any]],
    duckdb_conn,
) -> List[Dict[str, Any]]:
    """
    Execute distinct queries for each prewarm spec.

    This runs on the main thread before launching the sidecar.
    Fast operation - just SQL, no LLM calls.
    """
    prewarm_data = []

    for spec in specs:
        try:
            result = duckdb_conn.execute(spec['distinct_query']).fetchall()
            values = [row[0] for row in result if row[0] is not None]

            if values:
                prewarm_data.append({
                    'function': spec['function'],
                    'cascade': spec['cascade'],
                    'input_key': spec.get('input_key', 'text'),
                    'values': values,
                    'distinct_query': spec['distinct_query'],  # For logging
                })
                log.debug(f"[prewarm] {spec['function']}: {len(values)} distinct values")

        except Exception as e:
            log.warning(f"[prewarm] Distinct query failed for {spec['function']}: {e}")
            log.debug(f"[prewarm] Query was: {spec['distinct_query']}")

    return prewarm_data


def _run_prewarm_sidecar(
    prewarm_data: List[Dict[str, Any]],
    parallel: int,
    caller_id: str,
):
    """
    Run the prewarm sidecar in a background thread.

    For each function's distinct values, runs the cascade in parallel.
    Cache hits from this warm the cache for the main query.

    IMPORTANT: Uses execute_sql_function_sync to ensure results are cached
    with the same keys as the main query execution path.
    """
    from rvbbit.semantic_sql.registry import execute_sql_function_sync, get_cached_result

    sidecar_session = f"prewarm_{uuid.uuid4().hex[:8]}"

    log.info(f"[prewarm] Sidecar {sidecar_session} started (parent: {caller_id})")
    print(f"🔥 [prewarm] Sidecar {sidecar_session} started")

    for data in prewarm_data:
        function = data['function']
        input_key = data['input_key']
        values = data['values']
        # Get all args info for multi-argument functions
        all_args = data.get('all_args', [])
        arg_names = data.get('arg_names', [input_key])
        column_arg_index = data.get('column_arg_index', 0)

        log.info(f"[prewarm] Processing {function}: {len(values)} values with {parallel} workers")
        print(f"🔥 [prewarm] Processing {function}: {len(values)} values, {parallel} workers")

        # Track stats
        completed = 0
        cache_hits = 0
        errors = 0

        def process_value(value):
            nonlocal completed, cache_hits, errors
            try:
                # Build args dict matching what the UDF passes
                # Include ALL arguments for proper cache key matching
                args = {}

                for i, arg_info in enumerate(all_args):
                    if i < len(arg_names):
                        arg_name = arg_names[i]
                    else:
                        arg_name = f'arg{i}'

                    if i == column_arg_index:
                        # This is the variable column - use the distinct value
                        args[arg_name] = str(value)
                    elif not arg_info.get('is_column', False):
                        # This is a constant - parse the SQL literal
                        const_sql = arg_info.get('sql', '')
                        # Strip quotes from string literals
                        if const_sql.startswith("'") and const_sql.endswith("'"):
                            args[arg_name] = const_sql[1:-1]
                        elif const_sql.startswith('"') and const_sql.endswith('"'):
                            args[arg_name] = const_sql[1:-1]
                        else:
                            args[arg_name] = const_sql

                # Fallback: if no all_args, just use input_key
                if not args:
                    args = {input_key: str(value)}

                # Debug: show what we're caching
                if completed == 0:  # Only log first value
                    import json
                    print(f"🔍 [prewarm] Cache key preview: {function}:{json.dumps(args, sort_keys=True)[:100]}")

                # Check if already cached (another thread may have done it)
                found, _ = get_cached_result(function, args)
                if found:
                    cache_hits += 1
                    completed += 1
                    return

                # Execute through the registry's SQL function path
                # This ensures the result gets cached with the correct key
                value_session = f"{sidecar_session}_{function}_{abs(hash(str(value))) % 10000:04d}"

                execute_sql_function_sync(
                    name=function,
                    args=args,
                    session_id=value_session,
                )

                completed += 1

            except Exception as e:
                errors += 1
                log.debug(f"[prewarm] Failed for value '{str(value)[:50]}': {e}")

        # Run in parallel with thread pool
        with ThreadPoolExecutor(max_workers=parallel, thread_name_prefix=f"prewarm-{function}") as executor:
            list(executor.map(process_value, values))

        log.info(
            f"[prewarm] {function} complete: "
            f"{completed}/{len(values)} processed, "
            f"~{cache_hits} cache hits, "
            f"{errors} errors"
        )

    log.info(f"[prewarm] Sidecar {sidecar_session} finished")


# ============================================================
# Integration helper for postgres_server.py
# ============================================================

def wrap_query_with_prewarm(
    execute_fn,
    query: str,
    caller_id: str,
    duckdb_conn,
):
    """
    Wrapper that launches prewarm sidecar before executing main query.

    Usage in postgres_server.py:
        result = wrap_query_with_prewarm(
            lambda: self.duckdb_conn.execute(query),
            query,
            caller_id,
            self.duckdb_conn
        )

    Args:
        execute_fn: Function that executes the main query
        query: The SQL query string
        caller_id: Caller ID for tracking
        duckdb_conn: DuckDB connection

    Returns:
        Result of execute_fn()
    """
    # Launch sidecar (non-blocking)
    sidecar = maybe_launch_prewarm_sidecar(query, caller_id, duckdb_conn)

    try:
        # Execute main query
        return execute_fn()
    finally:
        # Optionally wait for sidecar to finish (or let it continue in background)
        # For now, we don't wait - the sidecar races with the main query
        pass
