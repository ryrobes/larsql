# SQL Tools Implementation Plan

**Goal**: Add specialized SQL database discovery, RAG-based schema search, and query execution tools to Windlass.

## Overview

Enable LLM agents to:
1. **Discover** schemas from multiple databases (PostgreSQL, MySQL, SQLite, CSV)
2. **Search** for relevant tables/columns using RAG semantic search
3. **Execute** SQL queries across databases using DuckDB ATTACH

## Key Design Decisions

### Single Unified RAG Index
- **One `rag_id` for all databases** - enables cross-database discovery
- LLM searches "sales table" and finds it across all databases
- Naturally disambiguates when multiple matches exist
- Simpler mental model than per-database indices

### DuckDB ATTACH Strategy
- Unified SQL interface across all database types
- Correct syntax: `db_alias.schema.table` (e.g., `prod_db.public.users`)
- Supports cross-database joins
- On-demand attachment (no connection pool in v0)

### CSV Folder Approach
- **CSV folders treated as databases** - Point to a directory with multiple CSV files
- Each CSV file becomes a **schema** (filename sanitized for SQL: `bigfoot_sightings.csv` → `bigfoot_sightings`)
- Query syntax: `SELECT * FROM csv_files.bigfoot_sightings LIMIT 10`
- Much more practical than individual CSV connection configs
- Auto-discovery of all CSVs in folder

### Rich Metadata Collection
- **Low-cardinality columns** (< 100 distinct): Show value distribution with counts/percentages
- **High-cardinality columns**: Show distinct_count, min, max
- **Sample rows**: 500 rows per table (configurable)
- All in single JSON file per table for fast RAG embedding

### CLI Integration
- Short-circuit existing `windlass sql` command
- `windlass sql chart` - triggers schema discovery (nautical theme ⛵)
- Backwards compatible with existing `windlass sql "SELECT ..."` queries

## Architecture

```
sql_connections/
├── prod_db.json              # Connection config (passwords via env vars)
├── analytics_db.json
├── csv_files.json            # CSV folder config (points to directory)
├── discovery_metadata.json   # Global metadata (single rag_id)
└── samples/
    ├── prod_db/
    │   └── public/
    │       ├── users.json    # Table metadata + samples + distributions
    │       └── orders.json
    ├── analytics_db/
    │   └── public/
    │       └── sales_fact.json
    └── csv_files/
        ├── bigfoot_sightings.json  # Each CSV file = schema
        ├── sales_2024.json
        └── customer_data.json
```

## Implementation Phases

---

## Phase 1: Core Infrastructure (Foundation)

**Files to create/modify:**
- `windlass/sql_tools/__init__.py` - New module
- `windlass/sql_tools/config.py` - Connection config schema
- `windlass/sql_tools/connector.py` - DuckDB ATTACH logic
- `windlass/cli.py` - Short-circuit for `windlass sql chart`

### 1.1 Connection Config Schema

**File**: `windlass/sql_tools/config.py`

```python
from typing import Optional, Literal
from pydantic import BaseModel

class SqlConnectionConfig(BaseModel):
    """Configuration for a SQL database connection."""
    connection_name: str
    type: Literal["postgres", "mysql", "sqlite", "csv_folder"]
    enabled: bool = True

    # Database connection (not used for CSV)
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    user: Optional[str] = None
    password_env: Optional[str] = None  # Env var name for password

    # CSV folder-specific (NEW APPROACH!)
    folder_path: Optional[str] = None  # For csv_folder type - points to directory with CSVs
    # Each CSV file becomes a schema: bigfoot_sightings.csv → bigfoot_sightings
    # Query: SELECT * FROM csv_files.bigfoot_sightings LIMIT 10

    # Discovery settings
    sample_row_limit: int = 500
    distinct_value_threshold: int = 100  # Show distribution if < this

    # DuckDB extension (auto-install if needed)
    duckdb_extension: Optional[str] = None  # e.g., "postgres", "mysql"

class DiscoveryMetadata(BaseModel):
    """Global metadata for SQL schema discovery."""
    last_discovery: str  # ISO timestamp
    rag_id: str
    databases_indexed: list[str]
    table_count: int
    total_columns: int
    embed_model: str
```

