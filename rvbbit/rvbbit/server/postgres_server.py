"""
PostgreSQL wire protocol server for RVBBIT.

This server accepts connections from any PostgreSQL client (DBeaver, psql, DataGrip, Tableau)
and executes queries on RVBBIT session DuckDB with rvbbit_udf() and rvbbit_cascade_udf().

Each client connection gets its own isolated DuckDB session with:
- rvbbit_udf() registered (simple LLM UDF)
- rvbbit_cascade_udf() registered (full cascade per row)
- Temp tables (session-scoped)
- ATTACH support (connect to external databases)

Usage:
    from rvbbit.server.postgres_server import start_postgres_server

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
from threading import Lock
from typing import Optional

from .postgres_protocol import (
    PostgresMessage,
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
    NoData
)


class ClientConnection:
    """
    Represents a single client connection.

    Each client gets:
    - Unique session ID
    - Isolated DuckDB session
    - RVBBIT UDFs registered
    - Dedicated socket
    """

    def __init__(self, sock, addr, session_prefix='pg_client'):
        self.sock = sock
        self.addr = addr
        self.session_id = None  # Will be set in handle_startup based on database name
        self.session_prefix = session_prefix
        self.database_name = 'default'  # Logical database name from client connection
        self.user_name = 'rvbbit'       # Logical user name from client connection
        self.application_name = 'unknown'
        self.is_persistent_db = False   # True if using persistent DuckDB file
        self.duckdb_conn = None
        self.db_lock = None  # Lock for thread-safe DuckDB access
        self.running = True
        self.query_count = 0
        self.transaction_status = 'I'  # 'I' = idle, 'T' = in transaction, 'E' = error

        # Extended Query Protocol state
        self.prepared_statements = {}  # name → {query, param_types, param_count}
        self.portals = {}               # name → {statement_name, params, result_formats, query}

        # Lazy attach manager (initialized in setup_session)
        self._lazy_attach = None
        self._duckdb_catalog_name = None

        # Cache: last seen attached database set (to refresh views after lazy ATTACH)
        self._last_attached_db_names = set()

    def setup_session(self):
        """
        Create DuckDB session and register RVBBIT UDFs.

        This is called once per client connection.
        The session persists for the lifetime of the connection.

        Database routing:
        - 'memory' or 'default' → in-memory DuckDB (per-client, ephemeral)
        - Any other name → persistent file at session_dbs/{database}.duckdb

        Persistent databases survive restarts and are shared across connections.
        """
        try:
            import duckdb
            from ..sql_tools.udf import register_rvbbit_udf
            from ..config import get_config

            # Determine if this is a persistent or in-memory database
            if self.database_name.lower() in ('memory', 'default', ':memory:'):
                # In-memory database - ephemeral, per-client
                self.is_persistent_db = False
                self.duckdb_conn = duckdb.connect(':memory:')
                self.db_lock = Lock()  # Per-connection lock (not shared)
                print(f"[{self.session_id}]   📦 In-memory database (ephemeral)")
            else:
                # Persistent database - file-based, shared across connections
                self.is_persistent_db = True
                config = get_config()
                db_dir = os.path.join(config.root_dir, 'session_dbs')
                os.makedirs(db_dir, exist_ok=True)

                # Sanitize database name for filename
                safe_db_name = self.database_name.replace("/", "_").replace("\\", "_").replace("..", "_")
                db_path = os.path.join(db_dir, f"{safe_db_name}.duckdb")

                # Each client gets its own connection to the same file
                # DuckDB handles internal locking for concurrent access
                self.duckdb_conn = duckdb.connect(db_path)
                self.db_lock = Lock()  # Per-connection lock for thread safety

                # Check if this is a new or existing database
                is_new = not os.path.exists(db_path) or os.path.getsize(db_path) == 0
                if is_new:
                    print(f"[{self.session_id}]   📁 Created persistent database: {safe_db_name}")
                else:
                    print(f"[{self.session_id}]   📂 Opened persistent database: {safe_db_name}")

            # Cache DuckDB's internal catalog name (filename base or 'memory')
            try:
                self._duckdb_catalog_name = self.duckdb_conn.execute("SELECT current_database()").fetchone()[0]
            except Exception:
                self._duckdb_catalog_name = None

            # Configure DuckDB
            self.duckdb_conn.execute("SET threads TO 4")

            # Reset our transaction status to idle
            self.transaction_status = 'I'

            # DataGrip/PostgreSQL clients frequently schema-qualify functions as pg_catalog.func(...),
            # but DuckDB parses that as a column reference. We register unqualified compat macros
            # and later strip the pg_catalog. prefix for function calls at execution time.
            try:
                self.duckdb_conn.execute("CREATE OR REPLACE MACRO pg_get_userbyid(x) AS 'rvbbit'")
                self.duckdb_conn.execute("CREATE OR REPLACE MACRO txid_current() AS (epoch_ms(now())::BIGINT % 4294967296)")
                self.duckdb_conn.execute("CREATE OR REPLACE MACRO pg_is_in_recovery() AS false")
                self.duckdb_conn.execute("CREATE OR REPLACE MACRO pg_tablespace_location(x) AS NULL")
            except Exception:
                pass

            # Register RVBBIT UDFs (rvbbit_udf + rvbbit_cascade_udf + hardcoded aggregates)
            register_rvbbit_udf(self.duckdb_conn)

            # Register dynamic SQL functions from cascade registry (SUMMARIZE_URLS, etc.)
            from ..sql_tools.udf import register_dynamic_sql_functions
            register_dynamic_sql_functions(self.duckdb_conn)

            # Lazy ATTACH: configured sql_connections/*.json attached on first reference.
            # Non-fatal if config loading fails.
            try:
                from ..sql_tools.config import load_sql_connections
                from ..sql_tools.lazy_attach import LazyAttachManager
                self._lazy_attach = LazyAttachManager(self.duckdb_conn, load_sql_connections())
            except Exception:
                self._lazy_attach = None

            # DuckDB v1.4.2+ has built-in pg_catalog support
            print(f"[{self.session_id}]   ℹ️  Using DuckDB's built-in pg_catalog (v1.4.2+)")

            # Create metadata table for tracking ATTACH commands (persistent DBs only)
            self._create_attachments_metadata_table()

            # Create registry table for auto-materialized RVBBIT query results
            self._create_results_registry_table()

            # Replay any previously attached databases from metadata
            self._replay_attachments()

            # Create views for ATTACH'd databases so they appear in DBeaver
            self._create_attached_db_views()

            # Register UDF to refresh views after manual ATTACH
            self._register_refresh_views_udf()

            print(f"[{self.session_id}] ✓ Session ready (database: {self.database_name})")

        except Exception as e:
            print(f"[{self.session_id}] ✗ Error setting up session: {e}")
            raise

    def _execute_locked(self, query: str):
        """
        Execute a query on DuckDB with thread-safe locking.

        CRITICAL: DuckDB connections are NOT thread-safe. Multiple clients
        sharing the same session connection can cause segfaults without locking.
        """
        with self.db_lock:
            return self.duckdb_conn.execute(query)

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
        """
        import re

        # Replace tablealias.xmin with a stable constant
        query = re.sub(r'(?i)\b[a-zA-Z_][a-zA-Z0-9_]*\.xmin\b', '0', query)

        # Replace missing pg_class column (Postgres-only) with a stable constant
        query = re.sub(r'(?i)\b[a-zA-Z_][a-zA-Z0-9_]*\.relforcerowsecurity\b', 'false', query)

        return query

    @staticmethod
    def _quote_ident(name: str) -> str:
        return f'"{name.replace(chr(34), chr(34) * 2)}"'

    def _rewrite_information_schema_catalog_filters(self, query: str) -> str:
        """
        Restrict `information_schema` catalog views to the current DuckDB database.

        DuckDB's information_schema.* surfaces attached database catalogs, which can confuse
        PostgreSQL clients (DataGrip shows them as FDW/foreign catalogs). Postgres exposes only
        the connected database, so we filter these queries to the current DuckDB catalog.
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
            alias_candidate = m.group(2)
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

            alias = alias_candidate if alias_candidate and alias_candidate.lower() not in reserved else None
            from_end = m.end(0) if alias else table_ref_end

            qualifier = f"{alias}.{catalog_col}" if alias else catalog_col
            escaped_catalog = catalog.replace("'", "''")
            cond = f"{qualifier} = '{escaped_catalog}'"

            # Find WHERE after the FROM match (avoid CTE/subquery WHEREs earlier in the SQL)
            after_from = query[from_end:]
            w = re.search(r'(?is)\bwhere\b', after_from)
            if w:
                insert_at = from_end + w.end()
                query = query[:insert_at] + f" {cond} AND" + query[insert_at:]
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

    def _create_attachments_metadata_table(self):
        """
        Create metadata table for tracking ATTACH commands.

        This table persists ATTACH statements so they can be replayed when
        a new connection is established to the same database file.

        Only created for persistent databases (not in-memory).
        """
        if not self.is_persistent_db:
            return  # Only for persistent databases

        try:
            # Check if table already exists
            existing = self.duckdb_conn.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = '_rvbbit_attachments'
            """).fetchall()

            if not existing:
                # Create metadata table
                self.duckdb_conn.execute("""
                    CREATE TABLE _rvbbit_attachments (
                        id INTEGER PRIMARY KEY,
                        database_alias VARCHAR NOT NULL,
                        database_path VARCHAR NOT NULL,
                        attached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(database_alias)
                    )
                """)

                # Create sequence for auto-incrementing IDs
                self.duckdb_conn.execute("""
                    CREATE SEQUENCE _rvbbit_attachments_seq START 1
                """)

                print(f"[{self.session_id}]   ✅ Created _rvbbit_attachments metadata table")
        except Exception as e:
            # Non-fatal - just log the error
            print(f"[{self.session_id}]   ⚠️  Could not create attachments metadata table: {e}")

    def _create_results_registry_table(self):
        """
        Create registry table for tracking auto-materialized RVBBIT query results.

        RVBBIT queries (cascades, UDFs, semantic operators) are expensive and
        non-deterministic. Auto-materializing their results provides "query insurance"
        so users don't lose expensive work if their connection drops or client crashes.

        Results are organized into date-based schemas for easy discovery and cleanup:
        - _results_20250103.q_abc12345 (query result table)
        - _rvbbit_results (registry of all materialized results)

        Only created for persistent databases (not in-memory).
        """
        if not self.is_persistent_db:
            return  # Only for persistent databases

        try:
            # Check if registry table already exists
            existing = self.duckdb_conn.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = '_rvbbit_results'
            """).fetchall()

            if not existing:
                # Create registry table
                self.duckdb_conn.execute("""
                    CREATE TABLE _rvbbit_results (
                        query_id VARCHAR PRIMARY KEY,
                        schema_name VARCHAR NOT NULL,
                        table_name VARCHAR NOT NULL,
                        full_table_name VARCHAR NOT NULL,
                        query_fingerprint VARCHAR,
                        row_count INTEGER,
                        column_count INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                print(f"[{self.session_id}]   ✅ Created _rvbbit_results registry table")
        except Exception as e:
            # Non-fatal - just log the error
            print(f"[{self.session_id}]   ⚠️  Could not create results registry table: {e}")

    def _maybe_materialize_result(self, query: str, result_df, query_id: str = None):
        """
        Auto-materialize RVBBIT query results for "query insurance".

        This saves expensive LLM-powered query results to a date-based schema
        so users can recover them if their connection drops or client crashes.

        Args:
            query: The original SQL query
            result_df: The pandas DataFrame result
            query_id: Optional query ID for naming (generated if not provided)

        Returns:
            Dict with result location info if materialized:
            {
                'db_name': database name,
                'db_path': full path to DuckDB file,
                'schema_name': schema within DuckDB,
                'table_name': table within schema
            }
            Returns None if not materialized.
        """
        import pandas as pd
        from datetime import datetime

        # Skip if not a persistent database
        if not self.is_persistent_db:
            return None

        # Skip if empty results
        if result_df is None or len(result_df) == 0:
            return None

        # Skip if results are too large (configurable threshold)
        max_rows = 100000  # Could make this configurable
        if len(result_df) > max_rows:
            print(f"[{self.session_id}]   ⚠️  Skipping auto-materialize: {len(result_df)} rows > {max_rows} limit")
            return None

        try:
            # Generate query ID if not provided
            if not query_id:
                query_id = uuid.uuid4().hex[:12]
            else:
                # Use last 12 chars of existing query_id
                query_id = query_id[-12:] if len(query_id) > 12 else query_id

            # Create date-based schema name
            date_str = datetime.now().strftime('%Y%m%d')
            schema_name = f"_results_{date_str}"
            table_name = f"q_{query_id}"
            full_table_name = f"{schema_name}.{table_name}"

            # Create schema if not exists
            self.duckdb_conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")

            # Register DataFrame and create table
            temp_name = f"_temp_materialize_{query_id}"
            self.duckdb_conn.register(temp_name, result_df)
            self.duckdb_conn.execute(f"CREATE TABLE {full_table_name} AS SELECT * FROM {temp_name}")
            self.duckdb_conn.unregister(temp_name)

            # Create query fingerprint (first 200 chars, normalized)
            query_fingerprint = ' '.join(query.split())[:200]

            # Log to registry
            self.duckdb_conn.execute("""
                INSERT INTO _rvbbit_results
                (query_id, schema_name, table_name, full_table_name, query_fingerprint, row_count, column_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [query_id, schema_name, table_name, full_table_name, query_fingerprint, len(result_df), len(result_df.columns)])

            # Get the full database path for SQL Trail logging
            from ..config import get_config
            config = get_config()
            safe_db_name = self.database_name.replace("/", "_").replace("\\", "_").replace("..", "_")
            db_path = os.path.join(config.root_dir, 'session_dbs', f"{safe_db_name}.duckdb")

            # Also export to Parquet for cross-process access (DuckDB has file-level locks)
            parquet_dir = os.path.join(config.root_dir, 'session_dbs', '.results_cache')
            os.makedirs(parquet_dir, exist_ok=True)
            parquet_path = os.path.join(parquet_dir, f"{safe_db_name}_{schema_name}_{table_name}.parquet")
            try:
                result_df.to_parquet(parquet_path, index=False)
            except Exception as parquet_err:
                # Non-fatal - DuckDB table is still available
                print(f"[{self.session_id}]   ⚠️  Parquet export failed: {parquet_err}")

            print(f"[{self.session_id}]   💾 Auto-materialized: {full_table_name} ({len(result_df)} rows, {len(result_df.columns)} cols)")

            return {
                'db_name': self.database_name,
                'db_path': db_path,
                'schema_name': schema_name,
                'table_name': table_name
            }

        except Exception as e:
            # Non-fatal - log and continue
            print(f"[{self.session_id}]   ⚠️  Auto-materialize failed: {e}")
            return None

    def _extract_rvbbit_hints(self, query: str) -> tuple:
        """
        Extract RVBBIT hint comments from query.

        Hints are embedded as /*RVBBIT:key=value*/ comments by the sql_rewriter.
        This method extracts them and returns a clean query for execution.

        Returns:
            (clean_query, hints_dict) where hints_dict contains extracted hints

        Example:
            Input:  "/*RVBBIT:save_as=players*/ SELECT * FROM emails"
            Output: ("SELECT * FROM emails", {"save_as": "players"})
        """
        import re
        hints = {}

        # Match /*RVBBIT:key=value*/ patterns
        # Value can be identifier or dotted identifier (schema.table)
        pattern = r'/\*RVBBIT:(\w+)=([a-zA-Z_][a-zA-Z0-9_.]*)\*/'

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
            print(f"[{self.session_id}]   ⚠️  Arrow save skipped: empty result")
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
            temp_name = f"_rvbbit_arrow_{hash(name) & 0xFFFFFF:06x}"
            self.duckdb_conn.register(temp_name, result_df)

            try:
                # Drop existing table if any, then create new one
                self.duckdb_conn.execute(f"DROP TABLE IF EXISTS {full_name}")
                self.duckdb_conn.execute(f"CREATE TABLE {full_name} AS SELECT * FROM {temp_name}")
                print(f"[{self.session_id}]   📌 Arrow saved: {full_name} ({len(result_df)} rows, {len(result_df.columns)} cols)")
            finally:
                self.duckdb_conn.unregister(temp_name)

        except Exception as e:
            print(f"[{self.session_id}]   ⚠️  Arrow save failed for '{name}': {e}")

    def _replay_attachments(self):
        """
        Re-execute ATTACH commands from metadata table.

        Called on session startup to restore previously attached databases.
        If an attached file no longer exists, it's removed from metadata.
        """
        if not self.is_persistent_db:
            return  # Only for persistent databases

        try:
            # Check if metadata table exists
            tables = self.duckdb_conn.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = '_rvbbit_attachments'
            """).fetchall()

            if not tables:
                return  # No attachments to replay

            # Get all stored attachments
            attachments = self.duckdb_conn.execute("""
                SELECT database_alias, database_path
                FROM _rvbbit_attachments
                ORDER BY id
            """).fetchall()

            if not attachments:
                return

            print(f"[{self.session_id}]   🔗 Replaying {len(attachments)} ATTACH command(s)...")

            replayed_count = 0
            failed_count = 0

            for alias, path in attachments:
                try:
                    # Re-execute ATTACH
                    self.duckdb_conn.execute(f"ATTACH '{path}' AS {alias}")
                    print(f"[{self.session_id}]      ✓ ATTACH '{path}' AS {alias}")
                    replayed_count += 1
                except Exception as e:
                    # File might not exist anymore - remove from metadata
                    try:
                        self.duckdb_conn.execute(
                            "DELETE FROM _rvbbit_attachments WHERE database_alias = ?",
                            [alias]
                        )
                        print(f"[{self.session_id}]      ⚠️  Could not replay ATTACH {alias}: {e}")
                        print(f"[{self.session_id}]         Removed from metadata (file may have been deleted)")
                        failed_count += 1
                    except:
                        pass

            if replayed_count > 0:
                print(f"[{self.session_id}]   ✅ Replayed {replayed_count} ATTACH command(s)")
            if failed_count > 0:
                print(f"[{self.session_id}]   ⚠️  {failed_count} ATTACH command(s) failed (files removed)")

        except Exception as e:
            # Non-fatal - just log the error
            print(f"[{self.session_id}]   ⚠️  Could not replay attachments: {e}")

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
        print(f"[{self.session_id}]   🔧 Starting pg_catalog view creation...")
        try:
            # NOTE: DuckDB treats 'pg_catalog' as a reserved system schema
            # We create views in 'main' schema but query them as 'pg_catalog.xyz'
            # DuckDB will automatically search 'main' when 'pg_catalog' doesn't have the object

            # pg_namespace - Schemas/namespaces
            print(f"[{self.session_id}]      Creating pg_namespace view...")
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
            print(f"[{self.session_id}]      ✓ pg_namespace created")

            # pg_class - Tables, views, sequences, indexes
            self.duckdb_conn.execute("""
                CREATE OR REPLACE VIEW main.pg_pg_class AS
                SELECT
                    table_name as relname,
                    0 as relnamespace,
                    CASE table_type
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
                FROM information_schema.tables
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
                    'rvbbit_udf' as proname,
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
                    'PostgreSQL-compatible server (RVBBIT/DuckDB)' as category,
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

            print(f"[{self.session_id}]   ✅ ALL pg_catalog views created successfully!")
            print(f"[{self.session_id}]   ✅ Schema introspection is now ENABLED")

        except Exception as e:
            # Non-fatal - catalog views are nice-to-have
            print(f"[{self.session_id}]   ❌ ERROR creating pg_catalog views: {e}")
            import traceback
            traceback.print_exc()
            print(f"[{self.session_id}]   ⚠️  Schema introspection will NOT work!")

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
                print(f"[{self.session_id}]   🧹 Cleaned up {dropped_count} orphaned views (DETACH'd databases)")

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
            print(f"[{self.session_id}]   ⚠️  Could not cleanup orphaned views: {e}")

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
                print(f"[{self.session_id}]   ℹ️  No ATTACH'd databases to expose")
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
                print(f"[{self.session_id}]   ✅ Exposed {view_count} relation(s) from ATTACH'd databases")
            else:
                print(f"[{self.session_id}]   ℹ️  No tables found in ATTACH'd databases")

        except Exception as e:
            # Non-fatal - ATTACH views are nice-to-have
            print(f"[{self.session_id}]   ⚠️  Could not create ATTACH'd DB views: {e}")

    def _handle_attach(self, query: str):
        """
        Handle ATTACH command - execute and persist to metadata.

        Parses ATTACH statement, executes it on DuckDB, stores metadata for
        persistence, and creates views for the attached database's tables.

        Args:
            query: ATTACH statement (e.g., "ATTACH '/path/db.duckdb' AS my_db")
        """
        import re

        print(f"[{self.session_id}]   🔗 ATTACH command detected")

        # Parse ATTACH statement
        # Handles: ATTACH '/path' AS alias, ATTACH DATABASE '/path' AS alias, ATTACH '/path' (alias = filename)
        match = re.search(r"ATTACH\s+(?:DATABASE\s+)?['\"]([^'\"]+)['\"](?:\s+AS\s+(\w+))?", query, re.IGNORECASE)

        if not match:
            send_error(self.sock, "Could not parse ATTACH statement", transaction_status=self.transaction_status)
            print(f"[{self.session_id}]   ✗ Could not parse ATTACH statement")
            return

        db_path = match.group(1)
        db_alias = match.group(2)

        # If no alias provided, DuckDB uses filename without extension
        if not db_alias:
            import os
            db_alias = os.path.splitext(os.path.basename(db_path))[0]

        try:
            # 1. Execute ATTACH
            self.duckdb_conn.execute(query)
            print(f"[{self.session_id}]      ✓ Attached: {db_path} AS {db_alias}")

            # 2. Store in metadata (only for persistent databases)
            if self.is_persistent_db:
                try:
                    # Delete if exists, then insert (simpler than INSERT OR REPLACE)
                    self.duckdb_conn.execute(
                        "DELETE FROM _rvbbit_attachments WHERE database_alias = ?",
                        [db_alias]
                    )
                    self.duckdb_conn.execute("""
                        INSERT INTO _rvbbit_attachments (id, database_alias, database_path)
                        VALUES (nextval('_rvbbit_attachments_seq'), ?, ?)
                    """, [db_alias, db_path])
                    print(f"[{self.session_id}]      ✓ Stored in metadata")
                except Exception as e:
                    print(f"[{self.session_id}]      ⚠️  Could not store metadata: {e}")

            # 3. Create views for attached database tables
            self._create_attached_db_views()

            # 4. Send success response
            self.sock.sendall(CommandComplete.encode('ATTACH'))
            self.sock.sendall(ReadyForQuery.encode('I'))
            print(f"[{self.session_id}]   ✅ ATTACH complete")

        except Exception as e:
            error_message = str(e)
            send_error(self.sock, error_message, transaction_status=self.transaction_status)
            print(f"[{self.session_id}]   ✗ ATTACH error: {error_message}")

    def _handle_detach(self, query: str):
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
            print(f"[{self.session_id}]   🗑️  DETACH {db_name} - cleaning up...")

            # Remove from metadata table (persistent databases only)
            if self.is_persistent_db:
                try:
                    deleted = self.duckdb_conn.execute(
                        "DELETE FROM _rvbbit_attachments WHERE database_alias = ?",
                        [db_name]
                    )
                    print(f"[{self.session_id}]      🗑️  Removed from metadata")
                except Exception as e:
                    print(f"[{self.session_id}]      ⚠️  Could not remove metadata: {e}")

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
                    print(f"[{self.session_id}]      🧹 Dropped {dropped_count} views for {db_name}")

            except Exception as e:
                print(f"[{self.session_id}]      ⚠️  Could not cleanup views: {e}")

        # Execute the actual DETACH command
        try:
            self.duckdb_conn.execute(query)
            self.sock.sendall(CommandComplete.encode('DETACH'))
            self.sock.sendall(ReadyForQuery.encode('I'))
            print(f"[{self.session_id}]   ✓ DETACH executed")

        except Exception as e:
            error_message = str(e)
            send_error(self.sock, error_message, transaction_status=self.transaction_status)
            print(f"[{self.session_id}]   ✗ DETACH error: {error_message}")

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
            print(f"[{self.session_id}]   ✅ Registered refresh_attached_views() UDF")

        except Exception as e:
            # "already created" is expected when multiple connections share DuckDB
            if "already created" in str(e).lower():
                pass  # Silently skip - UDF is already there
            else:
                print(f"[{self.session_id}]   ⚠️  Could not register refresh UDF: {e}")

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
                        'rvbbit'::VARCHAR as usename,
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
                    CREATE OR REPLACE MACRO pg_catalog.pg_is_in_recovery() AS false
                """)
                stubs_created.append("pg_is_in_recovery()")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    pass

            # txid_current() - Current transaction ID (use timestamp-based fake)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_catalog.txid_current() AS
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
                    CREATE OR REPLACE MACRO pg_catalog.pg_backend_pid() AS {pid}
                """)
                stubs_created.append("pg_backend_pid()")
            except Exception as e:
                pass

            # pg_current_xact_id() - Alias for txid_current (newer PG versions)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE MACRO pg_catalog.pg_current_xact_id() AS
                        (epoch_ms(now())::BIGINT % 4294967296)
                """)
                stubs_created.append("pg_current_xact_id()")
            except Exception as e:
                pass

            if stubs_created:
                print(f"[{self.session_id}]   ✅ Created PG compat stubs: {', '.join(stubs_created)}")

        except Exception as e:
            print(f"[{self.session_id}]   ⚠️  Error creating PG compat stubs: {e}")

    def handle_startup(self, startup_params: dict):
        """
        Handle client startup message.

        Extracts database name and username from startup params.
        Sets up consistent session_id for persistent database.

        Database routing:
        - 'memory' or 'default' → in-memory DuckDB (ephemeral)
        - Any other name → persistent file at session_dbs/{database}.duckdb
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
            or 'rvbbit'
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

        if os.environ.get('RVBBIT_PG_LOG_STARTUP_PARAMS') == '1':
            print(f"[{self.session_id or self.addr}]   🔎 Startup params: {startup_params}")

        # Store database name for session setup
        self.database_name = database

        # Create unique session_id per client connection
        # Each client needs its own connection for thread safety
        client_id = uuid.uuid4().hex[:8]
        self.session_id = f"{self.session_prefix}_{database}_{client_id}"

        # Determine persistence mode
        is_persistent = database.lower() not in ('memory', 'default', ':memory:')
        mode_icon = "📂" if is_persistent else "📦"
        mode_text = "persistent" if is_persistent else "in-memory"

        print(f"[{self.session_id}] 🔌 Client startup:")
        print(f"   User: {user}")
        print(f"   Database: {database} ({mode_text}) {mode_icon}")
        print(f"   Application: {application_name}")

        # Note: send_startup_response is called AFTER setup_session in handle()

    def handle_query(self, query: str):
        """
        Execute query on DuckDB and send results to client.

        Args:
            query: SQL query string (may include rvbbit_udf(), rvbbit_cascade_udf())
        """
        self.query_count += 1

        # Clean query (remove null terminators, whitespace)
        query = query.strip()

        # Handle empty queries (PostgreSQL protocol requirement)
        # Some clients (like DataGrip) send empty queries for protocol probing
        if not query:
            print(f"[{self.session_id}] Query #{self.query_count}: (empty)")
            self.sock.sendall(EmptyQueryResponse.encode())
            self.sock.sendall(ReadyForQuery.encode(self.transaction_status))
            return

        # Log query (show more for catalog queries)
        is_catalog = self._is_catalog_query(query.upper())
        if is_catalog:
            print(f"[{self.session_id}] Query #{self.query_count} [CATALOG]: {query[:200]}{'...' if len(query) > 200 else ''}")
        else:
            print(f"[{self.session_id}] Query #{self.query_count}: {query[:100]}{'...' if len(query) > 100 else ''}")

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

            # Handle ANALYZE queries (async execution + LLM analysis)
            # Syntax: ANALYZE 'prompt here' SELECT * FROM table;
            # Token-based parsing handles newlines and whitespace properly
            if query_upper.startswith('ANALYZE'):
                from ..sql_tools.sql_directives import parse_sql_directives
                directive, inner_sql = parse_sql_directives(query)
                if directive and directive.directive_type == 'ANALYZE':
                    # Reconstruct format expected by _handle_analyze_query
                    # (it expects to parse the prompt itself for backwards compatibility)
                    reconstructed = f"'{directive.prompt}' {inner_sql}"
                    self._handle_analyze_query(reconstructed)
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

            # Set caller context for RVBBIT queries (enables cost tracking and debugging)
            from rvbbit.sql_rewriter import rewrite_rvbbit_syntax, _is_rvbbit_statement, _is_map_run_statement
            _current_query_id = None
            _query_start_time = None

            if _is_rvbbit_statement(query):
                from rvbbit.session_naming import generate_woodland_id
                from rvbbit.caller_context import set_caller_context, build_sql_metadata

                caller_id = f"sql-{generate_woodland_id()}"
                metadata = build_sql_metadata(
                    sql_query=query,
                    protocol="postgresql_wire",
                    triggered_by="postgres_server"
                )
                # Set caller context with connection_id for global registry lookup
                set_caller_context(caller_id, metadata, connection_id=self.session_id)
                print(f"[{self.session_id}] 🔗 Set caller_context: {caller_id} → registry[{self.session_id}]")

                # Log query start for SQL Trail analytics
                # fingerprint_query() will detect semantic operators before sqlglot parsing
                import time
                from rvbbit.sql_trail import log_query_start
                _query_start_time = time.time()
                _current_query_id = log_query_start(
                    caller_id=caller_id,
                    query_raw=query,
                    protocol='postgresql_wire'
                )

                # SPECIAL PATH: MAP PARALLEL with true concurrency
                # Only attempt to parse if this is MAP/RUN syntax (not just UDF calls)
                from rvbbit.sql_rewriter import _parse_rvbbit_statement
                if _is_map_run_statement(query):
                    try:
                        # Normalize query first (same as rewrite_rvbbit_syntax does)
                        normalized = query.strip()
                        lines = [line.split('--')[0].strip() for line in normalized.split('\n')]
                        normalized = ' '.join(line for line in lines if line)

                        print(f"[{self.session_id}]      🔍 Parsing normalized query: {normalized[:100]}...")
                        stmt = _parse_rvbbit_statement(normalized)
                        print(f"[{self.session_id}]      ✓ Parsed: mode={stmt.mode}, parallel={stmt.parallel}, as_table={stmt.with_options.get('as_table')}")

                        # SPECIAL PATH 1: MAP PARALLEL (true concurrency)
                        # SPECIAL PATH 2: Table materialization (CREATE TABLE AS or WITH as_table)
                        # Both need server-side handling to avoid DuckDB timing issues

                        if stmt.mode == 'MAP' and (stmt.parallel or stmt.with_options.get('as_table')):
                            is_parallel = stmt.parallel is not None
                            is_materialized = stmt.with_options.get('as_table') is not None

                            if is_parallel and is_materialized:
                                print(f"[{self.session_id}]   🚀 MAP PARALLEL + Materialization: {stmt.parallel} workers → {stmt.with_options['as_table']}")
                            elif is_parallel:
                                print(f"[{self.session_id}]   🚀 MAP PARALLEL detected: {stmt.parallel} workers")
                            else:
                                print(f"[{self.session_id}]   💾 Table materialization: {stmt.with_options['as_table']}")

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
                                print(f"[{self.session_id}]      🔧 DISTINCT applied: {original_count} → {deduped_count} rows ({savings:.0f}% reduction)")

                        if not re.search(r'\bLIMIT\s+\d+', using_query, re.IGNORECASE):
                            using_query += ' LIMIT 1000'  # Safety

                        print(f"[{self.session_id}]      📊 Fetching input rows...")
                        input_df = self.duckdb_conn.execute(using_query).fetchdf()
                        print(f"[{self.session_id}]      ✓ Got {len(input_df)} input rows")

                        # 2. Convert to JSON array for parallel processing
                        import json
                        rows_json = json.dumps(input_df.to_dict('records'))

                        # 3. Execute (parallel or sequential)
                        result_column = stmt.result_alias or stmt.with_options.get('result_column', 'result')

                        if is_parallel:
                            print(f"[{self.session_id}]      ⚡ Executing in parallel ({stmt.parallel} workers)...")
                            from rvbbit.sql_tools.udf import rvbbit_map_parallel_exec

                            result_df = rvbbit_map_parallel_exec(
                                cascade_path=stmt.cascade_path,
                                rows_json_array=rows_json,
                                max_workers=stmt.parallel,
                                result_column=result_column
                            )
                            print(f"[{self.session_id}]      ✓ Parallel execution complete")
                        else:
                            # Sequential execution for non-parallel materialization
                            print(f"[{self.session_id}]      🔄 Executing sequentially for materialization...")
                            # Use the regular rewritten query but execute row-by-row
                            from rvbbit.sql_rewriter import _rewrite_map
                            from dataclasses import replace

                            # Build statement without as_table to get clean execution query
                            temp_stmt_options = dict(stmt.with_options)
                            temp_stmt_options.pop('as_table', None)  # Remove to avoid recursive materialization

                            # Create new statement with modified options
                            temp_stmt = replace(stmt, with_options=temp_stmt_options)

                            print(f"[{self.session_id}]      🔍 Rewriting query without as_table...")
                            rewritten_query = _rewrite_map(temp_stmt)
                            print(f"[{self.session_id}]      🔍 Executing rewritten query...")
                            result_df = self.duckdb_conn.execute(rewritten_query).fetchdf()
                            print(f"[{self.session_id}]      ✓ Sequential execution complete ({len(result_df)} rows)")

                        # 4. Apply schema extraction if specified
                        if stmt.output_columns:
                            print(f"[{self.session_id}]      🔧 Applying schema extraction...")
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
                            print(f"[{self.session_id}]      💾 Materializing to table: {as_table}")
                            # Register and create table
                            self.duckdb_conn.register("_temp_materialize", result_df)
                            self.duckdb_conn.execute(f"CREATE OR REPLACE TEMP TABLE {as_table} AS SELECT * FROM _temp_materialize")
                            self.duckdb_conn.unregister("_temp_materialize")
                            print(f"[{self.session_id}]      ✓ Table created: {as_table}")

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
                            _result_location = self._maybe_materialize_result(query, result_df, _current_query_id)
                            send_query_results(self.sock, result_df, self.transaction_status)

                        if is_parallel and is_materialized:
                            print(f"[{self.session_id}]   ✅ MAP PARALLEL + Materialized: {len(result_df)} rows, {stmt.parallel} workers → {stmt.with_options['as_table']}")
                        elif is_parallel:
                            print(f"[{self.session_id}]   ✅ MAP PARALLEL complete: {len(result_df)} rows, {stmt.parallel} workers")
                        else:
                            print(f"[{self.session_id}]   ✅ Materialized to table: {stmt.with_options['as_table']} ({len(result_df)} rows)")

                        # Log query completion for SQL Trail (special path)
                        # NOTE: Cost/token data is NOT aggregated here - it arrives async via
                        # the cost worker (~3-5s later). The API joins with unified_logs/MV
                        # to get live cost data at query time.
                        if _current_query_id and _query_start_time:
                            try:
                                from rvbbit.sql_trail import (
                                    log_query_complete,
                                    get_cascade_paths, get_cascade_summary, clear_cascade_executions
                                )
                                from rvbbit.caller_context import get_caller_id, clear_caller_context

                                duration_ms = (time.time() - _query_start_time) * 1000
                                caller_id = get_caller_id()

                                # Get cascade execution info
                                cascade_paths = get_cascade_paths(caller_id) if caller_id else []
                                cascade_summary = get_cascade_summary(caller_id) if caller_id else {}

                                # Build result location args if auto-materialized
                                result_kwargs = {}
                                if '_result_location' in dir() and _result_location:
                                    result_kwargs = {
                                        'result_db_name': _result_location.get('db_name'),
                                        'result_db_path': _result_location.get('db_path'),
                                        'result_schema': _result_location.get('schema_name'),
                                        'result_table': _result_location.get('table_name'),
                                    }

                                log_query_complete(
                                    query_id=_current_query_id,
                                    status='completed',
                                    rows_output=len(result_df),
                                    duration_ms=duration_ms,
                                    cascade_paths=cascade_paths,
                                    cascade_count=cascade_summary.get('cascade_count', 0),
                                    **result_kwargs
                                )

                                # Clear cascade tracking and caller context
                                if caller_id:
                                    clear_cascade_executions(caller_id)
                                clear_caller_context(connection_id=self.session_id)
                            except Exception as trail_e:
                                print(f"[{self.session_id}]   ⚠️  SQL Trail log failed: {trail_e}")

                        return  # Skip normal execution path

                    except Exception as parallel_error:
                        # If parallel execution fails, log and fall back to normal path
                        print(f"[{self.session_id}]   ⚠️  Special path failed: {parallel_error}")
                        traceback.print_exc()  # Use module-level import
                        print(f"[{self.session_id}]      Falling back to sequential execution")
                        # Fall through to normal execution

            # Check for prewarm sidecar opportunity (-- @ parallel: N annotation)
            # IMPORTANT: Must run BEFORE rewrite_rvbbit_syntax which strips comments!
            # This launches a background thread to warm the cache for scalar semantic functions
            prewarm_sidecar = None
            original_query = query  # Preserve original with annotations
            print(f"[{self.session_id}]   📋 Prewarm check starting...")
            try:
                from rvbbit.sql_tools.prewarm_sidecar import maybe_launch_prewarm_sidecar
                from rvbbit.caller_context import get_caller_id

                prewarm_caller_id = get_caller_id()
                # If no caller_id but query has parallel annotation, generate one
                if not prewarm_caller_id:
                    from rvbbit.sql_tools.prewarm_sidecar import _get_parallel_annotation
                    if _get_parallel_annotation(original_query):
                        from rvbbit.session_naming import generate_woodland_id
                        prewarm_caller_id = f"prewarm-{generate_woodland_id()}"
                        print(f"[{self.session_id}]   🚀 Prewarm: Generated caller_id {prewarm_caller_id}")

                if prewarm_caller_id:
                    prewarm_sidecar = maybe_launch_prewarm_sidecar(
                        query=original_query,  # Use original query with annotations
                        caller_id=prewarm_caller_id,
                        duckdb_conn=self.duckdb_conn,
                    )
            except Exception as prewarm_e:
                # Prewarm failures are non-fatal
                print(f"[{self.session_id}]   ⚠️  Prewarm check failed: {prewarm_e}")

            # Rewrite RVBBIT MAP/RUN syntax to standard SQL
            # This strips annotations/comments, so prewarm check must happen first
            # Arrow syntax (-> table_name) is converted to hint comments here
            query = rewrite_rvbbit_syntax(query, duckdb_conn=self.duckdb_conn)

            # Extract RVBBIT hints (e.g., save_as from arrow syntax)
            # Hints are embedded as /*RVBBIT:key=value*/ comments
            query, rvbbit_hints = self._extract_rvbbit_hints(query)

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
            _result_location = self._maybe_materialize_result(original_query, result_df, _current_query_id)

            # Arrow syntax: save result as named table if save_as hint present
            if 'save_as' in rvbbit_hints:
                self._save_result_as(rvbbit_hints['save_as'], result_df)

            # Send results back to client (with current transaction status)
            send_query_results(self.sock, result_df, self.transaction_status)

            print(f"[{self.session_id}]   ✓ Returned {len(result_df)} rows")

            # Log query completion for SQL Trail (if we started tracking)
            # NOTE: Cost/token data is NOT aggregated here - it arrives async via
            # the cost worker (~3-5s later). The API joins with unified_logs/MV
            # to get live cost data at query time.
            if _current_query_id and _query_start_time:
                try:
                    from rvbbit.sql_trail import (
                        log_query_complete,
                        get_cascade_paths, get_cascade_summary, clear_cascade_executions
                    )
                    from rvbbit.caller_context import get_caller_id, clear_caller_context

                    duration_ms = (time.time() - _query_start_time) * 1000
                    caller_id = get_caller_id()

                    # Get cascade execution info
                    cascade_paths = get_cascade_paths(caller_id) if caller_id else []
                    cascade_summary = get_cascade_summary(caller_id) if caller_id else {}

                    # Build result location args if auto-materialized
                    result_kwargs = {}
                    if _result_location:
                        result_kwargs = {
                            'result_db_name': _result_location.get('db_name'),
                            'result_db_path': _result_location.get('db_path'),
                            'result_schema': _result_location.get('schema_name'),
                            'result_table': _result_location.get('table_name'),
                        }
                        print(f"[{self.session_id}]   📝 Logging result location to SQL Trail: {result_kwargs}")

                    log_query_complete(
                        query_id=_current_query_id,
                        status='completed',
                        rows_output=len(result_df),
                        duration_ms=duration_ms,
                        cascade_paths=cascade_paths,
                        cascade_count=cascade_summary.get('cascade_count', 0),
                        **result_kwargs
                    )

                    # Clear cascade tracking and caller context
                    if caller_id:
                        clear_cascade_executions(caller_id)
                    clear_caller_context(connection_id=self.session_id)
                except Exception as trail_e:
                    # Note: traceback is imported at module level
                    print(f"[{self.session_id}]   ⚠️  SQL Trail log failed: {trail_e}")
                    traceback.print_exc()

        except Exception as e:
            # Send error to client
            error_message = str(e)
            error_detail = traceback.format_exc()

            # Log query error for SQL Trail
            if _current_query_id and _query_start_time:
                try:
                    from rvbbit.sql_trail import log_query_error
                    from rvbbit.caller_context import clear_caller_context
                    duration_ms = (time.time() - _query_start_time) * 1000
                    log_query_error(
                        query_id=_current_query_id,
                        error_message=error_message,
                        error_type=type(e).__name__,
                        duration_ms=duration_ms,
                    )
                    # Clear caller context to avoid leaking to next query
                    clear_caller_context(connection_id=self.session_id)
                except Exception as trail_e:
                    print(f"[{self.session_id}]   ⚠️  SQL Trail error log failed: {trail_e}")

            # Mark transaction as errored if we were in one
            if self.transaction_status == 'T':
                self.transaction_status = 'E'

            send_error(self.sock, error_message, detail=error_detail, transaction_status=self.transaction_status)

            print(f"[{self.session_id}]   ✗ Query error: {error_message}")

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

        print(f"[{self.session_id}]   📋 Catalog query detected: {query[:80]}...")

        try:
            # ACL aggregation queries (DataGrip) often UNION tablespace + database ACLs.
            # DuckDB's pg_database lacks datacl, so return an empty but correctly-shaped result.
            if 'PG_TABLESPACE' in query_upper and 'PG_DATABASE' in query_upper and 'DATACL' in query_upper:
                cols = self._expected_result_columns(query) or ['object_id', 'acl']
                send_query_results(self.sock, self._empty_df_for_columns(cols), self.transaction_status)
                print(f"[{self.session_id}]   ✓ ACL union catalog query handled (empty)")
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

                db_description = 'RVBBIT Persistent Database' if self.is_persistent_db else 'RVBBIT In-Memory Database'
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
                print(f"[{self.session_id}]   ✓ pg_database → {self.database_name}")
                return

            # PRIORITY: pg_namespace queries FIRST (before CURRENT_SCHEMA which they may contain)
            # DataGrip schema listing queries contain current_schema() but need full schema list
            if 'PG_NAMESPACE' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]   🔧 Handling pg_namespace query for schema browser...")
                try:
                    # Prefer DuckDB's built-in pg_catalog when possible (keeps types and OIDs consistent)
                    try:
                        direct_df = self.duckdb_conn.execute(self._rewrite_pg_catalog_function_calls(query)).fetchdf()
                        send_query_results(self.sock, direct_df, self.transaction_status)
                        print(f"[{self.session_id}]   ✅ pg_namespace executed natively ({len(direct_df)} rows)")
                        return
                    except Exception:
                        pass

                    # DataGrip's schema browser query references columns DuckDB doesn't expose
                    # on pg_namespace (e.g., xmin). Provide a compatible projection while
                    # preserving DuckDB's *real* schema OIDs so joins against pg_class work.
                    schema_rows = self.duckdb_conn.execute(
                        "SELECT oid, nspname, nspowner FROM pg_catalog.pg_namespace"
                    ).fetchdf()

                    # Shape to match common DataGrip query:
                    #   N.oid::bigint as id,
                    #   N.xmin as state_number,
                    #   nspname as name,
                    #   D.description,
                    #   pg_get_userbyid(N.nspowner) as owner
                    result_df = pd.DataFrame({
                        'id': schema_rows['oid'].astype('int64'),
                        'state_number': 0,
                        'name': schema_rows['nspname'].astype(str),
                        'description': None,
                        'owner': self.user_name,
                    })

                    # Ensure pg_catalog + information_schema appear (some clients expect them)
                    existing = set(result_df['name'].tolist())
                    if 'pg_catalog' not in existing:
                        result_df = pd.concat([result_df, pd.DataFrame([{
                            'id': 11,
                            'state_number': 0,
                            'name': 'pg_catalog',
                            'description': 'System catalog',
                            'owner': self.user_name,
                        }])], ignore_index=True)
                    if 'information_schema' not in existing:
                        result_df = pd.concat([result_df, pd.DataFrame([{
                            'id': 12,
                            'state_number': 0,
                            'name': 'information_schema',
                            'description': 'Information schema',
                            'owner': self.user_name,
                        }])], ignore_index=True)

                    result_df = result_df.sort_values('name').reset_index(drop=True)

                    # Debug: show what schemas we found
                    print(f"[{self.session_id}]   📋 Schemas found:")
                    for _, row in result_df.head(10).iterrows():
                        print(f"[{self.session_id}]      - {row['name']} (id={row['id']})")

                    send_query_results(self.sock, result_df, self.transaction_status)
                    print(f"[{self.session_id}]   ✅ pg_namespace handled ({len(result_df)} schemas)")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]   ⚠️  Could not handle pg_namespace: {e}")
                    # Fall through to default handler

            # Simple function handlers (AFTER pg_namespace to not intercept schema queries)
            # Skip if this is a pg_database or pg_namespace query
            if 'CURRENT_DATABASE()' in query_upper and 'PG_DATABASE' not in query_upper and 'PG_NAMESPACE' not in query_upper:
                cols = self._expected_result_columns(query) or ['current_database']
                row = {}
                for c in cols:
                    key = c.strip('"').lower()
                    if key in {'current_database', 'current_database()'}:
                        row[c] = self.database_name
                    elif key in {'current_schema', 'current_schema()'}:
                        row[c] = 'main'
                    elif key in {'current_user', 'session_user'}:
                        row[c] = self.user_name
                    else:
                        row[c] = None
                result_df = pd.DataFrame({c: [row[c]] for c in cols})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ CURRENT_DATABASE() → {self.database_name}")
                return

            # Skip if this is a pg_namespace query (which may use current_schema() in WHERE)
            if ('CURRENT_SCHEMA()' in query_upper or 'CURRENT_SCHEMAS(' in query_upper) and 'PG_NAMESPACE' not in query_upper:
                if 'SESSION_USER' in query_upper:
                    result_df = pd.DataFrame({'current_schema': ['main'], 'session_user': ['rvbbit']})
                else:
                    result_df = pd.DataFrame({'current_schema': ['main']})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ CURRENT_SCHEMA() handled")
                return

            if 'VERSION()' in query_upper:
                # Get DuckDB version
                try:
                    import duckdb
                    duckdb_version = duckdb.__version__
                except Exception:
                    duckdb_version = "unknown"

                version_str = f"RVBBIT 0.1 PGwire (DuckDB {duckdb_version} engine, PG 14.0 compat)"
                result_df = pd.DataFrame({'version': [version_str]})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ VERSION() → {version_str}")
                return

            if 'HAS_TABLE_PRIVILEGE' in query_upper or 'HAS_SCHEMA_PRIVILEGE' in query_upper:
                result_df = pd.DataFrame({'has_privilege': [True]})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ HAS_PRIVILEGE function handled")
                return

            # Special case 4: PostgreSQL functions that don't exist in DuckDB
            if 'PG_GET_KEYWORDS' in query_upper:
                # Dynamically build keyword list from SQL function registry
                # catcode: U=unreserved, R=reserved, T=type, C=column
                keywords = set()

                # Core RVBBIT keywords (always present)
                keywords.add('rvbbit')
                keywords.add('map')

                # Get keywords from registered SQL functions
                try:
                    from rvbbit.semantic_sql.registry import get_sql_function_registry
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
                    print(f"[{self.session_id}]   ⚠️  Could not load SQL registry: {e}")

                # Build result DataFrame
                rvbbit_keywords = [(word, 'U', 'unreserved (RVBBIT)') for word in sorted(keywords)]
                result_df = pd.DataFrame(rvbbit_keywords, columns=['word', 'catcode', 'catdesc'])
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ PG_GET_KEYWORDS() → {len(rvbbit_keywords)} RVBBIT keywords")
                return

            # Special case 5: pg_locks (DataGrip queries this for transaction info)
            if 'PG_LOCKS' in query_upper:
                # Return empty result - we don't track locks
                result_df = pd.DataFrame({'transaction_id': pd.Series([], dtype='int64')})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ pg_locks handled (empty)")
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
                print(f"[{self.session_id}]   ✓ pg_is_in_recovery() handled (false)")
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
                print(f"[{self.session_id}]   ✓ pg_stat_activity handled")
                return

            # Handle pg_timezone_names/pg_timezone_abbrevs (DataGrip queries these)
            if 'PG_TIMEZONE_NAMES' in query_upper or 'PG_TIMEZONE_ABBREVS' in query_upper:
                print(f"[{self.session_id}]   🔧 Handling timezone catalog query...")
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
                print(f"[{self.session_id}]   ✓ timezone catalog handled")
                return

            # Handle pg_roles (DataGrip queries this for user management)
            if 'PG_ROLES' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]   🔧 Handling pg_roles query...")
                cols = self._expected_result_columns(query) or ['role_id', 'role_name']
                base = {
                    'role_id': 1,
                    'id': 1,
                    'oid': 1,
                    'rolname': self.user_name,
                    'role_name': self.user_name,
                    'is_super': True,
                    'rolsuper': True,
                    'is_inherit': True,
                    'rolinherit': True,
                    'can_createrole': True,
                    'rolcreaterole': True,
                    'can_createdb': True,
                    'rolcreatedb': True,
                    'can_login': True,
                    'rolcanlogin': True,
                    'rolreplication': False,
                    'rolbypassrls': False,
                    'rolconnlimit': -1,
                }
                result_df = pd.DataFrame({c: [base.get(c, base.get(c.lower(), None))] for c in cols})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ pg_roles handled")
                return

            # Handle pg_user (DataGrip queries this for user permissions)
            if 'PG_USER' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]   🔧 Handling pg_user query...")
                cols = self._expected_result_columns(query) or ['usename', 'usesuper']
                base = {
                    'usename': self.user_name,
                    'usesysid': 1,
                    'usecreatedb': True,
                    'usesuper': True,
                    'userepl': False,
                    'usebypassrls': False,
                    'passwd': '********',
                    'valuntil': None,
                    'useconfig': None,
                }
                result_df = pd.DataFrame({c: [base.get(c, base.get(c.lower(), None))] for c in cols})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ pg_user handled")
                return

            # Handle pg_auth_members (DataGrip queries for role membership)
            if 'PG_AUTH_MEMBERS' in query_upper:
                print(f"[{self.session_id}]   🔧 Handling pg_auth_members query...")
                cols = self._expected_result_columns(query) or ['id', 'role_id', 'admin_option']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ pg_auth_members handled (empty)")
                return

            # Handle pg_tablespace queries (DataGrip queries this)
            if 'PG_TABLESPACE' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]   🔧 Handling pg_tablespace query...")
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
                print(f"[{self.session_id}]   ✓ pg_tablespace handled")
                return

            # Special case 4: pg_class queries with regclass type columns
            # DBeaver queries pg_class with c.*, which has regclass-typed columns
            # Even after column rewriting, JOIN conditions and functions still fail
            # Solution: Replace entire query with pg_tables equivalent
            if 'FROM PG_CATALOG.PG_CLASS' in query_upper and 'C.*' in query_upper:
                # Log the FULL original query for debugging
                print(f"[{self.session_id}]   📝 ORIGINAL QUERY:")
                print(f"[{self.session_id}]      {query[:500]}")
                if len(query) > 500:
                    print(f"[{self.session_id}]      ... (truncated)")

                print(f"[{self.session_id}]   🔧 Bypassing pg_class query (using compatible columns)...")
                try:
                    # Extract WHERE clause from original query to preserve DBeaver's filters
                    import re
                    where_match = re.search(r'\bWHERE\b(.+?)(?:ORDER BY|LIMIT|$)', query, re.IGNORECASE | re.DOTALL)
                    where_clause = where_match.group(1).strip() if where_match else "c.relkind IN ('r', 'v', 'm', 'f', 'p')"

                    print(f"[{self.session_id}]      Extracted WHERE: {where_clause[:200]}")

                    # Query pg_catalog.pg_class with ONLY core columns that definitely exist
                    # DuckDB v1.4.2's pg_class is PostgreSQL 9.x compatible, missing newer columns
                    # We'll provide NULL for any missing columns DBeaver expects
                    safe_query = f"""
                        SELECT
                            c.oid,
                            c.relname,
                            c.relnamespace,
                            c.relkind,
                            c.relowner,
                            COALESCE(c.relhasindex, false) as relhasindex,
                            NULL::BOOLEAN as relrowsecurity,
                            NULL::BOOLEAN as relforcerowsecurity,
                            NULL::BOOLEAN as relispartition,
                            NULL::VARCHAR as description,
                            NULL::VARCHAR as partition_expr,
                            NULL::VARCHAR as partition_key
                        FROM pg_catalog.pg_class c
                        WHERE {where_clause}
                        ORDER BY c.relname
                        LIMIT 1000
                    """
                    result_df = self.duckdb_conn.execute(safe_query).fetchdf()

                    # Debug: Log what we're returning
                    print(f"[{self.session_id}]   📊 Returning {len(result_df)} relations:")
                    for idx, row in result_df.head(5).iterrows():
                        print(f"[{self.session_id}]      - {row['relname']} (kind={row['relkind']}, namespace={row['relnamespace']})")

                    send_query_results(self.sock, result_df, self.transaction_status)
                    print(f"[{self.session_id}]   ✅ Data sent successfully")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]   ✗ Safe query failed: {e}")
                    print(f"[{self.session_id}]   ✗ Error details: {str(e)[:200]}")
                    import traceback
                    traceback.print_exc()
                    # Fall through to default handler

            # Special case 5: pg_attribute queries (column metadata)
            # DBeaver queries with a.* which includes columns that don't exist in DuckDB v1.4.2
            if 'FROM PG_CATALOG.PG_ATTRIBUTE' in query_upper and 'A.*' in query_upper:
                print(f"[{self.session_id}]   📝 ORIGINAL pg_attribute QUERY:")
                print(f"[{self.session_id}]      {query[:500]}")

                print(f"[{self.session_id}]   🔧 Bypassing pg_attribute query (using safe columns)...")
                try:
                    # Extract WHERE clause
                    import re
                    where_match = re.search(r'\bWHERE\b(.+?)(?:ORDER BY|LIMIT|$)', query, re.IGNORECASE | re.DOTALL)
                    where_clause = where_match.group(1).strip() if where_match else "a.attnum > 0 AND NOT a.attisdropped"

                    print(f"[{self.session_id}]      Extracted WHERE: {where_clause[:200]}")

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

                    print(f"[{self.session_id}]   📊 Returning {len(result_df)} columns:")
                    for idx, row in result_df.head(10).iterrows():
                        print(f"[{self.session_id}]      - {row['relname']}.{row['attname']} (type={row['atttypid']}, notnull={row['attnotnull']})")

                    send_query_results(self.sock, result_df, self.transaction_status)
                    print(f"[{self.session_id}]   ✅ Column data sent successfully")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]   ✗ pg_attribute query failed: {e}")
                    print(f"[{self.session_id}]   ✗ Error details: {str(e)[:200]}")
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
                    clean_query = self._rewrite_pg_catalog_function_calls(clean_query)
                    clean_query = self._rewrite_information_schema_catalog_filters(clean_query)
                    clean_query = self._rewrite_pg_system_column_refs(clean_query)
                    result_df = self.duckdb_conn.execute(clean_query).fetchdf()
                    send_query_results(self.sock, result_df, self.transaction_status)
                    print(f"[{self.session_id}]   ✓ Type cast query handled")
                    return
                except:
                    # If that fails, return empty
                    pass

            # Default: Try to execute the query as-is
            # With pg_catalog views created, most queries should work!
            try:
                rewritten_query = self._rewrite_pg_catalog_function_calls(query)
                rewritten_query = self._rewrite_information_schema_catalog_filters(rewritten_query)
                rewritten_query = self._rewrite_pg_system_column_refs(rewritten_query)
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
                print(f"[{self.session_id}]   ✓ Catalog query executed ({len(result_df)} rows)")
                return

            except Exception as query_error:
                # Query failed - this might be a complex pg_catalog query we don't support
                print(f"[{self.session_id}]   ⚠️  Catalog query failed: {str(query_error)[:100]}")

                # Fallback: Return empty result (safe - clients handle this gracefully)
                cols = self._expected_result_columns(query)
                empty_df = self._empty_df_for_columns(cols) if cols else pd.DataFrame()
                send_query_results(self.sock, empty_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ Returned empty result (fallback)")

        except Exception as e:
            # Complete failure - return empty result to keep client from crashing
            print(f"[{self.session_id}]   ⚠️  Catalog query handler error: {e}")
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

    def _execute_show_and_send_extended(self, query: str):
        """
        Execute SHOW command and send results via Extended Query Protocol.

        Sends only DataRows + CommandComplete (RowDescription sent by Describe Portal).

        Args:
            query: SHOW command
        """
        import pandas as pd
        query_upper = query.upper()

        # SHOW search_path
        if 'SEARCH_PATH' in query_upper:
            result_df = pd.DataFrame({'search_path': ['main, pg_catalog']})
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

        send_execute_results(self.sock, result_df, send_row_description=True)  # Describe sent NoData

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
            print(f"[{self.session_id}]      Ignoring PostgreSQL-specific SET: {query[:60]}")
        else:
            # Try to execute on DuckDB (might work for some SET commands)
            try:
                self.duckdb_conn.execute(query)
                print(f"[{self.session_id}]      SET command executed on DuckDB")
            except Exception as e:
                # DuckDB doesn't support this either - ignore
                print(f"[{self.session_id}]      Ignoring unsupported SET: {query[:60]}")

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

        print(f"[{self.session_id}]   📋 SHOW command detected: {query[:60]}...")

        try:
            # SHOW search_path - schema search order
            if 'SEARCH_PATH' in query_upper:
                result_df = pd.DataFrame({'search_path': ['main, pg_catalog']})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ SHOW search_path handled")
                return

            # SHOW timezone
            if 'TIMEZONE' in query_upper or 'TIME ZONE' in query_upper:
                result_df = pd.DataFrame({'TimeZone': ['UTC']})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ SHOW timezone handled")
                return

            # SHOW server_version
            if 'SERVER_VERSION' in query_upper:
                result_df = pd.DataFrame({'server_version': ['14.0']})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ SHOW server_version handled")
                return

            # SHOW client_encoding
            if 'CLIENT_ENCODING' in query_upper:
                result_df = pd.DataFrame({'client_encoding': ['UTF8']})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ SHOW client_encoding handled")
                return

            # SHOW transaction isolation level
            if 'TRANSACTION' in query_upper and 'ISOLATION' in query_upper:
                result_df = pd.DataFrame({'transaction_isolation': ['read committed']})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ SHOW transaction isolation level handled")
                return

            # SHOW tables - this DuckDB supports natively!
            if 'TABLES' in query_upper:
                result_df = self.duckdb_conn.execute(query).fetchdf()
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ SHOW tables executed ({len(result_df)} rows)")
                return

            # SHOW RESULTS - list auto-materialized RVBBIT query results
            if 'RESULTS' in query_upper:
                try:
                    # Check if registry table exists
                    tables = self.duckdb_conn.execute("""
                        SELECT table_name FROM information_schema.tables
                        WHERE table_name = '_rvbbit_results'
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
                            FROM _rvbbit_results
                            ORDER BY created_at DESC
                            LIMIT 50
                        """).fetchdf()
                    else:
                        result_df = pd.DataFrame({
                            'info': ['No auto-materialized results yet. Run RVBBIT queries to see results here.']
                        })
                    send_query_results(self.sock, result_df, self.transaction_status)
                    print(f"[{self.session_id}]   ✓ SHOW RESULTS: {len(result_df)} entries")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]   ⚠️  SHOW RESULTS failed: {e}")
                    result_df = pd.DataFrame({'error': [str(e)]})
                    send_query_results(self.sock, result_df, self.transaction_status)
                    return

            # Try to execute on DuckDB (might work for some SHOW commands)
            try:
                result_df = self.duckdb_conn.execute(query).fetchdf()
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ SHOW command executed on DuckDB")
            except Exception as e:
                # DuckDB doesn't support this SHOW command - return empty
                print(f"[{self.session_id}]   ℹ️  Unsupported SHOW command, returning empty")
                result_df = pd.DataFrame({'setting': ['']})
                send_query_results(self.sock, result_df, self.transaction_status)

        except Exception as e:
            # Complete failure - send error
            error_message = str(e)
            error_detail = f"SHOW command not supported: {query}"
            send_error(self.sock, error_message, detail=error_detail, transaction_status=self.transaction_status)
            print(f"[{self.session_id}]   ✗ SHOW command error: {error_message}")

    def _handle_begin(self, send_ready=True):
        """
        Handle BEGIN transaction.

        Args:
            send_ready: If True, send ReadyForQuery (Simple Query mode)
                       If False, don't send (Extended Query - waits for Sync)
        """
        try:
            if self.transaction_status == 'T':
                # Already in transaction - commit current one first
                print(f"[{self.session_id}]   ℹ️  Already in transaction, auto-committing previous")
                self.duckdb_conn.execute("COMMIT")

            # Start new transaction
            self.duckdb_conn.execute("BEGIN TRANSACTION")
            self.transaction_status = 'T'

            self.sock.sendall(CommandComplete.encode('BEGIN'))
            if send_ready:
                self.sock.sendall(ReadyForQuery.encode('T'))  # 'T' = in transaction
            print(f"[{self.session_id}]   ✓ BEGIN transaction")

        except Exception as e:
            print(f"[{self.session_id}]   ✗ BEGIN error: {e}")
            if send_ready:
                send_error(self.sock, str(e))
            else:
                # In Extended Query, errors are sent but not ReadyForQuery (wait for Sync)
                self.sock.sendall(ErrorResponse.encode('ERROR', str(e)))

    def _handle_commit(self, send_ready=True):
        """
        Handle COMMIT transaction.

        Args:
            send_ready: If True, send ReadyForQuery (Simple Query mode)
                       If False, don't send (Extended Query - waits for Sync)
        """
        try:
            if self.transaction_status == 'E':
                # Transaction is in error state - can't commit
                print(f"[{self.session_id}]   ⚠️  Transaction in error state, auto-rolling back")
                self.duckdb_conn.execute("ROLLBACK")
            elif self.transaction_status == 'T':
                # Commit active transaction
                self.duckdb_conn.execute("COMMIT")
            # else: not in transaction, that's fine

            self.transaction_status = 'I'

            self.sock.sendall(CommandComplete.encode('COMMIT'))
            if send_ready:
                self.sock.sendall(ReadyForQuery.encode('I'))  # 'I' = idle
            print(f"[{self.session_id}]   ✓ COMMIT transaction")

        except Exception as e:
            print(f"[{self.session_id}]   ✗ COMMIT error: {e}")
            if send_ready:
                send_error(self.sock, str(e))
            else:
                self.sock.sendall(ErrorResponse.encode('ERROR', str(e)))

    def _handle_rollback(self, send_ready=True):
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
            print(f"[{self.session_id}]   ✓ ROLLBACK transaction")

        except Exception as e:
            print(f"[{self.session_id}]   ✗ ROLLBACK error: {e}")
            if send_ready:
                send_error(self.sock, str(e))
            else:
                self.sock.sendall(ErrorResponse.encode('ERROR', str(e)))

    def _handle_background_query(self, query: str):
        """
        Execute a query in the background and return job info immediately.

        The query runs asynchronously in a separate thread with its own DuckDB
        connection to the same database file. Results are materialized to a
        table and status is tracked in sql_query_log (ClickHouse).

        Usage:
            BACKGROUND SELECT * FROM expensive_computation;

        Returns immediately with:
            job_id (e.g., 'job-swift-fox-abc123'), status, result_table, check_status

        The user can then:
            - Poll: SELECT * FROM job('job-swift-fox-abc123')
            - Wait: SELECT * FROM await_job('job-swift-fox-abc123')
            - List all: SELECT * FROM jobs()
            - Query results: SELECT * FROM _results_YYYYMMDD.job_swift_fox_abc123
        """
        import time
        import pandas as pd
        from datetime import datetime
        from concurrent.futures import ThreadPoolExecutor

        # Check for persistent database (required for background queries)
        if not self.is_persistent_db:
            send_error(self.sock, "BACKGROUND queries require a persistent database. Connect with a database name other than 'memory'.")
            return

        # Generate job ID using woodland naming (user-friendly, unique)
        from ..session_naming import generate_woodland_id
        job_id = f"job-{generate_woodland_id()}"

        # Log query start (also generates internal UUID query_id)
        from ..sql_trail import log_query_start, log_query_complete, log_query_error
        internal_query_id = log_query_start(
            caller_id=job_id,  # Use job_id as caller_id for lookup
            query_raw=query,
            protocol='postgresql_wire_background'
        )

        if not internal_query_id:
            send_error(self.sock, "Failed to initialize background job")
            return

        # Capture database info for background thread
        db_name = self.database_name
        from ..config import get_config
        config = get_config()
        safe_db_name = db_name.replace("/", "_").replace("\\", "_").replace("..", "_")
        db_path = os.path.join(config.root_dir, 'session_dbs', f"{safe_db_name}.duckdb")
        session_id = self.session_id

        # Predict result table location (use full job_id as table name)
        date_str = datetime.now().strftime('%Y%m%d')
        result_schema = f"_results_{date_str}"
        # Convert job-swift-fox-abc123 to job_swift_fox_abc123 (valid SQL identifier)
        safe_job_id = job_id.replace('-', '_')
        result_table_name = safe_job_id
        full_result_table = f"{result_schema}.{result_table_name}"

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

                print(f"[{session_id}] 🔄 Background job {job_id} starting")

                # Open fresh DuckDB connection to same database file
                bg_conn = duckdb.connect(db_path)
                bg_conn.execute("SET threads TO 4")

                # Register UDFs on this connection
                from ..sql_tools.udf import register_rvbbit_udf, register_dynamic_sql_functions
                register_rvbbit_udf(bg_conn)
                register_dynamic_sql_functions(bg_conn)

                # Lazy attach configured sources for background execution too
                try:
                    from ..sql_tools.config import load_sql_connections
                    from ..sql_tools.lazy_attach import LazyAttachManager
                    LazyAttachManager(bg_conn, load_sql_connections()).ensure_for_query(query, aggressive=False)
                except Exception:
                    pass

                # Rewrite the query (handles RVBBIT syntax, semantic operators, etc.)
                from ..sql_rewriter import rewrite_rvbbit_syntax
                rewritten = rewrite_rvbbit_syntax(query, duckdb_conn=bg_conn)

                # Debug: print rewritten query
                print(f"[{session_id}] 📝 Rewritten query (first 500 chars):")
                print(rewritten[:500])

                # Execute
                result = bg_conn.execute(rewritten)
                result_df = result.fetchdf() if result else pd.DataFrame()

                print(f"[{session_id}] 📊 Background job {job_id} executed, {len(result_df)} rows")

                # Materialize results to the database
                result_location = None
                if len(result_df) > 0:
                    try:
                        # Create schema if not exists
                        bg_conn.execute(f"CREATE SCHEMA IF NOT EXISTS {result_schema}")

                        # Register DataFrame and create table
                        temp_name = f"_temp_bg_{safe_job_id}"
                        bg_conn.register(temp_name, result_df)
                        bg_conn.execute(f"CREATE OR REPLACE TABLE {full_result_table} AS SELECT * FROM {temp_name}")
                        bg_conn.unregister(temp_name)

                        result_location = {
                            'db_name': db_name,
                            'db_path': db_path,
                            'schema_name': result_schema,
                            'table_name': result_table_name
                        }

                        print(f"[{session_id}] 💾 Background job {job_id} materialized to {full_result_table}")

                    except Exception as mat_err:
                        print(f"[{session_id}] ⚠️  Background job {job_id} materialization failed: {mat_err}")

                # Log completion
                duration_ms = (time.time() - bg_start) * 1000
                log_query_complete(
                    query_id=internal_query_id,
                    status='completed',
                    rows_output=len(result_df),
                    duration_ms=duration_ms,
                    result_db_name=result_location.get('db_name') if result_location else None,
                    result_db_path=result_location.get('db_path') if result_location else None,
                    result_schema=result_location.get('schema_name') if result_location else None,
                    result_table=result_location.get('table_name') if result_location else None,
                )

                print(f"[{session_id}] ✅ Background job {job_id} completed: {len(result_df)} rows in {duration_ms:.0f}ms")

            except Exception as e:
                tb_module.print_exc()
                duration_ms = (time.time() - bg_start) * 1000
                log_query_error(internal_query_id, str(e), duration_ms=duration_ms)
                print(f"[{session_id}] ❌ Background job {job_id} failed: {e}")

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

        send_query_results(self.sock, job_df, self.transaction_status)
        print(f"[{self.session_id}] 🚀 Background job {job_id} submitted → {full_result_table}")

    def _handle_analyze_query(self, query_with_prompt: str):
        """
        Execute a query in background, then analyze results with LLM.

        The query runs asynchronously, results are formatted for LLM consumption,
        then passed to an analysis cascade. Results and analysis are stored.

        Usage:
            ANALYZE 'why were sales low in December?' SELECT * FROM sales;

        Returns immediately with:
            job_id (e.g., 'analysis-swift-fox-abc123'), status, prompt, result_table

        The user can then:
            - Poll: SELECT * FROM job('analysis-swift-fox-abc123')
            - Get analysis: SELECT * FROM analysis('analysis-swift-fox-abc123')
            - Query results: SELECT * FROM _results_YYYYMMDD.analysis_swift_fox_abc123
            - View logs: SELECT * FROM messages('analysis-swift-fox-abc123')
        """
        import time
        import re
        import pandas as pd
        from datetime import datetime
        from concurrent.futures import ThreadPoolExecutor

        # Parse prompt from query: ANALYZE 'prompt' SELECT ...
        # Support both single and double quotes
        prompt_match = re.match(r"""^(['"])(.*?)\1\s+(.+)$""", query_with_prompt, re.DOTALL)
        if not prompt_match:
            send_error(self.sock, "ANALYZE syntax: ANALYZE 'your question' SELECT ... ")
            return

        prompt = prompt_match.group(2)
        query = prompt_match.group(3).strip()

        if not query:
            send_error(self.sock, "ANALYZE requires a SQL query after the prompt")
            return

        # Check for persistent database (required)
        if not self.is_persistent_db:
            send_error(self.sock, "ANALYZE queries require a persistent database. Connect with a database name other than 'memory'.")
            return

        # Generate job ID using woodland naming
        from ..session_naming import generate_woodland_id
        job_id = f"analysis-{generate_woodland_id()}"

        # Log query start
        from ..sql_trail import log_query_start, log_query_complete, log_query_error
        internal_query_id = log_query_start(
            caller_id=job_id,
            query_raw=f"ANALYZE '{prompt}' {query}",
            protocol='postgresql_wire_analysis'
        )

        if not internal_query_id:
            send_error(self.sock, "Failed to initialize analysis job")
            return

        # Capture database info for background thread
        db_name = self.database_name
        from ..config import get_config
        config = get_config()
        safe_db_name = db_name.replace("/", "_").replace("\\", "_").replace("..", "_")
        db_path = os.path.join(config.root_dir, 'session_dbs', f"{safe_db_name}.duckdb")
        session_id = self.session_id

        # Predict result table location
        date_str = datetime.now().strftime('%Y%m%d')
        result_schema = f"_results_{date_str}"
        safe_job_id = job_id.replace('-', '_')
        result_table_name = safe_job_id
        full_result_table = f"{result_schema}.{result_table_name}"

        def format_for_llm(df: pd.DataFrame, max_rows: int = 100) -> str:
            """Format DataFrame for LLM consumption - compact but informative."""
            if len(df) == 0:
                return "No rows returned."

            lines = []
            lines.append(f"Rows: {len(df):,} | Columns: {len(df.columns)}")

            # Column info with types
            col_types = [f"{c} ({df[c].dtype})" for c in df.columns]
            lines.append(f"Schema: {', '.join(col_types)}")
            lines.append("")

            # Sample data as markdown table (truncated)
            sample_df = df.head(max_rows)
            try:
                # Truncate long string values for display
                display_df = sample_df.copy()
                for col in display_df.select_dtypes(include=['object']).columns:
                    display_df[col] = display_df[col].astype(str).str[:100]
                lines.append(display_df.to_markdown(index=False))
            except Exception:
                # Fallback to CSV if markdown fails
                lines.append(sample_df.to_csv(index=False))

            if len(df) > max_rows:
                lines.append(f"\n... ({len(df) - max_rows:,} more rows not shown)")

            # Numeric column statistics
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                lines.append("\nNumeric Statistics:")
                try:
                    stats = df[numeric_cols].describe().round(2)
                    lines.append(stats.to_markdown())
                except Exception:
                    pass

            return "\n".join(lines)

        def execute_and_analyze():
            """Background thread: execute query, analyze with LLM, store results."""
            import duckdb
            import traceback as tb_module
            import json
            bg_start = time.time()
            bg_conn = None
            result_df = pd.DataFrame()
            analysis_text = None

            try:
                # Set caller context for cost tracking
                from ..caller_context import set_caller_context, build_sql_metadata, clear_caller_context
                metadata = build_sql_metadata(
                    sql_query=query,
                    protocol="postgresql_wire_analysis",
                    triggered_by="analyze_query"
                )
                set_caller_context(job_id, metadata)

                print(f"[{session_id}] 🔬 Analysis job {job_id} starting: {prompt[:50]}...")

                # Open fresh DuckDB connection
                bg_conn = duckdb.connect(db_path)
                bg_conn.execute("SET threads TO 4")

                # Register UDFs
                from ..sql_tools.udf import register_rvbbit_udf, register_dynamic_sql_functions
                register_rvbbit_udf(bg_conn)
                register_dynamic_sql_functions(bg_conn)

                # Lazy attach configured sources for analysis execution too
                try:
                    from ..sql_tools.config import load_sql_connections
                    from ..sql_tools.lazy_attach import LazyAttachManager
                    LazyAttachManager(bg_conn, load_sql_connections()).ensure_for_query(query, aggressive=False)
                except Exception:
                    pass

                # Rewrite and execute query
                from ..sql_rewriter import rewrite_rvbbit_syntax
                rewritten = rewrite_rvbbit_syntax(query, duckdb_conn=bg_conn)
                result = bg_conn.execute(rewritten)
                result_df = result.fetchdf() if result else pd.DataFrame()

                print(f"[{session_id}] 📊 Analysis job {job_id} query complete: {len(result_df)} rows")

                # Materialize query results
                result_location = None
                if len(result_df) > 0:
                    try:
                        bg_conn.execute(f"CREATE SCHEMA IF NOT EXISTS {result_schema}")
                        temp_name = f"_temp_analysis_{safe_job_id}"
                        bg_conn.register(temp_name, result_df)
                        bg_conn.execute(f"CREATE OR REPLACE TABLE {full_result_table} AS SELECT * FROM {temp_name}")
                        bg_conn.unregister(temp_name)
                        result_location = {
                            'db_name': db_name,
                            'db_path': db_path,
                            'schema_name': result_schema,
                            'table_name': result_table_name
                        }
                        print(f"[{session_id}] 💾 Analysis job {job_id} results saved to {full_result_table}")
                    except Exception as mat_err:
                        print(f"[{session_id}] ⚠️  Analysis job {job_id} materialization failed: {mat_err}")

                # Format data for LLM
                formatted_data = format_for_llm(result_df, max_rows=100)

                # Call analysis via trait (uses sql_analyze cascade)
                print(f"[{session_id}] 🤖 Analysis job {job_id} calling cascade...")
                try:
                    from ..trait_registry import get_trait
                    analyze_trait = get_trait('sql_analyze')

                    if analyze_trait:
                        # Pass session/caller context for proper observability
                        analysis_result = analyze_trait(
                            prompt=prompt,
                            query=query,
                            data=formatted_data,
                            row_count=len(result_df),
                            columns=list(result_df.columns),
                            _session_id=f"analyze-{job_id}",
                            _caller_id=job_id,
                        )
                        if isinstance(analysis_result, dict):
                            analysis_text = analysis_result.get('analysis') or analysis_result.get('result') or str(analysis_result)
                        else:
                            analysis_text = str(analysis_result)
                    else:
                        # Fallback: run cascade directly if trait not registered
                        from ..runner import run_cascade
                        from ..config import get_config
                        import os as os_module
                        cfg = get_config()
                        cascade_path = os_module.path.join(cfg.root_dir, 'cascades', 'sql_analyze.yaml')

                        print(f"[{session_id}] ⚠️  sql_analyze trait not found, running cascade directly")

                        cascade_result = run_cascade(
                            cascade_path,
                            input_data={
                                "prompt": prompt,
                                "query": query,
                                "data": formatted_data,
                                "row_count": len(result_df),
                                "columns": ", ".join(result_df.columns),
                            },
                            session_id=f"analyze-{job_id}",
                            caller_id=job_id,
                        )

                        # Extract analysis from cascade result
                        state = cascade_result.get("state", {})
                        if "analysis" in state:
                            analysis_text = state["analysis"]
                        elif cascade_result.get("lineage"):
                            last_output = cascade_result["lineage"][-1].get("output", {})
                            analysis_text = last_output.get("analysis", str(last_output))
                        else:
                            analysis_text = str(cascade_result.get("outputs", {}))

                except Exception as llm_err:
                    print(f"[{session_id}] ⚠️  Analysis job {job_id} cascade failed: {llm_err}")
                    import traceback as tb_mod
                    tb_mod.print_exc()
                    analysis_text = f"Analysis failed: {llm_err}"

                # Store analysis in _analysis table
                try:
                    bg_conn.execute("""
                        CREATE TABLE IF NOT EXISTS _analysis (
                            job_id VARCHAR PRIMARY KEY,
                            prompt VARCHAR,
                            analysis TEXT,
                            query_sql VARCHAR,
                            row_count INTEGER,
                            column_count INTEGER,
                            columns VARCHAR,
                            result_table VARCHAR,
                            created_at TIMESTAMP DEFAULT current_timestamp
                        )
                    """)

                    # Use parameterized insert to handle special characters
                    bg_conn.execute("""
                        INSERT OR REPLACE INTO _analysis
                        (job_id, prompt, analysis, query_sql, row_count, column_count, columns, result_table, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        job_id,
                        prompt,
                        analysis_text,
                        query[:1000],  # Truncate long queries
                        len(result_df),
                        len(result_df.columns),
                        json.dumps(list(result_df.columns)),
                        full_result_table if result_location else None,
                        datetime.now()
                    ])

                    print(f"[{session_id}] 📝 Analysis job {job_id} stored in _analysis table")

                except Exception as store_err:
                    print(f"[{session_id}] ⚠️  Analysis job {job_id} failed to store: {store_err}")

                # Log completion
                duration_ms = (time.time() - bg_start) * 1000
                log_query_complete(
                    query_id=internal_query_id,
                    status='completed',
                    rows_output=len(result_df),
                    duration_ms=duration_ms,
                    result_db_name=result_location.get('db_name') if result_location else None,
                    result_db_path=result_location.get('db_path') if result_location else None,
                    result_schema=result_location.get('schema_name') if result_location else None,
                    result_table=result_location.get('table_name') if result_location else None,
                )

                print(f"[{session_id}] ✅ Analysis job {job_id} completed in {duration_ms:.0f}ms")

            except Exception as e:
                tb_module.print_exc()
                duration_ms = (time.time() - bg_start) * 1000
                log_query_error(internal_query_id, str(e), duration_ms=duration_ms)
                print(f"[{session_id}] ❌ Analysis job {job_id} failed: {e}")

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
        self._background_executor.submit(execute_and_analyze)

        # Return job info immediately
        job_df = pd.DataFrame([{
            'job_id': job_id,
            'status': 'running',
            'prompt': prompt[:100] + ('...' if len(prompt) > 100 else ''),
            'result_table': full_result_table,
            'submitted_at': datetime.now().isoformat(),
            'query_preview': query[:100] + ('...' if len(query) > 100 else ''),
            'check_status': f"SELECT * FROM job('{job_id}')",
            'get_analysis': f"SELECT * FROM analysis('{job_id}')",
            'message_log': f"SELECT * FROM messages('{job_id}')",
        }])

        send_query_results(self.sock, job_df, self.transaction_status)
        print(f"[{self.session_id}] 🔬 Analysis job {job_id} submitted: {prompt[:50]}...")

    def _handle_parse(self, msg: dict):
        """
        Handle Parse message - prepare a SQL statement.

        Args:
            msg: Decoded Parse message {statement_name, query, param_types}
        """
        stmt_name = msg['statement_name']
        query = msg['query']
        param_types = msg['param_types']

        print(f"[{self.session_id}]   🔧 Parse statement '{stmt_name or '(unnamed)'}': {query[:80]}...")

        try:
            # Rewrite RVBBIT MAP/RUN syntax to standard SQL BEFORE preparing
            from rvbbit.sql_rewriter import rewrite_rvbbit_syntax
            original_query = query
            query = rewrite_rvbbit_syntax(query, duckdb_conn=self.duckdb_conn)

            if query != original_query:
                print(f"[{self.session_id}]      🔄 Rewrote RVBBIT syntax ({len(original_query)} → {len(query)} chars)")

            # Store prepared statement
            # We don't actually use DuckDB PREPARE yet - just store the query
            # DuckDB PREPARE has different syntax ($1 vs ?)
            self.prepared_statements[stmt_name] = {
                'query': query,
                'param_types': param_types,
                'param_count': len(param_types)
            }

            # Send ParseComplete
            self.sock.sendall(ParseComplete.encode())
            print(f"[{self.session_id}]      ✓ Statement prepared ({len(param_types)} parameters)")

        except Exception as e:
            print(f"[{self.session_id}]      ✗ Parse error: {e}")
            send_error(self.sock, f"Parse error: {str(e)}", transaction_status=self.transaction_status)

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

        print(f"[{self.session_id}]   🔗 Bind portal '{portal_name or '(unnamed)'}' to statement '{stmt_name or '(unnamed)'}'")

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
                        elif param_type == 23:  # INTEGER
                            params.append(int(value_str))
                        elif param_type == 20:  # BIGINT
                            params.append(int(value_str))
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
            self.portals[portal_name] = {
                'statement_name': stmt_name,
                'params': params,
                'result_formats': result_formats,
                'query': stmt['query'],
                'row_description_sent': False  # Track if Describe sent RowDescription
            }

            # Send BindComplete
            self.sock.sendall(BindComplete.encode())
            print(f"[{self.session_id}]      ✓ Parameters bound ({len(params)} values)")

        except Exception as e:
            print(f"[{self.session_id}]      ✗ Bind error: {e}")
            send_error(self.sock, f"Bind error: {str(e)}", transaction_status=self.transaction_status)

    def _handle_describe(self, msg: dict):
        """
        Handle Describe message - describe statement or portal.

        Args:
            msg: Decoded Describe message {type, name}
        """
        describe_type = msg['type']
        name = msg['name']

        print(f"[{self.session_id}]   📋 Describe {describe_type} '{name or '(unnamed)'}'")

        try:
            if describe_type == 'S':  # Statement
                if name not in self.prepared_statements:
                    raise Exception(f"Prepared statement '{name}' does not exist")

                stmt = self.prepared_statements[name]

                # Send ParameterDescription
                self.sock.sendall(ParameterDescription.encode(stmt['param_types']))

                # Send NoData (we don't know columns without executing)
                self.sock.sendall(NoData.encode())

                print(f"[{self.session_id}]      ✓ Statement described ({len(stmt['param_types'])} parameters)")

            elif describe_type == 'P':  # Portal
                if name not in self.portals:
                    raise Exception(f"Portal '{name}' does not exist")

                # For all portals: Return NoData
                # Column metadata will come from Execute's RowDescription
                # This avoids double-execution and keeps protocol simple
                self.sock.sendall(NoData.encode())
                print(f"[{self.session_id}]      ✓ Portal described (NoData - Execute will send columns)")

        except Exception as e:
            print(f"[{self.session_id}]      ✗ Describe error: {e}")
            send_error(self.sock, f"Describe error: {str(e)}", transaction_status=self.transaction_status)

    def _handle_execute(self, msg: dict):
        """
        Handle Execute message - execute a bound portal.

        Args:
            msg: Decoded Execute message {portal_name, max_rows}
        """
        portal_name = msg['portal_name']
        max_rows = msg['max_rows']

        print(f"[{self.session_id}]   ▶️  Execute portal '{portal_name or '(unnamed)'}' (max_rows={max_rows})")

        try:
            # Get portal
            if portal_name not in self.portals:
                raise Exception(f"Portal '{portal_name}' does not exist")

            portal = self.portals[portal_name]
            query = portal['query']
            params = portal['params']

            # Check for special PostgreSQL functions and commands
            query_upper = query.upper().strip()

            # SHOW commands - Handle via Extended Query
            if query_upper.startswith('SHOW '):
                print(f"[{self.session_id}]      Detected SHOW command via Extended Query")
                # Handle SHOW and send results via Extended Query (no RowDescription!)
                self._execute_show_and_send_extended(query)
                return

            # pg_get_keywords() - Return empty result
            if 'PG_GET_KEYWORDS' in query_upper:
                print(f"[{self.session_id}]      Detected pg_get_keywords() - returning empty")
                import pandas as pd
                send_execute_results(self.sock, pd.DataFrame(columns=['word']), send_row_description=True)  # Describe sent NoData
                return

            # pg_class queries with c.* - Use the bypass logic
            if 'FROM PG_CATALOG.PG_CLASS' in query_upper and 'C.*' in query_upper:
                print(f"[{self.session_id}]      Detected pg_class c.* query - using safe column bypass")
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

                    print(f"[{self.session_id}]         WHERE: {where_clause[:100]}")

                    # Use safe column subset (avoids regclass and missing functions)
                    safe_query = f"""
                        SELECT
                            c.oid,
                            c.relname,
                            c.relnamespace,
                            c.relkind,
                            c.relowner,
                            COALESCE(c.relhasindex, false) as relhasindex,
                            NULL::BOOLEAN as relrowsecurity,
                            NULL::BOOLEAN as relforcerowsecurity,
                            NULL::BOOLEAN as relispartition,
                            NULL::VARCHAR as description,
                            NULL::VARCHAR as partition_expr,
                            NULL::VARCHAR as partition_key
                        FROM pg_catalog.pg_class c
                        WHERE {where_clause}
                        LIMIT 1000
                    """
                    result_df = self.duckdb_conn.execute(safe_query, params).fetchdf()
                    send_execute_results(self.sock, result_df, send_row_description=True)  # Describe sent NoData
                    print(f"[{self.session_id}]      ✓ pg_class bypass executed ({len(result_df)} rows)")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]      ✗ Bypass failed: {str(e)[:200]}")
                    import traceback
                    traceback.print_exc()
                    # Fall through

            # pg_attribute queries with a.* - Use safe column subset
            if 'FROM PG_CATALOG.PG_ATTRIBUTE' in query_upper and 'A.*' in query_upper:
                print(f"[{self.session_id}]      Detected pg_attribute a.* query - using safe column bypass")
                try:
                    # Extract WHERE clause
                    import re
                    where_match = re.search(r'\bWHERE\b(.+?)(?:ORDER BY|LIMIT|$)', query, re.IGNORECASE | re.DOTALL)
                    if where_match:
                        where_clause = where_match.group(1).strip()
                        # Convert $1, $2 to ?
                        for i in range(len(params), 0, -1):
                            where_clause = where_clause.replace(f'${i}', '?')
                    else:
                        where_clause = "a.attnum > 0 AND NOT a.attisdropped"

                    print(f"[{self.session_id}]         WHERE: {where_clause[:100]}")

                    # Use safe column subset
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
                    result_df = self.duckdb_conn.execute(safe_query, params).fetchdf()
                    send_execute_results(self.sock, result_df, send_row_description=True)  # Describe sent NoData
                    print(f"[{self.session_id}]      ✓ pg_attribute bypass executed ({len(result_df)} rows)")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]      ✗ pg_attribute bypass failed: {str(e)[:200]}")
                    import traceback
                    traceback.print_exc()
                    # Fall through

            # Strip regclass/regtype/regproc casts from ANY other pg_catalog query
            if 'PG_CATALOG' in query_upper and ('::REGCLASS' in query_upper or '::REGTYPE' in query_upper or '::REGPROC' in query_upper or '::OID' in query_upper):
                print(f"[{self.session_id}]      Detected pg_catalog query with type casts - stripping")
                # Strip all PostgreSQL type casts
                clean_query = query
                for cast in ['::regclass', '::regtype', '::regproc', '::oid', '::REGCLASS', '::REGTYPE', '::REGPROC', '::OID']:
                    clean_query = clean_query.replace(cast, '')

                # Convert placeholders
                duckdb_query = clean_query
                for i in range(len(params), 0, -1):
                    duckdb_query = duckdb_query.replace(f'${i}', '?')
                duckdb_query = self._rewrite_pg_catalog_function_calls(duckdb_query)
                duckdb_query = self._rewrite_information_schema_catalog_filters(duckdb_query)
                duckdb_query = self._rewrite_pg_system_column_refs(duckdb_query)

                try:
                    result_df = self.duckdb_conn.execute(duckdb_query, params).fetchdf()
                    send_execute_results(self.sock, result_df, send_row_description=True)  # Describe sent NoData
                    print(f"[{self.session_id}]      ✓ Catalog query executed after stripping type casts ({len(result_df)} rows)")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]      ✗ Even after stripping, query failed: {str(e)[:100]}")
                    # Fall through to error handling

            # Check if this is a SET or RESET command
            if query_upper.startswith('SET ') or query_upper.startswith('RESET '):
                # Handle SET commands via Extended Query Protocol
                print(f"[{self.session_id}]      Detected SET/RESET via Extended Query")
                self._execute_set_command(query)
                # Send CommandComplete (SET commands don't return rows!)
                self.sock.sendall(CommandComplete.encode('SET'))
                print(f"[{self.session_id}]      ✓ SET/RESET handled")
                return

            # Check if this is a transaction command
            if query_upper in ['BEGIN', 'BEGIN TRANSACTION', 'BEGIN WORK', 'START TRANSACTION']:
                print(f"[{self.session_id}]      Detected BEGIN via Extended Query")
                self._handle_begin(send_ready=False)  # Extended Query - wait for Sync
                return
            elif query_upper in ['COMMIT', 'COMMIT TRANSACTION', 'COMMIT WORK', 'END', 'END TRANSACTION']:
                print(f"[{self.session_id}]      Detected COMMIT via Extended Query")
                self._handle_commit(send_ready=False)  # Extended Query - wait for Sync
                return
            elif query_upper in ['ROLLBACK', 'ROLLBACK TRANSACTION', 'ROLLBACK WORK', 'ABORT']:
                print(f"[{self.session_id}]      Detected ROLLBACK via Extended Query")
                self._handle_rollback(send_ready=False)  # Extended Query - wait for Sync
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

            print(f"[{self.session_id}]      Converted query: {duckdb_query[:80]}...")
            print(f"[{self.session_id}]      Parameters: {params}")

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

            # Send results (WITH RowDescription since Describe sent NoData for regular queries)
            send_execute_results(self.sock, result_df, send_row_description=True)

            print(f"[{self.session_id}]      ✓ Executed, returned {len(result_df)} rows")

        except Exception as e:
            print(f"[{self.session_id}]      ✗ Execute error: {e}")
            # Mark transaction as errored
            if self.transaction_status == 'T':
                self.transaction_status = 'E'
            send_error(self.sock, f"Execute error: {str(e)}", transaction_status=self.transaction_status)

    def _handle_close(self, msg: dict):
        """
        Handle Close message - close prepared statement or portal.

        Args:
            msg: Decoded Close message {type, name}
        """
        close_type = msg['type']
        name = msg['name']

        print(f"[{self.session_id}]   🗑️  Close {close_type} '{name or '(unnamed)'}'")

        try:
            if close_type == 'S':  # Statement
                if name in self.prepared_statements:
                    del self.prepared_statements[name]
                    print(f"[{self.session_id}]      ✓ Statement closed")
            elif close_type == 'P':  # Portal
                if name in self.portals:
                    del self.portals[name]
                    print(f"[{self.session_id}]      ✓ Portal closed")

            # Send CloseComplete
            self.sock.sendall(CloseComplete.encode())

        except Exception as e:
            print(f"[{self.session_id}]      ✗ Close error: {e}")
            send_error(self.sock, f"Close error: {str(e)}", transaction_status=self.transaction_status)

    def _handle_sync(self):
        """
        Handle Sync message - synchronization point.

        Sends ReadyForQuery with current transaction status.
        """
        print(f"[{self.session_id}]   🔄 Sync (transaction_status={self.transaction_status})")

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
        try:
            # Step 0: Check for SSL request (common - psql tries SSL first)
            first_message = PostgresMessage.read_startup_message(self.sock)
            if not first_message:
                print(f"[{self.addr}] ✗ Failed to read initial message")
                return

            # Handle SSL request
            if first_message.get('ssl_request'):
                print(f"[{self.addr}] SSL requested - rejecting (not supported in v1)")
                # Send 'N' to indicate SSL not supported
                self.sock.sendall(b'N')

                # Now read the REAL startup message (client will retry without SSL)
                startup = PostgresMessage.read_startup_message(self.sock)
                if not startup:
                    print(f"[{self.addr}] ✗ Failed to read startup after SSL rejection")
                    return
            else:
                # No SSL request - this IS the startup message
                startup = first_message

            # Step 2: Handle startup (sets session_id based on database name)
            self.handle_startup(startup['params'])

            # Step 3: Setup DuckDB session with RVBBIT UDFs (now that session_id is set)
            self.setup_session()

            # Step 4: Send startup response (now that database is ready)
            send_startup_response(self.sock)

            # Step 5: Message loop
            while self.running:
                msg_type, payload = PostgresMessage.read_message(self.sock)

                if msg_type is None:
                    # Connection closed by client
                    print(f"[{self.session_id}] Connection closed by client")
                    break

                if msg_type == MessageType.QUERY:
                    # Simple query protocol
                    # Payload is null-terminated SQL string
                    query = payload.rstrip(b'\x00').decode('utf-8')
                    self.handle_query(query)

                elif msg_type == MessageType.TERMINATE:
                    # Client requested clean disconnect
                    print(f"[{self.session_id}] Client requested termination")
                    break

                # Extended Query Protocol (NEW!)
                elif msg_type == MessageType.PARSE:
                    msg = ParseMessage.decode(payload)
                    self._handle_parse(msg)

                elif msg_type == MessageType.BIND:
                    msg = BindMessage.decode(payload)
                    self._handle_bind(msg)

                elif msg_type == MessageType.DESCRIBE:
                    msg = DescribeMessage.decode(payload)
                    self._handle_describe(msg)

                elif msg_type == MessageType.EXECUTE:
                    msg = ExecuteMessage.decode(payload)
                    self._handle_execute(msg)

                elif msg_type == MessageType.CLOSE:
                    msg = CloseMessage.decode(payload)
                    self._handle_close(msg)

                elif msg_type == MessageType.SYNC:
                    self._handle_sync()

                else:
                    # Unknown message type
                    print(f"[{self.session_id}] ⚠ Unknown message type: {msg_type} ({chr(msg_type) if 32 <= msg_type <= 126 else '?'})")
                    send_error(
                        self.sock,
                        f"Unsupported message type: {msg_type}",
                        detail="RVBBIT PostgreSQL server implements Simple Query Protocol only."
                    )

        except Exception as e:
            print(f"[{self.session_id}] ✗ Connection error: {e}")
            traceback.print_exc()

        finally:
            # Step 5: Cleanup
            self.cleanup()

    def cleanup(self):
        """
        Clean up connection and DuckDB session.

        Called when client disconnects or connection errors.
        Ensures DuckDB is left in a clean state for reconnection.

        IMPORTANT: Multiple clients may share the same DuckDB connection
        (if they connect to the same database name). We must NOT force-close
        the connection unless it's truly corrupt, or we'll break other clients.
        """
        print(f"[{self.session_id}] 🧹 Cleaning up ({self.query_count} queries executed)")

        # 1. Try to rollback any open transaction to leave DuckDB in clean state
        if self.duckdb_conn:
            try:
                self.duckdb_conn.execute("ROLLBACK")
                print(f"[{self.session_id}]   ✓ Transaction rolled back")
            except Exception as e:
                error_msg = str(e).lower()
                # "no transaction is active" is NORMAL - not an error
                # Only force-close on actual connection problems
                if "no transaction" in error_msg:
                    # This is fine - no transaction was active
                    print(f"[{self.session_id}]   ✓ No active transaction (clean state)")
                elif "connection" in error_msg and "closed" in error_msg:
                    # Connection is already dead - remove from cache
                    print(f"[{self.session_id}]   ⚠️ Connection already closed, removing from cache")
                    try:
                        from ..sql_tools.session_db import force_close_session
                        force_close_session(self.session_id)
                    except:
                        pass
                else:
                    # Unknown error - log but don't force-close (other clients may be using it)
                    print(f"[{self.session_id}]   ⚠️ Rollback warning: {e}")

        # 2. Close socket
        try:
            self.sock.close()
        except:
            pass

        # Note: We keep the DuckDB connection in cache for other clients
        # and quick reconnect. Only truly dead connections are removed above.


class RVBBITPostgresServer:
    """
    PostgreSQL wire protocol server for RVBBIT.

    Listens on TCP port, accepts PostgreSQL client connections,
    and routes queries to RVBBIT DuckDB sessions.

    Features:
    - Concurrent connections (thread per client)
    - Isolated DuckDB sessions (one per client)
    - RVBBIT UDFs auto-registered
    - Simple Query Protocol (sufficient for most tools)
    """

    def __init__(self, host='0.0.0.0', port=5432, session_prefix='pg_client'):
        """
        Initialize server.

        Args:
            host: Host to listen on (0.0.0.0 = all interfaces)
            port: Port to listen on (5432 = standard PostgreSQL port)
            session_prefix: Prefix for DuckDB session IDs
        """
        self.host = host
        self.port = port
        self.session_prefix = session_prefix
        self.running = False
        self.client_count = 0

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
            print("❌ ERROR: Could not start server")
            print("=" * 70)
            print(f"Failed to bind to {self.host}:{self.port}")
            print(f"Error: {e}")
            print(f"\n💡 Possible causes:")
            print(f"   1. Port {self.port} is already in use")
            print(f"   2. Permission denied (ports < 1024 require root)")
            print(f"\n💡 Solutions:")
            print(f"   1. Stop other process: sudo lsof -ti:{self.port} | xargs kill")
            print(f"   2. Use different port: rvbbit server --port 5433")
            print(f"   3. Use sudo (not recommended): sudo rvbbit server --port {self.port}")
            print("=" * 70)
            return

        sock.listen(5)  # Backlog of 5 pending connections
        self.running = True

        # Initialize cascade registry and dynamic operator patterns (cached for server lifetime)
        try:
            from rvbbit.semantic_sql.registry import initialize_registry
            from rvbbit.sql_tools.dynamic_operators import initialize_dynamic_patterns

            print("🔄 Initializing cascade registry...")
            initialize_registry(force=True)

            print("🔄 Loading dynamic operator patterns...")
            patterns = initialize_dynamic_patterns(force=True)

            print(f"✅ Loaded {len(patterns['all_keywords'])} semantic SQL operators")
            print(f"   - {len(patterns['infix'])} infix: {', '.join(sorted(list(patterns['infix']))[:5])}{'...' if len(patterns['infix']) > 5 else ''}")
            print(f"   - {len(patterns['function'])} functions: {', '.join(sorted(list(patterns['function']))[:5])}{'...' if len(patterns['function']) > 5 else ''}")
            print()
        except Exception as e:
            print(f"⚠️  Warning: Could not initialize dynamic operators: {e}")
            print(f"   Semantic SQL operators may not work correctly")
            print()

        # Print startup banner
        print("=" * 70)
        print("🌊 RVBBIT POSTGRESQL SERVER")
        print("=" * 70)
        print(f"📡 Listening on: {self.host}:{self.port}")
        print(f"🔗 Connection string: postgresql://rvbbit@localhost:{self.port}/default")
        print()
        print("✨ Available SQL functions:")
        print("   • rvbbit_udf(instructions, input_value)")
        print("     → Simple LLM extraction/classification")
        print()
        print("   • rvbbit_cascade_udf(cascade_path, json_inputs)")
        print("     → Full multi-cell cascade per row (with candidates!)")
        print()
        print("📚 Connect from:")
        print(f"   • psql:      psql postgresql://localhost:{self.port}/default")
        print(f"   • DBeaver:   New Connection → PostgreSQL → localhost:{self.port}")
        print(f"   • Python:    psycopg2.connect('postgresql://localhost:{self.port}/default')")
        print(f"   • DataGrip:  New Data Source → PostgreSQL → localhost:{self.port}")
        print()
        print("💡 Each connection gets:")
        print("   • Isolated DuckDB session")
        print("   • Temp tables (session-scoped)")
        print("   • RVBBIT UDFs registered")
        print("   • ATTACH support (connect to Postgres/MySQL/S3)")
        print()
        print("⏸️  Press Ctrl+C to stop")
        print("=" * 70)

        try:
            while self.running:
                # Accept new connection (blocking)
                client_sock, addr = sock.accept()
                self.client_count += 1

                print(f"\n🔌 Client #{self.client_count} connected from {addr[0]}:{addr[1]}")

                # Handle client in separate thread (allows concurrent connections)
                client = ClientConnection(client_sock, addr, self.session_prefix)
                thread = threading.Thread(
                    target=client.handle,
                    daemon=True,
                    name=f"Client-{self.client_count}"
                )
                thread.start()

        except KeyboardInterrupt:
            print("\n\n⏹️  Shutting down server...")
            print(f"   Total connections served: {self.client_count}")

        except Exception as e:
            print(f"\n❌ Server error: {e}")
            traceback.print_exc()

        finally:
            sock.close()
            self.running = False
            print("✅ Server stopped")


def start_postgres_server(host='0.0.0.0', port=5432, session_prefix='pg_client'):
    """
    Start RVBBIT PostgreSQL wire protocol server.

    Args:
        host: Host to listen on (default: 0.0.0.0 = all interfaces)
        port: Port to listen on (default: 5432 = standard PostgreSQL)
        session_prefix: Prefix for DuckDB session IDs (default: 'pg_client')

    Example:
        # Start server
        start_postgres_server(port=5433)

        # Connect from psql
        $ psql postgresql://localhost:5433/default

        # Query with LLM UDFs!
        default=> SELECT rvbbit_udf('Extract brand', 'Apple iPhone') as brand;
         brand
        -------
         Apple
        (1 row)
    """
    server = RVBBITPostgresServer(host, port, session_prefix)
    server.start()
