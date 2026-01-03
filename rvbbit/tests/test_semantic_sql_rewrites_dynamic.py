"""
Dynamic SQL Rewrite Tests for Semantic SQL Operators.

This test suite automatically discovers all cascade files with `sql_function` metadata
and generates rewrite tests for each operator pattern. No LLM calls - pure syntax testing.

Test Coverage:
- All built-in operators in cascades/semantic_sql/
- User-defined operators in traits/ with sql_function metadata
- Multiple calling shapes per operator (infix, function, aggregate)
- Argument variations (optional params, different arities)

The test dynamically generates test cases based on the operator patterns defined
in each cascade's `sql_function.operators` list.
"""

import pytest
import yaml
import os
from pathlib import Path
from typing import List, Dict, Any, Tuple
from rvbbit.sql_rewriter import rewrite_rvbbit_syntax


# ============================================================================
# Test Case Discovery
# ============================================================================

def discover_sql_cascades() -> List[Dict[str, Any]]:
    """
    Discover all cascade files with sql_function metadata.

    Scans:
    - cascades/semantic_sql/ (built-in operators)
    - traits/**/*.cascade.yaml (user-defined operators)

    Returns:
        List of cascade metadata dicts with:
        - path: str - Full path to cascade file
        - cascade_id: str - Unique cascade identifier
        - function_name: str - SQL function name
        - operators: List[str] - Operator patterns
        - args: List[dict] - Argument definitions
        - returns: str - Return type
        - shape: str - SCALAR, AGGREGATE, or TABLE
    """
    from rvbbit.config import get_config

    config = get_config()
    cascades = []

    # Scan directories
    search_paths = [
        Path(config.cascades_dir) / "semantic_sql",
        Path(config.traits_dir),
    ]

    for base_path in search_paths:
        if not base_path.exists():
            continue

        for cascade_file in base_path.rglob("*.cascade.yaml"):
            try:
                with open(cascade_file, 'r') as f:
                    cascade_data = yaml.safe_load(f)

                # Check if this cascade has sql_function metadata
                if 'sql_function' not in cascade_data:
                    continue

                sql_func = cascade_data['sql_function']

                # Skip if no operators defined
                if 'operators' not in sql_func or not sql_func['operators']:
                    continue

                cascades.append({
                    'path': str(cascade_file),
                    'cascade_id': cascade_data.get('cascade_id', cascade_file.stem),
                    'function_name': sql_func['name'],
                    'operators': sql_func['operators'],
                    'args': sql_func.get('args', []),
                    'returns': sql_func.get('returns', 'VARCHAR'),
                    'shape': sql_func.get('shape', 'SCALAR'),
                })

            except Exception as e:
                print(f"Warning: Could not load {cascade_file}: {e}")
                continue

    return cascades


