"""
Database adapter layer for LARS - DuckDB + Parquet persistence.

This module provides a unified database interface for LARS, backed by
DuckDB reading from Parquet files. It replaces the previous
implementation with a pure local storage solution.

Key features:
- No external database server required
- Concurrent read/write support via separate parquet files
- Compatible API with the previous DuckDB adapter
- Async fire-and-forget logging for query/deref events
"""
import json
import os
import threading
import time
import contextvars
import atexit
import uuid
import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from .lars_db import LarsDB, get_lars_db, SYSTEM_TABLES


# =============================================================================
# Schema Not Initialized Error (kept for API compatibility)
# =============================================================================

class SchemaNotInitializedError(Exception):
    """
    Raised when tables don't exist or can't be accessed.
    
    With parquet-backed storage, this typically means the data directory
    hasn't been created yet.
    """

    def __init__(self, original_error: Exception, table_name: str | None = None):
        self.original_error = original_error
        self.table_name = table_name

        if table_name:
            message = (
                f"\n\n"
                f"╔══════════════════════════════════════════════════════════════════╗\n"
                f"║  Table '{table_name}' has no data yet.                           \n"
                f"║                                                                  \n"
                f"║  Tables are created automatically when data is first written.    \n"
                f"║  If you expected data to exist, check $LARS_ROOT/data/           \n"
                f"╚══════════════════════════════════════════════════════════════════╝\n"
            )
        else:
            message = (
                f"\n\n"
                f"╔══════════════════════════════════════════════════════════════════╗\n"
                f"║  Database not initialized.                                       \n"
                f"║                                                                  \n"
                f"║  Ensure $LARS_ROOT is set and the data directory exists.         \n"
                f"╚══════════════════════════════════════════════════════════════════╝\n"
            )

        super().__init__(message)


# =============================================================================
# Query Logging Context Variables (kept for API compatibility)
# =============================================================================

query_source_context: contextvars.ContextVar[str] = contextvars.ContextVar('query_source', default='unknown')
query_caller_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('query_caller', default=None)
query_request_path_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('query_request_path', default=None)
query_page_ref_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('query_page_ref', default=None)


def set_query_source(source: str):
    """Set the query source for the current context (e.g., 'ui_backend')."""
    query_source_context.set(source)


def set_query_caller(caller: str):
    """Set the caller function/endpoint for the current context."""
    query_caller_context.set(caller)


def set_query_request_path(path: str):
    """Set the request path for the current context."""
    query_request_path_context.set(path)


def set_query_page_ref(page_ref: str):
    """Set the page reference (from Referer header) for the current context."""
    query_page_ref_context.set(page_ref)


# =============================================================================
# Compatibility Stubs for DuckDB-specific functions
# =============================================================================

def _normalize_db_mode(mode: str | None) -> str:
    """
    Normalize database mode string.
    
    With DuckDB/Parquet backend, always returns 'duckdb'.
    Kept for CLI compatibility.
    """
    return "duckdb"


def _clickhouse_server_reachable(
    *,
    host: str = "localhost",
    port: int = 9000,
    database: str = "lars",
    user: str = "default",
    password: str = "",
    timeout_s: float = 0.5,
) -> bool:
    """
    Check if DuckDB server is reachable.
    
    Always returns False with DuckDB/Parquet backend.
    Kept for CLI compatibility.
    """
    return False


# =============================================================================
# Async Query Logger
# =============================================================================

def _log_query_debug(query_type: str, sql: str, duration_ms: float, rows: int = 0):
    """
    Write query to debug log file when LARS_QUERY_DEBUG=1.
    Useful for identifying which queries are slow during cascade execution.
    """
    import os
    if not os.environ.get("LARS_QUERY_DEBUG"):
        return
    
    log_path = os.path.expanduser("~/query_debug.log")
    try:
        # Extract table name from SQL for quick scanning
        sql_lower = sql.lower()
        table = "?"
        if " from " in sql_lower:
            parts = sql_lower.split(" from ")[1].split()[0]
            table = parts.strip("(").split(".")[0] if parts else "?"
        
        # Truncate SQL for readability
        sql_preview = sql.replace("\n", " ")[:200]
        
        with open(log_path, "a") as f:
            from datetime import datetime
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            f.write(f"[{ts}] {duration_ms:7.1f}ms | {rows:5d} rows | {table:30s} | {query_type:7s} | {sql_preview}\n")
    except Exception:
        pass  # Don't let logging errors affect queries


def _env_enabled(name: str, default: str = "0") -> bool:
    """Parse common true/false env strings."""
    return os.environ.get(name, default).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
        "",
    )


