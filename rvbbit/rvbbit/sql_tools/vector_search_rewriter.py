"""
Vector Search Rewriter - SQL sugar for vector search table functions.

Rewrites natural field-aware syntax to underlying vector search plumbing:

FOUR SEARCH FUNCTIONS:

1. VECTOR_SEARCH - Pure semantic (ClickHouse, fastest)
   VECTOR_SEARCH('query', table.column, limit[, min_score])
   → read_json_auto(vector_search_json_3/4(...)) WHERE metadata.column_name = 'column'

2. ELASTIC_SEARCH - Pure semantic (Elastic)
   ELASTIC_SEARCH('query', table.column, limit[, min_score])
   → vector_search_elastic(...) with weights (1.0, 0.0)

3. HYBRID_SEARCH - Semantic + keyword (Elastic)
   HYBRID_SEARCH('query', table.column, limit[, min_score, sem_weight, kw_weight])
   → vector_search_elastic(...) with custom weights

4. KEYWORD_SEARCH - Pure BM25 keyword (Elastic)
   KEYWORD_SEARCH('query', table.column, limit[, min_score])
   → vector_search_elastic(...) with weights (0.0, 1.0)

Key innovation: table.column syntax (identifier) instead of 'table.column' (string)
- IDE autocomplete support
- Natural SQL feel
- Automatic metadata.column_name filtering (for ClickHouse)
- Clear functional intent (semantic vs keyword vs hybrid)
"""

import re
import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class VectorSearchCall:
    """A parsed VECTOR_SEARCH or HYBRID_SEARCH table function call."""
    function_name: str      # "VECTOR_SEARCH", "ELASTIC_SEARCH", "HYBRID_SEARCH", or "KEYWORD_SEARCH"
    query_text: str         # Search query
    field_ref: str          # "table.column"
    table_name: str         # "table"
    column_name: str        # "column"
    limit: int              # Max results
    min_score: Optional[float] = None      # Score threshold
    semantic_weight: Optional[float] = None  # For HYBRID_SEARCH
    keyword_weight: Optional[float] = None   # For HYBRID_SEARCH
    index_name: Optional[str] = None       # Elastic index name (for ELASTIC/HYBRID/KEYWORD)
    start_pos: int = 0      # Character position in SQL
    end_pos: int = 0        # Character position in SQL


def has_vector_search_calls(sql: str) -> bool:
    """
    Check if SQL contains any vector search table functions.

    Detects:
    - VECTOR_SEARCH (ClickHouse pure semantic)
    - ELASTIC_SEARCH (Elastic pure semantic)
    - HYBRID_SEARCH (Elastic semantic + keyword)
    - KEYWORD_SEARCH (Elastic pure keyword)

    Returns:
        True if query uses vector search sugar syntax
    """
    sql_upper = sql.upper()
    return (
        'VECTOR_SEARCH(' in sql_upper or
        'ELASTIC_SEARCH(' in sql_upper or
        'HYBRID_SEARCH(' in sql_upper or
        'KEYWORD_SEARCH(' in sql_upper
    )


