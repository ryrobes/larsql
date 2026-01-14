"""
SQL schema discovery orchestration.

Charts all configured SQL databases and builds a unified RAG index.
"""

import os
import yaml
import time
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn


def _sanitize_for_yaml(obj):
    """
    Recursively convert non-YAML-serializable types to strings.
    Handles pandas NA, Timestamp, numpy types, etc.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_for_yaml(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_yaml(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    # Handle pandas/numpy NA values
    try:
        import pandas as pd
        if pd.isna(obj):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    # Convert everything else to string (Timestamp, numpy types, etc.)
    return str(obj)

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

# Elasticsearch indexing
try:
    from ..elastic import get_elastic_client, create_sql_schema_index, index_sql_schema
    ELASTICSEARCH_AVAILABLE = True
except ImportError:
    ELASTICSEARCH_AVAILABLE = False

console = Console()


def discover_all_schemas(session_id: str | None = None):
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

    # Check if Elasticsearch is available
    elastic_enabled = False
    if ELASTICSEARCH_AVAILABLE:
        try:
            es = get_elastic_client()
            if es.ping():
                create_sql_schema_index()  # Ensure index exists
                elastic_enabled = True
                console.print("[dim]✓ Elasticsearch connected - will index schemas for hybrid search[/dim]")
        except Exception as e:
            console.print(f"[dim]⚠ Elasticsearch not available: {e}[/dim]")
            console.print("[dim]  Continuing with ClickHouse RAG only[/dim]")

    # Load connections
    connections = load_sql_connections()
    if not connections:
        console.print("[yellow]⚠️  No SQL connections found in sql_connections/[/yellow]")
        console.print("[dim]Create connection configs like: sql_connections/prod_db.yaml[/dim]")
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
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:

        for conn_name, conn_config in connections.items():
            db_task = progress.add_task(f"📊 Charting {conn_name}...", total=None)

            try:
                # Connect
                connector = DatabaseConnector()
                connector.attach(conn_config)
                metadata_extractor = TableMetadata(connector)

                # Get tables
                tables = metadata_extractor.get_tables(conn_config)
                console.print(f"[dim]  └─ {len(tables)} table(s) in {conn_name}[/dim]")

                if not tables:
                    progress.update(db_task, completed=True)
                    continue

                # Update progress bar with table count
                progress.update(db_task, total=len(tables), completed=0)

                # Process each table
                for idx, (schema, table_name) in enumerate(tables):
                    progress.update(db_task, description=f"📊 Charting {conn_name} ({table_name})", completed=idx)

                    # Extract metadata
                    table_meta = metadata_extractor.extract_table_metadata(
                        conn_config, schema, table_name
                    )

                    if table_meta is None:
                        continue

                    # Save to file
                    if conn_config.type == "csv_folder":
                        # CSV: flat structure under connection name
                        db_dir = os.path.join(samples_dir, conn_name)
                    elif conn_config.type == "duckdb_folder":
                        # DuckDB folder: research_dbs/db_name/table.json
                        # schema here is the db_name (e.g., "market_research")
                        db_dir = os.path.join(samples_dir, conn_name, schema or "default")
                    else:
                        # Database: db/schema/table.json
                        db_dir = os.path.join(samples_dir, conn_name, schema or "default")

                    os.makedirs(db_dir, exist_ok=True)
                    table_file = os.path.join(db_dir, f"{table_name}.yaml")

                    with open(table_file, "w") as f:
                        yaml.safe_dump(_sanitize_for_yaml(table_meta), f, default_flow_style=False, sort_keys=False, allow_unicode=True)

                    total_tables += 1
                    total_columns += len(table_meta["columns"])

                    # Also index to Elasticsearch if available
                    # Note: Embedding will be added after RAG index builds it
                    if elastic_enabled:
                        try:
                            # Build qualified name for Elasticsearch ID
                            if table_meta['schema'] and table_meta['schema'] != table_meta['database']:
                                qualified_name = f"{table_meta['database']}.{table_meta['schema']}.{table_meta['table_name']}"
                            else:
                                qualified_name = f"{table_meta['database']}.{table_meta['table_name']}"

                            # Temporarily index without embedding - will update after RAG index is built
                            table_meta['qualified_name'] = qualified_name
                            table_meta['embedding'] = None  # Will be updated later
                            table_meta['embedding_model'] = None
                            table_meta['indexed_at'] = datetime.now().isoformat()

                            # Don't index yet - we'll do it after embeddings are created
                            # Just store for later
                            if not hasattr(discover_all_schemas, '_pending_elastic_docs'):
                                discover_all_schemas._pending_elastic_docs = []
                            discover_all_schemas._pending_elastic_docs.append(table_meta)

                        except Exception as e:
                            console.print(f"[dim]⚠ Elasticsearch prep failed for {table_name}: {e}[/dim]")

                databases_indexed.append(conn_name)
                progress.update(db_task, completed=len(tables))
                connector.close()

            except Exception as e:
                console.print(f"[red]✗ Failed to chart {conn_name}: {e}[/red]")
                progress.update(db_task, completed=True)

    console.print(f"[green]✓ Charted {total_tables} tables across {len(databases_indexed)} database(s)[/green]")

    # Build unified RAG index
    console.print("[bold cyan]🔍 Building unified RAG index...[/bold cyan]")

    rag_config = RagConfig(
        directory=samples_dir,
        recursive=True,
        include=["*.yaml"],
        exclude=[]
    )

    try:
        rag_ctx = ensure_rag_index(
            rag_config=rag_config,
            cascade_path=None,
            session_id=session_id
        )

        # Index to Elasticsearch with embeddings from ClickHouse
        if elastic_enabled and hasattr(discover_all_schemas, '_pending_elastic_docs'):
            console.print("[bold cyan]📦 Indexing to Elasticsearch with embeddings...[/bold cyan]")

            try:
                from ..db_adapter import get_db
                db = get_db()

                # Get all embeddings from ClickHouse RAG index
                # Group by doc_id and get first chunk's embedding
                embeddings_query = f"""
                    SELECT
                        doc_id,
                        rel_path,
                        argMax(embedding, chunk_index) as embedding,
                        argMax(embedding_model, chunk_index) as embedding_model
                    FROM rag_chunks
                    WHERE rag_id = '{rag_ctx.rag_id}'
                    GROUP BY doc_id, rel_path
                """
                embeddings_data = db.query(embeddings_query)

                # Create mapping: table filename -> embedding
                # rel_path looks like "conn_name/schema/table.yaml" or "conn_name/table.yaml"
                embedding_map = {}
                for row in embeddings_data:
                    # Extract table name from path (handle both .yaml and legacy .json)
                    path_parts = row['rel_path'].split('/')
                    table_filename = path_parts[-1]
                    table_name = table_filename.replace('.yaml', '').replace('.json', '')
                    embedding_map[table_name] = row

                # Update pending docs with embeddings
                docs_with_embeddings = []
                for doc in discover_all_schemas._pending_elastic_docs:
                    table_name = doc['table_name']

                    if table_name in embedding_map:
                        emb_data = embedding_map[table_name]
                        doc['embedding'] = emb_data['embedding']
                        doc['embedding_model'] = emb_data['embedding_model']
                    else:
                        # Index without embedding (text search only)
                        console.print(f"[dim]  ⚠ No embedding found for {table_name}[/dim]")
                        doc['embedding'] = None
                        doc['embedding_model'] = None

                    docs_with_embeddings.append(doc)

                # Bulk index to Elasticsearch
                if docs_with_embeddings:
                    from ..elastic import bulk_index_sql_schemas
                    indexed_count = bulk_index_sql_schemas(docs_with_embeddings)
                    console.print(f"[green]✓ Indexed {indexed_count} schemas to Elasticsearch[/green]")

                # Clean up
                del discover_all_schemas._pending_elastic_docs

            except Exception as e:
                console.print(f"[yellow]⚠ Elasticsearch indexing failed: {e}[/yellow]")
                console.print("[dim]  ClickHouse RAG indexing succeeded - you can still use sql_search[/dim]")

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
        console.print(f"[dim]  Metadata saved: sql_connections/discovery_metadata.yaml[/dim]")
        console.print()
        console.print("[cyan]💡 Use sql_search tool in cascades to search schemas[/cyan]")

    except Exception as e:
        console.print(f"[yellow]⚠️  Failed to build RAG index: {e}[/yellow]")
        console.print(f"[dim]RAG semantic search will not be available, but schema files were saved.[/dim]")
        import traceback
        traceback.print_exc()

        # Save metadata without RAG info so schema files are still usable
        metadata = DiscoveryMetadata(
            last_discovery=datetime.now().isoformat(),
            rag_id=f"sql_schemas_{int(time.time())}",  # Fallback ID
            databases_indexed=databases_indexed,
            table_count=total_tables,
            total_columns=total_columns,
            embed_model="none"
        )
        save_discovery_metadata(metadata)

        console.print(f"[bold green]✓ Schema discovery completed![/bold green]")
        console.print(f"[dim]  Tables saved: {total_tables}[/dim]")
        console.print(f"[dim]  Location: sql_connections/samples/[/dim]")
        console.print()
        console.print("[yellow]💡 Note: sql_search tool requires RAG index. Check embedding API configuration.[/yellow]")
        console.print("[dim]     You can still use sql_query tool with qualified table names.[/dim]")
