"""
Dynamic Operator Pattern System for Semantic SQL.

Automatically extracts operator patterns from cascade registry instead of
hardcoding them in semantic_operators.py.

This enables:
- User-created cascades automatically work (no code changes)
- Editing cascades updates operators instantly
- True "cascades all the way down" philosophy

Architecture:
    1. Server startup: initialize_dynamic_patterns()
    2. Extract patterns from all cascades in registry
    3. Cache patterns in module-level variable
    4. semantic_operators.py uses cached patterns

Example Cascade:
    sql_function:
      operators:
        - "{{ text }} MEANS {{ criterion }}"  → Detects "MEANS" (infix)
        - "EMBED({{ text }})"                 → Detects "EMBED" (function)
        - "VECTOR_SEARCH('{{ q }}', '{{ t }}')" → Detects "VECTOR_SEARCH" (function)
"""

import re
import logging
from typing import List, Dict, Set, Tuple, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# Global Pattern Cache
# ============================================================================

_operator_patterns_cache: Optional[Dict[str, Set[str]]] = None
_function_name_cache: Optional[Set[str]] = None


def initialize_dynamic_patterns(force: bool = False) -> Dict[str, Set[str]]:
    """
    Initialize dynamic operator patterns from cascade registry.

    Extracts all operator keywords from cascades and caches them.
    Should be called once at server startup.

    Args:
        force: Force reinitialization even if already cached

    Returns:
        Dict with keys:
        - "infix": Set of infix operators (e.g., {"MEANS", "ABOUT", "SIMILAR_TO"})
        - "function": Set of function names (e.g., {"EMBED", "VECTOR_SEARCH"})
        - "all_keywords": Set of all keywords for quick detection

    Example:
        >>> patterns = initialize_dynamic_patterns()
        >>> "EMBED" in patterns["function"]
        True
        >>> "MEANS" in patterns["infix"]
        True
    """
    global _operator_patterns_cache, _function_name_cache

    if _operator_patterns_cache is not None and not force:
        return _operator_patterns_cache

    logger.info("Initializing dynamic operator patterns from cascade registry...")

    try:
        from rvbbit.semantic_sql.registry import initialize_registry, get_sql_function_registry
    except ImportError:
        logger.warning("semantic_sql.registry not available - using empty patterns")
        _operator_patterns_cache = {"infix": set(), "function": set(), "all_keywords": set()}
        return _operator_patterns_cache

    # Initialize registry to load all cascades
    initialize_registry(force=force)
    registry = get_sql_function_registry()

    infix_operators = set()
    function_names = set()

    for func_name, entry in registry.items():
        for operator_pattern in entry.operators:
            # Extract operator keywords from pattern

            # Pattern 1: Infix operators (e.g., "{{ text }} MEANS {{ criterion }}")
            # Look for WORD between }} and {{
            infix_match = re.search(r'\}\}\s+(\w+)\s+', operator_pattern)
            if infix_match:
                keyword = infix_match.group(1).upper()
                infix_operators.add(keyword)
                logger.debug(f"Found infix operator: {keyword} from {func_name}")
                continue

            # Pattern 1b: Symbol operators (e.g., "{{ text }} ~ {{ criterion }}")
            # Look for single-char symbol between }} and {{
            symbol_match = re.search(r'\}\}\s+([~!<>=]+)\s+', operator_pattern)
            if symbol_match:
                keyword = symbol_match.group(1)
                infix_operators.add(keyword)
                logger.debug(f"Found symbol operator: {keyword} from {func_name}")
                continue

            # Pattern 2: Function calls (e.g., "EMBED({{ text }})")
            # Look for WORD followed by (
            func_match = re.match(r'^(\w+)\s*\(', operator_pattern)
            if func_match:
                keyword = func_match.group(1).upper()
                function_names.add(keyword)
                logger.debug(f"Found function operator: {keyword} from {func_name}")
                continue

            # Pattern 3: Just the function name in registry
            # Fall back to extracting from pattern if no clear match
            # Example: "VECTOR_SEARCH('{{ query }}', '{{ table }}')"
            words = re.findall(r'\b([A-Z_]{2,})\b', operator_pattern)
            if words:
                for word in words:
                    if word not in ['VARCHAR', 'INTEGER', 'DOUBLE', 'TABLE', 'JSON', 'SELECT', 'FROM', 'WHERE']:
                        function_names.add(word)
                        logger.debug(f"Found operator keyword: {word} from {func_name}")

    # Build combined keyword set for quick checks
    all_keywords = infix_operators | function_names

    _operator_patterns_cache = {
        "infix": infix_operators,
        "function": function_names,
        "all_keywords": all_keywords
    }

    _function_name_cache = function_names

    logger.info(f"Loaded {len(infix_operators)} infix operators: {sorted(infix_operators)}")
    logger.info(f"Loaded {len(function_names)} function operators: {sorted(function_names)}")

    return _operator_patterns_cache


def get_operator_patterns_cached() -> Dict[str, Set[str]]:
    """
    Get cached operator patterns.

    If not initialized, initializes automatically.

    Returns:
        Dict with "infix", "function", and "all_keywords" sets
    """
    if _operator_patterns_cache is None:
        return initialize_dynamic_patterns()
    return _operator_patterns_cache


