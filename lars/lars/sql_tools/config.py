"""
SQL connection configuration and metadata management.
"""

import atexit
import json
import os
import tempfile
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field


# ============================================================================
# Google Credentials Resolver
# ============================================================================
# Cache for resolved credentials (avoids creating multiple temp files)
_google_creds_cache: Dict[str, str] = {}


def resolve_google_credentials(env_var: str = "GOOGLE_APPLICATION_CREDENTIALS") -> Optional[str]:
    """
    Resolve Google credentials from environment variable.

    Supports two formats:
    1. File path: Traditional path to a JSON credentials file
    2. JSON string: Raw JSON content (common in containerized deployments)

    If JSON content is detected (starts with '{'), it will be written to a
    temporary file and that path will be returned. The temp file persists
    for the lifetime of the process and is cleaned up on exit.

    Args:
        env_var: Name of the environment variable containing credentials
                 (default: GOOGLE_APPLICATION_CREDENTIALS)

    Returns:
        Path to credentials file, or None if not set/invalid
    """
    global _google_creds_cache

    # Return cached result if already resolved
    if env_var in _google_creds_cache:
        return _google_creds_cache[env_var]

    creds_value = os.getenv(env_var, "").strip()
    if not creds_value:
        return None

    # Check if it looks like JSON content (starts with '{')
    if creds_value.startswith("{"):
        # Validate it's actually valid JSON
        try:
            json.loads(creds_value)
        except json.JSONDecodeError as e:
            print(f"[sql_tools] Warning: {env_var} looks like JSON but failed to parse: {e}")
            # Fall back to treating it as a path
            _google_creds_cache[env_var] = creds_value
            return creds_value

        # Write JSON to a temporary file
        try:
            # Create temp file that persists (delete=False)
            fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="gcp_creds_")
            with os.fdopen(fd, 'w') as f:
                f.write(creds_value)

            _google_creds_cache[env_var] = temp_path

            # Register cleanup handler
            def _cleanup():
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
            atexit.register(_cleanup)

            print(f"[sql_tools] Resolved {env_var} from JSON string to temp file")
            return temp_path

        except Exception as e:
            print(f"[sql_tools] Warning: Failed to write credentials to temp file: {e}")
            return None
    else:
        # Treat as file path
        if not os.path.exists(creds_value):
            print(f"[sql_tools] Warning: {env_var} file not found: {creds_value}")
        _google_creds_cache[env_var] = creds_value
        return creds_value


class SqlConnectionConfig(BaseModel):
    """Configuration for a SQL database connection.

    Supports multiple connection shapes:
    - Native ATTACH: postgres, mysql, sqlite, bigquery, snowflake, motherduck
    - Remote Filesystems: s3, azure, gcs, http
    - Lakehouse: delta, iceberg
    - Scanners: odbc, adbc, gsheets, excel
    - Hybrid/Materialization: mongodb, cassandra, clickhouse
    - File-based: csv_folder, duckdb_folder
    """
    connection_name: str
    type: Literal[
        # Existing types
        "postgres", "mysql", "sqlite", "duckdb", "csv_folder", "duckdb_folder", "clickhouse",
        # Phase 1: Native ATTACH cloud databases
        "bigquery", "snowflake", "motherduck",
        # Phase 2: Remote filesystems
        "s3", "azure", "gcs", "http",
        # Phase 3: Lakehouse formats
        "delta", "iceberg",
        # Phase 4: Scanner functions
        "odbc", "adbc", "gsheets", "excel",
        # Phase 5: Hybrid/materialization
        "mongodb", "cassandra"
    ]
    enabled: bool = True

    # === Existing Fields (postgres, mysql, sqlite, clickhouse) ===
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    user: Optional[str] = None
    password_env: Optional[str] = None  # Env var name for password

    # Folder-based connections (csv_folder, duckdb_folder)
    folder_path: Optional[str] = None

    # === Phase 1: Cloud Database Fields ===
    # BigQuery
    project_id: Optional[str] = None           # GCP project ID
    credentials_env: Optional[str] = None      # Env var for GCP service account JSON

    # Snowflake
    account: Optional[str] = None              # Snowflake account identifier
    warehouse: Optional[str] = None            # Snowflake warehouse
    role: Optional[str] = None                 # Snowflake role

    # Motherduck
    motherduck_token_env: Optional[str] = None # Env var for Motherduck token

    # === Phase 2: Remote Filesystem Fields ===
    bucket: Optional[str] = None               # S3/Azure/GCS bucket/container
    prefix: Optional[str] = None               # Path prefix within bucket
    region: Optional[str] = None               # AWS region (default: us-east-1)
    access_key_env: Optional[str] = None       # Env var for AWS access key
    secret_key_env: Optional[str] = None       # Env var for AWS secret key
    connection_string_env: Optional[str] = None # Env var for Azure connection string
    file_pattern: Optional[str] = None         # Glob pattern (e.g., "*.parquet", "**/*.csv")
    endpoint_url: Optional[str] = None         # S3-compatible endpoint (MinIO, R2)

    # === Phase 3: Lakehouse Fields ===
    table_path: Optional[str] = None           # Delta/Iceberg table location
    catalog_type: Optional[str] = None         # Iceberg catalog type (rest, glue, hive)
    catalog_uri: Optional[str] = None          # Iceberg catalog URI

    # === Phase 4: Scanner Fields ===
    # ODBC
    odbc_dsn: Optional[str] = None             # ODBC Data Source Name
    odbc_connection_string_env: Optional[str] = None  # Env var for ODBC connection string

    # ADBC
    adbc_driver: Optional[str] = None          # ADBC driver path

    # Google Sheets
    spreadsheet_id: Optional[str] = None       # Google Sheets ID (from URL)
    sheet_name: Optional[str] = None           # Specific sheet name (optional)

    # Excel
    file_path: Optional[str] = None            # Path to Excel file

    # === Phase 5: Hybrid/Materialization Fields ===
    # MongoDB
    mongodb_uri_env: Optional[str] = None      # Env var for MongoDB connection URI

    # Cassandra
    cassandra_hosts: Optional[List[str]] = None  # List of Cassandra host addresses
    cassandra_keyspace: Optional[str] = None     # Cassandra keyspace name

    # === Discovery Settings ===
    sample_row_limit: int = 50
    distinct_value_threshold: int = 100        # Show distribution if < this many distinct values
    read_only: bool = True                     # Default to read-only connections

    # === Internal Fields ===
    duckdb_extension: Optional[str] = None     # DuckDB extension to auto-install
    password: Optional[str] = Field(default=None, exclude=True)  # Resolved at runtime