**Configuration file format** (`sql_connections/prod_db.json`):
```json
{
  "connection_name": "prod_db",
  "type": "postgres",
  "host": "localhost",
  "port": 5432,
  "database": "production",
  "user": "analytics_user",
  "password_env": "PROD_DB_PASSWORD",
  "enabled": true,
  "sample_row_limit": 500,
  "distinct_value_threshold": 100
}
```

**CSV folder connection** (`sql_connections/csv_files.json`):
```json
{
  "connection_name": "csv_files",
  "type": "csv_folder",
  "folder_path": "/home/ryanr/csv-files",
  "enabled": true,
  "sample_row_limit": 500,
  "distinct_value_threshold": 100
}
```

Each CSV file in the folder becomes a schema:
- `bigfoot_sightings.csv` → Query: `SELECT * FROM csv_files.bigfoot_sightings`
- `sales_2024.csv` → Query: `SELECT * FROM csv_files.sales_2024`

### 1.2 Connection Loading

**File**: `windlass/sql_tools/config.py` (continued)

```python
import os
import json
from pathlib import Path
from typing import Dict, List
from ..config import get_config

def load_sql_connections() -> Dict[str, SqlConnectionConfig]:
    """Load all enabled SQL connection configs from sql_connections/."""
    cfg = get_config()
    sql_dir = os.path.join(cfg.root_dir, "sql_connections")

    if not os.path.exists(sql_dir):
        return {}

    connections = {}
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
                        config.password = os.getenv(config.password_env)

                    connections[config.connection_name] = config
        except Exception as e:
            print(f"Warning: Failed to load {file.name}: {e}")

    return connections

def save_discovery_metadata(metadata: DiscoveryMetadata):
    """Save global discovery metadata."""
    cfg = get_config()
    sql_dir = os.path.join(cfg.root_dir, "sql_connections")
    os.makedirs(sql_dir, exist_ok=True)

    meta_path = os.path.join(sql_dir, "discovery_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata.model_dump(), f, indent=2)

def load_discovery_metadata() -> Optional[DiscoveryMetadata]:
    """Load global discovery metadata if exists."""
    cfg = get_config()
    meta_path = os.path.join(cfg.root_dir, "sql_connections", "discovery_metadata.json")

    if not os.path.exists(meta_path):
        return None

    with open(meta_path) as f:
        return DiscoveryMetadata(**json.load(f))
```

### 1.3 DuckDB Connector

**File**: `windlass/sql_tools/connector.py`

```python
import duckdb
from typing import Optional
from .config import SqlConnectionConfig

class DatabaseConnector:
    """Handle DuckDB ATTACH for various database types."""

    def __init__(self):
        self.conn = duckdb.connect(":memory:")  # In-memory DuckDB
        self._attached = set()

    def attach(self, config: SqlConnectionConfig) -> str:
        """
        Attach database to DuckDB and return alias.
        Returns the alias name to use in queries.
        """
        alias = config.connection_name

        if alias in self._attached:
            return alias

        if config.type == "postgres":
            # Install extension if needed
            self.conn.execute("INSTALL postgres; LOAD postgres;")

            # Build connection string
            conn_str = f"dbname={config.database} host={config.host} port={config.port} user={config.user}"
            if hasattr(config, 'password') and config.password:
                conn_str += f" password={config.password}"

            self.conn.execute(f"ATTACH '{conn_str}' AS {alias} (TYPE postgres);")

        elif config.type == "mysql":
            self.conn.execute("INSTALL mysql; LOAD mysql;")

            conn_str = f"host={config.host} port={config.port} database={config.database} user={config.user}"
            if hasattr(config, 'password') and config.password:
                conn_str += f" password={config.password}"

            self.conn.execute(f"ATTACH '{conn_str}' AS {alias} (TYPE mysql);")

        elif config.type == "sqlite":
            # SQLite just needs file path
            self.conn.execute(f"ATTACH '{config.database}' AS {alias} (TYPE sqlite);")

        elif config.type == "csv":
            # CSV: Create view from file
            # Note: CSV doesn't use ATTACH, we'll read it directly
            table_name = f"{alias}_table"
            self.conn.execute(f"CREATE VIEW {table_name} AS SELECT * FROM read_csv_auto('{config.file_path}');")

        self._attached.add(alias)
        return alias

    def execute(self, sql: str):
        """Execute SQL query."""
        return self.conn.execute(sql)

    def fetch_df(self, sql: str):
        """Execute SQL and return pandas DataFrame."""
        return self.conn.execute(sql).df()

    def close(self):
        """Close connection."""
        self.conn.close()
```