def has_any_semantic_operator(query: str) -> bool:
    """
    Check if query contains any registered semantic operator.

    Dynamically checks against all operators loaded from cascade registry.

    Args:
        query: SQL query to check

    Returns:
        True if query contains any registered semantic operator

    Example:
        >>> has_any_semantic_operator("SELECT * FROM t WHERE x MEANS 'y'")
        True
        >>> has_any_semantic_operator("SELECT EMBED(text) FROM docs")
        True
        >>> has_any_semantic_operator("SELECT * FROM products")
        False
    """
    patterns = get_operator_patterns_cached()

    # Quick check: scan for any known keywords
    query_upper = query.upper()

    for keyword in patterns["all_keywords"]:
        # Check if this is a word-based operator or symbol operator
        is_word_operator = keyword.isalnum()

        if is_word_operator:
            # Use word boundary regex to avoid false positives
            if re.search(rf'\b{keyword}\b', query_upper):
                return True
        else:
            # Symbol operators like ~, !~, etc. - check for presence
            if keyword in query:
                return True

    return False


def has_semantic_operator_in_line(line: str) -> bool:
    """
    Check if a line contains any registered semantic operator.

    Dynamically checks against all operators loaded from cascade registry.

    Args:
        line: Single line of SQL

    Returns:
        True if line contains any registered semantic operator
    """
    patterns = get_operator_patterns_cached()

    line_upper = line.upper()

    # Check for infix operators (with context)
    for keyword in patterns["infix"]:
        # Check if this is a word-based operator (MEANS, ABOUT) or symbol (~, !~)
        is_word_operator = keyword.isalnum()

        if is_word_operator:
            # Infix operators typically have format: col KEYWORD 'value'
            if re.search(rf'\b{keyword}\s+[\'"]', line_upper):
                return True
            # Also check: col KEYWORD other_col
            if re.search(rf'\b{keyword}\s+\w+', line_upper):
                return True
        else:
            # Symbol operators like ~, !~, etc.
            # Just check if the symbol exists in the line (more lenient)
            if keyword in line:
                return True

    # Check for function operators
    for keyword in patterns["function"]:
        # Function operators have format: KEYWORD(args)
        if re.search(rf'\b{keyword}\s*\(', line_upper):
            return True

    return False


def get_dynamic_rewrite_info() -> str:
    """
    Get summary of dynamically loaded operators.

    Useful for debugging and documentation.

    Returns:
        Human-readable summary string
    """
    patterns = get_operator_patterns_cached()

    infix_list = sorted(patterns["infix"])
    function_list = sorted(patterns["function"])

    return f"""
Dynamic Semantic SQL Operators (loaded from cascades):

Infix Operators ({len(infix_list)}):
{chr(10).join(f'  - {op}' for op in infix_list)}

Function Operators ({len(function_list)}):
{chr(10).join(f'  - {op}' for op in function_list)}

Total: {len(patterns['all_keywords'])} unique operators
Source: cascades/semantic_sql/*.cascade.yaml + traits/semantic_sql/*.cascade.yaml
"""


# ============================================================================
# Refresh API
# ============================================================================

def refresh_operator_patterns() -> Dict[str, Set[str]]:
    """
    Force refresh of operator patterns from cascade registry.

    Useful when cascades are added/modified at runtime.

    Returns:
        Updated pattern dict
    """
    logger.info("Refreshing operator patterns from cascade registry...")
    return initialize_dynamic_patterns(force=True)


# ============================================================================
# Generic Operator Rewriting
# ============================================================================

def rewrite_infix_operators(line: str) -> str:
    """
    Generic rewriter for infix operators using cascade registry.

    Handles operators like:
        col OPERATOR 'value' → sql_function_name('value', col)

    Automatically works with user-created cascades!

    Args:
        line: SQL line to rewrite

    Returns:
        Rewritten line with UDF calls
    """
    from rvbbit.semantic_sql.registry import get_sql_function_registry

    patterns_cache = get_operator_patterns_cached()
    result = line

    # Get function mappings from registry
    registry = get_sql_function_registry()

    for operator_keyword in patterns_cache['infix']:
        # Find SQL function for this operator
        matching_funcs = [
            (name, entry) for name, entry in registry.items()
            if any(operator_keyword in op.upper() for op in entry.operators)
        ]

        if not matching_funcs:
            continue

        func_name, entry = matching_funcs[0]

        # Pattern: col OPERATOR 'value' or col OPERATOR other_col
        # Rewrite to: sql_function(col, 'value')
        pattern = rf'(\w+(?:\.\w+)?)\s+{operator_keyword}\s+(\'[^\']*\'|"[^"]*"|\w+(?:\.\w+)?)'

        def replace_operator(match):
            col = match.group(1)
            value = match.group(2)
            return f"{func_name}({col}, {value})"

        old_result = result
        result = re.sub(pattern, replace_operator, result, flags=re.IGNORECASE)

        if result != old_result:
            logger.debug(f"Rewrote {operator_keyword}: {old_result.strip()[:60]}... → {result.strip()[:60]}...")

    return result
