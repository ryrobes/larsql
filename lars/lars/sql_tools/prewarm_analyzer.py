"""
Prewarm Analyzer - Extracts scalar semantic function calls for cache pre-warming.

Given a SQL query with scalar semantic functions, this module:
1. Finds all semantic function calls
2. Extracts the argument expressions
3. Generates "distinct values" queries to feed into LARS MAP PARALLEL

The sidecar prewarm strategy:
- While the main query executes serially (row by row)
- A parallel sidecar pre-computes distinct values
- Cache hits accelerate the serial execution

This is a "race to warm the cache" optimization that doesn't change SQL semantics.
"""

import sqlglot
from sqlglot import exp
from typing import List, Dict, Any, Optional, Tuple
import logging

log = logging.getLogger(__name__)


def analyze_query_for_prewarm(query: str) -> List[Dict[str, Any]]:
    """
    Analyze a SQL query and return pre-warm specifications for scalar semantic functions.

    Args:
        query: SQL query string

    Returns:
        List of dicts with:
        - function: The semantic function name (e.g., 'semantic_clean_year')
        - arg_sql: The SQL expression passed to the function
        - distinct_query: Query to get distinct values for pre-warming
        - cascade: Path to the cascade file
        - input_key: The cascade input parameter name (usually 'text')
    """
    try:
        parsed = sqlglot.parse_one(query, dialect='duckdb')
    except Exception as e:
        log.warning(f"[prewarm] Failed to parse query: {e}")
        return []

    # Get registered SQL functions from registry
    registered_functions = _get_registered_scalar_functions()

    results = []
    seen = set()

    for func in parsed.find_all(exp.Anonymous):
        func_name = func.name.lower()

        # Check if this is a registered semantic SQL function
        # Try multiple naming conventions:
        # 1. Direct name (e.g., 'condense')
        # 2. With semantic_ prefix (e.g., 'semantic_condense')
        # 3. Short name if called with semantic_ prefix
        func_info = registered_functions.get(func_name)
        registry_name = func_name  # Will be updated to canonical name
        if not func_info:
            # Try with semantic_ prefix
            func_info = registered_functions.get(f'semantic_{func_name}')
            if func_info:
                registry_name = f'semantic_{func_name}'
        if not func_info:
            # If called as semantic_*, try the short name
            if func_name.startswith('semantic_'):
                short_name = func_name.replace('semantic_', '')
                func_info = registered_functions.get(short_name)
                if func_info:
                    registry_name = short_name
                if not func_info:
                    func_info = registered_functions.get(f'semantic_{short_name}')
                    if func_info:
                        registry_name = f'semantic_{short_name}'

        if not func_info:
            continue

        # Use the canonical registry name for cache key matching
        registry_name = func_info.get('name', registry_name)

        # Only prewarm SCALAR functions (not aggregates)
        if func_info.get('shape', 'SCALAR') != 'SCALAR':
            log.debug(f"[prewarm] Skipping non-scalar function: {func_name} (shape={func_info.get('shape')})")
            continue

        if not func.expressions:
            continue

        # Extract ALL arguments from the function call
        # First arg is typically the column (varies per row), others may be constants
        all_args = []
        column_arg_index = 0  # First arg is the variable column by default

        for i, arg_expr in enumerate(func.expressions):
            arg_sql = arg_expr.sql(dialect='duckdb')
            # Check if this is a column reference or a constant
            is_column = isinstance(arg_expr, (exp.Column, exp.Identifier)) or \
                       (hasattr(arg_expr, 'find') and arg_expr.find(exp.Column))
            all_args.append({
                'sql': arg_sql,
                'is_column': is_column,
                'index': i,
            })

        if not all_args:
            continue

        # Find the column argument (first column reference)
        column_arg = next((a for a in all_args if a['is_column']), all_args[0])
        column_arg_sql = column_arg['sql']
        column_arg_index = column_arg['index']

        # Dedupe by (registry_name, all args) - same function on same args only needs one prewarm
        key = (registry_name, tuple(a['sql'] for a in all_args))
        if key in seen:
            continue
        seen.add(key)

        # Build the distinct values query for the column argument
        distinct_query = _build_distinct_query(parsed, func, column_arg_sql)

        if distinct_query:
            # Get arg names from registry
            arg_names = func_info.get('arg_names', ['text'])

            results.append({
                'function': registry_name,  # Use canonical registry name!
                'arg_sql': column_arg_sql,
                'distinct_query': distinct_query,
                'cascade': func_info['cascade_path'],
                'input_key': func_info.get('input_key', 'text'),
                # Include all args for proper cache key matching
                'all_args': all_args,
                'arg_names': arg_names,
                'column_arg_index': column_arg_index,
            })

    return results


