"""
SQL Rewriter for RVBBIT Extended SQL Syntax.

Handles:
- RVBBIT MAP/RUN syntax for cascade execution
- Semantic SQL operators (MEANS, ABOUT, ~, SEMANTIC JOIN, RELEVANCE TO)
- LLM aggregate functions (LLM_SUMMARIZE, LLM_CLASSIFY, etc.)

Processing order:
1. RVBBIT MAP/RUN statements
2. Semantic operators (MEANS, ABOUT, ~, etc.)
3. LLM aggregates (SUMMARIZE, CLASSIFY, etc.)

All stages support -- @ annotation hints for model selection and prompt customization.
"""

import re
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass


# ============================================================================
# Exceptions
# ============================================================================

class RVBBITSyntaxError(Exception):
    """Invalid RVBBIT SQL syntax."""
    pass


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_MAP_LIMIT = 1000
DEFAULT_RESULT_COLUMN = 'result'
DEFAULT_PARALLEL = 10


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class RVBBITStatement:
    """Parsed RVBBIT statement."""
    mode: str
    cascade_path: str
    using_query: str
    result_alias: Optional[str]
    with_options: Dict[str, Any]
    parallel: Optional[int] = None
    output_columns: Optional[List[Tuple[str, str]]] = None  # [(col_name, sql_type), ...]


# ============================================================================
# Main Entry Point
# ============================================================================

def rewrite_rvbbit_syntax(query: str, duckdb_conn=None) -> str:
    """
    Detect and rewrite RVBBIT extended SQL syntax.

    Handles:
    1. RVBBIT MAP/RUN statements
    2. Dimension functions in GROUP BY (TOPICS, SENTIMENT, etc.)
    3. Semantic SQL operators (MEANS, ABOUT, ~, etc.)
    4. LLM aggregate functions (LLM_SUMMARIZE, LLM_CLASSIFY, etc.)

    These can be combined - a query can have multiple features.
    """
    # Normalize query first (remove comments, normalize whitespace)
    normalized = query.strip()
    lines = [line.split('--')[0].strip() for line in normalized.split('\n')]
    normalized = ' '.join(line for line in lines if line)

    # Check for EXPLAIN prefix
    explain_match = re.match(r'EXPLAIN\s+', normalized, re.IGNORECASE)
    if explain_match:
        from rvbbit.sql_explain import explain_rvbbit_map, format_explain_result

        # Strip EXPLAIN and parse statement
        inner_query = normalized[explain_match.end():].strip()

        if not _is_rvbbit_statement(inner_query):
            # Not an RVBBIT statement, return as-is (might be regular EXPLAIN)
            return query

        stmt = _parse_rvbbit_statement(inner_query)

        if stmt.mode != 'MAP':
            # EXPLAIN only supported for MAP currently
            raise RVBBITSyntaxError("EXPLAIN is only supported for RVBBIT MAP")

        # Analyze (don't execute)
        if duckdb_conn is None:
            # Can't analyze without connection, return error message
            return "SELECT 'ERROR: EXPLAIN requires database connection for analysis' AS error"

        result = explain_rvbbit_map(stmt, duckdb_conn)

        # Return formatted plan as a SELECT query
        plan_text = format_explain_result(result)
        # Escape single quotes for SQL
        plan_text_escaped = plan_text.replace("'", "''")
        return f"SELECT '{plan_text_escaped}' AS query_plan"

    result = query

    # Process RVBBIT MAP/RUN statements (only for actual MAP/RUN syntax)
    if _is_map_run_statement(normalized):
        stmt = _parse_rvbbit_statement(normalized)

        if stmt.mode == 'MAP':
            result = _rewrite_map(stmt)
        elif stmt.mode == 'RUN':
            result = _rewrite_run(stmt)
        else:
            raise RVBBITSyntaxError(f"Unknown mode: {stmt.mode}")

    # Process dimension functions (GROUP BY TOPICS(...), GROUP BY sentiment(...), etc.)
    # This must run BEFORE semantic operators to properly handle dimension expressions
    result = _rewrite_dimension_functions(result)

    # Process semantic SQL operators (MEANS, ABOUT, ~, SEMANTIC JOIN, RELEVANCE TO)
    # This must run BEFORE LLM aggregates since both use -- @ annotations
    result = _rewrite_semantic_operators(result)

    # Process LLM aggregate functions (can be in original query or in rewritten query)
    result = _rewrite_llm_aggregates(result)

    return result


