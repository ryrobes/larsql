"""
Semantic SQL Operators.

Transforms semantic SQL syntax into UDF calls backed by RVBBIT cascades.

Architecture:
    All semantic operators are "prompt sugar" - syntax that rewrites to cascade
    invocations. A cascade with `sql_function` metadata becomes a SQL-callable
    function. Built-in operators (MEANS, ABOUT, IMPLIES, etc.) are defined as
    cascade YAML files in cascades/semantic_sql/ (user-space, fully customizable).

    Three shapes:
    - SCALAR: Per-row functions (e.g., MEANS, IMPLIES, ABOUT)
    - ROW: Multi-column per-row (e.g., match_pair)
    - AGGREGATE: Collection functions (e.g., SUMMARIZE, MEANING, TOPICS)

    Resolution is inside-out like Lisp:
    - Aggregates resolve first (become CTEs)
    - Scalars resolve inline per row

Operator Syntax:

    col MEANS 'x'           → matches('x', col)
    col NOT MEANS 'x'       → NOT matches('x', col)
    col ABOUT 'x'           → score('x', col) > 0.5
    col ABOUT 'x' > 0.7     → score('x', col) > 0.7
    col NOT ABOUT 'x'       → score('x', col) <= 0.5
    col IMPLIES 'x'         → implies(col, 'x')
    col CONTRADICTS other   → contradicts(col, other)
    a ~ b                   → match_pair(a, b, 'same entity')
    ORDER BY col RELEVANCE TO 'x'      → ORDER BY score('x', col) DESC
    SEMANTIC DISTINCT col              → Dedupe by semantic similarity
    GROUP BY MEANING(col, n, 'hint')   → Cluster values semantically
    GROUP BY TOPICS(col, n)            → Extract and group by themes

Annotation hints (-- @) for model selection and prompt customization:

    -- @ use a fast and cheap model
    WHERE description MEANS 'sustainable'

    Becomes:
    WHERE matches('use a fast and cheap model - sustainable', description)

The annotation prompt is prepended to the criteria, allowing bodybuilder's
request mode to pick up model hints naturally.

Cascade Integration:
    When USE_CASCADE_FUNCTIONS is True, operators resolve through the cascade
    registry instead of direct UDF calls. This enables:
    - Full RVBBIT observability (logging, tracing, cost tracking)
    - User-defined overrides (put your own cascade in traits/)
    - Wards, retries, multi-modal - all RVBBIT features available
"""

import re
import logging
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ============================================================================
# Cascade Integration Configuration
# ============================================================================

# When True, rewriter uses cascade-based function names (e.g., cascade_matches)
# When False, uses direct UDF names (e.g., matches)
USE_CASCADE_FUNCTIONS = True

# Mapping from operator to function name (direct UDF vs cascade-backed)
OPERATOR_FUNCTIONS = {
    # Direct UDF names (current implementation)
    "direct": {
        "matches": "matches",
        "score": "score",
        "implies": "implies",
        "contradicts": "contradicts",
        "match_pair": "match_pair",
        "summarize": "summarize",
        "llm_themes_2": "llm_themes_2",
        "llm_cluster_2": "llm_cluster_2",
        "classify_single": "classify_single",
    },
    # Cascade-backed function names
    "cascade": {
        "matches": "cascade_matches",
        "score": "cascade_score",
        "implies": "cascade_implies",
        "contradicts": "cascade_contradicts",
        "match_pair": "cascade_match_pair",  # TODO: add cascade
        "summarize": "cascade_summarize",
        "llm_themes_2": "cascade_themes",
        "llm_cluster_2": "cascade_cluster",
        "classify_single": "cascade_classify",
    },
}


def get_function_name(operator: str) -> str:
    """Get the function name for an operator based on current configuration."""
    mode = "cascade" if USE_CASCADE_FUNCTIONS else "direct"
    return OPERATOR_FUNCTIONS[mode].get(operator, operator)


def set_use_cascade_functions(enabled: bool) -> None:
    """Enable or disable cascade-backed functions."""
    global USE_CASCADE_FUNCTIONS
    USE_CASCADE_FUNCTIONS = enabled
    log.info(f"[semantic_operators] Cascade functions {'enabled' if enabled else 'disabled'}")


# ============================================================================
# Annotation Parsing (shared with llm_agg_rewriter)
# ============================================================================

@dataclass
class SemanticAnnotation:
    """Parsed annotation for a semantic operator."""
    prompt: Optional[str] = None          # Custom prompt/instructions/model hints
    model: Optional[str] = None           # Explicit model override
    threshold: Optional[float] = None     # Score threshold for ABOUT
    parallel: Optional[int] = None        # Reserved for future parallelism (currently ignored)
    batch_size: Optional[int] = None      # Reserved for future parallelism (currently ignored)
    parallel_scope: str = "operator"      # "operator" (default) or "query" (all operators)
    start_pos: int = 0                    # Start position in query
    end_pos: int = 0                      # End position in query
    line_start: int = 0                   # Line number where annotation starts
    line_end: int = 0                     # Line number where annotation ends


