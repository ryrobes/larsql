"""
Cascade Executor for SQL Functions.

Executes LARS cascades as SQL UDFs, bridging the SQL and cascade systems.
"""

import json
import re
import asyncio
import copy
from typing import Any, Dict, Optional, List, Tuple, Union
from concurrent.futures import ThreadPoolExecutor
import logging

log = logging.getLogger(__name__)

# Shared thread pool for cascade execution
_executor = ThreadPoolExecutor(max_workers=8)

# Pattern for takes config embedded in criterion strings
# Format: __LARS_TAKES:{"factor":3,"evaluator":"..."}__
_TAKES_PATTERN = re.compile(r'^__LARS_TAKES:(\{.*?\})__\s*')


def _extract_takes_from_inputs(inputs: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Extract takes config from input strings and return cleaned inputs.

    The takes config is embedded in criterion/query strings as a special prefix:
        __LARS_TAKES:{"factor":3}__ actual criterion here

    Returns:
        (cleaned_inputs, takes_config) - inputs with prefix stripped, and extracted config
    """
    takes_config = None
    cleaned_inputs = {}

    #log.info(f"[cascade_udf] 🔍 Checking inputs for takes config: {inputs}")
    #print(f"[cascade_udf] 🔍 Checking inputs for takes config: {list(inputs.keys())}")

    for key, value in inputs.items():
        if isinstance(value, str):
            #print(f"[cascade_udf] 🔍 Checking key '{key}': value starts with '{value[:80]}...' " if len(value) > 80 else f"[cascade_udf] 🔍 Checking key '{key}': value='{value}'")
            match = _TAKES_PATTERN.match(value)
            if match:
                try:
                    takes_config = json.loads(match.group(1))
                    # Strip the prefix from the value
                    cleaned_inputs[key] = value[match.end():].lstrip()
                    log.info(f"[cascade_udf] [OK] Extracted takes config: {takes_config}")
                    print(f"[cascade_udf] [OK] Extracted takes config: {takes_config}")
                    print(f"[cascade_udf] [OK] Cleaned value: '{cleaned_inputs[key]}'")
                except json.JSONDecodeError as e:
                    log.warning(f"[cascade_udf] [ERR] Failed to parse takes config: {e}")
                    print(f"[cascade_udf] [ERR] Failed to parse takes config: {e}")
                    cleaned_inputs[key] = value
            else:
                cleaned_inputs[key] = value
        else:
            cleaned_inputs[key] = value

    # if not takes_config:
    #     print(f"[cascade_udf] ⚪ No takes config found in inputs")

    return cleaned_inputs, takes_config


# Pattern for source column embedded in inputs
# Format: __LARS_SOURCE:{"column":"name","row":0,"table":"tablename"}__
_SOURCE_CONTEXT_PATTERN = re.compile(r'^__LARS_SOURCE:(\{.*?\})__\s*')


def _extract_source_context_from_inputs(
    inputs: Dict[str, Any]
) -> Tuple[Dict[str, Any], Optional[str], Optional[int], Optional[str]]:
    """
    Extract source lineage context from input strings and return cleaned inputs.

    The source context can be embedded in criterion/query strings as a special prefix:
        __LARS_SOURCE:{"column":"description","row":0}__ actual criterion here

    Or passed as special keys that are extracted and removed:
        _lars_source_column, _lars_source_row, _lars_source_table

    Returns:
        (cleaned_inputs, source_column, source_row_index, source_table)
    """
    source_column = None
    source_row_index = None
    source_table = None
    cleaned_inputs = {}

    for key, value in inputs.items():
        # Check for special source context keys
        if key == '_lars_source_column':
            source_column = str(value) if value is not None else None
            continue  # Don't include in cleaned inputs
        elif key == '_lars_source_row':
            try:
                source_row_index = int(value) if value is not None else None
            except (ValueError, TypeError):
                pass
            continue
        elif key == '_lars_source_table':
            source_table = str(value) if value is not None else None
            continue

        # Check for embedded source context prefix in string values
        if isinstance(value, str):
            match = _SOURCE_CONTEXT_PATTERN.match(value)
            if match:
                try:
                    source_data = json.loads(match.group(1))
                    source_column = source_column or source_data.get('column')
                    if 'row' in source_data:
                        try:
                            source_row_index = int(source_data['row'])
                        except (ValueError, TypeError):
                            pass
                    source_table = source_table or source_data.get('table')
                    # Strip the prefix from the value
                    cleaned_inputs[key] = value[match.end():].lstrip()
                    log.debug(f"[cascade_udf] Extracted source context: column={source_column}, row={source_row_index}, table={source_table}")
                except json.JSONDecodeError as e:
                    log.warning(f"[cascade_udf] Failed to parse source context: {e}")
                    cleaned_inputs[key] = value
            else:
                cleaned_inputs[key] = value
        else:
            cleaned_inputs[key] = value

    return cleaned_inputs, source_column, source_row_index, source_table


def _auto_format_inputs_as_toon(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Auto-format large arrays in inputs as TOON for token efficiency.

    This is applied to aggregate operators (summarize, themes, etc.) that
    receive large arrays of text/data from SQL GROUP BY operations.

    Args:
        inputs: Cascade inputs dictionary

    Returns:
        Modified inputs with TOON-encoded arrays where beneficial
    """
    from ..toon_utils import format_for_llm_context, TOON_AVAILABLE

    if not TOON_AVAILABLE:
        return inputs

    modified_inputs = {}

    for key, value in inputs.items():
        if isinstance(value, list) and len(value) > 10:
            try:
                # Format as TOON if beneficial
                formatted, metrics = format_for_llm_context(value, format="auto", min_rows=10)
                if metrics.get("format") == "toon":
                    modified_inputs[key] = formatted
                    log.info(
                        f"[cascade_udf] Auto-formatted '{key}' as TOON "
                        f"({len(value)} items, {metrics.get('token_savings_pct', 0):.1f}% savings)"
                    )
                else:
                    modified_inputs[key] = value
            except Exception as e:
                log.debug(f"[cascade_udf] TOON formatting skipped for '{key}': {e}")
                modified_inputs[key] = value
        else:
            modified_inputs[key] = value

    return modified_inputs


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge override into base dict.

    Override values take precedence. Nested dicts are merged recursively.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _inject_overrides_into_cascade(cascade_path: str, overrides_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Load a cascade file and inject overrides at cascade and cell levels.

    This enables cascade-level and cell-level overrides triggered by SQL comment hints:
        -- @ takes.factor: 3  (keyword-based)
        -- @@ run 3 takes with cheap model  (NL-interpreted)

    Supports two override formats:

    1. Legacy flat format (for backwards compatibility):
       {"factor": 3, "evaluator": "...", "model": "..."}

    2. New structured format (from NL interpreter):
       {
         "cascade_overrides": {
           "takes": {"factor": 3, ...},
           "token_budget": {...},
           "narrator": {...}
         },
         "cell_overrides": {
           "default": {"model": "...", "rules": {...}, "wards": {...}},
           "specific_cell": {"model": "..."}
         }
       }

    Args:
        cascade_path: Path to the cascade YAML/JSON file
        overrides_config: Override configuration from SQL hints

    Returns:
        Modified cascade config dict with overrides injected
    """
    from ..loaders import load_config_file

    # Load cascade as dict
    cascade_dict = load_config_file(cascade_path)
    config = copy.deepcopy(cascade_dict)

    # Detect format: new structured vs legacy flat
    is_new_format = 'cascade_overrides' in overrides_config or 'cell_overrides' in overrides_config

    if is_new_format:
        # New structured format from NL interpreter
        cascade_overrides = overrides_config.get('cascade_overrides', {})
        cell_overrides = overrides_config.get('cell_overrides', {})

        # Apply cascade-level overrides
        for key, value in cascade_overrides.items():
            if key == 'takes':
                # Merge with existing takes config
                existing = config.get('takes', {})
                config['takes'] = _deep_merge(existing, value)
                log.info(f"[cascade_udf] Injected cascade takes: {config['takes']}")
            elif key in ['token_budget', 'narrator', 'auto_context', 'memory', 'max_parallel']:
                config[key] = value
                log.info(f"[cascade_udf] Injected cascade {key}: {value}")

        # Apply cell-level overrides
        if cell_overrides and 'cells' in config:
            default_overrides = cell_overrides.get('default', {})

            for i, cell in enumerate(config['cells']):
                cell_name = cell.get('name', f'cell_{i}')

                # Get specific overrides for this cell, or use default
                specific_overrides = cell_overrides.get(cell_name, {})
                merged_overrides = _deep_merge(default_overrides, specific_overrides)

                if not merged_overrides:
                    continue

                # Apply overrides to cell
                for key, value in merged_overrides.items():
                    if key == 'model':
                        config['cells'][i]['model'] = value
                        log.info(f"[cascade_udf] Cell '{cell_name}' model → {value}")
                    elif key == 'takes':
                        existing = config['cells'][i].get('takes', {})
                        config['cells'][i]['takes'] = _deep_merge(existing, value)
                        log.info(f"[cascade_udf] Cell '{cell_name}' takes → {config['cells'][i]['takes']}")
                    elif key == 'rules':
                        existing = config['cells'][i].get('rules', {})
                        config['cells'][i]['rules'] = _deep_merge(existing, value)
                        log.info(f"[cascade_udf] Cell '{cell_name}' rules → {config['cells'][i]['rules']}")
                    elif key == 'wards':
                        existing = config['cells'][i].get('wards', {})
                        config['cells'][i]['wards'] = _deep_merge(existing, value)
                        log.info(f"[cascade_udf] Cell '{cell_name}' wards → {config['cells'][i]['wards']}")
                    elif key == 'intra_context':
                        existing = config['cells'][i].get('intra_context', {})
                        config['cells'][i]['intra_context'] = _deep_merge(existing, value)
                        log.info(f"[cascade_udf] Cell '{cell_name}' intra_context → {config['cells'][i]['intra_context']}")
                    elif key == 'context':
                        existing = config['cells'][i].get('context', {})
                        config['cells'][i]['context'] = _deep_merge(existing, value)
                        log.info(f"[cascade_udf] Cell '{cell_name}' context → {config['cells'][i]['context']}")
                    elif key in ['skills', 'handoffs', 'use_native_tools', 'output_schema']:
                        config['cells'][i][key] = value
                        log.info(f"[cascade_udf] Cell '{cell_name}' {key} → {value}")

    else:
        # Legacy flat format for backwards compatibility
        takes = {}

        # Map hint keys to cascade takes config
        if 'factor' in overrides_config:
            takes['factor'] = overrides_config['factor']

        if 'multi_model' in overrides_config:
            takes['multi_model'] = overrides_config['multi_model']
            # Ensure factor matches number of models
            if 'factor' not in takes:
                takes['factor'] = len(overrides_config['multi_model'])

        if 'evaluator' in overrides_config:
            takes['evaluator_instructions'] = overrides_config['evaluator']

        if 'max_parallel' in overrides_config:
            takes['max_parallel'] = overrides_config['max_parallel']

        if 'mode' in overrides_config:
            takes['mode'] = overrides_config['mode']

        if 'mutate' in overrides_config:
            takes['mutate'] = overrides_config['mutate']

        if 'reforge' in overrides_config:
            # Reforge is a nested config
            takes['reforge'] = {'rounds': overrides_config['reforge']}

        if 'evaluator_model' in overrides_config:
            takes['evaluator_model'] = overrides_config['evaluator_model']

        # Inject at top level
        if takes:
            config['takes'] = takes
            log.info(f"[cascade_udf] Injected takes config: {takes}")

    return config


# Backwards compatibility alias
_inject_takes_into_cascade = _inject_overrides_into_cascade


def _run_cascade_sync(
    cascade_path_or_config: Union[str, Dict[str, Any]],
    session_id: str,
    inputs: Dict[str, Any],
    caller_id: str | None = None,
    invocation_metadata: Dict[str, Any] | None = None,
    source_column: str | None = None,
    source_row_index: int | None = None,
    source_table: str | None = None,
) -> Dict[str, Any]:
    """Run a cascade synchronously (blocking).

    Args:
        cascade_path_or_config: Path to cascade file, or cascade config dict
        session_id: Session ID for execution
        inputs: Input data for the cascade
        caller_id: Caller ID for cost tracking
        invocation_metadata: Additional metadata about the invocation
        source_column: Column name being processed (for SQL lineage tracking)
        source_row_index: Row index in source query (for SQL lineage tracking)
        source_table: Table name if known (for SQL lineage tracking)
    """
    from ..runner import LARSRunner

    # Enrich invocation_metadata with source context if provided
    enriched_metadata = invocation_metadata.copy() if invocation_metadata else {}
    if source_column is not None or source_row_index is not None or source_table is not None:
        if 'source' not in enriched_metadata:
            enriched_metadata['source'] = {}
        if source_column is not None:
            enriched_metadata['source']['column'] = source_column
        if source_row_index is not None:
            enriched_metadata['source']['row_index'] = source_row_index
        if source_table is not None:
            enriched_metadata['source']['table'] = source_table

    # LARSRunner takes session_id AND caller_id for proper tracking
    runner = LARSRunner(
        cascade_path_or_config,
        session_id=session_id,
        caller_id=caller_id,
        invocation_metadata=enriched_metadata if enriched_metadata else None
    )
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

    Supports cascade-level takes via SQL comment hints:
        -- @ takes.factor: 3
        -- @ takes.evaluator: Pick the most accurate response
        -- @ models: [claude-sonnet, gpt-4o, gemini-pro]
        SELECT description MEANS 'is eco-friendly' FROM products

    When takes config is detected, the cascade is run multiple times
    and an evaluator picks the best result.

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

        # Extract takes config from inputs (embedded as special prefix)
        cleaned_inputs, takes_config = _extract_takes_from_inputs(inputs)

        # Extract source lineage context from inputs (for row/column tracking)
        cleaned_inputs, source_column, source_row_index, source_table = _extract_source_context_from_inputs(cleaned_inputs)

        # Auto-format large arrays as TOON for token efficiency
        cleaned_inputs = _auto_format_inputs_as_toon(cleaned_inputs)

        # Look up the function
        fn = get_sql_function(cascade_id)
        if not fn:
            return json.dumps({"error": f"SQL function not found: {cascade_id}"})

        # Use cache_name to allow cache sharing (e.g., ask_data + ask_data_sql)
        cache_name = fn.cache_name

        # Check cache (only if no takes - takes bypass cache for fresh sampling)
        if use_cache and not takes_config:
            found, cached = get_cached_result(cache_name, cleaned_inputs)
            if found:
                log.debug(f"[cascade_udf] Cache hit for {cascade_id} (cache_name={cache_name})")
                # Track cache hit for SQL Trail
                if caller_id:
                    increment_cache_hit(caller_id)

                # For sql_statement mode, cached value is SQL - need to execute it
                if fn.output_mode == 'sql_statement' and isinstance(cached, str):
                    from .sql_macro import bind_sql_parameters, execute_sql_statement
                    import tempfile

                    bound_sql = bind_sql_parameters(cached, cleaned_inputs, fn.args)
                    results = execute_sql_statement(bound_sql)

                    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                        json.dump(results, f)
                        return f.name

                # For sql_execute mode, cached value is SQL expression - execute it
                if fn.output_mode == 'sql_execute' and isinstance(cached, str):
                    from .sql_macro import bind_sql_parameters, execute_sql_fragment

                    bound_sql = bind_sql_parameters(cached, cleaned_inputs, fn.args)
                    result_value = execute_sql_fragment(bound_sql, fn.returns)
                    return str(result_value) if result_value is not None else ""

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
                inputs=cleaned_inputs
            )

        # Determine what to run: original cascade or modified with takes
        if takes_config:
            # Inject takes into cascade config (in-memory, not modifying file)
            cascade_config = _inject_takes_into_cascade(fn.cascade_path, takes_config)
            log.info(f"[cascade_udf] Running {cascade_id} with takes: factor={takes_config.get('factor', 'N/A')}")
            print(f"[cascade_udf] [RUN] Running {cascade_id} WITH TAKES: {takes_config}")
            print(f"[cascade_udf] [RUN] Injected cascade config has takes: {cascade_config.get('takes', 'NONE')}")
            result = _run_cascade_sync(
                cascade_config, session_id, cleaned_inputs, caller_id=caller_id,
                source_column=source_column, source_row_index=source_row_index, source_table=source_table
            )
        else:
            # Execute the cascade normally (pass caller_id so it propagates to unified_logs!)
            #print(f"[cascade_udf] [EXEC] Running {cascade_id} normally (no takes)")
            result = _run_cascade_sync(
                fn.cascade_path, session_id, cleaned_inputs, caller_id=caller_id,
                source_column=source_column, source_row_index=source_row_index, source_table=source_table
            )

        # Extract the output using proper cascade result parsing
        output = _extract_cascade_output(result)

        # Handle output_mode: sql_statement returns full SQL to execute
        if fn.output_mode == 'sql_statement':
            from .sql_macro import bind_sql_parameters, execute_sql_statement
            import tempfile

            sql_statement = str(output).strip()
            log.debug(f"[cascade_udf] sql_statement mode - executing: {sql_statement[:100]}...")

            # Bind parameters and execute
            bound_sql = bind_sql_parameters(sql_statement, cleaned_inputs, fn.args)

            # Execute and get table results
            results = execute_sql_statement(bound_sql)

            # Write to temp file for read_json_auto()
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(results, f)
                temp_path = f.name

            log.debug(f"[cascade_udf] Wrote {len(results)} rows to {temp_path}")

            # Cache the SQL statement (not the results file)
            if use_cache and not takes_config:
                set_cached_result(cache_name, cleaned_inputs, sql_statement)

            return temp_path

        # Handle output_mode: sql_execute returns SQL expression for scalar
        if fn.output_mode == 'sql_execute':
            from .sql_macro import bind_sql_parameters, execute_sql_fragment

            sql_fragment = str(output).strip()
            log.debug(f"[cascade_udf] sql_execute mode - executing: {sql_fragment[:100]}...")

            # Cache the SQL fragment
            if use_cache and not takes_config:
                set_cached_result(cache_name, cleaned_inputs, sql_fragment)

            # Bind and execute
            bound_sql = bind_sql_parameters(sql_fragment, cleaned_inputs, fn.args)
            result_value = execute_sql_fragment(bound_sql, fn.returns)
            return str(result_value) if result_value is not None else ""

        # Handle output_mode: sql_raw returns SQL as-is
        if fn.output_mode == 'sql_raw':
            sql_raw = str(output).strip()
            if use_cache and not takes_config:
                set_cached_result(cache_name, cleaned_inputs, sql_raw)
            return sql_raw

        # Post-process based on return type (for output_mode: value)
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

        # Cache result (but not takes runs - they're for fresh sampling)
        if use_cache and not takes_config:
            set_cached_result(cache_name, cleaned_inputs, output)

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


def semantic_cluster_cascade(values_json: str, num_clusters: int = 8, criterion: str | None = None) -> str:
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


def register_cascade_udfs(connection, existing: set | None = None) -> None:
    """
    Register cascade-based UDFs with a DuckDB connection.

    These are alternatives to the direct-call UDFs in llm_aggregates.py.
    They route through the cascade system for full observability.

    Args:
        connection: DuckDB connection to register with
        existing: Pre-fetched set of existing function names (for batch efficiency)
    """
    from ..sql_tools.udf import get_registered_functions, safe_create_function

    # Get existing functions if not provided
    if existing is None:
        existing = get_registered_functions(connection)

    # Boolean functions (SCALAR)
    safe_create_function(connection, "cascade_matches", semantic_matches_cascade, existing, return_type="BOOLEAN")
    safe_create_function(connection, "cascade_implies", semantic_implies_cascade, existing, return_type="BOOLEAN")
    safe_create_function(connection, "cascade_contradicts", semantic_contradicts_cascade, existing, return_type="BOOLEAN")

    # Score function (SCALAR)
    safe_create_function(connection, "cascade_score", semantic_score_cascade, existing, return_type="DOUBLE")

    # Aggregate functions (via JSON input)
    safe_create_function(connection, "cascade_summarize", semantic_summarize_cascade, existing, return_type="VARCHAR")
    safe_create_function(connection, "cascade_themes", semantic_themes_cascade, existing, return_type="VARCHAR")
    safe_create_function(connection, "cascade_cluster", semantic_cluster_cascade, existing, return_type="VARCHAR")
    safe_create_function(connection, "cascade_classify", semantic_classify_cascade, existing, return_type="VARCHAR")

    # Generic cascade executor
    safe_create_function(connection, "run_cascade", execute_cascade_udf, existing, return_type="VARCHAR")

    log.info("[cascade_udf] Registered cascade-based UDFs")


# Feature flag to enable cascade-based UDFs
USE_CASCADE_UDFS = False


def set_use_cascade_udfs(enabled: bool) -> None:
    """Enable or disable cascade-based UDFs."""
    global USE_CASCADE_UDFS
    USE_CASCADE_UDFS = enabled
    log.info(f"[cascade_udf] Cascade UDFs {'enabled' if enabled else 'disabled'}")
