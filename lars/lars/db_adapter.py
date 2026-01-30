"""
Database adapter layer for LARS - ClickHouse-compatible persistence.

This module provides a single adapter that handles all database operations.

By default, LARS uses a ClickHouse server. For easier local evaluation, it can
optionally fall back to CHDB (embedded ClickHouse) so users don't need a running
ClickHouse service.

Key features:
- Singleton pattern for connection reuse
- Batch INSERT for efficient writes
- ALTER TABLE UPDATE for cost tracking and winner flagging
- Native vector search with cosineDistance()
- Auto-create database and tables on startup
- Query logging to ui_sql_log table (async fire-and-forget)
"""
import json
import os
import math
import threading
import hashlib
import time
import queue
import contextvars
import atexit
import traceback
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import pandas as pd


# =============================================================================
# Schema Not Initialized Error
# =============================================================================

class SchemaNotInitializedError(Exception):
    """
    Raised when ClickHouse tables don't exist or can't be accessed.

    This typically means the user needs to run `lars db init` to create
    the database schema before using LARS.
    """

    def __init__(self, original_error: Exception, table_name: str | None = None):
        self.original_error = original_error
        self.table_name = table_name

        if table_name:
            message = (
                f"\n\n"
                f"╔══════════════════════════════════════════════════════════════════╗\n"
                f"║  Database table '{table_name}' does not exist.                   \n"
                f"║                                                                  \n"
                f"║  Please initialize the database schema by running:               \n"
                f"║                                                                  \n"
                f"║      lars db init                                              \n"
                f"║                                                                  \n"
                f"║  This creates all required tables and runs migrations.           \n"
                f"╚══════════════════════════════════════════════════════════════════╝\n"
            )
        else:
            message = (
                f"\n\n"
                f"╔══════════════════════════════════════════════════════════════════╗\n"
                f"║  Database schema not initialized or connection failed.           \n"
                f"║                                                                  \n"
                f"║  Please initialize the database schema by running:               \n"
                f"║                                                                  \n"
                f"║      lars db init                                              \n"
                f"║                                                                  \n"
                f"║  Make sure ClickHouse is running and accessible.                 \n"
                f"╚══════════════════════════════════════════════════════════════════╝\n"
            )

        super().__init__(message)


def _is_missing_table_error(error: Exception) -> tuple[bool, str | None]:
    """
    Check if an exception is due to a missing table.

    Returns:
        Tuple of (is_missing_table, table_name_or_none)
    """
    import re
    err_str = str(error).lower()

    # ClickHouse error patterns for missing tables
    # "Code: 60. DB::Exception: Table lars.unified_logs doesn't exist"
    # "Table lars.unified_logs doesn't exist"
    # "Unknown table expression identifier 'unified_logs'"

    if "doesn't exist" in err_str or "does not exist" in err_str:
        # Try to extract table name from common ClickHouse patterns.
        #
        # Examples:
        # - "Table lars.unified_logs doesn't exist"
        # - "Table lars.unified_logs does not exist"
        # - "Table `lars`.`unified_logs` doesn't exist"
        # - "Table `lars`.`unified_logs` does not exist"
        match = re.search(
            r"table\s+(?:`?(\w+)`?\.)?`?(\w+)`?\s+does(?:n't| not)\s+exist",
            err_str,
        )
        if match:
            # group(2) is the table name; group(1) is optional database
            return True, match.group(2)
        return True, None

    if "unknown table" in err_str:
        # Pattern: "Unknown table expression identifier 'tablename'"
        match = re.search(r"['\"](\w+)['\"]", err_str)
        if match:
            return True, match.group(1)
        return True, None

    # Database doesn't exist
    if "database" in err_str and ("doesn't exist" in err_str or "does not exist" in err_str):
        return True, None

    return False, None


# =============================================================================
# Backend Selection Helpers (ClickHouse server vs CHDB)
# =============================================================================

def _normalize_db_mode(mode: str | None) -> str:
    val = (mode or "").strip().lower()
    if not val:
        return "auto"
    if val in ("auto",):
        return "auto"
    if val in ("clickhouse", "server", "clickhouse_server", "ch"):
        return "clickhouse"
    if val in ("chdb", "embedded", "local"):
        return "chdb"
    # Unknown mode: treat as auto (safer default than hard-fail).
    return "auto"


def _clickhouse_server_reachable(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    timeout_s: float = 0.5,
) -> bool:
    """
    Best-effort ClickHouse reachability check for auto mode.

    Keep this fast: it runs on startup for users without ClickHouse.
    """
    try:
        from clickhouse_driver import Client  # type: ignore

        client = Client(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=timeout_s,
            send_receive_timeout=max(1, timeout_s),
            sync_request_timeout=max(1, timeout_s),
            settings={"use_numpy": False, "max_execution_time": 2},
        )
        client.execute("SELECT 1")
        try:
            client.disconnect()
        except Exception:
            pass
        return True
    except Exception:
        return False


_CLICKHOUSE_PARAM_RE = re.compile(r"%\(([A-Za-z0-9_]+)\)s")


def _format_datetime_for_clickhouse(value: Any) -> str:
    """
    Format datetime/date-like values for ClickHouse SQL literals.

    ClickHouse DateTime/DateTime64 parsing accepts common string formats.
    Prefer a space separator to avoid edge cases across engines.
    """
    # pandas.Timestamp acts like datetime; avoid importing pandas here.
    if isinstance(value, datetime):
        dt = value
        # Normalize tz-aware to UTC and drop tzinfo (ClickHouse typically stores naive).
        try:
            if dt.tzinfo is not None:
                from datetime import timezone
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            dt = dt.replace(tzinfo=None)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f").rstrip("0").rstrip(".")

    # date objects
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day") and not hasattr(value, "hour"):
        try:
            return f"{int(value.year):04d}-{int(value.month):02d}-{int(value.day):02d}"
        except Exception:
            return str(value)

    return str(value)


def _escape_clickhouse_literal(value: Any) -> str:
    """
    Escape a Python value as a ClickHouse SQL literal.

    Used for CHDB execution and for any code paths that require local param
    substitution (ClickHouse server mode still relies on clickhouse-driver's
    native parameter binding).
    """
    if value is None:
        return "NULL"

    # bool is a subclass of int, so check it first.
    if isinstance(value, bool):
        return "1" if value else "0"

    if isinstance(value, (int,)):
        return str(value)

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "NULL"
        return repr(value)

    # UUIDs and other identifiers
    if hasattr(value, "hex") and type(value).__name__.lower() == "uuid":
        return "'" + str(value) + "'"

    if isinstance(value, (bytes, bytearray, memoryview)):
        return "'" + bytes(value).hex() + "'"

    # Datetime/date-like
    if isinstance(value, datetime) or (hasattr(value, "isoformat") and hasattr(value, "year") and hasattr(value, "month")):
        s = _format_datetime_for_clickhouse(value)
        s = s.replace("\\", "\\\\").replace("'", "''")
        return f"'{s}'"

    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_escape_clickhouse_literal(v) for v in value) + "]"

    if isinstance(value, dict):
        s = json.dumps(value, default=str, ensure_ascii=False)
        s = s.replace("\\", "\\\\").replace("'", "''")
        return f"'{s}'"

    # Fallback: treat as string
    s = str(value)
    s = s.replace("\\", "\\\\").replace("'", "''")
    return f"'{s}'"


