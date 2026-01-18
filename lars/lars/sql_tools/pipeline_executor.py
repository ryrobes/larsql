"""
Pipeline Executor: Execute pipeline stages on query results.

This module handles the execution of PIPELINE-shaped cascades on DataFrames
after the base SQL query has been executed.

Data flow:
    1. Base SQL is executed → initial DataFrame
    2. Each pipeline stage receives the DataFrame and returns a transformed DataFrame
    3. Final result is optionally saved to INTO table

DataFrame serialization strategy:
    - Small tables (<1000 rows): Pass as JSON records in `_table`
    - Large tables (>=1000 rows): Write to temp parquet, pass path in `_table_path`
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .pipeline_parser import PipelineStage

log = logging.getLogger(__name__)

# Threshold for switching from inline JSON to parquet file
LARGE_TABLE_THRESHOLD = 1000


def _make_json_serializable(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert DataFrame to use JSON-serializable types.

    Handles:
        - Decimal → float
        - numpy types → Python native types
        - datetime/timestamp → ISO string
        - bytes → base64 string
    """
    import base64
    from datetime import datetime, date

    df = df.copy()

    for col in df.columns:
        # Check first non-null value to determine type
        non_null = df[col].dropna()
        if len(non_null) == 0:
            continue

        sample = non_null.iloc[0]

        # Handle Decimal
        if isinstance(sample, Decimal):
            df[col] = df[col].apply(lambda x: float(x) if x is not None else None)
        # Handle numpy integer types
        elif isinstance(sample, (np.integer,)):
            df[col] = df[col].apply(lambda x: int(x) if x is not None else None)
        # Handle numpy float types
        elif isinstance(sample, (np.floating,)):
            df[col] = df[col].apply(lambda x: float(x) if x is not None else None)
        # Handle bytes
        elif isinstance(sample, bytes):
            df[col] = df[col].apply(lambda x: base64.b64encode(x).decode('utf-8') if x is not None else None)
        # Handle datetime/timestamp - convert to ISO string
        elif isinstance(sample, (datetime, date, pd.Timestamp)):
            df[col] = df[col].apply(lambda x: x.isoformat() if x is not None else None)

    return df


@dataclass
class PipelineExecutionError(Exception):
    """Raised when a pipeline stage fails."""
    stage_name: str
    stage_index: int
    inner_error: Exception

    def __str__(self) -> str:
        return (
            f"Pipeline stage '{self.stage_name}' (index {self.stage_index}) failed: "
            f"{self.inner_error}"
        )


@dataclass
class PipelineContext:
    """Context passed to each pipeline stage."""
    stage_index: int
    total_stages: int
    previous_stage: Optional[str]
    original_query: Optional[str]
    session_id: str
    caller_id: Optional[str]


def _serialize_dataframe(
    df: pd.DataFrame,
    context: PipelineContext
) -> Dict[str, Any]:
    """
    Serialize a DataFrame for passing to a cascade.

    Returns a dict with:
        - _table: JSON records (for small tables) or message about file
        - _table_path: Path to parquet file (for large tables)
        - _table_columns: List of column names
        - _table_row_count: Number of rows
        - _pipeline_context: Execution context
    """
    row_count = len(df)
    columns = list(df.columns)

    result: Dict[str, Any] = {
        "_table_columns": columns,
        "_table_row_count": row_count,
        "_pipeline_context": {
            "stage_index": context.stage_index,
            "total_stages": context.total_stages,
            "previous_stage": context.previous_stage,
            "original_query": context.original_query,
        }
    }

    if row_count < LARGE_TABLE_THRESHOLD:
        # Small table: inline as JSON records
        # Convert to JSON-serializable types first (handles Decimal, numpy types, etc.)
        serializable_df = _make_json_serializable(df)
        result["_table"] = serializable_df.to_dict(orient="records")
    else:
        # Large table: write to temp parquet
        temp_dir = Path(tempfile.gettempdir()) / "lars_pipeline"
        temp_dir.mkdir(exist_ok=True)

        parquet_path = temp_dir / f"pipeline_{context.session_id}_{context.stage_index}.parquet"
        df.to_parquet(parquet_path, index=False)

        result["_table"] = f"[Large table with {row_count} rows - see _table_path]"
        result["_table_path"] = str(parquet_path)

    return result


