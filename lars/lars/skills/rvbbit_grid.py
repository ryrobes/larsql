"""
RVBBIT Atom Grid tools for Calliope.

Provides tools for reading, planning, and manipulating the atom grid.
These replace the old canvas_* tools for the new grid-based UI.
"""

import json
import urllib.request
import urllib.error
from typing import Optional
from .base import simple_eddy
from ..skill_registry import register_skill


RVBBIT_PORT = 9876


def _rvbbit_url(path: str) -> str:
    return f"http://127.0.0.1:{RVBBIT_PORT}/{path.lstrip('/')}"


def _get(path: str, timeout: int = 10) -> dict:
    try:
        req = urllib.request.Request(_rvbbit_url(path))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, data: dict = None, timeout: int = 15) -> dict:
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            _rvbbit_url(path),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def _delete(path: str, timeout: int = 10) -> dict:
    try:
        req = urllib.request.Request(_rvbbit_url(path), method="DELETE")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


# ── Grid Awareness ───────────────────────────────────────────


@simple_eddy
def grid_current() -> str:
    """
    Get the current grid state: name, columns, all atoms with their
    intent, position, size, lifecycle, and display type.

    Use this to understand what's already on the grid before making changes.

    Returns:
        JSON string with grid name, id, columns, atomCount, and atoms array.
    """
    result = _get("grid/current")
    return json.dumps(result, indent=2)


@simple_eddy
def grid_get_atom(atom_id: str) -> str:
    """
    Get detailed info about a specific atom, including its resolved SQL,
    dimensions, and display type.

    Args:
        atom_id: UUID of the atom to inspect.

    Returns:
        JSON string with atom details.
    """
    result = _get(f"grid/atoms/{atom_id}")
    return json.dumps(result, indent=2)


# ── Grid Planning (Calliope's main tool) ─────────────────────


@simple_eddy
def grid_plan_atoms(
    atoms: list,
    grid_name: Optional[str] = None,
    auto_execute: bool = True,
) -> str:
    """
    Plan and create multiple atoms on the grid at once.
    This is your primary tool for building dashboards and explorations.

    Each atom needs:
    - intent: Natural language description of what this atom should show.
      Write it as if you're briefing an analyst. Be specific about the
      data, dimensions, groupings, and desired visualization.
    - col: Column position (0-indexed)
    - row: Row position (0-indexed)
    - colSpan: Width in grid cells (default 1). Use 2 for charts, 1 for KPIs.
    - rowSpan: Height in grid cells (default 1). Use 2 for detailed charts/tables.

    If grid_name is set, a new sub-grid is created first and atoms are
    added inside it. The user will see the new grid appear and populate.

    The atoms will be resolved by worker agents who will:
    1. Discover the relevant schema
    2. Generate and verify SQL
    3. Pick the best display type (chart, table, map, number, etc.)

    You do NOT need to write SQL — just describe what you want clearly.

    Args:
        atoms: List of dicts, each with {intent, col, row, colSpan?, rowSpan?}
        grid_name: Optional name for a new sub-grid to contain these atoms.
        auto_execute: Whether to immediately resolve atoms (default True).

    Returns:
        JSON with created atom IDs and grid info.

    Example:
        grid_plan_atoms(atoms=[
            {"intent": "Total number of bigfoot sightings as a big number", "col": 0, "row": 0, "colSpan": 1, "rowSpan": 1},
            {"intent": "Bar chart of top 15 US states by sighting count", "col": 1, "row": 0, "colSpan": 2, "rowSpan": 2},
            {"intent": "Monthly trend of sightings over time as a line chart", "col": 3, "row": 0, "colSpan": 2, "rowSpan": 2},
            {"intent": "Map of sighting locations colored by classification type", "col": 0, "row": 2, "colSpan": 3, "rowSpan": 2},
            {"intent": "Recent sightings table showing date, state, county, and description", "col": 3, "row": 2, "colSpan": 2, "rowSpan": 2},
        ], grid_name="Bigfoot Analysis")
    """
    payload = {
        "atoms": atoms,
        "autoExecute": auto_execute,
    }
    if grid_name:
        payload["gridName"] = grid_name
    
    result = _post("grid/atoms/plan", payload)
    return json.dumps(result, indent=2)


# ── Individual Atom Operations ───────────────────────────────


@simple_eddy
def grid_add_atom(
    intent: str,
    col: int = 0,
    row: int = 0,
    col_span: int = 1,
    row_span: int = 1,
) -> str:
    """
    Add a single atom to the current grid.

    Args:
        intent: Natural language description of what this atom should show.
        col: Column position (0-indexed).
        row: Row position (0-indexed).
        col_span: Width in grid cells.
        row_span: Height in grid cells.

    Returns:
        JSON with the created atom ID.
    """
    result = _post("grid/atoms/add", {
        "intent": intent,
        "col": col,
        "row": row,
        "colSpan": col_span,
        "rowSpan": row_span,
    })
    return json.dumps(result, indent=2)


