"""
Skill for dynamically calling any cascade from SQL.

Enables the cascade() SQL operator to work with prewarm parallelization
while avoiding double cascade execution overhead.
"""

from .base import simple_eddy
import json


@simple_eddy
def call_cascade_dynamic(cascade_path: str, inputs_json: str) -> str:
    """
    Dynamically invoke any cascade and return its result.

    This is a thin wrapper that enables cascade() SQL operator to work with
    semantic SQL's prewarm parallelization system while avoiding double
    cascade execution overhead.

    Args:
        cascade_path: Relative path to cascade (e.g., 'skills/fraud_check.yaml')
        inputs_json: JSON string of cascade inputs

    Returns:
        JSON string with cascade result (pass-through from lars_cascade_udf_impl)
    """
    from ..sql_tools.udf import lars_cascade_udf_impl

    # Normalize JSON for consistent caching (sort keys)
    try:
        inputs_dict = json.loads(inputs_json)
        normalized_json = json.dumps(inputs_dict, sort_keys=True)
    except (json.JSONDecodeError, TypeError):
        # If it's not valid JSON, pass through as-is
        normalized_json = inputs_json

    # Call the cascade via the same UDF path (has its own caching)
    # Return the result directly as a string (already JSON formatted)
    return lars_cascade_udf_impl(
        cascade_path=cascade_path,
        inputs_json=normalized_json,
        use_cache=True
    )
