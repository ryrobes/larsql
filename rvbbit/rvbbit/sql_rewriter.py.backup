"""
SQL Rewriter for RVBBIT MAP/RUN Syntax

This module detects and rewrites RVBBIT-specific SQL syntax into standard
DuckDB SQL that calls rvbbit() and rvbbit_run() UDFs.

Syntax:
    RVBBIT MAP 'cascade.yaml' [AS result_alias]
    USING (SELECT ...)
    [WITH (option = value, ...)]

Example:
    RVBBIT MAP 'enrich.yaml' AS enriched
    USING (SELECT * FROM products LIMIT 10)

    Rewrites to:
    WITH rvbbit_input AS (SELECT * FROM products LIMIT 10)
    SELECT i.*, rvbbit_run('enrich.yaml', to_json(i)) AS enriched
    FROM rvbbit_input i
"""

import re
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass


# ============================================================================
# Exception Classes
# ============================================================================

class RVBBITSyntaxError(Exception):
    """Invalid RVBBIT SQL syntax."""
    pass


class RVBBITLimitError(Exception):
    """Query exceeds safety limits."""
    pass


class RVBBITBudgetError(Exception):
    """Estimated cost exceeds budget."""
    pass


# ============================================================================
# Configuration / Defaults
# ============================================================================

DEFAULT_MAP_LIMIT = 1000         # Auto-inject LIMIT for MAP if missing
DEFAULT_RESULT_COLUMN = 'result' # Default result column name
DEFAULT_CACHE = True             # Cache by default
DEFAULT_PARALLEL = 10            # Default concurrent workers for MAP PARALLEL


# ============================================================================
# Parsed Statement Representation
# ============================================================================

@dataclass
class RVBBITStatement:
    """Parsed RVBBIT statement."""
    mode: str                        # 'MAP' or 'RUN'
    cascade_path: str                # Path to cascade file
    using_query: str                 # Inner SQL query
    result_alias: Optional[str]      # AS alias (or None)
    with_options: Dict[str, Any]     # WITH options
    batch_size: Optional[int] = None # For MAP BATCH <n>
    parallel: Optional[int] = None   # For MAP PARALLEL <n>
    returning_clause: Optional[str] = None  # For RETURNING (...)


# ============================================================================
# Main Entry Point
# ============================================================================

def rewrite_rvbbit_syntax(query: str) -> str:
    """
    Detect and rewrite RVBBIT MAP/RUN syntax to standard SQL.

    Args:
        query: Raw SQL query (may contain RVBBIT syntax)

    Returns:
        Rewritten SQL using rvbbit() and rvbbit_run() UDFs
        (or original query if no RVBBIT syntax detected)

    Raises:
        RVBBITSyntaxError: Invalid RVBBIT syntax

    Example:
        >>> query = "RVBBIT MAP 'x.yaml' USING (SELECT a FROM t LIMIT 10)"
        >>> rewrite_rvbbit_syntax(query)
        'WITH rvbbit_input AS (SELECT a FROM t LIMIT 10) SELECT i.*, ...'
    """
    # Quick check: does this look like an RVBBIT statement?
    if not _is_rvbbit_statement(query):
        return query  # Passthrough

    # Debug: Log detection
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[SQL Rewriter] Detected RVBBIT syntax: {query[:100]}")

    # Parse the statement
    stmt = _parse_rvbbit_statement(query)

    logger.info(f"[SQL Rewriter] Parsed: mode={stmt.mode}, parallel={stmt.parallel}, cascade={stmt.cascade_path}")

    # Rewrite based on mode
    if stmt.mode == 'MAP':
        rewritten = _rewrite_map(stmt)
        logger.info(f"[SQL Rewriter] Rewritten MAP query (length: {len(rewritten)})")
        return rewritten
    elif stmt.mode == 'RUN':
        return _rewrite_run(stmt)
    else:
        raise RVBBITSyntaxError(f"Unknown mode: {stmt.mode}")


# ============================================================================
# Detection
# ============================================================================

def _is_rvbbit_statement(query: str) -> bool:
    """
    Check if query contains RVBBIT syntax.

    Returns:
        True if query contains RVBBIT MAP or RVBBIT RUN
    """
    query_upper = query.strip().upper()

    # Strip SQL comments before checking
    # Remove single-line comments (-- ...)
    lines = query_upper.split('\n')
    non_comment_lines = [line.split('--')[0].strip() for line in lines]
    clean_query = ' '.join(line for line in non_comment_lines if line)

    return (
        'RVBBIT MAP' in clean_query or
        'RVBBIT RUN' in clean_query
    )


# ============================================================================
# Parsing
# ============================================================================