@simple_eddy
def grid_update_atom(
    atom_id: str,
    intent: Optional[str] = None,
    col: Optional[int] = None,
    row: Optional[int] = None,
    col_span: Optional[int] = None,
    row_span: Optional[int] = None,
) -> str:
    """
    Update an existing atom's intent, position, or size.

    Args:
        atom_id: UUID of the atom to update.
        intent: New intent text (triggers re-resolution).
        col: New column position.
        row: New row position.
        col_span: New width.
        row_span: New height.

    Returns:
        JSON confirmation.
    """
    payload = {}
    if intent is not None:
        payload["intent"] = intent
    if col is not None:
        payload["col"] = col
    if row is not None:
        payload["row"] = row
    if col_span is not None:
        payload["colSpan"] = col_span
    if row_span is not None:
        payload["rowSpan"] = row_span
    
    result = _post(f"grid/atoms/{atom_id}/update", payload)
    return json.dumps(result, indent=2)


@simple_eddy
def grid_remove_atom(atom_id: str) -> str:
    """
    Remove an atom from the current grid.

    Args:
        atom_id: UUID of the atom to remove.

    Returns:
        JSON confirmation.
    """
    result = _delete(f"grid/atoms/{atom_id}")
    return json.dumps(result, indent=2)


# ── Grid Operations ──────────────────────────────────────────


@simple_eddy
def grid_execute() -> str:
    """
    Trigger resolution of all pending (drafting/stale) atoms on the current grid.
    Call this after adding atoms with auto_execute=False, or to re-resolve stale atoms.

    Returns:
        JSON with count of pending and total atoms.
    """
    result = _post("grid/execute")
    return json.dumps(result, indent=2)


@simple_eddy
def grid_create_subgrid(name: str) -> str:
    """
    Create a new sub-grid and drill into it.
    The current grid gets a grid-ref atom pointing to the new grid.

    Args:
        name: Name for the new sub-grid.

    Returns:
        JSON with new grid info.
    """
    result = _post("grid/create", {"name": name})
    return json.dumps(result, indent=2)


@simple_eddy
def grid_drill_up() -> str:
    """
    Drill up to the parent grid.
    If already at the meta (Home) grid, this is a no-op.

    Returns:
        JSON with the parent grid info.
    """
    result = _post("grid/drill-up")
    return json.dumps(result, indent=2)


@simple_eddy
def grid_atom_screenshot(atom_id: str, save_path: Optional[str] = None) -> str:
    """
    Get a screenshot of a rendered atom.

    Returns the path to the saved PNG file. If the atom hasn't been rendered
    yet or the grid isn't loaded, returns an error.

    Use this to visually verify what an atom looks like after resolution.

    Args:
        atom_id: UUID of the atom to screenshot
        save_path: Optional path to save the PNG. If not given, returns the
                   default path at ~/.rvbbit/atom-thumbnails/{atom_id}.png
    """
    import os

    # Check if screenshot already exists on disk (captured by the UI)
    default_path = os.path.expanduser(f"~/.rvbbit/atom-thumbnails/{atom_id}.png")
    if os.path.exists(default_path):
        if save_path:
            import shutil
            shutil.copy2(default_path, save_path)
            return json.dumps({"path": save_path, "source": "disk"})
        return json.dumps({"path": default_path, "source": "disk"})

    # Try fetching from the API (triggers capture if grid is loaded)
    try:
        url = _rvbbit_url(f"grid/atoms/{atom_id}/screenshot")
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.headers.get("Content-Type", "").startswith("image/"):
                png_data = resp.read()
                out_path = save_path or default_path
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(png_data)
                return json.dumps({"path": out_path, "source": "api", "size": len(png_data)})
            else:
                return json.dumps({"error": "No screenshot available", "response": resp.read().decode()[:200]})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Registration ─────────────────────────────────────────────

register_skill("grid_current", grid_current)
register_skill("grid_get_atom", grid_get_atom)
register_skill("grid_plan_atoms", grid_plan_atoms)
register_skill("grid_add_atom", grid_add_atom)
register_skill("grid_update_atom", grid_update_atom)
register_skill("grid_remove_atom", grid_remove_atom)
register_skill("grid_execute", grid_execute)
register_skill("grid_create_subgrid", grid_create_subgrid)
register_skill("grid_drill_up", grid_drill_up)
register_skill("grid_atom_screenshot", grid_atom_screenshot)
