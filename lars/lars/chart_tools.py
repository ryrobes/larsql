"""
Chart Tools: Functions for chart spec generation and rendering.

These functions are used by pipeline cascades to transform data into
chart specifications and render them to images.

Supports:
- Vega-Lite specifications
- Plotly specifications
- Matplotlib code execution

Usage in cascade YAML:
    cells:
      - name: render
        deterministic: true
        tool: python:lars.chart_tools.render_spec_to_image
        inputs:
          spec: "{{ input._table[0].spec }}"
          library: "{{ input._table[0].library }}"
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import base64
import io
import json
import os
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Theme Definitions
# =============================================================================

CHART_THEMES = {
    "dark": {
        "name": "dark",
        "plotly": {
            # Match UI: PlotlyPanel.jsx darkLayout
            "paper_bgcolor": "rgba(0,0,0,0)",  # transparent
            "plot_bgcolor": "rgba(0,0,0,0)",   # transparent
            "font": {
                "family": "'Google Sans', sans-serif",
                "color": "#cbd5e1",  # slate-300
            },
            "xaxis": {
                "gridcolor": "#1e293b",  # slate-800
                "linecolor": "#334155",  # slate-700
                "tickcolor": "#64748b",  # slate-500
                "zerolinecolor": "#334155",
            },
            "yaxis": {
                "gridcolor": "#1e293b",
                "linecolor": "#334155",
                "tickcolor": "#64748b",
                "zerolinecolor": "#334155",
            },
            "colorway": ["#00e5ff", "#ff6b6b", "#4ade80", "#fbbf24", "#a78bfa", "#f472b6"],
            "margin": {"t": 40, "r": 20, "b": 40, "l": 50},
        },
        "vega-lite": {
            # Match UI: VegaLitePanel.jsx darkConfig
            "background": "transparent",
            "view": {"stroke": "transparent"},
            "axis": {
                "domainColor": "#334155",  # slate-700
                "gridColor": "#1e293b",    # slate-800
                "tickColor": "#64748b",    # slate-500
                "labelColor": "#94a3b8",   # slate-400
                "titleColor": "#cbd5e1",   # slate-300
                "labelFont": "'Google Sans', sans-serif",
                "titleFont": "'Google Sans', sans-serif",
            },
            "legend": {
                "labelColor": "#94a3b8",
                "titleColor": "#cbd5e1",
                "labelFont": "'Google Sans', sans-serif",
                "titleFont": "'Google Sans', sans-serif",
            },
            "title": {
                "color": "#e2e8f0",  # slate-200
                "font": "'Google Sans', sans-serif",
            },
            "range": {
                "category": ["#00e5ff", "#ff6b6b", "#4ade80", "#fbbf24", "#a78bfa", "#f472b6"],
            },
        },
        "matplotlib": "dark_background"
    },
    "light": {
        "name": "light",
        "plotly": {
            "template": "plotly_white",
            "paper_bgcolor": "#ffffff",
            "plot_bgcolor": "#ffffff",
            "font": {"color": "#333333"}
        },
        "vega-lite": {
            "background": "#ffffff",
            "title": {"color": "#333333"},
            "axis": {
                "gridColor": "#eeeeee",
                "labelColor": "#666666",
                "titleColor": "#333333",
                "domainColor": "#cccccc"
            },
            "legend": {"labelColor": "#666666", "titleColor": "#333333"},
            "view": {"stroke": "#cccccc"}
        },
        "matplotlib": "seaborn-v0_8-whitegrid"
    },
    "midnight": {
        "name": "midnight",
        "plotly": {
            "template": "plotly_dark",
            "paper_bgcolor": "#0d1117",
            "plot_bgcolor": "#0d1117",
            "font": {"color": "#c9d1d9"}
        },
        "vega-lite": {
            "background": "#0d1117",
            "title": {"color": "#c9d1d9"},
            "axis": {
                "gridColor": "#21262d",
                "labelColor": "#8b949e",
                "titleColor": "#c9d1d9",
                "domainColor": "#30363d"
            },
            "legend": {"labelColor": "#8b949e", "titleColor": "#c9d1d9"},
            "view": {"stroke": "#21262d"}
        },
        "matplotlib": "dark_background"
    },
    "paper": {
        "name": "paper",
        "plotly": {
            "template": "simple_white",
            "paper_bgcolor": "#faf9f6",
            "plot_bgcolor": "#faf9f6",
            "font": {"color": "#2d2d2d", "family": "Georgia, serif"}
        },
        "vega-lite": {
            "background": "#faf9f6",
            "title": {"color": "#2d2d2d"},
            "axis": {
                "gridColor": "#e8e6e1",
                "labelColor": "#555555",
                "titleColor": "#2d2d2d",
                "domainColor": "#cccccc"
            },
            "legend": {"labelColor": "#555555", "titleColor": "#2d2d2d"},
            "view": {"stroke": "#cccccc"}
        },
        "matplotlib": "seaborn-v0_8-paper"
    }
}


# =============================================================================
# Spec Wrapping
# =============================================================================

def wrap_spec(
    spec: Union[Dict, str],
    library: str,
    _table: Optional[List[Dict]] = None,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Wrap a generated chart spec with library metadata.

    Args:
        spec: Chart specification (dict for vega-lite/plotly, str for matplotlib)
        library: Library name (vega-lite, plotly, matplotlib)
        _table: Original table data (unused, for pipeline compatibility)
        _table_columns: Original column names (unused)

    Returns:
        Dict with 'data' key containing single row with code and format
    """
    # Format matches library name for UI rendering
    return {
        "data": [{
            "spec": spec,
            "format": library  # "plotly", "vega-lite", or "matplotlib"
        }]
    }