### 1.4 CLI Short-Circuit

**File**: `windlass/cli.py` (modify existing `sql` command)

Find the existing `sql` command handler and add:

```python
@cli.command()
@click.argument("query")
@click.option("--format", type=click.Choice(["table", "json", "csv"]), default="table")
@click.option("--limit", type=int, default=None)
def sql(query: str, format: str, limit: Optional[int]):
    """
    Execute SQL query on Windlass logs or trigger schema discovery.

    Special commands:
      - windlass sql chart         # Discover all SQL schemas
      - windlass sql "SELECT ..."  # Query Windlass logs (existing)
    """
    # Short-circuit for discovery
    if query.lower() in ("chart", "discover", "scan"):
        from windlass.sql_tools.discovery import discover_all_schemas
        discover_all_schemas()
        return

    # Existing behavior: query Windlass logs
    from windlass.unified_logs import query_unified
    # ... existing implementation ...
```

---

## Phase 2: Schema Discovery (Data Collection)

**Files to create:**
- `windlass/sql_tools/discovery.py` - Main discovery orchestration
- `windlass/sql_tools/metadata.py` - Table metadata extraction

### 2.1 Table Metadata Extraction

**File**: `windlass/sql_tools/metadata.py`

```python
from typing import Dict, List, Any, Optional
import json
from .connector import DatabaseConnector
from .config import SqlConnectionConfig

class TableMetadata:
    """Extract and format table metadata."""

    def __init__(self, connector: DatabaseConnector):
        self.conn = connector

    def get_tables(self, config: SqlConnectionConfig) -> List[str]:
        """List all tables in database."""
        if config.type == "csv":
            # CSV is a single "table"
            return [f"{config.connection_name}_table"]

        # For databases, query information_schema
        alias = config.connection_name
        if config.type in ("postgres", "mysql"):
            sql = f"""
                SELECT table_schema, table_name
                FROM {alias}.information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'mysql')
                ORDER BY table_schema, table_name
            """
        elif config.type == "sqlite":
            sql = f"SELECT name FROM {alias}.sqlite_master WHERE type='table'"

        df = self.conn.fetch_df(sql)

        if config.type == "sqlite":
            return [(None, row['name']) for _, row in df.iterrows()]
        else:
            return [(row['table_schema'], row['table_name']) for _, row in df.iterrows()]

    def extract_table_metadata(
        self,
        config: SqlConnectionConfig,
        schema: Optional[str],
        table_name: str
    ) -> Dict[str, Any]:
        """
        Extract comprehensive metadata for a single table.

        Returns:
        {
          "table_name": "users",
          "schema": "public",
          "database": "prod_db",
          "row_count": 12500,
          "columns": [
            {
              "name": "id",
              "type": "INTEGER",
              "nullable": false,
              "metadata": {
                "distinct_count": 10000,
                "min": 1,
                "max": 10000
              }
            },
            {
              "name": "country",
              "type": "VARCHAR(50)",
              "nullable": true,
              "metadata": {
                "distinct_count": 50,
                "value_distribution": [
                  {"value": "USA", "count": 8234, "percentage": 67.2},
                  {"value": "Canada", "count": 2103, "percentage": 17.1},
                  ...
                ]
              }
            }
          ],
          "sample_rows": [...]
        }
        """
        alias = config.connection_name

        # Build qualified table name
        if config.type == "csv":
            full_table_name = f"{alias}_table"
        elif schema:
            full_table_name = f"{alias}.{schema}.{table_name}"
        else:
            full_table_name = f"{alias}.{table_name}"

        # Get row count
        row_count_sql = f"SELECT COUNT(*) as cnt FROM {full_table_name}"
        row_count = self.conn.fetch_df(row_count_sql).iloc[0]['cnt']

        # Get column info
        columns = self._extract_column_metadata(
            full_table_name,
            config.distinct_value_threshold,
            row_count
        )

        # Get sample rows
        sample_sql = f"SELECT * FROM {full_table_name} LIMIT {config.sample_row_limit}"
        sample_df = self.conn.fetch_df(sample_sql)
        sample_rows = sample_df.to_dict('records')

        return {
            "table_name": table_name,
            "schema": schema,
            "database": config.connection_name,
            "row_count": row_count,
            "columns": columns,
            "sample_rows": sample_rows
        }

    def _extract_column_metadata(
        self,
        full_table_name: str,
        threshold: int,
        total_rows: int
    ) -> List[Dict[str, Any]]:
        """Extract metadata for all columns."""
        # Get column names and types via DESCRIBE
        desc_sql = f"DESCRIBE {full_table_name}"
        desc_df = self.conn.fetch_df(desc_sql)

        columns = []
        for _, col_row in desc_df.iterrows():
            col_name = col_row['column_name']
            col_type = col_row['column_type']
            nullable = col_row['null'] == 'YES'

            # Get distinct count
            distinct_sql = f"SELECT COUNT(DISTINCT {col_name}) as cnt FROM {full_table_name}"
            distinct_count = self.conn.fetch_df(distinct_sql).iloc[0]['cnt']

            metadata = {
                "distinct_count": distinct_count
            }

            # Low-cardinality: get value distribution
            if distinct_count < threshold:
                dist_sql = f"""
                    SELECT
                        {col_name} as value,
                        COUNT(*) as count,
                        ROUND(100.0 * COUNT(*) / {total_rows}, 2) as percentage
                    FROM {full_table_name}
                    GROUP BY {col_name}
                    ORDER BY count DESC
                """
                dist_df = self.conn.fetch_df(dist_sql)
                metadata["value_distribution"] = dist_df.to_dict('records')
            else:
                # High-cardinality: get min/max
                if col_type in ('INTEGER', 'BIGINT', 'DOUBLE', 'DECIMAL', 'DATE', 'TIMESTAMP'):
                    minmax_sql = f"SELECT MIN({col_name}) as min_val, MAX({col_name}) as max_val FROM {full_table_name}"
                    minmax = self.conn.fetch_df(minmax_sql).iloc[0]
                    metadata["min"] = minmax['min_val']
                    metadata["max"] = minmax['max_val']

            columns.append({
                "name": col_name,
                "type": col_type,
                "nullable": nullable,
                "metadata": metadata
            })

        return columns
```

