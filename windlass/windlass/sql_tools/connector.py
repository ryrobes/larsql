"""
Database connector using DuckDB ATTACH for unified SQL interface.
"""

import os
import re
import shutil
import tempfile
import time
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

        elif config.type == "duckdb_folder":
            self._attach_duckdb_folder(config, alias)

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

    def _attach_duckdb_file(self, db_file: Path, db_name: str, max_retries: int = 2) -> bool:
        """
        Attach a single DuckDB file with fallback for locked files.

        Strategy:
        1. Try direct READ_ONLY attach (fastest, works when no exclusive lock)
        2. Retry with exponential backoff (handles transient locks from brief writes)
        3. Fall back to copy-on-read (guarantees success even with persistent locks)

        The copy-on-read approach copies the file to a temp location, which works
        even when the original has an exclusive lock. The data may be milliseconds
        stale, but this is acceptable for read-only operations like schema discovery.

        Args:
            db_file: Path to the .duckdb file
            db_name: Sanitized name to use as database alias
            max_retries: Number of direct attach attempts before falling back to copy

        Returns:
            True if used snapshot copy (file was locked), False if direct attach succeeded

        Raises:
            Exception if attachment failed completely (even with copy fallback)
        """
        last_error = None

        # Strategy 1 & 2: Try direct attach with retries for transient locks
        for attempt in range(max_retries):
            try:
                self.conn.execute(f"ATTACH '{db_file}' AS {db_name} (READ_ONLY)")
                return False  # Success - no snapshot needed
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Check if this is a lock-related error
                is_lock_error = any(phrase in error_str for phrase in [
                    "lock", "could not set lock", "database is locked",
                    "unable to open", "exclusive"
                ])

                if not is_lock_error:
                    # Non-lock error (e.g., corrupt file, permission denied) - don't retry
                    raise

                if attempt < max_retries - 1:
                    # Exponential backoff: 0.3s, 0.6s, 1.2s...
                    sleep_time = 0.3 * (2 ** attempt)
                    time.sleep(sleep_time)

        # Strategy 3: All retries failed due to lock - fall back to copy-on-read
        try:
            # Use a dedicated temp directory for windlass DuckDB snapshots
            # This keeps temp files organized and allows easy cleanup
            temp_dir = Path(tempfile.gettempdir()) / "windlass_duckdb_snapshots"
            temp_dir.mkdir(exist_ok=True)

            # Use consistent filename (overwrites previous snapshot of same db)
            # This prevents accumulation of stale temp files
            temp_path = temp_dir / f"{db_name}.duckdb"

            # Copy the file - this works even with exclusive locks on the original
            # because we're reading the file content, not acquiring a DuckDB lock
            shutil.copy2(db_file, temp_path)

            # Attach the snapshot copy
            self.conn.execute(f"ATTACH '{temp_path}' AS {db_name} (READ_ONLY)")

            return True  # Success via snapshot

        except Exception as copy_error:
            # Even copy failed - could be permission issue, disk space, or corrupt file
            raise Exception(
                f"Failed to attach {db_file.name}: "
                f"direct attach failed ({last_error}), "
                f"snapshot copy also failed ({copy_error})"
            )

    def _attach_duckdb_folder(self, config: SqlConnectionConfig, alias: str):
        """
        Attach all DuckDB files in folder as separate databases.

        Each .duckdb file becomes a separate attached database.
        Query syntax: SELECT * FROM db_name.table_name
        Where: db_name comes from filename (e.g., market_research.duckdb → market_research)

        DuckDB files have structure: db_name.main.table_name
        But we expose as: db_name.table_name for simplicity (main schema implied)

        Handles locked files gracefully:
        - Retries with backoff for transient locks (brief write operations)
        - Falls back to snapshot copy for persistent locks (active writer process)
        """
        if not config.folder_path:
            raise ValueError(f"DuckDB folder connection {alias} missing folder_path")

        folder = Path(config.folder_path)
        if not folder.exists():
            raise FileNotFoundError(f"DuckDB folder not found: {config.folder_path}")

        if not folder.is_dir():
            raise ValueError(f"DuckDB folder_path is not a directory: {config.folder_path}")

        # Find all DuckDB files
        duckdb_files = list(folder.glob("*.duckdb"))

        if not duckdb_files:
            print(f"Warning: No .duckdb files found in {config.folder_path}")
            return

        # Track attached databases for this folder
        if not hasattr(self, '_duckdb_folder_dbs'):
            self._duckdb_folder_dbs = {}
        self._duckdb_folder_dbs[alias] = []

        # Statistics for summary
        attached_count = 0
        failed_count = 0
        snapshot_count = 0
        total_tables = 0

        for db_file in duckdb_files:
            db_name = sanitize_name(db_file.name)  # market_research.duckdb → market_research

            try:
                # Check if already attached (from previous call or persistent cache)
                existing = self.conn.execute("""
                    SELECT database_name FROM duckdb_databases()
                    WHERE database_name = ?
                """, [db_name]).fetchone()

                if existing:
                    # Already attached - just count tables and track
                    tables = self.conn.execute(f"""
                        SELECT table_name FROM duckdb_tables()
                        WHERE database_name = '{db_name}'
                    """).fetchall()
                    table_count = len(tables)
                    total_tables += table_count
                    attached_count += 1
                    self._duckdb_folder_dbs[alias].append(db_name)
                    continue

                # Attach with lock-aware fallback
                used_snapshot = self._attach_duckdb_file(db_file, db_name)

                # Count tables
                tables = self.conn.execute(f"""
                    SELECT table_name FROM duckdb_tables()
                    WHERE database_name = '{db_name}'
                """).fetchall()
                table_count = len(tables)
                total_tables += table_count

                attached_count += 1
                self._duckdb_folder_dbs[alias].append(db_name)

                if used_snapshot:
                    snapshot_count += 1
                    print(f"    📸 Attached {db_file.name} → {db_name} ({table_count} tables) [snapshot - file was locked]")
                else:
                    print(f"    ✓ Attached {db_file.name} → {db_name} ({table_count} tables)")

            except Exception as e:
                failed_count += 1
                print(f"    ⚠️  Failed to attach {db_file.name}: {str(e)[:100]}")

        # Summary
        if attached_count > 0:
            print(f"  └─ Attached {attached_count} DuckDB file(s) ({total_tables} total tables)")
            if snapshot_count > 0:
                print(f"      ({snapshot_count} via snapshot copy due to locks)")
        if failed_count > 0:
            print(f"      ({failed_count} file(s) skipped due to errors)")

    def list_duckdb_schemas(self, alias: str) -> List[str]:
        """
        List all attached DuckDB databases for a duckdb_folder connection.

        Returns:
            List of database names (e.g., ['market_research', 'demo_research'])
        """
        if not hasattr(self, '_duckdb_folder_dbs') or alias not in self._duckdb_folder_dbs:
            return []
        return self._duckdb_folder_dbs[alias]

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
