"""
Caller Context System for RVBBIT

Tracks the "caller" that initiated a cascade execution, enabling:
- Cost rollup by SQL query
- Debugging: "What spawned this session?"
- Analytics: Usage by origin (SQL vs UI vs CLI)

Uses ContextVars for thread-safe context propagation PLUS a global registry
for DuckDB UDFs (which execute in DuckDB's internal thread pool where contextvars don't work).
"""

from contextvars import ContextVar
from typing import Optional, Dict, Any, Tuple, List
import threading


# ============================================================================
# Context Variables (Thread-Safe within single thread/coroutine)
# ============================================================================

_caller_id: ContextVar[Optional[str]] = ContextVar('caller_id', default=None)
_invocation_metadata: ContextVar[Optional[Dict]] = ContextVar('invocation_metadata', default=None)


# ============================================================================
# Global Registry (Cross-Thread Access for DuckDB UDFs)
# ============================================================================
# DuckDB executes UDFs in its own thread pool, so contextvars don't work.
# We use:
# 1. Thread-local storage (for postgres_server query execution thread)
# 2. Global fallback registry (keyed by connection_id)

_thread_local = threading.local()
_global_caller_registry: Dict[str, Tuple[str, Dict[str, Any]]] = {}
_registry_lock = threading.Lock()

# DuckDB attachments for sql_statement execution
# We store attachment info (not the connection itself) to avoid deadlocks
# The connection is busy during UDF execution, so we create a sibling connection
_duckdb_attachments_registry: Dict[str, List[Tuple[str, str]]] = {}  # connection_id -> [(alias, path), ...]


# ============================================================================
# DuckDB Connection Management
# ============================================================================

def set_duckdb_attachments(connection_id: str, attachments: List[Tuple[str, str]]):
    """
    Register DuckDB attachment info for UDF access.

    Instead of storing the connection (which causes deadlocks), we store
    the attachment info so execute_sql_statement can create a sibling
    connection with the same attached databases.

    Args:
        connection_id: Unique identifier (e.g., postgres session_id)
        attachments: List of (alias, path) tuples for ATTACH commands
    """
    with _registry_lock:
        _duckdb_attachments_registry[connection_id] = attachments


def get_duckdb_attachments(connection_id: str = None) -> List[Tuple[str, str]]:
    """
    Get DuckDB attachment info for creating a sibling connection.

    Args:
        connection_id: Optional connection ID to look up

    Returns:
        List of (alias, path) tuples or empty list
    """
    with _registry_lock:
        # Try specific connection first
        if connection_id and connection_id in _duckdb_attachments_registry:
            return _duckdb_attachments_registry[connection_id]

        # Fallback: return any attachments (queries are serialized anyway)
        if _duckdb_attachments_registry:
            return next(iter(_duckdb_attachments_registry.values()))

    return []


def clear_duckdb_attachments(connection_id: str):
    """
    Remove DuckDB attachment info from the registry.

    Args:
        connection_id: Connection ID to remove
    """
    with _registry_lock:
        _duckdb_attachments_registry.pop(connection_id, None)


# ============================================================================
# Context Management
# ============================================================================

def set_caller_context(caller_id: str, metadata: Dict[str, Any], connection_id: str = None):
    """
    Set caller context for current thread/async context AND all storage layers.

    Sets in 3 places for maximum compatibility:
    1. Contextvar (works within same thread/coroutine)
    2. Thread-local (works for postgres_server's query execution thread)
    3. Global registry (works across ALL threads, keyed by connection_id)

    Args:
        caller_id: Unique identifier for the caller (e.g., 'sql-clever-fox-abc123')
        metadata: Invocation metadata dict
        connection_id: Optional connection ID for DuckDB UDF access (postgres session_id)

    Example:
        set_caller_context('sql-quick-rabbit-xyz', {
            'origin': 'sql',
            'sql_query': 'RVBBIT MAP ...',
            'triggered_by': 'postgres_server'
        }, connection_id='pg_client_abc123')
    """
    # 1. Set in contextvar (works within same thread)
    _caller_id.set(caller_id)
    _invocation_metadata.set(metadata)

    # 2. Set in thread-local (persists for query execution thread, accessible to DuckDB callbacks)
    _thread_local.caller_id = caller_id
    _thread_local.invocation_metadata = metadata

    # 3. Set in global registry (works across ALL threads if connection_id known)
    if connection_id:
        with _registry_lock:
            _global_caller_registry[connection_id] = (caller_id, metadata)