### 2.2 Discovery Orchestration

**File**: `windlass/sql_tools/discovery.py`

```python
import os
import json
import time
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..config import get_config
from ..rag.indexer import ensure_rag_index
from ..cascade import RagConfig
from .config import (
    load_sql_connections,
    save_discovery_metadata,
    DiscoveryMetadata
)
from .connector import DatabaseConnector
from .metadata import TableMetadata

console = Console()

def discover_all_schemas(session_id: str = None):
    """
    Chart all SQL schemas:
    1. Connect to each database
    2. Extract table metadata (schema, samples, distributions)
    3. Save to sql_connections/samples/
    4. Build unified RAG index
    5. Save discovery metadata
    """
    if not session_id:
        session_id = f"sql_discovery_{int(time.time())}"

    console.print("[bold cyan]⚓ Charting SQL databases...[/bold cyan]")

    # Load connections
    connections = load_sql_connections()
    if not connections:
        console.print("[yellow]⚠️  No SQL connections found in sql_connections/[/yellow]")
        console.print("[dim]Create connection configs like: sql_connections/prod_db.json[/dim]")
        return

    console.print(f"[dim]Found {len(connections)} enabled connection(s)[/dim]")

    cfg = get_config()
    sql_dir = os.path.join(cfg.root_dir, "sql_connections")
    samples_dir = os.path.join(sql_dir, "samples")

    # Statistics
    total_tables = 0
    total_columns = 0
    databases_indexed = []

    # Discover each database
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:

        for conn_name, conn_config in connections.items():
            task = progress.add_task(f"📊 Charting {conn_name}...", total=None)

            try:
                # Connect
                connector = DatabaseConnector()
                connector.attach(conn_config)
                metadata_extractor = TableMetadata(connector)

                # Get tables
                tables = metadata_extractor.get_tables(conn_config)
                console.print(f"[dim]  └─ {len(tables)} table(s) in {conn_name}[/dim]")

                # Process each table
                for schema, table_name in tables:
                    # Extract metadata
                    table_meta = metadata_extractor.extract_table_metadata(
                        conn_config, schema, table_name
                    )

                    # Save to file
                    if conn_config.type == "csv":
                        # CSV: flat structure
                        db_dir = os.path.join(samples_dir, conn_name)
                    else:
                        # Database: db/schema/table.json
                        db_dir = os.path.join(samples_dir, conn_name, schema or "default")

                    os.makedirs(db_dir, exist_ok=True)
                    table_file = os.path.join(db_dir, f"{table_name}.json")

                    with open(table_file, "w") as f:
                        json.dump(table_meta, f, indent=2, default=str)

                    total_tables += 1
                    total_columns += len(table_meta["columns"])

                databases_indexed.append(conn_name)
                connector.close()
                progress.update(task, completed=True)

            except Exception as e:
                console.print(f"[red]✗ Failed to chart {conn_name}: {e}[/red]")
                progress.update(task, completed=True)

    console.print(f"[green]✓ Charted {total_tables} tables across {len(databases_indexed)} database(s)[/green]")

    # Build unified RAG index
    console.print("[bold cyan]🔍 Building unified RAG index...[/bold cyan]")

    rag_config = RagConfig(
        directory=samples_dir,
        recursive=True,
        include=["*.json"],
        exclude=[]
    )

    rag_ctx = ensure_rag_index(
        rag_config=rag_config,
        cascade_path=None,
        session_id=session_id
    )

    # Save discovery metadata
    metadata = DiscoveryMetadata(
        last_discovery=datetime.now().isoformat(),
        rag_id=rag_ctx.rag_id,
        databases_indexed=databases_indexed,
        table_count=total_tables,
        total_columns=total_columns,
        embed_model=rag_ctx.embed_model
    )

    save_discovery_metadata(metadata)

    console.print(f"[bold green]🎯 SQL schema discovery complete![/bold green]")
    console.print(f"[dim]  RAG ID: {rag_ctx.rag_id}[/dim]")
    console.print(f"[dim]  Tables indexed: {total_tables}[/dim]")
    console.print(f"[dim]  Total columns: {total_columns}[/dim]")
```

