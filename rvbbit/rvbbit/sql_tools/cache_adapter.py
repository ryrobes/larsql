"""
Persistent Cache Adapter for Semantic SQL operations.

Provides a two-tier caching system:
- L1: In-memory dict (fast, volatile)
- L2: ClickHouse table (persistent, queryable)

Features:
- Write-through: Writes go to both L1 and L2
- Read-through: L1 miss -> L2 lookup -> populate L1
- TTL support with automatic expiration
- Analytics tracking (hit counts, last access)
- Browseable cache contents via SQL
- Selective pruning by function, age, pattern

Usage:
    from rvbbit.sql_tools.cache_adapter import SemanticCache

    cache = SemanticCache.get_instance()

    # Get (returns None if not found)
    result = cache.get("semantic_matches", {"text": "hello", "criterion": "greeting"})

    # Set (writes to both L1 and L2)
    cache.set("semantic_matches", {"text": "hello", "criterion": "greeting"}, True, "BOOLEAN")

    # Clear
    cache.clear(function_name="semantic_matches")  # Clear specific function
    cache.clear()  # Clear all
"""

import json
import hashlib
import time
import threading
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


class SemanticCache:
    """
    Two-tier cache for semantic SQL operations.

    L1: In-memory dict for fast lookups
    L2: ClickHouse table for persistence and queryability
    """

    _instance = None
    _lock = threading.Lock()

    # L1 cache: Dict[cache_key, (result, result_type, created_at, expires_at)]
    _l1_cache: Dict[str, Tuple[Any, str, float, Optional[float]]] = {}
    _l1_lock = threading.Lock()

    # ClickHouse connection (lazy initialized)
    _db = None
    _db_initialized = False
    _table_ensured = False

    # Configuration
    DEFAULT_TTL_SECONDS = 0  # 0 = infinite (no expiration)
    L1_MAX_SIZE = 10000  # Max entries in L1 before eviction

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "SemanticCache":
        """Get the singleton cache instance."""
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
                log.warning(f"[SemanticCache] ClickHouse not available: {e}")
                self._db = None
                self._db_initialized = True  # Don't retry
        return self._db

    def _ensure_table(self):
        """Ensure the cache table exists in ClickHouse."""
        if self._table_ensured or not self._db:
            return

        try:
            from ..schema import SEMANTIC_SQL_CACHE_SCHEMA
            self._db.ensure_table_exists("semantic_sql_cache", SEMANTIC_SQL_CACHE_SCHEMA)
            self._table_ensured = True
            log.info("[SemanticCache] Table semantic_sql_cache ensured")
        except Exception as e:
            log.warning(f"[SemanticCache] Could not ensure table: {e}")

    @staticmethod
    def make_cache_key(function_name: str, args: Dict[str, Any]) -> str:
        """
        Create a deterministic cache key from function name and arguments.

        Args:
            function_name: The semantic SQL function name
            args: Function arguments as a dictionary

        Returns:
            MD5 hash string
        """
        args_json = json.dumps(args, sort_keys=True, default=str)
        key_data = f"{function_name}:{args_json}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(
        self,
        function_name: str,
        args: Dict[str, Any],
        track_hit: bool = True
    ) -> Tuple[bool, Any, str]:
        """
        Get a cached result.

        Args:
            function_name: The semantic SQL function name
            args: Function arguments
            track_hit: Whether to increment hit counter (default True)

        Returns:
            Tuple of (found, result, result_type)
            - found: True if cache hit, False if miss
            - result: The cached value (or None if miss)
            - result_type: The type hint ('BOOLEAN', 'DOUBLE', etc.)
        """
        cache_key = self.make_cache_key(function_name, args)

        # Try L1 first
        l1_result = self._get_l1(cache_key)
        if l1_result is not None:
            result, result_type, created_at, expires_at = l1_result

            # Check expiration
            if expires_at is not None and time.time() > expires_at:
                self._evict_l1(cache_key)
            else:
                if track_hit:
                    self._record_hit_async(cache_key)
                return True, result, result_type

        # Try L2
        l2_result = self._get_l2(cache_key)
        if l2_result is not None:
            result, result_type, created_at, expires_at, ttl_seconds = l2_result

            # Check expiration
            if expires_at is not None and time.time() > expires_at:
                # Expired in L2, will be cleaned up by TTL
                return False, None, ""

            # Populate L1
            self._set_l1(cache_key, result, result_type, created_at, expires_at)

            if track_hit:
                self._record_hit_async(cache_key)

            return True, result, result_type

        return False, None, ""

    def set(
        self,
        function_name: str,
        args: Dict[str, Any],
        result: Any,
        result_type: str = "VARCHAR",
        ttl_seconds: Optional[int] = None,
        session_id: str = "",
        caller_id: str = ""
    ) -> str:
        """
        Cache a result (writes to both L1 and L2).

        Args:
            function_name: The semantic SQL function name
            args: Function arguments
            result: The result to cache
            result_type: Type hint ('BOOLEAN', 'DOUBLE', 'VARCHAR', 'JSON')
            ttl_seconds: Time-to-live in seconds (None or 0 = infinite)
            session_id: Optional session ID for tracking
            caller_id: Optional caller ID for tracking

        Returns:
            The cache key
        """
        cache_key = self.make_cache_key(function_name, args)
        created_at = time.time()

        # Calculate expiration
        expires_at = None
        if ttl_seconds and ttl_seconds > 0:
            expires_at = created_at + ttl_seconds

        # Set L1
        self._set_l1(cache_key, result, result_type, created_at, expires_at)

        # Set L2 (async, fire-and-forget)
        self._set_l2_async(
            cache_key=cache_key,
            function_name=function_name,
            args=args,
            result=result,
            result_type=result_type,
            created_at=created_at,
            expires_at=expires_at,
            ttl_seconds=ttl_seconds or 0,
            session_id=session_id,
            caller_id=caller_id
        )

        return cache_key

    def _get_l1(self, cache_key: str) -> Optional[Tuple[Any, str, float, Optional[float]]]:
        """Get from L1 cache."""
        with self._l1_lock:
            return self._l1_cache.get(cache_key)

    def _set_l1(
        self,
        cache_key: str,
        result: Any,
        result_type: str,
        created_at: float,
        expires_at: Optional[float]
    ):
        """Set in L1 cache with LRU-style eviction."""
        with self._l1_lock:
            # Simple size-based eviction if needed
            if len(self._l1_cache) >= self.L1_MAX_SIZE and cache_key not in self._l1_cache:
                # Evict oldest 10%
                items = list(self._l1_cache.items())
                items.sort(key=lambda x: x[1][2])  # Sort by created_at
                evict_count = self.L1_MAX_SIZE // 10
                for key, _ in items[:evict_count]:
                    del self._l1_cache[key]

            self._l1_cache[cache_key] = (result, result_type, created_at, expires_at)

    def _evict_l1(self, cache_key: str):
        """Remove from L1 cache."""
        with self._l1_lock:
            self._l1_cache.pop(cache_key, None)

    def _get_l2(self, cache_key: str) -> Optional[Tuple[Any, str, float, Optional[float], int]]:
        """Get from L2 (ClickHouse) cache."""
        db = self._get_db()
        if not db:
            return None

        try:
            query = """
                SELECT result, result_type, created_at, expires_at, ttl_seconds
                FROM semantic_sql_cache
                WHERE cache_key = %(cache_key)s
                LIMIT 1
            """
            rows = db.query(query, {"cache_key": cache_key})

            if rows and len(rows) > 0:
                row = rows[0]
                # Handle both dict and tuple formats from ClickHouse driver
                if isinstance(row, dict):
                    result = row.get("result")
                    result_type = row.get("result_type")
                    created_at_raw = row.get("created_at")
                    expires_at_raw = row.get("expires_at")
                    ttl_seconds = row.get("ttl_seconds", 0)
                else:
                    result = row[0]
                    result_type = row[1]
                    created_at_raw = row[2]
                    expires_at_raw = row[3]
                    ttl_seconds = row[4]

                created_at = created_at_raw.timestamp() if hasattr(created_at_raw, 'timestamp') else float(created_at_raw)

                # Handle far-future "never expires" sentinel
                if self._is_far_future(expires_at_raw):
                    expires_at = None
                elif expires_at_raw and hasattr(expires_at_raw, 'timestamp'):
                    expires_at = expires_at_raw.timestamp()
                elif expires_at_raw:
                    expires_at = float(expires_at_raw)
                else:
                    expires_at = None

                return (result, result_type, created_at, expires_at, ttl_seconds)

            return None

        except Exception as e:
            log.debug(f"[SemanticCache] L2 get error: {e}")
            return None

    # Far future date for "never expires" (year 2100)
    FAR_FUTURE = datetime(2100, 1, 1)

    def _set_l2_async(
        self,
        cache_key: str,
        function_name: str,
        args: Dict[str, Any],
        result: Any,
        result_type: str,
        created_at: float,
        expires_at: Optional[float],
        ttl_seconds: int,
        session_id: str,
        caller_id: str
    ):
        """Set in L2 (ClickHouse) cache asynchronously."""
        # Run in thread to not block
        def _write():
            db = self._get_db()
            if not db:
                return

            try:
                args_json = json.dumps(args, sort_keys=True, default=str)
                args_preview = args_json[:200]
                result_str = json.dumps(result, default=str) if not isinstance(result, str) else result
                result_bytes = len(result_str.encode('utf-8'))

                # Convert timestamps to datetime
                created_dt = datetime.fromtimestamp(created_at)
                # Use far future date for "never expires" (TTL requires non-nullable DateTime)
                expires_dt = datetime.fromtimestamp(expires_at) if expires_at else self.FAR_FUTURE

                # Use INSERT with ON DUPLICATE KEY UPDATE semantics via ReplacingMergeTree
                # ClickHouse will handle deduplication
                row = {
                    "cache_key": cache_key,
                    "function_name": function_name,
                    "args_json": args_json,
                    "args_preview": args_preview,
                    "result": result_str,
                    "result_type": result_type,
                    "created_at": created_dt,
                    "expires_at": expires_dt,
                    "ttl_seconds": ttl_seconds,
                    "hit_count": 1,
                    "last_hit_at": created_dt,
                    "result_bytes": result_bytes,
                    "first_session_id": session_id,
                    "first_caller_id": caller_id,
                }

                db.insert_rows("semantic_sql_cache", [row])
                log.debug(f"[SemanticCache] L2 set: {function_name} -> {cache_key[:8]}...")

            except Exception as e:
                log.debug(f"[SemanticCache] L2 set error: {e}")

        # Fire and forget
        threading.Thread(target=_write, daemon=True).start()

    def _record_hit_async(self, cache_key: str):
        """
        Record a cache hit in L2 asynchronously.

        Uses INSERT to add a new row with incremented hit_count.
        ReplacingMergeTree will dedupe by cache_key, keeping the row with latest last_hit_at.
        """
        def _update():
            db = self._get_db()
            if not db:
                return

            try:
                # ReplacingMergeTree doesn't allow UPDATE on version column (last_hit_at)
                # Instead, we fetch the current row and re-insert with updated values
                # This is eventually consistent - the ReplacingMergeTree will dedupe

                query = """
                    SELECT
                        cache_key, function_name, args_json, args_preview,
                        result, result_type, created_at, expires_at, ttl_seconds,
                        hit_count, result_bytes, first_session_id, first_caller_id
                    FROM semantic_sql_cache
                    WHERE cache_key = %(cache_key)s
                    LIMIT 1
                """
                rows = db.query(query, {"cache_key": cache_key})

                if rows and len(rows) > 0:
                    row = rows[0]
                    # Handle both dict and tuple formats
                    if isinstance(row, dict):
                        new_row = {
                            "cache_key": row.get("cache_key"),
                            "function_name": row.get("function_name"),
                            "args_json": row.get("args_json"),
                            "args_preview": row.get("args_preview"),
                            "result": row.get("result"),
                            "result_type": row.get("result_type"),
                            "created_at": row.get("created_at"),
                            "expires_at": row.get("expires_at"),
                            "ttl_seconds": row.get("ttl_seconds"),
                            "hit_count": (row.get("hit_count") or 0) + 1,  # Increment
                            "last_hit_at": datetime.now(),  # Update
                            "result_bytes": row.get("result_bytes"),
                            "first_session_id": row.get("first_session_id"),
                            "first_caller_id": row.get("first_caller_id"),
                        }
                    else:
                        new_row = {
                            "cache_key": row[0],
                            "function_name": row[1],
                            "args_json": row[2],
                            "args_preview": row[3],
                            "result": row[4],
                            "result_type": row[5],
                            "created_at": row[6],
                            "expires_at": row[7],
                            "ttl_seconds": row[8],
                            "hit_count": row[9] + 1,  # Increment
                            "last_hit_at": datetime.now(),  # Update
                            "result_bytes": row[10],
                            "first_session_id": row[11],
                            "first_caller_id": row[12],
                        }
                    db.insert_rows("semantic_sql_cache", [new_row])

            except Exception as e:
                log.debug(f"[SemanticCache] Hit record error: {e}")

        # Fire and forget
        threading.Thread(target=_update, daemon=True).start()

    def clear(
        self,
        function_name: Optional[str] = None,
        older_than_days: Optional[int] = None,
        cache_key: Optional[str] = None
    ) -> int:
        """
        Clear cache entries.

        Args:
            function_name: If provided, only clear entries for this function
            older_than_days: If provided, only clear entries older than N days
            cache_key: If provided, only clear this specific entry

        Returns:
            Number of entries cleared (approximate)
        """
        cleared_count = 0

        # Clear L1
        with self._l1_lock:
            if cache_key:
                if cache_key in self._l1_cache:
                    del self._l1_cache[cache_key]
                    cleared_count += 1
            elif function_name or older_than_days:
                # Need to iterate and filter
                keys_to_delete = []
                cutoff_time = time.time() - (older_than_days * 86400) if older_than_days else None

                for key, (result, result_type, created_at, expires_at) in self._l1_cache.items():
                    should_delete = True

                    if older_than_days and created_at > cutoff_time:
                        should_delete = False

                    # Note: L1 doesn't store function_name, so we can't filter by it in L1
                    # This is a limitation - L1 will be fully cleared if function_name is specified

                    if should_delete:
                        keys_to_delete.append(key)

                for key in keys_to_delete:
                    del self._l1_cache[key]
                cleared_count += len(keys_to_delete)
            else:
                # Clear all
                cleared_count = len(self._l1_cache)
                self._l1_cache.clear()

        # Clear L2
        db = self._get_db()
        if db:
            try:
                conditions = []
                params = {}

                if cache_key:
                    conditions.append("cache_key = %(cache_key)s")
                    params["cache_key"] = cache_key

                if function_name:
                    conditions.append("function_name = %(function_name)s")
                    params["function_name"] = function_name

                if older_than_days:
                    conditions.append(f"created_at < now() - INTERVAL {older_than_days} DAY")

                if conditions:
                    where_clause = " AND ".join(conditions)
                    query = f"ALTER TABLE semantic_sql_cache DELETE WHERE {where_clause}"
                else:
                    query = "TRUNCATE TABLE semantic_sql_cache"

                db.execute(query, params)
                log.info(f"[SemanticCache] L2 cleared: {query[:100]}...")

            except Exception as e:
                log.warning(f"[SemanticCache] L2 clear error: {e}")

        return cleared_count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        stats = {
            "l1": {
                "entries": len(self._l1_cache),
                "max_size": self.L1_MAX_SIZE,
            },
            "l2": {
                "available": False,
                "entries": 0,
                "total_hits": 0,
                "total_bytes": 0,
                "by_function": {},
            }
        }

        db = self._get_db()
        if db:
            try:
                # Get L2 stats
                query = """
                    SELECT
                        count() as entries,
                        sum(hit_count) as total_hits,
                        sum(result_bytes) as total_bytes
                    FROM semantic_sql_cache
                """
                rows = db.query(query)
                if rows and len(rows) > 0:
                    row = rows[0]
                    stats["l2"]["available"] = True
                    # Handle both dict and tuple formats from ClickHouse driver
                    if isinstance(row, dict):
                        stats["l2"]["entries"] = row.get("entries", 0)
                        stats["l2"]["total_hits"] = row.get("total_hits", 0) or 0
                        stats["l2"]["total_bytes"] = row.get("total_bytes", 0) or 0
                    else:
                        stats["l2"]["entries"] = row[0]
                        stats["l2"]["total_hits"] = row[1] or 0
                        stats["l2"]["total_bytes"] = row[2] or 0

                # Get by-function breakdown
                query = """
                    SELECT
                        function_name,
                        count() as entries,
                        sum(hit_count) as hits,
                        sum(result_bytes) as bytes
                    FROM semantic_sql_cache
                    GROUP BY function_name
                    ORDER BY entries DESC
                """
                rows = db.query(query)
                for row in rows:
                    # Handle both dict and tuple formats
                    if isinstance(row, dict):
                        func_name = row.get("function_name", "unknown")
                        stats["l2"]["by_function"][func_name] = {
                            "entries": row.get("entries", 0),
                            "hits": row.get("hits", 0) or 0,
                            "bytes": row.get("bytes", 0) or 0,
                        }
                    else:
                        stats["l2"]["by_function"][row[0]] = {
                            "entries": row[1],
                            "hits": row[2] or 0,
                            "bytes": row[3] or 0,
                        }

            except Exception as e:
                log.debug(f"[SemanticCache] Stats error: {e}")

        return stats

    def _is_far_future(self, dt) -> bool:
        """Check if a datetime is the far-future 'never expires' sentinel."""
        if dt is None:
            return True
        if hasattr(dt, 'year'):
            return dt.year >= 2099
        return False

    def list_entries(
        self,
        function_name: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "last_hit_at DESC"
    ) -> List[Dict[str, Any]]:
        """
        List cache entries for browsing.

        Args:
            function_name: Filter by function name
            limit: Max entries to return
            offset: Offset for pagination
            order_by: SQL ORDER BY clause

        Returns:
            List of cache entry dictionaries
        """
        db = self._get_db()
        if not db:
            return []

        try:
            where_clause = ""
            params = {}

            if function_name:
                where_clause = "WHERE function_name = %(function_name)s"
                params["function_name"] = function_name

            # Validate order_by to prevent SQL injection
            valid_columns = ["last_hit_at", "created_at", "hit_count", "result_bytes", "function_name"]
            order_parts = order_by.split()
            if order_parts[0] not in valid_columns:
                order_by = "last_hit_at DESC"

            query = f"""
                SELECT
                    cache_key,
                    function_name,
                    args_preview,
                    substring(result, 1, 200) as result_preview,
                    result_type,
                    created_at,
                    expires_at,
                    hit_count,
                    last_hit_at,
                    result_bytes
                FROM semantic_sql_cache
                {where_clause}
                ORDER BY {order_by}
                LIMIT {limit} OFFSET {offset}
            """

            rows = db.query(query, params)

            entries = []
            for row in rows:
                # Handle both dict and tuple formats
                if isinstance(row, dict):
                    expires_at = row.get("expires_at")
                    entries.append({
                        "cache_key": row.get("cache_key"),
                        "function_name": row.get("function_name"),
                        "args_preview": row.get("args_preview"),
                        "result_preview": row.get("result_preview"),
                        "result_type": row.get("result_type"),
                        "created_at": str(row.get("created_at")),
                        "expires_at": None if self._is_far_future(expires_at) else str(expires_at),
                        "hit_count": row.get("hit_count"),
                        "last_hit_at": str(row.get("last_hit_at")),
                        "result_bytes": row.get("result_bytes"),
                    })
                else:
                    expires_at = row[6]
                    entries.append({
                        "cache_key": row[0],
                        "function_name": row[1],
                        "args_preview": row[2],
                        "result_preview": row[3],
                        "result_type": row[4],
                        "created_at": str(row[5]),
                        "expires_at": None if self._is_far_future(expires_at) else str(expires_at),
                        "hit_count": row[7],
                        "last_hit_at": str(row[8]),
                        "result_bytes": row[9],
                    })

            return entries

        except Exception as e:
            log.warning(f"[SemanticCache] List error: {e}")
            return []

    def get_entry(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Get full details of a cache entry.

        Args:
            cache_key: The cache key to look up

        Returns:
            Full cache entry dictionary or None
        """
        db = self._get_db()
        if not db:
            return None

        try:
            query = """
                SELECT
                    cache_key,
                    function_name,
                    args_json,
                    result,
                    result_type,
                    created_at,
                    expires_at,
                    ttl_seconds,
                    hit_count,
                    last_hit_at,
                    result_bytes,
                    first_session_id,
                    first_caller_id
                FROM semantic_sql_cache
                WHERE cache_key = %(cache_key)s
                LIMIT 1
            """

            rows = db.query(query, {"cache_key": cache_key})

            if rows and len(rows) > 0:
                row = rows[0]
                # Handle both dict and tuple formats
                if isinstance(row, dict):
                    expires_at = row.get("expires_at")
                    return {
                        "cache_key": row.get("cache_key"),
                        "function_name": row.get("function_name"),
                        "args_json": row.get("args_json"),
                        "result": row.get("result"),
                        "result_type": row.get("result_type"),
                        "created_at": str(row.get("created_at")),
                        "expires_at": None if self._is_far_future(expires_at) else str(expires_at),
                        "ttl_seconds": row.get("ttl_seconds"),
                        "hit_count": row.get("hit_count"),
                        "last_hit_at": str(row.get("last_hit_at")),
                        "result_bytes": row.get("result_bytes"),
                        "first_session_id": row.get("first_session_id"),
                        "first_caller_id": row.get("first_caller_id"),
                    }
                else:
                    expires_at = row[6]
                    return {
                        "cache_key": row[0],
                        "function_name": row[1],
                        "args_json": row[2],
                        "result": row[3],
                        "result_type": row[4],
                        "created_at": str(row[5]),
                        "expires_at": None if self._is_far_future(expires_at) else str(expires_at),
                        "ttl_seconds": row[7],
                        "hit_count": row[8],
                        "last_hit_at": str(row[9]),
                        "result_bytes": row[10],
                        "first_session_id": row[11],
                        "first_caller_id": row[12],
                    }

            return None

        except Exception as e:
            log.warning(f"[SemanticCache] Get entry error: {e}")
            return None

    def prune_expired(self) -> int:
        """
        Manually prune expired entries from L1 and trigger L2 cleanup.

        Returns:
            Number of L1 entries pruned
        """
        pruned = 0
        now = time.time()

        # Prune L1
        with self._l1_lock:
            keys_to_delete = []
            for key, (result, result_type, created_at, expires_at) in self._l1_cache.items():
                if expires_at is not None and now > expires_at:
                    keys_to_delete.append(key)

            for key in keys_to_delete:
                del self._l1_cache[key]
            pruned = len(keys_to_delete)

        # L2 pruning happens automatically via TTL, but we can trigger OPTIMIZE
        db = self._get_db()
        if db:
            try:
                db.execute("OPTIMIZE TABLE semantic_sql_cache FINAL")
                log.info("[SemanticCache] L2 optimized (expired entries cleaned)")
            except Exception as e:
                log.debug(f"[SemanticCache] L2 optimize error: {e}")

        return pruned


# Convenience functions for backwards compatibility
_cache_instance: Optional[SemanticCache] = None


def get_cache() -> SemanticCache:
    """Get the global cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SemanticCache.get_instance()
    return _cache_instance


def get_cached_result(name: str, args: Dict[str, Any]) -> Tuple[bool, Any]:
    """
    Get a cached result (backwards compatible API).

    Returns (found, result) tuple.
    """
    found, result, _ = get_cache().get(name, args)
    return found, result


def set_cached_result(
    name: str,
    args: Dict[str, Any],
    result: Any,
    result_type: str = "VARCHAR",
    ttl_seconds: Optional[int] = None
) -> None:
    """Cache a result (backwards compatible API)."""
    # Get session/caller context if available
    session_id = ""
    caller_id = ""
    try:
        from ..caller_context import get_caller_id
        caller_id = get_caller_id() or ""
    except Exception:
        pass

    get_cache().set(
        name, args, result, result_type,
        ttl_seconds=ttl_seconds,
        session_id=session_id,
        caller_id=caller_id
    )


def clear_cache(name: Optional[str] = None) -> int:
    """Clear cache (backwards compatible API)."""
    return get_cache().clear(function_name=name)


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    return get_cache().get_stats()
