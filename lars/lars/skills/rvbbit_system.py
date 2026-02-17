"""
RVBBIT System skills — workspace overview, viewport, topology, screenshots.

These give Calliope situational awareness. She can see the big picture:
what's on the canvas, how things are wired together, what the user is
looking at, and take snapshots for analysis.
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


def _get(path: str, params: dict = None, timeout: int = 10) -> dict:
    resp = requests.get(_rvbbit_url(path), params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict = None, timeout: int = 15) -> dict:
    resp = requests.post(_rvbbit_url(path), json=data or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


@simple_eddy
def system_overview() -> str:
    """
    Get a comprehensive overview of the current RVBBIT workspace.
    
    Returns:
    - Connected data sources
    - Number of cells on canvas
    - Active cascades
    - Current viewport position
    - Warren (workspace) info
    
    This is your "where am I, what's going on" snapshot. Call this at the
    start of a conversation or when you need to re-orient.
    
    Returns:
        JSON overview of the current workspace state
    """
    from rich.console import Console
    console = Console()
    
    overview = {}
    
    try:
        # Get full state
        try:
            state = _get("/state")
            overview["warren"] = {
                "name": state.get("name", "unknown"),
                "id": state.get("id", "unknown"),
            }
            overview["cell_count"] = len(state.get("cells", {}))
            overview["colony_count"] = len(state.get("cascades", state.get("colonies", {})))
            overview["wire_count"] = len(state.get("wires", {}))
        except Exception:
            overview["state"] = "unavailable"
        
        # Get data connections
        try:
            connections = _get("/schema/connections")
            conn_list = connections if isinstance(connections, list) else connections.get("connections", [])
            overview["data_sources"] = [
                {"name": c.get("name", "?"), "type": c.get("type", "?")} 
                for c in conn_list
            ]
        except Exception:
            overview["data_sources"] = "unavailable"
        
        # Get viewport
        try:
            viewport = _get("/viewport")
            overview["viewport"] = viewport
        except Exception:
            pass
        
        # Get params
        try:
            params = _get("/params")
            if params:
                overview["active_params"] = params
        except Exception:
            pass
        
        console.print(f"[cyan]{S.OK} System overview loaded[/cyan]")
        return json.dumps(overview, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def system_topology() -> str:
    """
    Get the cascade/wire topology of the canvas.
    
    Shows how cells are connected — which cells feed into which,
    what cascades exist, and the data flow graph. Useful for
    understanding complex dashboards.
    
    Returns:
        JSON representation of the canvas topology (nodes and edges)
    """
    try:
        result = _get("/topology")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def system_screenshot(region: Optional[str] = None) -> str:
    """
    Take a screenshot of the current canvas state.
    
    Returns a base64-encoded image of what's visible on the canvas.
    Useful for debugging layout issues or verifying what cells look like.
    
    Args:
        region: Optional region to capture (JSON string: {"x": 0, "y": 0, "w": 800, "h": 600})
    
    Returns:
        JSON with base64 screenshot data
    """
    try:
        payload = {}
        if region:
            try:
                payload = json.loads(region)
            except json.JSONDecodeError:
                pass
        result = _post("/screenshot", payload)
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def system_viewport(x: Optional[float] = None, y: Optional[float] = None, 
                     zoom: Optional[float] = None) -> str:
    """
    Get or set the canvas viewport (camera position and zoom).
    
    Call with no arguments to get the current viewport.
    Call with x/y/zoom to move the camera — useful for directing the
    user's attention to specific cells or areas.
    
    Args:
        x: Camera X position (optional)
        y: Camera Y position (optional)
        zoom: Zoom level (optional, 1.0 = normal)
    
    Returns:
        JSON with current/updated viewport state
    """
    try:
        if x is None and y is None and zoom is None:
            return json.dumps(_get("/viewport"), indent=2)
        
        payload = {}
        if x is not None:
            payload["x"] = x
        if y is not None:
            payload["y"] = y
        if zoom is not None:
            payload["zoom"] = zoom
        
        result = _post("/viewport", payload)
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "RVBBIT not reachable"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@simple_eddy
def system_health() -> str:
    """
    Quick health check — is RVBBIT running and responsive?
    
    Returns:
        JSON with health status
    """
    try:
        result = _get("/health")
        return json.dumps(result, indent=2)
    except requests.exceptions.ConnectionError:
        return json.dumps({"status": "unreachable", "error": "RVBBIT not responding on expected port"})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


# ── Registration ──

register_skill("system_overview", system_overview)
register_skill("system_topology", system_topology)
register_skill("system_screenshot", system_screenshot)
register_skill("system_viewport", system_viewport)
register_skill("system_health", system_health)
