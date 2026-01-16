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
from threading import Lock
from typing import Optional

from ..console_style import S, styled_print

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
    NoData,
    RowDescription,
)


class ClientConnection:
    """
    Represents a single client connection.

    Each client gets:
    - Unique session ID
    - Isolated DuckDB session
    - LARS UDFs registered
    - Dedicated socket
    """

    def __init__(self, sock, addr, session_prefix='pg_client'):
        self.sock = sock
        self.addr = addr
        self.session_id = None  # Will be set in handle_startup based on database name
        self.session_prefix = session_prefix
        self.database_name = 'default'  # Logical database name from client connection
        self.user_name = 'lars'       # Logical user name from client connection
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
        Create DuckDB session and register LARS UDFs.

        This is called once per client connection.
        The session persists for the lifetime of the connection.

        Database routing:
        - 'memory' or 'default' → in-memory DuckDB (per-client, ephemeral)
        - Any other name → persistent file at session_dbs/{database}.duckdb

        Persistent databases survive restarts and are shared across connections.
        """
        try:
            import duckdb
            from ..sql_tools.udf import register_lars_udf
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
                    styled_print(f"[{self.session_id}]   {S.SAVE} Created persistent database: {safe_db_name}")
                else:
                    styled_print(f"[{self.session_id}]   {S.DB} Opened persistent database: {safe_db_name}")

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
                self.duckdb_conn.execute("CREATE OR REPLACE MACRO pg_get_userbyid(x) AS 'lars'")
                self.duckdb_conn.execute("CREATE OR REPLACE MACRO txid_current() AS (epoch_ms(now())::BIGINT % 4294967296)")
                self.duckdb_conn.execute("CREATE OR REPLACE MACRO pg_is_in_recovery() AS false")
                self.duckdb_conn.execute("CREATE OR REPLACE MACRO pg_tablespace_location(x) AS NULL")
            except Exception:
                pass

            # Register LARS UDFs (lars_udf + lars_cascade_udf + hardcoded aggregates)
            register_lars_udf(self.duckdb_conn)

            # Register dynamic SQL functions from cascade registry (SUMMARIZE_URLS, etc.)
            from ..sql_tools.udf import register_dynamic_sql_functions
            register_dynamic_sql_functions(self.duckdb_conn)

            # Lazy ATTACH: configured sql_connections/*.yaml attached on first reference.
            # Non-fatal if config loading fails.
            try:
                from ..sql_tools.config import load_sql_connections
                from ..sql_tools.lazy_attach import LazyAttachManager
                self._lazy_attach = LazyAttachManager(self.duckdb_conn, load_sql_connections())
            except Exception:
                self._lazy_attach = None

            # DuckDB v1.4.2+ has built-in pg_catalog support
            styled_print(f"[{self.session_id}]   {S.INFO}  Using DuckDB's built-in pg_catalog (v1.4.2+)")

            # Create PostgreSQL compatibility stubs (functions and macros)
            self._create_pg_compat_stubs()

            # Create metadata table for tracking ATTACH commands (persistent DBs only)
            self._create_attachments_metadata_table()

            # Create registry table for auto-materialized LARS query results
            self._create_results_registry_table()

            # Replay any previously attached databases from metadata
            self._replay_attachments()

            # Create views for ATTACH'd databases so they appear in DBeaver
            self._create_attached_db_views()

            # Register UDF to refresh views after manual ATTACH
            self._register_refresh_views_udf()

            styled_print(f"[{self.session_id}] {S.OK} Session ready (database: {self.database_name})")

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
            'PG_ENUM': ['oid', 'enumtypid', 'enumsortorder', 'enumlabel'],
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
                if extracted:
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
            'pg_enum',
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
        if 'PG_CLASS' in query.upper() and 'RELKIND' in query.upper() and 'RELNAMESPACE' in query.upper():
            print(f"[DEBUG] _rewrite_missing_table_joins: pg_class query BEFORE rewrite:")
            for i, line in enumerate(query.split('\n'), 1):
                if line.strip():
                    print(f"[DEBUG]   Line {i}: {line.strip()[:80]}")
            print(f"[DEBUG]   WHERE in original: {'WHERE' in query.upper()}")

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
                print(f"[DEBUG] _rewrite_missing_table_joins: Removing LEFT JOIN to {table}")
                print(f"[DEBUG]   Alias: {alias}")
                print(f"[DEBUG]   Matched ({len(matched_text)} chars): {matched_text[:200]}{'...' if len(matched_text) > 200 else ''}")

                # Remove the entire LEFT JOIN clause
                result = result[:join_start] + ' ' + result[on_end:]

                # Replace column references like D.description with NULL
                # Be careful to only replace the alias, not table names
                result = re.sub(rf'\b{alias}\.(\w+)\b', 'NULL', result, flags=re.IGNORECASE)
                print(f"[DEBUG]   Alias '{alias}' column refs replaced with NULL")
                # Continue scanning for additional JOINs to the same missing table (if any)
                search_from = 0

        # Debug: Check if this is the pg_class table query
        if 'PG_CLASS' in query.upper() and 'RELKIND' in query.upper() and 'RELNAMESPACE' in query.upper():
            print(f"[DEBUG] _rewrite_missing_table_joins: pg_class query AFTER rewrite:")
            for i, line in enumerate(result.split('\n'), 1):
                if line.strip():
                    print(f"[DEBUG]   Line {i}: {line.strip()[:80]}")
            print(f"[DEBUG]   WHERE in result: {'WHERE' in result.upper()}")

        # Debug: show if WHERE clause is present
        if 'WHERE' in query.upper() and 'WHERE' not in result.upper():
            print(f"[DEBUG] WARNING: WHERE clause was lost during JOIN rewriting!")
            print(f"[DEBUG]   Original had WHERE at position: {query.upper().find('WHERE')}")
            # Show what was around the WHERE
            where_pos = query.upper().find('WHERE')
            print(f"[DEBUG]   Context around WHERE: ...{query[max(0,where_pos-50):where_pos+50]}...")

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
        MISSING_TABLES = {
            'pg_trigger', 'pg_rewrite', 'pg_policy', 'pg_policies', 'pg_rules',
            'pg_operator', 'pg_opclass', 'pg_opfamily', 'pg_aggregate',
            'pg_cast', 'pg_collation', 'pg_conversion', 'pg_enum', 'pg_range',
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

        if removed_count > 0:
            print(f"[DEBUG] _strip_union_parts: Removed {removed_count} UNION parts with missing tables")

        if not filtered_parts:
            # All parts had missing tables - return a minimal valid query
            # that matches the structure but returns no rows
            print(f"[DEBUG] _strip_union_parts: All UNION parts had missing tables, returning first part with FALSE condition")
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
        if has_pg_inherits:
            print(f"[DEBUG] _rewrite_pg_inherits_subqueries: Found pg_inherits in query")

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
                    print(f"[DEBUG] _rewrite_pg_inherits_subqueries: Could not find closing paren")
                    break

                # Replace the subquery with NULL or empty subquery depending on context
                old_subquery = result[start_pos:end_pos + 1]
                print(f"[DEBUG] _rewrite_pg_inherits_subqueries: Replacing subquery: {old_subquery[:80]}...")

                # Check if this subquery is used with IN/NOT IN/EXISTS (need valid subquery, not scalar)
                # Look at the 30 chars before the subquery
                prefix = result[max(0, start_pos - 30):start_pos].upper()
                if ' IN' in prefix or 'IN(' in prefix.replace(' ', '') or 'EXISTS' in prefix:
                    # Replace with empty subquery for IN/NOT IN/EXISTS clauses
                    replacement = "(SELECT NULL WHERE FALSE)"
                    print(f"[DEBUG] Using empty subquery replacement (context: ...{prefix[-20:]})")
                else:
                    # Replace with NULL scalar for SELECT list columns
                    replacement = "NULL::VARCHAR"
                    print(f"[DEBUG] Using NULL::VARCHAR replacement (context: ...{prefix[-20:]})")

                result = result[:start_pos] + replacement + result[end_pos + 1:]

        if has_pg_inherits and 'pg_inherits' not in result.lower():
            print(f"[DEBUG] _rewrite_pg_inherits_subqueries: Successfully removed all pg_inherits references")
            # Print full query to see the structure - split into lines for analysis
            lines = result.split('\n')
            print(f"[DEBUG] Rewritten query has {len(lines)} lines:")
            for i, line in enumerate(lines, 1):
                print(f"[DEBUG]   Line {i}: {line[:120]}{'...' if len(line) > 120 else ''}")
        elif has_pg_inherits:
            print(f"[DEBUG] _rewrite_pg_inherits_subqueries: WARNING - pg_inherits still in result!")

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
            styled_print(f"[{self.session_id}]      {S.WARN}  {handler_name}: Column count mismatch! described {described_col_count}, returning {actual_col_count}")
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
        try:
            rel_df = self.duckdb_conn.execute(
                f"""
                SELECT oid, relnamespace, relkind, relname
                FROM pg_catalog.pg_class
                WHERE relnamespace IN ({placeholders})
                  AND relkind IN ('r','m','v','p','f','S')
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
                WHERE table_name = '_lars_attachments'
            """).fetchall()

            if not existing:
                # Create metadata table
                self.duckdb_conn.execute("""
                    CREATE TABLE _lars_attachments (
                        id INTEGER PRIMARY KEY,
                        database_alias VARCHAR NOT NULL,
                        database_path VARCHAR NOT NULL,
                        attached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(database_alias)
                    )
                """)

                # Create sequence for auto-incrementing IDs
                self.duckdb_conn.execute("""
                    CREATE SEQUENCE _lars_attachments_seq START 1
                """)

                styled_print(f"[{self.session_id}]   {S.DONE} Created _lars_attachments metadata table")
        except Exception as e:
            # Non-fatal - just log the error
            styled_print(f"[{self.session_id}]   {S.WARN}  Could not create attachments metadata table: {e}")

    def _create_results_registry_table(self):
        """
        Create registry table for tracking auto-materialized LARS query results.

        LARS queries (cascades, UDFs, semantic operators) are expensive and
        non-deterministic. Auto-materializing their results provides "query insurance"
        so users don't lose expensive work if their connection drops or client crashes.

        Results are organized into date-based schemas for easy discovery and cleanup:
        - _results_20250103.q_abc12345 (query result table)
        - _lars_results (registry of all materialized results)

        Only created for persistent databases (not in-memory).
        """
        if not self.is_persistent_db:
            return  # Only for persistent databases

        try:
            # Check if registry table already exists
            existing = self.duckdb_conn.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = '_lars_results'
            """).fetchall()

            if not existing:
                # Create registry table
                self.duckdb_conn.execute("""
                    CREATE TABLE _lars_results (
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
                styled_print(f"[{self.session_id}]   {S.DONE} Created _lars_results registry table")
        except Exception as e:
            # Non-fatal - just log the error
            styled_print(f"[{self.session_id}]   {S.WARN}  Could not create results registry table: {e}")

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
        return sanitized

    def _maybe_materialize_result(self, query: str, result_df, query_id: str | None = None, caller_id: str | None = None):
        """
        Auto-materialize LARS query results for "query insurance".

        Creates an ACTUAL TABLE in ClickHouse for each result set:
        - Result table: lars_results.r_<caller_id>
        - Log entry: lars_results.query_results (metadata/index)

        This gives full columnar benefits - results are queryable with SQL!

        Args:
            query: The original SQL query
            result_df: The pandas DataFrame result
            query_id: Optional query ID for naming (generated if not provided)
            caller_id: Optional caller_id for linking to sql_query_log

        Returns:
            Dict with result location info if materialized:
            {
                'stored_in': 'clickhouse',
                'result_table': 'r_abc123',
                'caller_id': caller_id,
                'query_id': query_id,
                'row_count': N,
                'column_count': N
            }
            Returns None if not materialized.
        """
        import json
        import re
        from datetime import datetime

        styled_print(f"[{self.session_id}]   {S.SEARCH} _maybe_materialize_result called: query_id={query_id}, caller_id={caller_id}, rows={len(result_df) if result_df is not None else 0}")

        # Skip if empty results
        if result_df is None or len(result_df) == 0:
            styled_print(f"[{self.session_id}]   {S.SKIP}  Skipping: empty results")
            return None

        # Skip if results are too large (configurable threshold)
        max_rows = 100000  # Could make this configurable
        if len(result_df) > max_rows:
            styled_print(f"[{self.session_id}]   {S.WARN}  Skipping auto-materialize: {len(result_df)} rows > {max_rows} limit")
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
            styled_print(f"[{self.session_id}]   {S.SEARCH} Creating ClickHouse table {result_table_name} for {len(result_df)} rows...")
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
                            row_values.append(val.item())
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
                            return "'" + v.replace("\\", "\\\\").replace("'", "''") + "'"
                        elif isinstance(v, bool):
                            return '1' if v else '0'
                        elif isinstance(v, (int, float)):
                            return str(v)
                        elif isinstance(v, (dict, list)):
                            return "'" + json.dumps(v).replace("\\", "\\\\").replace("'", "''") + "'"
                        else:
                            return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"

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
                safe_query = query[:10000].replace("'", "''")

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

                styled_print(f"[{self.session_id}]   {S.SAVE} Results materialized: lars_results.{result_table_name} ({len(result_df)} rows, {len(columns)} cols)")

                result_location = {
                    'stored_in': 'clickhouse',
                    'result_table': result_table_name,
                    'caller_id': effective_caller_id,
                    'query_id': query_id,
                    'row_count': len(result_df),
                    'column_count': len(columns)
                }

            except Exception as ch_err:
                styled_print(f"[{self.session_id}]   {S.WARN}  ClickHouse storage failed: {ch_err}")
                import traceback
                traceback.print_exc()
                # Continue to try DuckDB

            # === SECONDARY: Also store in DuckDB (for persistent databases only) ===
            if self.is_persistent_db:
                try:
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
                        INSERT INTO _lars_results
                        (query_id, schema_name, table_name, full_table_name, query_fingerprint, row_count, column_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, [query_id, schema_name, table_name, full_table_name, query_fingerprint, len(result_df), len(result_df.columns)])

                    styled_print(f"[{self.session_id}]   {S.SAVE} Also stored in DuckDB: {full_table_name}")

                except Exception as duckdb_err:
                    # Non-fatal - ClickHouse is primary
                    styled_print(f"[{self.session_id}]   {S.WARN}  DuckDB storage failed (non-fatal): {duckdb_err}")

            return result_location

        except Exception as e:
            # Non-fatal - log and continue
            styled_print(f"[{self.session_id}]   {S.WARN}  Auto-materialize failed: {e}")
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
            styled_print(f"[{self.session_id}]   {S.WARN}  Arrow save skipped: empty result")
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
                print(f"[{self.session_id}]   📌 Arrow saved: {full_name} ({len(result_df)} rows, {len(result_df.columns)} cols)")
            finally:
                self.duckdb_conn.unregister(temp_name)

        except Exception as e:
            styled_print(f"[{self.session_id}]   {S.WARN}  Arrow save failed for '{name}': {e}")

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
                WHERE table_name = '_lars_attachments'
            """).fetchall()

            if not tables:
                return  # No attachments to replay

            # Get all stored attachments
            attachments = self.duckdb_conn.execute("""
                SELECT database_alias, database_path
                FROM _lars_attachments
                ORDER BY id
            """).fetchall()

            if not attachments:
                return

            styled_print(f"[{self.session_id}]   {S.LINK} Replaying {len(attachments)} ATTACH command(s)...")

            replayed_count = 0
            failed_count = 0

            for alias, path in attachments:
                try:
                    # Re-execute ATTACH
                    self.duckdb_conn.execute(f"ATTACH '{path}' AS {alias}")
                    styled_print(f"[{self.session_id}]      {S.OK} ATTACH '{path}' AS {alias}")
                    replayed_count += 1
                except Exception as e:
                    # File might not exist anymore - remove from metadata
                    try:
                        self.duckdb_conn.execute(
                            "DELETE FROM _lars_attachments WHERE database_alias = ?",
                            [alias]
                        )
                        styled_print(f"[{self.session_id}]      {S.WARN}  Could not replay ATTACH {alias}: {e}")
                        print(f"[{self.session_id}]         Removed from metadata (file may have been deleted)")
                        failed_count += 1
                    except:
                        pass

            if replayed_count > 0:
                styled_print(f"[{self.session_id}]   {S.DONE} Replayed {replayed_count} ATTACH command(s)")
            if failed_count > 0:
                styled_print(f"[{self.session_id}]   {S.WARN}  {failed_count} ATTACH command(s) failed (files removed)")

        except Exception as e:
            # Non-fatal - just log the error
            styled_print(f"[{self.session_id}]   {S.WARN}  Could not replay attachments: {e}")

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
        styled_print(f"[{self.session_id}]   {S.CFG} Starting pg_catalog view creation...")
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
            styled_print(f"[{self.session_id}]      {S.OK} pg_namespace created")

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

            styled_print(f"[{self.session_id}]   {S.DONE} ALL pg_catalog views created successfully!")
            styled_print(f"[{self.session_id}]   {S.DONE} Schema introspection is now ENABLED")

        except Exception as e:
            # Non-fatal - catalog views are nice-to-have
            styled_print(f"[{self.session_id}]   {S.ERR} ERROR creating pg_catalog views: {e}")
            import traceback
            traceback.print_exc()
            styled_print(f"[{self.session_id}]   {S.WARN}  Schema introspection will NOT work!")

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
            styled_print(f"[{self.session_id}]   {S.WARN}  Could not cleanup orphaned views: {e}")

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
                styled_print(f"[{self.session_id}]   {S.INFO}  No ATTACH'd databases to expose")
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
                styled_print(f"[{self.session_id}]   {S.DONE} Exposed {view_count} relation(s) from ATTACH'd databases")
            else:
                styled_print(f"[{self.session_id}]   {S.INFO}  No tables found in ATTACH'd databases")

        except Exception as e:
            # Non-fatal - ATTACH views are nice-to-have
            styled_print(f"[{self.session_id}]   {S.WARN}  Could not create ATTACH'd DB views: {e}")

    def _handle_attach(self, query: str):
        """
        Handle ATTACH command - execute and persist to metadata.

        Parses ATTACH statement, executes it on DuckDB, stores metadata for
        persistence, and creates views for the attached database's tables.

        Args:
            query: ATTACH statement (e.g., "ATTACH '/path/db.duckdb' AS my_db")
        """
        import re

        styled_print(f"[{self.session_id}]   {S.LINK} ATTACH command detected")

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
            styled_print(f"[{self.session_id}]      {S.OK} Attached: {db_path} AS {db_alias}")

            # 2. Store in metadata (only for persistent databases)
            if self.is_persistent_db:
                try:
                    # Delete if exists, then insert (simpler than INSERT OR REPLACE)
                    self.duckdb_conn.execute(
                        "DELETE FROM _lars_attachments WHERE database_alias = ?",
                        [db_alias]
                    )
                    self.duckdb_conn.execute("""
                        INSERT INTO _lars_attachments (id, database_alias, database_path)
                        VALUES (nextval('_lars_attachments_seq'), ?, ?)
                    """, [db_alias, db_path])
                    styled_print(f"[{self.session_id}]      {S.OK} Stored in metadata")
                except Exception as e:
                    styled_print(f"[{self.session_id}]      {S.WARN}  Could not store metadata: {e}")

            # 3. Create views for attached database tables
            self._create_attached_db_views()

            # 4. Send success response
            self.sock.sendall(CommandComplete.encode('ATTACH'))
            self.sock.sendall(ReadyForQuery.encode('I'))
            styled_print(f"[{self.session_id}]   {S.DONE} ATTACH complete")

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
            styled_print(f"[{self.session_id}]   {S.DEL}  DETACH {db_name} - cleaning up...")

            # Remove from metadata table (persistent databases only)
            if self.is_persistent_db:
                try:
                    deleted = self.duckdb_conn.execute(
                        "DELETE FROM _lars_attachments WHERE database_alias = ?",
                        [db_name]
                    )
                    styled_print(f"[{self.session_id}]      {S.DEL}  Removed from metadata")
                except Exception as e:
                    styled_print(f"[{self.session_id}]      {S.WARN}  Could not remove metadata: {e}")

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
                styled_print(f"[{self.session_id}]      {S.WARN}  Could not cleanup views: {e}")

        # Execute the actual DETACH command
        try:
            self.duckdb_conn.execute(query)
            self.sock.sendall(CommandComplete.encode('DETACH'))
            self.sock.sendall(ReadyForQuery.encode('I'))
            styled_print(f"[{self.session_id}]   {S.OK} DETACH executed")

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
            styled_print(f"[{self.session_id}]   {S.DONE} Registered refresh_attached_views() UDF")

        except Exception as e:
            # "already created" is expected when multiple connections share DuckDB
            if "already created" in str(e).lower():
                pass  # Silently skip - UDF is already there
            else:
                styled_print(f"[{self.session_id}]   {S.WARN}  Could not register refresh UDF: {e}")

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
                            WHEN setting_name = 'search_path' THEN 'main, pg_catalog'
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

            # pg_enum - enum types (empty stub)
            try:
                self.duckdb_conn.execute("""
                    CREATE OR REPLACE VIEW pg_catalog.pg_enum AS
                    SELECT
                        0::INTEGER as oid,
                        0::INTEGER as enumtypid,
                        0::REAL as enumsortorder,
                        ''::VARCHAR as enumlabel
                    WHERE false
                """)
                stubs_created.append("pg_enum")
            except Exception as e:
                pass

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

            if stubs_created:
                styled_print(f"[{self.session_id}]   {S.DONE} Created PG compat stubs: {', '.join(stubs_created)}")

        except Exception as e:
            styled_print(f"[{self.session_id}]   {S.WARN}  Error creating PG compat stubs: {e}")

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
            print(f"[{self.session_id or self.addr}]   🔎 Startup params: {startup_params}")

        # Store database name for session setup
        self.database_name = database

        # Create unique session_id per client connection
        # Each client needs its own connection for thread safety
        client_id = uuid.uuid4().hex[:8]
        self.session_id = f"{self.session_prefix}_{database}_{client_id}"

        # Determine persistence mode
        is_persistent = database.lower() not in ('memory', 'default', ':memory:')
        mode_text = "persistent" if is_persistent else "in-memory"

        styled_print(f"[{self.session_id}] {S.LINK} Client startup:")
        print(f"   User: {user}")
        print(f"   Database: {database} ({mode_text})")
        print(f"   Application: {application_name}")

        # Note: send_startup_response is called AFTER setup_session in handle()

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

        styled_print(f"[{self.session_id}] {S.LINK} Set caller_context: {caller_id} → registry[{self.session_id}] ({len(attachments)} attachments)")

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
                get_cascade_paths, get_cascade_summary, clear_cascade_executions
            )
            from lars.caller_context import clear_caller_context

            duration_ms = (time.time() - query_start_time) * 1000

            cascade_paths = get_cascade_paths(caller_id) if caller_id else []
            cascade_summary = get_cascade_summary(caller_id) if caller_id else {}

            result_kwargs = {}
            if result_location:
                # New format: results stored in ClickHouse (lars_results.query_results)
                # The API will query ClickHouse directly using caller_id
                if result_location.get('stored_in') == 'clickhouse':
                    # Just log that we have results, actual data is in lars_results database
                    styled_print(f"[{self.session_id}]   {S.LOG} Results stored in ClickHouse: caller_id={result_location.get('caller_id')}, rows={result_location.get('row_count')}")
                else:
                    # Legacy format (DuckDB) - for backwards compatibility
                    result_kwargs = {
                        'result_db_name': result_location.get('db_name'),
                        'result_db_path': result_location.get('db_path'),
                        'result_schema': result_location.get('schema_name'),
                        'result_table': result_location.get('table_name'),
                    }
                    styled_print(f"[{self.session_id}]   {S.LOG} Logging result location to SQL Trail: {result_kwargs}")

            log_query_complete(
                query_id=query_id,
                status='completed',
                rows_output=len(result_df) if result_df is not None else 0,
                duration_ms=duration_ms,
                cascade_paths=cascade_paths,
                cascade_count=cascade_summary.get('cascade_count', 0),
                **result_kwargs
            )

            if caller_id:
                clear_cascade_executions(caller_id)
            clear_caller_context(connection_id=self.session_id)

        except Exception as e:
            styled_print(f"[{self.session_id}]   {S.WARN}  SQL Trail completion log failed: {e}")

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
            styled_print(f"[{self.session_id}]   {S.WARN}  SQL Trail error log failed: {e}")

    def handle_query(self, query: str):
        """
        Execute query on DuckDB and send results to client.

        Args:
            query: SQL query string (may include lars_udf(), lars_cascade_udf())
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

                        styled_print(f"[{self.session_id}]      {S.SEARCH} Parsing normalized query: {normalized[:100]}...")
                        stmt = _parse_lars_statement(normalized)
                        styled_print(f"[{self.session_id}]      {S.OK} Parsed: mode={stmt.mode}, parallel={stmt.parallel}, as_table={stmt.with_options.get('as_table')}")

                        # SPECIAL PATH 1: MAP PARALLEL (true concurrency)
                        # SPECIAL PATH 2: Table materialization (CREATE TABLE AS or WITH as_table)
                        # Both need server-side handling to avoid DuckDB timing issues

                        if stmt.mode == 'MAP' and (stmt.parallel or stmt.with_options.get('as_table')):
                            is_parallel = stmt.parallel is not None
                            is_materialized = stmt.with_options.get('as_table') is not None

                            if is_parallel and is_materialized:
                                styled_print(f"[{self.session_id}]   {S.RUN} MAP PARALLEL + Materialization: {stmt.parallel} workers → {stmt.with_options['as_table']}")
                            elif is_parallel:
                                styled_print(f"[{self.session_id}]   {S.RUN} MAP PARALLEL detected: {stmt.parallel} workers")
                            else:
                                styled_print(f"[{self.session_id}]   {S.SAVE} Table materialization: {stmt.with_options['as_table']}")

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
                                styled_print(f"[{self.session_id}]      {S.CFG} DISTINCT applied: {original_count} → {deduped_count} rows ({savings:.0f}% reduction)")

                        if not re.search(r'\bLIMIT\s+\d+', using_query, re.IGNORECASE):
                            using_query += ' LIMIT 1000'  # Safety

                        styled_print(f"[{self.session_id}]      {S.CHART} Fetching input rows...")
                        input_df = self.duckdb_conn.execute(using_query).fetchdf()
                        styled_print(f"[{self.session_id}]      {S.OK} Got {len(input_df)} input rows")

                        # 2. Convert to JSON array for parallel processing
                        import json
                        rows_json = json.dumps(input_df.to_dict('records'))

                        # 3. Execute (parallel or sequential)
                        result_column = stmt.result_alias or stmt.with_options.get('result_column', 'result')

                        if is_parallel:
                            styled_print(f"[{self.session_id}]      {S.FAST} Executing in parallel ({stmt.parallel} workers)...")
                            from lars.sql_tools.udf import lars_map_parallel_exec

                            result_df = lars_map_parallel_exec(
                                cascade_path=stmt.cascade_path,
                                rows_json_array=rows_json,
                                max_workers=stmt.parallel,
                                result_column=result_column
                            )
                            styled_print(f"[{self.session_id}]      {S.OK} Parallel execution complete")
                        else:
                            # Sequential execution for non-parallel materialization
                            styled_print(f"[{self.session_id}]      {S.RETRY} Executing sequentially for materialization...")
                            # Use the regular rewritten query but execute row-by-row
                            from lars.sql_rewriter import _rewrite_map
                            from dataclasses import replace

                            # Build statement without as_table to get clean execution query
                            temp_stmt_options = dict(stmt.with_options)
                            temp_stmt_options.pop('as_table', None)  # Remove to avoid recursive materialization

                            # Create new statement with modified options
                            temp_stmt = replace(stmt, with_options=temp_stmt_options)

                            styled_print(f"[{self.session_id}]      {S.SEARCH} Rewriting query without as_table...")
                            rewritten_query = _rewrite_map(temp_stmt)
                            styled_print(f"[{self.session_id}]      {S.SEARCH} Executing rewritten query...")
                            result_df = self.duckdb_conn.execute(rewritten_query).fetchdf()
                            styled_print(f"[{self.session_id}]      {S.OK} Sequential execution complete ({len(result_df)} rows)")

                        # 4. Apply schema extraction if specified
                        if stmt.output_columns:
                            styled_print(f"[{self.session_id}]      {S.CFG} Applying schema extraction...")
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
                            styled_print(f"[{self.session_id}]      {S.SAVE} Materializing to table: {as_table}")
                            # Register and create table
                            self.duckdb_conn.register("_temp_materialize", result_df)
                            self.duckdb_conn.execute(f"CREATE OR REPLACE TEMP TABLE {as_table} AS SELECT * FROM _temp_materialize")
                            self.duckdb_conn.unregister("_temp_materialize")
                            styled_print(f"[{self.session_id}]      {S.OK} Table created: {as_table}")

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
                            styled_print(f"[{self.session_id}]   {S.DONE} MAP PARALLEL + Materialized: {len(result_df)} rows, {stmt.parallel} workers → {stmt.with_options['as_table']}")
                        elif is_parallel:
                            styled_print(f"[{self.session_id}]   {S.DONE} MAP PARALLEL complete: {len(result_df)} rows, {stmt.parallel} workers")
                        else:
                            styled_print(f"[{self.session_id}]   {S.DONE} Materialized to table: {stmt.with_options['as_table']} ({len(result_df)} rows)")

                        # Log query completion for SQL Trail (special path)
                        # Uses unified helper for consistent logging
                        self._complete_query_tracking(
                            _current_query_id, _query_start_time, _caller_id, result_df,
                            result_location=_result_location if '_result_location' in dir() else None
                        )

                        return  # Skip normal execution path

                    except Exception as parallel_error:
                        # If parallel execution fails, log and fall back to normal path
                        styled_print(f"[{self.session_id}]   {S.WARN}  Special path failed: {parallel_error}")
                        traceback.print_exc()  # Use module-level import
                        print(f"[{self.session_id}]      Falling back to sequential execution")
                        # Fall through to normal execution

            # Check for prewarm sidecar opportunity (-- @ parallel: N annotation)
            # IMPORTANT: Must run BEFORE rewrite_lars_syntax which strips comments!
            # This launches a background thread to warm the cache for scalar semantic functions
            prewarm_sidecar = None
            original_query = query  # Preserve original with annotations
            styled_print(f"[{self.session_id}]   {S.CLIP} Prewarm check starting...")
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
                        styled_print(f"[{self.session_id}]   {S.RUN} Prewarm: Generated caller_id {prewarm_caller_id}")

                if prewarm_caller_id:
                    prewarm_sidecar = maybe_launch_prewarm_sidecar(
                        query=original_query,  # Use original query with annotations
                        caller_id=prewarm_caller_id,
                        duckdb_conn=self.duckdb_conn,
                    )
            except Exception as prewarm_e:
                # Prewarm failures are non-fatal
                styled_print(f"[{self.session_id}]   {S.WARN}  Prewarm check failed: {prewarm_e}")

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

            styled_print(f"[{self.session_id}]   {S.OK} Returned {len(result_df)} rows")

            # Log query completion for SQL Trail (if we started tracking)
            # Uses unified helper for consistent logging
            self._complete_query_tracking(
                _current_query_id, _query_start_time, _caller_id, result_df,
                result_location=_result_location
            )

        except Exception as e:
            # Send error to client
            error_message = str(e)
            error_detail = traceback.format_exc()

            # Log query error for SQL Trail
            # Uses unified helper for consistent logging
            self._error_query_tracking(_current_query_id, _query_start_time, e)

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

        styled_print(f"[{self.session_id}]   {S.CLIP} Catalog query detected: {query[:80]}...")

        try:
            # ACL aggregation queries (DataGrip) often UNION tablespace + database ACLs.
            # DuckDB's pg_database lacks datacl, so return an empty but correctly-shaped result.
            if 'PG_TABLESPACE' in query_upper and 'PG_DATABASE' in query_upper and 'DATACL' in query_upper:
                cols = self._expected_result_columns(query) or ['object_id', 'acl']
                send_query_results(self.sock, self._empty_df_for_columns(cols), self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} ACL union catalog query handled (empty)")
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

                db_description = 'LARS Persistent Database' if self.is_persistent_db else 'LARS In-Memory Database'
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
                styled_print(f"[{self.session_id}]   {S.OK} pg_database → {self.database_name}")
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
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_namespace query for schema browser...")
                try:
                    # Get expected columns from the query
                    expected_cols = self._expected_result_columns(query) or ['id', 'state_number', 'name', 'description', 'owner']
                    print(f"[{self.session_id}]      Expected columns: {expected_cols}")

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
                                row_dict[col] = self.user_name
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
                                else:
                                    new_row[col] = None
                            result_df = pd.concat([result_df, pd.DataFrame([new_row])], ignore_index=True)

                    # Sort by name column if available
                    if name_col and name_col in result_df.columns:
                        result_df = result_df.sort_values(name_col).reset_index(drop=True)

                    # Debug: show what schemas we found
                    styled_print(f"[{self.session_id}]   {S.CLIP} Schemas found ({len(result_df)}):")
                    for _, row in result_df.head(10).iterrows():
                        display_val = row.get(name_col, row.iloc[0]) if name_col else row.iloc[0]
                        print(f"[{self.session_id}]      - {display_val}")

                    send_query_results(self.sock, result_df, self.transaction_status)
                    styled_print(f"[{self.session_id}]   {S.DONE} pg_namespace handled ({len(result_df)} schemas)")
                    return
                except Exception as e:
                    styled_print(f"[{self.session_id}]   {S.WARN}  Could not handle pg_namespace: {e}")
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
                styled_print(f"[{self.session_id}]   {S.OK} CURRENT_DATABASE() → {self.database_name}")
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
                styled_print(f"[{self.session_id}]   {S.OK} CURRENT_SCHEMA(S) handled")
                return

            if 'VERSION()' in query_upper:
                # Return PostgreSQL-compatible version string (avoid mentioning DuckDB to prevent IDE mode switching)
                version_str = "PostgreSQL 14.0 on x86_64-pc-linux-gnu, compiled by gcc"
                result_df = pd.DataFrame({'version': [version_str]})
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} VERSION() → {version_str}")
                return

            if 'HAS_TABLE_PRIVILEGE' in query_upper or 'HAS_SCHEMA_PRIVILEGE' in query_upper:
                result_df = pd.DataFrame({'has_privilege': [True]})
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} HAS_PRIVILEGE function handled")
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
                    styled_print(f"[{self.session_id}]   {S.WARN}  Could not load SQL registry: {e}")

                # Build result DataFrame
                lars_keywords = [(word, 'U', 'unreserved (LARS)') for word in sorted(keywords)]
                result_df = pd.DataFrame(lars_keywords, columns=['word', 'catcode', 'catdesc'])
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} PG_GET_KEYWORDS() → {len(lars_keywords)} LARS keywords")
                return

            # Special case 5: pg_locks (DataGrip queries this for transaction info)
            if 'PG_LOCKS' in query_upper:
                # Return empty result - we don't track locks
                result_df = pd.DataFrame({'transaction_id': pd.Series([], dtype='int64')})
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_locks handled (empty)")
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
                styled_print(f"[{self.session_id}]   {S.OK} pg_is_in_recovery() handled (false)")
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
                styled_print(f"[{self.session_id}]   {S.OK} pg_stat_activity handled")
                return

            # Handle pg_timezone_names/pg_timezone_abbrevs (DataGrip queries these)
            if 'PG_TIMEZONE_NAMES' in query_upper or 'PG_TIMEZONE_ABBREVS' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling timezone catalog query...")
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
                styled_print(f"[{self.session_id}]   {S.OK} timezone catalog handled")
                return

            # Handle pg_roles (DataGrip queries this for user management)
            if 'PG_ROLES' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_roles query...")
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
                styled_print(f"[{self.session_id}]   {S.OK} pg_roles handled")
                return

            # Handle pg_user_mappings (DataGrip queries for FDW user mappings)
            # Must check before pg_user to avoid false match
            if 'PG_USER_MAPPINGS' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_user_mappings query...")
                cols = self._expected_result_columns(query) or ['id', 'server_id', 'user', 'options']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_user_mappings handled (empty)")
                return

            # Handle pg_user (DataGrip queries this for user permissions)
            # Exclude pg_user_mappings which contains 'PG_USER'
            if 'PG_USER' in query_upper and 'FROM' in query_upper and 'PG_USER_MAPPINGS' not in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_user query...")
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
                styled_print(f"[{self.session_id}]   {S.OK} pg_user handled")
                return

            # Handle pg_auth_members (DataGrip queries for role membership)
            if 'PG_AUTH_MEMBERS' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_auth_members query...")
                cols = self._expected_result_columns(query) or ['id', 'role_id', 'admin_option']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_auth_members handled (empty)")
                return

            # Handle pg_language (DataGrip queries for procedural languages)
            if 'PG_LANGUAGE' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_language query...")
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
                styled_print(f"[{self.session_id}]   {S.OK} pg_language handled ({len(languages)} languages)")
                return

            # Handle pg_cast queries (DataGrip queries for type casting information)
            if 'PG_CAST' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_cast query...")
                cols = self._expected_result_columns(query) or ['oid', 'castsource', 'casttarget', 'castfunc', 'castcontext', 'castmethod']
                # Return empty - DuckDB doesn't have pg_cast
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_cast handled (empty)")
                return

            # Handle pg_collation queries (DataGrip queries for collation information)
            if self._primary_from_table(query_upper) == 'PG_COLLATION':
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_collation query...")
                cols = self._expected_result_columns(query) or ['oid', 'collname', 'collnamespace', 'collowner']
                # Return empty - DuckDB doesn't have pg_collation
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_collation handled (empty)")
                return

            # Handle pg_inherits queries (including subqueries) - DuckDB doesn't have inheritance
            # Only match if pg_inherits is the main table, not just a LEFT JOIN in a pg_class query
            if 'PG_INHERITS' in query_upper and 'PG_CLASS' not in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_inherits query...")
                cols = self._expected_result_columns(query) or ['inhrelid', 'inhparent', 'inhseqno']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_inherits handled (empty)")
                return

            # Handle pg_partitioned_table queries - DuckDB doesn't have table partitioning metadata
            if 'PG_PARTITIONED_TABLE' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_partitioned_table query...")
                cols = self._expected_result_columns(query) or ['partrelid', 'partstrat', 'partnatts']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_partitioned_table handled (empty)")
                return

            # Handle pg_operator queries - DuckDB doesn't have pg_operator
            if self._primary_from_table(query_upper) == 'PG_OPERATOR':
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_operator query...")
                cols = self._expected_result_columns(query) or ['oid', 'oprname', 'oprnamespace', 'oprowner']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_operator handled (empty)")
                return

            # Handle pg_aggregate queries - DuckDB doesn't have pg_aggregate
            if 'PG_AGGREGATE' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_aggregate query...")
                cols = self._expected_result_columns(query) or ['aggfnoid', 'aggkind', 'aggnumdirectargs']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_aggregate handled (empty)")
                return

            # Handle complex pg_constraint queries with PostgreSQL-specific array functions
            # These use UNNEST, regoper::varchar etc. that don't work in DuckDB
            if 'PG_CONSTRAINT' in query_upper and ('CONEXCLOP' in query_upper or 'UNNEST' in query_upper or 'REGOPER' in query_upper):
                styled_print(f"[{self.session_id}]   {S.CFG} Handling complex pg_constraint query...")
                cols = self._expected_result_columns(query) or ['oid', 'conname', 'connamespace', 'contype']
                result_df = pd.DataFrame(columns=cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_constraint (complex) handled (empty)")
                return

            # Handle pg_tablespace queries (DataGrip queries this)
            if 'PG_TABLESPACE' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_tablespace query...")
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
                styled_print(f"[{self.session_id}]   {S.OK} pg_tablespace handled")
                return

            # Handle pg_extension (DataGrip queries for extensions)
            if 'PG_EXTENSION' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_extension query...")
                cols = self._expected_result_columns(query) or ['oid', 'extname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_extension handled (empty)")
                return

            # Handle pg_cast (DataGrip queries for type casts)
            if 'PG_CAST' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_cast query...")
                cols = self._expected_result_columns(query) or ['oid', 'castsource', 'casttarget']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_cast handled (empty)")
                return

            # Handle pg_collation (DataGrip queries for collations)
            if self._primary_from_table(query_upper) == 'PG_COLLATION':
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_collation query...")
                cols = self._expected_result_columns(query) or ['oid', 'collname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_collation handled (empty)")
                return

            # Handle pg_inherits (DataGrip queries for table inheritance)
            # Only match if pg_inherits is the main table, not just a LEFT JOIN in a pg_class query
            if 'PG_INHERITS' in query_upper and 'FROM' in query_upper and 'PG_CLASS' not in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_inherits query...")
                cols = self._expected_result_columns(query) or ['inhrelid', 'inhparent', 'inhseqno']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_inherits handled (empty)")
                return

            # Handle pg_foreign_table (DataGrip queries for foreign tables)
            if 'PG_FOREIGN_TABLE' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_foreign_table query...")
                cols = self._expected_result_columns(query) or ['ftrelid', 'ftserver', 'ftoptions']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_foreign_table handled (empty)")
                return

            # Handle pg_foreign_data_wrapper (DataGrip queries for FDW)
            if 'PG_FOREIGN_DATA_WRAPPER' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_foreign_data_wrapper query...")
                cols = self._expected_result_columns(query) or ['oid', 'fdwname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_foreign_data_wrapper handled (empty)")
                return

            # Handle pg_operator (DataGrip queries for operators)
            if self._primary_from_table(query_upper) == 'PG_OPERATOR':
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_operator query...")
                cols = self._expected_result_columns(query) or ['oid', 'oprname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_operator handled (empty)")
                return

            # Handle pg_foreign_server (DataGrip queries for FDW servers)
            if 'PG_FOREIGN_SERVER' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_foreign_server query...")
                cols = self._expected_result_columns(query) or ['oid', 'srvname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_foreign_server handled (empty)")
                return

            # Handle pg_event_trigger (DataGrip queries for event triggers)
            if 'PG_EVENT_TRIGGER' in query_upper and 'FROM' in query_upper:
                styled_print(f"[{self.session_id}]   {S.CFG} Handling pg_event_trigger query...")
                cols = self._expected_result_columns(query) or ['oid', 'evtname']
                result_df = self._empty_df_for_columns(cols)
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} pg_event_trigger handled (empty)")
                return

            # Special case 4: pg_class queries with regclass type columns
            # DBeaver queries pg_class with c.*, which has regclass-typed columns
            # Even after column rewriting, JOIN conditions and functions still fail
            # Solution: Replace entire query with pg_tables equivalent
            if 'FROM PG_CATALOG.PG_CLASS' in query_upper and 'C.*' in query_upper:
                # Log the FULL original query for debugging
                styled_print(f"[{self.session_id}]   {S.LOG} ORIGINAL QUERY:")
                print(f"[{self.session_id}]      {query[:500]}")
                if len(query) > 500:
                    print(f"[{self.session_id}]      ... (truncated)")

                styled_print(f"[{self.session_id}]   {S.CFG} Bypassing pg_class query (using compatible columns)...")
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
                    styled_print(f"[{self.session_id}]   {S.CHART} Returning {len(result_df)} relations:")
                    for idx, row in result_df.head(5).iterrows():
                        print(f"[{self.session_id}]      - {row['relname']} (kind={row['relkind']}, namespace={row['relnamespace']})")

                    send_query_results(self.sock, result_df, self.transaction_status)
                    styled_print(f"[{self.session_id}]   {S.DONE} Data sent successfully")
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
                styled_print(f"[{self.session_id}]   {S.LOG} ORIGINAL pg_attribute QUERY:")
                print(f"[{self.session_id}]      {query[:500]}")

                styled_print(f"[{self.session_id}]   {S.CFG} Bypassing pg_attribute query (using safe columns)...")
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

                    styled_print(f"[{self.session_id}]   {S.CHART} Returning {len(result_df)} columns:")
                    for idx, row in result_df.head(10).iterrows():
                        print(f"[{self.session_id}]      - {row['relname']}.{row['attname']} (type={row['atttypid']}, notnull={row['attnotnull']})")

                    send_query_results(self.sock, result_df, self.transaction_status)
                    styled_print(f"[{self.session_id}]   {S.DONE} Column data sent successfully")
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
                    # Rewrite pg_inherits subqueries FIRST (DuckDB doesn't have pg_inherits)
                    clean_query = self._rewrite_pg_inherits_subqueries(clean_query)
                    clean_query = self._rewrite_pg_get_expr_calls(clean_query)
                    clean_query = self._rewrite_pg_catalog_function_calls(clean_query)
                    clean_query = self._rewrite_information_schema_catalog_filters(clean_query)
                    clean_query = self._rewrite_pg_system_column_refs(clean_query)
                    result_df = self.duckdb_conn.execute(clean_query).fetchdf()
                    send_query_results(self.sock, result_df, self.transaction_status)
                    styled_print(f"[{self.session_id}]   {S.OK} Type cast query handled")
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
                styled_print(f"[{self.session_id}]   {S.OK} Catalog query executed ({len(result_df)} rows)")
                return

            except Exception as query_error:
                # Query failed - this might be a complex pg_catalog query we don't support
                styled_print(f"[{self.session_id}]   {S.WARN}  Catalog query failed: {str(query_error)[:100]}")

                # Fallback: Return empty result (safe - clients handle this gracefully)
                cols = self._expected_result_columns(query)
                empty_df = self._empty_df_for_columns(cols) if cols else pd.DataFrame()
                send_query_results(self.sock, empty_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} Returned empty result (fallback)")

        except Exception as e:
            # Complete failure - return empty result to keep client from crashing
            styled_print(f"[{self.session_id}]   {S.WARN}  Catalog query handler error: {e}")
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

        send_execute_results(self.sock, result_df, send_row_description=send_row_description)
        styled_print(f"[{self.session_id}]      {S.OK} SHOW handled, returned {len(result_df)} rows (row_desc={'sent' if send_row_description else 'skipped'})")

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

        styled_print(f"[{self.session_id}]   {S.CLIP} SHOW command detected: {query[:60]}...")

        try:
            # SHOW search_path - schema search order
            if 'SEARCH_PATH' in query_upper:
                result_df = pd.DataFrame({'search_path': ['main, pg_catalog']})
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} SHOW search_path handled")
                return

            # SHOW timezone
            if 'TIMEZONE' in query_upper or 'TIME ZONE' in query_upper:
                result_df = pd.DataFrame({'TimeZone': ['UTC']})
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} SHOW timezone handled")
                return

            # SHOW server_version
            if 'SERVER_VERSION' in query_upper:
                result_df = pd.DataFrame({'server_version': ['14.0']})
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} SHOW server_version handled")
                return

            # SHOW client_encoding
            if 'CLIENT_ENCODING' in query_upper:
                result_df = pd.DataFrame({'client_encoding': ['UTF8']})
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} SHOW client_encoding handled")
                return

            # SHOW transaction isolation level
            if 'TRANSACTION' in query_upper and 'ISOLATION' in query_upper:
                result_df = pd.DataFrame({'transaction_isolation': ['read committed']})
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} SHOW transaction isolation level handled")
                return

            # SHOW tables - this DuckDB supports natively!
            if 'TABLES' in query_upper:
                result_df = self.duckdb_conn.execute(query).fetchdf()
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} SHOW tables executed ({len(result_df)} rows)")
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
                    styled_print(f"[{self.session_id}]   {S.OK} SHOW RESULTS: {len(result_df)} entries")
                    return
                except Exception as e:
                    styled_print(f"[{self.session_id}]   {S.WARN}  SHOW RESULTS failed: {e}")
                    result_df = pd.DataFrame({'error': [str(e)]})
                    send_query_results(self.sock, result_df, self.transaction_status)
                    return

            # Try to execute on DuckDB (might work for some SHOW commands)
            try:
                result_df = self.duckdb_conn.execute(query).fetchdf()
                send_query_results(self.sock, result_df, self.transaction_status)
                styled_print(f"[{self.session_id}]   {S.OK} SHOW command executed on DuckDB")
            except Exception as e:
                # DuckDB doesn't support this SHOW command - return empty
                styled_print(f"[{self.session_id}]   {S.INFO}  Unsupported SHOW command, returning empty")
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
                styled_print(f"[{self.session_id}]   {S.INFO}  Already in transaction, auto-committing previous")
                self.duckdb_conn.execute("COMMIT")

            # Start new transaction
            self.duckdb_conn.execute("BEGIN TRANSACTION")
            self.transaction_status = 'T'

            self.sock.sendall(CommandComplete.encode('BEGIN'))
            if send_ready:
                self.sock.sendall(ReadyForQuery.encode('T'))  # 'T' = in transaction
            styled_print(f"[{self.session_id}]   {S.OK} BEGIN transaction")

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
                styled_print(f"[{self.session_id}]   {S.WARN}  Transaction in error state, auto-rolling back")
                self.duckdb_conn.execute("ROLLBACK")
            elif self.transaction_status == 'T':
                # Commit active transaction
                self.duckdb_conn.execute("COMMIT")
            # else: not in transaction, that's fine

            self.transaction_status = 'I'

            self.sock.sendall(CommandComplete.encode('COMMIT'))
            if send_ready:
                self.sock.sendall(ReadyForQuery.encode('I'))  # 'I' = idle
            styled_print(f"[{self.session_id}]   {S.OK} COMMIT transaction")

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
            styled_print(f"[{self.session_id}]   {S.OK} ROLLBACK transaction")

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

                styled_print(f"[{session_id}] {S.RETRY} Background job {job_id} starting")

                # Open fresh DuckDB connection to same database file
                bg_conn = duckdb.connect(db_path)
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

                # Rewrite the query (handles LARS syntax, semantic operators, etc.)
                from ..sql_rewriter import rewrite_lars_syntax
                rewritten = rewrite_lars_syntax(query, duckdb_conn=bg_conn)

                # Debug: print rewritten query
                styled_print(f"[{session_id}] {S.LOG} Rewritten query (first 500 chars):")
                print(rewritten[:500])

                # Execute
                result = bg_conn.execute(rewritten)
                result_df = result.fetchdf() if result else pd.DataFrame()

                styled_print(f"[{session_id}] {S.CHART} Background job {job_id} executed, {len(result_df)} rows")

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

                        styled_print(f"[{session_id}] {S.SAVE} Background job {job_id} materialized to {full_result_table}")

                    except Exception as mat_err:
                        styled_print(f"[{session_id}] {S.WARN}  Background job {job_id} materialization failed: {mat_err}")

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

                styled_print(f"[{session_id}] {S.DONE} Background job {job_id} completed: {len(result_df)} rows in {duration_ms:.0f}ms")

            except Exception as e:
                tb_module.print_exc()
                duration_ms = (time.time() - bg_start) * 1000
                log_query_error(internal_query_id, str(e), duration_ms=duration_ms)
                styled_print(f"[{session_id}] {S.ERR} Background job {job_id} failed: {e}")

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
        styled_print(f"[{self.session_id}] {S.RUN} Background job {job_id} submitted → {full_result_table}")

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

                styled_print(f"[{session_id}] {S.SEARCH} Analysis job {job_id} starting: {prompt[:50]}...")

                # Open fresh DuckDB connection
                bg_conn = duckdb.connect(db_path)
                bg_conn.execute("SET threads TO 4")

                # Register UDFs
                from ..sql_tools.udf import register_lars_udf, register_dynamic_sql_functions
                register_lars_udf(bg_conn)
                register_dynamic_sql_functions(bg_conn)

                # Lazy attach configured sources for analysis execution too
                try:
                    from ..sql_tools.config import load_sql_connections
                    from ..sql_tools.lazy_attach import LazyAttachManager
                    LazyAttachManager(bg_conn, load_sql_connections()).ensure_for_query(query, aggressive=False)
                except Exception:
                    pass

                # Rewrite and execute query
                from ..sql_rewriter import rewrite_lars_syntax
                rewritten = rewrite_lars_syntax(query, duckdb_conn=bg_conn)
                result = bg_conn.execute(rewritten)
                result_df = result.fetchdf() if result else pd.DataFrame()

                styled_print(f"[{session_id}] {S.CHART} Analysis job {job_id} query complete: {len(result_df)} rows")

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
                        styled_print(f"[{session_id}] {S.SAVE} Analysis job {job_id} results saved to {full_result_table}")
                    except Exception as mat_err:
                        styled_print(f"[{session_id}] {S.WARN}  Analysis job {job_id} materialization failed: {mat_err}")

                # Format data for LLM
                formatted_data = format_for_llm(result_df, max_rows=100)

                # Call analysis via skill (uses sql_analyze cascade)
                styled_print(f"[{session_id}] {S.AGENT} Analysis job {job_id} calling cascade...")
                try:
                    from ..skill_registry import get_skill
                    analyze_skill = get_skill('sql_analyze')

                    if analyze_skill:
                        # Pass session/caller context for proper observability
                        analysis_result = analyze_skill(
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
                        # Fallback: run cascade directly if skill not registered
                        from ..runner import run_cascade
                        from ..config import get_config
                        import os as os_module
                        cfg = get_config()
                        cascade_path = os_module.path.join(cfg.root_dir, 'cascades', 'sql_analyze.yaml')

                        styled_print(f"[{session_id}] {S.WARN}  sql_analyze skill not found, running cascade directly")

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
                    styled_print(f"[{session_id}] {S.WARN}  Analysis job {job_id} cascade failed: {llm_err}")
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

                    styled_print(f"[{session_id}] {S.LOG} Analysis job {job_id} stored in _analysis table")

                except Exception as store_err:
                    styled_print(f"[{session_id}] {S.WARN}  Analysis job {job_id} failed to store: {store_err}")

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

                styled_print(f"[{session_id}] {S.DONE} Analysis job {job_id} completed in {duration_ms:.0f}ms")

            except Exception as e:
                tb_module.print_exc()
                duration_ms = (time.time() - bg_start) * 1000
                log_query_error(internal_query_id, str(e), duration_ms=duration_ms)
                styled_print(f"[{session_id}] {S.ERR} Analysis job {job_id} failed: {e}")

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
        styled_print(f"[{self.session_id}] {S.SEARCH} Analysis job {job_id} submitted: {prompt[:50]}...")

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
            import traceback
            traceback.print_exc()
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
            styled_print(f"[{self.session_id}] {S.DONE} Created watch '{watch.name}'")

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
            styled_print(f"[{self.session_id}] {S.DONE} Dropped watch '{name}'")
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
        styled_print(f"[{self.session_id}] {S.CLIP} Listed {len(watches)} watches")

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
        styled_print(f"[{self.session_id}] {S.INFO} Described watch '{name}'")

    def _trigger_watch(self, name: str, extended_query_mode: bool = False, send_row_description: bool = True):
        """Force immediate evaluation of a watch."""
        import pandas as pd
        from ..watcher import trigger_watch, get_watch

        watch = get_watch(name)
        if not watch:
            send_error(self.sock, f"Watch '{name}' not found")
            return

        styled_print(f"[{self.session_id}] {S.FAST} Triggering watch '{name}'...")

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
            styled_print(f"[{self.session_id}] {S.DONE} Triggered watch '{name}'")

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
                styled_print(f"[{self.session_id}] {S.DONE} Watch '{directive.name}' {status}")
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
                styled_print(f"[{self.session_id}] {S.DONE} Watch '{directive.name}' poll interval set to {directive.set_value}")
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

        styled_print(f"[{self.session_id}]   {S.CFG} Parse statement '{stmt_name or '(unnamed)'}': {query[:80]}...")

        try:
            # Rewrite LARS MAP/RUN syntax to standard SQL BEFORE preparing
            from lars.sql_rewriter import rewrite_lars_syntax
            original_query = query
            query = rewrite_lars_syntax(query, duckdb_conn=self.duckdb_conn)

            if query != original_query:
                styled_print(f"[{self.session_id}]      {S.RETRY} Rewrote LARS syntax ({len(original_query)} → {len(query)} chars)")
                # Debug: for pg_class queries, show the FROM/WHERE/AND structure
                if 'PG_CLASS' in original_query.upper() and 'RELKIND' in original_query.upper():
                    print(f"[{self.session_id}]      [DEBUG] ORIGINAL query FROM/WHERE structure:")
                    for i, line in enumerate(original_query.split('\n'), 1):
                        line_upper = line.upper().strip()
                        if any(kw in line_upper for kw in ['FROM PG_', 'WHERE ', 'AND RELNAMESPACE', 'LEFT JOIN', 'LEFT OUTER']):
                            print(f"[{self.session_id}]        Line {i}: {line.strip()[:100]}")

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
            self.sock.sendall(ParseComplete.encode())
            styled_print(f"[{self.session_id}]      {S.OK} Statement prepared ({len(param_types)} parameters)")

        except Exception as e:
            print(f"[{self.session_id}]      ✗ Parse error: {e}")
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

        styled_print(f"[{self.session_id}]   {S.LINK} Bind portal '{portal_name or '(unnamed)'}' to statement '{stmt_name or '(unnamed)'}'")

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
            self.sock.sendall(BindComplete.encode())
            styled_print(f"[{self.session_id}]      {S.OK} Parameters bound ({len(params)} values)")

        except Exception as e:
            print(f"[{self.session_id}]      ✗ Bind error: {e}")
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

        styled_print(f"[{self.session_id}]   {S.CLIP} Describe {describe_type} '{name or '(unnamed)'}'")

        try:
            if describe_type == 'S':  # Statement
                if name not in self.prepared_statements:
                    raise Exception(f"Prepared statement '{name}' does not exist")

                stmt = self.prepared_statements[name]

                # Send ParameterDescription
                self.sock.sendall(ParameterDescription.encode(stmt['param_types']))

                # Send NoData (we don't know columns without executing)
                self.sock.sendall(NoData.encode())

                styled_print(f"[{self.session_id}]      {S.OK} Statement described ({len(stmt['param_types'])} parameters)")

            elif describe_type == 'P':  # Portal
                if name not in self.portals:
                    raise Exception(f"Portal '{name}' does not exist")

                portal = self.portals[name]
                query = portal['query']
                params = portal['params']
                query_upper = query.upper().strip()

                # For non-SELECT queries (SET, BEGIN, COMMIT, etc.), return NoData
                is_non_select = (
                    query_upper.startswith('SET ') or
                    query_upper.startswith('RESET ') or
                    query_upper.startswith('BEGIN') or
                    query_upper.startswith('COMMIT') or
                    query_upper.startswith('ROLLBACK') or
                    query_upper.startswith('START TRANSACTION') or
                    query_upper.startswith('END') or
                    query_upper.startswith('DISCARD') or
                    query_upper.startswith('DEALLOCATE') or
                    query_upper.startswith('CLOSE') or
                    query_upper.startswith('LISTEN') or
                    query_upper.startswith('UNLISTEN') or
                    query_upper.startswith('NOTIFY')
                )

                if is_non_select:
                    self.sock.sendall(NoData.encode())
                    portal['row_description_sent'] = False
                    styled_print(f"[{self.session_id}]      {S.OK} Portal described (NoData - non-SELECT command)")
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
                        styled_print(f"[{self.session_id}]      {S.OK} Portal described (WATCH {watch_directive.command} - {len(columns)} columns)")
                    else:
                        # Couldn't parse - send NoData
                        self.sock.sendall(NoData.encode())
                        portal['row_description_sent'] = False
                        styled_print(f"[{self.session_id}]      {S.OK} Portal described (WATCH command - NoData)")
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
                    styled_print(f"[{self.session_id}]      {S.OK} Portal described (SHOW command - {len(columns)} columns)")
                else:
                    # For SELECT queries, try to get column metadata
                    try:
                        # Convert PostgreSQL placeholders to DuckDB format
                        desc_query = query
                        for i in range(len(params), 0, -1):
                            desc_query = desc_query.replace(f'${i}', '?')

                        # Debug: show original query before ANY rewriters for pg_class
                        if 'PG_CLASS' in query_upper and 'RELKIND' in query_upper:
                            print(f"[DEBUG] pg_class: ORIGINAL QUERY STRUCTURE:")
                            for i, line in enumerate(desc_query.split('\n'), 1):
                                if line.strip():
                                    print(f"[DEBUG]   Line {i}: {line.strip()[:100]}")

                        # Apply standard query rewrites
                        desc_query = self._rewrite_pg_catalog_function_calls(desc_query)
                        desc_query = self._rewrite_information_schema_catalog_filters(desc_query)
                        # Debug: track WHERE through rewriters for pg_class table queries
                        is_pg_class_table_query = 'PG_CLASS' in query_upper and 'RELKIND' in query_upper
                        if is_pg_class_table_query:
                            print(f"[DEBUG] pg_class: ORIGINAL QUERY (first 500 chars):")
                            print(f"[DEBUG]   {desc_query[:500]}...")
                            print(f"[DEBUG] pg_class: BEFORE rewriters - WHERE: {'WHERE' in desc_query.upper()}")
                        desc_query = self._rewrite_pg_system_column_refs(desc_query)
                        if is_pg_class_table_query:
                            print(f"[DEBUG] pg_class: AFTER system_refs - WHERE: {'WHERE' in desc_query.upper()}")
                        desc_query = self._rewrite_missing_table_joins(desc_query)
                        # NOTE: UNION stripping disabled - causes parameter count mismatches
                        # desc_query = self._strip_union_parts_with_missing_tables(desc_query)
                        if is_pg_class_table_query:
                            print(f"[DEBUG] pg_class: AFTER missing_joins - WHERE: {'WHERE' in desc_query.upper()}")
                        desc_query = self._rewrite_pg_inherits_subqueries(desc_query)
                        if is_pg_class_table_query:
                            print(f"[DEBUG] pg_class: AFTER pg_inherits - WHERE: {'WHERE' in desc_query.upper()}")
                        desc_query = self._rewrite_pg_get_expr_calls(desc_query)
                        desc_query = self._rewrite_missing_pg_database_columns(desc_query)

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
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (NoData - empty query)")
                            return

                        # Handle special catalog tables that need specific column info
                        # pg_timezone_names / pg_timezone_abbrevs
                        if 'PG_TIMEZONE_NAMES' in query_upper or 'PG_TIMEZONE_ABBREVS' in query_upper:
                            cols = self._expected_result_columns(query) or ['name', 'is_dst']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (timezone catalog - {len(columns)} columns)")
                            return

                        # pg_roles
                        if 'PG_ROLES' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'rolname', 'rolsuper']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_roles - {len(columns)} columns)")
                            return

                        # pg_user - DataGrip checks superuser status
                        if 'PG_USER' in query_upper and 'FROM' in query_upper and 'PG_USER_MAPPINGS' not in query_upper:
                            cols = self._expected_result_columns(query) or ['usename', 'usesuper']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_user - {len(columns)} columns)")
                            return

                        # pg_namespace (schema browser) - provide expected columns
                        is_pg_class_main = 'FROM PG_CATALOG.PG_CLASS' in query_upper or 'FROM PG_CLASS' in query_upper
                        is_pg_namespace_main = ('FROM PG_CATALOG.PG_NAMESPACE' in query_upper or 'FROM PG_NAMESPACE' in query_upper)
                        if is_pg_namespace_main and not is_pg_class_main:
                            cols = self._expected_result_columns(query) or ['id', 'state_number', 'name', 'description', 'owner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_namespace - {len(columns)} columns)")
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
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_class table browser - {len(columns)} columns)")
                            return

                        # pg_event_trigger - DuckDB doesn't have event triggers
                        if 'PG_EVENT_TRIGGER' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'evtname', 'evtevent', 'evtowner', 'evtfoid', 'evtenabled', 'evttags']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_event_trigger - {len(columns)} columns)")
                            return

                        # Foreign data wrapper tables - DuckDB doesn't have FDW
                        if 'PG_FOREIGN_DATA_WRAPPER' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'fdwname', 'fdwowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_foreign_data_wrapper - {len(columns)} columns)")
                            return

                        if 'PG_FOREIGN_SERVER' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'srvname', 'srvowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_foreign_server - {len(columns)} columns)")
                            return

                        if 'PG_FOREIGN_TABLE' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['ftrelid', 'ftserver', 'ftoptions']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_foreign_table - {len(columns)} columns)")
                            return

                        # pg_extension - DuckDB doesn't have extensions
                        if 'PG_EXTENSION' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'extname', 'extowner', 'extnamespace']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_extension - {len(columns)} columns)")
                            return

                        # pg_language - DuckDB doesn't have procedural languages
                        if 'PG_LANGUAGE' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'lanname', 'lanowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_language - {len(columns)} columns)")
                            return

                        # pg_cast - DuckDB doesn't have pg_cast
                        if 'PG_CAST' in query_upper and 'FROM' in query_upper:
                            cols = self._expected_result_columns(query) or ['oid', 'castsource', 'casttarget', 'castfunc', 'castcontext', 'castmethod']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_cast - {len(columns)} columns)")
                            return

                        # pg_collation - DuckDB doesn't have pg_collation
                        if self._primary_from_table(query_upper) == 'PG_COLLATION':
                            cols = self._expected_result_columns(query) or ['oid', 'collname', 'collnamespace', 'collowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_collation - {len(columns)} columns)")
                            return

                        # pg_inherits - DuckDB doesn't have table inheritance
                        # Only match if pg_inherits is the main table, not just a LEFT JOIN in a pg_class query
                        if 'PG_INHERITS' in query_upper and 'PG_CLASS' not in query_upper:
                            cols = self._expected_result_columns(query) or ['inhrelid', 'inhparent', 'inhseqno']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_inherits - {len(columns)} columns)")
                            return

                        # pg_partitioned_table - DuckDB doesn't have partition metadata
                        if 'PG_PARTITIONED_TABLE' in query_upper:
                            cols = self._expected_result_columns(query) or ['partrelid', 'partstrat', 'partnatts']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_partitioned_table - {len(columns)} columns)")
                            return

                        # pg_description - DuckDB doesn't have pg_description
                        # Catches UNION queries where pg_description is the main FROM table
                        if 'FROM PG_CATALOG.PG_DESCRIPTION' in query_upper or 'FROM PG_DESCRIPTION' in query_upper:
                            cols = self._expected_result_columns(query) or ['id', 'sub_ids', 'kind', 'description']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_description - {len(columns)} columns)")
                            return

                        # pg_operator - DuckDB doesn't have pg_operator
                        if self._primary_from_table(query_upper) == 'PG_OPERATOR':
                            cols = self._expected_result_columns(query) or ['oid', 'oprname', 'oprnamespace', 'oprowner']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_operator - {len(columns)} columns)")
                            return

                        # pg_aggregate - DuckDB doesn't have pg_aggregate
                        if 'PG_AGGREGATE' in query_upper:
                            cols = self._expected_result_columns(query) or ['aggfnoid', 'aggkind', 'aggnumdirectargs']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_aggregate - {len(columns)} columns)")
                            return

                        # Complex pg_constraint queries with PostgreSQL-specific array functions
                        if 'PG_CONSTRAINT' in query_upper and ('CONEXCLOP' in query_upper or 'UNNEST' in query_upper or 'REGOPER' in query_upper):
                            cols = self._expected_result_columns(query) or ['oid', 'conname', 'connamespace', 'contype']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_constraint complex - {len(columns)} columns)")
                            return

                        # pg_depend queries with regclass casts - return empty result
                        if 'PG_DEPEND' in query_upper and ('REGCLASS' in query_upper or 'REFOBJID' in query_upper):
                            cols = self._expected_result_columns(query) or ['dependent_id', 'owner_id', 'refobjsubid']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (pg_depend - {len(columns)} columns)")
                            return

                        # Any query with regclass type casts that DuckDB doesn't support
                        if '::REGCLASS' in query_upper or 'REGCLASS' in query_upper:
                            cols = self._expected_result_columns(query) or ['result']
                            columns = [(c, 'VARCHAR') for c in cols]
                            self.sock.sendall(RowDescription.encode(columns))
                            portal['row_description_sent'] = True
                            portal['described_columns'] = len(columns)
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (regclass query - {len(columns)} columns)")
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
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (missing pg_catalog table - {len(columns)} columns)")
                            return

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
                        styled_print(f"[{self.session_id}]      {S.OK} Portal described ({len(columns)} columns)")

                    except Exception as desc_err:
                        # If DuckDB can't parse the query, try to extract columns from the SQL text
                        # This prevents "Received resultset tuples, but no field structure" errors
                        styled_print(f"[{self.session_id}]      {S.WARN}  Could not describe portal via DuckDB: {str(desc_err)[:100]}")

                        # For SELECT queries, try to infer columns from the query text
                        if query_upper.strip().startswith('SELECT'):
                            extracted_cols = self._expected_result_columns(query)
                            if extracted_cols:
                                # Send RowDescription with inferred columns (all as VARCHAR)
                                columns = [(c, 'VARCHAR') for c in extracted_cols]
                                self.sock.sendall(RowDescription.encode(columns))
                                portal['row_description_sent'] = True
                                portal['described_columns'] = len(columns)  # Track for Execute validation
                                styled_print(f"[{self.session_id}]      {S.OK} Portal described (inferred {len(columns)} columns from query)")
                            else:
                                # Can't infer columns - send NoData as last resort
                                # This may cause issues but is better than crashing
                                self.sock.sendall(NoData.encode())
                                portal['row_description_sent'] = False
                                styled_print(f"[{self.session_id}]      {S.OK} Portal described (NoData - couldn't infer columns)")
                        else:
                            # Non-SELECT queries don't return rows
                            self.sock.sendall(NoData.encode())
                            portal['row_description_sent'] = False
                            styled_print(f"[{self.session_id}]      {S.OK} Portal described (NoData - non-SELECT)")

        except Exception as e:
            error_str = str(e)
            print(f"[{self.session_id}]      ✗ Describe error: {error_str[:200]}")

            # Check if this is a "Table does not exist" error for a pg_catalog table
            import re
            missing_table_match = re.search(r"Table with name (\w+) does not exist", error_str, re.IGNORECASE)
            if missing_table_match:
                missing_table = missing_table_match.group(1).lower()
                known_missing = {
                    'pg_trigger', 'pg_rewrite', 'pg_policy', 'pg_policies', 'pg_rules',
                    'pg_operator', 'pg_opclass', 'pg_opfamily', 'pg_aggregate',
                    'pg_cast', 'pg_collation', 'pg_conversion', 'pg_enum', 'pg_range',
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
                    print(f"[{self.session_id}]      → Missing pg_catalog table '{missing_table}' in Describe - sending NoData")
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

        styled_print(f"[{self.session_id}]   {S.EXEC}  Execute portal '{portal_name or '(unnamed)'}' (max_rows={max_rows})")

        # Initialize tracking variables (set properly once we have the portal)
        _query_id, _query_start_time, _caller_id = None, None, None

        try:
            # Get portal
            if portal_name not in self.portals:
                raise Exception(f"Portal '{portal_name}' does not exist")

            portal = self.portals[portal_name]
            query = portal['query']
            params = portal['params']
            original_query = portal.get('original_query')  # For SQL Trail detection

            # Set up SQL Trail tracking if this is an LARS statement
            # Uses original_query (before rewriting) for accurate detection
            _query_id, _query_start_time, _caller_id = self._setup_query_tracking(
                query, original_query=original_query
            )

            # Check if Describe already sent RowDescription
            # If so, Execute should NOT send RowDescription again
            row_desc_already_sent = portal.get('row_description_sent', False)
            send_row_desc = not row_desc_already_sent

            # Check if Describe cached a result for a missing pg_catalog table
            if 'missing_table_result' in portal:
                result_df = portal['missing_table_result']
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} Missing pg_catalog table - returning cached empty result")
                return

            # Check for special PostgreSQL functions and commands
            query_upper = query.upper().strip()

            # Empty query - send EmptyQueryResponse
            if not query_upper or query_upper.startswith('--'):
                print(f"[{self.session_id}]      Empty query detected - sending EmptyQueryResponse")
                self.sock.sendall(EmptyQueryResponse.encode())
                return

            # SHOW commands - Handle via Extended Query
            if query_upper.startswith('SHOW '):
                print(f"[{self.session_id}]      Detected SHOW command via Extended Query")
                # Handle SHOW and send results - skip RowDescription if Describe already sent it
                self._execute_show_and_send_extended(query, send_row_description=send_row_desc)
                return

            # WATCH commands - Handle reactive SQL subscriptions via Extended Query
            from ..sql_tools.sql_directives import is_watch_command
            if is_watch_command(query):
                print(f"[{self.session_id}]      Detected WATCH command via Extended Query")
                self._handle_watch_command(query, extended_query_mode=True, send_row_description=send_row_desc)
                return

            # pg_get_keywords() - Return empty result
            if 'PG_GET_KEYWORDS' in query_upper:
                print(f"[{self.session_id}]      Detected pg_get_keywords() - returning empty")
                import pandas as pd
                send_execute_results(self.sock, pd.DataFrame(columns=['word']), send_row_description=send_row_desc)
                return

            # current_schemas() - Return PostgreSQL array format (DuckDB returns scalar)
            # This is critical for DataGrip which parses the array to build search path
            if 'CURRENT_SCHEMAS(' in query_upper and 'PG_NAMESPACE' not in query_upper:
                print(f"[{self.session_id}]      Detected current_schemas() - returning PostgreSQL array format")
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
                styled_print(f"[{self.session_id}]      {S.OK} current_schemas() → {{main}}")
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
                styled_print(f"[{self.session_id}]      {S.CFG} Handling pg_namespace query for schema browser (Extended)...")
                import pandas as pd
                try:
                    # Get the columns that Describe promised (or use defaults)
                    expected_cols = self._expected_result_columns(query) or ['id', 'state_number', 'name', 'description', 'owner']
                    print(f"[{self.session_id}]      Expected columns: {expected_cols}")

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
                                row_dict[col] = self.user_name
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
                                else:
                                    new_row[col] = None
                            result_df = pd.concat([result_df, pd.DataFrame([new_row])], ignore_index=True)

                    # Sort by name column if available
                    if name_col and name_col in result_df.columns:
                        result_df = result_df.sort_values(name_col).reset_index(drop=True)

                    # Debug: show what schemas we found
                    styled_print(f"[{self.session_id}]      {S.CLIP} Schemas found ({len(result_df)}):")
                    for _, row in result_df.head(10).iterrows():
                        display_val = row.get(name_col, row.iloc[0]) if name_col else row.iloc[0]
                        print(f"[{self.session_id}]         - {display_val}")

                    # Validate column count before sending
                    actual_send_row_desc = send_row_desc
                    if not send_row_desc and portal_name in self.portals:
                        described_col_count = self.portals[portal_name].get('described_columns')
                        if described_col_count is not None and described_col_count != len(expected_cols):
                            styled_print(f"[{self.session_id}]      {S.WARN}  pg_namespace column mismatch: described {described_col_count}, returning {len(expected_cols)}")
                            actual_send_row_desc = True
                    send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)
                    styled_print(f"[{self.session_id}]      {S.DONE} pg_namespace handled ({len(result_df)} schemas)")
                    return
                except Exception as e:
                    styled_print(f"[{self.session_id}]      {S.WARN}  Could not handle pg_namespace: {e}")
                    # Don't fall through - return empty result with expected columns to prevent mismatch
                    expected_cols = self._expected_result_columns(query) or ['id', 'state_number', 'name', 'description', 'owner']
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    styled_print(f"[{self.session_id}]      {S.OK} pg_namespace fallback (empty with {len(expected_cols)} cols)")
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
                    # Validate column count
                    actual_send_row_desc = send_row_desc
                    if not send_row_desc and portal_name in self.portals:
                        described_col_count = self.portals[portal_name].get('described_columns')
                        if described_col_count is not None and described_col_count != len(result_df.columns):
                            styled_print(f"[{self.session_id}]      {S.WARN}  pg_class bypass column mismatch: described {described_col_count}, returning {len(result_df.columns)}")
                            actual_send_row_desc = True
                    send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)
                    styled_print(f"[{self.session_id}]      {S.OK} pg_class bypass executed ({len(result_df)} rows × {len(result_df.columns)} cols)")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]      ✗ Bypass failed: {str(e)[:200]}")
                    # Don't fall through - return empty result with expected columns
                    expected_cols = self._expected_result_columns(query) or ['relkind', 'relname', 'oid']
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    styled_print(f"[{self.session_id}]      {S.OK} pg_class bypass fallback (empty with {len(expected_cols)} cols)")
                    return

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
                    # Validate column count
                    actual_send_row_desc = send_row_desc
                    if not send_row_desc and portal_name in self.portals:
                        described_col_count = self.portals[portal_name].get('described_columns')
                        if described_col_count is not None and described_col_count != len(result_df.columns):
                            styled_print(f"[{self.session_id}]      {S.WARN}  pg_attribute bypass column mismatch: described {described_col_count}, returning {len(result_df.columns)}")
                            actual_send_row_desc = True
                    send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)
                    styled_print(f"[{self.session_id}]      {S.OK} pg_attribute bypass executed ({len(result_df)} rows × {len(result_df.columns)} cols)")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]      ✗ pg_attribute bypass failed: {str(e)[:200]}")
                    # Don't fall through - return empty result with expected columns
                    expected_cols = self._expected_result_columns(query) or ['relname', 'attname', 'attnum']
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    styled_print(f"[{self.session_id}]      {S.OK} pg_attribute bypass fallback (empty with {len(expected_cols)} cols)")
                    return

            # Strip regclass/regtype/regproc casts from ANY other pg_catalog query
            if 'PG_CATALOG' in query_upper and ('::REGCLASS' in query_upper or '::REGTYPE' in query_upper or '::REGPROC' in query_upper or '::OID' in query_upper):
                print(f"[{self.session_id}]      Detected pg_catalog query with type casts - stripping")

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
                            styled_print(f"[{self.session_id}]      {S.WARN}  COLUMN MISMATCH (type cast stripping)!")
                            print(f"[{self.session_id}]         Described: {described_col_count}, Actual: {actual_col_count}")
                            print(f"[{self.session_id}]         Columns: {list(result_df.columns)}")
                            actual_send_row_desc = True  # Resend RowDescription to fix mismatch
                    send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)
                    styled_print(f"[{self.session_id}]      {S.OK} Catalog query executed after stripping type casts ({len(result_df)} rows × {len(result_df.columns)} cols)")
                    return
                except Exception as e:
                    print(f"[{self.session_id}]      ✗ Even after stripping, query failed: {str(e)[:100]}")
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
                            styled_print(f"[{self.session_id}]      {S.WARN}  COLUMN MISMATCH in fallback!")
                            print(f"[{self.session_id}]         Described: {described_col_count}, Inferred: {len(expected_cols)}")
                            # Adjust columns to match described count
                            if described_col_count > len(expected_cols):
                                # Add placeholder columns
                                for i in range(len(expected_cols), described_col_count):
                                    expected_cols.append(f'col_{i+1}')
                            else:
                                # Truncate to described count
                                expected_cols = expected_cols[:described_col_count]
                            print(f"[{self.session_id}]         Adjusted to: {len(expected_cols)} cols")
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)
                    styled_print(f"[{self.session_id}]      {S.OK} Type cast query fallback (empty with {len(expected_cols)} cols)")
                    styled_print(f"[{self.session_id}]      {S.WARN}  ZERO ROWS (fallback) for: {query[:200]}...")
                    return

            # Check if this is a SET or RESET command
            if query_upper.startswith('SET ') or query_upper.startswith('RESET '):
                # Handle SET commands via Extended Query Protocol
                print(f"[{self.session_id}]      Detected SET/RESET via Extended Query")
                self._execute_set_command(query)
                # Send CommandComplete (SET commands don't return rows!)
                self.sock.sendall(CommandComplete.encode('SET'))
                styled_print(f"[{self.session_id}]      {S.OK} SET/RESET handled")
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

            # DataGrip: pg_class "table browser" UNION query (object listing across schemas)
            # This UNION includes branches over tables DuckDB doesn't implement (pg_collation, pg_operator, etc.),
            # but DataGrip still expects rows from pg_class/pg_type/pg_proc. Build those parts explicitly.
            if self._is_datagrip_pg_class_table_browser_union(query_upper):
                print(f"[{self.session_id}]      Handling pg_class table browser UNION (DataGrip)...")
                result_df = self._build_datagrip_pg_class_table_browser_union_result(query, params)
                self._validate_custom_handler_columns(portal_name, len(result_df.columns), 'pg_class table browser UNION')
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_class table browser UNION handled ({len(result_df)} rows × {len(result_df.columns)} cols)")
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

            print(f"[{self.session_id}]      Converted query: {duckdb_query[:80]}...")
            print(f"[{self.session_id}]      Parameters: {params}")

            # Handle special catalog queries that need actual data (not just empty results)
            import pandas as pd

            # pg_timezone_names / pg_timezone_abbrevs - return common timezones
            if 'PG_TIMEZONE_NAMES' in query_upper or 'PG_TIMEZONE_ABBREVS' in query_upper:
                print(f"[{self.session_id}]      Handling timezone catalog query...")
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
                styled_print(f"[{self.session_id}]      {S.OK} Timezone catalog handled ({len(result_df)} rows)")
                return

            # pg_roles - return current user as a role
            if 'PG_ROLES' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]      Handling pg_roles query...")
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
                styled_print(f"[{self.session_id}]      {S.OK} pg_roles handled ({len(result_df)} rows, {len(cols)} cols)")
                return

            # pg_user - return current user info (DataGrip checks superuser status)
            if 'PG_USER' in query_upper and 'FROM' in query_upper and 'PG_USER_MAPPINGS' not in query_upper:
                print(f"[{self.session_id}]      Handling pg_user query...")
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
                styled_print(f"[{self.session_id}]      {S.OK} pg_user handled ({len(result_df)} rows, {len(cols)} cols)")
                return

            # pg_event_trigger - return empty result (DuckDB doesn't have event triggers)
            if 'PG_EVENT_TRIGGER' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]      Handling pg_event_trigger query...")
                cols = self._expected_result_columns(query) or ['oid', 'evtname', 'evtevent', 'evtowner', 'evtfoid', 'evtenabled', 'evttags']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_event_trigger handled (empty)")
                return

            # Foreign data wrapper tables - return empty results (DuckDB doesn't have FDW)
            if 'PG_FOREIGN_DATA_WRAPPER' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]      Handling pg_foreign_data_wrapper query...")
                cols = self._expected_result_columns(query) or ['oid', 'fdwname', 'fdwowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_foreign_data_wrapper handled (empty)")
                return

            if 'PG_FOREIGN_SERVER' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]      Handling pg_foreign_server query...")
                cols = self._expected_result_columns(query) or ['oid', 'srvname', 'srvowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_foreign_server handled (empty)")
                return

            if 'PG_FOREIGN_TABLE' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]      Handling pg_foreign_table query...")
                cols = self._expected_result_columns(query) or ['ftrelid', 'ftserver', 'ftoptions']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_foreign_table handled (empty)")
                return

            # pg_extension - return empty result (DuckDB doesn't have extensions)
            if 'PG_EXTENSION' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]      Handling pg_extension query...")
                cols = self._expected_result_columns(query) or ['oid', 'extname', 'extowner', 'extnamespace']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_extension handled (empty)")
                return

            # pg_language - return empty result (DuckDB doesn't have procedural languages)
            if 'PG_LANGUAGE' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]      Handling pg_language query...")
                cols = self._expected_result_columns(query) or ['oid', 'lanname', 'lanowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_language handled (empty)")
                return

            # pg_cast - return empty result (DuckDB doesn't have pg_cast)
            if 'PG_CAST' in query_upper and 'FROM' in query_upper:
                print(f"[{self.session_id}]      Handling pg_cast query...")
                cols = self._expected_result_columns(query) or ['oid', 'castsource', 'casttarget', 'castfunc', 'castcontext', 'castmethod']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_cast handled (empty)")
                return

            # pg_collation - return empty result (DuckDB doesn't have pg_collation)
            if self._primary_from_table(query_upper) == 'PG_COLLATION':
                print(f"[{self.session_id}]      Handling pg_collation query...")
                cols = self._expected_result_columns(query) or ['oid', 'collname', 'collnamespace', 'collowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_collation handled (empty)")
                return

            # pg_inherits - return empty result (DuckDB doesn't have table inheritance)
            # Only match if pg_inherits is the main table, not just a LEFT JOIN in a pg_class query
            if 'PG_INHERITS' in query_upper and 'PG_CLASS' not in query_upper:
                print(f"[{self.session_id}]      Handling pg_inherits query...")
                cols = self._expected_result_columns(query) or ['inhrelid', 'inhparent', 'inhseqno']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_inherits handled (empty)")
                return

            # pg_partitioned_table - return empty result (DuckDB doesn't have partition metadata)
            if 'PG_PARTITIONED_TABLE' in query_upper:
                print(f"[{self.session_id}]      Handling pg_partitioned_table query...")
                cols = self._expected_result_columns(query) or ['partrelid', 'partstrat', 'partnatts']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_partitioned_table handled (empty)")
                return

            # pg_description - return empty result (DuckDB doesn't have pg_description)
            # This catches UNION queries where pg_description is the main FROM table
            if 'FROM PG_CATALOG.PG_DESCRIPTION' in query_upper or 'FROM PG_DESCRIPTION' in query_upper:
                print(f"[{self.session_id}]      Handling pg_description query (main FROM table)...")
                cols = self._expected_result_columns(query) or ['id', 'sub_ids', 'kind', 'description']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_description handled (empty)")
                return

            # pg_operator - return empty result (DuckDB doesn't have pg_operator)
            if self._primary_from_table(query_upper) == 'PG_OPERATOR':
                print(f"[{self.session_id}]      Handling pg_operator query...")
                cols = self._expected_result_columns(query) or ['oid', 'oprname', 'oprnamespace', 'oprowner']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_operator handled (empty)")
                return

            # pg_aggregate - return empty result (DuckDB doesn't have pg_aggregate)
            if 'PG_AGGREGATE' in query_upper:
                print(f"[{self.session_id}]      Handling pg_aggregate query...")
                cols = self._expected_result_columns(query) or ['aggfnoid', 'aggkind', 'aggnumdirectargs']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_aggregate handled (empty)")
                return

            # Complex pg_constraint queries with PostgreSQL-specific array functions
            if 'PG_CONSTRAINT' in query_upper and ('CONEXCLOP' in query_upper or 'UNNEST' in query_upper or 'REGOPER' in query_upper):
                print(f"[{self.session_id}]      Handling complex pg_constraint query...")
                cols = self._expected_result_columns(query) or ['oid', 'conname', 'connamespace', 'contype']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_constraint (complex) handled (empty)")
                return

            # pg_depend queries with regclass casts - return empty result
            if 'PG_DEPEND' in query_upper and ('REGCLASS' in query_upper or 'REFOBJID' in query_upper):
                print(f"[{self.session_id}]      Handling pg_depend query (regclass)...")
                cols = self._expected_result_columns(query) or ['dependent_id', 'owner_id', 'refobjsubid']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} pg_depend handled (empty)")
                return

            # Any query with regclass type casts that DuckDB doesn't support
            if '::REGCLASS' in query_upper or 'REGCLASS' in query_upper:
                print(f"[{self.session_id}]      Handling regclass query...")
                cols = self._expected_result_columns(query) or ['result']
                result_df = pd.DataFrame(columns=cols)
                send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} regclass query handled (empty)")
                return

            # Handle queries with missing pg_catalog tables (DataGrip introspection)
            missing_table_result = self._handle_missing_pg_catalog_tables(query_upper, duckdb_query)
            if missing_table_result is not None:
                send_execute_results(self.sock, missing_table_result, send_row_description=send_row_desc)
                styled_print(f"[{self.session_id}]      {S.OK} Missing pg_catalog table handled (empty result)")
                if len(missing_table_result) == 0:
                    styled_print(f"[{self.session_id}]      {S.WARN}  ZERO ROWS (missing pg_catalog handler) for: {query[:200]}...")
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
                    styled_print(f"[{self.session_id}]      {S.WARN}  COLUMN MISMATCH DETECTED!")
                    print(f"[{self.session_id}]         Query: {query[:200]}...")
                    print(f"[{self.session_id}]         Described: {described_col_count} cols, Actual: {actual_col_count} cols")
                    print(f"[{self.session_id}]         Actual columns: {list(result_df.columns)}")
                    actual_send_row_desc = True

            # Send results - only include RowDescription if Describe didn't already send it
            send_execute_results(self.sock, result_df, send_row_description=actual_send_row_desc)

            # Debug: log column counts for tracking ArrayIndexOutOfBounds issues
            desc_count = described_col_count if described_col_count is not None else '?'
            if not actual_send_row_desc:
                styled_print(f"[{self.session_id}]      {S.OK} Executed, {len(result_df)} rows × {actual_col_count} cols (desc: {desc_count}, row_desc=skip)")
            else:
                styled_print(f"[{self.session_id}]      {S.OK} Executed, {len(result_df)} rows × {actual_col_count} cols (row_desc=sent)")

            # CRITICAL DEBUG: Log 0-row results - DataGrip may expect data from these queries
            if len(result_df) == 0:
                styled_print(f"[{self.session_id}]      {S.WARN}  ZERO ROWS returned for query (first 300 chars):")
                print(f"[{self.session_id}]         {query[:300]}...")
                # Also log the rewritten query
                print(f"[{self.session_id}]         Rewritten (first 200 chars): {duckdb_query[:200]}...")

            # Auto-materialize for query insurance (Extended Query Protocol)
            _result_location = self._maybe_materialize_result(
                original_query or query, result_df, _query_id, _caller_id
            )

            # Log query completion for SQL Trail (Extended Query Protocol)
            self._complete_query_tracking(
                _query_id, _query_start_time, _caller_id, result_df,
                result_location=_result_location
            )

        except Exception as e:
            error_str = str(e)
            print(f"[{self.session_id}]      ✗ Execute error: {error_str[:200]}")

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
                    'pg_cast', 'pg_collation', 'pg_conversion', 'pg_enum', 'pg_range',
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
                    print(f"[{self.session_id}]      → Missing pg_catalog table '{missing_table}' - returning empty result")
                    # Try to infer expected columns from the query
                    expected_cols = self._expected_result_columns(query)
                    if not expected_cols:
                        # Default columns for common introspection queries
                        expected_cols = ['oid', 'name']
                    import pandas as pd
                    result_df = pd.DataFrame(columns=expected_cols)
                    send_execute_results(self.sock, result_df, send_row_description=send_row_desc)
                    styled_print(f"[{self.session_id}]      {S.OK} Missing table fallback (empty with {len(expected_cols)} cols)")
                    styled_print(f"[{self.session_id}]      {S.WARN}  ZERO ROWS (missing table: {missing_table}) for: {query[:200]}...")
                    return

            # Mark transaction as errored
            if self.transaction_status == 'T':
                self.transaction_status = 'E'
            # In Extended Query Protocol, don't send ReadyForQuery - wait for Sync
            self.sock.sendall(ErrorResponse.encode('ERROR', f"Execute error: {str(e)}"))

            # Log query error for SQL Trail (Extended Query Protocol)
            self._error_query_tracking(_query_id, _query_start_time, e)

    def _handle_close(self, msg: dict):
        """
        Handle Close message - close prepared statement or portal.

        Args:
            msg: Decoded Close message {type, name}
        """
        close_type = msg['type']
        name = msg['name']

        styled_print(f"[{self.session_id}]   {S.DEL}  Close {close_type} '{name or '(unnamed)'}'")

        try:
            if close_type == 'S':  # Statement
                if name in self.prepared_statements:
                    del self.prepared_statements[name]
                    styled_print(f"[{self.session_id}]      {S.OK} Statement closed")
            elif close_type == 'P':  # Portal
                if name in self.portals:
                    del self.portals[name]
                    styled_print(f"[{self.session_id}]      {S.OK} Portal closed")

            # Send CloseComplete
            self.sock.sendall(CloseComplete.encode())

        except Exception as e:
            print(f"[{self.session_id}]      ✗ Close error: {e}")
            # In Extended Query Protocol, don't send ReadyForQuery - wait for Sync
            self.sock.sendall(ErrorResponse.encode('ERROR', f"Close error: {str(e)}"))

    def _handle_sync(self):
        """
        Handle Sync message - synchronization point.

        Sends ReadyForQuery with current transaction status.
        """
        styled_print(f"[{self.session_id}]   {S.RETRY} Sync (transaction_status={self.transaction_status})")

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

            # Step 3: Setup DuckDB session with LARS UDFs (now that session_id is set)
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
                    styled_print(f"[{self.session_id}] {S.WARN} Unknown message type: {msg_type} ({chr(msg_type) if 32 <= msg_type <= 126 else '?'})")
                    send_error(
                        self.sock,
                        f"Unsupported message type: {msg_type}",
                        detail="LARS PostgreSQL server implements Simple Query Protocol only."
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
                styled_print(f"[{self.session_id}]   {S.OK} Transaction rolled back")
            except Exception as e:
                error_msg = str(e).lower()
                # "no transaction is active" is NORMAL - not an error
                # Only force-close on actual connection problems
                if "no transaction" in error_msg:
                    # This is fine - no transaction was active
                    styled_print(f"[{self.session_id}]   {S.OK} No active transaction (clean state)")
                elif "connection" in error_msg and "closed" in error_msg:
                    # Connection is already dead - remove from cache
                    styled_print(f"[{self.session_id}]   {S.WARN} Connection already closed, removing from cache")
                    try:
                        from ..sql_tools.session_db import force_close_session
                        force_close_session(self.session_id)
                    except:
                        pass
                else:
                    # Unknown error - log but don't force-close (other clients may be using it)
                    styled_print(f"[{self.session_id}]   {S.WARN} Rollback warning: {e}")

        # 2. Close socket
        try:
            self.sock.close()
        except:
            pass

        # Note: We keep the DuckDB connection in cache for other clients
        # and quick reconnect. Only truly dead connections are removed above.


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

        sock.listen(5)  # Backlog of 5 pending connections
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
        styled_print(f"{S.PAUSE}  Press Ctrl+C to stop")
        print("=" * 70)

        try:
            while self.running:
                # Accept new connection (blocking)
                client_sock, addr = sock.accept()
                self.client_count += 1

                styled_print(f"\n{S.LINK} Client #{self.client_count} connected from {addr[0]}:{addr[1]}")

                # Handle client in separate thread (allows concurrent connections)
                client = ClientConnection(client_sock, addr, self.session_prefix)
                thread = threading.Thread(
                    target=client.handle,
                    daemon=True,
                    name=f"Client-{self.client_count}"
                )
                thread.start()

        except KeyboardInterrupt:
            styled_print(f"\n\n{S.STOP}  Shutting down server...")
            print(f"   Total connections served: {self.client_count}")

        except Exception as e:
            styled_print(f"\n{S.ERR} Server error: {e}")
            traceback.print_exc()

        finally:
            sock.close()
            self.running = False
            styled_print(f"{S.DONE} Server stopped")


def start_postgres_server(host='0.0.0.0', port=5432, session_prefix='pg_client'):
    """
    Start LARS PostgreSQL wire protocol server.

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
        default=> SELECT lars_udf('Extract brand', 'Apple iPhone') as brand;
         brand
        -------
         Apple
        (1 row)
    """
    server = LARSPostgresServer(host, port, session_prefix)
    server.start()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='LARS PostgreSQL Wire Protocol Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to listen on')
    parser.add_argument('--port', type=int, default=15432, help='Port to listen on')
    parser.add_argument('--session-prefix', default='pg_client', help='Session ID prefix')
    args = parser.parse_args()

    start_postgres_server(host=args.host, port=args.port, session_prefix=args.session_prefix)
