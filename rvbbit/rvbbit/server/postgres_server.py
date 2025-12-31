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

import socket
import threading
import uuid
import traceback
from typing import Optional

from .postgres_protocol import (
    PostgresMessage,
    MessageType,
    CommandComplete,
    ReadyForQuery,
    ErrorResponse,
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
        self.duckdb_conn = None
        self.running = True
        self.query_count = 0
        self.transaction_status = 'I'  # 'I' = idle, 'T' = in transaction, 'E' = error

        # Extended Query Protocol state
        self.prepared_statements = {}  # name → {query, param_types, param_count}
        self.portals = {}               # name → {statement_name, params, result_formats, query}

    def setup_session(self):
        """
        Create DuckDB session and register RVBBIT UDFs.

        This is called once per client connection.
        The session persists for the lifetime of the connection.
        """
        try:
            # Import here to avoid circular dependencies
            from ..sql_tools.session_db import get_session_db
            from ..sql_tools.udf import register_rvbbit_udf

            # Get or create session DuckDB
            self.duckdb_conn = get_session_db(self.session_id)

            # Register RVBBIT UDFs (rvbbit_udf + rvbbit_cascade_udf)
            register_rvbbit_udf(self.duckdb_conn)

            # DuckDB v1.4.2+ has built-in pg_catalog support - no need to create views!
            # Just ensure DuckDB's built-in catalog is enabled
            print(f"[{self.session_id}]   ℹ️  Using DuckDB's built-in pg_catalog (v1.4.2+)")

            # Create views for ATTACH'd databases so they appear in DBeaver
            self._create_attached_db_views()

            # Register UDF to refresh views after manual ATTACH
            self._register_refresh_views_udf()

            print(f"[{self.session_id}] ✓ Session created with RVBBIT UDFs registered")

        except Exception as e:
            print(f"[{self.session_id}] ✗ Error setting up session: {e}")
            raise

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
            # Get all currently attached databases
            attached_db_names = set()
            attached_dbs = self.duckdb_conn.execute("""
                SELECT database_name
                FROM duckdb_databases()
                WHERE NOT internal
                  AND database_name NOT IN ('system', 'temp', 'memory')
                  AND database_name NOT LIKE 'pg_client_%'
            """).fetchall()

            for (db_name,) in attached_dbs:
                attached_db_names.add(db_name)

            # Get all views with __ pattern (ATTACH'd database views)
            views = self.duckdb_conn.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                  AND table_type = 'VIEW'
                  AND table_name LIKE '%__%'
            """).fetchall()

            dropped_count = 0
            for (view_name,) in views:
                # Extract database name from view (before __)
                db_prefix = view_name.split('__')[0] if '__' in view_name else None

                # If database doesn't exist, drop the view
                if db_prefix and db_prefix not in attached_db_names:
                    try:
                        self.duckdb_conn.execute(f'DROP VIEW IF EXISTS main."{view_name}"')
                        dropped_count += 1
                    except:
                        pass

            if dropped_count > 0:
                print(f"[{self.session_id}]   🧹 Cleaned up {dropped_count} orphaned views (DETACH'd databases)")

        except Exception as e:
            # Non-fatal
            print(f"[{self.session_id}]   ⚠️  Could not cleanup orphaned views: {e}")

    def _create_attached_db_views(self):
        """
        Create views in main schema for all tables in ATTACH'd databases.

        This makes ATTACH'd cascade sessions browsable in DBeaver!

        For each table in attached database:
          test_session.main._load_products → view: test_session__load_products

        DBeaver can then browse these views under the main schema.
        """
        try:
            # First, clean up any orphaned views from DETACH'd databases
            self._cleanup_orphaned_views()

            # Get all attached databases (exclude system DBs and current DB)
            attached_dbs = self.duckdb_conn.execute("""
                SELECT database_name, database_oid
                FROM duckdb_databases()
                WHERE NOT internal
                  AND database_name NOT IN ('system', 'temp', 'memory')
                  AND database_name NOT LIKE 'pg_client_%'
                ORDER BY database_name
            """).fetchall()

            if not attached_dbs:
                print(f"[{self.session_id}]   ℹ️  No ATTACH'd databases to expose")
                return

            view_count = 0
            for db_name, db_oid in attached_dbs:
                # Get tables in this database
                tables = self.duckdb_conn.execute(f"""
                    SELECT schema_name, table_name
                    FROM duckdb_tables()
                    WHERE database_name = '{db_name}'
                      AND NOT temporary
                    ORDER BY schema_name, table_name
                """).fetchall()

                for schema, table in tables:
                    # Create view name: dbname__tablename
                    # Use double underscore to distinguish from regular table names
                    view_name = f"{db_name}__{table}"

                    try:
                        # Create view pointing to attached database table
                        self.duckdb_conn.execute(f"""
                            CREATE OR REPLACE VIEW main."{view_name}" AS
                            SELECT * FROM "{db_name}"."{schema}"."{table}"
                        """)
                        view_count += 1
                    except Exception as e:
                        # Skip if view creation fails
                        pass

            if view_count > 0:
                print(f"[{self.session_id}]   ✅ Created {view_count} views for ATTACH'd databases")
            else:
                print(f"[{self.session_id}]   ℹ️  No tables found in ATTACH'd databases")

        except Exception as e:
            # Non-fatal - ATTACH views are nice-to-have
            print(f"[{self.session_id}]   ⚠️  Could not create ATTACH'd DB views: {e}")

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
            print(f"[{self.session_id}]   🗑️  DETACH {db_name} - cleaning up views...")

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
            print(f"[{self.session_id}]   ⚠️  Could not register refresh UDF: {e}")

    def handle_startup(self, startup_params: dict):
        """
        Handle client startup message.

        Extracts database name and username from startup params.
        Sets up consistent session_id for persistent database.
        """
        database = startup_params.get('database', 'default')
        user = startup_params.get('user', 'rvbbit')
        application_name = startup_params.get('application_name', 'unknown')

        # Create consistent session_id based on database name
        # This ensures reconnecting to the same database reuses the same DuckDB file
        self.session_id = f"{self.session_prefix}_{database}"

        print(f"[{self.session_id}] 🔌 Client startup:")
        print(f"   User: {user}")
        print(f"   Database: {database}")
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

        # Log query (show more for catalog queries)
        is_catalog = self._is_catalog_query(query.upper()) if len(query) > 0 else False
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

            # Handle DETACH commands - cleanup views for the detached database
            if query_upper.startswith('DETACH '):
                self._handle_detach(query)
                return

            # Handle PostgreSQL catalog queries (pg_catalog, information_schema)
            if self._is_catalog_query(query):
                self._handle_catalog_query(query)
                return

            # Set caller context for RVBBIT queries (enables cost tracking and debugging)
            from rvbbit.sql_rewriter import rewrite_rvbbit_syntax, _is_rvbbit_statement
            if _is_rvbbit_statement(query):
                from rvbbit.session_naming import generate_woodland_id
                from rvbbit.caller_context import set_caller_context, build_sql_metadata

                caller_id = f"sql-{generate_woodland_id()}"
                metadata = build_sql_metadata(
                    sql_query=query,
                    protocol="postgresql_wire",
                    triggered_by="postgres_server"
                )
                set_caller_context(caller_id, metadata)

                # SPECIAL PATH: MAP PARALLEL with true concurrency
                from rvbbit.sql_rewriter import _parse_rvbbit_statement
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
                            # 6. Send results to client
                            send_query_results(self.sock, result_df, self.transaction_status)

                        if is_parallel and is_materialized:
                            print(f"[{self.session_id}]   ✅ MAP PARALLEL + Materialized: {len(result_df)} rows, {stmt.parallel} workers → {stmt.with_options['as_table']}")
                        elif is_parallel:
                            print(f"[{self.session_id}]   ✅ MAP PARALLEL complete: {len(result_df)} rows, {stmt.parallel} workers")
                        else:
                            print(f"[{self.session_id}]   ✅ Materialized to table: {stmt.with_options['as_table']} ({len(result_df)} rows)")

                        return  # Skip normal execution path

                except Exception as parallel_error:
                    # If parallel execution fails, log and fall back to normal path
                    print(f"[{self.session_id}]   ⚠️  Special path failed: {parallel_error}")
                    import traceback
                    traceback.print_exc()
                    print(f"[{self.session_id}]      Falling back to sequential execution")
                    # Fall through to normal execution

            # Rewrite RVBBIT MAP/RUN syntax to standard SQL
            query = rewrite_rvbbit_syntax(query, duckdb_conn=self.duckdb_conn)

            # Execute on DuckDB
            result_df = self.duckdb_conn.execute(query).fetchdf()

            # Send results back to client (with current transaction status)
            send_query_results(self.sock, result_df, self.transaction_status)

            print(f"[{self.session_id}]   ✓ Returned {len(result_df)} rows")

        except Exception as e:
            # Send error to client
            error_message = str(e)
            error_detail = traceback.format_exc()

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
            'PG_PROC',
            'PG_DESCRIPTION',
            'PG_SETTINGS',
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
            # Special case 1: Functions that need custom implementation
            if 'CURRENT_DATABASE()' in query_upper:
                # DuckDB doesn't have this function, return constant
                result_df = pd.DataFrame({'current_database': ['default']})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ CURRENT_DATABASE() handled")
                return

            if 'CURRENT_SCHEMA()' in query_upper or 'CURRENT_SCHEMAS(' in query_upper:
                # Return default schema
                result_df = pd.DataFrame({'current_schema': ['main']})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ CURRENT_SCHEMA() handled")
                return

            if 'VERSION()' in query_upper:
                # Return PostgreSQL-compatible version string
                result_df = pd.DataFrame({'version': ['PostgreSQL 14.0 (RVBBIT/DuckDB)']})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ VERSION() handled")
                return

            # Special case 2: HAS_*_PRIVILEGE functions (always return true for simplicity)
            if 'HAS_TABLE_PRIVILEGE' in query_upper or 'HAS_SCHEMA_PRIVILEGE' in query_upper:
                result_df = pd.DataFrame({'has_privilege': [True]})
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ HAS_PRIVILEGE function handled")
                return

            # Special case 3: SIMPLE pg_namespace queries (not JOINs!) - include ATTACH'd databases
            # Only bypass if it's the main table, not part of a JOIN
            if ('FROM PG_CATALOG.PG_NAMESPACE' in query_upper or 'FROM PG_NAMESPACE' in query_upper) and 'JOIN' not in query_upper:
                print(f"[{self.session_id}]   🔧 Enhancing pg_namespace to include ATTACH'd databases...")
                try:
                    # Get all attached databases from duckdb_databases()
                    # Map them as PostgreSQL schemas
                    enhanced_query = """
                        SELECT
                            database_name as nspname,
                            database_oid as oid
                        FROM duckdb_databases()
                        WHERE database_name NOT IN ('system', 'temp')
                        UNION ALL
                        SELECT 'pg_catalog' as nspname, 11 as oid
                        UNION ALL
                        SELECT 'information_schema' as nspname, 12 as oid
                        ORDER BY nspname
                    """
                    result_df = self.duckdb_conn.execute(enhanced_query).fetchdf()
                    send_query_results(self.sock, result_df, self.transaction_status)
                    print(f"[{self.session_id}]   ✅ Enhanced pg_namespace with ATTACH'd databases ({len(result_df)} schemas)")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]   ⚠️  Could not enhance pg_namespace: {e}")
                    # Fall through to default handler

            # Special case 4: PostgreSQL functions that don't exist in DuckDB
            if 'PG_GET_KEYWORDS' in query_upper:
                # Return empty - DuckDB doesn't have this function
                result_df = pd.DataFrame(columns=['word', 'catcode', 'catdesc'])
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ PG_GET_KEYWORDS() handled (empty)")
                return

            # Special case 4: pg_class queries with regclass type columns
            # DBeaver queries pg_class with c.*, which has regclass-typed columns
            # Even after column rewriting, JOIN conditions and functions still fail
            # Solution: Replace entire query with pg_tables equivalent
            if 'FROM PG_CATALOG.PG_CLASS' in query_upper and ('C.*' in query_upper or 'C.OID' in query_upper):
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
                result_df = self.duckdb_conn.execute(query).fetchdf()
                send_query_results(self.sock, result_df, self.transaction_status)
                print(f"[{self.session_id}]   ✓ Catalog query executed ({len(result_df)} rows)")
                return

            except Exception as query_error:
                # Query failed - this might be a complex pg_catalog query we don't support
                print(f"[{self.session_id}]   ⚠️  Catalog query failed: {str(query_error)[:100]}")

                # Fallback: Return empty result (safe - clients handle this gracefully)
                empty_df = pd.DataFrame()
                send_query_results(self.sock, empty_df)
                print(f"[{self.session_id}]   ✓ Returned empty result (fallback)")

        except Exception as e:
            # Complete failure - return empty result to keep client from crashing
            print(f"[{self.session_id}]   ⚠️  Catalog query handler error: {e}")
            import pandas as pd
            send_query_results(self.sock, pd.DataFrame())

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
            if 'FROM PG_CATALOG.PG_CLASS' in query_upper and ('C.*' in query_upper or 'C.OID' in query_upper):
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

            print(f"[{self.session_id}]      Converted query: {duckdb_query[:80]}...")
            print(f"[{self.session_id}]      Parameters: {params}")

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
        """
        print(f"[{self.session_id}] 🧹 Cleaning up ({self.query_count} queries executed)")

        # Close socket
        try:
            self.sock.close()
        except:
            pass

        # Optional: cleanup DuckDB session file
        # For now, we keep session files for debugging/analysis
        # Uncomment to delete:
        # from ..sql_tools.session_db import cleanup_session_db
        # cleanup_session_db(self.session_id, delete_file=True)


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
