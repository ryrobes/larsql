"""
Database adapter layer for Windlass - Pure ClickHouse Implementation.

This module provides a single ClickHouseAdapter that handles all database operations.
No more dual-mode (chDB/ClickHouse) - we now use ClickHouse server exclusively.

Key features:
- Singleton pattern for connection reuse
- Batch INSERT for efficient writes
- ALTER TABLE UPDATE for cost tracking and winner flagging
- Native vector search with cosineDistance()
- Auto-create database and tables on startup
- Query logging to ui_sql_log table (async fire-and-forget)
"""
import json
import threading
import hashlib
import time
import queue
import contextvars
import atexit
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import pandas as pd


# =============================================================================
# Query Logging System - Async fire-and-forget logging to ClickHouse
# =============================================================================

# Context variable to track the source of queries (e.g., 'ui_backend', 'windlass_core')
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

    def __init__(self, host: str = None, port: int = None, database: str = None,
                 user: str = None, password: str = None):
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
        """Lazily create a dedicated ClickHouse client for logging."""
        if self._client is not None:
            return self._client

        if self._host is None:
            # Get config from main adapter if not provided
            try:
                from .config import get_config
                config = get_config()
                self._host = config.clickhouse_host
                self._port = config.clickhouse_port
                self._database = config.clickhouse_database
                self._user = config.clickhouse_user
                self._password = config.clickhouse_password
            except Exception:
                self._enabled = False
                return None

        try:
            from clickhouse_driver import Client
            self._client = Client(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._user,
                password=self._password,
                connect_timeout=5,
                send_receive_timeout=10,
                settings={
                    'use_numpy': False,
                    'max_execution_time': 10,
                }
            )
            # Ensure ui_sql_log table exists
            self._ensure_table()
            return self._client
        except Exception as e:
            print(f"[QueryLogger] Failed to create client: {e}")
            self._enabled = False
            return None

    def _ensure_table(self):
        """Ensure ui_sql_log table exists."""
        try:
            from .schema import UI_SQL_LOG_SCHEMA
            self._client.execute(UI_SQL_LOG_SCHEMA)
        except Exception as e:
            print(f"[QueryLogger] Failed to create ui_sql_log table: {e}")
            self._enabled = False

    def log_query(
        self,
        query_type: str,
        sql_preview: str,
        duration_ms: float,
        rows_returned: int = None,
        rows_affected: int = None,
        success: bool = True,
        error_message: str = None
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

            values = []
            for entry in batch:
                values.append(tuple(entry.get(col) for col in columns))

            cols_str = ', '.join(columns)
            client.execute(
                f"INSERT INTO ui_sql_log ({cols_str}) VALUES",
                values,
                settings={'use_numpy': False}
            )
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


class ClickHouseAdapter:
    """
    Pure ClickHouse adapter - single implementation for all database operations.

    This adapter:
    - Connects to ClickHouse server (no embedded chDB, no Parquet files)
    - Provides batch INSERT for efficient writes
    - Supports ALTER TABLE UPDATE for cost tracking and winner flagging
    - Implements native vector search with cosineDistance()
    - Auto-creates database and tables on first use
    - Thread-safe: Uses locks for concurrent access from main thread + background workers
    """

    _instance = None
    _lock = threading.Lock()
    _initialized = False
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
        database: str = "windlass",
        user: str = "default",
        password: str = "",
        auto_create: bool = True
    ):
        """
        Initialize ClickHouse adapter (singleton - only runs once).

        Args:
            host: ClickHouse server hostname
            port: Native protocol port (9000)
            database: Database name
            user: Username
            password: Password
            auto_create: Automatically create database and tables if they don't exist
        """
        # Skip if already initialized (singleton)
        if ClickHouseAdapter._initialized:
            return

        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password

        try:
            from clickhouse_driver import Client
            self._Client = Client
        except ImportError:
            raise ImportError(
                "clickhouse-driver is not installed. "
                "Install it with: pip install clickhouse-driver"
            )

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
                'use_numpy': True,
                'max_block_size': 100000,
                'max_threads': 4,  # Limit threads per query
                'max_execution_time': 60,  # 60s query timeout
            }
        )

        # Auto-create tables
        if auto_create:
            self._ensure_tables()
            self._run_migrations()

        ClickHouseAdapter._initialized = True

    def _ensure_database(self):
        """Ensure the database exists, creating it if necessary."""
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
                print(f"[Windlass] Creating database '{self.database}'...")
                system_client.execute(f"CREATE DATABASE IF NOT EXISTS {self.database}")
                print(f"[Windlass] Database '{self.database}' created")
        except Exception as e:
            print(f"[Windlass] Warning: Could not check/create database: {e}")

    def _ensure_tables(self):
        """Ensure all required tables exist."""
        from .schema import get_all_schemas

        schemas = get_all_schemas()
        for table_name, ddl in schemas.items():
            try:
                # Check if table exists
                result = self.client.execute(
                    f"SELECT 1 FROM system.tables WHERE database = '{self.database}' AND name = '{table_name}'"
                )
                if not result:
                    print(f"[Windlass] Creating table '{table_name}'...")
                    self.client.execute(ddl)
                    print(f"[Windlass] Table '{table_name}' created")
            except Exception as e:
                print(f"[Windlass] Warning: Could not ensure table '{table_name}': {e}")

    def _run_migrations(self):
        """
        Run all pending migrations from the migrations directory.

        Migrations are SQL files that use IF NOT EXISTS / IF EXISTS clauses
        for idempotency, so they're safe to run multiple times.
        """
        from pathlib import Path

        # Find migrations directory (relative to this file)
        migrations_dir = Path(__file__).parent.parent / "migrations"

        if not migrations_dir.exists():
            return

        # Get all .sql files sorted alphabetically
        migration_files = sorted(migrations_dir.glob("*.sql"))

        if not migration_files:
            return

        print(f"[Windlass] Running {len(migration_files)} migrations...")

        for migration_file in migration_files:
            try:
                # Read migration SQL
                sql_content = migration_file.read_text()

                # Split by semicolons and execute each statement
                statements = [s.strip() for s in sql_content.split(';') if s.strip()]

                executed = 0
                for statement in statements:
                    # Skip comments-only blocks
                    lines = [l for l in statement.split('\n') if l.strip() and not l.strip().startswith('--')]
                    if not lines:
                        continue

                    # Skip SELECT statements (verification queries)
                    first_line = lines[0].strip().upper()
                    if first_line.startswith('SELECT'):
                        continue

                    try:
                        self.client.execute(statement)
                        executed += 1
                    except Exception as stmt_err:
                        # Log but don't fail - migration may have already been applied
                        err_str = str(stmt_err).lower()
                        if "already exists" not in err_str and "duplicate" not in err_str:
                            print(f"[Windlass] Migration '{migration_file.name}' warning: {stmt_err}")

                if executed > 0:
                    print(f"[Windlass] Migration '{migration_file.name}': {executed} statements executed")

            except Exception as e:
                print(f"[Windlass] Warning: Could not run migration '{migration_file.name}': {e}")

    # =========================================================================
    # Query Operations
    # =========================================================================

    def query(self, sql: str, params: Dict = None, output_format: str = "dict") -> Any:
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
                print(f"[ClickHouse Error] Query failed: {e}")
                print(f"[ClickHouse Error] SQL: {sql[:500]}...")
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
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

    def query_df(self, sql: str, params: Dict = None) -> pd.DataFrame:
        """
        Execute query and return pandas DataFrame.

        Convenience wrapper for query(..., output_format="dataframe").
        """
        return self.query(sql, params, output_format="dataframe")

    def execute(self, sql: str, params: Dict = None):
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
                self.client.execute(sql, params or {})
            except Exception as e:
                success = False
                error_msg = str(e)
                print(f"[ClickHouse Error] Execute failed: {e}")
                print(f"[ClickHouse Error] SQL: {sql[:500]}...")
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                logger = get_query_logger()
                if logger:
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

    def insert_rows(self, table: str, rows: List[Dict], columns: List[str] = None):
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
        should_log = table != 'ui_sql_log'
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

        # Convert rows to list of tuples
        values = []
        for row in rows:
            row_values = []
            for col in columns:
                val = row.get(col)
                val = convert_value(val, col)
                row_values.append(val)
            values.append(tuple(row_values))

        cols_str = ', '.join(columns)
        with ClickHouseAdapter._query_lock:
            try:
                # Disable numpy processing in clickhouse_driver
                self.client.execute(
                    f"INSERT INTO {table} ({cols_str}) VALUES",
                    values,
                    settings={'use_numpy': False}
                )
            except Exception as e:
                success = False
                error_msg = str(e)
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

    def insert_dataframe(self, table: str, df: pd.DataFrame, columns: List[str] = None):
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

        # Use clickhouse-driver's native DataFrame insert
        cols_str = ', '.join(columns)
        with ClickHouseAdapter._query_lock:
            try:
                self.client.insert_dataframe(
                    f"INSERT INTO {table} ({cols_str}) VALUES",
                    df[columns],
                    settings={'use_numpy': True}
                )
            except Exception as e:
                success = False
                error_msg = str(e)
                print(f"[ClickHouse Error] Insert DataFrame failed: {e}")
                print(f"[ClickHouse Error] Table: {table}")
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                logger = get_query_logger()
                if logger:
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
                # Escape single quotes
                escaped = val.replace("'", "''")
                set_parts.append(f"{col} = '{escaped}'")
            elif isinstance(val, list):
                # Check if it's a numeric array (for embeddings)
                if val and all(isinstance(x, (int, float)) for x in val):
                    # Format as ClickHouse array literal: [1.0, 2.0, 3.0]
                    array_str = '[' + ', '.join(str(x) for x in val) + ']'
                    set_parts.append(f"{col} = {array_str}")
                else:
                    # Non-numeric array - store as JSON string
                    json_str = json.dumps(val, default=str, ensure_ascii=False).replace("'", "''")
                    set_parts.append(f"{col} = '{json_str}'")
            elif isinstance(val, dict):
                json_str = json.dumps(val, default=str, ensure_ascii=False).replace("'", "''")
                set_parts.append(f"{col} = '{json_str}'")
            else:
                set_parts.append(f"{col} = '{str(val)}'")

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
        cost data to system/phase_start rows that share the same trace_id.
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
                # Only update the assistant row - system/phase_start rows share trace_id
                # but shouldn't have cost data (prevents double-counting in SUM queries)
                self.update_row(
                    table,
                    update_data,
                    f"trace_id = '{trace_id}' AND role = 'assistant'",
                    sync=False  # Don't wait for each individual update
                )

    def mark_sounding_winner(
        self,
        table: str,
        session_id: str,
        phase_name: str,
        winning_index: int
    ):
        """
        Mark all rows in a sounding as winner/loser.

        Updates is_winner for all rows matching the session/phase/sounding.

        Args:
            table: Table name (usually unified_logs)
            session_id: Session ID
            phase_name: Phase name
            winning_index: The winning sounding index
        """
        # Mark winner
        self.update_row(
            table,
            {'is_winner': True},
            f"session_id = '{session_id}' AND phase_name = '{phase_name}' AND sounding_index = {winning_index}",
            sync=True
        )

        # Mark losers (all other sounding indexes in same phase)
        start_time = time.time()
        success = True
        error_msg = None

        sql = f"""
            ALTER TABLE {table}
            UPDATE is_winner = false
            WHERE session_id = '{session_id}'
              AND phase_name = '{phase_name}'
              AND sounding_index IS NOT NULL
              AND sounding_index != {winning_index}
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
        where: str = None,
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
                - phase_name: str
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
                "phase_name": row.get("phase_name"),
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
        phase_names: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get context cards for a session.

        Args:
            session_id: Session ID to query
            phase_names: Optional list of phase names to filter by
            limit: Maximum number of cards to return

        Returns:
            List of context card dictionaries
        """
        where_parts = [f"session_id = '{session_id}'"]

        if phase_names:
            phases_str = ", ".join([f"'{p}'" for p in phase_names])
            where_parts.append(f"phase_name IN ({phases_str})")

        where_clause = " AND ".join(where_parts)

        sql = f"""
            SELECT
                session_id,
                content_hash,
                summary,
                keywords,
                estimated_tokens,
                role,
                phase_name,
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
                phase_name,
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
                phase_name,
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
                    print(f"[Windlass] Creating table '{table_name}'...")
                    self.client.execute(ddl)  # Direct execute to avoid nested lock
                    print(f"[Windlass] Table '{table_name}' created")
            except Exception as e:
                print(f"[Windlass] Warning: Could not ensure table '{table_name}': {e}")

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

    _adapter_singleton = ClickHouseAdapter(
        host=config.clickhouse_host,
        port=config.clickhouse_port,
        database=config.clickhouse_database,
        user=config.clickhouse_user,
        password=config.clickhouse_password
    )

    return _adapter_singleton


def get_db() -> ClickHouseAdapter:
    """Alias for get_db_adapter() - shorter name for convenience."""
    return get_db_adapter()


def reset_adapter():
    """Reset the adapter singleton (useful for testing)."""
    global _adapter_singleton
    _adapter_singleton = None
    ClickHouseAdapter._instance = None
    ClickHouseAdapter._initialized = False