def get_caller_id(connection_id: str = None) -> Optional[str]:
    """
    Get current caller_id from any available storage layer.

    Tries in priority order:
    1. Contextvar (same thread/coroutine)
    2. Thread-local (same thread, works for DuckDB UDF callbacks)
    3. Global registry with specific connection_id
    4. Global registry search (any connection - fallback for DuckDB UDFs)

    Args:
        connection_id: Optional connection ID to look up in global registry

    Returns:
        caller_id or None if not set
    """
    # 1. Try contextvar first (works within same thread/coroutine)
    ctx_caller = _caller_id.get()
    if ctx_caller:
        return ctx_caller

    # 2. Try thread-local (works for DuckDB UDF callbacks on query thread)
    try:
        tl_caller = getattr(_thread_local, 'caller_id', None)
        if tl_caller:
            return tl_caller
    except AttributeError:
        pass

    # 3. Try global registry with specific connection_id
    if connection_id:
        with _registry_lock:
            entry = _global_caller_registry.get(connection_id)
            if entry:
                return entry[0]  # Return caller_id

    # 4. Last resort: search global registry for ANY caller_id (for DuckDB UDFs)
    # Since postgres_server queries are serialized (db_lock), this is safe
    with _registry_lock:
        if _global_caller_registry:
            # Return the first (and likely only) caller_id
            result = next(iter(_global_caller_registry.values()))[0]
            # DEBUG: Log when we fall back to global registry
            #print(f"[caller_context] get_caller_id() using global registry fallback: {result}")
            return result

    # DEBUG: Log when no caller_id is found
    #print(f"[caller_context] get_caller_id() returning None - no caller context set")
    return None


def get_invocation_metadata() -> Optional[Dict]:
    """
    Get current invocation metadata from context.

    Returns:
        metadata dict or None if not set
    """
    return _invocation_metadata.get()


def get_caller_context() -> tuple[Optional[str], Optional[Dict]]:
    """
    Get both caller_id and metadata in one call.

    Returns:
        (caller_id, metadata) tuple
    """
    return _caller_id.get(), _invocation_metadata.get()


def clear_caller_context(connection_id: str = None):
    """
    Clear caller context from contextvar AND global registry.

    Args:
        connection_id: Optional connection ID to remove from global registry

    Useful for cleanup after execution or in test fixtures.
    """
    # Clear contextvar
    _caller_id.set(None)
    _invocation_metadata.set(None)

    # Clear from global registry
    if connection_id:
        with _registry_lock:
            _global_caller_registry.pop(connection_id, None)


def has_caller_context() -> bool:
    """
    Check if caller context is set.

    Returns:
        True if caller_id is set
    """
    return _caller_id.get() is not None


# ============================================================================
# Context Builders (Helpers)
# ============================================================================

def build_sql_metadata(
    sql_query: str,
    protocol: str,
    triggered_by: str,
    row_count: Optional[int] = None,
    parallel_workers: Optional[int] = None
) -> Dict[str, Any]:
    """
    Build invocation metadata for SQL origin.

    Args:
        sql_query: Full SQL query text
        protocol: 'postgresql_wire' or 'http'
        triggered_by: 'postgres_server' or 'http_api'
        row_count: Expected rows to process (if known)
        parallel_workers: PARALLEL count (if specified)

    Returns:
        Metadata dict
    """
    import hashlib
    from datetime import datetime, timezone

    metadata = {
        'origin': 'sql',
        'triggered_by': triggered_by,
        'invocation_timestamp': datetime.now(timezone.utc).isoformat(),
        'sql': {
            'query': sql_query,
            'query_hash': hashlib.md5(sql_query.encode()).hexdigest(),
            'protocol': protocol
        }
    }

    if row_count is not None:
        metadata['sql']['row_count'] = row_count

    if parallel_workers is not None:
        metadata['sql']['parallel_workers'] = parallel_workers

    return metadata


def build_cli_metadata(command_args: list, cascade_file: str, input_source: str) -> Dict[str, Any]:
    """
    Build invocation metadata for CLI origin.

    Args:
        command_args: sys.argv
        cascade_file: Path to cascade file
        input_source: 'file', 'inline', or 'stdin'

    Returns:
        Metadata dict
    """
    from datetime import datetime, timezone

    return {
        'origin': 'cli',
        'triggered_by': 'cli',
        'invocation_timestamp': datetime.now(timezone.utc).isoformat(),
        'cli': {
            'command': ' '.join(command_args),
            'cascade_file': cascade_file,
            'input_source': input_source
        }
    }


def build_ui_metadata(component: str, action: str, source: str) -> Dict[str, Any]:
    """
    Build invocation metadata for UI origin.

    Args:
        component: 'playground', 'notebook', 'sessions', etc.
        action: 'run', 're-run', 'fork', 'auto-fix'
        source: 'trait', 'cascade', 'example', 'scratch'

    Returns:
        Metadata dict
    """
    from datetime import datetime, timezone

    return {
        'origin': 'ui',
        'triggered_by': 'dashboard_ui',
        'invocation_timestamp': datetime.now(timezone.utc).isoformat(),
        'ui': {
            'component': component,
            'action': action,
            'cascade_source': source
        }
    }
