"""
rvbbit_udf() - LLM-powered SQL user-defined function.

This allows you to use LLMs directly in SQL queries for data enrichment:

    SELECT
      product_name,
      rvbbit_udf('Extract brand name', product_name) as brand,
      rvbbit_udf('Classify: electronics/clothing/home', product_name) as category
    FROM products

The UDF:
- Spawns mini LLM calls per row
- Caches results (same input → same output)
- Handles errors gracefully (returns NULL on failure)
- Supports batching for efficiency
"""

import hashlib
import json
from typing import Optional, Dict, Any
import duckdb


# Global cache for UDF results
_udf_cache: Dict[str, str] = {}

# Global cache for cascade UDF results (full cascade executions)
_cascade_udf_cache: Dict[str, str] = {}

# Track which connections have UDF registered (to avoid duplicate registration)
_registered_connections: set = set()


def _make_cache_key(instructions: str, input_value: str, model: str = None) -> str:
    """Create cache key for UDF result."""
    cache_str = f"{instructions}|{input_value}|{model or 'default'}"
    return hashlib.md5(cache_str.encode()).hexdigest()


def _make_cascade_cache_key(cascade_path: str, inputs: dict) -> str:
    """Create cache key for cascade UDF result."""
    # Sort inputs for consistent hashing
    inputs_str = json.dumps(inputs, sort_keys=True)
    cache_str = f"{cascade_path}|{inputs_str}"
    return hashlib.md5(cache_str.encode()).hexdigest()


def rvbbit_udf_impl(
    instructions: str,
    input_value: str,
    model: str = None,
    temperature: float = 0.0,
    max_tokens: int = 500,
    use_cache: bool = True
) -> str:
    """
    Core implementation of rvbbit_udf.

    Args:
        instructions: What to ask the LLM (e.g., "Extract brand name from this product")
        input_value: The data to process (e.g., "Apple iPhone 15 Pro")
        model: Optional model override (default: uses RVBBIT_DEFAULT_MODEL)
        temperature: LLM temperature (default: 0.0 for deterministic)
        max_tokens: Max tokens in response
        use_cache: Whether to use cache (default: True)

    Returns:
        LLM response as string (or None on error)
    """
    # Check cache first
    if use_cache:
        cache_key = _make_cache_key(instructions, input_value, model)
        if cache_key in _udf_cache:
            return _udf_cache[cache_key]

    try:
        # Import locally to avoid circular dependencies
        from ..agent import Agent
        from ..config import get_config

        # Get config for model and API settings
        config_obj = get_config()

        # Get model (use default if not specified)
        if model is None:
            model = config_obj.default_model

        # Build prompt
        system_prompt = f"{instructions}\n\nInput: {input_value}\n\nReturn ONLY the result, no explanation or markdown."

        # Create agent with system prompt and API config
        agent = Agent(
            system_prompt=system_prompt,
            model=model,
            tools=[],
            base_url=config_obj.provider_base_url,
            api_key=config_obj.provider_api_key
        )

        # Run LLM - agent.run() just takes input_message and context_messages
        response = agent.run(
            input_message="Process the input above.",
            context_messages=[]
        )

        # Extract text from response (handle different response formats)
        if isinstance(response, list) and len(response) > 0:
            # Response is a list of messages - take the last assistant message
            for msg in reversed(response):
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    result = msg.get("content", "")
                    break
            else:
                result = str(response)
        elif isinstance(response, dict) and "content" in response:
            result = response["content"]
        elif isinstance(response, str):
            result = response
        else:
            result = str(response)

        # Strip whitespace
        result = result.strip()

        # Never return empty string - DuckDB treats it as NULL in some contexts
        if not result:
            result = "N/A"

        # Cache result
        if use_cache:
            _udf_cache[cache_key] = result

        return result

    except Exception as e:
        # Log error with more detail
        import logging
        import traceback
        logging.getLogger(__name__).error(f"rvbbit_udf error for '{instructions}': {e}\n{traceback.format_exc()}")
        return f"ERROR: {str(e)[:50]}"