def _rewrite_dimension_functions(query: str) -> str:
    """
    Rewrite dimension functions (TOPICS, SENTIMENT, etc.) to CTE-based execution.

    Transforms GROUP BY expressions that use dimension-shaped cascades into
    proper CTEs that:
    1. Extract bucket definitions from all values
    2. Classify each row into a bucket
    3. Replace the dimension function with the bucket column

    Example:
        SELECT state, topics(title, 8) as topic, COUNT(*)
        FROM bigfoot_vw
        GROUP BY state, topics(title, 8)

    Becomes:
        WITH
        _dim_topics_title_abc123_mapping AS (
            SELECT topics_compute(to_json(LIST(title)), 8) as _result
            FROM bigfoot_vw
        ),
        _dim_classified AS (
            SELECT *,
                json_extract_string(_result->'mapping', title) as __dim_topics_title_abc123
            FROM bigfoot_vw, _dim_topics_title_abc123_mapping
        )
        SELECT state, __dim_topics_title_abc123 as topic, COUNT(*)
        FROM _dim_classified
        GROUP BY state, __dim_topics_title_abc123
    """
    try:
        from rvbbit.sql_tools.dimension_rewriter import (
            rewrite_dimension_functions,
            has_dimension_functions
        )

        # Quick check to avoid unnecessary processing
        if not has_dimension_functions(query):
            return query

        result = rewrite_dimension_functions(query)

        if result.changed:
            import logging
            logging.getLogger(__name__).debug(
                f"[sql_rewriter] Dimension rewrite applied: {len(result.dimension_exprs)} expressions"
            )
            return result.sql_out

        if result.errors:
            import logging
            logging.getLogger(__name__).warning(
                f"[sql_rewriter] Dimension rewrite errors: {result.errors}"
            )

        return query

    except ImportError:
        # Dimension rewriter not available
        return query
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[sql_rewriter] Dimension rewrite failed: {e}")
        return query


def _rewrite_semantic_operators(query: str) -> str:
    """
    Rewrite semantic SQL operators to UDF calls.

    Transforms:
        col MEANS 'x'           → matches('x', col)
        col ABOUT 'x'           → score('x', col) > 0.5
        a ~ b                   → match_pair(a, b, 'same entity')
        ORDER BY col RELEVANCE TO 'x'  → ORDER BY score('x', col) DESC
        SEMANTIC JOIN t ON a ~ b       → CROSS JOIN t WHERE match_pair(...)

    Supports -- @ annotation hints for model selection and prompt customization.
    """
    try:
        import os

        # v2 (token-aware) rewriter: partial infix desugaring only.
        # It is intentionally conservative and falls back to legacy on error.
        # Default: enabled. Set RVBBIT_SEMANTIC_REWRITE_V2=0 to disable.
        v2_setting = os.environ.get("RVBBIT_SEMANTIC_REWRITE_V2", "").strip().lower()
        v2_enabled = v2_setting not in ("0", "false", "no", "off")

        if v2_enabled:
            try:
                from rvbbit.sql_tools.semantic_rewriter_v2 import rewrite_semantic_sql_v2
                from rvbbit.sql_tools.semantic_operators import rewrite_semantic_operators as legacy_rewrite

                v2_result = rewrite_semantic_sql_v2(query)
                if v2_result.errors:
                    return legacy_rewrite(query)

                # Always run legacy after v2 so existing query-level and special-case rewrites
                # (VECTOR_SEARCH, EMBED context injection, RELEVANCE TO, ABOUT thresholds, etc.)
                # continue to function during v2 rollout.
                return legacy_rewrite(v2_result.sql_out)

            except Exception:
                # Any failure: fall back to legacy
                from rvbbit.sql_tools.semantic_operators import rewrite_semantic_operators
                return rewrite_semantic_operators(query)

        from rvbbit.sql_tools.semantic_operators import rewrite_semantic_operators
        return rewrite_semantic_operators(query)
    except ImportError:
        # Fallback if module not available
        return query
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Semantic operator rewrite failed: {e}")
        return query


