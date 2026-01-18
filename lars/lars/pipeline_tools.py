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
          columns: "{{ input.columns }}"
"""

from typing import Any, Dict, List, Optional
import json


def compute_stats(
    _table: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute descriptive statistics for numeric columns.

    Args:
        _table: List of records (rows)
        columns: Specific columns to analyze (default: all numeric)
        _table_columns: Available column names

    Returns:
        Dict with 'data' key containing stats table
    """
    import pandas as pd

    if not _table:
        return {"data": [{"error": "No data provided"}]}

    df = pd.DataFrame(_table)

    # Select columns to analyze
    if columns:
        if isinstance(columns, str):
            columns = [c.strip() for c in columns.split(",")]
        numeric_cols = [c for c in columns if c in df.columns]
    else:
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()

    if not numeric_cols:
        return {"data": [{"error": "No numeric columns found"}]}

    # Compute stats
    stats_data = []
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) == 0:
            continue

        stats_data.append({
            "column": col,
            "count": int(len(series)),
            "mean": round(float(series.mean()), 4),
            "std": round(float(series.std()), 4) if len(series) > 1 else 0,
            "min": float(series.min()),
            "p25": float(series.quantile(0.25)),
            "p50": float(series.quantile(0.50)),
            "p75": float(series.quantile(0.75)),
            "max": float(series.max()),
        })

    return {"data": stats_data}


def random_sample(
    _table: List[Dict[str, Any]],
    n: int = 10,
    fraction: Optional[float] = None,
    seed: Optional[int] = None,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Take a random sample of rows.

    Args:
        _table: List of records (rows)
        n: Number of rows to sample (default: 10)
        fraction: Fraction of rows to sample (overrides n if provided)
        seed: Random seed for reproducibility
        _table_columns: Available column names

    Returns:
        Dict with 'data' key containing sampled rows
    """
    import pandas as pd

    if not _table:
        return {"data": []}

    df = pd.DataFrame(_table)

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
    _table: List[Dict[str, Any]],
    column: str,
    n: int = 10,
    ascending: bool = False,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Get top N rows by a column value.

    Args:
        _table: List of records (rows)
        column: Column to sort by
        n: Number of rows to return (default: 10)
        ascending: Sort ascending instead of descending
        _table_columns: Available column names

    Returns:
        Dict with 'data' key containing top rows
    """
    import pandas as pd

    if not _table:
        return {"data": []}

    df = pd.DataFrame(_table)

    if column not in df.columns:
        return {"data": [], "error": f"Column '{column}' not found"}

    sorted_df = df.sort_values(by=column, ascending=ascending).head(int(n))

    return {"data": sorted_df.to_dict(orient="records")}


def group_aggregate(
    _table: List[Dict[str, Any]],
    group_by: str,
    agg_column: str,
    agg_func: str = "sum",
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Group by a column and aggregate another.

    Args:
        _table: List of records (rows)
        group_by: Column to group by
        agg_column: Column to aggregate
        agg_func: Aggregation function (sum, mean, count, min, max)
        _table_columns: Available column names

    Returns:
        Dict with 'data' key containing grouped results
    """
    import pandas as pd

    if not _table:
        return {"data": []}

    df = pd.DataFrame(_table)

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
    _table: List[Dict[str, Any]],
    index: str,
    columns: str,
    values: str,
    agg_func: str = "sum",
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Create a pivot table.

    Args:
        _table: List of records (rows)
        index: Column for row labels
        columns: Column for column labels
        values: Column for values
        agg_func: Aggregation function (sum, mean, count, min, max)
        _table_columns: Available column names

    Returns:
        Dict with 'data' key containing pivoted table
    """
    import pandas as pd

    if not _table:
        return {"data": []}

    df = pd.DataFrame(_table)

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
    _table: List[Dict[str, Any]],
    column_name: str = "row_num",
    start: int = 1,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Add a row number column.

    Args:
        _table: List of records (rows)
        column_name: Name for the row number column
        start: Starting number (default: 1)
        _table_columns: Available column names

    Returns:
        Dict with 'data' key containing rows with row numbers
    """
    if not _table:
        return {"data": []}

    result = []
    for i, row in enumerate(_table, start=int(start)):
        new_row = {column_name: i}
        new_row.update(row)
        result.append(new_row)

    return {"data": result}


def deduplicate(
    _table: List[Dict[str, Any]],
    columns: Optional[str] = None,
    keep: str = "first",
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Remove duplicate rows.

    Args:
        _table: List of records (rows)
        columns: Columns to check for duplicates (comma-separated, default: all)
        keep: Which duplicate to keep ('first', 'last', 'none')
        _table_columns: Available column names

    Returns:
        Dict with 'data' key containing deduplicated rows
    """
    import pandas as pd

    if not _table:
        return {"data": []}

    df = pd.DataFrame(_table)

    subset = None
    if columns:
        subset = [c.strip() for c in columns.split(",")]

    keep_val = keep.lower() if keep.lower() in ("first", "last") else "first"
    if keep.lower() == "none":
        keep_val = False

    deduped = df.drop_duplicates(subset=subset, keep=keep_val)

    return {"data": deduped.to_dict(orient="records")}


def filter_rows(
    _table: List[Dict[str, Any]],
    column: str,
    operator: str,
    value: Any,
    _table_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Filter rows based on a condition.

    Args:
        _table: List of records (rows)
        column: Column to filter on
        operator: Comparison operator (eq, ne, gt, ge, lt, le, contains, startswith, endswith)
        value: Value to compare against
        _table_columns: Available column names

    Returns:
        Dict with 'data' key containing filtered rows
    """
    import pandas as pd

    if not _table:
        return {"data": []}

    df = pd.DataFrame(_table)

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
    _table: List[Dict[str, Any]],
    _table_columns: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Pass data through unchanged.

    Used by the PASS cascade in CHOOSE branches when no action is needed
    but the pipeline should continue.

    Args:
        _table: List of records (rows)
        _table_columns: Available column names
        **kwargs: Any additional arguments (ignored)

    Returns:
        Dict with 'data' key containing original rows unchanged
    """
    if not _table:
        return {"data": []}

    return {"data": _table}
