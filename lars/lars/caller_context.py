"""
Caller Context System for LARS

Tracks the "caller" that initiated a cascade execution, enabling:
- Cost rollup by SQL query
- Debugging: "What spawned this session?"
- Analytics: Usage by origin (SQL vs UI vs CLI)

Uses SQLite scratch DB as the authoritative store for cross-thread access.
ContextVars and thread-local are kept for fast local access within the same thread.
"""

from contextvars import ContextVar
from typing import Optional, Dict, Any, Tuple, List
import threading
import json
import logging

log = logging.getLogger(__name__)


# ============================================================================
# Context Variables (Thread-Safe within single thread/coroutine)
# ============================================================================
# These provide fast access within the same thread - scratch is the fallback

_caller_id: ContextVar[Optional[str]] = ContextVar('caller_id', default=None)
_invocation_metadata: ContextVar[Optional[Dict]] = ContextVar('invocation_metadata', default=None)

# Thread-local for same-thread access (backup for contextvar)
_thread_local = threading.local()

# Lock for DuckDB attachments registry (still in-memory, not high-frequency)
_registry_lock = threading.Lock()

# DuckDB attachments for sql_statement execution
# We store attachment info (not the connection itself) to avoid deadlocks
_duckdb_attachments_registry: Dict[str, List[Tuple[str, str]]] = {}  # connection_id -> [(alias, path), ...]


# ============================================================================
# Scratch DB Operations
# ============================================================================

def _get_scratch_conn():
    """Get SQLite scratch connection, returns None if unavailable."""
    try:
        from .scratch_db import get_param_connection
        return get_param_connection()
    except Exception:
        return None


