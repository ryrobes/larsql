"""
RVBBIT Canvas skills — create, read, update, delete, move cells on the canvas.

These are Calliope's hands. She uses these to build and manipulate
the visual workspace in response to user requests.

All calls hit the RVBBIT embedded server (default port 9876).
"""

import os
import json
import requests
from typing import Optional, List
from .base import simple_eddy
from ..skill_registry import register_skill
from ..console_style import S


def _rvbbit_url(path: str) -> str:
    port = int(os.environ.get("RVBBIT_PORT", "9876"))
    return f"http://127.0.0.1:{port}{path}"


def _get(path: str, params: dict = None, timeout: int = 10) -> dict:
    """GET request to RVBBIT embedded server."""
    resp = requests.get(_rvbbit_url(path), params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict = None, timeout: int = 15) -> dict:
    """POST request to RVBBIT embedded server."""
    resp = requests.post(_rvbbit_url(path), json=data or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _delete(path: str, timeout: int = 10) -> dict:
    """DELETE request to RVBBIT embedded server."""
    resp = requests.delete(_rvbbit_url(path), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ── Canvas read operations ──

@simple_eddy
def canvas_list_cells(colony: Optional[str] = None, state: Optional[str] = None) -> str:
    """
    List all cells currently on the RVBBIT canvas.
    
    Returns a summary of each cell: id, type, SQL query (if any), position, 
    and current state. Use this to understand what's on the canvas before
    making changes.
    
    Args:
        colony: Filter by colony/cascade ID (optional)
        state: Filter by cell state like "ready", "running", "error" (optional)
    
    Returns:
        JSON array of cell summaries
    """
    from rich.console import Console
    console = Console()
    
    try:
        result = _get("/state/cells")
        cells = result if isinstance(result, list) else result.get("cells", [])
        
        # Apply filters
        if colony:
            cells = [c for c in cells if c.get("colonyId") == colony]
        if state:
            cells = [c for c in cells if c.get("state") == state]
        
        # Summarize for context efficiency
        summaries = []
        for c in cells:
            summary = {
                "id": c.get("id"),
                "type": c.get("type", "unknown"),
                "label": c.get("label", ""),
                "sql": (c.get("sql") or "")[:200],  # Truncate long SQL
                "state": c.get("state", "unknown"),
                "position": {
                    "x": c.get("x", 0),
                    "y": c.get("y", 0),
                    "w": c.get("w", 300),
                    "h": c.get("h", 200),
                },
                "colonyId": c.get("colonyId"),
            }
            summaries.append(summary)
        
        console.print(f"[cyan]{S.OK} Found {len(summaries)} cells on canvas[/cyan]")
        return json.dumps(summaries, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def canvas_get_cell(cell_id: str) -> str:
    """
    Get detailed information about a specific cell.
    
    Returns full cell data including SQL, configuration, output data,
    position, and state. Use this to inspect a cell before updating it.
    
    Args:
        cell_id: The cell's unique ID
    
    Returns:
        JSON object with full cell details
    """
    try:
        result = _get(f"/cells/{cell_id}/detail")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def canvas_search_cells(query: Optional[str] = None, cell_type: Optional[str] = None, 
                         colony: Optional[str] = None) -> str:
    """
    Search for cells on the canvas by query text, type, or colony.
    
    Args:
        query: Text to search for in cell SQL, labels, or data
        cell_type: Filter by cell type (e.g., "sql", "text", "param")
        colony: Filter by colony/cascade ID
    
    Returns:
        JSON array of matching cells
    """
    try:
        params = {}
        if query:
            params["q"] = query
        if cell_type:
            params["type"] = cell_type
        if colony:
            params["colony"] = colony
        result = _get("/cells/search", params=params)
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Canvas write operations ──

@simple_eddy
def canvas_create_cell(
    sql: str,
    x: float = 100.0,
    y: float = 100.0,
    w: float = 400.0,
    h: float = 300.0,
    label: Optional[str] = None,
    colony_id: Optional[str] = None,
) -> str:
    """
    Create a new cell on the RVBBIT canvas.
    
    The cell will execute its SQL through LARS (supporting semantic operators,
    federated queries across all connected data sources, etc.).
    
    Args:
        sql: The SQL query for this cell. Can use LARS operators like MEANS, 
             SIMILAR_TO, ask_data(), etc. Can reference any connected database.
        x: X position on canvas (default 100)
        y: Y position on canvas (default 100)
        w: Width in pixels (default 400)
        h: Height in pixels (default 300)
        label: Optional display label for the cell
        colony_id: Optional colony/cascade to group this cell into
    
    Returns:
        JSON with the created cell's ID and details
    """
    from rich.console import Console
    console = Console()
    
    try:
        payload = {
            "sql": sql,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
        }
        if label:
            payload["label"] = label
        if colony_id:
            payload["colonyId"] = colony_id
            
        result = _post("/cells", payload)
        cell_id = result.get("id", "unknown")
        console.print(f"[green]{S.OK} Created cell {cell_id}[/green]")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def canvas_update_cell(
    cell_id: str,
    sql: Optional[str] = None,
    label: Optional[str] = None,
    properties: Optional[str] = None,
) -> str:
    """
    Update an existing cell's SQL, label, or other properties.
    
    Args:
        cell_id: The cell to update
        sql: New SQL query (optional)
        label: New display label (optional)
        properties: JSON string of additional properties to set (optional)
    
    Returns:
        JSON confirmation of the update
    """
    from rich.console import Console
    console = Console()
    
    try:
        payload = {}
        if sql is not None:
            payload["sql"] = sql
        if label is not None:
            payload["label"] = label
        if properties:
            try:
                extra = json.loads(properties)
                payload.update(extra)
            except json.JSONDecodeError:
                pass
        
        result = _post(f"/cells/{cell_id}/update", payload)
        console.print(f"[green]{S.OK} Updated cell {cell_id}[/green]")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def canvas_move_cell(
    cell_id: str,
    x: Optional[float] = None,
    y: Optional[float] = None,
    w: Optional[float] = None,
    h: Optional[float] = None,
) -> str:
    """
    Move and/or resize a cell on the canvas.
    
    Args:
        cell_id: The cell to move
        x: New X position (optional)
        y: New Y position (optional)
        w: New width (optional)
        h: New height (optional)
    
    Returns:
        JSON confirmation
    """
    try:
        payload = {}
        if x is not None:
            payload["x"] = x
        if y is not None:
            payload["y"] = y
        if w is not None:
            payload["w"] = w
        if h is not None:
            payload["h"] = h
        
        result = _post(f"/cells/{cell_id}/move", payload)
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def canvas_delete_cell(cell_id: str) -> str:
    """
    Delete a cell from the canvas.
    
    Args:
        cell_id: The cell to delete
    
    Returns:
        JSON confirmation
    """
    from rich.console import Console
    console = Console()
    
    try:
        result = _delete(f"/cells/{cell_id}")
        console.print(f"[yellow]{S.WARN} Deleted cell {cell_id}[/yellow]")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def canvas_refresh_cell(cell_id: str) -> str:
    """
    Re-execute a cell's SQL query and refresh its data.
    
    Args:
        cell_id: The cell to refresh
    
    Returns:
        JSON confirmation
    """
    try:
        result = _post(f"/cells/{cell_id}/refresh")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def canvas_get_cell_data(cell_id: str) -> str:
    """
    Read the current output data from a cell.
    
    Returns the cell's query results — useful for inspecting what data
    a cell is showing, or building on top of existing cells.
    
    Args:
        cell_id: The cell whose data to read
    
    Returns:
        JSON with the cell's output data (rows, columns, etc.)
    """
    try:
        result = _get(f"/cells/{cell_id}/data")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Registration ──

register_skill("canvas_list_cells", canvas_list_cells)
register_skill("canvas_get_cell", canvas_get_cell)
register_skill("canvas_search_cells", canvas_search_cells)
register_skill("canvas_create_cell", canvas_create_cell)
register_skill("canvas_update_cell", canvas_update_cell)
register_skill("canvas_move_cell", canvas_move_cell)
register_skill("canvas_delete_cell", canvas_delete_cell)
register_skill("canvas_refresh_cell", canvas_refresh_cell)
register_skill("canvas_get_cell_data", canvas_get_cell_data)
