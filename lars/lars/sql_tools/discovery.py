"""
SQL schema discovery orchestration.

Charts all configured SQL databases and builds a unified RAG index.
"""

import os
import yaml
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from ..console_style import S


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
from .sql_duckdb_index import USE_DEDICATED_SQL_DUCKDB_INDEX, rebuild_sql_index
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


_KG_TIER2_AUTO = os.getenv(
    "LARS_KG_TIER2_AUTO", "0",
).strip().lower() in {"1", "true", "yes", "on"}

_KG_TIER2_MAX_ENTITIES = int(os.getenv("LARS_KG_TIER2_MAX_ENTITIES", "0"))  # 0 = all
_KG_TIER2_MODEL_TIER = os.getenv("LARS_KG_TIER2_MODEL_TIER", "fast")


def _run_kg_extraction(samples_dir: str, session_id: str | None = None):
    """Run Tier 1 KG extraction, then KG embeddings.

    Tier 2 is controlled by LARS_KG_TIER2_AUTO (default off).
    Non-fatal: logs warnings on failure.
    """
    try:
        from ..kg.extractor import extract_kg_from_crawl
        console.print(f"[bold cyan]🔗 Building knowledge graph (Tier 1)...[/bold cyan]")
        result = extract_kg_from_crawl(samples_dir=samples_dir, session_id=session_id)
        console.print(
            f"[green][OK] Knowledge graph: "
            f"{result['entities_added']} entities, "
            f"{result['edges_added']} edges, "
            f"{result['observations_added']} observations "
            f"({result['elapsed_seconds']}s)[/green]"
        )
    except Exception as e:
        console.print(f"[yellow][WARN] Knowledge graph extraction failed: {e}[/yellow]")
        console.print("[dim]  Schema discovery and RAG index are unaffected.[/dim]")
        return  # Skip Tier 2 if Tier 1 failed

    # Tier 2: optional LLM enrichment (manual by default)
    if _KG_TIER2_AUTO:
        try:
            from ..kg.dreamer import dream_tier2
            limit_label = f"max {_KG_TIER2_MAX_ENTITIES}" if _KG_TIER2_MAX_ENTITIES > 0 else "all"
            console.print(
                f"[bold cyan]🧠 Dreaming (Tier 2 enrichment, "
                f"{limit_label} entities, "
                f"model={_KG_TIER2_MODEL_TIER})...[/bold cyan]"
            )
            t2_result = dream_tier2(
                max_entities=_KG_TIER2_MAX_ENTITIES,
                model_tier=_KG_TIER2_MODEL_TIER,
                samples_dir=samples_dir,
            )
        except Exception as e:
            console.print(f"[yellow][WARN] Tier 2 enrichment failed: {e}[/yellow]")
            console.print("[dim]  Tier 1 data is unaffected. You can run kg_dream manually.[/dim]")
    else:
        console.print("[dim]Tier 2 dreaming skipped (manual). Run 'lars kg dream' when ready.[/dim]")

    # Tier 2.5: Embed entities for kg_search (runs after Tier 1 / optional Tier 2)
    try:
        from ..kg.embedder import embed_kg_entities
        console.print(f"[bold cyan]🔮 Embedding KG entities for semantic search...[/bold cyan]")
        _ = embed_kg_entities()
    except Exception as e:
        console.print(f"[yellow][WARN] KG entity embedding failed: {e}[/yellow]")
        console.print("[dim]  KG data is unaffected. You can run kg_embed manually.[/dim]")

    # Tier 2.5b: Embed observations for observation-level relevance ranking
    try:
        from ..kg.embedder import embed_kg_observations
        console.print(f"[bold cyan]🔮 Embedding KG observations for relevance ranking...[/bold cyan]")
        _ = embed_kg_observations()
    except Exception as e:
        console.print(f"[yellow][WARN] KG observation embedding failed: {e}[/yellow]")
        console.print("[dim]  kg_search will fall back to tier/confidence ranking for observations.[/dim]")


_SQL_FIELD_INDEX_INCLUDE_TEXT_SAMPLES = os.getenv(
    "LARS_SQL_FIELD_INDEX_INCLUDE_TEXT_SAMPLES",
    "0",
).strip().lower() in {"1", "true", "yes", "on"}
_SQL_FIELD_INDEX_MAX_SAMPLE_VALUE_CHARS = max(
    16,
    int(os.getenv("LARS_SQL_FIELD_INDEX_MAX_SAMPLE_VALUE_CHARS", "80")),
)
_SQL_FIELD_INDEX_MAX_SAMPLE_VALUES = max(
    0,
    int(os.getenv("LARS_SQL_FIELD_INDEX_MAX_SAMPLE_VALUES", "5")),
)


def _ident_equal(left: Optional[str], right: Optional[str]) -> bool:
    if left is None or right is None:
        return False
    return str(left).strip().lower() == str(right).strip().lower()


def _normalized_schema_value(database: Optional[str], schema: Optional[str]) -> Optional[str]:
    if schema is None:
        return None
    norm_schema = str(schema).strip()
    norm_db = str(database).strip() if database else ""
    if not norm_schema:
        return None
    if norm_db and _ident_equal(norm_schema, norm_db):
        return None
    return norm_schema


def _sql_table_ref_for_index(table_meta: dict, conn_type: Optional[str] = None) -> Optional[str]:
    database = str(table_meta.get("database") or "").strip()
    table_name = str(table_meta.get("table_name") or "").strip()
    if not database or not table_name:
        return None

    raw_schema = str(table_meta.get("schema") or "").strip()
    schema = _normalized_schema_value(database, raw_schema)
    ctype = str(conn_type or "").strip().lower()

    # For duckdb_folder connections, metadata.schema is the attached DB name.
    if ctype == "duckdb_folder":
        if raw_schema:
            return f"{raw_schema}.{table_name}"
        return f"{database}.{table_name}"

    # Connection-local, schema-less query forms.
    if ctype in {
        "csv_folder",
        "jsonl_folder",
        "markdown_folder",
        "sqlite",
        "duckdb",
        "native",
        "s3",
        "azure",
        "gcs",
        "http",
        "mongodb",
        "cassandra",
        "oracle",
        "mssql",
        "db2",
        "hana",
        "excel",
        "gsheets",
        "delta",
        "iceberg",
        "clickhouse",
    }:
        return f"{database}.{table_name}"

    if schema:
        return f"{database}.{schema}.{table_name}"
    return f"{database}.{table_name}"


def _enrich_table_doc_for_index(table_meta: dict, conn_type: Optional[str] = None) -> dict:
    doc = dict(table_meta or {})
    sql_table_ref = _sql_table_ref_for_index(doc, conn_type)
    if sql_table_ref:
        doc["sql_table_ref"] = sql_table_ref
        doc["example_query"] = f"SELECT * FROM {sql_table_ref} LIMIT 5"
    return doc


def _is_text_like_type(col_type: str) -> bool:
    col_type_norm = str(col_type or "").upper()
    text_markers = ("CHAR", "TEXT", "STRING", "VARCHAR", "JSON", "XML", "CLOB", "BLOB", "BYTEA")
    return any(marker in col_type_norm for marker in text_markers)


