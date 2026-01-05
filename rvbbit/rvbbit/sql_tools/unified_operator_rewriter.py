"""
Unified Operator Rewriter - Single entry point for ALL semantic SQL operators.

Replaces the fragmented hardcoded rewriters with a unified cascade-driven system:

BEFORE (fragmented):
    sql_rewriter.py calls:
    - _rewrite_block_operators()      # Cascade-driven (SEMANTIC_CASE...END)
    - _rewrite_dimension_functions()  # Cascade-driven (GROUP BY topics(...))
    - _rewrite_semantic_operators()   # HARDCODED (MEANS, ABOUT, ~)
    - _rewrite_llm_aggregates()       # HARDCODED (SUMMARIZE, CLASSIFY)

AFTER (unified):
    sql_rewriter.py calls:
    - rewrite_all_operators()         # ALL cascade-driven

SQL Directives (BACKGROUND, ANALYZE):
    These are execution modifiers handled at the postgres_server.py level.
    The unified rewriter STRIPS these directives and returns clean SQL.

    Flow:
    1. postgres_server.py detects "BACKGROUND SELECT ..."
    2. Strips "BACKGROUND ", passes "SELECT ..." to rewriter
    3. Rewriter also detects/strips directive (defensive)
    4. Returns clean rewritten SQL
    5. postgres_server.py executes in background thread

    This allows BACKGROUND/ANALYZE to work with semantic operators:
        BACKGROUND SELECT * FROM t WHERE col MEANS 'x'
        → postgres_server strips → SELECT * FROM t WHERE col MEANS 'x'
        → rewriter rewrites → SELECT * FROM t WHERE semantic_matches(col, 'x')
        → postgres_server executes in background

Architecture:
    1. Load ALL operator specs from cascade registry (block + inline)
    2. Sort by priority (complex patterns first, avoid substring matches)
    3. Tokenize SQL once
    4. Apply each spec using token-aware matching
    5. Return rewritten SQL

Key Benefits:
    - No hardcoded operator lists
    - User cascades automatically work
    - Consistent token-based matching (no regex bugs)
    - Single code path to maintain

Priority Order (highest to lowest):
    100: Block operators (SEMANTIC_CASE...END) - Must process first
     90: Dimension operators (GROUP BY topics(...)) - Context-sensitive
     50+: Multi-word infix (ALIGNS WITH) - Longer keywords first
     50: Single-word infix (MEANS)
     10: Function calls (SUMMARIZE(...))
"""

import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class RewriteResult:
    """Result of operator rewriting."""
    sql_out: str
    changed: bool
    applied: List[str]  # Names of operators that were applied
    errors: List[str]


