"""
Embedding Operator Rewrites for Semantic SQL.

DEPRECATED: This module implemented "magic" query-level rewrites for EMBED(...) and
VECTOR_SEARCH(...). The project now uses an explicit-only policy for these:
  - `semantic_embed(text)` (pure)
  - `semantic_embed_with_storage(text, model, source_table, column_name, source_id)` (explicit storage)
  - `read_json_auto(vector_search_json_N(...))` (explicit vector search)

Keep this file only as historical reference; it is no longer called from the main
SQL rewrite pipeline.

These functions should be integrated into semantic_operators.py by:
1. Adding patterns to _has_semantic_operator_in_line()
2. Adding rewrite calls to _rewrite_line()

Example Integration:
    # In _has_semantic_operator_in_line():
    patterns = [
        ...existing patterns...,
        r'\bEMBED\s*\(',
        r'\bVECTOR_SEARCH\s*\(',
        r'\bSIMILAR_TO\b',
    ]

    # In _rewrite_line():
    # 12. Embedding operators
    result = _rewrite_embed(result, annotation_prefix)
    result = _rewrite_vector_search(result, annotation_prefix)
    result = _rewrite_similar_to(result, annotation_prefix)
"""

import re
import logging

log = logging.getLogger(__name__)


# ============================================================================
# EMBED() Function Rewriter
# ============================================================================

def _rewrite_embed_query_level(query: str, annotation_prefix: str = "") -> str:
    """
    Query-level EMBED() rewrite with smart table/ID context injection.

    When users write:
        SELECT id, EMBED(description) FROM products;

    We rewrite to:
        SELECT id, semantic_embed_with_storage(description, NULL, 'products', CAST(id AS VARCHAR)) FROM products;

    This allows the cascade to store embeddings in rvbbit_embeddings with proper
    table/row associations, enabling VECTOR_SEARCH to find them!

    This is MUCH better than competitors (PostgresML, pgvector) which require:
    - Manual ALTER TABLE ADD COLUMN
    - Explicit UPDATE statements
    - Offline batch scripts

    Args:
        query: Full SQL query
        annotation_prefix: Optional annotation text

    Returns:
        Query with context-injected EMBED() calls
    """
    if 'EMBED(' not in query.upper():
        return query

    # Use context injection to add table/ID parameters
    from .embed_context_injection import inject_embed_context
    return inject_embed_context(query)


def _rewrite_embed(line: str, annotation_prefix: str = "") -> str:
    """
    Line-level EMBED() rewrite (placeholder).

    Actual rewriting happens at query level via _rewrite_embed_query_level()
    to enable table/ID context injection.

    This is kept for compatibility but returns line unchanged.
    """
    return line


# ============================================================================
# VECTOR_SEARCH() Function Rewriter
# ============================================================================

