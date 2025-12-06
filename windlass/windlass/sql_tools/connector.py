"""
Database connector using DuckDB ATTACH for unified SQL interface.
"""

import os
import re
from pathlib import Path
from typing import Optional, List, Tuple

try:
    import duckdb
except ImportError:
    raise ImportError("duckdb is required for SQL tools. Install with: pip install duckdb")

from .config import SqlConnectionConfig


def sanitize_name(name: str) -> str:
    """
    Sanitize a filename or string for use as SQL identifier.

    Examples:
        bigfoot_sightings.csv -> bigfoot_sightings
        Sales-2024.csv -> sales_2024
        My Data!.csv -> my_data
    """
    # Remove extension
    name = Path(name).stem

    # Replace special chars with underscore
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)

    # Remove leading/trailing underscores
    name = name.strip('_')

    # Lowercase for consistency
    name = name.lower()

    # Ensure doesn't start with number
    if name and name[0].isdigit():
        name = f"csv_{name}"

    return name or "unnamed"


class DatabaseConnector:
    """Handle DuckDB ATTACH for various database types."""

    def __init__(self):
        self.conn = duckdb.connect(":memory:")  # In-memory DuckDB
        self._attached = set()

    def attach(self, config: SqlConnectionConfig) -> str:
        """
        Attach database to DuckDB and return alias.

        For csv_folder type, this also discovers all CSV files and creates views.

        Returns:
            The alias name to use in queries
        """
        alias = config.connection_name

        if alias in self._attached:
            return alias

        if config.type == "postgres":
            self._attach_postgres(config, alias)

        elif config.type == "mysql":
            self._attach_mysql(config, alias)

        elif config.type == "sqlite":
            self._attach_sqlite(config, alias)

        elif config.type == "csv_folder":
            self._attach_csv_folder(config, alias)

        else:
            raise ValueError(f"Unsupported database type: {config.type}")

        self._attached.add(alias)
        return alias

    def _attach_postgres(self, config: SqlConnectionConfig, alias: str):
        """Attach PostgreSQL database."""
        # Install extension if needed
        try:
            self.conn.execute("INSTALL postgres;")
        except Exception:
            pass  # Already installed

        self.conn.execute("LOAD postgres;")

        # Build connection string
        conn_str = f"dbname={config.database} host={config.host} port={config.port} user={config.user}"
        if config.password:
            conn_str += f" password={config.password}"

        self.conn.execute(f"ATTACH '{conn_str}' AS {alias} (TYPE postgres);")

    def _attach_mysql(self, config: SqlConnectionConfig, alias: str):
        """Attach MySQL database."""
        try:
            self.conn.execute("INSTALL mysql;")
        except Exception:
            pass

        self.conn.execute("LOAD mysql;")

        conn_str = f"host={config.host} port={config.port} database={config.database} user={config.user}"
        if config.password:
            conn_str += f" password={config.password}"

        self.conn.execute(f"ATTACH '{conn_str}' AS {alias} (TYPE mysql);")

    def _attach_sqlite(self, config: SqlConnectionConfig, alias: str):
        """Attach SQLite database."""
        # SQLite just needs file path
        self.conn.execute(f"ATTACH '{config.database}' AS {alias} (TYPE sqlite);")

    def _attach_csv_folder(self, config: SqlConnectionConfig, alias: str):
        """
        Attach CSV folder as a database.

        Each CSV file becomes a "schema" (actually a view in DuckDB).
        Query syntax: SELECT * FROM csv_files.bigfoot_sightings
        """
        if not config.folder_path:
            raise ValueError(f"CSV folder connection {alias} missing folder_path")

        folder = Path(config.folder_path)
        if not folder.exists():
            raise FileNotFoundError(f"CSV folder not found: {config.folder_path}")

        if not folder.is_dir():
            raise ValueError(f"CSV folder_path is not a directory: {config.folder_path}")

        # Find all CSV files
        csv_files = list(folder.glob("*.csv"))

        if not csv_files:
            print(f"Warning: No CSV files found in {config.folder_path}")
            return

        # Create schema first
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        # Create a view for each CSV file
        # Schema name = sanitized filename
        loaded_count = 0
        failed_count = 0
        for csv_file in csv_files:
            schema_name = sanitize_name(csv_file.name)
            view_name = f"{alias}.{schema_name}"

            try:
                # Use DuckDB's read_csv_auto for automatic type detection
                # Add ignore_errors to handle malformed CSV files gracefully
                self.conn.execute(f"""
                    CREATE VIEW {view_name} AS
                    SELECT * FROM read_csv_auto('{csv_file}', AUTO_DETECT=TRUE, ignore_errors=true)
                """)
                loaded_count += 1
            except Exception as e:
                failed_count += 1
                print(f"    ⚠️  Skipped {csv_file.name}: {str(e)[:100]}")

        if loaded_count > 0:
            print(f"  └─ Loaded {loaded_count} CSV file(s) from {config.folder_path}")
        if failed_count > 0:
            print(f"      ({failed_count} file(s) skipped due to errors)")

    def list_csv_schemas(self, alias: str) -> List[str]:
        """
        List all CSV schemas (views) for a csv_folder connection.

        Returns:
            List of schema names (e.g., ['bigfoot_sightings', 'sales_2024'])
        """
        # Query information schema for tables in the alias schema
        result = self.conn.execute(f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = '{alias}'
              AND table_type = 'VIEW'
            ORDER BY table_name
        """).fetchall()

        schemas = [row[0] for row in result]
        return schemas

    def execute(self, sql: str):
        """Execute SQL query and return result object."""
        return self.conn.execute(sql)

    def fetch_df(self, sql: str):
        """Execute SQL and return pandas DataFrame."""
        return self.conn.execute(sql).df()

    def fetch_all(self, sql: str):
        """Execute SQL and return all rows."""
        return self.conn.execute(sql).fetchall()

    def fetch_one(self, sql: str):
        """Execute SQL and return first row."""
        return self.conn.execute(sql).fetchone()

    def close(self):
        """Close connection."""
        self.conn.close()