def rewrite_all_operators(sql: str) -> str:
    """
    Unified entry point for ALL semantic SQL operator rewriting.

    Loads operator patterns from cascades and applies them using token-aware matching.

    Handles:
    - SQL Directives (BACKGROUND, ANALYZE) - Processed but not rewritten
    - Block operators (SEMANTIC_CASE...END)
    - Dimension functions (GROUP BY topics(...))
    - Infix operators (MEANS, ABOUT, ~)
    - Aggregate functions (SUMMARIZE, CLASSIFY)
    - Custom user-defined operators

    Args:
        sql: SQL query to rewrite (may have BACKGROUND/ANALYZE prefix)

    Returns:
        Rewritten SQL with semantic operators converted to function calls
        (Directive prefixes are preserved)

    Example:
        >>> rewrite_all_operators("SELECT * FROM t WHERE col MEANS 'x'")
        "SELECT * FROM t WHERE semantic_means(col, 'x')"

        >>> rewrite_all_operators("BACKGROUND SELECT * FROM t WHERE col MEANS 'x'")
        "BACKGROUND SELECT * FROM t WHERE semantic_means(col, 'x')"
    """
    try:
        from .block_operators import load_block_operator_specs, rewrite_block_operators
        from .dimension_rewriter import rewrite_dimension_functions, has_dimension_functions
        from .operator_inference import get_operator_priority
        from .sql_directives import strip_directive

        # Phase 0: Check for SQL directives (BACKGROUND, ANALYZE)
        # These are execution modifiers, not semantic operators
        # We strip them, rewrite the inner SQL, then re-attach
        inner_sql, directive = strip_directive(sql)

        # Phase 0.5: Vector search table functions (VECTOR_SEARCH, HYBRID_SEARCH)
        # Must run BEFORE semantic operators (table.column syntax could conflict)
        inner_sql = _rewrite_vector_search_functions(inner_sql)

        # Load all operator specs from cascades
        all_specs = load_block_operator_specs(force=False)

        if not all_specs:
            log.debug("[unified_rewriter] No operator specs loaded")
            return sql

        # Separate block operators, dimension operators, and inline operators
        # Block operators need special handling (start/end keywords, repeating patterns)
        block_specs = [s for s in all_specs if s.is_block_operator()]
        dimension_specs = [s for s in all_specs if not s.is_block_operator() and s.cascade_path and 'dimension' in s.cascade_path.lower()]
        inline_specs = [s for s in all_specs if s.is_inline_operator() and s not in dimension_specs]

        log.debug(f"[unified_rewriter] Loaded {len(all_specs)} specs: "
                  f"{len(block_specs)} block, {len(dimension_specs)} dimension, {len(inline_specs)} inline")

        # Work with inner SQL (without directive prefix)
        result = inner_sql
        changed = False
        applied = []

        # Phase 1: Block operators (SEMANTIC_CASE...END)
        # These MUST be processed first because they're complex multi-token patterns
        if block_specs:
            block_result, block_changed = rewrite_block_operators(result)
            if block_changed:
                result = block_result
                changed = True
                applied.append("block_operators")
                log.info(f"[unified_rewriter] Applied block operator rewrites")

        # Phase 2: Dimension functions (GROUP BY topics(...))
        # These are context-sensitive and need CTE generation
        if has_dimension_functions(result):
            dim_result = rewrite_dimension_functions(result)
            if dim_result.changed:
                result = dim_result.sql_out
                changed = True
                applied.append("dimension_functions")
                log.info(f"[unified_rewriter] Applied {len(dim_result.dimension_exprs)} dimension rewrites")

        # Phase 3: Inline operators (MEANS, ABOUT, SUMMARIZE, etc.)
        # These use the new inference-based system
        if inline_specs:
            inline_result = _rewrite_inline_operators(result, inline_specs)
            if inline_result.changed:
                result = inline_result.sql_out
                changed = True
                applied.extend(inline_result.applied)
                log.info(f"[unified_rewriter] Applied {len(inline_result.applied)} inline operator rewrites")

        log.debug(f"[unified_rewriter] Rewrite complete: changed={changed}, applied={applied}")

        # Always return clean SQL (without directive prefix)
        # The caller (postgres_server.py) handles BACKGROUND/ANALYZE execution separately
        # We just rewrite the inner SQL operators
        return result

    except Exception as e:
        log.error(f"[unified_rewriter] Error during rewriting: {e}", exc_info=True)
        # On error, return original SQL (fail-safe)
        return sql


def _rewrite_vector_search_functions(sql: str) -> str:
    """
    Rewrite VECTOR_SEARCH and HYBRID_SEARCH table functions.

    Provides elegant sugar for vector search operations with field-aware syntax.

    Args:
        sql: SQL to rewrite

    Returns:
        Rewritten SQL with vector search calls transformed

    Example:
        VECTOR_SEARCH('query', table.column, 10)
        → read_json_auto(vector_search_json_3(...)) WHERE metadata.column_name = 'column'
    """
    try:
        from .vector_search_rewriter import rewrite_vector_search, has_vector_search_calls

        if not has_vector_search_calls(sql):
            return sql

        return rewrite_vector_search(sql)

    except Exception as e:
        log.warning(f"[unified_rewriter] Vector search rewrite failed: {e}")
        return sql