def rewrite_vector_search(sql: str) -> str:
    """
    Rewrite all vector search table functions.

    Handles:
    1. VECTOR_SEARCH('query', table.column, limit[, min_score])
       → ClickHouse pure semantic (fastest)

    2. ELASTIC_SEARCH('query', table.column, limit[, min_score])
       → Elastic pure semantic (when you need Elastic specifically)

    3. HYBRID_SEARCH('query', table.column, limit[, min_score, sem_weight, kw_weight])
       → Elastic semantic + keyword mix

    4. KEYWORD_SEARCH('query', table.column, limit[, min_score])
       → Elastic pure BM25 keyword search

    Args:
        sql: SQL query to rewrite

    Returns:
        Rewritten SQL with underlying vector search calls

    Examples:
        >>> rewrite_vector_search("SELECT * FROM VECTOR_SEARCH('q', t.c, 10)")
        "SELECT * FROM read_json_auto(vector_search_json_3('q', 't.c', 10)) WHERE metadata.column_name = 'c'"

        >>> rewrite_vector_search("SELECT * FROM KEYWORD_SEARCH('q', t.c, 10)")
        "SELECT * FROM vector_search_elastic_4('q', 't', 'c', 10)"
    """
    if not has_vector_search_calls(sql):
        return sql

    result = sql

    # Find and rewrite all function types (in reverse order to preserve positions)
    # Order matters - do most specific patterns first to avoid partial matches

    # 1. HYBRID_SEARCH (most specific - has weights)
    hybrid_calls = _find_hybrid_search_calls(sql)
    for call in reversed(hybrid_calls):
        replacement = _generate_hybrid_search_rewrite(call)
        result = result[:call.start_pos] + replacement + result[call.end_pos:]

    # 2. KEYWORD_SEARCH (pure BM25)
    keyword_calls = _find_keyword_search_calls(sql)
    for call in reversed(keyword_calls):
        replacement = _generate_keyword_search_rewrite(call)
        result = result[:call.start_pos] + replacement + result[call.end_pos:]

    # 3. ELASTIC_SEARCH (pure semantic on Elastic)
    elastic_calls = _find_elastic_search_calls(sql)
    for call in reversed(elastic_calls):
        replacement = _generate_elastic_search_rewrite(call)
        result = result[:call.start_pos] + replacement + result[call.end_pos:]

    # 4. VECTOR_SEARCH (ClickHouse pure semantic - do last to avoid matching ELASTIC_SEARCH substring)
    vector_calls = _find_vector_search_calls(sql)
    for call in reversed(vector_calls):
        replacement = _generate_vector_search_rewrite(call)
        result = result[:call.start_pos] + replacement + result[call.end_pos:]

    return result


def _find_vector_search_calls(sql: str) -> List[VectorSearchCall]:
    """
    Find all VECTOR_SEARCH(...) calls in SQL.

    Uses regex for MVP (token-based in future).

    Returns:
        List of VectorSearchCall objects
    """
    from .field_reference import parse_field_reference

    calls = []

    # Pattern: VECTOR_SEARCH('query', table.column, limit[, min_score])
    # Group 1: Full match (for position)
    # Group 2: Query string
    # Group 3: Field reference
    # Group 4: Rest of args

    pattern = re.compile(
        r'\bVECTOR_SEARCH\s*\(\s*'
        r'(["\'])(.*?)\1\s*,\s*'  # Query string
        r'([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*'  # Field ref
        r'([^)]+)'  # Rest of args
        r'\)',
        re.IGNORECASE
    )

    for match in pattern.finditer(sql):
        query_text = match.group(2)
        field_ref_str = match.group(3)
        rest_args = match.group(4).strip()

        # Parse field reference
        field_ref = parse_field_reference(field_ref_str)
        if not field_ref:
            log.warning(f"Invalid field reference in VECTOR_SEARCH: {field_ref_str}")
            continue

        # Parse rest of args (limit[, min_score])
        args = [arg.strip() for arg in rest_args.split(',')]

        limit = int(args[0]) if args else 10
        min_score = float(args[1]) if len(args) > 1 else None

        call = VectorSearchCall(
            function_name="VECTOR_SEARCH",
            query_text=query_text,
            field_ref=field_ref_str,
            table_name=field_ref.table,
            column_name=field_ref.column,
            limit=limit,
            min_score=min_score,
            start_pos=match.start(),
            end_pos=match.end()
        )
        calls.append(call)

    return calls


