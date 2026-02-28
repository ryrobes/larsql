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
import logging
import os
import threading
import time
import contextvars
import atexit
import uuid
import copy
import random
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd

from .lars_db import LarsDB, get_lars_db, SYSTEM_TABLES


log = logging.getLogger(__name__)


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


def _env_float(name: str, default: float) -> float:
    """Parse float env values with fallback."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _env_csv(name: str) -> List[str]:
    """Parse comma-separated env list values."""
    raw = os.environ.get(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


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
            get_db_adapter().insert_rows("ui_sql_log", batch, log_query=False)
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
            get_db_adapter().insert_rows("deref_log", batch, log_query=False)
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
    _SHADOW_UI_READS_ENABLED = True
    _SHADOW_UI_QUERY_SOURCE = "ui_backend"
    _SHADOW_UI_MAX_STALE_SECONDS = 5.0
    _CH_READ_ALL_TOKENS = {"*", "all"}
    _CH_READ_TABLE_ALIASES = {
        "lars_system.logs": "unified_logs",
        "lars_system.logs_raw": "unified_logs_base",
        "lars_system.sessions": "session_state",
    }
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

    @staticmethod
    def _canonicalize_ch_read_table_name(table_name: str) -> str:
        token = (table_name or "").strip().strip("`\"").lower()
        return DuckDBAdapter._CH_READ_TABLE_ALIASES.get(token, token)

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
            self._shadow_ui_reads_enabled = (
                bool(DuckDBAdapter._SHADOW_UI_READS_ENABLED)
                and _env_enabled("LARS_SHADOW_UI_READS_ENABLED", "1")
            )
            self._shadow_ui_query_source = (
                os.environ.get("LARS_SHADOW_UI_QUERY_SOURCE", DuckDBAdapter._SHADOW_UI_QUERY_SOURCE).strip()
                or DuckDBAdapter._SHADOW_UI_QUERY_SOURCE
            )
            self._shadow_ui_max_stale_seconds = max(
                0.1,
                _env_float(
                    "LARS_SHADOW_UI_MAX_STALE_SECONDS",
                    float(DuckDBAdapter._SHADOW_UI_MAX_STALE_SECONDS),
                ),
            )
            self._shadow_store = None
            self._shadow_store_init_attempted = False
            self._read_cache_enabled = bool(DuckDBAdapter._READ_CACHE_CONFIG.get("enabled", True))
            self._read_cache_ttl_s = float(DuckDBAdapter._READ_CACHE_CONFIG.get("ttl_seconds", 0.75))
            self._read_cache_max_entries = int(DuckDBAdapter._READ_CACHE_CONFIG.get("max_entries", 512))
            self._read_cache_max_rows = int(DuckDBAdapter._READ_CACHE_CONFIG.get("max_rows", 2000))
            self._read_cache_lock = threading.Lock()
            self._read_cache: Dict[str, tuple[float, Any]] = {}
            self._ch_shadow_writer = None
            self._ch_shadow_writer_init_attempted = False
            self._shadow_parity_enabled = _env_enabled(
                "LARS_CH_SHADOW_PARITY_CHECK_ENABLED", "1"
            )
            self._shadow_parity_interval_s = max(
                10.0, _env_float("LARS_CH_SHADOW_PARITY_CHECK_INTERVAL_SECONDS", 60.0)
            )
            self._shadow_parity_stop = threading.Event()
            self._shadow_parity_thread = None
            self._shadow_parity_baseline: Dict[str, Dict[str, Optional[int]]] = {}
            # Optional ClickHouse read router (default off). This preserves
            # DuckDB/parquet as the baseline behavior unless explicitly enabled.
            self._ch_read_enabled = _env_enabled("LARS_CH_READ_ENABLED", "0")
            ch_read_sources = _env_csv("LARS_CH_READ_QUERY_SOURCES")
            if not ch_read_sources:
                ch_read_sources = ["ui_backend"]
            self._ch_read_query_sources = {s.strip().lower() for s in ch_read_sources if s.strip()}
            ch_read_tables = _env_csv("LARS_CH_READ_TABLES")
            lowered_tables = [t.strip().lower() for t in ch_read_tables]
            self._ch_read_all_tables = any(token in DuckDBAdapter._CH_READ_ALL_TOKENS for token in lowered_tables)
            self._ch_read_tables = set()
            for token in lowered_tables:
                if token in DuckDBAdapter._CH_READ_ALL_TOKENS:
                    continue
                canonical = DuckDBAdapter._canonicalize_ch_read_table_name(token)
                if canonical:
                    self._ch_read_tables.add(canonical)
            self._ch_read_fallback_to_duck = _env_enabled("LARS_CH_READ_FALLBACK_TO_DUCK", "1")
            if self._ch_read_enabled and not self._ch_read_fallback_to_duck:
                # Strict CH mode should avoid shadow Duck reads to prevent split-brain
                # between CH snapshots and shadow/parquet snapshots.
                self._shadow_ui_reads_enabled = False
            try:
                retry_attempts = int(os.environ.get("LARS_CH_READ_RETRY_ATTEMPTS", "0"))
            except Exception:
                retry_attempts = 0
            self._ch_read_retry_attempts = max(0, retry_attempts)
            self._ch_read_retry_sleep_s = max(
                0.0, _env_float("LARS_CH_READ_RETRY_SLEEP_SECONDS", 0.05)
            )
            self._ch_read_retry_on_empty = _env_enabled("LARS_CH_READ_RETRY_ON_EMPTY", "0")
            self._ch_read_compare_enabled = _env_enabled("LARS_CH_READ_COMPARE_ENABLED", "0")
            self._ch_read_compare_sample_pct = min(
                1.0,
                max(0.0, _env_float("LARS_CH_READ_COMPARE_SAMPLE_PCT", 0.01)),
            )
            try:
                compare_max_rows = int(os.environ.get("LARS_CH_READ_COMPARE_MAX_ROWS", "50"))
            except Exception:
                compare_max_rows = 50
            self._ch_read_compare_max_rows = max(1, compare_max_rows)
            self._ch_read_client = None
            self._ch_read_client_lock = threading.Lock()
            self._ch_read_client_retry_after_ts = 0.0
            self._ch_read_last_fail_log_ts = 0.0
            self._duck_primary_write_enabled = _env_enabled(
                "LARS_DUCK_PRIMARY_WRITE_ENABLED", "1"
            )
            self._duck_primary_write_disabled_tables = set(
                _env_csv("LARS_DUCK_PRIMARY_WRITE_DISABLED_TABLES")
            )
            self._duck_primary_skip_log_tables: set[str] = set()
            DuckDBAdapter._initialized = True

    def _should_write_duck_primary(self, table: str) -> bool:
        """Return True when parquet remains the primary sink for this table."""
        if not self._duck_primary_write_enabled:
            return False
        return table not in self._duck_primary_write_disabled_tables

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

    def _get_shadow_store(self):
        """Lazy-load shadow read store integration (Studio backend only)."""
        if self._shadow_store is not None:
            return self._shadow_store
        if self._shadow_store_init_attempted:
            return None

        self._shadow_store_init_attempted = True
        try:
            from lars.studio.backend.shadow_read_store import get_shadow_read_store

            self._shadow_store = get_shadow_read_store()
            return self._shadow_store
        except Exception:
            self._shadow_store = None
            return None

    def _get_clickhouse_shadow_writer(self):
        """Lazy-load optional ClickHouse shadow writer."""
        if self._ch_shadow_writer is not None:
            return self._ch_shadow_writer
        if self._ch_shadow_writer_init_attempted:
            return None

        self._ch_shadow_writer_init_attempted = True
        try:
            from .clickhouse_shadow_writer import ClickHouseShadowWriter

            writer = ClickHouseShadowWriter()
            if writer.enabled:
                self._ch_shadow_writer = writer
            return self._ch_shadow_writer
        except Exception as e:
            log.warning("[CH Shadow] initialization failed: %s", e)
            self._ch_shadow_writer = None
            return None

    def _shadow_write_rows(self, table: str, rows: List[Dict]) -> None:
        writer = self._get_clickhouse_shadow_writer()
        if writer is None:
            return
        try:
            self._start_shadow_parity_monitor_if_needed(writer)
            writer.enqueue(table, rows)
        except Exception:
            # Primary persistence is DuckDB; shadow write must never block/raise.
            pass

    def _start_shadow_parity_monitor_if_needed(self, writer) -> None:
        """
        Start periodic parity checks once shadow writing is active.

        Uses delta-since-start counts so historical data mismatches do not
        create noise during cutover.
        """
        if not self._shadow_parity_enabled or writer is None:
            return
        if self._shadow_parity_thread is not None and self._shadow_parity_thread.is_alive():
            return

        tables = sorted(writer.tables)
        if not tables:
            return

        baseline: Dict[str, Dict[str, Optional[int]]] = {}
        for table in tables:
            baseline[table] = {
                "duck": self.get_table_row_count(table),
                "ch": writer.get_table_count(table),
            }
        self._shadow_parity_baseline = baseline

        self._shadow_parity_stop.clear()

        def _loop():
            tick = 0
            while not self._shadow_parity_stop.wait(self._shadow_parity_interval_s):
                tick += 1
                try:
                    writer.flush_now()
                    mismatches: List[str] = []
                    ok_parts: List[str] = []
                    for table in tables:
                        base = self._shadow_parity_baseline.get(table, {})
                        base_duck = base.get("duck")
                        base_ch = base.get("ch")

                        duck_now = self.get_table_row_count(table)
                        ch_now = writer.get_table_count(table)
                        if base_ch is None and ch_now is not None:
                            # First successful CH observation becomes baseline.
                            base_ch = ch_now
                            base["ch"] = base_ch

                        duck_delta = None if base_duck is None else (duck_now - base_duck)
                        ch_delta = (
                            None
                            if base_ch is None or ch_now is None
                            else (ch_now - base_ch)
                        )
                        parity_delta = (
                            None
                            if duck_delta is None or ch_delta is None
                            else (duck_delta - ch_delta)
                        )

                        if parity_delta not in (None, 0):
                            mismatches.append(
                                f"{table}(duck+{duck_delta}, ch+{ch_delta}, delta={parity_delta})"
                            )
                        else:
                            if duck_delta is None or ch_delta is None:
                                ok_parts.append(f"{table}(pending)")
                            else:
                                ok_parts.append(f"{table}(+{duck_delta})")

                    if mismatches:
                        log.warning("[CH Shadow] parity mismatch: %s", ", ".join(mismatches))
                    elif tick % 10 == 0:
                        # Low-noise heartbeat every ~10 intervals.
                        log.info("[CH Shadow] parity ok: %s", ", ".join(ok_parts))
                except Exception as e:
                    log.warning("[CH Shadow] parity check failed: %s", e)

        self._shadow_parity_thread = threading.Thread(
            target=_loop,
            daemon=True,
            name="lars-ch-shadow-parity",
        )
        self._shadow_parity_thread.start()

    def shutdown_shadow_parity_monitor(self):
        """Stop periodic shadow parity monitor."""
        self._shadow_parity_stop.set()
        if self._shadow_parity_thread is not None and self._shadow_parity_thread.is_alive():
            self._shadow_parity_thread.join(timeout=2.0)

    def backfill_shadow_tables(
        self,
        tables: List[str] | None = None,
        *,
        clear_target: bool = False,
        batch_rows: int = 2000,
    ) -> Dict[str, Any]:
        """
        One-shot backfill of parquet data into shadow ClickHouse tables.

        Useful when you need full historical parity (not just post-restart).
        """
        writer = self._get_clickhouse_shadow_writer()
        if writer is None:
            return {"enabled": False, "error": "shadow writer not enabled"}

        selected_tables = tables or sorted(writer.tables)
        reports: Dict[str, Any] = {"enabled": True, "tables": {}}

        for table in selected_tables:
            table_dir = self._db.root / "system" / table
            if not table_dir.exists():
                reports["tables"][table] = {
                    "status": "skipped",
                    "error": f"table dir missing: {table_dir}",
                }
                continue

            parquet_glob = str(table_dir / "**" / "*.parquet")
            report = writer.backfill_parquet_glob(
                table=table,
                parquet_glob=parquet_glob,
                batch_rows=batch_rows,
                clear_target=clear_target,
            )
            duck_count = self.get_table_row_count(table)
            ch_count = writer.get_table_count(table)
            report["duck_count"] = duck_count
            report["clickhouse_count"] = ch_count
            report["delta"] = None if ch_count is None else (duck_count - ch_count)
            reports["tables"][table] = report

        return reports

    def get_shadow_write_stats(self) -> Dict[str, Any]:
        """Return ClickHouse shadow writer runtime stats."""
        writer = self._get_clickhouse_shadow_writer()
        if writer is None:
            return {"enabled": False}
        return writer.stats()

    def mirror_rows_to_shadow(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        *,
        clear_table: bool = False,
        flush: bool = False,
        batch_rows: int = 2000,
        normalize_rows: bool = True,
    ) -> Dict[str, Any]:
        """
        Mirror rows directly to ClickHouse shadow writer without Duck primary writes.

        Useful for write paths that do not use insert_rows() (for example,
        dedicated DuckDB index files) but still need parity data in ClickHouse.
        """
        writer = self._get_clickhouse_shadow_writer()
        report: Dict[str, Any] = {
            "enabled": False,
            "table": table,
            "rows_attempted": len(rows or []),
            "rows_enqueued": 0,
            "clear_table": bool(clear_table),
            "flushed": bool(flush),
            "error": None,
        }
        if writer is None or not getattr(writer, "enabled", False):
            return report

        report["enabled"] = True
        if not writer.allows_table(table):
            report["error"] = "table not configured for shadow writing"
            return report

        payload = rows or []
        try:
            if normalize_rows and payload:
                payload = self._db.normalize_rows_for_write(table, payload)

            if clear_table:
                writer.flush_now()
                writer.truncate_table(table)

            if payload:
                batch_size = max(1, int(batch_rows))
                for i in range(0, len(payload), batch_size):
                    batch = payload[i : i + batch_size]
                    writer.enqueue(table, batch)
                    report["rows_enqueued"] += len(batch)

            if flush:
                writer.flush_now()
        except Exception as e:
            report["error"] = str(e)
            log.warning("[CH Shadow] mirror_rows_to_shadow failed for %s: %s", table, e)

        return report

    def get_shadow_parity_counts(
        self,
        tables: List[str] | None = None,
        *,
        flush: bool = True,
    ) -> Dict[str, Dict[str, Optional[int]]]:
        """
        Return row-count parity snapshot between DuckDB and ClickHouse shadow tables.

        This is meant for migration validation, not transactional consistency.
        """
        writer = self._get_clickhouse_shadow_writer()
        if tables is not None:
            selected_tables = tables
        elif writer is not None:
            selected_tables = sorted(writer.tables)
        else:
            selected_tables = ["unified_logs_base", "costs"]
        if writer is None:
            return {
                table: {
                    "duck_count": self.get_table_row_count(table),
                    "clickhouse_count": None,
                    "delta": None,
                }
                for table in selected_tables
            }

        if flush:
            writer.flush_now()

        out: Dict[str, Dict[str, Optional[int]]] = {}
        for table in selected_tables:
            duck_count = self.get_table_row_count(table)
            ch_count = writer.get_table_count(table)
            out[table] = {
                "duck_count": duck_count,
                "clickhouse_count": ch_count,
                "delta": None if ch_count is None else (duck_count - ch_count),
            }
        return out

    def _should_try_shadow_query(self, sql: str) -> bool:
        """Return True when this query should try Studio shadow store first."""
        if not self._shadow_ui_reads_enabled:
            return False

        source = query_source_context.get()
        if source != self._shadow_ui_query_source:
            return False

        sql_lower = sql.lstrip().lower()
        return (
            sql_lower.startswith("select")
            or sql_lower.startswith("with")
            or sql_lower.startswith("describe")
            or sql_lower.startswith("show")
        )

    def _query_shadow_store(self, sql: str, output_format: str):
        """Query shadow store, returning None when unavailable or stale."""
        store = self._get_shadow_store()
        if store is None or not getattr(store, "enabled", False):
            return None

        return store.query(
            sql,
            output_format=output_format,
            max_stale_seconds=self._shadow_ui_max_stale_seconds,
        )

    def _get_clickhouse_read_client(self):
        """Lazy-load optional ClickHouse read client for env-gated read routing."""
        now = time.time()
        if now < self._ch_read_client_retry_after_ts:
            return None

        if self._ch_read_client is not None:
            return self._ch_read_client

        try:
            import clickhouse_driver
        except Exception as e:
            self._ch_read_client_retry_after_ts = time.time() + 5.0
            log.warning("[CH Read] clickhouse_driver import failed: %s", e)
            return None

        from .config import get_config

        cfg = get_config()
        host = cfg.clickhouse_host or "127.0.0.1"
        # Prefer explicit/native ports first. clickhouse_port can be HTTP.
        port_raw = (
            os.environ.get("LARS_CH_READ_NATIVE_PORT")
            or os.environ.get("LARS_CH_SHADOW_WRITE_NATIVE_PORT")
            or os.environ.get("LARS_CLICKHOUSE_NATIVE_PORT")
            or str(cfg.clickhouse_port or "9000")
        )
        try:
            port = int(port_raw)
        except Exception:
            port = 9000
        user = cfg.clickhouse_user or "default"
        password = cfg.clickhouse_password or ""
        db_name = cfg.clickhouse_database or "lars"

        try:
            client = clickhouse_driver.Client(
                host=host,
                port=port,
                user=user,
                password=password,
                database=db_name,
                connect_timeout=1.0,
                send_receive_timeout=3.0,
            )
            with self._ch_read_client_lock:
                client.execute("SELECT 1")
            self._ch_read_client = client
            return self._ch_read_client
        except Exception as e:
            self._ch_read_client_retry_after_ts = time.time() + 5.0
            log.warning("[CH Read] connect failed %s:%s: %s", host, port, e)
            self._ch_read_client = None
            return None

    def _extract_sql_tables(self, sql: str) -> set[str]:
        """
        Best-effort table extractor for FROM/JOIN clauses.
        Conservative is fine: if uncertain, routing falls back to DuckDB.
        """
        import re

        sql_no_comments = re.sub(r"--[^\n]*", " ", sql)
        sql_no_comments = re.sub(r"/\*.*?\*/", " ", sql_no_comments, flags=re.DOTALL)
        pattern = re.compile(r"\b(?:from|join)\s+([`\"\w\.\-]+)", re.IGNORECASE)

        out: set[str] = set()
        for match in pattern.finditer(sql_no_comments):
            token = (match.group(1) or "").strip().strip(",")
            if not token or token.startswith("("):
                continue
            token = DuckDBAdapter._canonicalize_ch_read_table_name(token)
            if not token:
                continue
            out.add(token)
        return out

    def _rewrite_sql_table_aliases_for_ch(self, sql: str) -> str:
        """
        Rewrite common Duck/Studio logical table names to ClickHouse physical
        shadow tables so read routing can handle `unified_logs` style queries.
        """
        import re

        if not sql:
            return sql
        if "unified_logs" not in sql.lower() and "lars_system." not in sql.lower():
            return sql

        pattern = re.compile(
            r"(?P<prefix>\b(?:from|join)\s+)(?P<table>[`\"\w\.\-]+)",
            re.IGNORECASE,
        )

        def _replace(match: re.Match[str]) -> str:
            table_token = match.group("table")
            canonical = DuckDBAdapter._canonicalize_ch_read_table_name(table_token)
            if not canonical or canonical == table_token.strip("`\"").lower():
                return match.group(0)
            return f"{match.group('prefix')}{canonical}"

        return pattern.sub(_replace, sql)

    def _translate_duck_sql_for_clickhouse(self, sql: str) -> str:
        """
        Best-effort translation for DuckDB-centric read SQL before CH execution.

        This keeps call sites Duck-friendly while strict CH read routing is enabled.
        """
        import re

        out = sql

        # FINAL is used for Duck dedup semantics; MergeTree rejects it.
        out = re.sub(r"\bFINAL\b", "", out, flags=re.IGNORECASE)

        # Duck prefix(x, y) -> CH startsWith(x, y)
        out = re.sub(r"\bprefix\s*\(", "startsWith(", out, flags=re.IGNORECASE)

        # Duck CAST(x AS VARCHAR/TEXT) can fail for Nullable values in CH.
        # Prefer toString(x), which preserves Nullable semantics safely.
        out = re.sub(
            r"\bCAST\s*\(\s*([^)]+?)\s+AS\s+(?:VARCHAR|TEXT)\s*\)",
            r"toString(\1)",
            out,
            flags=re.IGNORECASE,
        )

        # Duck epoch_ms(ts) -> CH epoch milliseconds
        def _replace_epoch_ms(match: re.Match[str]) -> str:
            arg = (match.group(1) or "").strip()
            return f"(toUnixTimestamp({arg}) * 1000)"

        out = re.sub(
            r"\bepoch_ms\s*\(\s*([^)]+?)\s*\)",
            _replace_epoch_ms,
            out,
            flags=re.IGNORECASE,
        )

        # Common Duck interval-seconds pattern: epoch(MAX(ts) - MIN(ts))
        def _replace_epoch_max_min(match: re.Match[str]) -> str:
            max_arg = (match.group(1) or "").strip()
            min_arg = (match.group(2) or "").strip()
            return f"(toUnixTimestamp(MAX({max_arg})) - toUnixTimestamp(MIN({min_arg})))"

        out = re.sub(
            r"\bepoch\s*\(\s*MAX\s*\(\s*([^)]+?)\s*\)\s*-\s*MIN\s*\(\s*([^)]+?)\s*\)\s*\)",
            _replace_epoch_max_min,
            out,
            flags=re.IGNORECASE,
        )

        # Duck epoch(ts) -> CH toUnixTimestamp(ts)
        def _replace_epoch(match: re.Match[str]) -> str:
            arg = (match.group(1) or "").strip()
            return f"toUnixTimestamp({arg})"

        out = re.sub(
            r"\bepoch\s*\(\s*([^)]+?)\s*\)",
            _replace_epoch,
            out,
            flags=re.IGNORECASE,
        )

        return out

    def _query_tables_allowed_for_ch(self, sql: str) -> bool:
        tables = self._extract_sql_tables(sql)
        if not tables:
            return False
        if self._ch_read_all_tables:
            return True
        if not self._ch_read_tables:
            return False

        for table in tables:
            short = table.split(".")[-1]
            if table in self._ch_read_tables or short in self._ch_read_tables:
                continue
            return False
        return True

    def _should_try_clickhouse_query(self, sql: str, output_format: str) -> bool:
        """Return True if this query is eligible for ClickHouse read routing."""
        if not self._ch_read_enabled:
            return False

        if output_format not in ("dict", "raw", "dataframe"):
            return False

        source = (query_source_context.get() or "").strip().lower()
        if not source:
            return False
        if (
            self._ch_read_query_sources
            and "*" not in self._ch_read_query_sources
            and source not in self._ch_read_query_sources
        ):
            return False

        sql_lower = sql.lstrip().lower()
        if not (sql_lower.startswith("select") or sql_lower.startswith("with")):
            return False

        return self._query_tables_allowed_for_ch(sql)

    def _query_clickhouse(self, sql: str, output_format: str):
        """Execute a read query against ClickHouse and normalize output shape."""
        client = self._get_clickhouse_read_client()
        if client is None:
            raise RuntimeError("clickhouse read client unavailable")

        with self._ch_read_client_lock:
            result, col_types = client.execute(sql, with_column_types=True)

        if output_format == "raw":
            return result

        columns = [c[0] for c in (col_types or [])]
        if output_format == "dict":
            return [dict(zip(columns, row)) for row in result]
        if output_format == "dataframe":
            return pd.DataFrame(result, columns=columns)
        return result

    def _query_clickhouse_with_retries(self, sql: str, output_format: str):
        """
        Execute CH read with bounded retry behavior.

        Useful during cutover where writes are eventually visible and consumers
        poll frequently. Retries can optionally trigger on empty results.
        """
        total_attempts = max(1, 1 + self._ch_read_retry_attempts)
        last_err: Exception | None = None

        for attempt_idx in range(total_attempts):
            try:
                result = self._query_clickhouse(sql, output_format)
                if (
                    self._ch_read_retry_on_empty
                    and attempt_idx < (total_attempts - 1)
                    and self._result_row_count(result, output_format) == 0
                ):
                    if self._ch_read_retry_sleep_s > 0:
                        time.sleep(self._ch_read_retry_sleep_s)
                    continue
                return result
            except Exception as e:
                last_err = e
                if attempt_idx >= (total_attempts - 1):
                    raise
                if self._ch_read_retry_sleep_s > 0:
                    time.sleep(self._ch_read_retry_sleep_s)

        # Defensive: should not happen because loop either returns or raises.
        if last_err is not None:
            raise last_err
        raise RuntimeError("clickhouse read retry loop exited unexpectedly")

    def _should_compare_clickhouse_query(self) -> bool:
        if not self._ch_read_compare_enabled:
            return False
        if self._ch_read_compare_sample_pct <= 0:
            return False
        return random.random() < self._ch_read_compare_sample_pct

    def _result_signature(self, result: Any, output_format: str) -> tuple[int, str]:
        """Create a compact signature for sampled parity checks."""
        max_rows = self._ch_read_compare_max_rows
        if output_format == "dataframe":
            row_count = int(len(result)) if result is not None else 0
            sample_rows = []
            if result is not None and row_count > 0:
                sample_rows = result.head(max_rows).to_dict(orient="records")
        elif output_format == "dict":
            row_count = int(len(result)) if result is not None else 0
            sample_rows = list(result[:max_rows]) if result else []
        else:
            row_count = int(len(result)) if isinstance(result, (list, tuple)) else 0
            if isinstance(result, (list, tuple)):
                sample_rows = [list(r) for r in result[:max_rows]]
            else:
                sample_rows = []

        encoded = json.dumps(sample_rows, default=str, sort_keys=True, ensure_ascii=False)
        digest = hashlib.md5(encoded.encode("utf-8", errors="replace")).hexdigest()
        return row_count, digest

    def _compare_clickhouse_vs_duck(
        self,
        *,
        ch_sql: str,
        duck_sql: str,
        ch_result: Any,
        output_format: str,
    ) -> None:
        """Sampled best-effort comparison for confidence during phased cutover."""
        try:
            duck_result = self._db.query(duck_sql, output_format=output_format)
            ch_rows, ch_sig = self._result_signature(ch_result, output_format)
            duck_rows, duck_sig = self._result_signature(duck_result, output_format)
            if ch_rows != duck_rows or ch_sig != duck_sig:
                log.warning(
                    "[CH Read] sampled mismatch rows(ch=%s duck=%s) sig(ch=%s duck=%s) sql=%s",
                    ch_rows,
                    duck_rows,
                    ch_sig[:8],
                    duck_sig[:8],
                    ch_sql[:240].replace("\n", " "),
                )
        except Exception as e:
            log.warning("[CH Read] sampled compare failed: %s", e)

    def _result_row_count(self, result: Any, output_format: str) -> int:
        if output_format == "dataframe":
            return len(result) if result is not None else 0
        if output_format == "dict":
            return len(result) if result is not None else 0
        return len(result) if isinstance(result, (list, tuple)) else 0

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
            ch_sql = self._rewrite_sql_table_aliases_for_ch(sql)
            ch_sql = self._translate_duck_sql_for_clickhouse(ch_sql)
            
            # Translate DuckDB-specific SQL to DuckDB
            sql = self._translate_clickhouse_sql(sql)

            if self._can_use_read_cache(sql, output_format):
                cache_key = f"{output_format}:{sql}"
                cached_result = self._read_cache_get(cache_key)
                if cached_result is not None:
                    rows_returned = self._result_row_count(cached_result, output_format)
                    return cached_result

            if self._should_try_clickhouse_query(ch_sql, output_format):
                try:
                    ch_result = self._query_clickhouse_with_retries(ch_sql, output_format)
                    if self._should_compare_clickhouse_query():
                        self._compare_clickhouse_vs_duck(
                            ch_sql=ch_sql,
                            duck_sql=sql,
                            ch_result=ch_result,
                            output_format=output_format,
                        )
                    if cache_key is not None:
                        self._read_cache_set(cache_key, ch_result)
                    rows_returned = self._result_row_count(ch_result, output_format)
                    return ch_result
                except Exception as e:
                    if not self._ch_read_fallback_to_duck:
                        raise
                    now = time.time()
                    if now - self._ch_read_last_fail_log_ts >= 5.0:
                        self._ch_read_last_fail_log_ts = now
                        log.warning("[CH Read] query failed; falling back to DuckDB: %s", e)

            if self._should_try_shadow_query(sql):
                shadow_result = self._query_shadow_store(sql, output_format)
                if shadow_result is not None:
                    if cache_key is not None:
                        self._read_cache_set(cache_key, shadow_result)
                    rows_returned = self._result_row_count(shadow_result, output_format)
                    return shadow_result

            result = self._db.query(sql, output_format=output_format)

            if cache_key is not None:
                self._read_cache_set(cache_key, result)
            
            rows_returned = self._result_row_count(result, output_format)
            
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

            rows = self._db.normalize_rows_for_write(table, rows)
            if not rows:
                return

            write_duck_primary = self._should_write_duck_primary(table)
            if write_duck_primary:
                self._db.write(table, rows, rows_already_normalized=True)
            else:
                writer = self._get_clickhouse_shadow_writer()
                shadow_accepts_table = False
                if writer is not None:
                    if hasattr(writer, "allows_table"):
                        shadow_accepts_table = bool(writer.allows_table(table))
                    else:
                        shadow_accepts_table = table in writer.tables
                if not shadow_accepts_table:
                    raise RuntimeError(
                        f"Duck primary writes are disabled for '{table}', "
                        f"but no alternate sink is configured for that table."
                    )
                if table not in self._duck_primary_skip_log_tables:
                    self._duck_primary_skip_log_tables.add(table)
                    log.warning(
                        "[Persistence] Duck primary write disabled for table=%s; relying on shadow sink",
                        table,
                    )

            self._shadow_write_rows(table, rows)
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

    def _quote_identifier(self, identifier: str) -> str:
        """Quote an identifier for SQL generation."""
        return '"' + str(identifier).replace('"', '""') + '"'

    def _sql_literal(self, value: Any) -> str:
        """Serialize Python value as a SQL literal."""
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            return f"'{value.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
        text = str(value).replace("\\", "\\\\").replace("'", "''")
        return f"'{text}'"

    def _build_delete_where_clause(
        self,
        key_columns: Sequence[str],
        key_tuples: Sequence[Tuple[Any, ...]],
    ) -> str:
        """Build SQL predicate matching one or more key tuples."""
        if not key_columns or not key_tuples:
            return "1 = 0"

        if len(key_columns) == 1:
            col_sql = self._quote_identifier(key_columns[0])
            literals = ", ".join(self._sql_literal(key_tuple[0]) for key_tuple in key_tuples)
            return f"{col_sql} IN ({literals})"

        cols_sql = ", ".join(self._quote_identifier(col) for col in key_columns)
        tuples_sql = ", ".join(
            "(" + ", ".join(self._sql_literal(v) for v in key_tuple) + ")"
            for key_tuple in key_tuples
        )
        return f"({cols_sql}) IN ({tuples_sql})"

    def delete_rows_by_keys(
        self,
        table: str,
        key_columns: Sequence[str],
        key_rows: Sequence[Dict[str, Any] | Any],
        *,
        batch_size: int = 500,
        log_query: bool = True,
    ) -> int:
        """
        Delete rows by key columns with optional ClickHouse shadow mirroring.

        This keeps turnkey DuckDB/parquet behavior as default while allowing
        strict ClickHouse modes to apply equivalent deletes when enabled.
        """
        if not key_columns or not key_rows:
            return 0

        normalized_cols = [str(col).strip() for col in key_columns if str(col).strip()]
        if not normalized_cols:
            return 0

        start_time = time.time()
        success = True
        error_msg = None
        deleted_keys = 0

        try:
            key_tuples: List[Tuple[Any, ...]] = []
            seen: set[Tuple[Any, ...]] = set()
            for row in key_rows:
                if isinstance(row, dict):
                    values: List[Any] = []
                    missing = False
                    for col in normalized_cols:
                        value = row.get(col)
                        if value is None:
                            missing = True
                            break
                        values.append(value)
                    if missing:
                        continue
                    key_tuple = tuple(values)
                elif len(normalized_cols) == 1 and row is not None:
                    key_tuple = (row,)
                else:
                    continue

                if key_tuple in seen:
                    continue
                seen.add(key_tuple)
                key_tuples.append(key_tuple)

            if not key_tuples:
                return 0

            batch_size = max(1, int(batch_size))
            write_duck_primary = self._should_write_duck_primary(table)
            writer = self._get_clickhouse_shadow_writer()
            shadow_accepts_table = False
            if writer is not None:
                if hasattr(writer, "allows_table"):
                    shadow_accepts_table = bool(writer.allows_table(table))
                else:
                    shadow_accepts_table = table in getattr(writer, "tables", set())

            if not write_duck_primary and not shadow_accepts_table:
                raise RuntimeError(
                    f"Duck primary deletes are disabled for '{table}', "
                    f"but no alternate sink is configured for that table."
                )

            if write_duck_primary:
                for i in range(0, len(key_tuples), batch_size):
                    batch = key_tuples[i : i + batch_size]
                    where_clause = self._build_delete_where_clause(normalized_cols, batch)
                    delete_sql = f"DELETE FROM {table} WHERE {where_clause}"
                    self._db.execute(delete_sql)
                    deleted_keys += len(batch)
            else:
                deleted_keys = len(key_tuples)

            if shadow_accepts_table and writer is not None and hasattr(writer, "delete_by_keys"):
                key_dict_rows = [
                    {col: value for col, value in zip(normalized_cols, key_tuple)}
                    for key_tuple in key_tuples
                ]
                writer.delete_by_keys(table, normalized_cols, key_dict_rows)
            elif not write_duck_primary and shadow_accepts_table:
                raise RuntimeError(
                    f"Shadow sink for '{table}' does not support key-based deletes."
                )

            self._invalidate_read_cache()
            return deleted_keys
        except Exception as e:
            success = False
            error_msg = str(e)
            print(f"[DuckDB Error] delete_rows_by_keys failed: {e}")
            raise
        finally:
            if log_query:
                duration_ms = (time.time() - start_time) * 1000
                logger = get_query_logger()
                if logger:
                    logger.log_query(
                        query_type='delete_rows_by_keys',
                        sql_preview=f"DELETE {table} ({deleted_keys} keys)",
                        duration_ms=duration_ms,
                        rows_affected=deleted_keys,
                        success=success,
                        error_message=error_msg
                    )

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
            # Route through insert_rows so Duck + shadow write path is identical.
            self.insert_rows('costs', cost_rows, log_query=False)

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
        
        # Route through insert_rows so sink behavior stays consistent.
        self.insert_rows('take_winners', [winner_record], log_query=False)

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
        self.insert_rows('context_cards', rows, log_query=False)

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


def get_shadow_write_stats() -> Dict[str, Any]:
    """Get ClickHouse shadow writer stats from the singleton adapter."""
    return get_db_adapter().get_shadow_write_stats()


def mirror_rows_to_shadow(
    table: str,
    rows: List[Dict[str, Any]],
    *,
    clear_table: bool = False,
    flush: bool = False,
    batch_rows: int = 2000,
    normalize_rows: bool = True,
) -> Dict[str, Any]:
    """Mirror rows directly to ClickHouse shadow tables without Duck primary writes."""
    return get_db_adapter().mirror_rows_to_shadow(
        table=table,
        rows=rows,
        clear_table=clear_table,
        flush=flush,
        batch_rows=batch_rows,
        normalize_rows=normalize_rows,
    )


def get_shadow_parity_counts(
    tables: List[str] | None = None,
    *,
    flush: bool = True,
) -> Dict[str, Dict[str, Optional[int]]]:
    """Get row-count parity snapshot for shadowed tables."""
    return get_db_adapter().get_shadow_parity_counts(tables=tables, flush=flush)


def backfill_shadow_tables(
    tables: List[str] | None = None,
    *,
    clear_target: bool = False,
    batch_rows: int = 2000,
) -> Dict[str, Any]:
    """One-shot backfill of parquet data into shadow ClickHouse tables."""
    return get_db_adapter().backfill_shadow_tables(
        tables=tables,
        clear_target=clear_target,
        batch_rows=batch_rows,
    )


def reset_adapter():
    """Reset the adapter singleton (mainly for testing)."""
    global _db_adapter
    if _db_adapter is not None:
        try:
            _db_adapter.shutdown_shadow_parity_monitor()
        except Exception:
            pass
        writer = getattr(_db_adapter, "_ch_shadow_writer", None)
        if writer is not None:
            try:
                writer.shutdown()
            except Exception:
                pass
        read_client = getattr(_db_adapter, "_ch_read_client", None)
        if read_client is not None:
            try:
                read_client.disconnect()
            except Exception:
                pass
    _db_adapter = None
    DuckDBAdapter._instance = None
    DuckDBAdapter._initialized = False
    DuckDBAdapter._housekeeping_done = False
