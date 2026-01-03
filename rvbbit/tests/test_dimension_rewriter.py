"""
Dimension Function Rewriter Tests.

Tests the transformation of DIMENSION-shaped cascades in GROUP BY/SELECT
into CTE-based execution for semantic bucketing.

Test Coverage:
- Detection of dimension functions from registry
- CTE generation for bucket extraction
- CTE generation for row classification
- Main query rewriting (SELECT/GROUP BY/FROM)
- WHERE clause propagation
- Alias preservation
- Multiple dimensions in same query
- Scalar modifier arguments
- Expression deduplication (same expr = same CTE)

NO LLM CALLS - pure syntax/transformation testing.
"""

import pytest
import re
from typing import List, Dict, Any
from dataclasses import dataclass


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def dimension_registry():
    """Get dimension functions from registry."""
    try:
        from rvbbit.semantic_sql.registry import initialize_registry, get_sql_function_registry
        initialize_registry(force=True)
        registry = get_sql_function_registry()

        dimension_funcs = {
            name: entry for name, entry in registry.items()
            if entry.sql_function.get('shape', '').upper() == 'DIMENSION'
        }
        return dimension_funcs
    except ImportError:
        pytest.skip("Registry not available")


@pytest.fixture
def rewriter():
    """Get the dimension rewriter module."""
    from rvbbit.sql_tools import dimension_rewriter
    return dimension_rewriter


# ============================================================================
# Discovery Tests
# ============================================================================

class TestDimensionDiscovery:
    """Test that dimension cascades are discovered correctly."""

    def test_dimension_cascades_found(self, dimension_registry):
        """Verify we found dimension-shaped cascades."""
        assert len(dimension_registry) > 0, "No DIMENSION-shaped cascades found in registry"

        print(f"\nFound {len(dimension_registry)} dimension functions:")
        for name, entry in dimension_registry.items():
            print(f"  - {name}: {entry.sql_function.get('args', [])}")

    def test_topics_dimension_registered(self, dimension_registry):
        """Verify topics dimension is registered."""
        assert 'topics' in dimension_registry, "topics dimension not found"
        entry = dimension_registry['topics']
        assert entry.sql_function.get('shape') == 'DIMENSION'
        assert entry.sql_function.get('mode') == 'mapping'

    def test_sentiment_dimension_registered(self, dimension_registry):
        """Verify sentiment dimension is registered."""
        assert 'sentiment' in dimension_registry, "sentiment dimension not found"
        entry = dimension_registry['sentiment']
        assert entry.sql_function.get('shape') == 'DIMENSION'

    def test_dimension_has_source_arg(self, dimension_registry):
        """Verify dimension functions have a dimension_source arg."""
        for name, entry in dimension_registry.items():
            args = entry.sql_function.get('args', [])
            source_args = [a for a in args if a.get('role') == 'dimension_source']
            assert len(source_args) == 1, f"{name} should have exactly one dimension_source arg"


# ============================================================================
# Argument Parsing Tests
# ============================================================================

class TestArgumentParsing:
    """Test function argument parsing."""

    def test_parse_simple_args(self, rewriter):
        """Test parsing simple arguments."""
        args = rewriter._parse_function_args("title, 8")
        assert args == ["title", "8"]

    def test_parse_quoted_string_args(self, rewriter):
        """Test parsing quoted string arguments."""
        args = rewriter._parse_function_args("observed, 'fear', 5")
        assert args == ["observed", "'fear'", "5"]

    def test_parse_double_quoted_args(self, rewriter):
        """Test parsing double-quoted arguments."""
        args = rewriter._parse_function_args('title, "custom focus", 3')
        assert args == ["title", '"custom focus"', "3"]

    def test_parse_nested_function_args(self, rewriter):
        """Test parsing with nested function call."""
        args = rewriter._parse_function_args("LOWER(title), 8")
        assert args == ["LOWER(title)", "8"]

    def test_parse_qualified_column(self, rewriter):
        """Test parsing table.column format."""
        args = rewriter._parse_function_args("t.title, 8")
        assert args == ["t.title", "8"]

    def test_parse_empty_args(self, rewriter):
        """Test parsing empty arguments."""
        args = rewriter._parse_function_args("")
        assert args == []

    def test_parse_single_arg(self, rewriter):
        """Test parsing single argument."""
        args = rewriter._parse_function_args("title")
        assert args == ["title"]


