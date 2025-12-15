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
        # Use persistent DuckDB file to cache materialized CSVs
        # This avoids re-importing on every tool call
        import os
        from pathlib import Path

        # Get data directory from config (or default)
        data_dir = os.getenv('WINDLASS_DATA_DIR', os.path.join(os.getcwd(), 'data'))
        os.makedirs(data_dir, exist_ok=True)

        duckdb_path = os.path.join(data_dir, 'sql_cache.duckdb')

        # Connect to persistent DuckDB file (creates if doesn't exist)
        self.conn = duckdb.connect(duckdb_path)
        self._attached = set()

        print(f"[SQL] Using DuckDB cache: {duckdb_path}")

    def attach(self, config: SqlConnectionConfig) -> str:
        """
        Attach database to DuckDB and return alias.

        For csv_folder type, this also discovers all CSV files and materializes them.
        Uses persistent DuckDB file, so materialization happens only once.

        Returns:
            The alias name to use in queries
        """
        alias = config.connection_name

        # Check if already attached (in-memory check)
        if alias in self._attached:
            return alias

        # For CSV folders, also check if schema exists in DuckDB file (persistence check)
        if config.type == "csv_folder":
            schema_exists = self.conn.execute(f"""
                SELECT COUNT(*) FROM information_schema.schemata
                WHERE schema_name = '{alias}'
            """).fetchone()[0] > 0

            if schema_exists:
                # Schema exists in persistent file, just mark as attached
                self._attached.add(alias)
                print(f"[SQL] Using cached schema: {alias} (already materialized)")
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

        # MATERIALIZE each CSV as a TABLE (not view!)
        # This imports data once, queries are fast (no re-reading CSV)
        # Schema name = sanitized filename
        loaded_count = 0
        failed_count = 0
        total_rows = 0
        newly_imported_count = 0

        for csv_file in csv_files:
            schema_name = sanitize_name(csv_file.name)
            table_name = f"{alias}.{schema_name}"

            try:
                # Check if table already exists (skip re-materialization)
                table_exists = self.conn.execute(f"""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = '{alias}' AND table_name = '{schema_name}'
                """).fetchone()[0] > 0

                if table_exists:
                    # Already materialized, skip
                    row_count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                    total_rows += row_count
                    loaded_count += 1
                    # Silent - already loaded
                    continue

                # Import CSV into DuckDB table (CTAS - Create Table As Select)
                # This reads CSV once and stores persistently
                self.conn.execute(f"""
                    CREATE TABLE {table_name} AS
                    SELECT * FROM read_csv_auto('{csv_file}', AUTO_DETECT=TRUE, ignore_errors=true)
                """)

                # Count rows for feedback
                row_count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                total_rows += row_count

                loaded_count += 1
                newly_imported_count += 1
                print(f"    ✓ Materialized {csv_file.name} → {schema_name} ({row_count:,} rows)")
            except Exception as e:
                failed_count += 1
                print(f"    ⚠️  Skipped {csv_file.name}: {str(e)[:100]}")

        if loaded_count > 0:
            if newly_imported_count > 0:
                print(f"  └─ Imported {newly_imported_count} NEW CSV file(s) (first time)")
            cached_count = loaded_count - newly_imported_count
            if cached_count > 0:
                print(f"  └─ Using {cached_count} cached CSV table(s) (instant)")
            print(f"  └─ Total: {loaded_count} CSV tables ({total_rows:,} rows) ready for queries")
        if failed_count > 0:
            print(f"      ({failed_count} file(s) skipped due to errors)")

    def list_csv_schemas(self, alias: str) -> List[str]:
        """
        List all CSV schemas (materialized tables) for a csv_folder connection.

        Returns:
            List of schema names (e.g., ['bigfoot_sightings', 'sales_2024'])
        """
        # Query information schema for tables in the alias schema
        # Changed from table_type='VIEW' to 'BASE TABLE' (materialized)
        result = self.conn.execute(f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = '{alias}'
              AND table_type = 'BASE TABLE'
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