def rvbbit_cascade_udf_impl(
    cascade_path: str,
    inputs_json: str,
    use_cache: bool = True,
    return_field: Optional[str] = None
) -> str:
    """
    Run a complete cascade as a SQL UDF.

    This enables multi-phase LLM workflows per database row with full validation,
    soundings, wards, and all cascade features. Particularly powerful for:
    - Complex multi-step reasoning per row
    - Validated outputs (wards + output_schema)
    - Soundings per row (best-of-N selection)
    - Tool usage per row (query other data, call APIs)

    Args:
        cascade_path: Path to cascade file (e.g., "tackle/fraud_check.yaml")
        inputs_json: JSON string of cascade inputs (e.g., '{"customer_id": 123}')
        use_cache: Whether to use cache (default: True)
        return_field: Optional field to extract from result (e.g., "risk_score")
                     If None, returns full result as JSON string

    Returns:
        JSON string with cascade outputs, or specific field value if return_field specified

    Example SQL:
        SELECT
          customer_id,
          rvbbit_cascade_udf(
            'tackle/fraud_check.yaml',
            json_object('customer_id', customer_id)
          ) as fraud_analysis
        FROM transactions;

    With field extraction:
        SELECT
          customer_id,
          rvbbit_cascade_udf(
            'tackle/fraud_check.yaml',
            json_object('customer_id', customer_id),
            'risk_score'
          ) as risk_score
        FROM transactions;
    """
    import uuid
    import os

    try:
        # Parse inputs (might be JSON string from SQL)
        if isinstance(inputs_json, str):
            inputs = json.loads(inputs_json)
        else:
            inputs = inputs_json

        # Create cache key
        cache_key = _make_cascade_cache_key(cascade_path, inputs)

        # Check cache
        if use_cache and cache_key in _cascade_udf_cache:
            cached_result = _cascade_udf_cache[cache_key]

            # If return_field specified, extract it
            if return_field:
                result_obj = json.loads(cached_result)
                # Try to extract from outputs first, then state
                for phase_output in result_obj.get("outputs", {}).values():
                    if isinstance(phase_output, dict) and return_field in phase_output:
                        return str(phase_output[return_field])
                # Fallback: search in state
                if return_field in result_obj.get("state", {}):
                    return str(result_obj["state"][return_field])

            return cached_result

        # Resolve cascade path
        resolved_path = cascade_path
        if not os.path.isabs(cascade_path):
            resolved_path = os.path.join(os.getcwd(), cascade_path)

        # Add extension if needed
        if not os.path.exists(resolved_path):
            for ext in [".yaml", ".yml", ".json"]:
                if os.path.exists(resolved_path + ext):
                    resolved_path = resolved_path + ext
                    break

        if not os.path.exists(resolved_path):
            return json.dumps({"error": f"Cascade not found: {cascade_path}", "status": "failed"})

        # Generate unique session ID for this UDF call
        session_id = f"cascade_udf_{uuid.uuid4().hex[:8]}"

        # Run cascade
        from ..runner import run_cascade

        result = run_cascade(
            resolved_path,
            inputs,
            session_id=session_id
        )

        # Serialize relevant outputs as JSON
        # We want to return something useful for SQL queries
        outputs = {}
        for phase_item in result.get("lineage", []):
            cell_name = phase_item.get("phase")
            phase_output = phase_item.get("output")
            if cell_name:
                outputs[cell_name] = phase_output

        json_result = json.dumps({
            "outputs": outputs,
            "state": result.get("state", {}),
            "status": result.get("status", "unknown"),
            "session_id": session_id,
            "has_errors": result.get("has_errors", False)
        })

        # Cache result
        if use_cache:
            _cascade_udf_cache[cache_key] = json_result

        # Extract specific field if requested
        if return_field:
            result_obj = json.loads(json_result)
            for phase_output in result_obj.get("outputs", {}).values():
                if isinstance(phase_output, dict) and return_field in phase_output:
                    return str(phase_output[return_field])
            if return_field in result_obj.get("state", {}):
                return str(result_obj["state"][return_field])
            # Field not found, return NULL
            return "NULL"

        return json_result

    except Exception as e:
        # Log error with detail
        import logging
        import traceback
        logging.getLogger(__name__).error(f"rvbbit_cascade_udf error for '{cascade_path}': {e}\n{traceback.format_exc()}")
        return json.dumps({"error": str(e), "status": "failed"})


