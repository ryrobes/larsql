"""
Metric Registry - Dynamic SQL operator registration for promoted metrics.

When an understanding is promoted to a metric, it becomes a first-class
SQL operator that can be used like any other semantic SQL function.

The metric's understanding document serves as the "cascade" that defines
how to compute it. Polymorphic modes allow different invocation patterns:
- REVENUE          → scalar value
- REVENUE BY region → breakdown
- REVENUE TREND    → time series finding
"""

import json
from typing import Any, Callable, Dict, List, Optional

from ..config import get_config
from ..db_adapter import get_db_adapter


def get_promoted_metrics() -> List[Dict[str, Any]]:
    """
    Get all active promoted metrics.

    Returns:
        List of metric definitions with their understanding docs and modes
    """
    db = get_db_adapter()

    rows = db.query(
        """
        SELECT
            metric_name,
            understanding_id,
            understanding_doc,
            modes,
            source_tables,
            key_columns,
            promoted_at,
            total_usage_count,
            unique_users,
            status
        FROM promoted_metrics FINAL
        WHERE status = 'active'
        ORDER BY metric_name
        """,
        output_format="dict",
    )

    # Parse the modes JSON
    for row in rows:
        if row.get("modes"):
            try:
                row["modes"] = json.loads(row["modes"])
            except json.JSONDecodeError:
                row["modes"] = []

    return rows


def get_metric(metric_name: str) -> Optional[Dict[str, Any]]:
    """Get a specific promoted metric by name."""
    db = get_db_adapter()

    rows = db.query(
        """
        SELECT
            metric_name,
            understanding_id,
            understanding_doc,
            modes,
            source_tables,
            key_columns,
            promoted_at,
            total_usage_count,
            status
        FROM promoted_metrics FINAL
        WHERE metric_name = %(name)s
          AND status = 'active'
        LIMIT 1
        """,
        {"name": metric_name.upper()},
        output_format="dict",
    )

    if not rows:
        return None

    row = rows[0]
    if row.get("modes"):
        try:
            row["modes"] = json.loads(row["modes"])
        except json.JSONDecodeError:
            row["modes"] = []

    return row


def register_promoted_metrics(duckdb_conn) -> int:
    """
    Register all promoted metrics as DuckDB SQL functions.

    This is called during connection initialization, alongside
    the regular semantic SQL function registration.

    Args:
        duckdb_conn: The DuckDB connection to register functions on

    Returns:
        Number of metrics registered
    """
    metrics = get_promoted_metrics()
    registered = 0

    for metric in metrics:
        try:
            _register_metric_function(duckdb_conn, metric)
            registered += 1
        except Exception as e:
            print(f"[BI] Warning: Failed to register metric {metric['metric_name']}: {e}")

    if registered > 0:
        print(f"[BI] Registered {registered} promoted metrics as SQL operators")

    return registered


def _register_metric_function(duckdb_conn, metric: Dict[str, Any]):
    """
    Register a single metric as a DuckDB function.

    The function executes the bi_answer cascade with the metric's
    understanding as context.
    """
    metric_name = metric["metric_name"]
    understanding_doc = metric["understanding_doc"]
    modes = metric.get("modes", [])

    def metric_executor(context: str = "") -> str:
        """Execute the metric with optional context."""
        from ..runner import run_cascade
        from ..config import get_config
        import os

        config = get_config()

        # Build the question from metric name + context
        if context:
            question = f"{metric_name} {context}"
        else:
            question = f"What is {metric_name}?"

        # Find the cascade
        cascade_path = os.path.join(config.root_dir, "cascades", "bi", "answer.cascade.yaml")

        # Run with the understanding pre-loaded
        result = run_cascade(
            cascade_path,
            input_data={
                "question": question,
                "context": f"This is the promoted metric '{metric_name}'. Use this understanding:\n\n{understanding_doc}",
            },
            session_id=f"metric_{metric_name.lower()}",
        )

        # Extract the answer
        state = result.get("state", {})
        lineage = result.get("lineage", [])

        if lineage:
            last_output = lineage[-1].get("output", {})
            if isinstance(last_output, dict):
                return json.dumps(last_output.get("answer", last_output))
            return str(last_output)

        return json.dumps(state)

    # Register the base function (returns JSON)
    # Note: DuckDB's Python UDF registration is limited, so we use a simple approach
    # More sophisticated registration would require the sql_tools/udf.py infrastructure
    try:
        duckdb_conn.create_function(
            metric_name.lower(),
            metric_executor,
            return_type="VARCHAR",
            parameters=["VARCHAR"],
        )
    except Exception as e:
        # Function might already exist, try removing first
        try:
            duckdb_conn.execute(f"DROP FUNCTION IF EXISTS {metric_name.lower()}")
            duckdb_conn.create_function(
                metric_name.lower(),
                metric_executor,
                return_type="VARCHAR",
                parameters=["VARCHAR"],
            )
        except Exception:
            raise e


def update_metric_usage(metric_name: str):
    """Update usage statistics for a metric after it's called."""
    db = get_db_adapter()

    db.execute(
        """
        ALTER TABLE promoted_metrics
        UPDATE
            total_usage_count = total_usage_count + 1,
            last_used_at = now64()
        WHERE metric_name = %(name)s
        """,
        {"name": metric_name.upper()},
    )


def deprecate_metric(metric_name: str, reason: str = "") -> bool:
    """Mark a metric as deprecated."""
    db = get_db_adapter()

    db.execute(
        """
        ALTER TABLE promoted_metrics
        UPDATE status = 'deprecated'
        WHERE metric_name = %(name)s
        """,
        {"name": metric_name.upper()},
    )
    return True


def list_metric_modes(metric_name: str) -> List[Dict[str, Any]]:
    """
    Get all discovered modes for a metric.

    Modes are discovered from usage patterns and define the
    polymorphic invocation patterns for the metric.
    """
    db = get_db_adapter()

    rows = db.query(
        """
        SELECT
            mode_id,
            metric_name,
            pattern,
            pattern_type,
            output_type,
            example_queries,
            usage_count,
            first_seen,
            last_used_at
        FROM bi_metric_modes FINAL
        WHERE metric_name = %(name)s
        ORDER BY usage_count DESC
        """,
        {"name": metric_name.upper()},
        output_format="dict",
    )
    return rows


def add_metric_mode(
    metric_name: str,
    pattern: str,
    output_type: str,
    example_query: str = "",
) -> str:
    """
    Add a new mode to a metric.

    This is typically called when a new usage pattern is detected.
    """
    import uuid

    db = get_db_adapter()
    mode_id = f"mode_{uuid.uuid4().hex[:12]}"

    row = {
        "mode_id": mode_id,
        "metric_name": metric_name.upper(),
        "pattern": pattern,
        "pattern_type": "template",
        "output_type": output_type,
        "example_queries": [example_query] if example_query else [],
        "usage_count": 1,
    }

    db.insert_rows("bi_metric_modes", [row])
    return mode_id
