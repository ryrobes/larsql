"""
LLM-facing SQL tools for schema search and query execution.
"""

import json
import os
from typing import Optional

from ..config import get_config
from ..rag.store import search_chunks
from ..rag.context import RagContext
from .config import load_discovery_metadata, load_sql_connections
from .connector import DatabaseConnector


def sql_rag_search(
    query: str,
    k: int = 10,
    score_threshold: Optional[float] = 0.3
) -> str:
    """
    Search SQL schema metadata using ClickHouse RAG (pure vector search).

    **Note:** This is the legacy RAG-based approach. For better results with smaller
    payloads, use `sql_search` which uses Elasticsearch hybrid search.

    Finds relevant tables and columns across all configured databases.
    Returns table metadata including column info, distributions, and sample values.

    This tool searches the unified schema index built by `windlass sql chart`.
    If you get an error about missing index, ask the user to run: windlass sql chart

    Example queries:
      - "tables with user information"
      - "sales or revenue data"
      - "bigfoot sightings location data"
      - "customer country information"

    Args:
        query: Natural language description of what to find
        k: Number of results to return (default: 10)
        score_threshold: Minimum similarity score (default: 0.3)

    Returns:
        JSON with matching tables and their metadata including:
        - Full column schemas with types
        - Value distributions for low-cardinality columns
        - Min/max ranges for high-cardinality columns
        - Sample rows from each table (can be large!)
    """
    # Load discovery metadata
    meta = load_discovery_metadata()
    if not meta:
        return json.dumps({
            "error": "No SQL schema index found. Run: windlass sql chart",
            "hint": "The discovery process charts all databases and builds a searchable index."
        })

    # Get RAG context
    cfg = get_config()
    samples_dir = os.path.join(cfg.root_dir, "sql_connections", "samples")

    # Verify RAG index exists in ClickHouse
    from ..db_adapter import get_db
    db = get_db()
    chunk_count = db.query(
        f"SELECT count() as cnt FROM rag_chunks WHERE rag_id = '{meta.rag_id}'"
    )
    if not chunk_count or chunk_count[0]['cnt'] == 0:
        return json.dumps({
            "error": f"RAG index not found in database for rag_id: {meta.rag_id}",
            "hint": "Run: windlass sql chart"
        })

    # Create RagContext (ClickHouse-based, no file paths needed)
    rag_ctx = RagContext(
        rag_id=meta.rag_id,
        directory=samples_dir,
        embed_model=meta.embed_model,
        stats={},
        session_id=None,
        cascade_id=None,
        phase_name=None,
        trace_id=None,
        parent_id=None
    )

    # Search
    results = search_chunks(
        rag_ctx=rag_ctx,
        query=query,
        k=k,
        score_threshold=score_threshold
    )

    if not results:
        return json.dumps({
            "query": query,
            "message": "No matching tables found. Try a broader query or different keywords.",
            "rag_id": meta.rag_id,
            "databases_available": meta.databases_indexed
        })

    # Parse results - each chunk is from a table.json file
    tables = []
    seen_tables = set()  # Deduplicate if multiple chunks from same table

    for result in results:
        # result['source'] is like "csv_files/bigfoot_sightings.json"
        full_path = os.path.join(samples_dir, result['source'])

        # Deduplicate by file path
        if full_path in seen_tables:
            continue
        seen_tables.add(full_path)

        try:
            with open(full_path) as f:
                table_meta = json.load(f)

                # Build qualified table name
                if table_meta['schema'] and table_meta['schema'] != table_meta['database']:
                    qualified_name = f"{table_meta['database']}.{table_meta['schema']}.{table_meta['table_name']}"
                else:
                    qualified_name = f"{table_meta['database']}.{table_meta['table_name']}"

                tables.append({
                    "qualified_name": qualified_name,
                    "database": table_meta['database'],
                    "schema": table_meta['schema'],
                    "table_name": table_meta['table_name'],
                    "row_count": table_meta['row_count'],
                    "columns": table_meta['columns'],
                    "sample_rows": table_meta['sample_rows'][:5],  # First 5 samples
                    "match_score": result['score']
                })
        except Exception as e:
            print(f"Warning: Failed to load {full_path}: {e}")

    return json.dumps({
        "query": query,
        "rag_id": meta.rag_id,
        "total_results": len(tables),
        "tables": tables
    }, indent=2, default=str)


