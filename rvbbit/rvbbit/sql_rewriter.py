"""
SQL Rewriter for RVBBIT MAP/RUN Syntax (Clean Version)

Phase 1-2: MAP with optional PARALLEL
"""

import re
from typing import Optional, Dict, Any, Tuple
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


# ============================================================================
# Main Entry Point
# ============================================================================

def rewrite_rvbbit_syntax(query: str) -> str:
    """Detect and rewrite RVBBIT MAP/RUN syntax."""
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

    # Extract AS alias
    result_alias = None
    as_match = re.match(r'AS\s+(\w+)', remaining, re.IGNORECASE)
    if as_match:
        result_alias = as_match.group(1)
        remaining = remaining[as_match.end():].strip()

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

    return RVBBITStatement(
        mode=mode,
        cascade_path=cascade_path,
        using_query=using_query,
        result_alias=result_alias,
        with_options=with_options,
        parallel=parallel
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


# ============================================================================
# MAP Rewrite
# ============================================================================

def _rewrite_map(stmt: RVBBITStatement) -> str:
    """Rewrite RVBBIT MAP to row-wise UDF calls."""
    using_query = _ensure_limit(stmt.using_query)
    result_column = stmt.result_alias or stmt.with_options.get('result_column', DEFAULT_RESULT_COLUMN)

    # For Phase 2 MVP: PARALLEL syntax is accepted but executes sequentially
    # Real ThreadPoolExecutor optimization deferred to Phase 2B
    # This allows users to write PARALLEL queries that work today and get faster later
    if stmt.parallel is not None:
        # TODO Phase 2B: Add actual concurrent execution with ThreadPoolExecutor
        pass  # Fall through to sequential logic

    # Sequential execution (works for both MAP and MAP PARALLEL currently)
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