# ============================================================================
# Source Extraction Tests
# ============================================================================

class TestSourceExtraction:
    """Test FROM clause source extraction."""

    def test_extract_simple_table(self, rewriter):
        """Test extracting simple table name."""
        query = "SELECT * FROM bigfoot_vw WHERE x = 1"
        source = rewriter._extract_source(query)
        assert source == "bigfoot_vw"

    def test_extract_table_with_alias(self, rewriter):
        """Test extracting table with alias."""
        query = "SELECT * FROM bigfoot_vw bf WHERE x = 1"
        source = rewriter._extract_source(query)
        assert source == "bigfoot_vw"

    def test_extract_table_with_as_alias(self, rewriter):
        """Test extracting table with AS alias."""
        query = "SELECT * FROM bigfoot_vw AS bf WHERE x = 1"
        source = rewriter._extract_source(query)
        assert source == "bigfoot_vw"

    def test_extract_subquery(self, rewriter):
        """Test extracting subquery source."""
        query = "SELECT * FROM (SELECT * FROM t WHERE x > 10) sub WHERE y = 1"
        source = rewriter._extract_source(query)
        assert "(SELECT * FROM t WHERE x > 10)" in source


# ============================================================================
# WHERE Extraction Tests
# ============================================================================

class TestWhereExtraction:
    """Test WHERE clause extraction."""

    def test_extract_simple_where(self, rewriter):
        """Test extracting simple WHERE clause."""
        query = "SELECT * FROM t WHERE x = 1"
        where = rewriter._extract_where_clause(query)
        assert "WHERE x = 1" in where

    def test_extract_where_with_group_by(self, rewriter):
        """Test WHERE extraction stops at GROUP BY."""
        query = "SELECT * FROM t WHERE x = 1 GROUP BY y"
        where = rewriter._extract_where_clause(query)
        assert "WHERE x = 1" in where
        assert "GROUP BY" not in where

    def test_extract_where_with_order_by(self, rewriter):
        """Test WHERE extraction stops at ORDER BY."""
        query = "SELECT * FROM t WHERE x = 1 ORDER BY y"
        where = rewriter._extract_where_clause(query)
        assert "WHERE x = 1" in where
        assert "ORDER BY" not in where

    def test_no_where_clause(self, rewriter):
        """Test query without WHERE clause."""
        query = "SELECT * FROM t GROUP BY y"
        where = rewriter._extract_where_clause(query)
        assert where == ""

    def test_complex_where(self, rewriter):
        """Test complex WHERE clause."""
        query = "SELECT * FROM t WHERE x > 1 AND y = 'test' AND z IN (1,2,3) GROUP BY a"
        where = rewriter._extract_where_clause(query)
        assert "x > 1" in where
        assert "y = 'test'" in where


# ============================================================================
# Column Name Sanitization Tests
# ============================================================================

class TestColumnSanitization:
    """Test column name sanitization for identifiers."""

    def test_simple_column(self, rewriter):
        """Test simple column name."""
        assert rewriter._sanitize_col_name("title") == "title"

    def test_qualified_column(self, rewriter):
        """Test table.column format."""
        assert rewriter._sanitize_col_name("t.title") == "title"

    def test_special_chars(self, rewriter):
        """Test column with special characters."""
        assert rewriter._sanitize_col_name("my-column") == "my_column"

    def test_multi_qualified(self, rewriter):
        """Test schema.table.column format."""
        assert rewriter._sanitize_col_name("schema.table.col") == "col"


# ============================================================================
# Dimension Detection Tests
# ============================================================================