# =============================================================================
# Library Detection
# =============================================================================

def detect_chart_library(spec: Union[Dict, str]) -> str:
    """
    Auto-detect chart library from spec structure.

    Args:
        spec: Chart specification

    Returns:
        Library name: 'vega-lite', 'plotly', or 'matplotlib'
    """
    if isinstance(spec, str):
        return "matplotlib"

    if isinstance(spec, dict):
        # Vega-Lite indicators
        if "$schema" in spec and "vega-lite" in spec.get("$schema", ""):
            return "vega-lite"
        if "mark" in spec or "encoding" in spec:
            return "vega-lite"
        if "layer" in spec or "vconcat" in spec or "hconcat" in spec:
            return "vega-lite"

        # Plotly indicators
        if "data" in spec and isinstance(spec.get("data"), list):
            if spec["data"] and isinstance(spec["data"][0], dict):
                if "type" in spec["data"][0] or "x" in spec["data"][0] or "y" in spec["data"][0]:
                    return "plotly"
        if "layout" in spec and "traces" not in spec:
            return "plotly"

    # Default to plotly
    return "plotly"


# =============================================================================
# Style Application
# =============================================================================

def apply_chart_styles(
    spec: Union[Dict, str] = None,
    library: str = "auto",
    theme: str = "auto",
    custom: Optional[str] = None,
    _table: Optional[List[Dict]] = None,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Apply theme styling to a chart spec.

    Supports two input formats:
    1. Legacy spec format: {format: "plotly", spec: {...full spec...}}
    2. Data-driven format: {format: "plotly", config: {...}, col1: val, col2: val, ...}

    For data-driven format, expands config to full spec first, then applies styles.

    Args:
        spec: Chart specification from previous stage (extracted from _table[0].code)
        library: Library name
        theme: Theme name ('auto', 'dark', 'light', 'midnight', 'paper') or 'auto'
        custom: JSON string with custom theme overrides
        _table: Pipeline table input (spec extracted from first row)
        _table_columns: Column names

    Returns:
        Dict with 'data' key containing themed spec
    """
    # If spec is None but _table is provided, extract from table
    if spec is None and _table and len(_table) > 0:
        first_row = _table[0]

        # Check for data-driven format (has config, not spec)
        if "config" in first_row and "spec" not in first_row:
            logger.info("[apply_chart_styles] Detected data-driven format, expanding config")
            spec, library = expand_data_driven_chart(_table)
        else:
            # Legacy format with spec
            spec = first_row.get("spec")
            # Format field contains the library name (e.g., "plotly", "vega-lite")
            library = first_row.get("format", library)

    # Resolve theme configuration
    if custom:
        try:
            theme_config = json.loads(custom) if isinstance(custom, str) else custom
        except json.JSONDecodeError:
            logger.warning(f"Invalid custom theme JSON, using default: {custom[:100]}")
            theme_config = CHART_THEMES.get("dark", {})
    elif theme == "auto":
        theme_name = os.environ.get("LARS_CHART_THEME", "dark")
        theme_config = CHART_THEMES.get(theme_name, CHART_THEMES["dark"])
    else:
        theme_config = CHART_THEMES.get(theme, CHART_THEMES["dark"])

    # Apply theme based on library
    if library == "plotly":
        styled_spec = dict(spec) if isinstance(spec, dict) else spec
        if isinstance(styled_spec, dict):
            plotly_config = theme_config.get("plotly", {})
            styled_spec["layout"] = {
                **styled_spec.get("layout", {}),
                **plotly_config
            }

    elif library == "vega-lite":
        styled_spec = dict(spec) if isinstance(spec, dict) else spec
        if isinstance(styled_spec, dict):
            vegalite_config = theme_config.get("vega-lite", {})
            styled_spec["config"] = {
                **styled_spec.get("config", {}),
                **vegalite_config
            }

    elif library == "matplotlib":
        # For matplotlib, prepend style directive to code
        style_name = theme_config.get("matplotlib", "dark_background")
        if isinstance(spec, str):
            styled_spec = f"plt.style.use('{style_name}')\n{spec}"
        else:
            styled_spec = spec

    else:
        styled_spec = spec

    resolved_theme = theme_config.get("name", theme)

    return {
        "data": [{
            "spec": styled_spec,
            "format": library,  # "plotly", "vega-lite", or "matplotlib"
            "theme": resolved_theme
        }]
    }


# =============================================================================
# Data-Driven Chart Expansion
# =============================================================================

def expand_data_driven_chart(
    rows: List[Dict],
) -> Tuple[Dict, str]:
    """
    Expand data-driven chart format into a full spec.

    The data-driven format has:
    - format: "plotly" or "vega-lite"
    - config: shorthand config referencing column names
    - data columns: the actual data

    This function expands the config + data into a full Plotly or Vega-Lite spec.

    Args:
        rows: List of row dicts with format, config, and data columns

    Returns:
        Tuple of (expanded_spec, library_name)
    """
    if not rows:
        raise ValueError("No rows provided for chart expansion")

    first_row = rows[0]
    library = first_row.get("format", "plotly")
    config = first_row.get("config")

    if config is None:
        raise ValueError("No config found in data-driven chart format")

    # Parse config if it's a string
    if isinstance(config, str):
        config = json.loads(config)

    # Extract data columns (everything except format and config)
    data_columns = [k for k in first_row.keys() if k not in ("format", "config")]
    data = [{col: row.get(col) for col in data_columns} for row in rows]

    if library == "plotly":
        spec = _expand_plotly_config(config, data)
    elif library == "vega-lite":
        spec = _expand_vegalite_config(config, data)
    else:
        raise ValueError(f"Unknown chart format: {library}")

    return spec, library


def _expand_plotly_config(config: Dict, data: List[Dict]) -> Dict:
    """Expand Plotly shorthand config into a full spec."""
    chart_type = config.get("type", "bar")
    x_col = config.get("x")
    y_col = config.get("y")
    color_col = config.get("color")
    values_col = config.get("values")
    labels_col = config.get("labels")
    title = config.get("title", "")
    mode = config.get("mode")

    def get_column(col: str) -> List:
        return [row.get(col) for row in data]

    # Build trace based on chart type
    if chart_type == "pie":
        trace = {
            "type": "pie",
            "values": get_column(values_col) if values_col else [],
            "labels": get_column(labels_col) if labels_col else [],
        }
    elif chart_type in ("scatter", "line"):
        trace = {
            "type": "scatter",
            "x": get_column(x_col) if x_col else [],
            "y": get_column(y_col) if y_col else [],
            "mode": mode or ("lines" if chart_type == "line" else "markers"),
        }
    elif color_col:
        # Grouped chart - create multiple traces
        groups = {}
        for row in data:
            group_key = row.get(color_col)
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(row)

        traces = []
        for group_name, group_data in groups.items():
            trace = {
                "type": chart_type if chart_type != "line" else "scatter",
                "name": str(group_name),
                "x": [row.get(x_col) for row in group_data] if x_col else [],
                "y": [row.get(y_col) for row in group_data] if y_col else [],
            }
            if chart_type == "line":
                trace["mode"] = mode or "lines"
            traces.append(trace)

        return {
            "data": traces,
            "layout": {"title": {"text": title}} if title else {}
        }
    else:
        trace = {
            "type": chart_type,
            "x": get_column(x_col) if x_col else [],
            "y": get_column(y_col) if y_col else [],
        }

    return {
        "data": [trace],
        "layout": {"title": {"text": title}} if title else {}
    }


def _expand_vegalite_config(config: Dict, data: List[Dict]) -> Dict:
    """Expand Vega-Lite shorthand config into a full spec."""
    # Check if it's already a full spec (has encoding)
    if "encoding" in config:
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "data": {"values": data},
            **config
        }

    # Shorthand expansion
    mark = config.get("mark", config.get("type", "bar"))
    x_col = config.get("x")
    y_col = config.get("y")
    color_col = config.get("color")
    size_col = config.get("size")
    theta_col = config.get("theta")
    title = config.get("title")

    # Handle pie/donut charts
    if mark in ("pie", "donut", "arc") or theta_col:
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "data": {"values": data},
            "mark": {"type": "arc", "innerRadius": 50 if mark == "donut" else 0},
            "encoding": {}
        }
        if theta_col:
            spec["encoding"]["theta"] = {"field": theta_col, "type": "quantitative"}
        if color_col:
            spec["encoding"]["color"] = {"field": color_col, "type": "nominal"}
        if title:
            spec["title"] = title
        return spec

    # Standard x/y charts
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": data},
        "mark": mark,
        "encoding": {}
    }

    if x_col:
        # Infer type from data
        sample = data[0].get(x_col) if data else None
        x_type = "quantitative" if isinstance(sample, (int, float)) else "nominal"
        spec["encoding"]["x"] = {"field": x_col, "type": x_type}

    if y_col:
        sample = data[0].get(y_col) if data else None
        y_type = "quantitative" if isinstance(sample, (int, float)) else "nominal"
        spec["encoding"]["y"] = {"field": y_col, "type": y_type}

    if color_col:
        spec["encoding"]["color"] = {"field": color_col, "type": "nominal"}

    if size_col:
        spec["encoding"]["size"] = {"field": size_col, "type": "quantitative"}

    if title:
        spec["title"] = title

    return spec


# =============================================================================
# Rendering
# =============================================================================

def render_spec_to_image(
    spec: Union[Dict, str] = None,
    library: str = "auto",
    width: int = 800,
    height: int = 600,
    scale: int = 2,
    _table: Optional[List[Dict]] = None,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Render a chart spec to PNG image.

    Supports two input formats:
    1. Legacy spec format: {format: "plotly", spec: {...full spec...}}
    2. Data-driven format: {format: "plotly", config: {...}, col1: val, col2: val, ...}

    Auto-detects format and library from input structure.

    Args:
        spec: Chart specification (dict for vega-lite/plotly, str for matplotlib)
        library: Library name or 'auto' to detect
        width: Image width in pixels
        height: Image height in pixels
        scale: Resolution multiplier (2 = retina quality)
        _table: Pipeline table input (spec/config extracted from rows)
        _table_columns: Column names

    Returns:
        Dict with 'data' key containing image as base64 data URL
    """
    # Debug logging
    logger.info(f"[render_spec_to_image] Called with spec={type(spec)}, _table={type(_table)}, _table len={len(_table) if _table else 0}")
    if _table and len(_table) > 0:
        first_row = _table[0]
        logger.info(f"[render_spec_to_image] First row keys: {list(first_row.keys()) if isinstance(first_row, dict) else type(first_row)}")

    # If spec is None but _table is provided, extract from table
    if spec is None and _table and len(_table) > 0:
        first_row = _table[0]

        # Check for data-driven format (has config, not spec)
        if "config" in first_row and "spec" not in first_row:
            logger.info("[render_spec_to_image] Detected data-driven format, expanding config")
            spec, library = expand_data_driven_chart(_table)
        else:
            # Legacy format with spec
            spec = first_row.get("spec")
            library = first_row.get("format", library)

    # Ensure numeric types
    width = int(width)
    height = int(height)
    scale = int(scale)

    # Auto-detect library if needed
    if library == "auto":
        library = detect_chart_library(spec)

    logger.info(f"[render_spec_to_image] Rendering {library} chart ({width}x{height}, scale={scale})")

    # Render based on library
    if library == "vega-lite":
        img_bytes = _render_vegalite(spec, width, height, scale)
    elif library == "plotly":
        img_bytes = _render_plotly(spec, width, height, scale)
    elif library == "matplotlib":
        img_bytes = _render_matplotlib(spec, width, height)
    else:
        raise ValueError(f"Unknown chart library: {library}")

    img_b64 = base64.b64encode(img_bytes).decode('utf-8')

    result = {
        "data": [{
            "image": f"data:image/png;base64,{img_b64}",
            "format": "image-base64",
            "library": library,
            "width": width,
            "height": height
        }]
    }

    # Debug output
    print(f"\n{'='*60}")
    print(f"[DEBUG] render_spec_to_image OUTPUT")
    print(f"{'='*60}")
    print(f"Image size: {len(img_bytes)} bytes")
    print(f"Base64 length: {len(img_b64)} chars")
    print(f"Data URL prefix: {result['data'][0]['image'][:80]}...")
    print(f"Result keys: {list(result['data'][0].keys())}")
    print(f"{'='*60}\n")

    return result


def _render_vegalite(spec: Dict, width: int, height: int, scale: int) -> bytes:
    """Render Vega-Lite spec to PNG bytes."""
    try:
        import vl_convert as vlc
    except ImportError:
        raise ImportError("vl-convert-python is required for Vega-Lite rendering. Install with: pip install vl-convert-python")

    # Inject dimensions
    full_spec = {**spec, "width": width, "height": height}

    # Render to PNG
    return vlc.vegalite_to_png(full_spec, scale=scale)


def _render_plotly(spec: Dict, width: int, height: int, scale: int) -> bytes:
    """Render Plotly spec to PNG bytes."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        raise ImportError("plotly is required for Plotly rendering. Install with: pip install plotly")

    try:
        import kaleido  # noqa: F401 - just checking it's installed
    except ImportError:
        raise ImportError("kaleido is required for Plotly image export. Install with: pip install kaleido")

    fig = go.Figure(spec)
    fig.update_layout(width=width, height=height)

    return fig.to_image(format="png", scale=scale)


def _render_matplotlib(code: str, width: int, height: int) -> bytes:
    """Execute matplotlib code and return PNG bytes."""
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError("matplotlib is required for matplotlib rendering. Install with: pip install matplotlib")

    import pandas as pd

    # Create figure with specified dimensions
    fig = plt.figure(figsize=(width/100, height/100), dpi=100)

    # Execute code with fig, plt, pd in namespace
    namespace = {
        'plt': plt,
        'fig': fig,
        'pd': pd,
    }

    try:
        exec(code, namespace)
    except Exception as e:
        plt.close('all')
        raise RuntimeError(f"Matplotlib code execution failed: {e}")

    # Get the figure (might have been replaced by the code)
    final_fig = namespace.get('fig', plt.gcf())

    # Render to bytes
    buf = io.BytesIO()
    final_fig.savefig(
        buf,
        format='png',
        dpi=150,
        bbox_inches='tight',
        facecolor=final_fig.get_facecolor(),
        edgecolor='none'
    )
    plt.close('all')

    buf.seek(0)
    return buf.read()


# =============================================================================
# Config-Based Chart Generation (Fungible Queries)
# =============================================================================

def merge_config_with_data(
    format: str,
    config: Union[Dict, str],
    table: List[Dict],
    _table: Optional[List[Dict]] = None,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Merge chart config with data rows to create a fungible chart result.

    Instead of embedding data values in a chart spec, this returns the original
    data rows with 'format' and 'config' columns added. The frontend's
    chartConfigExpander.js will expand this into a full spec at render time.

    This approach keeps queries fungible - they can be re-run without the LLM
    call because the config just references column names, not actual values.

    Args:
        format: Chart library ("plotly" or "vega-lite")
        config: Config object referencing column names (e.g., {type: 'bar', x: 'month', y: 'revenue'})
        table: Original data rows from the pipeline
        _table: Pipeline table input (fallback if table not provided)
        _table_columns: Column names (unused, for pipeline compatibility)

    Returns:
        Dict with 'data' key containing rows with format, config, and data columns

    Example output format:
        {
            "data": [
                {"format": "plotly", "config": {...}, "month": "Jan", "revenue": 100},
                {"format": "plotly", "config": {...}, "month": "Feb", "revenue": 150},
                ...
            ]
        }

    The frontend detects this format and expands config + data into a full spec.
    """
    # Parse config if it's a JSON string
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            logger.warning(f"Invalid config JSON, using as-is: {config[:100] if len(config) > 100 else config}")

    # Use table or fall back to _table
    data_rows = table if table else (_table or [])

    if not data_rows:
        logger.warning("[merge_config_with_data] No data rows provided")
        return {"data": [{"format": format, "config": config}]}

    # Add format and config to each row
    result_rows = []
    for row in data_rows:
        result_row = {
            "format": format,
            "config": config,  # Same config for all rows
            **row  # Original data columns
        }
        result_rows.append(result_row)

    logger.info(f"[merge_config_with_data] Created {len(result_rows)} rows with {format} config: {list(config.keys()) if isinstance(config, dict) else 'string'}")

    return {"data": result_rows}


def generate_chart_sql(
    format: str,
    config: Union[Dict, str],
    source_sql: str,
    source_columns: Optional[List[str]] = None,
    _table: Optional[List[Dict]] = None,
    _table_columns: Optional[List[str]] = None,
    _pipeline_context: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Generate SQL that produces a chart-ready result.

    Returns a SQL query string that can be saved and re-executed to produce
    the same chart without needing an LLM call. The SQL wraps the original
    query with format and config columns.

    Args:
        format: Chart library ("plotly" or "vega-lite")
        config: Config object referencing column names
        source_sql: Original SQL query to wrap
        source_columns: List of column names to include from source
        _table: Pipeline table input (unused)
        _table_columns: Column names from pipeline (fallback for source_columns)
        _pipeline_context: Pipeline context (fallback for source_sql)

    Returns:
        Dict with 'data' key containing single row with 'query' column

    Example output:
        SELECT
          'plotly' as format,
          '{"type":"bar","x":"month","y":"revenue"}'::JSON as config,
          month, revenue
        FROM (SELECT month, revenue FROM sales) AS _source
    """
    # Parse config if string
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            pass

    # Get source SQL from parameter or pipeline context
    sql_source = source_sql
    if not sql_source and _pipeline_context:
        sql_source = _pipeline_context.get("original_query", "")

    if not sql_source:
        logger.warning("[generate_chart_sql] No source SQL provided")
        sql_source = "SELECT * FROM _input_table"

    # Use provided columns or fall back to _table_columns
    columns = source_columns if source_columns else (_table_columns or [])

    # Format config as JSON string for SQL
    if isinstance(config, dict):
        config_json = json.dumps(config)
    else:
        config_json = str(config)

    # Escape single quotes in config JSON for SQL string literal
    config_escaped = config_json.replace("'", "''")

    # Build column list
    col_list = ", ".join(columns) if columns else "*"

    # Generate the wrapped SQL query
    # Use a subquery to wrap the original SQL
    sql = f"""SELECT
  '{format}' as format,
  '{config_escaped}'::JSON as config,
  {col_list}
FROM ({sql_source}) AS _source"""

    logger.info(f"[generate_chart_sql] Generated SQL for {format} chart with columns: {columns}")

    return {
        "data": [{
            "query": sql,
            "format": format,
            "config": config
        }]
    }


# =============================================================================
# Output Utilities
# =============================================================================

def wrap_stylized_image(
    image: str,
    prompt: str,
    fidelity: float = 0.8,
    source_image: Optional[str] = None,
    _table: Optional[List[Dict]] = None,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Wrap a stylized image result with metadata.

    Args:
        image: Base64 encoded image or data URL
        prompt: The style prompt used
        fidelity: Fidelity level used (0.0-1.0)
        source_image: Original image before stylization
        _table: Pipeline table input
        _table_columns: Column names

    Returns:
        Dict with 'data' key containing image and metadata
    """
    # Ensure image is a data URL
    if not image.startswith("data:"):
        image = f"data:image/png;base64,{image}"

    result = {
        "image": image,
        "format": "image-base64",
        "style_prompt": prompt,
        "fidelity": fidelity,
    }

    if source_image:
        result["source_image"] = source_image

    return {"data": [result]}


def wrap_generated_image(
    _table: Optional[List[Dict]] = None,
    _table_columns: Optional[List[str]] = None,
    style_prompt: str = "",
    fidelity: float = 0.8,
) -> Dict[str, Any]:
    """
    Wrap image generation output into pipeline-compatible format.

    Image generation cells save images to disk and return file paths.
    This function returns the image path directly (the UI can resolve it)
    instead of converting to base64 - this avoids ClickHouse query size limits.

    Args:
        _table: Image generation output (has 'images' array with file paths)
        _table_columns: Column names
        style_prompt: The style prompt used (for metadata)
        fidelity: Fidelity level used (for metadata)

    Returns:
        Dict with 'data' key containing image path
    """
    if not _table or len(_table) == 0:
        logger.warning("[wrap_generated_image] No input table provided")
        return {"data": [{"error": "No image generated", "format": "error"}]}

    first_row = _table[0]

    # Check for images array (from image generation cell)
    images = first_row.get("images", [])
    src = first_row.get("src")

    if not images and not src:
        # Maybe the image is already a path or base64 (passed through from a previous stage)
        existing_image = first_row.get("image", "")
        if existing_image:
            return {"data": [first_row]}
        logger.warning("[wrap_generated_image] No images found in input")
        return {"data": [{"error": "No images in generation output", "format": "error"}]}

    # Get the first image path - keep it as-is (API path)
    # The UI will resolve /api/images/... paths directly
    image_path = images[0] if images else src

    logger.info(f"[wrap_generated_image] Returning image path: {image_path}")

    return {
        "data": [{
            "image": image_path,
            "format": "image",
            "style_prompt": style_prompt,
            "fidelity": fidelity,
            "source": "stylized"
        }]
    }


def debug_pipeline_input(
    _table: Optional[List[Dict]] = None,
    _table_columns: Optional[List[str]] = None,
    stage_name: str = "UNKNOWN",
) -> Dict[str, Any]:
    """
    Debug function to print pipeline input details.

    This is used to diagnose data flow issues between pipeline stages.
    Prints detailed info about what the stage is receiving.

    Returns the input unchanged (pass-through).
    """
    print(f"\n{'='*60}")
    print(f"[DEBUG] Pipeline Stage: {stage_name}")
    print(f"{'='*60}")

    print(f"_table type: {type(_table)}")
    print(f"_table_columns: {_table_columns}")

    if _table is None:
        print("_table is None!")
    elif not _table:
        print("_table is empty list!")
    else:
        print(f"_table length: {len(_table)}")
        for i, row in enumerate(_table[:3]):  # Show first 3 rows
            print(f"\nRow {i}:")
            if isinstance(row, dict):
                for k, v in row.items():
                    if isinstance(v, str) and len(v) > 100:
                        print(f"  {k}: {v[:100]}... ({len(v)} chars)")
                    else:
                        print(f"  {k}: {v}")
            else:
                print(f"  (not a dict): {type(row)} = {row}")

    print(f"{'='*60}\n")

    # Return input unchanged
    return {"data": _table or []}


def select_final_output(
    stylized: Optional[str] = None,
    base: Optional[str] = None,
    spec: Optional[Union[Dict, str]] = None,
    library: Optional[str] = None,
    _table: Optional[List[Dict]] = None,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Select the appropriate output from pipeline results.

    Prefers stylized > base > spec.

    Args:
        stylized: Stylized image (if STYLIZE was run)
        base: Base rendered image
        spec: Chart spec (if only spec generation was done)
        library: Chart library
        _table: Pipeline table input
        _table_columns: Column names

    Returns:
        Dict with 'data' key containing selected output
    """
    if stylized:
        # Stylized image takes priority
        if not stylized.startswith("data:"):
            stylized = f"data:image/png;base64,{stylized}"
        return {
            "data": [{
                "image": stylized,
                "format": "image-base64",
                "source": "stylized"
            }]
        }

    if base:
        # Base rendered image
        if not base.startswith("data:"):
            base = f"data:image/png;base64,{base}"
        return {
            "data": [{
                "image": base,
                "format": "image-base64",
                "source": "rendered"
            }]
        }

    if spec:
        # Just the spec
        return {
            "data": [{
                "spec": spec,
                "format": library or "unknown"
            }]
        }

    return {"data": [{"error": "No output available", "format": "error"}]}