def validate_connection_config(config: SqlConnectionConfig) -> List[str]:
    """Validate required fields for each connection type.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Native ATTACH types
    if config.type == "postgres":
        if not config.host:
            errors.append("postgres requires host")
        if not config.database:
            errors.append("postgres requires database")

    elif config.type == "mysql":
        if not config.host:
            errors.append("mysql requires host")
        if not config.database:
            errors.append("mysql requires database")

    elif config.type == "sqlite":
        if not config.database:
            errors.append("sqlite requires database (file path)")

    elif config.type == "duckdb":
        if not config.database:
            errors.append("duckdb requires database (file path)")

    elif config.type == "bigquery":
        if not config.project_id:
            errors.append("bigquery requires project_id")

    elif config.type == "snowflake":
        if not config.account:
            errors.append("snowflake requires account")
        if not config.user:
            errors.append("snowflake requires user")

    elif config.type == "motherduck":
        if not config.database:
            errors.append("motherduck requires database")

    # Remote filesystem types
    elif config.type == "s3":
        if not config.bucket:
            errors.append("s3 requires bucket")

    elif config.type == "azure":
        if not config.bucket:
            errors.append("azure requires bucket (container name)")

    elif config.type == "gcs":
        if not config.bucket:
            errors.append("gcs requires bucket")

    elif config.type == "http":
        if not config.folder_path:
            errors.append("http requires folder_path (base URL)")

    # Lakehouse types
    elif config.type == "delta":
        if not config.table_path:
            errors.append("delta requires table_path")

    elif config.type == "iceberg":
        if not config.table_path and not config.catalog_uri:
            errors.append("iceberg requires table_path or catalog_uri")

    # Scanner types
    elif config.type == "odbc":
        if not config.odbc_dsn and not config.odbc_connection_string_env:
            errors.append("odbc requires odbc_dsn or odbc_connection_string_env")

    elif config.type == "adbc":
        if not config.adbc_driver:
            errors.append("adbc requires adbc_driver")

    elif config.type == "gsheets":
        if not config.spreadsheet_id:
            errors.append("gsheets requires spreadsheet_id")

    elif config.type == "excel":
        if not config.file_path:
            errors.append("excel requires file_path")

    # Hybrid types
    elif config.type == "mongodb":
        if not config.mongodb_uri_env:
            errors.append("mongodb requires mongodb_uri_env")
        if not config.database:
            errors.append("mongodb requires database")

    elif config.type == "cassandra":
        if not config.cassandra_hosts:
            errors.append("cassandra requires cassandra_hosts")
        if not config.cassandra_keyspace:
            errors.append("cassandra requires cassandra_keyspace")

    # Folder types
    elif config.type == "csv_folder":
        if not config.folder_path:
            errors.append("csv_folder requires folder_path")

    elif config.type == "duckdb_folder":
        if not config.folder_path:
            errors.append("duckdb_folder requires folder_path")

    elif config.type == "clickhouse":
        if not config.host:
            errors.append("clickhouse requires host")

    return errors


class DiscoveryMetadata(BaseModel):
    """Global metadata for SQL schema discovery."""
    last_discovery: str  # ISO timestamp
    rag_id: str
    databases_indexed: List[str]
    table_count: int
    total_columns: int
    embed_model: str


def load_sql_connections() -> Dict[str, SqlConnectionConfig]:
    """
    Load all enabled SQL connection configs from sql_connections/.

    Also auto-discovers:
    - research_dbs/*.duckdb files (as duckdb_folder connection)

    Returns:
        Dict mapping connection_name to SqlConnectionConfig
    """
    from ..config import get_config

    cfg = get_config()
    sql_dir = os.path.join(cfg.root_dir, "sql_connections")

    connections = {}

    # Load explicit YAML configs from sql_connections/
    if os.path.exists(sql_dir):
        for file in Path(sql_dir).glob("*.yaml"):
            if file.name == "discovery_metadata.yaml":
                continue

            try:
                with open(file) as f:
                    data = yaml.safe_load(f)
                    config = SqlConnectionConfig(**data)

                    if config.enabled:
                        # Resolve password from env var if specified
                        if config.password_env:
                            password = os.getenv(config.password_env)
                            if password:
                                config.password = password
                            else:
                                print(f"Warning: Password env var {config.password_env} not set for {config.connection_name}")

                        connections[config.connection_name] = config
            except Exception as e:
                print(f"Warning: Failed to load {file.name}: {e}")

    # Auto-discover research_dbs/ folder for DuckDB files
    research_dbs_dir = os.path.join(cfg.root_dir, "research_dbs")
    if os.path.exists(research_dbs_dir) and os.path.isdir(research_dbs_dir):
        duckdb_files = list(Path(research_dbs_dir).glob("*.duckdb"))
        if duckdb_files:
            # Create virtual duckdb_folder connection
            connections["research_dbs"] = SqlConnectionConfig(
                connection_name="research_dbs",
                type="duckdb_folder",
                folder_path=research_dbs_dir,
                enabled=True,
                sample_row_limit=100,
                distinct_value_threshold=50
            )

    # Auto-create ClickHouse connection for lars.* tables
    # This allows queries like SELECT * FROM lars.unified_logs to work in DuckDB
    # Note: clickhouse-connect uses HTTP port (8123), not native port (9000)
    clickhouse_host = os.getenv("LARS_CLICKHOUSE_HOST", "localhost")
    clickhouse_port = int(os.getenv("LARS_CLICKHOUSE_PORT", "8123"))  # HTTP port
    clickhouse_database = os.getenv("LARS_CLICKHOUSE_DATABASE", "lars")
    clickhouse_user = os.getenv("LARS_CLICKHOUSE_USER", "lars")
    clickhouse_password = os.getenv("LARS_CLICKHOUSE_PASSWORD", "lars")

    connections["lars"] = SqlConnectionConfig(
        connection_name="lars",
        type="clickhouse",
        host=clickhouse_host,
        port=clickhouse_port,
        database=clickhouse_database,
        user=clickhouse_user,
        password=clickhouse_password if clickhouse_password else None,
        enabled=True,
        sample_row_limit=100,
        distinct_value_threshold=50
    )

    return connections


def save_discovery_metadata(metadata: DiscoveryMetadata):
    """Save global discovery metadata."""
    from ..config import get_config

    cfg = get_config()
    sql_dir = os.path.join(cfg.root_dir, "sql_connections")
    os.makedirs(sql_dir, exist_ok=True)

    meta_path = os.path.join(sql_dir, "discovery_metadata.yaml")
    with open(meta_path, "w") as f:
        yaml.safe_dump(metadata.model_dump(), f, default_flow_style=False, sort_keys=False)


def load_discovery_metadata() -> Optional[DiscoveryMetadata]:
    """Load global discovery metadata if exists."""
    from ..config import get_config

    cfg = get_config()
    meta_path = os.path.join(cfg.root_dir, "sql_connections", "discovery_metadata.yaml")

    if not os.path.exists(meta_path):
        return None

    try:
        with open(meta_path) as f:
            return DiscoveryMetadata(**yaml.safe_load(f))
    except Exception as e:
        print(f"Warning: Failed to load discovery metadata: {e}")
        return None
