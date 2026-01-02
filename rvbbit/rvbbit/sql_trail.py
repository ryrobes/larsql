"""
SQL Trail - Query lifecycle tracking and fingerprinting.

Provides query-level observability for SQL-driven LLM workflows where the unit
of work is the SQL query (via caller_id), not individual sessions.

Core Functions:
- fingerprint_query(sql) - Normalize SQL via sqlglot AST, extract UDF types
- log_query_start(caller_id, query, protocol) - Insert to sql_query_log
- log_query_complete(query_id, status, rows, duration) - Update completion
- log_query_error(query_id, error) - Update with error
- increment_cache_hit(caller_id) - Atomic counter increment
- increment_cache_miss(caller_id) - Atomic counter increment
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Optional, List, Tuple, Dict, Any

logger = logging.getLogger(__name__)

# ============================================================================
# Cascade Tracking (Thread-Safe)
# ============================================================================
# Tracks which cascades were executed for each caller_id
# This allows sql_query_log to record cascade_paths

_cascade_registry: Dict[str, List[Dict[str, Any]]] = {}
_cascade_lock = Lock()

# Cache for schema checks
_cascade_columns_exist: Optional[bool] = None


def _has_cascade_columns(db) -> bool:
    """
    Check if sql_query_log has cascade tracking columns.

    Caches result to avoid repeated DESCRIBE queries.
    Returns True if cascade_paths and cascade_count columns exist.
    """
    global _cascade_columns_exist

    if _cascade_columns_exist is not None:
        return _cascade_columns_exist

    try:
        result = db.execute("DESCRIBE TABLE sql_query_log")
        columns = {row[0] for row in result}
        _cascade_columns_exist = 'cascade_count' in columns and 'cascade_paths' in columns

        if not _cascade_columns_exist:
            logger.info(
                "SQL Trail: cascade_paths/cascade_count columns not found. "
                "Run migration: ALTER TABLE sql_query_log ADD COLUMN cascade_paths Array(String) DEFAULT [], "
                "ADD COLUMN cascade_count UInt16 DEFAULT 0"
            )
    except Exception as e:
        logger.debug(f"SQL Trail: Could not check for cascade columns: {e}")
        _cascade_columns_exist = False

    return _cascade_columns_exist


# Try to import sqlglot for AST-based fingerprinting
try:
    import sqlglot
    from sqlglot import exp
    SQLGLOT_AVAILABLE = True
except ImportError:
    SQLGLOT_AVAILABLE = False
    logger.info("sqlglot not available - SQL fingerprinting will use raw hash fallback")


# Known RVBBIT UDF function names (lowercase for matching)
RVBBIT_UDF_NAMES = {
    'rvbbit_udf', 'rvbbit', 'rvbbit_cascade_udf', 'rvbbit_run',
    'rvbbit_run_batch', 'rvbbit_run_parallel_batch', 'rvbbit_map_parallel_exec',
    'llm_summarize', 'llm_classify', 'llm_sentiment', 'llm_themes', 'llm_agg',
    'llm_matches', 'llm_score', 'llm_match_pair', 'llm_match_template', 'llm_semantic_case',
    'matches', 'score', 'match_pair', 'match_template', 'semantic_case'
}


def fingerprint_query(sql: str) -> Tuple[str, str, List[str]]:
    """
    Normalize SQL query to a fingerprint and extract UDF types.

    Uses sqlglot to parse the SQL, extract RVBBIT UDF function calls,
    and normalize literals to placeholders for consistent fingerprinting.

    Args:
        sql: Raw SQL query string

    Returns:
        Tuple of (fingerprint_hash, template, udf_types)
        - fingerprint_hash: MD5 of normalized query (16 chars)
        - template: SQL with literals replaced by ? placeholders
        - udf_types: List of RVBBIT UDF types found (e.g., ['rvbbit_udf', 'llm_summarize'])
    """
    if not SQLGLOT_AVAILABLE:
        # Fallback: simple hash of raw query
        fingerprint = hashlib.md5(sql.encode()).hexdigest()[:16]
        return fingerprint, sql, _extract_udf_types_regex(sql)

    try:
        # Parse SQL using DuckDB dialect
        parsed = sqlglot.parse_one(sql, dialect='duckdb')

        # Extract UDF types from function calls
        udf_types = _extract_udf_types_ast(parsed)

        # Normalize: replace literals with placeholders
        normalized = _normalize_literals(parsed)
        template = normalized.sql(dialect='duckdb')

        # Compute fingerprint from normalized SQL
        fingerprint = hashlib.md5(template.encode()).hexdigest()[:16]

        return fingerprint, template, udf_types

    except Exception as e:
        # Fallback on parse error
        logger.debug(f"sqlglot parse failed, using raw hash fallback: {e}")
        fingerprint = hashlib.md5(sql.encode()).hexdigest()[:16]
        return fingerprint, sql, _extract_udf_types_regex(sql)


def _extract_udf_types_ast(ast: 'exp.Expression') -> List[str]:
    """Extract RVBBIT UDF function calls from parsed AST."""
    udf_types = set()

    for func in ast.find_all(exp.Func):
        func_name = (func.name or '').lower()
        if func_name in RVBBIT_UDF_NAMES:
            udf_types.add(func_name)

    return sorted(udf_types)


def _extract_udf_types_regex(sql: str) -> List[str]:
    """Fallback: extract UDF types using regex (when sqlglot fails)."""
    import re
    sql_lower = sql.lower()
    udf_types = set()

    for udf_name in RVBBIT_UDF_NAMES:
        # Look for function call pattern: udf_name(
        if re.search(rf'\b{udf_name}\s*\(', sql_lower):
            udf_types.add(udf_name)

    return sorted(udf_types)


def _normalize_literals(ast: 'exp.Expression') -> 'exp.Expression':
    """Replace literal values with ? placeholders for fingerprinting."""
    def transform(node):
        if isinstance(node, exp.Literal):
            # Replace all literals with placeholder
            return exp.Placeholder(this='?')
        return node

    return ast.transform(transform)


def _determine_query_type(udf_types: List[str], sql: str) -> str:
    """Determine the primary query type based on UDFs found."""
    sql_upper = sql.upper()

    # Check for specific patterns
    if 'rvbbit_cascade_udf' in udf_types or 'rvbbit_run' in udf_types:
        return 'rvbbit_cascade_udf'
    if 'rvbbit_run_parallel_batch' in udf_types or 'rvbbit_map_parallel_exec' in udf_types:
        return 'rvbbit_map'
    if 'rvbbit_udf' in udf_types or 'rvbbit' in udf_types:
        return 'rvbbit_udf'
    if any(udf in udf_types for udf in ['llm_summarize', 'llm_classify', 'llm_sentiment', 'llm_themes', 'llm_agg']):
        return 'llm_aggregate'
    if any(udf in udf_types for udf in ['matches', 'score', 'match_pair', 'semantic_case']):
        return 'semantic_op'

    # Check for RVBBIT MAP/RUN syntax
    if 'RVBBIT MAP' in sql_upper:
        return 'rvbbit_map'
    if 'RVBBIT RUN' in sql_upper:
        return 'rvbbit_run'

    if udf_types:
        return udf_types[0]  # First UDF type found

    return 'plain_sql'


def log_query_start(
    caller_id: str,
    query_raw: str,
    protocol: str,
    client_info: Optional[str] = None
) -> Optional[str]:
    """
    Log query start to sql_query_log and return query_id.

    This should be called when a SQL query begins execution, before any
    UDF calls are made. The query_id is used to update the record later
    with completion status, duration, and cache metrics.

    Args:
        caller_id: Unique identifier for this query (e.g., "sql-clever-fox-abc123")
        query_raw: Full SQL query text
        protocol: Source protocol ("postgresql_wire", "http", "notebook")
        client_info: Optional client information (e.g., IP address)

    Returns:
        query_id UUID string, or None on error
    """
    query_id = str(uuid.uuid4())
    fingerprint, template, udf_types = fingerprint_query(query_raw)
    query_type = _determine_query_type(udf_types, query_raw)

    try:
        from .db_adapter import get_db
        db = get_db()

        db.insert_rows('sql_query_log', [{
            'query_id': query_id,
            'caller_id': caller_id,
            'query_raw': query_raw,
            'query_fingerprint': fingerprint,
            'query_template': template,
            'query_type': query_type,
            'udf_types': udf_types,
            'udf_count': len(udf_types),
            'started_at': datetime.now(timezone.utc),
            'status': 'running',
            'protocol': protocol,
            'timestamp': datetime.now(timezone.utc),
        }])

        logger.debug(f"SQL Trail: Started query {query_id[:8]} ({query_type})")
        return query_id

    except Exception as e:
        logger.error(f"SQL Trail: Failed to log query start: {e}")
        return None


def log_query_complete(
    query_id: Optional[str],
    status: str = 'completed',
    rows_output: Optional[int] = None,
    duration_ms: Optional[float] = None,
    total_cost: Optional[float] = None,
    total_tokens_in: Optional[int] = None,
    total_tokens_out: Optional[int] = None,
    llm_calls_count: Optional[int] = None,
    cascade_paths: Optional[List[str]] = None,
    cascade_count: Optional[int] = None
):
    """
    Update query log with completion data.

    Called after query execution finishes (successfully or with error).
    Uses ClickHouse ALTER TABLE UPDATE for in-place modification.

    Args:
        query_id: The query_id returned from log_query_start
        status: Completion status ('completed', 'error', 'cancelled')
        rows_output: Number of rows returned by the query
        duration_ms: Total execution time in milliseconds
        total_cost: Aggregated LLM cost for all calls spawned by this query
        total_tokens_in: Total input tokens across all LLM calls
        total_tokens_out: Total output tokens across all LLM calls
        llm_calls_count: Total number of LLM calls made
        cascade_paths: List of cascade file paths executed by this query
        cascade_count: Number of cascade executions
    """
    if not query_id:
        return

    try:
        from .db_adapter import get_db
        db = get_db()

        # Build SET clause dynamically
        updates = [f"status = '{status}'", "completed_at = now64(6)"]

        if duration_ms is not None:
            updates.append(f"duration_ms = {duration_ms}")
        if rows_output is not None:
            updates.append(f"rows_output = {rows_output}")
        if total_cost is not None:
            updates.append(f"total_cost = {total_cost}")
        if total_tokens_in is not None:
            updates.append(f"total_tokens_in = {total_tokens_in}")
        if total_tokens_out is not None:
            updates.append(f"total_tokens_out = {total_tokens_out}")
        if llm_calls_count is not None:
            updates.append(f"llm_calls_count = {llm_calls_count}")
        # Cascade tracking columns (added in later migration)
        # Check if columns exist before adding to update
        if cascade_paths or cascade_count is not None:
            if _has_cascade_columns(db):
                if cascade_paths:
                    paths_str = "['" + "','".join(p.replace("'", "\\'") for p in cascade_paths) + "']"
                    updates.append(f"cascade_paths = {paths_str}")
                if cascade_count is not None:
                    updates.append(f"cascade_count = {cascade_count}")

        set_clause = ', '.join(updates)

        db.execute(f"""
            ALTER TABLE sql_query_log
            UPDATE {set_clause}
            WHERE query_id = '{query_id}'
        """)

        logger.debug(f"SQL Trail: Completed query {query_id[:8]} ({status})")

    except Exception as e:
        logger.debug(f"SQL Trail: Failed to log query complete: {e}")


def log_query_error(
    query_id: Optional[str],
    error_message: str,
    error_type: Optional[str] = None,
    duration_ms: Optional[float] = None
):
    """
    Update query log with error data.

    Called when query execution fails with an exception.

    Args:
        query_id: The query_id returned from log_query_start
        error_message: Error message text
        error_type: Optional error type (e.g., exception class name)
        duration_ms: Optional duration until error in milliseconds
    """
    if not query_id:
        return

    try:
        from .db_adapter import get_db
        db = get_db()

        # Escape single quotes for SQL
        safe_msg = error_message.replace("'", "''")[:500]

        updates = [
            "status = 'error'",
            "completed_at = now64(6)",
            f"error_message = '{safe_msg}'"
        ]
        if duration_ms is not None:
            updates.append(f"duration_ms = {duration_ms}")

        set_clause = ', '.join(updates)

        db.execute(f"""
            ALTER TABLE sql_query_log
            UPDATE {set_clause}
            WHERE query_id = '{query_id}'
        """)

        logger.debug(f"SQL Trail: Query {query_id[:8]} error: {error_message[:50]}")

    except Exception as e:
        logger.debug(f"SQL Trail: Failed to log query error: {e}")


def increment_cache_hit(caller_id: Optional[str]):
    """
    Increment cache_hits counter for a query.

    Called when a UDF returns a cached result instead of calling LLM.
    Uses ClickHouse atomic increment.

    Args:
        caller_id: The caller_id for the current SQL query
    """
    if not caller_id:
        return

    try:
        from .db_adapter import get_db
        db = get_db()

        db.execute(f"""
            ALTER TABLE sql_query_log
            UPDATE cache_hits = cache_hits + 1
            WHERE caller_id = '{caller_id}'
        """)

    except Exception as e:
        # Fire-and-forget - don't fail the main path
        logger.debug(f"SQL Trail: Failed to increment cache hit: {e}")


def increment_cache_miss(caller_id: Optional[str]):
    """
    Increment cache_misses counter for a query.

    Called when a UDF actually invokes LLM (cache miss).
    Uses ClickHouse atomic increment.

    Args:
        caller_id: The caller_id for the current SQL query
    """
    if not caller_id:
        return

    try:
        from .db_adapter import get_db
        db = get_db()

        db.execute(f"""
            ALTER TABLE sql_query_log
            UPDATE cache_misses = cache_misses + 1
            WHERE caller_id = '{caller_id}'
        """)

    except Exception as e:
        # Fire-and-forget - don't fail the main path
        logger.debug(f"SQL Trail: Failed to increment cache miss: {e}")


def increment_llm_call(caller_id: Optional[str]):
    """
    Increment llm_calls_count counter for a query.

    Called when a UDF makes an LLM call.
    Uses ClickHouse atomic increment.

    Args:
        caller_id: The caller_id for the current SQL query
    """
    if not caller_id:
        return

    try:
        from .db_adapter import get_db
        db = get_db()

        db.execute(f"""
            ALTER TABLE sql_query_log
            UPDATE llm_calls_count = llm_calls_count + 1
            WHERE caller_id = '{caller_id}'
        """)

    except Exception as e:
        # Fire-and-forget - don't fail the main path
        logger.debug(f"SQL Trail: Failed to increment LLM call count: {e}")


def aggregate_query_costs(caller_id: str) -> dict:
    """
    Aggregate costs from all LLM calls spawned by a SQL query.

    Queries unified_logs to sum up costs, tokens, and call counts
    for all sessions/messages with the given caller_id.

    Args:
        caller_id: The caller_id for the SQL query

    Returns:
        Dict with aggregated metrics: {total_cost, total_tokens_in, total_tokens_out, llm_calls_count}
    """
    try:
        from .db_adapter import get_db
        db = get_db()

        result = db.query(f"""
            SELECT
                SUM(cost) as total_cost,
                SUM(tokens_in) as total_tokens_in,
                SUM(tokens_out) as total_tokens_out,
                COUNT(*) as llm_calls_count
            FROM unified_logs
            WHERE caller_id = '{caller_id}'
              AND cost IS NOT NULL
        """)

        if result:
            return {
                'total_cost': result[0].get('total_cost'),
                'total_tokens_in': result[0].get('total_tokens_in'),
                'total_tokens_out': result[0].get('total_tokens_out'),
                'llm_calls_count': result[0].get('llm_calls_count', 0)
            }

    except Exception as e:
        logger.debug(f"SQL Trail: Failed to aggregate costs: {e}")

    return {}


# ============================================================================
# Cascade Execution Tracking
# ============================================================================

def register_cascade_execution(
    caller_id: str,
    cascade_id: str,
    cascade_path: str,
    session_id: str,
    inputs: Optional[Dict] = None
):
    """
    Register a cascade execution for a SQL query.

    Called when execute_cascade_udf runs a cascade. This tracks which
    cascades were invoked by a SQL query for later logging.

    Args:
        caller_id: The caller_id for the parent SQL query
        cascade_id: The cascade's ID (e.g., 'semantic_matches')
        cascade_path: Path to the cascade file
        session_id: The session_id created for this cascade run
        inputs: Optional dict of inputs passed to the cascade
    """
    if not caller_id:
        return

    entry = {
        'cascade_id': cascade_id,
        'cascade_path': cascade_path,
        'session_id': session_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'inputs_summary': str(inputs)[:200] if inputs else None
    }

    with _cascade_lock:
        if caller_id not in _cascade_registry:
            _cascade_registry[caller_id] = []
        _cascade_registry[caller_id].append(entry)

    logger.debug(f"SQL Trail: Registered cascade {cascade_id} for {caller_id[:16]}")


def get_cascade_executions(caller_id: str) -> List[Dict[str, Any]]:
    """
    Get all cascade executions for a caller_id.

    Args:
        caller_id: The caller_id to look up

    Returns:
        List of cascade execution dicts
    """
    with _cascade_lock:
        return _cascade_registry.get(caller_id, []).copy()


def get_cascade_paths(caller_id: str) -> List[str]:
    """
    Get unique cascade paths executed for a caller_id.

    Args:
        caller_id: The caller_id to look up

    Returns:
        List of unique cascade file paths
    """
    with _cascade_lock:
        executions = _cascade_registry.get(caller_id, [])
        paths = list(set(e['cascade_path'] for e in executions if e.get('cascade_path')))
        return sorted(paths)


def clear_cascade_executions(caller_id: str):
    """
    Clear cascade execution records for a caller_id.

    Called after logging is complete to prevent memory leaks.

    Args:
        caller_id: The caller_id to clear
    """
    with _cascade_lock:
        if caller_id in _cascade_registry:
            del _cascade_registry[caller_id]


def get_cascade_summary(caller_id: str) -> Dict[str, Any]:
    """
    Get a summary of cascade executions for a caller_id.

    Returns aggregated info about all cascades run by this query.

    Args:
        caller_id: The caller_id to summarize

    Returns:
        Dict with cascade_count, cascade_paths, session_ids
    """
    with _cascade_lock:
        executions = _cascade_registry.get(caller_id, [])

    if not executions:
        return {
            'cascade_count': 0,
            'cascade_paths': [],
            'cascade_ids': [],
            'session_ids': []
        }

    return {
        'cascade_count': len(executions),
        'cascade_paths': list(set(e['cascade_path'] for e in executions if e.get('cascade_path'))),
        'cascade_ids': list(set(e['cascade_id'] for e in executions if e.get('cascade_id'))),
        'session_ids': [e['session_id'] for e in executions if e.get('session_id')]
    }