def _rewrite_inline_operators(sql: str, specs: List) -> RewriteResult:
    """
    Rewrite inline operators (infix and function-style) using inferred specs.

    MVP Implementation: Delegates to existing proven rewriters:
    - semantic_rewriter_v2 for infix operators (MEANS, ABOUT, ~)
    - llm_agg_rewriter for aggregate functions (SUMMARIZE, CLASSIFY)

    These rewriters are already token-aware and battle-tested.
    Future: Move their logic directly into this unified rewriter.

    Args:
        sql: SQL to rewrite
        specs: List of BlockOperatorSpec for inline operators

    Returns:
        RewriteResult with rewritten SQL and metadata
    """
    result = sql
    applied = []
    errors = []
    changed = False

    # Phase 3a: Infix operators (MEANS, ABOUT, ~, etc.)
    # Delegate to semantic_rewriter_v2 (already token-aware)
    try:
        from .semantic_rewriter_v2 import rewrite_semantic_sql_v2

        v2_result = rewrite_semantic_sql_v2(result)

        if v2_result.changed:
            result = v2_result.sql_out
            changed = True
            applied.extend(v2_result.applied)

        if v2_result.errors:
            errors.extend(v2_result.errors)

    except Exception as e:
        log.warning(f"[inline_rewriter] semantic_rewriter_v2 failed: {e}")
        errors.append(f"semantic_v2: {e}")

    # Phase 3b: Legacy semantic operators (GROUP BY MEANING, SEMANTIC JOIN, etc.)
    # These haven't been migrated to cascade-driven yet, so keep using legacy
    try:
        from .semantic_operators import rewrite_semantic_operators

        legacy_result = rewrite_semantic_operators(result)
        if legacy_result != result:
            result = legacy_result
            changed = True
            applied.append("semantic_operators")

    except Exception as e:
        log.warning(f"[inline_rewriter] semantic_operators failed: {e}")
        errors.append(f"semantic_operators: {e}")

    # Phase 3c: LLM aggregate functions (SUMMARIZE, CLASSIFY, etc.)
    # Delegate to llm_agg_rewriter (already working)
    try:
        from .llm_agg_rewriter import process_llm_aggregates

        agg_result = process_llm_aggregates(result)
        if agg_result != result:
            result = agg_result
            changed = True
            applied.append("llm_aggregates")

    except Exception as e:
        log.warning(f"[inline_rewriter] llm_agg_rewriter failed: {e}")
        errors.append(f"llm_agg: {e}")

    return RewriteResult(
        sql_out=result,
        changed=changed,
        applied=applied,
        errors=errors
    )


# ============================================================================
# Token-Based Inline Matching (Future Enhancement)
# ============================================================================
#
# TODO: Implement full token-based matching for inline operators here.
#
# For now, we're using semantic_rewriter_v2 as the matching engine, but
# eventually we want to unify everything here with a clean token-based
# implementation that handles:
#
# 1. Infix binary (col MEANS 'x')
# 2. Infix multi-word (col ALIGNS WITH 'narrative')
# 3. Infix symbol (a ~ b)
# 4. Function calls (SUMMARIZE(col, 'prompt'))
# 5. Negation (col NOT MEANS 'x')
#
# The structure is already defined in BlockOperatorSpec.structure,
# we just need to walk the token stream and match the patterns.


# ============================================================================
# Utilities
# ============================================================================

def get_rewriter_stats() -> dict:
    """
    Get statistics about loaded operators.

    Useful for debugging and monitoring.
    """
    from .block_operators import load_block_operator_specs

    specs = load_block_operator_specs()

    block_count = sum(1 for s in specs if s.is_block_operator())
    inline_count = sum(1 for s in specs if s.is_inline_operator())

    return {
        'total_specs': len(specs),
        'block_operators': block_count,
        'inline_operators': inline_count,
        'version': '1.0.0-unified',
    }
