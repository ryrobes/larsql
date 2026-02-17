"""
RVBBIT Query skill — run SQL through the canvas.

This is distinct from smart_sql_run (which uses LARS's DuckDB directly).
This routes through RVBBIT's embedded server, which means:
1. It goes through the full LARS pgwire stack (semantic operators work)
2. Results can feed into canvas cells
3. The query is visible in RVBBIT's query history

Use this for "show me" queries that the user might want on the canvas.
Use smart_sql_run for quick analytical queries that don't need visualization.
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


@simple_eddy
def canvas_query(sql: str, create_cell: bool = False, label: Optional[str] = None) -> str:
    """
    Execute a SQL query through RVBBIT.
    
    The query goes through the full LARS stack — all semantic operators
    (MEANS, SIMILAR_TO, TOPICS(), SUMMARIZE(), ask_data()) are available,
    as well as federated access to all connected data sources.
    
    Args:
        sql: SQL query to execute. Can use qualified table names (db.table)
             and LARS semantic operators.
        create_cell: If True, also create a cell on the canvas showing these results
        label: Optional label for the cell (only used if create_cell=True)
    
    Returns:
        JSON with query results (columns, rows, row_count)
    """
    from rich.console import Console
    console = Console()
    
    try:
        port = int(os.environ.get("RVBBIT_PORT", "9876"))
        url = f"http://127.0.0.1:{port}/query"
        
        payload = {"sql": sql}
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        
        row_count = result.get("row_count", len(result.get("rows", [])))
        console.print(f"[green]{S.OK} Query returned {row_count} rows[/green]")
        
        # Optionally create a cell showing these results
        if create_cell:
            cell_payload = {"sql": sql}
            if label:
                cell_payload["label"] = label
            cell_resp = requests.post(
                f"http://127.0.0.1:{port}/cells",
                json=cell_payload,
                timeout=15,
            )
            if cell_resp.status_code == 200:
                cell_data = cell_resp.json()
                result["cell_created"] = cell_data.get("id", True)
                console.print(f"[green]{S.OK} Created cell: {result['cell_created']}[/green]")
        
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Registration ──

register_skill("canvas_query", canvas_query)