def _parse_annotations(query: str) -> List[Tuple[int, int, SemanticAnnotation]]:
    """
    Parse all -- @ annotations from query.

    Returns list of (end_line, end_pos, annotation) tuples.

    Supports:
        -- @ Free-form prompt text (model hints like "use a fast model")
        -- @ More prompt text (consecutive lines merge)
        -- @ model: anthropic/claude-haiku
        -- @ threshold: 0.7
    """
    annotations = []
    lines = query.split('\n')

    current_annotation = None
    current_pos = 0
    prompt_lines = []

    for line_num, line in enumerate(lines):
        line_start = current_pos
        line_end = current_pos + len(line)

        stripped = line.strip()
        if stripped.startswith('-- @'):
            content = stripped[4:].strip()

            if current_annotation is None:
                current_annotation = SemanticAnnotation(
                    start_pos=line_start,
                    line_start=line_num
                )
                prompt_lines = []

            # Check for standalone keywords first (no colon)
            content_lower = content.lower()
            if content_lower in ('parallel', 'parallel execution'):
                # -- @ parallel (without value)
                import os
                current_annotation.parallel = os.cpu_count() or 8
            # Check for key: value pattern
            elif ':' in content and not content.startswith('http'):
                key, _, value = content.partition(':')
                key = key.strip().lower()
                value = value.strip()

                if key == 'model':
                    current_annotation.model = value
                elif key == 'threshold':
                    try:
                        current_annotation.threshold = float(value)
                    except ValueError:
                        pass
                elif key == 'parallel':
                    try:
                        # If value is empty or "true", use CPU count as default
                        if not value or value.lower() in ('true', 'yes'):
                            import os
                            current_annotation.parallel = os.cpu_count() or 8
                        else:
                            current_annotation.parallel = int(value)
                    except ValueError:
                        import os
                        current_annotation.parallel = os.cpu_count() or 8
                elif key == 'batch_size':
                    try:
                        current_annotation.batch_size = int(value)
                    except ValueError:
                        pass
                elif key == 'parallel_scope':
                    if value.lower() in ('query', 'operator'):
                        current_annotation.parallel_scope = value.lower()
                elif key == 'prompt':
                    prompt_lines.append(value)
                else:
                    # Unknown key or natural language with colon
                    prompt_lines.append(content)
            else:
                # No colon (or URL), it's prompt text
                prompt_lines.append(content)

            current_annotation.end_pos = line_end
            current_annotation.line_end = line_num

        else:
            # Not an annotation line
            if current_annotation is not None:
                if prompt_lines:
                    current_annotation.prompt = ' '.join(prompt_lines)
                annotations.append((line_num, current_annotation.end_pos, current_annotation))
                current_annotation = None
                prompt_lines = []

        current_pos = line_end + 1  # +1 for newline

    # Handle annotation at end of query
    if current_annotation is not None:
        if prompt_lines:
            current_annotation.prompt = ' '.join(prompt_lines)
        annotations.append((len(lines), current_annotation.end_pos, current_annotation))

    return annotations


def _find_annotation_for_line(
    annotations: List[Tuple[int, int, SemanticAnnotation]],
    target_line: int
) -> Optional[SemanticAnnotation]:
    """
    Find annotation that applies to a given line.

    An annotation applies if it ends on the line immediately before the target.
    """
    for end_line, end_pos, annotation in annotations:
        # Annotation applies if it ends right before target line
        if end_line == target_line:
            return annotation
    return None


# ============================================================================
# Semantic Operator Detection
# ============================================================================

def has_semantic_operators(query: str) -> bool:
    """
    Check if query contains any semantic SQL operators.

    Dynamically checks against operators loaded from cascade registry.
    Operators are discovered from cascades/semantic_sql/*.cascade.yaml
    and traits/semantic_sql/*.cascade.yaml on server startup.

    This means user-created cascades automatically work without code changes!
    """
    # Use dynamic pattern detection
    from .dynamic_operators import has_any_semantic_operator
    return has_any_semantic_operator(query)


# ============================================================================
# Rewriting Functions
# ============================================================================

def rewrite_semantic_operators(query: str) -> str:
    """
    Rewrite semantic SQL operators to UDF calls.

    Preserves annotations by injecting prompt text into the criteria string,
    allowing bodybuilder to pick up model hints.

    IMPORTANT: Only removes annotations that are actually used for semantic operators.
    Annotations before LLM aggregate functions (SUMMARIZE, THEMES, etc.) are preserved
    for the LLM aggregate rewriter to consume.

    Args:
        query: SQL query with semantic operators

    Returns:
        Rewritten SQL with UDF calls
    """
    if not has_semantic_operators(query):
        return query

    # Parse annotations first (we need line numbers)
    annotations = _parse_annotations(query)

    # Track which annotations were used (by line range)
    used_annotation_lines = set()

    # Split into lines for line-by-line processing
    lines = query.split('\n')
    result_lines = []

    for line_num, line in enumerate(lines):
        stripped = line.strip()

        # Check if this line is a pure annotation line
        if stripped.startswith('-- @'):
            # Check if the NEXT non-annotation line has a semantic operator
            # If so, we'll consume this annotation; otherwise preserve it
            next_code_line_num = _find_next_code_line(lines, line_num + 1)
            if next_code_line_num is not None:
                next_line = lines[next_code_line_num]
                if _has_semantic_operator_in_line(next_line):
                    # This annotation will be consumed by semantic operator rewrite
                    used_annotation_lines.add(line_num)
                    continue  # Skip this annotation line

            # Preserve annotation for other rewriters (LLM aggregates, etc.)
            result_lines.append(line)
            continue

        # Find annotation for this line (only if it has semantic operators)
        annotation = None
        if _has_semantic_operator_in_line(line):
            annotation = _find_annotation_for_line(annotations, line_num)

        # Apply rewrites to this line
        rewritten_line = _rewrite_line(line, annotation)
        result_lines.append(rewritten_line)

    result = '\n'.join(result_lines)

    # Post-processing: Fix double WHERE clauses that can occur with multi-line
    # SEMANTIC JOIN followed by WHERE on a separate line
    result = _fix_double_where(result)

    # Get annotation prefix for query-level rewrites
    # Use the first annotation if present
    annotation_prefix = ""
    if annotations:
        first_annotation = annotations[0][2]  # (line_num, end_pos, annotation)
        if first_annotation.prompt:
            annotation_prefix = first_annotation.prompt + " - "

    # Query-level rewrites (these transform the entire query structure)
    #
    # NOTE: EMBED(...) and VECTOR_SEARCH(...) sugar has been removed in favor of
    # explicit function calls:
    #   - semantic_embed(text)
    #   - semantic_embed_with_storage(text, model, source_table, column_name, source_id)
    #   - read_json_auto(vector_search_json_N(...))
    #
    # Structural helpers can be reintroduced later once we have robust SQL parsing.

    # SEMANTIC DISTINCT: SELECT SEMANTIC DISTINCT col FROM table
    result = _rewrite_semantic_distinct(result, annotation_prefix)

    # GROUP BY MEANING(col): Cluster values semantically
    result = _rewrite_group_by_meaning(result, annotation_prefix)

    # GROUP BY TOPICS(col, n): Group by extracted themes
    result = _rewrite_group_by_topics(result, annotation_prefix)

    return result