---

## Phase 3: RAG Integration (Search Layer)

**Files to create:**
- `windlass/sql_tools/tools.py` - LLM-facing tools

### 3.1 SQL Search Tool

**File**: `windlass/sql_tools/tools.py`

```python
import json
from typing import Optional
from ..rag.store import search_chunks
from ..rag.context import get_rag_context_by_id
from .config import load_discovery_metadata

def sql_search(
    query: str,
    k: int = 10,
    score_threshold: Optional[float] = 0.3
) -> str:
    """
    Search SQL schema metadata using semantic search.

    Finds relevant tables and columns across all configured databases.
    Returns table metadata including column info, distributions, and sample values.

    Example queries:
      - "tables with user information"
      - "sales or revenue data"
      - "customer country information"

    Args:
        query: Natural language description of what to find
        k: Number of results to return (default: 10)
        score_threshold: Minimum similarity score (default: 0.3)

    Returns:
        JSON with matching tables and their metadata
    """
    # Load discovery metadata
    meta = load_discovery_metadata()
    if not meta:
        return json.dumps({
            "error": "No SQL schema index found. Run: windlass sql chart"
        })

    # Get RAG context
    rag_ctx = get_rag_context_by_id(meta.rag_id)
    if not rag_ctx:
        return json.dumps({
            "error": f"RAG context not found: {meta.rag_id}. Run: windlass sql chart"
        })

    # Search
    results = search_chunks(
        rag_ctx=rag_ctx,
        query=query,
        k=k,
        score_threshold=score_threshold
    )

    # Parse results - each chunk is a table.json file
    tables = []
    for result in results:
        # Load the full table metadata file
        # result['source'] is the relative path like "prod_db/public/users.json"
        import os
        from ..config import get_config

        cfg = get_config()
        full_path = os.path.join(
            cfg.root_dir,
            "sql_connections",
            "samples",
            result['source']
        )

        try:
            with open(full_path) as f:
                table_meta = json.load(f)
                tables.append({
                    "table": f"{table_meta['database']}.{table_meta['schema']}.{table_meta['table_name']}"
                              if table_meta['schema']
                              else f"{table_meta['database']}.{table_meta['table_name']}",
                    "database": table_meta['database'],
                    "schema": table_meta['schema'],
                    "table_name": table_meta['table_name'],
                    "row_count": table_meta['row_count'],
                    "columns": table_meta['columns'],
                    "score": result['score'],
                    "sample_rows": table_meta['sample_rows'][:5]  # First 5 samples
                })
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to load {full_path}: {e}[/yellow]")

    return json.dumps({
        "query": query,
        "rag_id": meta.rag_id,
        "total_results": len(tables),
        "tables": tables
    }, indent=2)

def list_sql_connections() -> str:
    """
    List all configured SQL database connections.

    Returns:
        JSON with connection names and last discovery info
    """
    meta = load_discovery_metadata()
    connections = load_sql_connections()

    return json.dumps({
        "connections": list(connections.keys()),
        "last_discovery": meta.last_discovery if meta else None,
        "rag_id": meta.rag_id if meta else None,
        "table_count": meta.table_count if meta else None,
    }, indent=2)
```

