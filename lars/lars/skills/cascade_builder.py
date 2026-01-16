"""
Cascade Builder Tools for Calliope.

Provides structured cascade construction with validation and visualization support.
These tools enable Calliope to incrementally build cascades through conversation.
"""

import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pathlib import Path

import yaml

from .base import simple_eddy
from .state_tools import get_current_session_id
from ..config import get_config

from rich.console import Console

console = Console()


@simple_eddy
def cascade_write(
    cascade_id: str,
    action: str,
    cell: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    position: Optional[int] = None,
    cell_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build and modify cascades incrementally. Calliope uses this to construct workflows.

    This tool creates cascade YAML files that can be run independently. Each action
    modifies the cascade and returns the current state for visualization.

    Args:
        cascade_id: Unique identifier for the cascade being built
        action: What to do - one of:
            - "create": Initialize a new cascade (use metadata for description, inputs_schema)
            - "add_cell": Add a new cell (provide cell dict, optional position)
            - "update_cell": Modify existing cell (provide cell_name and cell dict)
            - "delete_cell": Remove a cell (provide cell_name)
            - "reorder": Change cell order (provide cell_name and position)
            - "finalize": Validate and mark as ready for use
        cell: Cell definition dict. For hitl cells: {"name": "...", "hitl": "<html>...", "handoffs": [...]}
              For tool cells: {"name": "...", "tool": "sql_data", "inputs": {...}}
              For LLM cells: {"name": "...", "instructions": "...", "skills": [...]}
        metadata: Cascade-level metadata: {"description": "...", "inputs_schema": {...}, "model": "..."}
        position: Where to insert/move cell (0-indexed). None = append.
        cell_name: Name of cell to update/delete/reorder.

    Returns:
        {
            "success": True/False,
            "cascade_id": "...",
            "path": "cascades/calliope/{session}/...",
            "cells": [...],  # List of cell summaries for visualization
            "graph": {       # Node/edge structure for graph rendering
                "nodes": [...],
                "edges": [...]
            },
            "validation": {
                "valid": True/False,
                "errors": [...],
                "warnings": [...]
            },
            "yaml_preview": "..."  # First 50 lines of YAML for display
        }

    Example - Create a new cascade:
        cascade_write(
            cascade_id="feedback_app",
            action="create",
            metadata={
                "description": "Customer feedback review application",
                "inputs_schema": {"feedback_file": "Path to feedback CSV"}
            }
        )

    Example - Add a HITL screen:
        cascade_write(
            cascade_id="feedback_app",
            action="add_cell",
            cell={
                "name": "review_screen",
                "hitl": '''
                    <h2>Review Feedback</h2>
                    <div id="feedback-grid"></div>
                    <script>loadFeedback();</script>
                    <form hx-post="..." hx-ext="json-enc">
                        <button name="response[action]" value="approve">Approve</button>
                    </form>
                ''',
                "handoffs": ["process_approved", "review_screen"]
            }
        )

    Example - Add a data cell:
        cascade_write(
            cascade_id="feedback_app",
            action="add_cell",
            cell={
                "name": "load_feedback",
                "tool": "sql_data",
                "inputs": {
                    "query": "SELECT * FROM read_csv('{{ input.feedback_file }}')"
                }
            },
            position=0  # Insert at beginning
        )
    """
    session_id = get_current_session_id()
    if not session_id:
        return {"success": False, "error": "No session context - cannot determine save location"}

    config = get_config()

    # Cascade storage directory
    cascade_dir = Path(config.cascades_dir) / "calliope" / session_id
    cascade_dir.mkdir(parents=True, exist_ok=True)

    cascade_path = cascade_dir / f"{cascade_id}.yaml"

    try:
        # Load existing cascade or create new
        if action == "create":
            if cascade_path.exists():
                # File already exists - update metadata but preserve cells!
                console.print(f"[yellow]{S.WARN} Cascade already exists - updating metadata only[/yellow]")
                with open(cascade_path, 'r') as f:
                    cascade_data = yaml.safe_load(f)
                # Update metadata but preserve cells
                if metadata:
                    if "description" in metadata:
                        cascade_data["description"] = metadata["description"]
                    if "inputs_schema" in metadata:
                        cascade_data["inputs_schema"] = metadata["inputs_schema"]
                    if "model" in metadata:
                        cascade_data["model"] = metadata["model"]
            else:
                cascade_data = _create_cascade(cascade_id, metadata or {})
        else:
            if not cascade_path.exists():
                return {
                    "success": False,
                    "error": f"Cascade '{cascade_id}' does not exist. Use action='create' first."
                }
            with open(cascade_path, 'r') as f:
                cascade_data = yaml.safe_load(f)

        # Execute action
        if action == "create":
            pass  # Already handled above
        elif action == "add_cell":
            cascade_data = _add_cell(cascade_data, cell, position)
        elif action == "update_cell":
            cascade_data = _update_cell(cascade_data, cell_name, cell)
        elif action == "delete_cell":
            cascade_data = _delete_cell(cascade_data, cell_name)
        elif action == "reorder":
            cascade_data = _reorder_cell(cascade_data, cell_name, position)
        elif action == "finalize":
            cascade_data = _finalize_cascade(cascade_data)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

        # Validate against Pydantic model
        validation = _validate_cascade(cascade_data)

        # Save to disk with explicit fsync to ensure data is written before spawn_cascade reads it
        with open(cascade_path, 'w') as f:
            yaml.dump(cascade_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())

        console.print(f"[dim]  → Wrote {len(cascade_data.get('cells', []))} cells to {cascade_path}[/dim]")

        # Build visualization data
        cells_summary = _build_cells_summary(cascade_data.get("cells", []))
        graph_data = _build_graph_data(cascade_data.get("cells", []))
        yaml_preview = _get_yaml_preview(cascade_path)

        console.print(f"[green]{S.OK} Cascade updated ({action})[/green]")

        return {
            "success": True,
            "cascade_id": cascade_id,
            "path": str(cascade_path),
            "cells": cells_summary,
            "graph": graph_data,
            "validation": validation,
            "yaml_preview": yaml_preview,
            "cell_count": len(cascade_data.get("cells", [])),
        }

    except Exception as e:
        console.print(f"[red]✗ cascade_write failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@simple_eddy
def cascade_read(cascade_id: str, session_id: str | None = None) -> Dict[str, Any]:
    """
    Read an existing cascade and return its structure.

    Use this to:
    - Inspect a cascade built in a previous session
    - Load a cascade for modification
    - Understand the structure of example cascades

    Args:
        cascade_id: The cascade to read (can be just the name or full path)
        session_id: Optional session ID (defaults to current session for Calliope cascades)

    Returns:
        {
            "success": True/False,
            "cascade_id": "...",
            "path": "...",
            "data": {...},  # Full cascade data
            "cells": [...],  # Cell summaries
            "graph": {...},  # For visualization
            "validation": {...},
            "yaml_preview": "..."
        }
    """
    current_session = get_current_session_id()
    session_id = session_id or current_session

    config = get_config()

    # Try different locations
    search_paths = []

    # 1. Calliope directory for current/specified session
    if session_id:
        search_paths.append(Path(config.cascades_dir) / "calliope" / session_id / f"{cascade_id}.yaml")

    # 2. General cascades directory
    search_paths.append(Path(config.cascades_dir) / f"{cascade_id}.yaml")

    # 3. Skills directory
    search_paths.append(Path(config.root_dir) / "skills" / f"{cascade_id}.yaml")

    # 4. Examples directory
    search_paths.append(Path(config.examples_dir) / f"{cascade_id}.yaml")
    search_paths.append(Path(config.examples_dir) / "yaml" / f"{cascade_id}.yaml")

    # 5. If cascade_id is already a path
    if "/" in cascade_id or cascade_id.endswith(".yaml"):
        search_paths.insert(0, Path(cascade_id))
        search_paths.insert(1, Path(config.root_dir) / cascade_id)

    cascade_path = None
    for path in search_paths:
        if path.exists():
            cascade_path = path
            break

    if not cascade_path:
        return {
            "success": False,
            "error": f"Cascade '{cascade_id}' not found. Searched: {[str(p) for p in search_paths[:3]]}..."
        }

    try:
        with open(cascade_path, 'r') as f:
            cascade_data = yaml.safe_load(f)

        cells_summary = _build_cells_summary(cascade_data.get("cells", []))
        graph_data = _build_graph_data(cascade_data.get("cells", []))
        validation = _validate_cascade(cascade_data)
        yaml_preview = _get_yaml_preview(cascade_path)

        return {
            "success": True,
            "cascade_id": cascade_data.get("cascade_id", cascade_id),
            "path": str(cascade_path),
            "data": cascade_data,
            "cells": cells_summary,
            "graph": graph_data,
            "validation": validation,
            "yaml_preview": yaml_preview,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Helper Functions
# =============================================================================

def _create_cascade(cascade_id: str, metadata: dict) -> dict:
    """Initialize a new cascade structure."""
    return {
        "cascade_id": cascade_id,
        "description": metadata.get("description", f"Cascade built by Calliope"),
        "inputs_schema": metadata.get("inputs_schema", {}),
        "model": metadata.get("model"),  # Optional default model
        "cells": [],
        "_calliope_metadata": {
            "created_at": datetime.now().isoformat(),
            "version": 1,
        }
    }


def _add_cell(cascade_data: dict, cell: dict, position: int | None = None) -> dict:
    """Add a cell to the cascade."""
    if not cell:
        raise ValueError("Cell definition required for add_cell action")

    if not cell.get("name"):
        raise ValueError("Cell must have a 'name' field")

    # Check for duplicate names
    existing_names = {c["name"] for c in cascade_data.get("cells", [])}
    if cell["name"] in existing_names:
        raise ValueError(f"Cell with name '{cell['name']}' already exists")

    cells = cascade_data.get("cells", [])

    if position is not None and 0 <= position <= len(cells):
        cells.insert(position, cell)
    else:
        cells.append(cell)

    cascade_data["cells"] = cells
    return cascade_data


def _update_cell(cascade_data: dict, cell_name: str, cell: dict) -> dict:
    """Update an existing cell."""
    if not cell_name:
        raise ValueError("cell_name required for update_cell action")

    cells = cascade_data.get("cells", [])
    for i, c in enumerate(cells):
        if c["name"] == cell_name:
            # Merge updates (keep fields not in update)
            cells[i] = {**c, **cell}
            cascade_data["cells"] = cells
            return cascade_data

    raise ValueError(f"Cell '{cell_name}' not found")


def _delete_cell(cascade_data: dict, cell_name: str) -> dict:
    """Remove a cell from the cascade."""
    if not cell_name:
        raise ValueError("cell_name required for delete_cell action")

    cells = cascade_data.get("cells", [])
    original_len = len(cells)
    cells = [c for c in cells if c["name"] != cell_name]

    if len(cells) == original_len:
        raise ValueError(f"Cell '{cell_name}' not found")

    cascade_data["cells"] = cells
    return cascade_data


def _reorder_cell(cascade_data: dict, cell_name: str, position: int) -> dict:
    """Move a cell to a new position."""
    if not cell_name:
        raise ValueError("cell_name required for reorder action")
    if position is None:
        raise ValueError("position required for reorder action")

    cells = cascade_data.get("cells", [])

    # Find and remove the cell
    cell = None
    for i, c in enumerate(cells):
        if c["name"] == cell_name:
            cell = cells.pop(i)
            break

    if cell is None:
        raise ValueError(f"Cell '{cell_name}' not found")

    # Insert at new position
    position = max(0, min(position, len(cells)))
    cells.insert(position, cell)

    cascade_data["cells"] = cells
    return cascade_data


def _finalize_cascade(cascade_data: dict) -> dict:
    """Mark cascade as finalized after validation."""
    cascade_data["_calliope_metadata"] = cascade_data.get("_calliope_metadata", {})
    cascade_data["_calliope_metadata"]["finalized_at"] = datetime.now().isoformat()
    cascade_data["_calliope_metadata"]["status"] = "ready"
    return cascade_data


def _validate_cascade(cascade_data: dict) -> dict:
    """Validate cascade structure and return errors/warnings."""
    errors = []
    warnings = []

    # Try to validate with Pydantic (soft validation - don't fail)
    try:
        from ..cascade import CascadeConfig
        CascadeConfig(**cascade_data)
    except Exception as e:
        errors.append(f"Schema validation: {str(e)[:200]}")

    # Additional structural warnings
    cells = cascade_data.get("cells", [])

    if not cells:
        warnings.append("Cascade has no cells")

    # Check for unreachable cells (not referenced in any handoff)
    all_handoffs = set()
    for cell in cells:
        handoffs = cell.get("handoffs", [])
        for h in handoffs:
            if isinstance(h, str):
                all_handoffs.add(h)
            elif isinstance(h, dict) and "target" in h:
                all_handoffs.add(h["target"])

    first_cell = cells[0]["name"] if cells else None
    for cell in cells[1:]:  # Skip first cell
        if cell["name"] not in all_handoffs:
            warnings.append(f"Cell '{cell['name']}' is not reachable from any handoff")

    # Check for undefined handoff targets
    cell_names = {c["name"] for c in cells}
    for cell in cells:
        handoffs = cell.get("handoffs", [])
        for h in handoffs:
            target = h if isinstance(h, str) else h.get("target") if isinstance(h, dict) else None
            if target and target not in cell_names:
                errors.append(f"Cell '{cell['name']}' has handoff to undefined cell '{target}'")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def _build_cells_summary(cells: list) -> list:
    """Build cell summaries for visualization."""
    summaries = []
    for cell in cells:
        cell_type = (
            "llm" if cell.get("instructions") else
            "hitl" if cell.get("hitl") else
            "tool" if cell.get("tool") else
            "mapping" if cell.get("for_each_row") else
            "unknown"
        )

        summaries.append({
            "name": cell["name"],
            "type": cell_type,
            "tool": cell.get("tool"),
            "handoffs": cell.get("handoffs", []),
            "has_context": bool(cell.get("context")),
        })

    return summaries


def _build_graph_data(cells: list) -> dict:
    """Build node/edge structure for graph visualization."""
    nodes = []
    edges = []

    for i, cell in enumerate(cells):
        cell_type = (
            "llm" if cell.get("instructions") else
            "hitl" if cell.get("hitl") else
            "tool" if cell.get("tool") else
            "mapping" if cell.get("for_each_row") else
            "unknown"
        )

        nodes.append({
            "id": cell["name"],
            "label": cell["name"],
            "type": cell_type,
            "tool": cell.get("tool"),
            "position": i,
        })

        handoffs = cell.get("handoffs", [])
        for h in handoffs:
            target = h if isinstance(h, str) else h.get("target") if isinstance(h, dict) else None
            if target:
                edges.append({
                    "source": cell["name"],
                    "target": target,
                })

    return {"nodes": nodes, "edges": edges}


def _get_yaml_preview(path: Path, max_lines: int = 50) -> str:
    """Get first N lines of YAML for preview."""
    try:
        with open(path, 'r') as f:
            lines = f.readlines()[:max_lines]
            preview = ''.join(lines)
            if len(lines) == max_lines:
                preview += "\n... (truncated)"
            return preview
    except Exception:
        return ""