def _rewrite_llm_aggregates(query: str) -> str:
    """
    Rewrite LLM aggregate functions to implementation calls.

    Transforms:
        SELECT category, LLM_SUMMARIZE(review_text) FROM reviews GROUP BY category
    Into:
        SELECT category, llm_summarize_impl(LIST(review_text)::VARCHAR) FROM reviews GROUP BY category
    """
    try:
        from rvbbit.sql_tools.llm_agg_rewriter import process_llm_aggregates
        return process_llm_aggregates(query)
    except ImportError:
        # Fallback if module not available
        return query
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"LLM aggregate rewrite failed: {e}")
        return query


def _is_map_run_statement(query: str) -> bool:
    """Check if query contains RVBBIT MAP or RUN syntax (not just UDF calls)."""
    clean = query.strip().upper()
    lines = [line.split('--')[0].strip() for line in clean.split('\n')]
    clean = ' '.join(line for line in lines if line)
    return 'RVBBIT MAP' in clean or 'RVBBIT RUN' in clean


def _is_rvbbit_statement(query: str) -> bool:
    """Check if query contains RVBBIT syntax, semantic operators, or UDF function calls."""
    import re

    # Normalize query for detection (strip inline -- comments, normalize whitespace)
    raw = query.strip()
    lines = [line.split('--')[0].strip() for line in raw.split('\n')]
    normalized = ' '.join(line for line in lines if line)
    if not normalized:
        return False

    # Also create a version with string literals stripped to reduce false positives
    # (e.g., SELECT 'ALIGNS' should not be treated as a semantic operator query).
    normalized_no_strings = re.sub(r"\'(?:\'\'|[^'])*\'", "''", normalized)
    normalized_no_strings = re.sub(r"\"(?:\"\"|[^\"])*\"", "\"\"", normalized_no_strings)

    # Check for RVBBIT MAP/RUN syntax first
    if _is_map_run_statement(normalized):
        return True

    # Dynamic detection: if the query contains ANY configured semantic SQL operator
    # (infix or function-style keywords from the cascade registry), treat it as RVBBIT.
    # This keeps SQL Trail logging working as new operators are added.
    try:
        from rvbbit.sql_tools.dynamic_operators import has_any_semantic_operator
        if has_any_semantic_operator(normalized_no_strings):
            return True
    except Exception:
        # Best-effort: fall back to static patterns below
        pass

    # Dynamic detection: if the query calls any registered SQL function from the cascade
    # registry (including semantic_* short aliases), treat it as RVBBIT.
    try:
        from rvbbit.semantic_sql.registry import get_sql_function_registry
        sql_lower_norm = normalized.lower()
        for fn_name in get_sql_function_registry().keys():
            fn_lower = fn_name.lower()
            if re.search(rf'\b{re.escape(fn_lower)}\s*\(', sql_lower_norm):
                return True
            if fn_lower.startswith('semantic_'):
                alias = fn_lower.replace('semantic_', '', 1)
                if re.search(rf'\b{re.escape(alias)}\s*\(', sql_lower_norm):
                    return True
    except Exception:
        pass

    # Explicit vector search form: read_json_auto(vector_search_json_N(...))
    # These UDFs are registered in DuckDB (not part of the cascade registry), but they
    # should still flow through SQL Trail logging.
    try:
        if re.search(r'\bvector_search_json_\d+\s*\(', normalized_no_strings, re.IGNORECASE):
            return True
    except Exception:
        pass

    # Check for semantic operators (MEANS, ABOUT, IMPLIES, etc.)
    # These get rewritten to UDF calls but need to be detected BEFORE rewriting
    query_upper = normalized_no_strings.upper()
    semantic_patterns = [
        r'\bMEANS\s+\'',             # col MEANS 'x'
        r'\bNOT\s+MEANS\s+\'',       # col NOT MEANS 'x'
        r'\bABOUT\s+\'',             # col ABOUT 'x'
        r'\bNOT\s+ABOUT\s+\'',       # col NOT ABOUT 'x'
        r'\w+\s*~\s*[\'\w]',         # a ~ b or a ~ 'x' (tilde operator)
        r'\w+\s*!~\s*[\'\w]',        # a !~ b (negated tilde)
        r'\bSEMANTIC\s+JOIN\b',      # SEMANTIC JOIN
        r'\bRELEVANCE\s+TO\s+\'',    # ORDER BY col RELEVANCE TO 'x'
        r'\bSEMANTIC\s+DISTINCT\b',  # SEMANTIC DISTINCT
        r'\bGROUP\s+BY\s+MEANING\s*\(', # GROUP BY MEANING(col)
        r'\bGROUP\s+BY\s+TOPICS\s*\(',  # GROUP BY TOPICS(col)
        r'\bIMPLIES\s+\'',           # col IMPLIES 'x'
        r'\bIMPLIES\s+\w+',          # col IMPLIES other_col
        r'\bCONTRADICTS\s+\'',       # col CONTRADICTS 'x'
        r'\bCONTRADICTS\s+\w+',      # col CONTRADICTS other_col
    ]
    if any(re.search(p, query_upper, re.IGNORECASE) for p in semantic_patterns):
        return True

    # Check for RVBBIT UDF function calls (already rewritten or direct)
    sql_lower = normalized.lower()
    udf_patterns = [
        # RVBBIT core
        r'\brvbbit_udf\s*\(', r'\brvbbit\s*\(', r'\brvbbit_cascade_udf\s*\(',
        r'\brvbbit_run\s*\(', r'\brvbbit_run_batch\s*\(', r'\brvbbit_run_parallel_batch\s*\(',
        r'\brvbbit_map_parallel_exec\s*\(',
        # Scalar semantic operators
        r'\bmatches\s*\(', r'\bscore\s*\(', r'\bmatch_pair\s*\(', r'\bmatch_template\s*\(',
        r'\bsemantic_case\s*\(', r'\bclassify_single\s*\(',
        r'\bimplies\s*\(', r'\bcontradicts\s*\(',
        r'\bllm_matches\s*\(', r'\bllm_score\s*\(', r'\bllm_match_pair\s*\(',
        r'\bllm_match_template\s*\(', r'\bllm_semantic_case\s*\(',
        # Aggregate functions (both LLM_ prefixed and short aliases)
        r'\bsummarize\s*\(', r'\bllm_summarize\s*\(',
        r'\bclassify\s*\(', r'\bllm_classify\s*\(',
        r'\bsentiment\s*\(', r'\bllm_sentiment\s*\(',
        r'\bthemes\s*\(', r'\btopics\s*\(', r'\bllm_themes\s*\(',
        r'\bdedupe\s*\(', r'\bllm_dedupe\s*\(',
        r'\bcluster\s*\(', r'\bllm_cluster\s*\(',
        r'\bconsensus\s*\(', r'\bllm_consensus\s*\(',
        r'\boutliers\s*\(', r'\bllm_outliers\s*\(',
        r'\bllm_agg\s*\(',
    ]
    return any(re.search(p, sql_lower) for p in udf_patterns)


