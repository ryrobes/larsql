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

from .config import SqlConnectionConfig, resolve_google_credentials
from ..console_style import S, styled_print


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

    def __init__(self, use_cache: bool = True):
        # Use persistent DuckDB file to cache materialized CSVs
        # This avoids re-importing on every tool call
        # For .duckdb files, use in-memory (no caching needed - they're already fast)
        import os
        from pathlib import Path

        self._attached = set()
        self._use_cache = use_cache

        if use_cache:
            # Get data directory from config (or default)
            data_dir = os.getenv('LARS_DATA_DIR', os.path.join(os.getcwd(), 'data'))
            os.makedirs(data_dir, exist_ok=True)

            duckdb_path = os.path.join(data_dir, 'sql_cache.duckdb')

            # Connect to persistent DuckDB file (creates if doesn't exist)
            self.conn = duckdb.connect(duckdb_path)
            print(f"[SQL] Using DuckDB cache: {duckdb_path}")
        else:
            # In-memory DuckDB (for .duckdb files - no caching needed)
            self.conn = duckdb.connect(':memory:')
            print(f"[SQL] Using in-memory DuckDB (no cache)")

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

        # Phase 1: Cloud databases
        elif config.type == "bigquery":
            self._attach_bigquery(config, alias)

        elif config.type == "snowflake":
            self._attach_snowflake(config, alias)

        elif config.type == "motherduck":
            self._attach_motherduck(config, alias)

        # Phase 2: Remote filesystems
        elif config.type == "s3":
            self._attach_s3(config, alias)

        elif config.type == "azure":
            self._attach_azure(config, alias)

        elif config.type == "gcs":
            self._attach_gcs(config, alias)

        elif config.type == "http":
            self._attach_http(config, alias)

        # Phase 3: Lakehouse formats
        elif config.type == "delta":
            self._attach_delta(config, alias)

        elif config.type == "iceberg":
            self._attach_iceberg(config, alias)

        # Phase 4: Scanner functions
        elif config.type == "odbc":
            self._attach_odbc(config, alias)

        elif config.type == "gsheets":
            self._attach_gsheets(config, alias)

        elif config.type == "excel":
            self._attach_excel(config, alias)

        # Phase 5: Hybrid/materialization types
        elif config.type == "mongodb":
            self._attach_mongodb(config, alias)

        elif config.type == "cassandra":
            self._attach_cassandra(config, alias)

        elif config.type == "clickhouse":
            self._attach_clickhouse(config, alias)

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

    # =========================================================================
    # Phase 1: Cloud Database Connectors
    # =========================================================================

    def _attach_bigquery(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Google BigQuery as a DuckDB database.

        Requires:
        - project_id: GCP project ID
        - credentials_env: Environment variable containing path to service account JSON
                          (or GOOGLE_APPLICATION_CREDENTIALS is used by default)

        Query syntax: SELECT * FROM {alias}.{dataset}.{table}
        """
        try:
            self.conn.execute("INSTALL bigquery FROM community;")
        except Exception:
            pass  # Already installed

        self.conn.execute("LOAD bigquery;")

        # Build connection string
        conn_str = f"project={config.project_id}"

        # Handle credentials - BigQuery extension uses GOOGLE_APPLICATION_CREDENTIALS
        # Use resolver to support both file paths and JSON strings
        if config.credentials_env:
            creds_path = resolve_google_credentials(config.credentials_env)
            if creds_path:
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
        else:
            # Try default GOOGLE_APPLICATION_CREDENTIALS
            creds_path = resolve_google_credentials()
            if creds_path:
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path

        # Attach with READ_ONLY by default
        read_only_clause = ", READ_ONLY" if config.read_only else ""
        self.conn.execute(f"ATTACH '{conn_str}' AS {alias} (TYPE bigquery{read_only_clause});")
        print(f"    [OK] Attached BigQuery project: {config.project_id} → {alias}")

    def _attach_snowflake(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Snowflake as a DuckDB database.

        Requires:
        - account: Snowflake account identifier (e.g., xy12345.us-east-1)
        - user: Username
        - password_env: Environment variable containing password
        - database: Database name (optional)
        - warehouse: Warehouse name (optional)
        - role: Role name (optional)

        Query syntax: SELECT * FROM {alias}.{schema}.{table}
        """
        try:
            self.conn.execute("INSTALL snowflake;")
        except Exception:
            pass

        self.conn.execute("LOAD snowflake;")

        # Build connection string
        conn_parts = [f"account={config.account}", f"user={config.user}"]

        if config.password:
            conn_parts.append(f"password={config.password}")

        if config.database:
            conn_parts.append(f"database={config.database}")

        if config.warehouse:
            conn_parts.append(f"warehouse={config.warehouse}")

        if config.role:
            conn_parts.append(f"role={config.role}")

        conn_str = ";".join(conn_parts)
        self.conn.execute(f"ATTACH '{conn_str}' AS {alias} (TYPE snowflake);")
        print(f"    [OK] Attached Snowflake: {config.account} → {alias}")

    def _attach_motherduck(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Motherduck cloud database.

        Requires:
        - database: Motherduck database name
        - motherduck_token_env: Environment variable containing Motherduck token

        Query syntax: SELECT * FROM {alias}.{table}
        """
        # Set token if provided
        if config.motherduck_token_env:
            token = os.getenv(config.motherduck_token_env)
            if token:
                self.conn.execute(f"SET motherduck_token='{token}';")

        # Attach Motherduck database (uses md: prefix)
        self.conn.execute(f"ATTACH 'md:{config.database}' AS {alias};")
        print(f"    [OK] Attached Motherduck: {config.database} → {alias}")

    # =========================================================================
    # Phase 2: Remote Filesystem Connectors
    # =========================================================================

    def _attach_s3(self, config: SqlConnectionConfig, alias: str):
        """
        Attach S3 bucket as a DuckDB schema with views for each file.

        Requires:
        - bucket: S3 bucket name
        - prefix: Optional path prefix within bucket
        - region: AWS region (default: us-east-1)
        - access_key_env: Environment variable for AWS_ACCESS_KEY_ID
        - secret_key_env: Environment variable for AWS_SECRET_ACCESS_KEY
        - file_pattern: Glob pattern for files (default: *.parquet)

        Query syntax: SELECT * FROM {alias}.{filename}
        """
        try:
            self.conn.execute("INSTALL httpfs;")
        except Exception:
            pass
        self.conn.execute("LOAD httpfs;")

        # Configure S3 credentials
        region = config.region or "us-east-1"
        self.conn.execute(f"SET s3_region='{region}';")

        if config.access_key_env:
            access_key = os.getenv(config.access_key_env, "")
            if access_key:
                self.conn.execute(f"SET s3_access_key_id='{access_key}';")

        if config.secret_key_env:
            secret_key = os.getenv(config.secret_key_env, "")
            if secret_key:
                self.conn.execute(f"SET s3_secret_access_key='{secret_key}';")

        # Support S3-compatible storage (MinIO, R2, etc.)
        if config.endpoint_url:
            # Strip http:// or https:// from endpoint for DuckDB
            endpoint = config.endpoint_url.replace('http://', '').replace('https://', '')
            self.conn.execute(f"SET s3_endpoint='{endpoint}';")
            self.conn.execute("SET s3_url_style='path';")
            # Disable SSL for local endpoints (MinIO)
            if 'localhost' in config.endpoint_url or '127.0.0.1' in config.endpoint_url:
                self.conn.execute("SET s3_use_ssl=false;")

        # Create schema for this connection
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        # Build S3 path
        prefix = config.prefix.rstrip('/') if config.prefix else ""
        s3_base = f"s3://{config.bucket}/{prefix}" if prefix else f"s3://{config.bucket}"

        # Determine file pattern and format
        pattern = config.file_pattern or "*.parquet"

        # List files and create views
        files = self._list_s3_files(s3_base, pattern)
        loaded_count = 0

        for file_path in files:
            table_name = sanitize_name(Path(file_path).name)
            try:
                # Determine read function based on file extension
                if file_path.endswith('.parquet'):
                    self.conn.execute(f"""
                        CREATE VIEW {alias}.{table_name} AS
                        SELECT * FROM read_parquet('{file_path}')
                    """)
                elif file_path.endswith('.csv'):
                    self.conn.execute(f"""
                        CREATE VIEW {alias}.{table_name} AS
                        SELECT * FROM read_csv_auto('{file_path}')
                    """)
                elif file_path.endswith('.json') or file_path.endswith('.jsonl'):
                    self.conn.execute(f"""
                        CREATE VIEW {alias}.{table_name} AS
                        SELECT * FROM read_json_auto('{file_path}')
                    """)
                else:
                    continue  # Skip unsupported formats

                loaded_count += 1
                print(f"    [OK] Registered S3 file: {Path(file_path).name} → {alias}.{table_name}")
            except Exception as e:
                print(f"    [WARN]  Skipped {file_path}: {str(e)[:80]}")

        print(f"  └─ Attached S3 bucket: s3://{config.bucket} → {alias} ({loaded_count} files)")

    def _list_s3_files(self, s3_base: str, pattern: str) -> List[str]:
        """
        List S3 files matching pattern.

        Uses DuckDB's glob function if available, otherwise returns the pattern path.
        """
        import fnmatch

        try:
            # Try to use DuckDB's glob for S3
            glob_path = f"{s3_base.rstrip('/')}/{pattern}"
            result = self.conn.execute(f"SELECT * FROM glob('{glob_path}')").fetchall()
            return [row[0] for row in result]
        except Exception:
            # Fallback: just return the glob path itself (DuckDB can expand it)
            return [f"{s3_base.rstrip('/')}/{pattern}"]

    def _attach_azure(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Azure Blob Storage as a DuckDB schema.

        Requires:
        - bucket: Azure container name
        - prefix: Optional path prefix within container
        - connection_string_env: Environment variable for Azure connection string

        Query syntax: SELECT * FROM {alias}.{filename}
        """
        try:
            self.conn.execute("INSTALL azure;")
        except Exception:
            pass
        self.conn.execute("LOAD azure;")

        # Configure Azure credentials
        if config.connection_string_env:
            conn_str = os.getenv(config.connection_string_env, "")
            if conn_str:
                self.conn.execute(f"SET azure_storage_connection_string='{conn_str}';")

        # Create schema
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        # Build Azure path
        prefix = config.prefix.rstrip('/') if config.prefix else ""
        azure_base = f"azure://{config.bucket}/{prefix}" if prefix else f"azure://{config.bucket}"

        pattern = config.file_pattern or "*.parquet"

        # List files and create views
        files = self._list_azure_files(azure_base, pattern)
        loaded_count = 0

        for file_path in files:
            table_name = sanitize_name(Path(file_path).name)
            try:
                if file_path.endswith('.parquet'):
                    self.conn.execute(f"""
                        CREATE VIEW {alias}.{table_name} AS
                        SELECT * FROM read_parquet('{file_path}')
                    """)
                elif file_path.endswith('.csv'):
                    self.conn.execute(f"""
                        CREATE VIEW {alias}.{table_name} AS
                        SELECT * FROM read_csv_auto('{file_path}')
                    """)
                else:
                    continue

                loaded_count += 1
                print(f"    [OK] Registered Azure file: {Path(file_path).name} → {alias}.{table_name}")
            except Exception as e:
                print(f"    [WARN]  Skipped {file_path}: {str(e)[:80]}")

        print(f"  └─ Attached Azure container: {config.bucket} → {alias} ({loaded_count} files)")

    def _list_azure_files(self, azure_base: str, pattern: str) -> List[str]:
        """List Azure files matching pattern."""
        try:
            glob_path = f"{azure_base.rstrip('/')}/{pattern}"
            result = self.conn.execute(f"SELECT * FROM glob('{glob_path}')").fetchall()
            return [row[0] for row in result]
        except Exception:
            return [f"{azure_base.rstrip('/')}/{pattern}"]

    def _attach_gcs(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Google Cloud Storage as a DuckDB schema.

        Requires:
        - bucket: GCS bucket name
        - prefix: Optional path prefix within bucket
        - credentials_env: Environment variable for GCP credentials path

        Query syntax: SELECT * FROM {alias}.{filename}
        """
        try:
            self.conn.execute("INSTALL httpfs;")
        except Exception:
            pass
        self.conn.execute("LOAD httpfs;")

        # Configure GCS credentials - use resolver for JSON string support
        if config.credentials_env:
            creds_path = resolve_google_credentials(config.credentials_env)
            if creds_path:
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
        else:
            # Try default GOOGLE_APPLICATION_CREDENTIALS
            creds_path = resolve_google_credentials()
            if creds_path:
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path

        # Create schema
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        # Build GCS path
        prefix = config.prefix.rstrip('/') if config.prefix else ""
        gcs_base = f"gcs://{config.bucket}/{prefix}" if prefix else f"gcs://{config.bucket}"

        pattern = config.file_pattern or "*.parquet"

        # List files and create views
        files = self._list_gcs_files(gcs_base, pattern)
        loaded_count = 0

        for file_path in files:
            table_name = sanitize_name(Path(file_path).name)
            try:
                if file_path.endswith('.parquet'):
                    self.conn.execute(f"""
                        CREATE VIEW {alias}.{table_name} AS
                        SELECT * FROM read_parquet('{file_path}')
                    """)
                elif file_path.endswith('.csv'):
                    self.conn.execute(f"""
                        CREATE VIEW {alias}.{table_name} AS
                        SELECT * FROM read_csv_auto('{file_path}')
                    """)
                else:
                    continue

                loaded_count += 1
                print(f"    [OK] Registered GCS file: {Path(file_path).name} → {alias}.{table_name}")
            except Exception as e:
                print(f"    [WARN]  Skipped {file_path}: {str(e)[:80]}")

        print(f"  └─ Attached GCS bucket: gs://{config.bucket} → {alias} ({loaded_count} files)")

    def _list_gcs_files(self, gcs_base: str, pattern: str) -> List[str]:
        """List GCS files matching pattern."""
        try:
            glob_path = f"{gcs_base.rstrip('/')}/{pattern}"
            result = self.conn.execute(f"SELECT * FROM glob('{glob_path}')").fetchall()
            return [row[0] for row in result]
        except Exception:
            return [f"{gcs_base.rstrip('/')}/{pattern}"]

    def _attach_http(self, config: SqlConnectionConfig, alias: str):
        """
        Attach HTTP-accessible files as a DuckDB schema.

        Requires:
        - folder_path: Base URL for HTTP files

        Query syntax: SELECT * FROM {alias}.{filename}
        """
        try:
            self.conn.execute("INSTALL httpfs;")
        except Exception:
            pass
        self.conn.execute("LOAD httpfs;")

        # Create schema
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        # HTTP files don't support glob, so we need explicit file paths
        # For now, treat folder_path as a single file or a base URL
        base_url = config.folder_path

        if not base_url:
            print(f"    [WARN]  HTTP connection {alias} missing folder_path")
            return

        # Create a view for the HTTP file
        table_name = sanitize_name(Path(base_url).name) or "data"

        try:
            if base_url.endswith('.parquet'):
                self.conn.execute(f"""
                    CREATE VIEW {alias}.{table_name} AS
                    SELECT * FROM read_parquet('{base_url}')
                """)
            elif base_url.endswith('.csv'):
                self.conn.execute(f"""
                    CREATE VIEW {alias}.{table_name} AS
                    SELECT * FROM read_csv_auto('{base_url}')
                """)
            elif base_url.endswith('.json') or base_url.endswith('.jsonl'):
                self.conn.execute(f"""
                    CREATE VIEW {alias}.{table_name} AS
                    SELECT * FROM read_json_auto('{base_url}')
                """)
            else:
                # Try parquet as default
                self.conn.execute(f"""
                    CREATE VIEW {alias}.{table_name} AS
                    SELECT * FROM read_parquet('{base_url}')
                """)

            print(f"    [OK] Attached HTTP file: {base_url} → {alias}.{table_name}")
        except Exception as e:
            print(f"    [WARN]  Failed to attach HTTP file {base_url}: {str(e)[:80]}")

    # =========================================================================
    # Phase 3: Lakehouse Format Connectors
    # =========================================================================

    def _attach_delta(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Delta Lake table as a DuckDB view.

        Requires:
        - table_path: Path to Delta table (s3://, azure://, or local path)
        - access_key_env/secret_key_env: For S3-based Delta tables

        Query syntax: SELECT * FROM {alias}.{table_name}
        """
        try:
            self.conn.execute("INSTALL delta;")
        except Exception:
            pass
        self.conn.execute("LOAD delta;")

        # Configure S3 if table is on S3
        if config.table_path and config.table_path.startswith('s3://'):
            try:
                self.conn.execute("INSTALL httpfs;")
            except Exception:
                pass
            self.conn.execute("LOAD httpfs;")

            region = config.region or "us-east-1"
            self.conn.execute(f"SET s3_region='{region}';")

            if config.access_key_env:
                access_key = os.getenv(config.access_key_env, "")
                if access_key:
                    self.conn.execute(f"SET s3_access_key_id='{access_key}';")

            if config.secret_key_env:
                secret_key = os.getenv(config.secret_key_env, "")
                if secret_key:
                    self.conn.execute(f"SET s3_secret_access_key='{secret_key}';")

        # Create schema
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        # Create view for Delta table
        table_name = sanitize_name(Path(config.table_path).name) or "delta_table"

        try:
            self.conn.execute(f"""
                CREATE VIEW {alias}.{table_name} AS
                SELECT * FROM delta_scan('{config.table_path}')
            """)
            print(f"    [OK] Attached Delta table: {config.table_path} → {alias}.{table_name}")
        except Exception as e:
            print(f"    [WARN]  Failed to attach Delta table: {str(e)[:80]}")

    def _attach_iceberg(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Iceberg table as a DuckDB view.

        Requires:
        - catalog_type: Type of catalog (rest, glue, hive)
        - catalog_uri: URI of the catalog (for REST catalog)
        - table_path: Path to Iceberg table (for file-based)

        Query syntax: SELECT * FROM {alias}.{table_name}
        """
        try:
            self.conn.execute("INSTALL iceberg;")
        except Exception:
            pass
        self.conn.execute("LOAD iceberg;")

        # Create schema
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        if config.catalog_type == "rest" and config.catalog_uri:
            # REST catalog - attach as Iceberg database
            try:
                self.conn.execute(f"ATTACH '{config.catalog_uri}' AS {alias} (TYPE iceberg);")
                print(f"    [OK] Attached Iceberg REST catalog: {config.catalog_uri} → {alias}")
            except Exception as e:
                print(f"    [WARN]  Failed to attach Iceberg catalog: {str(e)[:80]}")
        elif config.table_path:
            # File-based Iceberg table
            table_name = sanitize_name(Path(config.table_path).name) or "iceberg_table"
            try:
                self.conn.execute(f"""
                    CREATE VIEW {alias}.{table_name} AS
                    SELECT * FROM iceberg_scan('{config.table_path}')
                """)
                print(f"    [OK] Attached Iceberg table: {config.table_path} → {alias}.{table_name}")
            except Exception as e:
                print(f"    [WARN]  Failed to attach Iceberg table: {str(e)[:80]}")

    # =========================================================================
    # Phase 4: Scanner Function Connectors
    # =========================================================================

    def _attach_odbc(self, config: SqlConnectionConfig, alias: str):
        """
        Attach ODBC data source as DuckDB views.

        Requires:
        - odbc_dsn: ODBC DSN name, OR
        - odbc_connection_string_env: Environment variable containing connection string

        Query syntax: SELECT * FROM {alias}.{schema}_{table}
        """
        # Note: DuckDB ODBC support requires the odbc extension or native ODBC scanner
        # The approach depends on DuckDB version and available extensions

        # Build connection string
        if config.odbc_connection_string_env:
            conn_str = os.getenv(config.odbc_connection_string_env, "")
        elif config.odbc_dsn:
            conn_str = f"DSN={config.odbc_dsn}"
        else:
            print(f"    [WARN]  ODBC connection {alias} requires odbc_dsn or odbc_connection_string_env")
            return

        # Create schema
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        # For now, we create a placeholder - full ODBC table discovery would require
        # connecting to the ODBC source and querying its metadata
        styled_print(f"    {S.INFO}  ODBC connection configured: {alias}")
        print(f"       Use: SELECT * FROM odbc_scan('{conn_str}', 'table_name')")
        print(f"       Discovery requires manual table listing for ODBC sources")

    def _attach_gsheets(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Google Sheets as a DuckDB view.

        Requires:
        - spreadsheet_id: Google Sheets spreadsheet ID
        - sheet_name: Optional specific sheet name
        - credentials_env: Environment variable for GCP credentials

        Query syntax: SELECT * FROM {alias}.{sheet_name}
        """
        # Install gsheets extension (community extension)
        # Note: This may not be available in all DuckDB versions
        try:
            self.conn.execute("INSTALL gsheets FROM community;")
        except Exception as e:
            print(f"    [WARN]  gsheets extension not available: {str(e)[:60]}")
            print(f"       Alternative: Use Python to fetch and materialize the data")
            return

        try:
            self.conn.execute("LOAD gsheets;")
        except Exception as e:
            print(f"    [WARN]  Failed to load gsheets extension: {str(e)[:60]}")
            return

        # Create schema
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        # Configure credentials if provided
        if config.credentials_env:
            creds = os.getenv(config.credentials_env, "")
            if creds:
                try:
                    self.conn.execute(f"CREATE SECRET gsheet_secret (TYPE gsheet, token='{creds}');")
                except Exception:
                    pass  # Secret may already exist

        # Create view for the sheet
        sheet_ref = config.sheet_name or ""
        table_name = (config.sheet_name or "sheet").replace(" ", "_").replace("-", "_")

        try:
            if sheet_ref:
                self.conn.execute(f"""
                    CREATE VIEW {alias}.{table_name} AS
                    SELECT * FROM read_gsheet('{config.spreadsheet_id}', sheet='{sheet_ref}')
                """)
            else:
                self.conn.execute(f"""
                    CREATE VIEW {alias}.{table_name} AS
                    SELECT * FROM read_gsheet('{config.spreadsheet_id}')
                """)

            print(f"    [OK] Attached Google Sheet: {config.spreadsheet_id} → {alias}.{table_name}")
        except Exception as e:
            print(f"    [WARN]  Failed to attach Google Sheet: {str(e)[:80]}")

    def _attach_excel(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Excel file as DuckDB views.

        Requires:
        - file_path: Path to Excel file (.xlsx)
        - sheet_name: Optional specific sheet name

        Query syntax: SELECT * FROM {alias}.{sheet_name}
        """
        # Install Excel extension (may be named 'excel' or 'spatial' depending on version)
        try:
            self.conn.execute("INSTALL spatial;")  # Excel support often bundled with spatial
        except Exception:
            pass

        try:
            self.conn.execute("LOAD spatial;")
        except Exception:
            pass

        if not config.file_path:
            print(f"    [WARN]  Excel connection {alias} requires file_path")
            return

        file_path = Path(config.file_path)
        if not file_path.exists():
            print(f"    [WARN]  Excel file not found: {config.file_path}")
            return

        # Create schema
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

        # Discover sheets if not specified
        if config.sheet_name:
            sheets = [config.sheet_name]
        else:
            # Try to discover sheet names
            try:
                import openpyxl
                wb = openpyxl.load_workbook(config.file_path, read_only=True)
                sheets = wb.sheetnames
                wb.close()
            except ImportError:
                # Fall back to single sheet assumption
                sheets = ["Sheet1"]
            except Exception:
                sheets = ["Sheet1"]

        loaded_count = 0
        for sheet in sheets:
            table_name = sheet.replace(" ", "_").replace("-", "_")
            try:
                self.conn.execute(f"""
                    CREATE VIEW {alias}.{table_name} AS
                    SELECT * FROM st_read('{config.file_path}', layer='{sheet}')
                """)
                loaded_count += 1
                print(f"    [OK] Attached Excel sheet: {sheet} → {alias}.{table_name}")
            except Exception as e:
                # Try alternative read method
                try:
                    # Some DuckDB versions use read_xlsx
                    self.conn.execute(f"""
                        CREATE VIEW {alias}.{table_name} AS
                        SELECT * FROM read_xlsx('{config.file_path}', sheet='{sheet}')
                    """)
                    loaded_count += 1
                    print(f"    [OK] Attached Excel sheet: {sheet} → {alias}.{table_name}")
                except Exception as e2:
                    print(f"    [WARN]  Failed to attach sheet {sheet}: {str(e2)[:60]}")

        if loaded_count > 0:
            print(f"  └─ Attached Excel file: {config.file_path} ({loaded_count} sheets)")

    # =========================================================================
    # Phase 5: Hybrid/Materialization Connectors
    # =========================================================================

    def _attach_mongodb(self, config: SqlConnectionConfig, alias: str):
        """
        Attach MongoDB database by materializing collections into DuckDB.

        Requires:
        - mongodb_uri_env: Environment variable containing MongoDB URI
        - database: MongoDB database name

        Query syntax: SELECT * FROM {alias}.{collection_name}

        Note: This materializes data into DuckDB (not live connection).
        Nested documents are flattened with underscores.
        """
        try:
            from pymongo import MongoClient
            import pandas as pd
        except ImportError:
            print(f"    [WARN]  MongoDB connector requires: pip install pymongo pandas")
            return

        uri = os.getenv(config.mongodb_uri_env) if config.mongodb_uri_env else None
        if not uri:
            print(f"    [WARN]  MongoDB connection {alias} missing mongodb_uri_env or env var not set")
            return

        if not config.database:
            print(f"    [WARN]  MongoDB connection {alias} missing database name")
            return

        try:
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            db = client[config.database]

            # Create schema
            self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

            collection_count = 0
            total_rows = 0

            for collection_name in db.list_collection_names():
                # Sample documents
                limit = config.sample_row_limit or 1000
                docs = list(db[collection_name].find().limit(limit))

                if not docs:
                    continue

                # Convert to DataFrame (flattens nested docs)
                df = pd.json_normalize(docs)

                # Clean column names
                df.columns = [c.replace(".", "_").replace("$", "") for c in df.columns]

                # Convert ObjectId to string
                if "_id" in df.columns:
                    df["_id"] = df["_id"].astype(str)

                # Register in DuckDB
                table_name = collection_name.replace("-", "_").replace(" ", "_")
                temp_name = f'_mongo_{table_name}'

                self.conn.register(temp_name, df)
                self.conn.execute(f"""
                    CREATE OR REPLACE TABLE {alias}.{table_name} AS
                    SELECT * FROM {temp_name}
                """)
                self.conn.unregister(temp_name)

                collection_count += 1
                total_rows += len(df)
                print(f"    [OK] Materialized collection: {collection_name} → {alias}.{table_name} ({len(df)} rows)")

            client.close()
            print(f"  └─ Materialized MongoDB: {config.database} ({collection_count} collections, {total_rows:,} rows)")

        except Exception as e:
            print(f"    [WARN]  Failed to connect to MongoDB: {str(e)[:80]}")

    def _attach_cassandra(self, config: SqlConnectionConfig, alias: str):
        """
        Attach Cassandra keyspace by materializing tables into DuckDB.

        Requires:
        - cassandra_hosts: List of Cassandra host addresses
        - cassandra_keyspace: Keyspace name
        - user: Optional username
        - password_env: Optional password environment variable

        Query syntax: SELECT * FROM {alias}.{table_name}

        Note: This materializes data into DuckDB (not live connection).
        """
        try:
            from cassandra.cluster import Cluster
            from cassandra.auth import PlainTextAuthProvider
            import pandas as pd
        except ImportError:
            print(f"    [WARN]  Cassandra connector requires: pip install cassandra-driver pandas")
            return

        if not config.cassandra_hosts:
            print(f"    [WARN]  Cassandra connection {alias} missing cassandra_hosts")
            return

        if not config.cassandra_keyspace:
            print(f"    [WARN]  Cassandra connection {alias} missing cassandra_keyspace")
            return

        try:
            # Setup authentication if provided
            auth = None
            if config.user:
                password = os.getenv(config.password_env) if config.password_env else None
                auth = PlainTextAuthProvider(config.user, password or "")

            cluster = Cluster(config.cassandra_hosts, auth_provider=auth)
            session = cluster.connect(config.cassandra_keyspace)

            # Create schema
            self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

            # Get tables from system schema
            tables_query = f"""
                SELECT table_name FROM system_schema.tables
                WHERE keyspace_name = '{config.cassandra_keyspace}'
            """
            tables = session.execute(tables_query)

            table_count = 0
            total_rows = 0

            for row in tables:
                table_name = row.table_name
                limit = config.sample_row_limit or 1000

                try:
                    sample_query = f"SELECT * FROM {table_name} LIMIT {limit}"
                    rows = session.execute(sample_query)

                    df = pd.DataFrame(list(rows))
                    if df.empty:
                        continue

                    # Register in DuckDB
                    temp_name = f'_cass_{table_name}'
                    self.conn.register(temp_name, df)
                    self.conn.execute(f"""
                        CREATE OR REPLACE TABLE {alias}.{table_name} AS
                        SELECT * FROM {temp_name}
                    """)
                    self.conn.unregister(temp_name)

                    table_count += 1
                    total_rows += len(df)
                    print(f"    [OK] Materialized table: {table_name} → {alias}.{table_name} ({len(df)} rows)")

                except Exception as e:
                    print(f"    [WARN]  Failed to materialize {table_name}: {str(e)[:60]}")

            cluster.shutdown()
            print(f"  └─ Materialized Cassandra: {config.cassandra_keyspace} ({table_count} tables, {total_rows:,} rows)")

        except Exception as e:
            print(f"    [WARN]  Failed to connect to Cassandra: {str(e)[:80]}")

    def _attach_clickhouse(self, config: SqlConnectionConfig, alias: str):
        """
        Attach ClickHouse database by materializing tables into DuckDB.

        Requires:
        - host: ClickHouse server hostname
        - port: HTTP port (default 8123)
        - database: Database name (default 'default')
        - user: Username (default 'default')
        - password_env: Optional password environment variable

        Query syntax: SELECT * FROM {alias}.{table_name}

        Note: This materializes data into DuckDB (not live connection).
        """
        try:
            import clickhouse_connect
            import pandas as pd
        except ImportError:
            print(f"    [WARN]  ClickHouse connector requires: pip install clickhouse-connect pandas")
            return

        if not config.host:
            print(f"    [WARN]  ClickHouse connection {alias} missing host")
            return

        # Get connection parameters
        host = config.host
        port = config.port or 8123  # ClickHouse HTTP port (default)
        database = config.database or "default"
        user = config.user or "default"
        password = config.password or (os.getenv(config.password_env) if config.password_env else "")

        try:
            client = clickhouse_connect.get_client(
                host=host,
                port=port,
                database=database,
                username=user,
                password=password,
            )

            # Create schema
            self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias};")

            # Get list of tables in the database
            # Filter out internal ClickHouse tables (.inner* are MV backing tables)
            tables_result = client.query(f"SHOW TABLES FROM {database}")
            table_names = [
                row[0] for row in tables_result.result_rows
                if not row[0].startswith('.inner')
            ]

            table_count = 0
            total_rows = 0

            for table_name in table_names:
                limit = config.sample_row_limit or 1000

                try:
                    # Get sample data
                    df = client.query_df(f"SELECT * FROM {database}.{table_name} LIMIT {limit}")

                    if df.empty:
                        continue

                    # Sanitize table name for DuckDB
                    safe_table_name = table_name.replace("-", "_").replace(" ", "_")
                    temp_name = f'_ch_{safe_table_name}'

                    self.conn.register(temp_name, df)
                    self.conn.execute(f"""
                        CREATE OR REPLACE TABLE {alias}.{safe_table_name} AS
                        SELECT * FROM {temp_name}
                    """)
                    self.conn.unregister(temp_name)

                    table_count += 1
                    total_rows += len(df)
                    print(f"    [OK] Materialized table: {table_name} → {alias}.{safe_table_name} ({len(df)} rows)")

                except Exception as e:
                    print(f"    [WARN]  Failed to materialize {table_name}: {str(e)[:60]}")

            client.close()
            print(f"  └─ Materialized ClickHouse: {database} ({table_count} tables, {total_rows:,} rows)")

        except Exception as e:
            print(f"    [WARN]  Failed to connect to ClickHouse: {str(e)[:80]}")

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
                print(f"    [OK] Materialized {csv_file.name} → {schema_name} ({row_count:,} rows)")
            except Exception as e:
                failed_count += 1
                print(f"    [WARN]  Skipped {csv_file.name}: {str(e)[:100]}")

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
            # Use a dedicated temp directory for lars DuckDB snapshots
            # This keeps temp files organized and allows easy cleanup
            temp_dir = Path(tempfile.gettempdir()) / "lars_duckdb_snapshots"
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
                    print(f"    [SNAP] Attached {db_file.name} → {db_name} ({table_count} tables) [snapshot - file was locked]")
                else:
                    print(f"    [OK] Attached {db_file.name} → {db_name} ({table_count} tables)")

            except Exception as e:
                failed_count += 1
                print(f"    [WARN]  Failed to attach {db_file.name}: {str(e)[:100]}")

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
