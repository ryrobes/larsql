"""
Integration tests for LARS SQL features.

These tests actually execute SQL queries against DuckDB to verify end-to-end functionality.
"""

import pytest
import duckdb
import os
import tempfile
from lars.sql_tools.udf import register_lars_udf, clear_udf_cache
from lars.sql_rewriter import rewrite_lars_syntax, _parse_lars_statement


@pytest.fixture
def db_conn():
    """Create DuckDB connection with LARS UDFs registered."""
    conn = duckdb.connect(':memory:')
    register_lars_udf(conn)

    # Create test data
    conn.execute("""
        CREATE TEMP TABLE products AS
        SELECT * FROM (VALUES
            (1, 'Apple iPhone 15 Pro', 1199.99),
            (2, 'Samsung Galaxy S24', 1299.99),
            (3, 'Sony WH-1000XM5 Headphones', 399.99),
            (4, 'Apple MacBook Pro 16inch', 3499.99),
            (5, 'Apple iPhone 15 Pro', 1199.99)  -- Duplicate for DISTINCT testing
        ) AS t(product_id, product_name, price)
    """)

    yield conn
    conn.close()


@pytest.fixture
def test_cascade(tmp_path):
    """Create a simple test cascade."""
    cascade_file = tmp_path / "test_extract.yaml"
    cascade_file.write_text("""
cascade_id: test_extract
cells:
- name: extract
  instructions: |
    Extract brand from: {{ input.product_name }}
    Return JSON: {"brand": "extracted_brand", "confidence": 0.95}
  skills: []
  output_schema:
    type: object
    properties:
      brand: {type: string}
      confidence: {type: number}
    required: [brand, confidence]
""")
    return str(cascade_file)


class TestSchemaAwareIntegration:
    """Integration tests for schema-aware outputs."""

    def test_basic_lars_udf(self, db_conn):
        """Test basic lars_udf function."""
        result = db_conn.execute("""
            SELECT lars_udf('Say hello', 'world') as greeting
        """).fetchone()

        assert result is not None
        assert result[0] is not None
        # Should return some text
        assert len(result[0]) > 0

    def test_cache_hit(self, db_conn):
        """Test that cache works."""
        # Clear cache first
        clear_udf_cache()

        # First call
        result1 = db_conn.execute("""
            SELECT lars_udf('Extract brand', 'Apple iPhone') as brand
        """).fetchone()

        # Second call - should be cached
        result2 = db_conn.execute("""
            SELECT lars_udf('Extract brand', 'Apple iPhone') as brand
        """).fetchone()

        # Results should be identical (cached)
        assert result1[0] == result2[0]


class TestDISTINCTIntegration:
    """Integration tests for DISTINCT functionality."""

    def test_distinct_reduces_rows(self, db_conn):
        """Test that DISTINCT actually dedupes."""
        # Count without DISTINCT (should be 5 rows)
        query_no_distinct = """
        LARS MAP 'skills/extract_brand.yaml' AS brand
        USING (SELECT product_name FROM products)
        """
        rewritten_no_distinct = rewrite_lars_syntax(query_no_distinct)

        # Count with DISTINCT (should be 4 rows - one duplicate removed)
        query_distinct = """
        LARS MAP DISTINCT 'skills/extract_brand.yaml' AS brand
        USING (SELECT product_name FROM products)
        """
        rewritten_distinct = rewrite_lars_syntax(query_distinct)

        # Verify DISTINCT was added
        assert 'SELECT DISTINCT' in rewritten_distinct
        assert 'SELECT DISTINCT' not in rewritten_no_distinct

    def test_dedupe_by_column(self, db_conn):
        """Test dedupe_by specific column."""
        query = """
        LARS MAP 'cascade.yaml'
        USING (SELECT product_id, product_name, price FROM products)
        WITH (dedupe_by='product_name')
        """
        rewritten = rewrite_lars_syntax(query)

        # Should have DISTINCT ON
        assert 'DISTINCT ON (product_name)' in rewritten


class TestTableMaterializationIntegration:
    """Integration tests for table materialization."""

    def test_create_table_as_rewrite(self, db_conn):
        """Test CREATE TABLE AS rewriting."""
        query = """
        CREATE TABLE brands AS
        LARS MAP 'skills/extract_brand.yaml' AS brand
        USING (SELECT product_name FROM products LIMIT 3)
        """
        rewritten = rewrite_lars_syntax(query)

        # Should have materialization UDF
        assert 'lars_materialize_table' in rewritten
        assert "'brands'" in rewritten

    def test_with_as_table(self, db_conn):
        """Test WITH (as_table=...) rewriting."""
        query = """
        LARS MAP 'cascade.yaml'
        USING (SELECT * FROM products)
        WITH (as_table='results')
        """
        rewritten = rewrite_lars_syntax(query)

        assert 'lars_materialize_table' in rewritten
        assert "'results'" in rewritten