def _parse_rvbbit_statement(query: str) -> RVBBITStatement:
    """Parse RVBBIT statement."""
    query = query.strip()
    # Remove SQL comments and normalize whitespace
    lines = [line.split('--')[0].strip() for line in query.split('\n')]
    # Join with spaces (not newlines) to normalize multi-line queries
    query = ' '.join(line for line in lines if line)

    # Check for CREATE TABLE wrapper
    create_table_name = None
    create_match = re.match(r'CREATE\s+(?:TEMP\s+)?TABLE\s+(\w+)\s+AS\s+', query, re.IGNORECASE)
    if create_match:
        create_table_name = create_match.group(1)
        # Strip CREATE TABLE wrapper
        query = query[create_match.end():].strip()

    # Extract mode
    mode_match = re.match(r'RVBBIT\s+(MAP|RUN)', query, re.IGNORECASE)
    if not mode_match:
        raise RVBBITSyntaxError(f"Expected RVBBIT MAP or RVBBIT RUN, got: {query[:50]}...")

    mode = mode_match.group(1).upper()
    remaining = query[mode_match.end():].strip()

    # Extract PARALLEL and DISTINCT (can appear in either order for MAP)
    parallel = None
    is_distinct = False

    if mode == 'MAP':
        # Try PARALLEL first, then DISTINCT
        parallel_match = re.match(r'PARALLEL\s+(\d+)', remaining, re.IGNORECASE)
        if parallel_match:
            parallel = int(parallel_match.group(1))
            remaining = remaining[parallel_match.end():].strip()

        # Now check for DISTINCT (after PARALLEL if present)
        distinct_match = re.match(r'DISTINCT\s+', remaining, re.IGNORECASE)
        if distinct_match:
            is_distinct = True
            remaining = remaining[distinct_match.end():].strip()

        # If we didn't find PARALLEL yet, try again after DISTINCT
        if parallel is None:
            parallel_match = re.match(r'PARALLEL\s+(\d+)', remaining, re.IGNORECASE)
            if parallel_match:
                parallel = int(parallel_match.group(1))
                remaining = remaining[parallel_match.end():].strip()

    # Extract cascade path
    cascade_match = re.match(r"'([^']+)'", remaining)
    if not cascade_match:
        raise RVBBITSyntaxError(f"Expected cascade path as string literal, got: {remaining[:100]}")

    cascade_path = cascade_match.group(1)
    remaining = remaining[cascade_match.end():].strip()

    # Extract AS alias or AS (col TYPE, ...) schema
    result_alias = None
    output_columns = None

    # Check for AS keyword
    if remaining.upper().startswith('AS '):
        # Have AS - is it AS identifier or AS (...)?
        after_as_keyword = remaining[3:].strip()  # Skip 'AS '

        if after_as_keyword.startswith('('):
            # AS (col TYPE, ...) schema
            schema_content, after_schema = _extract_balanced_parens(after_as_keyword)
            if schema_content:
                output_columns = _parse_output_schema(schema_content)
                remaining = after_schema.strip()
        else:
            # AS identifier
            id_match = re.match(r'(\w+)', after_as_keyword)
            if id_match:
                result_alias = id_match.group(1)
                remaining = after_as_keyword[id_match.end():].strip()

    # Extract USING clause
    if not remaining.upper().startswith('USING'):
        raise RVBBITSyntaxError("Expected USING (SELECT ...)")

    remaining = remaining[5:].strip()
    using_query, remaining = _extract_balanced_parens(remaining)
    if using_query is None:
        raise RVBBITSyntaxError("Expected balanced parentheses after USING")

    # Extract WITH options
    with_options = {}
    remaining = remaining.strip()
    if remaining.upper().startswith('WITH'):
        remaining = remaining[4:].strip()
        with_clause, remaining = _extract_balanced_parens(remaining)
        if with_clause is None:
            raise RVBBITSyntaxError("Expected balanced parentheses after WITH")
        with_options = _parse_with_options(with_clause)

    # Store DISTINCT flag in with_options
    if is_distinct:
        with_options['distinct'] = True

    # Store CREATE TABLE name if present (takes precedence over WITH as_table)
    if create_table_name:
        with_options['as_table'] = create_table_name

    # Infer schema from cascade if requested
    if with_options.get('infer_schema') and not output_columns:
        output_columns = _infer_columns_from_cascade(cascade_path)

    return RVBBITStatement(
        mode=mode,
        cascade_path=cascade_path,
        using_query=using_query,
        result_alias=result_alias,
        with_options=with_options,
        parallel=parallel,
        output_columns=output_columns
    )