def _rewrite_vector_search_query_level(query: str, annotation_prefix: str = "") -> str:
    """
    Rewrite VECTOR_SEARCH() as a query-level transformation using CTEs.

    DuckDB table functions can't contain subqueries, so we extract VECTOR_SEARCH
    calls to CTEs and replace them with table references.

    Strategy:
        1. Find all VECTOR_SEARCH() calls in the query
        2. Create a CTE for each that calls vector_search_json()
        3. Replace VECTOR_SEARCH() with read_json_auto(CTE result)

    Example:
        Before:
            SELECT * FROM VECTOR_SEARCH('eco', 'products', 10)

        After:
            WITH __vsr_0 AS (
                SELECT vector_search_json('eco', 'products', 10) as json_data
            )
            SELECT * FROM read_json_auto((SELECT json_data FROM __vsr_0))

    Args:
        query: Full SQL query
        annotation_prefix: Optional annotation text

    Returns:
        Rewritten query with CTEs
    """
    if 'VECTOR_SEARCH' not in query.upper():
        return query

    import random

    # Find all VECTOR_SEARCH calls
    pattern = r'\bVECTOR_SEARCH\s*\((.*?)\)'
    matches = list(re.finditer(pattern, query, re.IGNORECASE))

    if not matches:
        return query

    # Build CTEs for each VECTOR_SEARCH call
    ctes = []
    replacements = {}

    for idx, match in enumerate(matches):
        args = match.group(1)
        cte_name = f"__vsr_{idx}"

        # Count arguments (simple comma split)
        # Note: This doesn't handle nested commas in strings, but good enough for now
        arg_count = len([a.strip() for a in args.split(',') if a.strip()])

        # DuckDB doesn't support function overloading, so we use arity suffixes
        # like llm_aggregates: vector_search_json_2, vector_search_json_3, vector_search_json_4
        func_name = f"vector_search_json_{arg_count}"

        # Apply annotation prefix if present
        if annotation_prefix:
            arg_parts = args.split(',', 1)
            if len(arg_parts) > 0:
                query_part = arg_parts[0].strip()
                rest_args = arg_parts[1] if len(arg_parts) > 1 else ""

                if query_part.startswith("'") or query_part.startswith('"'):
                    quote = query_part[0]
                    query_text = query_part[1:-1] if query_part.endswith(quote) else query_part[1:]
                    new_query = f"{quote}{annotation_prefix}{query_text}{quote}"
                    args = f"{new_query}, {rest_args}" if rest_args else new_query

        # Create CTE that produces a table we can select from
        # UDF returns temp file path, read_json_auto parses it
        cte = f"{cte_name} AS (SELECT * FROM read_json_auto({func_name}({args})))"
        ctes.append(cte)

        # Store replacement - just reference the CTE table
        replacements[match.group(0)] = cte_name

    # Check if query already has WITH clause BEFORE replacing
    has_existing_with = re.match(r'^\s*WITH\s+', query, re.IGNORECASE)

    if has_existing_with:
        # Query already has WITH - insert our CTEs at the beginning
        # Pattern: WITH existing_cte AS (...) SELECT ...
        # Result: WITH __vsr_0 AS (...), existing_cte AS (...) SELECT ...

        # Find where existing CTEs end (before main SELECT)
        # We need to insert AFTER "WITH " but BEFORE the first user-defined CTE
        with_start = re.search(r'^\s*WITH\s+', query, re.IGNORECASE)
        if with_start:
            # Insert our CTEs right after "WITH "
            before_with = query[:with_start.end()]
            after_with = query[with_start.end():]

            # Build our CTEs
            our_ctes = ", ".join(ctes) + ", "

            # Replace VECTOR_SEARCH in the rest of the query
            for original, replacement in replacements.items():
                after_with = after_with.replace(original, replacement)

            result = before_with + our_ctes + after_with
    else:
        # No existing WITH - simple case
        # Replace VECTOR_SEARCH calls first
        result = query
        for original, replacement in replacements.items():
            result = result.replace(original, replacement)

        # Prepend new WITH clause
        cte_clause = "WITH " + ", ".join(ctes) + "\n"
        result = cte_clause + result

    log.debug(f"Rewrote VECTOR_SEARCH (query-level): Added {len(ctes)} CTE(s)")

    return result


def _rewrite_vector_search(line: str, annotation_prefix: str = "") -> str:
    """
    Placeholder for line-level rewrite (actual rewriting done at query level).

    The actual VECTOR_SEARCH rewriting happens in the query-level rewriter
    (_rewrite_vector_search_query_level) because DuckDB table functions can't
    contain subqueries.

    This function is kept for compatibility but just returns the line unchanged.
    """
    return line


# ============================================================================
# SIMILAR_TO Operator Rewriter
# ============================================================================

