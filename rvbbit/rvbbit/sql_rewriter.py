"""
SQL Rewriter for RVBBIT MAP/RUN Syntax (Clean Version)

Phase 1-2: MAP with optional PARALLEL
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
    """Detect and rewrite RVBBIT MAP/RUN syntax."""
    # Check for EXPLAIN prefix
    explain_match = re.match(r'EXPLAIN\s+', query.strip(), re.IGNORECASE)
    if explain_match:
        from rvbbit.sql_explain import explain_rvbbit_map, format_explain_result

        # Strip EXPLAIN and parse statement
        inner_query = query[explain_match.end():].strip()

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

    if not _is_rvbbit_statement(query):
        return query

    stmt = _parse_rvbbit_statement(query)

    if stmt.mode == 'MAP':
        return _rewrite_map(stmt)
    elif stmt.mode == 'RUN':
        return _rewrite_run(stmt)
    else:
        raise RVBBITSyntaxError(f"Unknown mode: {stmt.mode}")


def _is_rvbbit_statement(query: str) -> bool:
    """Check if query contains RVBBIT syntax."""
    clean = query.strip().upper()
    lines = [line.split('--')[0].strip() for line in clean.split('\n')]
    clean = ' '.join(line for line in lines if line)
    return 'RVBBIT MAP' in clean or 'RVBBIT RUN' in clean


def _parse_rvbbit_statement(query: str) -> RVBBITStatement:
    """Parse RVBBIT statement."""
    query = query.strip()
    lines = [line.split('--')[0] for line in query.split('\n')]
    query = '\n'.join(lines).strip()

    # Extract mode
    mode_match = re.match(r'RVBBIT\s+(MAP|RUN)', query, re.IGNORECASE)
    if not mode_match:
        raise RVBBITSyntaxError("Expected RVBBIT MAP or RVBBIT RUN")

    mode = mode_match.group(1).upper()
    remaining = query[mode_match.end():].strip()

    # Extract DISTINCT (optional for MAP)
    is_distinct = False
    if mode == 'MAP':
        distinct_match = re.match(r'DISTINCT\s+', remaining, re.IGNORECASE)
        if distinct_match:
            is_distinct = True
            remaining = remaining[distinct_match.end():].strip()

    # Extract PARALLEL (optional)
    parallel = None
    if mode == 'MAP':
        parallel_match = re.match(r'PARALLEL\s+(\d+)', remaining, re.IGNORECASE)
        if parallel_match:
            parallel = int(parallel_match.group(1))
            remaining = remaining[parallel_match.end():].strip()

    # Extract cascade path
    cascade_match = re.match(r"'([^']+)'", remaining)
    if not cascade_match:
        raise RVBBITSyntaxError("Expected cascade path as string literal")

    cascade_path = cascade_match.group(1)
    remaining = remaining[cascade_match.end():].strip()

    # Extract AS alias or AS (col TYPE, ...) schema
    result_alias = None
    output_columns = None

    as_match = re.match(r'AS\s+(\w+)', remaining, re.IGNORECASE)
    if as_match:
        result_alias = as_match.group(1)
        remaining = remaining[as_match.end():].strip()
    else:
        # Try AS (col TYPE, col TYPE, ...)
        as_schema_match = re.match(r'AS\s*\(', remaining, re.IGNORECASE)
        if as_schema_match:
            remaining = remaining[as_schema_match.end():].strip()
            schema_content, remaining = _extract_balanced_parens('(' + remaining)
            if schema_content:
                output_columns = _parse_output_schema(schema_content)

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
    if stmt.with_options.get('distinct'):
        dedupe_by = stmt.with_options.get('dedupe_by')
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
    json_extract_string(_raw_result, '$.outputs.' || json_extract_string(_raw_result, '$.state.last_phase')),
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
    json_extract_string(_raw_result, '$.outputs.' || json_extract_string(_raw_result, '$.state.last_phase')),
    _raw_result
  ) AS {result_column}
FROM rvbbit_raw r
        """.strip()

    # Handle typed output columns if specified
    if stmt.output_columns:
        # Generate typed column extraction from JSON result
        select_cols = []
        for col_name, col_type in stmt.output_columns:
            if col_type in ('VARCHAR', 'TEXT', 'STRING'):
                expr = f"json_extract_string(_raw_result, '$.{col_name}') AS {col_name}"
            elif col_type in ('BIGINT', 'INTEGER', 'INT'):
                expr = f"CAST(json_extract(_raw_result, '$.{col_name}') AS BIGINT) AS {col_name}"
            elif col_type in ('DOUBLE', 'FLOAT', 'REAL'):
                expr = f"CAST(json_extract(_raw_result, '$.{col_name}') AS DOUBLE) AS {col_name}"
            elif col_type == 'BOOLEAN':
                expr = f"CAST(json_extract(_raw_result, '$.{col_name}') AS BOOLEAN) AS {col_name}"
            elif col_type == 'JSON':
                expr = f"json_extract(_raw_result, '$.{col_name}') AS {col_name}"
            else:
                # Generic cast for other types
                expr = f"CAST(json_extract(_raw_result, '$.{col_name}') AS {col_type}) AS {col_name}"

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
        'phase': 'Phase 3',
        'supported_features': {
            'RVBBIT MAP': True,
            'RVBBIT MAP PARALLEL': True,  # Syntax supported, threading TBD
            'RVBBIT RUN': True,
            'AS alias': True,
            'WITH options': True,
            'Auto-LIMIT': True
        }
    }