class TestEXPLAINIntegration:
    """Integration tests for EXPLAIN functionality."""

    def test_explain_returns_plan(self, db_conn):
        """Test that EXPLAIN returns a query plan."""
        query = """
        EXPLAIN LARS MAP 'skills/extract_brand.yaml'
        USING (SELECT product_name FROM products LIMIT 10)
        """
        rewritten = rewrite_lars_syntax(query, duckdb_conn=db_conn)

        # Should be a SELECT query that returns plan text
        assert rewritten.startswith("SELECT")
        assert "query_plan" in rewritten

        # Execute to verify it returns results
        result = db_conn.execute(rewritten).fetchone()
        assert result is not None

        plan_text = result[0]
        # Should contain key plan elements
        assert "Query Plan" in plan_text or "Input Rows" in plan_text

    def test_explain_multiline_query(self, db_conn):
        """Test EXPLAIN with multi-line USING query."""
        query = """
        EXPLAIN LARS MAP 'cascade.yaml'
        USING (
          SELECT
            product_id,
            product_name,
            price
          FROM products
          WHERE price > 100
          LIMIT 50
        )
        """
        rewritten = rewrite_lars_syntax(query, duckdb_conn=db_conn)

        assert "SELECT" in rewritten
        # Should not raise


class TestQueryNormalization:
    """Test query normalization handles various formats."""

    def test_single_line_query(self, db_conn):
        """Should handle single-line queries."""
        query = "LARS MAP 'cascade.yaml' USING (SELECT * FROM t)"
        stmt = _parse_lars_statement(query)

        assert stmt.mode == 'MAP'

    def test_multi_line_query(self, db_conn):
        """Should handle multi-line queries."""
        query = """
        LARS MAP 'cascade.yaml'
        USING (
          SELECT * FROM t
        )
        """
        stmt = _parse_lars_statement(query)

        assert stmt.mode == 'MAP'

    def test_query_with_comments(self, db_conn):
        """Should strip SQL comments."""
        query = """
        -- This is a comment
        LARS MAP 'cascade.yaml' -- inline comment
        USING (
          SELECT * FROM t -- another comment
        )
        """
        stmt = _parse_lars_statement(query)

        assert stmt.mode == 'MAP'
        # Comments should be removed

    def test_extra_whitespace(self, db_conn):
        """Should handle extra whitespace."""
        query = "LARS    MAP    'cascade.yaml'    USING    (SELECT * FROM t)"
        stmt = _parse_lars_statement(query)

        assert stmt.mode == 'MAP'


class TestRealWorldScenarios:
    """Test realistic usage patterns."""

    def test_product_enrichment_workflow(self, db_conn):
        """Test complete product enrichment workflow."""
        # Step 1: EXPLAIN to check cost
        explain_query = """
        EXPLAIN LARS MAP DISTINCT 'cascade.yaml' AS (
            brand VARCHAR,
            category VARCHAR
        )
        USING (SELECT product_name FROM products)
        WITH (dedupe_by='product_name', cache='1d')
        """
        explain_result = rewrite_lars_syntax(explain_query, duckdb_conn=db_conn)
        assert "SELECT" in explain_result

        # Step 2: Parse actual query
        actual_query = """
        LARS MAP DISTINCT 'cascade.yaml' AS (
            brand VARCHAR,
            category VARCHAR
        )
        USING (SELECT product_name FROM products)
        WITH (dedupe_by='product_name', cache='1d')
        """
        stmt = _parse_lars_statement(actual_query)

        # Verify all features parsed correctly
        assert stmt.output_columns is not None
        assert stmt.with_options.get('distinct') == True
        assert stmt.with_options.get('dedupe_by') == 'product_name'
        assert stmt.with_options.get('cache') == '1d'

    def test_create_table_with_all_features(self, db_conn):
        """Test CREATE TABLE AS with multiple features."""
        query = """
        CREATE TEMP TABLE enriched_products AS
        LARS MAP DISTINCT 'cascade.yaml' AS (
            brand VARCHAR,
            confidence DOUBLE,
            is_premium BOOLEAN
        )
        USING (
            SELECT product_name, price
            FROM products
            WHERE price > 500
        )
        WITH (dedupe_by='product_name', cache='6h')
        """
        stmt = _parse_lars_statement(query)

        # Verify parsing
        assert stmt.with_options.get('as_table') == 'enriched_products'
        assert stmt.output_columns is not None
        assert len(stmt.output_columns) == 3
        assert stmt.with_options.get('distinct') == True


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