def _get_registered_scalar_functions() -> Dict[str, Dict[str, Any]]:
    """
    Get all registered scalar SQL functions from the semantic SQL registry.

    Returns dict mapping function_name -> {cascade_path, shape, input_key, arg_names, ...}
    """
    try:
        from lars.semantic_sql.registry import get_sql_function_registry

        registry = get_sql_function_registry()
        result = {}

        for name, entry in registry.items():
            # Get ALL arg names (for multi-arg functions)
            arg_names = []
            input_key = 'text'
            if entry.args:
                arg_names = [a.get('name', f'arg{i}') for i, a in enumerate(entry.args)]
                input_key = arg_names[0] if arg_names else 'text'

            result[name.lower()] = {
                'name': name,  # Canonical registry name
                'cascade_path': entry.cascade_path,
                'shape': entry.shape,
                'input_key': input_key,
                'arg_names': arg_names,
            }

        return result

    except Exception as e:
        log.warning(f"[prewarm] Failed to load registry: {e}")
        return {}


def _build_distinct_query(
    full_query: exp.Expression,
    func_node: exp.Anonymous,
    arg_sql: str
) -> Optional[str]:
    """
    Build a query to get distinct values of a semantic function's argument.

    Strategy:
    1. Find the SELECT containing the function
    2. Clone it and replace SELECT clause with DISTINCT <arg>
    3. Remove ORDER BY, LIMIT, GROUP BY (not relevant for distinct values)
    4. Preserve FROM, WHERE, JOINs, CTEs
    5. Add safety LIMIT 500
    """
    # Find the SELECT containing this function
    parent_select = func_node.find_ancestor(exp.Select)
    if not parent_select:
        return None

    # Clone the select
    cloned = parent_select.copy()

    # Parse the argument expression
    arg_expr = _parse_expression(arg_sql)
    if arg_expr is None:
        return None

    # Replace SELECT clause with DISTINCT <arg>
    cloned.set("expressions", [arg_expr])
    # Set DISTINCT using the proper Expression type
    cloned.set("distinct", exp.Distinct())

    # Remove clauses not relevant for distinct value extraction
    _remove_nodes(cloned, (exp.Order, exp.Limit, exp.Group, exp.Having))

    # Add safety limit to avoid pulling millions of distinct values
    cloned = cloned.limit(500)

    # Handle CTEs - check if we need to include WITH clause
    with_clause = full_query.find(exp.With)

    # Check if cloned already has a WITH clause (can happen if parent_select is the top-level)
    cloned_with = cloned.find(exp.With)

    if with_clause and not cloned_with:
        # Check if our cloned query references any CTE
        cte_names = _get_cte_names(with_clause)
        tables_used = {t.name for t in cloned.find_all(exp.Table) if t.name}

        if cte_names & tables_used:
            # Attach the WITH clause to our cloned select
            cloned.set("with", with_clause.copy())

    return cloned.sql(dialect='duckdb')


def _parse_expression(sql: str) -> Optional[exp.Expression]:
    """Parse a SQL expression string into an AST node."""
    try:
        # Try direct parse
        return sqlglot.parse_one(sql, dialect='duckdb', into=exp.Expression)
    except:
        pass

    try:
        # Wrap in SELECT and extract
        wrapper = sqlglot.parse_one(f"SELECT {sql}", dialect='duckdb')
        if wrapper.expressions:
            return wrapper.expressions[0]
    except Exception as e:
        log.warning(f"[prewarm] Failed to parse expression '{sql}': {e}")

    return None


def _remove_nodes(tree: exp.Expression, node_types: Tuple) -> None:
    """Remove all nodes of given types from tree."""
    for node in list(tree.find_all(node_types)):
        node.pop()


def _get_cte_names(with_clause: exp.With) -> set:
    """Extract CTE names from a WITH clause."""
    names = set()
    for cte in with_clause.expressions:
        if hasattr(cte, 'alias') and cte.alias:
            names.add(cte.alias)
    return names


