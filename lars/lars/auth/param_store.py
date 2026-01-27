"""
Parameter Store - User-Scoped Key-Value Storage

Provides persistent parameter storage for @param_get/@param_set operations,
scoped by user_id and database_name.

Uses two-tier caching (L1 in-memory, L2 ClickHouse) following the
pattern established in cache_adapter.py.

Usage:
    from lars.auth.param_store import get_param_store

    store = get_param_store()

    # Single values
    store.set('user123', 'mydb', 'filter_category', 'electronics')
    value = store.get('user123', 'mydb', 'filter_category')

    # Array values (for multi-select)
    store.set_array('user123', 'mydb', 'selected_depts', ['HR', 'Sales'])
    values = store.get_array('user123', 'mydb', 'selected_depts')
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
    Two-tier parameter store with L1 (memory) and L2 (ClickHouse) caching.

    Parameters are scoped by (user_id, database_name, param_name).
    """

    _instance = None
    _lock = threading.Lock()

    # L1 cache: Dict[(user_id, database_name, param_name), (value, values_array, updated_at)]
    _l1_cache: Dict[Tuple[str, str, str], Tuple[Optional[str], List[str], float]] = {}
    _l1_lock = threading.Lock()

    # ClickHouse connection (lazy initialized)
    _db = None
    _db_initialized = False
    _table_ensured = False

    # Configuration
    L1_MAX_SIZE = 5000  # Max entries in L1 before eviction

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

    def _get_db(self):
        """Lazily initialize ClickHouse connection."""
        if not self._db_initialized:
            try:
                from ..db_adapter import get_db
                self._db = get_db()
                self._db_initialized = True
                self._ensure_table()
            except Exception as e:
                log.warning(f"[ParamStore] ClickHouse not available: {e}")
                self._db = None
                self._db_initialized = True
        return self._db

    def _ensure_table(self):
        """Ensure the param_store table exists."""
        if self._table_ensured or not self._db:
            return

        try:
            # Table is created via migration 044_param_store.sql
            self._db.query("SELECT 1 FROM param_store LIMIT 0")
            self._table_ensured = True
            log.debug("[ParamStore] Table verified")
        except Exception as e:
            log.warning(f"[ParamStore] Table not found, run migrations: {e}")

    @staticmethod
    def _make_key(user_id: str, database_name: str, param_name: str) -> Tuple[str, str, str]:
        """Create a cache key tuple."""
        return (user_id, database_name, param_name)

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
        key = self._make_key(user_id, database_name, param_name)

        # Try L1 first
        l1_result = self._get_l1(key)
        if l1_result is not None:
            value, _, _ = l1_result
            log.debug(f"[ParamStore] L1 hit: {param_name} = {value!r}")
            return value if value is not None else default

        # Try L2
        l2_result = self._get_l2(user_id, database_name, param_name)
        if l2_result is not None:
            value, values_array, updated_at = l2_result
            # Populate L1
            self._set_l1(key, value, values_array, updated_at)
            log.debug(f"[ParamStore] L2 hit: {param_name} = {value!r}")
            return value if value is not None else default

        log.debug(f"[ParamStore] Miss: {param_name} = default {default!r}")
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
            ttl_seconds: Optional TTL in seconds

        Returns:
            The value that was set
        """
        key = self._make_key(user_id, database_name, param_name)
        now = time.time()

        if value is None:
            # Clear the param
            self._evict_l1(key)
            self._delete_l2(user_id, database_name, param_name)
            log.debug(f"[ParamStore] Cleared: {param_name}")
            return None

        # Set L1
        self._set_l1(key, value, [], now)

        # Set L2 (async)
        self._set_l2_async(user_id, database_name, param_name, value, [], ttl_seconds)

        log.debug(f"[ParamStore] Set: {param_name} = {value!r}")
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
        key = self._make_key(user_id, database_name, param_name)

        # Try L1 first
        l1_result = self._get_l1(key)
        if l1_result is not None:
            _, values_array, _ = l1_result
            return values_array

        # Try L2
        l2_result = self._get_l2(user_id, database_name, param_name)
        if l2_result is not None:
            value, values_array, updated_at = l2_result
            # Populate L1
            self._set_l1(key, value, values_array, updated_at)
            return values_array

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
        key = self._make_key(user_id, database_name, param_name)
        now = time.time()

        # Set L1
        self._set_l1(key, None, values, now)

        # Set L2 (async)
        self._set_l2_async(user_id, database_name, param_name, None, values, ttl_seconds)

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
        current = self.get_array(user_id, database_name, param_name)

        if value in current:
            current.remove(value)
        else:
            current.append(value)

        return self.set_array(user_id, database_name, param_name, current)

    # =========================================================================
    # L1 Cache Operations
    # =========================================================================

    def _get_l1(self, key: Tuple[str, str, str]) -> Optional[Tuple[Optional[str], List[str], float]]:
        """Get from L1 cache."""
        with self._l1_lock:
            return self._l1_cache.get(key)

    def _set_l1(
        self,
        key: Tuple[str, str, str],
        value: Optional[str],
        values_array: List[str],
        updated_at: float
    ):
        """Set in L1 cache with size-based eviction."""
        with self._l1_lock:
            # Evict oldest 10% if at capacity
            if len(self._l1_cache) >= self.L1_MAX_SIZE and key not in self._l1_cache:
                items = list(self._l1_cache.items())
                items.sort(key=lambda x: x[1][2])  # Sort by updated_at
                evict_count = self.L1_MAX_SIZE // 10
                for k, _ in items[:evict_count]:
                    del self._l1_cache[k]

            self._l1_cache[key] = (value, values_array, updated_at)

    def _evict_l1(self, key: Tuple[str, str, str]):
        """Remove from L1 cache."""
        with self._l1_lock:
            self._l1_cache.pop(key, None)

    # =========================================================================
    # L2 (ClickHouse) Operations
    # =========================================================================

    def _get_l2(
        self,
        user_id: str,
        database_name: str,
        param_name: str
    ) -> Optional[Tuple[Optional[str], List[str], float]]:
        """Get from L2 (ClickHouse)."""
        db = self._get_db()
        if not db:
            return None

        try:
            rows = db.query(
                """
                SELECT param_value, param_values, updated_at
                FROM param_store
                WHERE user_id = %(user_id)s
                  AND database_name = %(database_name)s
                  AND param_name = %(param_name)s
                LIMIT 1
                """,
                {
                    "user_id": user_id,
                    "database_name": database_name,
                    "param_name": param_name,
                }
            )

            if rows and len(rows) > 0:
                row = rows[0]
                if isinstance(row, dict):
                    value = row.get('param_value')
                    values_array = row.get('param_values', [])
                    updated_at_raw = row.get('updated_at')
                else:
                    value = row[0]
                    values_array = row[1] if len(row) > 1 else []
                    updated_at_raw = row[2] if len(row) > 2 else None

                updated_at = updated_at_raw.timestamp() if hasattr(updated_at_raw, 'timestamp') else time.time()
                return (value, values_array or [], updated_at)

            return None

        except Exception as e:
            log.debug(f"[ParamStore] L2 get error: {e}")
            return None

    def _set_l2_async(
        self,
        user_id: str,
        database_name: str,
        param_name: str,
        value: Optional[str],
        values_array: List[str],
        ttl_seconds: Optional[int] = None
    ):
        """Set in L2 (ClickHouse) asynchronously."""
        def _write():
            db = self._get_db()
            if not db:
                return

            try:
                now = datetime.now()
                expires_at = None
                if ttl_seconds and ttl_seconds > 0:
                    from datetime import timedelta
                    expires_at = now + timedelta(seconds=ttl_seconds)

                row = {
                    'user_id': user_id,
                    'database_name': database_name,
                    'param_name': param_name,
                    'param_value': value or '',
                    'param_type': 'array' if values_array else 'string',
                    'param_values': values_array,
                    'created_at': now,
                    'updated_at': now,
                    'expires_at': expires_at,
                }

                db.insert_rows('param_store', [row])
                log.debug(f"[ParamStore] L2 set: {param_name}")

            except Exception as e:
                log.debug(f"[ParamStore] L2 set error: {e}")

        threading.Thread(target=_write, daemon=True).start()

    def _delete_l2(self, user_id: str, database_name: str, param_name: str):
        """Delete from L2 (async)."""
        def _delete():
            db = self._get_db()
            if not db:
                return

            try:
                db.execute(
                    """
                    ALTER TABLE param_store DELETE
                    WHERE user_id = %(user_id)s
                      AND database_name = %(database_name)s
                      AND param_name = %(param_name)s
                    """,
                    {
                        "user_id": user_id,
                        "database_name": database_name,
                        "param_name": param_name,
                    }
                )
            except Exception as e:
                log.debug(f"[ParamStore] L2 delete error: {e}")

        threading.Thread(target=_delete, daemon=True).start()

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
        db = self._get_db()
        if not db:
            # Fall back to L1 only
            result = {}
            with self._l1_lock:
                for key, (value, values_array, _) in self._l1_cache.items():
                    if key[0] == user_id and key[1] == database_name:
                        param_name = key[2]
                        result[param_name] = values_array if values_array else value
            return result

        try:
            rows = db.query(
                """
                SELECT param_name, param_value, param_values, param_type
                FROM param_store
                WHERE user_id = %(user_id)s
                  AND database_name = %(database_name)s
                """,
                {"user_id": user_id, "database_name": database_name}
            )

            result = {}
            for row in rows:
                if isinstance(row, dict):
                    name = row.get('param_name')
                    value = row.get('param_value')
                    values = row.get('param_values', [])
                    ptype = row.get('param_type', 'string')
                else:
                    name = row[0]
                    value = row[1]
                    values = row[2] if len(row) > 2 else []
                    ptype = row[3] if len(row) > 3 else 'string'

                result[name] = values if (ptype == 'array' and values) else value

            return result

        except Exception as e:
            log.debug(f"[ParamStore] List error: {e}")
            return {}

    def clear_session(self, user_id: str, database_name: str):
        """Clear all parameters for a user/database."""
        # Clear L1
        with self._l1_lock:
            keys_to_delete = [
                k for k in self._l1_cache
                if k[0] == user_id and k[1] == database_name
            ]
            for k in keys_to_delete:
                del self._l1_cache[k]

        # Clear L2
        db = self._get_db()
        if db:
            try:
                db.execute(
                    """
                    ALTER TABLE param_store DELETE
                    WHERE user_id = %(user_id)s
                      AND database_name = %(database_name)s
                    """,
                    {"user_id": user_id, "database_name": database_name}
                )
            except Exception as e:
                log.debug(f"[ParamStore] Clear session error: {e}")

    def clear_all(self, user_id: str):
        """Clear all parameters for a user across all databases."""
        # Clear L1
        with self._l1_lock:
            keys_to_delete = [k for k in self._l1_cache if k[0] == user_id]
            for k in keys_to_delete:
                del self._l1_cache[k]

        # Clear L2
        db = self._get_db()
        if db:
            try:
                db.execute(
                    "ALTER TABLE param_store DELETE WHERE user_id = %(user_id)s",
                    {"user_id": user_id}
                )
            except Exception as e:
                log.debug(f"[ParamStore] Clear all error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get param store statistics."""
        stats = {
            'l1_entries': len(self._l1_cache),
            'l1_max_size': self.L1_MAX_SIZE,
            'l2_available': False,
            'l2_entries': 0,
        }

        db = self._get_db()
        if db:
            try:
                rows = db.query("SELECT count() as cnt FROM param_store")
                if rows:
                    stats['l2_available'] = True
                    stats['l2_entries'] = rows[0].get('cnt', 0) if isinstance(rows[0], dict) else rows[0][0]
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