def _extract_balanced_parens(text: str) -> Tuple[Optional[str], str]:
    """Extract content within balanced parentheses."""
    if not text.startswith('('):
        return None, text

    depth = 0
    for i, char in enumerate(text):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return text[1:i], text[i+1:]

    raise RVBBITSyntaxError(f"Unbalanced parentheses: {text[:50]}...")


def _parse_with_options(with_clause: str) -> Dict[str, Any]:
    """Parse WITH (key = value, ...) options."""
    options = {}
    parts = _smart_split(with_clause, ',')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if '=' not in part:
            raise RVBBITSyntaxError(f"Expected 'key = value', got: {part}")

        key, value = part.split('=', 1)
        options[key.strip()] = _parse_value(value.strip())

    return options


def _smart_split(text: str, delimiter: str) -> list:
    """Split by delimiter, respecting nested parens/quotes."""
    parts, current, depth, in_string, string_char = [], [], 0, False, None

    for char in text:
        if char in ('"', "'"):
            if not in_string:
                in_string, string_char = True, char
            elif char == string_char:
                in_string = False

        if not in_string:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1

        if char == delimiter and depth == 0 and not in_string:
            parts.append(''.join(current))
            current = []
        else:
            current.append(char)

    if current:
        parts.append(''.join(current))

    return parts


