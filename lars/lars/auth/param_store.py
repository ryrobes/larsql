"""
Parameter Store - User-Scoped Key-Value Storage

Provides persistent parameter storage for @param_get/@param_set operations,
scoped by user_id and database_name.

Uses ClickHouse-backed storage (Memory engine) for cross-worker consistency.

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
    ClickHouse-backed parameter store.

    Parameters are scoped by (user_id, database_name, param_name) and stored in
    ClickHouse (Memory engine). Reads always go to ClickHouse to avoid the
    cross-process staleness issues of in-memory caching.
    """

    _instance = None
    _lock = threading.Lock()

    # ClickHouse connection (lazy initialized)
    _db = None
    _db_initialized = False
    _table_ensured = False

    # In-process fallback store when ClickHouse is unavailable.
    # NOTE: This is not used as a cache when ClickHouse is available, to avoid
    # cross-process staleness issues. It's only a "no ClickHouse" fallback.
    _fallback_store: Dict[Tuple[str, str, str], Tuple[Optional[str], List[str], str, float]] = {}
    _fallback_lock = threading.Lock()

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

    def _get_param_lock(self, key: Tuple[str, str, str]) -> threading.Lock:
        """Get (or create) a per-param lock for atomic read/modify/write operations."""
        with self._param_locks_lock:
            lock = self._param_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._param_locks[key] = lock
            return lock

    def _fallback_get(self, key: Tuple[str, str, str]) -> Optional[Tuple[Optional[str], List[str], str, float]]:
        with self._fallback_lock:
            return self._fallback_store.get(key)

    def _fallback_set(self, key: Tuple[str, str, str], value: Optional[str], values_array: List[str], ptype: str):
        now = time.time()
        with self._fallback_lock:
            self._fallback_store[key] = (value, values_array, ptype, now)

    def _fallback_clear_session(self, user_id: str, database_name: str):
        with self._fallback_lock:
            keys_to_delete = [
                k for k in self._fallback_store
                if k[0] == user_id and k[1] == database_name
            ]
            for k in keys_to_delete:
                del self._fallback_store[k]

    def _fallback_clear_all(self, user_id: str):
        with self._fallback_lock:
            keys_to_delete = [k for k in self._fallback_store if k[0] == user_id]
            for k in keys_to_delete:
                del self._fallback_store[k]

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

        l2_result = self._get_l2(user_id, database_name, param_name)
        if l2_result is not None:
            value, _values_array, ptype, _updated_at = l2_result
            if ptype == 'null':
                return default
            if ptype == 'array':
                # If the key is currently an array param, scalar reads treat it as unset.
                return default
            log.debug(f"[ParamStore] Hit: {param_name} = {value!r}")
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

        # Clearing uses a tombstone row (ptype='null') to avoid "eventual delete" races
        # and to guarantee read-your-writes semantics even if the underlying engine
        # delays DELETE visibility.
        ptype = 'null' if value is None else 'string'
        self._set_l2_sync(
            user_id,
            database_name,
            param_name,
            value=value,
            values_array=[],
            param_type=ptype,
            ttl_seconds=ttl_seconds,
        )

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
        l2_result = self._get_l2(user_id, database_name, param_name)
        if l2_result is not None:
            _value, values_array, ptype, _updated_at = l2_result
            if ptype == 'array':
                return values_array
            # Treat scalar/null as empty selection for array reads.
            return []

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
        self._set_l2_sync(
            user_id,
            database_name,
            param_name,
            value=None,
            values_array=values,
            param_type='array',
            ttl_seconds=ttl_seconds,
        )

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
    # L2 (ClickHouse) Operations
    # =========================================================================

    def _get_l2(
        self,
        user_id: str,
        database_name: str,
        param_name: str
    ) -> Optional[Tuple[Optional[str], List[str], str, float]]:
        """Get from L2 (ClickHouse Memory table) - uses ORDER BY for latest value."""
        db = self._get_db()
        if not db:
            key = self._make_key(user_id, database_name, param_name)
            return self._fallback_get(key)

        try:
            # Memory engine: no FINAL needed, just ORDER BY updated_at DESC to get latest.
            rows = db.query(
                """
                SELECT param_value, param_values, param_type, updated_at
                FROM param_store
                WHERE user_id = %(user_id)s
                  AND database_name = %(database_name)s
                  AND param_name = %(param_name)s
                ORDER BY updated_at DESC
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
                    ptype = row.get('param_type', 'string')
                    updated_at_raw = row.get('updated_at')
                else:
                    value = row[0]
                    values_array = row[1] if len(row) > 1 else []
                    ptype = row[2] if len(row) > 2 else 'string'
                    updated_at_raw = row[3] if len(row) > 3 else None

                updated_at = updated_at_raw.timestamp() if hasattr(updated_at_raw, 'timestamp') else time.time()
                return (value, values_array or [], ptype or 'string', updated_at)

            return None

        except Exception as e:
            log.debug(f"[ParamStore] L2 get error: {e}")
            return None

    def _set_l2_sync(
        self,
        user_id: str,
        database_name: str,
        param_name: str,
        value: Optional[str],
        values_array: List[str],
        param_type: str,
        ttl_seconds: Optional[int] = None
    ):
        """Set in L2 (ClickHouse Memory table) synchronously.

        Strategy: append-only INSERT with updated_at ordering.
        Reads use ORDER BY updated_at DESC LIMIT 1, so duplicates are harmless and
        this avoids transient "missing between DELETE and INSERT" windows.
        """
        db = self._get_db()
        if not db:
            key = self._make_key(user_id, database_name, param_name)
            self._fallback_set(key, value, values_array, param_type)
            return

        try:
            now = datetime.now()
            row = {
                'user_id': user_id,
                'database_name': database_name,
                'param_name': param_name,
                'param_value': value if value is not None else '',
                'param_type': param_type,
                'param_values': values_array,
                'created_at': now,
                'updated_at': now,
            }

            db.insert_rows('param_store', [row])
            log.debug(f"[ParamStore] L2 set (sync): {param_name}")

        except Exception as e:
            log.debug(f"[ParamStore] L2 set error: {e}")

    def _set_l2_async(
        self,
        user_id: str,
        database_name: str,
        param_name: str,
        value: Optional[str],
        values_array: List[str],
        ttl_seconds: Optional[int] = None
    ):
        """Set in L2 (ClickHouse) asynchronously (deprecated, use _set_l2_sync for param operations)."""
        def _write():
            inferred_type = 'array' if value is None else 'string'
            self._set_l2_sync(
                user_id,
                database_name,
                param_name,
                value=value,
                values_array=values_array,
                param_type=inferred_type,
                ttl_seconds=ttl_seconds,
            )

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
        result = {}

        # Get params from L2 (Memory engine: use subquery to get latest per param_name)
        db = self._get_db()
        if not db:
            # Fallback mode: return the in-process store for this user/database
            with self._fallback_lock:
                for (uid, dbname, pname), (value, values, ptype, _ts) in self._fallback_store.items():
                    if uid != user_id or dbname != database_name:
                        continue
                    if ptype == 'null':
                        continue
                    if ptype == 'array':
                        result[pname] = values or []
                    else:
                        result[pname] = value
            return result

        if db:
            try:
                rows = db.query(
                    """
                    SELECT param_name, param_value, param_values, param_type
                    FROM param_store
                    WHERE user_id = %(user_id)s
                      AND database_name = %(database_name)s
                      AND (user_id, database_name, param_name, updated_at) IN (
                          SELECT user_id, database_name, param_name, max(updated_at)
                          FROM param_store
                          WHERE user_id = %(user_id)s
                            AND database_name = %(database_name)s
                          GROUP BY user_id, database_name, param_name
                      )
                    """,
                    {"user_id": user_id, "database_name": database_name}
                )

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

                    if ptype == 'null':
                        continue
                    if ptype == 'array':
                        result[name] = values or []
                    else:
                        result[name] = value

            except Exception as e:
                log.debug(f"[ParamStore] L2 list error: {e}")

        return result

    def clear_session(self, user_id: str, database_name: str):
        """Clear all parameters for a user/database."""
        # Clear L2
        db = self._get_db()
        if not db:
            self._fallback_clear_session(user_id, database_name)
            return

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
        # Clear L2
        db = self._get_db()
        if not db:
            self._fallback_clear_all(user_id)
            return

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
            'l1_entries': 0,
            'l1_max_size': 0,
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