def _find_hybrid_search_calls(sql: str) -> List[VectorSearchCall]:
    """
    Find all HYBRID_SEARCH(...) calls in SQL.

    Pattern: HYBRID_SEARCH('query', table.column, limit[, min_score, sem_weight, kw_weight])

    Returns:
        List of VectorSearchCall objects
    """
    from .field_reference import parse_field_reference

    calls = []

    pattern = re.compile(
        r'\bHYBRID_SEARCH\s*\(\s*'
        r'(["\'])(.*?)\1\s*,\s*'  # Query string
        r'([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*'  # Field ref
        r'([^)]+)'  # Rest of args
        r'\)',
        re.IGNORECASE
    )

    for match in pattern.finditer(sql):
        query_text = match.group(2)
        field_ref_str = match.group(3)
        rest_args = match.group(4).strip()

        # Parse field reference
        field_ref = parse_field_reference(field_ref_str)
        if not field_ref:
            log.warning(f"Invalid field reference in HYBRID_SEARCH: {field_ref_str}")
            continue

        # Parse rest of args (limit[, min_score, sem_weight, kw_weight, index_name])
        args = [arg.strip() for arg in rest_args.split(',')]

        limit = int(args[0]) if args else 10
        min_score = float(args[1]) if len(args) > 1 else None
        semantic_weight = float(args[2]) if len(args) > 2 else None
        keyword_weight = float(args[3]) if len(args) > 3 else None

        # Index name is last arg (quoted string)
        index_name = None
        if len(args) > 4:
            index_arg = args[4].strip()
            # Remove quotes if present
            if (index_arg.startswith("'") and index_arg.endswith("'")) or \
               (index_arg.startswith('"') and index_arg.endswith('"')):
                index_name = index_arg[1:-1]

        call = VectorSearchCall(
            function_name="HYBRID_SEARCH",
            query_text=query_text,
            field_ref=field_ref_str,
            table_name=field_ref.table,
            column_name=field_ref.column,
            limit=limit,
            min_score=min_score,
            semantic_weight=semantic_weight,
            keyword_weight=keyword_weight,
            index_name=index_name,
            start_pos=match.start(),
            end_pos=match.end()
        )
        calls.append(call)

    return calls


def _generate_vector_search_rewrite(call: VectorSearchCall) -> str:
    """
    Generate rewritten SQL for VECTOR_SEARCH call.

    Wraps with read_json_auto() and adds metadata.column_name filter.

    Args:
        call: Parsed VectorSearchCall

    Returns:
        Rewritten SQL fragment

    Example:
        VECTOR_SEARCH('query', bird_line.text, 10)
        →
        read_json_auto(
          vector_search_json_3('query', 'bird_line.text', 10)
        )
        WHERE metadata.column_name = 'text'
    """
    # Build inner function call
    # Use numbered functions based on arg count
    if call.min_score is None:
        # 3 args: query, field, limit
        inner_call = f"vector_search_json_3('{call.query_text}', '{call.field_ref}', {call.limit})"
    else:
        # 4 args: query, field, limit, min_score
        inner_call = f"vector_search_json_4('{call.query_text}', '{call.field_ref}', {call.limit}, {call.min_score})"

    # The vector_search_json_* UDFs return a FILE PATH to JSON (for read_json_auto)
    # Simply wrap in read_json_auto - it handles file paths correctly!
    rewritten = f"read_json_auto({inner_call})"

    return rewritten


def _generate_hybrid_search_rewrite(call: VectorSearchCall) -> str:
    """
    Generate rewritten SQL for HYBRID_SEARCH call.

    Calls vector_search_elastic with proper args + metadata column filtering.

    Cascade signature: (query, source_table, limit, threshold, sem_weight, kw_weight, index_name)

    Args:
        call: Parsed VectorSearchCall

    Returns:
        Rewritten SQL fragment

    Example:
        HYBRID_SEARCH('query', bird_line.text, 10, 0.5, 0.8, 0.2)
        →
        (SELECT * FROM vector_search_elastic('query', 'bird_line', 10, 0.5, 0.8, 0.2)
         WHERE metadata.column_name = 'text')
    """
    # Build args for vector_search_elastic cascade
    # Args: query, source_table, limit, threshold, semantic_weight, keyword_weight, index_name
    args = [f"'{call.query_text}'"]

    # source_table (use table name for filtering)
    if call.table_name:
        args.append(f"'{call.table_name}'")

    # limit
    args.append(str(call.limit))

    # threshold (min_score)
    if call.min_score is not None:
        args.append(str(call.min_score))

    # semantic_weight
    if call.semantic_weight is not None:
        args.append(str(call.semantic_weight))

    # keyword_weight
    if call.keyword_weight is not None:
        args.append(str(call.keyword_weight))

    # index_name (optional)
    if call.index_name:
        args.append(f"'{call.index_name}'")

    # Generate function call (cascade handles all arities, returns JSON array)
    # Iterate through array indices to extract rows (unnest doesn't work on JSON strings)
    rewritten = f"""
(WITH _search_result AS (
  SELECT vector_search_elastic({', '.join(args)}) AS result_json
),
_array_indices AS (
  SELECT unnest(generate_series(0, CAST(json_array_length(result_json) AS INTEGER) - 1)) AS idx
  FROM _search_result
)
SELECT
  json_extract_string(json_extract(result_json, '$[' || idx || ']'), '$.id') AS id,
  json_extract_string(json_extract(result_json, '$[' || idx || ']'), '$.text') AS text,
  CAST(json_extract(json_extract(result_json, '$[' || idx || ']'), '$.similarity') AS DOUBLE) AS similarity,
  CAST(json_extract(json_extract(result_json, '$[' || idx || ']'), '$.score') AS DOUBLE) AS score
FROM _search_result, _array_indices)
    """.strip()

    return rewritten


