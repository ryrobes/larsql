"""
LLM-facing SQL tools for schema search and query execution.
"""

import json
import math
import os
from typing import Optional


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization.

    Converts NaN/Infinity to None, which becomes null in JSON.
    This is necessary because pandas converts SQL NULLs to float('nan')
    for numeric columns, and json.dumps outputs literal NaN which is
    invalid JSON that JavaScript's JSON.parse() cannot handle.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj

from ..config import get_config
from ..rag.store import search_chunks


def _compact_tables(tables: list) -> list:
    """
    Strip heavy metadata from table schemas to reduce output size.

    Removes value_distribution arrays from column metadata which can be
    massive (thousands of entries per column). Keeps essential info:
    - Table name, database, schema
    - Row count
    - Column names and types
    - Basic stats (min, max, distinct_count)

    This prevents issues with:
    - JDBC clients failing on huge VARCHAR values
    - PostgreSQL wire protocol message limits
    - JSON parsing overhead in downstream tools
    """
    compacted = []
    for table in tables:
        compact_table = {
            "qualified_name": table.get("qualified_name"),
            "database": table.get("database"),
            "schema": table.get("schema"),
            "table_name": table.get("table_name"),
            "description": table.get("description"),
            "row_count": table.get("row_count"),
            "match_score": table.get("match_score"),
        }

        # Compact columns - keep type info but strip value_distribution
        if "columns" in table:
            compact_columns = []
            for col in table.get("columns", []):
                compact_col = {
                    "name": col.get("name"),
                    "type": col.get("type"),
                    "nullable": col.get("nullable"),
                }
                # Keep basic metadata but exclude value_distribution
                if "metadata" in col and col["metadata"]:
                    compact_col["metadata"] = {
                        "distinct_count": col["metadata"].get("distinct_count"),
                        "min": col["metadata"].get("min"),
                        "max": col["metadata"].get("max"),
                        # Explicitly exclude value_distribution
                    }
                compact_columns.append(compact_col)
            compact_table["columns"] = compact_columns

        compacted.append(compact_table)

    return compacted
from ..rag.context import RagContext
from .config import load_discovery_metadata, load_sql_connections
from .connector import DatabaseConnector