def _find_next_code_line(lines: list, start: int) -> Optional[int]:
    """Find the next non-annotation, non-empty line number."""
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith('-- @') and not stripped.startswith('--'):
            return i
    return None


def _has_semantic_operator_in_line(line: str) -> bool:
    """
    Check if a line contains any semantic operator.

    Dynamically checks against operators loaded from cascade registry.
    """
    # Ignore if line is a comment
    if line.strip().startswith('--'):
        return False

    from .dynamic_operators import has_semantic_operator_in_line as dynamic_check
    return dynamic_check(line)


def _fix_double_where(query: str) -> str:
    """
    Fix double WHERE clauses in a query (CTE-aware).

    When SEMANTIC JOIN is on one line and WHERE is on a subsequent line,
    we end up with two WHERE keywords in the SAME query scope.
    This function merges them with AND.

    IMPORTANT: This should only fix WHERE clauses in the same scope,
    not across different CTEs or subqueries!

    Example (needs fix):
        CROSS JOIN t WHERE match_pair(...)
        WHERE price > 100
    Becomes:
        CROSS JOIN t WHERE match_pair(...)
        AND price > 100

    Example (DON'T fix):
        WITH cte AS (SELECT * FROM t WHERE x = 1)
        SELECT * FROM cte WHERE y = 2
    Should stay unchanged (different scopes)!
    """
    # Skip fix if query has WITH clause (CTEs have their own scopes)
    if re.search(r'^\s*WITH\s+', query, re.IGNORECASE):
        return query

    # Skip fix if query has subqueries (different scopes)
    if query.count('SELECT') > 1:
        return query

    # Count WHERE occurrences in simple queries only
    where_count = len(re.findall(r'\bWHERE\b', query, re.IGNORECASE))

    if where_count <= 1:
        return query

    # Find all WHERE positions
    where_positions = [(m.start(), m.end()) for m in re.finditer(r'\bWHERE\b', query, re.IGNORECASE)]

    if len(where_positions) < 2:
        return query

    # Replace all but the first WHERE with AND
    # Work backwards to preserve positions
    result = query
    for start, end in reversed(where_positions[1:]):
        result = result[:start] + 'AND' + result[end:]

    return result


def _rewrite_dynamic_infix_operators(
    line: str,
    annotation_prefix: str
) -> str:
    """
    Generic rewriter for ALL infix operators using cascade registry.

    Handles operators like:
        col OPERATOR 'value' → sql_function_name(col, 'value')
        col OPERATOR other_col → sql_function_name(col, other_col)

    Automatically works with user-created cascades!

    This replaces per-operator hardcoded expression rewrites with a single
    registry-driven implementation.

    Args:
        line: SQL line to rewrite
        annotation_prefix: Annotation prefix to inject into criteria

    Returns:
        Rewritten line with UDF calls
    """
    from .dynamic_operators import get_operator_patterns_cached

    try:
        from rvbbit.semantic_sql.registry import get_sql_function_registry
    except ImportError:
        # Registry not available - return line unchanged
        return line

    result = line
    patterns_cache = get_operator_patterns_cached()
    registry = get_sql_function_registry()

    # Process each infix operator found by dynamic detection
    # Sort by length (descending) to handle multi-word operators first
    # e.g., "ALIGNS WITH" before "ALIGNS"
    infix_operators = sorted(patterns_cache.get('infix', set()), key=len, reverse=True)

    # Skip operators now handled by v2 (token-aware rewriter).
    # v2 runs first and handles these safely without matching inside string literals.
    v2_handled = {"ABOUT", "NOT ABOUT"}

    for operator_keyword in infix_operators:
        if operator_keyword.upper() in v2_handled:
            continue
        # Find SQL function for this operator
        matching_funcs = [
            (name, entry) for name, entry in registry.items()
            if any(operator_keyword.upper() in op.upper() for op in entry.operators)
        ]

        if not matching_funcs:
            continue

        func_name, entry = matching_funcs[0]
        returns_upper = str(getattr(entry, "returns", "") or "").upper()

        # Check if this is a word-based operator or symbol operator
        is_word_operator = operator_keyword.replace('_', '').replace(' ', '').isalnum()

        if is_word_operator:
            # Word-based operator (MEANS, ABOUT, ALIGNS, ASK, etc.)
            # Pattern: col OPERATOR 'value' or col OPERATOR other_col
            # Use word boundaries to avoid false matches
            # Also support optional infix NOT for boolean-returning operators:
            #   col NOT OPERATOR 'value'  -> NOT func(col, 'value')
            pattern = rf'(\w+(?:\.\w+)?)\s+(?:(NOT)\s+)?{re.escape(operator_keyword)}\s+(\'[^\']*\'|"[^"]*"|\w+(?:\.\w+)?)'
        else:
            # Symbol operator (~, !~, etc.)
            # Pattern: col OPERATOR 'value' or col OPERATOR other_col
            # Also support optional leading ! for boolean-returning operators:
            #   col !~ other  -> NOT func(col, other)   (if "~" is defined)
            pattern = rf'(\w+(?:\.\w+)?)\s*(?P<bang>!)?\s*{re.escape(operator_keyword)}\s*(\'[^\']*\'|"[^"]*"|\w+(?:\.\w+)?)'

        def replace_operator(match):
            col = match.group(1)
            not_kw = (match.group(2) if is_word_operator else None)
            bang = (match.group("bang") if not is_word_operator else None)
            value = match.group(3) if is_word_operator else match.group(2)

            is_negated = bool(not_kw) or bool(bang)
            if is_negated and returns_upper != "BOOLEAN":
                # Don't attempt to negate non-boolean operators.
                return match.group(0)

            # Inject annotation prefix if the value is a quoted string
            if annotation_prefix and value.startswith(("'", '"')):
                quote = value[0]
                inner = value[1:-1]
                value = f"{quote}{annotation_prefix}{inner}{quote}"

            # Generate function call with correct argument order
            # First arg is always the text column, second is the criterion/value
            expr = f"{func_name}({col}, {value})"
            return f"NOT {expr}" if is_negated else expr

        old_result = result
        result = re.sub(pattern, replace_operator, result, flags=re.IGNORECASE)

        if result != old_result:
            log.debug(f"[dynamic_rewrite] {operator_keyword}: {old_result.strip()[:60]}... → {result.strip()[:60]}...")

    return result