---

## Phase 4: Query Execution (Runtime)

### 4.1 SQL Execution Tool

**File**: `windlass/sql_tools/tools.py` (continued)

```python
def run_sql(sql: str, connection: str, limit: Optional[int] = 1000) -> str:
    """
    Execute SQL query on a specific database connection.

    Uses DuckDB ATTACH to connect to the database and execute queries.
    Results are returned as JSON.

    IMPORTANT: Use qualified table names in queries:
      - PostgreSQL/MySQL: connection_name.schema.table
      - SQLite: connection_name.table
      - CSV: connection_name_table

    Examples:
      - "SELECT * FROM prod_db.public.users LIMIT 10"
      - "SELECT COUNT(*) FROM analytics_db.sales_fact WHERE date > '2024-01-01'"
      - "SELECT * FROM sales_data_table"  # CSV

    Args:
        sql: SQL query to execute
        connection: Name of the connection to use
        limit: Maximum rows to return (default: 1000)

    Returns:
        JSON with query results
    """
    from .config import load_sql_connections
    from .connector import DatabaseConnector

    # Load connection config
    connections = load_sql_connections()
    if connection not in connections:
        return json.dumps({
            "error": f"Connection '{connection}' not found",
            "available_connections": list(connections.keys())
        })

    conn_config = connections[connection]

    try:
        # Connect and attach
        connector = DatabaseConnector()
        connector.attach(conn_config)

        # Add LIMIT if not present
        sql_with_limit = sql.strip()
        if limit and "LIMIT" not in sql_with_limit.upper():
            sql_with_limit += f" LIMIT {limit}"

        # Execute
        df = connector.fetch_df(sql_with_limit)

        # Convert to JSON
        results = df.to_dict('records')

        connector.close()

        return json.dumps({
            "sql": sql_with_limit,
            "connection": connection,
            "row_count": len(results),
            "results": results
        }, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": str(e),
            "sql": sql,
            "connection": connection
        })
```

---

## Phase 5: Registration & Documentation

### 5.1 Tool Registration

**File**: `windlass/__init__.py` (add to existing tool registration)

```python
# SQL tools
from windlass.sql_tools.tools import sql_search, run_sql, list_sql_connections

register_tackle("sql_search", sql_search)
register_tackle("run_sql", run_sql)
register_tackle("list_sql_connections", list_sql_connections)
```

### 5.2 Example Cascade

**File**: `examples/sql_analysis_flow.json`

```json
{
  "cascade_id": "sql_analysis_demo",
  "description": "Demonstrates SQL schema discovery and query execution",
  "inputs_schema": {
    "question": "Natural language question about the data"
  },
  "phases": [
    {
      "name": "discover_schema",
      "instructions": "The user asked: {{ input.question }}\n\nFirst, search for relevant tables using sql_search. Find tables that might contain data relevant to this question.",
      "tackle": ["sql_search", "list_sql_connections"],
      "handoffs": ["write_query"]
    },
    {
      "name": "write_query",
      "instructions": "Based on the schema information from the previous phase, write a SQL query to answer: {{ input.question }}\n\nUse the run_sql tool to execute your query.\n\nIMPORTANT: Use qualified table names like: database.schema.table",
      "tackle": ["run_sql"],
      "handoffs": ["analyze_results"]
    },
    {
      "name": "analyze_results",
      "instructions": "Analyze the query results and provide a clear answer to: {{ input.question }}\n\nSummarize key findings and insights.",
      "tackle": []
    }
  ]
}
```

