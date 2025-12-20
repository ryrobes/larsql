"""
Data-focused tools for SQL notebooks / data cascades.

These tools support the "notebook" pattern where phases produce DataFrames
that can be referenced by downstream phases via temp tables.

Supports multi-modal outputs:
- DataFrames (tables)
- Images (matplotlib, PIL, OpenCV)
- Charts (Plotly, Altair)
- Markdown text
"""

import json
import os
import io
import base64
import pandas as pd
from typing import Optional, Dict, Any, List
from datetime import datetime

from .base import simple_eddy
from ..sql_tools.session_db import get_session_db
from ..config import get_config


def _get_session_duckdb(session_id: str):
    """Get or create session-scoped DuckDB for temp tables."""
    if not session_id:
        return None
    return get_session_db(session_id)


def _serialize_for_json(obj):
    """Convert non-JSON-serializable types to serializable equivalents."""
    import numpy as np

    if isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_json(v) for v in obj]
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif isinstance(obj, (np.integer, np.floating)):
        return obj.item()  # Convert numpy types to Python types
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif hasattr(obj, 'isoformat'):  # datetime-like objects
        return obj.isoformat()
    else:
        # Check for matplotlib Figure that slipped through
        type_name = type(obj).__name__
        type_module = getattr(type(obj), '__module__', '')
        if type_name == 'Figure' and 'matplotlib' in type_module:
            return f"<matplotlib.Figure object - not serialized>"
        return obj


def _get_image_dir():
    """Get the directory for storing generated images."""
    config = get_config()
    image_dir = config.image_dir
    os.makedirs(image_dir, exist_ok=True)
    return image_dir


def _save_matplotlib_figure(fig, session_id: str, phase_name: str) -> Dict[str, Any]:
    """Save a matplotlib figure to file and return metadata.

    Returns standard image protocol format for consistency with other tools:
    {"content": "description", "images": ["/path/to/image.png"], ...}

    Images are saved in IMAGE_DIR/{session_id}/{phase_name}_{timestamp}.png
    to match the API endpoint structure.
    """
    base_image_dir = _get_image_dir()
    session_dir = os.path.join(base_image_dir, session_id)
    os.makedirs(session_dir, exist_ok=True)

    filename = f"{phase_name}_{datetime.now().strftime('%H%M%S')}.png"
    filepath = os.path.join(session_dir, filename)

    # Save figure
    fig.savefig(filepath, dpi=150, bbox_inches='tight', facecolor='#0a0a0a', edgecolor='none')

    # Close the figure to free memory
    import matplotlib.pyplot as plt
    plt.close(fig)

    # Return standard image protocol format
    # API URL format: /api/images/{session_id}/{filename}
    return {
        "type": "image",
        "content": f"Generated matplotlib figure: {phase_name}",
        "images": [filepath],
        "format": "png",
        "path": filepath,
        "filename": filename,
        "session_id": session_id,
        "api_url": f"/api/images/{session_id}/{filename}",
        "_route": "success"
    }


def _save_pil_image(img, session_id: str, phase_name: str) -> Dict[str, Any]:
    """Save a PIL Image to file and return metadata.

    Returns standard image protocol format for consistency with other tools:
    {"content": "description", "images": ["/path/to/image.png"], ...}

    Images are saved in IMAGE_DIR/{session_id}/{phase_name}_{timestamp}.png
    to match the API endpoint structure.
    """
    base_image_dir = _get_image_dir()
    session_dir = os.path.join(base_image_dir, session_id)
    os.makedirs(session_dir, exist_ok=True)

    filename = f"{phase_name}_{datetime.now().strftime('%H%M%S')}.png"
    filepath = os.path.join(session_dir, filename)

    # Save image
    img.save(filepath)

    # Return standard image protocol format
    # API URL format: /api/images/{session_id}/{filename}
    return {
        "type": "image",
        "content": f"Generated PIL image: {phase_name} ({img.width}x{img.height})",
        "images": [filepath],
        "format": "png",
        "path": filepath,
        "filename": filename,
        "session_id": session_id,
        "api_url": f"/api/images/{session_id}/{filename}",
        "width": img.width,
        "height": img.height,
        "_route": "success"
    }


