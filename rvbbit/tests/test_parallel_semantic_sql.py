"""
Tests for Parallel Semantic SQL Execution via UNION ALL Splitting.

Tests that -- @ parallel: N annotation correctly splits queries into
parallel UNION ALL branches for scalar operators, and safely disables
for aggregate operators.
"""

import pytest
from rvbbit.sql_rewriter import rewrite_rvbbit_syntax
from rvbbit.sql_tools.semantic_operators import (
    _parse_annotations,
    _has_aggregate_operators,
    _split_query_for_parallel
)


class TestAnnotationParsing:
    """Test parsing of parallel annotations."""

    def test_parallel_with_value(self):
        """Test -- @ parallel: 5"""
        query = "-- @ parallel: 5\nSELECT * FROM t"
        annotations = _parse_annotations(query)
        assert len(annotations) == 1
        assert annotations[0][2].parallel == 5

    def test_parallel_keyword_only(self):
        """Test -- @ parallel (defaults to CPU count)."""
        query = "-- @ parallel\nSELECT * FROM t"
        annotations = _parse_annotations(query)
        assert len(annotations) == 1
        # Should be CPU count (varies by machine, just check it's set)
        assert annotations[0][2].parallel is not None
        assert annotations[0][2].parallel >= 1

    def test_parallel_with_batch_size(self):
        """Test -- @ parallel: 10 with -- @ batch_size: 100."""
        query = "-- @ parallel: 10\n-- @ batch_size: 100\nSELECT * FROM t"
        annotations = _parse_annotations(query)
        assert len(annotations) == 1
        assert annotations[0][2].parallel == 10
        assert annotations[0][2].batch_size == 100

    def test_parallel_combined_with_other_annotations(self):
        """Test parallel combined with model and threshold."""
        query = "-- @ model: google/gemini-flash\n-- @ parallel: 8\n-- @ threshold: 0.7\nWHERE x"
        annotations = _parse_annotations(query)
        assert len(annotations) == 1
        ann = annotations[0][2]
        assert ann.parallel == 8
        assert ann.model == "google/gemini-flash"
        assert ann.threshold == 0.7


class TestAggregateDetection:
    """Test detection of aggregate operators."""

    def test_detects_summarize(self):
        """Should detect SUMMARIZE aggregate."""
        assert _has_aggregate_operators("SELECT SUMMARIZE(text) FROM t GROUP BY x")
        assert _has_aggregate_operators("SELECT state, SUMMARIZE(observed) FROM t GROUP BY state")

    def test_detects_themes(self):
        """Should detect THEMES/TOPICS aggregates."""
        assert _has_aggregate_operators("SELECT THEMES(text, 3) FROM t GROUP BY category")
        assert _has_aggregate_operators("SELECT TOPICS(comments) FROM t GROUP BY topic")

    def test_detects_cluster(self):
        """Should detect CLUSTER aggregate."""
        assert _has_aggregate_operators("SELECT CLUSTER(category, 5) FROM t")
        assert _has_aggregate_operators("GROUP BY MEANING(col)")

    def test_detects_consensus(self):
        """Should detect CONSENSUS aggregate."""
        assert _has_aggregate_operators("SELECT CONSENSUS(texts) FROM t")

    def test_detects_rewritten_aggregates(self):
        """Should detect rewritten aggregate function names."""
        assert _has_aggregate_operators("SELECT llm_summarize_1(LIST(text))")
        assert _has_aggregate_operators("SELECT llm_themes_2(LIST(text), 3)")

    def test_ignores_scalar_operators(self):
        """Should NOT detect scalar operators as aggregates."""
        assert not _has_aggregate_operators("SELECT * FROM t WHERE col MEANS 'x'")
        assert not _has_aggregate_operators("SELECT col EXTRACTS 'name' FROM t")
        assert not _has_aggregate_operators("SELECT CONDENSE(text) FROM t")
        assert not _has_aggregate_operators("WHERE col ASK 'question'")


