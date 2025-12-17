"""
SQL connection configuration and metadata management.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class SqlConnectionConfig(BaseModel):
    """Configuration for a SQL database connection."""
    connection_name: str
    type: Literal["postgres", "mysql", "sqlite", "csv_folder", "duckdb_folder"]
    enabled: bool = True

    # Database connection (not used for CSV/DuckDB folders)
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    user: Optional[str] = None
    password_env: Optional[str] = None  # Env var name for password

    # Folder-based connections
    folder_path: Optional[str] = None  # For csv_folder/duckdb_folder - points to directory
    # csv_folder: Each CSV file becomes a table: bigfoot_sightings.csv → csv_files.bigfoot_sightings
    # duckdb_folder: Each .duckdb file becomes a schema: market_research.duckdb → research_dbs.market_research.table_name

    # Discovery settings
    sample_row_limit: int = 50
    distinct_value_threshold: int = 100  # Show distribution if < this

    # DuckDB extension (auto-install if needed)
    duckdb_extension: Optional[str] = None  # e.g., "postgres", "mysql"

    # Resolved password (not in config file, set at runtime)
    password: Optional[str] = Field(default=None, exclude=True)


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

    # Load explicit JSON configs from sql_connections/
    if os.path.exists(sql_dir):
        for file in Path(sql_dir).glob("*.json"):
            if file.name == "discovery_metadata.json":
                continue

            try:
                with open(file) as f:
                    data = json.load(f)
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

    return connections


def save_discovery_metadata(metadata: DiscoveryMetadata):
    """Save global discovery metadata."""
    from ..config import get_config

    cfg = get_config()
    sql_dir = os.path.join(cfg.root_dir, "sql_connections")
    os.makedirs(sql_dir, exist_ok=True)

    meta_path = os.path.join(sql_dir, "discovery_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata.model_dump(), f, indent=2)


def load_discovery_metadata() -> Optional[DiscoveryMetadata]:
    """Load global discovery metadata if exists."""
    from ..config import get_config

    cfg = get_config()
    meta_path = os.path.join(cfg.root_dir, "sql_connections", "discovery_metadata.json")

    if not os.path.exists(meta_path):
        return None

    try:
        with open(meta_path) as f:
            return DiscoveryMetadata(**json.load(f))
    except Exception as e:
        print(f"Warning: Failed to load discovery metadata: {e}")
        return None