def _convert_plotly_figure(fig, phase_name: str = "chart") -> Dict[str, Any]:
    """Convert a Plotly figure to JSON for frontend rendering.

    Returns a consistent format with content field for system compatibility.
    """
    # Get the figure as JSON
    fig_json = fig.to_json()
    fig_dict = json.loads(fig_json)

    return {
        "type": "plotly",
        "content": f"Generated Plotly chart: {phase_name}",
        "data": fig_dict.get("data", []),
        "layout": fig_dict.get("layout", {}),
        "_route": "success"
    }


def _is_matplotlib_figure(obj) -> bool:
    """Check if object is a matplotlib Figure."""
    try:
        import matplotlib.figure
        if isinstance(obj, matplotlib.figure.Figure):
            return True
    except ImportError:
        pass

    # Fallback: check type name for cases where import paths differ
    type_name = type(obj).__name__
    type_module = getattr(type(obj), '__module__', '')
    if type_name == 'Figure' and 'matplotlib' in type_module:
        return True

    return False


def _is_pil_image(obj) -> bool:
    """Check if object is a PIL Image."""
    try:
        from PIL import Image
        return isinstance(obj, Image.Image)
    except ImportError:
        return False


def _is_plotly_figure(obj) -> bool:
    """Check if object is a Plotly figure."""
    try:
        import plotly.graph_objects as go
        if isinstance(obj, go.Figure):
            return True
        # Also check for plotly express figures
        if hasattr(obj, 'to_json') and 'plotly' in str(type(obj).__module__):
            return True
        return False
    except ImportError:
        return False


def _is_numpy_array(obj) -> bool:
    """Check if object is a numpy array (potential image)."""
    try:
        import numpy as np
        return isinstance(obj, np.ndarray)
    except ImportError:
        return False


def _run_sql_with_connection(sql: str, connection: str, limit: int = 10000) -> Dict[str, Any]:
    """Execute SQL via the existing connector infrastructure."""
    from ..sql_tools.tools import run_sql as tools_run_sql
    result_json = tools_run_sql(sql, connection, limit)
    return json.loads(result_json)


@simple_eddy
def sql_data(
    query: str,
    connection: str = None,
    limit: int = 10000,
    materialize: bool = True,
    _phase_name: str = None,
    _session_id: str = None
) -> Dict[str, Any]:
    """
    Execute SQL query and return results as DataFrame.

    Optionally materializes result as a temp table named '_<phase_name>'
    for downstream SQL phases to reference directly.

    Args:
        query: SQL query to execute (Jinja2 already rendered by deterministic executor)
        connection: Database connection name. If None, uses session DuckDB only.
        limit: Maximum rows to return (default 10000)
        materialize: If True, create temp table for downstream references
        _phase_name: Injected by runner - used for temp table naming
        _session_id: Injected by runner - used for session DuckDB

    Returns:
        {
            "dataframe": pd.DataFrame,
            "rows": List[Dict],  # For JSON serialization
            "columns": List[str],
            "row_count": int,
            "_route": "success" | "error"
        }

    Example cascade usage:
        phases:
          - name: "customers"
            tool: "sql_data"
            inputs:
              connection: "prod_db"
              query: |
                SELECT * FROM users WHERE created_at > '{{ state.start_date }}'

          - name: "orders"
            tool: "sql_data"
            inputs:
              query: |
                SELECT o.* FROM orders o
                JOIN _customers c ON o.user_id = c.id  -- Reference temp table!
    """
    try:
        # Get session DuckDB for temp table operations
        session_db = _get_session_duckdb(_session_id)

        # If we have a connection, use the standard run_sql
        if connection:
            result = _run_sql_with_connection(query, connection, limit)

            if "error" in result and result["error"]:
                return {
                    "_route": "error",
                    "error": result["error"]
                }

            # Convert to DataFrame
            df = pd.DataFrame(result.get("results", []))
        else:
            # Query directly against session DuckDB (for temp table queries)
            if not session_db:
                return {
                    "_route": "error",
                    "error": "No connection specified and no session DuckDB available"
                }
            df = session_db.execute(query).fetchdf()
            if limit:
                df = df.head(limit)

        # Materialize as temp table for downstream phases
        if materialize and _phase_name and session_db:
            table_name = f"_{_phase_name}"
            # Register DataFrame and create table
            session_db.register("_temp_df", df)
            session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
            session_db.unregister("_temp_df")

        # Note: We don't include 'dataframe' in return as it's not JSON-serializable
        # Downstream phases access data via temp tables or by reconstructing from 'rows'
        return {
            "rows": df.to_dict('records'),
            "columns": list(df.columns),
            "row_count": len(df),
            "_route": "success"
        }

    except Exception as e:
        return {
            "_route": "error",
            "error": str(e)
        }


