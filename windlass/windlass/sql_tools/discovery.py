"""
SQL schema discovery orchestration.

Charts all configured SQL databases and builds a unified RAG index.
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

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
        include=["*.json"],
        exclude=[]
    )

    try:
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
        console.print(f"[dim]  Metadata saved: sql_connections/discovery_metadata.json[/dim]")
        console.print()
        console.print("[cyan]💡 Use sql_search tool in cascades to search schemas[/cyan]")

    except Exception as e:
        console.print(f"[red]✗ Failed to build RAG index: {e}[/red]")
        import traceback
        traceback.print_exc()