def _parse_value(value_str: str) -> Any:
    """Parse value string to Python type."""
    value_str = value_str.strip()

    if value_str.lower() == 'true':
        return True
    if value_str.lower() == 'false':
        return False

    if (value_str.startswith("'") and value_str.endswith("'")) or \
       (value_str.startswith('"') and value_str.endswith('"')):
        return value_str[1:-1]

    try:
        return float(value_str) if '.' in value_str else int(value_str)
    except ValueError:
        return value_str


def _parse_output_schema(schema_str: str) -> List[Tuple[str, str]]:
    """
    Parse AS (col TYPE, col TYPE, ...) output schema.

    Args:
        schema_str: String like "brand VARCHAR, confidence DOUBLE"

    Returns:
        List of (column_name, sql_type) tuples

    Example:
        >>> _parse_output_schema("brand VARCHAR, confidence DOUBLE, is_luxury BOOLEAN")
        [("brand", "VARCHAR"), ("confidence", "DOUBLE"), ("is_luxury", "BOOLEAN")]
    """
    columns = []
    parts = _smart_split(schema_str, ',')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Split into name and type (e.g., "brand VARCHAR")
        tokens = part.split()
        if len(tokens) != 2:
            raise RVBBITSyntaxError(
                f"Expected 'column_name TYPE', got: {part}"
            )

        col_name, col_type = tokens

        # Validate type is a known SQL type
        valid_types = {
            'VARCHAR', 'TEXT', 'STRING',  # String types
            'BIGINT', 'INTEGER', 'INT', 'SMALLINT', 'TINYINT',  # Integer types
            'DOUBLE', 'FLOAT', 'REAL', 'DECIMAL', 'NUMERIC',  # Float types
            'BOOLEAN', 'BOOL',  # Boolean
            'JSON',  # JSON type
            'TIMESTAMP', 'DATE', 'TIME',  # Temporal
        }

        if col_type.upper() not in valid_types:
            raise RVBBITSyntaxError(
                f"Unsupported SQL type: {col_type}. Valid types: {', '.join(sorted(valid_types))}"
            )

        columns.append((col_name, col_type.upper()))

    return columns


def _infer_columns_from_cascade(cascade_path: str) -> Optional[List[Tuple[str, str]]]:
    """
    Load cascade file and infer output columns from output_schema.

    Allows: RVBBIT MAP 'cascade.yaml' USING (...) WITH (infer_schema=true)

    Args:
        cascade_path: Path to cascade file

    Returns:
        List of (col_name, sql_type) or None if no output_schema
    """
    import os
    import json
    import yaml

    # Resolve cascade path
    if not os.path.isabs(cascade_path):
        cascade_path = os.path.join(os.getcwd(), cascade_path)

    if not os.path.exists(cascade_path):
        for ext in ['.yaml', '.yml', '.json']:
            if os.path.exists(cascade_path + ext):
                cascade_path = cascade_path + ext
                break

    if not os.path.exists(cascade_path):
        return None

    # Load cascade config
    try:
        with open(cascade_path, 'r') as f:
            if cascade_path.endswith('.json'):
                config = json.load(f)
            else:
                config = yaml.safe_load(f)
    except Exception:
        return None

    # Find first cell with output_schema
    cells = config.get('cells', [])
    for cell in cells:
        output_schema = cell.get('output_schema')
        if output_schema and isinstance(output_schema, dict):
            # Convert JSON Schema to SQL types
            return _json_schema_to_sql_types(output_schema)

    return None


def _json_schema_to_sql_types(json_schema: dict) -> List[Tuple[str, str]]:
    """
    Convert JSON Schema to SQL column types.

    Args:
        json_schema: JSON Schema dict with 'properties' and 'type' fields

    Returns:
        List of (column_name, sql_type) tuples

    Example:
        >>> schema = {
        ...     "type": "object",
        ...     "properties": {
        ...         "brand": {"type": "string"},
        ...         "confidence": {"type": "number"},
        ...         "is_luxury": {"type": "boolean"}
        ...     }
        ... }
        >>> _json_schema_to_sql_types(schema)
        [("brand", "VARCHAR"), ("confidence", "DOUBLE"), ("is_luxury", "BOOLEAN")]
    """
    columns = []

    properties = json_schema.get('properties', {})
    for prop_name, prop_schema in properties.items():
        prop_type = prop_schema.get('type', 'string')

        # Map JSON Schema types to SQL types
        if prop_type == 'string':
            sql_type = 'VARCHAR'
        elif prop_type == 'number':
            sql_type = 'DOUBLE'
        elif prop_type == 'integer':
            sql_type = 'BIGINT'
        elif prop_type == 'boolean':
            sql_type = 'BOOLEAN'
        elif prop_type == 'array':
            sql_type = 'JSON'  # DuckDB can handle JSON arrays
        elif prop_type == 'object':
            sql_type = 'JSON'  # Nested objects as JSON
        else:
            sql_type = 'VARCHAR'  # Fallback

        columns.append((prop_name, sql_type))

    return columns


