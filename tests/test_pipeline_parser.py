"""
Tests for the pipeline parser.

Verifies parsing of THEN/INTO syntax for post-query processing.
"""

from lars.sql_tools.pipeline_parser import (
    has_pipeline_syntax,
    parse_pipeline_syntax,
)


class TestHasPipelineSyntax:
    """Test the quick-check function for pipeline syntax."""

    def test_simple_then(self):
        sql = "SELECT * FROM products THEN ANALYZE 'trends'"
        assert has_pipeline_syntax(sql) is True

    def test_no_then(self):
        sql = "SELECT * FROM products WHERE category = 'electronics'"
        assert has_pipeline_syntax(sql) is False

    def test_then_in_string(self):
        """THEN inside a string should not trigger pipeline syntax."""
        sql = "SELECT * FROM products WHERE name = 'THEN something'"
        assert has_pipeline_syntax(sql) is False

    def test_then_in_comment(self):
        """THEN inside a comment should not trigger pipeline syntax."""
        sql = "SELECT * FROM products -- THEN ANALYZE"
        assert has_pipeline_syntax(sql) is False

    def test_case_insensitive(self):
        sql = "SELECT * FROM products then analyze 'test'"
        assert has_pipeline_syntax(sql) is True


class TestParsePipelineSyntax:
    """Test full pipeline parsing."""

    def test_single_stage_infix(self):
        """Test infix style: THEN STAGE 'arg'"""
        sql = "SELECT * FROM products THEN ANALYZE 'what are the trends?'"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.base_sql == "SELECT * FROM products"
        assert len(result.stages) == 1
        assert result.stages[0].name == "ANALYZE"
        assert result.stages[0].args == ["what are the trends?"]
        assert result.into_table is None

    def test_single_stage_function(self):
        """Test function style: THEN STAGE('arg')"""
        sql = "SELECT * FROM products THEN ANALYZE('what are the trends?')"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.base_sql == "SELECT * FROM products"
        assert len(result.stages) == 1
        assert result.stages[0].name == "ANALYZE"
        assert result.stages[0].args == ["what are the trends?"]

    def test_multiple_function_args(self):
        """Test function style with multiple args."""
        sql = "SELECT * FROM products THEN FILTER('eco-friendly', 'strict')"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert len(result.stages) == 1
        assert result.stages[0].args == ["eco-friendly", "strict"]

    def test_no_args(self):
        """Test stage with no arguments."""
        sql = "SELECT * FROM products THEN SPEAK"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert len(result.stages) == 1
        assert result.stages[0].name == "SPEAK"
        assert result.stages[0].args == []

    def test_multiple_stages(self):
        """Test multiple chained stages."""
        sql = """
        SELECT * FROM sales
        THEN ANALYZE 'trends?'
        THEN SPEAK
        """
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert len(result.stages) == 2
        assert result.stages[0].name == "ANALYZE"
        assert result.stages[0].args == ["trends?"]
        assert result.stages[1].name == "SPEAK"
        assert result.stages[1].args == []

    def test_into_table(self):
        """Test INTO clause for saving results."""
        sql = "SELECT * FROM products THEN ANALYZE 'trends' INTO analysis_results"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.base_sql == "SELECT * FROM products"
        assert len(result.stages) == 1
        assert result.into_table == "analysis_results"

    def test_multiple_stages_with_into(self):
        """Test multiple stages ending with INTO."""
        sql = """
        SELECT * FROM sales
        THEN ANALYZE 'what sells best?'
        THEN ENRICH 'add recommendations'
        INTO quarterly_analysis
        """
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert len(result.stages) == 2
        assert result.stages[0].name == "ANALYZE"
        assert result.stages[1].name == "ENRICH"
        assert result.into_table == "quarterly_analysis"

    def test_complex_base_sql(self):
        """Test with complex base SQL including WHERE, JOIN, etc."""
        sql = """
        SELECT p.*, c.name as category_name
        FROM products p
        JOIN categories c ON p.category_id = c.id
        WHERE p.price > 100
        ORDER BY p.price DESC
        LIMIT 50
        THEN ANALYZE 'which products perform best?'
        """
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert "JOIN categories" in result.base_sql
        assert "WHERE p.price > 100" in result.base_sql
        assert "LIMIT 50" in result.base_sql
        assert len(result.stages) == 1

    def test_then_in_string_preserved(self):
        """THEN inside a string in base SQL should be preserved."""
        sql = "SELECT * FROM products WHERE name LIKE '%THEN%' THEN ANALYZE 'test'"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert "LIKE '%THEN%'" in result.base_sql
        assert len(result.stages) == 1

    def test_semicolon_handling(self):
        """Test that trailing semicolons are handled correctly."""
        sql = "SELECT * FROM products THEN ANALYZE 'test';"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.base_sql == "SELECT * FROM products"
        assert len(result.stages) == 1

    def test_no_pipeline_returns_none(self):
        """Test that queries without THEN return None."""
        sql = "SELECT * FROM products WHERE category = 'electronics'"
        result = parse_pipeline_syntax(sql)

        assert result is None

    def test_escaped_quotes_in_args(self):
        """Test that escaped quotes in arguments are handled."""
        sql = "SELECT * FROM products THEN ANALYZE 'what''s the trend?'"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.stages[0].args == ["what's the trend?"]