class TestQuerySplitting:
    """Test UNION ALL query splitting logic."""

    def test_simple_where_clause(self):
        """Test splitting simple WHERE query."""
        query = "SELECT * FROM products WHERE price < 100 LIMIT 100"
        result = _split_query_for_parallel(query, parallel_count=5)

        # Should have 5 UNION ALL branches
        assert result.count('UNION ALL') == 4  # 4 unions = 5 branches

        # Should have mod filters (using hash for type safety)
        for i in range(5):
            assert f'hash(id) % 5 = {i}' in result

        # Should have distributed LIMIT (100 / 5 = 20 per branch)
        assert result.count('LIMIT 20') == 5

    def test_no_where_clause(self):
        """Test splitting query without WHERE."""
        query = "SELECT * FROM articles LIMIT 60"
        result = _split_query_for_parallel(query, parallel_count=3)

        # Should add WHERE clause (using hash for type safety)
        for i in range(3):
            assert f'WHERE hash(id) % 3 = {i}' in result

        # Should have distributed LIMIT (60 / 3 = 20 per branch)
        assert result.count('LIMIT 20') == 3

    def test_preserves_order_by(self):
        """Test that ORDER BY is preserved at outer level."""
        query = "SELECT * FROM docs WHERE active = true ORDER BY created_at LIMIT 100"
        result = _split_query_for_parallel(query, parallel_count=4)

        # Should have ORDER BY at outer SELECT level
        assert 'ORDER BY created_at' in result

        # Inner branches should NOT have ORDER BY
        first_branch = result.split('UNION ALL')[0]
        assert 'ORDER BY' not in first_branch

    def test_batch_size_enforcement(self):
        """Test that batch_size caps total LIMIT."""
        query = "SELECT * FROM huge_table LIMIT 10000"
        result = _split_query_for_parallel(query, parallel_count=5, batch_size=500)

        # Should cap at batch_size (500 / 5 = 100 per branch)
        assert result.count('LIMIT 100') == 5