class TestDimensionDetection:
    """Test detection of dimension functions in queries."""

    def test_has_dimension_topics(self, rewriter, dimension_registry):
        """Test detection of topics dimension."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = "SELECT topics(title, 8) FROM t GROUP BY topics(title, 8)"
        assert rewriter.has_dimension_functions(query)

    def test_has_dimension_sentiment(self, rewriter, dimension_registry):
        """Test detection of sentiment dimension."""
        if 'sentiment' not in dimension_registry:
            pytest.skip("sentiment dimension not registered")

        query = "SELECT sentiment(observed) FROM t GROUP BY sentiment(observed)"
        assert rewriter.has_dimension_functions(query)

    def test_no_dimension_regular_sql(self, rewriter):
        """Test no false positives on regular SQL."""
        query = "SELECT COUNT(*) FROM t GROUP BY state"
        assert not rewriter.has_dimension_functions(query)

    def test_no_dimension_scalar_function(self, rewriter):
        """Test no false positives on scalar functions."""
        query = "SELECT UPPER(title) FROM t GROUP BY UPPER(title)"
        assert not rewriter.has_dimension_functions(query)


# ============================================================================
# CTE Generation Tests
# ============================================================================

class TestCTEGeneration:
    """Test CTE generation for dimension functions."""

    def test_basic_topics_rewrite(self, rewriter, dimension_registry):
        """Test basic topics rewrite generates CTEs."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = """
        SELECT topics(title, 8) as topic, COUNT(*)
        FROM bigfoot_vw
        GROUP BY topics(title, 8)
        """

        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed, "Query should have been rewritten"
        assert "WITH" in result.sql_out
        assert "_mapping" in result.sql_out
        assert "_dim_classified" in result.sql_out
        assert "topics_compute" in result.sql_out
        assert "to_json(LIST(title))" in result.sql_out

    def test_scalar_args_passed(self, rewriter, dimension_registry):
        """Test scalar arguments are passed to compute function."""
        if 'sentiment' not in dimension_registry:
            pytest.skip("sentiment dimension not registered")

        query = """
        SELECT sentiment(observed, 'fear') as fear_level, COUNT(*)
        FROM bigfoot_vw
        GROUP BY sentiment(observed, 'fear')
        """

        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        assert "'fear'" in result.sql_out
        assert "sentiment_compute" in result.sql_out

    def test_multiple_dimensions(self, rewriter, dimension_registry):
        """Test multiple dimension functions in same query."""
        if 'topics' not in dimension_registry or 'sentiment' not in dimension_registry:
            pytest.skip("topics or sentiment dimension not registered")

        query = """
        SELECT topics(title, 5) as topic, sentiment(observed) as mood, COUNT(*)
        FROM bigfoot_vw
        GROUP BY topics(title, 5), sentiment(observed)
        """

        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        assert "topics_compute" in result.sql_out
        assert "sentiment_compute" in result.sql_out
        # Should have 2 mapping CTEs + 1 classification CTE
        assert result.sql_out.count("_mapping AS") >= 2


# ============================================================================
# Query Rewrite Tests
# ============================================================================

class TestQueryRewrite:
    """Test full query rewriting."""

    def test_select_replaced(self, rewriter, dimension_registry):
        """Test dimension call in SELECT is replaced."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = "SELECT topics(title, 8) as topic FROM bigfoot_vw GROUP BY topics(title, 8)"
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        # Original function call should be gone
        assert "topics(title, 8)" not in result.sql_out.lower()
        # Replaced with dimension column reference
        assert "__dim_topics_" in result.sql_out

    def test_group_by_replaced(self, rewriter, dimension_registry):
        """Test dimension call in GROUP BY is replaced."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = "SELECT topics(title, 8), COUNT(*) FROM bigfoot_vw GROUP BY topics(title, 8)"
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        # GROUP BY should use dimension column
        assert re.search(r'GROUP BY\s+__dim_topics_', result.sql_out)

    def test_from_clause_replaced(self, rewriter, dimension_registry):
        """Test FROM clause is replaced with _dim_classified."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = "SELECT topics(title, 8) FROM bigfoot_vw GROUP BY topics(title, 8)"
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        assert "FROM _dim_classified" in result.sql_out

    def test_alias_preserved(self, rewriter, dimension_registry):
        """Test column alias is preserved."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = "SELECT topics(title, 8) AS incident_type FROM bigfoot_vw GROUP BY topics(title, 8)"
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        assert "AS incident_type" in result.sql_out or "as incident_type" in result.sql_out.lower()

    def test_where_propagated(self, rewriter, dimension_registry):
        """Test WHERE clause is propagated to CTEs."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = """
        SELECT topics(title, 8), COUNT(*)
        FROM bigfoot_vw
        WHERE year > 2000
        GROUP BY topics(title, 8)
        """
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        # WHERE should appear in extraction CTE
        assert result.sql_out.count("WHERE year > 2000") >= 1

    def test_order_by_preserved(self, rewriter, dimension_registry):
        """Test ORDER BY clause is preserved."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = """
        SELECT topics(title, 8), COUNT(*) as cnt
        FROM bigfoot_vw
        GROUP BY topics(title, 8)
        ORDER BY cnt DESC
        """
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        assert "ORDER BY cnt DESC" in result.sql_out

    def test_regular_columns_preserved(self, rewriter, dimension_registry):
        """Test regular columns in GROUP BY are preserved."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = """
        SELECT state, topics(title, 8), COUNT(*)
        FROM bigfoot_vw
        GROUP BY state, topics(title, 8)
        """
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        assert "state" in result.sql_out
        # state should still be in GROUP BY
        assert re.search(r'GROUP BY\s+state', result.sql_out)


# ============================================================================
# Expression Deduplication Tests
# ============================================================================

class TestExpressionDeduplication:
    """Test that identical expressions share CTEs."""

    def test_same_expr_same_id(self, rewriter, dimension_registry):
        """Test identical expressions get same ID."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = """
        SELECT topics(title, 8), COUNT(*)
        FROM bigfoot_vw
        GROUP BY topics(title, 8)
        """
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        # Should have exactly one mapping CTE for topics
        assert result.sql_out.count("topics_compute") == 1

    def test_different_args_different_ctes(self, rewriter, dimension_registry):
        """Test different arguments create different CTEs."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = """
        SELECT topics(title, 5), topics(title, 10), COUNT(*)
        FROM bigfoot_vw
        GROUP BY topics(title, 5), topics(title, 10)
        """
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        # Should have two mapping CTEs for different topic counts
        assert result.sql_out.count("topics_compute") == 2


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Test integration with main SQL rewriter."""

    def test_dimension_through_main_rewriter(self, dimension_registry):
        """Test dimension rewrite through main SQL rewriter."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

        query = """
        SELECT state, topics(title, 8) as topic, COUNT(*)
        FROM bigfoot_vw
        GROUP BY state, topics(title, 8)
        """

        result = rewrite_rvbbit_syntax(query)

        assert "WITH" in result
        assert "_dim_classified" in result
        assert "__dim_topics_" in result

    def test_dimension_with_semantic_operators(self, dimension_registry):
        """Test dimension functions work with other semantic operators."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        from rvbbit.sql_rewriter import rewrite_rvbbit_syntax

        query = """
        SELECT state, topics(title, 8) as topic, COUNT(*)
        FROM bigfoot_vw
        WHERE title MEANS 'visual sighting'
        GROUP BY state, topics(title, 8)
        """

        result = rewrite_rvbbit_syntax(query)

        # Should have dimension CTEs
        assert "_dim_classified" in result
        # Should also have MEANS rewritten to matches
        assert "matches" in result.lower() or "semantic_matches" in result.lower()