class DataNamespace:
    """
    Namespace object that provides access to prior phase DataFrames.

    Usage in python_data code:
        df = data.raw_customers      # Get DataFrame from prior phase
        df = data['raw_customers']   # Alternative dict-style access
    """

    def __init__(self, outputs: Dict[str, Any], session_db=None):
        self._outputs = outputs
        self._session_db = session_db
        self._cache = {}

    def __getattr__(self, name: str) -> pd.DataFrame:
        if name.startswith('_'):
            raise AttributeError(name)
        return self._get_dataframe(name)

    def __getitem__(self, name: str) -> pd.DataFrame:
        return self._get_dataframe(name)

    def _get_dataframe(self, name: str) -> pd.DataFrame:
        # Check cache first
        if name in self._cache:
            return self._cache[name]

        # Try to get from outputs
        output = self._outputs.get(name)

        if output is None:
            # Try loading from temp table if session_db available
            if self._session_db:
                try:
                    df = self._session_db.execute(f"SELECT * FROM _{name}").fetchdf()
                    self._cache[name] = df
                    return df
                except Exception:
                    pass
            raise AttributeError(f"No data found for phase '{name}'")

        # Extract DataFrame from various output formats
        if isinstance(output, pd.DataFrame):
            df = output
        elif isinstance(output, dict):
            if 'dataframe' in output and isinstance(output['dataframe'], pd.DataFrame):
                df = output['dataframe']
            elif 'rows' in output:
                df = pd.DataFrame(output['rows'])
            elif 'result' in output and isinstance(output['result'], pd.DataFrame):
                df = output['result']
            elif 'results' in output:
                # Handle output from run_sql which uses 'results' key
                df = pd.DataFrame(output['results'])
            else:
                # Assume dict is the data itself
                df = pd.DataFrame([output]) if not isinstance(output, list) else pd.DataFrame(output)
        elif isinstance(output, list):
            df = pd.DataFrame(output)
        else:
            raise TypeError(f"Cannot convert output of phase '{name}' to DataFrame")

        self._cache[name] = df
        return df

    def list_available(self) -> List[str]:
        """List all available phase names."""
        return list(self._outputs.keys())


