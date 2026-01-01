"""
Cascade Executor for SQL Functions.

Executes RVBBIT cascades as SQL UDFs, bridging the SQL and cascade systems.
"""

import json
import hashlib
import asyncio
from typing import Any, Dict, Optional, List
from concurrent.futures import ThreadPoolExecutor
import logging

log = logging.getLogger(__name__)

# Shared thread pool for cascade execution
_executor = ThreadPoolExecutor(max_workers=8)

# Result cache
_cache: Dict[str, Any] = {}


def _make_cache_key(cascade_id: str, inputs: Dict[str, Any]) -> str:
    """Create a cache key from cascade ID and inputs."""
    inputs_json = json.dumps(inputs, sort_keys=True, default=str)
    key_data = f"{cascade_id}:{inputs_json}"
    return hashlib.md5(key_data.encode()).hexdigest()


def _run_cascade_sync(cascade_path: str, inputs: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """Run a cascade synchronously (blocking)."""
    from ..runner import RVBBITRunner

    async def _run():
        runner = RVBBITRunner(cascade_path)
        return await runner.run(inputs=inputs, session_id=session_id)

    return asyncio.run(_run())


def execute_cascade_udf(
    cascade_id: str,
    inputs_json: str,
    use_cache: bool = True,
) -> str:
    """
    Execute a cascade as a SQL UDF.

    This is the core function registered as a DuckDB UDF that enables
    calling any cascade with sql_function config from SQL.

    Args:
        cascade_id: The cascade ID or function name to execute
        inputs_json: JSON string of inputs for the cascade
        use_cache: Whether to use cached results

    Returns:
        JSON string of the cascade result
    """
    from .registry import get_sql_function, get_cached_result, set_cached_result
    from ..session_naming import generate_woodland_id

    try:
        # Parse inputs
        inputs = json.loads(inputs_json) if inputs_json else {}

        # Look up the function
        fn = get_sql_function(cascade_id)
        if not fn:
            return json.dumps({"error": f"SQL function not found: {cascade_id}"})

        # Check cache
        if use_cache:
            found, cached = get_cached_result(cascade_id, inputs)
            if found:
                log.debug(f"[cascade_udf] Cache hit for {cascade_id}")
                return json.dumps(cached) if not isinstance(cached, str) else cached

        # Generate session ID
        woodland_id = generate_woodland_id()
        session_id = f"sql_fn_{cascade_id}_{woodland_id}"

        # Execute the cascade
        result = _run_cascade_sync(fn.cascade_path, inputs, session_id)

        # Extract the output
        output = result.get("result") or result.get("output") or result

        # Post-process based on return type
        if fn.returns == "BOOLEAN":
            if isinstance(output, str):
                output = output.lower().strip() in ("true", "yes", "1")
            output = bool(output)
        elif fn.returns == "DOUBLE":
            if isinstance(output, str):
                try:
                    output = float(output.strip())
                except ValueError:
                    output = 0.0
        elif fn.returns == "INTEGER":
            if isinstance(output, str):
                try:
                    output = int(float(output.strip()))
                except ValueError:
                    output = 0

        # Cache result
        if use_cache:
            set_cached_result(cascade_id, inputs, output)

        # Return as JSON if complex, otherwise as string
        if isinstance(output, (dict, list)):
            return json.dumps(output)
        else:
            return str(output)

    except Exception as e:
        log.error(f"[cascade_udf] Error executing {cascade_id}: {e}")
        return json.dumps({"error": str(e)})


def semantic_matches_cascade(text: str, criterion: str) -> bool:
    """
    MEANS operator via cascade.

    SELECT * FROM docs WHERE semantic_matches(title, 'nighttime')
    """
    result = execute_cascade_udf(
        "semantic_matches",
        json.dumps({"text": text, "criterion": criterion})
    )

    try:
        if result.lower() in ("true", "yes", "1"):
            return True
        elif result.lower() in ("false", "no", "0"):
            return False
        else:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and "error" in parsed:
                log.warning(f"semantic_matches error: {parsed['error']}")
                return False
            return bool(parsed)
    except (json.JSONDecodeError, ValueError):
        return result.lower().strip() in ("true", "yes", "1")


def semantic_score_cascade(text: str, criterion: str) -> float:
    """
    ABOUT / RELEVANCE TO operator via cascade.

    SELECT * FROM docs WHERE semantic_score(title, 'interesting') > 0.7
    """
    result = execute_cascade_udf(
        "semantic_score",
        json.dumps({"text": text, "criterion": criterion})
    )

    try:
        return float(result)
    except ValueError:
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and "error" in parsed:
                log.warning(f"semantic_score error: {parsed['error']}")
                return 0.0
            return float(parsed)
        except (json.JSONDecodeError, ValueError):
            return 0.0


def semantic_implies_cascade(premise: str, conclusion: str) -> bool:
    """
    IMPLIES operator via cascade.

    SELECT * FROM docs WHERE semantic_implies(title, 'visual contact')
    """
    result = execute_cascade_udf(
        "semantic_implies",
        json.dumps({"premise": premise, "conclusion": conclusion})
    )

    try:
        if result.lower() in ("true", "yes", "1"):
            return True
        elif result.lower() in ("false", "no", "0"):
            return False
        else:
            parsed = json.loads(result)
            return bool(parsed)
    except (json.JSONDecodeError, ValueError):
        return result.lower().strip() in ("true", "yes", "1")


def semantic_contradicts_cascade(text_a: str, text_b: str) -> bool:
    """
    CONTRADICTS operator via cascade.

    SELECT * FROM docs WHERE semantic_contradicts(title, observed)
    """
    result = execute_cascade_udf(
        "semantic_contradicts",
        json.dumps({"text_a": text_a, "text_b": text_b})
    )

    try:
        if result.lower() in ("true", "yes", "1"):
            return True
        elif result.lower() in ("false", "no", "0"):
            return False
        else:
            parsed = json.loads(result)
            return bool(parsed)
    except (json.JSONDecodeError, ValueError):
        return result.lower().strip() in ("true", "yes", "1")


def semantic_summarize_cascade(texts_json: str) -> str:
    """
    SUMMARIZE aggregate via cascade.

    SELECT state, semantic_summarize(to_json(list(title))) FROM docs GROUP BY state
    """
    result = execute_cascade_udf(
        "semantic_summarize",
        json.dumps({"texts": texts_json})
    )

    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and "error" in parsed:
            log.warning(f"semantic_summarize error: {parsed['error']}")
            return f"Error: {parsed['error']}"
        return str(parsed)
    except json.JSONDecodeError:
        return result


def semantic_themes_cascade(texts_json: str, num_topics: int = 5) -> str:
    """
    TOPICS/THEMES aggregate via cascade.

    Returns JSON with topics and assignments.
    """
    result = execute_cascade_udf(
        "semantic_themes",
        json.dumps({"texts": texts_json, "num_topics": num_topics})
    )

    return result


def semantic_cluster_cascade(values_json: str, num_clusters: int = 8, criterion: str = None) -> str:
    """
    MEANING/CLUSTER aggregate via cascade.

    Returns JSON with clusters and assignments.
    """
    inputs = {"values": values_json, "num_clusters": num_clusters}
    if criterion:
        inputs["criterion"] = criterion

    result = execute_cascade_udf(
        "semantic_cluster",
        json.dumps(inputs)
    )

    return result


def semantic_classify_cascade(text: str, topics_json: str) -> str:
    """
    Classify a single text into one of the provided topics.

    SELECT semantic_classify(title, '["Topic A", "Topic B"]') FROM docs
    """
    result = execute_cascade_udf(
        "semantic_classify",
        json.dumps({"text": text, "topics": topics_json})
    )

    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and "error" in parsed:
            log.warning(f"semantic_classify error: {parsed['error']}")
            return "Unknown"
        return str(parsed)
    except json.JSONDecodeError:
        return result.strip()


def register_cascade_udfs(connection) -> None:
    """
    Register cascade-based UDFs with a DuckDB connection.

    These are alternatives to the direct-call UDFs in llm_aggregates.py.
    They route through the cascade system for full observability.
    """
    try:
        # Boolean functions (SCALAR)
        connection.create_function(
            "cascade_matches",
            semantic_matches_cascade,
            return_type="BOOLEAN"
        )
        connection.create_function(
            "cascade_implies",
            semantic_implies_cascade,
            return_type="BOOLEAN"
        )
        connection.create_function(
            "cascade_contradicts",
            semantic_contradicts_cascade,
            return_type="BOOLEAN"
        )

        # Score function (SCALAR)
        connection.create_function(
            "cascade_score",
            semantic_score_cascade,
            return_type="DOUBLE"
        )

        # Aggregate functions (via JSON input)
        connection.create_function(
            "cascade_summarize",
            semantic_summarize_cascade,
            return_type="VARCHAR"
        )
        connection.create_function(
            "cascade_themes",
            semantic_themes_cascade,
            return_type="VARCHAR"
        )
        connection.create_function(
            "cascade_cluster",
            semantic_cluster_cascade,
            return_type="VARCHAR"
        )
        connection.create_function(
            "cascade_classify",
            semantic_classify_cascade,
            return_type="VARCHAR"
        )

        # Generic cascade executor
        connection.create_function(
            "run_cascade",
            execute_cascade_udf,
            return_type="VARCHAR"
        )

        log.info("[cascade_udf] Registered cascade-based UDFs")

    except Exception as e:
        log.warning(f"[cascade_udf] Failed to register UDFs: {e}")


# Feature flag to enable cascade-based UDFs
USE_CASCADE_UDFS = False


def set_use_cascade_udfs(enabled: bool) -> None:
    """Enable or disable cascade-based UDFs."""
    global USE_CASCADE_UDFS
    USE_CASCADE_UDFS = enabled
    log.info(f"[cascade_udf] Cascade UDFs {'enabled' if enabled else 'disabled'}")