### 5.3 Update CLAUDE.md

Add section after section 2.8 (Docker Sandboxed Execution):

```markdown
### 2.9. SQL Tools - Multi-Database Discovery & Query

Windlass includes specialized tools for SQL database schema discovery, semantic search, and query execution across multiple databases.

**Supported Databases:**
- PostgreSQL
- MySQL
- SQLite
- CSV files

**Architecture:**
- Unified RAG index across all databases
- DuckDB ATTACH for cross-database queries
- Rich metadata (column types, distributions, samples)

**Configuration:**

Create connection configs in `sql_connections/`:

```json
{
  "connection_name": "prod_db",
  "type": "postgres",
  "host": "localhost",
  "port": 5432,
  "database": "production",
  "user": "analytics",
  "password_env": "PROD_DB_PASSWORD",
  "enabled": true
}
```

**Discovery:**

```bash
# Chart all schemas (builds RAG index)
windlass sql chart
```

**Built-in Tools:**

1. **sql_search(query, k=10)** - Semantic search for tables/columns
   ```json
   {"tool": "sql_search", "arguments": {"query": "user account data"}}
   ```

2. **run_sql(sql, connection, limit=1000)** - Execute SQL query
   ```json
   {"tool": "run_sql", "arguments": {
     "sql": "SELECT * FROM prod_db.public.users WHERE country = 'USA'",
     "connection": "prod_db"
   }}
   ```

3. **list_sql_connections()** - List available connections

**Use Cases:**
- Natural language SQL queries
- Cross-database analysis
- Schema exploration
- Data discovery workflows
```

---

## Testing Plan

### Unit Tests

**File**: `windlass/tests/test_sql_tools.py`

```python
import pytest
from windlass.sql_tools.config import SqlConnectionConfig
from windlass.sql_tools.connector import DatabaseConnector

def test_postgres_connection_config():
    config = SqlConnectionConfig(
        connection_name="test_db",
        type="postgres",
        host="localhost",
        port=5432,
        database="test",
        user="test_user"
    )
    assert config.connection_name == "test_db"
    assert config.type == "postgres"

def test_csv_connection_config():
    config = SqlConnectionConfig(
        connection_name="csv_data",
        type="csv",
        file_path="data/test.csv"
    )
    assert config.type == "csv"
    assert config.file_path == "data/test.csv"

def test_duckdb_csv_attach(tmp_path):
    # Create test CSV
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("id,name\n1,Alice\n2,Bob\n")

    config = SqlConnectionConfig(
        connection_name="test_csv",
        type="csv",
        file_path=str(csv_file)
    )

    connector = DatabaseConnector()
    alias = connector.attach(config)

    # Query
    df = connector.fetch_df(f"SELECT * FROM {alias}_table")
    assert len(df) == 2
    assert list(df.columns) == ['id', 'name']
```

### Integration Test

Create a test cascade that:
1. Discovers a test SQLite database
2. Searches for tables
3. Executes a query
4. Validates results

---

## Migration & Rollout Strategy

### Phase 1 (MVP)
- ✅ PostgreSQL support
- ✅ CSV support
- ✅ Basic metadata (no distributions yet)
- ✅ RAG search
- ✅ Query execution

### Phase 2 (Rich Metadata)
- ✅ Value distributions for low-cardinality columns
- ✅ Min/max for high-cardinality
- ✅ Configurable thresholds

### Phase 3 (Additional Databases)
- ✅ MySQL support
- ✅ SQLite support

### Phase 4 (Optimization)
- Connection pooling
- Incremental discovery (skip unchanged tables)
- Parallel table scanning

---

## File Checklist

