"""
Dimension Function Rewriter for Semantic SQL.

Transforms dimension functions in GROUP BY/SELECT into CTE-based execution.

A dimension function is like DATE_TRUNC but for semantic bucketing:
- It needs to see ALL values to determine what buckets exist
- Then it assigns each row to a bucket
- The result is a scalar per row (the bucket label)

Example:
    SELECT state, sentiment(observed, 'fear') as mood, COUNT(*)
    FROM bigfoot_vw
    GROUP BY state, sentiment(observed, 'fear')

Becomes:
    WITH
    _dim_sentiment_observed_abc123_mapping AS (
        SELECT sentiment_compute(to_json(LIST(observed)), 'fear') as _mapping
        FROM bigfoot_vw
    ),
    _dim_classified AS (
        SELECT *,
            COALESCE(
                (SELECT value::VARCHAR FROM json_each(_mapping->'mapping')
                 WHERE key = observed LIMIT 1),
                'Unknown'
            ) as __dim_sentiment_observed_abc123
        FROM bigfoot_vw, _dim_sentiment_observed_abc123_mapping
    )
    SELECT state, __dim_sentiment_observed_abc123 as mood, COUNT(*)
    FROM _dim_classified
    GROUP BY state, __dim_sentiment_observed_abc123

Cascade authors define dimension functions with:
    sql_function:
      name: sentiment
      shape: DIMENSION
      mode: mapping  # or "extractor_classifier"
      args:
        - name: text
          type: VARCHAR
          role: dimension_source  # The column to bucket
        - name: focus
          type: VARCHAR
          default: null
"""

import re
import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any

log = logging.getLogger(__name__)


@dataclass
class DimensionExpr:
    """A parsed dimension function expression."""
    func_name: str              # "sentiment"
    source_col: str             # "observed" (the column to bucket)
    scalar_args: List[str]      # ["'fear'", "3"] (modifiers for cascade)
    alias: Optional[str]        # "mood" if "sentiment(...) as mood"
    full_match: str             # The full matched text
    id: str                     # "__dim_sentiment_observed_abc123"
    entry: Any                  # SQLFunctionEntry from registry


@dataclass
class DimensionRewriteResult:
    """Result of dimension rewriting."""
    sql_out: str
    changed: bool
    dimension_exprs: List[DimensionExpr] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def rewrite_dimension_functions(query: str) -> DimensionRewriteResult:
    """
    Main entry point: detect and rewrite dimension functions.

    Args:
        query: SQL query that may contain dimension functions

    Returns:
        DimensionRewriteResult with rewritten SQL
    """
    try:
        # Get dimension-shaped functions from registry
        dimension_funcs = _get_dimension_functions()

        if not dimension_funcs:
            return DimensionRewriteResult(sql_out=query, changed=False)

        # Find all dimension expressions in the query
        exprs = _find_dimension_expressions(query, dimension_funcs)

        if not exprs:
            return DimensionRewriteResult(sql_out=query, changed=False)

        log.info(f"[dimension_rewriter] Found {len(exprs)} dimension expressions")

        # Extract source table/subquery and WHERE clause
        source = _extract_source(query)
        where_clause = _extract_where_clause(query)

        if not source:
            return DimensionRewriteResult(
                sql_out=query,
                changed=False,
                errors=["Could not extract source table/subquery"]
            )

        # Generate CTEs for bucket computation
        ctes = _generate_dimension_ctes(exprs, source, where_clause)

        # Rewrite the main query to use bucket columns
        rewritten = _rewrite_main_query(query, exprs, source)

        # Assemble final query
        final_sql = f"WITH\n{ctes}\n{rewritten}"

        return DimensionRewriteResult(
            sql_out=final_sql,
            changed=True,
            dimension_exprs=exprs
        )

    except Exception as e:
        log.warning(f"[dimension_rewriter] Error: {e}")
        return DimensionRewriteResult(
            sql_out=query,
            changed=False,
            errors=[str(e)]
        )


