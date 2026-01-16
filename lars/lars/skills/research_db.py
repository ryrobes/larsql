"""
Research Database Tools - DuckDB-based persistence for cascade-specific data.

This module provides tools for cascades to store and query structured data
in a dedicated DuckDB database. The database name is declared at the cascade
level via the `research_db` config field, allowing multiple cascades to share
the same database.

Usage in cascade:
    {
        "cascade_id": "market_research",
        "research_db": "market_research",
        "cells": [...]
    }

The LLM just writes SQL - no need to specify database names or paths.
"""
import os
import json
from contextvars import ContextVar
from typing import Optional, Any, List, Dict

from .base import simple_eddy
from ..config import get_config

# ContextVar to track current research database name
current_research_db_context = ContextVar("current_research_db_context", default=None)


def set_current_research_db(db_name: Optional[str]):
    """Set the current research database name for this execution context."""
    return current_research_db_context.set(db_name)


def get_current_research_db() -> Optional[str]:
    """Get the current research database name."""
    return current_research_db_context.get()


def _get_db_path(db_name: str) -> str:
    """Get the full path to a research database file."""
    config = get_config()
    return os.path.join(config.research_db_dir, f"{db_name}.duckdb")


def _get_connection(db_name: str):
    """Get a DuckDB connection, creating the database if needed."""
    import duckdb
    db_path = _get_db_path(db_name)
    return duckdb.connect(db_path)


def _is_select_query(sql: str) -> bool:
    """Check if the SQL is a SELECT query (returns data)."""
    sql_upper = sql.strip().upper()
    return (
        sql_upper.startswith("SELECT") or
        sql_upper.startswith("WITH") or
        sql_upper.startswith("SHOW") or
        sql_upper.startswith("DESCRIBE") or
        sql_upper.startswith("EXPLAIN")
    )


def _get_effective_db_name() -> str:
    """
    Get the effective database name, falling back to cascade_id if not explicitly set.

    This allows cascades to use research_query/research_execute without explicit
    research_db config - they'll get automatic persistence using their cascade_id.
    """
    db_name = get_current_research_db()
    if db_name:
        return db_name

    # Fall back to cascade_id if available
    from .state_tools import get_current_cascade_id
    cascade_id = get_current_cascade_id()
    if cascade_id:
        return cascade_id

    return None


@simple_eddy
def research_query(sql: str) -> str:
    """
    Execute a SELECT query on the research database and return results as JSON.

    Use this for reading data: SELECT, WITH, SHOW, DESCRIBE queries.
    Returns a JSON array of objects representing the query results.

    The database is determined by:
    1. The 'research_db' field in cascade config (if set)
    2. The cascade_id (automatic fallback for implicit persistence)

    Examples:
        research_query("SELECT * FROM programs LIMIT 10")
        research_query("SELECT COUNT(*) as total FROM courses WHERE competitor = 'zollege'")
        research_query("SHOW TABLES")
    """
    db_name = _get_effective_db_name()
    if not db_name:
        return json.dumps({
            "error": "No research database available. Either set 'research_db' in cascade config or ensure cascade context is set."
        })

    try:
        conn = _get_connection(db_name)
        result = conn.execute(sql).fetchall()
        columns = [desc[0] for desc in conn.description] if conn.description else []
        conn.close()

        # Convert to list of dicts
        rows = [dict(zip(columns, row)) for row in result]

        # Handle special types (dates, decimals, etc.)
        def serialize_value(v):
            if v is None:
                return None
            if isinstance(v, (int, float, str, bool)):
                return v
            return str(v)

        serialized_rows = [
            {k: serialize_value(v) for k, v in row.items()}
            for row in rows
        ]

        return json.dumps(serialized_rows, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def research_execute(sql: str) -> str:
    """
    Execute a DDL or DML statement on the research database.

    Use this for:
    - Creating tables: CREATE TABLE ...
    - Inserting data: INSERT INTO ...
    - Updating data: UPDATE ... SET ...
    - Deleting data: DELETE FROM ...
    - Altering schema: ALTER TABLE ...

    Returns a success message with affected row count (if applicable).

    The database is determined by:
    1. The 'research_db' field in cascade config (if set)
    2. The cascade_id (automatic fallback for implicit persistence)

    Examples:
        research_execute("CREATE TABLE IF NOT EXISTS programs (id VARCHAR PRIMARY KEY, name VARCHAR, price DECIMAL)")
        research_execute("INSERT INTO programs VALUES ('p1', 'CNA Training', 1200)")
        research_execute("UPDATE programs SET price = 1300 WHERE id = 'p1'")
    """
    db_name = _get_effective_db_name()
    if not db_name:
        return json.dumps({
            "error": "No research database available. Either set 'research_db' in cascade config or ensure cascade context is set."
        })

    try:
        conn = _get_connection(db_name)

        # Execute the statement
        cursor = conn.execute(sql)

        # Try to get affected rows (not all statements support this)
        affected = -1
        try:
            affected = cursor.rowcount if hasattr(cursor, 'rowcount') else -1
        except:
            pass

        conn.close()

        # Determine statement type for message
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("CREATE"):
            # Try to extract table name
            import re
            match = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\']?(\w+)["\']?', sql, re.IGNORECASE)
            table_name = match.group(1) if match else "table"
            return f"Table '{table_name}' created successfully."
        elif sql_upper.startswith("INSERT"):
            if affected > 0:
                return f"Inserted {affected} row(s)."
            return "Insert executed successfully."
        elif sql_upper.startswith("UPDATE"):
            if affected >= 0:
                return f"Updated {affected} row(s)."
            return "Update executed successfully."
        elif sql_upper.startswith("DELETE"):
            if affected >= 0:
                return f"Deleted {affected} row(s)."
            return "Delete executed successfully."
        elif sql_upper.startswith("DROP"):
            return "Drop executed successfully."
        elif sql_upper.startswith("ALTER"):
            return "Alter executed successfully."
        else:
            return "Statement executed successfully."

    except Exception as e:
        return json.dumps({"error": str(e)})


def research_db_info(db_name: str | None = None) -> dict:
    """
    Get information about a research database (for debugging/admin).
    Not exposed as an LLM tool - used internally.
    """
    if db_name is None:
        db_name = get_current_research_db()

    if not db_name:
        return {"error": "No database specified"}

    db_path = _get_db_path(db_name)

    info = {
        "name": db_name,
        "path": db_path,
        "exists": os.path.exists(db_path),
    }

    if info["exists"]:
        info["size_bytes"] = os.path.getsize(db_path)

        try:
            conn = _get_connection(db_name)
            tables = conn.execute("SHOW TABLES").fetchall()
            info["tables"] = [t[0] for t in tables]
            conn.close()
        except Exception as e:
            info["error"] = str(e)

    return info