def _parse_rvbbit_statement(query: str) -> RVBBITStatement:
    """
    Parse RVBBIT statement into components.

    Args:
        query: RVBBIT statement

    Returns:
        Parsed statement

    Raises:
        RVBBITSyntaxError: Invalid syntax
    """
    query = query.strip()

    # Strip SQL comments before parsing
    lines = query.split('\n')
    non_comment_lines = [line.split('--')[0] for line in lines]
    query = '\n'.join(non_comment_lines).strip()

    # Extract mode (MAP or RUN)
    mode_match = re.match(r'RVBBIT\s+(MAP|RUN)', query, re.IGNORECASE)
    if not mode_match:
        raise RVBBITSyntaxError("Expected RVBBIT MAP or RVBBIT RUN")

    mode = mode_match.group(1).upper()
    remaining = query[mode_match.end():].strip()

    # Extract optional PARALLEL <n> (only for MAP)
    parallel = None
    if mode == 'MAP':
        parallel_match = re.match(r'PARALLEL\s+(\d+)', remaining, re.IGNORECASE)
        if parallel_match:
            parallel = int(parallel_match.group(1))
            remaining = remaining[parallel_match.end():].strip()

    # Extract cascade path (string literal)
    cascade_match = re.match(r"'([^']+)'", remaining)
    if not cascade_match:
        raise RVBBITSyntaxError(
            "Expected cascade path as string literal after RVBBIT MAP/RUN\n"
            "Example: RVBBIT MAP 'cascades/enrich.yaml' ..."
        )

    cascade_path = cascade_match.group(1)
    remaining = remaining[cascade_match.end():].strip()

    # Extract optional AS alias
    result_alias = None
    as_match = re.match(r'AS\s+(\w+)', remaining, re.IGNORECASE)
    if as_match:
        result_alias = as_match.group(1)
        remaining = remaining[as_match.end():].strip()

    # Extract USING clause (balanced parentheses)
    if not remaining.upper().startswith('USING'):
        raise RVBBITSyntaxError(
            "Expected USING (SELECT ...) after cascade path\n"
            "Example: RVBBIT MAP 'x.yaml' USING (SELECT * FROM t LIMIT 10)"
        )

    remaining = remaining[5:].strip()  # Skip 'USING'

    using_query, remaining = _extract_balanced_parens(remaining)
    if using_query is None:
        raise RVBBITSyntaxError(
            "Expected balanced parentheses after USING\n"
            "Example: USING (SELECT * FROM t)"
        )

    # Extract optional WITH clause
    with_options = {}
    remaining = remaining.strip()
    if remaining.upper().startswith('WITH'):
        remaining = remaining[4:].strip()  # Skip 'WITH'
        with_clause, remaining = _extract_balanced_parens(remaining)
        if with_clause is None:
            raise RVBBITSyntaxError("Expected balanced parentheses after WITH")

        with_options = _parse_with_options(with_clause)

    # Build statement
    stmt = RVBBITStatement(
        mode=mode,
        cascade_path=cascade_path,
        using_query=using_query,
        result_alias=result_alias,
        with_options=with_options,
        parallel=parallel
    )

    return stmt


def _extract_balanced_parens(text: str) -> Tuple[Optional[str], str]:
    """
    Extract content within balanced parentheses.

    Args:
        text: Text starting with '('

    Returns:
        (content, remaining_text) or (None, text) if not starting with '('

    Example:
        >>> _extract_balanced_parens("(SELECT a FROM t) WITH ...")
        ('SELECT a FROM t', ' WITH ...')
    """
    if not text.startswith('('):
        return None, text

    depth = 0
    i = 0

    for i, char in enumerate(text):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                # Found matching closing paren
                content = text[1:i]  # Exclude outer parens
                remaining = text[i+1:]
                return content, remaining

    # Unbalanced parentheses
    raise RVBBITSyntaxError(
        f"Unbalanced parentheses in query\n"
        f"Missing closing ')' for: {text[:50]}..."
    )


def _parse_with_options(with_clause: str) -> Dict[str, Any]:
    """
    Parse WITH (key = value, ...) options.

    Args:
        with_clause: Content inside WITH (...)

    Returns:
        Dictionary of options

    Example:
        >>> _parse_with_options("cache = true, budget_dollars = 5.0")
        {'cache': True, 'budget_dollars': 5.0}
    """
    options = {}

    # Split by comma (being careful about nested parens/strings)
    parts = _smart_split(with_clause, ',')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Parse key = value
        if '=' not in part:
            raise RVBBITSyntaxError(
                f"Expected 'key = value' in WITH clause, got: {part}"
            )

        key, value = part.split('=', 1)
        key = key.strip()
        value = value.strip()

        # Parse value type
        options[key] = _parse_value(value)

    return options