# ============================================================================
# MAP Rewrite
# ============================================================================

def _rewrite_map(stmt: RVBBITStatement) -> str:
    """Rewrite RVBBIT MAP to row-wise UDF calls."""
    using_query = _ensure_limit(stmt.using_query)
    result_column = stmt.result_alias or stmt.with_options.get('result_column', DEFAULT_RESULT_COLUMN)

    # Apply DISTINCT deduplication if requested
    dedupe_by = stmt.with_options.get('dedupe_by')
    if stmt.with_options.get('distinct') or dedupe_by:
        if dedupe_by:
            # Dedupe by specific column(s)
            using_query = f"SELECT DISTINCT ON ({dedupe_by}) * FROM ({using_query}) AS t"
        else:
            # Dedupe all columns
            using_query = f"SELECT DISTINCT * FROM ({using_query}) AS t"

    if stmt.parallel is not None:
        # PARALLEL execution: Use batching + parallelism
        # Note: For now, fall back to sequential with note about parallelism
        # True parallelism requires redesign to avoid DuckDB's table function + subquery limitation
        max_workers = stmt.parallel

        # TODO: Implement true parallel execution
        # Current limitation: DuckDB table functions can't take subqueries,
        # and temp tables created during query execution aren't visible to later parts of same query.
        #
        # For now, execute sequentially (same as non-PARALLEL MAP)
        # Future: Could use DuckDB's parallel execution hints or custom extension

        rewritten = f"""
WITH rvbbit_input AS (
  {using_query}
),
rvbbit_raw AS (
  SELECT
    i.*,
    rvbbit_run('{stmt.cascade_path}', to_json(i)) AS _raw_result
  FROM rvbbit_input i
)
SELECT
  r.* EXCLUDE (_raw_result),
  COALESCE(
    json_extract_string(_raw_result, '$.state.output_extract'),
    json_extract_string(_raw_result, '$.outputs.' || json_extract_string(_raw_result, '$.state.last_cell')),
    _raw_result
  ) AS {result_column}
FROM rvbbit_raw r
        """.strip()
    else:
        # Sequential execution (existing logic)
        rewritten = f"""
WITH rvbbit_input AS (
  {using_query}
),
rvbbit_raw AS (
  SELECT
    i.*,
    rvbbit_run('{stmt.cascade_path}', to_json(i)) AS _raw_result
  FROM rvbbit_input i
)
SELECT
  r.* EXCLUDE (_raw_result),
  COALESCE(
    json_extract_string(_raw_result, '$.state.output_extract'),
    json_extract_string(_raw_result, '$.outputs.' || json_extract_string(_raw_result, '$.state.last_cell')),
    _raw_result
  ) AS {result_column}
FROM rvbbit_raw r
        """.strip()

    # Handle typed output columns if specified
    if stmt.output_columns:
        # Generate typed column extraction from JSON result
        # Data is at: $.state.validated_output.{col_name} (for output_schema cascades)
        select_cols = []
        for col_name, col_type in stmt.output_columns:
            # Extract from state.validated_output (where output_schema results are stored)
            if col_type in ('VARCHAR', 'TEXT', 'STRING'):
                expr = f"json_extract_string(_raw_result, '$.state.validated_output.{col_name}') AS {col_name}"
            elif col_type in ('BIGINT', 'INTEGER', 'INT'):
                expr = f"CAST(json_extract(_raw_result, '$.state.validated_output.{col_name}') AS BIGINT) AS {col_name}"
            elif col_type in ('DOUBLE', 'FLOAT', 'REAL'):
                expr = f"CAST(json_extract(_raw_result, '$.state.validated_output.{col_name}') AS DOUBLE) AS {col_name}"
            elif col_type == 'BOOLEAN':
                expr = f"CAST(json_extract(_raw_result, '$.state.validated_output.{col_name}') AS BOOLEAN) AS {col_name}"
            elif col_type == 'JSON':
                expr = f"json_extract(_raw_result, '$.state.validated_output.{col_name}') AS {col_name}"
            else:
                # Generic cast for other types
                expr = f"CAST(json_extract(_raw_result, '$.state.validated_output.{col_name}') AS {col_type}) AS {col_name}"

            select_cols.append(expr)

        # Replace the final SELECT with typed extraction
        # Find the last SELECT in the rewritten query
        lines = rewritten.split('\n')
        select_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if 'SELECT' in lines[i]:
                select_idx = i
                break

        if select_idx is not None:
            # Replace from SELECT onwards
            rewritten = '\n'.join(lines[:select_idx]) + f"""
SELECT
  r.* EXCLUDE (_raw_result),
  {',\n  '.join(select_cols)}
FROM rvbbit_raw r
            """.strip()

    # Handle table materialization if requested
    as_table = stmt.with_options.get('as_table')
    if as_table:
        # Wrap query to materialize results to a table
        rewritten = f"""
WITH rvbbit_data AS (
  {rewritten}
),
rvbbit_materialize AS (
  SELECT rvbbit_materialize_table(
    '{as_table}',
    (SELECT json_group_array(to_json(r)) FROM rvbbit_data r)
  ) as metadata
)
SELECT * FROM {as_table}
        """.strip()

    return rewritten


