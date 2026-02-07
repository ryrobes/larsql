"""
PostgreSQL wire protocol server for LARS.

This server accepts connections from any PostgreSQL client (DBeaver, psql, DataGrip, Tableau)
and executes queries on LARS session DuckDB with lars_udf() and lars_cascade_udf().

Each client connection gets its own isolated DuckDB session with:
- lars_udf() registered (simple LLM UDF)
- lars_cascade_udf() registered (full cascade per row)
- Temp tables (session-scoped)
- ATTACH support (connect to external databases)

Usage:
    from lars.server.postgres_server import start_postgres_server

    start_postgres_server(host='0.0.0.0', port=5432)

Then connect from any PostgreSQL client:
    psql postgresql://localhost:5432/default
    DBeaver: Add PostgreSQL connection → localhost:5432
"""

import os
import socket
import threading
import uuid
import traceback
import re
from threading import Lock
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from ..console_style import S, styled_print

from .postgres_protocol import (
    PostgresMessage,
    PostgresProtocolError,
    MessageType,
    CommandComplete,
    ReadyForQuery,
    ErrorResponse,
    EmptyQueryResponse,
    send_startup_response,
    send_query_results,
    send_execute_results,
    send_error,
    # Extended Query Protocol classes
    ParseMessage,
    BindMessage,
    DescribeMessage,
    ExecuteMessage,
    CloseMessage,
    ParseComplete,
    BindComplete,
    CloseComplete,
    ParameterDescription,
    NoData,
    RowDescription,
    # Authentication classes
    AuthenticationCleartextPassword,
    PasswordMessage,
)


# ============================================================================
# EXPLAIN Formatting Helper
# ============================================================================

def _format_native_explain_df(result_df):
    """
    Format native DuckDB EXPLAIN results for better readability.

    DuckDB EXPLAIN returns a DataFrame with columns ['explain_key', 'explain_value']:
    - explain_key: 'physical_plan' (or 'logical_plan' for EXPLAIN (LOGICAL))
    - explain_value: The actual plan tree as ASCII text

    This function transforms the raw DuckDB output into a single-column result
    with the plan type label followed by the formatted plan tree.

    For semantic SQL EXPLAIN results (which already have a single 'query_plan' column),
    this function passes them through unchanged.

    Args:
        result_df: DataFrame from DuckDB EXPLAIN query

    Returns:
        DataFrame with single 'query_plan' column containing the formatted plan,
        or the original DataFrame if it doesn't match the DuckDB EXPLAIN format.
    """
    import pandas as pd

    # Check if this is a native DuckDB EXPLAIN result
    columns = list(result_df.columns)

    if columns == ['explain_key', 'explain_value']:
        # Native DuckDB EXPLAIN format - format it nicely
        plan_parts = []
        for _, row in result_df.iterrows():
            plan_type = str(row['explain_key'])
            plan_text = str(row['explain_value'])

            # Format with plan type header
            # Replace escaped newlines with actual newlines if needed
            if '\\n' in plan_text:
                plan_text = plan_text.replace('\\n', '\n')

            plan_parts.append(f"{plan_type}:\n{plan_text}")

        # Combine all plan parts (usually just one, but EXPLAIN ANALYZE may have more)
        formatted_plan = '\n'.join(plan_parts)

        return pd.DataFrame([{'query_plan': formatted_plan}])

    # Not a DuckDB EXPLAIN format - return unchanged
    # This handles semantic EXPLAIN results that already have a 'query_plan' column
    return result_df


class ClientConnection:
    """
    Represents a single client connection.

    Each client gets:
    - Unique session ID
    - Isolated DuckDB session
    - LARS UDFs registered
    - Dedicated socket
    """

    def __init__(self, sock, addr, session_prefix='pg_client', server=None, idle_timeout=0):
        self.sock = sock
        self.addr = addr
        # Stable identifier for correlating runtime_event_log rows across a single TCP connection.
        self.connection_id = uuid.uuid4().hex[:12]
        self.session_id = None  # Will be set in handle_startup based on database name
        self.session_prefix = session_prefix
        self.server = server  # Reference to parent server for connection tracking
        self.idle_timeout = idle_timeout  # Seconds before disconnecting idle client (0 = disabled)
        self.database_name = 'default'  # Logical database name from client connection
        self.results_db_name = 'lars_results_default'  # ClickHouse database for INTO tables (namespaced by database_name)
        self.user_name = 'lars'       # Logical user name from client connection
        self.application_name = 'unknown'
        self.duckdb_conn = None
        self.db_lock = None  # Lock for thread-safe DuckDB access
        self.running = True
        self.query_count = 0
        self.transaction_status = 'I'  # 'I' = idle, 'T' = in transaction, 'E' = error
        self._last_activity = None  # Timestamp of last activity (for idle timeout)

        # Extended Query Protocol state
        self.prepared_statements = {}  # name → {query, param_types, param_count}
        self.portals = {}               # name → {statement_name, params, result_formats, query}

        # Lazy attach manager (initialized in setup_session)
        self._lazy_attach = None
        self._duckdb_catalog_name = None

        # Cache: last seen attached database set (to refresh views after lazy ATTACH)
        self._last_attached_db_names = set()

        # DuckDB connection pooling (optional, pre-warmed in-memory connections)
        self._is_pooled_connection = False

        # Console logging: keep stdout sane under concurrent connections.
        # Most events are written to ClickHouse `runtime_event_log` instead.
        self._console_log_level = self._parse_log_level(os.environ.get("LARS_PG_CONSOLE_LOG_LEVEL", "ERROR"))

        # Authentication state
        self.authenticated_user = None  # User dict from auth.validate_api_key()
        self.auth_user_id = 'anonymous'  # User ID for param store scoping

    @staticmethod
    def _parse_log_level(level: str) -> int:
        val = (level or "").strip().upper()
        if val in ("NONE", "OFF", "SILENT"):
            return 10_000
        mapping = {
            "DEBUG": 10,
            "INFO": 20,
            "WARN": 30,
            "WARNING": 30,
            "ERROR": 40,
            "FATAL": 50,
        }
        return mapping.get(val, 30)

    @staticmethod
    def _level_value(level: str) -> int:
        return ClientConnection._parse_log_level(level)

    def _runtime_log(self, level: str, message: str, *, event: str = "", **extra) -> None:
        """
        Write an operational log event to ClickHouse (and optionally to stdout).

        This is for high-volume runtime/pgwire logs, not cascade message records.
        """
        try:
            from lars.runtime_event_logger import get_runtime_event_logger

            logger = get_runtime_event_logger()
            client_addr = None
            try:
                client_addr = f"{self.addr[0]}:{self.addr[1]}"
            except Exception:
                client_addr = None

            logger.log_event(
                source="pgwire",
                level=level,
                event=event,
                message=message,
                connection_id=self.connection_id,
                session_id=self.session_id,
                query_id=extra.pop("query_id", None),
                caller_id=extra.pop("caller_id", None),
                user_name=self.user_name,
                auth_user_id=self.auth_user_id,
                database_name=self.database_name,
                results_db=self.results_db_name,
                application_name=self.application_name,
                client_addr=client_addr,
                thread_id=threading.get_ident(),
                extra=extra,
            )
        except Exception:
            pass

        # Optional stdout echo for high-severity messages only.
        if self._level_value(level) >= self._console_log_level:
            try:
                print(f"[{self.session_id or self.addr}] {level.upper()}: {message}")
            except Exception:
                pass

    def setup_session_minimal(self):
        """
        FAST session setup - just enough to respond to client.

        Called BEFORE sending startup response to minimize client wait time.
        Heavy operations (auto-attach, views, etc.) are deferred to setup_session_deferred().
        """
        try:
            import duckdb
            from ..sql_tools.udf import register_dynamic_sql_functions, register_lars_udf

            # Pgwire uses an in-memory DuckDB session per client connection (optionally pre-warmed from a pool).
            # Durable tables/results live in ClickHouse (via INTO rewriting / query insurance).
            self.db_lock = Lock()  # Per-connection lock (not shared)
            pooled_conn = None
            try:
                from ..sql_tools.connection_pool import get_pooled_connection
                pooled_conn = get_pooled_connection(timeout=2.0)  # Wait up to 2s for pooled conn
            except ImportError:
                pooled_conn = None
            except Exception as e:
                self._runtime_log(
                    "WARN",
                    f"DuckDB pool get failed: {e}",
                    event="duckdb_pool_error",
                )

            if pooled_conn is not None:
                self.duckdb_conn = pooled_conn
                self._is_pooled_connection = True
                self._runtime_log(
                    "DEBUG",
                    "DuckDB in-memory session (pooled, pre-warmed)",
                    event="duckdb_session",
                    pooled=True,
                    duckdb_conn_obj_id=id(self.duckdb_conn),
                )
            else:
                self.duckdb_conn = duckdb.connect(':memory:')
                self._is_pooled_connection = False
                self._runtime_log(
                    "DEBUG",
                    "DuckDB in-memory session (fresh)",
                    event="duckdb_session",
                    pooled=False,
                    duckdb_conn_obj_id=id(self.duckdb_conn),
                )

            # Cache DuckDB's internal catalog name (usually 'memory')
            try:
                self._duckdb_catalog_name = self.duckdb_conn.execute("SELECT current_database()").fetchone()[0]
            except Exception:
                self._duckdb_catalog_name = None

            # Initialize connection if not pre-warmed by the pool.
            # Pooled connections already have extensions/UDFs/attachments initialized.
            if not self._is_pooled_connection:
                with self.db_lock:
                    # Configure DuckDB
                    self.duckdb_conn.execute("SET threads TO 4")

                    # Install and load community extensions for graph queries
                    # Use timeout to prevent blocking on network issues
                    duckpgq_installed = False

                    def install_duckpgq():
                        self.duckdb_conn.execute("INSTALL duckpgq FROM community;")

                    try:
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(install_duckpgq)
                            future.result(timeout=5.0)  # 5 second timeout
                        duckpgq_installed = True
                    except FuturesTimeoutError:
                        self._runtime_log(
                            "WARN",
                            "duckpgq install timed out (network issue?), skipping",
                            event="duckdb_extension_timeout",
                            extension="duckpgq",
                        )
                    except Exception:
                        duckpgq_installed = True  # Already installed

                    if duckpgq_installed:
                        try:
                            self.duckdb_conn.execute("LOAD duckpgq;")
                        except Exception as e:
                            self._runtime_log(
                                "WARN",
                                f"Could not load duckpgq: {e}",
                                event="duckdb_extension_load_failed",
                                extension="duckpgq",
                            )

                    # DataGrip/PostgreSQL clients frequently schema-qualify functions as pg_catalog.func(...),
                    # but DuckDB parses that as a column reference. We register unqualified compat macros
                    # and later strip the pg_catalog. prefix for function calls at execution time.
                    try:
                        self.duckdb_conn.execute("CREATE OR REPLACE MACRO pg_get_userbyid(x) AS 'lars'")
                        self.duckdb_conn.execute(
                            "CREATE OR REPLACE MACRO txid_current() AS (epoch_ms(now())::BIGINT % 4294967296)"
                        )
                        self.duckdb_conn.execute("CREATE OR REPLACE MACRO pg_is_in_recovery() AS false")
                        self.duckdb_conn.execute("CREATE OR REPLACE MACRO pg_tablespace_location(x) AS NULL")
                    except Exception:
                        pass

                    # Register LARS UDFs (lars_udf + lars_cascade_udf + hardcoded aggregates)
                    register_lars_udf(self.duckdb_conn)

                    # Register dynamic SQL functions from cascade registry (SUMMARIZE_URLS, etc.)
                    register_dynamic_sql_functions(self.duckdb_conn)

                    self._runtime_log("INFO", "Initialized DuckDB session (UDFs, extensions)", event="duckdb_init")

            # Reset our transaction status to idle
            self.transaction_status = 'I'

            # Initialize lazy attach manager (but DON'T auto-attach yet - that's slow)
            # Each session gets its own lazy attach manager (tracks what's been attached in this session)
            try:
                from ..sql_tools.config import load_sql_connections
                from ..sql_tools.lazy_attach import LazyAttachManager
                self._lazy_attach = LazyAttachManager(self.duckdb_conn, load_sql_connections())
            except Exception:
                self._lazy_attach = None

            # Minimal setup complete - client can now receive response
            self._runtime_log("DEBUG", "Minimal setup complete", event="session_minimal_ready")

        except Exception as e:
            self._runtime_log(
                "ERROR",
                f"Error in minimal session setup: {e}",
                event="session_minimal_error",
            )
            raise

    def setup_session_deferred(self):
        """
        Heavy session setup - auto-attach, metadata tables, views, etc.

        Called after minimal setup but BEFORE sending startup response.
        This ensures the session is fully ready before the client can send queries.
        (Previously this ran after startup response, but aggressive clients like
        DataGrip would send queries immediately and timeout waiting for responses.)
        """
        try:
            # Register promoted metrics as SQL operators (BI of Intent)
            try:
                from ..bi.metric_registry import register_promoted_metrics
                promoted_count = register_promoted_metrics(self.duckdb_conn)
                if promoted_count > 0:
                    self._runtime_log(
                        "INFO",
                        f"Registered {promoted_count} promoted metric(s)",
                        event="metrics_promoted_registered",
                        promoted_count=promoted_count,
                    )
            except Exception:
                # Non-fatal - BI tables may not exist yet
                pass

            # Auto-attach all configured connections (can be slow but must complete before client queries)
            # NOTE: We attach for BOTH pooled and fresh connections. Pooled connections skip
            # attach during warming (LARS_POOL_ATTACH_ALL=0 by default) for faster startup,
            # so we must attach here. attach_all() is idempotent - already-attached DBs are skipped.
            from ..sql_tools.lazy_attach import _auto_attach_all_enabled
            if self._lazy_attach and _auto_attach_all_enabled():
                try:
                    results = self._lazy_attach.attach_all()
                    attached = [r for r in results if r["status"] == "attached"]
                    failed = [r for r in results if r["status"] == "failed"]
                    if attached:
                        self._runtime_log(
                            "INFO",
                            f"Auto-attached {len(attached)} connection(s)",
                            event="auto_attach_complete",
                            attached_count=len(attached),
                            failed_count=len(failed),
                        )
                    if failed:
                        self._runtime_log(
                            "WARN",
                            f"{len(failed)} connection(s) failed to auto-attach",
                            event="auto_attach_failed",
                            attached_count=len(attached),
                            failed_count=len(failed),
                            failed=failed[:10],
                        )
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"Auto-attach failed: {e}",
                        event="auto_attach_error",
                    )

            # Always sync shared parquet tables
            # This is fast (directory scan + view creation) and ensures new tables are visible
            try:
                from ..sql_tools.shared_parquet import sync_shared_views, is_shared_tables_enabled
                if is_shared_tables_enabled():
                    with self.db_lock:
                        count = sync_shared_views(self.duckdb_conn)
                        if count > 0:
                            self._runtime_log(
                                "INFO",
                                f"Synced {count} shared table(s)",
                                event="shared_tables_synced",
                                shared_table_count=count,
                            )
            except Exception as e:
                self._runtime_log(
                    "WARN",
                    f"Shared tables sync failed: {e}",
                    event="shared_tables_sync_failed",
                )

            # Attach LARS system tables (unified_logs, costs, sessions, etc.)
            try:
                from ..lars_db import attach_system_views
                with self.db_lock:
                    system_count = attach_system_views(self.duckdb_conn)
                    if system_count > 0:
                        self._runtime_log(
                            "INFO",
                            f"Attached {system_count} system table(s)",
                            event="system_tables_attached",
                            system_table_count=system_count,
                        )
            except Exception as e:
                self._runtime_log(
                    "WARN",
                    f"System tables attach failed: {e}",
                    event="system_tables_attach_failed",
                )

            # DuckDB v1.4.2+ has built-in pg_catalog support
            self._runtime_log(
                "DEBUG",
                "Using DuckDB's built-in pg_catalog (v1.4.2+)",
                event="duckdb_pg_catalog",
            )

            # Create PostgreSQL compatibility stubs (functions and macros)
            self._create_pg_compat_stubs()

            # Create views for ATTACH'd databases so they appear in DBeaver
            self._create_attached_db_views()

            # Register UDF to refresh views after manual ATTACH
            self._register_refresh_views_udf()

            self._runtime_log(
                "INFO",
                "Session ready",
                event="session_ready",
                database_name=self.database_name,
                results_db=self.results_db_name,
            )

        except Exception as e:
            # Non-fatal - deferred setup failures shouldn't kill the connection
            self._runtime_log(
                "WARN",
                f"Deferred setup error (non-fatal): {e}",
                event="session_deferred_error",
            )

    def setup_session(self):
        """
        Full session setup (legacy - calls both minimal and deferred).

        For backward compatibility with any code that calls setup_session() directly.
        """
        self.setup_session_minimal()
        self.setup_session_deferred()

    def _execute_locked(self, query: str):
        """
        Execute a query on DuckDB with thread-safe locking.

        CRITICAL: DuckDB connections are NOT thread-safe. Multiple clients
        sharing the same session connection can cause segfaults without locking.
        """
        with self.db_lock:
            return self.duckdb_conn.execute(query)

    def _get_readonly_conn(self):
        """
        Get a connection for EXPLAIN queries.

        For file-based databases with multiple workers, DuckDB's locking can
        cause issues. We use the existing session connection with locking
        instead of opening new connections.

        Returns:
            (connection, should_close) tuple
        """
        # Always use the existing connection - DuckDB file locking is too strict
        # for multiple read-only connections when a writer is active.
        # The session's db_lock will serialize access within this process.
        return self.duckdb_conn, False

    @staticmethod
    def _rewrite_pg_catalog_function_calls(query: str) -> str:
        """
        Rewrite `pg_catalog.func(` → `func(` for function-style calls.

        DuckDB does not support schema-qualified function calls, but Postgres clients
        commonly emit them in catalog queries (especially DataGrip).
        """
        import re
        return re.sub(
            r'(?i)\bpg_catalog\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
            r'\1(',
            query
        )

    @staticmethod
    def _rewrite_pg_system_column_refs(query: str) -> str:
        """
        Rewrite PostgreSQL system columns that DuckDB's pg_catalog tables don't expose.

        JetBrains DataGrip (and some other clients) select `xmin` as a "state_number"
        to detect catalog changes. DuckDB's pg_catalog compatibility tables do not
        include `xmin`, so these queries fail unless we replace it with a constant.

        DuckDB's pg_class also does not include `relforcerowsecurity` (present in newer
        PostgreSQL versions), which can appear in DataGrip introspection queries.

        PostgreSQL system columns we need to handle:
        - xmin, xmax: Transaction IDs (MVCC versioning)
        - cmin, cmax: Command identifiers within transaction
        - ctid: Tuple identifier (physical row location)
        - tableoid: OID of the table containing the row
        - relforcerowsecurity, relrowsecurity: Row-level security columns
        - relrewrite: Table rewrite temp relation OID
        - relpartbound: Partition bound expression
        """
        import re

        # =================================================================
        # PostgreSQL MVCC system columns (all rows have these)
        # =================================================================

        # xmin: Transaction ID that inserted this row version
        # DataGrip uses this as "state_number" to detect catalog changes
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.xmin\b', '0::int4', query)

        # xmax: Transaction ID of deleting transaction, or 0 if not deleted
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.xmax\b', '0::int4', query)

        # cmin, cmax: Command identifiers within the inserting/deleting transaction
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.cmin\b', '0::int4', query)
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.cmax\b', '0::int4', query)

        # ctid: Physical location of the row (block, offset)
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.ctid\b', "'(0,0)'::text", query)

        # tableoid: OID of the table containing this row
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.tableoid\b', '0::int4', query)

        # =================================================================
        # pg_class columns not in DuckDB's implementation
        # =================================================================

        # relforcerowsecurity: Force row security even for table owner (PostgreSQL 9.5+)
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.relforcerowsecurity\b', 'false', query)

        # relrowsecurity: Row-level security is enabled (PostgreSQL 9.5+)
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.relrowsecurity\b', 'false', query)

        # relrewrite: For tables being rewritten, OID of new temp relation
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.relrewrite\b', '0::int4', query)

        # relpartbound: Partition bound expression (PostgreSQL 10+)
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.relpartbound\b', 'NULL::text', query)

        # relispartition: Whether the table is a partition (PostgreSQL 10+)
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.relispartition\b', 'false', query)

        # =================================================================
        # pg_attribute columns not in DuckDB's implementation
        # =================================================================

        # attidentity: Identity column type ('a' = always, 'd' = by default, '' = not identity)
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.attidentity\b', "''::text", query)

        # attgenerated: Generated column type ('s' = stored, '' = not generated)
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.attgenerated\b', "''::text", query)

        # attcompression: Compression method for the column
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.attcompression\b', "''::text", query)

        # =================================================================
        # pg_namespace columns not in DuckDB's implementation
        # =================================================================

        # nspacl: Access privileges for the namespace
        query = re.sub(r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\.nspacl\b', 'NULL::text[]', query)

        # =================================================================
        # PostgreSQL functions that don't work with rewritten values
        # =================================================================

        # age(xmin) - After xmin is rewritten to 0::int4, age() fails because
        # DuckDB's built-in age() requires timestamps. DataGrip uses age(c.xmin)
        # as a "state_number" to detect catalog changes. Return 0 for any
        # age() call on integer-like values.
        # Patterns: age(0::int4), age(0), age(123), age(c.xmin) before xmin rewrite
        query = re.sub(r'(?i)\bage\s*\(\s*0::int4\s*\)', '0', query)
        query = re.sub(r'(?i)\bage\s*\(\s*0\s*\)', '0', query)
        query = re.sub(r'(?i)\bage\s*\(\s*\d+\s*\)', '0', query)

        # =================================================================
        # DataGrip placeholders
        # =================================================================

        # #TXAGE - DataGrip uses this as a placeholder for transaction age
        # It gets used in WHERE clauses like "WHERE 0 <= #TXAGE"
        # Replace with 0 since DuckDB doesn't track transaction ages
        query = re.sub(r'#TXAGE\b', '0', query)

        return query

    @staticmethod
    def _quote_ident(name: str) -> str:
        return f'"{name.replace(chr(34), chr(34) * 2)}"'

    def _handle_missing_pg_catalog_tables(self, query_upper: str, query: str):
        """
        Handle queries where the PRIMARY table is a missing pg_catalog table.

        Only intercepts if the main FROM table is missing (not JOINs).
        For JOINs to missing tables, use _rewrite_missing_table_joins instead.

        Returns:
            DataFrame if query was handled (missing primary table), None otherwise
        """
        import pandas as pd
        import re

        # Tables that DuckDB's pg_catalog doesn't have - only intercept if PRIMARY table
        MISSING_PRIMARY_TABLES = {
            'PG_LOCKS': ['locktype', 'database', 'relation', 'page', 'tuple',
                        'virtualxid', 'transactionid', 'classid', 'objid',
                        'objsubid', 'virtualtransaction', 'pid', 'mode',
                        'granted', 'fastpath', 'waitstart'],
            'PG_STAT_STATEMENTS': ['userid', 'dbid', 'queryid', 'query', 'calls',
                                   'total_time', 'rows', 'shared_blks_hit'],
            'PG_STAT_USER_TABLES': ['relid', 'schemaname', 'relname', 'seq_scan',
                                    'idx_scan', 'n_tup_ins', 'n_tup_upd', 'n_tup_del'],
            'PG_STAT_USER_INDEXES': ['relid', 'indexrelid', 'schemaname', 'relname',
                                     'indexrelname', 'idx_scan', 'idx_tup_read'],
            'PG_STATIO_USER_TABLES': ['relid', 'schemaname', 'relname', 'heap_blks_read',
                                      'heap_blks_hit', 'idx_blks_read', 'idx_blks_hit'],
            'PG_REPLICATION_SLOTS': ['slot_name', 'plugin', 'slot_type', 'datoid',
                                     'database', 'temporary', 'active', 'restart_lsn'],
            'PG_PUBLICATION': ['oid', 'pubname', 'pubowner', 'puballtables',
                              'pubinsert', 'pubupdate', 'pubdelete'],
            'PG_SUBSCRIPTION': ['oid', 'subdbid', 'subname', 'subowner',
                               'subenabled', 'subconninfo', 'subslotname'],
            'PG_STATISTIC': ['starelid', 'staattnum', 'stainherit', 'stanullfrac',
                            'stawidth', 'stadistinct'],
            'PG_STATISTIC_EXT': ['oid', 'stxrelid', 'stxname', 'stxnamespace',
                                'stxowner', 'stxkeys'],
            'PG_POLICIES': ['oid', 'polname', 'polrelid', 'polcmd',
                           'polpermissive', 'polroles', 'polqual', 'polwithcheck'],
            'PG_RULES': ['schemaname', 'tablename', 'rulename', 'definition'],
            'PG_HBA_FILE_RULES': ['line_number', 'type', 'database', 'user_name',
                                  'address', 'netmask', 'auth_method'],
            'PG_FILE_SETTINGS': ['sourcefile', 'sourceline', 'seqno', 'name',
                                'setting', 'applied', 'error'],
            'PG_AUTH_MEMBERS': ['member', 'roleid', 'admin_option', 'grantor'],
            'PG_ROLES': ['oid', 'rolname', 'rolsuper', 'rolinherit', 'rolcreaterole',
                        'rolcreatedb', 'rolcanlogin', 'rolreplication', 'rolconnlimit',
                        'rolpassword', 'rolvaliduntil', 'rolbypassrls', 'rolconfig'],
            'PG_EVENT_TRIGGER': ['oid', 'evtname', 'evtevent', 'evtowner', 'evtfoid',
                                'evtenabled', 'evttags'],
            'PG_FOREIGN_DATA_WRAPPER': ['oid', 'fdwname', 'fdwowner', 'fdwhandler',
                                        'fdwvalidator', 'fdwacl', 'fdwoptions'],
            'PG_FOREIGN_SERVER': ['oid', 'srvname', 'srvowner', 'srvfdw', 'srvtype',
                                  'srvversion', 'srvacl', 'srvoptions'],
            'PG_FOREIGN_TABLE': ['ftrelid', 'ftserver', 'ftoptions'],
            'PG_EXTENSION': ['oid', 'extname', 'extowner', 'extnamespace', 'extrelocatable',
                            'extversion', 'extconfig', 'extcondition'],
            'PG_LANGUAGE': ['oid', 'lanname', 'lanowner', 'lanispl', 'lanpltrusted',
                           'lanplcallfoid', 'laninline', 'lanvalidator', 'lanacl'],
            'PG_CAST': ['oid', 'castsource', 'casttarget', 'castfunc', 'castcontext',
                       'castmethod'],
            'PG_COLLATION': ['oid', 'collname', 'collnamespace', 'collowner', 'collprovider',
                            'collisdeterministic', 'collencoding', 'collcollate', 'collctype',
                            'colliculocale', 'collversion'],
            'PG_INHERITS': ['inhrelid', 'inhparent', 'inhseqno'],
            'PG_PARTITIONED_TABLE': ['partrelid', 'partstrat', 'partnatts', 'partdefid',
                                     'partattrs', 'partclass', 'partcollation', 'partexprs'],
            'PG_RANGE': ['rngtypid', 'rngsubtype', 'rngmultitypid', 'rngcollation',
                        'rngsubopc', 'rngcanonical', 'rngsubdiff'],
            'PG_OPERATOR': ['oid', 'oprname', 'oprnamespace', 'oprowner', 'oprkind',
                           'oprcanmerge', 'oprcanhash', 'oprleft', 'oprright', 'oprresult',
                           'oprcom', 'oprnegate', 'oprcode', 'oprrest', 'oprjoin'],
            'PG_OPCLASS': ['oid', 'opcmethod', 'opcname', 'opcnamespace', 'opcowner',
                          'opcfamily', 'opcintype', 'opcdefault', 'opckeytype'],
            'PG_OPFAMILY': ['oid', 'opfmethod', 'opfname', 'opfnamespace', 'opfowner'],
            'PG_AM': ['oid', 'amname', 'amhandler', 'amtype'],
            'PG_AMOP': ['oid', 'amopfamily', 'amoplefttype', 'amoprighttype', 'amopstrategy',
                       'amoppurpose', 'amopopr', 'amopmethod', 'amopsortfamily'],
            'PG_AMPROC': ['oid', 'amprocfamily', 'amproclefttype', 'amprocrighttype',
                        'amprocnum', 'amproc'],
            'PG_AGGREGATE': ['aggfnoid', 'aggkind', 'aggnumdirectargs', 'aggtransfn',
                            'aggfinalfn', 'aggcombinefn', 'aggserialfn', 'aggdeserialfn',
                            'aggmtransfn', 'aggminvtransfn', 'aggmfinalfn', 'aggfinalextra',
                            'aggmfinalextra', 'aggfinalmodify', 'aggmfinalmodify',
                            'aggsortop', 'aggtranstype', 'aggtransspace', 'aggmtranstype',
                            'aggmtransspace', 'agginitval', 'aggminitval'],
            'PG_CONVERSION': ['oid', 'conname', 'connamespace', 'conowner', 'conforencoding',
                             'contoencoding', 'conproc', 'condefault'],
            # NOTE: PG_ENUM removed - DuckDB 1.4.2+ has built-in pg_catalog.pg_enum
            'PG_TRIGGER': ['oid', 'tgrelid', 'tgparentid', 'tgname', 'tgfoid', 'tgtype',
                          'tgenabled', 'tgisinternal', 'tgconstrrelid', 'tgconstrindid',
                          'tgconstraint', 'tgdeferrable', 'tginitdeferred', 'tgnargs',
                          'tgattr', 'tgargs', 'tgqual', 'tgoldtable', 'tgnewtable'],
            'PG_REWRITE': ['oid', 'rulename', 'ev_class', 'ev_type', 'ev_enabled',
                          'is_instead', 'ev_qual', 'ev_action'],
            'PG_POLICY': ['oid', 'polname', 'polrelid', 'polcmd', 'polpermissive',
                         'polroles', 'polqual', 'polwithcheck'],
            'PG_SECLABEL': ['objoid', 'classoid', 'objsubid', 'provider', 'label'],
            'PG_SHSECLABEL': ['objoid', 'classoid', 'provider', 'label'],
            'PG_TS_CONFIG': ['oid', 'cfgname', 'cfgnamespace', 'cfgowner', 'cfgparser'],
            'PG_TS_DICT': ['oid', 'dictname', 'dictnamespace', 'dictowner', 'dicttemplate', 'dictinitoption'],
            'PG_TS_PARSER': ['oid', 'prsname', 'prsnamespace', 'prsstart', 'prstoken', 'prsend', 'prsheadline', 'prslextype'],
            'PG_TS_TEMPLATE': ['oid', 'tmplname', 'tmplnamespace', 'tmplinit', 'tmpllexize'],
        }

        # Check if query's PRIMARY table (after FROM, before JOIN) is a missing table
        # Pattern: FROM [pg_catalog.]table_name [alias]
        # Use re.IGNORECASE since query_upper is uppercase but pattern has lowercase
        from_match = re.search(
            r'\bFROM\s+(?:PG_CATALOG\.)?(\w+)',
            query_upper
        )

        if from_match:
            primary_table = from_match.group(1).upper()  # Normalize to uppercase

            # Special case: if query contains pg_class, don't intercept for pg_inherits
            # This handles table queries that JOIN to pg_inherits
            if primary_table == 'PG_INHERITS' and 'PG_CLASS' in query_upper:
                return None

            if primary_table in MISSING_PRIMARY_TABLES:
                # This is a query with a missing primary table - return empty
                columns = MISSING_PRIMARY_TABLES[primary_table]
                extracted = self._expected_result_columns(query)
                # Only override with extracted columns if it's not just ['*']
                # SELECT * should use the predefined columns, not literal '*'
                if extracted and extracted != ['*']:
                    columns = extracted
                return pd.DataFrame(columns=columns)

        return None

    def _rewrite_missing_table_joins(self, query: str) -> str:
        """
        Rewrite queries to handle LEFT JOINs to missing pg_catalog tables.

        When a query has a LEFT JOIN to a table that doesn't exist in DuckDB
        (like pg_shdescription), we remove the JOIN and replace column references
        with NULL values.
        """
        import re

        def _sql_comment_spans(sql: str):
            """
            Return a list of (start, end) spans that are within SQL comments.

            Handles:
            - Line comments: -- ... \n
            - Block comments: /* ... */ (best-effort, supports nesting)
            Skips comment markers that appear inside single/double-quoted strings.
            """
            spans = []
            i = 0
            in_single = False
            in_double = False
            line_start = None
            block_start = None
            block_depth = 0

            while i < len(sql):
                # Line comment
                if line_start is not None:
                    if sql[i] == '\n':
                        spans.append((line_start, i))
                        line_start = None
                    i += 1
                    continue

                # Block comment (supports nesting)
                if block_depth > 0:
                    if not in_single and not in_double and sql.startswith('/*', i):
                        block_depth += 1
                        i += 2
                        continue
                    if not in_single and not in_double and sql.startswith('*/', i):
                        block_depth -= 1
                        i += 2
                        if block_depth == 0 and block_start is not None:
                            spans.append((block_start, i))
                            block_start = None
                        continue
                    i += 1
                    continue

                # Not in comment: detect comment starts (only when not in quotes)
                if not in_single and not in_double:
                    if sql.startswith('--', i):
                        line_start = i
                        i += 2
                        continue
                    if sql.startswith('/*', i):
                        block_start = i
                        block_depth = 1
                        i += 2
                        continue

                # Quotes
                ch = sql[i]
                if ch == "'" and not in_double:
                    # Postgres-style escaping for single quotes: ''
                    if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                        i += 2
                        continue
                    in_single = not in_single
                    i += 1
                    continue
                if ch == '"' and not in_single:
                    in_double = not in_double
                    i += 1
                    continue

                i += 1

            if line_start is not None:
                spans.append((line_start, len(sql)))
            if block_depth > 0 and block_start is not None:
                spans.append((block_start, len(sql)))

            return spans

        def _pos_in_spans(pos: int, spans) -> bool:
            return any(start <= pos < end for start, end in spans)

        # Tables that might appear in JOINs but don't exist in DuckDB
        # This list should match MISSING_PRIMARY_TABLES keys (lowercased)
        MISSING_JOIN_TABLES = [
            # Core missing tables
            'pg_description',
            'pg_shdescription',
            'pg_stat_activity',
            'pg_inherits',
            # Monitoring/stats tables
            'pg_locks',
            'pg_stat_statements',
            'pg_stat_user_tables',
            'pg_stat_user_indexes',
            'pg_statio_user_tables',
            # Replication tables
            'pg_replication_slots',
            'pg_publication',
            'pg_subscription',
            # Statistics tables
            'pg_statistic',
            'pg_statistic_ext',
            # Policy/rules tables
            'pg_policies',
            'pg_policy',
            'pg_rules',
            # Config tables
            'pg_hba_file_rules',
            'pg_file_settings',
            # Auth tables
            'pg_auth_members',
            'pg_roles',
            # Event/trigger tables
            'pg_event_trigger',
            'pg_trigger',
            'pg_rewrite',
            # Foreign data tables
            'pg_foreign_data_wrapper',
            'pg_foreign_server',
            'pg_foreign_table',
            # Extension/language tables
            'pg_extension',
            'pg_language',
            # Type/operator tables
            'pg_cast',
            'pg_collation',
            'pg_operator',
            'pg_opclass',
            'pg_opfamily',
            'pg_aggregate',
            'pg_conversion',
            # NOTE: pg_enum removed - DuckDB 1.4.2+ has it built-in
            'pg_range',
            # Access method tables
            'pg_am',
            'pg_amop',
            'pg_amproc',
            # Partitioning
            'pg_partitioned_table',
            # Security labels
            'pg_seclabel',
            'pg_shseclabel',
            # Text search tables
            'pg_ts_config',
            'pg_ts_dict',
            'pg_ts_parser',
            'pg_ts_template',
        ]

        result = query

        # Debug: Check if this is the pg_class table query
        # if 'PG_CLASS' in query.upper() and 'RELKIND' in query.upper() and 'RELNAMESPACE' in query.upper():
        #     print(f"[DEBUG] _rewrite_missing_table_joins: pg_class query BEFORE rewrite:")
        #     # for i, line in enumerate(query.split('\n'), 1):
        #     #     if line.strip():
        #     #         print(f"[DEBUG]   Line {i}: {line.strip()[:80]}")
        #     print(f"[DEBUG]   WHERE in original: {'WHERE' in query.upper()}")

        for table in MISSING_JOIN_TABLES:
            # Two-phase approach: first find the LEFT JOIN start, then find ON condition end
            # This handles nested parentheses correctly
            join_pattern = rf'''(?ix)
                \s+LEFT\s+(?:OUTER\s+)?JOIN\s+
                (?:pg_catalog\.)?{table}\s+
                (?:AS\s+)?                    # Optional AS keyword
                ([a-zA-Z_][a-zA-Z0-9_]*)      # Capture alias
                \s+ON\s+
            '''
            join_re = re.compile(join_pattern, flags=re.IGNORECASE | re.VERBOSE)
            search_from = 0

            while True:
                match = join_re.search(result, search_from)
                if not match:
                    break

                # DataGrip often includes commented-out JOINs like:
                #   ... amcanorder /* left join pg_catalog.pg_am am on ... */ ...
                # The old rewriter could match inside the block comment and remove the closing "*/",
                # leaving an unterminated comment and causing DuckDB parse errors.
                comment_spans = _sql_comment_spans(result)
                if _pos_in_spans(match.start(), comment_spans):
                    search_from = match.end()
                    continue

                alias = match.group(1)
                join_start = match.start()
                on_start = match.end()  # Position right after "ON "

                # Now find where the ON condition ends
                # It ends at: WHERE, ORDER BY, GROUP BY, LIMIT, another JOIN, or end of query
                # But we need to handle nested parentheses in the ON condition

                # If ON condition starts with (, find matching )
                if on_start < len(result) and result[on_start] == '(':
                    # Find matching closing paren with proper nesting
                    paren_count = 1
                    pos = on_start + 1
                    while pos < len(result) and paren_count > 0:
                        if result[pos] == '(':
                            paren_count += 1
                        elif result[pos] == ')':
                            paren_count -= 1
                        pos += 1
                    on_end = pos  # Position after the closing )
                else:
                    # ON condition without parens - find end by looking for keywords
                    # Match until WHERE, ORDER, GROUP, HAVING, LIMIT, another JOIN, or end
                    rest = result[on_start:]
                    end_match = re.search(
                        r'(?i)\s+(?:WHERE|ORDER\s+BY|GROUP\s+BY|HAVING|LIMIT|OFFSET|'
                        r'LEFT\s+(?:OUTER\s+)?JOIN|RIGHT\s+(?:OUTER\s+)?JOIN|'
                        r'INNER\s+JOIN|FULL\s+(?:OUTER\s+)?JOIN|CROSS\s+JOIN|JOIN)\b',
                        rest
                    )
                    if end_match:
                        on_end = on_start + end_match.start()
                    else:
                        on_end = len(result)

                # Extract what we're removing for debugging
                matched_text = result[join_start:on_end]
                # print(f"[DEBUG] _rewrite_missing_table_joins: Removing LEFT JOIN to {table}")
                # print(f"[DEBUG]   Alias: {alias}")
                # print(f"[DEBUG]   Matched ({len(matched_text)} chars): {matched_text[:200]}{'...' if len(matched_text) > 200 else ''}")

                # Remove the entire LEFT JOIN clause
                result = result[:join_start] + ' ' + result[on_end:]

                # Replace column references like D.description with NULL
                # Be careful to only replace the alias, not table names
                result = re.sub(rf'\b{alias}\.(\w+)\b', 'NULL', result, flags=re.IGNORECASE)
                #print(f"[DEBUG]   Alias '{alias}' column refs replaced with NULL")
                # Continue scanning for additional JOINs to the same missing table (if any)
                search_from = 0

        # Debug: Check if this is the pg_class table query
        # if 'PG_CLASS' in query.upper() and 'RELKIND' in query.upper() and 'RELNAMESPACE' in query.upper():
        #     print(f"[DEBUG] _rewrite_missing_table_joins: pg_class query AFTER rewrite:")
        #     # for i, line in enumerate(result.split('\n'), 1):
        #     #     if line.strip():
        #     #         print(f"[DEBUG]   Line {i}: {line.strip()[:80]}")
        #     print(f"[DEBUG]   WHERE in result: {'WHERE' in result.upper()}")

        # Debug: show if WHERE clause is present
        # if 'WHERE' in query.upper() and 'WHERE' not in result.upper():
        #     print(f"[DEBUG] WARNING: WHERE clause was lost during JOIN rewriting!")
        #     print(f"[DEBUG]   Original had WHERE at position: {query.upper().find('WHERE')}")
        #     # Show what was around the WHERE
        #     where_pos = query.upper().find('WHERE')
        #     print(f"[DEBUG]   Context around WHERE: ...{query[max(0,where_pos-50):where_pos+50]}...")

        return result

    def _strip_union_parts_with_missing_tables(self, query: str) -> str:
        """
        Remove UNION/UNION ALL parts that reference missing pg_catalog tables.

        For queries like:
            SELECT ... FROM pg_description JOIN pg_class ...
            UNION ALL
            SELECT ... FROM pg_description JOIN pg_trigger ...  -- missing!
            UNION ALL
            SELECT ... FROM pg_description JOIN pg_proc ...

        This removes the pg_trigger part entirely.
        """
        import re

        # Tables that DuckDB doesn't have (used in regular JOINs)
        # NOTE: pg_enum removed - DuckDB 1.4.2+ has it built-in
        MISSING_TABLES = {
            'pg_trigger', 'pg_rewrite', 'pg_policy', 'pg_policies', 'pg_rules',
            'pg_operator', 'pg_opclass', 'pg_opfamily', 'pg_aggregate',
            'pg_cast', 'pg_collation', 'pg_conversion', 'pg_range',
            'pg_extension', 'pg_language', 'pg_foreign_data_wrapper',
            'pg_foreign_server', 'pg_foreign_table', 'pg_event_trigger',
            'pg_publication', 'pg_subscription', 'pg_replication_slots',
            'pg_locks', 'pg_stat_statements', 'pg_stat_user_tables',
            'pg_stat_user_indexes', 'pg_statio_user_tables',
            'pg_statistic', 'pg_statistic_ext', 'pg_inherits',
            'pg_partitioned_table', 'pg_seclabel', 'pg_shseclabel',
            'pg_ts_config', 'pg_ts_dict', 'pg_ts_parser', 'pg_ts_template',
            'pg_am', 'pg_amop', 'pg_amproc', 'pg_roles', 'pg_auth_members',
            'pg_hba_file_rules', 'pg_file_settings', 'pg_description',
            'pg_shdescription', 'pg_stat_activity',
        }

        # Only process if query has UNION
        if 'UNION' not in query.upper():
            return query

        # Split by UNION ALL or UNION (case-insensitive)
        # We need to be careful not to split inside subqueries
        parts = []
        current_part = []
        paren_depth = 0
        tokens = re.split(r'(\bUNION\s+ALL\b|\bUNION\b)', query, flags=re.IGNORECASE)

        i = 0
        while i < len(tokens):
            token = tokens[i]
            token_upper = token.upper().strip()

            if token_upper in ('UNION ALL', 'UNION'):
                # Check if we're inside parentheses
                current_text = ''.join(current_part)
                paren_depth = current_text.count('(') - current_text.count(')')
                if paren_depth == 0:
                    # Not inside parens, this is a real UNION
                    parts.append(''.join(current_part))
                    current_part = []
                else:
                    # Inside parens, keep it
                    current_part.append(token)
            else:
                current_part.append(token)
            i += 1

        # Add the last part
        if current_part:
            parts.append(''.join(current_part))

        if len(parts) <= 1:
            # No UNION splitting happened
            return query

        # Filter out parts that reference missing tables
        filtered_parts = []
        removed_count = 0
        for part in parts:
            part_lower = part.lower()
            has_missing = False
            for table in MISSING_TABLES:
                # Check for JOIN to this table (not just any reference)
                # Pattern: JOIN [pg_catalog.]table_name
                if re.search(rf'\bjoin\s+(?:pg_catalog\.)?{table}\b', part_lower):
                    has_missing = True
                    removed_count += 1
                    break
            if not has_missing:
                filtered_parts.append(part)

        # if removed_count > 0:
        #     print(f"[DEBUG] _strip_union_parts: Removed {removed_count} UNION parts with missing tables")

        if not filtered_parts:
            # All parts had missing tables - return a minimal valid query
            # that matches the structure but returns no rows
            #print(f"[DEBUG] _strip_union_parts: All UNION parts had missing tables, returning first part with FALSE condition")
            # Take first part and add WHERE FALSE
            first_part = parts[0].strip()
            if 'WHERE' in first_part.upper():
                return re.sub(r'\bWHERE\b', 'WHERE FALSE AND', first_part, count=1, flags=re.IGNORECASE)
            else:
                # Add WHERE FALSE before ORDER BY, GROUP BY, or at end
                for keyword in ['ORDER BY', 'GROUP BY', 'HAVING', 'LIMIT']:
                    if keyword in first_part.upper():
                        pos = first_part.upper().find(keyword)
                        return first_part[:pos] + ' WHERE FALSE ' + first_part[pos:]
                return first_part + ' WHERE FALSE'

        # Reconstruct with UNION ALL
        result = ' UNION ALL '.join(p.strip() for p in filtered_parts)
        return result

    def _rewrite_pg_inherits_subqueries(self, query: str) -> str:
        """
        Replace correlated subqueries to pg_inherits with NULL.

        DataGrip's table introspection queries include subqueries like:
        (SELECT string_agg(inhparent::regclass::varchar, ', ' ORDER BY inhrelid)
         FROM pg_catalog.pg_inherits WHERE inhrelid = T.oid)

        DuckDB doesn't support ORDER BY inside string_agg, and pg_inherits
        is empty anyway, so we replace the entire subquery with NULL.
        """
        import re

        # Find all occurrences of "FROM pg_catalog.pg_inherits" or "FROM pg_inherits"
        # and replace the enclosing parenthesized subquery with NULL
        result = query
        search_patterns = [
            r'from\s+pg_catalog\.pg_inherits\b',
            r'from\s+pg_inherits\b'
        ]

        has_pg_inherits = 'pg_inherits' in query.lower()
        # if has_pg_inherits:
        #     print(f"[DEBUG] _rewrite_pg_inherits_subqueries: Found pg_inherits in query")

        for search_pattern in search_patterns:
            while True:
                match = re.search(search_pattern, result, re.IGNORECASE)
                if not match:
                    break

                # Find the opening paren of this subquery by scanning backwards
                pos = match.start()
                paren_count = 0
                start_pos = None

                # Scan backwards to find the opening paren with SELECT
                for i in range(pos - 1, -1, -1):
                    if result[i] == ')':
                        paren_count += 1
                    elif result[i] == '(':
                        if paren_count == 0:
                            # Check if this is a SELECT subquery
                            after_paren = result[i+1:pos].strip().upper()
                            if after_paren.startswith('SELECT'):
                                start_pos = i
                                break
                        else:
                            paren_count -= 1

                if start_pos is None:
                    # Couldn't find opening paren, skip this match
                    break

                # Find the closing paren by scanning forwards
                paren_count = 1
                end_pos = None
                for i in range(start_pos + 1, len(result)):
                    if result[i] == '(':
                        paren_count += 1
                    elif result[i] == ')':
                        paren_count -= 1
                        if paren_count == 0:
                            end_pos = i
                            break

                if end_pos is None:
                    # Couldn't find closing paren, skip
                    #print(f"[DEBUG] _rewrite_pg_inherits_subqueries: Could not find closing paren")
                    break

                # Replace the subquery with NULL or empty subquery depending on context
                old_subquery = result[start_pos:end_pos + 1]
                #print(f"[DEBUG] _rewrite_pg_inherits_subqueries: Replacing subquery: {old_subquery[:80]}...")

                # Check if this subquery is used with IN/NOT IN/EXISTS (need valid subquery, not scalar)
                # Look at the 30 chars before the subquery
                prefix = result[max(0, start_pos - 30):start_pos].upper()
                if ' IN' in prefix or 'IN(' in prefix.replace(' ', '') or 'EXISTS' in prefix:
                    # Replace with empty subquery for IN/NOT IN/EXISTS clauses
                    replacement = "(SELECT NULL WHERE FALSE)"
                    #print(f"[DEBUG] Using empty subquery replacement (context: ...{prefix[-20:]})")
                else:
                    # Replace with NULL scalar for SELECT list columns
                    replacement = "NULL::VARCHAR"
                    #print(f"[DEBUG] Using NULL::VARCHAR replacement (context: ...{prefix[-20:]})")

                result = result[:start_pos] + replacement + result[end_pos + 1:]

        if has_pg_inherits and 'pg_inherits' not in result.lower():
            #print(f"[DEBUG] _rewrite_pg_inherits_subqueries: Successfully removed all pg_inherits references")
            # Print full query to see the structure - split into lines for analysis
            lines = result.split('\n')
            #print(f"[DEBUG] Rewritten query has {len(lines)} lines:")
            # for i, line in enumerate(lines, 1):
            #     print(f"[DEBUG]   Line {i}: {line[:120]}{'...' if len(line) > 120 else ''}")
        elif has_pg_inherits:
            self._runtime_log(
                "WARN",
                "pg_inherits rewrite incomplete (reference still present)",
                event="pg_inherits_rewrite_incomplete",
                query_preview=result[:500],
            )

        return result

    def _rewrite_missing_pg_database_columns(self, query: str) -> str:
        """
        Rewrite queries that reference pg_database columns not in DuckDB.

        DuckDB's pg_database only has: oid, datname
        PostgreSQL has many more columns that clients query.
        """
        import re

        # Map of missing pg_database columns to their default values
        MISSING_COLUMNS = {
            'datistemplate': 'false',
            'datallowconn': 'true',
            'datconnlimit': '-1',
            'datlastsysoid': '0',
            'datfrozenxid': '0',
            'datminmxid': '0',
            'dattablespace': '0',
            'datacl': 'NULL',
            'datcollate': "'en_US.UTF-8'",
            'datctype': "'en_US.UTF-8'",
            'datdba': '1',  # OID of owner
        }

        result = query
        for col, default in MISSING_COLUMNS.items():
            # Replace column reference with default value (preserve alias if any)
            # Pattern: N.datistemplate or datistemplate (standalone)
            result = re.sub(rf'(?i)\b(\w+\.)?{col}\b', default, result)

        return result

    @staticmethod
    def _rewrite_pg_get_expr_calls(query: str) -> str:
        """
        Replace pg_get_expr(...) calls with NULL::VARCHAR.

        DuckDB's macro system doesn't support overloading, and pg_get_expr is used
        to decompile partition expressions which DuckDB doesn't have anyway.
        Replace all pg_get_expr calls (2 or 3 args) with NULL.
        """
        import re

        # Match pg_get_expr(arg1, arg2) or pg_get_expr(arg1, arg2, arg3)
        # Also match pg_catalog.pg_get_expr(...)
        # Use a recursive approach to handle nested parentheses
        pattern = r'(?i)(?:pg_catalog\.)?pg_get_expr\s*\('

        result = query
        while True:
            match = re.search(pattern, result)
            if not match:
                break

            start_pos = match.start()
            paren_start = match.end() - 1  # Position of opening paren

            # Find the matching closing paren
            paren_count = 1
            end_pos = None
            for i in range(paren_start + 1, len(result)):
                if result[i] == '(':
                    paren_count += 1
                elif result[i] == ')':
                    paren_count -= 1
                    if paren_count == 0:
                        end_pos = i
                        break

            if end_pos is None:
                # Couldn't find closing paren, abort
                break

            # Replace the entire pg_get_expr(...) call with NULL::VARCHAR
            result = result[:start_pos] + 'NULL::VARCHAR' + result[end_pos + 1:]

        return result

    def _rewrite_information_schema_catalog_filters(self, query: str) -> str:
        """
        Restrict `information_schema` catalog views to the current DuckDB database.

        DuckDB's information_schema.* surfaces attached database catalogs, which can confuse
        PostgreSQL clients (DataGrip shows them as FDW/foreign catalogs). Postgres exposes only
        the connected database, so we filter these queries to:
        - The current DuckDB catalog (session database)

        We explicitly exclude internal catalogs (those starting with __).
        """
        import re

        catalog = self._duckdb_catalog_name
        if not catalog:
            return query

        def inject(table_ref: str, catalog_col: str) -> str:
            nonlocal query

            m = re.search(
                rf'(?is)\bfrom\s+({re.escape(table_ref)})(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?',
                query,
            )
            if not m:
                return query

            table_ref_end = m.end(1)
            alias_take = m.group(2)
            reserved = {
                'where',
                'order',
                'group',
                'having',
                'limit',
                'offset',
                'fetch',
                'union',
                'join',
                'left',
                'right',
                'inner',
                'full',
                'cross',
            }

            alias = alias_take if alias_take and alias_take.lower() not in reserved else None
            from_end = m.end(0) if alias else table_ref_end

            qualifier = f"{alias}.{catalog_col}" if alias else catalog_col
            escaped_catalog = catalog.replace("'", "''")
            # Include current catalog only, exclude internal catalogs (__ prefix)
            # Note: Use LIKE with ESCAPE to treat underscores literally
            cond = f"{qualifier} = '{escaped_catalog}' AND {qualifier} NOT LIKE '!_!_%' ESCAPE '!'"

            # Find WHERE after the FROM match (avoid CTE/subquery WHEREs earlier in the SQL)
            after_from = query[from_end:]
            w = re.search(r'(?is)\bwhere\b', after_from)
            if w:
                insert_at = from_end + w.end()
                query = query[:insert_at] + f" ({cond}) AND" + query[insert_at:]
                return query

            # Insert WHERE before ORDER/GROUP/HAVING/LIMIT/OFFSET/FETCH if present
            tail = after_from
            k = re.search(r'(?is)\b(order\s+by|group\s+by|having|limit|offset|fetch)\b', tail)
            if k:
                insert_at = from_end + k.start()
                query = query[:insert_at] + f" WHERE {cond} " + query[insert_at:]
                return query

            query = query.rstrip() + f" WHERE {cond}"
            return query

        # Apply to common info_schema views used for introspection
        inject('information_schema.schemata', 'catalog_name')
        inject('information_schema.tables', 'table_catalog')
        inject('information_schema.columns', 'table_catalog')
        return query

    def _refresh_attached_view_cache(self) -> None:
        """
        Refresh view exposure for any newly ATTACH'd databases.

        Lazy ATTACH can occur outside explicit ATTACH commands; detect and rebuild
        exposure views when the set of attached DBs changes.
        """
        try:
            current = self.duckdb_conn.execute(
                """
                SELECT database_name
                FROM duckdb_databases()
                WHERE NOT internal
                """
            ).fetchall()
            names = {r[0] for r in current}
        except Exception:
            return

        if names != self._last_attached_db_names:
            self._last_attached_db_names = names
            self._create_attached_db_views()

    @staticmethod
    def _extract_top_level_select_list(query: str) -> Optional[str]:
        """
        Extract the top-level SELECT list (text between SELECT and FROM) for simple parsing.

        Best-effort: handles parentheses, quotes, and block/line comments well enough for
        typical client catalog queries.
        """
        sql = query.strip().rstrip(';')
        lower = sql.lower()

        in_single = False
        in_double = False
        depth = 0
        i = 0
        select_start = None

        def is_word_boundary(idx: int) -> bool:
            if idx <= 0:
                return True
            return not (lower[idx - 1].isalnum() or lower[idx - 1] == '_')

        while i < len(sql):
            ch = sql[i]

            # Comments (only when not in quotes)
            if not in_single and not in_double:
                if sql.startswith('/*', i):
                    end = sql.find('*/', i + 2)
                    i = len(sql) if end == -1 else end + 2
                    continue
                if sql.startswith('--', i):
                    end = sql.find('\n', i + 2)
                    i = len(sql) if end == -1 else end + 1
                    continue

            # Quotes
            if ch == "'" and not in_double:
                if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                    i += 2
                    continue
                in_single = not in_single
                i += 1
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                i += 1
                continue

            if in_single or in_double:
                i += 1
                continue

            # Parens
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)

            # Find top-level SELECT, then top-level FROM
            if depth == 0:
                if select_start is None and lower.startswith('select', i) and is_word_boundary(i):
                    select_start = i + 6
                    i += 6
                    continue
                if select_start is not None and lower.startswith('from', i) and is_word_boundary(i):
                    return sql[select_start:i].strip()

            i += 1

        # SELECT without FROM (common for client probe queries)
        if select_start is not None:
            return sql[select_start:].strip()

        return None

    @staticmethod
    def _split_top_level_commas(select_list: str) -> list[str]:
        items: list[str] = []
        current: list[str] = []
        in_single = False
        in_double = False
        depth = 0
        i = 0
        while i < len(select_list):
            ch = select_list[i]

            # Comments (only when not in quotes)
            if not in_single and not in_double:
                if select_list.startswith('/*', i):
                    end = select_list.find('*/', i + 2)
                    i = len(select_list) if end == -1 else end + 2
                    continue
                if select_list.startswith('--', i):
                    end = select_list.find('\n', i + 2)
                    i = len(select_list) if end == -1 else end + 1
                    continue

            if ch == "'" and not in_double:
                if in_single and i + 1 < len(select_list) and select_list[i + 1] == "'":
                    current.append("''")
                    i += 2
                    continue
                in_single = not in_single
                current.append(ch)
                i += 1
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                current.append(ch)
                i += 1
                continue

            if in_single or in_double:
                current.append(ch)
                i += 1
                continue

            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)

            if ch == ',' and depth == 0:
                item = ''.join(current).strip()
                if item:
                    items.append(item)
                current = []
                i += 1
                continue

            current.append(ch)
            i += 1

        tail = ''.join(current).strip()
        if tail:
            items.append(tail)
        return items

    @staticmethod
    def _infer_select_item_output_name(select_item: str) -> str:
        """
        Infer the output column name for a single SELECT item.

        Examples:
          - "N.oid::bigint as id" -> "id"
          - "rolsuper is_super"   -> "is_super"
          - "D.description"       -> "description"
          - "current_user"        -> "current_user"
        """
        import re

        item = select_item.strip()
        # Normalize whitespace
        item = re.sub(r'\s+', ' ', item)

        # Prefer explicit AS alias
        m = re.search(r'(?i)\s+as\s+(".*?"|[a-zA-Z_][a-zA-Z0-9_]*)\s*$', item)
        if m:
            alias = m.group(1)
            return alias[1:-1] if alias.startswith('"') and alias.endswith('"') else alias

        # Alias without AS: last token if more than one token
        tokens = item.split(' ')
        if len(tokens) >= 2:
            alias = tokens[-1]
            return alias[1:-1] if alias.startswith('"') and alias.endswith('"') else alias

        # No alias: derive from expression
        expr = tokens[0]
        expr = expr.strip()

        # Strip casts suffixes
        expr = re.sub(r'::[a-zA-Z_][a-zA-Z0-9_]*(?:\\(.*?\\))?$', '', expr)

        # Unwrap simple schema/table qualification
        if '.' in expr:
            expr = expr.split('.')[-1]

        # Function call name
        if expr.endswith(')') and '(' in expr:
            expr = expr[:expr.find('(')]

        return expr.strip('"')

    def _expected_result_columns(self, query: str) -> Optional[list[str]]:
        select_list = self._extract_top_level_select_list(query)
        if not select_list:
            return None
        items = self._split_top_level_commas(select_list)
        if not items:
            return None
        return [self._infer_select_item_output_name(item) for item in items]

    @staticmethod
    def _empty_df_for_columns(columns: list[str]):
        import pandas as pd

        def dtype_for(col: str):
            name = col.strip('"').lower()
            if name in {'id', 'oid', 'object_id', 'transaction_id', 'role_id', 'usesysid'} or name.endswith('_id'):
                return 'int64'
            if name.startswith('is_') or name.startswith('has_') or name.endswith('_option') or name in {
                'allow_connections', 'is_template', 'usesuper', 'usecreatedb'
            }:
                return 'bool'
            return 'object'

        return pd.DataFrame({c: pd.Series([], dtype=dtype_for(c)) for c in columns})

    def _validate_custom_handler_columns(self, portal_name: str, actual_col_count: int, handler_name: str) -> bool:
        """
        Validate that a custom Execute handler returns the same column count as Describe.
        Returns True if columns match or if validation cannot be performed, False if mismatch.
        """
        if portal_name not in self.portals:
            return True
        portal = self.portals[portal_name]
        described_col_count = portal.get('described_columns')
        if described_col_count is None:
            return True
        if described_col_count != actual_col_count:
            self._runtime_log(
                "WARN",
                f"{handler_name}: Column count mismatch (described {described_col_count}, returning {actual_col_count})",
                event="execute_handler_column_mismatch",
                portal_name=portal_name,
                handler_name=handler_name,
                described_columns=described_col_count,
                actual_columns=actual_col_count,
            )
            return False
        return True

    @staticmethod
    def _is_datagrip_pg_class_table_browser_union(query_upper: str) -> bool:
        """
        Detect DataGrip's "pg_class table browser" UNION ALL query used to enumerate objects.

        DataGrip runs a single UNION ALL query across multiple pg_catalog tables (pg_class,
        pg_type, pg_collation, pg_operator, pg_opclass, pg_opfamily, pg_proc) filtered by a
        list of schema OIDs. DuckDB lacks some of these tables, so the UNION needs special
        handling to avoid failing (or being short-circuited to empty).
        """
        if 'UNION ALL' not in query_upper:
            return False
        if 'FROM PG_CATALOG.PG_CLASS' not in query_upper and 'FROM PG_CLASS' not in query_upper:
            return False
        # Ensure it's the object browser union (includes pg_type + pg_proc branches).
        if 'PG_CATALOG.PG_TYPE' not in query_upper and 'FROM PG_TYPE' not in query_upper:
            return False
        if 'PG_CATALOG.PG_PROC' not in query_upper and 'FROM PG_PROC' not in query_upper:
            return False
        # DataGrip aliases the namespace as schemaId and emits a kind discriminator.
        return ('SCHEMAID' in query_upper) and (' KIND' in query_upper or '\nKIND' in query_upper)

    @staticmethod
    def _primary_from_table(query_upper: str) -> Optional[str]:
        import re

        from_match = re.search(r'\bFROM\s+(?:PG_CATALOG\.)?(\w+)', query_upper)
        if not from_match:
            return None
        return from_match.group(1).upper()

    def _build_datagrip_pg_class_table_browser_union_result(self, query: str, params: list):
        import pandas as pd
        import re

        expected_cols = self._expected_result_columns(query) or ['oid', 'schemaId', 'kind']
        if not params:
            return pd.DataFrame(columns=expected_cols)

        query_upper = query.upper()
        namespace_groups = re.findall(
            r'\b(?:RELNAMESPACE|TYPNAMESPACE|COLLNAMESPACE|OPRNAMESPACE|OPCNAMESPACE|OPFNAMESPACE|PRONAMESPACE)\b\s+IN\s*\(',
            query_upper,
        )
        group_count = len(namespace_groups)
        if group_count > 0 and len(params) % group_count == 0:
            group_size = len(params) // group_count
            schema_params = params[:group_size]
        else:
            schema_params = params

        schema_ids: list[int] = []
        seen: set[int] = set()
        for v in schema_params:
            if v is None:
                continue
            try:
                i = int(v)
            except Exception:
                continue
            if i not in seen:
                seen.add(i)
                schema_ids.append(i)

        if not schema_ids:
            return pd.DataFrame(columns=expected_cols)

        placeholders = ','.join(['?'] * len(schema_ids))

        def _norm(col: str) -> str:
            return col.strip().strip('"').lower()

        def _make_row(oid, schema_id, kind, name):
            row = {}
            for col in expected_cols:
                key = _norm(col)
                if key in {'oid', 'id'}:
                    row[col] = oid
                elif key in {
                    'schemaid',
                    'schema_id',
                    'namespace',
                    'relnamespace',
                    'typnamespace',
                    'pronamespace',
                    'collnamespace',
                    'oprnamespace',
                    'opcnamespace',
                    'opfnamespace',
                }:
                    row[col] = schema_id
                elif key == 'kind':
                    row[col] = kind
                elif key == 'name':
                    row[col] = name
                else:
                    row[col] = None
            return row

        rows = []

        # Relations (pg_class) - includes tables/views/sequences, with DataGrip's translate() mapping.
        # NOTE: DuckDB's pg_catalog.pg_class is EMPTY - synthesize from information_schema.tables
        try:
            rel_df = self.duckdb_conn.execute(
                f"""
                SELECT
                    ABS(hash(t.table_schema || '.' || t.table_name) % 2147483647)::INTEGER as oid,
                    COALESCE(n.oid, 0) as relnamespace,
                    CASE t.table_type
                        WHEN 'BASE TABLE' THEN 'r'
                        WHEN 'VIEW' THEN 'v'
                        WHEN 'LOCAL TEMPORARY' THEN 'r'
                        ELSE 'r'
                    END as relkind,
                    t.table_name as relname
                FROM information_schema.tables t
                LEFT JOIN pg_catalog.pg_namespace n ON n.nspname = t.table_schema
                WHERE n.oid IN ({placeholders})
                """,
                schema_ids,
            ).fetchdf()
        except Exception:
            rel_df = pd.DataFrame(columns=['oid', 'relnamespace', 'relkind', 'relname'])

        relkind_map = {'r': 'r', 'm': 'm', 'v': 'v', 'p': 'r', 'f': 'f', 'S': 'S', 's': 's'}
        for _, r in rel_df.iterrows():
            if pd.isna(r.get('oid')) or pd.isna(r.get('relnamespace')):
                continue
            oid = int(r['oid'])
            schema_id = int(r['relnamespace'])
            relkind = None if pd.isna(r.get('relkind')) else str(r.get('relkind'))
            kind = relkind_map.get(relkind, relkind)
            name = None if pd.isna(r.get('relname')) else str(r.get('relname'))
            rows.append(_make_row(oid, schema_id, kind, name))

        # Types (pg_type) - approximate DataGrip's filtering, avoiding PostgreSQL-only casts.
        try:
            type_df = self.duckdb_conn.execute(
                f"""
                SELECT
                    t.oid,
                    t.typnamespace,
                    t.typname,
                    t.typtype,
                    t.typcategory,
                    t.typelem,
                    t.typisdefined,
                    c.relkind AS relkind
                FROM pg_catalog.pg_type t
                LEFT JOIN pg_catalog.pg_class c ON t.typrelid = c.oid
                WHERE t.typnamespace IN ({placeholders})
                """,
                schema_ids,
            ).fetchdf()
        except Exception:
            type_df = pd.DataFrame(
                columns=['oid', 'typnamespace', 'typname', 'typtype', 'typcategory', 'typelem', 'typisdefined', 'relkind']
            )

        for _, r in type_df.iterrows():
            if pd.isna(r.get('oid')) or pd.isna(r.get('typnamespace')):
                continue
            oid = int(r['oid'])
            schema_id = int(r['typnamespace'])
            typtype = '' if pd.isna(r.get('typtype')) else str(r.get('typtype')).strip()
            typcategory = '' if pd.isna(r.get('typcategory')) else str(r.get('typcategory')).strip()
            relkind = '' if pd.isna(r.get('relkind')) else str(r.get('relkind')).strip()
            typelem_raw = r.get('typelem')
            typisdefined_raw = r.get('typisdefined')

            include = False
            if typtype in {'d', 'e'}:
                include = True
            elif relkind == 'c':
                include = True
            elif typtype == 'b':
                try:
                    typelem = 0 if pd.isna(typelem_raw) else int(typelem_raw)
                except Exception:
                    typelem = 0
                if typelem == 0 or typcategory != 'A':
                    include = True
            elif typtype == 'p':
                # Match DataGrip: include pseudo-types that are not defined.
                if pd.isna(typisdefined_raw) or (typisdefined_raw is False):
                    include = True

            if not include:
                continue

            name = None if pd.isna(r.get('typname')) else str(r.get('typname'))
            rows.append(_make_row(oid, schema_id, 'T', name))

        # Routines/Aggregates (pg_proc) - 'R' for routines, 'a' for aggregates.
        try:
            proc_df = self.duckdb_conn.execute(
                f"""
                SELECT oid, pronamespace, proname, prokind
                FROM pg_catalog.pg_proc
                WHERE pronamespace IN ({placeholders})
                """,
                schema_ids,
            ).fetchdf()
        except Exception:
            proc_df = pd.DataFrame(columns=['oid', 'pronamespace', 'proname', 'prokind'])

        for _, r in proc_df.iterrows():
            if pd.isna(r.get('oid')) or pd.isna(r.get('pronamespace')):
                continue
            oid = int(r['oid'])
            schema_id = int(r['pronamespace'])
            prokind = None if pd.isna(r.get('prokind')) else str(r.get('prokind')).strip()
            kind = 'a' if prokind == 'a' else 'R'
            name = None if pd.isna(r.get('proname')) else str(r.get('proname'))
            rows.append(_make_row(oid, schema_id, kind, name))

        result_df = pd.DataFrame(rows, columns=expected_cols)

        schema_col = next(
            (c for c in expected_cols if _norm(c) in {'schemaid', 'schema_id', 'namespace', 'relnamespace', 'typnamespace', 'pronamespace'}),
            None,
        )
        if schema_col and schema_col in result_df.columns:
            sort_cols = [schema_col]
            name_col = next((c for c in expected_cols if _norm(c) == 'name'), None)
            if name_col and name_col in result_df.columns:
                sort_cols.append(name_col)
            result_df = result_df.sort_values(sort_cols).reset_index(drop=True)

        return result_df

    def _pandas_dtype_to_clickhouse(self, dtype) -> str:
        """Convert pandas dtype to ClickHouse type."""
        dtype_str = str(dtype).lower()

        if 'int64' in dtype_str:
            return 'Int64'
        elif 'int32' in dtype_str:
            return 'Int32'
        elif 'int16' in dtype_str:
            return 'Int16'
        elif 'int8' in dtype_str:
            return 'Int8'
        elif 'uint64' in dtype_str:
            return 'UInt64'
        elif 'uint32' in dtype_str:
            return 'UInt32'
        elif 'uint16' in dtype_str:
            return 'UInt16'
        elif 'uint8' in dtype_str:
            return 'UInt8'
        elif 'float64' in dtype_str:
            return 'Float64'
        elif 'float32' in dtype_str:
            return 'Float32'
        elif 'bool' in dtype_str:
            return 'Bool'
        elif 'datetime64' in dtype_str:
            return 'DateTime64(6)'
        elif 'date' in dtype_str:
            return 'Date'
        elif 'timedelta' in dtype_str:
            return 'Int64'  # Store as microseconds
        else:
            return 'String'  # Default to String for object, category, etc.

    def _sanitize_column_name(self, name: str) -> str:
        """Sanitize column name for ClickHouse."""
        import re
        # Replace non-alphanumeric chars with underscore
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', str(name))
        # Ensure starts with letter or underscore
        if sanitized and sanitized[0].isdigit():
            sanitized = '_' + sanitized
        # Avoid empty names
        if not sanitized:
            sanitized = '_col'
        # Avoid SQL reserved keywords as column names
        reserved_keywords = {'NULL', 'TRUE', 'FALSE', 'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'TABLE', 'INDEX', 'ORDER', 'BY', 'GROUP', 'HAVING', 'LIMIT', 'OFFSET', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'ON', 'AS', 'IN', 'IS', 'LIKE', 'BETWEEN', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'UNION', 'ALL', 'DISTINCT', 'VALUES', 'SET', 'INTO', 'DEFAULT', 'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES', 'CONSTRAINT', 'CHECK', 'UNIQUE', 'AUTO_INCREMENT'}
        if sanitized.upper() in reserved_keywords:
            sanitized = f'col_{sanitized}'
        return sanitized

    def _maybe_materialize_result(self, query: str, result_df, query_id: str | None = None, caller_id: str | None = None):
        """
        Auto-materialize LARS query results for "query insurance".

        Stores results as parquet files organized by query fingerprint:
            $LARS_ROOT/data/results/{query_fingerprint}/{caller_id}.parquet

        This enables:
        - Historical query results grouped by "same" query shape
        - Deterministic file paths (derivable from sql_query_log)
        - UI integration for viewing past runs in /sql-trail

        Args:
            query: The original SQL query
            result_df: The pandas DataFrame result
            query_id: Optional query ID for naming (generated if not provided)
            caller_id: Optional caller_id for linking to sql_query_log

        Returns:
            Dict with result location info if materialized, None otherwise.
        """
        if result_df is None or len(result_df) == 0:
            return None
        
        if not caller_id:
            return None
        
        try:
            # Get query fingerprint
            from ..sql_trail import get_query_fingerprint
            query_fingerprint = get_query_fingerprint(query)
            
            if not query_fingerprint:
                return None
            
            # Store the result
            from ..result_store import store_result
            return store_result(
                df=result_df,
                query_fingerprint=query_fingerprint,
                caller_id=caller_id,
                query_preview=query[:200] if query else "",
            )
            
        except Exception as e:
            # Non-blocking - log and continue
            self._runtime_log(
                "DEBUG",
                f"Result materialization failed: {e}",
                event="result_store_error",
            )
            return None
        
        # --- Original implementation below (kept for reference) ---
        import json
        import re
        from datetime import datetime

        # Skip if empty results
        if result_df is None or len(result_df) == 0:
            return None

        # Skip if results are too large (configurable threshold)
        max_rows = 100000  # Could make this configurable
        if len(result_df) > max_rows:
            self._runtime_log(
                "DEBUG",
                f"Skipping auto-materialize: {len(result_df)} rows > {max_rows} limit",
                event="query_insurance_skip_large",
                query_id=query_id,
                caller_id=caller_id,
                row_count=len(result_df),
                max_rows=max_rows,
            )
            return None

        result_location = None

        try:
            # Generate query ID if not provided
            if not query_id:
                query_id = uuid.uuid4().hex[:12]
            else:
                # Use last 12 chars of existing query_id
                query_id = query_id[-12:] if len(query_id) > 12 else query_id

            # Use caller_id if provided, otherwise generate one
            effective_caller_id = caller_id or f"sql-{query_id}"

            # Sanitize caller_id for table name (alphanumeric + underscore only)
            safe_table_suffix = re.sub(r'[^a-zA-Z0-9]', '_', effective_caller_id)
            result_table_name = f"r_{safe_table_suffix}"

            # === PRIMARY: Create actual table in ClickHouse ===
            try:
                from ..db_adapter import get_db
                db = get_db()

                # Build column definitions
                columns = list(result_df.columns)
                sanitized_columns = [self._sanitize_column_name(c) for c in columns]
                column_types = [self._pandas_dtype_to_clickhouse(result_df[col].dtype) for col in columns]

                # Create column spec for CREATE TABLE
                column_defs = []
                for san_col, ch_type in zip(sanitized_columns, column_types):
                    # Use Nullable for all columns to handle None values
                    column_defs.append(f"`{san_col}` Nullable({ch_type})")

                columns_sql = ",\n    ".join(column_defs)

                # Drop existing table if exists (result tables are ephemeral)
                drop_sql = f"DROP TABLE IF EXISTS lars_results.{result_table_name}"
                db.execute(drop_sql)

                # Create the result table
                create_sql = f"""
                    CREATE TABLE lars_results.{result_table_name} (
                        {columns_sql}
                    )
                    ENGINE = MergeTree()
                    ORDER BY tuple()
                """
                db.execute(create_sql)

                # Insert data row by row (for type safety)
                # Build INSERT statement with placeholders
                placeholders = ", ".join(["%s"] * len(columns))
                col_names = ", ".join([f"`{c}`" for c in sanitized_columns])

                # Prepare rows for insertion
                rows_to_insert = []
                for _, row in result_df.iterrows():
                    row_values = []
                    for val in row:
                        if val is None or (hasattr(val, '__class__') and val.__class__.__name__ == 'NaT'):
                            row_values.append(None)
                        elif hasattr(val, 'isoformat'):
                            row_values.append(val.isoformat())
                        elif isinstance(val, bytes):
                            row_values.append(val.hex())
                        elif hasattr(val, 'item'):  # numpy types
                            # .item() only works on single-element arrays
                            try:
                                row_values.append(val.item())
                            except ValueError:
                                # Multi-element array - convert to list
                                row_values.append(val.tolist() if hasattr(val, 'tolist') else list(val))
                        else:
                            row_values.append(val)
                    rows_to_insert.append(tuple(row_values))

                # Batch insert (ClickHouse is optimized for this)
                if rows_to_insert:
                    # Build VALUES clause
                    def format_value(v):
                        if v is None:
                            return 'NULL'
                        elif isinstance(v, str):
                            # Escape: backslash, single quote, and % (ClickHouse driver uses %-formatting)
                            return "'" + v.replace("\\", "\\\\").replace("'", "''").replace("%", "%%") + "'"
                        elif isinstance(v, bool):
                            return '1' if v else '0'
                        elif isinstance(v, float):
                            # Handle nan/inf - ClickHouse can't store these in numeric columns
                            import math
                            if math.isnan(v) or math.isinf(v):
                                return 'NULL'
                            return str(v)
                        elif isinstance(v, int):
                            return str(v)
                        elif isinstance(v, (dict, list)):
                            # Escape: backslash, single quote, and % (ClickHouse driver uses %-formatting)
                            return "'" + json.dumps(v).replace("\\", "\\\\").replace("'", "''").replace("%", "%%") + "'"
                        else:
                            # Escape: backslash, single quote, and % (ClickHouse driver uses %-formatting)
                            return "'" + str(v).replace("\\", "\\\\").replace("'", "''").replace("%", "%%") + "'"

                    # Insert in batches of 1000
                    batch_size = 1000
                    for i in range(0, len(rows_to_insert), batch_size):
                        batch = rows_to_insert[i:i + batch_size]
                        values_strs = []
                        for row_tuple in batch:
                            row_str = "(" + ", ".join(format_value(v) for v in row_tuple) + ")"
                            values_strs.append(row_str)

                        insert_sql = f"INSERT INTO lars_results.{result_table_name} ({col_names}) VALUES {', '.join(values_strs)}"
                        db.execute(insert_sql)

                # Log to query_results index table
                safe_caller_id = effective_caller_id.replace("'", "''")
                safe_query_id = query_id.replace("'", "''")
                safe_source_db = self.database_name.replace("'", "''")
                # Escape single quotes for SQL and % for Python string formatting (ClickHouse driver uses %)
                safe_query = query[:10000].replace("'", "''").replace("%", "%%")

                # Format arrays for ClickHouse
                columns_arr = "[" + ",".join(f"'{c.replace(chr(39), chr(39)+chr(39))}'" for c in sanitized_columns) + "]"
                types_arr = "[" + ",".join(f"'{t.replace(chr(39), chr(39)+chr(39))}'" for t in column_types) + "]"

                log_sql = f"""
                    INSERT INTO lars_results.query_results
                    (caller_id, query_id, result_table, columns, column_types, row_count, column_count, source_database, source_query)
                    VALUES (
                        '{safe_caller_id}',
                        '{safe_query_id}',
                        '{result_table_name}',
                        {columns_arr},
                        {types_arr},
                        {len(result_df)},
                        {len(columns)},
                        '{safe_source_db}',
                        '{safe_query}'
                    )
                """
                db.execute(log_sql)

                self._runtime_log(
                    "DEBUG",
                    f"Results materialized: lars_results.{result_table_name} ({len(result_df)} rows, {len(columns)} cols)",
                    event="query_insurance_materialized",
                    query_id=query_id,
                    caller_id=effective_caller_id,
                    result_table=result_table_name,
                    row_count=len(result_df),
                    column_count=len(columns),
                )

                result_location = {
                    'stored_in': 'clickhouse',
                    'result_table': result_table_name,
                    'caller_id': effective_caller_id,
                    'query_id': query_id,
                    'row_count': len(result_df),
                    'column_count': len(columns)
                }

            except Exception as ch_err:
                self._runtime_log(
                    "WARN",
                    f"ClickHouse storage failed: {ch_err}",
                    event="query_insurance_clickhouse_failed",
                    query_id=query_id,
                    caller_id=effective_caller_id,
                    error_type=type(ch_err).__name__,
                )
                if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                    import traceback
                    traceback.print_exc()
                # Continue to try DuckDB

            return result_location

        except Exception as e:
            # Non-fatal - log and continue
            self._runtime_log(
                "WARN",
                f"Auto-materialize failed: {e}",
                event="query_insurance_error",
                query_id=query_id,
                caller_id=caller_id,
                error_type=type(e).__name__,
            )
            if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                import traceback
                traceback.print_exc()
            return None

    def _extract_lars_hints(self, query: str) -> tuple:
        """
        Extract LARS hint comments from query.

        Hints are embedded as /*LARS:key=value*/ comments by the sql_rewriter.
        This method extracts them and returns a clean query for execution.

        Returns:
            (clean_query, hints_dict) where hints_dict contains extracted hints

        Example:
            Input:  "/*LARS:save_as=players*/ SELECT * FROM emails"
            Output: ("SELECT * FROM emails", {"save_as": "players"})
        """
        import re
        hints = {}

        # Match /*LARS:key=value*/ patterns
        # Value can be identifier or dotted identifier (schema.table)
        pattern = r'/\*LARS:(\w+)=([a-zA-Z_][a-zA-Z0-9_.]*)\*/'

        for match in re.finditer(pattern, query):
            hints[match.group(1)] = match.group(2)

        # Strip hint comments from query
        clean_query = re.sub(pattern, '', query).strip()

        return clean_query, hints

    def _save_result_as(self, name: str, result_df):
        """
        Save query result as a named table (arrow alias syntax).

        This creates a full table copy, not a view. The table persists
        in the session database for later reference.

        Args:
            name: Table name, optionally with schema (e.g., "players" or "enron.players")
            result_df: pandas DataFrame with query results

        Handles:
            - Simple names: "players" -> creates table in default schema
            - Dotted names: "enron.players" -> creates schema if needed, then table
        """
        if result_df is None or len(result_df) == 0:
            self._runtime_log(
                "DEBUG",
                "Arrow save skipped: empty result",
                event="arrow_save_skip_empty",
                name=name,
            )
            return

        try:
            # Parse schema.table or just table
            if '.' in name:
                schema, table = name.rsplit('.', 1)
                self.duckdb_conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                full_name = name
            else:
                full_name = name

            # Register DataFrame and create table
            # Use hash of name for temp table to avoid collisions
            temp_name = f"_lars_arrow_{hash(name) & 0xFFFFFF:06x}"
            self.duckdb_conn.register(temp_name, result_df)

            try:
                # Drop existing table if any, then create new one
                self.duckdb_conn.execute(f"DROP TABLE IF EXISTS {full_name}")
                self.duckdb_conn.execute(f"CREATE TABLE {full_name} AS SELECT * FROM {temp_name}")
                self._runtime_log(
                    "DEBUG",
                    f"Arrow saved: {full_name} ({len(result_df)} rows, {len(result_df.columns)} cols)",
                    event="arrow_save_complete",
                    name=full_name,
                    row_count=len(result_df),
                    column_count=len(result_df.columns),
                )
            finally:
                self.duckdb_conn.unregister(temp_name)

        except Exception as e:
            self._runtime_log(
                "WARN",
                f"Arrow save failed for '{name}': {e}",
                event="arrow_save_failed",
                name=name,
                error_type=type(e).__name__,
            )

    def _create_pg_catalog_views(self):
        """
        Create PostgreSQL-compatible catalog views in DuckDB session.

        This enables SQL editors (DBeaver, DataGrip) to discover:
        - Tables and views (pg_tables, pg_class)
        - Columns (pg_attribute)
        - Schemas (pg_namespace)
        - Data types (pg_type)

        Maps DuckDB's information_schema to PostgreSQL's pg_catalog.
        """
        self._runtime_log(
            "DEBUG",
            "Starting pg_catalog view creation...",
            event="pg_catalog_views_start",
        )
        try:
            # NOTE: DuckDB treats 'pg_catalog' as a reserved system schema
            # We create views in 'main' schema but query them as 'pg_catalog.xyz'
            # DuckDB will automatically search 'main' when 'pg_catalog' doesn't have the object

            # pg_namespace - Schemas/namespaces
            self._runtime_log("DEBUG", "Creating pg_namespace view...", event="pg_catalog_view_create", view="pg_namespace")
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_namespace AS
                SELECT 'main' as nspname, 0 as oid
                UNION ALL
                SELECT 'pg_catalog' as nspname, 0 as oid
                UNION ALL
                SELECT 'information_schema' as nspname, 0 as oid
                UNION ALL
                SELECT 'public' as nspname, 0 as oid
                UNION ALL
                SELECT DISTINCT
                    table_schema as nspname,
                    0 as oid
                FROM information_schema.tables
                WHERE table_schema NOT IN ('main', 'pg_catalog', 'information_schema', 'public')
            """)
            self._runtime_log("DEBUG", "pg_namespace created", event="pg_catalog_view_created", view="pg_namespace")

            # pg_class - Tables, views, sequences, indexes
            # NOTE: DuckDB's pg_catalog.pg_class is EMPTY - synthesize from information_schema.tables
            # Join with pg_namespace to get proper namespace OIDs
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_class AS
                SELECT
                    ABS(hash(t.table_schema || '.' || t.table_name) % 2147483647)::INTEGER as oid,
                    t.table_name as relname,
                    COALESCE(n.oid, 0) as relnamespace,
                    CASE t.table_type
                        WHEN 'BASE TABLE' THEN 'r'
                        WHEN 'VIEW' THEN 'v'
                        WHEN 'LOCAL TEMPORARY' THEN 'r'
                        ELSE 'r'
                    END as relkind,
                    0 as relowner,
                    0 as relam,
                    0 as relfilenode,
                    0 as reltablespace,
                    0 as relpages,
                    0.0 as reltuples,
                    0 as relallvisible,
                    0 as reltoastrelid,
                    false as relhasindex,
                    false as relisshared,
                    'p' as relpersistence,
                    false as relhasrules,
                    false as relhastriggers,
                    false as relhassubclass,
                    0 as relrowsecurity,
                    false as relforcerowsecurity,
                    false as relispopulated,
                    'n' as relreplident,
                    false as relispartition,
                    0 as relrewrite,
                    0 as relfrozenxid,
                    0 as relminmxid
                FROM information_schema.tables t
                LEFT JOIN pg_catalog.pg_namespace n ON n.nspname = t.table_schema
            """)

            # pg_tables - Simplified table list
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_tables AS
                SELECT
                    table_schema as schemaname,
                    table_name as tablename,
                    NULL::VARCHAR as tableowner,
                    NULL::VARCHAR as tablespace,
                    false as hasindexes,
                    false as hasrules,
                    false as hastriggers,
                    false as rowsecurity
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            """)

            # pg_attribute - Column information
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_attribute AS
                SELECT
                    0 as attrelid,
                    column_name as attname,
                    0 as atttypid,
                    0 as attstattarget,
                    -1 as attlen,
                    ordinal_position as attnum,
                    0 as attndims,
                    -1 as attcacheoff,
                    -1 as atttypmod,
                    false as attbyval,
                    'p' as attalign,
                    'p' as attstorage,
                    CASE is_nullable WHEN 'NO' THEN true ELSE false END as attnotnull,
                    false as atthasdef,
                    '' as attidentity,
                    'a' as attgenerated,
                    false as attisdropped,
                    true as attislocal,
                    0 as attinhcount,
                    0 as attcollation,
                    NULL as attacl,
                    NULL as attoptions,
                    NULL as attfdwoptions,
                    NULL as attmissingval,
                    table_schema,
                    table_name,
                    data_type
                FROM information_schema.columns
            """)

            # pg_type - Data type information
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_type AS
                SELECT
                    data_type as typname,
                    0 as oid,
                    0 as typnamespace,
                    0 as typowner,
                    -1 as typlen,
                    true as typbyval,
                    'b' as typtype,
                    'U' as typcategory,
                    false as typispreferred,
                    true as typisdefined,
                    ',' as typdelim,
                    0 as typrelid,
                    0 as typelem,
                    0 as typarray,
                    '-' as typinput,
                    '-' as typoutput,
                    '-' as typreceive,
                    '-' as typsend,
                    '-' as typmodin,
                    '-' as typmodout,
                    '-' as typanalyze,
                    'd' as typalign,
                    'p' as typstorage,
                    false as typnotnull,
                    0 as typbasetype,
                    -1 as typtypmod,
                    0 as typndims,
                    0 as typcollation,
                    NULL as typdefaultbin,
                    NULL as typdefault,
                    NULL as typacl
                FROM (SELECT DISTINCT data_type FROM information_schema.columns)
            """)

            # pg_index - Index information (minimal - DuckDB doesn't expose index details easily)
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_index AS
                SELECT
                    0 as indexrelid,
                    0 as indrelid,
                    0 as indnatts,
                    0 as indnkeyatts,
                    false as indisunique,
                    false as indisprimary,
                    false as indisexclusion,
                    false as indimmediate,
                    false as indisclustered,
                    false as indisvalid,
                    false as indcheckxmin,
                    false as indisready,
                    false as indislive,
                    false as indisreplident,
                    NULL as indkey,
                    NULL as indcollation,
                    NULL as indclass,
                    NULL as indoption,
                    NULL as indexprs,
                    NULL as indpred
                WHERE false  -- Empty table, no indexes for now
            """)

            # pg_description - Object comments/descriptions
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_description AS
                SELECT
                    0 as objoid,
                    0 as classoid,
                    0 as objsubid,
                    NULL::VARCHAR as description
                WHERE false  -- Empty table
            """)

            # pg_database - Database list
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_database AS
                SELECT
                    'default' as datname,
                    0 as oid,
                    0 as datdba,
                    6 as encoding,
                    'C' as datcollate,
                    'C' as datctype,
                    false as datistemplate,
                    true as datallowconn,
                    -1 as datconnlimit,
                    0 as datlastsysoid,
                    0 as datfrozenxid,
                    0 as datminmxid,
                    0 as dattablespace,
                    NULL as datacl
            """)

            # pg_proc - Functions/procedures (minimal)
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_proc AS
                SELECT
                    0 as oid,
                    'lars_udf' as proname,
                    0 as pronamespace,
                    0 as proowner,
                    0 as prolang,
                    0.0 as procost,
                    0.0 as prorows,
                    0 as provariadic,
                    'u' as prosupport,
                    'v' as prokind,
                    false as prosecdef,
                    false as proleakproof,
                    false as proisstrict,
                    false as proretset,
                    'v' as provolatile,
                    's' as proparallel,
                    2 as pronargs,
                    0 as pronargdefaults,
                    0 as prorettype,
                    NULL as proargtypes,
                    NULL as proallargtypes,
                    NULL as proargmodes,
                    NULL as proargnames,
                    NULL as proargdefaults,
                    NULL as protrftypes,
                    NULL as prosrc,
                    NULL as probin,
                    NULL as proconfig,
                    NULL as proacl
            """)

            # pg_settings - Server configuration (minimal)
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_settings AS
                SELECT
                    'server_version' as name,
                    '14.0' as setting,
                    NULL::VARCHAR as unit,
                    'PostgreSQL-compatible server (LARS/DuckDB)' as category,
                    'Shows the server version.' as short_desc,
                    'Shows the server version number.' as extra_desc,
                    'internal' as context,
                    'string' as vartype,
                    'default' as source,
                    '14.0' as min_val,
                    NULL::VARCHAR as max_val,
                    NULL::VARCHAR as enumvals,
                    '14.0' as boot_val,
                    '14.0' as reset_val,
                    NULL::VARCHAR as sourcefile,
                    NULL::INTEGER as sourceline,
                    false as pending_restart
            """)

            self._runtime_log(
                "INFO",
                "ALL pg_catalog views created successfully (schema introspection enabled)",
                event="pg_catalog_views_ready",
            )

        except Exception as e:
            # Non-fatal - catalog views are nice-to-have
            self._runtime_log(
                "WARN",
                f"ERROR creating pg_catalog views: {e}",
                event="pg_catalog_views_error",
                error_type=type(e).__name__,
            )
            if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                import traceback
                traceback.print_exc()
            self._runtime_log(
                "WARN",
                "Schema introspection may not work",
                event="pg_catalog_views_disabled",
            )

    def _cleanup_orphaned_views(self):
        """
        Clean up views pointing to DETACH'd or non-existent databases.

        After server restart, ATTACH'd databases are gone but views remain.
        This method drops orphaned views (views with __ pattern that point to non-existent DBs).
        """
        try:
            # Get all currently attached databases (exclude current DB)
            attached_db_names = set()
            attached_dbs = self.duckdb_conn.execute(
                """
                SELECT database_name
                FROM duckdb_databases()
                WHERE NOT internal
                  AND database_name NOT IN ('system', 'temp')
                  AND database_name <> current_database()
                  AND database_name NOT LIKE 'pg_client_%'
                """
            ).fetchall()

            for (db_name,) in attached_dbs:
                attached_db_names.add(db_name)

            # Get all views with __ pattern in main schema (legacy exposure)
            views = self.duckdb_conn.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_type = 'VIEW'
                  AND (
                    (table_schema = 'main' AND table_name LIKE '%__%')
                    OR (table_schema NOT IN ('main', 'pg_catalog', 'information_schema') AND table_schema LIKE '%__%')
                  )
                """
            ).fetchall()

            dropped_count = 0
            dropped_schemas = set()
            for view_schema, view_name in views:
                # Extract database name from schema/view prefix (before __)
                db_prefix = None
                if view_schema != 'main' and '__' in view_schema:
                    db_prefix = view_schema.split('__')[0]
                elif '__' in view_name:
                    db_prefix = view_name.split('__')[0]

                # If database doesn't exist, drop the view
                if db_prefix and db_prefix not in attached_db_names:
                    try:
                        self.duckdb_conn.execute(
                            f"DROP VIEW IF EXISTS {self._quote_ident(view_schema)}.{self._quote_ident(view_name)}"
                        )
                        dropped_count += 1
                        if view_schema != 'main':
                            dropped_schemas.add(view_schema)
                    except:
                        pass

            if dropped_count > 0:
                self._runtime_log(
                    "INFO",
                    f"Cleaned up {dropped_count} orphaned views (DETACH'd databases)",
                    event="orphaned_views_cleaned",
                    dropped_count=dropped_count,
                )

            # Best-effort: drop any now-empty orphan schemas we created for exposure
            for schema_name in sorted(dropped_schemas):
                try:
                    remaining = self.duckdb_conn.execute(
                        """
                        SELECT COUNT(*)::BIGINT
                        FROM information_schema.tables
                        WHERE table_schema = ?
                        """,
                        [schema_name],
                    ).fetchone()[0]
                    if int(remaining) == 0:
                        self.duckdb_conn.execute(f"DROP SCHEMA IF EXISTS {self._quote_ident(schema_name)}")
                except Exception:
                    pass

        except Exception as e:
            # Non-fatal
            self._runtime_log(
                "WARN",
                f"Could not cleanup orphaned views: {e}",
                event="orphaned_views_cleanup_failed",
                error_type=type(e).__name__,
            )

    def _create_attached_db_views(self):
        """
        Create views in main schema for all tables in ATTACH'd databases.

        This makes ATTACH'd cascade sessions browsable in DBeaver!

        For each relation in an attached database:
          ext.main.t1 → schema: ext__main, view: ext__main.t1

        This keeps attached catalogs out of information_schema introspection while still
        making the data browsable as normal schemas/views in Postgres clients.
        """
        try:
            # First, clean up any orphaned views from DETACH'd databases
            self._cleanup_orphaned_views()

            # Cache current attached DBs for change detection
            try:
                self._last_attached_db_names = {
                    r[0]
                    for r in self.duckdb_conn.execute(
                        "SELECT database_name FROM duckdb_databases() WHERE NOT internal"
                    ).fetchall()
                }
            except Exception:
                pass

            # Get all attached databases (exclude system DBs and current DB)
            attached_dbs = self.duckdb_conn.execute(
                """
                SELECT database_name, database_oid
                FROM duckdb_databases()
                WHERE NOT internal
                  AND database_name NOT IN ('system', 'temp')
                  AND database_name <> current_database()
                  AND database_name NOT LIKE 'pg_client_%'
                ORDER BY database_name
                """
            ).fetchall()

            if not attached_dbs:
                self._runtime_log(
                    "DEBUG",
                    "No ATTACH'd databases to expose",
                    event="attached_db_views_none",
                )
                return

            schema_count = 0
            view_count = 0
            for db_name, db_oid in attached_dbs:
                # Get tables in this database
                tables = self.duckdb_conn.execute(
                    """
                    SELECT schema_name, table_name
                    FROM duckdb_tables()
                    WHERE database_name = ?
                      AND NOT internal
                      AND NOT temporary
                    ORDER BY schema_name, table_name
                    """,
                    [db_name],
                ).fetchall()

                for schema, table in tables:
                    # Expose attached db.schema as a schema in the current database.
                    # This avoids Postgres clients interpreting attached catalogs as FDW/foreign objects.
                    expose_schema = f"{db_name}__{schema}"

                    try:
                        self.duckdb_conn.execute(
                            f"CREATE SCHEMA IF NOT EXISTS {self._quote_ident(expose_schema)}"
                        )
                        schema_count += 1
                    except Exception:
                        pass

                    try:
                        # Create a view in the exposure schema with the original table name
                        self.duckdb_conn.execute(
                            f"""
                            CREATE OR REPLACE VIEW {self._quote_ident(expose_schema)}.{self._quote_ident(table)} AS
                            SELECT * FROM {self._quote_ident(db_name)}.{self._quote_ident(schema)}.{self._quote_ident(table)}
                            """
                        )
                        view_count += 1
                    except Exception as e:
                        # Skip if view creation fails
                        pass

                    # Back-compat (legacy): also create a flattened view in main.
                    legacy_view = f"{db_name}__{table}" if schema in ("main", "public") else f"{db_name}__{schema}__{table}"
                    try:
                        self.duckdb_conn.execute(
                            f"""
                            CREATE OR REPLACE VIEW main.{self._quote_ident(legacy_view)} AS
                            SELECT * FROM {self._quote_ident(db_name)}.{self._quote_ident(schema)}.{self._quote_ident(table)}
                            """
                        )
                    except Exception:
                        pass

            if view_count > 0:
                self._runtime_log(
                    "INFO",
                    f"Exposed {view_count} relation(s) from ATTACH'd databases",
                    event="attached_db_views_ready",
                    view_count=view_count,
                    schema_count=schema_count,
                )
            else:
                self._runtime_log(
                    "DEBUG",
                    "No tables found in ATTACH'd databases",
                    event="attached_db_views_empty",
                )

        except Exception as e:
            # Non-fatal - ATTACH views are nice-to-have
            self._runtime_log(
                "WARN",
                f"Could not create ATTACH'd DB views: {e}",
                event="attached_db_views_error",
                error_type=type(e).__name__,
            )

    def _handle_shared_table_create(self, query: str, send_ready: bool = True) -> bool:
        """
        Handle CREATE TABLE shared.* - write to parquet for cross-session visibility.

        Intercepts CREATE [OR REPLACE] TABLE shared.name AS SELECT ... and routes
        to shared_parquet.write_shared_table() which:
        1. Executes the SELECT query
        2. Writes results to a parquet file (atomic via temp+rename)
        3. Creates a view in the current session pointing to the parquet file

        Supported syntax:
            CREATE TABLE shared.my_table AS SELECT * FROM source;
            CREATE OR REPLACE TABLE shared.my_table AS SELECT * FROM source;
            CREATE TABLE shared.staging.my_table AS SELECT * FROM source;  (explicit subdir)
            CREATE TABLE shared.results.my_table AS SELECT * FROM source;
            CREATE TABLE shared.user.my_table AS SELECT * FROM source;

        View naming:
            shared.name              -> view: shared.name        (file: staging/name.parquet)
            shared.staging.name      -> view: shared.name        (file: staging/name.parquet)
            shared.results.name      -> view: shared.results_name (file: results/name.parquet)
            shared.user.name         -> view: shared.user_name    (file: user/name.parquet)

        Args:
            query: CREATE TABLE statement targeting shared schema
        """
        import re

        self._runtime_log(
            "DEBUG",
            "Shared table CREATE detected",
            event="shared_table_create_detected",
        )

        # For multi-panel queries, extract only the first statement (CREATE TABLE)
        # Split on panel markers to isolate setup SQL
        if '--- PANEL' in query or '---PANEL' in query:
            # Multi-panel query: extract just the CREATE TABLE statement
            parts = re.split(r'\n---\s*PANEL', query, maxsplit=1, flags=re.IGNORECASE)
            first_statement = parts[0].strip()
            self._runtime_log(
                "DEBUG",
                "Multi-panel query: extracted setup statement",
                event="shared_table_create_multi_panel",
            )
        else:
            first_statement = query

        # Parse the CREATE TABLE statement
        # Pattern: CREATE [OR REPLACE] TABLE shared.[subdir.]name AS SELECT ...
        # Note: \s* allows leading whitespace/newlines from frontend parsing
        pattern = r'''
            ^\s*CREATE\s+
            (?:OR\s+REPLACE\s+)?
            TABLE\s+
            shared\.
            (?:(\w+)\.)?           # Optional subdir (staging, results, user)
            (\w+)                  # Table name
            \s+AS\s+
            (.+)$                  # SELECT query
        '''
        match = re.match(pattern, first_statement, re.IGNORECASE | re.VERBOSE | re.DOTALL)

        if not match:
            # Try simpler pattern without AS (might be CREATE TABLE shared.x (...))
            if send_ready:
                send_error(
                    self.sock,
                    "Shared tables require CREATE TABLE shared.name AS SELECT syntax",
                    transaction_status=self.transaction_status
                )
            else:
                self.sock.sendall(ErrorResponse.encode(
                    "ERROR",
                    "Shared tables require CREATE TABLE shared.name AS SELECT syntax",
                ))
            self._runtime_log(
                "WARN",
                "Could not parse shared table CREATE",
                event="shared_table_create_parse_failed",
                query_preview=first_statement[:300],
            )
            return False

        explicit_subdir = match.group(1)  # None if not specified
        table_name = match.group(2)
        select_query = match.group(3).rstrip(';').strip()

        # Determine subdir and view name
        valid_subdirs = ('staging', 'results', 'user')
        if explicit_subdir:
            subdir = explicit_subdir.lower()
            if subdir not in valid_subdirs:
                message = f"Invalid shared table subdirectory '{subdir}'. Must be one of: {', '.join(valid_subdirs)}"
                if send_ready:
                    send_error(
                        self.sock,
                        message,
                        transaction_status=self.transaction_status
                    )
                else:
                    self.sock.sendall(ErrorResponse.encode("ERROR", message))
                return False
            # Explicit subdir: include prefix in view name (except staging which is default)
            if subdir == 'staging':
                view_name = table_name
            else:
                view_name = f"{subdir}_{table_name}"
        else:
            # No explicit subdir: default to staging, use simple view name
            subdir = 'staging'
            view_name = table_name

        self._runtime_log(
            "DEBUG",
            f"Target: shared.{view_name} (file: {subdir}/{table_name}.parquet)",
            event="shared_table_create_target",
            table_name=table_name,
            view_name=view_name,
            subdir=subdir,
            query_preview=(select_query[:200] + ("..." if len(select_query) > 200 else "")),
        )

        try:
            from ..sql_tools.shared_parquet import write_shared_table_with_view_name

            with self.db_lock:
                parquet_path = write_shared_table_with_view_name(
                    self.duckdb_conn,
                    table_name,
                    view_name,
                    select_query,
                    subdir=subdir,
                    schema='shared'
                )

            if parquet_path:
                self._runtime_log(
                    "INFO",
                    f"Shared table written: {parquet_path}",
                    event="shared_table_create_written",
                    parquet_path=str(parquet_path),
                    table_name=table_name,
                    view_name=view_name,
                    subdir=subdir,
                )
                self._runtime_log(
                    "DEBUG",
                    f"View created: shared.{view_name}",
                    event="shared_table_create_view",
                    view_name=view_name,
                )

                # Send success response
                self.sock.sendall(CommandComplete.encode('CREATE TABLE'))
                if send_ready:
                    self.sock.sendall(ReadyForQuery.encode(self.transaction_status))
                self._runtime_log(
                    "INFO",
                    "Shared table created successfully",
                    event="shared_table_create_complete",
                    table_name=table_name,
                    view_name=view_name,
                    subdir=subdir,
                )
                return True
            else:
                if send_ready:
                    send_error(
                        self.sock,
                        "Failed to create shared table - check logs for details",
                        transaction_status=self.transaction_status
                    )
                else:
                    self.sock.sendall(ErrorResponse.encode(
                        "ERROR",
                        "Failed to create shared table - check logs for details",
                    ))
                return False

        except Exception as e:
            error_msg = str(e)
            if send_ready:
                send_error(self.sock, f"Shared table creation failed: {error_msg}", transaction_status=self.transaction_status)
            else:
                self.sock.sendall(ErrorResponse.encode("ERROR", f"Shared table creation failed: {error_msg}"))
            self._runtime_log(
                "ERROR",
                f"Shared table creation failed: {error_msg}",
                event="shared_table_create_error",
                table_name=table_name,
                error_type=type(e).__name__,
            )
            return False

    def _handle_attach(self, query: str, send_ready: bool = True) -> bool:
        """
        Handle ATTACH command - execute and refresh views.

        Parses ATTACH statement, executes it on DuckDB, and creates views for the
        attached database's tables.

        Args:
            query: ATTACH statement (e.g., "ATTACH '/path/db.duckdb' AS my_db")
        """
        import re

        self._runtime_log(
            "DEBUG",
            "ATTACH command detected",
            event="attach_detected",
        )

        # Parse ATTACH statement
        # Handles: ATTACH '/path' AS alias, ATTACH DATABASE '/path' AS alias, ATTACH '/path' (alias = filename)
        match = re.search(r"ATTACH\s+(?:DATABASE\s+)?['\"]([^'\"]+)['\"](?:\s+AS\s+(\w+))?", query, re.IGNORECASE)

        if not match:
            if send_ready:
                send_error(self.sock, "Could not parse ATTACH statement", transaction_status=self.transaction_status)
            else:
                self.sock.sendall(ErrorResponse.encode("ERROR", "Could not parse ATTACH statement"))
            self._runtime_log(
                "WARN",
                "Could not parse ATTACH statement",
                event="attach_parse_failed",
                query_preview=query[:200],
            )
            return False

        db_path = match.group(1)
        db_alias = match.group(2)

        # If no alias provided, DuckDB uses filename without extension
        if not db_alias:
            import os
            db_alias = os.path.splitext(os.path.basename(db_path))[0]

        try:
            # 1. Execute ATTACH
            self.duckdb_conn.execute(query)
            self._runtime_log(
                "INFO",
                f"Attached: {db_path} AS {db_alias}",
                event="attach_executed",
                db_path=db_path,
                db_alias=db_alias,
            )

            # 2. Create views for attached database tables
            self._create_attached_db_views()

            # 3. Send success response
            self.sock.sendall(CommandComplete.encode('ATTACH'))
            if send_ready:
                self.sock.sendall(ReadyForQuery.encode('I'))
            self._runtime_log(
                "INFO",
                "ATTACH complete",
                event="attach_complete",
                db_alias=db_alias,
            )
            return True

        except Exception as e:
            error_message = str(e)
            if send_ready:
                send_error(self.sock, error_message, transaction_status=self.transaction_status)
            else:
                self.sock.sendall(ErrorResponse.encode("ERROR", error_message))
            self._runtime_log(
                "ERROR",
                f"ATTACH error: {error_message}",
                event="attach_error",
                db_path=db_path,
                db_alias=db_alias,
                error_type=type(e).__name__,
            )
            return False

    def _handle_detach(self, query: str, send_ready: bool = True) -> bool:
        """
        Handle DETACH command - cleanup views before detaching.

        Args:
            query: DETACH statement (e.g., "DETACH my_db" or "DETACH IF EXISTS my_db")
        """
        import re

        # Extract database name from DETACH statement
        # Handles: DETACH db_name, DETACH IF EXISTS db_name, DETACH DATABASE db_name
        match = re.search(r'DETACH\s+(?:IF\s+EXISTS\s+)?(?:DATABASE\s+)?(\w+)', query, re.IGNORECASE)

        if match:
            db_name = match.group(1)
            self._runtime_log(
                "INFO",
                f"DETACH {db_name} - cleaning up...",
                event="detach_cleanup_start",
                db_name=db_name,
            )

            # Drop all views for this database
            try:
                views_to_drop = self.duckdb_conn.execute(f"""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'main'
                      AND table_type = 'VIEW'
                      AND table_name LIKE '{db_name}__%%'
                """).fetchall()

                dropped_count = 0
                for (view_name,) in views_to_drop:
                    try:
                        self.duckdb_conn.execute(f'DROP VIEW IF EXISTS main."{view_name}"')
                        dropped_count += 1
                    except:
                        pass

                if dropped_count > 0:
                    self._runtime_log(
                        "INFO",
                        f"Dropped {dropped_count} views for {db_name}",
                        event="detach_views_dropped",
                        db_name=db_name,
                        dropped_count=dropped_count,
                    )

            except Exception as e:
                self._runtime_log(
                    "WARN",
                    f"Could not cleanup views: {e}",
                    event="detach_cleanup_error",
                    db_name=db_name,
                    error_type=type(e).__name__,
                )

        # Execute the actual DETACH command
        try:
            self.duckdb_conn.execute(query)
            self.sock.sendall(CommandComplete.encode('DETACH'))
            if send_ready:
                self.sock.sendall(ReadyForQuery.encode('I'))
            self._runtime_log(
                "INFO",
                "DETACH executed",
                event="detach_executed",
                db_name=(db_name if match else None),
            )
            return True

        except Exception as e:
            error_message = str(e)
            if send_ready:
                send_error(self.sock, error_message, transaction_status=self.transaction_status)
            else:
                self.sock.sendall(ErrorResponse.encode("ERROR", error_message))
            self._runtime_log(
                "ERROR",
                f"DETACH error: {error_message}",
                event="detach_error",
                db_name=(db_name if match else None),
                error_type=type(e).__name__,
            )
            return False

    def _register_refresh_views_udf(self):
        """
        Register refresh_attached_views() UDF.

        Users can call this after manually ATTACH'ing a database:
          SELECT refresh_attached_views();

        This will create views for the newly ATTACH'd database's tables.

        Note: Multiple connections share the same DuckDB, so the UDF may
        already be registered. We silently skip if it already exists.
        """
        try:
            def refresh_attached_views() -> str:
                """Refresh views for ATTACH'd databases."""
                # Call the view creation method
                self._create_attached_db_views()
                return "Views refreshed for ATTACH'd databases"

            self.duckdb_conn.create_function('refresh_attached_views', refresh_attached_views)
            self._runtime_log(
                "DEBUG",
                "Registered refresh_attached_views() UDF",
                event="refresh_views_udf_registered",
            )

        except Exception as e:
            # "already created" is expected when multiple connections share DuckDB
            if "already created" in str(e).lower():
                pass  # Silently skip - UDF is already there
            else:
                self._runtime_log(
                    "WARN",
                    f"Could not register refresh UDF: {e}",
                    event="refresh_views_udf_error",
                    error_type=type(e).__name__,
                )

    def _create_pg_compat_stubs(self):
        """
        Create PostgreSQL compatibility stubs for advanced clients like DataGrip.

        DataGrip queries PostgreSQL-specific system tables and functions that
        DuckDB doesn't have. We create stub versions that return sensible defaults.

        Stubs created:
        - pg_locks: Empty view (no active locks)
        - pg_is_in_recovery(): Returns false (not a replica)
        - txid_current(): Returns monotonic transaction ID
        - pg_stat_activity: Empty view (no other sessions visible)
        """
        import time

        stubs_created = []

        try:
            # pg_locks - Lock information (empty, we don't track locks)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_locks AS
                    SELECT
                        NULL::BIGINT as locktype,
                        NULL::BIGINT as database,
                        NULL::BIGINT as relation,
                        NULL::INTEGER as page,
                        NULL::SMALLINT as tuple,
                        NULL::VARCHAR as virtualxid,
                        NULL::BIGINT as transactionid,
                        NULL::BIGINT as classid,
                        NULL::BIGINT as objid,
                        NULL::SMALLINT as objsubid,
                        NULL::VARCHAR as virtualtransaction,
                        NULL::INTEGER as pid,
                        NULL::VARCHAR as mode,
                        NULL::BOOLEAN as granted,
                        NULL::BOOLEAN as fastpath,
                        NULL::TIMESTAMP as waitstart
                    WHERE false
                """)
                stubs_created.append("pg_locks")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    pass  # View might already exist

            # pg_stat_activity - Session information (show just this session)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_stat_activity AS
                    SELECT
                        NULL::INTEGER as datid,
                        'default'::VARCHAR as datname,
                        NULL::INTEGER as pid,
                        NULL::INTEGER as leader_pid,
                        'default'::VARCHAR as usesysid,
                        'lars'::VARCHAR as usename,
                        ''::VARCHAR as application_name,
                        '127.0.0.1'::VARCHAR as client_addr,
                        NULL::VARCHAR as client_hostname,
                        NULL::INTEGER as client_port,
                        NOW()::TIMESTAMP as backend_start,
                        NULL::TIMESTAMP as xact_start,
                        NULL::TIMESTAMP as query_start,
                        NULL::TIMESTAMP as state_change,
                        'idle'::VARCHAR as wait_event_type,
                        NULL::VARCHAR as wait_event,
                        'active'::VARCHAR as state,
                        NULL::BIGINT as backend_xid,
                        NULL::BIGINT as backend_xmin,
                        ''::VARCHAR as query,
                        'client backend'::VARCHAR as backend_type
                    LIMIT 1
                """)
                stubs_created.append("pg_stat_activity")
            except Exception as e:
                pass

            # pg_is_in_recovery() - Are we a replica? No.
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_is_in_recovery() AS false
                """)
                stubs_created.append("pg_is_in_recovery()")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    pass

            # txid_current() - Current transaction ID (use timestamp-based fake)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO txid_current() AS
                        (epoch_ms(now())::BIGINT % 4294967296)
                """)
                stubs_created.append("txid_current()")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    pass

            # pg_backend_pid() - Return a fake PID
            try:
                import os
                pid = os.getpid()
                self.duckdb_conn.execute(f"""
                    CREATE OR REPLACE MACRO pg_backend_pid() AS {pid}
                """)
                stubs_created.append("pg_backend_pid()")
            except Exception as e:
                pass

            # pg_current_xact_id() - Alias for txid_current (newer PG versions)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_current_xact_id() AS
                        (epoch_ms(now())::BIGINT % 4294967296)
                """)
                stubs_created.append("pg_current_xact_id()")
            except Exception as e:
                pass

            # =========================================================
            # DataGrip introspection functions
            # =========================================================

            # pg_get_userbyid(oid) - Get username by OID
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_userbyid(user_oid) AS
                        CASE WHEN user_oid = 0 THEN 'postgres'
                             WHEN user_oid = 10 THEN 'lars'
                             ELSE 'user_' || COALESCE(user_oid::VARCHAR, '0')
                        END
                """)
                stubs_created.append("pg_get_userbyid()")
            except Exception as e:
                pass

            # pg_get_expr(expr_text, relid) - Get expression text
            # Note: DuckDB doesn't support macro overloading, so we only create the 2-arg version.
            # The query rewriter will handle pg_get_expr calls by replacing them with NULL.
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_expr(expr_text, relid) AS
                        NULL::VARCHAR
                """)
                stubs_created.append("pg_get_expr()")
            except Exception as e:
                pass

            # pg_encoding_to_char(encoding_int) - Get encoding name
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_encoding_to_char(enc) AS
                        CASE WHEN enc = 6 THEN 'UTF8'
                             WHEN enc = 0 THEN 'SQL_ASCII'
                             ELSE 'UTF8'
                        END
                """)
                stubs_created.append("pg_encoding_to_char()")
            except Exception as e:
                pass

            # pg_tablespace_location(oid) - Get tablespace location
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_tablespace_location(ts_oid) AS ''
                """)
                stubs_created.append("pg_tablespace_location()")
            except Exception as e:
                pass

            # format_type(type_oid, typemod) - Format type for display
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO format_type(type_oid, typemod) AS
                        CASE
                            WHEN type_oid = 16 THEN 'boolean'
                            WHEN type_oid = 17 THEN 'bytea'
                            WHEN type_oid = 18 THEN 'char'
                            WHEN type_oid = 19 THEN 'name'
                            WHEN type_oid = 20 THEN 'bigint'
                            WHEN type_oid = 21 THEN 'smallint'
                            WHEN type_oid = 23 THEN 'integer'
                            WHEN type_oid = 25 THEN 'text'
                            WHEN type_oid = 26 THEN 'oid'
                            WHEN type_oid = 114 THEN 'json'
                            WHEN type_oid = 700 THEN 'real'
                            WHEN type_oid = 701 THEN 'double precision'
                            WHEN type_oid = 1043 THEN 'character varying'
                            WHEN type_oid = 1082 THEN 'date'
                            WHEN type_oid = 1083 THEN 'time'
                            WHEN type_oid = 1114 THEN 'timestamp'
                            WHEN type_oid = 1184 THEN 'timestamp with time zone'
                            WHEN type_oid = 2950 THEN 'uuid'
                            WHEN type_oid = 3802 THEN 'jsonb'
                            ELSE 'unknown'
                        END
                """)
                stubs_created.append("format_type()")
            except Exception as e:
                pass

            # pg_get_constraintdef(constraint_oid) - Get constraint definition
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_constraintdef(con_oid) AS ''
                """)
                stubs_created.append("pg_get_constraintdef()")
            except Exception as e:
                pass

            # pg_get_constraintdef with pretty flag
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_constraintdef(con_oid, pretty) AS ''
                """)
            except Exception as e:
                pass

            # pg_get_indexdef(index_oid) - Get index definition
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_indexdef(idx_oid) AS ''
                """)
                stubs_created.append("pg_get_indexdef()")
            except Exception as e:
                pass

            # pg_get_indexdef with column number
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_indexdef(idx_oid, col_num, pretty) AS ''
                """)
            except Exception as e:
                pass

            # pg_relation_size(oid) - Get relation size in bytes
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_relation_size(rel_oid) AS 0::BIGINT
                """)
                stubs_created.append("pg_relation_size()")
            except Exception as e:
                pass

            # pg_table_size(oid) - Get table size including indexes
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_table_size(rel_oid) AS 0::BIGINT
                """)
                stubs_created.append("pg_table_size()")
            except Exception as e:
                pass

            # pg_total_relation_size(oid) - Get total relation size
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_total_relation_size(rel_oid) AS 0::BIGINT
                """)
                stubs_created.append("pg_total_relation_size()")
            except Exception as e:
                pass

            # pg_size_pretty(size) - Format size as human-readable
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_size_pretty(size_bytes) AS
                        CASE
                            WHEN size_bytes >= 1099511627776 THEN ROUND(size_bytes / 1099511627776.0, 1)::VARCHAR || ' TB'
                            WHEN size_bytes >= 1073741824 THEN ROUND(size_bytes / 1073741824.0, 1)::VARCHAR || ' GB'
                            WHEN size_bytes >= 1048576 THEN ROUND(size_bytes / 1048576.0, 1)::VARCHAR || ' MB'
                            WHEN size_bytes >= 1024 THEN ROUND(size_bytes / 1024.0, 1)::VARCHAR || ' kB'
                            ELSE size_bytes::VARCHAR || ' bytes'
                        END
                """)
                stubs_created.append("pg_size_pretty()")
            except Exception as e:
                pass

            # pg_get_partkeydef(oid) - Get partition key definition
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_partkeydef(rel_oid) AS ''
                """)
                stubs_created.append("pg_get_partkeydef()")
            except Exception as e:
                pass

            # obj_description(oid, catalog) - Get object description
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO obj_description(obj_oid, catalog_name) AS NULL::VARCHAR
                """)
                stubs_created.append("obj_description()")
            except Exception as e:
                pass

            # col_description(table_oid, column_num) - Get column description
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO col_description(rel_oid, col_num) AS NULL::VARCHAR
                """)
                stubs_created.append("col_description()")
            except Exception as e:
                pass

            # shobj_description(oid, catalog) - Get shared object description
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO shobj_description(obj_oid, catalog_name) AS NULL::VARCHAR
                """)
                stubs_created.append("shobj_description()")
            except Exception as e:
                pass

            # pg_has_role(user, role, privilege) - Check role membership
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_has_role(user_oid, role_oid, priv) AS true
                """)
                stubs_created.append("pg_has_role()")
            except Exception as e:
                pass

            # has_table_privilege variants
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO has_table_privilege(table_oid, priv) AS true
                """)
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO has_table_privilege(user_name, table_oid, priv) AS true
                """)
                stubs_created.append("has_table_privilege()")
            except Exception as e:
                pass

            # has_schema_privilege variants
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO has_schema_privilege(schema_oid, priv) AS true
                """)
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO has_schema_privilege(user_name, schema_oid, priv) AS true
                """)
                stubs_created.append("has_schema_privilege()")
            except Exception as e:
                pass

            # pg_get_serial_sequence(table, column) - Get sequence for serial column
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_serial_sequence(tab_name, col_name) AS NULL::VARCHAR
                """)
                stubs_created.append("pg_get_serial_sequence()")
            except Exception as e:
                pass

            # current_setting(name) - Get configuration setting
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO current_setting(setting_name) AS
                        CASE
                            WHEN setting_name = 'server_version' THEN '14.0'
                            WHEN setting_name = 'server_version_num' THEN '140000'
                            WHEN setting_name = 'standard_conforming_strings' THEN 'on'
                            WHEN setting_name = 'client_encoding' THEN 'UTF8'
                            WHEN setting_name = 'DateStyle' THEN 'ISO, MDY'
                            WHEN setting_name = 'TimeZone' THEN 'UTC'
                            WHEN setting_name = 'search_path' THEN 'lars_system, main, pg_catalog'
                            ELSE ''
                        END
                """)
                stubs_created.append("current_setting()")
            except Exception as e:
                pass

            # current_setting with missing_ok flag
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO current_setting(setting_name, missing_ok) AS
                        CASE
                            WHEN setting_name = 'server_version' THEN '14.0'
                            WHEN setting_name = 'server_version_num' THEN '140000'
                            WHEN setting_name = 'standard_conforming_strings' THEN 'on'
                            WHEN setting_name = 'client_encoding' THEN 'UTF8'
                            ELSE ''
                        END
                """)
            except Exception as e:
                pass

            # pg_postmaster_start_time() - Get server start time
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_postmaster_start_time() AS NOW()
                """)
                stubs_created.append("pg_postmaster_start_time()")
            except Exception as e:
                pass

            # version() - Get PostgreSQL version string (avoid mentioning DuckDB to prevent IDE mode switching)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO version() AS
                        'PostgreSQL 14.0 on x86_64-pc-linux-gnu, compiled by gcc'
                """)
                stubs_created.append("version()")
            except Exception as e:
                pass

            # pg_get_viewdef(oid) - Get view definition (return empty string)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_viewdef(view_oid) AS ''
                """)
                stubs_created.append("pg_get_viewdef()")
            except Exception as e:
                pass

            # pg_get_viewdef with pretty flag
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_viewdef(view_oid, pretty) AS ''
                """)
            except Exception as e:
                pass

            # pg_get_functiondef(oid) - Get function definition
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_functiondef(func_oid) AS ''
                """)
                stubs_created.append("pg_get_functiondef()")
            except Exception as e:
                pass

            # pg_get_triggerdef(oid) - Get trigger definition
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_triggerdef(trig_oid) AS ''
                """)
                stubs_created.append("pg_get_triggerdef()")
            except Exception as e:
                pass

            # pg_get_triggerdef with pretty flag
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_triggerdef(trig_oid, pretty) AS ''
                """)
            except Exception as e:
                pass

            # pg_get_ruledef(oid) - Get rule definition
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_ruledef(rule_oid) AS ''
                """)
                stubs_created.append("pg_get_ruledef()")
            except Exception as e:
                pass

            # pg_get_ruledef with pretty flag
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_get_ruledef(rule_oid, pretty) AS ''
                """)
            except Exception as e:
                pass

            # age(timestamp) - Calculate age from timestamp (return interval-like string)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO age(ts) AS
                        CASE
                            WHEN ts IS NULL THEN NULL
                            ELSE (NOW() - ts::TIMESTAMP)::VARCHAR
                        END
                """)
                stubs_created.append("age()")
            except Exception as e:
                pass

            # age(timestamp, timestamp) - Calculate age between two timestamps
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO age(ts1, ts2) AS
                        CASE
                            WHEN ts1 IS NULL OR ts2 IS NULL THEN NULL
                            ELSE (ts1::TIMESTAMP - ts2::TIMESTAMP)::VARCHAR
                        END
                """)
            except Exception as e:
                pass

            # age(integer) - For xmin/oid values, return 0 (used by DataGrip for state tracking)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO age(xmin_val) AS 0::INTEGER
                """)
            except Exception as e:
                pass

            # quote_ident(text) - Quote an identifier (DataGrip uses this extensively)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO quote_ident(ident) AS
                        '"' || REPLACE(ident::VARCHAR, '"', '""') || '"'
                """)
                stubs_created.append("quote_ident()")
            except Exception as e:
                pass

            # quote_literal(text) - Quote a literal string
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO quote_literal(lit) AS
                        '''' || REPLACE(lit::VARCHAR, '''', '''''') || ''''
                """)
                stubs_created.append("quote_literal()")
            except Exception as e:
                pass

            # translate(text, from, to) - Translate characters (like tr command)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO translate(str, from_chars, to_chars) AS
                        REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(str::VARCHAR,
                            substr(from_chars, 1, 1), substr(to_chars || '', 1, 1)),
                            substr(from_chars, 2, 1), substr(to_chars || '', 2, 1)),
                            substr(from_chars, 3, 1), substr(to_chars || '', 3, 1)),
                            substr(from_chars, 4, 1), substr(to_chars || '', 4, 1)),
                            substr(from_chars, 5, 1), substr(to_chars || '', 5, 1)),
                            substr(from_chars, 6, 1), substr(to_chars || '', 6, 1))
                """)
                stubs_created.append("translate()")
            except Exception as e:
                pass

            # array_length(array, dimension) - Get array length
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO array_length(arr, dim) AS
                        len(arr)
                """)
                stubs_created.append("array_length()")
            except Exception as e:
                pass

            # =========================================================
            # Stub views for pg_catalog tables DataGrip needs
            # =========================================================

            # pg_tablespace - tablespace info
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_tablespace AS
                    SELECT
                        0::INTEGER as oid,
                        'pg_default'::VARCHAR as spcname,
                        10::INTEGER as spcowner,
                        NULL::VARCHAR[] as spcacl,
                        NULL::VARCHAR[] as spcoptions
                """)
                stubs_created.append("pg_tablespace")
            except Exception as e:
                pass

            # pg_am - access methods (index types)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_am AS
                    SELECT 403::INTEGER as oid, 'btree'::VARCHAR as amname, 'i'::CHAR as amtype, 5::INTEGER as amstrategies, 0::INTEGER as amsupport
                    UNION ALL SELECT 405, 'hash', 'i', 1, 0
                    UNION ALL SELECT 783, 'gist', 'i', 0, 0
                    UNION ALL SELECT 2742, 'gin', 'i', 0, 0
                """)
                stubs_created.append("pg_am")
            except Exception as e:
                pass

            # pg_constraint - constraints (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_constraint AS
                    SELECT
                        0::INTEGER as oid,
                        ''::VARCHAR as conname,
                        0::INTEGER as connamespace,
                        ''::CHAR as contype,
                        false::BOOLEAN as condeferrable,
                        false::BOOLEAN as condeferred,
                        true::BOOLEAN as convalidated,
                        0::INTEGER as conrelid,
                        0::INTEGER as contypid,
                        0::INTEGER as conindid,
                        0::INTEGER as conparentid,
                        0::INTEGER as confrelid,
                        ''::CHAR as confupdtype,
                        ''::CHAR as confdeltype,
                        ''::CHAR as confmatchtype,
                        true::BOOLEAN as conislocal,
                        0::INTEGER as coninhcount,
                        false::BOOLEAN as connoinherit,
                        NULL::INTEGER[] as conkey,
                        NULL::INTEGER[] as confkey,
                        NULL::INTEGER[] as conpfeqop,
                        NULL::INTEGER[] as conppeqop,
                        NULL::INTEGER[] as conffeqop,
                        NULL::INTEGER[] as conexclop,
                        NULL::VARCHAR as conbin
                    WHERE false
                """)
                stubs_created.append("pg_constraint")
            except Exception as e:
                pass

            # pg_index - index info (empty stub, DuckDB has its own)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_index AS
                    SELECT
                        0::INTEGER as indexrelid,
                        0::INTEGER as indrelid,
                        0::SMALLINT as indnatts,
                        0::SMALLINT as indnkeyatts,
                        false::BOOLEAN as indisunique,
                        false::BOOLEAN as indisprimary,
                        false::BOOLEAN as indisexclusion,
                        true::BOOLEAN as indimmediate,
                        false::BOOLEAN as indisclustered,
                        true::BOOLEAN as indisvalid,
                        false::BOOLEAN as indcheckxmin,
                        true::BOOLEAN as indisready,
                        true::BOOLEAN as indislive,
                        false::BOOLEAN as indisreplident,
                        NULL::INTEGER[] as indkey,
                        NULL::INTEGER[] as indcollation,
                        NULL::INTEGER[] as indclass,
                        NULL::INTEGER[] as indoption,
                        NULL::VARCHAR as indexprs,
                        NULL::VARCHAR as indpred
                    WHERE false
                """)
                stubs_created.append("pg_index")
            except Exception as e:
                pass

            # pg_depend - object dependencies (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_depend AS
                    SELECT
                        0::INTEGER as classid,
                        0::INTEGER as objid,
                        0::INTEGER as objsubid,
                        0::INTEGER as refclassid,
                        0::INTEGER as refobjid,
                        0::INTEGER as refobjsubid,
                        'n'::CHAR as deptype
                    WHERE false
                """)
                stubs_created.append("pg_depend")
            except Exception as e:
                pass

            # pg_description - object descriptions/comments (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_description AS
                    SELECT
                        0::INTEGER as objoid,
                        0::INTEGER as classoid,
                        0::INTEGER as objsubid,
                        ''::VARCHAR as description
                    WHERE false
                """)
                stubs_created.append("pg_description")
            except Exception as e:
                pass

            # pg_shdescription - shared object descriptions (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_shdescription AS
                    SELECT
                        0::INTEGER as objoid,
                        0::INTEGER as classoid,
                        ''::VARCHAR as description
                    WHERE false
                """)
                stubs_created.append("pg_shdescription")
            except Exception as e:
                pass

            # pg_extension - extensions (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_extension AS
                    SELECT
                        0::INTEGER as oid,
                        'plpgsql'::VARCHAR as extname,
                        10::INTEGER as extowner,
                        11::INTEGER as extnamespace,
                        false::BOOLEAN as extrelocatable,
                        '1.0'::VARCHAR as extversion,
                        NULL::INTEGER[] as extconfig,
                        NULL::VARCHAR[] as extcondition
                """)
                stubs_created.append("pg_extension")
            except Exception as e:
                pass

            # pg_trigger - triggers (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_trigger AS
                    SELECT
                        0::INTEGER as oid,
                        0::INTEGER as tgrelid,
                        0::INTEGER as tgparentid,
                        ''::VARCHAR as tgname,
                        0::INTEGER as tgfoid,
                        0::SMALLINT as tgtype,
                        ''::CHAR as tgenabled,
                        false::BOOLEAN as tgisinternal,
                        0::INTEGER as tgconstrrelid,
                        0::INTEGER as tgconstrindid,
                        0::INTEGER as tgconstraint,
                        false::BOOLEAN as tgdeferrable,
                        false::BOOLEAN as tginitdeferred,
                        0::SMALLINT as tgnargs,
                        NULL::INTEGER[] as tgattr,
                        NULL::BYTEA as tgargs,
                        NULL::VARCHAR as tgqual,
                        NULL::VARCHAR as tgoldtable,
                        NULL::VARCHAR as tgnewtable
                    WHERE false
                """)
                stubs_created.append("pg_trigger")
            except Exception as e:
                pass

            # pg_policy - row-level security policies (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_policy AS
                    SELECT
                        0::INTEGER as oid,
                        ''::VARCHAR as polname,
                        0::INTEGER as polrelid,
                        ''::CHAR as polcmd,
                        false::BOOLEAN as polpermissive,
                        NULL::INTEGER[] as polroles,
                        NULL::VARCHAR as polqual,
                        NULL::VARCHAR as polwithcheck
                    WHERE false
                """)
                stubs_created.append("pg_policy")
            except Exception as e:
                pass

            # pg_inherits - table inheritance (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_inherits AS
                    SELECT
                        0::INTEGER as inhrelid,
                        0::INTEGER as inhparent,
                        0::INTEGER as inhseqno,
                        false::BOOLEAN as inhdetachpending
                    WHERE false
                """)
                stubs_created.append("pg_inherits")
            except Exception as e:
                pass

            # pg_rewrite - query rewrite rules (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_rewrite AS
                    SELECT
                        0::INTEGER as oid,
                        ''::VARCHAR as rulename,
                        0::INTEGER as ev_class,
                        ''::CHAR as ev_type,
                        ''::CHAR as ev_enabled,
                        false::BOOLEAN as is_instead,
                        NULL::VARCHAR as ev_qual,
                        NULL::VARCHAR as ev_action
                    WHERE false
                """)
                stubs_created.append("pg_rewrite")
            except Exception as e:
                pass

            # pg_collation - collation info
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_collation AS
                    SELECT
                        100::INTEGER as oid,
                        'default'::VARCHAR as collname,
                        11::INTEGER as collnamespace,
                        10::INTEGER as collowner,
                        'd'::CHAR as collprovider,
                        true::BOOLEAN as collisdeterministic,
                        -1::INTEGER as collencoding,
                        'en_US.UTF-8'::VARCHAR as collcollate,
                        'en_US.UTF-8'::VARCHAR as collctype,
                        NULL::VARCHAR as collversion
                """)
                stubs_created.append("pg_collation")
            except Exception as e:
                pass

            # NOTE: pg_enum stub removed - DuckDB 1.4.2+ has built-in pg_catalog.pg_enum
            # with correct columns: oid, enumtypid, enumsortorder, enumlabel

            # pg_cast - type casts (minimal stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_cast AS
                    SELECT
                        0::INTEGER as oid,
                        0::INTEGER as castsource,
                        0::INTEGER as casttarget,
                        0::INTEGER as castfunc,
                        'e'::CHAR as castcontext,
                        'f'::CHAR as castmethod
                    WHERE false
                """)
                stubs_created.append("pg_cast")
            except Exception as e:
                pass

            # pg_foreign_server - foreign servers (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_foreign_server AS
                    SELECT
                        0::INTEGER as oid,
                        ''::VARCHAR as srvname,
                        10::INTEGER as srvowner,
                        0::INTEGER as srvfdw,
                        ''::VARCHAR as srvtype,
                        ''::VARCHAR as srvversion,
                        NULL::VARCHAR[] as srvacl,
                        NULL::VARCHAR[] as srvoptions
                    WHERE false
                """)
                stubs_created.append("pg_foreign_server")
            except Exception as e:
                pass

            # pg_foreign_table - foreign tables (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_foreign_table AS
                    SELECT
                        0::INTEGER as ftrelid,
                        0::INTEGER as ftserver,
                        NULL::VARCHAR[] as ftoptions
                    WHERE false
                """)
                stubs_created.append("pg_foreign_table")
            except Exception as e:
                pass

            # pg_matviews - materialized views (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_matviews AS
                    SELECT
                        ''::VARCHAR as schemaname,
                        ''::VARCHAR as matviewname,
                        ''::VARCHAR as matviewowner,
                        ''::VARCHAR as tablespace,
                        false::BOOLEAN as hasindexes,
                        false::BOOLEAN as ispopulated,
                        ''::VARCHAR as definition
                    WHERE false
                """)
                stubs_created.append("pg_matviews")
            except Exception as e:
                pass

            # pg_sequences - sequences (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_sequences AS
                    SELECT
                        ''::VARCHAR as schemaname,
                        ''::VARCHAR as sequencename,
                        ''::VARCHAR as sequenceowner,
                        0::INTEGER as data_type,
                        1::BIGINT as start_value,
                        1::BIGINT as min_value,
                        9223372036854775807::BIGINT as max_value,
                        1::BIGINT as increment_by,
                        false::BOOLEAN as cycle,
                        50::BIGINT as cache_size,
                        NULL::BIGINT as last_value
                    WHERE false
                """)
                stubs_created.append("pg_sequences")
            except Exception as e:
                pass

            # pg_statio_user_tables - table I/O stats (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_statio_user_tables AS
                    SELECT
                        0::INTEGER as relid,
                        ''::VARCHAR as schemaname,
                        ''::VARCHAR as relname,
                        0::BIGINT as heap_blks_read,
                        0::BIGINT as heap_blks_hit,
                        0::BIGINT as idx_blks_read,
                        0::BIGINT as idx_blks_hit,
                        0::BIGINT as toast_blks_read,
                        0::BIGINT as toast_blks_hit,
                        0::BIGINT as tidx_blks_read,
                        0::BIGINT as tidx_blks_hit
                    WHERE false
                """)
                stubs_created.append("pg_statio_user_tables")
            except Exception as e:
                pass

            # pg_stat_user_tables - table stats (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_stat_user_tables AS
                    SELECT
                        0::INTEGER as relid,
                        ''::VARCHAR as schemaname,
                        ''::VARCHAR as relname,
                        0::BIGINT as seq_scan,
                        0::BIGINT as seq_tup_read,
                        0::BIGINT as idx_scan,
                        0::BIGINT as idx_tup_fetch,
                        0::BIGINT as n_tup_ins,
                        0::BIGINT as n_tup_upd,
                        0::BIGINT as n_tup_del,
                        0::BIGINT as n_tup_hot_upd,
                        0::BIGINT as n_live_tup,
                        0::BIGINT as n_dead_tup,
                        0::BIGINT as n_mod_since_analyze,
                        0::BIGINT as n_ins_since_vacuum,
                        NULL::TIMESTAMP as last_vacuum,
                        NULL::TIMESTAMP as last_autovacuum,
                        NULL::TIMESTAMP as last_analyze,
                        NULL::TIMESTAMP as last_autoanalyze,
                        0::BIGINT as vacuum_count,
                        0::BIGINT as autovacuum_count,
                        0::BIGINT as analyze_count,
                        0::BIGINT as autoanalyze_count
                    WHERE false
                """)
                stubs_created.append("pg_stat_user_tables")
            except Exception as e:
                pass

            # pg_language - procedural languages (stub with common languages)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_language AS
                    SELECT
                        oid::INTEGER as oid,
                        lanname::VARCHAR as lanname,
                        lanowner::INTEGER as lanowner,
                        lanispl::BOOLEAN as lanispl,
                        lanpltrusted::BOOLEAN as lanpltrusted,
                        lanplcallfoid::INTEGER as lanplcallfoid,
                        laninline::INTEGER as laninline,
                        lanvalidator::INTEGER as lanvalidator,
                        lanacl::VARCHAR as lanacl
                    FROM (
                        SELECT 12 as oid, 'internal' as lanname, 10 as lanowner, false as lanispl, false as lanpltrusted, 0 as lanplcallfoid, 0 as laninline, 0 as lanvalidator, NULL as lanacl
                        UNION ALL
                        SELECT 13 as oid, 'c' as lanname, 10 as lanowner, false as lanispl, false as lanpltrusted, 0 as lanplcallfoid, 0 as laninline, 0 as lanvalidator, NULL as lanacl
                        UNION ALL
                        SELECT 14 as oid, 'sql' as lanname, 10 as lanowner, false as lanispl, true as lanpltrusted, 0 as lanplcallfoid, 0 as laninline, 0 as lanvalidator, NULL as lanacl
                        UNION ALL
                        SELECT 13346 as oid, 'plpgsql' as lanname, 10 as lanowner, true as lanispl, true as lanpltrusted, 0 as lanplcallfoid, 0 as laninline, 0 as lanvalidator, NULL as lanacl
                    ) _pg_language_data
                """)
                stubs_created.append("pg_language")
            except Exception as e:
                pass

            # pg_proc - procedures/functions (minimal stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_proc AS
                    SELECT
                        0::INTEGER as oid,
                        ''::VARCHAR as proname,
                        0::INTEGER as pronamespace,
                        0::INTEGER as proowner,
                        0::INTEGER as prolang,
                        0::DOUBLE as procost,
                        0::DOUBLE as prorows,
                        0::INTEGER as provariadic,
                        ''::VARCHAR as prosupport,
                        ''::VARCHAR as prokind,
                        false::BOOLEAN as prosecdef,
                        false::BOOLEAN as proleakproof,
                        false::BOOLEAN as proisstrict,
                        false::BOOLEAN as proretset,
                        ''::VARCHAR as provolatile,
                        ''::VARCHAR as proparallel,
                        0::INTEGER as pronargs,
                        0::INTEGER as pronargdefaults,
                        0::INTEGER as prorettype,
                        NULL::INTEGER[] as proargtypes,
                        NULL::INTEGER[] as proallargtypes,
                        NULL::VARCHAR[] as proargmodes,
                        NULL::VARCHAR[] as proargnames,
                        NULL::VARCHAR as proargdefaults,
                        NULL::INTEGER[] as protrftypes,
                        ''::VARCHAR as prosrc,
                        ''::VARCHAR as probin,
                        NULL::VARCHAR[] as proconfig,
                        NULL::VARCHAR as proacl
                    WHERE false
                """)
                stubs_created.append("pg_proc")
            except Exception as e:
                pass

            # if stubs_created:
            #     styled_print(f"[{self.session_id}]   {S.DONE} Created PG compat stubs: {', '.join(stubs_created)}")

        except Exception as e:
            self._runtime_log(
                "WARN",
                f"Error creating PG compat stubs: {e}",
                event="pg_compat_stubs_error",
                error_type=type(e).__name__,
            )

    def handle_startup(self, startup_params: dict):
        """
        Handle client startup message.

        Extracts database name and username from startup params.
        Sets up session_id and ClickHouse results namespace for INTO tables.

        Notes:
        - DuckDB is always ephemeral per pgwire connection.
        - The `database` name namespaces INTO tables into ClickHouse database: lars_results_<database>.
        """
        import re

        # Different clients vary slightly in startup param keys; be liberal in what we accept.
        database = (
            startup_params.get('database')
            or startup_params.get('dbname')
            or startup_params.get('db')
            or 'default'
        )
        user = (
            startup_params.get('user')
            or startup_params.get('username')
            or 'lars'
        )
        application_name = startup_params.get('application_name', 'unknown')

        # Some drivers may smuggle dbname via `options` (rare); best-effort.
        options = startup_params.get('options')
        if (not startup_params.get('database')) and options:
            m = re.search(r'(?i)(?:--dbname=|-d\s+)([a-zA-Z0-9_-]+)', options)
            if m:
                database = m.group(1)

        self.user_name = user
        self.application_name = application_name

        if os.environ.get('LARS_PG_LOG_STARTUP_PARAMS') == '1':
            self._runtime_log(
                "DEBUG",
                "Startup params",
                event="startup_params",
                startup_params=startup_params,
            )

        # Enforce safe database names (used for ClickHouse namespace: lars_results_<db_name>).
        # Be strict: reject anything outside [A-Za-z_][A-Za-z0-9_]{0,63}.
        # This avoids injection and "silent fixing" that could misroute persisted tables.
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", database or ""):
            raise ValueError(
                f"Invalid database name '{database}'. "
                "Use only letters, numbers, and underscores; must start with a letter or underscore; max 64 chars."
            )

        # Store database name for session setup
        self.database_name = database
        self.results_db_name = f"lars_results_{database}"

        # Create unique session_id per client connection
        # Each client needs its own connection for thread safety
        client_id = uuid.uuid4().hex[:8]
        self.session_id = f"{self.session_prefix}_{database}_{client_id}"

        self._runtime_log(
            "INFO",
            "Client startup",
            event="startup",
            user=user,
            database=database,
            results_db=self.results_db_name,
            application_name=application_name,
        )

        # Note: send_startup_response is called AFTER setup_session in handle()

    def _authenticate(self) -> bool:
        """
        Authenticate the client using API key or password.

        If LARS_AUTH_ENABLED is set, this method:
        1. Sends AuthenticationCleartextPassword to request password
        2. Reads PasswordMessage response from client
        3. Validates the credential as either:
           - A LARS API key (JWT token)
           - A user password
        4. Sets self.authenticated_user with user info

        Returns:
            True if authentication successful (or auth disabled)
            False if authentication failed
        """
        try:
            from lars.auth import get_auth_manager

            auth = get_auth_manager()

            # If auth disabled, allow all connections
            if not auth.is_enabled():
                self.authenticated_user = None
                self.auth_user_id = 'anonymous'
                return True

            # Request password from client
            self._runtime_log(
                "INFO",
                "Requesting authentication...",
                event="auth_request",
            )
            self.sock.sendall(AuthenticationCleartextPassword.encode())

            # Read password response
            credential = PasswordMessage.read(self.sock)
            if credential is None:
                self._runtime_log(
                    "WARN",
                    "No password provided",
                    event="auth_no_password",
                )
                return False

            # Validate the credential (API key or password)
            # Username comes from the StartupMessage (self.user_name)
            print(f"[pgwire._authenticate] Attempting auth for user={self.user_name!r}, credential_len={len(credential)}, pid={os.getpid()}")
            user = auth.authenticate(self.user_name, credential)
            if not user:
                print(f"[pgwire._authenticate] ❌ Auth failed for user={self.user_name!r}, pid={os.getpid()}")
                self._runtime_log(
                    "WARN",
                    f"Invalid credentials for user: {self.user_name}",
                    event="auth_invalid_credentials",
                    user_name=self.user_name,
                )
                return False

            # Store authenticated user info
            self.authenticated_user = user
            self.auth_user_id = user['user_id']

            auth_method = user.get('auth_method', 'unknown')
            if auth_method == 'api_key':
                self._runtime_log(
                    "INFO",
                    f"Authenticated: {user.get('username')} (key: {user.get('key_name', 'api')})",
                    event="auth_success",
                    auth_method="api_key",
                    username=user.get("username"),
                    key_name=user.get("key_name", "api"),
                )
            else:
                self._runtime_log(
                    "INFO",
                    f"Authenticated: {user.get('username')} (password)",
                    event="auth_success",
                    auth_method="password",
                    username=user.get("username"),
                )
            return True

        except ImportError:
            # Auth module not available - allow connection
            self._runtime_log(
                "WARN",
                "Auth module not available - allowing connection",
                event="auth_module_missing",
            )
            self.authenticated_user = None
            self.auth_user_id = 'anonymous'
            return True
        except Exception as e:
            self._runtime_log(
                "ERROR",
                f"Authentication error: {e}",
                event="auth_error",
                error_type=type(e).__name__,
            )
            return False

    # =========================================================================
    # SQL Trail Query Tracking Helpers
    # =========================================================================
    # These methods provide unified logging for both Simple Query Protocol
    # (handle_query) and Extended Query Protocol (_handle_execute).

    def _get_duckdb_attachments(self):
        """
        Get list of DuckDB attachments for caller context.

        Returns:
            List of (alias, path) tuples for attached databases.
        """
        attachments = []
        try:
            rows = self.duckdb_conn.execute("""
                SELECT database_alias, database_path
                FROM _lars_attachments
                ORDER BY id
            """).fetchall()
            attachments = [(alias, path) for alias, path in rows]
        except Exception:
            try:
                rows = self.duckdb_conn.execute("""
                    SELECT database_name, path
                    FROM duckdb_databases()
                    WHERE database_name NOT IN ('memory', 'system', 'temp')
                      AND path IS NOT NULL AND path != ''
                """).fetchall()
                attachments = [(name, path) for name, path in rows]
            except Exception:
                pass
        return attachments

    def _setup_query_tracking(self, query: str, original_query: str | None = None):
        """
        Set up query tracking for SQL Trail if this is an LARS statement.

        This method checks if the query contains LARS syntax, semantic operators,
        or UDF calls, and if so, sets up caller context and starts tracking.

        Args:
            query: The query to execute (may be rewritten)
            original_query: The original query before rewriting (for detection/logging).
                           If None, uses `query` for both.

        Returns:
            Tuple of (query_id, start_time, caller_id) if tracking was set up,
            or (None, None, None) if this is not an LARS statement.
        """
        from lars.sql_rewriter import _is_lars_statement

        # Use original_query for detection if available, otherwise use query
        detection_query = original_query if original_query else query

        # Skip catalog/introspection queries - they have no semantic SQL, cost nothing,
        # and just clutter the SQL Trail UI. Check both original and rewritten query
        # since catalog detection needs to catch both forms.
        if self._is_catalog_query(detection_query) or self._is_catalog_query(query):
            return None, None, None

        if not _is_lars_statement(detection_query):
            return None, None, None

        import time
        from lars.session_naming import generate_woodland_id
        from lars.caller_context import set_caller_context, build_sql_metadata, set_duckdb_attachments
        from lars.sql_trail import log_query_start

        caller_id = f"sql-{generate_woodland_id()}"
        metadata = build_sql_metadata(
            sql_query=detection_query,
            protocol="postgresql_wire",
            triggered_by="postgres_server"
        )
        set_caller_context(caller_id, metadata, connection_id=self.session_id)

        # Set up DuckDB attachments for sql_statement mode
        attachments = self._get_duckdb_attachments()
        set_duckdb_attachments(self.session_id, attachments)

        self._runtime_log(
            "DEBUG",
            f"Set caller_context: {caller_id} ({len(attachments)} attachments)",
            event="caller_context_set",
            caller_id=caller_id,
            attachments_count=len(attachments),
        )

        query_start_time = time.time()
        log_query = original_query if original_query else query
        query_id = log_query_start(
            caller_id=caller_id,
            query_raw=log_query,
            protocol='postgresql_wire'
        )

        return query_id, query_start_time, caller_id

    def _complete_query_tracking(
        self,
        query_id,
        query_start_time,
        caller_id,
        result_df,
        result_location=None
    ):
        """
        Log query completion for SQL Trail.

        Called after successful query execution to record duration, row count,
        cascade execution info, and result location.

        Args:
            query_id: The query_id returned from _setup_query_tracking
            query_start_time: The start time returned from _setup_query_tracking
            caller_id: The caller_id returned from _setup_query_tracking
            result_df: The result DataFrame (for row count)
            result_location: Optional dict with {db_name, db_path, schema_name, table_name}
        """
        if not query_id or not query_start_time:
            return

        try:
            import time
            from lars.sql_trail import (
                log_query_complete,
                get_cascade_paths, get_cascade_summary, clear_cascade_executions,
                get_and_clear_cache_counts
            )
            from lars.caller_context import clear_caller_context

            duration_ms = (time.time() - query_start_time) * 1000

            cascade_paths = get_cascade_paths(caller_id) if caller_id else []
            cascade_summary = get_cascade_summary(caller_id) if caller_id else {}

            # Get accumulated cache counts for this query
            cache_hits, cache_misses = get_and_clear_cache_counts(caller_id)

            result_kwargs = {}
            if result_location:
                # New format: results stored in ClickHouse (lars_results.query_results)
                # The API will query ClickHouse directly using caller_id
                if result_location.get('stored_in') == 'clickhouse':
                    # Just log that we have results, actual data is in lars_results database
                    self._runtime_log(
                        "DEBUG",
                        f"Results stored in ClickHouse: caller_id={result_location.get('caller_id')}, rows={result_location.get('row_count')}",
                        event="sql_trail_result_stored_clickhouse",
                        caller_id=result_location.get("caller_id"),
                        row_count=result_location.get("row_count"),
                    )
                else:
                    # Legacy format (DuckDB) - for backwards compatibility
                    result_kwargs = {
                        'result_db_name': result_location.get('db_name'),
                        'result_db_path': result_location.get('db_path'),
                        'result_schema': result_location.get('schema_name'),
                        'result_table': result_location.get('table_name'),
                    }
                    self._runtime_log(
                        "DEBUG",
                        f"Logging result location to SQL Trail: {result_kwargs}",
                        event="sql_trail_result_location",
                        result_location=result_kwargs,
                    )

            log_query_complete(
                query_id=query_id,
                status='completed',
                rows_output=len(result_df) if result_df is not None else 0,
                duration_ms=duration_ms,
                cascade_paths=cascade_paths,
                cascade_count=cascade_summary.get('cascade_count', 0),
                cache_hits=cache_hits,
                cache_misses=cache_misses,
                **result_kwargs
            )

            if caller_id:
                clear_cascade_executions(caller_id)
            clear_caller_context(connection_id=self.session_id)

        except Exception as e:
            self._runtime_log(
                "WARN",
                f"SQL Trail completion log failed: {e}",
                event="sql_trail_complete_error",
                error_type=type(e).__name__,
            )

    def _error_query_tracking(
        self,
        query_id,
        query_start_time,
        error
    ):
        """
        Log query error for SQL Trail.

        Called when query execution fails to record the error and duration.

        Args:
            query_id: The query_id returned from _setup_query_tracking
            query_start_time: The start time returned from _setup_query_tracking
            error: The exception that occurred
        """
        if not query_id or not query_start_time:
            return

        try:
            import time
            from lars.sql_trail import log_query_error
            from lars.caller_context import clear_caller_context

            duration_ms = (time.time() - query_start_time) * 1000
            log_query_error(
                query_id=query_id,
                error_message=str(error),
                error_type=type(error).__name__,
                duration_ms=duration_ms,
            )
            clear_caller_context(connection_id=self.session_id)

        except Exception as e:
            self._runtime_log(
                "WARN",
                f"SQL Trail error log failed: {e}",
                event="sql_trail_error_log_failed",
                error_type=type(e).__name__,
            )

    def _split_sql_statements(self, sql: str) -> list[str]:
        """
        Split SQL into individual statements, respecting string literals and comments.

        Splits on semicolons that are not inside strings or comments.
        """
        from ..sql_tools.pipeline_parser import _tokenize

        statements: list[str] = []
        current: list[str] = []

        for tok in _tokenize(sql):
            if tok.typ == "punct" and tok.text == ";":
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
                continue
            current.append(tok.text)

        stmt = "".join(current).strip()
        if stmt:
            statements.append(stmt)

        return statements

    def handle_query(self, query: str):
        """
        Execute query on DuckDB and send results to client.

        Args:
            query: SQL query string (may include lars_udf(), lars_cascade_udf())
        """
        self.query_count += 1

        # Clean query (remove null terminators, whitespace)
        query = query.strip()

        # Support multiple statements in a single Simple Query message (e.g. "SELECT 1; SELECT 2;")
        # IMPORTANT: Clients read until ReadyForQuery, so we must only send ReadyForQuery once at the end.
        if ';' in query:
            split_statements = self._split_sql_statements(query)
            if len(split_statements) > 1:
                self._handle_multi_statement_query(split_statements, original_query=query)
                return
            # Normalize single-statement queries by stripping trailing semicolons
            if len(split_statements) == 1:
                query = split_statements[0]
            elif len(split_statements) == 0:
                query = ""

        # Handle empty queries (PostgreSQL protocol requirement)
        # Some clients (like DataGrip) send empty queries for protocol probing
        if not query:
            self._runtime_log("DEBUG", f"Query #{self.query_count}: (empty)", event="query_empty", query_count=self.query_count)
            self.sock.sendall(EmptyQueryResponse.encode())
            self.sock.sendall(ReadyForQuery.encode(self.transaction_status))
            return

        # Log query (show more for catalog queries)
        is_catalog = self._is_catalog_query(query.upper())
        if is_catalog:
            self._runtime_log(
                "DEBUG",
                f"Query #{self.query_count} [CATALOG]: {query[:200]}{'...' if len(query) > 200 else ''}",
                event="query_received",
                query_count=self.query_count,
                is_catalog=True,
            )
        else:
            self._runtime_log(
                "INFO",
                f"Query #{self.query_count}: {query[:200]}{'...' if len(query) > 200 else ''}",
                event="query_received",
                query_count=self.query_count,
                is_catalog=False,
                query=query,
            )

        try:
            # Handle PostgreSQL-specific SET commands that DuckDB doesn't understand
            query_upper = query.upper()

            if query_upper.startswith('SET ') or query_upper.startswith('RESET '):
                # PostgreSQL clients send session config commands
                # DuckDB doesn't support many of these, so we fake success
                self._handle_set_command(query)
                return

            # Handle PostgreSQL SHOW commands
            if query_upper.startswith('SHOW '):
                self._handle_show_command(query)
                return

            # Handle BACKGROUND queries (async execution)
            # Token-based parsing handles newlines and whitespace properly
            if query_upper.startswith('BACKGROUND'):
                from ..sql_tools.sql_directives import parse_sql_directives
                directive, inner_sql = parse_sql_directives(query)
                if directive and directive.directive_type == 'BACKGROUND':
                    self._handle_background_query(inner_sql)
                    return

            # NOTE: Legacy ANALYZE 'prompt' SELECT ... directive removed.
            # Use: SELECT ... THEN ANALYZE 'prompt' [INTO ...]
            if query_upper.startswith('ANALYZE'):
                from ..sql_tools.sql_directives import parse_sql_directives
                directive, _ = parse_sql_directives(query)
                if directive and directive.directive_type == 'ANALYZE':
                    send_error(
                        self.sock,
                        "ANALYZE 'prompt' SELECT ... has been removed. Use THEN ANALYZE instead.",
                        detail="Example: SELECT * FROM t THEN ANALYZE 'what are the trends?'",
                        transaction_status=self.transaction_status,
                    )
                    return

            # Handle WATCH commands (reactive SQL subscriptions)
            # Syntax: CREATE WATCH name POLL EVERY 'interval' AS query ON TRIGGER CASCADE 'path'
            #         DROP WATCH name
            #         SHOW WATCHES
            #         DESCRIBE WATCH name
            #         TRIGGER WATCH name
            #         ALTER WATCH name SET ...
            from ..sql_tools.sql_directives import is_watch_command
            if is_watch_command(query):
                self._handle_watch_command(query)
                return

            # Handle EXPLAIN queries - must be checked BEFORE pipeline syntax
            # because EXPLAIN SELECT ... THEN PIVOT would otherwise be intercepted by pipeline handler
            # Supports: EXPLAIN SELECT ... MEANS ...
            #           EXPLAIN SELECT ... THEN PIVOT ...
            #           EXPLAIN (FORMAT JSON) SELECT ...
            #           explain\nselect ... (lowercase, newline after EXPLAIN)
            import re
            if re.match(r'^EXPLAIN[\s(]', query_upper):
                self._handle_explain_query(query)
                return

            # Handle CREATE TABLE shared.* AS SELECT - write to parquet for cross-session visibility
            # Syntax: CREATE [OR REPLACE] TABLE shared.name AS SELECT ...
            #         CREATE [OR REPLACE] TABLE shared.subdir.name AS SELECT ...
            # Note: \s* allows leading whitespace/newlines from frontend parsing
            shared_table_match = re.match(r'^\s*CREATE\s+(OR\s+REPLACE\s+)?TABLE\s+SHARED\.', query_upper)
            if shared_table_match:
                self._runtime_log(
                    "DEBUG",
                    "Intercepted CREATE TABLE shared.* -> routing to parquet handler",
                    event="shared_table_create_intercept",
                )
                self._handle_shared_table_create(query)
                return

            # Pre-process CANVAS syntax before pipeline check
            # CANVAS() rewrites to SQL with THEN RENDER_CANVAS(...) which needs pipeline handling
            from ..sql_tools.canvas_rewriter import has_canvas_syntax, rewrite_canvas_syntax
            if has_canvas_syntax(query):
                query = rewrite_canvas_syntax(query)
                self._runtime_log(
                    "DEBUG",
                    "CANVAS syntax rewritten",
                    event="canvas_rewrite",
                )

            # Handle PIPELINE syntax (THEN/INTO for post-query processing)
            # Syntax: SELECT * FROM table THEN ANALYZE 'prompt' INTO result_table
            from ..sql_tools.pipeline_parser import has_pipeline_syntax, parse_pipeline_syntax
            if has_pipeline_syntax(query):
                pipeline = parse_pipeline_syntax(query)
                if pipeline and pipeline.stages:
                    self._handle_pipeline_query(pipeline, query)
                    return

            # Handle transaction commands (BEGIN, COMMIT, ROLLBACK)
            if query_upper in ['BEGIN', 'BEGIN TRANSACTION', 'BEGIN WORK', 'START TRANSACTION']:
                self._handle_begin()
                return
            elif query_upper in ['COMMIT', 'COMMIT TRANSACTION', 'COMMIT WORK', 'END', 'END TRANSACTION']:
                self._handle_commit()
                return
            elif query_upper in ['ROLLBACK', 'ROLLBACK TRANSACTION', 'ROLLBACK WORK', 'ABORT']:
                self._handle_rollback()
                return

            # Handle ATTACH commands - track and persist for reconnection
            if query_upper.startswith('ATTACH '):
                self._handle_attach(query)
                return

            # Handle DETACH commands - cleanup views for the detached database
            if query_upper.startswith('DETACH '):
                self._handle_detach(query)
                return

            # Handle PostgreSQL catalog queries (pg_catalog, information_schema)
            if self._is_catalog_query(query):
                self._handle_catalog_query(query)
                return

            # Lazy ATTACH: attach configured sql_connections on-demand when referenced.
            # Do this before MAP/RUN execution and before prewarm distinct queries.
            if self._lazy_attach is not None:
                try:
                    self._lazy_attach.ensure_for_query(query, aggressive=False)
                    self._refresh_attached_view_cache()
                except Exception:
                    pass

            # Set caller context for LARS queries (enables cost tracking and debugging)
            # Uses unified helper for both Simple Query and Extended Query protocols
            from lars.sql_rewriter import rewrite_lars_syntax, _is_map_run_statement
            _current_query_id, _query_start_time, _caller_id = self._setup_query_tracking(query)

            if _current_query_id:
                # SPECIAL PATH: MAP PARALLEL with true concurrency
                # Only attempt to parse if this is MAP/RUN syntax (not just UDF calls)
                from lars.sql_rewriter import _parse_lars_statement
                if _is_map_run_statement(query):
                    try:
                        # Normalize query first (same as rewrite_lars_syntax does)
                        normalized = query.strip()
                        lines = [line.split('--')[0].strip() for line in normalized.split('\n')]
                        normalized = ' '.join(line for line in lines if line)

                        self._runtime_log(
                            "DEBUG",
                            f"Parsing normalized query: {normalized[:100]}...",
                            event="map_parallel_parse",
                        )
                        stmt = _parse_lars_statement(normalized)
                        self._runtime_log(
                            "DEBUG",
                            f"Parsed: mode={stmt.mode}, parallel={stmt.parallel}, as_table={stmt.with_options.get('as_table')}",
                            event="map_parallel_parsed",
                            mode=stmt.mode,
                            parallel=stmt.parallel,
                            as_table=stmt.with_options.get("as_table"),
                        )

                        # SPECIAL PATH 1: MAP PARALLEL (true concurrency)
                        # SPECIAL PATH 2: Table materialization (CREATE TABLE AS or WITH as_table)
                        # Both need server-side handling to avoid DuckDB timing issues

                        if stmt.mode == 'MAP' and (stmt.parallel or stmt.with_options.get('as_table')):
                            is_parallel = stmt.parallel is not None
                            is_materialized = stmt.with_options.get('as_table') is not None

                            if is_parallel and is_materialized:
                                self._runtime_log(
                                    "DEBUG",
                                    f"MAP PARALLEL + Materialization: {stmt.parallel} workers → {stmt.with_options['as_table']}",
                                    event="map_parallel_detected",
                                    parallel=stmt.parallel,
                                    as_table=stmt.with_options.get("as_table"),
                                )
                            elif is_parallel:
                                self._runtime_log(
                                    "DEBUG",
                                    f"MAP PARALLEL detected: {stmt.parallel} workers",
                                    event="map_parallel_detected",
                                    parallel=stmt.parallel,
                                )
                            else:
                                self._runtime_log(
                                    "DEBUG",
                                    f"Table materialization: {stmt.with_options['as_table']}",
                                    event="map_parallel_materialize_only",
                                    as_table=stmt.with_options.get("as_table"),
                                )

                        # 1. Execute USING query to get input rows
                        import re
                        using_query = stmt.using_query

                        # Apply DISTINCT if requested (BEFORE parallel execution for cache efficiency!)
                        dedupe_by = stmt.with_options.get('dedupe_by')
                        if stmt.with_options.get('distinct') or dedupe_by:
                            original_count = None
                            if dedupe_by:
                                # Count before dedupe for logging
                                try:
                                    original_count = self.duckdb_conn.execute(f"SELECT COUNT(*) FROM ({using_query}) AS t").fetchone()[0]
                                except:
                                    pass
                                # Dedupe by specific column
                                using_query = f"SELECT DISTINCT ON ({dedupe_by}) * FROM ({using_query}) AS t"
                            else:
                                # Dedupe all columns
                                using_query = f"SELECT DISTINCT * FROM ({using_query}) AS t"

                            if original_count:
                                deduped_count = self.duckdb_conn.execute(f"SELECT COUNT(*) FROM ({using_query}) AS t").fetchone()[0]
                                savings = ((original_count - deduped_count) / original_count * 100) if original_count > 0 else 0
                                self._runtime_log(
                                    "DEBUG",
                                    f"DISTINCT applied: {original_count} → {deduped_count} rows ({savings:.0f}% reduction)",
                                    event="map_parallel_deduped",
                                    original_count=original_count,
                                    deduped_count=deduped_count,
                                    savings_pct=savings,
                                    dedupe_by=dedupe_by,
                                )

                        if not re.search(r'\bLIMIT\s+\d+', using_query, re.IGNORECASE):
                            using_query += ' LIMIT 1000'  # Safety

                        self._runtime_log(
                            "DEBUG",
                            "Fetching input rows...",
                            event="map_parallel_fetch_inputs",
                        )
                        input_df = self.duckdb_conn.execute(using_query).fetchdf()
                        self._runtime_log(
                            "DEBUG",
                            f"Got {len(input_df)} input rows",
                            event="map_parallel_inputs_ready",
                            row_count=len(input_df),
                        )

                        # 2. Convert to JSON array for parallel processing
                        import json
                        rows_json = json.dumps(input_df.to_dict('records'))

                        # 3. Execute (parallel or sequential)
                        result_column = stmt.result_alias or stmt.with_options.get('result_column', 'result')

                        if is_parallel:
                            self._runtime_log(
                                "DEBUG",
                                f"Executing in parallel ({stmt.parallel} workers)...",
                                event="map_parallel_execute_start",
                                parallel=stmt.parallel,
                            )
                            from lars.sql_tools.udf import lars_map_parallel_exec

                            result_df = lars_map_parallel_exec(
                                cascade_path=stmt.cascade_path,
                                rows_json_array=rows_json,
                                max_workers=stmt.parallel,
                                result_column=result_column
                            )
                            self._runtime_log(
                                "DEBUG",
                                "Parallel execution complete",
                                event="map_parallel_execute_complete",
                                row_count=len(result_df) if result_df is not None else 0,
                            )
                        else:
                            # Sequential execution for non-parallel materialization
                            self._runtime_log(
                                "DEBUG",
                                "Executing sequentially for materialization...",
                                event="map_parallel_execute_sequential",
                            )
                            # Use the regular rewritten query but execute row-by-row
                            from lars.sql_rewriter import _rewrite_map
                            from dataclasses import replace

                            # Build statement without as_table to get clean execution query
                            temp_stmt_options = dict(stmt.with_options)
                            temp_stmt_options.pop('as_table', None)  # Remove to avoid recursive materialization

                            # Create new statement with modified options
                            temp_stmt = replace(stmt, with_options=temp_stmt_options)

                            self._runtime_log(
                                "DEBUG",
                                "Rewriting query without as_table...",
                                event="map_parallel_rewrite_without_as_table",
                            )
                            rewritten_query = _rewrite_map(temp_stmt)
                            self._runtime_log(
                                "DEBUG",
                                "Executing rewritten query...",
                                event="map_parallel_execute_rewritten",
                            )
                            result_df = self.duckdb_conn.execute(rewritten_query).fetchdf()
                            self._runtime_log(
                                "DEBUG",
                                f"Sequential execution complete ({len(result_df)} rows)",
                                event="map_parallel_execute_rewritten_complete",
                                row_count=len(result_df),
                            )

                        # 4. Apply schema extraction if specified
                        if stmt.output_columns:
                            self._runtime_log(
                                "DEBUG",
                                "Applying schema extraction...",
                                event="map_parallel_schema_extract",
                                output_columns=len(stmt.output_columns),
                            )
                            # Register result for JSON extraction
                            self.duckdb_conn.register("_parallel_raw", result_df)

                            # Build typed column extraction
                            select_cols = []
                            for col_name, col_type in stmt.output_columns:
                                # Extract from result column which contains the JSON
                                if col_type in ('VARCHAR', 'TEXT', 'STRING'):
                                    expr = f"json_extract_string({result_column}, '$.state.validated_output.{col_name}') AS {col_name}"
                                elif col_type in ('BIGINT', 'INTEGER', 'INT'):
                                    expr = f"CAST(json_extract({result_column}, '$.state.validated_output.{col_name}') AS BIGINT) AS {col_name}"
                                elif col_type in ('DOUBLE', 'FLOAT', 'REAL'):
                                    expr = f"CAST(json_extract({result_column}, '$.state.validated_output.{col_name}') AS DOUBLE) AS {col_name}"
                                elif col_type == 'BOOLEAN':
                                    expr = f"CAST(json_extract({result_column}, '$.state.validated_output.{col_name}') AS BOOLEAN) AS {col_name}"
                                elif col_type == 'JSON':
                                    expr = f"json_extract({result_column}, '$.state.validated_output.{col_name}') AS {col_name}"
                                else:
                                    expr = f"CAST(json_extract({result_column}, '$.state.validated_output.{col_name}') AS {col_type}) AS {col_name}"
                                select_cols.append(expr)

                            # Execute extraction query
                            extraction_query = f"SELECT * EXCLUDE ({result_column}), {', '.join(select_cols)} FROM _parallel_raw"
                            result_df = self.duckdb_conn.execute(extraction_query).fetchdf()
                            self.duckdb_conn.unregister("_parallel_raw")

                        # 5. Handle table materialization if requested
                        as_table = stmt.with_options.get('as_table')
                        if as_table:
                            self._runtime_log(
                                "DEBUG",
                                f"Materializing to table: {as_table}",
                                event="map_parallel_materialize_start",
                                as_table=as_table,
                            )
                            # Register and create table
                            self.duckdb_conn.register("_temp_materialize", result_df)
                            self.duckdb_conn.execute(f"CREATE OR REPLACE TEMP TABLE {as_table} AS SELECT * FROM _temp_materialize")
                            self.duckdb_conn.unregister("_temp_materialize")
                            self._runtime_log(
                                "DEBUG",
                                f"Table created: {as_table}",
                                event="map_parallel_materialize_complete",
                                as_table=as_table,
                            )

                            # Return metadata instead of data
                            import pandas as pd
                            metadata_df = pd.DataFrame([{
                                "status": "success",
                                "table_created": as_table,
                                "row_count": len(result_df),
                                "columns": list(result_df.columns)
                            }])
                            send_query_results(self.sock, metadata_df, self.transaction_status)
                        else:
                            # 6. Auto-materialize for query insurance, then send results to client
                            _result_location = self._maybe_materialize_result(query, result_df, _current_query_id, _caller_id)
                            send_query_results(self.sock, result_df, self.transaction_status)

                        if is_parallel and is_materialized:
                            self._runtime_log(
                                "DEBUG",
                                f"MAP PARALLEL + Materialized: {len(result_df)} rows, {stmt.parallel} workers → {stmt.with_options['as_table']}",
                                event="map_parallel_complete",
                                row_count=len(result_df),
                                parallel=stmt.parallel,
                                as_table=stmt.with_options.get("as_table"),
                            )
                        elif is_parallel:
                            self._runtime_log(
                                "DEBUG",
                                f"MAP PARALLEL complete: {len(result_df)} rows, {stmt.parallel} workers",
                                event="map_parallel_complete",
                                row_count=len(result_df),
                                parallel=stmt.parallel,
                            )
                        else:
                            self._runtime_log(
                                "DEBUG",
                                f"Materialized to table: {stmt.with_options['as_table']} ({len(result_df)} rows)",
                                event="map_parallel_materialize_only_complete",
                                row_count=len(result_df),
                                as_table=stmt.with_options.get("as_table"),
                            )

                        # Log query completion for SQL Trail (special path)
                        # Uses unified helper for consistent logging
                        self._complete_query_tracking(
                            _current_query_id, _query_start_time, _caller_id, result_df,
                            result_location=_result_location if '_result_location' in dir() else None
                        )

                        return  # Skip normal execution path

                    except Exception as parallel_error:
                        # If parallel execution fails, log and fall back to normal path
                        self._runtime_log(
                            "WARN",
                            f"Special path failed: {parallel_error}",
                            event="map_parallel_special_path_failed",
                            error_type=type(parallel_error).__name__,
                        )
                        if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                            traceback.print_exc()  # Use module-level import
                        self._runtime_log(
                            "DEBUG",
                            "Falling back to sequential execution",
                            event="map_parallel_fallback",
                        )
                        # Fall through to normal execution

            # Early termination detection for LIMIT-friendly semantic queries
            # This allows us to skip LLM calls once we have enough matches
            # Must detect BEFORE rewriting since operators like MEANS become function calls
            _early_term_enabled = False
            _early_term_limit = None
            try:
                from lars.sql_tools.early_termination import (
                    set_early_termination_hint,
                    is_limit_friendly_query,
                )
                from lars.sql_tools.semantic_rewriter_v2 import _tokenize

                # Quick check: does query contain scalar semantic operators?
                # BOOLEAN: MEANS, IMPLIES, CONTRADICTS, ALIGNS, MATCHES
                # DOUBLE: ABOUT (returns relevance score)
                query_upper = query.upper()
                has_semantic = any(op in query_upper for op in [
                    'MEANS', 'ABOUT', 'IMPLIES', 'CONTRADICTS',
                    'ALIGNS', 'SIMILAR', 'MATCHES',
                ])

                if has_semantic and _caller_id:
                    # Tokenize and check if limit-friendly
                    tokens = _tokenize(query)
                    is_friendly, limit_value, reason = is_limit_friendly_query(tokens)

                    if is_friendly and limit_value:
                        set_early_termination_hint(_caller_id, limit_value)
                        _early_term_enabled = True
                        _early_term_limit = limit_value
                        self._runtime_log(
                            "INFO",
                            f"Early termination enabled: LIMIT {limit_value}",
                            event="early_termination_enabled",
                            limit=limit_value,
                            caller_id=_caller_id,
                        )
                    elif limit_value and reason:
                        self._runtime_log(
                            "DEBUG",
                            f"Early termination skipped: {reason}",
                            event="early_termination_skipped",
                            limit=limit_value,
                            reason=reason,
                            caller_id=_caller_id,
                        )
            except Exception as et_error:
                # Early termination detection is non-fatal
                self._runtime_log(
                    "WARN",
                    f"Early termination check failed: {et_error}",
                    event="early_termination_error",
                    error_type=type(et_error).__name__,
                )

            # Check for prewarm sidecar opportunity (-- @ parallel: N annotation)
            # IMPORTANT: Must run BEFORE rewrite_lars_syntax which strips comments!
            # This launches a background thread to warm the cache for scalar semantic functions
            prewarm_sidecar = None
            original_query = query  # Preserve original with annotations
            try:
                from lars.sql_tools.prewarm_sidecar import maybe_launch_prewarm_sidecar
                from lars.caller_context import get_caller_id

                prewarm_caller_id = get_caller_id()
                # If no caller_id but query has parallel annotation, generate one
                if not prewarm_caller_id:
                    from lars.sql_tools.prewarm_sidecar import _get_parallel_annotation
                    if _get_parallel_annotation(original_query):
                        from lars.session_naming import generate_woodland_id
                        prewarm_caller_id = f"prewarm-{generate_woodland_id()}"
                        self._runtime_log(
                            "DEBUG",
                            f"Prewarm: generated caller_id {prewarm_caller_id}",
                            event="prewarm_generated_caller_id",
                            caller_id=prewarm_caller_id,
                        )

                if prewarm_caller_id:
                    prewarm_sidecar = maybe_launch_prewarm_sidecar(
                        query=original_query,  # Use original query with annotations
                        caller_id=prewarm_caller_id,
                        duckdb_conn=self.duckdb_conn,
                    )
            except Exception as prewarm_e:
                # Prewarm failures are non-fatal
                self._runtime_log(
                    "WARN",
                    f"Prewarm check failed: {prewarm_e}",
                    event="prewarm_error",
                    error_type=type(prewarm_e).__name__,
                )

            # Deref preprocessing: evaluate @cascade() expressions first
            from ..sql_tools.deref_preprocessor import preprocess_deref_cascades
            deref_context = {
                'session_id': f"{self.auth_user_id}:{self.database_name}",  # Scoped by user + database for param store
                'protocol': 'pgwire',
                'database_name': self.database_name,
                'user_name': self.user_name,
                'application_name': self.application_name,
                'client_address': f"{self.addr[0]}:{self.addr[1]}" if self.addr else '',
                'caller_id': getattr(self, '_current_caller_id', None),
            }
            query = preprocess_deref_cascades(query, deref_context)

            # Rewrite into_ table references to read from ClickHouse
            # Tables created with ... INTO xxx are stored in ClickHouse as:
            #   <results_db_name>.into_xxx  (results_db_name = lars_results_<database_name>)
            try:
                from ..sql_tools.into_table_rewriter import rewrite_into_tables
                query, into_changed = rewrite_into_tables(query, results_db=self.results_db_name)
                if into_changed:
                    self._runtime_log(
                        "DEBUG",
                        "INTO table references rewritten",
                        event="into_table_rewritten",
                    )
            except Exception as e:
                self._runtime_log(
                    "WARN",
                    f"INTO table rewrite skipped: {e}",
                    event="into_table_rewrite_skipped",
                    error_type=type(e).__name__,
                )

            # Rewrite LARS MAP/RUN syntax to standard SQL
            # This strips annotations/comments, so prewarm check must happen first
            # Arrow syntax (-> table_name) is converted to hint comments here
            query = rewrite_lars_syntax(query, duckdb_conn=self.duckdb_conn)

            # Extract LARS hints (e.g., save_as from arrow syntax)
            # Hints are embedded as /*LARS:key=value*/ comments
            query, lars_hints = self._extract_lars_hints(query)

            # Execute on DuckDB (with defensive None check)
            try:
                result = self.duckdb_conn.execute(query)
            except Exception as first_exec_error:
                # Retry once with aggressive lazy attach (catches missed patterns)
                if self._lazy_attach is not None:
                    try:
                        self._lazy_attach.ensure_for_query(original_query, aggressive=True)
                        result = self.duckdb_conn.execute(query)
                    except Exception:
                        raise first_exec_error
                raise
            if result is None:
                # Query returned no result object (e.g., empty after rewrite)
                import pandas as pd
                result_df = pd.DataFrame()
            else:
                result_df = result.fetchdf()

            # Auto-materialize for query insurance (uses original query for detection)
            _result_location = self._maybe_materialize_result(original_query, result_df, _current_query_id, _caller_id)

            # Arrow syntax: save result as named table if save_as hint present
            if 'save_as' in lars_hints:
                self._save_result_as(lars_hints['save_as'], result_df)

            # Send results back to client (with current transaction status)
            send_query_results(self.sock, result_df, self.transaction_status)

            self._runtime_log(
                "DEBUG",
                f"Returned {len(result_df)} rows",
                event="query_returned_rows",
                row_count=len(result_df),
            )

            # Log query completion for SQL Trail (if we started tracking)
            # Uses unified helper for consistent logging
            self._complete_query_tracking(
                _current_query_id, _query_start_time, _caller_id, result_df,
                result_location=_result_location
            )

            # Clear early termination hint and log stats
            if _early_term_enabled and _caller_id:
                try:
                    from lars.sql_tools.early_termination import clear_early_termination_hint
                    stats = clear_early_termination_hint(_caller_id)
                    if stats:
                        # Show processed vs matches for debugging
                        self._runtime_log(
                            "DEBUG",
                            f"Early termination: processed {stats.get('processed_count', 0)} rows, found {stats.get('match_count', 0)} matches (target: {stats.get('limit_hint', 0)})",
                            event="early_termination_stats",
                            stats=stats,
                        )
                except Exception:
                    pass  # Non-fatal

        except Exception as e:
            # Send error to client
            error_message = str(e)
            error_detail = traceback.format_exc()

            # Log query error for SQL Trail
            # Uses unified helper for consistent logging
            self._error_query_tracking(_current_query_id, _query_start_time, e)

            # Clear early termination hint on error (avoid leaking state)
            if _early_term_enabled and _caller_id:
                try:
                    from lars.sql_tools.early_termination import clear_early_termination_hint
                    clear_early_termination_hint(_caller_id)
                except Exception:
                    pass  # Non-fatal

            # Mark transaction as errored if we were in one
            if self.transaction_status == 'T':
                self.transaction_status = 'E'

            send_error(self.sock, error_message, detail=error_detail, transaction_status=self.transaction_status)

            self._runtime_log(
                "ERROR",
                f"Query error: {error_message}",
                event="query_error",
                error_type=type(e).__name__,
            )

    def _handle_multi_statement_query(self, statements: list[str], original_query: str) -> None:
        """
        Handle multiple SQL statements sent in a single Simple Query message.

        PostgreSQL clients read responses until ReadyForQuery, so this must send
        ReadyForQuery exactly once after all statements have been processed.
        """
        self._runtime_log(
            "INFO",
            f"Multi-statement query ({len(statements)} statements)",
            event="query_multi_statement",
            statement_count=len(statements),
            query_preview=original_query[:500],
        )

        for i, stmt in enumerate(statements, start=1):
            stmt = stmt.strip()
            if not stmt:
                continue

            self._runtime_log(
                "DEBUG",
                f"Multi-statement part {i}/{len(statements)}: {stmt[:200]}{'...' if len(stmt) > 200 else ''}",
                event="query_multi_statement_part",
                statement_index=i,
                statement_count=len(statements),
            )

            ok = self._execute_statement_no_ready(stmt)
            if not ok:
                # Match PostgreSQL semantics: errors inside a transaction move us to aborted state.
                if self.transaction_status == 'T':
                    self.transaction_status = 'E'
                break

        # One ReadyForQuery for the entire batch (Simple Query protocol requirement)
        self.sock.sendall(ReadyForQuery.encode(self.transaction_status))

    def _execute_statement_no_ready(self, query: str) -> bool:
        """
        Execute a single SQL statement and send results without ReadyForQuery.

        Returns:
            True on success, False if an error was sent.
        """
        import traceback

        query = query.strip()
        if not query:
            return True

        query_upper = query.upper()

        _query_id = None
        _query_start_time = None
        _caller_id = None

        try:
            # PostgreSQL-specific SET/RESET (no ReadyForQuery here - batch mode)
            if query_upper.startswith('SET ') or query_upper.startswith('RESET '):
                self._execute_set_command(query)
                self.sock.sendall(CommandComplete.encode('SET'))
                return True

            # PostgreSQL SHOW (no ReadyForQuery here - batch mode)
            if query_upper.startswith('SHOW '):
                self._execute_show_and_send_extended(query, send_row_description=True)
                return True

            # BACKGROUND queries (async execution)
            if query_upper.startswith('BACKGROUND'):
                from ..sql_tools.sql_directives import parse_sql_directives
                directive, inner_sql = parse_sql_directives(query)
                if directive and directive.directive_type == 'BACKGROUND':
                    return bool(self._handle_background_query(inner_sql, extended_query_mode=True, send_row_description=True))

            # Legacy ANALYZE directive removed (keep behavior consistent with Simple Query mode)
            if query_upper.startswith('ANALYZE'):
                from ..sql_tools.sql_directives import parse_sql_directives
                directive, _ = parse_sql_directives(query)
                if directive and directive.directive_type == 'ANALYZE':
                    self.sock.sendall(ErrorResponse.encode(
                        'ERROR',
                        "ANALYZE 'prompt' SELECT ... has been removed. Use THEN ANALYZE instead.",
                        detail="Example: SELECT * FROM t THEN ANALYZE 'what are the trends?'",
                    ))
                    if self.transaction_status == 'T':
                        self.transaction_status = 'E'
                    return False

            # WATCH commands (reactive subscriptions)
            # NOTE: The Simple Query multi-statement protocol expects a single ReadyForQuery at the end.
            # The WATCH command handlers currently use Simple Query response helpers, so disallow batching.
            from ..sql_tools.sql_directives import is_watch_command
            if is_watch_command(query):
                self.sock.sendall(ErrorResponse.encode(
                    'ERROR',
                    "Batched WATCH commands are not supported (send as separate statements).",
                ))
                if self.transaction_status == 'T':
                    self.transaction_status = 'E'
                return False

            # EXPLAIN must be checked BEFORE pipeline syntax
            import re
            if re.match(r'^EXPLAIN[\s(]', query_upper):
                ok = self._handle_explain_query_extended(query, send_row_description=True)
                return bool(ok)

            # Handle CREATE TABLE shared.* AS SELECT
            shared_table_match = re.match(r'^\s*CREATE\s+(OR\s+REPLACE\s+)?TABLE\s+SHARED\.', query_upper)
            if shared_table_match:
                ok = self._handle_shared_table_create(query, send_ready=False)
                return bool(ok)

            # Pre-process CANVAS syntax before pipeline check
            from ..sql_tools.canvas_rewriter import has_canvas_syntax, rewrite_canvas_syntax
            if has_canvas_syntax(query):
                query = rewrite_canvas_syntax(query)
                query_upper = query.upper()

            # PIPELINE syntax (THEN/INTO)
            from ..sql_tools.pipeline_parser import has_pipeline_syntax, parse_pipeline_syntax
            if has_pipeline_syntax(query):
                pipeline = parse_pipeline_syntax(query)
                if pipeline and pipeline.stages:
                    ok = self._handle_pipeline_query(pipeline, query, extended_query_mode=True, send_row_description=True)
                    return bool(ok)

            # Transaction commands (BEGIN, COMMIT, ROLLBACK)
            if query_upper in ['BEGIN', 'BEGIN TRANSACTION', 'BEGIN WORK', 'START TRANSACTION']:
                return self._handle_begin(send_ready=False)
            if query_upper in ['COMMIT', 'COMMIT TRANSACTION', 'COMMIT WORK', 'END', 'END TRANSACTION']:
                return self._handle_commit(send_ready=False)
            if query_upper in ['ROLLBACK', 'ROLLBACK TRANSACTION', 'ROLLBACK WORK', 'ABORT']:
                return self._handle_rollback(send_ready=False)

            # ATTACH/DETACH
            if query_upper.startswith('ATTACH '):
                ok = self._handle_attach(query, send_ready=False)
                return bool(ok)
            if query_upper.startswith('DETACH '):
                ok = self._handle_detach(query, send_ready=False)
                return bool(ok)

            # We intentionally do not run the Simple Query catalog handler here, since it
            # sends ReadyForQuery. Most clients won't batch catalog/introspection queries.
            if self._is_catalog_query(query):
                self.sock.sendall(ErrorResponse.encode(
                    'ERROR',
                    "Batched catalog queries are not supported (send as separate statements).",
                ))
                if self.transaction_status == 'T':
                    self.transaction_status = 'E'
                return False

            # Lazy ATTACH: attach configured sql_connections on-demand when referenced
            if self._lazy_attach is not None:
                try:
                    self._lazy_attach.ensure_for_query(query, aggressive=False)
                    self._refresh_attached_view_cache()
                except Exception:
                    pass

            # Execute normal SQL with unified rewriting (semantic operators, deref, INTO rewrites)
            from lars.sql_rewriter import rewrite_lars_syntax

            original_query = query
            _query_id, _query_start_time, _caller_id = self._setup_query_tracking(query)

            # Deref preprocessing: evaluate @cascade() expressions first
            from ..sql_tools.deref_preprocessor import preprocess_deref_cascades
            deref_context = {
                'session_id': f"{self.auth_user_id}:{self.database_name}",
                'protocol': 'pgwire',
                'database_name': self.database_name,
                'user_name': self.user_name,
                'application_name': self.application_name,
                'client_address': f"{self.addr[0]}:{self.addr[1]}" if self.addr else '',
                'caller_id': _caller_id,
            }
            query = preprocess_deref_cascades(query, deref_context)

            # Rewrite into_ table references to read from ClickHouse
            try:
                from ..sql_tools.into_table_rewriter import rewrite_into_tables
                query, _ = rewrite_into_tables(query, results_db=self.results_db_name)
            except Exception:
                pass

            # Rewrite LARS MAP/RUN syntax to standard SQL (strips annotations/comments)
            query = rewrite_lars_syntax(query, duckdb_conn=self.duckdb_conn)

            # Extract LARS hints (e.g., save_as from arrow syntax)
            query, lars_hints = self._extract_lars_hints(query)

            # Execute on DuckDB (retry once with aggressive lazy attach)
            try:
                result = self.duckdb_conn.execute(query)
            except Exception as first_exec_error:
                if self._lazy_attach is not None:
                    try:
                        self._lazy_attach.ensure_for_query(original_query, aggressive=True)
                        result = self.duckdb_conn.execute(query)
                    except Exception:
                        raise first_exec_error
                raise

            import pandas as pd
            result_df = pd.DataFrame() if result is None else result.fetchdf()

            # Auto-materialize for query insurance
            _result_location = self._maybe_materialize_result(original_query, result_df, _query_id, _caller_id)

            # Arrow syntax: save result as named table if save_as hint present
            if 'save_as' in lars_hints:
                self._save_result_as(lars_hints['save_as'], result_df)

            # Send results (no ReadyForQuery)
            send_execute_results(self.sock, result_df, send_row_description=True)

            # SQL Trail completion
            self._complete_query_tracking(
                _query_id, _query_start_time, _caller_id, result_df,
                result_location=_result_location
            )

            return True

        except Exception as e:
            error_message = str(e)
            error_detail = traceback.format_exc()

            # Mark transaction as errored if we were in one
            if self.transaction_status == 'T':
                self.transaction_status = 'E'

            # SQL Trail error logging + caller_context cleanup (if we started tracking)
            self._error_query_tracking(_query_id, _query_start_time, e)

            self.sock.sendall(ErrorResponse.encode('ERROR', error_message, detail=error_detail))
            return False

    def _is_catalog_query(self, query: str) -> bool:
        """
        Check if query is a PostgreSQL catalog query.

        DBeaver and other clients query pg_catalog, information_schema, pg_class, etc.
        to get metadata (tables, columns, types).

        Returns:
            True if this is a catalog/metadata query
        """
        query_upper = query.upper()

        # Common catalog patterns
        catalog_indicators = [
            'PG_CATALOG',
            'PG_CLASS',
            'PG_NAMESPACE',
            'PG_TYPE',
            'PG_ATTRIBUTE',
            'PG_INDEX',
            'PG_DATABASE',
            'PG_TABLES',
            'PG_TABLESPACE',      # DataGrip: tablespaces
            'PG_PROC',
            'PG_DESCRIPTION',
            'PG_SETTINGS',
            'PG_LOCKS',           # DataGrip: transaction locks
            'PG_STAT_ACTIVITY',   # DataGrip: session info
            'PG_IS_IN_RECOVERY',  # DataGrip: replica check
            'TXID_CURRENT',       # DataGrip: transaction ID
            'PG_TIMEZONE_NAMES',  # DataGrip: timezone list
            'PG_TIMEZONE_ABBREVS',
            'PG_ROLES',           # DataGrip: user management
            'PG_USER',            # DataGrip: user permissions
            'PG_AUTH_MEMBERS',    # DataGrip: role membership
            'INFORMATION_SCHEMA',
            '::REGCLASS',  # PostgreSQL type casting
            '::REGPROC',
            '::REGTYPE',
            '::OID',
            'CURRENT_SCHEMA',
            'CURRENT_DATABASE',
            'VERSION()',
            'HAS_TABLE_PRIVILEGE',
            'HAS_SCHEMA_PRIVILEGE'
        ]

        return any(indicator in query_upper for indicator in catalog_indicators)

    def _handle_catalog_query(self, query: str):
        """
        Handle PostgreSQL catalog queries using pg_catalog views and information_schema.

        With pg_catalog views now created, most queries will work automatically.
        This method handles special cases and provides fallbacks.

        Args:
            query: Catalog query
        """
        import pandas as pd

        query_upper = query.upper()

        self._runtime_log(
            "DEBUG",
            f"Catalog query detected: {query[:80]}...",
            event="catalog_query_detected",
            query_preview=query[:200],
        )

        try:
            # ACL aggregation queries (DataGrip) often UNION tablespace + database ACLs.
            # DuckDB's pg_database lacks datacl, so return an empty but correctly-shaped result.
            if 'PG_TABLESPACE' in query_upper and 'PG_DATABASE' in query_upper and 'DATACL' in query_upper:
                cols = self._expected_result_columns(query) or ['object_id', 'acl']
                send_query_results(self.sock, self._empty_df_for_columns(cols), self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    "ACL union catalog query handled (empty)",
                    event="catalog_acl_union_empty",
                )
                return

            # pg_database list queries (DataGrip schema browser)
            # Must come BEFORE current_database() handler since queries often contain both.
            import re
            is_pg_database_from = re.search(r'(?is)\bfrom\s+(?:pg_catalog\.)?pg_database\b', query) is not None
            wants_extended_pg_database = any(
                token in query_upper
                for token in (
                    'DATDBA',
                    'DATISTEMPLATE',
                    'DATALLOWCONN',
                    'DATCONNLIMIT',
                    'DATCOLLATE',
                    'DATCTYPE',
                    'ENCODING',
                    'DATTABLESPACE',
                    'PG_DATABASE_SIZE',
                    'PG_GET_USERBYID',
                    'PG_ENCODING_TO_CHAR',
                )
            )
            if is_pg_database_from and wants_extended_pg_database:
                cols = self._expected_result_columns(query)
                if not cols:
                    cols = [
                        'id',
                        'name',
                        'description',
                        'is_template',
                        'allow_connections',
                        'owner',
                    ]

                db_description = 'LARS Database'
                base = {
                    'id': 1,
                    'oid': 1,
                    'name': self.database_name,
                    'datname': self.database_name,
                    'description': db_description,
                    'is_template': False,
                    'datistemplate': False,
                    'allow_connections': True,
                    'datallowconn': True,
                    'owner': self.user_name,
                    'datdba': 1,
                    'encoding': 6,
                    'collate': 'en_US.UTF-8',
                    'ctype': 'en_US.UTF-8',
                    'connection_limit': -1,
                    'datconnlimit': -1,
                    'tablespace': 'pg_default',
                    'dattablespace': 0,
                    'size': None,
                }
                result_df = pd.DataFrame({c: [base.get(c, base.get(c.lower(), None))] for c in cols})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    f"pg_database → {self.database_name}",
                    event="catalog_pg_database",
                    database_name=self.database_name,
                )
                return

            # PRIORITY: pg_namespace queries FIRST (before CURRENT_SCHEMA which they may contain)
            # DataGrip schema listing queries contain current_schema() but need full schema list
            # BUT: Don't handle if pg_class is the main table (pg_namespace might just be in a JOIN)
            # AND: Don't handle ACL queries (they just need nspacl, not full schema browser handling)
            is_pg_class_main = 'FROM PG_CATALOG.PG_CLASS' in query_upper or 'FROM PG_CLASS' in query_upper
            is_pg_namespace_main = ('FROM PG_CATALOG.PG_NAMESPACE' in query_upper or 'FROM PG_NAMESPACE' in query_upper)
            # ACL queries select acl/nspacl columns - should NOT use schema browser handler
            # Check SELECT clause for ACL columns (before FROM to avoid matching 'PG_NAMESPACE')
            select_clause = query_upper.split('FROM')[0] if 'FROM' in query_upper else ''
            is_acl_query = 'NSPACL' in select_clause or ' ACL' in select_clause or ',ACL' in select_clause or '.ACL' in select_clause

            if is_pg_namespace_main and not is_pg_class_main and 'FROM' in query_upper and not is_acl_query:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_namespace query for schema browser...",
                    event="catalog_pg_namespace_start",
                )
                try:
                    # Get expected columns from the query
                    expected_cols = self._expected_result_columns(query) or ['id', 'state_number', 'name', 'description', 'owner']

                    # Expand '*' or 'n.*' to actual pg_namespace columns
                    # DuckDB's pg_namespace has: oid, nspname, nspowner, nspacl
                    pg_namespace_cols = ['oid', 'nspname', 'nspowner', 'nspacl']
                    expanded_cols = []
                    for col in expected_cols:
                        if col == '*' or col.endswith('.*'):
                            expanded_cols.extend(pg_namespace_cols)
                        else:
                            expanded_cols.append(col)
                    # Deduplicate while preserving order (pandas can't handle duplicate column names)
                    seen = set()
                    unique_cols = []
                    for col in expanded_cols:
                        if col not in seen:
                            seen.add(col)
                            unique_cols.append(col)
                    expected_cols = unique_cols

                    self._runtime_log(
                        "DEBUG",
                        f"pg_namespace expected columns: {expected_cols}",
                        event="catalog_pg_namespace_expected_cols",
                        expected_cols=expected_cols,
                    )

                    # Get schema data from DuckDB's pg_catalog
                    schema_rows = self.duckdb_conn.execute(
                        "SELECT oid, nspname, nspowner FROM pg_catalog.pg_namespace"
                    ).fetchdf()

                    # Build result with columns matching what the query asked for
                    result_data = []
                    for _, row in schema_rows.iterrows():
                        row_dict = {}
                        for col in expected_cols:
                            col_lower = col.lower()
                            if col_lower in ('id', 'oid'):
                                row_dict[col] = int(row['oid'])
                            elif col_lower in ('state_number', 'xmin'):
                                row_dict[col] = 0
                            elif col_lower in ('name', 'nspname', 'schema_name'):
                                row_dict[col] = str(row['nspname'])
                            elif col_lower == 'description':
                                row_dict[col] = None
                            elif col_lower in ('owner', 'nspowner'):
                                row_dict[col] = int(row['nspowner']) if 'nspowner' in row else self.user_name
                            elif col_lower == 'nspacl':
                                row_dict[col] = None  # ACL not supported
                            else:
                                row_dict[col] = None
                        result_data.append(row_dict)

                    result_df = pd.DataFrame(result_data, columns=expected_cols)

                    # Find the name column for sorting and deduplication
                    name_col = next((c for c in expected_cols if c.lower() in ('name', 'nspname', 'schema_name')), None)

                    # Ensure pg_catalog + information_schema appear (only if we have a name column)
                    if name_col:
                        existing = set(result_df[name_col].tolist()) if len(result_df) > 0 else set()
                    else:
                        existing = set()  # No name column - skip deduplication
                    for schema_name, schema_id, desc in [('pg_catalog', 11, 'System catalog'), ('information_schema', 12, 'Information schema')]:
                        if schema_name not in existing:
                            new_row = {}
                            for col in expected_cols:
                                col_lower = col.lower()
                                if col_lower in ('id', 'oid'):
                                    new_row[col] = schema_id
                                elif col_lower in ('state_number', 'xmin'):
                                    new_row[col] = 0
                                elif col_lower in ('name', 'nspname', 'schema_name'):
                                    new_row[col] = schema_name
                                elif col_lower == 'description':
                                    new_row[col] = desc
                                elif col_lower in ('owner', 'nspowner'):
                                    new_row[col] = self.user_name
                                elif col_lower == 'nspacl':
                                    new_row[col] = None  # ACL not supported
                                else:
                                    new_row[col] = None
                            result_df = pd.concat([result_df, pd.DataFrame([new_row])], ignore_index=True)

                    # Sort by name column if available
                    if name_col and name_col in result_df.columns:
                        result_df = result_df.sort_values(name_col).reset_index(drop=True)

                    try:
                        if name_col and name_col in result_df.columns:
                            preview = [str(v) for v in result_df[name_col].head(10).tolist()]
                        else:
                            preview = [str(v) for v in result_df.iloc[:, 0].head(10).tolist()]
                    except Exception:
                        preview = []
                    self._runtime_log(
                        "DEBUG",
                        f"Schemas found: {len(result_df)}",
                        event="catalog_pg_namespace_preview",
                        schema_count=len(result_df),
                        preview=preview,
                    )

                    send_query_results(self.sock, result_df, self.transaction_status)
                    self._runtime_log(
                        "DEBUG",
                        f"pg_namespace handled ({len(result_df)} schemas)",
                        event="catalog_pg_namespace_handled",
                        schema_count=len(result_df),
                    )
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"Could not handle pg_namespace: {e}",
                        event="catalog_pg_namespace_error",
                        error_type=type(e).__name__,
                    )
                    # Fall through to default handler

            # Simple function handlers (AFTER pg_namespace to not intercept schema queries)
            # Skip if this is a pg_database or pg_namespace query
            if 'CURRENT_DATABASE()' in query_upper and 'PG_DATABASE' not in query_upper and 'PG_NAMESPACE' not in query_upper:
                cols = self._expected_result_columns(query) or ['current_database']
                row = {}
                for c in cols:
                    key = c.strip('"').lower()
                    if key in {'current_database', 'current_database()', 'a'}:  # 'a' is common alias
                        row[c] = self.database_name
                    elif key in {'current_schema', 'current_schema()'}:
                        row[c] = 'main'
                    elif key in {'current_schemas', 'current_schemas(false)', 'current_schemas(true)', 'b'}:  # 'b' is common alias
                        # PostgreSQL returns arrays like {main} or {main,pg_catalog}
                        row[c] = '{main}'
                    elif key in {'current_user', 'session_user'}:
                        row[c] = self.user_name
                    else:
                        row[c] = None
                result_df = pd.DataFrame({c: [row[c]] for c in cols})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    f"CURRENT_DATABASE() → {self.database_name}",
                    event="catalog_current_database",
                    database_name=self.database_name,
                )
                return

            # Skip if this is a pg_namespace query (which may use current_schema() in WHERE)
            if ('CURRENT_SCHEMA()' in query_upper or 'CURRENT_SCHEMAS(' in query_upper) and 'PG_NAMESPACE' not in query_upper:
                cols = self._expected_result_columns(query)
                if cols:
                    row = {}
                    for c in cols:
                        key = c.strip('"').lower()
                        if key in {'current_schema', 'current_schema()'}:
                            row[c] = 'main'
                        elif key in {'current_schemas', 'b'}:  # 'b' is common alias in DataGrip queries
                            # PostgreSQL returns arrays like {main} or {main,pg_catalog}
                            row[c] = '{main}'  # PostgreSQL array format
                        elif key in {'current_database', 'current_database()', 'a'}:  # 'a' is common alias
                            row[c] = self.database_name
                        elif key in {'session_user'}:
                            row[c] = self.user_name
                        else:
                            row[c] = None
                    result_df = pd.DataFrame({c: [row[c]] for c in cols})
                elif 'SESSION_USER' in query_upper:
                    result_df = pd.DataFrame({'current_schema': ['main'], 'session_user': [self.user_name]})
                else:
                    result_df = pd.DataFrame({'current_schema': ['main']})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    "CURRENT_SCHEMA(S) handled",
                    event="catalog_current_schema",
                )
                return

            if 'VERSION()' in query_upper:
                # Return PostgreSQL-compatible version string (avoid mentioning DuckDB to prevent IDE mode switching)
                version_str = "PostgreSQL 14.0 on x86_64-pc-linux-gnu, compiled by gcc"
                result_df = pd.DataFrame({'version': [version_str]})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    f"VERSION() → {version_str}",
                    event="catalog_version",
                )
                return

            if 'HAS_TABLE_PRIVILEGE' in query_upper or 'HAS_SCHEMA_PRIVILEGE' in query_upper:
                result_df = pd.DataFrame({'has_privilege': [True]})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    "HAS_PRIVILEGE function handled",
                    event="catalog_has_privilege",
                )
                return

            # Special case 4: PostgreSQL functions that don't exist in DuckDB
            if 'PG_GET_KEYWORDS' in query_upper:
                # Dynamically build keyword list from SQL function registry
                # catcode: U=unreserved, R=reserved, T=type, C=column
                keywords = set()

                # Core LARS keywords (always present)
                keywords.add('lars')
                keywords.add('map')

                # Get keywords from registered SQL functions
                try:
                    from lars.semantic_sql.registry import get_sql_function_registry
                    import re

                    registry = get_sql_function_registry()
                    for name, entry in registry.items():
                        # Add function name
                        keywords.add(name.lower())

                        # Extract operator keywords from patterns like "{{ text }} MEANS {{ criterion }}"
                        for operator in entry.operators:
                            # Find words between }} and {{ (the operator keywords)
                            matches = re.findall(r'\}\}\s*(\w+)', operator)
                            for match in matches:
                                keywords.add(match.lower())

                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"Could not load SQL registry: {e}",
                        event="catalog_pg_get_keywords_registry_error",
                        error_type=type(e).__name__,
                    )

                # Build result DataFrame
                lars_keywords = [(word, 'U', 'unreserved (LARS)') for word in sorted(keywords)]
                result_df = pd.DataFrame(lars_keywords, columns=['word', 'catcode', 'catdesc'])
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    f"PG_GET_KEYWORDS() → {len(lars_keywords)} LARS keywords",
                    event="catalog_pg_get_keywords",
                    keyword_count=len(lars_keywords),
                )
                return

            # Special case 5: pg_locks (DataGrip queries this for transaction info)
            if 'PG_LOCKS' in query_upper:
                # Return empty result - we don't track locks
                result_df = pd.DataFrame({'transaction_id': pd.Series([], dtype='int64')})
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Special case 6: pg_is_in_recovery() (DataGrip checks if replica)
            if 'PG_IS_IN_RECOVERY' in query_upper:
                # Not a replica - return false, or if checking txid_current, return that
                if 'TXID_CURRENT' in query_upper:
                    # Query like: CASE WHEN pg_is_in_recovery() THEN null ELSE txid_current() END
                    import time
                    txid = int(time.time() * 1000) % 4294967296
                    result_df = pd.DataFrame({'current_txid': [txid]})
                else:
                    result_df = pd.DataFrame({'pg_is_in_recovery': [False]})
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Special case 7: pg_stat_activity (DataGrip session info)
            if 'PG_STAT_ACTIVITY' in query_upper:
                result_df = pd.DataFrame({
                    'datid': [0],
                    'datname': [self.database_name],
                    'pid': [1],
                    'usename': [self.user_name],
                    'application_name': [self.application_name or ''],
                    'state': ['active']
                })
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_timezone_names/pg_timezone_abbrevs (DataGrip queries these)
            if 'PG_TIMEZONE_NAMES' in query_upper or 'PG_TIMEZONE_ABBREVS' in query_upper:
                cols = self._expected_result_columns(query) or ['name', 'is_dst']
                # Return common timezones (minimal shape, matching DataGrip's union query)
                rows = [
                    {'name': 'UTC', 'is_dst': False},
                    {'name': 'America/New_York', 'is_dst': False},
                    {'name': 'America/Los_Angeles', 'is_dst': False},
                    {'name': 'Europe/London', 'is_dst': False},
                ]
                result_df = pd.DataFrame([{c: r.get(c, None) for c in cols} for r in rows])
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_roles (DataGrip queries this for user management)
            if 'PG_ROLES' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['role_id', 'role_name']
                # Use 1/0 for booleans - JDBC expects integers for these fields
                base = {
                    'role_id': 1,
                    'id': 1,
                    'oid': 1,
                    'rolname': self.user_name,
                    'role_name': self.user_name,
                    'is_super': 1,
                    'rolsuper': 1,
                    'is_inherit': 1,
                    'rolinherit': 1,
                    'can_createrole': 1,
                    'rolcreaterole': 1,
                    'can_createdb': 1,
                    'rolcreatedb': 1,
                    'can_login': 1,
                    'rolcanlogin': 1,
                    'rolreplication': 0,
                    'rolbypassrls': 0,
                    'rolconnlimit': -1,
                }
                result_df = pd.DataFrame({c: [base.get(c, base.get(c.lower(), None))] for c in cols})
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_user_mappings (DataGrip queries for FDW user mappings)
            # Must check before pg_user to avoid false match
            if 'PG_USER_MAPPINGS' in query_upper:
                cols = self._expected_result_columns(query) or ['id', 'server_id', 'user', 'options']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_user (DataGrip queries this for user permissions)
            # Exclude pg_user_mappings which contains 'PG_USER'
            if 'PG_USER' in query_upper and 'FROM' in query_upper and 'PG_USER_MAPPINGS' not in query_upper:
                cols = self._expected_result_columns(query) or ['usename', 'usesuper']
                # Use 1/0 for booleans - JDBC expects integers for these fields
                base = {
                    'usename': self.user_name,
                    'usesysid': 1,
                    'usecreatedb': 1,
                    'usesuper': 1,
                    'userepl': 1,
                    'usebypassrls': 0,
                    'passwd': None,
                    'valuntil': None,
                    'useconfig': None,
                }
                result_df = pd.DataFrame({c: [base.get(c, base.get(c.lower(), None))] for c in cols})
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_auth_members (DataGrip queries for role membership)
            if 'PG_AUTH_MEMBERS' in query_upper:
                cols = self._expected_result_columns(query) or ['id', 'role_id', 'admin_option']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_language (DataGrip queries for procedural languages)
            if 'PG_LANGUAGE' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['oid', 'lanname']
                # Provide standard PostgreSQL languages
                languages = [
                    {'oid': 12, 'lanname': 'internal', 'lanowner': 10, 'lanispl': False, 'lanpltrusted': False,
                     'lanplcallfoid': 0, 'laninline': 0, 'lanvalidator': 0, 'lanacl': None},
                    {'oid': 13, 'lanname': 'c', 'lanowner': 10, 'lanispl': False, 'lanpltrusted': False,
                     'lanplcallfoid': 0, 'laninline': 0, 'lanvalidator': 0, 'lanacl': None},
                    {'oid': 14, 'lanname': 'sql', 'lanowner': 10, 'lanispl': False, 'lanpltrusted': True,
                     'lanplcallfoid': 0, 'laninline': 0, 'lanvalidator': 0, 'lanacl': None},
                    {'oid': 13346, 'lanname': 'plpgsql', 'lanowner': 10, 'lanispl': True, 'lanpltrusted': True,
                     'lanplcallfoid': 0, 'laninline': 0, 'lanvalidator': 0, 'lanacl': None},
                ]
                result_df = pd.DataFrame([{c: lang.get(c, lang.get(c.lower(), None)) for c in cols} for lang in languages])
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_cast queries (DataGrip queries for type casting information)
            if 'PG_CAST' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['oid', 'castsource', 'casttarget', 'castfunc', 'castcontext', 'castmethod']
                # Return empty - DuckDB doesn't have pg_cast
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_collation queries (DataGrip queries for collation information)
            if self._primary_from_table(query_upper) == 'PG_COLLATION':
                cols = self._expected_result_columns(query) or ['oid', 'collname', 'collnamespace', 'collowner']
                # Return empty - DuckDB doesn't have pg_collation
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_inherits queries (including subqueries) - DuckDB doesn't have inheritance
            # Only match if pg_inherits is the main table, not just a LEFT JOIN in a pg_class query
            if 'PG_INHERITS' in query_upper and 'PG_CLASS' not in query_upper:
                cols = self._expected_result_columns(query) or ['inhrelid', 'inhparent', 'inhseqno']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_partitioned_table queries - DuckDB doesn't have table partitioning metadata
            if 'PG_PARTITIONED_TABLE' in query_upper:
                cols = self._expected_result_columns(query) or ['partrelid', 'partstrat', 'partnatts']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_operator queries - DuckDB doesn't have pg_operator
            if self._primary_from_table(query_upper) == 'PG_OPERATOR':
                cols = self._expected_result_columns(query) or ['oid', 'oprname', 'oprnamespace', 'oprowner']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_aggregate queries - DuckDB doesn't have pg_aggregate
            if 'PG_AGGREGATE' in query_upper:
                cols = self._expected_result_columns(query) or ['aggfnoid', 'aggkind', 'aggnumdirectargs']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle complex pg_constraint queries with PostgreSQL-specific array functions
            # These use UNNEST, regoper::varchar etc. that don't work in DuckDB
            if 'PG_CONSTRAINT' in query_upper and ('CONEXCLOP' in query_upper or 'UNNEST' in query_upper or 'REGOPER' in query_upper):
                cols = self._expected_result_columns(query) or ['oid', 'conname', 'connamespace', 'contype']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_tablespace queries (DataGrip queries this)
            if 'PG_TABLESPACE' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['id', 'name']
                base = {
                    'id': 1,
                    'oid': 0,
                    'name': 'pg_default',
                    'spcname': 'pg_default',
                    'spcowner': 1,
                    'owner': self.user_name,
                    'location': '',
                    'description': 'Default tablespace',
                    'state_number': 0,
                }
                result_df = pd.DataFrame({c: [base.get(c, base.get(c.lower(), None))] for c in cols})
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_extension (DataGrip queries for extensions)
            if 'PG_EXTENSION' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['oid', 'extname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_cast (DataGrip queries for type casts)
            if 'PG_CAST' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['oid', 'castsource', 'casttarget']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_collation (DataGrip queries for collations)
            if self._primary_from_table(query_upper) == 'PG_COLLATION':
                cols = self._expected_result_columns(query) or ['oid', 'collname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_inherits (DataGrip queries for table inheritance)
            # Only match if pg_inherits is the main table, not just a LEFT JOIN in a pg_class query
            if 'PG_INHERITS' in query_upper and 'FROM' in query_upper and 'PG_CLASS' not in query_upper:
                cols = self._expected_result_columns(query) or ['inhrelid', 'inhparent', 'inhseqno']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_foreign_table (DataGrip queries for foreign tables)
            if 'PG_FOREIGN_TABLE' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['ftrelid', 'ftserver', 'ftoptions']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_foreign_data_wrapper (DataGrip queries for FDW)
            if 'PG_FOREIGN_DATA_WRAPPER' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['oid', 'fdwname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_operator (DataGrip queries for operators)
            if self._primary_from_table(query_upper) == 'PG_OPERATOR':
                cols = self._expected_result_columns(query) or ['oid', 'oprname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_foreign_server (DataGrip queries for FDW servers)
            if 'PG_FOREIGN_SERVER' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['oid', 'srvname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Handle pg_event_trigger (DataGrip queries for event triggers)
            if 'PG_EVENT_TRIGGER' in query_upper and 'FROM' in query_upper:
                cols = self._expected_result_columns(query) or ['oid', 'evtname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            # Special case 4: pg_class queries with regclass type columns
            # DBeaver queries pg_class with c.*, which has regclass-typed columns
            # Even after column rewriting, JOIN conditions and functions still fail
            # Solution: Replace entire query with pg_tables equivalent
            if 'FROM PG_CATALOG.PG_CLASS' in query_upper and 'C.*' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Bypassing pg_class query (using compatible columns)...",
                    event="catalog_pg_class_bypass",
                )
                try:
                    # Extract WHERE clause from original query to preserve DBeaver's filters
                    import re
                    where_match = re.search(r'\bWHERE\b(.+?)(?:ORDER BY|LIMIT|$)', query, re.IGNORECASE | re.DOTALL)
                    where_clause = where_match.group(1).strip() if where_match else "c.relkind IN ('r', 'v', 'm', 'f', 'p')"

                    # Use information_schema.tables joined with pg_namespace for proper OIDs
                    # DuckDB's pg_catalog.pg_class is EMPTY - doesn't contain user tables
                    # We synthesize pg_class rows from information_schema.tables

                    # Transform WHERE clause column references (handle both prefixed c.col and unprefixed col)
                    transformed_where = where_clause
                    # relnamespace -> n.oid (with or without c. prefix)
                    transformed_where = re.sub(r'\b(c\.)?relnamespace\b', 'n.oid', transformed_where, flags=re.IGNORECASE)
                    # relkind -> CASE expression (with or without c. prefix)
                    transformed_where = re.sub(r'\b(c\.)?relkind\b', "(CASE t.table_type WHEN 'BASE TABLE' THEN 'r' WHEN 'VIEW' THEN 'v' ELSE 'r' END)", transformed_where, flags=re.IGNORECASE)
                    # relname -> t.table_name (with or without c. prefix)
                    transformed_where = re.sub(r'\b(c\.)?relname\b', 't.table_name', transformed_where, flags=re.IGNORECASE)

                    safe_query = f"""
                        SELECT
                            ABS(hash(t.table_schema || '.' || t.table_name) % 2147483647)::INTEGER as oid,
                            t.table_name as relname,
                            COALESCE(n.oid, 0) as relnamespace,
                            CASE t.table_type
                                WHEN 'BASE TABLE' THEN 'r'
                                WHEN 'VIEW' THEN 'v'
                                WHEN 'LOCAL TEMPORARY' THEN 'r'
                                ELSE 'r'
                            END as relkind,
                            0 as relowner,
                            false as relhasindex,
                            NULL::BOOLEAN as relrowsecurity,
                            NULL::BOOLEAN as relforcerowsecurity,
                            NULL::BOOLEAN as relispartition,
                            NULL::VARCHAR as description,
                            NULL::VARCHAR as partition_expr,
                            NULL::VARCHAR as partition_key
                        FROM information_schema.tables t
                        LEFT JOIN pg_catalog.pg_namespace n ON n.nspname = t.table_schema
                        WHERE {transformed_where}
                        ORDER BY t.table_name
                        LIMIT 1000
                    """
                    result_df = self.duckdb_conn.execute(safe_query).fetchdf()

                    send_query_results(self.sock, result_df, self.transaction_status)
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"pg_class bypass failed: {e}",
                        event="catalog_pg_class_bypass_failed",
                        error_type=type(e).__name__,
                    )
                    if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                        import traceback
                        traceback.print_exc()
                    # Fall through to default handler

            # Special case 5: pg_attribute queries (column metadata)
            # DBeaver queries with a.* which includes columns that don't exist in DuckDB v1.4.2
            if 'FROM PG_CATALOG.PG_ATTRIBUTE' in query_upper and 'A.*' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Bypassing pg_attribute query (using safe columns)...",
                    event="catalog_pg_attribute_bypass",
                )
                try:
                    # Extract WHERE clause
                    import re
                    where_match = re.search(r'\bWHERE\b(.+?)(?:ORDER BY|LIMIT|$)', query, re.IGNORECASE | re.DOTALL)
                    where_clause = where_match.group(1).strip() if where_match else "a.attnum > 0 AND NOT a.attisdropped"

                    # Query with only columns that exist in DuckDB v1.4.2
                    safe_query = f"""
                        SELECT
                            c.relname,
                            a.attname,
                            a.attnum,
                            a.atttypid,
                            a.attnotnull,
                            a.attlen,
                            a.attrelid,
                            NULL::VARCHAR as def_value,
                            NULL::VARCHAR as description,
                            NULL::INTEGER as objid
                        FROM pg_catalog.pg_attribute a
                        INNER JOIN pg_catalog.pg_class c ON (a.attrelid = c.oid)
                        WHERE {where_clause}
                        ORDER BY a.attnum
                        LIMIT 1000
                    """
                    result_df = self.duckdb_conn.execute(safe_query).fetchdf()

                    send_query_results(self.sock, result_df, self.transaction_status)
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"pg_attribute bypass failed: {e}",
                        event="catalog_pg_attribute_bypass_failed",
                        error_type=type(e).__name__,
                    )
                    if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                        import traceback
                        traceback.print_exc()
                    # Fall through to default handler

            # Special case 6: PostgreSQL type casts (::regclass, ::oid, etc.)
            if '::REGCLASS' in query_upper or '::OID' in query_upper or '::REGPROC' in query_upper or '::REGTYPE' in query_upper:
                # Strip type casts and try to execute
                # This is a simplified approach - just remove the cast
                clean_query = query.replace('::regclass', '').replace('::oid', '').replace('::regproc', '').replace('::regtype', '')
                clean_query = clean_query.replace('::REGCLASS', '').replace('::OID', '').replace('::REGPROC', '').replace('::REGTYPE', '')
                try:
                    # Rewrite pg_inherits subqueries FIRST (DuckDB doesn't have pg_inherits)
                    clean_query = self._rewrite_pg_inherits_subqueries(clean_query)
                    clean_query = self._rewrite_pg_get_expr_calls(clean_query)
                    clean_query = self._rewrite_pg_catalog_function_calls(clean_query)
                    clean_query = self._rewrite_information_schema_catalog_filters(clean_query)
                    clean_query = self._rewrite_pg_system_column_refs(clean_query)
                    result_df = self.duckdb_conn.execute(clean_query).fetchdf()
                    send_query_results(self.sock, result_df, self.transaction_status)
                    return
                except:
                    # If that fails, return empty
                    pass

            # Default: Try to execute the query as-is
            # With pg_catalog views created, most queries should work!
            try:
                # Rewrite pg_inherits subqueries FIRST (DuckDB doesn't have pg_inherits)
                rewritten_query = self._rewrite_pg_inherits_subqueries(query)
                rewritten_query = self._rewrite_pg_get_expr_calls(rewritten_query)
                rewritten_query = self._rewrite_pg_catalog_function_calls(rewritten_query)
                rewritten_query = self._rewrite_information_schema_catalog_filters(rewritten_query)
                rewritten_query = self._rewrite_pg_system_column_refs(rewritten_query)
                # Remove LEFT JOINs to missing pg_catalog tables (pg_description, pg_inherits, etc.)
                rewritten_query = self._rewrite_missing_table_joins(rewritten_query)
                # NOTE: UNION stripping disabled - causes parameter count mismatches
                # rewritten_query = self._strip_union_parts_with_missing_tables(rewritten_query)
                result_df = self.duckdb_conn.execute(rewritten_query).fetchdf()

                # Normalize catalog names for Postgres clients (DuckDB uses 'memory' for in-memory)
                if 'INFORMATION_SCHEMA' in query_upper and self._duckdb_catalog_name:
                    try:
                        if 'catalog_name' in result_df.columns:
                            result_df.loc[result_df['catalog_name'] == self._duckdb_catalog_name, 'catalog_name'] = self.database_name
                        if 'table_catalog' in result_df.columns:
                            result_df.loc[result_df['table_catalog'] == self._duckdb_catalog_name, 'table_catalog'] = self.database_name
                    except Exception:
                        pass
                send_query_results(self.sock, result_df, self.transaction_status)
                return

            except Exception as query_error:
                # Query failed - this might be a complex pg_catalog query we don't support
                self._runtime_log(
                    "WARN",
                    f"Catalog query failed: {str(query_error)[:200]}",
                    event="catalog_query_failed",
                    error_type=type(query_error).__name__,
                )

                # Fallback: Return empty result (safe - clients handle this gracefully)
                cols = self._expected_result_columns(query)
                empty_df = self._empty_df_for_columns(cols) if cols else pd.DataFrame()
                send_query_results(self.sock, empty_df, self.transaction_status)

        except Exception as e:
            # Complete failure - return empty result to keep client from crashing
            self._runtime_log(
                "WARN",
                f"Catalog query handler error: {e}",
                event="catalog_query_handler_error",
                error_type=type(e).__name__,
            )
            import pandas as pd
            cols = self._expected_result_columns(query)
            empty_df = self._empty_df_for_columns(cols) if cols else pd.DataFrame()
            send_query_results(self.sock, empty_df, self.transaction_status)

    def _rewrite_pg_class_query(self, query: str) -> str:
        """
        Rewrite pg_class query to avoid regclass-typed columns.

        DBeaver queries like:
          SELECT c.oid, c.*, ... FROM pg_catalog.pg_class c ...

        The c.* includes columns with 'regclass' type that cause errors.
        We replace c.* with explicit safe column list.
        """
        import re

        # Replace 'c.*' with safe column list
        # These are the essential columns DBeaver needs
        safe_columns = """c.oid,
            c.relname,
            c.relnamespace,
            c.relkind,
            c.relowner,
            c.relam,
            c.relfilenode,
            c.reltablespace,
            c.relpages,
            c.reltuples,
            c.relallvisible,
            c.reltoastrelid,
            c.relhasindex,
            c.relisshared,
            c.relpersistence,
            c.relhasrules,
            c.relhastriggers,
            c.relhassubclass,
            c.relrowsecurity,
            c.relforcerowsecurity,
            c.relispopulated,
            c.relreplident,
            c.relispartition,
            c.relrewrite,
            c.relfrozenxid,
            c.relminmxid"""

        # Replace c.* with safe columns (but keep c.oid if it was already there)
        rewritten = re.sub(
            r'c\.oid\s*,\s*c\.\*',
            safe_columns,
            query,
            flags=re.IGNORECASE
        )

        # Also handle just c.* without c.oid
        rewritten = re.sub(
            r'(?<!\.)\bc\.\*',
            safe_columns,
            rewritten,
            flags=re.IGNORECASE
        )

        return rewritten

    def _execute_show_and_send_extended(self, query: str, send_row_description: bool = True):
        """
        Execute SHOW command and send results via Extended Query Protocol.

        Args:
            query: SHOW command
            send_row_description: Whether to send RowDescription (False if Describe already sent it)
        """
        import pandas as pd
        query_upper = query.upper()

        # SHOW search_path
        if 'SEARCH_PATH' in query_upper:
            result_df = pd.DataFrame({'search_path': ['lars_system, main, pg_catalog']})
        # SHOW timezone
        elif 'TIMEZONE' in query_upper or 'TIME ZONE' in query_upper:
            result_df = pd.DataFrame({'TimeZone': ['UTC']})
        # SHOW server_version
        elif 'SERVER_VERSION' in query_upper:
            result_df = pd.DataFrame({'server_version': ['14.0']})
        # SHOW transaction isolation level
        elif 'TRANSACTION' in query_upper and 'ISOLATION' in query_upper:
            result_df = pd.DataFrame({'transaction_isolation': ['read committed']})
        # Try DuckDB native
        else:
            try:
                result_df = self.duckdb_conn.execute(query).fetchdf()
            except:
                result_df = pd.DataFrame({'setting': ['']})

        send_execute_results(self.sock, result_df, send_row_description=send_row_description)
        self._runtime_log(
            "DEBUG",
            f"SHOW handled, returned {len(result_df)} rows (row_desc={'sent' if send_row_description else 'skipped'})",
            event="show_extended_handled",
            row_count=len(result_df),
            row_description_sent=bool(send_row_description),
        )

    def _execute_set_command(self, query: str):
        """
        Execute SET/RESET command (internal - no responses sent).

        Used by both Simple Query and Extended Query handlers.

        Args:
            query: SET or RESET command
        """
        query_upper = query.upper()

        # List of PostgreSQL settings we can safely ignore
        IGNORED_SETTINGS = [
            'EXTRA_FLOAT_DIGITS',
            'DATESTYLE',
            'TIMEZONE',
            'CLIENT_ENCODING',
            'APPLICATION_NAME',
            'STANDARD_CONFORMING_STRINGS',
            'INTERVALSTYLE',
            'BYTEA_OUTPUT',
            'DEFAULT_TRANSACTION_ISOLATION',
            'DEFAULT_TRANSACTION_READ_ONLY',
            'DEFAULT_TRANSACTION_DEFERRABLE'
        ]

        # Check if this is an ignored setting
        is_ignored = any(setting in query_upper for setting in IGNORED_SETTINGS)

        if is_ignored:
            # Silently ignore
            self._runtime_log(
                "DEBUG",
                f"Ignoring PostgreSQL-specific SET: {query[:200]}{'...' if len(query) > 200 else ''}",
                event="set_ignored",
            )
        else:
            # Try to execute on DuckDB (might work for some SET commands)
            try:
                self.duckdb_conn.execute(query)
                self._runtime_log("DEBUG", "SET command executed on DuckDB", event="set_executed")
            except Exception as e:
                # DuckDB doesn't support this either - ignore
                self._runtime_log(
                    "DEBUG",
                    f"Ignoring unsupported SET: {query[:200]}{'...' if len(query) > 200 else ''}",
                    event="set_unsupported",
                )

    def _handle_set_command(self, query: str):
        """
        Handle PostgreSQL SET/RESET commands (Simple Query Protocol).

        Many PostgreSQL clients send session configuration commands
        that DuckDB doesn't support (e.g., extra_float_digits, DateStyle).

        For v1, we silently accept these to maintain compatibility.

        Args:
            query: SET or RESET command
        """
        # Execute the SET command
        self._execute_set_command(query)

        # Send responses (Simple Query Protocol sends immediately)
        self.sock.sendall(CommandComplete.encode('SET'))
        self.sock.sendall(ReadyForQuery.encode('I'))

    def _handle_show_command(self, query: str):
        """
        Handle PostgreSQL SHOW commands.

        PostgreSQL has SHOW commands for various settings that DuckDB doesn't support.
        We intercept common ones and return sensible defaults.

        Args:
            query: SHOW command
        """
        import pandas as pd
        query_upper = query.upper()

        self._runtime_log(
            "DEBUG",
            f"SHOW command detected: {query[:200]}{'...' if len(query) > 200 else ''}",
            event="show_command",
        )

        try:
            # SHOW search_path - schema search order
            if 'SEARCH_PATH' in query_upper:
                result_df = pd.DataFrame({'search_path': ['lars_system, main, pg_catalog']})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log("DEBUG", "SHOW search_path handled", event="show_result", setting="search_path")
                return

            # SHOW timezone
            if 'TIMEZONE' in query_upper or 'TIME ZONE' in query_upper:
                result_df = pd.DataFrame({'TimeZone': ['UTC']})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log("DEBUG", "SHOW timezone handled", event="show_result", setting="timezone")
                return

            # SHOW server_version
            if 'SERVER_VERSION' in query_upper:
                result_df = pd.DataFrame({'server_version': ['14.0']})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log("DEBUG", "SHOW server_version handled", event="show_result", setting="server_version")
                return

            # SHOW client_encoding
            if 'CLIENT_ENCODING' in query_upper:
                result_df = pd.DataFrame({'client_encoding': ['UTF8']})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log("DEBUG", "SHOW client_encoding handled", event="show_result", setting="client_encoding")
                return

            # SHOW transaction isolation level
            if 'TRANSACTION' in query_upper and 'ISOLATION' in query_upper:
                result_df = pd.DataFrame({'transaction_isolation': ['read committed']})
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    "SHOW transaction isolation level handled",
                    event="show_result",
                    setting="transaction_isolation",
                )
                return

            # SHOW tables - this DuckDB supports natively!
            if 'TABLES' in query_upper:
                result_df = self.duckdb_conn.execute(query).fetchdf()
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    f"SHOW tables executed ({len(result_df)} rows)",
                    event="show_result",
                    setting="tables",
                    row_count=len(result_df),
                )
                return

            # SHOW RESULTS - list auto-materialized LARS query results
            if 'RESULTS' in query_upper:
                try:
                    # Check if registry table exists
                    tables = self.duckdb_conn.execute("""
                        SELECT table_name FROM information_schema.tables
                        WHERE table_name = '_lars_results'
                    """).fetchall()

                    if tables:
                        result_df = self.duckdb_conn.execute("""
                            SELECT
                                query_id,
                                full_table_name,
                                row_count,
                                column_count,
                                created_at,
                                LEFT(query_fingerprint, 60) || '...' as query_preview
                            FROM _lars_results
                            ORDER BY created_at DESC
                            LIMIT 50
                        """).fetchdf()
                    else:
                        result_df = pd.DataFrame({
                            'info': ['No auto-materialized results yet. Run LARS queries to see results here.']
                        })
                    send_query_results(self.sock, result_df, self.transaction_status)
                    self._runtime_log(
                        "DEBUG",
                        f"SHOW RESULTS: {len(result_df)} entries",
                        event="show_results",
                        entry_count=len(result_df),
                    )
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"SHOW RESULTS failed: {e}",
                        event="show_results_error",
                        error_type=type(e).__name__,
                    )
                    result_df = pd.DataFrame({'error': [str(e)]})
                    send_query_results(self.sock, result_df, self.transaction_status)
                    return

            # SHOW CONNECTIONS - list configured SQL connections and their status
            if 'CONNECTIONS' in query_upper:
                try:
                    if self._lazy_attach is not None:
                        connections = self._lazy_attach.get_available_connections()
                        if connections:
                            result_df = pd.DataFrame(connections)
                        else:
                            result_df = pd.DataFrame({
                                'info': ['No SQL connections configured. Add YAML files to sql_connections/']
                            })
                    else:
                        result_df = pd.DataFrame({
                            'info': ['Lazy attach manager not initialized']
                        })
                    send_query_results(self.sock, result_df, self.transaction_status)
                    self._runtime_log(
                        "DEBUG",
                        f"SHOW CONNECTIONS: {len(result_df)} entries",
                        event="show_connections",
                        entry_count=len(result_df),
                    )
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"SHOW CONNECTIONS failed: {e}",
                        event="show_connections_error",
                        error_type=type(e).__name__,
                    )
                    result_df = pd.DataFrame({'error': [str(e)]})
                    send_query_results(self.sock, result_df, self.transaction_status)
                    return

            # Try to execute on DuckDB (might work for some SHOW commands)
            try:
                result_df = self.duckdb_conn.execute(query).fetchdf()
                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log("DEBUG", "SHOW command executed on DuckDB", event="show_executed_duckdb")
            except Exception as e:
                # DuckDB doesn't support this SHOW command - return empty
                self._runtime_log(
                    "DEBUG",
                    "Unsupported SHOW command, returning empty",
                    event="show_unsupported",
                )
                result_df = pd.DataFrame({'setting': ['']})
                send_query_results(self.sock, result_df, self.transaction_status)

        except Exception as e:
            # Complete failure - send error
            error_message = str(e)
            error_detail = f"SHOW command not supported: {query}"
            send_error(self.sock, error_message, detail=error_detail, transaction_status=self.transaction_status)
            self._runtime_log(
                "ERROR",
                f"SHOW command error: {error_message}",
                event="show_error",
                error_type=type(e).__name__,
            )

    def _handle_begin(self, send_ready=True) -> bool:
        """
        Handle BEGIN transaction.

        Args:
            send_ready: If True, send ReadyForQuery (Simple Query mode)
                       If False, don't send (Extended Query - waits for Sync)
        """
        try:
            if self.transaction_status == 'T':
                # Already in transaction - commit current one first
                self._runtime_log(
                    "DEBUG",
                    "Already in transaction, auto-committing previous",
                    event="transaction_begin_autocommit",
                )
                self.duckdb_conn.execute("COMMIT")

            # Start new transaction
            self.duckdb_conn.execute("BEGIN TRANSACTION")
            self.transaction_status = 'T'

            self.sock.sendall(CommandComplete.encode('BEGIN'))
            if send_ready:
                self.sock.sendall(ReadyForQuery.encode('T'))  # 'T' = in transaction
            self._runtime_log("DEBUG", "BEGIN transaction", event="transaction_begin")
            return True

        except Exception as e:
            self._runtime_log(
                "ERROR",
                f"BEGIN error: {e}",
                event="transaction_begin_error",
                error_type=type(e).__name__,
            )
            if send_ready:
                send_error(self.sock, str(e))
            else:
                # In Extended Query, errors are sent but not ReadyForQuery (wait for Sync)
                self.sock.sendall(ErrorResponse.encode('ERROR', str(e)))
            return False

    def _handle_commit(self, send_ready=True) -> bool:
        """
        Handle COMMIT transaction.

        Args:
            send_ready: If True, send ReadyForQuery (Simple Query mode)
                       If False, don't send (Extended Query - waits for Sync)
        """
        try:
            if self.transaction_status == 'E':
                # Transaction is in error state - can't commit
                self._runtime_log(
                    "WARN",
                    "Transaction in error state, auto-rolling back",
                    event="transaction_commit_autorollback",
                )
                self.duckdb_conn.execute("ROLLBACK")
            elif self.transaction_status == 'T':
                # Commit active transaction
                self.duckdb_conn.execute("COMMIT")
            # else: not in transaction, that's fine

            self.transaction_status = 'I'

            self.sock.sendall(CommandComplete.encode('COMMIT'))
            if send_ready:
                self.sock.sendall(ReadyForQuery.encode('I'))  # 'I' = idle
            self._runtime_log("DEBUG", "COMMIT transaction", event="transaction_commit")
            return True

        except Exception as e:
            self._runtime_log(
                "ERROR",
                f"COMMIT error: {e}",
                event="transaction_commit_error",
                error_type=type(e).__name__,
            )
            if send_ready:
                send_error(self.sock, str(e))
            else:
                self.sock.sendall(ErrorResponse.encode('ERROR', str(e)))
            return False

    def _handle_rollback(self, send_ready=True) -> bool:
        """
        Handle ROLLBACK transaction.

        Args:
            send_ready: If True, send ReadyForQuery (Simple Query mode)
                       If False, don't send (Extended Query - waits for Sync)
        """
        try:
            if self.transaction_status in ['T', 'E']:
                # Rollback active or errored transaction
                self.duckdb_conn.execute("ROLLBACK")
            # else: not in transaction, that's fine

            self.transaction_status = 'I'

            self.sock.sendall(CommandComplete.encode('ROLLBACK'))
            if send_ready:
                self.sock.sendall(ReadyForQuery.encode('I'))  # 'I' = idle
            self._runtime_log("DEBUG", "ROLLBACK transaction", event="transaction_rollback")
            return True

        except Exception as e:
            self._runtime_log(
                "ERROR",
                f"ROLLBACK error: {e}",
                event="transaction_rollback_error",
                error_type=type(e).__name__,
            )
            if send_ready:
                send_error(self.sock, str(e))
            else:
                self.sock.sendall(ErrorResponse.encode('ERROR', str(e)))
            return False

    def _handle_background_query(self, query: str, extended_query_mode: bool = False, send_row_description: bool = True) -> bool:
        """
        Execute a query in the background and return job info immediately.

        The query runs asynchronously in a separate thread with its own DuckDB
        connection (in-memory). Results and status are tracked in sql_query_log
        (ClickHouse); result materialization uses ClickHouse ("query insurance").

        Usage:
            BACKGROUND SELECT * FROM expensive_computation;

        Returns immediately with:
            job_id (e.g., 'job-swift-fox-abc123'), status, result_table, check_status

        The user can then:
            - Poll: SELECT * FROM job('job-swift-fox-abc123')
            - Wait: SELECT * FROM await_job('job-swift-fox-abc123')
            - List all: SELECT * FROM jobs()
            - Query results: SELECT * FROM read_json_auto(clickhouse_scan_1('lars_results.r_job_swift_fox_abc123'))

        Args:
            query: The SQL query to execute in background (without BACKGROUND prefix)
            extended_query_mode: If True, use Extended Query Protocol response format
            send_row_description: If True (and extended_query_mode), send RowDescription
        """
        import time
        import pandas as pd
        from datetime import datetime
        from concurrent.futures import ThreadPoolExecutor
        import re

        # Generate job ID using woodland naming (user-friendly, unique)
        from ..session_naming import generate_woodland_id
        job_id = f"job-{generate_woodland_id()}"

        # Log query start (also generates internal UUID query_id)
        from ..sql_trail import log_query_start, log_query_complete, log_query_error, get_and_clear_cache_counts
        internal_query_id = log_query_start(
            caller_id=job_id,  # Use job_id as caller_id for lookup
            query_raw=query,
            protocol='postgresql_wire_background'
        )

        if not internal_query_id:
            if extended_query_mode:
                self.sock.sendall(ErrorResponse.encode('ERROR', "Failed to initialize background job"))
            else:
                send_error(self.sock, "Failed to initialize background job")
            return False

        session_id = self.session_id

        # Predict ClickHouse "query insurance" table name.
        # Matches _maybe_materialize_result() naming: r_<caller_id sanitized>.
        safe_job_id = re.sub(r'[^a-zA-Z0-9]', '_', job_id)
        result_table_name = f"r_{safe_job_id}"
        full_result_table = f"lars_results.{result_table_name}"

        def execute_in_background():
            """Background thread: execute query, materialize results, update status."""
            import duckdb
            import traceback as tb_module
            bg_start = time.time()
            bg_conn = None

            try:
                # Set caller context for cost tracking
                from ..caller_context import set_caller_context, build_sql_metadata, clear_caller_context
                metadata = build_sql_metadata(
                    sql_query=query,
                    protocol="postgresql_wire_background",
                    triggered_by="background_query"
                )
                set_caller_context(job_id, metadata)

                self._runtime_log(
                    "INFO",
                    f"Background job {job_id} starting",
                    event="background_job_start",
                    job_id=job_id,
                    internal_query_id=internal_query_id,
                )

                # Open fresh in-memory DuckDB connection (no DuckDB persistence).
                bg_conn = duckdb.connect()
                bg_conn.execute("SET threads TO 4")

                # Register UDFs on this connection
                from ..sql_tools.udf import register_lars_udf, register_dynamic_sql_functions
                register_lars_udf(bg_conn)
                register_dynamic_sql_functions(bg_conn)

                # Lazy attach configured sources for background execution too
                try:
                    from ..sql_tools.config import load_sql_connections
                    from ..sql_tools.lazy_attach import LazyAttachManager
                    LazyAttachManager(bg_conn, load_sql_connections()).ensure_for_query(query, aggressive=False)
                except Exception:
                    pass

                # Rewrite into_ table references to read from ClickHouse
                try:
                    from ..sql_tools.into_table_rewriter import rewrite_into_tables
                    query, _ = rewrite_into_tables(query, results_db=self.results_db_name)
                except Exception:
                    pass  # Non-fatal

                # Deref preprocessing: evaluate @cascade() expressions first
                try:
                    from ..sql_tools.deref_preprocessor import preprocess_deref_cascades
                    deref_context = {
                        'session_id': f"{self.auth_user_id}:{self.database_name}",
                        'protocol': 'pgwire_background',
                        'database_name': self.database_name,
                        'user_name': self.user_name,
                        'application_name': self.application_name,
                        'client_address': f"{self.addr[0]}:{self.addr[1]}" if self.addr else '',
                        'caller_id': job_id,
                    }
                    query = preprocess_deref_cascades(query, deref_context)
                except Exception:
                    pass  # Non-fatal

                # Support PIPELINE syntax (THEN/INTO) inside BACKGROUND
                from ..sql_tools.pipeline_parser import has_pipeline_syntax, parse_pipeline_syntax, preprocess_cte_pipelines
                from ..sql_rewriter import rewrite_lars_syntax

                if has_pipeline_syntax(query):
                    pipeline = parse_pipeline_syntax(query)
                    if pipeline and pipeline.stages:
                        base_sql = pipeline.base_sql
                        base_sql = rewrite_lars_syntax(base_sql, duckdb_conn=bg_conn)
                        base_sql = preprocess_cte_pipelines(
                            base_sql,
                            duckdb_conn=bg_conn,
                            session_id=session_id,
                            caller_id=job_id,
                        )
                        base_df = bg_conn.execute(base_sql).fetchdf()

                        from ..sql_tools.pipeline_executor import execute_pipeline_with_into
                        result_df = execute_pipeline_with_into(
                            stages=pipeline.stages,
                            initial_df=base_df,
                            into_table=pipeline.into_table,
                            duckdb_conn=bg_conn,
                            session_id=session_id,
                            results_db=self.results_db_name,
                            caller_id=job_id,
                            original_query=query,
                            base_into_table=pipeline.base_into_table,
                        )
                    else:
                        result_df = pd.DataFrame()
                else:
                    rewritten = rewrite_lars_syntax(query, duckdb_conn=bg_conn)
                    rewritten = preprocess_cte_pipelines(
                        rewritten,
                        duckdb_conn=bg_conn,
                        session_id=session_id,
                        caller_id=job_id,
                    )
                    result_df = bg_conn.execute(rewritten).fetchdf()

                self._runtime_log(
                    "INFO",
                    f"Background job {job_id} executed, {len(result_df)} rows",
                    event="background_job_executed",
                    job_id=job_id,
                    internal_query_id=internal_query_id,
                    row_count=len(result_df),
                )

                # Materialize results (ClickHouse "query insurance" table) and log location.
                result_location = None
                if len(result_df) > 0:
                    try:
                        result_location = self._maybe_materialize_result(
                            query=query,
                            result_df=result_df,
                            query_id=internal_query_id,
                            caller_id=job_id,
                        )
                        if result_location and result_location.get('result_table'):
                            self._runtime_log(
                                "DEBUG",
                                f"Background job {job_id} materialized to lars_results.{result_location['result_table']}",
                                event="background_job_materialized",
                                job_id=job_id,
                                internal_query_id=internal_query_id,
                                result_table=result_location.get("result_table"),
                            )
                    except Exception as mat_err:
                        self._runtime_log(
                            "WARN",
                            f"Background job {job_id} materialization failed: {mat_err}",
                            event="background_job_materialize_failed",
                            job_id=job_id,
                            internal_query_id=internal_query_id,
                            error_type=type(mat_err).__name__,
                        )

                # Log completion
                duration_ms = (time.time() - bg_start) * 1000
                cache_hits, cache_misses = get_and_clear_cache_counts(job_id)
                log_query_complete(
                    query_id=internal_query_id,
                    status='completed',
                    rows_output=len(result_df),
                    duration_ms=duration_ms,
                    result_db_name='lars_results' if result_location else None,
                    result_schema=None,
                    result_table=result_location.get('result_table') if result_location else None,
                    cache_hits=cache_hits,
                    cache_misses=cache_misses,
                )

                self._runtime_log(
                    "INFO",
                    f"Background job {job_id} completed: {len(result_df)} rows in {duration_ms:.0f}ms",
                    event="background_job_complete",
                    job_id=job_id,
                    internal_query_id=internal_query_id,
                    row_count=len(result_df),
                    duration_ms=duration_ms,
                    result_table=(result_location.get("result_table") if result_location else None),
                )

            except Exception as e:
                if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                    tb_module.print_exc()
                duration_ms = (time.time() - bg_start) * 1000
                log_query_error(internal_query_id, str(e), duration_ms=duration_ms)
                self._runtime_log(
                    "ERROR",
                    f"Background job {job_id} failed: {e}",
                    event="background_job_error",
                    job_id=job_id,
                    internal_query_id=internal_query_id,
                    error_type=type(e).__name__,
                )

            finally:
                if bg_conn:
                    try:
                        bg_conn.close()
                    except:
                        pass
                try:
                    from ..caller_context import clear_caller_context
                    clear_caller_context()
                except:
                    pass

        # Initialize background executor if needed
        if not hasattr(self, '_background_executor'):
            self._background_executor = ThreadPoolExecutor(
                max_workers=4,
                thread_name_prefix='bg_query'
            )

        # Submit to background executor
        self._background_executor.submit(execute_in_background)

        # Return job info immediately
        job_df = pd.DataFrame([{
            'job_id': job_id,
            'status': 'running',
            'result_table': full_result_table,
            'submitted_at': datetime.now().isoformat(),
            'query_preview': query[:100] + ('...' if len(query) > 100 else ''),
            'check_status': f"SELECT * FROM job('{job_id}')",
            'await_completion': f"SELECT * FROM await_job('{job_id}')",
            'message_log': f"SELECT * FROM messages('{job_id}')",
        }])

        if extended_query_mode:
            send_execute_results(self.sock, job_df, send_row_description=send_row_description)
        else:
            send_query_results(self.sock, job_df, self.transaction_status)
        self._runtime_log(
            "INFO",
            f"Background job {job_id} submitted → {full_result_table}",
            event="background_job_submitted",
            job_id=job_id,
            internal_query_id=internal_query_id,
            result_table=full_result_table,
        )
        return True

    def _handle_explain_query(self, query: str):
        """
        Handle EXPLAIN queries for semantic SQL and pipeline operators.

        Supports:
            EXPLAIN SELECT * FROM t WHERE col MEANS 'something'
            EXPLAIN SELECT * FROM t THEN PIVOT 'by region'
            EXPLAIN (FORMAT JSON) SELECT * FROM t THEN ANALYZE 'trends'

        For pipeline queries, explains both the base SQL and each stage.

        Uses read-only connection for file-based databases to avoid lock conflicts
        when multiple sessions run EXPLAIN concurrently.
        """
        import re
        import pandas as pd
        from ..sql_tools.pipeline_parser import has_pipeline_syntax, parse_pipeline_syntax

        self._runtime_log(
            "DEBUG",
            "EXPLAIN query",
            event="explain_query",
        )

        # Get read-only connection to avoid lock conflicts on file-based DBs
        explain_conn, should_close = self._get_readonly_conn()

        try:
            # Parse EXPLAIN prefix
            normalized = query.strip()
            explain_match = re.match(r'EXPLAIN\s*', normalized, re.IGNORECASE)
            if not explain_match:
                # Shouldn't happen, but handle gracefully
                send_error(self.sock, f"Invalid EXPLAIN syntax: {query[:50]}", transaction_status=self.transaction_status)
                return

            inner_query = normalized[explain_match.end():].strip()

            # Check for EXPLAIN (FORMAT JSON) syntax
            format_json = False
            format_match = re.match(r'\(\s*FORMAT\s+JSON\s*\)\s*', inner_query, re.IGNORECASE)
            if format_match:
                format_json = True
                inner_query = inner_query[format_match.end():].strip()

            # Check if the query has pipeline syntax (THEN/INTO)
            if has_pipeline_syntax(inner_query):
                # Explain pipeline query
                pipeline = parse_pipeline_syntax(inner_query)
                if pipeline and pipeline.stages:
                    try:
                        from ..sql_explain import explain_pipeline_query, format_explain_result, format_explain_json
                        result = explain_pipeline_query(
                            pipeline=pipeline,
                            original_query=inner_query,
                            duckdb_conn=explain_conn
                        )

                        if format_json:
                            import json
                            plan_json = json.dumps(format_explain_json(result), indent=2)
                            plan_json_escaped = plan_json.replace("'", "''")
                            explain_sql = f"SELECT '{plan_json_escaped}' AS query_plan"
                        else:
                            plan_text = format_explain_result(result)
                            plan_text_escaped = plan_text.replace("'", "''")
                            explain_sql = f"SELECT '{plan_text_escaped}' AS query_plan"

                        result_df = explain_conn.execute(explain_sql).fetchdf()
                        send_query_results(self.sock, result_df, self.transaction_status)
                        self._runtime_log(
                            "DEBUG",
                            "Returned pipeline EXPLAIN plan",
                            event="explain_pipeline_returned",
                        )
                        return
                    except Exception as e:
                        self._runtime_log(
                            "WARN",
                            f"Pipeline EXPLAIN failed: {e}",
                            event="explain_pipeline_failed",
                            error_type=type(e).__name__,
                        )
                        # Fall through to regular EXPLAIN handling

            # For non-pipeline queries, use the existing rewriter-based EXPLAIN
            # (handles LARS MAP/RUN and inline semantic functions)
            # Rewrite into_ table references to read from ClickHouse
            try:
                from ..sql_tools.into_table_rewriter import rewrite_into_tables
                query, _ = rewrite_into_tables(query, results_db=self.results_db_name)
            except Exception:
                pass  # Non-fatal

            from ..sql_rewriter import rewrite_lars_syntax
            explain_sql = rewrite_lars_syntax(query, duckdb_conn=explain_conn)

            # Execute the rewritten explain query
            try:
                result_df = explain_conn.execute(explain_sql).fetchdf()

                # Format native DuckDB EXPLAIN results for better readability
                # DuckDB returns columns ['explain_key', 'explain_value'] where:
                # - explain_key is 'physical_plan' (or 'logical_plan' for EXPLAIN ANALYZE)
                # - explain_value is the actual plan tree text
                result_df = _format_native_explain_df(result_df)

                send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "DEBUG",
                    "Returned EXPLAIN plan",
                    event="explain_returned",
                )
            except Exception as e:
                send_error(self.sock, f"EXPLAIN execution failed: {e}", transaction_status=self.transaction_status)
        finally:
            if should_close and explain_conn:
                try:
                    explain_conn.close()
                except Exception:
                    pass

    def _handle_explain_query_extended(self, query: str, send_row_description: bool = True) -> bool:
        """
        Handle EXPLAIN queries via Extended Query Protocol.

        Same as _handle_explain_query but uses Extended Query Protocol response format.

        Uses read-only connection for file-based databases to avoid lock conflicts
        when multiple sessions run EXPLAIN concurrently.
        """
        import re
        import pandas as pd
        from ..sql_tools.pipeline_parser import has_pipeline_syntax, parse_pipeline_syntax

        self._runtime_log(
            "DEBUG",
            "EXPLAIN query (Extended)",
            event="explain_query_extended",
        )

        # Get read-only connection to avoid lock conflicts on file-based DBs
        explain_conn, should_close = self._get_readonly_conn()

        try:
            # Parse EXPLAIN prefix
            normalized = query.strip()
            explain_match = re.match(r'EXPLAIN\s*', normalized, re.IGNORECASE)
            if not explain_match:
                self.sock.sendall(ErrorResponse.encode('ERROR', f"Invalid EXPLAIN syntax: {query[:50]}"))
                return False

            inner_query = normalized[explain_match.end():].strip()

            # Check for EXPLAIN (FORMAT JSON) syntax
            format_json = False
            format_match = re.match(r'\(\s*FORMAT\s+JSON\s*\)\s*', inner_query, re.IGNORECASE)
            if format_match:
                format_json = True
                inner_query = inner_query[format_match.end():].strip()

            # Check if the query has pipeline syntax (THEN/INTO)
            if has_pipeline_syntax(inner_query):
                pipeline = parse_pipeline_syntax(inner_query)
                if pipeline and pipeline.stages:
                    try:
                        from ..sql_explain import explain_pipeline_query, format_explain_result, format_explain_json
                        result = explain_pipeline_query(
                            pipeline=pipeline,
                            original_query=inner_query,
                            duckdb_conn=explain_conn
                        )

                        if format_json:
                            import json
                            plan_text = json.dumps(format_explain_json(result), indent=2)
                        else:
                            plan_text = format_explain_result(result)

                        result_df = pd.DataFrame([{'query_plan': plan_text}])
                        send_execute_results(self.sock, result_df, send_row_description=send_row_description)
                        self._runtime_log(
                            "DEBUG",
                            "Returned pipeline EXPLAIN plan (Extended)",
                            event="explain_pipeline_returned",
                        )
                        return True
                    except Exception as e:
                        self._runtime_log(
                            "WARN",
                            f"Pipeline EXPLAIN failed: {e}",
                            event="explain_pipeline_failed",
                            error_type=type(e).__name__,
                        )
                        # Fall through to regular EXPLAIN handling

            # For non-pipeline queries (or if pipeline explain failed), use rewriter-based EXPLAIN
            # Rewrite into_ table references to read from ClickHouse
            try:
                from ..sql_tools.into_table_rewriter import rewrite_into_tables
                query, _ = rewrite_into_tables(query, results_db=self.results_db_name)
            except Exception:
                pass  # Non-fatal

            try:
                from ..sql_rewriter import rewrite_lars_syntax
                explain_sql = rewrite_lars_syntax(query, duckdb_conn=explain_conn)

                # Execute the rewritten explain query
                result_df = explain_conn.execute(explain_sql).fetchdf()

                # Format native DuckDB EXPLAIN results for better readability
                result_df = _format_native_explain_df(result_df)

                send_execute_results(self.sock, result_df, send_row_description=send_row_description)
                self._runtime_log(
                    "DEBUG",
                    "Returned EXPLAIN plan (Extended)",
                    event="explain_returned",
                )
                return True
            except Exception as e:
                self._runtime_log(
                    "WARN",
                    f"EXPLAIN fallback failed: {e}",
                    event="explain_failed",
                    error_type=type(e).__name__,
                )
                self.sock.sendall(ErrorResponse.encode('ERROR', f"EXPLAIN execution failed: {e}"))
                return False
        finally:
            if should_close and explain_conn:
                try:
                    explain_conn.close()
                except Exception:
                    pass

    def _handle_pipeline_query(self, pipeline, original_query: str, extended_query_mode: bool = False, send_row_description: bool = True) -> bool:
        """
        Handle queries with THEN/INTO pipeline syntax.

        Executes the base SQL, then runs each pipeline stage cascade on the results.
        Optionally saves to INTO table.

        Args:
            pipeline: ParsedPipeline from pipeline_parser
            original_query: Original SQL for error messages
            extended_query_mode: If True, use Extended Query Protocol response format
            send_row_description: If True (and extended_query_mode), send RowDescription
        """
        import pandas as pd
        from ..sql_tools.pipeline_executor import execute_pipeline_with_into, PipelineExecutionError

        try:
            stage_summaries = [
                {"name": s.name, "args": list(s.args) if getattr(s, "args", None) else []}
                for s in pipeline.stages
            ]
        except Exception:
            stage_summaries = []

        self._runtime_log(
            "INFO",
            f"Pipeline query: {len(pipeline.stages)} stages",
            event="pipeline_start",
            stage_count=len(pipeline.stages),
            into_table=pipeline.into_table,
            stages=stage_summaries[:25],
        )

        try:
            # 1. Execute base SQL with unified rewriting (handles dimension functions, semantic operators, etc.)
            base_sql = pipeline.base_sql

            # Rewrite into_ table references to read from ClickHouse
            # Tables created with ... INTO xxx are stored in ClickHouse as:
            #   <results_db_name>.into_xxx  (results_db_name = lars_results_<database_name>)
            try:
                from ..sql_tools.into_table_rewriter import rewrite_into_tables
                base_sql, into_changed = rewrite_into_tables(base_sql, results_db=self.results_db_name)
                if into_changed:
                    self._runtime_log(
                        "DEBUG",
                        "INTO table references rewritten in base SQL",
                        event="pipeline_into_rewritten",
                    )
            except Exception as e:
                self._runtime_log(
                    "WARN",
                    f"INTO table rewrite skipped: {e}",
                    event="pipeline_into_rewrite_skipped",
                    error_type=type(e).__name__,
                )

            # Deref preprocessing: evaluate @cascade() expressions first
            from ..sql_tools.deref_preprocessor import preprocess_deref_cascades
            deref_context = {
                'session_id': f"{self.auth_user_id}:{self.database_name}",  # Scoped by user + database for param store
                'protocol': 'pgwire',
                'database_name': self.database_name,
                'user_name': self.user_name,
                'application_name': self.application_name,
                'client_address': f"{self.addr[0]}:{self.addr[1]}" if self.addr else '',
                'caller_id': getattr(self, '_current_caller_id', None),
            }
            base_sql = preprocess_deref_cascades(base_sql, deref_context)

            # Use the unified rewriter - same as normal query path
            # This ensures dimension functions (vibes, topics, etc.) get CTE transformation
            # BEFORE semantic rewriters inject ROW_NUMBER() for lineage tracking
            from ..sql_rewriter import rewrite_lars_syntax
            base_sql = rewrite_lars_syntax(base_sql, duckdb_conn=self.duckdb_conn)

            # Preprocess CTEs with THEN pipeline syntax
            # This executes pipelines inside CTEs and replaces them with materialized results
            from ..sql_tools.pipeline_parser import preprocess_cte_pipelines
            base_sql = preprocess_cte_pipelines(
                base_sql,
                duckdb_conn=self.duckdb_conn,
                session_id=self.session_id,
                caller_id=getattr(self, '_current_caller_id', None),
            )

            self._runtime_log(
                "DEBUG",
                f"Executing base: {base_sql[:200]}{'...' if len(base_sql) > 200 else ''}",
                event="pipeline_base_execute",
            )

            # Execute base query
            result = self.duckdb_conn.execute(base_sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            initial_df = pd.DataFrame(rows, columns=columns)

            self._runtime_log(
                "DEBUG",
                f"Base query returned {len(initial_df)} rows",
                event="pipeline_base_complete",
                row_count=len(initial_df),
            )

            # 2. Execute pipeline stages
            final_df = execute_pipeline_with_into(
                stages=pipeline.stages,
                initial_df=initial_df,
                into_table=pipeline.into_table,
                duckdb_conn=self.duckdb_conn,
                session_id=self.session_id,
                results_db=self.results_db_name,
                caller_id=getattr(self, '_current_caller_id', None),
                original_query=original_query,
                base_into_table=pipeline.base_into_table,
            )

            self._runtime_log(
                "INFO",
                f"Pipeline complete: {len(final_df)} rows",
                event="pipeline_complete",
                row_count=len(final_df),
                into_table=pipeline.into_table,
            )

            # 3. Send results to client
            if extended_query_mode:
                send_execute_results(self.sock, final_df, send_row_description=send_row_description)
            else:
                send_query_results(self.sock, final_df, self.transaction_status)
            return True

        except PipelineExecutionError as e:
            self._runtime_log(
                "ERROR",
                f"Pipeline failed at stage {e.stage_index}: {e.stage_name}",
                event="pipeline_stage_error",
                stage_index=e.stage_index,
                stage_name=e.stage_name,
            )
            if extended_query_mode:
                self.sock.sendall(ErrorResponse.encode('ERROR', str(e)))
            else:
                send_error(self.sock, str(e))
            return False

        except Exception as e:
            if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                import traceback
                traceback.print_exc()
            self._runtime_log(
                "ERROR",
                f"Pipeline error: {e}",
                event="pipeline_error",
                error_type=type(e).__name__,
            )
            if extended_query_mode:
                self.sock.sendall(ErrorResponse.encode('ERROR', f"Pipeline query failed: {e}"))
            else:
                send_error(self.sock, f"Pipeline query failed: {e}")
            return False

    def _handle_watch_command(self, query: str, extended_query_mode: bool = False, send_row_description: bool = True):
        """
        Handle WATCH SQL commands for reactive subscriptions.

        Commands:
            CREATE WATCH name POLL EVERY 'interval' AS query ON TRIGGER CASCADE 'path'
            DROP WATCH name
            SHOW WATCHES
            DESCRIBE WATCH name
            TRIGGER WATCH name
            ALTER WATCH name SET enabled = true|false
            ALTER WATCH name SET POLL EVERY 'interval'

        Watches are polling-based subscriptions that trigger cascades when query
        results change. The daemon (`lars serve watcher`) evaluates watches.

        Args:
            query: The WATCH SQL command
            extended_query_mode: If True, use Extended Query Protocol response format
            send_row_description: If True (and extended_query_mode), send RowDescription
        """
        import pandas as pd
        from datetime import datetime

        from ..sql_tools.sql_directives import parse_watch_command

        directive = parse_watch_command(query)

        if not directive:
            send_error(self.sock, f"Failed to parse WATCH command: {query[:100]}")
            return

        try:
            if directive.command == 'CREATE':
                self._create_watch(directive, extended_query_mode, send_row_description)

            elif directive.command == 'DROP':
                self._drop_watch(directive.name, extended_query_mode, send_row_description)

            elif directive.command == 'SHOW':
                self._show_watches(extended_query_mode, send_row_description)

            elif directive.command == 'DESCRIBE':
                self._describe_watch(directive.name, extended_query_mode, send_row_description)

            elif directive.command == 'TRIGGER':
                self._trigger_watch(directive.name, extended_query_mode, send_row_description)

            elif directive.command == 'ALTER':
                self._alter_watch(directive, extended_query_mode, send_row_description)

            else:
                send_error(self.sock, f"Unknown WATCH command: {directive.command}")

        except Exception as e:
            if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                import traceback
                traceback.print_exc()
            self._runtime_log(
                "ERROR",
                f"WATCH command failed: {e}",
                event="watch_command_error",
                error_type=type(e).__name__,
            )
            send_error(self.sock, f"WATCH command failed: {e}")

    def _create_watch(self, directive, extended_query_mode: bool = False, send_row_description: bool = True):
        """Create a new watch subscription."""
        import pandas as pd
        from ..watcher import create_watch

        try:
            watch = create_watch(
                name=directive.name,
                query=directive.query,
                action_type=directive.action_type,
                action_spec=directive.action_spec,
                poll_interval=directive.poll_interval or '5m',
                description=directive.description or '',
            )

            result_df = pd.DataFrame([{
                'status': 'created',
                'watch_name': watch.name,
                'watch_id': watch.watch_id,
                'poll_interval': f"{watch.poll_interval_seconds}s",
                'action_type': watch.action_type.value,
                'action_spec': watch.action_spec,
                'message': f"Watch '{watch.name}' created. Run `lars serve watcher` to start the daemon.",
            }])

            if extended_query_mode:
                send_execute_results(self.sock, result_df, send_row_description=send_row_description)
            else:
                send_query_results(self.sock, result_df, self.transaction_status)
            self._runtime_log(
                "INFO",
                f"Created watch '{watch.name}'",
                event="watch_created",
                watch_name=watch.name,
                watch_id=watch.watch_id,
            )

        except Exception as e:
            raise RuntimeError(f"Failed to create watch '{directive.name}': {e}")

    def _drop_watch(self, name: str, extended_query_mode: bool = False, send_row_description: bool = True):
        """Drop a watch subscription."""
        import pandas as pd
        from ..watcher import drop_watch, get_watch

        watch = get_watch(name)
        if not watch:
            send_error(self.sock, f"Watch '{name}' not found")
            return

        if drop_watch(name):
            result_df = pd.DataFrame([{
                'status': 'dropped',
                'watch_name': name,
                'message': f"Watch '{name}' deleted successfully.",
            }])
            if extended_query_mode:
                send_execute_results(self.sock, result_df, send_row_description=send_row_description)
            else:
                send_query_results(self.sock, result_df, self.transaction_status)
            self._runtime_log(
                "INFO",
                f"Dropped watch '{name}'",
                event="watch_dropped",
                watch_name=name,
            )
        else:
            send_error(self.sock, f"Failed to drop watch '{name}'")

    def _show_watches(self, extended_query_mode: bool = False, send_row_description: bool = True):
        """List all watches."""
        import pandas as pd
        from ..watcher import list_watches

        watches = list_watches(enabled_only=False)

        # Define column structure - must match Describe Portal RowDescription
        columns = ['name', 'enabled', 'poll_interval', 'action_type', 'action_spec',
                   'trigger_count', 'last_triggered', 'last_checked', 'errors']

        if not watches:
            # Return empty DataFrame with correct column structure
            result_df = pd.DataFrame(columns=columns)
        else:
            rows = []
            for w in watches:
                interval = f"{w.poll_interval_seconds}s"
                if w.poll_interval_seconds >= 60:
                    interval = f"{w.poll_interval_seconds // 60}m"

                rows.append({
                    'name': w.name,
                    'enabled': w.enabled,
                    'poll_interval': interval,
                    'action_type': w.action_type.value,
                    'action_spec': w.action_spec[:50] + ('...' if len(w.action_spec) > 50 else ''),
                    'trigger_count': w.trigger_count,
                    'last_triggered': w.last_triggered_at.isoformat() if w.last_triggered_at else None,
                    'last_checked': w.last_checked_at.isoformat() if w.last_checked_at else None,
                    'errors': w.consecutive_errors,
                })
            result_df = pd.DataFrame(rows, columns=columns)

        if extended_query_mode:
            send_execute_results(self.sock, result_df, send_row_description=send_row_description)
        else:
            send_query_results(self.sock, result_df, self.transaction_status)
        self._runtime_log(
            "DEBUG",
            f"Listed {len(watches)} watches",
            event="watch_listed",
            watch_count=len(watches),
        )

    def _describe_watch(self, name: str, extended_query_mode: bool = False, send_row_description: bool = True):
        """Show detailed info about a watch."""
        import pandas as pd
        from ..watcher import get_watch

        watch = get_watch(name)
        if not watch:
            send_error(self.sock, f"Watch '{name}' not found")
            return

        interval = f"{watch.poll_interval_seconds}s"
        if watch.poll_interval_seconds >= 60:
            interval = f"{watch.poll_interval_seconds // 60}m"

        result_df = pd.DataFrame([{
            'watch_id': watch.watch_id,
            'name': watch.name,
            'enabled': watch.enabled,
            'poll_interval': interval,
            'action_type': watch.action_type.value,
            'action_spec': watch.action_spec,
            'query': watch.query,
            'trigger_count': watch.trigger_count,
            'consecutive_errors': watch.consecutive_errors,
            'last_error': watch.last_error,
            'last_triggered': watch.last_triggered_at.isoformat() if watch.last_triggered_at else None,
            'last_checked': watch.last_checked_at.isoformat() if watch.last_checked_at else None,
            'last_result_hash': watch.last_result_hash,
            'created_at': watch.created_at.isoformat() if watch.created_at else None,
            'description': watch.description,
        }])

        if extended_query_mode:
            send_execute_results(self.sock, result_df, send_row_description=send_row_description)
        else:
            send_query_results(self.sock, result_df, self.transaction_status)
        self._runtime_log(
            "DEBUG",
            f"Described watch '{name}'",
            event="watch_described",
            watch_name=name,
        )

    def _trigger_watch(self, name: str, extended_query_mode: bool = False, send_row_description: bool = True):
        """Force immediate evaluation of a watch."""
        import pandas as pd
        from ..watcher import trigger_watch, get_watch

        watch = get_watch(name)
        if not watch:
            send_error(self.sock, f"Watch '{name}' not found")
            return

        self._runtime_log(
            "INFO",
            f"Triggering watch '{name}'...",
            event="watch_trigger_start",
            watch_name=name,
        )

        # Run the evaluation synchronously
        from ..watcher import WatchDaemon
        daemon = WatchDaemon()

        # Define column structure - must match Describe Portal RowDescription
        columns = ['status', 'watch_name', 'execution_id', 'execution_status',
                   'row_count', 'cascade_session_id', 'triggered_at']

        try:
            daemon._evaluate_watch(watch)

            # Get the most recent execution
            from ..db_adapter import get_db
            db = get_db()
            rows = []
            if db:
                exec_rows = db.query(
                    """SELECT * FROM lars.watch_executions
                       WHERE watch_name = %(name)s
                       ORDER BY triggered_at DESC LIMIT 1""",
                    {'name': name}
                )
                if exec_rows:
                    row = exec_rows[0]
                    rows.append({
                        'status': 'triggered',
                        'watch_name': name,
                        'execution_id': row.get('execution_id'),
                        'execution_status': row.get('status'),
                        'row_count': row.get('row_count'),
                        'cascade_session_id': row.get('cascade_session_id'),
                        'triggered_at': row.get('triggered_at'),
                    })

            if not rows:
                # Use consistent columns with None/null for missing values
                rows.append({
                    'status': 'evaluated',
                    'watch_name': name,
                    'execution_id': None,
                    'execution_status': 'no_change',
                    'row_count': None,
                    'cascade_session_id': None,
                    'triggered_at': None,
                })

            result_df = pd.DataFrame(rows, columns=columns)
            if extended_query_mode:
                send_execute_results(self.sock, result_df, send_row_description=send_row_description)
            else:
                send_query_results(self.sock, result_df, self.transaction_status)
            self._runtime_log(
                "INFO",
                f"Triggered watch '{name}'",
                event="watch_triggered",
                watch_name=name,
            )

        except Exception as e:
            send_error(self.sock, f"Failed to trigger watch '{name}': {e}")

    def _alter_watch(self, directive, extended_query_mode: bool = False, send_row_description: bool = True):
        """Modify watch settings."""
        import pandas as pd
        from ..watcher import get_watch, save_watch, set_watch_enabled, _parse_duration

        watch = get_watch(directive.name)
        if not watch:
            send_error(self.sock, f"Watch '{directive.name}' not found")
            return

        if directive.set_field == 'enabled':
            enabled = directive.set_value in ('true', '1', 'yes')
            if set_watch_enabled(directive.name, enabled):
                status = "enabled" if enabled else "disabled"
                result_df = pd.DataFrame([{
                    'status': 'altered',
                    'watch_name': directive.name,
                    'field': 'enabled',
                    'value': enabled,
                    'message': f"Watch '{directive.name}' {status}.",
                }])
                if extended_query_mode:
                    send_execute_results(self.sock, result_df, send_row_description=send_row_description)
                else:
                    send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "INFO",
                    f"Watch '{directive.name}' {status}",
                    event="watch_altered",
                    watch_name=directive.name,
                    field="enabled",
                    status=status,
                )
            else:
                send_error(self.sock, f"Failed to alter watch '{directive.name}'")

        elif directive.set_field == 'poll_interval':
            watch.poll_interval_seconds = _parse_duration(directive.set_value)
            if save_watch(watch):
                result_df = pd.DataFrame([{
                    'status': 'altered',
                    'watch_name': directive.name,
                    'field': 'poll_interval',
                    'value': directive.set_value,
                    'message': f"Watch '{directive.name}' poll interval set to {directive.set_value}.",
                }])
                if extended_query_mode:
                    send_execute_results(self.sock, result_df, send_row_description=send_row_description)
                else:
                    send_query_results(self.sock, result_df, self.transaction_status)
                self._runtime_log(
                    "INFO",
                    f"Watch '{directive.name}' poll interval set to {directive.set_value}",
                    event="watch_altered",
                    watch_name=directive.name,
                    field="poll_interval",
                    value=directive.set_value,
                )
            else:
                send_error(self.sock, f"Failed to alter watch '{directive.name}'")

        else:
            send_error(self.sock, f"Unknown field to alter: {directive.set_field}")

    def _handle_parse(self, msg: dict):
        """
        Handle Parse message - prepare a SQL statement.

        Args:
            msg: Decoded Parse message {statement_name, query, param_types}
        """
        stmt_name = msg['statement_name']
        query = msg['query']
        param_types = msg['param_types']

        self._runtime_log(
            "DEBUG",
            f"Parse statement '{stmt_name or '(unnamed)'}': {query[:200]}{'...' if len(query) > 200 else ''}",
            event="pgwire_parse",
            statement_name=stmt_name,
            param_count=len(param_types),
            query=query if len(query or "") <= 10_000 else (query[:10_000] + "..."),
            query_len=len(query or ""),
        )

        try:
            # Rewrite into_ table references to read from ClickHouse
            try:
                from ..sql_tools.into_table_rewriter import rewrite_into_tables
                query, _ = rewrite_into_tables(query, results_db=self.results_db_name)
            except Exception:
                pass  # Non-fatal

            # Rewrite LARS MAP/RUN syntax to standard SQL BEFORE preparing
            from lars.sql_rewriter import rewrite_lars_syntax
            original_query = query
            query = rewrite_lars_syntax(query, duckdb_conn=self.duckdb_conn)

            if query != original_query:
                self._runtime_log(
                    "DEBUG",
                    f"Rewrote LARS syntax ({len(original_query)} → {len(query)} chars)",
                    event="rewrite_lars_syntax",
                    before_len=len(original_query),
                    after_len=len(query),
                )

            # Store prepared statement
            # We don't actually use DuckDB PREPARE yet - just store the query
            # DuckDB PREPARE has different syntax ($1 vs ?)
            # NOTE: We store original_query for SQL Trail logging in _handle_execute
            self.prepared_statements[stmt_name] = {
                'query': query,
                'original_query': original_query,  # For SQL Trail detection/logging
                'param_types': param_types,
                'param_count': len(param_types)
            }

            # Send ParseComplete
            self._runtime_log("DEBUG", "SEND ParseComplete", event="pgwire_send", pgwire_message="ParseComplete")
            self.sock.sendall(ParseComplete.encode())
            self._runtime_log(
                "DEBUG",
                f"Statement prepared ({len(param_types)} parameters)",
                event="pgwire_parse_complete",
                statement_name=stmt_name,
                param_count=len(param_types),
            )

        except Exception as e:
            self._runtime_log("ERROR", f"Parse error: {e}", event="pgwire_error", pgwire_message="PARSE")
            # In Extended Query Protocol, don't send ReadyForQuery - wait for Sync
            self.sock.sendall(ErrorResponse.encode('ERROR', f"Parse error: {str(e)}"))

    def _handle_bind(self, msg: dict):
        """
        Handle Bind message - bind parameters to prepared statement.

        Args:
            msg: Decoded Bind message {portal_name, statement_name, param_formats, param_values, result_formats}
        """
        portal_name = msg['portal_name']
        stmt_name = msg['statement_name']
        param_values = msg['param_values']
        param_formats = msg['param_formats']
        result_formats = msg['result_formats']

        self._runtime_log(
            "DEBUG",
            f"Bind portal '{portal_name or '(unnamed)'}' to statement '{stmt_name or '(unnamed)'}'",
            event="pgwire_bind",
            portal_name=portal_name,
            statement_name=stmt_name,
        )

        try:
            # Get prepared statement
            if stmt_name not in self.prepared_statements:
                raise Exception(f"Prepared statement '{stmt_name}' does not exist")

            stmt = self.prepared_statements[stmt_name]

            # Convert parameter values from wire format to Python types
            params = []
            for i, value_bytes in enumerate(param_values):
                if value_bytes is None:
                    params.append(None)
                else:
                    # Get format (0=text, 1=binary)
                    fmt = param_formats[i] if i < len(param_formats) else (param_formats[0] if param_formats else 0)

                    if fmt == 0:  # Text format
                        value_str = value_bytes.decode('utf-8')

                        # Get parameter type OID (0 = infer type)
                        param_type = stmt['param_types'][i] if i < len(stmt['param_types']) else 0

                        # Cast based on type
                        if param_type == 0:
                            # Type not specified - infer from value
                            # Try int first, then float, else string
                            try:
                                params.append(int(value_str))
                            except:
                                try:
                                    params.append(float(value_str))
                                except:
                                    params.append(value_str)
                        elif param_type in (23, 20, 21):  # INTEGER, BIGINT, SMALLINT
                            try:
                                params.append(int(value_str))
                            except ValueError:
                                # Some clients send integral values as float-like strings (e.g. "4.0")
                                # even when the parameter type is an integer OID.
                                import re
                                stripped = value_str.strip()
                                if re.fullmatch(r"[+-]?\d+\.0+", stripped):
                                    params.append(int(stripped.split(".", 1)[0]))
                                else:
                                    raise
                        elif param_type == 701:  # DOUBLE
                            params.append(float(value_str))
                        elif param_type == 16:  # BOOLEAN
                            params.append(value_str.lower() in ('t', 'true', '1', 'yes'))
                        else:  # VARCHAR, TEXT, etc.
                            params.append(value_str)
                    else:
                        # Binary format - decode based on type
                        import struct
                        param_type = stmt['param_types'][i] if i < len(stmt['param_types']) else 0

                        if param_type == 23:  # INTEGER (int32)
                            params.append(struct.unpack('!i', value_bytes)[0])
                        elif param_type == 20:  # BIGINT (int64)
                            params.append(struct.unpack('!q', value_bytes)[0])
                        elif param_type == 21:  # SMALLINT (int16)
                            params.append(struct.unpack('!h', value_bytes)[0])
                        elif param_type == 701:  # DOUBLE (float64)
                            params.append(struct.unpack('!d', value_bytes)[0])
                        elif param_type == 700:  # FLOAT (float32)
                            params.append(struct.unpack('!f', value_bytes)[0])
                        elif param_type == 16:  # BOOLEAN (1 byte)
                            params.append(value_bytes[0] != 0)
                        elif param_type in [1043, 25]:  # VARCHAR, TEXT
                            params.append(value_bytes.decode('utf-8'))
                        else:
                            # Unknown type - try to decode as string
                            try:
                                params.append(value_bytes.decode('utf-8'))
                            except:
                                # If that fails, just use the bytes as-is
                                params.append(value_bytes)

            # Store portal
            # NOTE: original_query is used for SQL Trail detection/logging in _handle_execute
            self.portals[portal_name] = {
                'statement_name': stmt_name,
                'params': params,
                'result_formats': result_formats,
                'query': stmt['query'],
                'original_query': stmt.get('original_query'),  # For SQL Trail
                'row_description_sent': False  # Track if Describe sent RowDescription
            }

            # Send BindComplete
            self._runtime_log("DEBUG", "SEND BindComplete", event="pgwire_send", pgwire_message="BindComplete")
            self.sock.sendall(BindComplete.encode())
            self._runtime_log(
                "DEBUG",
                f"Parameters bound ({len(params)} values)",
                event="pgwire_bind_complete",
                portal_name=portal_name,
                statement_name=stmt_name,
                param_count=len(params),
            )

        except Exception as e:
            self._runtime_log("ERROR", f"Bind error: {e}", event="pgwire_error", pgwire_message="BIND")
            # In Extended Query Protocol, don't send ReadyForQuery - wait for Sync
            self.sock.sendall(ErrorResponse.encode('ERROR', f"Bind error: {str(e)}"))

    def _handle_describe(self, msg: dict):
        """
        Handle Describe message - describe statement or portal.

        Args:
            msg: Decoded Describe message {type, name}
        """
        describe_type = msg['type']
        name = msg['name']

        self._runtime_log(
            "DEBUG",
            f"Describe {describe_type} '{name or '(unnamed)'}'",
            event="pgwire_describe",
            describe_type=describe_type,
            name=name,
        )

        try:
            if describe_type == 'S':  # Statement
                if name not in self.prepared_statements:
                    raise Exception(f"Prepared statement '{name}' does not exist")

                stmt = self.prepared_statements[name]

                # Send ParameterDescription
                self._runtime_log(
                    "DEBUG",
                    f"SEND ParameterDescription ({len(stmt['param_types'])} params)",
                    event="pgwire_send",
                    pgwire_message="ParameterDescription",
                    param_count=len(stmt['param_types']),
                )
                self.sock.sendall(ParameterDescription.encode(stmt['param_types']))

                # Send NoData for Describe Statement
                # Per PostgreSQL protocol, NoData is valid here - it tells the client
                # that column info will be available after Bind (via Describe Portal).
                # This is the safest approach since we can't reliably determine columns
                # without actually executing the query with bound parameters.
                self._runtime_log("DEBUG", "SEND NoData", event="pgwire_send", pgwire_message="NoData")
                self.sock.sendall(NoData.encode())

                self._runtime_log(
                    "DEBUG",
                    f"Statement described ({len(stmt['param_types'])} parameters)",
                    event="pgwire_describe_complete",
                    describe_type="S",
                    name=name,
                    param_count=len(stmt['param_types']),
                )

            elif describe_type == 'P':  # Portal
                if name not in self.portals:
                    raise Exception(f"Portal '{name}' does not exist")

                portal = self.portals[name]
                query = portal['query']
                params = portal['params']
                query_upper = query.upper().strip()

                # For non-SELECT queries (SET, BEGIN, COMMIT, DDL, DML, etc.), return NoData
                is_non_select = (
                    # Transaction control
                    query_upper.startswith('SET ') or
                    query_upper.startswith('RESET ') or
                    query_upper.startswith('BEGIN') or
                    query_upper.startswith('COMMIT') or
                    query_upper.startswith('ROLLBACK') or
                    query_upper.startswith('START TRANSACTION') or
                    query_upper.startswith('END') or
                    # Session/connection
                    query_upper.startswith('DISCARD') or
                    query_upper.startswith('DEALLOCATE') or
                    query_upper.startswith('CLOSE') or
                    query_upper.startswith('LISTEN') or
                    query_upper.startswith('UNLISTEN') or
                    query_upper.startswith('NOTIFY') or
                    # DDL - Data Definition Language
                    query_upper.startswith('CREATE ') or
                    query_upper.startswith('DROP ') or
                    query_upper.startswith('ALTER ') or
                    query_upper.startswith('TRUNCATE ') or
                    # DML - Data Manipulation Language (non-SELECT)
                    query_upper.startswith('INSERT ') or
                    query_upper.startswith('UPDATE ') or
                    query_upper.startswith('DELETE ') or
                    # Privileges
                    query_upper.startswith('GRANT ') or
                    query_upper.startswith('REVOKE ') or
                    # Other
                    query_upper.startswith('VACUUM') or
                    query_upper.startswith('ANALYZE') or
                    query_upper.startswith('REINDEX') or
                    query_upper.startswith('CLUSTER') or
                    query_upper.startswith('REFRESH ')
                )

                if is_non_select:
                    self.sock.sendall(NoData.encode())
                    portal['row_description_sent'] = False
                    self._runtime_log(
                        "DEBUG",
                        "Portal described (NoData - non-SELECT command)",
                        event="pgwire_describe_portal",
                        describe_result="nodata_non_select",
                    )
                    return

                # BACKGROUND queries - Return job metadata columns
                # Check original_query since BACKGROUND prefix is stripped during rewriting
                original_query_for_directive = portal.get('original_query')
                if original_query_for_directive:
                    orig_upper = original_query_for_directive.upper().strip()
                    if orig_upper.startswith('BACKGROUND'):
                        # Send RowDescription with job metadata columns
                        columns = [
                            ('job_id', 'VARCHAR'),
                            ('status', 'VARCHAR'),
                            ('result_table', 'VARCHAR'),
                            ('submitted_at', 'VARCHAR'),
                            ('query_preview', 'VARCHAR'),
                            ('check_status', 'VARCHAR'),
                            ('await_completion', 'VARCHAR'),
                            ('message_log', 'VARCHAR'),
                        ]
                        self.sock.sendall(RowDescription.encode(columns))
                        portal['row_description_sent'] = True
                        portal['described_columns'] = len(columns)
                        self._runtime_log(
                            "DEBUG",
                            f"Portal described (BACKGROUND - {len(columns)} columns)",
                            event="pgwire_describe_portal",
                            describe_result="background",
                            column_count=len(columns),
                        )
                        return

                # WATCH commands - Handle reactive SQL subscriptions
                # Send appropriate RowDescription based on command type
                from ..sql_tools.sql_directives import is_watch_command, parse_watch_command
                if is_watch_command(query):
                    # Determine column structure based on WATCH command type
                    watch_directive = parse_watch_command(query)
                    if watch_directive:
                        if watch_directive.command == 'SHOW':
                            columns = [
                                ('name', 'VARCHAR'),
                                ('enabled', 'BOOLEAN'),
                                ('poll_interval', 'VARCHAR'),
                                ('action_type', 'VARCHAR'),
                                ('action_spec', 'VARCHAR'),
                                ('trigger_count', 'INTEGER'),
                                ('last_triggered', 'VARCHAR'),
                                ('last_checked', 'VARCHAR'),
                                ('errors', 'INTEGER'),
                            ]
                        elif watch_directive.command == 'DESCRIBE':
                            columns = [
                                ('watch_id', 'VARCHAR'),
                                ('name', 'VARCHAR'),
                                ('enabled', 'BOOLEAN'),
                                ('poll_interval', 'VARCHAR'),
                                ('action_type', 'VARCHAR'),
                                ('action_spec', 'VARCHAR'),
                                ('query', 'VARCHAR'),
                                ('trigger_count', 'INTEGER'),
                                ('consecutive_errors', 'INTEGER'),
                                ('last_error', 'VARCHAR'),
                                ('last_triggered', 'VARCHAR'),
                                ('last_checked', 'VARCHAR'),
                                ('last_result_hash', 'VARCHAR'),
                                ('created_at', 'VARCHAR'),
                                ('description', 'VARCHAR'),
                            ]
                        elif watch_directive.command == 'TRIGGER':
                            columns = [
                                ('status', 'VARCHAR'),
                                ('watch_name', 'VARCHAR'),
                                ('execution_id', 'VARCHAR'),
                                ('execution_status', 'VARCHAR'),
                                ('row_count', 'INTEGER'),
                                ('cascade_session_id', 'VARCHAR'),
                                ('triggered_at', 'VARCHAR'),
                            ]
                        elif watch_directive.command == 'CREATE':
                            columns = [
                                ('status', 'VARCHAR'),
                                ('watch_name', 'VARCHAR'),
                                ('watch_id', 'VARCHAR'),
                                ('poll_interval', 'VARCHAR'),
                                ('action_type', 'VARCHAR'),
                                ('action_spec', 'VARCHAR'),
                                ('message', 'VARCHAR'),
                            ]
                        elif watch_directive.command in ('DROP', 'ALTER'):
                            columns = [
                                ('status', 'VARCHAR'),
                                ('watch_name', 'VARCHAR'),
                                ('message', 'VARCHAR'),
                            ]
                            if watch_directive.command == 'ALTER':
                                columns.insert(2, ('field', 'VARCHAR'))
                                columns.insert(3, ('value', 'VARCHAR'))
                        else:
                            columns = [('result', 'VARCHAR')]

                        self.sock.sendall(RowDescription.encode(columns))
                        portal['row_description_sent'] = True
                        portal['described_columns'] = len(columns)
                        self._runtime_log(
                            "DEBUG",
                            f"Portal described (WATCH {watch_directive.command} - {len(columns)} columns)",
                            event="pgwire_describe_portal",
                            describe_result="watch",
                            watch_command=watch_directive.command,
                            column_count=len(columns),
                        )
                    else:
                        # Couldn't parse - send NoData
                        self.sock.sendall(NoData.encode())
                        portal['row_description_sent'] = False
                        self._runtime_log(
                            "DEBUG",
                            "Portal described (WATCH command - NoData)",
                            event="pgwire_describe_portal",
                            describe_result="watch_nodata",
                        )
                    return

                # EXPLAIN queries - return query_plan column without executing the query
                # Must be checked BEFORE pipeline syntax to avoid executing full pipeline
                # IMPORTANT: Check original_query (not rewritten query) because rewrite_lars_syntax()
                # transforms EXPLAIN into SELECT '...' AS query_plan during Parse phase
                import re
                original_query = portal.get('original_query') or query
                explain_check = (original_query).upper().strip()
                if re.match(r'^EXPLAIN[\s(]', explain_check):
                    # Check for FORMAT JSON in EXPLAIN options
                    is_json = 'FORMAT' in explain_check and 'JSON' in explain_check
                    if is_json:
                        columns = [('QUERY PLAN', 'JSON')]
                    else:
                        columns = [('query_plan', 'VARCHAR')]

                    self.sock.sendall(RowDescription.encode(columns))
                    portal['row_description_sent'] = True
                    portal['described_columns'] = len(columns)
                    self._runtime_log(
                        "DEBUG",
                        f"Portal described (EXPLAIN - {len(columns)} columns)",
                        event="pgwire_describe_portal",
                        describe_result="explain",
                        column_count=len(columns),
                    )
                    return

                # PIPELINE syntax (THEN/INTO) - Execute pipeline to determine result columns
                # Cache result for Execute phase to avoid re-running the pipeline
                # IMPORTANT: Use original_query for pipeline detection to avoid conflicts
                # with semantic SQL rewriters that might transform function names (e.g., DEDUPE)
                from ..sql_tools.pipeline_parser import has_pipeline_syntax, parse_pipeline_syntax
                original_query = portal.get('original_query') or query

                # Pre-process CANVAS syntax - rewrites to SQL with THEN RENDER_CANVAS(...)
                from ..sql_tools.canvas_rewriter import has_canvas_syntax, rewrite_canvas_syntax
                if has_canvas_syntax(original_query):
                    original_query = rewrite_canvas_syntax(original_query)
                    self._runtime_log(
                        "DEBUG",
                        "CANVAS syntax rewritten (Describe)",
                        event="describe_canvas_rewrite",
                    )

                if has_pipeline_syntax(original_query):
                    self._runtime_log(
                        "DEBUG",
                        "PIPELINE query detected in Describe - executing to determine columns",
                        event="describe_pipeline_detected",
                    )
                    try:
                        import pandas as pd
                        from ..sql_tools.pipeline_executor import execute_pipeline_with_into
                        from ..sql_rewriter import rewrite_lars_syntax

                        pipeline = parse_pipeline_syntax(original_query)
                        if pipeline and pipeline.stages:
                            # Execute base SQL with unified rewriting (handles dimension functions, semantic operators, etc.)
                            base_sql = pipeline.base_sql

                            # Rewrite into_ table references to read from ClickHouse
                            try:
                                from ..sql_tools.into_table_rewriter import rewrite_into_tables
                                base_sql, _ = rewrite_into_tables(base_sql, results_db=self.results_db_name)
                            except Exception:
                                pass  # Non-fatal

                            # Deref preprocessing: evaluate @cascade() expressions first
                            from ..sql_tools.deref_preprocessor import preprocess_deref_cascades
                            deref_context = {
                                'session_id': f"{self.auth_user_id}:{self.database_name}",
                                'protocol': 'pgwire',
                                'database_name': self.database_name,
                                'user_name': self.user_name,
                                'application_name': self.application_name,
                                'client_address': f"{self.addr[0]}:{self.addr[1]}" if self.addr else '',
                                'caller_id': getattr(self, '_current_caller_id', None),
                            }
                            base_sql = preprocess_deref_cascades(base_sql, deref_context)

                            base_sql = rewrite_lars_syntax(base_sql, duckdb_conn=self.duckdb_conn)

                            # Preprocess CTEs with THEN pipeline syntax
                            from ..sql_tools.pipeline_parser import preprocess_cte_pipelines
                            base_sql = preprocess_cte_pipelines(
                                base_sql,
                                duckdb_conn=self.duckdb_conn,
                                session_id=self.session_id,
                                caller_id=getattr(self, '_current_caller_id', None),
                            )

                            # Execute base query
                            result = self.duckdb_conn.execute(base_sql)
                            columns = [desc[0] for desc in result.description]
                            rows = result.fetchall()
                            initial_df = pd.DataFrame(rows, columns=columns)

                            # Execute pipeline stages
                            final_df = execute_pipeline_with_into(
                                stages=pipeline.stages,
                                initial_df=initial_df,
                                into_table=pipeline.into_table,
                                duckdb_conn=self.duckdb_conn,
                                session_id=self.session_id,
                                results_db=self.results_db_name,
                                caller_id=getattr(self, '_current_caller_id', None),
                                original_query=query,
                                base_into_table=pipeline.base_into_table,
                            )

                            # Cache result for Execute
                            portal['pipeline_result'] = final_df

                            # Send RowDescription with actual columns
                            desc_columns = []
                            for col_name, dtype in zip(final_df.columns, final_df.dtypes):
                                dtype_str = str(dtype).upper()
                                if 'INT' in dtype_str:
                                    col_type = 'BIGINT'
                                elif 'FLOAT' in dtype_str:
                                    col_type = 'DOUBLE'
                                elif 'BOOL' in dtype_str:
                                    col_type = 'BOOLEAN'
                                else:
                                    col_type = 'VARCHAR'
                                desc_columns.append((col_name, col_type))

                            self.sock.sendall(RowDescription.encode(desc_columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(desc_columns)
                            self._runtime_log(
                                "DEBUG",
                                f"Portal described (PIPELINE - {len(desc_columns)} columns, result cached)",
                                event="pgwire_describe_portal",
                                describe_result="pipeline",
                                column_count=len(desc_columns),
                                result_cached=True,
                            )
                            return

                    except Exception as e:
                        if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                            import traceback
                            traceback.print_exc()
                        self._runtime_log(
                            "WARN",
                            f"PIPELINE Describe failed: {e}",
                            event="describe_pipeline_failed",
                            error_type=type(e).__name__,
                        )
                        # Fall through to NoData as fallback
                        self.sock.sendall(NoData.encode())
                        portal['row_description_sent'] = False
                        return

                elif query_upper.startswith('SHOW '):
                    # SHOW commands return a single column - provide the correct RowDescription
                    # This prevents the wrapping logic from failing
                    if 'SEARCH_PATH' in query_upper:
                        columns = [('search_path', 'VARCHAR')]
                    elif 'TIMEZONE' in query_upper or 'TIME ZONE' in query_upper:
                        columns = [('TimeZone', 'VARCHAR')]
                    elif 'SERVER_VERSION' in query_upper:
                        columns = [('server_version', 'VARCHAR')]
                    elif 'TRANSACTION' in query_upper and 'ISOLATION' in query_upper:
                        columns = [('transaction_isolation', 'VARCHAR')]
                    else:
                        # Generic fallback for other SHOW commands
                        columns = [('setting', 'VARCHAR')]

                    self.sock.sendall(RowDescription.encode(columns))
                    portal['row_description_sent'] = True
                    portal['described_columns'] = len(columns)
                    self._runtime_log(
                        "DEBUG",
                        f"Portal described (SHOW command - {len(columns)} columns)",
                        event="pgwire_describe_portal",
                        describe_result="show",
                        column_count=len(columns),
                    )
                else:
                    # For SELECT queries, try to get column metadata
                    try:
                        # Convert PostgreSQL placeholders to DuckDB format
                        desc_query = query
                        for i in range(len(params), 0, -1):
                            desc_query = desc_query.replace(f'${i}', '?')

                        # Debug: show original query before ANY rewriters for pg_class
                        # if 'PG_CLASS' in query_upper and 'RELKIND' in query_upper:
                        #     print(f"[DEBUG] pg_class: ORIGINAL QUERY STRUCTURE:")
                        #     # for i, line in enumerate(desc_query.split('\n'), 1):
                        #     #     if line.strip():
                        #     #         print(f"[DEBUG]   Line {i}: {line.strip()[:100]}")

                        # Apply standard query rewrites
                        desc_query = self._rewrite_pg_catalog_function_calls(desc_query)
                        desc_query = self._rewrite_information_schema_catalog_filters(desc_query)
                        # Debug: track WHERE through rewriters for pg_class table queries
                        is_pg_class_table_query = 'PG_CLASS' in query_upper and 'RELKIND' in query_upper
                        # if is_pg_class_table_query:
                        #     print(f"[DEBUG] pg_class: ORIGINAL QUERY (first 500 chars):")
                        #     print(f"[DEBUG]   {desc_query[:500]}...")
                        #     print(f"[DEBUG] pg_class: BEFORE rewriters - WHERE: {'WHERE' in desc_query.upper()}")
                        desc_query = self._rewrite_pg_system_column_refs(desc_query)
                        # if is_pg_class_table_query:
                        #     print(f"[DEBUG] pg_class: AFTER system_refs - WHERE: {'WHERE' in desc_query.upper()}")
                        desc_query = self._rewrite_missing_table_joins(desc_query)
                        # NOTE: UNION stripping disabled - causes parameter count mismatches
                        # desc_query = self._strip_union_parts_with_missing_tables(desc_query)
                        # if is_pg_class_table_query:
                        #     print(f"[DEBUG] pg_class: AFTER missing_joins - WHERE: {'WHERE' in desc_query.upper()}")
                        desc_query = self._rewrite_pg_inherits_subqueries(desc_query)
                        # if is_pg_class_table_query:
                        #     print(f"[DEBUG] pg_class: AFTER pg_inherits - WHERE: {'WHERE' in desc_query.upper()}")
                        desc_query = self._rewrite_pg_get_expr_calls(desc_query)
                        desc_query = self._rewrite_missing_pg_database_columns(desc_query)

                        # Deref preprocessing: evaluate @cascade() expressions
                        from ..sql_tools.deref_preprocessor import preprocess_deref_cascades
                        deref_context = {
                            'session_id': f"{self.auth_user_id}:{self.database_name}",
                            'protocol': 'pgwire',
                            'database_name': self.database_name,
                            'user_name': self.user_name,
                            'application_name': self.application_name,
                            'client_address': f"{self.addr[0]}:{self.addr[1]}" if self.addr else '',
                            'caller_id': getattr(self, '_current_caller_id', None),
                        }
                        desc_query = preprocess_deref_cascades(desc_query, deref_context)

                        # Strip PostgreSQL type casts that DuckDB doesn't support
                        for cast in ['::regclass', '::regtype', '::regproc', '::oid', '::bigint',
                                     '::REGCLASS', '::REGTYPE', '::REGPROC', '::OID', '::BIGINT',
                                     '::integer', '::INTEGER', '::text', '::TEXT', '::varchar', '::VARCHAR']:
                            desc_query = desc_query.replace(cast, '')

                        # Check for empty query after rewrites (e.g., just comments or whitespace)
                        query_stripped = desc_query.strip()
                        if not query_stripped or query_stripped.startswith('--'):
                            self.sock.sendall(NoData.encode())
                            portal['row_description_sent'] = False
                            return

                        # Handle special catalog tables that need specific column info
                        # pg_timezone_names / pg_timezone_abbrevs
                        if 'PG_TIMEZONE_NAMES' in query_upper or 'PG_TIMEZONE_ABBREVS' in query_upper:
                            cols = self._expected_result_columns(query) or ['name', 'is_dst']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_roles
                        if 'PG_ROLES' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'rolname', 'rolsuper']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_user - DataGrip checks superuser status
                        if 'PG_USER' in query_upper and 'FROM' in query_upper and 'PG_USER_MAPPINGS' not in query_upper:
                            cols = self._expected_result_columns(query) or ['usename', 'usesuper']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_namespace (schema browser) - provide expected columns
                        is_pg_class_main = 'FROM PG_CATALOG.PG_CLASS' in query_upper or 'FROM PG_CLASS' in query_upper
                        is_pg_namespace_main = ('FROM PG_CATALOG.PG_NAMESPACE' in query_upper or 'FROM PG_NAMESPACE' in query_upper)
                        if is_pg_namespace_main and not is_pg_class_main:
                            cols = self._expected_result_columns(query) or ['id', 'state_number', 'name', 'description', 'owner']
                            # Expand '*' or 'n.*' to actual pg_namespace columns
                            pg_namespace_cols = ['oid', 'nspname', 'nspowner', 'nspacl']
                            expanded_cols = []
                            for c in cols:
                                if c == '*' or c.endswith('.*'):
                                    expanded_cols.extend(pg_namespace_cols)
                                else:
                                    expanded_cols.append(c)
                            # Deduplicate while preserving order (e.g., 'oid' appears in both SELECT n.oid and n.*)
                            seen = set()
                            unique_cols = []
                            for c in expanded_cols:
                                if c not in seen:
                                    seen.add(c)
                                    unique_cols.append(c)
                            cols = unique_cols
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_class (table browser) - provide expected columns without executing
                        # Complex pg_class queries with pg_inherits subqueries often fail during Describe
                        # due to DuckDB incompatibilities. Bypass execution and infer columns from query.
                        if is_pg_class_main:
                            cols = self._expected_result_columns(query) or [
                                'oid', 'relname', 'relnamespace', 'relkind', 'relowner',
                                'relhasindex', 'relrowsecurity', 'relforcerowsecurity',
                                'relispartition', 'description', 'partition_expr', 'partition_key'
                            ]
                            # Expand * or c.* to actual pg_class columns (must match Execute phase)
                            pg_class_star_cols = [
                                'relname', 'relnamespace', 'reltype', 'reloftype', 'relowner',
                                'relam', 'relfilenode', 'reltablespace', 'relpages', 'reltuples',
                                'relallvisible', 'reltoastrelid', 'relhasindex', 'relisshared',
                                'relpersistence', 'relkind', 'relnatts', 'relchecks', 'relhasrules',
                                'relhastriggers', 'relhassubclass', 'relrowsecurity', 'relforcerowsecurity',
                                'relispopulated', 'relreplident', 'relispartition', 'relrewrite',
                                'relfrozenxid', 'relminmxid', 'relacl', 'reloptions', 'relpartbound'
                            ]
                            expanded_cols = []
                            for c in cols:
                                if c == '*' or c.lower().endswith('.*'):
                                    expanded_cols.extend(pg_class_star_cols)
                                else:
                                    expanded_cols.append(c)
                            columns = [(c, 'VARCHAR') for c in expanded_cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_event_trigger - DuckDB doesn't have event triggers
                        if 'PG_EVENT_TRIGGER' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'evtname', 'evtevent', 'evtowner', 'evtfoid', 'evtenabled', 'evttags']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # Foreign data wrapper tables - DuckDB doesn't have FDW
                        if 'PG_FOREIGN_DATA_WRAPPER' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'fdwname', 'fdwowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        if 'PG_FOREIGN_SERVER' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'srvname', 'srvowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        if 'PG_FOREIGN_TABLE' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['ftrelid', 'ftserver', 'ftoptions']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_extension - DuckDB doesn't have extensions
                        if 'PG_EXTENSION' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'extname', 'extowner', 'extnamespace']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_language - DuckDB doesn't have procedural languages
                        if 'PG_LANGUAGE' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'lanname', 'lanowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_cast - DuckDB doesn't have pg_cast
                        if 'PG_CAST' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'castsource', 'casttarget', 'castfunc', 'castcontext', 'castmethod']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_collation - DuckDB doesn't have pg_collation
                        if self._primary_from_table(query_upper) == 'PG_COLLATION':
                            cols = self._expected_result_columns(query) or ['oid', 'collname', 'collnamespace', 'collowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_inherits - DuckDB doesn't have table inheritance
                        # Only match if pg_inherits is the main table, not just a LEFT JOIN in a pg_class query
                        if 'PG_INHERITS' in query_upper and 'PG_CLASS' not in query_upper:
                            cols = self._expected_result_columns(query) or ['inhrelid', 'inhparent', 'inhseqno']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_partitioned_table - DuckDB doesn't have partition metadata
                        if 'PG_PARTITIONED_TABLE' in query_upper:
                            cols = self._expected_result_columns(query) or ['partrelid', 'partstrat', 'partnatts']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_description - DuckDB doesn't have pg_description
                        # Catches UNION queries where pg_description is the main FROM table
                        if 'FROM PG_CATALOG.PG_DESCRIPTION' in query_upper or 'FROM PG_DESCRIPTION' in query_upper:
                            cols = self._expected_result_columns(query) or ['id', 'sub_ids', 'kind', 'description']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_operator - DuckDB doesn't have pg_operator
                        if self._primary_from_table(query_upper) == 'PG_OPERATOR':
                            cols = self._expected_result_columns(query) or ['oid', 'oprname', 'oprnamespace', 'oprowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_aggregate - DuckDB doesn't have pg_aggregate
                        if 'PG_AGGREGATE' in query_upper:
                            cols = self._expected_result_columns(query) or ['aggfnoid', 'aggkind', 'aggnumdirectargs']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # Complex pg_constraint queries with PostgreSQL-specific array functions
                        if 'PG_CONSTRAINT' in query_upper and ('CONEXCLOP' in query_upper or 'UNNEST' in query_upper or 'REGOPER' in query_upper):
                            cols = self._expected_result_columns(query) or ['oid', 'conname', 'connamespace', 'contype']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_attribute queries - expand a.* to actual columns
                        if 'PG_ATTRIBUTE' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or [
                                'relname', 'attname', 'attnum', 'atttypid', 'attnotnull',
                                'attlen', 'attrelid', 'def_value', 'description', 'objid'
                            ]
                            # Expand * or a.* to actual pg_attribute columns
                            pg_attribute_star_cols = [
                                'attrelid', 'attname', 'atttypid', 'attstattarget', 'attlen',
                                'attnum', 'attndims', 'attcacheoff', 'atttypmod', 'attbyval',
                                'attstorage', 'attalign', 'attnotnull', 'atthasdef', 'atthasmissing',
                                'attidentity', 'attgenerated', 'attisdropped', 'attislocal',
                                'attinhcount', 'attcollation', 'attacl', 'attoptions', 'attfdwoptions',
                                'attmissingval'
                            ]
                            expanded_cols = []
                            for c in cols:
                                if c == '*' or c.lower().endswith('.*'):
                                    expanded_cols.extend(pg_attribute_star_cols)
                                else:
                                    expanded_cols.append(c)
                            columns = [(c, 'VARCHAR') for c in expanded_cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # pg_depend queries with regclass casts - return empty result
                        if 'PG_DEPEND' in query_upper and ('REGCLASS' in query_upper or 'REFOBJID' in query_upper):
                            cols = self._expected_result_columns(query) or ['dependent_id', 'owner_id', 'refobjsubid']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # Any query with regclass type casts that DuckDB doesn't support
                        if '::REGCLASS' in query_upper or 'REGCLASS' in query_upper:
                            cols = self._expected_result_columns(query) or ['result']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            return

                        # Check for missing pg_catalog tables before trying to wrap
                        # This prevents errors like "pg_locks does not exist"
                        missing_result = self._handle_missing_pg_catalog_tables(query_upper, desc_query)
                        if missing_result is not None:
                            # Send RowDescription with the expected columns
                            columns = [(col, 'VARCHAR') for col in missing_result.columns]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            portal['missing_table_result'] = missing_result  # Cache for Execute
                            return

                        # Skill/UDF calls in FROM clause - don't execute during Describe
                        # LIMIT 0 doesn't prevent UDFs from being evaluated, causing double execution
                        # Instead, execute the query ONCE during Describe and cache for Execute
                        # Check both original syntax (skill::) and rewritten form (read_json_auto(skill())
                        desc_query_lower = desc_query.lower()
                        has_skill_call = (
                            'skill(' in desc_query_lower or
                            'skill::' in desc_query_lower or
                            'read_json_auto(skill' in desc_query_lower
                        )
                        if has_skill_call:
                            # Execute the skill query once and cache the result for Execute phase
                            try:
                                import pandas as pd
                                result = self.duckdb_conn.execute(desc_query, params)
                                columns_info = result.description or []
                                rows = result.fetchall()
                                col_names = [c[0] for c in columns_info]
                                result_df = pd.DataFrame(rows, columns=col_names) if col_names else pd.DataFrame()

                                # Cache result for Execute
                                portal['skill_result'] = result_df

                                # Build and send RowDescription
                                columns = []
                                for col_info in columns_info:
                                    col_name = col_info[0]
                                    col_type = str(col_info[1]) if col_info[1] else 'VARCHAR'
                                    columns.append((col_name, col_type))

                                if columns:
                                    self.sock.sendall(RowDescription.encode(columns))
                                    portal['row_description_sent'] = True
                                    portal['described_columns'] = len(columns)
                                else:
                                    self.sock.sendall(NoData.encode())
                                    portal['row_description_sent'] = False
                                return
                            except Exception as skill_err:
                                self._runtime_log(
                                    "WARN",
                                    f"Skill describe failed: {skill_err}",
                                    event="describe_skill_failed",
                                    error_type=type(skill_err).__name__,
                                )
                                # Fall through to normal describe logic

                        # Wrap query to get schema without returning data
                        # Use a subquery to handle complex queries
                        safe_desc_query = desc_query.strip().rstrip(';')
                        # Put the closing paren on its own line so trailing "-- ..." comments in the
                        # described SQL don't comment out the wrapper's closing paren.
                        wrapped_query = f"SELECT * FROM (\n{safe_desc_query}\n) _lars_desc_sub LIMIT 0"

                        result = self.duckdb_conn.execute(wrapped_query, params)

                        # Build column list from result.description
                        # DuckDB result.description: [(name, type, None, None, None, None, None), ...]
                        columns = []
                        if result.description:
                            for col_info in result.description:
                                col_name = col_info[0]
                                # col_info[1] is the DuckDB type object, convert to string
                                col_type = str(col_info[1]) if col_info[1] else 'VARCHAR'
                                columns.append((col_name, col_type))

                        # Send RowDescription with column metadata
                        self.sock.sendall(RowDescription.encode(columns))
                        portal['row_description_sent'] = True
                        portal['described_columns'] = len(columns)  # Track for Execute validation

                    except Exception as desc_err:
                        # If DuckDB can't parse the query, try to extract columns from the SQL text
                        # This prevents "Received resultset tuples, but no field structure" errors
                        self._runtime_log(
                            "WARN",
                            f"Could not describe portal via DuckDB: {str(desc_err)[:200]}",
                            event="describe_duckdb_failed",
                            error_type=type(desc_err).__name__,
                        )

                        # For SELECT queries, try to infer columns from the query text
                        if query_upper.strip().startswith('SELECT'):
                            extracted_cols = self._expected_result_columns(query)
                            if extracted_cols:
                                # Send RowDescription with inferred columns (all as VARCHAR)
                                columns = [(c, 'VARCHAR') for c in extracted_cols]
                                self.sock.sendall(RowDescription.encode(columns))
                                portal['row_description_sent'] = True
                                portal['described_columns'] = len(columns)  # Track for Execute validation
                            else:
                                # Can't infer columns - send NoData as last resort
                                # This may cause issues but is better than crashing
                                self.sock.sendall(NoData.encode())
                                portal['row_description_sent'] = False
                        else:
                            # Non-SELECT queries don't return rows
                            self.sock.sendall(NoData.encode())
                            portal['row_description_sent'] = False

        except Exception as e:
            error_str = str(e)
            self._runtime_log(
                "ERROR",
                f"Describe error: {error_str[:500]}",
                event="pgwire_describe_error",
                error_type=type(e).__name__,
            )

            # Check if this is a "Table does not exist" error for a pg_catalog table
            import re
            missing_table_match = re.search(r"Table with name (\w+) does not exist", error_str, re.IGNORECASE)
            if missing_table_match:
                missing_table = missing_table_match.group(1).lower()
                known_missing = {
                    'pg_trigger', 'pg_rewrite', 'pg_policy', 'pg_policies', 'pg_rules',
                    'pg_operator', 'pg_opclass', 'pg_opfamily', 'pg_aggregate',
                    'pg_cast', 'pg_collation', 'pg_conversion', 'pg_range',  # pg_enum removed - DuckDB has it
                    'pg_extension', 'pg_language', 'pg_foreign_data_wrapper',
                    'pg_foreign_server', 'pg_foreign_table', 'pg_event_trigger',
                    'pg_publication', 'pg_subscription', 'pg_replication_slots',
                    'pg_locks', 'pg_stat_statements', 'pg_stat_user_tables',
                    'pg_stat_user_indexes', 'pg_statio_user_tables',
                    'pg_statistic', 'pg_statistic_ext', 'pg_inherits',
                    'pg_partitioned_table', 'pg_seclabel', 'pg_shseclabel',
                    'pg_ts_config', 'pg_ts_dict', 'pg_ts_parser', 'pg_ts_template',
                    'pg_am', 'pg_amop', 'pg_amproc', 'pg_roles', 'pg_auth_members',
                    'pg_hba_file_rules', 'pg_file_settings', 'pg_description',
                    'pg_shdescription', 'pg_stat_activity',
                }
                if missing_table in known_missing:
                    self._runtime_log(
                        "DEBUG",
                        f"Missing pg_catalog table '{missing_table}' in Describe - sending NoData",
                        event="pgwire_describe_missing_pg_catalog_table",
                        missing_table=missing_table,
                    )
                    # For Describe, we can just send NoData to indicate no columns
                    self.sock.sendall(NoData.encode())
                    return

            # In Extended Query Protocol, don't send ReadyForQuery - wait for Sync
            self.sock.sendall(ErrorResponse.encode('ERROR', f"Describe error: {str(e)}"))

    def _handle_execute(self, msg: dict):
        """
        Handle Execute message - execute a bound portal.

        Args:
            msg: Decoded Execute message {portal_name, max_rows}
        """
        portal_name = msg['portal_name']
        max_rows = msg['max_rows']

        self._runtime_log(
            "DEBUG",
            f"Execute portal '{portal_name or '(unnamed)'}' (max_rows={max_rows})",
            event="pgwire_execute",
            portal_name=portal_name,
            max_rows=max_rows,
        )

        # Initialize tracking variables (set properly once we have the portal)
        _query_id, _query_start_time, _caller_id = None, None, None
        # Ensure these exist for error handling/logging even if portal lookup fails.
        query = ""
        original_query = None
        statement_name = None
        is_catalog = False
        execute_start = None
        error: Exception | None = None

        try:
            # Get portal
            if portal_name not in self.portals:
                raise Exception(f"Portal '{portal_name}' does not exist")

            portal = self.portals[portal_name]
            query = portal['query']
            params = portal['params']
            original_query = portal.get('original_query')  # For SQL Trail detection
            statement_name = portal.get('statement_name')

            # Log every executed SQL statement (Extended Query Protocol).
            # Use original_query when available (before semantic/EXPLAIN rewrites).
            self.query_count += 1
            query_for_log = (original_query or query or "").strip()
            is_catalog = self._is_catalog_query(query_for_log.upper())
            self._runtime_log(
                "DEBUG" if is_catalog else "INFO",
                f"Query #{self.query_count}: {query_for_log[:200]}{'...' if len(query_for_log) > 200 else ''}",
                event="query_execute",
                query_count=self.query_count,
                portal_name=portal_name,
                statement_name=statement_name,
                is_catalog=is_catalog,
                query=query_for_log if len(query_for_log) <= 10_000 else (query_for_log[:10_000] + "..."),
                query_len=len(query_for_log),
                param_count=len(params),
            )
            import time
            execute_start = time.time()

            # Set up SQL Trail tracking if this is an LARS statement
            # Uses original_query (before rewriting) for accurate detection
            _query_id, _query_start_time, _caller_id = self._setup_query_tracking(
                query, original_query=original_query
            )

            # Early termination detection for LIMIT-friendly semantic queries (Extended Query Protocol)
            # Must detect BEFORE execution since MEANS/similar operators become function calls after rewrite
            _early_term_enabled = False
            try:
                from lars.sql_tools.early_termination import (
                    set_early_termination_hint,
                    is_limit_friendly_query,
                )
                from lars.sql_tools.semantic_rewriter_v2 import _tokenize

                # Use original_query for detection (before rewriting)
                detect_query = original_query or query
                query_upper = detect_query.upper()

                # Quick check: does query contain scalar semantic operators?
                # BOOLEAN: MEANS, IMPLIES, CONTRADICTS, ALIGNS, MATCHES
                # DOUBLE: ABOUT (returns relevance score, still benefits from early termination)
                has_scalar_semantic = any(op in query_upper for op in [
                    'MEANS', 'ABOUT', 'IMPLIES', 'CONTRADICTS', 'ALIGNS', 'MATCHES',
                ])

                if has_scalar_semantic and _caller_id:
                    tokens = _tokenize(detect_query)
                    is_friendly, limit_value, reason = is_limit_friendly_query(tokens)

                    if is_friendly and limit_value:
                        set_early_termination_hint(_caller_id, limit_value)
                        _early_term_enabled = True
                        self._runtime_log(
                            "DEBUG",
                            f"Early termination enabled: LIMIT {limit_value}",
                            event="early_termination",
                            caller_id=_caller_id,
                            limit=limit_value,
                        )
                    elif limit_value and reason:
                        self._runtime_log(
                            "DEBUG",
                            f"Early termination skipped: {reason}",
                            event="early_termination",
                            caller_id=_caller_id,
                            skipped_reason=reason,
                            limit=limit_value,
                        )
            except Exception as et_error:
                self._runtime_log(
                    "WARN",
                    f"Early termination check failed: {et_error}",
                    event="early_termination_error",
                )

            # Check if Describe already sent RowDescription
            # If so, Execute should NOT send RowDescription again
            row_desc_already_sent = portal.get('row_description_sent', False)
            send_row_desc = not row_desc_already_sent

            # Check if Describe cached a result for a missing pg_catalog table
            if 'missing_table_result' in portal:
                result_df = portal['missing_table_result']
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                self._runtime_log(
                    "DEBUG",
                    "Missing pg_catalog table - returning cached empty result",
                    event="cached_result",
                    kind="missing_pg_catalog_table",
                )
                return

            # Check if Describe cached a skill result (to avoid double execution)
            if 'skill_result' in portal:
                result_df = portal['skill_result']
                # Describe already sent RowDescription, so don't send again
                send_execute_results(self.sock, result_df, send_row_description=False)
                self._runtime_log(
                    "DEBUG",
                    f"Skill call - returning cached result ({len(result_df)} rows)",
                    event="cached_result",
                    kind="skill",
                    rows=len(result_df),
                )
                return

            # Check for special PostgreSQL functions and commands
            query_upper = query.upper().strip()

            # Empty query - send EmptyQueryResponse
            if not query_upper or query_upper.startswith('--'):
                self._runtime_log(
                    "DEBUG",
                    "Empty query - sending EmptyQueryResponse",
                    event="empty_query",
                )
                self.sock.sendall(EmptyQueryResponse.encode())
                return

            # SHOW commands - Handle via Extended Query
            if query_upper.startswith('SHOW '):
                self._runtime_log(
                    "DEBUG",
                    "SHOW command via Extended Query",
                    event="show_command",
                )
                # Handle SHOW and send results - skip RowDescription if Describe already sent it
                self._execute_show_and_send_extended(query, send_row_description=send_row_desc)
                return

            # BACKGROUND queries - Handle async execution via Extended Query
            # Check original_query since BACKGROUND prefix is stripped during rewriting
            if original_query:
                original_upper = original_query.upper().strip()
                if original_upper.startswith('BACKGROUND'):
                    from ..sql_tools.sql_directives import parse_sql_directives
                    directive, inner_sql = parse_sql_directives(original_query)
                    if directive and directive.directive_type == 'BACKGROUND':
                        self._runtime_log(
                            "DEBUG",
                            "BACKGROUND directive via Extended Query",
                            event="background_query",
                        )
                        # Describe Portal already sent RowDescription with job metadata columns,
                        # so Execute only sends DataRows (no RowDescription)
                        self._handle_background_query(inner_sql, extended_query_mode=True, send_row_description=False)
                        return

            # Legacy ANALYZE 'prompt' SELECT ... directive removed.
            # Check original_query since directive prefixes are stripped during rewriting.
            if original_query:
                original_upper = original_query.upper().strip()
                if original_upper.startswith('ANALYZE'):
                    from ..sql_tools.sql_directives import parse_sql_directives
                    directive, _ = parse_sql_directives(original_query)
                    if directive and directive.directive_type == 'ANALYZE':
                        raise Exception(
                            "ANALYZE 'prompt' SELECT ... has been removed. Use THEN ANALYZE instead. "
                            "Example: SELECT * FROM t THEN ANALYZE 'what are the trends?'"
                        )

            # WATCH commands - Handle reactive SQL subscriptions via Extended Query
            from ..sql_tools.sql_directives import is_watch_command
            if is_watch_command(query):
                self._runtime_log(
                    "DEBUG",
                    "WATCH command via Extended Query",
                    event="watch_command",
                )
                self._handle_watch_command(query, extended_query_mode=True, send_row_description=send_row_desc)
                return

            # EXPLAIN queries - must be checked BEFORE pipeline syntax
            # because EXPLAIN SELECT ... THEN PIVOT would otherwise be intercepted by pipeline handler
            # IMPORTANT: Check original_query (not rewritten query) because rewrite_lars_syntax()
            # transforms EXPLAIN into SELECT '...' AS query_plan during Parse phase
            import re
            explain_check_query = (original_query or query).upper().strip()
            if re.match(r'^EXPLAIN[\s(]', explain_check_query):
                self._runtime_log(
                    "DEBUG",
                    "EXPLAIN via Extended Query",
                    event="explain_query",
                )
                # Use original_query for explain handling (has EXPLAIN prefix)
                self._handle_explain_query_extended(original_query or query, send_row_description=send_row_desc)
                return

            # PIPELINE syntax (THEN/INTO) - Handle post-query result processing via Extended Query
            # Check if Describe already executed the pipeline and cached the result
            if 'pipeline_result' in portal:
                self._runtime_log(
                    "DEBUG",
                    "PIPELINE cached result (from Describe)",
                    event="pipeline_cached_result",
                )
                cached_df = portal['pipeline_result']
                # Describe already sent RowDescription, so don't send again
                send_execute_results(self.sock, cached_df, send_row_description=False)
                return

            # Use original_query for pipeline detection to avoid conflicts with semantic rewriters
            from ..sql_tools.pipeline_parser import has_pipeline_syntax, parse_pipeline_syntax
            original_query = portal.get('original_query') or query

            # Pre-process CANVAS syntax - rewrites to SQL with THEN RENDER_CANVAS(...)
            from ..sql_tools.canvas_rewriter import has_canvas_syntax, rewrite_canvas_syntax
            if has_canvas_syntax(original_query):
                original_query = rewrite_canvas_syntax(original_query)
                self._runtime_log(
                    "DEBUG",
                    "CANVAS syntax rewritten (Execute)",
                    event="canvas_rewrite",
                )

            if has_pipeline_syntax(original_query):
                pipeline = parse_pipeline_syntax(original_query)
                if pipeline and pipeline.stages:
                    self._runtime_log(
                        "DEBUG",
                        "PIPELINE syntax via Extended Query",
                        event="pipeline_query",
                    )
                    self._handle_pipeline_query(pipeline, original_query, extended_query_mode=True, send_row_description=send_row_desc)
                    return

            # pg_get_keywords() - Return empty result
            if 'PG_GET_KEYWORDS' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "pg_get_keywords() - returning empty",
                    event="pg_get_keywords",
                )
                import pandas as pd
                send_execute_results(self.sock, pd.DataFrame(columns=['word']), send_row_description=send_row_desc)
                return

            # current_schemas() - Return PostgreSQL array format (DuckDB returns scalar)
            # This is critical for DataGrip which parses the array to build search path
            if 'CURRENT_SCHEMAS(' in query_upper and 'PG_NAMESPACE' not in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "current_schemas() - returning PostgreSQL array format",
                    event="current_schemas",
                )
                import pandas as pd
                cols = self._expected_result_columns(query)
                if cols:
                    row = {}
                    for c in cols:
                        key = c.strip('"').lower()
                        if key in {'current_database', 'current_database()', 'a'}:
                            row[c] = self.database_name
                        elif key in {'current_schemas', 'b'}:  # 'b' is common alias in DataGrip queries
                            row[c] = '{main}'  # PostgreSQL array format
                        elif key in {'current_schema', 'current_schema()'}:
                            row[c] = 'main'
                        elif key in {'current_user', 'session_user'}:
                            row[c] = self.user_name
                        else:
                            row[c] = None
                    result_df = pd.DataFrame({c: [row[c]] for c in cols})
                else:
                    result_df = pd.DataFrame({'current_schemas': ['{main}']})
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_namespace queries for schema browser (Extended Query mode)
            # IMPORTANT: Must return consistent columns with Describe Portal handler
            # DataGrip expects: id, state_number, name, description, owner
            # BUT: ACL queries like 'SELECT object_id, acl FROM pg_namespace' should not use this handler
            is_pg_class_main = 'FROM PG_CATALOG.PG_CLASS' in query_upper or 'FROM PG_CLASS' in query_upper
            is_pg_namespace_main = ('FROM PG_CATALOG.PG_NAMESPACE' in query_upper or 'FROM PG_NAMESPACE' in query_upper)
            # ACL queries select acl/nspacl columns - should NOT use schema browser handler
            # Check SELECT clause for ACL columns (before FROM to avoid matching 'PG_NAMESPACE')
            select_clause = query_upper.split('FROM')[0] if 'FROM' in query_upper else ''
            is_acl_query = 'NSPACL' in select_clause or ' ACL' in select_clause or ',ACL' in select_clause or '.ACL' in select_clause

            if is_pg_namespace_main and not is_pg_class_main and 'FROM' in query_upper and not is_acl_query:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_namespace query for schema browser (Extended)",
                    event="catalog_pg_namespace_handler",
                )
                import pandas as pd
                try:
                    # Get the columns that Describe promised (or use defaults)
                    expected_cols = self._expected_result_columns(query) or ['id', 'state_number', 'name', 'description', 'owner']

                    # Expand '*' or 'n.*' to actual pg_namespace columns
                    # DuckDB's pg_namespace has: oid, nspname, nspowner, nspacl
                    pg_namespace_cols = ['oid', 'nspname', 'nspowner', 'nspacl']
                    expanded_cols = []
                    for col in expected_cols:
                        if col == '*' or col.endswith('.*'):
                            expanded_cols.extend(pg_namespace_cols)
                        else:
                            expanded_cols.append(col)
                    # Deduplicate while preserving order (pandas can't handle duplicate column names)
                    seen = set()
                    unique_cols = []
                    for col in expanded_cols:
                        if col not in seen:
                            seen.add(col)
                            unique_cols.append(col)
                    expected_cols = unique_cols
                    self._runtime_log(
                        "DEBUG",
                        f"pg_namespace expected columns: {len(expected_cols)}",
                        event="catalog_pg_namespace_expected_cols",
                        expected_cols=expected_cols[:200],
                        expected_col_count=len(expected_cols),
                    )

                    # Get schema data from DuckDB's pg_catalog
                    schema_rows = self.duckdb_conn.execute(
                        "SELECT oid, nspname, nspowner FROM pg_catalog.pg_namespace"
                    ).fetchdf()

                    # Build result with columns matching what Describe sent
                    # Map our data to the expected column names
                    result_data = []
                    for _, row in schema_rows.iterrows():
                        row_dict = {}
                        for col in expected_cols:
                            col_lower = col.lower()
                            if col_lower in ('id', 'oid'):
                                row_dict[col] = int(row['oid'])
                            elif col_lower in ('state_number', 'xmin'):
                                row_dict[col] = 0
                            elif col_lower in ('name', 'nspname', 'schema_name'):
                                row_dict[col] = str(row['nspname'])
                            elif col_lower == 'description':
                                row_dict[col] = None
                            elif col_lower in ('owner', 'nspowner'):
                                row_dict[col] = int(row['nspowner']) if 'nspowner' in row else self.user_name
                            elif col_lower == 'nspacl':
                                row_dict[col] = None  # ACL not supported
                            else:
                                row_dict[col] = None
                        result_data.append(row_dict)

                    result_df = pd.DataFrame(result_data, columns=expected_cols)

                    # Find the name column for deduplication and sorting
                    name_col = next((c for c in expected_cols if c.lower() in ('name', 'nspname', 'schema_name')), None)

                    # Ensure pg_catalog + information_schema appear (only if we have a name column)
                    if name_col:
                        existing = set(result_df[name_col].tolist()) if len(result_df) > 0 else set()
                    else:
                        existing = set()  # No name column - skip deduplication

                    for schema_name, schema_id, desc in [('pg_catalog', 11, 'System catalog'), ('information_schema', 12, 'Information schema')]:
                        if schema_name not in existing:
                            new_row = {}
                            for col in expected_cols:
                                col_lower = col.lower()
                                if col_lower in ('id', 'oid'):
                                    new_row[col] = schema_id
                                elif col_lower in ('state_number', 'xmin'):
                                    new_row[col] = 0
                                elif col_lower in ('name', 'nspname', 'schema_name'):
                                    new_row[col] = schema_name
                                elif col_lower == 'description':
                                    new_row[col] = desc
                                elif col_lower in ('owner', 'nspowner'):
                                    new_row[col] = self.user_name
                                elif col_lower == 'nspacl':
                                    new_row[col] = None  # ACL not supported
                                else:
                                    new_row[col] = None
                            result_df = pd.concat([result_df, pd.DataFrame([new_row])], ignore_index=True)

                    # Sort by name column if available
                    if name_col and name_col in result_df.columns:
                        result_df = result_df.sort_values(name_col).reset_index(drop=True)

                    try:
                        top_schemas: list[str] = []
                        if name_col and name_col in result_df.columns:
                            top_schemas = [str(v) for v in result_df[name_col].head(10).tolist()]
                        elif len(result_df.columns) > 0:
                            top_schemas = [str(v) for v in result_df.iloc[:, 0].head(10).tolist()]
                        self._runtime_log(
                            "DEBUG",
                            f"pg_namespace schemas found: {len(result_df)}",
                            event="catalog_pg_namespace_schemas",
                            schema_count=len(result_df),
                            sample=top_schemas,
                        )
                    except Exception:
                        pass

                    # Validate column count before sending
                    actual_send_row_desc = send_row_desc
                    if not send_row_desc and portal_name in self.portals:
                        described_col_count = self.portals[portal_name].get('described_columns')
                        if described_col_count is not None and described_col_count != len(expected_cols):
                            self._runtime_log(
                                "WARN",
                                f"pg_namespace column mismatch: described {described_col_count}, returning {len(expected_cols)}",
                                event="catalog_column_mismatch",
                                table="pg_namespace",
                                described_col_count=described_col_count,
                                returning_col_count=len(expected_cols),
                            )
                            actual_send_row_desc = True
                    send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)
                    self._runtime_log(
                        "DEBUG",
                        f"pg_namespace handled ({len(result_df)} schemas)",
                        event="catalog_pg_namespace_complete",
                        schema_count=len(result_df),
                    )
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"Could not handle pg_namespace: {e}",
                        event="catalog_pg_namespace_failed",
                        error_type=type(e).__name__,
                    )
                    # Don't fall through - return empty result with expected columns to prevent mismatch
                    import pandas as pd
                    expected_cols = self._expected_result_columns(query) or ['id', 'state_number', 'name', 'description', 'owner']
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    self._runtime_log(
                        "DEBUG",
                        f"pg_namespace fallback (empty with {len(expected_cols)} cols)",
                        event="catalog_pg_namespace_fallback",
                        col_count=len(expected_cols),
                    )
                    return

            # pg_class queries with c.* - Use the bypass logic
            if 'FROM PG_CATALOG.PG_CLASS' in query_upper and 'C.*' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Detected pg_class c.* query - using safe column bypass",
                    event="catalog_pg_class_bypass",
                )
                try:
                    # Extract WHERE clause from original query
                    import re
                    where_match = re.search(r'\bWHERE\b(.+?)(?:ORDER BY|LIMIT|$)', query, re.IGNORECASE | re.DOTALL)
                    if where_match:
                        where_clause = where_match.group(1).strip()
                        # Strip type casts from WHERE clause too
                        where_clause = where_clause.replace('::int8', '').replace('::int4', '').replace('::int2', '')
                        where_clause = where_clause.replace('::text', '').replace('::varchar', '')

                        # Replace table alias (DBeaver might use 'pc', 'c', 'cl', etc.)
                        # Our bypass always uses 'c', so replace all variations
                        where_clause = re.sub(r'\b(pc|cl|cls|pg_class)\s*\.', 'c.', where_clause, flags=re.IGNORECASE)

                        # Convert $1, $2 to ? for DuckDB
                        for i in range(len(params), 0, -1):
                            where_clause = where_clause.replace(f'${i}', '?')
                    else:
                        where_clause = "c.relkind NOT IN ('i', 'I', 'c')"

                    self._runtime_log(
                        "DEBUG",
                        "pg_class bypass WHERE parsed",
                        event="catalog_pg_class_bypass_where",
                        where_preview=where_clause[:500],
                    )

                    # Use information_schema.tables joined with pg_namespace for proper OIDs
                    # DuckDB's pg_catalog.pg_class is EMPTY - doesn't contain user tables
                    # We synthesize pg_class rows from information_schema.tables

                    # Transform WHERE clause column references (handle both prefixed c.col and unprefixed col)
                    transformed_where = where_clause
                    # relnamespace -> n.oid (with or without c. prefix)
                    transformed_where = re.sub(r'\b(c\.)?relnamespace\b', 'n.oid', transformed_where, flags=re.IGNORECASE)
                    # relkind -> CASE expression (with or without c. prefix)
                    transformed_where = re.sub(r'\b(c\.)?relkind\b', "(CASE t.table_type WHEN 'BASE TABLE' THEN 'r' WHEN 'VIEW' THEN 'v' ELSE 'r' END)", transformed_where, flags=re.IGNORECASE)
                    # relname -> t.table_name (with or without c. prefix)
                    transformed_where = re.sub(r'\b(c\.)?relname\b', 't.table_name', transformed_where, flags=re.IGNORECASE)

                    self._runtime_log(
                        "DEBUG",
                        "pg_class bypass WHERE transformed",
                        event="catalog_pg_class_bypass_where_transformed",
                        where_preview=transformed_where[:500],
                    )

                    safe_query = f"""
                        SELECT
                            ABS(hash(t.table_schema || '.' || t.table_name) % 2147483647)::INTEGER as oid,
                            t.table_name as relname,
                            COALESCE(n.oid, 0)::INTEGER as relnamespace,
                            CASE t.table_type
                                WHEN 'BASE TABLE' THEN 'r'
                                WHEN 'VIEW' THEN 'v'
                                WHEN 'LOCAL TEMPORARY' THEN 'r'
                                ELSE 'r'
                            END as relkind,
                            0::INTEGER as relowner,
                            false as relhasindex,
                            false as relrowsecurity,
                            false as relforcerowsecurity,
                            false as relispartition,
                            ''::VARCHAR as description,
                            ''::VARCHAR as partition_expr,
                            ''::VARCHAR as partition_key
                        FROM information_schema.tables t
                        LEFT JOIN pg_catalog.pg_namespace n ON n.nspname = t.table_schema
                        WHERE {transformed_where}
                        LIMIT 1000
                    """
                    result_df = self.duckdb_conn.execute(safe_query, params).fetchdf()

                    # Get expected columns from the original query and project result to match
                    expected_cols = self._expected_result_columns(query)
                    if expected_cols and portal_name in self.portals:
                        described_col_count = self.portals[portal_name].get('described_columns')
                        if described_col_count and described_col_count != len(result_df.columns):
                            # Need to project our result to match expected columns
                            # Map pg_class column names to our synthetic columns
                            import pandas as pd

                            # pg_class columns that c.* expands to (in PostgreSQL order)
                            pg_class_star_cols = [
                                'relname', 'relnamespace', 'reltype', 'reloftype', 'relowner',
                                'relam', 'relfilenode', 'reltablespace', 'relpages', 'reltuples',
                                'relallvisible', 'reltoastrelid', 'relhasindex', 'relisshared',
                                'relpersistence', 'relkind', 'relnatts', 'relchecks', 'relhasrules',
                                'relhastriggers', 'relhassubclass', 'relrowsecurity', 'relforcerowsecurity',
                                'relispopulated', 'relreplident', 'relispartition', 'relrewrite',
                                'relfrozenxid', 'relminmxid', 'relacl', 'reloptions', 'relpartbound'
                            ]

                            col_map = {
                                'oid': 'oid',
                                'relname': 'relname',
                                'relnamespace': 'relnamespace',
                                'relkind': 'relkind',
                                'relowner': 'relowner',
                                'relhasindex': 'relhasindex',
                                'relrowsecurity': 'relrowsecurity',
                                'relforcerowsecurity': 'relforcerowsecurity',
                                'relispartition': 'relispartition',
                                'description': 'description',
                                'partition_expr': 'partition_expr',
                                'partition_key': 'partition_key',
                            }

                            # Expand * or c.* to actual pg_class columns
                            expanded_cols = []
                            for col in expected_cols:
                                if col == '*' or col.lower().endswith('.*'):
                                    expanded_cols.extend(pg_class_star_cols)
                                else:
                                    expanded_cols.append(col)

                            projected_data = {}
                            for col in expanded_cols:
                                # Strip alias prefix (c., n., etc.)
                                clean_col = re.sub(r'^[a-z]+\.', '', col.lower())
                                if clean_col in col_map and col_map[clean_col] in result_df.columns:
                                    projected_data[col] = result_df[col_map[clean_col]].tolist()
                                else:
                                    # Column not in our synthetic data - fill with NULL/default
                                    projected_data[col] = [None] * len(result_df)
                            result_df = pd.DataFrame(projected_data)
                            self._runtime_log(
                                "DEBUG",
                                f"pg_class bypass projected to {len(expanded_cols)} columns",
                                event="catalog_pg_class_bypass_projected",
                                projected_col_count=len(expanded_cols),
                                expected_col_count=len(expected_cols),
                            )

                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    self._runtime_log(
                        "DEBUG",
                        f"pg_class bypass executed ({len(result_df)} rows × {len(result_df.columns)} cols)",
                        event="catalog_pg_class_bypass_complete",
                        row_count=len(result_df),
                        col_count=len(result_df.columns),
                    )
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"pg_class bypass failed: {str(e)[:200]}",
                        event="catalog_pg_class_bypass_failed",
                        error_type=type(e).__name__,
                    )
                    # Don't fall through - return empty result with expected columns
                    import pandas as pd
                    expected_cols = self._expected_result_columns(query) or ['relkind', 'relname', 'oid']
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    self._runtime_log(
                        "DEBUG",
                        f"pg_class bypass fallback (empty with {len(expected_cols)} cols)",
                        event="catalog_pg_class_bypass_fallback",
                        col_count=len(expected_cols),
                    )
                    return

            # pg_attribute queries with a.* - Use information_schema.columns
            if 'FROM PG_CATALOG.PG_ATTRIBUTE' in query_upper and 'A.*' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Detected pg_attribute a.* query - using safe column bypass",
                    event="catalog_pg_attribute_bypass",
                )
                try:
                    # Extract WHERE clause
                    import re
                    import pandas as pd
                    where_match = re.search(r'\bWHERE\b(.+?)(?:ORDER BY|LIMIT|$)', query, re.IGNORECASE | re.DOTALL)
                    if where_match:
                        where_clause = where_match.group(1).strip()
                        # Convert $1, $2 to ?
                        for i in range(len(params), 0, -1):
                            where_clause = where_clause.replace(f'${i}', '?')
                    else:
                        where_clause = "1=1"

                    self._runtime_log(
                        "DEBUG",
                        "pg_attribute bypass WHERE parsed",
                        event="catalog_pg_attribute_bypass_where",
                        where_preview=where_clause[:500],
                    )

                    # Transform WHERE clause: a.attrelid -> table OID, a.attnum -> ordinal_position
                    # Also handle c.oid and c.relkind from pg_class join
                    transformed_where = where_clause
                    # pg_attribute columns
                    transformed_where = re.sub(r'\b(a\.)?attrelid\b', 'ABS(hash(c.table_schema || \'.\' || c.table_name) % 2147483647)', transformed_where, flags=re.IGNORECASE)
                    transformed_where = re.sub(r'\b(a\.)?attnum\b', 'c.ordinal_position', transformed_where, flags=re.IGNORECASE)
                    transformed_where = re.sub(r'\b(a\.)?attisdropped\b', 'false', transformed_where, flags=re.IGNORECASE)
                    # pg_class columns (from JOIN)
                    transformed_where = re.sub(r'\bc\.oid\b', 'ABS(hash(c.table_schema || \'.\' || c.table_name) % 2147483647)', transformed_where, flags=re.IGNORECASE)
                    transformed_where = re.sub(r'\bc\.relkind\b', "'r'", transformed_where, flags=re.IGNORECASE)  # Treat all as regular tables
                    # Remove relkind NOT IN filters since we don't have that info
                    transformed_where = re.sub(r"\s+AND\s+'r'\s+not\s+in\s+\([^)]+\)", '', transformed_where, flags=re.IGNORECASE)

                    self._runtime_log(
                        "DEBUG",
                        "pg_attribute bypass WHERE transformed",
                        event="catalog_pg_attribute_bypass_where_transformed",
                        where_preview=transformed_where[:500],
                    )

                    # Synthesize pg_attribute data from information_schema.columns
                    # Map DuckDB types to PostgreSQL type OIDs
                    safe_query = f"""
                        SELECT
                            c.table_name as relname,
                            c.column_name as attname,
                            c.ordinal_position::INTEGER as attnum,
                            CASE UPPER(c.data_type)
                                WHEN 'INTEGER' THEN 23
                                WHEN 'INT' THEN 23
                                WHEN 'INT4' THEN 23
                                WHEN 'BIGINT' THEN 20
                                WHEN 'INT8' THEN 20
                                WHEN 'SMALLINT' THEN 21
                                WHEN 'INT2' THEN 21
                                WHEN 'TINYINT' THEN 21
                                WHEN 'BOOLEAN' THEN 16
                                WHEN 'BOOL' THEN 16
                                WHEN 'DOUBLE' THEN 701
                                WHEN 'DOUBLE PRECISION' THEN 701
                                WHEN 'FLOAT8' THEN 701
                                WHEN 'REAL' THEN 700
                                WHEN 'FLOAT4' THEN 700
                                WHEN 'FLOAT' THEN 701
                                WHEN 'VARCHAR' THEN 1043
                                WHEN 'CHARACTER VARYING' THEN 1043
                                WHEN 'TEXT' THEN 25
                                WHEN 'DATE' THEN 1082
                                WHEN 'TIMESTAMP' THEN 1114
                                WHEN 'TIMESTAMP WITHOUT TIME ZONE' THEN 1114
                                WHEN 'TIMESTAMP WITH TIME ZONE' THEN 1184
                                WHEN 'TIMESTAMPTZ' THEN 1184
                                WHEN 'TIME' THEN 1083
                                WHEN 'TIME WITHOUT TIME ZONE' THEN 1083
                                WHEN 'INTERVAL' THEN 1186
                                WHEN 'NUMERIC' THEN 1700
                                WHEN 'DECIMAL' THEN 1700
                                WHEN 'UUID' THEN 2950
                                WHEN 'JSON' THEN 114
                                WHEN 'JSONB' THEN 3802
                                WHEN 'BYTEA' THEN 17
                                WHEN 'BLOB' THEN 17
                                ELSE 25  -- Default to TEXT
                            END::INTEGER as atttypid,
                            CASE WHEN c.is_nullable = 'NO' THEN true ELSE false END as attnotnull,
                            CASE UPPER(c.data_type)
                                WHEN 'INTEGER' THEN 4
                                WHEN 'BIGINT' THEN 8
                                WHEN 'SMALLINT' THEN 2
                                WHEN 'BOOLEAN' THEN 1
                                WHEN 'DOUBLE' THEN 8
                                WHEN 'REAL' THEN 4
                                ELSE -1
                            END::INTEGER as attlen,
                            ABS(hash(c.table_schema || '.' || c.table_name) % 2147483647)::INTEGER as attrelid,
                            c.column_default as def_value,
                            ''::VARCHAR as description,
                            0::INTEGER as objid,
                            c.data_type as data_type
                        FROM information_schema.columns c
                        WHERE {transformed_where}
                        ORDER BY c.ordinal_position
                        LIMIT 1000
                    """
                    result_df = self.duckdb_conn.execute(safe_query, params).fetchdf()

                    # Get expected columns and project result to match
                    expected_cols = self._expected_result_columns(query)
                    if expected_cols and portal_name in self.portals:
                        described_col_count = self.portals[portal_name].get('described_columns')
                        if described_col_count and described_col_count != len(result_df.columns):
                            # pg_attribute columns that a.* expands to
                            pg_attribute_star_cols = [
                                'attrelid', 'attname', 'atttypid', 'attstattarget', 'attlen',
                                'attnum', 'attndims', 'attcacheoff', 'atttypmod', 'attbyval',
                                'attstorage', 'attalign', 'attnotnull', 'atthasdef', 'atthasmissing',
                                'attidentity', 'attgenerated', 'attisdropped', 'attislocal',
                                'attinhcount', 'attcollation', 'attacl', 'attoptions', 'attfdwoptions',
                                'attmissingval'
                            ]
                            col_map = {
                                'relname': 'relname', 'attname': 'attname', 'attnum': 'attnum',
                                'atttypid': 'atttypid', 'attnotnull': 'attnotnull', 'attlen': 'attlen',
                                'attrelid': 'attrelid', 'def_value': 'def_value', 'description': 'description',
                                'objid': 'objid', 'data_type': 'data_type',
                            }
                            # Expand * or a.*
                            expanded_cols = []
                            for col in expected_cols:
                                if col == '*' or col.lower().endswith('.*'):
                                    expanded_cols.extend(pg_attribute_star_cols)
                                else:
                                    expanded_cols.append(col)
                            projected_data = {}
                            for col in expanded_cols:
                                clean_col = re.sub(r'^[a-z]+\.', '', col.lower())
                                if clean_col in col_map and col_map[clean_col] in result_df.columns:
                                    projected_data[col] = result_df[col_map[clean_col]].tolist()
                                else:
                                    projected_data[col] = [None] * len(result_df)
                            result_df = pd.DataFrame(projected_data)
                            self._runtime_log(
                                "DEBUG",
                                f"pg_attribute bypass projected to {len(expanded_cols)} columns",
                                event="catalog_pg_attribute_bypass_projected",
                                projected_col_count=len(expanded_cols),
                                expected_col_count=len(expected_cols),
                            )

                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    self._runtime_log(
                        "DEBUG",
                        f"pg_attribute bypass executed ({len(result_df)} rows × {len(result_df.columns)} cols)",
                        event="catalog_pg_attribute_bypass_complete",
                        row_count=len(result_df),
                        col_count=len(result_df.columns),
                    )
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"pg_attribute bypass failed: {str(e)[:200]}",
                        event="catalog_pg_attribute_bypass_failed",
                        error_type=type(e).__name__,
                    )
                    if os.environ.get("LARS_PG_TRACEBACK", "0").strip().lower() in ("1", "true", "yes", "on"):
                        import traceback
                        traceback.print_exc()
                    # Don't fall through - return empty result with expected columns
                    import pandas as pd
                    expected_cols = self._expected_result_columns(query) or ['relname', 'attname', 'attnum']
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    self._runtime_log(
                        "DEBUG",
                        f"pg_attribute bypass fallback (empty with {len(expected_cols)} cols)",
                        event="catalog_pg_attribute_bypass_fallback",
                        col_count=len(expected_cols),
                    )
                    return

            # Strip regclass/regtype/regproc casts from ANY other pg_catalog query
            if 'PG_CATALOG' in query_upper and ('::REGCLASS' in query_upper or '::REGTYPE' in query_upper or '::REGPROC' in query_upper or '::OID' in query_upper):
                self._runtime_log(
                    "DEBUG",
                    "Detected pg_catalog query with type casts - stripping",
                    event="catalog_type_cast_strip",
                )

                # FIRST: Rewrite pg_inherits subqueries BEFORE stripping type casts
                # This prevents malformed queries when type casts are removed from complex subqueries
                clean_query = self._rewrite_pg_inherits_subqueries(query)
                clean_query = self._rewrite_pg_get_expr_calls(clean_query)
                # Strip all PostgreSQL type casts
                for cast in ['::regclass', '::regtype', '::regproc', '::oid', '::REGCLASS', '::REGTYPE', '::REGPROC', '::OID']:
                    clean_query = clean_query.replace(cast, '')

                # Convert placeholders
                duckdb_query = clean_query
                for i in range(len(params), 0, -1):
                    duckdb_query = duckdb_query.replace(f'${i}', '?')
                duckdb_query = self._rewrite_pg_catalog_function_calls(duckdb_query)
                duckdb_query = self._rewrite_information_schema_catalog_filters(duckdb_query)
                duckdb_query = self._rewrite_pg_system_column_refs(duckdb_query)
                duckdb_query = self._rewrite_missing_table_joins(duckdb_query)
                # NOTE: UNION stripping disabled - causes parameter count mismatches
                # Rely on catch-all error handlers instead
                # duckdb_query = self._strip_union_parts_with_missing_tables(duckdb_query)
                duckdb_query = self._rewrite_pg_inherits_subqueries(duckdb_query)
                duckdb_query = self._rewrite_pg_get_expr_calls(duckdb_query)
                duckdb_query = self._rewrite_missing_pg_database_columns(duckdb_query)

                try:
                    result_df = self.duckdb_conn.execute(duckdb_query, params).fetchdf()
                    # Column count validation - critical for preventing ArrayIndexOutOfBoundsException
                    actual_send_row_desc = send_row_desc
                    if not send_row_desc and portal_name in self.portals:
                        described_col_count = self.portals[portal_name].get('described_columns')
                        actual_col_count = len(result_df.columns)
                        if described_col_count is not None and described_col_count != actual_col_count:
                            self._runtime_log(
                                "WARN",
                                "COLUMN MISMATCH (type cast stripping)",
                                event="catalog_column_mismatch",
                                described_col_count=described_col_count,
                                actual_col_count=actual_col_count,
                                actual_columns=list(result_df.columns)[:200],
                            )
                            actual_send_row_desc = True  # Resend RowDescription to fix mismatch
                    send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)
                    self._runtime_log(
                        "DEBUG",
                        f"Catalog query executed after stripping type casts ({len(result_df)} rows × {len(result_df.columns)} cols)",
                        event="catalog_type_cast_strip_complete",
                        row_count=len(result_df),
                        col_count=len(result_df.columns),
                    )
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"Catalog query failed after stripping type casts: {str(e)[:200]}",
                        event="catalog_type_cast_strip_failed",
                        error_type=type(e).__name__,
                    )
                    # ALWAYS return empty result - don't fall through to avoid cascading errors
                    expected_cols = self._expected_result_columns(query)
                    if not expected_cols:
                        # Default columns if we can't infer
                        expected_cols = ['result']
                    import pandas as pd
                    # Critical: validate column count matches what Describe sent
                    actual_send_row_desc = send_row_desc
                    if not send_row_desc and portal_name in self.portals:
                        described_col_count = self.portals[portal_name].get('described_columns')
                        if described_col_count is not None and described_col_count != len(expected_cols):
                            self._runtime_log(
                                "WARN",
                                "COLUMN MISMATCH in fallback (type cast stripping)",
                                event="catalog_column_mismatch",
                                described_col_count=described_col_count,
                                inferred_col_count=len(expected_cols),
                            )
                            # Adjust columns to match described count
                            if described_col_count > len(expected_cols):
                                # Add placeholder columns
                                for i in range(len(expected_cols), described_col_count):
                                    expected_cols.append(f'col_{i+1}')
                            else:
                                # Truncate to described count
                                expected_cols = expected_cols[:described_col_count]
                            self._runtime_log(
                                "DEBUG",
                                f"Fallback columns adjusted to described count: {len(expected_cols)}",
                                event="catalog_column_mismatch_adjusted",
                                adjusted_col_count=len(expected_cols),
                            )
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)
                    self._runtime_log(
                        "DEBUG",
                        f"Type cast query fallback (empty with {len(expected_cols)} cols)",
                        event="catalog_type_cast_strip_fallback",
                        col_count=len(expected_cols),
                    )
                    return

            # Check if this is a SET or RESET command
            if query_upper.startswith('SET ') or query_upper.startswith('RESET '):
                # Handle SET commands via Extended Query Protocol
                self._runtime_log(
                    "DEBUG",
                    "SET/RESET via Extended Query",
                    event="set_reset",
                )
                self._execute_set_command(query)
                # Send CommandComplete (SET commands don't return rows!)
                self.sock.sendall(CommandComplete.encode('SET'))
                return

            # Check if this is a transaction command
            if query_upper in ['BEGIN', 'BEGIN TRANSACTION', 'BEGIN WORK', 'START TRANSACTION']:
                self._runtime_log(
                    "DEBUG",
                    "BEGIN via Extended Query",
                    event="transaction",
                    command="BEGIN",
                )
                self._handle_begin(send_ready=False)  # Extended Query - wait for Sync
                return
            elif query_upper in ['COMMIT', 'COMMIT TRANSACTION', 'COMMIT WORK', 'END', 'END TRANSACTION']:
                self._runtime_log(
                    "DEBUG",
                    "COMMIT via Extended Query",
                    event="transaction",
                    command="COMMIT",
                )
                self._handle_commit(send_ready=False)  # Extended Query - wait for Sync
                return
            elif query_upper in ['ROLLBACK', 'ROLLBACK TRANSACTION', 'ROLLBACK WORK', 'ABORT']:
                self._runtime_log(
                    "DEBUG",
                    "ROLLBACK via Extended Query",
                    event="transaction",
                    command="ROLLBACK",
                )
                self._handle_rollback(send_ready=False)  # Extended Query - wait for Sync
                return

            # DataGrip: pg_class "table browser" UNION query (object listing across schemas)
            # This UNION includes branches over tables DuckDB doesn't implement (pg_collation, pg_operator, etc.),
            # but DataGrip still expects rows from pg_class/pg_type/pg_proc. Build those parts explicitly.
            if self._is_datagrip_pg_class_table_browser_union(query_upper):
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_class table browser UNION (DataGrip)",
                    event="catalog_datagrip_pg_class_union",
                )
                result_df = self._build_datagrip_pg_class_table_browser_union_result(query, params)
                self._validate_custom_handler_columns(portal_name, len(result_df.columns), 'pg_class table browser UNION')
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                self._runtime_log(
                    "DEBUG",
                    f"pg_class table browser UNION handled ({len(result_df)} rows × {len(result_df.columns)} cols)",
                    event="catalog_datagrip_pg_class_union_complete",
                    row_count=len(result_df),
                    col_count=len(result_df.columns),
                )
                return

            # Convert PostgreSQL placeholders ($1, $2, ...) to DuckDB placeholders (?)
            # Must replace in reverse order to avoid conflicts ($10 before $1)
            duckdb_query = query
            for i in range(len(params), 0, -1):
                duckdb_query = duckdb_query.replace(f'${i}', '?')

            # Strip pg_catalog. prefix for function calls (DuckDB doesn't support qualified funcs)
            duckdb_query = self._rewrite_pg_catalog_function_calls(duckdb_query)
            duckdb_query = self._rewrite_information_schema_catalog_filters(duckdb_query)
            duckdb_query = self._rewrite_pg_system_column_refs(duckdb_query)
            duckdb_query = self._rewrite_missing_table_joins(duckdb_query)
            # NOTE: UNION stripping disabled - causes parameter count mismatches
            # duckdb_query = self._strip_union_parts_with_missing_tables(duckdb_query)
            duckdb_query = self._rewrite_pg_inherits_subqueries(duckdb_query)
            duckdb_query = self._rewrite_pg_get_expr_calls(duckdb_query)
            duckdb_query = self._rewrite_missing_pg_database_columns(duckdb_query)

            # Deref preprocessing: evaluate @cascade() expressions
            from ..sql_tools.deref_preprocessor import preprocess_deref_cascades
            deref_context = {
                'session_id': f"{self.auth_user_id}:{self.database_name}",  # Scoped by user + database for param store
                'protocol': 'pgwire',
                'database_name': self.database_name,
                'user_name': self.user_name,
                'application_name': self.application_name,
                'client_address': f"{self.addr[0]}:{self.addr[1]}" if self.addr else '',
                'caller_id': getattr(self, '_current_caller_id', None),
            }
            duckdb_query = preprocess_deref_cascades(duckdb_query, deref_context)

            self._runtime_log(
                "DEBUG",
                "Execute query prepared for DuckDB",
                event="execute_query_prepared",
                duckdb_query_preview=(duckdb_query[:500] if duckdb_query else ""),
                duckdb_query_len=len(duckdb_query or ""),
                param_count=len(params),
            )

            # DDL/DML commands - Execute without returning rows
            # These commands don't return result sets, only CommandComplete
            ddl_dml_prefixes = (
                # DDL - Data Definition Language
                'CREATE ', 'DROP ', 'ALTER ', 'TRUNCATE ',
                # DML - Data Manipulation Language (non-SELECT)
                'INSERT ', 'UPDATE ', 'DELETE ',
                # Privileges
                'GRANT ', 'REVOKE ',
                # Maintenance
                'VACUUM', 'ANALYZE', 'REINDEX', 'CLUSTER', 'REFRESH ',
            )
            if any(query_upper.startswith(prefix) for prefix in ddl_dml_prefixes):
                # Determine the command tag (e.g., "CREATE VIEW", "DROP TABLE", etc.)
                # Extract first two words for compound commands like "CREATE VIEW"
                words = query_upper.split()
                if len(words) >= 2 and words[0] in ('CREATE', 'DROP', 'ALTER', 'TRUNCATE'):
                    # Handle special cases like "CREATE OR REPLACE VIEW"
                    if words[0] == 'CREATE' and len(words) >= 4 and words[1] == 'OR' and words[2] == 'REPLACE':
                        command_tag = f"CREATE {words[3]}"
                    else:
                        command_tag = f"{words[0]} {words[1]}"
                elif words[0] == 'INSERT':
                    command_tag = "INSERT 0 0"  # PostgreSQL format: INSERT oid count
                elif words[0] == 'UPDATE':
                    command_tag = "UPDATE 0"
                elif words[0] == 'DELETE':
                    command_tag = "DELETE 0"
                else:
                    command_tag = words[0] if words else "OK"

                self._runtime_log(
                    "INFO",
                    f"DDL/DML command: {command_tag}",
                    event="ddl_dml",
                    command_tag=command_tag,
                )
                # Execute without fetching results
                self.duckdb_conn.execute(duckdb_query, params)
                # Send only CommandComplete - no RowDescription or DataRows
                self.sock.sendall(CommandComplete.encode(command_tag))
                return

            # Handle special catalog queries that need actual data (not just empty results)
            import pandas as pd

            # pg_timezone_names / pg_timezone_abbrevs - return common timezones
            if 'PG_TIMEZONE_NAMES' in query_upper or 'PG_TIMEZONE_ABBREVS' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling timezone catalog query",
                    event="catalog_timezone",
                )
                cols = self._expected_result_columns(query) or ['name', 'is_dst']
                rows = [
                    {'name': 'UTC', 'is_dst': False, 'abbrev': 'UTC', 'utc_offset': '00:00:00'},
                    {'name': 'America/New_York', 'is_dst': False, 'abbrev': 'EST', 'utc_offset': '-05:00:00'},
                    {'name': 'America/Los_Angeles', 'is_dst': False, 'abbrev': 'PST', 'utc_offset': '-08:00:00'},
                    {'name': 'Europe/London', 'is_dst': False, 'abbrev': 'GMT', 'utc_offset': '00:00:00'},
                    {'name': 'Europe/Paris', 'is_dst': False, 'abbrev': 'CET', 'utc_offset': '01:00:00'},
                    {'name': 'Asia/Tokyo', 'is_dst': False, 'abbrev': 'JST', 'utc_offset': '09:00:00'},
                ]
                result_df = pd.DataFrame([{c: r.get(c, None) for c in cols} for r in rows])
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_roles - return current user as a role
            if 'PG_ROLES' in query_upper and 'FROM' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_roles query",
                    event="catalog_pg_roles",
                )
                cols = self._expected_result_columns(query) or ['oid', 'rolname', 'rolsuper']
                # Validate column count matches Describe
                self._validate_custom_handler_columns(portal_name, len(cols), 'pg_roles')
                # Use 1/0 for booleans - JDBC expects integers for these fields
                base = {
                    'oid': 1, 'role_id': 1, 'id': 1,
                    'rolname': self.user_name, 'role_name': self.user_name,
                    'rolsuper': 1, 'is_super': 1,
                    'rolinherit': 1, 'is_inherit': 1,
                    'rolcreaterole': 1, 'can_createrole': 1,
                    'rolcreatedb': 1, 'can_createdb': 1,
                    'rolcanlogin': 1, 'can_login': 1,
                    'rolreplication': 0, 'rolbypassrls': 0,
                    'rolconnlimit': -1, 'rolpassword': None, 'rolvaliduntil': None,
                    'rolconfig': None, 'description': None,
                }
                result_df = pd.DataFrame([{c: base.get(c, None) for c in cols}])
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                self._runtime_log(
                    "DEBUG",
                    f"pg_roles handled ({len(result_df)} rows, {len(cols)} cols)",
                    event="catalog_pg_roles_complete",
                    row_count=len(result_df),
                    col_count=len(cols),
                )
                return

            # pg_user - return current user info (DataGrip checks superuser status)
            if 'PG_USER' in query_upper and 'FROM' in query_upper and 'PG_USER_MAPPINGS' not in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_user query",
                    event="catalog_pg_user",
                )
                cols = self._expected_result_columns(query) or ['usename', 'usesuper']
                # Validate column count matches Describe
                self._validate_custom_handler_columns(portal_name, len(cols), 'pg_user')
                # Use 1/0 for booleans - JDBC expects integers for these fields
                base = {
                    'usename': self.user_name,
                    'usesysid': 1,
                    'usecreatedb': 1,
                    'usesuper': 1,
                    'userepl': 1,
                    'usebypassrls': 0,
                    'passwd': None,
                    'valuntil': None,
                    'useconfig': None,
                }
                result_df = pd.DataFrame([{c: base.get(c, None) for c in cols}])
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                self._runtime_log(
                    "DEBUG",
                    f"pg_user handled ({len(result_df)} rows, {len(cols)} cols)",
                    event="catalog_pg_user_complete",
                    row_count=len(result_df),
                    col_count=len(cols),
                )
                return

            # pg_event_trigger - return empty result (DuckDB doesn't have event triggers)
            if 'PG_EVENT_TRIGGER' in query_upper and 'FROM' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_event_trigger query (empty)",
                    event="catalog_pg_event_trigger",
                )
                cols = self._expected_result_columns(query) or ['oid', 'evtname', 'evtevent', 'evtowner', 'evtfoid', 'evtenabled', 'evttags']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # Foreign data wrapper tables - return empty results (DuckDB doesn't have FDW)
            if 'PG_FOREIGN_DATA_WRAPPER' in query_upper and 'FROM' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_foreign_data_wrapper query (empty)",
                    event="catalog_pg_foreign_data_wrapper",
                )
                cols = self._expected_result_columns(query) or ['oid', 'fdwname', 'fdwowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            if 'PG_FOREIGN_SERVER' in query_upper and 'FROM' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_foreign_server query (empty)",
                    event="catalog_pg_foreign_server",
                )
                cols = self._expected_result_columns(query) or ['oid', 'srvname', 'srvowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            if 'PG_FOREIGN_TABLE' in query_upper and 'FROM' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_foreign_table query (empty)",
                    event="catalog_pg_foreign_table",
                )
                cols = self._expected_result_columns(query) or ['ftrelid', 'ftserver', 'ftoptions']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_extension - return empty result (DuckDB doesn't have extensions)
            if 'PG_EXTENSION' in query_upper and 'FROM' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_extension query (empty)",
                    event="catalog_pg_extension",
                )
                cols = self._expected_result_columns(query) or ['oid', 'extname', 'extowner', 'extnamespace']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_language - return empty result (DuckDB doesn't have procedural languages)
            if 'PG_LANGUAGE' in query_upper and 'FROM' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_language query (empty)",
                    event="catalog_pg_language",
                )
                cols = self._expected_result_columns(query) or ['oid', 'lanname', 'lanowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_cast - return empty result (DuckDB doesn't have pg_cast)
            if 'PG_CAST' in query_upper and 'FROM' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_cast query (empty)",
                    event="catalog_pg_cast",
                )
                cols = self._expected_result_columns(query) or ['oid', 'castsource', 'casttarget', 'castfunc', 'castcontext', 'castmethod']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_collation - return empty result (DuckDB doesn't have pg_collation)
            if self._primary_from_table(query_upper) == 'PG_COLLATION':
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_collation query (empty)",
                    event="catalog_pg_collation",
                )
                cols = self._expected_result_columns(query) or ['oid', 'collname', 'collnamespace', 'collowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_inherits - return empty result (DuckDB doesn't have table inheritance)
            # Only match if pg_inherits is the main table, not just a LEFT JOIN in a pg_class query
            if 'PG_INHERITS' in query_upper and 'PG_CLASS' not in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_inherits query (empty)",
                    event="catalog_pg_inherits",
                )
                cols = self._expected_result_columns(query) or ['inhrelid', 'inhparent', 'inhseqno']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_partitioned_table - return empty result (DuckDB doesn't have partition metadata)
            if 'PG_PARTITIONED_TABLE' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_partitioned_table query (empty)",
                    event="catalog_pg_partitioned_table",
                )
                cols = self._expected_result_columns(query) or ['partrelid', 'partstrat', 'partnatts']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_description - return empty result (DuckDB doesn't have pg_description)
            # This catches UNION queries where pg_description is the main FROM table
            if 'FROM PG_CATALOG.PG_DESCRIPTION' in query_upper or 'FROM PG_DESCRIPTION' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_description query (empty)",
                    event="catalog_pg_description",
                )
                cols = self._expected_result_columns(query) or ['id', 'sub_ids', 'kind', 'description']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_operator - return empty result (DuckDB doesn't have pg_operator)
            if self._primary_from_table(query_upper) == 'PG_OPERATOR':
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_operator query (empty)",
                    event="catalog_pg_operator",
                )
                cols = self._expected_result_columns(query) or ['oid', 'oprname', 'oprnamespace', 'oprowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_aggregate - return empty result (DuckDB doesn't have pg_aggregate)
            if 'PG_AGGREGATE' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_aggregate query (empty)",
                    event="catalog_pg_aggregate",
                )
                cols = self._expected_result_columns(query) or ['aggfnoid', 'aggkind', 'aggnumdirectargs']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # Complex pg_constraint queries with PostgreSQL-specific array functions
            if 'PG_CONSTRAINT' in query_upper and ('CONEXCLOP' in query_upper or 'UNNEST' in query_upper or 'REGOPER' in query_upper):
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_constraint query (complex, empty)",
                    event="catalog_pg_constraint_complex",
                )
                cols = self._expected_result_columns(query) or ['oid', 'conname', 'connamespace', 'contype']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_depend queries with regclass casts - return empty result
            if 'PG_DEPEND' in query_upper and ('REGCLASS' in query_upper or 'REFOBJID' in query_upper):
                self._runtime_log(
                    "DEBUG",
                    "Handling pg_depend query (empty)",
                    event="catalog_pg_depend",
                )
                cols = self._expected_result_columns(query) or ['dependent_id', 'owner_id', 'refobjsubid']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # Any query with regclass type casts that DuckDB doesn't support
            if '::REGCLASS' in query_upper or 'REGCLASS' in query_upper:
                self._runtime_log(
                    "DEBUG",
                    "Handling regclass query (empty)",
                    event="catalog_regclass",
                )
                cols = self._expected_result_columns(query) or ['result']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                return

            # pg_settings - augment DuckDB's pg_settings with PostgreSQL-specific settings
            # DBeaver and other clients expect settings like 'standard_conforming_strings'
            if 'PG_SETTINGS' in query_upper and 'FROM' in query_upper:
                try:
                    # Execute the query against DuckDB first
                    result_df = self.duckdb_conn.execute(duckdb_query, params).fetchdf()

                    # PostgreSQL settings that DuckDB doesn't have but clients need
                    pg_specific_settings = {
                        'standard_conforming_strings': ('on', 'Standard-conforming string literals', 'bool'),
                        'backslash_quote': ('safe_encoding', 'Backslash handling in string literals', 'enum'),
                        'bytea_output': ('hex', 'Output format for bytea', 'enum'),
                        'client_min_messages': ('notice', 'Minimum message level for client', 'enum'),
                        'default_transaction_isolation': ('read committed', 'Default isolation level', 'enum'),
                        'default_transaction_read_only': ('off', 'Default read-only status', 'bool'),
                        'session_replication_role': ('origin', 'Replication role', 'enum'),
                        'synchronous_commit': ('on', 'Synchronous commit mode', 'enum'),
                        'transaction_isolation': ('read committed', 'Current isolation level', 'enum'),
                        'transaction_read_only': ('off', 'Current read-only status', 'bool'),
                    }

                    # If query is filtering by name and result is empty, check if it's asking for a PG setting
                    if len(result_df) == 0 and params:
                        setting_name = params[0] if params else None
                        if setting_name and setting_name in pg_specific_settings:
                            val, desc, vtype = pg_specific_settings[setting_name]
                            result_df = pd.DataFrame([{
                                'name': setting_name,
                                'setting': val,
                                'short_desc': desc,
                                'vartype': vtype
                            }])

                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    self._runtime_log(
                        "DEBUG",
                        f"pg_settings handled ({len(result_df)} rows)",
                        event="catalog_pg_settings_complete",
                        row_count=len(result_df),
                    )
                    return
                except Exception as e:
                    self._runtime_log(
                        "WARN",
                        f"pg_settings handler failed: {e}",
                        event="catalog_pg_settings_failed",
                        error_type=type(e).__name__,
                    )
                    # Fall through to normal execution

            # Handle queries with missing pg_catalog tables (DataGrip introspection)
            missing_table_result = self._handle_missing_pg_catalog_tables(query_upper, duckdb_query)
            if missing_table_result is not None:
                send_execute_results(self.sock, missing_table_result, send_row_description=send_row_desc)
                self._runtime_log(
                    "DEBUG",
                    f"Missing pg_catalog table handled (empty result, {len(missing_table_result)} rows)",
                    event="catalog_missing_pg_catalog_table",
                    row_count=len(missing_table_result),
                )
                return

            # Lazy attach configured sources for Extended Query Protocol too
            if self._lazy_attach is not None:
                try:
                    self._lazy_attach.ensure_for_query(duckdb_query, aggressive=False)
                    self._refresh_attached_view_cache()
                except Exception:
                    pass

            # Execute with parameters
            result_df = self.duckdb_conn.execute(duckdb_query, params).fetchdf()

            # Limit rows if max_rows > 0
            if max_rows > 0:
                result_df = result_df.head(max_rows)

            # Safety check: if Describe already sent column info, verify column count matches
            # If mismatch, force re-sending RowDescription to prevent ArrayIndexOutOfBoundsException
            actual_send_row_desc = send_row_desc
            described_col_count = None
            actual_col_count = len(result_df.columns)
            if not send_row_desc and portal_name in self.portals:
                portal = self.portals[portal_name]
                described_col_count = portal.get('described_columns')
                if described_col_count is not None and described_col_count != actual_col_count:
                    # Log the query that caused the mismatch for debugging
                    self._runtime_log(
                        "WARN",
                        "COLUMN MISMATCH DETECTED",
                        event="catalog_column_mismatch",
                        described_col_count=described_col_count,
                        actual_col_count=actual_col_count,
                        actual_columns=list(result_df.columns)[:200],
                        query_preview=(query[:500] if query else ""),
                    )
                    actual_send_row_desc = True

            # Send results - only include RowDescription if Describe didn't already send it
            send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)

            # CRITICAL DEBUG: Log 0-row results - DataGrip may expect data from these queries
            if len(result_df) == 0 and is_catalog:
                self._runtime_log(
                    "DEBUG",
                    "ZERO ROWS returned for catalog query",
                    event="catalog_zero_rows",
                    query_preview=(query[:500] if query else ""),
                    duckdb_query_preview=(duckdb_query[:500] if duckdb_query else ""),
                )

            # Auto-materialize for query insurance (Extended Query Protocol)
            _result_location = self._maybe_materialize_result(
                original_query or query, result_df, _query_id, _caller_id
            )

            # Log query completion for SQL Trail (Extended Query Protocol)
            self._complete_query_tracking(
                _query_id, _query_start_time, _caller_id, result_df,
                result_location=_result_location
            )

            # Clear early termination hint and log stats (Extended Query Protocol)
            if _early_term_enabled and _caller_id:
                try:
                    from lars.sql_tools.early_termination import clear_early_termination_hint
                    stats = clear_early_termination_hint(_caller_id)
                    if stats:
                        self._runtime_log(
                            "DEBUG",
                            "Early termination stats",
                            event="early_termination_stats",
                            processed_count=stats.get("processed_count", 0),
                            match_count=stats.get("match_count", 0),
                            limit_hint=stats.get("limit_hint", 0),
                        )
                except Exception:
                    pass  # Non-fatal

        except Exception as e:
            error = e
            error_str = str(e)
            self._runtime_log(
                "ERROR",
                f"Execute error: {error_str[:200]}",
                event="pgwire_error",
                pgwire_message="EXECUTE",
            )

            # Check if this is a "Table does not exist" error for a pg_catalog table
            # These are common during introspection and should return empty results, not errors
            import re
            missing_table_match = re.search(r"Table with name (\w+) does not exist", error_str, re.IGNORECASE)
            if missing_table_match:
                missing_table = missing_table_match.group(1).lower()
                # List of pg_catalog tables that DuckDB doesn't have
                known_missing = {
                    'pg_trigger', 'pg_rewrite', 'pg_policy', 'pg_policies', 'pg_rules',
                    'pg_operator', 'pg_opclass', 'pg_opfamily', 'pg_aggregate',
                    'pg_cast', 'pg_collation', 'pg_conversion', 'pg_range',  # pg_enum removed - DuckDB has it
                    'pg_extension', 'pg_language', 'pg_foreign_data_wrapper',
                    'pg_foreign_server', 'pg_foreign_table', 'pg_event_trigger',
                    'pg_publication', 'pg_subscription', 'pg_replication_slots',
                    'pg_locks', 'pg_stat_statements', 'pg_stat_user_tables',
                    'pg_stat_user_indexes', 'pg_statio_user_tables',
                    'pg_statistic', 'pg_statistic_ext', 'pg_inherits',
                    'pg_partitioned_table', 'pg_seclabel', 'pg_shseclabel',
                    'pg_ts_config', 'pg_ts_dict', 'pg_ts_parser', 'pg_ts_template',
                    'pg_am', 'pg_amop', 'pg_amproc', 'pg_roles', 'pg_auth_members',
                    'pg_hba_file_rules', 'pg_file_settings', 'pg_description',
                    'pg_shdescription', 'pg_stat_activity',
                }
                if missing_table in known_missing:
                    self._runtime_log(
                        "INFO",
                        f"Missing pg_catalog table '{missing_table}' - returning empty result",
                        event="pg_catalog_missing_table",
                        table=missing_table,
                    )
                    # Try to infer expected columns from the query
                    expected_cols = self._expected_result_columns(query)
                    if not expected_cols:
                        # Default columns for common introspection queries
                        expected_cols = ['oid', 'name']
                    import pandas as pd
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    error = None
                    return

            # Mark transaction as errored
            if self.transaction_status == 'T':
                self.transaction_status = 'E'

            # Clear early termination hint on error (Extended Query Protocol)
            if _early_term_enabled and _caller_id:
                try:
                    from lars.sql_tools.early_termination import clear_early_termination_hint
                    clear_early_termination_hint(_caller_id)
                except Exception:
                    pass  # Non-fatal

            # In Extended Query Protocol, don't send ReadyForQuery - wait for Sync
            self.sock.sendall(ErrorResponse.encode('ERROR', f"Execute error: {str(e)}"))

            # Log query error for SQL Trail (Extended Query Protocol)
            self._error_query_tracking(_query_id, _query_start_time, e)
        finally:
            try:
                if execute_start is not None:
                    import time
                    duration_ms = (time.time() - execute_start) * 1000.0
                    self._runtime_log(
                        "DEBUG" if is_catalog else "INFO",
                        f"Query #{self.query_count} complete ({duration_ms:.1f} ms)",
                        event="query_complete",
                        query_count=self.query_count,
                        portal_name=portal_name,
                        statement_name=statement_name,
                        is_catalog=is_catalog,
                        duration_ms=duration_ms,
                        ok=(error is None),
                        error_type=(type(error).__name__ if error else None),
                        error_message=(str(error)[:500] if error else None),
                    )
            except Exception:
                pass

    def _handle_close(self, msg: dict):
        """
        Handle Close message - close prepared statement or portal.

        Args:
            msg: Decoded Close message {type, name}
        """
        close_type = msg['type']
        name = msg['name']

        self._runtime_log(
            "DEBUG",
            f"Close {close_type} '{name or '(unnamed)'}'",
            event="pgwire_close",
            close_type=close_type,
            name=name,
        )

        try:
            if close_type == 'S':  # Statement
                if name in self.prepared_statements:
                    del self.prepared_statements[name]
                    self._runtime_log("DEBUG", "Statement closed", event="pgwire_close_complete", close_type="S", name=name)
            elif close_type == 'P':  # Portal
                if name in self.portals:
                    del self.portals[name]
                    self._runtime_log("DEBUG", "Portal closed", event="pgwire_close_complete", close_type="P", name=name)

            # Send CloseComplete
            self.sock.sendall(CloseComplete.encode())

        except Exception as e:
            self._runtime_log(
                "WARN",
                f"Close error: {e}",
                event="pgwire_close_error",
                error_type=type(e).__name__,
            )
            # In Extended Query Protocol, don't send ReadyForQuery - wait for Sync
            self.sock.sendall(ErrorResponse.encode('ERROR', f"Close error: {str(e)}"))

    def _handle_sync(self):
        """
        Handle Sync message - synchronization point.

        Sends ReadyForQuery with current transaction status.
        """
        self._runtime_log(
            "DEBUG",
            f"Sync (transaction_status={self.transaction_status})",
            event="pgwire_sync",
            transaction_status=self.transaction_status,
        )

        # Send ReadyForQuery with current transaction status
        self.sock.sendall(ReadyForQuery.encode(self.transaction_status))

    def handle(self):
        """
        Main client handling loop.

        Message flow:
        0. Handle SSL negotiation (reject for v1)
        1. Read startup message
        2. Setup DuckDB session
        3. Send startup response
        4. Loop: Read message → Execute → Send response
        5. Cleanup on disconnect
        """
        import time

        # Register with server for connection tracking
        if self.server:
            self.server.register_connection(self)

        # Initialize activity tracking
        self._last_activity = time.time()
        self._runtime_log(
            "INFO",
            "Connection opened",
            event="connection_open",
            addr=str(self.addr),
            idle_timeout=self.idle_timeout,
            socket_fd=getattr(self.sock, "fileno", lambda: None)(),
            active_connections=(self.server.get_active_count() if self.server else None),
        )

        try:
            # Set socket timeout for idle detection (if enabled)
            if self.idle_timeout > 0:
                self.sock.settimeout(self.idle_timeout)

            # Step 0: Check for SSL request (common - psql tries SSL first)
            try:
                first_message = PostgresMessage.read_startup_message(self.sock)
            except PostgresProtocolError as e:
                msg_type_chr = None
                try:
                    msg_type_chr = chr(e.msg_type) if e.msg_type is not None else None
                except Exception:
                    msg_type_chr = None
                self._runtime_log(
                    "WARN",
                    f"Startup protocol error: {e}",
                    event="pgwire_protocol_error",
                    phase="startup",
                    msg_type=e.msg_type,
                    msg_type_chr=msg_type_chr,
                    length=e.length,
                    payload_length=e.payload_length,
                )
                try:
                    self.sock.sendall(
                        ErrorResponse.encode(
                            'FATAL',
                            'Protocol error',
                            detail=str(e),
                            sqlstate='08P01',  # protocol_violation
                        )
                    )
                except Exception:
                    pass
                return
            if not first_message:
                self._runtime_log(
                    "WARN",
                    "Failed to read initial message",
                    event="startup_read_failed",
                    addr=str(self.addr),
                )
                return

            # CancelRequest uses a different startup code on a separate connection.
            # We don't support cancelling server-side execution, but we should handle
            # it gracefully without crashing the startup path.
            if first_message.get('cancel_request'):
                self._runtime_log(
                    "INFO",
                    "CancelRequest received - closing (not supported)",
                    event="cancel_request",
                    addr=str(self.addr),
                )
                return

            # Handle SSL request
            if first_message.get('ssl_request'):
                self._runtime_log(
                    "INFO",
                    "SSL requested - rejecting (not supported in v1)",
                    event="ssl_rejected",
                    addr=str(self.addr),
                )
                # Send 'N' to indicate SSL not supported
                self.sock.sendall(b'N')

                # Now read the REAL startup message (client will retry without SSL)
                try:
                    startup = PostgresMessage.read_startup_message(self.sock)
                except PostgresProtocolError as e:
                    msg_type_chr = None
                    try:
                        msg_type_chr = chr(e.msg_type) if e.msg_type is not None else None
                    except Exception:
                        msg_type_chr = None
                    self._runtime_log(
                        "WARN",
                        f"Startup protocol error: {e}",
                        event="pgwire_protocol_error",
                        phase="startup",
                        msg_type=e.msg_type,
                        msg_type_chr=msg_type_chr,
                        length=e.length,
                        payload_length=e.payload_length,
                    )
                    try:
                        self.sock.sendall(
                            ErrorResponse.encode(
                                'FATAL',
                                'Protocol error',
                                detail=str(e),
                                sqlstate='08P01',  # protocol_violation
                            )
                        )
                    except Exception:
                        pass
                    return
                if not startup:
                    self._runtime_log(
                        "WARN",
                        "Failed to read startup after SSL rejection",
                        event="startup_read_failed",
                        addr=str(self.addr),
                    )
                    return
                if startup.get('cancel_request'):
                    self._runtime_log(
                        "INFO",
                        "CancelRequest received after SSL rejection - closing (not supported)",
                        event="cancel_request",
                        addr=str(self.addr),
                    )
                    return
            else:
                # No SSL request - this IS the startup message
                startup = first_message

            # Step 2: Handle startup (sets session_id based on database name)
            try:
                self.handle_startup(startup['params'])
            except ValueError as e:
                # Fail fast before auth/session setup; invalid db names would corrupt ClickHouse namespacing.
                try:
                    self.sock.sendall(ErrorResponse.encode(
                        'FATAL',
                        "Invalid database name",
                        detail=str(e),
                        sqlstate='3D000',  # invalid_catalog_name
                    ))
                except Exception:
                    pass
                return

            # Step 2b: Authenticate (if auth enabled)
            if not self._authenticate():
                # Authentication failed - send error and close connection
                send_error(
                    self.sock,
                    "Authentication failed",
                    detail="Invalid username or password",
                    severity='FATAL'
                )
                return

            # Step 3: Setup DuckDB session with LARS UDFs
            # NOTE: We do ALL setup before sending startup response to avoid race conditions.
            # DataGrip and other aggressive clients send queries immediately after startup,
            # so deferred setup causes broken pipe errors if it takes too long.
            print(f"[pgwire.handle] Step 3a: setup_session_minimal (pid={os.getpid()})")
            self.setup_session_minimal()
            print(f"[pgwire.handle] Step 3b: setup_session_deferred (pid={os.getpid()})")
            self.setup_session_deferred()
            print(f"[pgwire.handle] Step 3 complete, duckdb_conn={'set' if self.duckdb_conn else 'None'} (pid={os.getpid()})")

            # Step 4: Send startup response (session is now fully ready)
            print(f"[pgwire.handle] Step 4: send_startup_response (pid={os.getpid()})")
            send_startup_response(self.sock)
            print(f"[pgwire.handle] Step 5: entering message loop (pid={os.getpid()})")

            # Step 5: Message loop
            while self.running:
                try:
                    msg_type, payload = PostgresMessage.read_message(self.sock)
                except socket.timeout:
                    # Idle timeout - disconnect client
                    self._runtime_log(
                        "INFO",
                        f"Idle timeout ({self.idle_timeout}s) - disconnecting",
                        event="idle_timeout",
                        idle_timeout=self.idle_timeout,
                    )
                    break
                except PostgresProtocolError as e:
                    msg_type_chr = None
                    try:
                        msg_type_chr = chr(e.msg_type) if e.msg_type is not None else None
                    except Exception:
                        msg_type_chr = None
                    self._runtime_log(
                        "WARN",
                        f"Protocol error: {e}",
                        event="pgwire_protocol_error",
                        phase="message",
                        msg_type=e.msg_type,
                        msg_type_chr=msg_type_chr,
                        length=e.length,
                        payload_length=e.payload_length,
                    )
                    try:
                        self.sock.sendall(
                            ErrorResponse.encode(
                                'FATAL',
                                'Protocol error',
                                detail=str(e),
                                sqlstate='08P01',  # protocol_violation
                            )
                        )
                    except Exception:
                        pass
                    break

                # Update activity timestamp
                self._last_activity = time.time()

                if msg_type is None:
                    # Connection closed by client
                    self._runtime_log("INFO", "Connection closed by client", event="connection_closed")
                    break

                if msg_type == MessageType.QUERY:
                    # Simple query protocol
                    # Payload is null-terminated SQL string
                    query = payload.rstrip(b'\x00').decode('utf-8')
                    self.handle_query(query)

                elif msg_type == MessageType.TERMINATE:
                    # Client requested clean disconnect
                    self._runtime_log("INFO", "Client requested termination", event="terminate")
                    break

                # Extended Query Protocol
                elif msg_type == MessageType.PARSE:
                    self._runtime_log(
                        "DEBUG",
                        f"RECV Parse ({len(payload)} bytes)",
                        event="pgwire_recv",
                        pgwire_message="PARSE",
                        payload_bytes=len(payload),
                    )
                    msg = ParseMessage.decode(payload)
                    self._handle_parse(msg)

                elif msg_type == MessageType.BIND:
                    self._runtime_log(
                        "DEBUG",
                        f"RECV Bind ({len(payload)} bytes)",
                        event="pgwire_recv",
                        pgwire_message="BIND",
                        payload_bytes=len(payload),
                    )
                    msg = BindMessage.decode(payload)
                    self._handle_bind(msg)

                elif msg_type == MessageType.DESCRIBE:
                    self._runtime_log(
                        "DEBUG",
                        f"RECV Describe ({len(payload)} bytes)",
                        event="pgwire_recv",
                        pgwire_message="DESCRIBE",
                        payload_bytes=len(payload),
                    )
                    msg = DescribeMessage.decode(payload)
                    self._handle_describe(msg)

                elif msg_type == MessageType.EXECUTE:
                    self._runtime_log(
                        "DEBUG",
                        f"RECV Execute ({len(payload)} bytes)",
                        event="pgwire_recv",
                        pgwire_message="EXECUTE",
                        payload_bytes=len(payload),
                    )
                    msg = ExecuteMessage.decode(payload)
                    self._handle_execute(msg)

                elif msg_type == MessageType.CLOSE:
                    msg = CloseMessage.decode(payload)
                    self._handle_close(msg)

                elif msg_type == MessageType.SYNC:
                    self._handle_sync()

                elif msg_type == MessageType.FLUSH:
                    # Flush tells server to send all pending responses immediately.
                    # Since we respond synchronously (not buffered), this is a no-op.
                    # DataGrip sends FLUSH between Parse/Bind to ensure responses arrive.
                    pass

                else:
                    # Unknown message type
                    try:
                        ascii_preview = chr(msg_type) if 32 <= msg_type <= 126 else "?"
                    except Exception:
                        ascii_preview = "?"
                    self._runtime_log(
                        "WARN",
                        f"Unknown message type: {msg_type} ({ascii_preview})",
                        event="pgwire_unknown_message_type",
                        msg_type=int(msg_type),
                        ascii=ascii_preview,
                    )
                    send_error(
                        self.sock,
                        f"Unsupported message type: {msg_type}",
                        detail="LARS PostgreSQL server implements Simple Query Protocol only."
                    )

        except Exception as e:
            print(f"[pgwire.handle] ❌ Connection error: {type(e).__name__}: {e} (pid={os.getpid()})")
            traceback.print_exc()
            self._runtime_log(
                "ERROR",
                f"Connection error: {e}",
                event="connection_error",
                error_type=type(e).__name__,
            )

        finally:
            # Step 5: Cleanup
            self.cleanup()

    def cleanup(self):
        """
        Clean up connection and DuckDB session.

        Called when client disconnects or connection errors.
        Ensures DuckDB is left in a clean state.
        """
        # Unregister from server first
        if self.server:
            self.server.unregister_connection(self)
            active_count = self.server.get_active_count()
            self._runtime_log(
                "INFO",
                f"Cleaning up ({self.query_count} queries executed, {active_count} active connections remaining)",
                event="cleanup",
                query_count=self.query_count,
                active_connections=active_count,
                pooled=self._is_pooled_connection,
            )
        else:
            self._runtime_log(
                "INFO",
                f"Cleaning up ({self.query_count} queries executed)",
                event="cleanup",
                query_count=self.query_count,
                pooled=self._is_pooled_connection,
            )

        # 1. Try to rollback any open transaction to leave DuckDB in clean state
        if self.duckdb_conn:
            try:
                self.duckdb_conn.execute("ROLLBACK")
                self._runtime_log("DEBUG", "Transaction rolled back", event="duckdb_rollback")
            except Exception as e:
                error_msg = str(e).lower()
                # "no transaction is active" is NORMAL - not an error
                if "no transaction" in error_msg:
                    # This is fine - no transaction was active
                    self._runtime_log("DEBUG", "No active transaction (clean state)", event="duckdb_rollback")
                else:
                    # Unknown error - log and continue
                    self._runtime_log("WARN", f"Rollback warning: {e}", event="duckdb_rollback")

            if self._is_pooled_connection:
                try:
                    from ..sql_tools.connection_pool import return_to_pool, refill_pool
                    duckdb_conn_obj_id = id(self.duckdb_conn)
                    returned = return_to_pool(self.duckdb_conn)
                    self.duckdb_conn = None
                    self._runtime_log(
                        "DEBUG",
                        "Returned DuckDB connection to pool" if returned else "Discarded DuckDB connection (pool disabled/full)",
                        event="duckdb_pool_return",
                        returned=returned,
                        duckdb_conn_obj_id=duckdb_conn_obj_id,
                    )
                    refill_pool()
                except Exception:
                    try:
                        self.duckdb_conn.close()
                    except Exception:
                        pass
                    self.duckdb_conn = None
            else:
                # Each pgwire client owns its DuckDB session; close it on disconnect.
                try:
                    duckdb_conn_obj_id = id(self.duckdb_conn)
                    self.duckdb_conn.close()
                    self._runtime_log(
                        "DEBUG",
                        "Closed DuckDB connection",
                        event="duckdb_close",
                        duckdb_conn_obj_id=duckdb_conn_obj_id,
                    )
                except Exception:
                    pass
                self.duckdb_conn = None

        # 2. Close socket
        try:
            self.sock.close()
        except:
            pass


class LARSPostgresServer:
    """
    PostgreSQL wire protocol server for LARS.

    Listens on TCP port, accepts PostgreSQL client connections,
    and routes queries to LARS DuckDB sessions.

    Features:
    - Concurrent connections (thread per client)
    - Isolated DuckDB sessions (one per client)
    - LARS UDFs auto-registered
    - Simple Query Protocol (sufficient for most tools)
    - Configurable connection limits and timeouts
    """

    def __init__(
        self,
        host='0.0.0.0',
        port=5432,
        session_prefix='pg_client',
        listen_backlog=1024,
        max_connections=0,
        idle_timeout=0,
    ):
        """
        Initialize server.

        Args:
            host: Host to listen on (0.0.0.0 = all interfaces)
            port: Port to listen on (5432 = standard PostgreSQL port)
            session_prefix: Prefix for DuckDB session IDs
            listen_backlog: Socket listen backlog (default: 1024, was 5)
            max_connections: Maximum concurrent connections (0 = unlimited)
            idle_timeout: Disconnect idle clients after N seconds (0 = no timeout)
        """
        self.host = host
        self.port = port
        self.session_prefix = session_prefix
        self.listen_backlog = listen_backlog
        self.max_connections = max_connections
        self.idle_timeout = idle_timeout
        self.running = False
        self.client_count = 0
        self.active_connections: set = set()  # Track active ClientConnection objects
        self._connections_lock = Lock()  # Protect active_connections set

    def register_connection(self, client: 'ClientConnection') -> None:
        """Register a client connection as active."""
        with self._connections_lock:
            self.active_connections.add(client)

    def unregister_connection(self, client: 'ClientConnection') -> None:
        """Unregister a client connection."""
        with self._connections_lock:
            self.active_connections.discard(client)

    def get_active_count(self) -> int:
        """Get count of active connections."""
        with self._connections_lock:
            return len(self.active_connections)

    def start(self):
        """
        Start server and accept connections.

        This is a blocking call - runs until interrupted (Ctrl+C).
        """
        # Create TCP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Bind to host:port
        try:
            sock.bind((self.host, self.port))
        except OSError as e:
            print("=" * 70)
            styled_print(f"{S.ERR} ERROR: Could not start server")
            print("=" * 70)
            print(f"Failed to bind to {self.host}:{self.port}")
            print(f"Error: {e}")
            styled_print(f"\n{S.TIP} Possible causes:")
            print(f"   1. Port {self.port} is already in use")
            print(f"   2. Permission denied (ports < 1024 require root)")
            styled_print(f"\n{S.TIP} Solutions:")
            print(f"   1. Stop other process: sudo lsof -ti:{self.port} | xargs kill")
            print(f"   2. Use different port: lars server --port 5433")
            print(f"   3. Use sudo (not recommended): sudo lars server --port {self.port}")
            print("=" * 70)
            return

        sock.listen(self.listen_backlog)
        self.running = True

        # Initialize cascade registry and dynamic operator patterns (cached for server lifetime)
        try:
            from lars.semantic_sql.registry import initialize_registry
            from lars.sql_tools.dynamic_operators import initialize_dynamic_patterns

            styled_print(f"{S.RETRY} Initializing cascade registry...")
            initialize_registry(force=True)

            styled_print(f"{S.RETRY} Loading dynamic operator patterns...")
            patterns = initialize_dynamic_patterns(force=True)

            styled_print(f"{S.DONE} Loaded {len(patterns['all_keywords'])} semantic SQL operators")
            print(f"   - {len(patterns['infix'])} infix: {', '.join(sorted(list(patterns['infix']))[:5])}{'...' if len(patterns['infix']) > 5 else ''}")
            print(f"   - {len(patterns['function'])} functions: {', '.join(sorted(list(patterns['function']))[:5])}{'...' if len(patterns['function']) > 5 else ''}")
            print()
        except Exception as e:
            styled_print(f"{S.WARN}  Warning: Could not initialize dynamic operators: {e}")
            print(f"   Semantic SQL operators may not work correctly")
            print()

        # Pre-warm DuckDB in-memory connection pool for fast pgwire startup (optional)
        try:
            from ..sql_tools.connection_pool import initialize_pool, pool_status
            styled_print(f"{S.RETRY} Pre-warming DuckDB connection pool...")
            initialize_pool()
            status = pool_status()
            if status.get("enabled"):
                styled_print(
                    f"{S.DONE} DuckDB pool warming (target: {status.get('warmup_size')}, max: {status.get('max_size')})"
                )
            else:
                styled_print(f"{S.WARN}  DuckDB pool disabled (LARS_POOL_ENABLED=0)")
            print()
        except ImportError:
            styled_print(f"{S.WARN}  DuckDB connection pool not available")
            print()
        except Exception as e:
            styled_print(f"{S.WARN}  DuckDB pool init failed: {e}")
            print()

        # Print startup banner
        print("=" * 70)
        styled_print(f"{S.CASCADE} LARS POSTGRESQL SERVER")
        print("=" * 70)
        styled_print(f"{S.WEB} Listening on: {self.host}:{self.port}")
        styled_print(f"{S.LINK} Connection string: postgresql://lars@localhost:{self.port}/default")
        print()
        styled_print(f"{S.DONE} Available SQL functions:")
        print("   • lars_udf(instructions, input_value)")
        print("     → Simple LLM extraction/classification")
        print()
        print("   • lars_cascade_udf(cascade_path, json_inputs)")
        print("     → Full multi-cell cascade per row (with takes!)")
        print()
        styled_print(f"{S.INFO} Connect from:")
        print(f"   • psql:      psql postgresql://localhost:{self.port}/default")
        print(f"   • DBeaver:   New Connection → PostgreSQL → localhost:{self.port}")
        print(f"   • Python:    psycopg2.connect('postgresql://localhost:{self.port}/default')")
        print(f"   • DataGrip:  New Data Source → PostgreSQL → localhost:{self.port}")
        print()
        styled_print(f"{S.TIP} Each connection gets:")
        print("   • Isolated DuckDB session")
        print("   • Temp tables (session-scoped)")
        print("   • LARS UDFs registered")
        print("   • ATTACH support (connect to Postgres/MySQL/S3)")
        print()
        styled_print(f"{S.INFO} Connection settings:")
        print(f"   • Listen backlog: {self.listen_backlog} (pending connections)")
        if self.max_connections > 0:
            print(f"   • Max connections: {self.max_connections}")
        else:
            print(f"   • Max connections: unlimited")
        if self.idle_timeout > 0:
            print(f"   • Idle timeout: {self.idle_timeout}s")
        else:
            print(f"   • Idle timeout: disabled")
        print()
        styled_print(f"{S.PAUSE}  Press Ctrl+C to stop")
        print("=" * 70)

        # Set up signal handler for forceful shutdown
        import signal
        import os

        shutdown_count = [0]  # Use list to allow modification in nested function

        def signal_handler(signum, frame):
            shutdown_count[0] += 1
            self.running = False

            if shutdown_count[0] == 1:
                styled_print(f"\n\n{S.STOP}  Shutting down server...")
                print(f"   Total connections served: {self.client_count}")

                # Signal UDF executors to stop
                try:
                    from lars.sql_tools.udf import request_shutdown
                    request_shutdown()
                    print("   Signalled UDF executors to stop...")
                except Exception:
                    pass

                print("   Press Ctrl+C again to force quit...")

            elif shutdown_count[0] >= 2:
                print("\n   Force quitting...")
                try:
                    sock.close()
                except Exception:
                    pass
                os._exit(0)

        # Install signal handlers
        original_sigint = signal.signal(signal.SIGINT, signal_handler)
        original_sigterm = signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Set socket timeout so accept() doesn't block forever
            sock.settimeout(1.0)

            while self.running:
                try:
                    # Accept new connection (with timeout)
                    client_sock, addr = sock.accept()
                    self.client_count += 1

                    # Set TCP_NODELAY to disable Nagle algorithm
                    # This ensures responses are sent immediately without buffering
                    # Critical for DataGrip and other clients that expect fast responses
                    client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                    # Check connection limit
                    with self._connections_lock:
                        active_count = len(self.active_connections)

                    if self.max_connections > 0 and active_count >= self.max_connections:
                        styled_print(f"\n{S.WARN} Client #{self.client_count} from {addr[0]}:{addr[1]} rejected (limit: {self.max_connections}/{self.max_connections})")
                        # Send PostgreSQL error response before closing
                        try:
                            error_msg = f"too many connections ({active_count}/{self.max_connections})"
                            error_response = ErrorResponse.encode(error_msg, code='53300')  # too_many_connections
                            client_sock.sendall(error_response)
                        except Exception:
                            pass
                        client_sock.close()
                        continue

                    styled_print(f"\n{S.LINK} Client #{self.client_count} connected from {addr[0]}:{addr[1]} ({active_count + 1} active)")

                    # Handle client in separate thread (allows concurrent connections)
                    client = ClientConnection(
                        client_sock,
                        addr,
                        self.session_prefix,
                        server=self,
                        idle_timeout=self.idle_timeout
                    )
                    thread = threading.Thread(
                        target=client.handle,
                        daemon=True,
                        name=f"Client-{self.client_count}"
                    )
                    thread.start()

                except socket.timeout:
                    # Timeout allows checking self.running flag
                    continue

        except KeyboardInterrupt:
            # Signal handler should have been called, but handle just in case
            if shutdown_count[0] == 0:
                signal_handler(signal.SIGINT, None)

        except Exception as e:
            styled_print(f"\n{S.ERR} Server error: {e}")
            traceback.print_exc()

        finally:
            # Restore original signal handlers
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

            sock.close()
            self.running = False
            styled_print(f"{S.DONE} Server stopped")


def start_postgres_server(
    host='0.0.0.0',
    port=5432,
    session_prefix='pg_client',
    listen_backlog=1024,
    max_connections=0,
    idle_timeout=0,
    pool_size=16,
):
    """
    Start LARS PostgreSQL wire protocol server.

    Args:
        host: Host to listen on (default: 0.0.0.0 = all interfaces)
        port: Port to listen on (default: 5432 = standard PostgreSQL)
        session_prefix: Prefix for DuckDB session IDs (default: 'pg_client')
        listen_backlog: Socket listen backlog (default: 1024)
        max_connections: Maximum concurrent connections (0 = unlimited)
        idle_timeout: Disconnect idle clients after N seconds (0 = no timeout)
        pool_size: Number of pre-warmed DuckDB connections (default: 16)

    Example:
        # Start server
        start_postgres_server(port=5433)

        # Connect from psql
        $ psql postgresql://localhost:5433/default

        # Query with LLM UDFs!
        default=> SELECT lars_udf('Extract brand', 'Apple iPhone') as brand;
         brand
        -------
         Apple
        (1 row)
    """
    import os
    import time
    
    # Set pool size before initializing (connection_pool reads from env)
    os.environ['LARS_POOL_SIZE'] = str(pool_size)
    
    # Pre-warm the connection pool
    try:
        from ..sql_tools.connection_pool import initialize_pool, pool_status
        print(f"[pool] Warming {pool_size} connections in background...")
        initialize_pool()
        
        # Wait briefly for some connections to warm, then report status
        time.sleep(0.5)
        status = pool_status()
        print(f"[pool] Status: {status['size']} ready, warming={'yes' if status['warming'] else 'done'}")
    except Exception as e:
        print(f"[warn] Connection pool initialization failed: {e}")
    
    server = LARSPostgresServer(
        host=host,
        port=port,
        session_prefix=session_prefix,
        listen_backlog=listen_backlog,
        max_connections=max_connections,
        idle_timeout=idle_timeout,
    )
    server.start()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='LARS PostgreSQL Wire Protocol Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to listen on')
    parser.add_argument('--port', type=int, default=15432, help='Port to listen on')
    parser.add_argument('--session-prefix', default='pg_client', help='Session ID prefix')
    parser.add_argument('--listen-backlog', type=int, default=1024, help='Socket listen backlog (default: 1024)')
    parser.add_argument('--max-connections', type=int, default=0, help='Max concurrent connections (0 = unlimited)')
    parser.add_argument('--idle-timeout', type=int, default=0, help='Idle connection timeout in seconds (0 = disabled)')
    args = parser.parse_args()

    start_postgres_server(
        host=args.host,
        port=args.port,
        session_prefix=args.session_prefix,
        listen_backlog=args.listen_backlog,
        max_connections=args.max_connections,
        idle_timeout=args.idle_timeout,
    )
