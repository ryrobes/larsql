"""
Parameter Store - User-Scoped Key-Value Storage

Provides persistent parameter storage for @param_get/@param_set operations,
scoped by user_id and database_name.

Uses SQLite scratch database (/dev/shm/lars_scratch.db) for fast, cross-process
key-value storage. The scratch DB is RAM-backed (tmpfs) and shared across all
connections.

Usage:
    from lars.auth.param_store import get_param_store

    store = get_param_store()

    # Single values
    store.set('user123', 'mydb', 'filter_category', 'electronics')
    value = store.get('user123', 'mydb', 'filter_category')

    # Array values (for multi-select)
    store.set_array('user123', 'mydb', 'selected_depts', ['HR', 'Sales'])
    values = store.get_array('user123', 'mydb', 'selected_depts')
    
SQL Access (via DuckDB):
    -- Scratch DB is auto-attached as 'scratch' schema
    SELECT * FROM scratch.kv WHERE user_id = '...' AND key = 'cat';
    INSERT OR REPLACE INTO scratch.kv (user_id, database, key, value) VALUES (...);
"""

import json
import time
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


class ParamStore:
    """
    SQLite-backed parameter store using scratch DB.

    Parameters are scoped by (user_id, database_name, param_name) and stored in
    the scratch SQLite database. Provides fast, cross-process access via WAL mode.
    """

    _instance = None
    _lock = threading.Lock()

    # SQLite connection (lazy initialized)
    _conn = None
    _conn_initialized = False

    # Per-key locks for read/modify/write operations (e.g., multi-select toggles).
    _param_locks: Dict[Tuple[str, str, str], threading.Lock] = {}
    _param_locks_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> 'ParamStore':
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_conn(self):
        """Get SQLite connection to scratch DB."""
        if self._conn is not None:
            return self._conn
        
        if not self._conn_initialized:
            try:
                from ..scratch_db import get_param_connection
                self._conn = get_param_connection()
                self._conn_initialized = True
                log.debug("[ParamStore] Connected to scratch DB")
            except Exception as e:
                log.warning(f"[ParamStore] Scratch DB not available: {e}")
                self._conn = None
                self._conn_initialized = True
        
        return self._conn

    @staticmethod
    def _make_key(user_id: str, database_name: str, param_name: str) -> Tuple[str, str, str]:
        """Create a cache key tuple."""
        return (user_id, database_name, param_name)

    def _get_param_lock(self, key: Tuple[str, str, str]) -> threading.Lock:
        """Get (or create) a per-param lock for atomic read/modify/write operations."""
        with self._param_locks_lock:
            lock = self._param_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._param_locks[key] = lock
            return lock

    # =========================================================================
    # Single Value Operations (for @param_set / @param_get)
    # =========================================================================

    def get(
        self,
        user_id: str,
        database_name: str,
        param_name: str,
        default: Optional[str] = None
    ) -> Optional[str]:
        """
        Get a parameter value.

        Args:
            user_id: User ID (or 'anonymous')
            database_name: Database name (e.g., 'memory', 'mydb')
            param_name: Parameter name
            default: Default value if not set

        Returns:
            Parameter value or default
        """
        conn = self._get_conn()
        if not conn:
            return default

        try:
            cursor = conn.execute(
                """
                SELECT value FROM kv
                WHERE user_id = ? AND database = ? AND key = ?
                """,
                (user_id, database_name, param_name)
            )
            row = cursor.fetchone()
            
            if row:
                value = row[0] if isinstance(row, tuple) else row['value']
                # Check if it's a JSON array (stored as string)
                if value and value.startswith('['):
                    # This is an array param, scalar reads treat it as unset
                    return default
                log.debug(f"[ParamStore] Hit: {param_name} = {value!r}")
                return value if value is not None else default
            
            log.debug(f"[ParamStore] Miss: {param_name} = default {default!r}")
            return default

        except Exception as e:
            log.debug(f"[ParamStore] Get error: {e}")
            return default

    def set(
        self,
        user_id: str,
        database_name: str,
        param_name: str,
        value: Optional[str],
        ttl_seconds: Optional[int] = None
    ) -> Optional[str]:
        """
        Set a parameter value.

        Args:
            user_id: User ID (or 'anonymous')
            database_name: Database name
            param_name: Parameter name
            value: Value to set (None clears the param)
            ttl_seconds: Optional TTL in seconds (not implemented for SQLite)

        Returns:
            The value that was set
        """
        conn = self._get_conn()
        if not conn:
            return value

        try:
            now = time.time()
            
            if value is None:
                # Delete the param
                conn.execute(
                    "DELETE FROM kv WHERE user_id = ? AND database = ? AND key = ?",
                    (user_id, database_name, param_name)
                )
            else:
                # Insert or replace
                conn.execute(
                    """
                    INSERT OR REPLACE INTO kv (user_id, database, key, value, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, database_name, param_name, value, now)
                )
            
            conn.commit()
            log.debug(f"[ParamStore] Set: {param_name} = {value!r}")
            return value

        except Exception as e:
            log.debug(f"[ParamStore] Set error: {e}")
            return value

    # =========================================================================
    # Array Value Operations (for @params_set / @params_get - multi-select)
    # =========================================================================

    def get_array(
        self,
        user_id: str,
        database_name: str,
        param_name: str
    ) -> List[str]:
        """
        Get an array parameter value.

        Args:
            user_id: User ID
            database_name: Database name
            param_name: Parameter name

        Returns:
            List of values (empty if not set)
        """
        conn = self._get_conn()
        if not conn:
            return []

        try:
            cursor = conn.execute(
                """
                SELECT value FROM kv
                WHERE user_id = ? AND database = ? AND key = ?
                """,
                (user_id, database_name, param_name)
            )
            row = cursor.fetchone()
            
            if row:
                value = row[0] if isinstance(row, tuple) else row['value']
                if value and value.startswith('['):
                    return json.loads(value)
                # Scalar value, return empty for array reads
                return []
            
            return []

        except Exception as e:
            log.debug(f"[ParamStore] Get array error: {e}")
            return []

    def set_array(
        self,
        user_id: str,
        database_name: str,
        param_name: str,
        values: List[str],
        ttl_seconds: Optional[int] = None
    ) -> List[str]:
        """
        Set an array parameter value.

        Args:
            user_id: User ID
            database_name: Database name
            param_name: Parameter name
            values: List of values

        Returns:
            The values that were set
        """
        conn = self._get_conn()
        if not conn:
            return values

        try:
            now = time.time()
            json_value = json.dumps(values)
            
            conn.execute(
                """
                INSERT OR REPLACE INTO kv (user_id, database, key, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, database_name, param_name, json_value, now)
            )
            conn.commit()
            
            return values

        except Exception as e:
            log.debug(f"[ParamStore] Set array error: {e}")
            return values

    def toggle_array_value(
        self,
        user_id: str,
        database_name: str,
        param_name: str,
        value: str
    ) -> List[str]:
        """
        Toggle a value in an array parameter (add if missing, remove if present).

        This is the behavior for multi-select checkbox interactions.

        Args:
            user_id: User ID
            database_name: Database name
            param_name: Parameter name
            value: Value to toggle

        Returns:
            Updated array of values
        """
        key = self._make_key(user_id, database_name, param_name)
        lock = self._get_param_lock(key)
        with lock:
            current = self.get_array(user_id, database_name, param_name)

            if value in current:
                current.remove(value)
            else:
                current.append(value)

            return self.set_array(user_id, database_name, param_name, current)

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def list_params(
        self,
        user_id: str,
        database_name: str
    ) -> Dict[str, Any]:
        """
        List all parameters for a user/database.

        Returns:
            Dict mapping param_name to value or values_array
        """
        result = {}

        conn = self._get_conn()
        if not conn:
            return result

        try:
            cursor = conn.execute(
                """
                SELECT key, value FROM kv
                WHERE user_id = ? AND database = ?
                """,
                (user_id, database_name)
            )
            
            for row in cursor.fetchall():
                key = row[0] if isinstance(row, tuple) else row['key']
                value = row[1] if isinstance(row, tuple) else row['value']
                
                # Parse JSON arrays
                if value and value.startswith('['):
                    try:
                        result[key] = json.loads(value)
                    except json.JSONDecodeError:
                        result[key] = value
                else:
                    result[key] = value

            return result

        except Exception as e:
            log.debug(f"[ParamStore] List error: {e}")
            return result

    def clear_session(self, user_id: str, database_name: str):
        """Clear all parameters for a user/database."""
        conn = self._get_conn()
        if not conn:
            return

        try:
            conn.execute(
                "DELETE FROM kv WHERE user_id = ? AND database = ?",
                (user_id, database_name)
            )
            conn.commit()
        except Exception as e:
            log.debug(f"[ParamStore] Clear session error: {e}")

    def clear_all(self, user_id: str):
        """Clear all parameters for a user across all databases."""
        conn = self._get_conn()
        if not conn:
            return

        try:
            conn.execute("DELETE FROM kv WHERE user_id = ?", (user_id,))
            conn.commit()
        except Exception as e:
            log.debug(f"[ParamStore] Clear all error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get param store statistics."""
        stats = {
            'backend': 'sqlite_scratch',
            'path': '/dev/shm/lars_scratch.db',
            'entries': 0,
        }

        conn = self._get_conn()
        if conn:
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM kv")
                row = cursor.fetchone()
                stats['entries'] = row[0] if row else 0
            except Exception as e:
                log.debug(f"[ParamStore] Stats error: {e}")

        return stats


# Global instance
_param_store: Optional[ParamStore] = None


def get_param_store() -> ParamStore:
    """Get the global param store instance."""
    global _param_store
    if _param_store is None:
        _param_store = ParamStore.get_instance()
    return _param_store


def reset_param_store() -> None:
    """Reset param store (for testing)."""
    global _param_store
    ParamStore._instance = None
    ParamStore._conn = None
    ParamStore._conn_initialized = False
    _param_store = None


# ============================================================================
# Backwards-compatible API (for existing param_store.py usage)
# ============================================================================

def param_store_get(
    session_id: str,
    key: str,
    default: Optional[str] = None
) -> Optional[str]:
    """
    Backwards-compatible get function.

    Note: session_id is interpreted as "user_id:database_name" or just used as user_id
    with default database 'memory'.
    """
    store = get_param_store()

    # Parse session_id (could be "user:db" or just a session identifier)
    if ':' in session_id:
        user_id, database_name = session_id.split(':', 1)
    else:
        # Use session_id as user_id, default database
        user_id = session_id
        database_name = 'memory'

    return store.get(user_id, database_name, key, default)


def param_store_set(
    session_id: str,
    key: str,
    value: Optional[str]
) -> Optional[str]:
    """Backwards-compatible set function."""
    store = get_param_store()

    if ':' in session_id:
        user_id, database_name = session_id.split(':', 1)
    else:
        user_id = session_id
        database_name = 'memory'

    return store.set(user_id, database_name, key, value)


def param_store_clear(session_id: str, key: str) -> None:
    """Backwards-compatible clear function."""
    param_store_set(session_id, key, None)


def param_store_clear_session(session_id: str) -> None:
    """Backwards-compatible clear session function."""
    store = get_param_store()

    if ':' in session_id:
        user_id, database_name = session_id.split(':', 1)
    else:
        user_id = session_id
        database_name = 'memory'

    store.clear_session(user_id, database_name)


def param_store_list(session_id: str) -> Dict[str, str]:
    """Backwards-compatible list function."""
    store = get_param_store()

    if ':' in session_id:
        user_id, database_name = session_id.split(':', 1)
    else:
        user_id = session_id
        database_name = 'memory'

    params = store.list_params(user_id, database_name)
    # Convert to simple string dict
    return {k: str(v) if v is not None else '' for k, v in params.items()}


def params_store_get(session_id: str, key: str) -> List[str]:
    """Backwards-compatible array get function."""
    store = get_param_store()

    if ':' in session_id:
        user_id, database_name = session_id.split(':', 1)
    else:
        user_id = session_id
        database_name = 'memory'

    return store.get_array(user_id, database_name, key)


def params_store_set(session_id: str, key: str, value: str) -> List[str]:
    """Backwards-compatible array toggle function."""
    store = get_param_store()

    if ':' in session_id:
        user_id, database_name = session_id.split(':', 1)
    else:
        user_id = session_id
        database_name = 'memory'

    return store.toggle_array_value(user_id, database_name, key, value)


def params_store_clear(session_id: str, key: str) -> None:
    """Backwards-compatible array clear function."""
    store = get_param_store()

    if ':' in session_id:
        user_id, database_name = session_id.split(':', 1)
    else:
        user_id = session_id
        database_name = 'memory'

    store.set_array(user_id, database_name, key, [])