def _rewrite_run(stmt: RVBBITStatement) -> str:
    """
    Rewrite RVBBIT RUN to batch cascade execution.

    RUN executes cascade ONCE over entire dataset (vs MAP = once per row).

    Args:
        stmt: Parsed RUN statement

    Returns:
        Rewritten SQL

    Example:
        Input:  RVBBIT RUN 'batch.yaml' USING (SELECT * FROM t LIMIT 500)
                WITH (as_table = 'batch_data')

        Output: SELECT rvbbit_run_batch(
                  'batch.yaml',
                  (SELECT json_group_array(to_json(i)) FROM (...) i),
                  'batch_data'
                ) AS result
    """
    using_query = _ensure_limit_run(stmt.using_query)

    # Get table name from WITH options (or generate one)
    table_name = stmt.with_options.get('as_table')
    if not table_name:
        # Auto-generate table name
        import hashlib
        import time
        query_hash = hashlib.md5(f"{stmt.cascade_path}{using_query}{time.time()}".encode()).hexdigest()[:8]
        table_name = f"_rvbbit_batch_{query_hash}"

    # Use rvbbit_run_batch UDF that:
    # 1. Creates temp table from JSON array
    # 2. Runs cascade with table reference
    # 3. Returns metadata row
    rewritten = f"""
SELECT rvbbit_run_batch(
  '{stmt.cascade_path}',
  (SELECT json_group_array(to_json(i)) FROM ({using_query}) AS i),
  '{table_name}'
) AS result
    """.strip()

    return rewritten


def _ensure_limit(query: str) -> str:
    """Ensure query has LIMIT for safety."""
    if re.search(r'\bLIMIT\s+\d+', query.upper()):
        return query
    return f"{query.rstrip().rstrip(';')} LIMIT {DEFAULT_MAP_LIMIT}"


def _ensure_limit_run(query: str) -> str:
    """
    Ensure RUN query has LIMIT for safety.

    RUN is for batches, so allow up to 10,000 rows by default.
    """
    DEFAULT_RUN_LIMIT = 10000

    if re.search(r'\bLIMIT\s+\d+', query.upper()):
        return query

    return f"{query.rstrip().rstrip(';')} LIMIT {DEFAULT_RUN_LIMIT}"


# ============================================================================
# Info
# ============================================================================

def get_rewriter_info() -> Dict[str, Any]:
    """Get rewriter information."""
    return {
        'version': '0.3.0',
        'cell': 'Cell 3',
        'supported_features': {
            'RVBBIT MAP': True,
            'RVBBIT MAP PARALLEL': True,  # Syntax supported, threading TBD
            'RVBBIT RUN': True,
            'AS alias': True,
            'WITH options': True,
            'Auto-LIMIT': True
        }
    }