def _find_elastic_search_calls(sql: str) -> List[VectorSearchCall]:
    """
    Find all ELASTIC_SEARCH(...) calls in SQL.

    Pure semantic search on Elastic backend (not ClickHouse).
    Use when you specifically need Elastic, or want Elastic features.

    Pattern: ELASTIC_SEARCH('query', table.column, limit[, min_score])

    Returns:
        List of VectorSearchCall objects
    """
    from .field_reference import parse_field_reference

    calls = []

    pattern = re.compile(
        r'\bELASTIC_SEARCH\s*\(\s*'
        r'(["\'])(.*?)\1\s*,\s*'  # Query string
        r'([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*'  # Field ref
        r'([^)]+)'  # Rest of args
        r'\)',
        re.IGNORECASE
    )

    for match in pattern.finditer(sql):
        query_text = match.group(2)
        field_ref_str = match.group(3)
        rest_args = match.group(4).strip()

        field_ref = parse_field_reference(field_ref_str)
        if not field_ref:
            log.warning(f"Invalid field reference in ELASTIC_SEARCH: {field_ref_str}")
            continue

        # Parse rest of args (limit[, min_score, index_name])
        args = [arg.strip() for arg in rest_args.split(',')]
        limit = int(args[0]) if args else 10
        min_score = float(args[1]) if len(args) > 1 else None

        # Index name is optional last arg (quoted string)
        index_name = None
        if len(args) > 2:
            index_arg = args[2].strip()
            if (index_arg.startswith("'") and index_arg.endswith("'")) or \
               (index_arg.startswith('"') and index_arg.endswith('"')):
                index_name = index_arg[1:-1]

        call = VectorSearchCall(
            function_name="ELASTIC_SEARCH",
            query_text=query_text,
            field_ref=field_ref_str,
            table_name=field_ref.table,
            column_name=field_ref.column,
            limit=limit,
            min_score=min_score,
            semantic_weight=1.0,  # Pure semantic
            keyword_weight=0.0,   # No keyword
            index_name=index_name,
            start_pos=match.start(),
            end_pos=match.end()
        )
        calls.append(call)

    return calls


def _find_keyword_search_calls(sql: str) -> List[VectorSearchCall]:
    """
    Find all KEYWORD_SEARCH(...) calls in SQL.

    Pure BM25 keyword search on Elastic (no semantic vectors).

    Pattern: KEYWORD_SEARCH('query', table.column, limit[, min_score])

    Returns:
        List of VectorSearchCall objects
    """
    from .field_reference import parse_field_reference

    calls = []

    pattern = re.compile(
        r'\bKEYWORD_SEARCH\s*\(\s*'
        r'(["\'])(.*?)\1\s*,\s*'  # Query string
        r'([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*'  # Field ref
        r'([^)]+)'  # Rest of args
        r'\)',
        re.IGNORECASE
    )

    for match in pattern.finditer(sql):
        query_text = match.group(2)
        field_ref_str = match.group(3)
        rest_args = match.group(4).strip()

        field_ref = parse_field_reference(field_ref_str)
        if not field_ref:
            log.warning(f"Invalid field reference in KEYWORD_SEARCH: {field_ref_str}")
            continue

        # Parse rest of args (limit[, min_score, index_name])
        args = [arg.strip() for arg in rest_args.split(',')]
        limit = int(args[0]) if args else 10
        min_score = float(args[1]) if len(args) > 1 else None

        # Index name is optional last arg (quoted string)
        index_name = None
        if len(args) > 2:
            index_arg = args[2].strip()
            if (index_arg.startswith("'") and index_arg.endswith("'")) or \
               (index_arg.startswith('"') and index_arg.endswith('"')):
                index_name = index_arg[1:-1]

        call = VectorSearchCall(
            function_name="KEYWORD_SEARCH",
            query_text=query_text,
            field_ref=field_ref_str,
            table_name=field_ref.table,
            column_name=field_ref.column,
            limit=limit,
            min_score=min_score,
            semantic_weight=0.0,  # No semantic
            keyword_weight=1.0,   # Pure keyword
            index_name=index_name,
            start_pos=match.start(),
            end_pos=match.end()
        )
        calls.append(call)

    return calls