def _rewrite_line(line: str, annotation: Optional[SemanticAnnotation]) -> str:
    """Rewrite semantic operators in a single line."""
    result = line

    # Build annotation prefix for criteria injection
    annotation_prefix = ""
    if annotation and annotation.prompt:
        annotation_prefix = annotation.prompt + " - "
    elif annotation and annotation.model:
        annotation_prefix = f"Use {annotation.model} - "

    # Get threshold from annotation or use default
    default_threshold = 0.5
    if annotation and annotation.threshold is not None:
        default_threshold = annotation.threshold

    # ===== Context-sensitive rewrites (kept in legacy for now) =====
    # These handle patterns that need query/statement context or custom semantics:
    # - ABOUT with threshold comparisons (> 0.7, etc.) and NOT ABOUT inversion
    # - RELEVANCE TO in ORDER BY context (+ NOT variant)
    # - SEMANTIC JOIN (multi-keyword transformation)
    #
    # Expression-level operators (MEANS, NOT MEANS, ~, !~, IMPLIES, CONTRADICTS, ASK, ALIGNS, ...)
    # are handled by v2 (token-aware) and/or the dynamic infix rewriter below.

    # 1. Rewrite: SEMANTIC JOIN (complex multi-keyword transformation)
    result = _rewrite_semantic_join(result, annotation_prefix)

    # 2. Rewrite: ORDER BY col NOT RELEVANCE TO 'query'
    # Special: ORDER BY context + negation
    result = _rewrite_not_relevance_to(result, annotation_prefix)

    # 3. Rewrite: ORDER BY col RELEVANCE TO 'query'
    # Special: ORDER BY context
    result = _rewrite_relevance_to(result, annotation_prefix)

    # 4. Rewrite: col NOT ABOUT 'criteria' → score('criteria', col) <= threshold
    # Special: Negation + threshold inversion
    result = _rewrite_not_about(result, annotation_prefix, default_threshold)

    # 5. Rewrite: col ABOUT 'criteria' [> threshold]
    # Special: Threshold comparison operators
    result = _rewrite_about(result, annotation_prefix, default_threshold)

    # ===== PHASE 2: GENERIC DYNAMIC REWRITING (NEW!) =====
    # Run this AFTER the special-case rewrites above so we don’t break:
    # - ABOUT default thresholds
    # - ORDER BY ... RELEVANCE TO ...
    # - Other context-sensitive patterns
    #
    # This enables ASK, ALIGNS WITH, EXTRACTS, SOUNDS_LIKE and any user-created
    # infix operators to work without additional hardcoding.
    result = _rewrite_dynamic_infix_operators(result, annotation_prefix)

    return result


def _rewrite_about(line: str, annotation_prefix: str, default_threshold: float) -> str:
    """
    Rewrite ABOUT operator.

    col ABOUT 'topic'         →  score('topic', col) > 0.5
    col ABOUT 'topic' > 0.7   →  score('topic', col) > 0.7

    With annotation:
    -- @ threshold: 0.8
    col ABOUT 'topic'  →  score('topic', col) > 0.8
    """
    fn_name = get_function_name("score")

    # Pattern with explicit threshold: col ABOUT 'x' > 0.7
    pattern_with_threshold = r'(\w+(?:\.\w+)?)\s+ABOUT\s+\'([^\']+)\'\s*(>|>=|<|<=)\s*([\d.]+)'

    def replacer_with_threshold(match):
        col = match.group(1)
        criteria = match.group(2)
        operator = match.group(3)
        threshold = match.group(4)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') {operator} {threshold}"

    result = re.sub(pattern_with_threshold, replacer_with_threshold, line, flags=re.IGNORECASE)

    # Pattern without threshold: col ABOUT 'x' (uses default)
    pattern_simple = r'(\w+(?:\.\w+)?)\s+ABOUT\s+\'([^\']+)\'(?!\s*[><])'

    def replacer_simple(match):
        col = match.group(1)
        criteria = match.group(2)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') > {default_threshold}"

    result = re.sub(pattern_simple, replacer_simple, result, flags=re.IGNORECASE)

    return result


def _rewrite_not_about(line: str, annotation_prefix: str, default_threshold: float) -> str:
    """
    Rewrite NOT ABOUT operator (inverts threshold comparison).

    col NOT ABOUT 'topic'         →  score('topic', col) <= 0.5
    col NOT ABOUT 'topic' > 0.7   →  score('topic', col) <= 0.7

    The threshold from the query is used as the cutoff for exclusion.
    """
    fn_name = get_function_name("score")

    # Pattern with explicit threshold: col NOT ABOUT 'x' > 0.7
    # Note: The > threshold in NOT ABOUT means "exclude anything scoring above this"
    pattern_with_threshold = r'(\w+(?:\.\w+)?)\s+NOT\s+ABOUT\s+\'([^\']+)\'\s*(>|>=)\s*([\d.]+)'

    def replacer_with_threshold(match):
        col = match.group(1)
        criteria = match.group(2)
        # For NOT ABOUT with >, we invert: NOT ABOUT 'x' > 0.7 means score <= 0.7
        threshold = match.group(4)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') <= {threshold}"

    result = re.sub(pattern_with_threshold, replacer_with_threshold, line, flags=re.IGNORECASE)

    # Pattern with < threshold: col NOT ABOUT 'x' < 0.3
    # This means "exclude anything scoring below 0.3" → score >= 0.3
    pattern_with_lt = r'(\w+(?:\.\w+)?)\s+NOT\s+ABOUT\s+\'([^\']+)\'\s*(<|<=)\s*([\d.]+)'

    def replacer_with_lt(match):
        col = match.group(1)
        criteria = match.group(2)
        threshold = match.group(4)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') >= {threshold}"

    result = re.sub(pattern_with_lt, replacer_with_lt, result, flags=re.IGNORECASE)

    # Pattern without threshold: col NOT ABOUT 'x' (uses inverted default)
    pattern_simple = r'(\w+(?:\.\w+)?)\s+NOT\s+ABOUT\s+\'([^\']+)\'(?!\s*[><])'

    def replacer_simple(match):
        col = match.group(1)
        criteria = match.group(2)
        full_criteria = f"{annotation_prefix}{criteria}" if annotation_prefix else criteria
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"{fn_name}({col}, '{full_criteria}') <= {default_threshold}"

    result = re.sub(pattern_simple, replacer_simple, result, flags=re.IGNORECASE)

    return result


