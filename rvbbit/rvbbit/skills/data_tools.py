"""
Data-focused tools for SQL notebooks / data cascades.

These tools support the "notebook" pattern where cells produce DataFrames
that can be referenced by downstream cells via temp tables.

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


def _save_matplotlib_figure(fig, session_id: str, cell_name: str) -> Dict[str, Any]:
    """Save a matplotlib figure to file and return metadata.

    Returns standard image protocol format for consistency with other tools:
    {"content": "description", "images": ["/path/to/image.png"], ...}

    Images are saved in IMAGE_DIR/{session_id}/{cell_name}_{timestamp}.png
    to match the API endpoint structure.
    """
    base_image_dir = _get_image_dir()
    session_dir = os.path.join(base_image_dir, session_id)
    os.makedirs(session_dir, exist_ok=True)

    filename = f"{cell_name}_{datetime.now().strftime('%H%M%S')}.png"
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
        "content": f"Generated matplotlib figure: {cell_name}",
        "images": [filepath],
        "format": "png",
        "path": filepath,
        "filename": filename,
        "session_id": session_id,
        "api_url": f"/api/images/{session_id}/{filename}",
        "_route": "success"
    }


def _save_pil_image(img, session_id: str, cell_name: str) -> Dict[str, Any]:
    """Save a PIL Image to file and return metadata.

    Returns standard image protocol format for consistency with other tools:
    {"content": "description", "images": ["/path/to/image.png"], ...}

    Images are saved in IMAGE_DIR/{session_id}/{cell_name}_{timestamp}.png
    to match the API endpoint structure.
    """
    base_image_dir = _get_image_dir()
    session_dir = os.path.join(base_image_dir, session_id)
    os.makedirs(session_dir, exist_ok=True)

    filename = f"{cell_name}_{datetime.now().strftime('%H%M%S')}.png"
    filepath = os.path.join(session_dir, filename)

    # Save image
    img.save(filepath)

    # Return standard image protocol format
    # API URL format: /api/images/{session_id}/{filename}
    return {
        "type": "image",
        "content": f"Generated PIL image: {cell_name} ({img.width}x{img.height})",
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


def _convert_plotly_figure(fig, cell_name: str = "chart") -> Dict[str, Any]:
    """Convert a Plotly figure to JSON for frontend rendering.

    Returns a consistent format with content field for system compatibility.
    """
    # Get the figure as JSON
    fig_json = fig.to_json()
    fig_dict = json.loads(fig_json)

    return {
        "type": "plotly",
        "content": f"Generated Plotly chart: {cell_name}",
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
    connection: str | None = None,
    limit: int = 10000,
    materialize: bool = True,
    _cell_name: str | None = None,
    _session_id: str | None = None,
    _caller_id: str | None = None,
    _cascade_id: str | None = None
) -> Dict[str, Any]:
    """
    Execute SQL query and return results as DataFrame.

    Optionally materializes result as a temp table named '_<cell_name>'
    for downstream SQL cells to reference directly.

    Args:
        query: SQL query to execute (Jinja2 already rendered by deterministic executor)
        connection: Database connection name. If None, uses session DuckDB only.
        limit: Maximum rows to return (default 10000)
        materialize: If True, create temp table for downstream references
        _cell_name: Injected by runner - used for temp table naming
        _session_id: Injected by runner - used for session DuckDB
        _caller_id: Injected by runner - caller ID for SQL Trail correlation
        _cascade_id: Injected by runner - cascade ID for context

    Returns:
        {
            "dataframe": pd.DataFrame,
            "rows": List[Dict],  # For JSON serialization
            "columns": List[str],
            "row_count": int,
            "_route": "success" | "error"
        }

    Example cascade usage:
        cells:
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

        # Register rvbbit_udf if session_db is available
        if session_db:
            from ..sql_tools.udf import register_rvbbit_udf
            try:
                register_rvbbit_udf(session_db, config={})
            except Exception as e:
                # Non-fatal if UDF registration fails
                import logging
                logging.getLogger(__name__).debug(f"Could not register rvbbit_udf: {e}")

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

        # Materialize as temp table for downstream cells
        if materialize and _cell_name and session_db:
            table_name = f"_{_cell_name}"
            # Register DataFrame and create table
            session_db.register("_temp_df", df)
            session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
            session_db.unregister("_temp_df")

        # Note: We don't include 'dataframe' in return as it's not JSON-serializable
        # Downstream cells access data via temp tables or by reconstructing from 'rows'
        # Use _serialize_for_json to handle numpy arrays (e.g., from DuckDB LIST columns)
        return {
            "rows": _serialize_for_json(df.to_dict('records')),
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
    Namespace object that provides access to prior cell DataFrames.

    Usage in python_data code:
        df = data.raw_customers      # Get DataFrame from prior cell
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
            raise AttributeError(f"No data found for cell '{name}'")

        # Extract data from various output formats
        if isinstance(output, pd.DataFrame):
            df = output
        elif isinstance(output, dict):
            if 'dataframe' in output and isinstance(output['dataframe'], pd.DataFrame):
                df = output['dataframe']
            elif 'rows' in output:
                # DataFrame result (sql_data, python_data DataFrame, js_data array)
                df = pd.DataFrame(output['rows'])
            elif 'result' in output:
                # Unwrap the result from API response format
                result_val = output['result']
                if isinstance(result_val, pd.DataFrame):
                    df = result_val
                elif isinstance(result_val, list) and result_val and isinstance(result_val[0], dict):
                    # List of dicts -> DataFrame
                    df = pd.DataFrame(result_val)
                else:
                    # Return dict/list/scalar as-is (don't force DataFrame conversion)
                    self._cache[name] = result_val
                    return result_val
            elif 'results' in output:
                # Handle output from run_sql which uses 'results' key
                df = pd.DataFrame(output['results'])
            else:
                # Dict is the data itself - return as-is
                self._cache[name] = output
                return output
        elif isinstance(output, list):
            if output and isinstance(output[0], dict):
                df = pd.DataFrame(output)
            else:
                # Return list as-is
                self._cache[name] = output
                return output
        else:
            # Return scalar as-is
            self._cache[name] = output
            return output

        self._cache[name] = df
        return df

    def list_available(self) -> List[str]:
        """List all available cell names."""
        return list(self._outputs.keys())


@simple_eddy
def python_data(
    code: str,
    _outputs: Dict[str, Any] | None = None,
    _state: Dict[str, Any] | None = None,
    _input: Dict[str, Any] | None = None,
    _cell_name: str | None = None,
    _session_id: str | None = None,
    _caller_id: str | None = None,
    _cascade_id: str | None = None
) -> Dict[str, Any]:
    """
    Execute inline Python code with access to prior cell DataFrames.

    The code environment includes:
        - data.<cell_name>: DataFrame from prior sql_data/python_data cells
        - data['cell_name']: Alternative dict-style access
        - state: Current cascade state dict (read-only recommended)
        - input: Original cascade input dict (includes _session_id, _caller_id, _cascade_id, _cell_name)
        - pd: pandas module
        - np: numpy module
        - json: json module

    The code MUST set a 'result' variable as its output.
    If result is a DataFrame, it will be materialized as a temp table.

    Args:
        code: Python code to execute
        _outputs: Injected by runner - all prior cell outputs
        _state: Injected by runner - current cascade state
        _input: Injected by runner - original cascade input
        _cell_name: Injected by runner - current cell name
        _session_id: Injected by runner - session ID for temp tables
        _caller_id: Injected by runner - caller ID for SQL Trail correlation
        _cascade_id: Injected by runner - cascade ID for context

    Returns:
        {
            "result": <the result value>,
            "dataframe": pd.DataFrame (if result is DataFrame),
            "rows": List[Dict] (if result is DataFrame),
            "type": "dataframe" | "dict" | "list" | "scalar",
            "_route": "success" | "error"
        }

    Example cascade usage:
        cells:
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

        # Build input dict with injected context for cascade code access
        input_with_context = dict(_input or {})
        input_with_context['_session_id'] = _session_id
        input_with_context['_caller_id'] = _caller_id
        input_with_context['_cascade_id'] = _cascade_id
        input_with_context['_cell_name'] = _cell_name

        # Build execution environment with common libraries
        exec_globals = {
            'data': data,
            'state': _state or {},
            'input': input_with_context,
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
            return _save_matplotlib_figure(result, _session_id or "unknown", _cell_name or "cell")

        # PIL Image
        if _is_pil_image(result):
            return _save_pil_image(result, _session_id or "unknown", _cell_name or "cell")

        # Plotly figure
        if _is_plotly_figure(result):
            return _convert_plotly_figure(result, _cell_name or "chart")

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
                        return _save_pil_image(img, _session_id or "unknown", _cell_name or "cell")
                    except Exception:
                        pass  # Fall through to treat as data

        # === Standard data outputs ===

        # DataFrame
        if isinstance(result, pd.DataFrame):
            # Materialize as temp table
            if _cell_name and session_db:
                table_name = f"_{_cell_name}"
                session_db.register("_temp_df", result)
                session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
                session_db.unregister("_temp_df")

            # Note: We don't include 'dataframe' or 'result' as they're not JSON-serializable
            # Downstream cells access data via temp tables or by reconstructing from 'rows'
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
            # Materialize dict results as temp tables
            # Creates: _cell_name (scalars), _cell_name_key (for nested arrays/dicts)
            if _cell_name and session_db:
                # First, create parent table with scalar values
                scalar_values = {}
                for key, value in result.items():
                    if isinstance(value, (str, int, float, bool, type(None))):
                        scalar_values[key] = value
                    elif isinstance(value, list) and value and isinstance(value[0], dict):
                        # Array of objects -> separate table
                        table_name = f"_{_cell_name}_{key}"
                        try:
                            nested_df = pd.DataFrame(value)
                            session_db.register("_temp_df", nested_df)
                            session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
                            session_db.unregister("_temp_df")
                        except Exception:
                            pass
                    elif isinstance(value, dict):
                        # Single dict -> single-row table
                        table_name = f"_{_cell_name}_{key}"
                        try:
                            nested_df = pd.DataFrame([value])
                            session_db.register("_temp_df", nested_df)
                            session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
                            session_db.unregister("_temp_df")
                        except Exception:
                            pass

                # Create parent table with scalars if any
                if scalar_values:
                    try:
                        parent_df = pd.DataFrame([scalar_values])
                        session_db.register("_temp_df", parent_df)
                        session_db.execute(f"CREATE OR REPLACE TABLE _{_cell_name} AS SELECT * FROM _temp_df")
                        session_db.unregister("_temp_df")
                    except Exception:
                        pass

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


# ============================================================================
# POLYGLOT DATA TOOLS - JavaScript and Clojure support
# ============================================================================

def _prepare_inputs_for_polyglot(outputs: Dict[str, Any]) -> Dict[str, Any]:
    """Convert prior cell outputs to a format suitable for other languages.

    DataFrames become arrays of objects, everything else passes through as JSON.
    """
    inputs = {}
    for name, output in (outputs or {}).items():
        if isinstance(output, dict):
            if 'rows' in output:
                # DataFrame result - send as array of objects
                inputs[name] = output['rows']
            elif 'result' in output:
                inputs[name] = output['result']
            else:
                inputs[name] = output
        elif isinstance(output, pd.DataFrame):
            inputs[name] = output.to_dict('records')
        elif isinstance(output, list):
            inputs[name] = output
        else:
            inputs[name] = output
    return inputs


def _format_polyglot_result(result: Any, cell_name: str, session_id: str) -> Dict[str, Any]:
    """Format result from polyglot execution into standard format.

    Also materializes DataFrames as temp tables if possible.
    """
    session_db = _get_session_duckdb(session_id)

    # Array of objects -> DataFrame
    if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
        df = pd.DataFrame(result)

        # Materialize as temp table
        if cell_name and session_db:
            table_name = f"_{cell_name}"
            session_db.register("_temp_df", df)
            session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
            session_db.unregister("_temp_df")

        return {
            "rows": result[:1000],  # Limit for UI
            "columns": list(df.columns),
            "row_count": len(result),
            "type": "dataframe",
            "_route": "success"
        }
    elif isinstance(result, list):
        return {
            "result": result,
            "type": "list",
            "_route": "success"
        }
    elif isinstance(result, dict):
        # Materialize dict results as temp tables
        # Creates: _cell_name (scalars), _cell_name_key (for nested arrays/dicts)
        if cell_name and session_db:
            scalar_values = {}
            for key, value in result.items():
                if isinstance(value, (str, int, float, bool, type(None))):
                    scalar_values[key] = value
                elif isinstance(value, list) and value and isinstance(value[0], dict):
                    # Array of objects -> table
                    table_name = f"_{cell_name}_{key}"
                    try:
                        nested_df = pd.DataFrame(value)
                        session_db.register("_temp_df", nested_df)
                        session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
                        session_db.unregister("_temp_df")
                    except Exception:
                        pass
                elif isinstance(value, dict):
                    # Single dict -> single-row table
                    table_name = f"_{cell_name}_{key}"
                    try:
                        nested_df = pd.DataFrame([value])
                        session_db.register("_temp_df", nested_df)
                        session_db.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_df")
                        session_db.unregister("_temp_df")
                    except Exception:
                        pass

            # Create parent table with scalars if any
            if scalar_values:
                try:
                    parent_df = pd.DataFrame([scalar_values])
                    session_db.register("_temp_df", parent_df)
                    session_db.execute(f"CREATE OR REPLACE TABLE _{cell_name} AS SELECT * FROM _temp_df")
                    session_db.unregister("_temp_df")
                except Exception:
                    pass

        return {
            "result": result,
            "type": "dict",
            "_route": "success"
        }
    else:
        return {
            "result": result,
            "type": "scalar",
            "_route": "success"
        }


@simple_eddy
def js_data(
    code: str,
    _outputs: Dict[str, Any] | None = None,
    _state: Dict[str, Any] | None = None,
    _input: Dict[str, Any] | None = None,
    _cell_name: str | None = None,
    _session_id: str | None = None,
    _caller_id: str | None = None,
    _cascade_id: str | None = None,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Execute JavaScript/Node.js code with access to prior cell data.

    The code environment includes:
        - data.<cell_name>: Array of objects from prior cells
        - data['cell_name']: Alternative bracket notation
        - state: Current cascade state object
        - input: Original cascade input object

    The code MUST set a 'result' variable as its output.
    If result is an array of objects, it becomes a DataFrame for downstream cells.

    Args:
        code: JavaScript code to execute
        _outputs: Injected by runner - all prior cell outputs
        _state: Injected by runner - current cascade state
        _input: Injected by runner - original cascade input
        _cell_name: Injected by runner - current cell name
        _session_id: Injected by runner - session ID for temp tables
        _caller_id: Injected by runner - caller ID for SQL Trail correlation
        _cascade_id: Injected by runner - cascade ID for context
        timeout: Execution timeout in seconds (default 30)

    Returns:
        {
            "result": <the result value>,
            "rows": List[Dict] (if result is array of objects),
            "type": "dataframe" | "dict" | "list" | "scalar",
            "_route": "success" | "error"
        }

    Example cascade usage:
        cells:
          - name: "transform"
            tool: "js_data"
            inputs:
              code: |
                const customers = data.raw_customers;
                result = customers.map(c => ({
                    ...c,
                    tier: c.spend > 1000 ? 'gold' : 'silver'
                }));
    """
    import subprocess
    import json as json_module
    import shutil

    try:
        # Check if Node.js is available
        if not shutil.which('node'):
            return {
                "_route": "error",
                "error": "Node.js not found. Install Node.js to use js_data cells."
            }

        # Prepare inputs for JavaScript
        inputs = _prepare_inputs_for_polyglot(_outputs)

        # Build the context object
        context = {
            "data": inputs,
            "state": _state or {},
            "input": _input or {}
        }

        # JavaScript runner - reads context from stdin, outputs result to stdout
        runner_code = '''
const context = JSON.parse(require("fs").readFileSync(0, "utf8"));
const data = context.data;
const state = context.state;
const input = context.input;

let result;

// User code
''' + code + '''

// Output result
if (result === undefined) {
    console.error("Error: Code must set a 'result' variable");
    process.exit(1);
}
console.log(JSON.stringify({ result }));
'''

        # Execute
        proc = subprocess.run(
            ['node', '-e', runner_code],
            input=json_module.dumps(context),
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if proc.returncode != 0:
            error_msg = proc.stderr.strip() or "JavaScript execution failed"
            return {
                "_route": "error",
                "error": error_msg,
                "stdout": proc.stdout.strip() if proc.stdout else None
            }

        # Parse output - last line is JSON result, everything before is console.log output
        stdout_lines = proc.stdout.strip().split('\n') if proc.stdout else []
        console_output = '\n'.join(stdout_lines[:-1]) if len(stdout_lines) > 1 else None
        result_line = stdout_lines[-1] if stdout_lines else '{}'

        try:
            output = json_module.loads(result_line)
            result = output.get('result')
        except json_module.JSONDecodeError as e:
            return {
                "_route": "error",
                "error": f"Failed to parse JavaScript output: {e}\nOutput: {proc.stdout[:500]}",
                "stdout": console_output
            }

        formatted = _format_polyglot_result(result, _cell_name, _session_id)
        if console_output:
            formatted['stdout'] = console_output
        if proc.stderr and proc.stderr.strip():
            formatted['stderr'] = proc.stderr.strip()
        return formatted

    except subprocess.TimeoutExpired:
        return {
            "_route": "error",
            "error": f"JavaScript execution timed out after {timeout} seconds"
        }
    except Exception as e:
        import traceback
        return {
            "_route": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@simple_eddy
def clojure_data(
    code: str,
    _outputs: Dict[str, Any] | None = None,
    _state: Dict[str, Any] | None = None,
    _input: Dict[str, Any] | None = None,
    _cell_name: str | None = None,
    _session_id: str | None = None,
    _caller_id: str | None = None,
    _cascade_id: str | None = None,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Execute Clojure code using Babashka with access to prior cell data.

    Babashka is a fast-starting Clojure interpreter (~10ms startup vs 2-3s for JVM).

    The code environment includes:
        - data: Map with prior cell outputs (keyword keys)
            - (:cell-name data) or (data :cell-name)
            - Cell names with underscores become kebab-case: raw_customers -> :raw-customers
        - state: Current cascade state map
        - input: Original cascade input map

    The code should evaluate to the result value (last expression).
    If result is a vector of maps, it becomes a DataFrame for downstream cells.

    Args:
        code: Clojure code to execute
        _outputs: Injected by runner - all prior cell outputs
        _state: Injected by runner - current cascade state
        _input: Injected by runner - original cascade input
        _cell_name: Injected by runner - current cell name
        _session_id: Injected by runner - session ID for temp tables
        _caller_id: Injected by runner - caller ID for SQL Trail correlation
        _cascade_id: Injected by runner - cascade ID for context
        timeout: Execution timeout in seconds (default 30)

    Returns:
        {
            "result": <the result value>,
            "rows": List[Dict] (if result is vector of maps),
            "type": "dataframe" | "dict" | "list" | "scalar",
            "_route": "success" | "error"
        }

    Example cascade usage:
        cells:
          - name: "transform"
            tool: "clojure_data"
            inputs:
              code: |
                (->> (:raw-customers data)
                     (filter #(> (:spend %) 1000))
                     (map #(assoc % :tier "gold")))
    """
    import subprocess
    import json as json_module
    import shutil

    try:
        # Check if Babashka is available
        if not shutil.which('bb'):
            return {
                "_route": "error",
                "error": "Babashka (bb) not found. Install: curl -sLO https://raw.githubusercontent.com/babashka/babashka/master/install && chmod +x install && ./install"
            }

        # Prepare inputs for Clojure (convert underscores to hyphens in keys)
        inputs = _prepare_inputs_for_polyglot(_outputs)
        clj_inputs = {}
        for name, value in inputs.items():
            clj_name = name.replace('_', '-')
            clj_inputs[clj_name] = value

        # Build the context
        context = {
            "data": clj_inputs,
            "state": _state or {},
            "input": _input or {}
        }

        # Babashka runner script
        # Uses cheshire for JSON parsing (built into babashka)
        runner_code = '''
(require '[cheshire.core :as json])

(def context (json/parse-string (slurp *in*) true))
(def data (:data context))
(def state (:state context))
(def input (:input context))

;; User code - should evaluate to result
(def result (do
''' + code + '''
))

;; Output as JSON
(println (json/generate-string {:result result}))
'''

        # Execute
        proc = subprocess.run(
            ['bb', '-e', runner_code],
            input=json_module.dumps(context),
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if proc.returncode != 0:
            error_msg = proc.stderr.strip() or "Clojure execution failed"
            return {
                "_route": "error",
                "error": error_msg,
                "stdout": proc.stdout.strip() if proc.stdout else None
            }

        # Parse output - last line is JSON result, everything before is println output
        stdout_lines = proc.stdout.strip().split('\n') if proc.stdout else []
        println_output = '\n'.join(stdout_lines[:-1]) if len(stdout_lines) > 1 else None
        result_line = stdout_lines[-1] if stdout_lines else '{}'

        try:
            output = json_module.loads(result_line)
            result = output.get('result')
        except json_module.JSONDecodeError as e:
            return {
                "_route": "error",
                "error": f"Failed to parse Clojure output: {e}\nOutput: {proc.stdout[:500]}",
                "stdout": println_output
            }

        formatted = _format_polyglot_result(result, _cell_name, _session_id)
        if println_output:
            formatted['stdout'] = println_output
        if proc.stderr and proc.stderr.strip():
            formatted['stderr'] = proc.stderr.strip()
        return formatted

    except subprocess.TimeoutExpired:
        return {
            "_route": "error",
            "error": f"Clojure execution timed out after {timeout} seconds"
        }
    except Exception as e:
        import traceback
        return {
            "_route": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@simple_eddy
def rvbbit_data(
    cell_yaml: str,
    _cell_name: str | None = None,
    _outputs: Dict[str, Any] | None = None,
    _session_id: str | None = None,
    _state: Dict[str, Any] | None = None,
    _input: Dict[str, Any] | None = None,
    _caller_id: str | None = None,
    _cascade_id: str | None = None,
) -> Dict[str, Any]:
    """
    Execute a full RVBBIT LLM cell within a notebook cell.

    The cell_yaml should be a valid cell definition with:
    - instructions: The prompt template (can use {{outputs.cell_name}}, {{input.x}}, {{state.x}})
    - model: Optional model override (default: system default)
    - output_schema: JSON schema for structured output (REQUIRED - must return structured data)
    - candidates: Optional candidates config for best-of-N attempts
    - reforge: Optional iterative refinement config
    - wards: Optional validation (pre/post)
    - skills: Optional tools to make available

    Example cell_yaml:
        instructions: |
          Analyze the customer orders from {{outputs.raw_orders}} and classify each customer.
        model: google/gemini-2.5-flash
        output_schema:
          type: array
          items:
            type: object
            properties:
              customer_id: { type: string }
              tier: { type: string }
              reason: { type: string }

    Returns structured data that can be queried by downstream SQL cells.
    """
    import yaml
    import traceback

    try:
        # Parse the cell YAML
        cell_config = yaml.safe_load(cell_yaml)

        if not cell_config:
            return {
                "_route": "error",
                "error": "Empty or invalid YAML"
            }

        # Require output_schema for structured output
        if 'output_schema' not in cell_config:
            return {
                "_route": "error",
                "error": "LLM cells require 'output_schema' to return structured data. Add an output_schema definition."
            }

        # Set the cell name
        cell_config['name'] = _cell_name or 'llm_cell'

        # Create a mini cascade with just this cell
        cascade_config = {
            'cascade_id': f'notebook_{_cell_name}',
            'description': 'Notebook LLM cell',
            'cells': [cell_config]
        }

        # Import runner components
        from ..runner import RVBBITRunner
        from ..echo import get_echo

        # Create a unique session for this cell execution
        cell_session_id = f"{_session_id}_llm_{_cell_name}" if _session_id else f"llm_{_cell_name}"

        # Get the echo and pre-populate lineage with prior outputs
        # This allows {{ outputs.cell_name }} to work in instructions
        echo = get_echo(cell_session_id)

        if _outputs:
            for cell_name, output in _outputs.items():
                # Add to lineage so {{ outputs.cell_name }} works
                echo.lineage.append({
                    'cell': cell_name,
                    'output': output
                })

        # Pre-populate state if provided
        if _state:
            echo.state.update(_state)

        # Create and run the runner
        runner = RVBBITRunner(
            config_path=cascade_config,
            session_id=cell_session_id,
            depth=1  # Mark as sub-cascade to avoid graph generation
        )

        # Run with input data
        result = runner.run(_input or {})

        # Extract the structured output from the cell
        # runner.run() returns the full echo: {session_id, state, history, lineage, errors, ...}
        # The cell output is in lineage[-1]["output"]
        cell_output = None
        if isinstance(result, dict):
            lineage = result.get('lineage', [])
            if lineage and len(lineage) > 0:
                # Get the last (and only) cell output
                cell_output = lineage[-1].get('output')

            # If not in lineage, try direct output key (fallback)
            if cell_output is None:
                cell_output = result.get('output')

        # If the result is wrapped in another layer, unwrap it
        if isinstance(cell_output, dict) and 'output' in cell_output:
            cell_output = cell_output['output']

        # Handle markdown code fences - LLMs sometimes wrap JSON in ```json ... ```
        # Also handles preamble text like "Here's the analysis:\n\n```json\n..."
        if isinstance(cell_output, str):
            import json as json_module
            import re

            content = cell_output.strip()

            # Try to extract content from code fences anywhere in the string
            # Matches ```json, ```JSON, ``` followed by content and closing ```
            fence_pattern = r'```(?:json|JSON)?\s*\n([\s\S]*?)\n\s*```'
            fence_match = re.search(fence_pattern, content)

            if fence_match:
                # Extract just the content inside the fences
                content = fence_match.group(1).strip()

            # Try to parse as JSON
            try:
                cell_output = json_module.loads(content)
            except (json_module.JSONDecodeError, ValueError):
                # If that failed, try to find JSON array or object directly
                # Look for [ ... ] or { ... } pattern
                json_pattern = r'(\[[\s\S]*\]|\{[\s\S]*\})'
                json_match = re.search(json_pattern, content)
                if json_match:
                    try:
                        cell_output = json_module.loads(json_match.group(1))
                    except (json_module.JSONDecodeError, ValueError):
                        # Still not valid JSON, keep as string
                        pass

        # Handle case where we couldn't find output
        if cell_output is None:
            return {
                "_route": "error",
                "error": "LLM cell did not produce output. Check the cell configuration.",
                "debug_result_keys": list(result.keys()) if isinstance(result, dict) else str(type(result))
            }

        # Format result for notebook consumption
        formatted = _format_polyglot_result(cell_output, _cell_name, _session_id)

        # Add metadata about the LLM execution
        formatted['_llm_execution'] = {
            'model': cell_config.get('model', 'default'),
            'had_candidates': 'candidates' in cell_config,
            'had_reforge': 'reforge' in cell_config,
        }

        return formatted

    except Exception as e:
        return {
            "_route": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }
