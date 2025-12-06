"""
Database adapter layer for Windlass logging queries.

Supports both:
- chDB (embedded): Reads parquet files directly - perfect for development
- ClickHouse server: Production-ready OLAP database

The adapter provides a consistent interface regardless of backend,
making it trivial to upgrade from embedded chDB to a full ClickHouse server.
"""
from abc import ABC, abstractmethod
import pandas as pd
from typing import Optional, Any
import re


class DatabaseAdapter(ABC):
    """Abstract base class for database adapters."""

    @abstractmethod
    def query(self, sql: str, output_format: str = "dataframe") -> Any:
        """
        Execute a SELECT query and return results.

        Args:
            sql: SQL query string
            output_format: Output format - "dataframe", "dict", "arrow"

        Returns:
            Query results in requested format
        """
        pass

    @abstractmethod
    def execute(self, sql: str):
        """
        Execute a non-SELECT query (CREATE, INSERT, ALTER, etc.).

        Args:
            sql: SQL statement
        """
        pass


class ChDBAdapter(DatabaseAdapter):
    """
    Embedded chDB adapter - reads parquet files directly.

    This is perfect for development and single-machine deployments.
    No server process needed, just point at parquet files.
    """

    def __init__(self, data_dir: str, use_shared_session: bool = False):
        """
        Initialize chDB adapter.

        Args:
            data_dir: Directory containing parquet files
            use_shared_session: If True, use a persistent session (not safe for multi-worker).
                               If False, create new session per query (safe for gunicorn).
        """
        self.data_dir = data_dir
        self.use_shared_session = use_shared_session
        # Import here to avoid hard dependency if using ClickHouse server
        try:
            import chdb
            import chdb.session
            self.chdb = chdb
            if use_shared_session:
                # Create a session for consistent state across queries
                # WARNING: Not safe for multi-worker/multi-process deployments
                self.session = chdb.session.Session()
            else:
                self.session = None
        except ImportError:
            raise ImportError(
                "chdb is not installed. Install it with: pip install chdb"
            )

    def query(self, sql: str, output_format: str = "dataframe") -> Any:
        """
        Execute query and return results.

        Args:
            sql: SQL query (will be adapted from DuckDB patterns if needed)
            output_format: "dataframe" (default), "dict", "arrow"

        Returns:
            Query results in requested format
        """
        # Adapt SQL from DuckDB patterns to chDB
        sql = self._adapt_sql(sql)

        # Map output format to chDB format
        format_map = {
            "dataframe": "DataFrame",
            "dict": "JSON",
            "arrow": "Arrow"
        }
        chdb_format = format_map.get(output_format, "DataFrame")

        try:
            if self.session:
                # Use persistent session (faster but not multi-worker safe)
                result = self.session.query(sql, chdb_format)
            else:
                # Create new session per query (slower but multi-worker safe)
                import chdb.session
                session = chdb.session.Session()
                result = session.query(sql, chdb_format)
            return result
        except Exception as e:
            # Add more context to errors
            print(f"[ChDB Error] Query failed: {e}")
            print(f"[ChDB Error] SQL: {sql}")
            raise

    def execute(self, sql: str):
        """Execute non-SELECT query."""
        sql = self._adapt_sql(sql)
        self.session.query(sql)

    def _adapt_sql(self, sql: str) -> str:
        """
        Adapt SQL from DuckDB patterns to chDB/ClickHouse syntax.

        Converts common DuckDB patterns:
        - FROM 'path/*.parquet' → FROM file('path/*.parquet', Parquet)
        - FROM read_parquet('path') → FROM file('path', Parquet)
        - DuckDB time functions → ClickHouse equivalents

        Args:
            sql: Original SQL (potentially with DuckDB syntax)

        Returns:
            Adapted SQL for chDB/ClickHouse
        """
        # Pattern 1: FROM 'path/*.parquet' or FROM "path/*.parquet"
        # Replace with: FROM file('path/*.parquet', Parquet)
        pattern1 = r"FROM\s+['\"]([^'\"]+\.parquet)['\"]"

        def replacer1(match):
            path = match.group(1)
            return f"FROM file('{path}', Parquet)"

        sql = re.sub(pattern1, replacer1, sql, flags=re.IGNORECASE)

        # Pattern 2: FROM read_parquet('path/**/*.parquet')
        # Replace with: FROM file('path/**/*.parquet', Parquet)
        pattern2 = r"FROM\s+read_parquet\s*\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*[^)]+)?\s*\)"

        def replacer2(match):
            path = match.group(1)
            return f"FROM file('{path}', Parquet)"

        sql = re.sub(pattern2, replacer2, sql, flags=re.IGNORECASE)

        # DuckDB time functions → ClickHouse equivalents
        time_conversions = {
            # DATE_TRUNC patterns
            r"DATE_TRUNC\s*\(\s*'day'\s*,\s*CAST\s*\(\s*(\w+)\s+AS\s+TIMESTAMP\s*\)\s*\)":
                r"toStartOfDay(toDateTime(\1))",
            r"DATE_TRUNC\s*\(\s*'week'\s*,\s*CAST\s*\(\s*(\w+)\s+AS\s+TIMESTAMP\s*\)\s*\)":
                r"toStartOfWeek(toDateTime(\1))",
            r"DATE_TRUNC\s*\(\s*'month'\s*,\s*CAST\s*\(\s*(\w+)\s+AS\s+TIMESTAMP\s*\)\s*\)":
                r"toStartOfMonth(toDateTime(\1))",
            r"DATE_TRUNC\s*\(\s*'hour'\s*,\s*CAST\s*\(\s*(\w+)\s+AS\s+TIMESTAMP\s*\)\s*\)":
                r"toStartOfHour(toDateTime(\1))",

            # strftime patterns
            r"strftime\s*\(\s*'%Y-%m-%d %H:00'\s*,\s*(\w+)\s*\)":
                r"formatDateTime(toDateTime(\1), '%Y-%m-%d %H:00')",
            r"strftime\s*\(\s*'%Y-%m-%d'\s*,\s*(\w+)\s*\)":
                r"formatDateTime(toDateTime(\1), '%Y-%m-%d')",
        }

        for pattern, replacement in time_conversions.items():
            sql = re.sub(pattern, replacement, sql, flags=re.IGNORECASE)

        return sql


class ClickHouseServerAdapter(DatabaseAdapter):
    """
    ClickHouse server adapter for production deployments.

    Use this when you've outgrown embedded chDB and need:
    - Multi-user access
    - Horizontal scaling
    - Replication and high availability
    - Advanced monitoring
    """

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
        Initialize ClickHouse server connection.

        Args:
            host: Server hostname
            port: Native protocol port (9000)
            database: Database name
            user: Username
            password: Password
            auto_create: Automatically create database if it doesn't exist (default: True)
        """
        self.database = database

        try:
            from clickhouse_driver import Client

            # First connect without database to check/create it
            if auto_create:
                system_client = Client(
                    host=host,
                    port=port,
                    user=user,
                    password=password
                )

                try:
                    # Check if database exists
                    result = system_client.execute(
                        f"SELECT 1 FROM system.databases WHERE name = '{database}'"
                    )

                    if not result:
                        # Database doesn't exist - create it
                        print(f"[Windlass] Creating database '{database}'...")
                        system_client.execute(f"CREATE DATABASE {database}")
                        print(f"[Windlass] ✓ Database '{database}' created")
                except Exception as e:
                    print(f"[Windlass] Warning: Could not check/create database: {e}")

            # Now connect to the database
            self.client = Client(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password
            )
        except ImportError:
            raise ImportError(
                "clickhouse-driver is not installed. "
                "Install it with: pip install clickhouse-driver"
            )

    def query(self, sql: str, output_format: str = "dataframe") -> Any:
        """
        Execute query on ClickHouse server.

        Args:
            sql: SQL query
            output_format: "dataframe", "dict", "arrow"

        Returns:
            Query results in requested format
        """
        if output_format == "dataframe":
            return self.client.query_dataframe(sql)
        elif output_format == "dict":
            result = self.client.execute(sql, with_column_types=True)
            # Convert to list of dicts
            rows, columns = result
            column_names = [col[0] for col in columns]
            return [dict(zip(column_names, row)) for row in rows]
        elif output_format == "arrow":
            # ClickHouse can export to Arrow format
            return self.client.query_arrow(sql)
        else:
            raise ValueError(f"Unknown output format: {output_format}")

    def execute(self, sql: str):
        """Execute non-SELECT query."""
        self.client.execute(sql)

    def ensure_table_exists(self, table_name: str, ddl: str):
        """
        Ensure a table exists, creating it if necessary.

        Args:
            table_name: Name of the table to check
            ddl: CREATE TABLE statement (should include IF NOT EXISTS)
        """
        try:
            # Try a simple query to check if table exists
            self.client.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
        except Exception:
            # Table doesn't exist - create it
            print(f"[Windlass] Creating table '{table_name}'...")
            self.execute(ddl)
            print(f"[Windlass] ✓ Table '{table_name}' created")


# Global adapter singleton (to reuse shared sessions)
_adapter_singleton = None

def get_db_adapter() -> DatabaseAdapter:
    """
    Get the appropriate database adapter based on configuration.

    This is the main entry point for all database operations.
    It checks the config and returns (in order of preference):
    1. ClickHouseServerAdapter (if configured)
    2. ChDBAdapter (embedded chDB, if available)
    3. DuckDBAdapter (fallback, widely available)

    Returns a singleton instance to reuse shared sessions and avoid chdb warnings.

    Returns:
        DatabaseAdapter instance
    """
    global _adapter_singleton

    # Return cached adapter if available
    if _adapter_singleton is not None:
        return _adapter_singleton

    from .config import get_config

    config = get_config()

    # Check if ClickHouse server is configured
    if hasattr(config, 'use_clickhouse_server') and config.use_clickhouse_server:
        _adapter_singleton = ClickHouseServerAdapter(
            host=config.clickhouse_host,
            port=config.clickhouse_port,
            database=config.clickhouse_database,
            user=getattr(config, 'clickhouse_user', 'default'),
            password=getattr(config, 'clickhouse_password', '')
        )
        return _adapter_singleton

    # Use chDB (embedded ClickHouse)
    # Check if we should use stateless mode (for multi-worker deployments like gunicorn)
    import os
    use_shared_session = os.getenv('WINDLASS_CHDB_SHARED_SESSION', 'false').lower() == 'true'
    _adapter_singleton = ChDBAdapter(config.data_dir, use_shared_session=use_shared_session)
    return _adapter_singleton