def register_rvbbit_udf(connection: duckdb.DuckDBPyConnection, config: Dict[str, Any] = None):
    """
    Register rvbbit_udf as a DuckDB user-defined function.

    Args:
        connection: DuckDB connection to register with
        config: Optional UDF configuration:
            - model: Default model for UDF calls
            - temperature: Default temperature
            - max_tokens: Default max tokens
            - cache_enabled: Whether to use cache

    Example:
        conn = duckdb.connect()
        register_rvbbit_udf(conn, {"model": "anthropic/claude-haiku-4.5"})

        # Now you can use it in SQL:
        result = conn.execute('''
            SELECT
              product_name,
              rvbbit_udf('Extract brand', product_name) as brand
            FROM products
        ''').fetchdf()
    """
    # Check if already registered for this connection
    conn_id = id(connection)
    if conn_id in _registered_connections:
        return  # Already registered, skip

    config = config or {}

    # Default config
    default_model = config.get("model")
    default_temperature = config.get("temperature", 0.0)
    default_max_tokens = config.get("max_tokens", 500)
    cache_enabled = config.get("cache_enabled", True)

    # Create wrapper with defaults
    def udf_wrapper(instructions: str, input_value: str) -> str:
        """Simple wrapper for SQL - takes 2 string arguments."""
        return rvbbit_udf_impl(
            instructions=instructions,
            input_value=input_value,
            model=default_model,
            temperature=default_temperature,
            max_tokens=default_max_tokens,
            use_cache=cache_enabled
        )

    # Register as DuckDB UDF (simple API - DuckDB infers types for simple UDF)
    try:
        connection.create_function(
            "rvbbit",
            udf_wrapper
        )
        # Register alias
        connection.create_function(
            "rvbbit_udf",
            udf_wrapper
        )
        _registered_connections.add(conn_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not register rvbbit: {e}")

    # Register cascade UDF separately (with explicit return type)
    try:
        def cascade_udf_wrapper(cascade_path: str, inputs_json: str) -> str:
            """Wrapper for cascade UDF - explicit return type."""
            return rvbbit_cascade_udf_impl(cascade_path, inputs_json)

        connection.create_function(
            "rvbbit_run",
            cascade_udf_wrapper,
            return_type="VARCHAR"
        )
        # Register alias
        connection.create_function(
            "rvbbit_cascade_udf",
            cascade_udf_wrapper,
            return_type="VARCHAR"
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not register rvbbit_run: {e}")



def clear_udf_cache():
    """Clear all UDF result caches (simple and cascade)."""
    global _udf_cache, _cascade_udf_cache
    _udf_cache.clear()
    _cascade_udf_cache.clear()


def get_udf_cache_stats() -> Dict[str, Any]:
    """Get UDF cache statistics."""
    return {
        "simple_udf": {
            "cached_entries": len(_udf_cache),
            "cache_size_bytes": sum(len(k) + len(v) for k, v in _udf_cache.items())
        },
        "cascade_udf": {
            "cached_entries": len(_cascade_udf_cache),
            "cache_size_bytes": sum(len(k) + len(v) for k, v in _cascade_udf_cache.items())
        },
        "total_entries": len(_udf_cache) + len(_cascade_udf_cache)
    }
