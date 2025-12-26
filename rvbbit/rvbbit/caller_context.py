"""
Caller Context System for RVBBIT

Tracks the "caller" that initiated a cascade execution, enabling:
- Cost rollup by SQL query
- Debugging: "What spawned this session?"
- Analytics: Usage by origin (SQL vs UI vs CLI)

Uses ContextVars for thread-safe context propagation.
"""

from contextvars import ContextVar
from typing import Optional, Dict, Any


# ============================================================================
# Context Variables (Thread-Safe)
# ============================================================================

_caller_id: ContextVar[Optional[str]] = ContextVar('caller_id', default=None)
_invocation_metadata: ContextVar[Optional[Dict]] = ContextVar('invocation_metadata', default=None)


# ============================================================================
# Context Management
# ============================================================================

def set_caller_context(caller_id: str, metadata: Dict[str, Any]):
    """
    Set caller context for current thread/async context.

    Args:
        caller_id: Unique identifier for the caller (e.g., 'sql-clever-fox-abc123')
        metadata: Invocation metadata dict

    Example:
        set_caller_context('sql-quick-rabbit-xyz', {
            'origin': 'sql',
            'sql_query': 'RVBBIT MAP ...',
            'triggered_by': 'postgres_server'
        })
    """
    _caller_id.set(caller_id)
    _invocation_metadata.set(metadata)


def get_caller_id() -> Optional[str]:
    """
    Get current caller_id from context.

    Returns:
        caller_id or None if not set
    """
    return _caller_id.get()


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


def clear_caller_context():
    """
    Clear caller context.

    Useful for cleanup after execution or in test fixtures.
    """
    _caller_id.set(None)
    _invocation_metadata.set(None)


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
