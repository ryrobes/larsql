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


def _run_cascade_sync(cascade_path: str, session_id: str, inputs: Dict[str, Any], caller_id: str = None) -> Dict[str, Any]:
    """Run a cascade synchronously (blocking)."""
    from ..runner import RVBBITRunner

    # RVBBITRunner takes session_id AND caller_id for proper tracking
    runner = RVBBITRunner(cascade_path, session_id=session_id, caller_id=caller_id)
    return runner.run(input_data=inputs)


def _strip_markdown_fences(text: str) -> str:
    """
    Strip markdown code fences from LLM output.

    Handles patterns like:
    - ```json\n{...}\n```
    - ```\n{...}\n```
    - Just the content if no fences present
    """
    import re

    if not isinstance(text, str):
        return text

    text = text.strip()

    # Pattern: ```json or ```sql or just ``` at start, ``` at end
    fence_pattern = r'^```(?:\w+)?\s*\n?(.*?)\n?```$'
    match = re.match(fence_pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()

    return text


def _extract_cascade_output(result: Dict[str, Any]) -> Any:
    """
    Extract the actual output value from a cascade result dict.

    The runner returns a complex structure with lineage, history, etc.
    This extracts the final cell output in priority order:
    1. lineage[-1]["output"] - most reliable for all cell types
    2. history (last assistant message content) - fallback for LLM cells
    3. result["result"] or result["output"] - direct keys
    4. result itself - last resort

    Also strips markdown code fences from string outputs.
    """
    if not result or not isinstance(result, dict):
        return result

    output = None

    # Strategy 1: Get from lineage (most reliable)
    lineage = result.get("lineage")
    if lineage and len(lineage) > 0:
        last_entry = lineage[-1]
        if isinstance(last_entry, dict) and "output" in last_entry:
            output = last_entry["output"]
            # If output is itself a dict with a 'result' key, unwrap it
            if isinstance(output, dict) and "result" in output:
                output = output["result"]

    # Strategy 2: Fallback to history for LLM cells
    if output is None:
        history = result.get("history")
        if history:
            for message in reversed(history):
                msg_role = message.get("role", "")
                if msg_role in ["system", "cell_complete", "structure"]:
                    continue

                # Prefer content_json (already parsed)
                content_json = message.get("content_json")
                if content_json:
                    output = content_json
                    break

                # Fallback to content
                content = message.get("content")
                if content and not content.startswith("Cell:") and not content.startswith("Cascade:"):
                    output = content
                    break

    # Strategy 3: Try direct keys
    if output is None:
        if "result" in result:
            output = result["result"]
        elif "output" in result:
            output = result["output"]
        else:
            output = result

    # Strip markdown code fences from string outputs
    if isinstance(output, str):
        output = _strip_markdown_fences(output)

        # Try to parse as JSON if it looks like JSON
        stripped = output.strip()
        if stripped.startswith('{') or stripped.startswith('['):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass

    return output


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
    from ..caller_context import get_caller_id
    from ..sql_trail import register_cascade_execution, increment_cache_hit, increment_cache_miss

    # Get caller_id from context (set by postgres_server for SQL queries)
    caller_id = get_caller_id()

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
                # Track cache hit for SQL Trail
                if caller_id:
                    increment_cache_hit(caller_id)
                return json.dumps(cached) if not isinstance(cached, str) else cached

        # Track cache miss for SQL Trail
        if caller_id:
            increment_cache_miss(caller_id)

        # Generate session ID
        woodland_id = generate_woodland_id()
        session_id = f"sql_fn_{cascade_id}_{woodland_id}"

        # Register cascade execution for SQL Trail
        if caller_id and fn:
            register_cascade_execution(
                caller_id=caller_id,
                cascade_id=cascade_id,
                cascade_path=fn.cascade_path,
                session_id=session_id,
                inputs=inputs
            )

        # Execute the cascade (pass caller_id so it propagates to unified_logs!)
        result = _run_cascade_sync(fn.cascade_path, session_id, inputs, caller_id=caller_id)

        # Extract the output using proper cascade result parsing
        output = _extract_cascade_output(result)

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