class TestEndToEndParallel:
    """Test end-to-end parallel execution with semantic operators."""

    def test_means_operator_with_parallel(self):
        """Test MEANS operator splits correctly."""
        query = "-- @ parallel: 3\nSELECT * FROM t WHERE col MEANS 'pattern' LIMIT 90"
        result = rewrite_rvbbit_syntax(query)

        # Should split into 3 branches
        assert result.count('UNION ALL') == 2

        # Should have rewritten MEANS → matches()
        assert 'matches(' in result
        assert "'pattern'" in result

        # Should have mod filters (using hash for type safety)
        assert 'hash(id) % 3 = 0' in result
        assert 'hash(id) % 3 = 1' in result
        assert 'hash(id) % 3 = 2' in result

    def test_multiple_operators_parallel(self):
        """Test multiple scalar operators in parallel query."""
        query = """-- @ parallel: 4
SELECT
  id,
  description MEANS 'eco' as eco,
  description EXTRACTS 'price' as price,
  CONDENSE(description) as summary
FROM products
LIMIT 100
"""
        result = rewrite_rvbbit_syntax(query)

        # Should split
        assert result.count('UNION ALL') == 3  # 4 branches

        # Infix operators should be rewritten
        assert 'matches(' in result  # MEANS → matches()
        assert 'semantic_extract(' in result  # EXTRACTS → semantic_extract()

        # Function operators stay as-is (already valid UDF calls)
        assert 'CONDENSE(' in result  # CONDENSE() is a UDF, not rewritten

    def test_aggregate_disables_parallel(self):
        """Test that aggregates disable parallel execution."""
        query = "-- @ parallel: 5\nSELECT state, SUMMARIZE(text) FROM t GROUP BY state"
        result = rewrite_rvbbit_syntax(query)

        # Should NOT split (aggregates unsafe)
        assert 'UNION ALL' not in result

        # Should still rewrite aggregate
        assert 'llm_summarize' in result

    def test_parallel_with_about_operator(self):
        """Test ABOUT operator with parallel."""
        query = "-- @ parallel: 4\nSELECT * FROM docs WHERE content ABOUT 'AI' > 0.7 LIMIT 80"
        result = rewrite_rvbbit_syntax(query)

        # Should split
        assert result.count('UNION ALL') == 3

        # ABOUT should be rewritten
        assert 'score(' in result or 'semantic_score(' in result
        assert '0.7' in result

    def test_parallel_with_ask_operator(self):
        """Test ASK operator with parallel."""
        query = "-- @ parallel: 3\nSELECT review ASK 'sentiment?' as mood FROM reviews LIMIT 60"
        result = rewrite_rvbbit_syntax(query)

        # Should split
        assert result.count('UNION ALL') == 2

        # ASK should be rewritten
        assert 'semantic_ask(' in result

    def test_no_parallel_annotation_unchanged(self):
        """Test that queries without parallel annotation are unchanged."""
        query = "SELECT * FROM t WHERE col MEANS 'pattern' LIMIT 100"
        result = rewrite_rvbbit_syntax(query)

        # Should NOT split
        assert 'UNION ALL' not in result

        # Should still rewrite operator
        assert 'matches(' in result


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_parallel_one_is_noop(self):
        """Test that parallel: 1 doesn't split (pointless)."""
        query = "-- @ parallel: 1\nSELECT * FROM t WHERE x MEANS 'y' LIMIT 10"
        result = rewrite_rvbbit_syntax(query)

        # Should not split (only 1 branch is pointless)
        assert 'UNION ALL' not in result

    def test_complex_where_clause(self):
        """Test splitting with complex WHERE clause."""
        query = """-- @ parallel: 3
SELECT * FROM t
WHERE price < 100
  AND category = 'electronics'
  AND description MEANS 'eco-friendly'
LIMIT 90
"""
        result = rewrite_rvbbit_syntax(query)

        # Should split
        assert result.count('UNION ALL') == 2

        # Should preserve all WHERE conditions
        assert 'price < 100' in result
        assert "category = 'electronics'" in result
        assert 'matches(' in result  # MEANS rewritten

    def test_preserves_select_columns(self):
        """Test that SELECT column list is preserved."""
        query = "-- @ parallel: 2\nSELECT id, name, CONDENSE(desc) as summary FROM t LIMIT 20"
        result = rewrite_rvbbit_syntax(query)

        # Should preserve columns in both branches
        assert result.count('id, name') == 2  # Once per branch
        # CONDENSE is a function operator - stays as CONDENSE() (registered UDF)
        assert 'CONDENSE(desc)' in result

    def test_handles_varchar_id_column(self):
        """Test that hash(id) works with VARCHAR id columns."""
        query = "-- @ parallel: 3\nSELECT id, text FROM tweets WHERE text MEANS 'x' LIMIT 30"
        result = _split_query_for_parallel(query, parallel_count=3)

        # Should use hash(id) not id (works for VARCHAR, UUID, any type)
        for i in range(3):
            assert f'hash(id) % 3 = {i}' in result

        # Should NOT have bare 'id %' (would fail on VARCHAR)
        # Count occurrences - should only appear with hash()
        import re
        bare_id_mod = re.findall(r'(?<!hash\()id\s*%', result)
        assert len(bare_id_mod) == 0, f"Found bare 'id %' (should use hash): {bare_id_mod}"

    def test_subquery_from_clause(self):
        """Test splitting with subquery in FROM clause."""
        query = "-- @ parallel: 2\nSELECT id, text FROM (SELECT * FROM tweets LIMIT 10) WHERE text MEANS 'x'"
        result = _split_query_for_parallel(query, parallel_count=2)

        # Should still add hash(id) % N filter
        assert 'hash(id) % 2 = 0' in result
        assert 'hash(id) % 2 = 1' in result


if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, '-v'])