def _pivot_tables_to_rows(tables: list, query: str, source: str, schema_brief: Optional[str] = None) -> list:
    """
    Convert a list of table metadata dicts into a flat row-per-table format.

    Instead of returning one row with all tables in a nested array, this returns
    one row per table with flattened fields. The columns array is pre-serialized
    as JSON to avoid STRUCT[] type issues with PostgreSQL wire protocol.

    Output structure per row:
    - query: The search query
    - source: Data source (elasticsearch, rag, etc.)
    - qualified_name: Full table reference
    - database, schema, table_name: Table identifiers
    - description: Table description
    - row_count: Number of rows
    - match_score: Search relevance score
    - columns_json: Pre-serialized JSON of column metadata
    - schema_brief: Optional LLM-generated summary (only on first row if present)
    - relevance, reasoning, key_columns_json, join_hint: Smart search enrichments (if present)
    """
    rows = []
    compacted = _compact_tables(tables)

    # Also need to preserve smart search fields that aren't in _compact_tables
    # Build a lookup by qualified_name
    smart_fields_by_name = {
        t.get("qualified_name"): {
            "relevance": t.get("relevance"),
            "reasoning": t.get("reasoning"),
            "key_columns": t.get("key_columns"),
            "join_hint": t.get("join_hint"),
        }
        for t in tables
    }

    for i, table in enumerate(compacted):
        qname = table.get("qualified_name")
        smart_fields = smart_fields_by_name.get(qname, {})

        row = {
            "query": query,
            "source": source,
            "qualified_name": qname,
            "database": table.get("database"),
            "schema": table.get("schema"),
            "table_name": table.get("table_name"),
            "description": table.get("description", ""),
            "row_count": table.get("row_count"),
            "match_score": table.get("match_score"),
            "columns_json": json.dumps(table.get("columns", [])),
        }

        # Add smart search enrichments if present
        if smart_fields.get("relevance"):
            row["relevance"] = smart_fields["relevance"]
        if smart_fields.get("reasoning"):
            row["reasoning"] = smart_fields["reasoning"]
        if smart_fields.get("key_columns"):
            row["key_columns_json"] = json.dumps(smart_fields["key_columns"])
        if smart_fields.get("join_hint"):
            row["join_hint"] = smart_fields["join_hint"]

        # Include schema_brief only on first row to avoid repetition
        if i == 0 and schema_brief:
            row["schema_brief"] = schema_brief

        rows.append(row)

    return rows


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

    This tool searches the unified schema index built by `lars sql chart`.
    If you get an error about missing index, ask the user to run: lars sql chart

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
        JSON array with one row per matching table:
        - query: Search query used
        - source: "rag"
        - qualified_name, database, schema, table_name: Table identifiers
        - description, row_count, match_score: Table metadata
        - columns_json: JSON string of column metadata
    """
    # Load discovery metadata
    meta = load_discovery_metadata()
    if not meta:
        return json.dumps({
            "error": "No SQL schema index found. Run: lars sql chart",
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
            "hint": "Run: lars sql chart"
        })

    # Create RagContext (ClickHouse-based, no file paths needed)
    rag_ctx = RagContext(
        rag_id=meta.rag_id,
        directory=samples_dir,
        embed_model=meta.embed_model,
        stats={},
        session_id=None,
        cascade_id=None,
        cell_name=None,
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

    # Return one row per table for easier SQL consumption
    rows = _pivot_tables_to_rows(tables, query, source="rag")
    return json.dumps(rows, default=str)


def sql_search(
    query: str,
    k: int = 10,
    min_row_count: Optional[int] = None,
    smart: Optional[bool] = None,
    task_context: Optional[str] = None
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
        smart: Enable LLM-powered smart filtering (default: from LARS_SMART_SEARCH env)
        task_context: Optional context about what user is trying to do

    Returns:
        JSON array with one row per matching table:
        - query: Search query used
        - source: "elasticsearch" or "elasticsearch+smart"
        - qualified_name, database, schema, table_name: Table identifiers
        - description, row_count, match_score: Table metadata
        - columns_json: JSON string of column metadata
        - schema_brief (first row only, if smart=True): Compact summary for LLM consumption
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
            cell_name="sql_search",
            cascade_id=None
        )
        query_embedding = embed_result['embeddings'][0]

        # Hybrid search - fetch more if smart filtering will be applied
        from ..rag.smart_search import is_smart_search_enabled

        use_smart = smart if smart is not None else is_smart_search_enabled()
        fetch_k = k * 3 if use_smart else k

        tables = hybrid_search_sql_schemas(
            query=query,
            query_embedding=query_embedding,
            k=fetch_k,
            min_row_count=min_row_count
        )

        # Apply smart filtering if enabled
        if use_smart and len(tables) > k:
            from ..rag.smart_search import smart_schema_search

            smart_result = smart_schema_search(
                query=query,
                raw_results=tables,
                k=k,
                task_context=task_context
            )

            smart_tables = smart_result.get("tables", tables[:k])
            schema_brief = smart_result.get("schema_brief")

            # Merge smart search results with original table metadata
            # Smart search returns different structure (relevance, reasoning, key_columns)
            # We need to map back to original tables and enrich with smart fields
            tables_by_name = {t.get("qualified_name"): t for t in tables}
            merged_tables = []
            for smart_table in smart_tables:
                qname = smart_table.get("qualified_name")
                original = tables_by_name.get(qname, {})
                # Start with original table metadata
                merged = {**original}
                # Add smart search enrichments
                if smart_table.get("relevance"):
                    merged["relevance"] = smart_table.get("relevance")
                if smart_table.get("reasoning"):
                    merged["reasoning"] = smart_table.get("reasoning")
                if smart_table.get("key_columns"):
                    merged["key_columns"] = smart_table.get("key_columns")
                if smart_table.get("join_hint"):
                    merged["join_hint"] = smart_table.get("join_hint")
                merged_tables.append(merged)

            # Return one row per table for easier SQL consumption
            rows = _pivot_tables_to_rows(merged_tables, query, source="elasticsearch+smart", schema_brief=schema_brief)
            return json.dumps(rows, default=str)

        # Return one row per table for easier SQL consumption
        rows = _pivot_tables_to_rows(tables[:k], query, source="elasticsearch")
        return json.dumps(rows, default=str)

    except ImportError:
        # Elasticsearch not available - fallback to RAG
        return sql_rag_search(query, k=k, score_threshold=0.3)
    except Exception as e:
        # If Elasticsearch fails, fallback to RAG
        print(f"Elasticsearch search failed, falling back to RAG: {e}")
        return sql_rag_search(query, k=k, score_threshold=0.3)


def smart_sql_search(
    query: str,
    k: int = 5,
    task_context: Optional[str] = None
) -> str:
    """
    Smart SQL schema search with LLM-powered filtering and synthesis.

    This is the recommended search for exploration and query building.
    It fetches more results than needed, then uses LLM to:
    1. Filter out irrelevant tables (keyword matches that aren't useful)
    2. Highlight only the columns that matter
    3. Generate a compact "schema_brief" for efficient context

    The schema_brief is ideal for LLM consumption - instead of passing
    all column metadata, it provides a 2-3 sentence summary like:
    "For finding user emails, use users.email (1M rows). Join to
    user_sessions for login timestamps."

    Args:
        query: Natural language description of what to find
        k: Number of tables to return (default: 5)
        task_context: Optional context about what you're trying to do
            (e.g., "write a query to find inactive users")

    Returns:
        JSON array with one row per matching table:
        - query, source, qualified_name, database, schema, table_name
        - description, row_count, match_score, columns_json
        - schema_brief (first row only): Compact LLM-ready summary

    Example:
        smart_sql_search("user email addresses", task_context="find inactive users")
    """
    return sql_search(
        query=query,
        k=k,
        smart=True,
        task_context=task_context
    )


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
      - DuckDB folders (research_dbs): db_name.table_name
        Example: SELECT * FROM market_research.zollege_schools
        (Each .duckdb file is attached directly as a database)

    Examples:
      - "SELECT * FROM prod_db.public.users LIMIT 10"
      - "SELECT COUNT(*) FROM csv_files.bigfoot_sightings WHERE state = 'California'"
      - "SELECT * FROM market_research.zollege_schools LIMIT 10"

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
            "hint": "Check sql_connections/*.yaml files"
        })

    conn_config = connections[connection]

    try:
        # For duckdb_folder (research_dbs), use in-memory (no cache needed - .duckdb is already fast)
        # For csv_folder, use cache (materializes CSVs to avoid slow re-imports)
        use_cache = conn_config.type != "duckdb_folder"

        connector = DatabaseConnector(use_cache=use_cache)
        connector.attach(conn_config)

        # Add LIMIT if not present and limit specified
        sql_with_limit = sql.strip()
        if limit and "LIMIT" not in sql_with_limit.upper():
            sql_with_limit += f" LIMIT {limit}"

        # Execute
        df = connector.fetch_df(sql_with_limit)

        # Convert to both formats for compatibility
        # - results: array of objects (legacy format for LLM tools)
        # - rows: array of arrays (compact format for HTML/HTMX rendering)
        results = sanitize_for_json(df.to_dict('records'))
        rows = [list(row.values()) for row in results]

        connector.close()

        return json.dumps({
            "sql": sql_with_limit,
            "connection": connection,
            "row_count": len(results),
            "columns": list(df.columns),
            "results": results,  # Array of objects: [{"col1": val1, ...}, ...]
            "rows": rows         # Array of arrays: [[val1, val2, ...], ...]
        }, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": str(e),
            "sql": sql,
            "connection": connection,
            "hint": "Check table names are qualified correctly (e.g., csv_files.bigfoot_sightings)",
            "columns": [],      # Safe defaults for HTML rendering
            "rows": [],
            "results": [],
            "row_count": 0
        })


def validate_sql(sql: str | None = None, connection: Optional[str] = None, *, content: str | None = None) -> str:
    """
    Validate SQL syntax and optionally check schema references.

    Uses DuckDB's EXPLAIN to parse and validate the query without executing it.
    If connection is provided, validates against that database's schema (tables exist, etc.).

    This tool is designed to be used as:
    1. A ward validator in cascades that generate SQL
    2. A loop_until validator: `loop_until: validate_sql`
    3. Direct function call: `validate_sql("SELECT * FROM users")`

    Returns the standard validator format: {"valid": bool, "reason": str}

    Args:
        sql: SQL query to validate (positional)
        connection: Optional connection name for schema validation.
                   If provided, validates that referenced tables/columns exist.
                   If omitted, auto-detects from SQL (e.g., csv_files.table → csv_files)
        content: Alternative to sql (used by loop_until validator interface)

    Returns:
        JSON with validation result: {"valid": bool, "reason": str}

    Examples:
        validate_sql("SELECT * FROM users")  # Syntax check only
        validate_sql("SELECT * FROM csv_files.data", "csv_files")  # With schema validation
        loop_until: validate_sql  # In cascade YAML
    """
    import duckdb
    import re

    # Support both direct call (sql=) and validator interface (content=)
    sql = sql or content
    if not sql:
        return json.dumps({
            "valid": False,
            "reason": "No SQL provided"
        })

    sql = sql.strip()

    # Remove markdown code blocks if LLM wrapped the SQL
    if sql.startswith("```sql"):
        sql = sql[6:]
    if sql.startswith("```"):
        sql = sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    sql = sql.strip()

    # Remove trailing semicolon for EXPLAIN (DuckDB doesn't like it)
    if sql.endswith(';'):
        sql = sql[:-1]

    # Basic sanity check
    if not sql:
        return json.dumps({
            "valid": False,
            "reason": "Empty SQL query"
        })

    # Check it starts with SELECT or WITH (safety)
    sql_upper = sql.upper().strip()
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return json.dumps({
            "valid": False,
            "reason": f"Only SELECT/WITH queries allowed, got: {sql[:30]}..."
        })

    # Auto-detect connection from SQL if not provided (e.g., csv_files.table → csv_files)
    if not connection:
        match = re.search(r'(?:FROM|JOIN)\s+["\']?(\w+)["\']?\s*\.', sql, re.IGNORECASE)
        if match:
            detected = match.group(1)
            # Verify it's a valid connection
            connections = load_sql_connections()
            if detected in connections:
                connection = detected

    try:
        if connection:
            # Validate with schema context - attach the database
            connections = load_sql_connections()
            if connection not in connections:
                return json.dumps({
                    "valid": False,
                    "reason": f"Connection '{connection}' not found. Available: {list(connections.keys())}"
                })

            conn_config = connections[connection]
            connector = DatabaseConnector(use_cache=False)
            connector.attach(conn_config)

            # Run EXPLAIN to validate syntax + schema
            connector.conn.execute(f"EXPLAIN {sql}")
            connector.close()
        else:
            # Syntax-only validation (no schema context)
            conn = duckdb.connect(':memory:')
            conn.execute(f"EXPLAIN {sql}")
            conn.close()

        return json.dumps({
            "valid": True,
            "reason": "SQL is valid"
        })

    except Exception as e:
        error_msg = str(e)

        # Categorize the error for better feedback
        if "Parser Error" in error_msg or "syntax error" in error_msg.lower():
            return json.dumps({
                "valid": False,
                "reason": f"Syntax error: {error_msg}"
            })
        elif "Catalog Error" in error_msg:
            # Table/column doesn't exist
            return json.dumps({
                "valid": False,
                "reason": f"Schema error (table/column not found): {error_msg}"
            })
        elif "Binder Error" in error_msg:
            # Column ambiguity, type mismatch, etc.
            return json.dumps({
                "valid": False,
                "reason": f"Binding error: {error_msg}"
            })
        else:
            return json.dumps({
                "valid": False,
                "reason": f"Validation failed: {error_msg}"
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
        "hint": "Run 'lars sql chart' to index/re-index databases"
    }, indent=2)
