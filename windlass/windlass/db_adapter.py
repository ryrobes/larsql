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
"""
import json
import threading
from typing import Any, Dict, List, Optional, Union
import pandas as pd


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
        with ClickHouseAdapter._query_lock:
            try:
                if output_format == "dataframe":
                    return self.client.query_dataframe(sql, params or {})
                elif output_format == "dict":
                    # Disable numpy for dict output to get native Python types
                    result = self.client.execute(sql, params or {}, with_column_types=True, settings={'use_numpy': False})
                    rows, columns = result
                    col_names = [c[0] for c in columns]
                    return [dict(zip(col_names, row)) for row in rows]
                else:  # raw
                    return self.client.execute(sql, params or {})
            except Exception as e:
                print(f"[ClickHouse Error] Query failed: {e}")
                print(f"[ClickHouse Error] SQL: {sql[:500]}...")
                raise

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
        with ClickHouseAdapter._query_lock:
            try:
                self.client.execute(sql, params or {})
            except Exception as e:
                print(f"[ClickHouse Error] Execute failed: {e}")
                print(f"[ClickHouse Error] SQL: {sql[:500]}...")
                raise

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
                print(f"[ClickHouse Error] Insert failed: {e}")
                print(f"[ClickHouse Error] Table: {table}, Columns: {columns}")
                raise

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
                print(f"[ClickHouse Error] Insert DataFrame failed: {e}")
                print(f"[ClickHouse Error] Table: {table}")
                raise

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
                print(f"[ClickHouse Error] Update failed: {e}")
                print(f"[ClickHouse Error] SQL: {sql[:500]}...")
                raise

    def batch_update_costs(self, table: str, updates: List[Dict]):
        """
        Batch update cost data for multiple rows by trace_id.

        This is more efficient than individual updates - ClickHouse processes
        as a single mutation operation.

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
                self.update_row(
                    table,
                    update_data,
                    f"trace_id = '{trace_id}'",
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
                print(f"[ClickHouse Error] Mark losers failed: {e}")
                raise

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