def _rewrite_relevance_to(line: str, annotation_prefix: str) -> str:
    """
    Rewrite RELEVANCE TO in ORDER BY.

    ORDER BY col RELEVANCE TO 'query'      →  ORDER BY score('query', col) DESC
    ORDER BY col RELEVANCE TO 'query' ASC  →  ORDER BY score('query', col) ASC

    With annotation:
    -- @ use a cheap model
    ORDER BY title RELEVANCE TO 'ML'  →  ORDER BY score('use a cheap model - ML', title) DESC
    """
    fn_name = get_function_name("score")

    # Pattern: ORDER BY col RELEVANCE TO 'query' [ASC|DESC]
    pattern = r'ORDER\s+BY\s+(\w+(?:\.\w+)?)\s+RELEVANCE\s+TO\s+\'([^\']+)\'(?:\s+(ASC|DESC))?'

    def replacer(match):
        col = match.group(1)
        query = match.group(2)
        direction = match.group(3) or 'DESC'  # Default to DESC (highest relevance first)
        full_query = f"{annotation_prefix}{query}" if annotation_prefix else query
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"ORDER BY {fn_name}({col}, '{full_query}') {direction}"

    return re.sub(pattern, replacer, line, flags=re.IGNORECASE)


def _rewrite_not_relevance_to(line: str, annotation_prefix: str) -> str:
    """
    Rewrite NOT RELEVANCE TO in ORDER BY (inverts to ASC).

    ORDER BY col NOT RELEVANCE TO 'query'      →  ORDER BY score('query', col) ASC
    ORDER BY col NOT RELEVANCE TO 'query' DESC →  ORDER BY score('query', col) DESC

    NOT RELEVANCE TO defaults to ASC (least relevant first), which is useful
    for filtering out irrelevant results or finding outliers.
    """
    fn_name = get_function_name("score")

    # Pattern: ORDER BY col NOT RELEVANCE TO 'query' [ASC|DESC]
    pattern = r'ORDER\s+BY\s+(\w+(?:\.\w+)?)\s+NOT\s+RELEVANCE\s+TO\s+\'([^\']+)\'(?:\s+(ASC|DESC))?'

    def replacer(match):
        col = match.group(1)
        query = match.group(2)
        direction = match.group(3) or 'ASC'  # Default to ASC (least relevant first for NOT)
        full_query = f"{annotation_prefix}{query}" if annotation_prefix else query
        # NEW: Use (text, criterion) order to match cascade YAMLs
        return f"ORDER BY {fn_name}({col}, '{full_query}') {direction}"

    return re.sub(pattern, replacer, line, flags=re.IGNORECASE)


def _rewrite_semantic_join(line: str, annotation_prefix: str) -> str:
    """
    Rewrite SEMANTIC JOIN.

    SEMANTIC JOIN t ON a.x ~ b.y  →  CROSS JOIN t WHERE match_pair(a.x, b.y, 'same entity')

    If the line already contains a WHERE clause after the SEMANTIC JOIN,
    we merge with AND instead of adding a new WHERE.

    Note: This is a line-level rewrite. Complex multi-line JOINs may need
    full SQL parsing for proper handling.
    """
    fn_name = get_function_name("match_pair")

    # Check if there's a WHERE clause elsewhere in the line (after potential SEMANTIC JOIN)
    # We'll use a placeholder and fix up afterward
    has_existing_where = bool(re.search(r'\bWHERE\b', line, re.IGNORECASE))

    # Pattern with alias: SEMANTIC JOIN table alias ON col1 ~ col2
    pattern_with_alias = r'SEMANTIC\s+JOIN\s+(\w+)\s+(\w+)\s+ON\s+(\w+(?:\.\w+)?)\s*~\s*(\w+(?:\.\w+)?)'

    def replacer_with_alias(match):
        table = match.group(1)
        alias = match.group(2)
        left = match.group(3)
        right = match.group(4)
        relationship = "same entity"
        full_relationship = f"{annotation_prefix}{relationship}" if annotation_prefix else relationship
        # Use placeholder that we'll fix up later
        return f"CROSS JOIN {table} {alias} {{{{SEMANTIC_WHERE}}}} {fn_name}({left}, {right}, '{full_relationship}')"

    # Pattern simple: SEMANTIC JOIN table ON col1 ~ col2
    pattern = r'SEMANTIC\s+JOIN\s+(\w+)\s+ON\s+(\w+(?:\.\w+)?)\s*~\s*(\w+(?:\.\w+)?)'

    def replacer(match):
        table = match.group(1)
        left = match.group(2)
        right = match.group(3)
        relationship = "same entity"
        full_relationship = f"{annotation_prefix}{relationship}" if annotation_prefix else relationship
        return f"CROSS JOIN {table} {{{{SEMANTIC_WHERE}}}} {fn_name}({left}, {right}, '{full_relationship}')"

    result = re.sub(pattern_with_alias, replacer_with_alias, line, flags=re.IGNORECASE)
    result = re.sub(pattern, replacer, result, flags=re.IGNORECASE)

    # Fix up the WHERE placeholder
    if '{{SEMANTIC_WHERE}}' in result:
        if has_existing_where:
            # There's an existing WHERE - our condition becomes part of it with AND
            # Replace the existing WHERE with our condition first, then AND WHERE
            result = result.replace('{{SEMANTIC_WHERE}}', 'WHERE')
            # Now find the other WHERE and change it to AND
            # This is tricky - we need to replace the SECOND WHERE with AND
            parts = result.split('WHERE', 2)  # Split into at most 3 parts
            if len(parts) == 3:
                # We have two WHEREs - merge them
                result = parts[0] + 'WHERE' + parts[1] + 'AND' + parts[2]
        else:
            # No existing WHERE - just use WHERE
            result = result.replace('{{SEMANTIC_WHERE}}', 'WHERE')

    return result


# ============================================================================
# Additional Semantic Operators (Future)
# ============================================================================

def _rewrite_semantic_distinct(query: str, annotation_prefix: str = "") -> str:
    """
    Rewrite SEMANTIC DISTINCT to use LLM deduplication.

    SELECT SEMANTIC DISTINCT company FROM suppliers
    →
    WITH _distinct_vals AS (
        SELECT to_json(LIST(company)) as _vals FROM (SELECT DISTINCT company FROM suppliers) _src
    ),
    _deduped AS (
        SELECT dedupe_2(_vals, 'same entity') as _json FROM _distinct_vals
    )
    SELECT unnest(from_json(_json, '["VARCHAR"]')) as value FROM _deduped

    With criteria:
    SELECT SEMANTIC DISTINCT company AS 'same business' FROM suppliers
    →
    Uses dedupe(..., 'same business')

    Also supports subqueries:
    SELECT SEMANTIC DISTINCT county FROM (SELECT * FROM bigfoot LIMIT 100)

    Key: Uses to_json(LIST()) to produce proper JSON format ["a","b"] instead of
    DuckDB's list format [a, b] which isn't valid JSON.
    """
    # Pattern: SELECT SEMANTIC DISTINCT col [AS 'criteria'] FROM (table_or_subquery)
    # Match either a simple table name OR a parenthesized subquery
    pattern = r"SELECT\s+SEMANTIC\s+DISTINCT\s+(\w+(?:\.\w+)?)\s*(?:AS\s+'([^']+)')?\s+FROM\s+(\([^)]+\)|\w+)"

    def replacer(match):
        col = match.group(1)
        criteria = match.group(2) or "same entity"
        source = match.group(3)  # Could be table name or (subquery)

        if annotation_prefix:
            criteria = f"{annotation_prefix}{criteria}"

        # Use CTE to properly aggregate, call dedupe, then unnest JSON array
        # Key insight: LIST()::VARCHAR produces DuckDB list format [a, b, c]
        # but dedupe_2 expects JSON format ["a", "b", "c"]
        # Use to_json(LIST()) to get proper JSON array
        return f"""WITH _distinct_vals AS (
    SELECT to_json(LIST({col})) as _vals FROM (SELECT DISTINCT {col} FROM {source}) _src
),
_deduped AS (
    SELECT dedupe_2(_vals, '{criteria}') as _json FROM _distinct_vals
)
SELECT unnest(from_json(_json, '["VARCHAR"]')) as value FROM _deduped"""

    return re.sub(pattern, replacer, query, flags=re.IGNORECASE)


def _rewrite_group_by_meaning(query: str, annotation_prefix: str = "") -> str:
    """
    Rewrite GROUP BY MEANING(col) to use semantic clustering.

    SELECT category, COUNT(*) FROM products GROUP BY MEANING(category)
    →
    SELECT _semantic_cluster as category, COUNT(*)
    FROM (
        SELECT *, meaning(category, (SELECT LIST(category)::VARCHAR FROM products)) as _semantic_cluster
        FROM products
    ) _clustered
    GROUP BY _semantic_cluster

    With number of clusters:
    GROUP BY MEANING(category, 5)

    With criteria:
    GROUP BY MEANING(category, 5, 'product type')
    """
    # Pattern: GROUP BY MEANING(col) or MEANING(col, n) or MEANING(col, n, 'criteria')
    pattern = r"GROUP\s+BY\s+MEANING\s*\(\s*(\w+(?:\.\w+)?)\s*(?:,\s*(\d+))?\s*(?:,\s*'([^']+)')?\s*\)"

    match = re.search(pattern, query, flags=re.IGNORECASE)
    if not match:
        return query

    col = match.group(1)
    num_clusters = match.group(2)
    criteria = match.group(3)

    if annotation_prefix and criteria:
        criteria = f"{annotation_prefix}{criteria}"
    elif annotation_prefix:
        criteria = annotation_prefix.rstrip(" -")

    # Find the FROM clause - could be table name or subquery
    # Match FROM followed by either (subquery) or table_name
    from_match = re.search(r"FROM\s+(\([^)]+\)|(\w+))", query, flags=re.IGNORECASE)
    if not from_match:
        return query

    source = from_match.group(1)  # Could be (subquery) or table_name
    is_subquery = source.startswith('(')

    # Build the meaning function call
    # Use to_json(LIST()) to get proper JSON format instead of DuckDB list format
    if num_clusters and criteria:
        meaning_call = f"meaning_4({col}, (SELECT to_json(LIST({col})) FROM {source}), {num_clusters}, '{criteria}')"
    elif num_clusters:
        meaning_call = f"meaning_3({col}, (SELECT to_json(LIST({col})) FROM {source}), {num_clusters})"
    elif criteria:
        meaning_call = f"meaning_4({col}, (SELECT to_json(LIST({col})) FROM {source}), NULL, '{criteria}')"
    else:
        meaning_call = f"meaning({col}, (SELECT to_json(LIST({col})) FROM {source}))"

    # Find SELECT columns and replace MEANING(...) expressions with _semantic_cluster
    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", query, flags=re.IGNORECASE | re.DOTALL)
    if not select_match:
        return query

    select_cols = select_match.group(1)

    # Replace MEANING(col, ...) expressions with _semantic_cluster
    # Must handle: MEANING(col), MEANING(col, n), MEANING(col, n, 'criteria')
    # And preserve any AS alias: MEANING(col, n, 'criteria') as encounter_type
    meaning_in_select = rf"MEANING\s*\(\s*{re.escape(col)}\s*(?:,\s*\d+)?\s*(?:,\s*'[^']*')?\s*\)"
    new_select_cols = re.sub(meaning_in_select, '_semantic_cluster', select_cols, flags=re.IGNORECASE)

    # Also replace bare column references (not inside function calls)
    # Use negative lookbehind for '(' and negative lookahead for '(' to avoid function args
    # This handles: SELECT col, COUNT(*) → SELECT _semantic_cluster AS col, COUNT(*)
    bare_col_pattern = rf'(?<!\()\b{re.escape(col)}\b(?!\s*\()'
    # Only replace if it's a standalone column (not already replaced by MEANING rewrite)
    if f'_semantic_cluster' not in new_select_cols or re.search(bare_col_pattern, new_select_cols):
        # Check if there are any bare column references left (not inside function calls)
        # Simple heuristic: if the column appears before a comma or 'as' (case insensitive)
        # but NOT after an open paren, it's a bare reference
        new_select_cols = re.sub(
            rf'(?<![(\w]){re.escape(col)}(?=\s*(?:,|$|\bas\b))',
            f'_semantic_cluster AS {col}',
            new_select_cols,
            flags=re.IGNORECASE
        )

    # Build CTE-based rewrite (cleaner than nested subqueries)
    # 1. Create clustered source with semantic cluster column
    # 2. Select from clustered, group by cluster
    new_query = f"""WITH _clustered AS (
    SELECT *, {meaning_call} as _semantic_cluster
    FROM {source}
)
SELECT {new_select_cols}
FROM _clustered
GROUP BY _semantic_cluster"""

    # Preserve ORDER BY if present (only at the end of query, not in subquery)
    # Look for ORDER BY after the GROUP BY clause
    after_groupby = re.search(r"GROUP\s+BY\s+MEANING\s*\([^)]+\)\s*(ORDER\s+BY\s+.+?)(?:;|$)", query, flags=re.IGNORECASE | re.DOTALL)
    if after_groupby:
        order_clause = after_groupby.group(1).strip()
        new_query = f"{new_query}\n{order_clause}"

    return new_query


def _rewrite_group_by_topics(query: str, annotation_prefix: str = "") -> str:
    """
    Rewrite GROUP BY TOPICS(col, n) to extract topics and classify rows.

    SELECT title, COUNT(*) FROM articles GROUP BY TOPICS(content, 3)
    →
    WITH _topics_json AS (
        SELECT llm_themes_2(to_json(LIST(content)), 3) as _topics
        FROM articles
    ),
    _classified AS (
        SELECT *, classify_single(content, (SELECT _topics FROM _topics_json)) as _topic
        FROM articles
    )
    SELECT _topic, COUNT(*)
    FROM _classified
    GROUP BY _topic

    The approach:
    1. Extract N topics from ALL text values using llm_themes aggregate
    2. For each row, classify it into ONE of those topics
    3. Group by the assigned topic

    Also supports subqueries:
    SELECT col, COUNT(*) FROM (SELECT * FROM t LIMIT 100) GROUP BY TOPICS(col, 3)
    """
    # Pattern: GROUP BY TOPICS(col, n) or TOPICS(col)
    pattern = r"GROUP\s+BY\s+TOPICS\s*\(\s*(\w+(?:\.\w+)?)\s*(?:,\s*(\d+))?\s*\)"

    match = re.search(pattern, query, flags=re.IGNORECASE)
    if not match:
        return query

    col = match.group(1)
    num_topics = match.group(2) or "5"

    # Find the FROM clause - could be table name or subquery
    # Match FROM followed by either (subquery) or table_name
    from_match = re.search(r"FROM\s+(\([^)]+\)|(\w+))", query, flags=re.IGNORECASE)
    if not from_match:
        return query

    source = from_match.group(1)  # Could be (subquery) or table_name

    # Find SELECT columns and replace the grouped column with _topic AS original_name
    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", query, flags=re.IGNORECASE | re.DOTALL)
    if not select_match:
        return query

    select_cols = select_match.group(1)
    # Replace column reference with topic, aliased back to original column name
    new_select_cols = re.sub(rf'\b{col}\b', f'_topic AS {col}', select_cols)

    # Build CTE-based rewrite
    # 1. Extract topics from all values using llm_themes_2 aggregate
    # 2. Classify each row into one of those topics
    # 3. Group by the assigned topic
    new_query = f"""WITH _topics_json AS (
    SELECT llm_themes_2(to_json(LIST({col})), {num_topics}) as _topics
    FROM {source}
),
_classified AS (
    SELECT *, classify_single({col}, (SELECT _topics FROM _topics_json)) as _topic
    FROM {source}
)
SELECT {new_select_cols}
FROM _classified
GROUP BY _topic"""

    return new_query


# ============================================================================
# Info
# ============================================================================

