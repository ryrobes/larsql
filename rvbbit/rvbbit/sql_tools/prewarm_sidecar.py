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

    # 2. Analyze query for prewarm opportunities
    from .prewarm_analyzer import analyze_query_for_prewarm
    specs = analyze_query_for_prewarm(query)

    if not specs:
        log.debug("[prewarm] No eligible scalar semantic functions found")
        return None

    log.info(f"[prewarm] Found {len(specs)} prewarm opportunities: {[s['function'] for s in specs]}")

    # 3. Execute distinct queries NOW (on main thread, fast SQL only)
    #    This gets us the values before launching the background thread
    prewarm_data = _fetch_distinct_values(specs, duckdb_conn)

    if not prewarm_data:
        log.debug("[prewarm] No values to prewarm")
        return None

    total_values = sum(len(d['values']) for d in prewarm_data)
    log.info(f"[prewarm] Launching sidecar for {total_values} total distinct values")

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

        for _, _, annotation in annotations:
            if annotation.parallel:
                return annotation.parallel

    except Exception as e:
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
    """
    from rvbbit.runner import RVBBITRunner

    sidecar_session = f"prewarm_{uuid.uuid4().hex[:8]}"

    log.info(f"[prewarm] Sidecar {sidecar_session} started (parent: {caller_id})")

    for data in prewarm_data:
        function = data['function']
        cascade = data['cascade']
        input_key = data['input_key']
        values = data['values']

        log.info(f"[prewarm] Processing {function}: {len(values)} values with {parallel} workers")

        # Track stats
        completed = 0
        cache_hits = 0
        errors = 0

        def process_value(value):
            nonlocal completed, cache_hits, errors
            try:
                # Create runner with parent tracking
                # Each value gets a unique session for isolation, but shares parent_session_id
                value_session = f"{sidecar_session}_{function}_{abs(hash(str(value))) % 10000:04d}"

                runner = RVBBITRunner(
                    cascade,
                    session_id=value_session,
                    parent_session_id=caller_id,  # Links cost to original query
                    caller_id=caller_id,          # Propagates to logs
                )

                result = runner.run(input_data={input_key: str(value)})

                completed += 1

                # Check if this was a cache hit (result came back instantly)
                # The cache check happens inside the cascade execution
                # We can infer cache hit by checking if lineage is empty/minimal
                if result and 'lineage' in result:
                    # If lineage has no LLM calls, it was likely cached
                    lineage = result.get('lineage', [])
                    if not lineage or all(not l.get('model') for l in lineage):
                        cache_hits += 1

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