def _deserialize_result(
    result: Any,
    original_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Deserialize cascade output back to a DataFrame.

    Handles:
        - Dict with 'data' key containing list of records
        - Dict with 'rows' key containing list of records
        - Dict with '_table' key containing list of records
        - List of records directly
        - Path to parquet file
        - JSON string
        - None or empty: returns original DataFrame (for side-effect stages)
    """
    if result is None:
        return original_df

    # Handle string result (could be JSON or parquet path)
    if isinstance(result, str):
        # Check if it's a parquet file path
        if result.endswith(".parquet") and Path(result).exists():
            return pd.read_parquet(result)

        # Try parsing as JSON
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            # Not JSON, return original
            log.warning(f"[pipeline] Could not parse result as JSON, returning original DataFrame")
            return original_df

    # Handle dict results
    if isinstance(result, dict):
        # Look for data in common keys (priority order)
        for key in ("data", "rows", "_table", "records", "results", "summary_table", "table", "output"):
            if key in result and isinstance(result[key], list):
                result = result[key]
                break
        else:
            # Check if all values are scalars (single-row result)
            if all(not isinstance(v, (dict, list)) for v in result.values()):
                result = [result]
            # Check if this looks like an analysis result - flatten to single row
            elif any(k in result for k in ("answer", "analysis", "summary", "insight")):
                # Flatten complex analysis to a single-row table
                flat_row = {}
                for k, v in result.items():
                    if isinstance(v, str):
                        flat_row[k] = v
                    elif isinstance(v, list):
                        # Join list items into a string, or take count
                        if all(isinstance(x, str) for x in v):
                            flat_row[k] = "; ".join(v)
                        else:
                            flat_row[f"{k}_count"] = len(v)
                            flat_row[k] = json.dumps(v)
                    elif isinstance(v, dict):
                        flat_row[k] = json.dumps(v)
                    else:
                        flat_row[k] = v
                result = [flat_row]
                log.info(f"[pipeline] Flattened analysis result to single row with keys: {list(flat_row.keys())}")
            else:
                log.warning(f"[pipeline] Dict result has no data key, returning original DataFrame")
                return original_df

    # Handle list of records
    if isinstance(result, list):
        if not result:
            return original_df
        return pd.DataFrame(result)

    log.warning(f"[pipeline] Unknown result type {type(result)}, returning original DataFrame")
    return original_df


def execute_pipeline_stages(
    stages: List[PipelineStage],
    initial_df: pd.DataFrame,
    session_id: str,
    caller_id: Optional[str] = None,
    original_query: Optional[str] = None,
) -> pd.DataFrame:
    """
    Execute pipeline chain, returning final DataFrame.

    Args:
        stages: List of pipeline stages to execute
        initial_df: Initial DataFrame from base SQL execution
        session_id: Session ID for cascade execution
        caller_id: Optional caller ID for tracking
        original_query: Optional original SQL for context

    Returns:
        Final transformed DataFrame

    Raises:
        PipelineExecutionError: If any stage fails
    """
    from ..semantic_sql.registry import get_pipeline_cascade, list_pipeline_cascades

    current_df = initial_df
    previous_stage: Optional[str] = None

    for idx, stage in enumerate(stages):
        log.info(f"[pipeline] Executing stage {idx + 1}/{len(stages)}: {stage.name}")

        # Look up the pipeline cascade
        cascade_entry = get_pipeline_cascade(stage.name)
        if not cascade_entry:
            available = list_pipeline_cascades()
            available_str = ", ".join(available) if available else "(none registered)"
            raise PipelineExecutionError(
                stage_name=stage.name,
                stage_index=idx,
                inner_error=ValueError(
                    f"Unknown pipeline stage '{stage.name}'. "
                    f"Available PIPELINE cascades: {available_str}"
                )
            )

        # Build execution context
        context = PipelineContext(
            stage_index=idx,
            total_stages=len(stages),
            previous_stage=previous_stage,
            original_query=original_query,
            session_id=session_id,
            caller_id=caller_id,
        )

        # Serialize DataFrame for cascade input
        serialized = _serialize_dataframe(current_df, context)

        # Add stage arguments using the cascade's declared argument names
        cascade_inputs = serialized.copy()
        if stage.args:
            # Get argument names from the cascade's sql_function config
            sql_func_args = cascade_entry.sql_function.get("args", [])
            # Filter out special args like _table that are handled separately
            user_arg_names = [
                arg["name"] for arg in sql_func_args
                if not arg["name"].startswith("_")
            ]

            # Map stage args to their declared names
            for i, arg_value in enumerate(stage.args):
                if i < len(user_arg_names):
                    cascade_inputs[user_arg_names[i]] = arg_value
                else:
                    # Fallback for extra args
                    cascade_inputs[f"arg{i}"] = arg_value

        # Execute the cascade
        try:
            from ..runner import LARSRunner
            from .. import _register_all_skills

            _register_all_skills()

            stage_session_id = f"{session_id}_stage_{idx}"
            runner = LARSRunner(
                cascade_entry.cascade_path,
                session_id=stage_session_id,
                caller_id=caller_id
            )

            result = runner.run(input_data=cascade_inputs)

            # Extract output from cascade
            from ..semantic_sql.executor import _extract_cascade_output
            output = _extract_cascade_output(result)

            # Deserialize back to DataFrame
            current_df = _deserialize_result(output, current_df)

            log.info(f"[pipeline] Stage {stage.name} completed: {len(current_df)} rows")

        except Exception as e:
            raise PipelineExecutionError(
                stage_name=stage.name,
                stage_index=idx,
                inner_error=e
            )

        previous_stage = stage.name

    return current_df


def _save_to_table(duckdb_conn: Any, df: pd.DataFrame, table_name: str) -> None:
    """Save DataFrame to a DuckDB table."""
    log.info(f"[pipeline] Saving {len(df)} rows to table: {table_name}")
    try:
        # Register as a temp table first, then create permanent table
        duckdb_conn.register("_pipeline_result", df)
        duckdb_conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _pipeline_result")
        duckdb_conn.unregister("_pipeline_result")
        log.info(f"[pipeline] Created table: {table_name}")
    except Exception as e:
        log.error(f"[pipeline] Failed to create table {table_name}: {e}")
        raise


def execute_pipeline_with_into(
    stages: List[PipelineStage],
    initial_df: pd.DataFrame,
    into_table: Optional[str],
    duckdb_conn: Any,
    session_id: str,
    caller_id: Optional[str] = None,
    original_query: Optional[str] = None,
    base_into_table: Optional[str] = None,
) -> pd.DataFrame:
    """
    Execute pipeline and optionally save to INTO tables (per-stage or final).

    Args:
        stages: List of pipeline stages (each may have its own into_table)
        initial_df: Initial DataFrame from base SQL
        into_table: Final table name (legacy, prefer stage.into_table)
        duckdb_conn: DuckDB connection for table creation
        session_id: Session ID
        caller_id: Optional caller ID
        original_query: Optional original SQL
        base_into_table: Optional table name for base SQL result (before stages)

    Returns:
        Final DataFrame
    """
    # Save base SQL result if base_into_table specified
    if base_into_table and duckdb_conn is not None:
        _save_to_table(duckdb_conn, initial_df, base_into_table)

    # Execute pipeline stages with per-stage INTO handling
    from ..semantic_sql.registry import get_pipeline_cascade, list_pipeline_cascades

    current_df = initial_df
    previous_stage: Optional[str] = None

    for idx, stage in enumerate(stages):
        log.info(f"[pipeline] Executing stage {idx + 1}/{len(stages)}: {stage.name}")

        # Look up the pipeline cascade
        cascade_entry = get_pipeline_cascade(stage.name)
        if not cascade_entry:
            available = list_pipeline_cascades()
            available_str = ", ".join(available) if available else "(none registered)"
            raise PipelineExecutionError(
                stage_name=stage.name,
                stage_index=idx,
                inner_error=ValueError(
                    f"Unknown pipeline stage '{stage.name}'. "
                    f"Available PIPELINE cascades: {available_str}"
                )
            )

        # Build execution context
        context = PipelineContext(
            stage_index=idx,
            total_stages=len(stages),
            previous_stage=previous_stage,
            original_query=original_query,
            session_id=session_id,
            caller_id=caller_id,
        )

        # Serialize DataFrame for cascade input
        serialized = _serialize_dataframe(current_df, context)

        # Add stage arguments using the cascade's declared argument names
        cascade_inputs = serialized.copy()
        if stage.args:
            sql_func_args = cascade_entry.sql_function.get("args", [])
            user_arg_names = [
                arg["name"] for arg in sql_func_args
                if not arg["name"].startswith("_")
            ]
            for i, arg_value in enumerate(stage.args):
                if i < len(user_arg_names):
                    cascade_inputs[user_arg_names[i]] = arg_value
                else:
                    cascade_inputs[f"arg{i}"] = arg_value

        # Execute the cascade
        try:
            from ..runner import LARSRunner
            from .. import _register_all_skills

            _register_all_skills()

            stage_session_id = f"{session_id}_stage_{idx}"
            runner = LARSRunner(
                cascade_entry.cascade_path,
                session_id=stage_session_id,
                caller_id=caller_id
            )

            result = runner.run(input_data=cascade_inputs)

            # Extract output from cascade
            from ..semantic_sql.executor import _extract_cascade_output
            output = _extract_cascade_output(result)

            # Deserialize back to DataFrame
            current_df = _deserialize_result(output, current_df)

            log.info(f"[pipeline] Stage {stage.name} completed: {len(current_df)} rows")

            # Save to per-stage INTO table if specified
            if stage.into_table and duckdb_conn is not None:
                _save_to_table(duckdb_conn, current_df, stage.into_table)

        except PipelineExecutionError:
            raise
        except Exception as e:
            raise PipelineExecutionError(
                stage_name=stage.name,
                stage_index=idx,
                inner_error=e
            )

        previous_stage = stage.name

    # Legacy: Save to final INTO table if specified and not already saved by last stage
    last_stage_into = stages[-1].into_table if stages else None
    if into_table and into_table != last_stage_into and duckdb_conn is not None:
        _save_to_table(duckdb_conn, current_df, into_table)

    return current_df
