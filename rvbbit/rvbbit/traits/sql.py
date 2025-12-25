import duckdb
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
