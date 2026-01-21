"""
Parameter Store

Session-scoped key-value storage for @param_get/@param_set operations.

Currently uses in-memory Python dict. Can be swapped to:
- ClickHouse memory table (queryable, survives backend restart)
- Redis (fast, TTL support)
- Any other backend

Session scoping is handled by prefixing keys with session_id.
"""

import logging
from typing import Optional
from threading import Lock
from datetime import datetime

logger = logging.getLogger(__name__)


# In-memory store: session_id -> {key -> ParamValue}
_param_store: dict[str, dict[str, 'ParamValue']] = {}
_store_lock = Lock()


class ParamValue:
    """A stored parameter value with metadata."""

    def __init__(self, value: Optional[str], set_at: datetime = None):
        self.value = value
        self.set_at = set_at or datetime.now()

    def __repr__(self):
        return f"ParamValue({self.value!r}, set_at={self.set_at})"


def param_store_get(
    session_id: str,
    key: str,
    default: Optional[str] = None
) -> Optional[str]:
    """
    Get a parameter value for a session.

    Args:
        session_id: The session identifier
        key: The parameter key
        default: Default value if not set

    Returns:
        The parameter value, or default if not set
    """
    with _store_lock:
        session_params = _param_store.get(session_id, {})
        param = session_params.get(key)

        if param is not None:
            logger.debug(f"param_get({session_id}, {key}) -> {param.value!r}")
            return param.value

        logger.debug(f"param_get({session_id}, {key}) -> default {default!r}")
        return default


def param_store_set(
    session_id: str,
    key: str,
    value: Optional[str]
) -> Optional[str]:
    """
    Set a parameter value for a session.

    Args:
        session_id: The session identifier
        key: The parameter key
        value: The value to set (None clears the param)

    Returns:
        The value that was set
    """
    with _store_lock:
        if session_id not in _param_store:
            _param_store[session_id] = {}

        if value is None:
            # Setting to None is equivalent to clearing
            _param_store[session_id].pop(key, None)
            logger.debug(f"param_set({session_id}, {key}) -> cleared")
        else:
            _param_store[session_id][key] = ParamValue(value)
            logger.debug(f"param_set({session_id}, {key}) -> {value!r}")

        return value


def param_store_clear(session_id: str, key: str) -> None:
    """
    Clear a parameter for a session.

    Args:
        session_id: The session identifier
        key: The parameter key to clear
    """
    with _store_lock:
        if session_id in _param_store:
            _param_store[session_id].pop(key, None)
            logger.debug(f"param_clear({session_id}, {key})")


def param_store_clear_session(session_id: str) -> None:
    """
    Clear all parameters for a session.

    Args:
        session_id: The session identifier
    """
    with _store_lock:
        _param_store.pop(session_id, None)
        logger.debug(f"param_clear_session({session_id})")


def param_store_list(session_id: str) -> dict[str, str]:
    """
    List all parameters for a session.

    Args:
        session_id: The session identifier

    Returns:
        Dict of key -> value for all params in session
    """
    with _store_lock:
        session_params = _param_store.get(session_id, {})
        return {k: v.value for k, v in session_params.items()}


def param_store_stats() -> dict:
    """
    Get stats about the param store.

    Returns:
        Dict with session_count, total_params, etc.
    """
    with _store_lock:
        total_params = sum(len(params) for params in _param_store.values())
        return {
            'session_count': len(_param_store),
            'total_params': total_params,
            'sessions': {
                sid: len(params) for sid, params in _param_store.items()
            }
        }


# ============================================================================
# Array storage functions (for multi-select)
# ============================================================================

# In-memory array store: session_id -> {key -> list[str]}
_params_store: dict[str, dict[str, list[str]]] = {}
_params_store_lock = Lock()


def params_store_get(
    session_id: str,
    key: str,
) -> list[str]:
    """
    Get an array parameter value for a session.

    Args:
        session_id: The session identifier
        key: The parameter key

    Returns:
        The array of values, or empty list if not set
    """
    with _params_store_lock:
        session_params = _params_store.get(session_id, {})
        values = session_params.get(key, [])
        logger.debug(f"params_get({session_id}, {key}) -> {values!r}")
        return values


def params_store_set(
    session_id: str,
    key: str,
    value: str
) -> list[str]:
    """
    Add a value to an array parameter for a session.

    If the value already exists in the array, it's removed (toggle behavior).
    This enables checkbox-style multi-select.

    Args:
        session_id: The session identifier
        key: The parameter key
        value: The value to add/toggle

    Returns:
        The updated array of values
    """
    with _params_store_lock:
        if session_id not in _params_store:
            _params_store[session_id] = {}

        if key not in _params_store[session_id]:
            _params_store[session_id][key] = []

        values = _params_store[session_id][key]

        # Toggle behavior: if exists, remove; otherwise add
        if value in values:
            values.remove(value)
            logger.debug(f"params_set({session_id}, {key}) toggle OFF: {value!r} -> {values!r}")
        else:
            values.append(value)
            logger.debug(f"params_set({session_id}, {key}) toggle ON: {value!r} -> {values!r}")

        return values


def params_store_clear(session_id: str, key: str) -> None:
    """
    Clear an array parameter for a session.

    Args:
        session_id: The session identifier
        key: The parameter key to clear
    """
    with _params_store_lock:
        if session_id in _params_store:
            _params_store[session_id].pop(key, None)
            logger.debug(f"params_clear({session_id}, {key})")


def params_store_clear_session(session_id: str) -> None:
    """
    Clear all array parameters for a session.

    Args:
        session_id: The session identifier
    """
    with _params_store_lock:
        _params_store.pop(session_id, None)
        logger.debug(f"params_clear_session({session_id})")


# Cleanup function for testing
def _reset_store() -> None:
    """Reset both stores (for testing only)."""
    global _param_store, _params_store
    with _store_lock:
        _param_store = {}
    with _params_store_lock:
        _params_store = {}