def _substitute_clickhouse_percent_params(sql: str, params: Dict[str, Any]) -> str:
    """
    Substitute clickhouse-driver style params in SQL: %(name)s.

    CHDB does not support clickhouse-driver's native parameter binding, so we
    need to substitute into SQL text safely.
    """
    if not params:
        return sql

    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in params:
            raise KeyError(f"Missing SQL param: {key}")
        return _escape_clickhouse_literal(params[key])

    return _CLICKHOUSE_PARAM_RE.sub(repl, sql)


# =============================================================================
# Query Logging System - Async fire-and-forget logging to ClickHouse
# =============================================================================

# Context variable to track the source of queries (e.g., 'ui_backend', 'lars_core')
query_source_context: contextvars.ContextVar[str] = contextvars.ContextVar('query_source', default='unknown')

# Context variable to track the caller function/endpoint
query_caller_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('query_caller', default=None)

# Context variable to track the request path (e.g., '/api/sextant/species/abc123')
query_request_path_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('query_request_path', default=None)

# Context variable to track the page reference from Referer header
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


class QueryLogger:
    """
    Async fire-and-forget query logger that writes to ui_sql_log table.

    Features:
    - Uses a separate ClickHouse client connection (bypasses main query lock)
    - Queue-based batching for efficient inserts
    - Background daemon thread flushes batches periodically
    - Never blocks the main query path
    - Graceful shutdown on process exit
    """

    _instance = None
    _lock = threading.Lock()

    # Batch settings
    BATCH_SIZE = 50  # Flush after this many entries
    FLUSH_INTERVAL = 2.0  # Flush every N seconds regardless of batch size

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, host: str | None = None, port: int | None = None, database: str | None = None,
                 user: str | None = None, password: str | None = None):
        """Initialize the query logger (singleton - only runs once)."""
        if self._initialized:
            return

        self._queue = queue.Queue()
        self._client = None
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._shutdown = False
        self._enabled = True  # Can be disabled if table creation fails

        # Start background flush thread
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

        # Register shutdown handler
        atexit.register(self._shutdown_handler)

        self._initialized = True

    def _get_client(self):
        """Get the main DB adapter for logging (works for ClickHouse server and CHDB)."""
        if self._client is not None:
            return self._client

        try:
            db = get_db_adapter()
            # Keep a cached reference to avoid repeated adapter lookups.
            self._client = db
            # Ensure ui_sql_log table exists.
            self._ensure_table()
            return self._client
        except Exception as e:
            print(f"[QueryLogger] Failed to get DB adapter: {e}")
            self._enabled = False
            return None

    def _ensure_table(self):
        """Ensure ui_sql_log table exists."""
        try:
            from .schema import UI_SQL_LOG_SCHEMA
            # Use log_query=False to avoid writing ui_sql_log about itself.
            if hasattr(self._client, "execute"):
                # ClickHouseAdapter.execute supports log_query kwarg.
                try:
                    self._client.execute(UI_SQL_LOG_SCHEMA, log_query=False)
                except TypeError:
                    # Backwards-compatible fallback if execute() doesn't accept log_query.
                    self._client.execute(UI_SQL_LOG_SCHEMA)
        except Exception as e:
            print(f"[QueryLogger] Failed to create ui_sql_log table: {e}")
            self._enabled = False

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
        """
        Log a query asynchronously (fire-and-forget).

        Args:
            query_type: Type of query ('query', 'execute', 'insert_rows', etc.)
            sql_preview: First 500 chars of SQL or table name
            duration_ms: Query duration in milliseconds
            rows_returned: Number of rows returned (for SELECT queries)
            rows_affected: Number of rows affected (for write operations)
            success: Whether the query succeeded
            error_message: Error message if query failed
        """
        if not self._enabled or self._shutdown:
            return

        try:
            # Get context
            source = query_source_context.get()
            caller = query_caller_context.get()
            request_path = query_request_path_context.get()
            page_ref = query_page_ref_context.get()

            # Create SQL hash for grouping similar queries
            sql_hash = hashlib.md5(sql_preview.encode('utf-8', errors='replace')).hexdigest()[:16]

            entry = {
                'query_type': query_type,
                'sql_preview': sql_preview[:500],  # Truncate to 500 chars
                'sql_hash': sql_hash,
                'duration_ms': duration_ms,
                'rows_returned': rows_returned,
                'rows_affected': rows_affected,
                'source': source,
                'caller': caller,
                'request_path': request_path[:200] if request_path else None,
                'page_ref': page_ref[:200] if page_ref else None,
                'success': success,
                'error_message': error_message[:500] if error_message else None,
            }

            # Non-blocking put
            self._queue.put_nowait(entry)
        except queue.Full:
            pass  # Drop entry if queue is full - never block
        except Exception:
            pass  # Silently ignore any logging errors

    def _flush_loop(self):
        """Background thread that flushes batched entries to ClickHouse."""
        batch = []
        last_flush = time.time()

        while not self._shutdown:
            try:
                # Try to get an entry with timeout
                try:
                    entry = self._queue.get(timeout=0.5)
                    batch.append(entry)
                except queue.Empty:
                    pass

                # Flush if batch is full or interval elapsed
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
                # Never crash the flush thread
                pass

        # Final flush on shutdown
        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, batch: List[Dict]):
        """Flush a batch of entries to ClickHouse."""
        client = self._get_client()
        if client is None or not batch:
            return

        try:
            columns = [
                'query_type', 'sql_preview', 'sql_hash', 'duration_ms',
                'rows_returned', 'rows_affected', 'source', 'caller',
                'request_path', 'page_ref', 'success', 'error_message'
            ]

            # Prefer adapter insert_rows for compatibility across backends.
            try:
                client.insert_rows("ui_sql_log", batch, columns=columns, log_query=False)
            except TypeError:
                # Older adapter signature without log_query.
                client.insert_rows("ui_sql_log", batch, columns=columns)
        except Exception as e:
            # Log but don't crash
            print(f"[QueryLogger] Flush failed: {e}")

    def _shutdown_handler(self):
        """Handle graceful shutdown."""
        self._shutdown = True
        # Give the flush thread a moment to finish
        if self._flush_thread.is_alive():
            self._flush_thread.join(timeout=1.0)


# Global query logger singleton (lazily initialized)
_query_logger: Optional[QueryLogger] = None


def get_query_logger() -> Optional[QueryLogger]:
    """Get the query logger singleton (lazily initialized)."""
    global _query_logger
    if _query_logger is None:
        _query_logger = QueryLogger()
    return _query_logger


# =============================================================================
# Deref Logging System - Async fire-and-forget logging for @cascade() evaluations
# =============================================================================