class TestEdgeCases:
    """Test edge cases and potential issues."""

    def test_newlines_in_query(self):
        """Test multi-line queries."""
        sql = """SELECT *
FROM products
WHERE active = true
THEN ANALYZE 'summarize'
INTO summary"""
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert "WHERE active = true" in result.base_sql
        assert result.into_table == "summary"

    def test_comments_in_base_sql(self):
        """Test that comments in base SQL are preserved."""
        sql = """
        SELECT * FROM products -- get all products
        /* multi-line
           comment */
        WHERE active = true
        THEN ANALYZE 'test'
        """
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert "-- get all products" in result.base_sql

    def test_subquery_with_then(self):
        """Test that THEN in subquery doesn't interfere."""
        # This is a tricky case - THEN in a CASE statement inside subquery
        sql = """
        SELECT * FROM (
            SELECT id, CASE WHEN status = 1 THEN 'active' ELSE 'inactive' END as status_text
            FROM items
        ) subq
        THEN ANALYZE 'summarize statuses'
        """
        result = parse_pipeline_syntax(sql)

        # The THEN in CASE should not split the query
        # (paren depth tracking should handle this)
        assert result is not None
        assert "CASE WHEN" in result.base_sql
        assert len(result.stages) == 1
        assert result.stages[0].name == "ANALYZE"


class TestPerStageInto:
    """Test per-stage INTO clause parsing."""

    def test_base_into_before_then(self):
        """Test INTO after base SQL, before first THEN."""
        sql = "SELECT * FROM sales INTO base_data THEN FILTER('above average')"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.base_sql == "SELECT * FROM sales"
        assert result.base_into_table == "base_data"
        assert len(result.stages) == 1
        assert result.stages[0].name == "FILTER"

    def test_stage_into_after_args(self):
        """Test INTO after a stage's arguments."""
        sql = "SELECT * FROM sales THEN FILTER('above average') INTO filtered_data"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.base_into_table is None
        assert len(result.stages) == 1
        assert result.stages[0].name == "FILTER"
        assert result.stages[0].into_table == "filtered_data"

    def test_multiple_stage_intos(self):
        """Test INTO for each stage in a pipeline."""
        sql = """
        SELECT * FROM sales INTO base_data
        THEN FILTER('above average') INTO filtered_data
        THEN ANALYZE 'summarize' INTO final_analysis
        """
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.base_sql == "SELECT * FROM sales"
        assert result.base_into_table == "base_data"
        assert len(result.stages) == 2

        assert result.stages[0].name == "FILTER"
        assert result.stages[0].into_table == "filtered_data"

        assert result.stages[1].name == "ANALYZE"
        assert result.stages[1].into_table == "final_analysis"

    def test_mixed_into_some_stages(self):
        """Test that not all stages need INTO."""
        sql = """
        SELECT * FROM sales
        THEN FILTER('above average')
        THEN ENRICH('add metadata') INTO enriched_data
        THEN ANALYZE 'summarize'
        """
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.base_into_table is None
        assert len(result.stages) == 3

        assert result.stages[0].into_table is None
        assert result.stages[1].into_table == "enriched_data"
        assert result.stages[2].into_table is None

    def test_base_into_with_final_into(self):
        """Test base INTO combined with final stage INTO."""
        sql = "SELECT * FROM sales INTO raw_data THEN ANALYZE 'summarize' INTO final_result"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert result.base_into_table == "raw_data"
        assert len(result.stages) == 1
        assert result.stages[0].into_table == "final_result"
        # into_table should point to last stage's INTO for backwards compat
        assert result.into_table == "final_result"

    def test_function_style_with_into(self):
        """Test function-style args with INTO."""
        sql = "SELECT * FROM logs THEN FILTER('error', 'critical') INTO error_logs"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert len(result.stages) == 1
        assert result.stages[0].args == ["error", "critical"]
        assert result.stages[0].into_table == "error_logs"

    def test_no_args_stage_with_into(self):
        """Test stage without args followed by INTO."""
        sql = "SELECT * FROM products THEN DEDUPE INTO unique_products"
        result = parse_pipeline_syntax(sql)

        assert result is not None
        assert len(result.stages) == 1
        assert result.stages[0].name == "DEDUPE"
        assert result.stages[0].args == []
        assert result.stages[0].into_table == "unique_products"