def _generate_elastic_search_rewrite(call: VectorSearchCall) -> str:
    """
    Generate rewritten SQL for ELASTIC_SEARCH call.

    Pure semantic search on Elastic (uses vector_search_elastic with 100% semantic weight).

    Cascade signature: (query, source_table, limit, threshold, sem_weight, kw_weight, index_name)

    Args:
        call: Parsed VectorSearchCall

    Returns:
        Rewritten SQL fragment

    Example:
        ELASTIC_SEARCH('query', bird_line.text, 10, 0.6, 'custom_idx')
        →
        (SELECT * FROM vector_search_elastic('query', 'bird_line', 10, 0.6, 1.0, 0.0, 'custom_idx')
         WHERE metadata.column_name = 'text')
    """
    # Build args for vector_search_elastic cascade
    args = [f"'{call.query_text}'"]

    # source_table
    if call.table_name:
        args.append(f"'{call.table_name}'")

    # limit
    args.append(str(call.limit))

    # threshold (min_score)
    min_score_val = call.min_score if call.min_score is not None else 0.0
    args.append(str(min_score_val))

    # semantic_weight (1.0 for pure semantic)
    args.append("1.0")

    # keyword_weight (0.0 for pure semantic)
    args.append("0.0")

    # index_name (optional)
    if call.index_name:
        args.append(f"'{call.index_name}'")

    # Generate function call (cascade handles all arities, returns JSON array)
    # Iterate through array indices to extract rows (unnest doesn't work on JSON strings)
    rewritten = f"""
(WITH _search_result AS (
  SELECT vector_search_elastic({', '.join(args)}) AS result_json
),
_array_indices AS (
  SELECT unnest(generate_series(0, CAST(json_array_length(result_json) AS INTEGER) - 1)) AS idx
  FROM _search_result
)
SELECT
  json_extract_string(json_extract(result_json, '$[' || idx || ']'), '$.id') AS id,
  json_extract_string(json_extract(result_json, '$[' || idx || ']'), '$.text') AS text,
  CAST(json_extract(json_extract(result_json, '$[' || idx || ']'), '$.similarity') AS DOUBLE) AS similarity,
  CAST(json_extract(json_extract(result_json, '$[' || idx || ']'), '$.score') AS DOUBLE) AS score
FROM _search_result, _array_indices)
    """.strip()

    return rewritten