class DerefLogger:
    """
    Async fire-and-forget logger for @cascade() deref evaluations.

    Records deref operations to ClickHouse for:
    - Debugging: See what values were injected into queries
    - Analytics: Track usage patterns of param_get/param_set/etc.
    - UI surfacing: Show deref values alongside query results
    - Audit trail: Know which sessions/clients are using what parameters

    Features:
    - Uses a separate ClickHouse client connection (bypasses main query lock)
    - Queue-based batching for efficient inserts
    - Background daemon thread flushes batches periodically
    - Never blocks the deref preprocessing path
    - Graceful shutdown on process exit
    """

    _instance = None
    _lock = threading.Lock()

    # Batch settings
    BATCH_SIZE = 100  # Flush after this many entries (derefs can be frequent)
    FLUSH_INTERVAL = 3.0  # Flush every N seconds regardless of batch size

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, host: str | None = None, port: int | None = None, database: str | None = None,
                 user: str | None = None, password: str | None = None):
        """Initialize the deref logger (singleton - only runs once)."""
        if self._initialized:
            return

        self._queue = queue.Queue()
        self._client = None
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._shutdown = False
        self._enabled = True  # Can be disabled if table creation fails

        # Start background flush thread
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

        # Register shutdown handler
        atexit.register(self._shutdown_handler)

        self._initialized = True

    def _get_client(self):
        """Get the main DB adapter for logging (works for ClickHouse server and CHDB)."""
        if self._client is not None:
            return self._client

        try:
            db = get_db_adapter()
            self._client = db
            return self._client
        except Exception as e:
            print(f"[DerefLogger] Failed to get DB adapter: {e}")
            self._enabled = False
            return None

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
        """
        Log a deref operation asynchronously (fire-and-forget).

        Args:
            deref_expression: The full deref expression (e.g., '@param_get("region", "ALL")')
            cascade_name: The cascade name (e.g., 'param_get')
            args: Parsed arguments list
            accessor_chain: Accessor suffix if any (e.g., '[0].field')
            resolved_value: The SQL-escaped value that was injected
            resolved_value_type: Type of the resolved value
            session_id: Session identifier
            protocol: 'pgwire' or 'http'
            database_name: Database being queried
            user_name: User name from connection
            application_name: Client application name
            client_address: Client IP:port
            caller_id: Pipeline caller ID if available
            cache_hit: Whether this was served from cache
            duration_ms: Resolution time in milliseconds
            error_message: Error message if resolution failed
        """
        if not self._enabled or self._shutdown:
            return

        try:
            # Convert args to JSON
            args_json = json.dumps(args, default=str, ensure_ascii=False)

            entry = {
                'deref_expression': deref_expression[:1000],  # Truncate very long expressions
                'cascade_name': cascade_name,
                'args_json': args_json,
                'accessor_chain': accessor_chain or '',
                'resolved_value': resolved_value[:5000] if resolved_value else '',  # Truncate large values
                'resolved_value_type': resolved_value_type,
                'cache_hit': cache_hit,
                'duration_ms': duration_ms,
                'error_message': error_message[:500] if error_message else '',
                'session_id': session_id,
                'protocol': protocol,
                'database_name': database_name,
                'user_name': user_name,
                'application_name': application_name,
                'client_address': client_address,
                'caller_id': caller_id,
            }

            # Non-blocking put
            self._queue.put_nowait(entry)
        except queue.Full:
            pass  # Drop entry if queue is full - never block
        except Exception:
            pass  # Silently ignore any logging errors

    def _flush_loop(self):
        """Background thread that flushes batched entries to ClickHouse."""
        batch = []
        last_flush = time.time()

        while not self._shutdown:
            try:
                # Try to get an entry with timeout
                try:
                    entry = self._queue.get(timeout=0.5)
                    batch.append(entry)
                except queue.Empty:
                    pass

                # Flush if batch is full or interval elapsed
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
                # Never crash the flush thread
                pass

        # Final flush on shutdown
        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, batch: List[Dict]):
        """Flush a batch of entries to ClickHouse."""
        client = self._get_client()
        if client is None or not batch:
            return

        try:
            columns = [
                'deref_expression', 'cascade_name', 'args_json', 'accessor_chain',
                'resolved_value', 'resolved_value_type', 'cache_hit', 'duration_ms',
                'error_message', 'session_id', 'protocol', 'database_name',
                'user_name', 'application_name', 'client_address', 'caller_id'
            ]
            # Prefer adapter insert_rows for compatibility across backends.
            try:
                client.insert_rows("deref_log", batch, columns=columns, log_query=False)
            except TypeError:
                client.insert_rows("deref_log", batch, columns=columns)
        except Exception as e:
            # Log but don't crash
            print(f"[DerefLogger] Flush failed: {e}")

    def _shutdown_handler(self):
        """Handle graceful shutdown."""
        self._shutdown = True
        # Give the flush thread a moment to finish
        if self._flush_thread.is_alive():
            self._flush_thread.join(timeout=1.0)


# Global deref logger singleton (lazily initialized)
_deref_logger: Optional[DerefLogger] = None


def get_deref_logger() -> Optional[DerefLogger]:
    """Get the deref logger singleton (lazily initialized)."""
    global _deref_logger
    if _deref_logger is None:
        _deref_logger = DerefLogger()
    return _deref_logger


def shutdown_async_loggers() -> None:
    """
    Stop background logging threads (QueryLogger/DerefLogger) if they were created.

    Useful in CHDB mode when the current process is only doing one-off setup and
    must release the CHDB file lock before starting another process.
    """
    global _query_logger, _deref_logger

    try:
        if _query_logger is not None:
            _query_logger._shutdown_handler()
    except Exception:
        pass
    _query_logger = None

    try:
        if _deref_logger is not None:
            _deref_logger._shutdown_handler()
    except Exception:
        pass
    _deref_logger = None