class QueryLogger:
    """
    Async fire-and-forget query logger that writes to ui_sql_log table.
    
    Uses a background thread to batch writes for efficiency.

    Disabled by default; set LARS_UI_QUERY_LOG_ENABLED=1 to enable.
    """
    
    _instance = None
    _lock = threading.Lock()
    BATCH_SIZE = 50
    FLUSH_INTERVAL = 2.0

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, **kwargs):
        if self._initialized:
            return
        
        from queue import Queue, Empty, Full
        self._Queue = Queue
        self._Empty = Empty
        self._Full = Full
        
        self._queue = Queue()
        self._shutdown = False
        self._enabled = _env_enabled("LARS_UI_QUERY_LOG_ENABLED", "0")
        self._db = None

        self._flush_thread = None
        if self._enabled:
            self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._flush_thread.start()
            atexit.register(self._shutdown_handler)
        
        self._initialized = True

    def _get_db(self):
        if self._db is None:
            self._db = get_lars_db()
        return self._db

    def log_query(
        self,
        query_type: str,
        sql_preview: str,
        duration_ms: float,
        rows_returned: int | None = None,
        rows_affected: int | None = None,
        success: bool = True,
        error_message: str | None = None
    ):
        if not self._enabled or self._shutdown:
            return

        try:
            import hashlib
            sql_hash = hashlib.md5(sql_preview.encode('utf-8', errors='replace')).hexdigest()[:16]
            
            entry = {
                'id': uuid.uuid4().hex,
                'timestamp': datetime.now(timezone.utc),
                'query_type': query_type,
                'sql_preview': sql_preview[:500],
                'sql_hash': sql_hash,
                'duration_ms': duration_ms,
                'rows_returned': rows_returned,
                'rows_affected': rows_affected,
                'source': query_source_context.get(),
                'caller': query_caller_context.get(),
                'request_path': (query_request_path_context.get() or '')[:200],
                'page_ref': (query_page_ref_context.get() or '')[:200],
                'success': success,
                'error_message': (error_message or '')[:500] if error_message else None,
            }
            
            self._queue.put_nowait(entry)
        except self._Full:
            pass
        except Exception:
            pass

    def _flush_loop(self):
        batch = []
        last_flush = time.time()

        while not self._shutdown:
            try:
                try:
                    entry = self._queue.get(timeout=0.5)
                    batch.append(entry)
                except self._Empty:
                    pass

                now = time.time()
                should_flush = (
                    len(batch) >= self.BATCH_SIZE or
                    (batch and now - last_flush >= self.FLUSH_INTERVAL)
                )

                if should_flush and batch:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = now

            except Exception:
                pass

        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, batch: List[Dict]):
        try:
            db = self._get_db()
            db.write("ui_sql_log", batch)
        except Exception as e:
            print(f"[QueryLogger] Flush failed: {e}")

    def _shutdown_handler(self):
        self._shutdown = True
        if self._flush_thread is not None and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=1.0)


_query_logger: Optional[QueryLogger] = None


def get_query_logger() -> Optional[QueryLogger]:
    global _query_logger
    if not _env_enabled("LARS_UI_QUERY_LOG_ENABLED", "0"):
        return None
    if _query_logger is None:
        _query_logger = QueryLogger()
    return _query_logger


# =============================================================================
# Async Deref Logger
# =============================================================================

class DerefLogger:
    """
    Async fire-and-forget logger for @cascade() deref evaluations.
    """
    
    _instance = None
    _lock = threading.Lock()
    BATCH_SIZE = 100
    FLUSH_INTERVAL = 3.0

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, **kwargs):
        if self._initialized:
            return
        
        from queue import Queue, Empty, Full
        self._Queue = Queue
        self._Empty = Empty
        self._Full = Full
        
        self._queue = Queue()
        self._shutdown = False
        self._enabled = True
        self._db = None
        
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()
        atexit.register(self._shutdown_handler)
        
        self._initialized = True

    def _get_db(self):
        if self._db is None:
            self._db = get_lars_db()
        return self._db

    def log_deref(
        self,
        deref_expression: str,
        cascade_name: str,
        args: list,
        accessor_chain: str | None,
        resolved_value: str,
        resolved_value_type: str,
        session_id: str,
        protocol: str = 'pgwire',
        database_name: str = '',
        user_name: str = '',
        application_name: str = '',
        client_address: str = '',
        caller_id: str | None = None,
        cache_hit: bool = False,
        duration_ms: float = 0.0,
        error_message: str | None = None
    ):
        if not self._enabled or self._shutdown:
            return

        try:
            entry = {
                'id': uuid.uuid4().hex,
                'timestamp': datetime.now(timezone.utc),
                'deref_expression': deref_expression[:1000],
                'cascade_name': cascade_name,
                'args_json': json.dumps(args, default=str, ensure_ascii=False),
                'accessor_chain': accessor_chain or '',
                'resolved_value': (resolved_value or '')[:5000],
                'resolved_value_type': resolved_value_type,
                'cache_hit': cache_hit,
                'duration_ms': duration_ms,
                'error_message': (error_message or '')[:500] if error_message else '',
                'session_id': session_id,
                'protocol': protocol,
                'database_name': database_name,
                'user_name': user_name,
                'application_name': application_name,
                'client_address': client_address,
                'caller_id': caller_id,
            }
            
            self._queue.put_nowait(entry)
        except self._Full:
            pass
        except Exception:
            pass

    def _flush_loop(self):
        batch = []
        last_flush = time.time()

        while not self._shutdown:
            try:
                try:
                    entry = self._queue.get(timeout=0.5)
                    batch.append(entry)
                except self._Empty:
                    pass

                now = time.time()
                should_flush = (
                    len(batch) >= self.BATCH_SIZE or
                    (batch and now - last_flush >= self.FLUSH_INTERVAL)
                )

                if should_flush and batch:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = now

            except Exception:
                pass

        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, batch: List[Dict]):
        try:
            db = self._get_db()
            db.write("deref_log", batch)
        except Exception as e:
            print(f"[DerefLogger] Flush failed: {e}")

    def _shutdown_handler(self):
        self._shutdown = True
        if self._flush_thread.is_alive():
            self._flush_thread.join(timeout=1.0)


_deref_logger: Optional[DerefLogger] = None


def get_deref_logger() -> Optional[DerefLogger]:
    global _deref_logger
    if _deref_logger is None:
        _deref_logger = DerefLogger()
    return _deref_logger


def shutdown_async_loggers() -> None:
    """Stop background logging threads."""
    global _query_logger, _deref_logger

    if _query_logger is not None:
        try:
            _query_logger._shutdown_handler()
        except Exception:
            pass
        _query_logger = None

    if _deref_logger is not None:
        try:
            _deref_logger._shutdown_handler()
        except Exception:
            pass
        _deref_logger = None


# =============================================================================
# DuckDB/Parquet Adapter (replaces ClickHouseAdapter)
# =============================================================================

