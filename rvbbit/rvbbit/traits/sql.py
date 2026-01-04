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
    columns: Optional[List[str]] = None
) -> dict:
    """
    Analyze SQL query results with an LLM.

    Takes formatted query results and a user's question, returns analysis.
    Used by the ANALYZE SQL command for async data analysis.

    Args:
        prompt: The user's analysis question (e.g., "why were sales low in December?")
        query: The original SQL query that was executed
        data: Formatted query results (markdown table + stats)
        row_count: Number of rows in the result
        columns: List of column names

    Returns:
        dict with 'analysis' key containing the LLM's analysis text
    """
    from ..sql_tools.llm_aggregates import _call_llm

    column_info = ", ".join(columns) if columns else "unknown"

    llm_prompt = f"""You are a data analyst. The user ran this SQL query:

```sql
{query}
```

Results ({row_count} rows, columns: {column_info}):
{data}

User's question: {prompt}

Provide a clear, concise analysis that directly answers the question.
Focus on actionable insights from the data, not just describing what you see.
If the data suggests causes or recommendations, include them."""

    analysis = _call_llm(llm_prompt, max_tokens=2000)

    return {"analysis": analysis}