def _get_dimension_functions() -> Dict[str, Any]:
    """Get all DIMENSION-shaped functions from the registry."""
    try:
        from rvbbit.semantic_sql.registry import get_sql_function_registry

        registry = get_sql_function_registry()

        return {
            name: entry for name, entry in registry.items()
            if _get_shape(entry).upper() == 'DIMENSION'
        }
    except ImportError:
        log.warning("[dimension_rewriter] Could not import registry")
        return {}


def _get_shape(entry) -> str:
    """Get the shape from a registry entry."""
    if hasattr(entry, 'shape'):
        return entry.shape
    if hasattr(entry, 'sql_function'):
        return entry.sql_function.get('shape', 'SCALAR')
    return 'SCALAR'


def _get_dimension_config(entry) -> Dict[str, Any]:
    """Get dimension-specific config from registry entry."""
    if hasattr(entry, 'sql_function'):
        return entry.sql_function
    return {}


def _find_dimension_expressions(
    query: str,
    dimension_funcs: Dict[str, Any]
) -> List[DimensionExpr]:
    """
    Find all dimension function calls in the query.

    Handles:
    - Simple: sentiment(observed)
    - With args: sentiment(observed, 'fear', 3)
    - With alias: sentiment(observed, 'fear') as mood
    - In SELECT and GROUP BY
    """
    exprs = []
    seen_ids = set()

    for func_name, entry in dimension_funcs.items():
        # Pattern: func_name(args) possibly followed by AS alias
        # Args can contain nested parens, strings, etc.
        pattern = rf'\b{re.escape(func_name)}\s*\(([^)]+)\)(?:\s+[Aa][Ss]\s+(\w+))?'

        for match in re.finditer(pattern, query, re.IGNORECASE):
            args_str = match.group(1).strip()
            alias = match.group(2)
            full_match = match.group(0)

            # Parse arguments
            args = _parse_function_args(args_str)
            if not args:
                continue

            # First arg is the dimension source (column)
            source_col = args[0].strip()

            # Remove quotes if it's a column reference (not a string literal)
            if not (source_col.startswith("'") or source_col.startswith('"')):
                source_col = source_col.strip('`"')

            # Remaining args are scalar modifiers
            scalar_args = [a.strip() for a in args[1:]]

            # Generate stable ID based on function + column + args
            id_base = f"{func_name}:{source_col}:{':'.join(scalar_args)}"
            id_hash = hashlib.md5(id_base.encode()).hexdigest()[:8]
            expr_id = f"__dim_{func_name}_{_sanitize_col_name(source_col)}_{id_hash}"

            # Skip if we've already seen this exact expression
            if expr_id in seen_ids:
                # But still record it for replacement (might have different alias)
                exprs.append(DimensionExpr(
                    func_name=func_name,
                    source_col=source_col,
                    scalar_args=scalar_args,
                    alias=alias,
                    full_match=full_match,
                    id=expr_id,
                    entry=entry,
                ))
                continue

            seen_ids.add(expr_id)
            exprs.append(DimensionExpr(
                func_name=func_name,
                source_col=source_col,
                scalar_args=scalar_args,
                alias=alias,
                full_match=full_match,
                id=expr_id,
                entry=entry,
            ))

            log.debug(f"[dimension_rewriter] Found: {func_name}({source_col}, {scalar_args}) -> {expr_id}")

    return exprs


def _parse_function_args(args_str: str) -> List[str]:
    """
    Parse function arguments, respecting nested parens and quotes.

    "observed, 'fear', 3" -> ["observed", "'fear'", "3"]
    """
    args = []
    current = []
    depth = 0
    in_string = False
    string_char = None

    for char in args_str:
        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
            current.append(char)
        elif char == string_char and in_string:
            in_string = False
            string_char = None
            current.append(char)
        elif char == '(' and not in_string:
            depth += 1
            current.append(char)
        elif char == ')' and not in_string:
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0 and not in_string:
            args.append(''.join(current).strip())
            current = []
        else:
            current.append(char)

    if current:
        args.append(''.join(current).strip())

    return [a for a in args if a]