def _write_context_to_scratch(connection_id: str, caller_id: str, metadata: Dict[str, Any]):
    """Write caller context to scratch.caller_context table."""
    conn = _get_scratch_conn()
    if not conn:
        return

    try:
        import time
        conn.execute(
            """
            INSERT OR REPLACE INTO caller_context (connection_id, caller_id, metadata_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (connection_id, caller_id, json.dumps(metadata) if metadata else '{}', time.time())
        )
        conn.commit()
    except Exception as e:
        log.debug(f"[caller_context] Failed to write to scratch: {e}")


def _read_context_from_scratch(connection_id: str | None = None) -> Optional[Tuple[str, Dict]]:
    """
    Read caller context from scratch.caller_context table.

    Args:
        connection_id: Specific connection to look up, or None for most recent

    Returns:
        (caller_id, metadata) tuple or None if not found
    """
    conn = _get_scratch_conn()
    if not conn:
        return None

    try:
        if connection_id:
            cursor = conn.execute(
                "SELECT caller_id, metadata_json FROM caller_context WHERE connection_id = ?",
                (connection_id,)
            )
        else:
            # Fallback: get most recent entry (for UDF threads without connection_id)
            cursor = conn.execute(
                "SELECT caller_id, metadata_json FROM caller_context ORDER BY created_at DESC LIMIT 1"
            )

        row = cursor.fetchone()
        if row:
            caller_id = row[0] if isinstance(row, tuple) else row['caller_id']
            metadata_json = row[1] if isinstance(row, tuple) else row['metadata_json']
            try:
                metadata = json.loads(metadata_json) if metadata_json else {}
            except Exception:
                metadata = {}
            return (caller_id, metadata)

    except Exception as e:
        log.debug(f"[caller_context] Failed to read from scratch: {e}")

    return None


def _clear_context_from_scratch(connection_id: str):
    """
    Clear caller context from scratch DB.

    Unlike scratch with TTL, we explicitly delete old entries.
    Also cleans up entries older than 1 hour on each call.
    """
    conn = _get_scratch_conn()
    if not conn:
        return

    try:
        import time
        # Delete the specific connection
        conn.execute("DELETE FROM caller_context WHERE connection_id = ?", (connection_id,))
        # Also clean up stale entries (older than 1 hour)
        one_hour_ago = time.time() - 3600
        conn.execute("DELETE FROM caller_context WHERE created_at < ?", (one_hour_ago,))
        conn.commit()
    except Exception as e:
        log.debug(f"[caller_context] Failed to clear from scratch: {e}")


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


def get_duckdb_attachments(connection_id: str | None = None) -> List[Tuple[str, str]]:
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

def set_caller_context(caller_id: str, metadata: Dict[str, Any], connection_id: str | None = None):
    """
    Set caller context for current thread AND scratch (cross-thread access).

    Stores in:
    1. ContextVar (fast access within same thread/coroutine)
    2. Thread-local (backup for same thread)
    3. scratch.caller_context (authoritative cross-thread store)

    Args:
        caller_id: Unique identifier for the caller (e.g., 'sql-clever-fox-abc123')
        metadata: Invocation metadata dict
        connection_id: Connection ID for cross-thread access (required for SQL queries)

    Example:
        set_caller_context('sql-quick-rabbit-xyz', {
            'origin': 'sql',
            'sql_query': 'LARS MAP ...',
            'triggered_by': 'postgres_server'
        }, connection_id='pg_client_abc123')
    """
    # 1. Set in contextvar (fast local access)
    _caller_id.set(caller_id)
    _invocation_metadata.set(metadata)

    # 2. Set in thread-local (backup)
    _thread_local.caller_id = caller_id
    _thread_local.invocation_metadata = metadata

    # 3. Write to scratch (authoritative cross-thread store)
    if connection_id:
        _write_context_to_scratch(connection_id, caller_id, metadata)


def get_caller_id(connection_id: str | None = None) -> Optional[str]:
    """
    Get current caller_id, trying local storage first then scratch.

    Priority order:
    1. ContextVar (same thread/coroutine) - fastest
    2. Thread-local (same thread) - fast
    3. scratch.caller_context (cross-thread) - authoritative

    Args:
        connection_id: Optional connection ID for scratch lookup

    Returns:
        caller_id or None if not set
    """
    # 1. Try contextvar first (fastest, same thread)
    ctx_caller = _caller_id.get()
    if ctx_caller:
        return ctx_caller

    # 2. Try thread-local (same thread backup)
    try:
        tl_caller = getattr(_thread_local, 'caller_id', None)
        if tl_caller:
            return tl_caller
    except AttributeError:
        pass

    # 3. Fall back to scratch (cross-thread authoritative store)
    result = _read_context_from_scratch(connection_id)
    if result:
        return result[0]

    return None


def get_invocation_metadata(connection_id: str | None = None) -> Optional[Dict]:
    """
    Get current invocation metadata from context.

    Args:
        connection_id: Optional connection ID for scratch lookup

    Returns:
        metadata dict or None if not set
    """
    # Try contextvar first
    metadata = _invocation_metadata.get()
    if metadata:
        return metadata

    # Try thread-local
    try:
        tl_metadata = getattr(_thread_local, 'invocation_metadata', None)
        if tl_metadata:
            return tl_metadata
    except AttributeError:
        pass

    # Fall back to scratch
    result = _read_context_from_scratch(connection_id)
    if result:
        return result[1]

    return None


def get_caller_context(connection_id: str | None = None) -> tuple[Optional[str], Optional[Dict]]:
    """
    Get both caller_id and metadata in one call.

    Args:
        connection_id: Optional connection ID for scratch lookup

    Returns:
        (caller_id, metadata) tuple
    """
    # Try local first
    caller_id = _caller_id.get()
    metadata = _invocation_metadata.get()

    if caller_id:
        return (caller_id, metadata)

    # Try thread-local
    try:
        tl_caller = getattr(_thread_local, 'caller_id', None)
        tl_metadata = getattr(_thread_local, 'invocation_metadata', None)
        if tl_caller:
            return (tl_caller, tl_metadata)
    except AttributeError:
        pass

    # Fall back to scratch
    result = _read_context_from_scratch(connection_id)
    if result:
        return result

    return (None, None)


def clear_caller_context(connection_id: str | None = None):
    """
    Clear caller context from all storage layers.

    Args:
        connection_id: Connection ID to clear from scratch

    Useful for cleanup after execution or in test fixtures.
    """
    # Clear contextvar
    _caller_id.set(None)
    _invocation_metadata.set(None)

    # Clear thread-local
    try:
        _thread_local.caller_id = None
        _thread_local.invocation_metadata = None
    except AttributeError:
        pass

    # Clear from scratch
    if connection_id:
        _clear_context_from_scratch(connection_id)


def has_caller_context() -> bool:
    """
    Check if caller context is set (local only, fast check).

    Returns:
        True if caller_id is set in local context
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
    parallel_workers: Optional[int] = None,
    source_column: Optional[str] = None,
    source_row_index: Optional[int] = None,
    source_table: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build invocation metadata for SQL origin.

    Args:
        sql_query: Full SQL query text
        protocol: 'postgresql_wire' or 'http'
        triggered_by: 'postgres_server' or 'http_api'
        row_count: Expected rows to process (if known)
        parallel_workers: PARALLEL count (if specified)
        source_column: Column name being processed (for semantic operators)
        source_row_index: Row index in source query (for LARS MAP)
        source_table: Table name if extractable from query

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

    # SQL source lineage (for row/column tracking)
    if source_column is not None or source_row_index is not None or source_table is not None:
        metadata['source'] = {}
        if source_column is not None:
            metadata['source']['column'] = source_column
        if source_row_index is not None:
            metadata['source']['row_index'] = source_row_index
        if source_table is not None:
            metadata['source']['table'] = source_table

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
        source: 'skill', 'cascade', 'example', 'scratch'

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


# ============================================================================
# Legacy Compatibility
# ============================================================================
# These are kept for code that directly imports the global registry

_global_caller_registry: Dict[str, Tuple[str, Dict[str, Any]]] = {}

def _sync_to_legacy_registry(connection_id: str, caller_id: str, metadata: Dict):
    """Sync to legacy in-memory registry for backward compatibility."""
    with _registry_lock:
        _global_caller_registry[connection_id] = (caller_id, metadata)