def _generate_keyword_search_rewrite(call: VectorSearchCall) -> str:
    """
    Generate rewritten SQL for KEYWORD_SEARCH call.

    Pure BM25 keyword search on Elastic (uses vector_search_elastic with 100% keyword weight).

    Cascade signature: (query, source_table, limit, threshold, sem_weight, kw_weight, index_name)

    Args:
        call: Parsed VectorSearchCall

    Returns:
        Rewritten SQL fragment

    Example:
        KEYWORD_SEARCH('MacBook Pro M3', products.description, 20, 0.5, 'products_idx')
        →
        (SELECT * FROM vector_search_elastic('MacBook Pro M3', 'products', 20, 0.5, 0.0, 1.0, 'products_idx')
         WHERE metadata.column_name = 'description')
    """
    # Build args for vector_search_elastic cascade
    args = [f"'{call.query_text}'"]

    # source_table
    if call.table_name:
        args.append(f"'{call.table_name}'")

    # limit
    args.append(str(call.limit))

    # threshold (min_score)
    min_score_val = call.min_score if call.min_score is not None else 0.0
    args.append(str(min_score_val))

    # semantic_weight (0.0 for pure keyword)
    args.append("0.0")

    # keyword_weight (1.0 for pure keyword)
    args.append("1.0")

    # index_name (optional)
    if call.index_name:
        args.append(f"'{call.index_name}'")

    # Generate function call (cascade handles all arities, returns JSON array)
    # Iterate through array indices to extract rows (unnest doesn't work on JSON strings)
    rewritten = f"""
(WITH _search_result AS (
  SELECT vector_search_elastic({', '.join(args)}) AS result_json
),
_array_indices AS (
  SELECT unnest(generate_series(0, CAST(json_array_length(result_json) AS INTEGER) - 1)) AS idx
  FROM _search_result
)
SELECT
  json_extract_string(json_extract(result_json, '$[' || idx || ']'), '$.id') AS id,
  json_extract_string(json_extract(result_json, '$[' || idx || ']'), '$.text') AS text,
  CAST(json_extract(json_extract(result_json, '$[' || idx || ']'), '$.similarity') AS DOUBLE) AS similarity,
  CAST(json_extract(json_extract(result_json, '$[' || idx || ']'), '$.score') AS DOUBLE) AS score
FROM _search_result, _array_indices)
    """.strip()

    return rewritten


# ============================================================================
# Integration Test
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("VECTOR SEARCH REWRITER TEST")
    print("=" * 80)

    test_cases = [
        # VECTOR_SEARCH (ClickHouse pure semantic)
        ("VECTOR_SEARCH: basic",
         "SELECT * FROM VECTOR_SEARCH('climate', articles.content, 10)",
         ["read_json_auto", "vector_search_json_3", "metadata.column_name = 'content'"]),

        ("VECTOR_SEARCH: with min_score",
         "SELECT * FROM VECTOR_SEARCH('AI', papers.abstract, 5, 0.7)",
         ["read_json_auto", "vector_search_json_4", "0.7", "metadata.column_name = 'abstract'"]),

        # ELASTIC_SEARCH (Elastic pure semantic)
        ("ELASTIC_SEARCH: basic",
         "SELECT * FROM ELASTIC_SEARCH('climate', articles.content, 10)",
         ["vector_search_elastic_7", "'articles'", "'content'", "1.0", "0.0"]),

        ("ELASTIC_SEARCH: with min_score",
         "SELECT * FROM ELASTIC_SEARCH('policy', docs.text, 20, 0.6)",
         ["vector_search_elastic_7", "0.6", "1.0", "0.0"]),

        # HYBRID_SEARCH (Elastic semantic + keyword)
        ("HYBRID_SEARCH: basic",
         "SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 10)",
         ["vector_search_elastic_4", "'Venezuela'", "'bird_line'", "'text'"]),

        ("HYBRID_SEARCH: with weights",
         "SELECT * FROM HYBRID_SEARCH('climate', articles.content, 20, 0.5, 0.8, 0.2)",
         ["vector_search_elastic_7", "0.5", "0.8", "0.2"]),

        # KEYWORD_SEARCH (Elastic pure BM25)
        ("KEYWORD_SEARCH: basic",
         "SELECT * FROM KEYWORD_SEARCH('MacBook Pro M3', products.description, 10)",
         ["vector_search_elastic_7", "'products'", "'description'", "0.0", "1.0"]),

        ("KEYWORD_SEARCH: with min_score",
         "SELECT * FROM KEYWORD_SEARCH('SKU-12345', products.sku, 5, 0.8)",
         ["vector_search_elastic_7", "0.8", "0.0", "1.0"]),
    ]

    for test_name, sql, expected_parts in test_cases:
        print(f"\n[{test_name}]")
        print(f"Input:  {sql}")
        result = rewrite_vector_search(sql)
        print(f"Output: {result[:200]}...")

        all_found = all(part in result for part in expected_parts)
        if all_found:
            print("✅ PASS")
        else:
            print("❌ FAIL")
            for part in expected_parts:
                if part not in result:
                    print(f"  Missing: {part}")