def _clean_sample_value(value: object, max_chars: int) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _write_field_index(db_dir: str, table_meta: dict, conn_type: Optional[str] = None):
    """
    Generate a field-level index file for granular RAG search.

    Creates one text chunk per column, formatted for good embedding quality.
    The RAG indexer picks this up automatically alongside the table YAML.
    """
    table_name = table_meta.get("table_name", "unknown")
    database = table_meta.get("database", "")
    schema = table_meta.get("schema", "")
    columns = table_meta.get("columns", [])
    row_count = table_meta.get("row_count", 0)

    if not columns:
        return

    # Build qualified name
    if schema and schema != database:
        qualified = f"{database}.{schema}.{table_name}"
    else:
        qualified = f"{database}.{table_name}"
    sql_table_ref = table_meta.get("sql_table_ref") or _sql_table_ref_for_index(table_meta, conn_type)
    example_query = table_meta.get("example_query")
    if not example_query and sql_table_ref:
        example_query = f"SELECT * FROM {sql_table_ref} LIMIT 5"

    # Generate one entry per field with rich searchable text
    field_entries = []
    for col in columns:
        col_name = col.get("name", "")
        col_type = col.get("type", "")
        nullable = col.get("nullable", True)
        meta = col.get("metadata", {})
        distinct = meta.get("distinct_count", "")

        # Build a natural language description for better embedding
        desc_parts = [
            f"Field '{col_name}' in table {qualified}.",
            f"Type: {col_type}.",
        ]
        if distinct:
            desc_parts.append(f"Has {distinct} distinct values.")
        if not nullable:
            desc_parts.append("NOT NULL (required).")
        if row_count:
            desc_parts.append(f"Table has {row_count} rows.")

        # Add sample values if available (from value_distribution), but gate noisy long-text fields.
        dist = meta.get("value_distribution", [])
        include_samples = True
        if _is_text_like_type(col_type) and not _SQL_FIELD_INDEX_INCLUDE_TEXT_SAMPLES:
            include_samples = False
        if include_samples and dist and len(dist) > 0 and _SQL_FIELD_INDEX_MAX_SAMPLE_VALUES > 0:
            samples = [
                _clean_sample_value(d.get("value"), _SQL_FIELD_INDEX_MAX_SAMPLE_VALUE_CHARS)
                for d in dist[:_SQL_FIELD_INDEX_MAX_SAMPLE_VALUES]
                if d.get("value") is not None
            ]
            if samples:
                desc_parts.append(f"Sample values: {', '.join(samples)}.")

        # Add min/max if available
        min_val = meta.get("min")
        max_val = meta.get("max")
        if min_val is not None and max_val is not None:
            desc_parts.append(f"Range: {min_val} to {max_val}.")

        field_entries.append({
            "field": col_name,
            "table": table_name,
            "qualified_table": qualified,
            "database": database,
            "schema": schema,
            "type": col_type,
            "description": " ".join(desc_parts),
        })

    if field_entries:
        fields_file = os.path.join(db_dir, f"{table_name}_fields.yaml")
        payload = {"fields": field_entries, "source_table": qualified}
        if sql_table_ref:
            payload["sql_table_ref"] = sql_table_ref
        if example_query:
            payload["example_query"] = example_query
        with open(fields_file, "w") as f:
            yaml.safe_dump(
                payload,
                f, default_flow_style=False, sort_keys=False, allow_unicode=True
            )


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
                console.print("[dim][OK] Elasticsearch connected - will index schemas for hybrid search[/dim]")
        except Exception as e:
            console.print(f"[dim][WARN] Elasticsearch not available: {e}[/dim]")
            console.print("[dim]  Continuing with Chroma RAG only[/dim]")

    # Load connections
    connections = load_sql_connections()
    if not connections:
        console.print("[yellow][WARN]  No SQL connections found in sql_connections/[/yellow]")
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
            db_task = progress.add_task(f"[CHART] Charting {conn_name}...", total=None)

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
                    progress.update(db_task, description=f"[CHART] Charting {conn_name} ({table_name})", completed=idx)

                    # Extract metadata
                    table_meta = metadata_extractor.extract_table_metadata(
                        conn_config, schema, table_name
                    )

                    if table_meta is None:
                        continue
                    table_doc = _enrich_table_doc_for_index(table_meta, conn_config.type)

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
                        yaml.safe_dump(_sanitize_for_yaml(table_doc), f, default_flow_style=False, sort_keys=False, allow_unicode=True)

                    # Generate field-level index file for granular RAG search
                    _write_field_index(db_dir, table_doc, conn_type=conn_config.type)

                    total_tables += 1
                    total_columns += len(table_doc["columns"])

                    # Also index to Elasticsearch if available
                    # Note: Embedding will be added after RAG index builds it
                    if elastic_enabled:
                        try:
                            # Build qualified name for Elasticsearch ID
                            if table_doc['schema'] and table_doc['schema'] != table_doc['database']:
                                qualified_name = f"{table_doc['database']}.{table_doc['schema']}.{table_doc['table_name']}"
                            else:
                                qualified_name = f"{table_doc['database']}.{table_doc['table_name']}"

                            # Temporarily index without embedding - will update after RAG index is built
                            table_doc['qualified_name'] = qualified_name
                            table_doc['embedding'] = None  # Will be updated later
                            table_doc['embedding_model'] = None
                            table_doc['indexed_at'] = datetime.now().isoformat()

                            # Don't index yet - we'll do it after embeddings are created
                            # Just store for later
                            if not hasattr(discover_all_schemas, '_pending_elastic_docs'):
                                discover_all_schemas._pending_elastic_docs = []
                            discover_all_schemas._pending_elastic_docs.append(table_doc)

                        except Exception as e:
                            console.print(f"[dim][WARN] Elasticsearch prep failed for {table_name}: {e}[/dim]")

                databases_indexed.append(conn_name)
                progress.update(db_task, completed=len(tables))
                connector.close()

            except Exception as e:
                console.print(f"[red]✗ Failed to chart {conn_name}: {e}[/red]")
                progress.update(db_task, completed=True)

    console.print(f"[green][OK] Charted {total_tables} tables across {len(databases_indexed)} database(s)[/green]")

    # Build unified RAG index (only if tables were found)
    if total_tables == 0:
        console.print(f"[dim]{S.SEARCH} Skipping RAG index (no tables discovered)[/dim]")
        console.print(f"[dim]  Location: sql_connections/samples/[/dim]")
        return

    console.print(f"[bold cyan]{S.SEARCH} Building unified RAG index...[/bold cyan]")

    # Ensure samples directory exists for RAG indexing
    os.makedirs(samples_dir, exist_ok=True)

    rag_config = RagConfig(
        directory=samples_dir,
        recursive=True,
        include=["*.yaml"],
        exclude=[]
    )

    try:
        if USE_DEDICATED_SQL_DUCKDB_INDEX:
            index_stats = rebuild_sql_index(
                samples_dir=samples_dir,
                embed_model=None,
                session_id=session_id,
                trace_id=None,
                parent_id=None,
                cell_name="sql_crawl",
                cascade_id=None,
            )
            rag_id = index_stats["rag_id"]
            embed_model = index_stats["embed_model"]
            embedding_dim = int(index_stats["embedding_dim"])
        else:
            rag_ctx = ensure_rag_index(
                rag_config=rag_config,
                cascade_path=None,
                session_id=session_id
            )
            rag_id = rag_ctx.rag_id
            embed_model = rag_ctx.embed_model
            embedding_dim = int(getattr(rag_ctx, "embedding_dim", 0) or 0)

        # Index to Elasticsearch (optional).
        #
        # Note: RAG vectors are stored in Chroma. Elastic indexing currently runs
        # in text-only mode (no dense_vector) unless we explicitly embed docs here.
        if elastic_enabled and hasattr(discover_all_schemas, '_pending_elastic_docs'):
            console.print("[bold cyan]📦 Indexing to Elasticsearch with embeddings...[/bold cyan]")

            try:
                docs_with_embeddings = []
                for doc in discover_all_schemas._pending_elastic_docs:
                    # Text-only indexing for now (no embeddings).
                    doc['embedding'] = None
                    doc['embedding_model'] = None
                    docs_with_embeddings.append(doc)

                # Bulk index to Elasticsearch
                if docs_with_embeddings:
                    from ..elastic import bulk_index_sql_schemas

                    # Note: Index is already recreated with fresh mapping at the start of discover_all_schemas()
                    # via create_sql_schema_index() call, which handles schema changes like nested MongoDB objects

                    indexed_count = bulk_index_sql_schemas(docs_with_embeddings)
                    console.print(f"[green][OK] Indexed {indexed_count} schemas to Elasticsearch[/green]")

                # Clean up
                del discover_all_schemas._pending_elastic_docs

            except Exception as e:
                console.print(f"[yellow][WARN] Elasticsearch indexing failed: {e}[/yellow]")
                console.print("[dim]  Chroma RAG indexing succeeded - you can still use sql_search[/dim]")

        # Save discovery metadata
        metadata = DiscoveryMetadata(
            last_discovery=datetime.now().isoformat(),
            rag_id=rag_id,
            databases_indexed=databases_indexed,
            table_count=total_tables,
            total_columns=total_columns,
            embed_model=embed_model
        )

        save_discovery_metadata(metadata)

        console.print(f"[bold green][TARGET] SQL schema discovery complete![/bold green]")
        console.print(f"[dim]  RAG ID: {rag_id}[/dim]")
        console.print(f"[dim]  Tables indexed: {total_tables}[/dim]")
        console.print(f"[dim]  Total columns: {total_columns}[/dim]")
        if USE_DEDICATED_SQL_DUCKDB_INDEX:
            console.print(f"[dim]  Backend: dedicated SQL DuckDB ({embedding_dim} dims)[/dim]")
        console.print(f"[dim]  Metadata saved: sql_connections/discovery_metadata.yaml[/dim]")
        console.print()
        console.print("[cyan][TIP] Use sql_search tool in cascades to search schemas[/cyan]")

        # Build Knowledge Graph (Tier 1 - deterministic)
        _run_kg_extraction(samples_dir, session_id)

    except Exception as e:
        console.print(f"[yellow][WARN]  Failed to build RAG index: {e}[/yellow]")
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

        console.print(f"[bold green][OK] Schema discovery completed![/bold green]")
        console.print(f"[dim]  Tables saved: {total_tables}[/dim]")
        console.print(f"[dim]  Location: sql_connections/samples/[/dim]")
        console.print()
        console.print("[yellow][TIP] Note: sql_search tool requires RAG index. Check embedding API configuration.[/yellow]")
        console.print("[dim]     You can still use sql_query tool with qualified table names.[/dim]")

        # Build Knowledge Graph even if RAG failed (Tier 1 is deterministic, no embeddings needed)
        _run_kg_extraction(samples_dir, session_id)