# ============================================================================
# Edge Case Tests
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_no_group_by(self, rewriter, dimension_registry):
        """Test dimension in SELECT without GROUP BY."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        # This is semantically weird but should still transform
        query = "SELECT topics(title, 8), title FROM bigfoot_vw LIMIT 10"
        result = rewriter.rewrite_dimension_functions(query)

        # Should still rewrite (bucket assignment per row)
        assert result.changed

    def test_dimension_only_in_select(self, rewriter, dimension_registry):
        """Test dimension only in SELECT, not in GROUP BY."""
        if 'topics' not in dimension_registry:
            pytest.skip("topics dimension not registered")

        query = "SELECT state, topics(title, 8) as topic FROM bigfoot_vw GROUP BY state"
        result = rewriter.rewrite_dimension_functions(query)

        assert result.changed
        assert "topics_compute" in result.sql_out

    def test_empty_query(self, rewriter):
        """Test empty query doesn't crash."""
        result = rewriter.rewrite_dimension_functions("")
        assert not result.changed

    def test_no_from_clause(self, rewriter):
        """Test query without FROM doesn't crash."""
        result = rewriter.rewrite_dimension_functions("SELECT 1")
        assert not result.changed


# ============================================================================
# Parametrized Rewrite Tests
# ============================================================================

