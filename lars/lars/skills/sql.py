import duckdb
import json
import math
from typing import List, Optional
from .base import simple_eddy


def _sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization.

    Converts NaN/Infinity to None, which becomes null in JSON.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    return obj


@simple_eddy
def run_sql(query: str, db_path: str = ":memory:") -> str:
    """
    Executes a SQL query using DuckDB.
    """
    con = duckdb.connect(db_path)
    try:
        # stricter: allow read-only if possible for safety?
        # User prompt implies generic SQL execution.
        df = con.execute(query).df()
        return df.to_json(orient="records")
    except Exception as e:
        raise e
    finally:
        con.close()


@simple_eddy
def smart_sql_run(query: str, limit: Optional[int] = 200) -> str:
    """
    Execute SQL queries with automatic database connection handling.

    This tool automatically detects and attaches referenced databases from
    your configured sql_connections. Use qualified table names like:
    - csv_files.bigfoot_sightings (CSV folder connection)
    - postgres_db.public.users (PostgreSQL connection)
    - research_dbs.market_data (DuckDB folder connection)

    Args:
        query: SQL query to execute. Use qualified table names (db.table or db.schema.table)
        limit: Maximum rows to return (default: 200, prevents huge results)

    Returns:
        JSON with query results:
        {
            "sql": "executed query",
            "row_count": 123,
            "columns": ["col1", "col2"],
            "results": [{"col1": val1, ...}, ...],
            "rows": [[val1, val2, ...], ...]
        }

    Examples:
        smart_sql_run("SELECT * FROM csv_files.bigfoot_sightings LIMIT 10")
        smart_sql_run("SELECT COUNT(*) FROM postgres_db.public.users")
    """
    try:
        # Import lazy attach and connection config
        from ..sql_tools.config import load_sql_connections
        from ..sql_tools.lazy_attach import LazyAttachManager
        from ..sql_tools.udf import register_lars_udf

        # Create in-memory DuckDB connection
        con = duckdb.connect(':memory:')

        try:
            # Load configured SQL connections
            connections = load_sql_connections()

            # Initialize lazy attach manager
            lazy_attach = LazyAttachManager(con, connections)

            # Auto-attach databases referenced in the query
            lazy_attach.ensure_for_query(query, aggressive=True)

            # Register LARS UDF for semantic SQL operators (optional, non-fatal if fails)
            try:
                register_lars_udf(con, config={})
            except Exception:
                pass

            # Add LIMIT if not present and limit specified
            sql_with_limit = query.strip()
            if sql_with_limit.endswith(';'):
                sql_with_limit = sql_with_limit[:-1]
            if limit and "LIMIT" not in sql_with_limit.upper():
                sql_with_limit += f" LIMIT {limit}"

            # Execute query
            df = con.execute(sql_with_limit).df()

            # Convert results to JSON-serializable format
            results = _sanitize_for_json(df.to_dict('records'))
            rows = [list(row.values()) for row in results]

            return json.dumps({
                "sql": sql_with_limit,
                "row_count": len(results),
                "columns": list(df.columns),
                "results": results,
                "rows": rows
            }, indent=2, default=str)

        finally:
            con.close()

    except Exception as e:
        return json.dumps({
            "error": str(e),
            "sql": query,
            "hint": "Check table names are qualified correctly (e.g., csv_files.bigfoot_sightings)",
            "columns": [],
            "rows": [],
            "results": [],
            "row_count": 0
        })


@simple_eddy
def sql_analyze(
    prompt: str,
    query: str,
    data: str,
    row_count: int = 0,
    columns: Optional[List[str]] = None,
    _session_id: str | None = None,
    _caller_id: str | None = None,
) -> dict:
    """
    Analyze SQL query results with an LLM.

    Takes formatted query results and a user's question, returns analysis.
    Used by the ANALYZE SQL command for async data analysis.

    This skill runs the sql_analyze cascade, providing full observability
    and proper cost tracking through unified_logs.

    Args:
        prompt: The user's analysis question (e.g., "why were sales low in December?")
        query: The original SQL query that was executed
        data: Formatted query results (markdown table + stats)
        row_count: Number of rows in the result
        columns: List of column names
        _session_id: Session ID for cascade execution (internal)
        _caller_id: Caller ID for cost tracking (internal)

    Returns:
        dict with 'analysis' key containing the LLM's analysis text
    """
    import json
    import os
    from ..runner import run_cascade
    from ..config import get_config
    from ..caller_context import get_caller_id

    # Build column info string
    column_info = ", ".join(columns) if columns else "unknown"

    # Get caller_id from context if not provided
    if not _caller_id:
        _caller_id = get_caller_id()

    # Resolve cascade path
    config = get_config()
    cascade_path = os.path.join(config.root_dir, 'cascades', 'sql_analyze.yaml')

    # Fallback to package-relative path
    if not os.path.exists(cascade_path):
        cascade_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cascades', 'sql_analyze.yaml')

    # Run the cascade
    result = run_cascade(
        cascade_path,
        input_data={
            "prompt": prompt,
            "query": query,
            "data": data,
            "row_count": row_count,
            "columns": column_info,
        },
        session_id=_session_id,
        caller_id=_caller_id,
    )

    # Extract analysis from cascade result
    # The cascade output_schema specifies {"analysis": "..."} format
    state = result.get("state", {})
    lineage = result.get("lineage", [])

    # Try to get analysis from state first
    if "analysis" in state:
        return {"analysis": state["analysis"]}

    # Try to get from last cell output
    if lineage:
        last_output = lineage[-1].get("output", {})
        if isinstance(last_output, dict) and "analysis" in last_output:
            return {"analysis": last_output["analysis"]}
        if isinstance(last_output, str):
            return {"analysis": last_output}

    # Fallback to full result
    return {"analysis": json.dumps(result.get("outputs", {}))}