class DuckDBAdapter:
    """
    DuckDB + Parquet adapter for LARS persistence.
    
    Provides a compatible interface using
    uses DuckDB reading from Parquet files for storage.
    
    Key differences from the previous implementation:
    - No external server required
    - Writes create new parquet files (append-only)
    - Updates are handled by writing new rows; reads use "latest wins" semantics
    - Vector search delegates to DuckDB VSS (see rag/duckdb_store.py)
    """
    
    _instance = None
    _lock = threading.Lock()
    _initialized = False
    _housekeeping_done = False
    _READ_CACHE_CONFIG = {
        "enabled": True,
        "ttl_seconds": 0.75,
        "max_entries": 512,
        "max_rows": 2000,
    }
    _READ_CACHE_TABLE_ALIASES = {
        "unified_logs",
        "unified_logs_base",
        "session_state",
        "lars_system.logs",
        "lars_system.logs_raw",
        "lars_system.sessions",
        "cascade_analytics",
        "cell_analytics",
        "cascade_sessions",
    }
    _READ_CACHE_NONDETERMINISTIC_TOKENS = (
        " now(",
        "current_timestamp",
        "current_time",
        "current_date",
        "random(",
        "uuid(",
        "now64(",
    )

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, **kwargs):
        """Initialize adapter. Ignores DuckDB-specific kwargs for compatibility."""
        with DuckDBAdapter._lock:
            if DuckDBAdapter._initialized:
                return
            
            self._db = get_lars_db()
            self._read_cache_enabled = bool(DuckDBAdapter._READ_CACHE_CONFIG.get("enabled", True))
            self._read_cache_ttl_s = float(DuckDBAdapter._READ_CACHE_CONFIG.get("ttl_seconds", 0.75))
            self._read_cache_max_entries = int(DuckDBAdapter._READ_CACHE_CONFIG.get("max_entries", 512))
            self._read_cache_max_rows = int(DuckDBAdapter._READ_CACHE_CONFIG.get("max_rows", 2000))
            self._read_cache_lock = threading.Lock()
            self._read_cache: Dict[str, tuple[float, Any]] = {}
            DuckDBAdapter._initialized = True

    def run_housekeeping(self):
        """
        Run database housekeeping for DuckDB/Parquet backend.
        
        - Compacts small parquet files into larger ones
        - Applies dedup for tables with primary keys
        """
        if DuckDBAdapter._housekeeping_done:
            return
            
        # Run compaction with a reasonable threshold for startup
        # (don't compact unless there are enough files to make it worthwhile)
        try:
            results = self._db.compact_all(threshold=10, force=False)
            compacted = [r for r in results if r.get('files_before', 0) > r.get('files_after', 0)]
            if compacted:
                tables = ', '.join(r['table'] for r in compacted)
                print(f"[Housekeeping] Compacted: {tables}")
        except Exception as e:
            print(f"[Housekeeping] Compaction warning: {e}")
        
        DuckDBAdapter._housekeeping_done = True

    # =========================================================================
    # Query Operations
    # =========================================================================

    def _invalidate_read_cache(self):
        """Invalidate short-lived in-process SELECT result cache."""
        with self._read_cache_lock:
            self._read_cache.clear()

    def _can_use_read_cache(self, sql: str, output_format: str) -> bool:
        """Return True if this SELECT is eligible for short TTL caching."""
        if not self._read_cache_enabled:
            return False
        if output_format not in ("dict", "raw"):
            return False

        sql_lower = sql.strip().lower()
        if not (sql_lower.startswith("select") or sql_lower.startswith("with")):
            return False

        if any(token in sql_lower for token in DuckDBAdapter._READ_CACHE_NONDETERMINISTIC_TOKENS):
            return False

        return any(alias in sql_lower for alias in DuckDBAdapter._READ_CACHE_TABLE_ALIASES)

    def _read_cache_get(self, cache_key: str) -> Any | None:
        """Fetch a cached query result if still fresh."""
        now = time.time()
        with self._read_cache_lock:
            entry = self._read_cache.get(cache_key)
            if not entry:
                return None

            cached_at, value = entry
            if now - cached_at > self._read_cache_ttl_s:
                self._read_cache.pop(cache_key, None)
                return None

            # Refresh recency for FIFO/LRU-like eviction.
            self._read_cache.pop(cache_key, None)
            self._read_cache[cache_key] = (cached_at, value)
            return copy.deepcopy(value)

    def _read_cache_set(self, cache_key: str, result: Any):
        """Store a query result for short-lived cache reuse."""
        if isinstance(result, list) and len(result) > self._read_cache_max_rows:
            return

        with self._read_cache_lock:
            self._read_cache[cache_key] = (time.time(), copy.deepcopy(result))

            while len(self._read_cache) > self._read_cache_max_entries:
                oldest_key = next(iter(self._read_cache), None)
                if oldest_key is None:
                    break
                self._read_cache.pop(oldest_key, None)

    def query(self, sql: str, params: Dict | None = None, output_format: str = "dict", log_query: bool = True) -> Any:
        """
        Execute a SELECT query and return results.
        
        Args:
            sql: SQL query string (DuckDB SQL dialect, with legacy compat)
            params: Optional query parameters (%(name)s style)
            output_format: "dict" (list of dicts), "dataframe", or "raw" (tuples)
            log_query: Whether to log this query
            
        Returns:
            Query results in requested format
        """
        start_time = time.time()
        rows_returned = 0
        success = True
        error_msg = None
        cache_key = None

        try:
            # Substitute params into SQL (DuckDB uses $1 style, but we support %(name)s for compat)
            if params:
                sql = self._substitute_params(sql, params)
            
            # Translate DuckDB-specific SQL to DuckDB
            sql = self._translate_clickhouse_sql(sql)

            if self._can_use_read_cache(sql, output_format):
                cache_key = f"{output_format}:{sql}"
                cached_result = self._read_cache_get(cache_key)
                if cached_result is not None:
                    if output_format == "dataframe":
                        rows_returned = len(cached_result) if cached_result is not None else 0
                    elif output_format == "dict":
                        rows_returned = len(cached_result)
                    else:
                        rows_returned = len(cached_result) if isinstance(cached_result, (list, tuple)) else 0
                    return cached_result

            result = self._db.query(sql, output_format=output_format)

            if cache_key is not None:
                self._read_cache_set(cache_key, result)
            
            if output_format == "dataframe":
                rows_returned = len(result) if result is not None else 0
            elif output_format == "dict":
                rows_returned = len(result)
            else:
                rows_returned = len(result) if isinstance(result, (list, tuple)) else 0
            
            return result
            
        except Exception as e:
            success = False
            error_msg = str(e)
            print(f"[DuckDB Error] Query failed: {e}")
            print(f"[DuckDB Error] SQL: {sql[:500]}...")
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            # Debug file logging (when LARS_QUERY_DEBUG=1)
            _log_query_debug('query', sql, duration_ms, rows_returned)
            
            if log_query:
                logger = get_query_logger()
                if logger:
                    logger.log_query(
                        query_type='query',
                        sql_preview=sql,
                        duration_ms=duration_ms,
                        rows_returned=rows_returned,
                        success=success,
                        error_message=error_msg
                    )

    def query_df(self, sql: str, params: Dict | None = None) -> pd.DataFrame:
        """Execute query and return pandas DataFrame."""
        return self.query(sql, params, output_format="dataframe")

    def execute(self, sql: str, params: Dict | None = None, log_query: bool = True):
        """
        Execute a non-SELECT statement (CREATE, INSERT, UPDATE, etc.).
        
        Note: Most writes should use insert_rows() instead.
        """
        start_time = time.time()
        success = True
        error_msg = None

        try:
            if params:
                sql = self._substitute_params(sql, params)
            
            # Translate DuckDB-specific SQL to DuckDB
            sql = self._translate_clickhouse_sql(sql)
            
            self._db.execute(sql)
            self._invalidate_read_cache()
        except Exception as e:
            success = False
            error_msg = str(e)
            # Suppress noisy "Can only X from/update base table" errors (parquet views are immutable)
            if "Can only delete from base table" not in str(e) and "Can only update base table" not in str(e):
                print(f"[DuckDB Error] Execute failed: {e}")
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            # Debug file logging (when LARS_QUERY_DEBUG=1)
            _log_query_debug('execute', sql, duration_ms, 0)
            
            if log_query:
                logger = get_query_logger()
                if logger:
                    logger.log_query(
                        query_type='execute',
                        sql_preview=sql,
                        duration_ms=duration_ms,
                        success=success,
                        error_message=error_msg
                    )

    def _substitute_params(self, sql: str, params: Dict[str, Any]) -> str:
        """Substitute %(name)s style params into SQL."""
        import re
        
        def escape_value(val: Any) -> str:
            if val is None:
                return "NULL"
            if isinstance(val, bool):
                return "true" if val else "false"
            if isinstance(val, (int, float)):
                return str(val)
            if isinstance(val, (list, tuple)):
                return "[" + ", ".join(escape_value(v) for v in val) + "]"
            if isinstance(val, dict):
                return "'" + json.dumps(val, default=str).replace("'", "''") + "'"
            # String
            return "'" + str(val).replace("'", "''") + "'"
        
        for key, val in params.items():
            placeholder = f"%({key})s"
            sql = sql.replace(placeholder, escape_value(val))
        
        return sql

    def _translate_clickhouse_sql(self, sql: str) -> str:
        """
        Translate DuckDB-specific SQL to DuckDB-compatible SQL.
        
        Handles common patterns that were used in the DuckDB implementation:
        - ALTER TABLE ... UPDATE → UPDATE ... SET ...
        - uniqExactIf(col, cond) → COUNT(DISTINCT col) FILTER (WHERE cond)
        - countIf(cond) → COUNT(*) FILTER (WHERE cond)
        - anyIf(col, cond) → FIRST(col) FILTER (WHERE cond)
        - dateDiff('unit', start, end) → date_diff('unit', start, end)
        """
        import re
        
        original_sql = sql
        
        # 1. ALTER TABLE ... UPDATE → UPDATE ... SET ...
        # Pattern: ALTER TABLE tablename UPDATE col1 = val1, col2 = val2 WHERE cond
        alter_update_pattern = re.compile(
            r'ALTER\s+TABLE\s+(\w+)\s+UPDATE\s+(.+?)\s+WHERE\s+(.+)',
            re.IGNORECASE | re.DOTALL
        )
        match = alter_update_pattern.match(sql.strip())
        if match:
            table_name = match.group(1)
            set_clause = match.group(2).strip()
            where_clause = match.group(3).strip()
            sql = f"UPDATE {table_name} SET {set_clause} WHERE {where_clause}"
        
        # 2. uniqExactIf(col, cond) → COUNT(DISTINCT col) FILTER (WHERE cond)
        def replace_uniqExactIf(m):
            col = m.group(1).strip()
            cond = m.group(2).strip()
            return f"COUNT(DISTINCT {col}) FILTER (WHERE {cond})"
        
        sql = re.sub(
            r'uniqExactIf\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_uniqExactIf,
            sql,
            flags=re.IGNORECASE
        )
        
        # 3. countIf(cond) → COUNT(*) FILTER (WHERE cond)
        def replace_countIf(m):
            cond = m.group(1).strip()
            return f"COUNT(*) FILTER (WHERE {cond})"
        
        sql = re.sub(
            r'countIf\s*\(\s*([^)]+)\s*\)',
            replace_countIf,
            sql,
            flags=re.IGNORECASE
        )
        
        # 4. anyIf(col, cond) → FIRST(col) FILTER (WHERE cond)
        def replace_anyIf(m):
            col = m.group(1).strip()
            cond = m.group(2).strip()
            return f"FIRST({col}) FILTER (WHERE {cond})"
        
        sql = re.sub(
            r'anyIf\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_anyIf,
            sql,
            flags=re.IGNORECASE
        )
        
        # 5. dateDiff → date_diff (DuckDB uses camelCase, DuckDB uses snake_case)
        sql = re.sub(r'\bdateDiff\s*\(', 'date_diff(', sql, flags=re.IGNORECASE)
        
        # 6. endsWith(str, suffix) → suffix(str, suffix) or ends_with(str, suffix)
        # DuckDB uses suffix() function
        sql = re.sub(r'\bendsWith\s*\(', 'suffix(', sql, flags=re.IGNORECASE)
        
        # 7. startsWith(str, prefix) → prefix(str, prefix) or starts_with(str, prefix)
        # DuckDB uses prefix() function  
        sql = re.sub(r'\bstartsWith\s*\(', 'prefix(', sql, flags=re.IGNORECASE)
        
        # 8. toString(x) → CAST(x AS VARCHAR)
        def replace_toString(m):
            arg = m.group(1).strip()
            return f"CAST({arg} AS VARCHAR)"
        
        sql = re.sub(
            r'\btoString\s*\(\s*([^)]+)\s*\)',
            replace_toString,
            sql,
            flags=re.IGNORECASE
        )
        
        # 9. toInt32/toInt64/toFloat64 → CAST AS INTEGER/BIGINT/DOUBLE
        sql = re.sub(r'\btoInt32\s*\(\s*([^)]+)\s*\)', r'CAST(\1 AS INTEGER)', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\btoInt64\s*\(\s*([^)]+)\s*\)', r'CAST(\1 AS BIGINT)', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\btoFloat64\s*\(\s*([^)]+)\s*\)', r'CAST(\1 AS DOUBLE)', sql, flags=re.IGNORECASE)
        
        # 10. ifNull(x, default) → COALESCE(x, default)
        sql = re.sub(r'\bifNull\s*\(', 'COALESCE(', sql, flags=re.IGNORECASE)
        
        # 11. JSONExtractString/JSONExtract → json_extract_string/json_extract
        sql = re.sub(r'\bJSONExtractString\s*\(', 'json_extract_string(', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bJSONExtract\s*\(', 'json_extract(', sql, flags=re.IGNORECASE)
        
        # 12. CREATE DATABASE → CREATE SCHEMA (DuckDB doesn't have databases, uses schemas)
        sql = re.sub(r'\bCREATE\s+DATABASE\s+', 'CREATE SCHEMA ', sql, flags=re.IGNORECASE)
        
        # 13. lagInFrame → LAG (DuckDB window function)
        sql = re.sub(r'\blagInFrame\s*\(', 'LAG(', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bleadInFrame\s*\(', 'LEAD(', sql, flags=re.IGNORECASE)
        
        # 14. arrayJoin → UNNEST (DuckDB array expansion)
        sql = re.sub(r'\barrayJoin\s*\(', 'UNNEST(', sql, flags=re.IGNORECASE)
        
        # 15. has(array, element) → array_contains(array, element) or list_contains
        sql = re.sub(r'\bhas\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)', r'list_contains(\1, \2)', sql, flags=re.IGNORECASE)
        
        # 16. length(array) for arrays → array_length / len
        # Note: length() works for strings in both, but for arrays DuckDB uses length()
        # DuckDB uses len() or array_length() - len() works for both strings and arrays
        
        # 17. toDateTime(x) → CAST(x AS TIMESTAMP)
        def replace_toDateTime(m):
            arg = m.group(1).strip()
            return f"CAST({arg} AS TIMESTAMP)"
        sql = re.sub(
            r'\btoDateTime\s*\(\s*([^)]+)\s*\)',
            replace_toDateTime,
            sql,
            flags=re.IGNORECASE
        )
        
        # 17b. toDate(x) → CAST(x AS DATE)
        def replace_toDate(m):
            arg = m.group(1).strip()
            return f"CAST({arg} AS DATE)"
        sql = re.sub(
            r'\btoDate\s*\(\s*([^)]+)\s*\)',
            replace_toDate,
            sql,
            flags=re.IGNORECASE
        )
        
        # 18. multiIf → CASE WHEN (complex, but handle simple pattern)
        # multiIf(cond1, val1, cond2, val2, default) → CASE WHEN cond1 THEN val1 WHEN cond2 THEN val2 ELSE default END
        # Too complex for regex - leave for manual handling
        
        # 19. Empty string comparisons - DuckDB uses = '', DuckDB same but nullable handling differs
        # No change needed
        
        # 20. FINAL keyword (remove it - handled by dedup views)
        sql = re.sub(r'\bFINAL\b', '', sql, flags=re.IGNORECASE)
        
        # 21. now64() → now() (DuckDB high-precision timestamp)
        sql = re.sub(r'\bnow64\s*\(\s*\)', 'now()', sql, flags=re.IGNORECASE)
        
        # 22. subtractMinutes(ts, n) → (ts - INTERVAL n MINUTE)
        def replace_subtractMinutes(m):
            ts = m.group(1).strip()
            n = m.group(2).strip()
            return f"({ts} - INTERVAL {n} MINUTE)"
        sql = re.sub(
            r'\bsubtractMinutes\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_subtractMinutes,
            sql,
            flags=re.IGNORECASE
        )
        
        # 23. subtractHours(ts, n) → (ts - INTERVAL n HOUR)
        def replace_subtractHours(m):
            ts = m.group(1).strip()
            n = m.group(2).strip()
            return f"({ts} - INTERVAL {n} HOUR)"
        sql = re.sub(
            r'\bsubtractHours\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_subtractHours,
            sql,
            flags=re.IGNORECASE
        )
        
        # 24. subtractDays(ts, n) → (ts - INTERVAL n DAY)
        def replace_subtractDays(m):
            ts = m.group(1).strip()
            n = m.group(2).strip()
            return f"({ts} - INTERVAL {n} DAY)"
        sql = re.sub(
            r'\bsubtractDays\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_subtractDays,
            sql,
            flags=re.IGNORECASE
        )
        
        # 25. toUnixTimestamp(ts) → epoch(ts)
        sql = re.sub(r'\btoUnixTimestamp\s*\(', 'epoch(', sql, flags=re.IGNORECASE)
        
        # 26. argMax(col, by_col) → FIRST(col ORDER BY by_col DESC)
        # This works in aggregate context - gets value of col where by_col is max
        def replace_argMax(m):
            col = m.group(1).strip()
            by_col = m.group(2).strip()
            return f"FIRST({col} ORDER BY {by_col} DESC)"
        sql = re.sub(
            r'\bargMax\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_argMax,
            sql,
            flags=re.IGNORECASE
        )
        
        # 27. argMin(col, by_col) → FIRST(col ORDER BY by_col ASC)
        def replace_argMin(m):
            col = m.group(1).strip()
            by_col = m.group(2).strip()
            return f"FIRST({col} ORDER BY {by_col} ASC)"
        sql = re.sub(
            r'\bargMin\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_argMin,
            sql,
            flags=re.IGNORECASE
        )
        
        # 28. toYYYYMM(ts) → strftime(ts, '%Y%m')::INTEGER
        sql = re.sub(r'\btoYYYYMM\s*\(\s*([^)]+)\s*\)', r"CAST(strftime(\1, '%Y%m') AS INTEGER)", sql, flags=re.IGNORECASE)
        
        # 29. toStartOfDay(ts) → date_trunc('day', ts)
        sql = re.sub(r'\btoStartOfDay\s*\(', "date_trunc('day', ", sql, flags=re.IGNORECASE)
        
        # 30. toStartOfHour(ts) → date_trunc('hour', ts)
        sql = re.sub(r'\btoStartOfHour\s*\(', "date_trunc('hour', ", sql, flags=re.IGNORECASE)
        
        # 31. any(col) → ANY_VALUE(col) - DuckDB aggregate to get any value from group
        sql = re.sub(r'\bany\s*\(', 'ANY_VALUE(', sql, flags=re.IGNORECASE)
        
        # 32. sumIf(col, cond) → SUM(col) FILTER (WHERE cond)
        def replace_sumIf(m):
            col = m.group(1).strip()
            cond = m.group(2).strip()
            return f"SUM({col}) FILTER (WHERE {cond})"
        sql = re.sub(
            r'\bsumIf\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_sumIf,
            sql,
            flags=re.IGNORECASE
        )
        
        # 33. avgIf(col, cond) → AVG(col) FILTER (WHERE cond)
        def replace_avgIf(m):
            col = m.group(1).strip()
            cond = m.group(2).strip()
            return f"AVG({col}) FILTER (WHERE {cond})"
        sql = re.sub(
            r'\bavgIf\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_avgIf,
            sql,
            flags=re.IGNORECASE
        )
        
        # 34. nullIf → NULLIF (case normalization)
        sql = re.sub(r'\bnullIf\s*\(', 'NULLIF(', sql)
        
        # 35. empty(str) → (str = '' OR str IS NULL)
        sql = re.sub(r'\bempty\s*\(\s*([^)]+)\s*\)', r'(\1 = \'\' OR \1 IS NULL)', sql, flags=re.IGNORECASE)
        
        # 36. notEmpty(str) → (str != '' AND str IS NOT NULL)
        sql = re.sub(r'\bnotEmpty\s*\(\s*([^)]+)\s*\)', r'(\1 != \'\' AND \1 IS NOT NULL)', sql, flags=re.IGNORECASE)
        
        # 37. replaceRegexpOne(str, pattern, repl) → regexp_replace(str, pattern, repl)
        sql = re.sub(r'\breplaceRegexpOne\s*\(', 'regexp_replace(', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\breplaceRegexpAll\s*\(', 'regexp_replace(', sql, flags=re.IGNORECASE)  # DuckDB replaces all by default
        
        # 38. groupArray(col) → list(col) - collect values into array
        sql = re.sub(r'\bgroupArray\s*\(', 'list(', sql, flags=re.IGNORECASE)
        
        # 39. arrayStringConcat(arr, sep) → array_to_string(arr, sep)
        sql = re.sub(r'\barrayStringConcat\s*\(', 'array_to_string(', sql, flags=re.IGNORECASE)
        
        # 40. splitByChar(sep, str) → string_split(str, sep) - note: args reversed!
        def replace_splitByChar(m):
            sep = m.group(1).strip()
            s = m.group(2).strip()
            return f"string_split({s}, {sep})"
        sql = re.sub(
            r'\bsplitByChar\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)',
            replace_splitByChar,
            sql,
            flags=re.IGNORECASE
        )
        
        # 41. tuple(...) → struct_pack(...) or row(...) for DuckDB anonymous structs
        # Note: groupArray(tuple(...)) becomes list(struct_pack(...))
        sql = re.sub(r'\btuple\s*\(', 'ROW(', sql, flags=re.IGNORECASE)
        
        # 42. position(haystack, needle) → strpos(haystack, needle) - same args
        # Note: DuckDB also has position(needle IN haystack) syntax which is different
        sql = re.sub(r'\bposition\s*\(([^,]+),\s*([^)]+)\)', r'strpos(\1, \2)', sql, flags=re.IGNORECASE)
        
        # 43. extract(str, pattern) → regexp_extract(str, pattern)
        sql = re.sub(r'\bextract\s*\(([^,]+),\s*([^)]+)\)', r'regexp_extract(\1, \2)', sql, flags=re.IGNORECASE)
        
        # 44. stddevPop → stddev_pop (case normalization for standard deviation)
        sql = re.sub(r'\bstddevPop\s*\(', 'stddev_pop(', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bstddevSamp\s*\(', 'stddev_samp(', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bvarPop\s*\(', 'var_pop(', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bvarSamp\s*\(', 'var_samp(', sql, flags=re.IGNORECASE)
        
        # 45. if(isNaN(expr), 0, expr) → COALESCE(expr, 0)
        # DuckDB uses isNaN for NaN checks; DuckDB aggregates return NULL instead
        # This handles patterns like: if(isNaN(AVG(col)), 0, AVG(col))
        # We use a function to handle nested parentheses properly
        def replace_if_isnan_pattern(sql_text):
            """Replace if(isNaN(X), default, X) with COALESCE(X, default)"""
            import re
            # Find if(isNaN( and then match parentheses properly
            pattern = r'\bif\s*\(\s*isNaN\s*\('
            result = []
            i = 0
            while i < len(sql_text):
                match = re.search(pattern, sql_text[i:], re.IGNORECASE)
                if not match:
                    result.append(sql_text[i:])
                    break
                
                # Add everything before the match
                result.append(sql_text[i:i + match.start()])
                
                # Find the start of the expression inside isNaN(
                expr_start = i + match.end()
                
                # Count parentheses to find end of isNaN(...)
                paren_count = 1
                j = expr_start
                while j < len(sql_text) and paren_count > 0:
                    if sql_text[j] == '(':
                        paren_count += 1
                    elif sql_text[j] == ')':
                        paren_count -= 1
                    j += 1
                
                expr = sql_text[expr_start:j-1]  # Expression inside isNaN()
                
                # Now we should be at ), skip comma and whitespace to get default value
                # Pattern: ), default, expr)
                rest = sql_text[j:]
                comma_match = re.match(r'\s*,\s*', rest)
                if comma_match:
                    default_start = j + comma_match.end()
                    # Find the default value (until next comma)
                    comma_pos = sql_text.find(',', default_start)
                    if comma_pos > 0:
                        default_val = sql_text[default_start:comma_pos].strip()
                        # Find the closing ) of the if()
                        # Skip the third argument (should be same as expr)
                        paren_count = 1
                        k = comma_pos + 1
                        while k < len(sql_text) and paren_count > 0:
                            if sql_text[k] == '(':
                                paren_count += 1
                            elif sql_text[k] == ')':
                                paren_count -= 1
                            k += 1
                        
                        result.append(f'COALESCE({expr}, {default_val})')
                        i = k
                        continue
                
                # Fallback: couldn't parse, keep original
                result.append(sql_text[i + match.start():i + match.end()])
                i = i + match.end()
            
            return ''.join(result)
        
        sql = replace_if_isnan_pattern(sql)
        
        # 46. isNaN(expr) standalone → false (DuckDB doesn't produce NaN from aggregates, just NULL)
        # If isNaN is still present, it's probably checking for actual NaN which is rare
        sql = re.sub(r'\bisNaN\s*\(\s*([^)]+)\s*\)', r'false', sql, flags=re.IGNORECASE)
        
        # 47. DESCRIBE TABLE tablename → DESCRIBE tablename (DuckDB doesn't use TABLE keyword)
        sql = re.sub(r'\bDESCRIBE\s+TABLE\s+', 'DESCRIBE ', sql, flags=re.IGNORECASE)
        
        return sql

    # =========================================================================
    # Insert Operations
    # =========================================================================

    def insert_rows(self, table: str, rows: List[Dict], columns: List[str] | None = None, log_query: bool = True):
        """
        Insert rows into a table (writes new parquet file).
        
        Args:
            table: Table name
            rows: List of dicts to insert
            columns: Optional column list (defaults to keys of first row)
            log_query: Whether to log this operation
        """
        if not rows:
            return

        start_time = time.time()
        success = True
        error_msg = None
        
        try:
            if columns:
                # Filter rows to only include specified columns
                rows = [{k: r.get(k) for k in columns} for r in rows]
            
            self._db.write(table, rows)
            self._invalidate_read_cache()
            
        except Exception as e:
            success = False
            error_msg = str(e)
            print(f"[DuckDB Error] Insert failed: {e}")
            raise
        finally:
            if log_query and table != 'ui_sql_log':  # Avoid recursion
                duration_ms = (time.time() - start_time) * 1000
                logger = get_query_logger()
                if logger:
                    logger.log_query(
                        query_type='insert_rows',
                        sql_preview=f"INSERT INTO {table} ({len(rows)} rows)",
                        duration_ms=duration_ms,
                        rows_affected=len(rows),
                        success=success,
                        error_message=error_msg
                    )

    def insert_dataframe(self, table: str, df: pd.DataFrame, columns: List[str] | None = None, log_query: bool = True):
        """Insert a pandas DataFrame into a table."""
        if df.empty:
            return
        
        rows = df.to_dict(orient='records')
        self.insert_rows(table, rows, columns, log_query)

    # =========================================================================
    # Update Operations (Append-Only Pattern)
    # =========================================================================
    
    def update_row(
        self,
        table: str,
        updates: Dict[str, Any],
        where: str,
        sync: bool = True,
        log_query: bool = True
    ):
        """
        Update rows by appending new versions (append-only pattern).
        
        With parquet storage, updates are implemented by inserting new rows
        with the updated values. Views should use ROW_NUMBER() OVER
        (PARTITION BY key ORDER BY updated_at DESC) to get latest values.
        
        Args:
            table: Table name
            updates: Dict of column -> new value
            where: WHERE clause (without WHERE keyword), e.g. "session_id = 'abc'"
            sync: Ignored (for legacy compatibility)
            log_query: Whether to log
        """
        import re
        
        if not updates:
            return
        
        # Parse simple WHERE clause to extract key column and value
        # Supports: "column = 'value'" or "column = value"
        match = re.match(r"(\w+)\s*=\s*'?([^']+)'?", where.strip())
        if match:
            key_column = match.group(1)
            key_value = match.group(2)
        else:
            # Fallback: just include the where clause info in metadata
            key_column = '_where'
            key_value = where
        
        # Create a new row with the key and updated values
        row = {key_column: key_value, **updates}
        
        # Add timestamp for ordering (critical for merge-on-read dedup)
        row['updated_at'] = datetime.now(timezone.utc)
        
        self.insert_rows(table, [row], log_query=log_query)

    def batch_update_costs(self, table: str, updates: List[Dict]):
        """
        Batch update cost records (append to costs table for merge-on-read).
        
        Each update dict should have:
        - trace_id or message_id: ID to join with unified_logs
        - cost: Cost value
        - (optional) tokens_in, tokens_out, tokens_reasoning, model, provider
        
        Note: unified_logs is parquet-backed (immutable). Costs are stored in a
        separate 'costs' table and merged via the unified_logs view on read.
        """
        if not updates:
            return
        
        # Write to costs table - merged with unified_logs via view
        cost_rows = []
        for update in updates:
            # Accept trace_id (from unified_logs.py) or message_id
            trace_id = update.get('trace_id') or update.get('message_id')
            if not trace_id:
                continue
                
            cost_rows.append({
                'id': uuid.uuid4().hex,
                'trace_id': trace_id,
                'message_id': update.get('message_id'),
                'session_id': update.get('session_id', ''),
                'timestamp': datetime.now(timezone.utc),
                'cost': update.get('cost'),
                'tokens_in': update.get('tokens_in'),
                'tokens_out': update.get('tokens_out'),
                'tokens_reasoning': update.get('tokens_reasoning'),
                'model': update.get('model'),
                'provider': update.get('provider'),
            })
        
        if cost_rows:
            self._db.write('costs', cost_rows)
            self._invalidate_read_cache()

    def mark_take_winner(
        self,
        table: str,
        session_id: str,
        cell_name: str,
        take_index: int,
        log_query: bool = True
    ):
        """
        Mark a take as the winner (append-only pattern).
        
        Writes a winner record to the take_winners table.
        Queries should join against this to determine winning takes.
        """
        winner_record = {
            'id': uuid.uuid4().hex,
            'timestamp': datetime.now(timezone.utc),
            'session_id': session_id,
            'cell_name': cell_name,
            'winning_take_index': take_index,
        }
        
        # Write to take_winners table (creates table if needed)
        self._db.write('take_winners', [winner_record])
        self._invalidate_read_cache()

    # =========================================================================
    # Vector Search (delegates to DuckDB VSS)
    # =========================================================================

    def vector_search(
        self,
        table: str,
        embedding: List[float],
        embedding_column: str = "embedding",
        limit: int = 10,
        where_clause: str | None = None,
        select_columns: List[str] | None = None,
    ) -> List[Dict]:
        """
        Vector similarity search.
        
        NOTE: Vector search uses DuckDB VSS (see rag/duckdb_store.py).
        This method is kept for API compatibility but may not work as expected.
        """
        print(f"[DuckDB] vector_search called - use rag/duckdb_store for vector operations")
        return []

    # =========================================================================
    # Context Cards (simplified for parquet)
    # =========================================================================

    def insert_context_cards(self, rows: List[Dict]):
        """Insert context cards."""
        if not rows:
            return
        self._db.write('context_cards', rows)
        self._invalidate_read_cache()

    def get_context_cards(
        self,
        session_id: str,
        cell_name: str | None = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get context cards for a session."""
        sql = f"""
            SELECT * FROM context_cards
            WHERE session_id = '{session_id}'
        """
        if cell_name:
            sql += f" AND cell_name = '{cell_name}'"
        sql += f" ORDER BY message_timestamp DESC LIMIT {limit}"
        
        return self.query(sql, output_format="dict", log_query=False)

    def get_context_cards_with_embeddings(
        self,
        session_id: str,
        cell_name: str | None = None,
    ) -> List[Dict]:
        """Get context cards with their embeddings."""
        return self.get_context_cards(session_id, cell_name, limit=1000)

    def search_context_cards_semantic(
        self,
        session_id: str,
        query_embedding: List[float],
        limit: int = 10,
        cell_name: str | None = None,
    ) -> List[Dict]:
        """
        Semantic search over context cards.
        
        NOTE: Should use DuckDB VSS for proper vector search (see rag/duckdb_store.py).
        """
        print(f"[DuckDB] search_context_cards_semantic - use rag/duckdb_store for vector search")
        return self.get_context_cards(session_id, cell_name, limit)

    # =========================================================================
    # Table Management
    # =========================================================================

    def ensure_table_exists(self, table_name: str, ddl: str):
        """
        Ensure a table exists.
        
        With parquet storage, tables are created automatically.
        This is a no-op.
        """
        pass

    def table_exists(self, table_name: str) -> bool:
        """Check if a table has any data."""
        return self._db.table_exists(table_name)

    def get_table_row_count(self, table_name: str) -> int:
        """Get approximate row count for a table."""
        try:
            result = self.query(f"SELECT COUNT(*) as cnt FROM {table_name}", log_query=False)
            return result[0]['cnt'] if result else 0
        except Exception:
            return 0


# =============================================================================
# Compatibility Aliases
# =============================================================================

# Keep ClickHouseAdapter as an alias for compatibility
ClickHouseAdapter = DuckDBAdapter


# =============================================================================
# Singleton Access Functions
# =============================================================================

_db_adapter: Optional[DuckDBAdapter] = None


def get_db_adapter() -> DuckDBAdapter:
    """
    Get the database adapter singleton.
    
    Returns a DuckDBAdapter instance (parquet-backed).
    """
    global _db_adapter
    
    if _db_adapter is None:
        _db_adapter = DuckDBAdapter()
    
    return _db_adapter


def get_db() -> DuckDBAdapter:
    """Alias for get_db_adapter()."""
    return get_db_adapter()


def ensure_housekeeping():
    """
    Ensure database housekeeping has been run.
    
    With parquet storage, this is a no-op (tables auto-create).
    """
    get_db_adapter().run_housekeeping()


def reset_adapter():
    """Reset the adapter singleton (mainly for testing)."""
    global _db_adapter
    _db_adapter = None
    DuckDBAdapter._instance = None
    DuckDBAdapter._initialized = False
    DuckDBAdapter._housekeeping_done = False