def _sanitize_col_name(col: str) -> str:
    """Sanitize column name for use in identifiers."""
    # Remove table prefix, keep just column name
    if '.' in col:
        col = col.split('.')[-1]
    # Replace non-alphanumeric with underscore
    return re.sub(r'[^a-zA-Z0-9]', '_', col)


def _extract_source(query: str) -> Optional[str]:
    """
    Extract the source table or subquery from a query.

    Returns the source as it should appear in the CTE.
    """
    # Try subquery first: FROM (SELECT ...) alias
    subquery_match = re.search(
        r'FROM\s+(\([^)]+\))\s*(?:AS\s+)?(\w+)?',
        query,
        re.IGNORECASE | re.DOTALL
    )
    if subquery_match:
        subquery = subquery_match.group(1)
        alias = subquery_match.group(2)
        if alias:
            return f"{subquery} AS {alias}"
        return subquery

    # Simple table: FROM table_name [alias]
    table_match = re.search(
        r'FROM\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?',
        query,
        re.IGNORECASE
    )
    if table_match:
        table = table_match.group(1)
        alias = table_match.group(2)
        # Don't return alias as source - we want the table name
        return table

    return None


def _extract_where_clause(query: str) -> str:
    """
    Extract WHERE clause from query.

    Returns empty string if no WHERE clause.
    Important: The WHERE must be applied to bucket extraction too!
    """
    # Match WHERE ... up to GROUP BY, ORDER BY, HAVING, LIMIT, or end
    where_match = re.search(
        r'\bWHERE\s+(.+?)(?=\s+(?:GROUP|ORDER|HAVING|LIMIT)\s|\s*$)',
        query,
        re.IGNORECASE | re.DOTALL
    )
    if where_match:
        return f"WHERE {where_match.group(1).strip()}"
    return ""


def _generate_dimension_ctes(
    exprs: List[DimensionExpr],
    source: str,
    where_clause: str
) -> str:
    """
    Generate CTEs for dimension bucket computation.

    For each unique dimension expression:
    1. Extraction CTE: compute bucket mapping from all values
    2. Classification CTE: add bucket column to each row
    """
    ctes = []

    # Dedupe expressions by ID (same expr may appear multiple times in query)
    unique_exprs = {e.id: e for e in exprs}

    # Generate extraction CTEs
    for expr_id, expr in unique_exprs.items():
        config = _get_dimension_config(expr.entry)
        mode = config.get('mode', 'mapping')

        # Build scalar args for the compute function
        scalar_args_str = ""
        if expr.scalar_args:
            scalar_args_str = ", " + ", ".join(expr.scalar_args)

        # DuckDB doesn't support function overloading for Python UDFs, so we use
        # arity-specific function names:
        # - {name}_compute   = 1 arg (just values_json)
        # - {name}_compute_2 = 2 args (values_json + one scalar)
        # - {name}_compute_3 = 3 args (values_json + two scalars)
        # Total arity = 1 (values_json) + len(scalar_args)
        total_arity = 1 + len(expr.scalar_args)
        if total_arity == 1:
            compute_func = f"{expr.func_name}_compute"
        else:
            compute_func = f"{expr.func_name}_compute_{total_arity}"

        if mode == 'mapping':
            # Single cascade mode: returns {mapping: {value: bucket}}
            ctes.append(f"""_{expr_id}_mapping AS (
    SELECT {compute_func}(
        to_json(LIST({expr.source_col})){scalar_args_str}
    ) as _result
    FROM {source}
    {where_clause}
)""")

        elif mode == 'extractor_classifier':
            # Two-stage mode
            extractor = config.get('extractor', {})
            extractor_func = extractor.get('function', f'{expr.func_name}_extract')

            ctes.append(f"""_{expr_id}_buckets AS (
    SELECT {extractor_func}(
        to_json(LIST({expr.source_col})){scalar_args_str}
    ) as _buckets
    FROM {source}
    {where_clause}
)""")

    # Generate classification CTE
    classify_cols = []
    cross_joins = []

    for expr_id, expr in unique_exprs.items():
        config = _get_dimension_config(expr.entry)
        mode = config.get('mode', 'mapping')

        if mode == 'mapping':
            # Look up value in the mapping
            # The cascade returns JSON like: {"mapping": {"value1": "bucket1", ...}}
            # NOTE: Use json_each() subquery for dynamic key lookup because:
            # 1. json_extract_string(json, path) requires path to be constant
            # 2. Column values may contain special chars ($, commas, quotes, etc.)
            # The subquery expands the JSON object and filters by key = column value
            classify_cols.append(f"""COALESCE(
            (SELECT TRIM(BOTH '"' FROM value::VARCHAR)
             FROM json_each(_{expr_id}_mapping._result->'mapping')
             WHERE key = _source.{expr.source_col}
             LIMIT 1),
            'Unknown'
        ) as {expr_id}""")
            cross_joins.append(f"_{expr_id}_mapping")

        elif mode == 'extractor_classifier':
            classifier = config.get('classifier', {})
            classifier_func = classifier.get('function', f'{expr.func_name}_classify')

            classify_cols.append(f"""{classifier_func}(
            _source.{expr.source_col},
            (SELECT _buckets FROM _{expr_id}_buckets)
        ) as {expr_id}""")

    # Build the classification CTE
    cross_join_str = ""
    if cross_joins:
        cross_join_str = ", " + ", ".join(cross_joins)

    ctes.append(f"""_dim_classified AS (
    SELECT _source.*,
        {(','+chr(10)+'        ').join(classify_cols)}
    FROM {source} AS _source{cross_join_str}
    {where_clause}
)""")

    return ",\n".join(ctes)