def generate_test_cases(cascade: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """
    Generate test cases for a single cascade.

    Args:
        cascade: Cascade metadata dict

    Returns:
        List of (test_name, input_sql, expected_function) tuples
    """
    test_cases = []
    function_name = cascade['function_name']
    operators = cascade['operators']
    args = cascade['args']
    shape = cascade['shape']

    for i, operator_pattern in enumerate(operators):
        # Generate test cases based on shape
        if shape == 'SCALAR':
            test_cases.extend(_generate_scalar_tests(function_name, operator_pattern, args, i))
        elif shape == 'AGGREGATE':
            test_cases.extend(_generate_aggregate_tests(function_name, operator_pattern, args, i))
        elif shape == 'TABLE':
            test_cases.extend(_generate_table_tests(function_name, operator_pattern, args, i))

    return test_cases


def _generate_scalar_tests(func_name: str, pattern: str, args: List[dict], pattern_idx: int) -> List[Tuple[str, str, str]]:
    """Generate test cases for SCALAR operators."""
    tests = []

    # Extract variable names from pattern ({{ var }})
    import re
    var_names = re.findall(r'\{\{\s*(\w+)\s*\}\}', pattern)

    # Build concrete examples
    if 'MEANS' in pattern or 'MATCHES' in pattern:
        # Boolean filter operators
        tests.append((
            f"{func_name}_means_where",
            "SELECT * FROM docs WHERE title MEANS 'visual contact'",
            func_name
        ))
        tests.append((
            f"{func_name}_means_not",
            "SELECT * FROM docs WHERE NOT (description MEANS 'hoax or prank')",
            func_name
        ))

    elif 'ABOUT' in pattern:
        # Relevance scoring
        tests.append((
            f"{func_name}_about_simple",
            "SELECT * FROM docs WHERE content ABOUT 'machine learning'",
            func_name
        ))
        tests.append((
            f"{func_name}_about_threshold",
            "SELECT * FROM docs WHERE content ABOUT 'data science' > 0.7",
            func_name
        ))
        tests.append((
            f"{func_name}_about_select",
            "SELECT title, content ABOUT 'AI safety' as relevance FROM docs",
            func_name
        ))

    elif 'RELEVANCE TO' in pattern:
        # Ordering by relevance
        tests.append((
            f"{func_name}_relevance_order",
            "SELECT * FROM docs ORDER BY content RELEVANCE TO 'quarterly earnings'",
            func_name
        ))
        tests.append((
            f"{func_name}_relevance_asc",
            "SELECT * FROM docs ORDER BY content RELEVANCE TO 'financial reports' ASC",
            func_name
        ))

    elif 'IMPLIES' in pattern:
        # Logical implication
        tests.append((
            f"{func_name}_implies_where",
            "SELECT * FROM claims WHERE observed IMPLIES 'witness saw a creature'",
            func_name
        ))
        tests.append((
            f"{func_name}_implies_columns",
            "SELECT * FROM claims WHERE premise IMPLIES conclusion",
            func_name
        ))

    elif 'CONTRADICTS' in pattern:
        # Contradiction detection
        tests.append((
            f"{func_name}_contradicts_literal",
            "SELECT * FROM reviews WHERE claim CONTRADICTS 'product is reliable'",
            func_name
        ))
        tests.append((
            f"{func_name}_contradicts_columns",
            "SELECT * FROM statements WHERE statement_a CONTRADICTS statement_b",
            func_name
        ))

    elif 'SIMILAR_TO' in pattern or 'SIMILAR TO' in pattern:
        # Similarity scoring
        tests.append((
            f"{func_name}_similar_where",
            "SELECT * FROM products WHERE description SIMILAR_TO 'sustainable and eco-friendly' > 0.7",
            func_name
        ))
        tests.append((
            f"{func_name}_similar_join",
            "SELECT c.company, s.vendor, c.company SIMILAR_TO s.vendor as match_score FROM customers c, suppliers s WHERE c.company SIMILAR_TO s.vendor > 0.8 LIMIT 100",
            func_name
        ))

    elif 'ALIGNS' in pattern:
        # Narrative alignment
        tests.append((
            f"{func_name}_aligns_where",
            "SELECT * FROM tweets WHERE text ALIGNS 'our product narrative' > 0.7",
            func_name
        ))
        tests.append((
            f"{func_name}_aligns_select",
            "SELECT author, text ALIGNS 'SQL is the future of AI' as alignment_score FROM tweets",
            func_name
        ))

    elif 'SOUNDS_LIKE' in pattern:
        # Phonetic matching
        tests.append((
            f"{func_name}_sounds_like",
            "SELECT * FROM customers WHERE name SOUNDS_LIKE 'Smith'",
            func_name
        ))

    elif 'EXTRACTS' in pattern.upper():
        # Information extraction
        tests.append((
            f"{func_name}_extracts_select",
            "SELECT ticket_id, description EXTRACTS 'customer name' as customer FROM tickets",
            func_name
        ))
        tests.append((
            f"{func_name}_extracts_multi",
            "SELECT review, review EXTRACTS 'product mentioned' as product, review EXTRACTS 'price' as price FROM reviews",
            func_name
        ))
        tests.append((
            f"{func_name}_extracts_where",
            "SELECT * FROM emails WHERE body EXTRACTS 'order number' IS NOT NULL",
            func_name
        ))

    elif 'ASK' in pattern.upper() and 'FROM' not in pattern.upper():
        # Generic prompt application (ASK operator, not ASK...FROM variant)
        tests.append((
            f"{func_name}_ask_simple",
            "SELECT review ASK 'is this positive or negative?' as sentiment FROM reviews",
            func_name
        ))
        tests.append((
            f"{func_name}_ask_numeric",
            "SELECT description ASK 'rate urgency 1-10' as urgency FROM tickets",
            func_name
        ))
        tests.append((
            f"{func_name}_ask_transform",
            "SELECT title ASK 'translate to Spanish' as titulo FROM articles",
            func_name
        ))
        tests.append((
            f"{func_name}_ask_where",
            "SELECT * FROM reviews WHERE review ASK 'is this spam?' = 'yes'",
            func_name
        ))

    elif 'CONDENSE' in pattern.upper() or 'TLDR' in pattern.upper():
        # Scalar text summarization (function operators - no rewriting needed!)
        # These are registered directly as UDFs via register_dynamic_sql_functions()
        # NOTE: Function operators like CONDENSE(x) don't get rewritten - they're already
        # valid SQL that calls the dynamically-registered UDF
        pass  # Skip test generation for function operators (they don't need rewriting)

    elif '~' in pattern:
        # Tilde operator for entity matching
        tests.append((
            f"{func_name}_tilde_literal",
            "SELECT * FROM docs WHERE title ~ 'visual contact'",
            func_name
        ))
        tests.append((
            f"{func_name}_tilde_simple",
            "SELECT * FROM customers c, suppliers s WHERE c.company ~ s.vendor",
            func_name
        ))
        tests.append((
            f"{func_name}_tilde_negation",
            "SELECT * FROM products p1, products p2 WHERE p1.name !~ p2.name",
            func_name
        ))

    # Direct function call (always works for scalar)
    if len(var_names) >= 2:
        tests.append((
            f"{func_name}_direct_call",
            f"SELECT {func_name}('{var_names[1]}', {var_names[0]}) FROM docs",
            func_name
        ))

    return tests


def _generate_aggregate_tests(func_name: str, pattern: str, args: List[dict], pattern_idx: int) -> List[Tuple[str, str, str]]:
    """Generate test cases for AGGREGATE operators."""
    tests = []

    if 'SUMMARIZE' in pattern.upper():
        tests.append((
            f"{func_name}_group_by",
            "SELECT category, SUMMARIZE(review_text) as summary FROM reviews GROUP BY category",
            "llm_summarize_1"  # Aggregates get rewritten to llm_*
        ))
        tests.append((
            f"{func_name}_simple",
            "SELECT state, SUMMARIZE(title) as summary FROM bigfoot GROUP BY state",
            "llm_summarize_1"
        ))

    elif 'THEMES' in pattern.upper() or 'TOPICS' in pattern.upper():
        tests.append((
            f"{func_name}_themes_default",
            "SELECT category, THEMES(review_text) as topics FROM reviews GROUP BY category",
            "llm_themes_1"
        ))
        tests.append((
            f"{func_name}_topics_count",
            "SELECT category, TOPICS(comments, 3) as main_topics FROM feedback GROUP BY category",
            "llm_themes_2"
        ))

    elif 'CLUSTER' in pattern.upper() or 'MEANING' in pattern.upper():
        tests.append((
            f"{func_name}_cluster",
            "SELECT CLUSTER(category, 5, 'by product type') FROM products",
            "llm_cluster_3"
        ))

    return tests


def _generate_table_tests(func_name: str, pattern: str, args: List[dict], pattern_idx: int) -> List[Tuple[str, str, str]]:
    """Generate test cases for TABLE-valued functions."""
    tests = []

    if 'VECTOR_SEARCH' in pattern:
        tests.append((
            f"{func_name}_basic",
            "SELECT * FROM VECTOR_SEARCH('eco-friendly products', 'products', 10)",
            "vector_search_json"
        ))
        tests.append((
            f"{func_name}_with_threshold",
            "SELECT * FROM VECTOR_SEARCH('query', 'table', 10, 0.7)",
            "vector_search_json"
        ))
        tests.append((
            f"{func_name}_column_filter",
            "SELECT * FROM VECTOR_SEARCH('eco-friendly', 'products.description', 10)",
            "vector_search_json"
        ))

    elif 'EMBED' in pattern:
        tests.append((
            f"{func_name}_simple",
            "SELECT id, EMBED(description) FROM products",
            "semantic_embed_with_storage"  # Context injection rewrites to storage version
        ))
        tests.append((
            f"{func_name}_with_model",
            "SELECT id, EMBED(text, 'openai/text-embedding-3-large') FROM docs",
            "semantic_embed_with_storage"
        ))

    return tests


# ============================================================================
# Pytest Dynamic Test Generation
# ============================================================================

# Discover all SQL cascades at module load time
ALL_SQL_CASCADES = discover_sql_cascades()

# Generate test case parameters
test_params = []
for cascade in ALL_SQL_CASCADES:
    cases = generate_test_cases(cascade)
    for test_name, input_sql, expected_func in cases:
        test_params.append((
            f"{cascade['cascade_id']}::{test_name}",
            input_sql,
            expected_func,
            cascade['cascade_id']
        ))


@pytest.mark.parametrize("test_id,input_sql,expected_function,cascade_id", test_params)
def test_sql_operator_rewrite(test_id: str, input_sql: str, expected_function: str, cascade_id: str):
    """
    Test that SQL operator is correctly rewritten to function call.

    This test does NOT execute the query or call LLMs - it only verifies
    that the SQL syntax is correctly transformed into the expected UDF call.

    Note: UDFs are registered with BOTH full name (semantic_*) and short name,
    so we accept either form in the rewritten SQL.
    """
    # Rewrite the SQL
    rewritten = rewrite_rvbbit_syntax(input_sql)

    # Build list of acceptable function names (full and short forms)
    acceptable_names = [expected_function]
    if expected_function.startswith('semantic_'):
        # Also accept short form
        short_name = expected_function.replace('semantic_', '')
        acceptable_names.append(short_name)

    # Verify at least one expected function appears in the rewritten SQL
    found = any(name in rewritten for name in acceptable_names)
    assert found, (
        f"Expected function '{expected_function}' (or short form) not found in rewrite.\n"
        f"Cascade: {cascade_id}\n"
        f"Original:  {input_sql}\n"
        f"Rewritten: {rewritten}\n"
        f"Looking for any of: {acceptable_names}"
    )


def test_all_cascades_discovered():
    """Sanity check that we discovered SQL cascades."""
    assert len(ALL_SQL_CASCADES) > 0, "No SQL cascades discovered!"

    # Verify we found the core built-ins
    found_ids = {c['cascade_id'] for c in ALL_SQL_CASCADES}

    expected_builtins = [
        'semantic_matches',
        'semantic_score',
        'semantic_implies',
        'semantic_contradicts',
        'semantic_aligns',
        'semantic_summarize',
        'semantic_themes',
        'semantic_cluster',
        'semantic_embed',
        'semantic_embed_with_storage',
        'semantic_vector_search',  # Note: 'vector_search' is the function name, but cascade_id is semantic_vector_search
        'semantic_similar_to',
    ]

    found_builtins = [bid for bid in expected_builtins if bid in found_ids]

    print(f"\nDiscovered {len(ALL_SQL_CASCADES)} SQL cascades")
    print(f"Found {len(found_builtins)}/{len(expected_builtins)} expected built-ins")
    print(f"Cascade IDs: {sorted(found_ids)}")

    # Should find at least 10 built-in operators
    assert len(found_builtins) >= 10, (
        f"Expected at least 10 built-in operators, found {len(found_builtins)}: {found_builtins}"
    )


def test_generated_test_count():
    """Verify we generated a reasonable number of test cases."""
    assert len(test_params) > 20, (
        f"Expected at least 20 generated test cases, got {len(test_params)}"
    )

    print(f"\n✅ Generated {len(test_params)} dynamic test cases")

    # Print breakdown by cascade
    by_cascade = {}
    for test_id, _, _, cascade_id in test_params:
        by_cascade[cascade_id] = by_cascade.get(cascade_id, 0) + 1

    print("\nTest cases by cascade:")
    for cascade_id, count in sorted(by_cascade.items()):
        print(f"  {cascade_id}: {count} tests")


# ============================================================================
# Manual Spot Checks (for debugging)
# ============================================================================

def test_spot_check_means_operator():
    """Spot check: MEANS operator should rewrite to matches (or semantic_matches)."""
    sql = "SELECT * FROM docs WHERE title MEANS 'visual contact'"
    rewritten = rewrite_rvbbit_syntax(sql)
    assert ('semantic_matches' in rewritten or 'matches' in rewritten)
    assert "'visual contact'" in rewritten
    assert 'title' in rewritten


def test_spot_check_about_operator():
    """Spot check: ABOUT operator should rewrite to score (or semantic_score)."""
    sql = "SELECT * FROM docs WHERE content ABOUT 'machine learning' > 0.7"
    rewritten = rewrite_rvbbit_syntax(sql)
    assert ('semantic_score' in rewritten or 'score' in rewritten)
    assert "'machine learning'" in rewritten
    assert '0.7' in rewritten


def test_spot_check_relevance_to_order_by_is_not_broken():
    """Spot check: ORDER BY ... RELEVANCE TO ... should not leave a stray TO token."""
    sql = "SELECT * FROM docs ORDER BY content RELEVANCE TO 'quarterly earnings'"
    rewritten = rewrite_rvbbit_syntax(sql)
    assert ('semantic_score' in rewritten or 'score' in rewritten)
    assert "'quarterly earnings'" in rewritten
    assert "TO) 'quarterly earnings'" not in rewritten


def test_spot_check_aligns_with_is_not_broken():
    """Spot check: ALIGNS WITH should rewrite as a single operator phrase."""
    sql = "SELECT * FROM policies WHERE description ALIGNS WITH 'customer-first values'"
    rewritten = rewrite_rvbbit_syntax(sql)
    assert ('semantic_aligns' in rewritten or 'aligns' in rewritten)
    assert "'customer-first values'" in rewritten
    assert ", WITH)" not in rewritten


def test_spot_check_embed_operator():
    """Spot check: EMBED operator with context injection."""
    sql = "SELECT id, EMBED(description) FROM products"
    rewritten = rewrite_rvbbit_syntax(sql)
    # Should inject table/column/ID for auto-storage
    assert 'semantic_embed_with_storage' in rewritten
    assert "'products'" in rewritten  # table name
    assert "'description'" in rewritten  # column name


def test_spot_check_vector_search():
    """Spot check: VECTOR_SEARCH table function."""
    sql = "SELECT * FROM VECTOR_SEARCH('eco-friendly', 'products', 10)"
    rewritten = rewrite_rvbbit_syntax(sql)
    assert 'vector_search_json' in rewritten
    assert "'eco-friendly'" in rewritten
    assert "'products'" in rewritten


def test_spot_check_summarize_aggregate():
    """Spot check: SUMMARIZE aggregate function."""
    sql = "SELECT state, SUMMARIZE(title) as summary FROM bigfoot GROUP BY state"
    rewritten = rewrite_rvbbit_syntax(sql)
    assert 'llm_summarize_1' in rewritten  # Aggregates use llm_* prefix
    assert 'LIST(title)' in rewritten  # Aggregates collect via LIST()


if __name__ == "__main__":
    # Run discovery and print summary
    print("="*70)
    print("Semantic SQL Dynamic Test Suite")
    print("="*70)

    cascades = discover_sql_cascades()
    print(f"\nDiscovered {len(cascades)} SQL cascades:")
    for c in cascades:
        print(f"  - {c['cascade_id']} ({c['shape']}): {len(c['operators'])} operators")

    print(f"\nGenerating test cases...")
    total_tests = 0
    for c in cascades:
        cases = generate_test_cases(c)
        total_tests += len(cases)
        print(f"  - {c['cascade_id']}: {len(cases)} test cases")

    print(f"\n✅ Total: {total_tests} dynamic test cases generated")
    print("\nRun with: pytest rvbbit/tests/test_semantic_sql_rewrites_dynamic.py -v")