def _smart_split(text: str, delimiter: str) -> list:
    """
    Split text by delimiter, respecting nested parens and quotes.

    Args:
        text: Text to split
        delimiter: Delimiter character

    Returns:
        List of parts
    """
    parts = []
    current = []
    depth = 0
    in_string = False
    string_char = None

    for char in text:
        # Handle string literals
        if char in ('"', "'"):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False

        # Handle parentheses (only outside strings)
        if not in_string:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1

        # Split on delimiter (only at depth 0, outside strings)
        if char == delimiter and depth == 0 and not in_string:
            parts.append(''.join(current))
            current = []
        else:
            current.append(char)

    # Add final part
    if current:
        parts.append(''.join(current))

    return parts


def _parse_value(value_str: str) -> Any:
    """
    Parse value string to Python type.

    Args:
        value_str: Value as string (e.g., "true", "5.0", "'hello'")

    Returns:
        Parsed value (bool, int, float, or str)
    """
    value_str = value_str.strip()

    # Boolean
    if value_str.lower() == 'true':
        return True
    if value_str.lower() == 'false':
        return False

    # String literal
    if value_str.startswith("'") and value_str.endswith("'"):
        return value_str[1:-1]
    if value_str.startswith('"') and value_str.endswith('"'):
        return value_str[1:-1]

    # Number
    try:
        if '.' in value_str:
            return float(value_str)
        else:
            return int(value_str)
    except ValueError:
        # Fallback: treat as string
        return value_str


# ============================================================================
# MAP Rewrite
# ============================================================================

def _rewrite_map(stmt: RVBBITStatement) -> str:
    """
    Rewrite RVBBIT MAP to row-wise UDF calls.

    Args:
        stmt: Parsed MAP statement

    Returns:
        Rewritten SQL

    Example (Sequential):
        Input:  RVBBIT MAP 'x.yaml' USING (SELECT a FROM t LIMIT 10)
        Output: WITH rvbbit_input AS (SELECT a FROM t LIMIT 10)
                SELECT i.*,
                  COALESCE(
                    json_extract_string(rvbbit_run(...), '$.state.output_extract'),
                    ...
                  ) AS result
                FROM rvbbit_input i

    Example (Parallel):
        Input:  RVBBIT MAP PARALLEL 5 'x.yaml' USING (SELECT a FROM t LIMIT 10)
        Output: WITH rvbbit_input AS (SELECT a FROM t LIMIT 10)
                SELECT * FROM rvbbit_map_parallel_unnest(
                  'x.yaml',
                  (SELECT list(to_json(i)) FROM rvbbit_input i),
                  5
                )
    """
    # Auto-inject LIMIT if missing
    using_query = _ensure_limit(stmt.using_query)

    # Determine result column name
    result_column = stmt.result_alias or stmt.with_options.get('result_column', DEFAULT_RESULT_COLUMN)

    # Check if PARALLEL specified
    if stmt.parallel is not None:
        # Use parallel batch execution
        max_workers = stmt.parallel
        # Create temp table, populate with parallel results, then query
        # This avoids complex JSON unnesting issues
        import uuid
        temp_table = f"_rvbbit_parallel_{uuid.uuid4().hex[:8]}"

        rewritten = f"""
WITH rvbbit_input AS (
  {using_query}
),
rvbbit_parallel_json AS (
  SELECT rvbbit_map_parallel(
    '{stmt.cascade_path}',
    (SELECT json_group_array(to_json(i)) FROM rvbbit_input i),
    {max_workers}
  ) AS results_json
),
rvbbit_results AS (
  SELECT unnest(results_json::JSON[]) AS row_json
  FROM rvbbit_parallel_json
)
SELECT
  json_extract_string(row_json, '$.' || k) AS value,
  k AS column_name
FROM rvbbit_results,
  LATERAL (SELECT unnest(json_keys(row_json)) AS k) AS keys
        """.strip()
        # Unnest JSON array and extract columns dynamically
        # Use json_structure to auto-detect schema
        rewritten = f"""
WITH rvbbit_input AS (
  {using_query}
),
rvbbit_parallel_result AS (
  SELECT rvbbit_map_parallel(
    '{stmt.cascade_path}',
    (SELECT json_group_array(to_json(i)) FROM rvbbit_input i),
    {max_workers}
  ) AS results_json
),
rvbbit_unnested AS (
  SELECT row_number() OVER () as _idx,
         unnest(results_json::JSON[]) AS row_json
  FROM rvbbit_parallel_result
)
SELECT * EXCLUDE (_idx, row_json),
       json_extract(row_json, '$') AS _all_cols
FROM rvbbit_unnested
        """.strip()
        # Actually - simplest solution: extract columns explicitly using json_extract_string
        # Get column names from first result and build explicit extraction
        rewritten = f"""
WITH rvbbit_input AS (
  {using_query}
),
rvbbit_parallel_result AS (
  SELECT rvbbit_map_parallel(
    '{stmt.cascade_path}',
    (SELECT json_group_array(to_json(i)) FROM rvbbit_input i),
    {max_workers}
  ) AS results_json
),
rvbbit_unnested AS (
  SELECT row_number() OVER () as _row_num,
         unnest(results_json::JSON[]) AS row_json
  FROM rvbbit_parallel_result
)
SELECT
  *,
  {result_column}
FROM (
  SELECT * REPLACE (
    json_extract_string(row_json, '$.' ||
      (SELECT column_name FROM (
        SELECT unnest(json_keys(row_json)) as column_name
      ) WHERE column_name != '{result_column}'
      LIMIT 1)
    ) AS first_col
  )
  FROM rvbbit_unnested
)
        """.strip()
        # Still too complex - let me just do the pragmatic solution
        return _rewrite_map_parallel_explicit(using_query, stmt.cascade_path, max_workers, result_column)

    # Sequential execution (original logic)
    # Build rewritten query with smart extraction
    # Try to extract useful value from cascade response:
    # 1. state.output_extract (most common for simple outputs)
    # 2. First output from outputs dict
    # 3. Full JSON as fallback
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

    return rewritten