def _rewrite_main_query(
    query: str,
    exprs: List[DimensionExpr],
    source: str
) -> str:
    """
    Rewrite the main query to use dimension bucket columns.

    1. Replace dimension function calls with bucket column references
    2. Replace FROM source with FROM _dim_classified
    """
    result = query

    # Sort by length (longest first) to avoid partial replacements
    sorted_exprs = sorted(exprs, key=lambda e: len(e.full_match), reverse=True)

    for expr in sorted_exprs:
        # Build replacement: either with alias or just the column ref
        if expr.alias:
            replacement = f"{expr.id} AS {expr.alias}"
        else:
            replacement = expr.id

        # Replace the full match
        # Use a function to handle case-insensitive replacement while preserving structure
        pattern = re.escape(expr.full_match)
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Replace FROM source with FROM _dim_classified
    # Handle various source patterns
    source_escaped = re.escape(source)

    # Pattern: FROM source [AS alias]
    # Important: The alias pattern must NOT match SQL keywords (GROUP, ORDER, WHERE, etc.)
    # Use negative lookahead to exclude keywords, and word boundary to avoid partial matches
    sql_keywords = r'(?!(?:GROUP|ORDER|WHERE|HAVING|LIMIT|JOIN|LEFT|RIGHT|INNER|OUTER|CROSS|UNION|EXCEPT|INTERSECT)\b)'

    # Match: FROM table [AS alias] or FROM table alias
    # The alias must not be a SQL keyword
    from_pattern = rf'FROM\s+{source_escaped}(?:\s+(?:AS\s+)?({sql_keywords}\w+))?'

    def from_replacer(m):
        # Don't carry over the alias - _dim_classified is our new source
        return "FROM _dim_classified"

    result = re.sub(from_pattern, from_replacer, result, flags=re.IGNORECASE)

    return result


# ============================================================================
# Integration with existing rewrite pipeline
# ============================================================================

def has_dimension_functions(query: str) -> bool:
    """
    Quick check if query contains any dimension functions.

    Used by main rewriter to decide whether to invoke dimension rewriting.
    """
    dimension_funcs = _get_dimension_functions()

    if not dimension_funcs:
        return False

    query_upper = query.upper()

    for func_name in dimension_funcs.keys():
        # Check for function call pattern
        if re.search(rf'\b{func_name.upper()}\s*\(', query_upper):
            return True

    return False