def get_semantic_operators_info() -> Dict[str, Any]:
    """Get information about supported semantic operators."""
    return {
        'version': '0.4.0',
        'supported_operators': {
            'MEANS': {
                'syntax': "col MEANS 'criteria'",
                'rewrites_to': "matches('criteria', col)",
                'description': 'Semantic boolean match'
            },
            'NOT MEANS': {
                'syntax': "col NOT MEANS 'criteria'",
                'rewrites_to': "NOT matches('criteria', col)",
                'description': 'Negated semantic boolean match'
            },
            'ABOUT': {
                'syntax': "col ABOUT 'criteria' [> threshold]",
                'rewrites_to': "score('criteria', col) > threshold",
                'description': 'Semantic score with threshold'
            },
            'NOT ABOUT': {
                'syntax': "col NOT ABOUT 'criteria' [> threshold]",
                'rewrites_to': "score('criteria', col) <= threshold",
                'description': 'Negated semantic score (excludes matches above threshold)'
            },
            '~': {
                'syntax': "a ~ b [AS 'relationship']",
                'rewrites_to': "match_pair(a, b, 'relationship')",
                'description': 'Semantic equality for JOINs'
            },
            '!~': {
                'syntax': "a !~ b [AS 'relationship']",
                'rewrites_to': "NOT match_pair(a, b, 'relationship')",
                'description': 'Negated semantic equality'
            },
            'RELEVANCE TO': {
                'syntax': "ORDER BY col RELEVANCE TO 'query'",
                'rewrites_to': "ORDER BY score('query', col) DESC",
                'description': 'Semantic ordering (most relevant first)'
            },
            'NOT RELEVANCE TO': {
                'syntax': "ORDER BY col NOT RELEVANCE TO 'query'",
                'rewrites_to': "ORDER BY score('query', col) ASC",
                'description': 'Inverted semantic ordering (least relevant first)'
            },
            'SEMANTIC JOIN': {
                'syntax': "SEMANTIC JOIN t ON a ~ b",
                'rewrites_to': "CROSS JOIN t WHERE match_pair(a, b, ...)",
                'description': 'Fuzzy JOIN'
            },
            'SEMANTIC DISTINCT': {
                'syntax': "SELECT SEMANTIC DISTINCT col [AS 'criteria'] FROM table",
                'rewrites_to': "SELECT unnest(dedupe(LIST(col), 'criteria'))",
                'description': 'Deduplicate by semantic similarity'
            },
            'GROUP BY MEANING': {
                'syntax': "GROUP BY MEANING(col[, n][, 'criteria'])",
                'rewrites_to': "GROUP BY meaning(col, all_values[, n][, 'criteria'])",
                'description': 'Group by semantic clusters'
            },
            'GROUP BY TOPICS': {
                'syntax': "GROUP BY TOPICS(col[, n])",
                'rewrites_to': "GROUP BY unnest(themes(col, n))",
                'description': 'Group by extracted themes/topics'
            },
            'IMPLIES': {
                'syntax': "a IMPLIES b / a IMPLIES 'conclusion'",
                'rewrites_to': "implies(a, b)",
                'description': 'Check if statement a implies statement b'
            },
            'CONTRADICTS': {
                'syntax': "a CONTRADICTS b / a CONTRADICTS 'statement'",
                'rewrites_to': "contradicts(a, b)",
                'description': 'Check if statements contradict each other'
            }
        },
        'annotation_support': {
            'prompt': "-- @ Free text prompt/model hints",
            'model': "-- @ model: provider/model-name",
            'threshold': "-- @ threshold: 0.7"
        }
    }


# ============================================================================
# Examples
# ============================================================================

EXAMPLES = """
# Semantic SQL Operators - Examples

## MEANS Operator (Semantic Boolean Filter)

```sql
-- Basic usage
SELECT * FROM products
WHERE description MEANS 'sustainable'

-- With annotation for model selection
-- @ use a fast and cheap model
WHERE description MEANS 'eco-friendly'

-- Equivalent to:
WHERE matches('use a fast and cheap model - eco-friendly', description)
```

## ABOUT Operator (Semantic Score Threshold)

```sql
-- Basic usage (default threshold 0.5)
SELECT * FROM articles
WHERE content ABOUT 'machine learning'

-- With explicit threshold
WHERE content ABOUT 'data science' > 0.7

-- With annotation
-- @ threshold: 0.8
-- @ use a fast model
WHERE content ABOUT 'AI research'
```

## Tilde (~) Operator (Semantic Equality)

```sql
-- Basic semantic equality
SELECT * FROM customers c, suppliers s
WHERE c.company ~ s.vendor

-- With explicit relationship
WHERE c.company_name ~ s.vendor_name AS 'same business entity'

-- In JOIN context
FROM customers c
SEMANTIC JOIN suppliers s ON c.company ~ s.vendor
```

## RELEVANCE TO (Semantic Ordering)

```sql
-- Order by semantic relevance
SELECT * FROM documents
ORDER BY content RELEVANCE TO 'quarterly earnings'

-- Ascending (least relevant first)
ORDER BY content RELEVANCE TO 'financial reports' ASC
```

## Negation Operators

```sql
-- NOT MEANS: Exclude semantic matches
SELECT * FROM products
WHERE description NOT MEANS 'contains plastic'

-- NOT ABOUT: Exclude content scoring above threshold
SELECT * FROM articles
WHERE content NOT ABOUT 'politics' > 0.3

-- !~: Negated semantic equality (not the same entity)
SELECT * FROM transactions t1, transactions t2
WHERE t1.merchant !~ t2.merchant
  AND t1.amount = t2.amount

-- NOT RELEVANCE TO: Order by least relevant first (find outliers)
SELECT * FROM support_tickets
ORDER BY description NOT RELEVANCE TO 'common issues'
LIMIT 10
```

## Combining Operators

```sql
SELECT
  p.name,
  p.description
FROM products p
SEMANTIC JOIN categories c ON p.category_text ~ c.name
WHERE p.description MEANS 'sustainable'
  AND p.title ABOUT 'organic' > 0.6
ORDER BY p.description RELEVANCE TO 'eco-friendly lifestyle'
LIMIT 100
```

## With Annotations

```sql
SELECT
  county,
  count(1) as incidents,
  -- @ use a fast and cheap model
  themes(title, 3) as top_themes,
  -- @ use a fast and cheap model
  avg(score('credibility of sighting', title)) as avg_cred
FROM bigfoot
-- @ use a fast and cheap model
WHERE title MEANS 'happened during the day'
  -- @ threshold: 0.3
  AND title ABOUT 'credible sighting'
GROUP BY county
```
"""