@simple_eddy
def python_data(
    code: str,
    _outputs: Dict[str, Any] = None,
    _state: Dict[str, Any] = None,
    _input: Dict[str, Any] = None,
    _phase_name: str = None,
    _session_id: str = None
) -> Dict[str, Any]:
    """
    Execute inline Python code with access to prior phase DataFrames.

    The code environment includes:
        - data.<phase_name>: DataFrame from prior sql_data/python_data phases
        - data['phase_name']: Alternative dict-style access
        - state: Current cascade state dict (read-only recommended)
        - input: Original cascade input dict
        - pd: pandas module
        - np: numpy module
        - json: json module

    The code MUST set a 'result' variable as its output.
    If result is a DataFrame, it will be materialized as a temp table.

    Args:
        code: Python code to execute
        _outputs: Injected by runner - all prior phase outputs
        _state: Injected by runner - current cascade state
        _input: Injected by runner - original cascade input
        _phase_name: Injected by runner - current phase name
        _session_id: Injected by runner - session ID for temp tables

    Returns:
        {
            "result": <the result value>,
            "dataframe": pd.DataFrame (if result is DataFrame),
            "rows": List[Dict] (if result is DataFrame),
            "type": "dataframe" | "dict" | "list" | "scalar",
            "_route": "success" | "error"
        }

    Example cascade usage:
        phases:
          - name: "transform"
            tool: "python_data"
            inputs:
              code: |
                df = data.raw_customers
                df['tier'] = df['spend'].apply(lambda x: 'gold' if x > 1000 else 'silver')
                result = df
    """
    import numpy as np
    import json as json_module

    try:
        # Get session DuckDB
        session_db = _get_session_duckdb(_session_id)

        # Build data namespace
        data = DataNamespace(_outputs or {}, session_db)

        # Build execution environment with common libraries
        exec_globals = {
            'data': data,
            'state': _state or {},
            'input': _input or {},
            'pd': pd,
            'np': np,
            'json': json_module,
            # Common utilities
            'print': print,  # Allow debugging
        }

        # Note: Visualization libraries (matplotlib, plotly, PIL) are NOT pre-imported.
        # Each cell should import what it needs, just like in Jupyter.
        # Only data access (data.*), pandas (pd), numpy (np), and json are pre-loaded.
        exec_locals = {}

        # Execute the code
        exec(code, exec_globals, exec_locals)

        # Extract result
        if 'result' not in exec_locals:
            return {
                "_route": "error",
                "error": "Code must set a 'result' variable. Example: result = df"
            }

        result = exec_locals['result']

        # Determine result type and format response

        # === Multi-modal outputs ===

        # Matplotlib figure
        if _is_matplotlib_figure(result):
            return _save_matplotlib_figure(result, _session_id or "unknown", _phase_name or "cell")

        # PIL Image
        if _is_pil_image(result):
            return _save_pil_image(result, _session_id or "unknown", _phase_name or "cell")

        # Plotly figure
        if _is_plotly_figure(result):
            return _convert_plotly_figure(result, _phase_name or "chart")

        # Numpy array (treat as image if it looks like one)
        if _is_numpy_array(result):
            import numpy as np
            # Check if it looks like an image (2D or 3D array with reasonable dimensions)
            if len(result.shape) in [2, 3] and result.shape[0] > 1 and result.shape[1] > 1:
                if result.shape[0] < 10000 and result.shape[1] < 10000:  # Sanity check
                    try:
                        from PIL import Image
                        # Convert numpy array to PIL Image
                        if len(result.shape) == 2:
                            # Grayscale
                            if result.dtype != np.uint8:
                                result = ((result - result.min()) / (result.max() - result.min()) * 255).astype(np.uint8)
                            img = Image.fromarray(result, mode='L')
                        else:
                            # RGB or RGBA
                            if result.dtype != np.uint8:
                                result = ((result - result.min()) / (result.max() - result.min()) * 255).astype(np.uint8)
                            mode = 'RGBA' if result.shape[2] == 4 else 'RGB'
                            img = Image.fromarray(result, mode=mode)
                        return _save_pil_image(img, _session_id or "unknown", _phase_name or "cell")
                    except Exception:
                        pass  # Fall through to treat as data

        # === Standard data outputs ===

        # DataFrame
        if isinstance(result, pd.DataFrame):
            # Materialize as temp table
            if _phase_name and session_db:
                table_name = f"_{_phase_name}"
                session_db.register("_temp_df", result)
                session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
                session_db.unregister("_temp_df")

            # Note: We don't include 'dataframe' or 'result' as they're not JSON-serializable
            # Downstream phases access data via temp tables or by reconstructing from 'rows'
            # Serialize rows to convert Timestamps and numpy types to JSON-serializable values
            rows = _serialize_for_json(result.to_dict('records'))
            return {
                "rows": rows,
                "columns": list(result.columns),
                "row_count": len(result),
                "type": "dataframe",
                "_route": "success"
            }

        elif isinstance(result, dict):
            return {
                "result": _serialize_for_json(result),
                "type": "dict",
                "_route": "success"
            }

        elif isinstance(result, list):
            return {
                "result": _serialize_for_json(result),
                "type": "list",
                "_route": "success"
            }

        else:
            return {
                "result": _serialize_for_json(result),
                "type": "scalar",
                "_route": "success"
            }

    except Exception as e:
        import traceback
        return {
            "_route": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }
