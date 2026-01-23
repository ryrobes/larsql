"""
Pipeline Tools: Deterministic Python functions for PIPELINE cascades.

These functions are used by deterministic cells in pipeline cascades
to perform data transformations without LLM calls.

Usage in cascade YAML:
    cells:
      - name: compute_stats
        tool: python:lars.pipeline_tools.compute_stats
        inputs:
          _table: "{{ input._table }}"
          _table_path: "{{ input._table_path | default('') }}"
          columns: "{{ input.columns }}"
"""

from typing import Any, Dict, List, Optional, Union
import json
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# =============================================================================
# Table Resolution Helper - Handles both inline and parquet file inputs
# =============================================================================

def _resolve_table(
    _table: Union[List[Dict[str, Any]], str, None],
    _table_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Resolve table data from either inline records or a parquet file.

    The pipeline executor serializes tables in two ways:
    - Small tables (<1000 rows): Inline as List[Dict] in _table
    - Large tables: Write to parquet file, _table contains a message,
      actual path is in _table_path

    Args:
        _table: Either a list of records (small table) or a string message (large table)
        _table_path: Path to parquet file for large tables

    Returns:
        List of records (rows as dicts)
    """
    import pandas as pd

    # Case 1: _table is already a list of records
    if isinstance(_table, list):
        return _table

    # Case 2: Large table - read from parquet file
    if _table_path and isinstance(_table_path, str) and _table_path.strip():
        path = Path(_table_path)
        if path.exists():
            logger.debug(f"Reading large table from parquet: {_table_path}")
            df = pd.read_parquet(path)
            return df.to_dict(orient="records")
        else:
            logger.warning(f"Parquet file not found: {_table_path}")

    # Case 3: Empty or invalid input
    if not _table:
        return []

    # Case 4: _table is a string (the "large table" message) but no valid path
    # This shouldn't happen in normal operation, but handle gracefully
    if isinstance(_table, str):
        logger.warning(f"_table is string but no valid _table_path: {_table[:100]}")
        return []

    return []

# =============================================================================
# render_canvas Cache - Hash-based memoization for pure transformations
# =============================================================================

_render_canvas_cache: dict[str, Dict[str, Any]] = {}
_render_canvas_stats = {'hits': 0, 'misses': 0}
_RENDER_CANVAS_CACHE_MAX = 500


def _render_canvas_cache_key(table: List[Dict], layout_type: str, dim1: int, dim2: int) -> str:
    """Generate cache key from render_canvas inputs."""
    # Serialize inputs to a stable string for hashing
    key_data = json.dumps({
        'table': table,
        'layout_type': layout_type,
        'dim1': dim1,
        'dim2': dim2
    }, sort_keys=True, default=str)
    return hashlib.md5(key_data.encode('utf-8')).hexdigest()


def get_render_canvas_cache_stats() -> dict:
    """Get render_canvas cache statistics."""
    total = _render_canvas_stats['hits'] + _render_canvas_stats['misses']
    hit_rate = _render_canvas_stats['hits'] / total if total > 0 else 0
    return {
        'hits': _render_canvas_stats['hits'],
        'misses': _render_canvas_stats['misses'],
        'size': len(_render_canvas_cache),
        'hit_rate': f"{hit_rate:.1%}"
    }


def compute_stats(
    _table: Union[List[Dict[str, Any]], str],
    columns: Optional[List[str]] = None,
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute comprehensive column profiles for chart planning and data exploration.

    Returns a profile for each column including:
    - Data type classification (numeric, string, datetime, boolean)
    - Role suggestion (dimension vs measure) based on type and cardinality
    - Count statistics (non_null, null_count, distinct/cardinality)
    - Numeric statistics (min, max, mean, std, quartiles) for numeric columns
    - Top values with counts (useful for seeing categories or spotting data issues)
    - Sample values (examples of actual data format)

    Args:
        _table: List of records (rows) or string message for large tables
        columns: Specific columns to analyze (default: all columns)
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing column profile table
    """
    import pandas as pd

    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {"data": [{"error": "No data provided"}]}

    df = pd.DataFrame(table_data)
    row_count = len(df)

    # Select columns to analyze
    if columns:
        if isinstance(columns, str):
            columns = [c.strip() for c in columns.split(",")]
        cols_to_analyze = [c for c in columns if c in df.columns]
    else:
        cols_to_analyze = list(df.columns)

    if not cols_to_analyze:
        return {"data": [{"error": "No columns found to analyze"}]}

    stats_data = []

    for col in cols_to_analyze:
        series = df[col]
        non_null = int(series.notna().sum())
        null_count = int(series.isna().sum())
        distinct = int(series.nunique())

        # Determine dtype category
        if pd.api.types.is_numeric_dtype(series):
            dtype = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(series):
            dtype = "datetime"
        elif pd.api.types.is_bool_dtype(series):
            dtype = "boolean"
        else:
            dtype = "string"

        # Suggest role based on type and cardinality
        # Dimensions: categorical data good for grouping (low-medium cardinality)
        # Measures: numeric data good for aggregation
        cardinality_ratio = distinct / row_count if row_count > 0 else 0
        if dtype == "numeric":
            # High cardinality numeric = likely a measure
            # Low cardinality numeric = could be a dimension (e.g., year, rating 1-5)
            if distinct <= 20 or cardinality_ratio < 0.05:
                role = "dimension"
            else:
                role = "measure"
        elif dtype in ("string", "boolean"):
            role = "dimension"
        elif dtype == "datetime":
            role = "dimension"  # Dates are typically used for grouping/filtering
        else:
            role = "dimension"

        # Get top values (most common) - useful for both categorical and spotting data issues
        value_counts = series.value_counts().head(5)
        top_values_list = [f"{v} ({c})" for v, c in value_counts.items()]
        top_values = ", ".join(top_values_list) if top_values_list else None

        # Get sample values (first few unique non-null values for format reference)
        sample_unique = series.dropna().unique()[:3]
        sample_values = ", ".join(str(v) for v in sample_unique) if len(sample_unique) > 0 else None

        row = {
            "column": col,
            "dtype": dtype,
            "role": role,
            "non_null": non_null,
            "null_count": null_count,
            "distinct": distinct,
            "top_values": top_values,
            "sample_values": sample_values,
        }

        # Add numeric stats for numeric columns
        if dtype == "numeric":
            numeric_series = series.dropna()
            if len(numeric_series) > 0:
                row["min"] = round(float(numeric_series.min()), 4)
                row["max"] = round(float(numeric_series.max()), 4)
                row["mean"] = round(float(numeric_series.mean()), 4)
                row["std"] = round(float(numeric_series.std()), 4) if len(numeric_series) > 1 else 0.0
                row["p25"] = round(float(numeric_series.quantile(0.25)), 4)
                row["p50"] = round(float(numeric_series.quantile(0.50)), 4)
                row["p75"] = round(float(numeric_series.quantile(0.75)), 4)
            else:
                row["min"] = row["max"] = row["mean"] = row["std"] = None
                row["p25"] = row["p50"] = row["p75"] = None
        else:
            # Non-numeric columns don't have these stats
            row["min"] = row["max"] = row["mean"] = row["std"] = None
            row["p25"] = row["p50"] = row["p75"] = None

        stats_data.append(row)

    return {"data": stats_data}


def random_sample(
    _table: Union[List[Dict[str, Any]], str],
    n: int = 10,
    fraction: Optional[float] = None,
    seed: Optional[int] = None,
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Take a random sample of rows.

    Args:
        _table: List of records (rows) or string message for large tables
        n: Number of rows to sample (default: 10)
        fraction: Fraction of rows to sample (overrides n if provided)
        seed: Random seed for reproducibility
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing sampled rows
    """
    import pandas as pd

    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {"data": []}

    df = pd.DataFrame(table_data)

    # Determine sample size
    if fraction is not None:
        fraction = float(fraction)
        sample_size = max(1, int(len(df) * fraction))
    else:
        sample_size = min(int(n), len(df))

    # Sample
    sampled = df.sample(n=sample_size, random_state=seed)

    return {"data": sampled.to_dict(orient="records")}


def top_n(
    _table: Union[List[Dict[str, Any]], str],
    column: str,
    n: int = 10,
    ascending: bool = False,
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get top N rows by a column value.

    Args:
        _table: List of records (rows) or string message for large tables
        column: Column to sort by
        n: Number of rows to return (default: 10)
        ascending: Sort ascending instead of descending
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing top rows
    """
    import pandas as pd

    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {"data": []}

    df = pd.DataFrame(table_data)

    if column not in df.columns:
        return {"data": [], "error": f"Column '{column}' not found"}

    sorted_df = df.sort_values(by=column, ascending=ascending).head(int(n))

    return {"data": sorted_df.to_dict(orient="records")}


def group_aggregate(
    _table: Union[List[Dict[str, Any]], str],
    group_by: str,
    agg_column: str,
    agg_func: str = "sum",
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Group by a column and aggregate another.

    Args:
        _table: List of records (rows) or string message for large tables
        group_by: Column to group by
        agg_column: Column to aggregate
        agg_func: Aggregation function (sum, mean, count, min, max)
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing grouped results
    """
    import pandas as pd

    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {"data": []}

    df = pd.DataFrame(table_data)

    if group_by not in df.columns:
        return {"data": [], "error": f"Group column '{group_by}' not found"}
    if agg_column not in df.columns:
        return {"data": [], "error": f"Aggregate column '{agg_column}' not found"}

    agg_funcs = {"sum": "sum", "mean": "mean", "count": "count", "min": "min", "max": "max"}
    func = agg_funcs.get(agg_func.lower(), "sum")

    grouped = df.groupby(group_by)[agg_column].agg(func).reset_index()
    grouped.columns = [group_by, f"{agg_column}_{func}"]

    return {"data": grouped.to_dict(orient="records")}


def pivot_table(
    _table: Union[List[Dict[str, Any]], str],
    index: str,
    columns: str,
    values: str,
    agg_func: str = "sum",
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a pivot table.

    Args:
        _table: List of records (rows) or string message for large tables
        index: Column for row labels
        columns: Column for column labels
        values: Column for values
        agg_func: Aggregation function (sum, mean, count, min, max)
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing pivoted table
    """
    import pandas as pd

    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {"data": []}

    df = pd.DataFrame(table_data)

    for col in [index, columns, values]:
        if col not in df.columns:
            return {"data": [], "error": f"Column '{col}' not found"}

    agg_funcs = {"sum": "sum", "mean": "mean", "count": "count", "min": "min", "max": "max"}
    func = agg_funcs.get(agg_func.lower(), "sum")

    pivoted = pd.pivot_table(
        df,
        index=index,
        columns=columns,
        values=values,
        aggfunc=func,
        fill_value=0
    ).reset_index()

    # Flatten column names if multi-level
    if hasattr(pivoted.columns, 'levels'):
        pivoted.columns = ['_'.join(str(c) for c in col).strip('_') for col in pivoted.columns.values]

    return {"data": pivoted.to_dict(orient="records")}


def add_row_number(
    _table: Union[List[Dict[str, Any]], str],
    column_name: str = "row_num",
    start: int = 1,
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add a row number column.

    Args:
        _table: List of records (rows) or string message for large tables
        column_name: Name for the row number column
        start: Starting number (default: 1)
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing rows with row numbers
    """
    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {"data": []}

    result = []
    for i, row in enumerate(table_data, start=int(start)):
        new_row = {column_name: i}
        new_row.update(row)
        result.append(new_row)

    return {"data": result}


def deduplicate(
    _table: Union[List[Dict[str, Any]], str],
    columns: Optional[str] = None,
    keep: str = "first",
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Remove duplicate rows.

    Args:
        _table: List of records (rows) or string message for large tables
        columns: Columns to check for duplicates (comma-separated, default: all)
        keep: Which duplicate to keep ('first', 'last', 'none')
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing deduplicated rows
    """
    import pandas as pd

    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {"data": []}

    df = pd.DataFrame(table_data)

    subset = None
    if columns:
        subset = [c.strip() for c in columns.split(",")]

    keep_val = keep.lower() if keep.lower() in ("first", "last") else "first"
    if keep.lower() == "none":
        keep_val = False

    deduped = df.drop_duplicates(subset=subset, keep=keep_val)

    return {"data": deduped.to_dict(orient="records")}


def filter_rows(
    _table: Union[List[Dict[str, Any]], str],
    column: str,
    operator: str,
    value: Any,
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Filter rows based on a condition.

    Args:
        _table: List of records (rows) or string message for large tables
        column: Column to filter on
        operator: Comparison operator (eq, ne, gt, ge, lt, le, contains, startswith, endswith)
        value: Value to compare against
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing filtered rows
    """
    import pandas as pd

    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {"data": []}

    df = pd.DataFrame(table_data)

    if column not in df.columns:
        return {"data": [], "error": f"Column '{column}' not found"}

    col = df[column]
    op = operator.lower()

    # Try to convert value to appropriate type
    try:
        if col.dtype in ['int64', 'float64']:
            value = float(value)
    except (ValueError, TypeError):
        pass

    if op == "eq":
        mask = col == value
    elif op == "ne":
        mask = col != value
    elif op == "gt":
        mask = col > value
    elif op == "ge":
        mask = col >= value
    elif op == "lt":
        mask = col < value
    elif op == "le":
        mask = col <= value
    elif op == "contains":
        mask = col.astype(str).str.contains(str(value), case=False, na=False)
    elif op == "startswith":
        mask = col.astype(str).str.startswith(str(value), na=False)
    elif op == "endswith":
        mask = col.astype(str).str.endswith(str(value), na=False)
    else:
        return {"data": [], "error": f"Unknown operator '{operator}'"}

    filtered = df[mask]

    return {"data": filtered.to_dict(orient="records")}


def passthrough(
    _table: Union[List[Dict[str, Any]], str],
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Pass data through unchanged.

    Used by the PASS cascade in CHOOSE branches when no action is needed
    but the pipeline should continue.

    Args:
        _table: List of records (rows) or string message for large tables
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables
        **kwargs: Any additional arguments (ignored)

    Returns:
        Dict with 'data' key containing original rows unchanged
    """
    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {"data": []}

    return {"data": table_data}


# =============================================================================
# Mermaid Visualization Functions
# =============================================================================

import re


def _sanitize_mermaid_node_id(text: str) -> str:
    """
    Sanitize text for use as a Mermaid node ID.

    - Replace spaces and special chars with underscores
    - Ensure it starts with a letter
    - Keep it reasonably short
    """
    if not text:
        return "empty"

    # Replace problematic characters
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', str(text))

    # Ensure starts with letter
    if sanitized and not sanitized[0].isalpha():
        sanitized = 'n_' + sanitized

    # Truncate if too long
    if len(sanitized) > 40:
        sanitized = sanitized[:40]

    return sanitized or "node"


def _escape_mermaid_label(text: str) -> str:
    """Escape text for use in Mermaid labels."""
    if not text:
        return ""
    # Escape quotes and pipes which have special meaning
    return str(text).replace('"', "'").replace('|', '/').replace('\n', ' ')


def mermaid_triples(
    _table: Union[List[Dict[str, Any]], str],
    subject_col: str = "subject",
    predicate_col: str = "predicate",
    object_col: str = "object",
    direction: str = "LR",
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convert triples data to Mermaid graph syntax.

    Args:
        _table: List of records containing subject/predicate/object triples or string for large tables
        subject_col: Column name for subject (default: "subject")
        predicate_col: Column name for predicate (default: "predicate")
        object_col: Column name for object (default: "object")
        direction: Graph direction - LR, RL, TB, BT (default: "LR")
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing single row with mermaid output
    """
    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        mermaid = f"graph {direction}\n    empty[No data]"
        return {"data": [{"mermaid": mermaid, "format": "mermaid-graph"}]}

    lines = [f"graph {direction}"]

    # Track unique nodes for labeling
    nodes_seen = set()
    edges = []

    for row in table_data:
        subj = row.get(subject_col, "")
        pred = row.get(predicate_col, "")
        obj = row.get(object_col, "")

        if not subj or not obj:
            continue

        subj_id = _sanitize_mermaid_node_id(subj)
        obj_id = _sanitize_mermaid_node_id(obj)
        pred_label = _escape_mermaid_label(pred)

        # Add node definitions if first time seeing them
        if subj_id not in nodes_seen:
            nodes_seen.add(subj_id)
            lines.append(f'    {subj_id}["{_escape_mermaid_label(subj)}"]')

        if obj_id not in nodes_seen:
            nodes_seen.add(obj_id)
            lines.append(f'    {obj_id}["{_escape_mermaid_label(obj)}"]')

        # Add edge
        edges.append(f"    {subj_id} -->|{pred_label}| {obj_id}")

    lines.extend(edges)

    mermaid = "\n".join(lines)
    return {"data": [{"mermaid": mermaid, "format": "mermaid-graph"}]}


def mermaid_timeline(
    _table: Union[List[Dict[str, Any]], str],
    timestamp_col: str = "timestamp",
    event_col: str = "event",
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convert timeline data to Mermaid timeline syntax.

    Args:
        _table: List of records containing timestamp/event data or string for large tables
        timestamp_col: Column name for timestamp (default: "timestamp")
        event_col: Column name for event description (default: "event")
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' key containing single row with mermaid output
    """
    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        mermaid = "timeline\n    title Empty\n    No events"
        return {"data": [{"mermaid": mermaid, "format": "mermaid-timeline"}]}

    lines = ["timeline"]

    for row in table_data:
        ts = row.get(timestamp_col, "")
        event = row.get(event_col, "")

        if ts and event:
            lines.append(f"    {_escape_mermaid_label(ts)} : {_escape_mermaid_label(event)}")

    mermaid = "\n".join(lines)
    return {"data": [{"mermaid": mermaid, "format": "mermaid-timeline"}]}


def render_canvas(
    _table: Union[List[Dict[str, Any]], str],
    layout_type: str = "grid",
    dim1: int = 2,
    dim2: int = 2,
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compose multiple panels into a canvas layout for visualization.

    This is the composition operator for LARS visual outputs. It takes
    a table of panels (each with content and position) and produces
    a single canvas JSON structure that frontends can render.

    Supports two layout modes:

    GRID Layout (cell-based):
        Args:
            layout_type: "grid"
            dim1: Number of grid columns
            dim2: Number of grid rows
            _table columns: name, content, col, row, colspan, rowspan,
                           [on_select, multi_select, hide_border, hide_title]

    FLOATING Layout (pixel-based):
        Args:
            layout_type: "floating"
            dim1: Canvas width in pixels
            dim2: Canvas height in pixels
            _table columns: name, content, x, y, width, height,
                           [on_select, multi_select, hide_border, hide_title]

    Optional columns (both layouts):
        on_select: Cascade template for click interactions (e.g., "@param_set('cat', label)")
        multi_select: Boolean, true for checkbox-style multi-select
        hide_border: Boolean, true to hide panel border
        hide_title: Boolean, true to hide panel header

    Returns:
        Dict with 'data' key containing single row with canvas JSON:
        {
            "data": [{
                "canvas": {
                    "layout": {"type": "grid"|"floating", ...},
                    "panels": [...]
                },
                "format": "canvas"
            }]
        }

    Example SQL usage:
        -- GRID layout with basic panels
        SELECT * FROM CANVAS(
            PANEL('Graph', 1, 1, graph_data),
            PANEL('Table', 2, 1, table_data)
        ) WITH GRID(2, 1)

        -- GRID layout with interactive panels
        SELECT * FROM CANVAS(
            PANEL('Filter', 1, 1, categories, on_select := '@param_set(''cat'', category)'),
            PANEL('Chart', 2, 1, chart_data, hide_border := true, hide_title := true)
        ) WITH GRID(2, 1)

        -- FLOATING layout
        SELECT * FROM CANVAS(
            PANEL('Chart', 50, 50, chart_data, width := 400, height := 300),
            PANEL('Info', 500, 50, info_data, width := 200, height := 150)
        ) WITH FLOATING(800, 600)

    Note:
        Results are cached by input hash since this is a pure transformation.
    """
    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    # Check cache first - pure function, same inputs = same output
    cache_key = _render_canvas_cache_key(table_data, layout_type, dim1, dim2)
    if cache_key in _render_canvas_cache:
        _render_canvas_stats['hits'] += 1
        logger.debug(f"render_canvas cache HIT (stats: {get_render_canvas_cache_stats()})")
        return _render_canvas_cache[cache_key]

    # Normalize layout_type (may come quoted from SQL)
    layout_type = str(layout_type).strip("'\"").lower()
    is_floating = layout_type == "floating"

    if not table_data:
        if is_floating:
            layout = {"type": "floating", "width": int(dim1), "height": int(dim2)}
        else:
            layout = {"type": "grid", "cols": int(dim1), "rows": int(dim2)}
        return {
            "data": [{
                "canvas": {"layout": layout, "panels": []},
                "format": "canvas"
            }]
        }

    # Validate: check for duplicate panel names
    panel_names = [row.get("name", f"Panel_{i}") for i, row in enumerate(table_data)]
    duplicates = [name for name in set(panel_names) if panel_names.count(name) > 1]
    if duplicates:
        return {
            "data": [{
                "error": f"Duplicate panel names: {', '.join(duplicates)}. Each panel must have a unique name.",
                "format": "error"
            }]
        }

    panels = []

    for row_data in table_data:
        name = row_data.get("name", "Untitled")
        content = row_data.get("content")

        # Detect panel type from content
        panel_type = _detect_panel_type(content)

        # Parse content if it's a JSON string
        if isinstance(content, str):
            try:
                content = json.loads(content)
                # Re-detect type after parsing
                panel_type = _detect_panel_type(content)
            except (json.JSONDecodeError, TypeError):
                # Keep as string, treat as text
                pass

        panel = {
            "name": str(name),
            "content": content,
            "type": panel_type,
        }

        if is_floating:
            # FLOATING: x, y, width, height
            panel["position"] = {
                "x": int(row_data.get("x", 0)),
                "y": int(row_data.get("y", 0)),
                "width": int(row_data.get("width", 200)),
                "height": int(row_data.get("height", 150))
            }
        else:
            # GRID: col, row, colspan, rowspan
            panel["cell"] = [
                int(row_data.get("col", 1)),
                int(row_data.get("row", 1)),
                int(row_data.get("colspan", 1)),
                int(row_data.get("rowspan", 1))
            ]

        # Interaction options
        on_select = row_data.get("on_select")
        if on_select and on_select != "NULL":
            panel["on_select"] = str(on_select)
            panel["multi_select"] = bool(row_data.get("multi_select", False))
            # Extract select_field from template: @param_set('key', field) -> field
            # This is used for toggle/deselect detection
            import re
            match = re.search(r"@param_set\s*\(\s*['\"][^'\"]+['\"]\s*,\s*(\w+)\s*\)", on_select)
            if match:
                panel["select_field"] = match.group(1)

        # Display options
        if row_data.get("hide_border"):
            panel["hide_border"] = True
        if row_data.get("hide_title"):
            panel["hide_title"] = True

        panels.append(panel)

    # Build layout metadata
    if is_floating:
        layout = {
            "type": "floating",
            "width": int(dim1),
            "height": int(dim2)
        }
    else:
        layout = {
            "type": "grid",
            "cols": int(dim1),
            "rows": int(dim2)
        }

    canvas = {
        "layout": layout,
        "panels": panels
    }

    result = {
        "data": [{
            "canvas": canvas,
            "format": "canvas"
        }]
    }

    # Cache the result
    if len(_render_canvas_cache) >= _RENDER_CANVAS_CACHE_MAX:
        # Simple eviction: clear half
        keys = list(_render_canvas_cache.keys())
        for k in keys[:len(keys)//2]:
            del _render_canvas_cache[k]
    _render_canvas_cache[cache_key] = result
    _render_canvas_stats['misses'] += 1
    logger.debug(f"render_canvas cache MISS (stats: {get_render_canvas_cache_stats()})")

    return result


def _detect_panel_type(content: Any) -> str:
    """
    Detect the panel type from content structure.

    Returns one of:
    - 'mermaid-graph': Mermaid graph diagram
    - 'mermaid-timeline': Mermaid timeline
    - 'data-grid': Array of records (table data)
    - 'text': Plain text or unknown format
    """
    if content is None:
        return "text"

    # Check for mermaid format (dict with 'mermaid' and 'format' keys)
    if isinstance(content, dict):
        if "mermaid" in content:
            fmt = content.get("format", "")
            if "timeline" in fmt:
                return "mermaid-timeline"
            return "mermaid-graph"
        # Single record - could be scalar result
        return "text"

    # Check for data grid (list of dicts)
    if isinstance(content, list):
        if len(content) > 0 and isinstance(content[0], dict):
            first = content[0]
            # Check if this is a single-row mermaid result from a pipeline
            if len(content) == 1 and "mermaid" in first:
                fmt = first.get("format", "")
                if "timeline" in fmt:
                    return "mermaid-timeline"
                return "mermaid-graph"
            return "data-grid"
        return "text"

    # String content
    if isinstance(content, str):
        # Check if it looks like mermaid syntax
        if content.strip().startswith(("graph ", "flowchart ", "timeline")):
            if content.strip().startswith("timeline"):
                return "mermaid-timeline"
            return "mermaid-graph"
        return "text"

    return "text"


# =============================================================================
# Property Graph Construction
# =============================================================================


def to_property_graph(
    _table: Union[List[Dict[str, Any]], str],
    graph_name: str,
    subject_col: str = "subject",
    predicate_col: str = "predicate",
    object_col: str = "object",
    evidence_col: str = "evidence",
    _table_columns: Optional[List[str]] = None,
    _table_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convert triples data to DuckPGQ property graph tables.

    Creates:
    - {graph_name}_nodes: Vertex table with unique entity IDs
    - {graph_name}_edges: Edge table with source/dest references and properties
    - {graph_name}: Property graph definition (CREATE PROPERTY GRAPH)

    Args:
        _table: List of records containing triples data or string for large tables
        graph_name: Name prefix for created tables/graph
        subject_col: Column name for subject (default: "subject")
        predicate_col: Column name for predicate (default: "predicate")
        object_col: Column name for object (default: "object")
        evidence_col: Column name for evidence (default: "evidence", optional)
        _table_columns: Available column names
        _table_path: Path to parquet file for large tables

    Returns:
        Dict with 'data' containing creation status and example queries
    """
    # Resolve table data (handles both inline and parquet file cases)
    table_data = _resolve_table(_table, _table_path)

    if not table_data:
        return {
            "data": [{
                "status": "error",
                "message": "No triples data provided",
                "graph_name": graph_name
            }]
        }

    # Sanitize graph name for SQL identifiers
    safe_name = _sanitize_sql_identifier(graph_name)
    nodes_table = f"{safe_name}_nodes"
    edges_table = f"{safe_name}_edges"

    # Check if evidence column exists in the data
    has_evidence = _table_columns and evidence_col in _table_columns
    if not has_evidence and table_data:
        has_evidence = evidence_col in table_data[0]

    # Collect unique entities (both subjects and objects)
    entities = set()
    edges = []

    for row in table_data:
        subj = row.get(subject_col, "")
        pred = row.get(predicate_col, "")
        obj = row.get(object_col, "")
        evidence = row.get(evidence_col, "") if has_evidence else ""

        if subj and obj:
            entities.add(str(subj))
            entities.add(str(obj))
            edges.append({
                "source": str(subj),
                "predicate": str(pred),
                "target": str(obj),
                "evidence": str(evidence) if evidence else None
            })

    if not entities:
        return {
            "data": [{
                "status": "error",
                "message": "No valid triples found (need subject and object)",
                "graph_name": graph_name
            }]
        }

    # Build SQL statements for graph creation
    # These will be executed by the pipeline runner in the current connection

    # 1. Create nodes table
    nodes_sql = f"""
CREATE OR REPLACE TABLE {nodes_table} AS
SELECT DISTINCT entity AS id, entity AS name
FROM (
    SELECT {_sql_quote(subject_col)} AS entity FROM (SELECT * FROM _lars_pipeline_input)
    UNION
    SELECT {_sql_quote(object_col)} AS entity FROM (SELECT * FROM _lars_pipeline_input)
)
"""

    # 2. Create edges table
    if has_evidence:
        edges_sql = f"""
CREATE OR REPLACE TABLE {edges_table} AS
SELECT
    {_sql_quote(subject_col)} AS source_id,
    {_sql_quote(predicate_col)} AS predicate,
    {_sql_quote(object_col)} AS target_id,
    {_sql_quote(evidence_col)} AS evidence
FROM _lars_pipeline_input
WHERE {_sql_quote(subject_col)} IS NOT NULL
  AND {_sql_quote(object_col)} IS NOT NULL
"""
    else:
        edges_sql = f"""
CREATE OR REPLACE TABLE {edges_table} AS
SELECT
    {_sql_quote(subject_col)} AS source_id,
    {_sql_quote(predicate_col)} AS predicate,
    {_sql_quote(object_col)} AS target_id
FROM _lars_pipeline_input
WHERE {_sql_quote(subject_col)} IS NOT NULL
  AND {_sql_quote(object_col)} IS NOT NULL
"""

    # 3. Create property graph (DuckPGQ)
    # Note: Both vertex and edge tables need LABEL for SQL/PGQ MATCH queries
    graph_sql = f"""
CREATE OR REPLACE PROPERTY GRAPH {safe_name}
VERTEX TABLES (
    {nodes_table} LABEL entity
)
EDGE TABLES (
    {edges_table}
        SOURCE KEY (source_id) REFERENCES {nodes_table}(id)
        DESTINATION KEY (target_id) REFERENCES {nodes_table}(id)
        LABEL has_relation
)
"""

    # Example query for user
    example_query = f"""
-- Query the graph with SQL/PGQ
SELECT * FROM GRAPH_TABLE({safe_name}
    MATCH (a:entity)-[r:has_relation]->(b:entity)
    COLUMNS (a.id AS source, r.predicate AS relation, b.id AS target{', r.evidence AS evidence' if has_evidence else ''})
)
LIMIT 20
"""

    return {
        "data": [{
            "status": "success",
            "graph_name": safe_name,
            "nodes_table": nodes_table,
            "edges_table": edges_table,
            "node_count": len(entities),
            "edge_count": len(edges),
            "has_evidence": has_evidence,
            "message": f"Created property graph '{safe_name}' with {len(entities)} nodes and {len(edges)} edges"
        }],
        # Return SQL statements for pipeline runner to execute
        "_execute_sql": [nodes_sql, edges_sql, graph_sql],
        "_example_query": example_query
    }


def _sanitize_sql_identifier(name: str) -> str:
    """Sanitize a string for use as SQL identifier."""
    import re
    # Replace non-alphanumeric with underscore
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    # Ensure doesn't start with number
    if safe and safe[0].isdigit():
        safe = f"g_{safe}"
    return safe.lower() or "graph"


def _sql_quote(identifier: str) -> str:
    """Quote a SQL identifier if needed."""
    # Simple identifiers don't need quoting
    import re
    if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', identifier):
        return identifier
    # Quote with double quotes, escape any existing quotes
    return f'"{identifier.replace(chr(34), chr(34)+chr(34))}"'


# =============================================================================
# Text Preprocessing Utilities
# =============================================================================

def strip_base64_images(
    text: str,
    placeholder: str = "[IMAGE]"
) -> Dict[str, Any]:
    """
    Strip base64-encoded images from text, replacing with placeholder.

    This is useful for preprocessing text before sending to LLMs that
    don't support multimodal input (images). Base64 images in markdown
    are detected and removed.

    Patterns handled:
    - data:image/...;base64,... (inline data URIs)
    - ![alt](data:image/...) (markdown image syntax)

    Args:
        text: Input text potentially containing base64 images
        placeholder: Text to replace images with (default: "[IMAGE]")

    Returns:
        Dict with 'text' (cleaned) and 'images_removed' (count)

    Usage in cascade:
        - name: preprocess
          deterministic: true
          tool: python:lars.pipeline_tools.strip_base64_images
          inputs:
            text: "{{ input.text }}"
    """
    import re

    if not text or not isinstance(text, str):
        return {"text": text or "", "images_removed": 0}

    images_removed = 0

    # Pattern 1: Markdown image with base64 data URI
    # ![alt text](data:image/png;base64,...)
    markdown_pattern = r'!\[[^\]]*\]\(data:image/[^;]+;base64,[A-Za-z0-9+/=]+\)'
    matches = re.findall(markdown_pattern, text)
    images_removed += len(matches)
    text = re.sub(markdown_pattern, placeholder, text)

    # Pattern 2: Standalone data URI (not in markdown)
    # data:image/png;base64,iVBORw0KGgo...
    # Be careful not to match inside URLs or other contexts
    standalone_pattern = r'(?<!["\'])data:image/[^;]+;base64,[A-Za-z0-9+/=]+'
    matches = re.findall(standalone_pattern, text)
    images_removed += len(matches)
    text = re.sub(standalone_pattern, placeholder, text)

    # Pattern 3: HTML img tags with base64 src
    # <img src="data:image/png;base64,..." />
    html_img_pattern = r'<img[^>]*src=["\']data:image/[^;]+;base64,[A-Za-z0-9+/=]+["\'][^>]*/?>'
    matches = re.findall(html_img_pattern, text, re.IGNORECASE)
    images_removed += len(matches)
    text = re.sub(html_img_pattern, placeholder, text, flags=re.IGNORECASE)

    return {
        "text": text,
        "images_removed": images_removed
    }