**New files to create:**
- [ ] `windlass/sql_tools/__init__.py`
- [ ] `windlass/sql_tools/config.py`
- [ ] `windlass/sql_tools/connector.py`
- [ ] `windlass/sql_tools/metadata.py`
- [ ] `windlass/sql_tools/discovery.py`
- [ ] `windlass/sql_tools/tools.py`
- [ ] `windlass/tests/test_sql_tools.py`
- [ ] `examples/sql_analysis_flow.json`

**Files to modify:**
- [ ] `windlass/cli.py` - Add chart short-circuit
- [ ] `windlass/__init__.py` - Register tools
- [ ] `CLAUDE.md` - Add SQL tools section

**Directories to create:**
- [ ] `windlass/sql_tools/`
- [ ] `sql_connections/` (user workspace)
- [ ] `sql_connections/samples/` (generated)

---

## Example Usage

### 1. Setup

```bash
# Create connection config
cat > sql_connections/prod_db.json <<EOF
{
  "connection_name": "prod_db",
  "type": "postgres",
  "host": "localhost",
  "port": 5432,
  "database": "production",
  "user": "analytics",
  "password_env": "PROD_DB_PASSWORD",
  "enabled": true
}
EOF

# Create CSV connection
cat > sql_connections/sales.json <<EOF
{
  "connection_name": "sales_data",
  "type": "csv",
  "file_path": "data/sales_2024.csv",
  "enabled": true
}
EOF

# Set password
export PROD_DB_PASSWORD=secret123
```

### 2. Discovery

```bash
# Chart schemas
windlass sql chart

# Output:
# ⚓ Charting SQL databases...
# Found 2 enabled connection(s)
# 📊 Charting prod_db...
#   └─ 47 table(s) in prod_db
# 📊 Charting sales_data...
#   └─ 1 table(s) in sales_data
# ✓ Charted 48 tables across 2 database(s)
# 🔍 Building unified RAG index...
# 🎯 SQL schema discovery complete!
#   RAG ID: a1b2c3d4e5f6
#   Tables indexed: 48
#   Total columns: 523
```

### 3. Use in Cascade

```bash
windlass examples/sql_analysis_flow.json --input '{
  "question": "How many users signed up from each country in 2024?"
}'

# Agent flow:
# Phase 1 (discover_schema):
#   - Calls sql_search("user signup country 2024")
#   - Finds prod_db.public.users table
#   - Sees country column with 50 distinct values + distribution
#   - Sees signup_date column (min: 2020-01-01, max: 2025-12-05)
#
# Phase 2 (write_query):
#   - Writes SQL:
#     SELECT country, COUNT(*) as user_count
#     FROM prod_db.public.users
#     WHERE signup_date >= '2024-01-01'
#     GROUP BY country
#     ORDER BY user_count DESC
#   - Calls run_sql with query
#
# Phase 3 (analyze_results):
#   - Summarizes findings
```

---

## Success Metrics

- [ ] Can discover PostgreSQL, MySQL, SQLite, CSV
- [ ] RAG search finds relevant tables with < 0.3 similarity threshold
- [ ] Value distributions accurate for low-cardinality columns
- [ ] Cross-database queries work (DuckDB ATTACH)
- [ ] Discovery completes in < 5 minutes for 100 tables
- [ ] CLI short-circuit doesn't break existing `windlass sql` queries
- [ ] Tools registered and available in cascades

---

## Future Enhancements

- **Incremental Discovery**: Skip unchanged tables (use mtime/checksum)
- **Schema Caching**: Cache DESCRIBE results
- **Query Optimization Hints**: Suggest indexes, explain plans
- **Visual Schema Browser**: Web UI for exploring schemas
- **Smart Query Generation**: LLM generates SQL from natural language
- **Cross-Database Joins**: Automatic query rewriting for optimal joins
- **Connection Pooling**: Reuse connections across tools
- **Security**: Row-level security, query sandboxing
- **Monitoring**: Track query costs, slow queries

---

## Notes

- CSV files are treated as single-table "databases"
- Passwords never logged (retrieved from env vars only)
- DuckDB handles type conversions automatically
- RAG index is incremental (existing RAG system already handles this)
- Discovery can be scheduled via cron: `0 2 * * * windlass sql chart`

---

**End of Implementation Plan**

*Ready to implement! Start with Phase 1, then iterate through each phase sequentially.*