def sql_search(
    query: str,
    k: int = 10,
    min_row_count: Optional[int] = None
) -> str:
    """
    Search SQL schema metadata using Elasticsearch hybrid search.

    **Recommended approach** - Uses hybrid search (vector + BM25 keywords) and returns
    compact, structured results without heavy sample data.

    Finds relevant tables and columns across all configured databases.
    Returns clean table metadata optimized for LLM consumption.

    Example queries:
      - "tables with user information"
      - "sales or revenue data"
      - "bigfoot sightings location data"
      - "customer country information"
      - "find tables with email addresses and login timestamps"

    The query can be verbose - both semantic meaning and keywords are used for matching.

    Args:
        query: Natural language description (can be multi-word, verbose)
        k: Number of results to return (default: 10)
        min_row_count: Optional filter for minimum table size

    Returns:
        JSON with matching tables and their metadata including:
        - Table names and database info
        - Full column schemas with types
        - Row counts
        **Note:** Sample rows are NOT included (use run_sql to query actual data)
    """
    try:
        # Try Elasticsearch first
        from ..elastic import get_elastic_client, hybrid_search_sql_schemas
        from ..rag.indexer import embed_texts

        es = get_elastic_client()
        if not es.ping():
            # Fallback to RAG search
            return sql_rag_search(query, k=k, score_threshold=0.3)

        # Embed the query
        cfg = get_config()
        embed_result = embed_texts(
            texts=[query],
            model=cfg.default_embed_model,
            session_id=None,
            trace_id=None,
            parent_id=None,
            phase_name="sql_search",
            cascade_id=None
        )
        query_embedding = embed_result['embeddings'][0]

        # Hybrid search
        tables = hybrid_search_sql_schemas(
            query=query,
            query_embedding=query_embedding,
            k=k,
            min_row_count=min_row_count
        )

        return json.dumps({
            "query": query,
            "source": "elasticsearch",
            "total_results": len(tables),
            "tables": tables,
            "note": "Results optimized for LLM - sample_rows excluded. Use run_sql to query actual data."
        }, indent=2, default=str)

    except ImportError:
        # Elasticsearch not available - fallback to RAG
        return sql_rag_search(query, k=k, score_threshold=0.3)
    except Exception as e:
        # If Elasticsearch fails, fallback to RAG
        print(f"Elasticsearch search failed, falling back to RAG: {e}")
        return sql_rag_search(query, k=k, score_threshold=0.3)


def run_sql(sql: str, connection: str, limit: Optional[int] = 200) -> str:
    """
    Execute SQL query on a specific database connection.

    Uses DuckDB to connect to the database and execute queries.
    Results are returned as JSON.

    IMPORTANT: Use qualified table names in queries:
      - PostgreSQL/MySQL: connection_name.schema.table
      - SQLite: connection_name.table
      - CSV folders: connection_name.table_name
        Example: SELECT * FROM csv_files.bigfoot_sightings

    Examples:
      - "SELECT * FROM prod_db.public.users LIMIT 10"
      - "SELECT COUNT(*) FROM csv_files.bigfoot_sightings WHERE state = 'California'"
      - "SELECT class, COUNT(*) as count FROM csv_files.bigfoot_sightings GROUP BY class"

    Args:
        sql: SQL query to execute
        connection: Name of the connection to use
        limit: Maximum rows to return (default: 200, prevents huge results)

    Returns:
        JSON with query results, row count, and any errors
    """
    # Load connection config
    connections = load_sql_connections()
    if connection not in connections:
        return json.dumps({
            "error": f"Connection '{connection}' not found",
            "available_connections": list(connections.keys()),
            "hint": "Check sql_connections/*.json files"
        })

    conn_config = connections[connection]

    try:
        # Connect and attach
        connector = DatabaseConnector()
        connector.attach(conn_config)

        # Add LIMIT if not present and limit specified
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
            "columns": list(df.columns),
            "results": results
        }, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": str(e),
            "sql": sql,
            "connection": connection,
            "hint": "Check table names are qualified correctly (e.g., csv_files.bigfoot_sightings)"
        })


def list_sql_connections() -> str:
    """
    List all configured SQL database connections.

    Shows which databases are available for querying and when they were last indexed.

    Returns:
        JSON with connection names, types, and last discovery info
    """
    meta = load_discovery_metadata()
    connections = load_sql_connections()

    conn_list = []
    for name, config in connections.items():
        conn_list.append({
            "name": name,
            "type": config.type,
            "enabled": config.enabled,
            "indexed": name in (meta.databases_indexed if meta else [])
        })

    return json.dumps({
        "connections": conn_list,
        "last_discovery": meta.last_discovery if meta else None,
        "rag_id": meta.rag_id if meta else None,
        "total_tables_indexed": meta.table_count if meta else 0,
        "hint": "Run 'windlass sql chart' to index/re-index databases"
    }, indent=2)