def generate_prewarm_map_sql(spec: Dict[str, Any], parallel: int = 5) -> str:
    """
    Generate LARS MAP PARALLEL SQL for pre-warming.

    Args:
        spec: Prewarm specification from analyze_query_for_prewarm()
        parallel: Number of parallel workers

    Returns:
        LARS MAP PARALLEL SQL statement
    """
    cascade = spec['cascade']
    distinct_query = spec['distinct_query']
    input_key = spec.get('input_key', 'text')

    # The MAP PARALLEL syntax expects a query that returns rows
    # Each row becomes input to the cascade
    return f"""LARS MAP PARALLEL {parallel} '{cascade}'
USING ({distinct_query})
WITH (cache='1d');"""


def should_prewarm(spec: Dict[str, Any], min_distinct: int = 10, max_distinct: int = 500) -> bool:
    """
    Heuristic: Should we bother pre-warming this function?

    Args:
        spec: Prewarm specification
        min_distinct: Don't prewarm if fewer than this (serial is fine)
        max_distinct: Don't prewarm if more than this (diminishing returns)

    Returns:
        True if pre-warming is likely beneficial
    """
    # This would actually execute the distinct query to check count
    # For now, return True and let the caller decide
    return True


# ============================================================
# Debug / Test Utilities
# ============================================================

def debug_analyze(query: str) -> None:
    """Print detailed analysis of a query for debugging."""
    print(f"\n{'='*70}")
    print("ORIGINAL QUERY:")
    print(query.strip())
    print()

    results = analyze_query_for_prewarm(query)

    if not results:
        print("No prewarm opportunities found.")
        return

    for i, r in enumerate(results, 1):
        print(f"--- Prewarm Opportunity {i} ---")
        print(f"Function: {r['function']}")
        print(f"Argument: {r['arg_sql']}")
        print(f"Cascade:  {r['cascade']}")
        print(f"\nDistinct Query:")
        print(r['distinct_query'])
        print(f"\nMAP PARALLEL SQL:")
        print(generate_prewarm_map_sql(r))
        print()


if __name__ == "__main__":
    # Run test cases
    test_queries = [
        # 1. Simple scalar
        "SELECT semantic_clean_year(year_field) FROM products",

        # 2. Expression argument
        """SELECT semantic_clean_year(COALESCE(date1, date2)) as clean_year
           FROM products WHERE status = 'active'""",

        # 3. Multiple functions (should generate 2 prewarm specs)
        """SELECT
             semantic_clean_year(year_field) as yr,
             semantic_sentiment(description) as sent
           FROM products""",

        # 4. With JOINs - preserves JOIN context
        """SELECT semantic_clean_year(p.year_field)
           FROM products p
           JOIN categories c ON p.cat_id = c.id
           WHERE p.status = 'active'""",

        # 5. With CTE - should prepend WITH clause
        """WITH active AS (SELECT * FROM products WHERE status = 'active')
           SELECT semantic_clean_year(year_field) FROM active""",

        # 6. Subquery source
        """SELECT semantic_clean_year(year_field)
           FROM (SELECT * FROM products WHERE status = 'active') sub""",

        # 7. Same function, same arg - should dedupe
        """SELECT
             semantic_clean_year(year_field) as yr1,
             semantic_clean_year(year_field) as yr2
           FROM products""",

        # 8. Function in subquery (inner context)
        """SELECT * FROM (
             SELECT semantic_clean_year(year_field) as clean_year, name
             FROM products
           ) sub
           WHERE clean_year > 2000""",

        # 9. With ORDER BY and LIMIT - should strip them
        """SELECT semantic_clean_year(year_field) as yr
           FROM products
           ORDER BY yr DESC
           LIMIT 10""",

        # 10. Complex expression
        """SELECT semantic_clean_year(
             CASE WHEN date1 IS NOT NULL THEN date1 ELSE date2 END
           ) FROM products""",

        # 11. Qualified column names
        """SELECT semantic_clean_year(p.year_field)
           FROM products p
           WHERE p.category = 'electronics'""",

        # 12. Multiple tables, qualified refs
        """SELECT
             semantic_clean_year(p.release_date) as yr,
             semantic_sentiment(r.comment) as sent
           FROM products p
           LEFT JOIN reviews r ON p.id = r.product_id
           WHERE p.active = true""",
    ]

    for query in test_queries:
        debug_analyze(query)