def _rewrite_similar_to(line: str, annotation_prefix: str = "") -> str:
    """
    Rewrite SIMILAR_TO operator to similar_to() function.

    Syntax:
        text1 SIMILAR_TO text2                → similar_to(text1, text2)
        description SIMILAR_TO 'reference'    → similar_to(description, 'reference')
        a.text SIMILAR_TO b.text              → similar_to(a.text, b.text)

    Handles both column-to-literal and column-to-column comparisons.

    Examples:
        Before: WHERE description SIMILAR_TO 'sustainable' > 0.7
        After:  WHERE similar_to(description, 'sustainable') > 0.7

        Before: SELECT a.name, b.name FROM t1 a, t2 b
                WHERE a.name SIMILAR_TO b.name > 0.8
        After:  SELECT a.name, b.name FROM t1 a, t2 b
                WHERE similar_to(a.name, b.name) > 0.8

    Args:
        line: SQL line to rewrite
        annotation_prefix: Optional annotation text (currently unused)

    Returns:
        Rewritten line with similar_to() calls
    """
    # Pattern: identifier SIMILAR_TO identifier/literal
    # Supports:
    #   - col SIMILAR_TO 'literal'
    #   - col SIMILAR_TO other_col
    #   - table.col SIMILAR_TO table2.col2

    # Regex pattern:
    # - Captures: (identifier) SIMILAR_TO (identifier|'literal'|"literal")
    # - identifier can be: col, table.col, schema.table.col
    #   pattern = r'([\w.]+)\s+SIMILAR_TO\s+([\w.]+|\'[^\']*\'|"[^"]*")'

    # More robust pattern that handles complex expressions
    # Captures: (left_expr) SIMILAR_TO (right_expr)
    # Where expr can be: col, table.col, 'literal', FUNC(args), etc.
    pattern = r'([\w.]+(?:\([^)]*\))?)\s+SIMILAR_TO\s+([\w.]+(?:\([^)]*\))?|\'[^\']*\'|"[^"]*")'

    def replace_similar_to(match):
        left = match.group(1)
        right = match.group(2)
        return f"similar_to({left}, {right})"

    result = re.sub(pattern, replace_similar_to, line, flags=re.IGNORECASE)

    if result != line:
        log.debug(f"Rewrote SIMILAR_TO: {line.strip()} → {result.strip()}")

    return result


# ============================================================================
# Integration Helpers
# ============================================================================

def has_embedding_operators(query: str) -> bool:
    """
    Check if query contains any embedding operators.

    Returns:
        True if query has EMBED, VECTOR_SEARCH, or SIMILAR_TO
    """
    patterns = [
        r'\bEMBED\s*\(',
        r'\bVECTOR_SEARCH\s*\(',
        r'\bSIMILAR_TO\b',
    ]

    for pattern in patterns:
        if re.search(pattern, query, re.IGNORECASE):
            return True

    return False


def rewrite_embedding_operators(line: str, annotation_prefix: str = "") -> str:
    """
    Apply all embedding operator rewrites to a line.

    This is a convenience function that applies all embedding rewrites in order.
    Can be called from semantic_operators.py's _rewrite_line().

    Args:
        line: SQL line to rewrite
        annotation_prefix: Optional annotation text for model hints

    Returns:
        Rewritten line with all embedding operators transformed
    """
    result = line

    # Order matters: process in order of complexity
    # 1. EMBED() - simplest (function call)
    result = _rewrite_embed(result, annotation_prefix)

    # 2. VECTOR_SEARCH() - complex (table function with wrapper)
    result = _rewrite_vector_search(result, annotation_prefix)

    # 3. SIMILAR_TO - infix operator (must be after other operators)
    result = _rewrite_similar_to(result, annotation_prefix)

    # 4. Generic dynamic rewrites (for user-created operators)
    from .dynamic_operators import rewrite_infix_operators
    result = rewrite_infix_operators(result)

    return result


# ============================================================================
# Example Integration Code
# ============================================================================

"""
To integrate into semantic_operators.py, add this to _has_semantic_operator_in_line():

    # Existing patterns...
    patterns = [
        r'\bMEANS\s+\'',
        r'\bABOUT\s+\'',
        # ... other patterns ...

        # Add embedding operator patterns
        r'\bEMBED\s*\(',
        r'\bVECTOR_SEARCH\s*\(',
        r'\bSIMILAR_TO\b',
    ]

And add this to the end of _rewrite_line() (before return):

    # 12. Embedding operators
    from rvbbit.sql_tools.embedding_operator_rewrites import rewrite_embedding_operators
    result = rewrite_embedding_operators(result, annotation_prefix)

That's it! The embedding operators will now be rewritten alongside existing semantic operators.
"""