class _ChdbClientWrapper:
    """
    Minimal clickhouse-driver-like client wrapper backed by CHDB.

    Implements the subset of methods used by ClickHouseAdapter:
    - execute(...)
    - query_dataframe(...)
    - disconnect()
    """

    def __init__(self, *, path: str, database: str):
        try:
            import chdb  # type: ignore
        except ImportError as e:
            raise ImportError(
                "chdb is not installed (required for LARS_DB_MODE=chdb). "
                "Install it with: pip install chdb"
            ) from e

        self._chdb = chdb
        self._path = path
        self._database = database
        try:
            self._conn = chdb.connect(path)
        except Exception as e:
            msg = str(e)
            if "Cannot lock file" in msg or "Another server instance" in msg:
                raise RuntimeError(
                    "CHDB storage is already in use by another process. "
                    "Stop the other LARS process or set LARS_CHDB_PATH to a different path."
                ) from e
            raise

        # Ensure the requested default database exists and is active.
        # Many migrations and queries rely on unqualified table names.
        try:
            self._conn.query(f"CREATE DATABASE IF NOT EXISTS {database}")
            self._conn.query(f"USE {database}")
        except Exception:
            # If database name is invalid, surface the original error.
            raise

    def disconnect(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def query_dataframe(self, sql: str, params: Dict | None = None):
        if params:
            sql = _substitute_clickhouse_percent_params(sql, params)
        return self._conn.query(sql, "dataframe")

    @staticmethod
    def _looks_like_select(sql: str) -> bool:
        # Fast heuristic: good enough for distinguishing query vs DDL/DML.
        s = sql.lstrip()
        if not s:
            return False
        upper = s[:20].upper()
        return upper.startswith(("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN"))

    def execute(
        self,
        sql: str,
        params: Dict | None = None,
        with_column_types: bool = False,
        settings: Dict | None = None,
        **kwargs,
    ):
        # CHDB doesn't accept clickhouse-driver params; substitute into SQL.
        if params:
            sql = _substitute_clickhouse_percent_params(sql, params)

        # Settings are either specified inline via SETTINGS clause or ignored here.
        _ = settings, kwargs

        # Query path (needs results).
        if with_column_types or self._looks_like_select(sql):
            fmt = "JSONCompact" if (with_column_types or self._looks_like_select(sql)) else "CSV"
            res = self._conn.query(sql, fmt)
            payload = res.bytes()
            if not payload:
                return ([], []) if with_column_types else []
            obj = json.loads(payload.decode("utf-8"))
            rows = [tuple(r) for r in obj.get("data", [])]
            if with_column_types:
                cols = [(m.get("name"), m.get("type")) for m in obj.get("meta", [])]
                return rows, cols
            return rows

        # DDL/DML path.
        self._conn.query(sql)
        return []


class ClickHouseAdapter:
    """
    ClickHouse-compatible adapter for all LARS persistence operations.

    This adapter:
    - Connects to ClickHouse server by default
    - Optionally uses CHDB (embedded ClickHouse) for local evaluation
    - Provides batch INSERT for efficient writes
    - Supports ALTER TABLE UPDATE for cost tracking and winner flagging
    - Implements native vector search with cosineDistance()
    - Auto-creates database and tables on first use
    - Thread-safe: Uses locks for concurrent access from main thread + background workers
    """

    _instance = None
    _lock = threading.Lock()
    _initialized = False
    _housekeeping_done = False  # Track if schema/migrations have been run
    _query_lock = threading.Lock()  # Serialize all queries to avoid concurrent connection issues

    def __new__(cls, *args, **kwargs):
        # Singleton pattern for connection reuse
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9000,
        database: str = "lars",
        user: str = "default",
        password: str = "",
        auto_create: bool = False,
        backend: str = "clickhouse",
        chdb_path: str | None = None,
    ):
        """
        Initialize ClickHouse adapter (singleton - only runs once).

        Args:
            host: ClickHouse server hostname
            port: Native protocol port (9000)
            database: Database name
            user: Username
            password: Password
            auto_create: If True, create database/tables/migrations on connect.
                         Default is False for fast cascade startup.
                         Use run_housekeeping() to explicitly initialize schema.
        """
        # Skip if already initialized (singleton)
        if ClickHouseAdapter._initialized:
            return

        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password

        self.backend = (backend or "clickhouse").strip().lower()
        if self.backend not in ("clickhouse", "chdb"):
            self.backend = "clickhouse"

        # ClickHouse server backend
        if self.backend == "clickhouse":
            try:
                from clickhouse_driver import Client  # type: ignore
                self._Client = Client
            except ImportError as e:
                raise ImportError(
                    "clickhouse-driver is not installed. "
                    "Install it with: pip install clickhouse-driver"
                ) from e

            # Create system client first (without database) to ensure database exists
            if auto_create:
                self._ensure_database()

            # Now connect to the database with connection pooling settings
            self.client = self._Client(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                # Connection settings for high concurrency
                connect_timeout=10,
                send_receive_timeout=30,
                sync_request_timeout=30,
                # Query settings
                settings={
                    "use_numpy": True,
                    "max_block_size": 100000,
                    "max_threads": 4,  # Limit threads per query
                    "max_execution_time": 60,  # 60s query timeout
                },
            )
            self.chdb_path = None
        else:
            # CHDB backend (embedded ClickHouse)
            if not chdb_path:
                from .config import get_config
                chdb_path = get_config().chdb_path

            self.chdb_path = chdb_path
            self._Client = None
            self.client = _ChdbClientWrapper(path=chdb_path, database=database)

        # Auto-create tables if requested
        if auto_create:
            self._ensure_tables()
            self._run_migrations()
            ClickHouseAdapter._housekeeping_done = True

        ClickHouseAdapter._initialized = True

    def run_housekeeping(self):
        """
        Run database schema and migration housekeeping.

        This is idempotent - safe to call multiple times.
        Should be called explicitly by:
        - Backend startup (app.py)
        - CLI commands that manage the database (db init, tools sync, etc.)

        NOT called by:
        - lars run (cascade execution should be fast)
        - Backend cascade API (reuses existing schema)
        """
        if ClickHouseAdapter._housekeeping_done:
            return

        with ClickHouseAdapter._lock:
            # Double-check after acquiring lock
            if ClickHouseAdapter._housekeeping_done:
                return

            self._ensure_database()
            self._ensure_tables()
            self._run_migrations()
            ClickHouseAdapter._housekeeping_done = True

    def _ensure_database(self):
        """Ensure the database exists, creating it if necessary."""
        if getattr(self, "backend", "clickhouse") == "chdb":
            # CHDB uses a local embedded ClickHouse; we can create/use databases directly.
            try:
                self.client.execute(f"CREATE DATABASE IF NOT EXISTS {self.database}")
                self.client.execute(f"USE {self.database}")
            except Exception as e:
                print(f"[LARS] Warning: Could not check/create database: {e}")
            return

        system_client = self._Client(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password
        )

        try:
            result = system_client.execute(
                f"SELECT 1 FROM system.databases WHERE name = '{self.database}'"
            )
            if not result:
                print(f"[LARS] Creating database '{self.database}'...")
                system_client.execute(f"CREATE DATABASE IF NOT EXISTS {self.database}")
                print(f"[LARS] Database '{self.database}' created")
        except Exception as e:
            print(f"[LARS] Warning: Could not check/create database: {e}")

    def _ensure_tables(self):
        """
        Legacy method - now a no-op since migrations handle table creation.

        Tables are created by numbered migrations in lars/migrations/sql/.
        This method is kept for backwards compatibility but does nothing.
        """
        # Tables are now created by migrations - see _run_migrations()
        pass

    def _run_migrations(self):
        """
        Run all pending migrations using the Rails-style migrations system.

        Migrations are numbered SQL files in lars/migrations/sql/ that are
        tracked in the schema_migrations table. Each migration runs exactly once.

        Features:
        - Version tracking in schema_migrations table
        - Checksum verification for change detection
        - Idempotent execution (each migration runs once)
        - Support for always_run maintenance tasks
        """
        try:
            from .migrations import MigrationRunner

            runner = MigrationRunner(db_adapter=self)
            successful, failed = runner.run_all(dry_run=False, stop_on_error=True)

            if failed > 0:
                print(f"[LARS] Warning: {failed} migration(s) failed")
            elif successful > 0:
                print(f"[LARS] {successful} migration(s) applied successfully")

        except ImportError as e:
            print(f"[LARS] Warning: Could not load migrations module: {e}")
        except Exception as e:
            print(f"[LARS] Warning: Migration error: {e}")

    # =========================================================================
    # Query Operations
    # =========================================================================

    def query(self, sql: str, params: Dict | None = None, output_format: str = "dict", log_query: bool = True) -> Any:
        """
        Execute a SELECT query and return results.

        Args:
            sql: SQL query string
            params: Optional query parameters (for parameterized queries)
            output_format: "dict" (list of dicts), "dataframe", or "raw" (tuples)

        Returns:
            Query results in requested format
        """
        start_time = time.time()
        rows_returned = 0
        success = True
        error_msg = None

        with ClickHouseAdapter._query_lock:
            try:
                if output_format == "dataframe":
                    result = self.client.query_dataframe(sql, params or {})
                    rows_returned = len(result) if result is not None else 0
                    return result
                elif output_format == "dict":
                    # Disable numpy for dict output to get native Python types
                    result = self.client.execute(sql, params or {}, with_column_types=True, settings={'use_numpy': False})
                    rows, columns = result
                    col_names = [c[0] for c in columns]
                    dict_result = [dict(zip(col_names, row)) for row in rows]
                    rows_returned = len(dict_result)
                    return dict_result
                else:  # raw
                    result = self.client.execute(sql, params or {})
                    rows_returned = len(result) if isinstance(result, (list, tuple)) else 0
                    return result
            except Exception as e:
                success = False
                error_msg = str(e)
                # Check if this is a missing table error
                is_missing, table_name = _is_missing_table_error(e)
                if is_missing:
                    raise SchemaNotInitializedError(e, table_name) from e
                print(f"[ClickHouse Error] Query failed: {e}")
                print(f"[ClickHouse Error] SQL: {sql[:500]}...")
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                logger = get_query_logger()
                if log_query and logger:
                    logger.log_query(
                        query_type='query',
                        sql_preview=sql,
                        duration_ms=duration_ms,
                        rows_returned=rows_returned,
                        success=success,
                        error_message=error_msg
                    )

    def query_df(self, sql: str, params: Dict | None = None) -> pd.DataFrame:
        """
        Execute query and return pandas DataFrame.

        Convenience wrapper for query(..., output_format="dataframe").
        """
        return self.query(sql, params, output_format="dataframe")

    def execute(self, sql: str, params: Dict | None = None, log_query: bool = True):
        """
        Execute a non-SELECT statement (CREATE, INSERT, ALTER, etc.).

        Args:
            sql: SQL statement
            params: Optional parameters
        """
        start_time = time.time()
        success = True
        error_msg = None

        with ClickHouseAdapter._query_lock:
            try:
                # Pass None when no params to avoid ClickHouse client scanning SQL for format strings
                self.client.execute(sql, params if params else None)
            except Exception as e:
                success = False
                error_msg = str(e)
                # Check if this is a missing table error
                is_missing, table_name = _is_missing_table_error(e)
                if is_missing:
                    raise SchemaNotInitializedError(e, table_name) from e
                print(f"[ClickHouse Error] Execute failed: {e}")
                print(f"[ClickHouse Error] SQL: {sql[:500]}...")
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                logger = get_query_logger()
                if log_query and logger:
                    logger.log_query(
                        query_type='execute',
                        sql_preview=sql,
                        duration_ms=duration_ms,
                        success=success,
                        error_message=error_msg
                    )

    # =========================================================================
    # Insert Operations
    # =========================================================================

    def insert_rows(self, table: str, rows: List[Dict], columns: List[str] | None = None, log_query: bool = True):
        """
        Batch INSERT rows into a table.

        Args:
            table: Table name
            rows: List of dicts to insert
            columns: Optional column list (defaults to keys of first row)
        """
        if not rows:
            return

        # Skip logging for ui_sql_log to avoid infinite recursion
        should_log = log_query and table != 'ui_sql_log'
        start_time = time.time() if should_log else 0
        success = True
        error_msg = None
        row_count = len(rows)

        if columns is None:
            columns = list(rows[0].keys())

        def convert_value(val, col):
            """Convert value to ClickHouse-compatible type."""
            # Handle None
            if val is None:
                # For non-nullable String columns, convert None to empty string
                # ClickHouse's clickhouse-driver can't serialize None for String type
                if col in ('session_id', 'trace_id', 'timestamp_iso'):
                    return ''
                return val

            # Handle numpy types (convert to Python native)
            # NumPy 2.0 removed np.float_, np.int_, np.bool_ etc. - use abstract types
            try:
                import numpy as np
                # Check if it's any numpy integer type (np.integer covers all int types)
                if isinstance(val, np.integer):
                    return int(val)
                # Check if it's any numpy floating type (np.floating covers all float types)
                if isinstance(val, np.floating):
                    return float(val)
                # Check if it's numpy boolean (check module to distinguish from Python bool)
                # In NumPy 2.0, np.bool_ is removed - check via module name instead
                if type(val).__module__ == 'numpy' and type(val).__name__ in ('bool_', 'bool'):
                    return bool(val)
                # Check if it's numpy array
                if isinstance(val, np.ndarray):
                    return val.tolist()
                # Check if it's numpy string (check dtype kind for string types)
                if hasattr(val, 'dtype') and val.dtype.kind in ('U', 'S'):
                    return str(val)
            except (ImportError, AttributeError, TypeError):
                pass

            # Handle JSON columns
            if isinstance(val, (list, dict)) and col.endswith('_json'):
                if not isinstance(val, str):
                    return json.dumps(val, default=str, ensure_ascii=False)

            # Handle array columns (context_hashes, etc.)
            if isinstance(val, list):
                return [str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v for v in val]

            return val

        cols_str = ', '.join(columns)
        with ClickHouseAdapter._query_lock:
            try:
                if getattr(self, "backend", "clickhouse") == "chdb":
                    # CHDB: use JSONEachRow for inserts (no Python-side value binding).
                    def _split_qualified_table_name(full_name: str) -> tuple[str, str]:
                        name = (full_name or "").strip()
                        if not name:
                            return self.database, name
                        # Common form: db.table
                        if "." in name and not name.startswith(".") and not name.endswith("."):
                            parts = name.split(".", 1)
                            if len(parts) == 2:
                                return parts[0], parts[1]
                        return self.database, name

                    def _get_column_types_map() -> dict[str, str]:
                        cache = getattr(self, "_chdb_table_column_types_cache", None)
                        if cache is None:
                            cache = {}
                            setattr(self, "_chdb_table_column_types_cache", cache)

                        db_name, table_name = _split_qualified_table_name(table)
                        cache_key = f"{db_name}.{table_name}"
                        cached = cache.get(cache_key)
                        if isinstance(cached, dict) and cached:
                            return cached

                        # Best-effort lookup; if it fails, default to conservative formatting.
                        try:
                            safe_db = db_name.replace("\\", "\\\\").replace("'", "''")
                            safe_table = table_name.replace("\\", "\\\\").replace("'", "''")
                            result = self.client.execute(
                                f"SELECT name, type FROM system.columns "
                                f"WHERE database = '{safe_db}' AND table = '{safe_table}'",
                                with_column_types=True,
                            )
                            if isinstance(result, tuple) and len(result) == 2:
                                type_rows, _ = result
                            else:
                                type_rows = result
                            mapping = {str(r[0]): str(r[1]) for r in (type_rows or []) if len(r) >= 2}
                            if mapping:
                                cache[cache_key] = mapping
                                return mapping
                        except Exception:
                            pass
                        return {}

                    col_types_map = _get_column_types_map()

                    def _json_safe_value(v: Any, col_type: str | None):
                        if v is None:
                            return None
                        if isinstance(v, (str, int, float, bool)):
                            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                                return None
                            if isinstance(v, str) and col_type and "DateTime" in col_type and "DateTime64" not in col_type:
                                # JSONEachRow is strict for DateTime (no fractional seconds).
                                s = v.replace("T", " ", 1)
                                if "." in s:
                                    s = s.split(".", 1)[0]
                                return s
                            return v
                        if isinstance(v, (bytes, bytearray, memoryview)):
                            return bytes(v).hex()
                        if isinstance(v, datetime):
                            # JSONEachRow is strict for DateTime (no fractional seconds). DateTime64 accepts both.
                            if col_type and "DateTime64" in col_type:
                                return _format_datetime_for_clickhouse(v)
                            return v.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
                        if hasattr(v, "to_pydatetime"):
                            try:
                                dt = v.to_pydatetime()
                                if col_type and "DateTime64" in col_type:
                                    return _format_datetime_for_clickhouse(dt)
                                return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                pass
                        if hasattr(v, "isoformat"):
                            try:
                                return v.isoformat()
                            except Exception:
                                pass
                        if isinstance(v, (list, tuple)):
                            return [_json_safe_value(x, None) for x in v]
                        if isinstance(v, dict):
                            return {k: _json_safe_value(val, None) for k, val in v.items()}
                        return str(v)

                    json_lines: list[str] = []
                    for row in rows:
                        payload_row = {}
                        for col in columns:
                            val = convert_value(row.get(col), col)
                            payload_row[col] = _json_safe_value(val, col_types_map.get(col))
                        json_lines.append(json.dumps(payload_row, default=str, ensure_ascii=False))

                    insert_sql = f"INSERT INTO {table} ({cols_str}) FORMAT JSONEachRow\n" + "\n".join(json_lines)
                    self.client.execute(insert_sql)
                else:
                    # ClickHouse server: clickhouse-driver can bind values efficiently.
                    values = []
                    for row in rows:
                        row_values = []
                        for col in columns:
                            val = convert_value(row.get(col), col)
                            row_values.append(val)
                        values.append(tuple(row_values))

                    # Disable numpy processing in clickhouse_driver
                    self.client.execute(
                        f"INSERT INTO {table} ({cols_str}) VALUES",
                        values,
                        settings={'use_numpy': False}
                    )
            except Exception as e:
                success = False
                error_msg = str(e)
                # Check if this is a missing table error
                is_missing, table_name = _is_missing_table_error(e)
                if is_missing:
                    raise SchemaNotInitializedError(e, table_name or table) from e
                print(f"[ClickHouse Error] Insert failed: {e}")
                print(f"[ClickHouse Error] Table: {table}, Columns: {columns}")
                raise
            finally:
                if should_log:
                    duration_ms = (time.time() - start_time) * 1000
                    logger = get_query_logger()
                    if logger:
                        logger.log_query(
                            query_type='insert_rows',
                            sql_preview=f"INSERT INTO {table} ({row_count} rows)",
                            duration_ms=duration_ms,
                            rows_affected=row_count,
                            success=success,
                            error_message=error_msg
                        )

    def insert_dataframe(self, table: str, df: pd.DataFrame, columns: List[str] | None = None, log_query: bool = True):
        """
        Insert a pandas DataFrame into a table.

        Args:
            table: Table name
            df: DataFrame to insert
            columns: Optional column subset
        """
        if df.empty:
            return

        start_time = time.time()
        success = True
        error_msg = None
        row_count = len(df)

        if columns is None:
            columns = list(df.columns)

        cols_str = ', '.join(columns)
        with ClickHouseAdapter._query_lock:
            try:
                if getattr(self, "backend", "clickhouse") == "chdb":
                    # CHDB: serialize dataframe rows via JSONEachRow.
                    def _split_qualified_table_name(full_name: str) -> tuple[str, str]:
                        name = (full_name or "").strip()
                        if not name:
                            return self.database, name
                        # Common form: db.table
                        if "." in name and not name.startswith(".") and not name.endswith("."):
                            parts = name.split(".", 1)
                            if len(parts) == 2:
                                return parts[0], parts[1]
                        return self.database, name

                    def _get_column_types_map() -> dict[str, str]:
                        cache = getattr(self, "_chdb_table_column_types_cache", None)
                        if cache is None:
                            cache = {}
                            setattr(self, "_chdb_table_column_types_cache", cache)

                        db_name, table_name = _split_qualified_table_name(table)
                        cache_key = f"{db_name}.{table_name}"
                        cached = cache.get(cache_key)
                        if isinstance(cached, dict) and cached:
                            return cached

                        # Best-effort lookup; if it fails, default to conservative formatting.
                        try:
                            safe_db = db_name.replace("\\", "\\\\").replace("'", "''")
                            safe_table = table_name.replace("\\", "\\\\").replace("'", "''")
                            result = self.client.execute(
                                f"SELECT name, type FROM system.columns "
                                f"WHERE database = '{safe_db}' AND table = '{safe_table}'",
                                with_column_types=True,
                            )
                            if isinstance(result, tuple) and len(result) == 2:
                                type_rows, _ = result
                            else:
                                type_rows = result
                            mapping = {str(r[0]): str(r[1]) for r in (type_rows or []) if len(r) >= 2}
                            if mapping:
                                cache[cache_key] = mapping
                                return mapping
                        except Exception:
                            pass
                        return {}

                    col_types_map = _get_column_types_map()

                    def _json_safe_value(v: Any, col_type: str | None):
                        if v is None:
                            return None
                        # pandas can produce numpy scalars; normalize.
                        try:
                            import numpy as np
                            if isinstance(v, np.integer):
                                v = int(v)
                            elif isinstance(v, np.floating):
                                v = float(v)
                            elif isinstance(v, np.ndarray):
                                v = v.tolist()
                        except Exception:
                            pass

                        if isinstance(v, (str, int, float, bool)):
                            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                                return None
                            if isinstance(v, str) and col_type and "DateTime" in col_type and "DateTime64" not in col_type:
                                # JSONEachRow is strict for DateTime (no fractional seconds).
                                s = v.replace("T", " ", 1)
                                if "." in s:
                                    s = s.split(".", 1)[0]
                                return s
                            return v
                        if isinstance(v, (bytes, bytearray, memoryview)):
                            return bytes(v).hex()
                        if isinstance(v, datetime):
                            # JSONEachRow is strict for DateTime (no fractional seconds). DateTime64 accepts both.
                            if col_type and "DateTime64" in col_type:
                                return _format_datetime_for_clickhouse(v)
                            return v.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
                        if hasattr(v, "to_pydatetime"):
                            try:
                                dt = v.to_pydatetime()
                                if col_type and "DateTime64" in col_type:
                                    return _format_datetime_for_clickhouse(dt)
                                return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                pass
                        if hasattr(v, "isoformat"):
                            try:
                                return v.isoformat()
                            except Exception:
                                pass
                        if isinstance(v, (list, tuple)):
                            return [_json_safe_value(x, None) for x in v]
                        if isinstance(v, dict):
                            return {k: _json_safe_value(val, None) for k, val in v.items()}
                        return str(v)

                    json_lines: list[str] = []
                    for row in df[columns].to_dict(orient="records"):
                        payload_row = {col: _json_safe_value(row.get(col), col_types_map.get(col)) for col in columns}
                        json_lines.append(json.dumps(payload_row, default=str, ensure_ascii=False))

                    insert_sql = f"INSERT INTO {table} ({cols_str}) FORMAT JSONEachRow\n" + "\n".join(json_lines)
                    self.client.execute(insert_sql)
                else:
                    # ClickHouse server: use clickhouse-driver's native DataFrame insert.
                    self.client.insert_dataframe(
                        f"INSERT INTO {table} ({cols_str}) VALUES",
                        df[columns],
                        settings={'use_numpy': True}
                    )
            except Exception as e:
                success = False
                error_msg = str(e)
                # Check if this is a missing table error
                is_missing, table_name = _is_missing_table_error(e)
                if is_missing:
                    raise SchemaNotInitializedError(e, table_name or table) from e
                print(f"[ClickHouse Error] Insert DataFrame failed: {e}")
                print(f"[ClickHouse Error] Table: {table}")
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                logger = get_query_logger()
                if log_query and logger:
                    logger.log_query(
                        query_type='insert_df',
                        sql_preview=f"INSERT INTO {table} (DataFrame {row_count} rows)",
                        duration_ms=duration_ms,
                        rows_affected=row_count,
                        success=success,
                        error_message=error_msg
                    )

    # =========================================================================
    # Update Operations (Mutations)
    # =========================================================================
    # ClickHouse supports ALTER TABLE UPDATE for in-place mutations.
    # These are efficient for our use case: one update per row, shortly after insert.

    def update_row(
        self,
        table: str,
        updates: Dict[str, Any],
        where: str,
        sync: bool = True
    ):
        """
        Update rows matching condition using ALTER TABLE UPDATE.

        Args:
            table: Table name
            updates: Dict of {column: value} to update
            where: WHERE clause (without WHERE keyword)
            sync: If True, wait for mutation to complete (mutations_sync=1)
        """
        if not updates:
            return

        start_time = time.time()
        success = True
        error_msg = None

        # Build SET clause with proper value formatting
        set_parts = []
        for col, val in updates.items():
            if val is None:
                set_parts.append(f"{col} = NULL")
            elif isinstance(val, bool):
                set_parts.append(f"{col} = {str(val).lower()}")
            elif isinstance(val, (int, float)):
                set_parts.append(f"{col} = {val}")
            elif isinstance(val, str):
                # Escape backslashes first, then single quotes
                # ClickHouse requires backslashes to be escaped in string literals
                escaped = val.replace("\\", "\\\\").replace("'", "''")
                set_parts.append(f"{col} = '{escaped}'")
            elif isinstance(val, list):
                # Check if it's a numeric array (for embeddings)
                if val and all(isinstance(x, (int, float)) for x in val):
                    # Format as ClickHouse array literal: [1.0, 2.0, 3.0]
                    array_str = '[' + ', '.join(str(x) for x in val) + ']'
                    set_parts.append(f"{col} = {array_str}")
                else:
                    # Non-numeric array - store as JSON string
                    # json.dumps produces backslashes (e.g., \n) that need escaping for ClickHouse
                    # Escape backslashes FIRST, then single quotes
                    json_str = json.dumps(val, default=str, ensure_ascii=False).replace("\\", "\\\\").replace("'", "''")
                    set_parts.append(f"{col} = '{json_str}'")
            elif isinstance(val, dict):
                # json.dumps produces backslashes (e.g., \n) that need escaping for ClickHouse
                # Escape backslashes FIRST, then single quotes
                json_str = json.dumps(val, default=str, ensure_ascii=False).replace("\\", "\\\\").replace("'", "''")
                set_parts.append(f"{col} = '{json_str}'")
            else:
                # Fallback for other types
                escaped = str(val).replace("\\", "\\\\").replace("'", "''")
                set_parts.append(f"{col} = '{escaped}'")

        set_clause = ', '.join(set_parts)
        settings = "SETTINGS mutations_sync = 1" if sync else ""

        sql = f"""
            ALTER TABLE {table}
            UPDATE {set_clause}
            WHERE {where}
            {settings}
        """
        with ClickHouseAdapter._query_lock:
            try:
                self.client.execute(sql)
            except Exception as e:
                success = False
                error_msg = str(e)
                # Check if this is a missing table error
                is_missing, table_name = _is_missing_table_error(e)
                if is_missing:
                    raise SchemaNotInitializedError(e, table_name or table) from e
                print(f"[ClickHouse Error] Update failed: {e}")
                print(f"[ClickHouse Error] SQL: {sql[:500]}...")
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                logger = get_query_logger()
                if logger:
                    logger.log_query(
                        query_type='update',
                        sql_preview=f"ALTER TABLE {table} UPDATE ... WHERE {where[:100]}",
                        duration_ms=duration_ms,
                        success=success,
                        error_message=error_msg
                    )

    def batch_update_costs(self, table: str, updates: List[Dict]):
        """
        Batch update cost data for multiple rows by trace_id.

        This is more efficient than individual updates - ClickHouse processes
        as a single mutation operation.

        IMPORTANT: Only updates rows with role='assistant' to avoid propagating
        cost data to system/cell_start rows that share the same trace_id.
        This prevents double/triple counting of costs in aggregate queries.

        Args:
            updates: List of dicts with keys: trace_id, cost, tokens_in, tokens_out, provider, model
        """
        if not updates:
            return

        # Build individual UPDATE statements for each trace_id
        # ClickHouse doesn't have CASE/WHEN in UPDATE, so we batch by grouping
        for update in updates:
            trace_id = update.get('trace_id')
            if not trace_id:
                continue

            update_data = {}
            if 'cost' in update and update['cost'] is not None:
                update_data['cost'] = update['cost']
            if 'tokens_in' in update and update['tokens_in'] is not None:
                update_data['tokens_in'] = update['tokens_in']
            if 'tokens_out' in update and update['tokens_out'] is not None:
                update_data['tokens_out'] = update['tokens_out']
            if 'tokens_reasoning' in update and update['tokens_reasoning'] is not None:
                update_data['tokens_reasoning'] = update['tokens_reasoning']
            if 'provider' in update and update['provider']:
                update_data['provider'] = update['provider']
            if 'model' in update and update['model']:
                update_data['model'] = update['model']

            # Calculate total_tokens (only if we have at least one token count)
            tokens_in_val = update_data.get('tokens_in', 0) or 0
            tokens_out_val = update_data.get('tokens_out', 0) or 0
            if 'tokens_in' in update_data or 'tokens_out' in update_data:
                update_data['total_tokens'] = tokens_in_val + tokens_out_val

            if update_data:
                # Only update the assistant row - system/cell_start rows share trace_id
                # but shouldn't have cost data (prevents double-counting in SUM queries)
                self.update_row(
                    table,
                    update_data,
                    f"trace_id = '{trace_id}' AND role = 'assistant'",
                    sync=False  # Don't wait for each individual update
                )

    def mark_take_winner(
        self,
        table: str,
        session_id: str,
        cell_name: str,
        winning_index: int
    ):
        """
        Mark all rows in a take as winner/loser.

        Updates is_winner for all rows matching the session/cell/take.

        Args:
            table: Table name (usually unified_logs)
            session_id: Session ID
            cell_name: Cell name
            winning_index: The winning take index
        """
        # Mark winner
        self.update_row(
            table,
            {'is_winner': True},
            f"session_id = '{session_id}' AND cell_name = '{cell_name}' AND take_index = {winning_index}",
            sync=True
        )

        # Mark losers (all other take indexes in same cell)
        start_time = time.time()
        success = True
        error_msg = None

        sql = f"""
            ALTER TABLE {table}
            UPDATE is_winner = false
            WHERE session_id = '{session_id}'
              AND cell_name = '{cell_name}'
              AND take_index IS NOT NULL
              AND take_index != {winning_index}
            SETTINGS mutations_sync = 1
        """
        with ClickHouseAdapter._query_lock:
            try:
                self.client.execute(sql)
            except Exception as e:
                success = False
                error_msg = str(e)
                print(f"[ClickHouse Error] Mark losers failed: {e}")
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                logger = get_query_logger()
                if logger:
                    logger.log_query(
                        query_type='update',
                        sql_preview=f"ALTER TABLE {table} UPDATE is_winner=false (mark losers)",
                        duration_ms=duration_ms,
                        success=success,
                        error_message=error_msg
                    )

    # =========================================================================
    # Vector Search Operations
    # =========================================================================

    def vector_search(
        self,
        table: str,
        embedding_col: str,
        query_vector: List[float],
        limit: int = 10,
        where: str | None = None,
        select_cols: str = "*"
    ) -> List[Dict]:
        """
        Semantic search using ClickHouse's cosineDistance function.

        Args:
            table: Table name
            embedding_col: Column containing embeddings (Array(Float32))
            query_vector: Query embedding vector
            limit: Max results to return
            where: Optional WHERE clause filter
            select_cols: Columns to select (default: *)

        Returns:
            List of dicts with results, sorted by similarity (ascending distance)
        """
        where_clause = f"WHERE {where}" if where else ""

        # Convert query vector to ClickHouse array format
        vec_str = f"[{','.join(str(v) for v in query_vector)}]"

        sql = f"""
            SELECT {select_cols},
                   cosineDistance({embedding_col}, {vec_str}) AS distance,
                   1 - cosineDistance({embedding_col}, {vec_str}) AS similarity
            FROM {table}
            {where_clause}
            ORDER BY distance ASC
            LIMIT {limit}
        """
        return self.query(sql, output_format="dict")

    # =========================================================================
    # Context Cards Operations
    # =========================================================================

    def insert_context_cards(self, rows: List[Dict]):
        """
        Insert context cards into the context_cards table.

        Args:
            rows: List of context card dictionaries with fields:
                - session_id: str
                - content_hash: str
                - summary: str
                - keywords_json: str (JSON array)
                - embedding_json: str (JSON array of floats)
                - embedding_model: str
                - embedding_dim: int
                - estimated_tokens: int
                - role: str
                - cell_name: str
                - cascade_id: str
                - turn_number: int
                - is_anchor: bool
                - is_callout: bool
                - callout_name: str
                - generator_model: str
                - message_timestamp: str (ISO format)
        """
        if not rows:
            return

        # Prepare rows for insertion
        prepared_rows = []
        for row in rows:
            prepared = {
                "session_id": row.get("session_id", ""),
                "content_hash": row.get("content_hash", ""),
                "summary": row.get("summary", ""),
                "keywords": json.loads(row.get("keywords_json", "[]")) if isinstance(row.get("keywords_json"), str) else row.get("keywords", []),
                "embedding": json.loads(row.get("embedding_json", "[]")) if isinstance(row.get("embedding_json"), str) else row.get("embedding", []),
                "embedding_model": row.get("embedding_model"),
                "embedding_dim": len(row.get("embedding", [])) if row.get("embedding") else None,
                "estimated_tokens": row.get("estimated_tokens", 0),
                "role": row.get("role", ""),
                "cell_name": row.get("cell_name"),
                "cascade_id": row.get("cascade_id"),
                "turn_number": row.get("turn_number"),
                "is_anchor": row.get("is_anchor", False),
                "is_callout": row.get("is_callout", False),
                "callout_name": row.get("callout_name"),
                "generator_model": row.get("generator_model"),
                "message_timestamp": row.get("message_timestamp"),
            }
            prepared_rows.append(prepared)

        # Use standard insert_rows
        self.insert_rows("context_cards", prepared_rows)

    def get_context_cards(
        self,
        session_id: str,
        cell_names: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get context cards for a session.

        Args:
            session_id: Session ID to query
            cell_names: Optional list of cell names to filter by
            limit: Maximum number of cards to return

        Returns:
            List of context card dictionaries
        """
        where_parts = [f"session_id = '{session_id}'"]

        if cell_names:
            cells_str = ", ".join([f"'{p}'" for p in cell_names])
            where_parts.append(f"cell_name IN ({cells_str})")

        where_clause = " AND ".join(where_parts)

        sql = f"""
            SELECT
                session_id,
                content_hash,
                summary,
                keywords,
                estimated_tokens,
                role,
                cell_name,
                turn_number,
                is_anchor,
                is_callout,
                callout_name,
                message_timestamp
            FROM context_cards
            WHERE {where_clause}
            ORDER BY message_timestamp DESC
            LIMIT {limit}
        """

        return self.query(sql, output_format="dict")

    def get_context_cards_with_embeddings(
        self,
        session_id: str,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get context cards with embeddings for semantic search.

        Args:
            session_id: Session ID to query
            limit: Maximum number of cards to return

        Returns:
            List of context card dictionaries including embeddings
        """
        sql = f"""
            SELECT
                session_id,
                content_hash,
                summary,
                keywords,
                embedding,
                estimated_tokens,
                role,
                cell_name,
                turn_number,
                is_anchor,
                is_callout,
                message_timestamp
            FROM context_cards
            WHERE session_id = '{session_id}'
                AND length(embedding) > 0
            ORDER BY message_timestamp DESC
            LIMIT {limit}
        """

        return self.query(sql, output_format="dict")

    def search_context_cards_semantic(
        self,
        session_id: str,
        query_embedding: List[float],
        limit: int = 20,
        similarity_threshold: float = 0.5
    ) -> List[Dict]:
        """
        Search context cards using semantic similarity.

        Args:
            session_id: Session ID to search within
            query_embedding: Query embedding vector
            limit: Maximum results to return
            similarity_threshold: Minimum similarity score (0-1)

        Returns:
            List of matching context cards with similarity scores
        """
        vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        sql = f"""
            SELECT
                session_id,
                content_hash,
                summary,
                keywords,
                estimated_tokens,
                role,
                cell_name,
                turn_number,
                is_anchor,
                is_callout,
                message_timestamp,
                1 - cosineDistance(embedding, {vec_str}) AS similarity
            FROM context_cards
            WHERE session_id = '{session_id}'
                AND length(embedding) > 0
            HAVING similarity >= {similarity_threshold}
            ORDER BY similarity DESC
            LIMIT {limit}
        """

        return self.query(sql, output_format="dict")

    # =========================================================================
    # Table Management
    # =========================================================================

    def ensure_table_exists(self, table_name: str, ddl: str):
        """
        Ensure a table exists, creating it if necessary.

        Args:
            table_name: Name of the table to check
            ddl: CREATE TABLE statement (should include IF NOT EXISTS)
        """
        with ClickHouseAdapter._query_lock:
            try:
                result = self.client.execute(
                    f"SELECT 1 FROM system.tables WHERE database = '{self.database}' AND name = '{table_name}'"
                )
                if not result:
                    print(f"[LARS] Creating table '{table_name}'...")
                    self.client.execute(ddl)  # Direct execute to avoid nested lock
                    print(f"[LARS] Table '{table_name}' created")
            except Exception as e:
                print(f"[LARS] Warning: Could not ensure table '{table_name}': {e}")

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        with ClickHouseAdapter._query_lock:
            result = self.client.execute(
                f"SELECT 1 FROM system.tables WHERE database = '{self.database}' AND name = '{table_name}'"
            )
            return len(result) > 0

    def get_table_row_count(self, table_name: str) -> int:
        """Get approximate row count for a table."""
        with ClickHouseAdapter._query_lock:
            result = self.client.execute(f"SELECT count() FROM {table_name}")
            return result[0][0] if result else 0


# Global adapter singleton
_adapter_singleton: Optional[ClickHouseAdapter] = None


def get_db_adapter() -> ClickHouseAdapter:
    """
    Get the ClickHouse database adapter (singleton).

    This is the main entry point for all database operations.
    Returns a singleton instance to reuse connections.

    Returns:
        ClickHouseAdapter instance
    """
    global _adapter_singleton

    if _adapter_singleton is not None:
        return _adapter_singleton

    from .config import get_config

    config = get_config()

    mode = _normalize_db_mode(getattr(config, "db_mode", "auto"))
    backend = "clickhouse"
    if mode == "chdb":
        backend = "chdb"
    elif mode == "clickhouse":
        backend = "clickhouse"
    else:
        # Auto: try ClickHouse server quickly, fall back to CHDB if unreachable.
        if not _clickhouse_server_reachable(
            host=config.clickhouse_host,
            port=config.clickhouse_port,
            database=config.clickhouse_database,
            user=config.clickhouse_user,
            password=config.clickhouse_password,
        ):
            backend = "chdb"

    _adapter_singleton = ClickHouseAdapter(
        host=config.clickhouse_host,
        port=config.clickhouse_port,
        database=config.clickhouse_database,
        user=config.clickhouse_user,
        password=config.clickhouse_password,
        backend=backend,
        chdb_path=getattr(config, "chdb_path", None),
    )

    return _adapter_singleton


def get_db() -> ClickHouseAdapter:
    """Alias for get_db_adapter() - shorter name for convenience."""
    return get_db_adapter()


def ensure_housekeeping():
    """
    Ensure database schema and migrations are up to date.

    Call this explicitly at:
    - Backend startup (before querying)
    - CLI commands that need full schema (db init, tools sync, etc.)

    This is idempotent - safe to call multiple times.
    Cascade runs (lars run) should NOT call this for fast startup.
    """
    db = get_db_adapter()
    db.run_housekeeping()


def reset_adapter():
    """Reset the adapter singleton (useful for testing)."""
    global _adapter_singleton
    _adapter_singleton = None
    ClickHouseAdapter._instance = None
    ClickHouseAdapter._initialized = False
    ClickHouseAdapter._housekeeping_done = False