def _rewrite_map_parallel_explicit(using_query: str, cascade_path: str, max_workers: int, result_column: str) -> str:
    """
    Rewrite MAP PARALLEL with column expansion.

    Extracts all JSON keys as columns using explicit extraction.
    """
    # Use LIST functions instead of JSON for cleaner unnesting
    return f"""
WITH rvbbit_input AS (
  {using_query}
),
rvbbit_parallel_raw AS (
  SELECT rvbbit_map_parallel(
    '{cascade_path}',
    (SELECT json_group_array(to_json(i)) FROM rvbbit_input i),
    {max_workers}
  ) AS results_json
),
rvbbit_unnested AS (
  SELECT
    row_number() OVER () AS _idx,
    elem AS row_json
  FROM (
    SELECT unnest(results_json::JSON[]) AS elem
    FROM rvbbit_parallel_raw
  )
),
rvbbit_with_keys AS (
  SELECT
    _idx,
    row_json,
    json_keys(row_json) AS keys_list
  FROM rvbbit_unnested
  LIMIT 1
)
SELECT
  json_extract_string(u.row_json, '$.' || k.key_name) AS value,
  k.key_name
FROM rvbbit_unnested u,
     rvbbit_with_keys wk,
     (SELECT unnest(wk.keys_list) AS key_name) k
WHERE u._idx = wk._idx
    """.strip()


def _ensure_limit(query: str) -> str:
    """
    Ensure query has a LIMIT clause for safety.

    If no LIMIT exists, auto-inject DEFAULT_MAP_LIMIT.

    Args:
        query: SQL query

    Returns:
        Query with LIMIT (either original or injected)
    """
    # Check if LIMIT already exists
    query_upper = query.upper()

    # Simple heuristic: look for LIMIT keyword
    # (This is naive but works for most cases; proper SQL parsing would be better)
    if re.search(r'\bLIMIT\s+\d+', query_upper):
        return query  # Already has LIMIT

    # No LIMIT found - auto-inject
    return f"{query.rstrip().rstrip(';')} LIMIT {DEFAULT_MAP_LIMIT}"


# ============================================================================
# RUN Rewrite (Stub for Phase 3)
# ============================================================================

def _rewrite_run(stmt: RVBBITStatement) -> str:
    """
    Rewrite RVBBIT RUN to batch UDF call.

    Args:
        stmt: Parsed RUN statement

    Returns:
        Rewritten SQL

    Note:
        This is a stub for Phase 3. Currently raises NotImplementedError.
    """
    raise NotImplementedError(
        "RVBBIT RUN is not yet implemented (coming in Phase 3).\n"
        "For now, use RVBBIT MAP for row-wise processing."
    )


# ============================================================================
# Utility Functions
# ============================================================================

def get_rewriter_info() -> Dict[str, Any]:
    """
    Get information about the SQL rewriter.

    Returns:
        Dictionary with version, supported features, defaults
    """
    return {
        'version': '0.2.0',
        'phase': 'Phase 2 (PARALLEL)',
        'supported_features': {
            'RVBBIT MAP': True,
            'RVBBIT MAP PARALLEL': True,
            'RVBBIT RUN': False,
            'MAP BATCH': False,
            'RETURNING': False,
            'AS alias': True,
            'WITH options': True,
            'Auto-LIMIT': True
        },
        'defaults': {
            'MAP_LIMIT': DEFAULT_MAP_LIMIT,
            'result_column': DEFAULT_RESULT_COLUMN,
            'cache': DEFAULT_CACHE,
            'parallel_workers': DEFAULT_PARALLEL
        }
    }
