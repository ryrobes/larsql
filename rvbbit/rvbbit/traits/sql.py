import duckdb
from typing import List, Optional
from .base import simple_eddy

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

    This trait runs the sql_analyze cascade, providing full observability
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