# Generate test cases for all dimension functions
def get_dimension_test_cases():
    """Generate test cases for all registered dimension functions."""
    try:
        from rvbbit.semantic_sql.registry import initialize_registry, get_sql_function_registry
        initialize_registry(force=True)
        registry = get_sql_function_registry()

        cases = []
        for name, entry in registry.items():
            if entry.sql_function.get('shape', '').upper() != 'DIMENSION':
                continue

            args = entry.sql_function.get('args', [])

            # Basic case with required args only
            source_arg = next((a for a in args if a.get('role') == 'dimension_source'), args[0] if args else None)
            if source_arg:
                cases.append((
                    f"{name}_basic",
                    f"SELECT {name}(col) as bucket, COUNT(*) FROM test_table GROUP BY {name}(col)",
                    name
                ))

            # Case with optional args
            optional_args = [a for a in args if a.get('role') != 'dimension_source' and 'default' in a]
            if optional_args:
                arg_values = []
                for a in optional_args[:2]:  # First 2 optional args
                    if a['type'] == 'VARCHAR':
                        arg_values.append("'test_value'")
                    elif a['type'] == 'INTEGER':
                        arg_values.append("5")
                    elif a['type'] == 'BOOLEAN':
                        arg_values.append("true")

                if arg_values:
                    args_str = ", ".join(["col"] + arg_values)
                    cases.append((
                        f"{name}_with_args",
                        f"SELECT {name}({args_str}) as bucket, COUNT(*) FROM test_table GROUP BY {name}({args_str})",
                        name
                    ))

        return cases
    except Exception:
        return []


DIMENSION_TEST_CASES = get_dimension_test_cases()


@pytest.mark.parametrize("test_id,query,func_name", DIMENSION_TEST_CASES)
def test_dimension_function_rewrite(test_id, query, func_name):
    """Test that dimension function is correctly rewritten."""
    from rvbbit.sql_tools.dimension_rewriter import rewrite_dimension_functions

    result = rewrite_dimension_functions(query)

    assert result.changed, f"Query for {func_name} should be rewritten"
    assert "WITH" in result.sql_out, f"CTE should be generated for {func_name}"
    assert f"{func_name}_compute" in result.sql_out, f"Compute function should be called for {func_name}"
    assert "_dim_classified" in result.sql_out, f"Classification CTE should be generated for {func_name}"


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    # Print discovered dimension functions
    print("=" * 70)
    print("Dimension Rewriter Test Suite")
    print("=" * 70)

    try:
        from rvbbit.semantic_sql.registry import initialize_registry, get_sql_function_registry
        initialize_registry(force=True)
        registry = get_sql_function_registry()

        dimension_funcs = {
            name: entry for name, entry in registry.items()
            if entry.sql_function.get('shape', '').upper() == 'DIMENSION'
        }

        print(f"\nDiscovered {len(dimension_funcs)} dimension functions:")
        for name, entry in dimension_funcs.items():
            args = entry.sql_function.get('args', [])
            arg_names = [a['name'] for a in args]
            print(f"  - {name}({', '.join(arg_names)})")

        print(f"\nGenerated {len(DIMENSION_TEST_CASES)} parametrized test cases")

    except Exception as e:
        print(f"Could not load registry: {e}")

    print("\nRun with: pytest rvbbit/tests/test_dimension_rewriter.py -v")
