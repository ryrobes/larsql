"""
RVBBIT Schema discovery skills — explore connected data sources.

These are Calliope's eyes. She uses these to understand what data
the user has, what tables exist, what columns mean, and preview
actual data before building anything.

All calls hit the RVBBIT embedded server (default port 9876),
which proxies schema operations to LARS.
"""

import os
import json
import requests
from typing import Optional
from .base import simple_eddy
from ..skill_registry import register_skill
from ..console_style import S


def _rvbbit_url(path: str) -> str:
    port = int(os.environ.get("RVBBIT_PORT", "9876"))
    return f"http://127.0.0.1:{port}{path}"


def _get(path: str, params: dict = None, timeout: int = 15) -> dict:
    resp = requests.get(_rvbbit_url(path), params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict = None, timeout: int = 15) -> dict:
    resp = requests.post(_rvbbit_url(path), json=data or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


@simple_eddy
def schema_list_connections() -> str:
    """
    List all configured data source connections.
    
    Returns the names and types of all databases/sources connected to LARS.
    This is the starting point for data exploration — see what's available
    before diving into tables.
    
    Returns:
        JSON array of connection objects with name, type, and status
    """
    from rich.console import Console
    console = Console()
    
    try:
        result = _get("/schema/connections")
        connections = result if isinstance(result, list) else result.get("connections", [])
        console.print(f"[cyan]{S.OK} Found {len(connections)} data connections[/cyan]")
        return json.dumps(connections, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def schema_list_tables(connection: Optional[str] = None) -> str:
    """
    List tables available in a data connection.
    
    If no connection is specified, lists tables from all connections.
    Returns table names, row counts (if available), and which connection
    each belongs to.
    
    Args:
        connection: Name of the data connection to explore (optional, lists all if omitted)
    
    Returns:
        JSON array of table objects
    """
    from rich.console import Console
    console = Console()
    
    try:
        params = {}
        if connection:
            params["connection"] = connection
        result = _get("/schema/tables", params=params)
        tables = result if isinstance(result, list) else result.get("tables", [])
        console.print(f"[cyan]{S.OK} Found {len(tables)} tables[/cyan]")
        return json.dumps(tables, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def schema_list_columns(connection: str, table: str) -> str:
    """
    List columns in a specific table.
    
    Returns column names, data types, nullability, and sample values.
    Essential for understanding what data is available before writing queries.
    
    Args:
        connection: Name of the data connection
        table: Name of the table to inspect
    
    Returns:
        JSON array of column objects with name, type, nullable, etc.
    """
    from rich.console import Console
    console = Console()
    
    try:
        params = {"connection": connection, "table": table}
        result = _get("/schema/columns", params=params)
        columns = result if isinstance(result, list) else result.get("columns", [])
        console.print(f"[cyan]{S.OK} {connection}.{table}: {len(columns)} columns[/cyan]")
        return json.dumps(columns, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def schema_preview_table(connection: str, table: str, limit: int = 5) -> str:
    """
    Preview sample rows from a table.
    
    Returns actual data rows — useful for understanding what values look like,
    data quality, common patterns, etc. Keep limit small for exploration.
    
    Args:
        connection: Name of the data connection
        table: Name of the table to preview
        limit: Number of sample rows (default 5, max recommended 20)
    
    Returns:
        JSON with columns and sample rows
    """
    from rich.console import Console
    console = Console()
    
    try:
        params = {"connection": connection, "table": table, "limit": str(limit)}
        result = _get("/schema/preview", params=params)
        rows = result.get("rows", result) if isinstance(result, dict) else result
        row_count = len(rows) if isinstance(rows, list) else "?"
        console.print(f"[cyan]{S.OK} Preview: {connection}.{table} ({row_count} rows)[/cyan]")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def schema_search(query: str) -> str:
    """
    Semantic search across all schemas — find tables and columns by meaning.
    
    Uses LARS's semantic search to find relevant tables/columns based on
    natural language descriptions. Great for discovery: "Where is revenue data?"
    or "Which table has customer emails?"
    
    Args:
        query: Natural language description of what you're looking for
    
    Returns:
        JSON with matched tables, columns, and relevance scores
    """
    from rich.console import Console
    console = Console()
    
    try:
        result = _post("/schema/search", {"query": query})
        console.print(f"[cyan]{S.OK} Schema search: '{query}'[/cyan]")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Registration ──

register_skill("schema_list_connections", schema_list_connections)
register_skill("schema_list_tables", schema_list_tables)
register_skill("schema_list_columns", schema_list_columns)
register_skill("schema_preview_table", schema_preview_table)
register_skill("schema_search", schema_search)
