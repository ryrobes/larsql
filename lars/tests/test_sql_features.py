"""
Tests for LARS SQL enhancements.

Features tested:
1. Schema-aware outputs (AS (col TYPE, ...))
2. EXPLAIN LARS MAP
3. MAP DISTINCT
4. Cache TTL
5. Table materialization (CREATE TABLE AS)
"""

import pytest
import duckdb
import time
from lars.sql_rewriter import (
    rewrite_lars_syntax,
    _parse_lars_statement,
    _parse_output_schema,
    _json_schema_to_sql_types,
    LARSSyntaxError
)
from lars.sql_tools.udf import (
    _parse_duration,
    _cache_get,
    _cache_set,
    _udf_cache,
    clear_udf_cache
)


class TestSchemaAwareOutputs:
    """Test schema-aware output parsing and generation."""

    def test_parse_explicit_schema(self):
        """Should parse AS (col TYPE, col TYPE) syntax."""
        query = """
        LARS MAP 'cascade.yaml' AS (
            brand VARCHAR,
            confidence DOUBLE,
            is_luxury BOOLEAN
        )
        USING (SELECT * FROM products)
        """
        stmt = _parse_lars_statement(query)

        assert stmt.output_columns is not None
        assert len(stmt.output_columns) == 3
        assert stmt.output_columns[0] == ('brand', 'VARCHAR')
        assert stmt.output_columns[1] == ('confidence', 'DOUBLE')
        assert stmt.output_columns[2] == ('is_luxury', 'BOOLEAN')

    def test_parse_infer_schema(self):
        """Should set infer_schema flag in WITH options."""
        query = """
        LARS MAP 'cascade.yaml'
        USING (SELECT * FROM t)
        WITH (infer_schema = true)
        """
        stmt = _parse_lars_statement(query)

        assert stmt.with_options.get('infer_schema') == True

    def test_json_schema_to_sql_types(self):
        """Should convert JSON Schema types to SQL types."""
        json_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "score": {"type": "number"},
                "active": {"type": "boolean"},
                "tags": {"type": "array"},
                "metadata": {"type": "object"}
            }
        }

        columns = _json_schema_to_sql_types(json_schema)

        assert len(columns) == 6
        assert ('name', 'VARCHAR') in columns
        assert ('age', 'BIGINT') in columns
        assert ('score', 'DOUBLE') in columns
        assert ('active', 'BOOLEAN') in columns
        assert ('tags', 'JSON') in columns
        assert ('metadata', 'JSON') in columns

    def test_parse_output_schema_types(self):
        """Should validate SQL type names."""
        # Valid types
        schema = "brand VARCHAR, count INTEGER, price DOUBLE, active BOOLEAN"
        columns = _parse_output_schema(schema)
        assert len(columns) == 4

        # Invalid type should raise
        with pytest.raises(LARSSyntaxError):
            _parse_output_schema("field INVALID_TYPE")

    def test_schema_in_rewritten_query(self):
        """Should generate typed extraction SQL."""
        query = """
        LARS MAP 'test.yaml' AS (brand VARCHAR, score DOUBLE)
        USING (SELECT * FROM t LIMIT 10)
        """
        rewritten = rewrite_lars_syntax(query)

        # Should have typed extraction
        assert "json_extract_string(_raw_result, '$.state.validated_output.brand')" in rewritten
        assert "CAST(json_extract(_raw_result, '$.state.validated_output.score') AS DOUBLE)" in rewritten
        assert "AS brand" in rewritten
        assert "AS score" in rewritten


class TestEXPLAIN:
    """Test EXPLAIN LARS MAP functionality."""

    def test_explain_detection(self):
        """Should detect EXPLAIN prefix."""
        query = "EXPLAIN LARS MAP 'cascade.yaml' USING (SELECT * FROM t)"

        # Without conn, should return error
        result = rewrite_lars_syntax(query, duckdb_conn=None)
        assert "ERROR" in result
        assert "requires database connection" in result

    def test_explain_multiline(self):
        """Should handle multi-line EXPLAIN queries."""
        query = """
        EXPLAIN LARS MAP 'cascade.yaml'
        USING (
          SELECT * FROM products LIMIT 100
        )
        """
        # Should not raise parse error
        result = rewrite_lars_syntax(query, duckdb_conn=None)
        assert "ERROR" in result or "SELECT" in result

    def test_explain_works_for_run(self):
        """EXPLAIN should work for both MAP and RUN."""
        query = "EXPLAIN LARS RUN 'cascade.yaml' USING (SELECT * FROM t)"
        result = rewrite_lars_syntax(query, duckdb_conn=duckdb.connect())
        # Should return a query plan, not raise an error
        assert "query_plan" in result or "Query Plan" in result


class TestMAPDISTINCT:
    """Test MAP DISTINCT deduplication."""

    def test_parse_distinct_keyword(self):
        """Should parse DISTINCT keyword."""
        query = "LARS MAP DISTINCT 'cascade.yaml' USING (SELECT * FROM t)"
        stmt = _parse_lars_statement(query)

        assert stmt.with_options.get('distinct') == True

    def test_parse_dedupe_by(self):
        """Should parse dedupe_by option."""
        query = """
        LARS MAP 'cascade.yaml'
        USING (SELECT * FROM t)
        WITH (dedupe_by='product_name')
        """
        stmt = _parse_lars_statement(query)

        assert stmt.with_options.get('dedupe_by') == 'product_name'

    def test_distinct_rewrite(self):
        """Should wrap USING query with DISTINCT."""
        query = "LARS MAP DISTINCT 'test.yaml' USING (SELECT name FROM t)"
        rewritten = rewrite_lars_syntax(query)

        assert "SELECT DISTINCT * FROM" in rewritten

    def test_dedupe_by_rewrite(self):
        """Should wrap USING query with DISTINCT ON."""
        query = """
        LARS MAP 'test.yaml'
        USING (SELECT * FROM t)
        WITH (dedupe_by='name')
        """
        rewritten = rewrite_lars_syntax(query)

        assert "DISTINCT ON (name)" in rewritten


class TestCacheTTL:
    """Test cache TTL functionality."""

    def test_parse_duration_seconds(self):
        """Should parse second durations."""
        assert _parse_duration('60s') == 60
        assert _parse_duration('120s') == 120

    def test_parse_duration_minutes(self):
        """Should parse minute durations."""
        assert _parse_duration('1m') == 60
        assert _parse_duration('30m') == 1800

    def test_parse_duration_hours(self):
        """Should parse hour durations."""
        assert _parse_duration('1h') == 3600
        assert _parse_duration('2h') == 7200

    def test_parse_duration_days(self):
        """Should parse day durations."""
        assert _parse_duration('1d') == 86400
        assert _parse_duration('7d') == 604800

    def test_parse_duration_raw_number(self):
        """Should accept raw seconds as int/float."""
        assert _parse_duration(3600) == 3600.0
        assert _parse_duration(1800.5) == 1800.5

    def test_parse_duration_invalid(self):
        """Should raise on invalid format."""
        with pytest.raises(ValueError):
            _parse_duration('invalid')
        with pytest.raises(ValueError):
            _parse_duration('1x')

    def test_cache_ttl_expiry(self):
        """Should expire cached values after TTL."""
        cache = {}

        # Set with 1 second TTL
        _cache_set(cache, 'key1', 'value1', ttl=1.0)

        # Should be retrievable immediately
        assert _cache_get(cache, 'key1') == 'value1'

        # Wait 2 seconds
        time.sleep(2)

        # Should be expired
        assert _cache_get(cache, 'key1') is None
        assert 'key1' not in cache  # Should be removed

    def test_cache_no_ttl(self):
        """Should cache indefinitely when TTL is None."""
        cache = {}

        _cache_set(cache, 'key1', 'value1', ttl=None)
        time.sleep(0.1)  # Small delay

        # Should still be there
        assert _cache_get(cache, 'key1') == 'value1'


class TestTableMaterialization:
    """Test CREATE TABLE AS and WITH (as_table=...) functionality."""

    def test_parse_create_table_as(self):
        """Should parse CREATE TABLE AS wrapper."""
        query = """
        CREATE TABLE brands AS
        LARS MAP 'extract_brand.yaml'
        USING (SELECT product_name FROM products LIMIT 100)
        """
        stmt = _parse_lars_statement(query)

        assert stmt.with_options.get('as_table') == 'brands'

    def test_parse_create_temp_table(self):
        """Should parse CREATE TEMP TABLE AS."""
        query = """
        CREATE TEMP TABLE enriched AS
        LARS MAP 'enrich.yaml'
        USING (SELECT * FROM data)
        """
        stmt = _parse_lars_statement(query)

        assert stmt.with_options.get('as_table') == 'enriched'

    def test_parse_with_as_table(self):
        """Should parse WITH (as_table='...')."""
        query = """
        LARS MAP 'cascade.yaml'
        USING (SELECT * FROM t)
        WITH (as_table='results')
        """
        stmt = _parse_lars_statement(query)

        assert stmt.with_options.get('as_table') == 'results'

    def test_create_table_precedence(self):
        """CREATE TABLE should take precedence over WITH."""
        query = """
        CREATE TABLE table1 AS
        LARS MAP 'cascade.yaml'
        USING (SELECT * FROM t)
        WITH (as_table='table2')
        """
        stmt = _parse_lars_statement(query)

        # CREATE TABLE name should win
        assert stmt.with_options.get('as_table') == 'table1'

    def test_materialization_in_rewrite(self):
        """Should wrap query with materialization UDF."""
        query = """
        LARS MAP 'test.yaml'
        USING (SELECT * FROM t)
        WITH (as_table='results')
        """
        rewritten = rewrite_lars_syntax(query)

        assert 'lars_materialize_table' in rewritten
        assert "'results'" in rewritten
        assert 'SELECT * FROM results' in rewritten


class TestCombinedFeatures:
    """Test feature combinations."""

    def test_explain_with_schema(self):
        """Should handle EXPLAIN with typed schema."""
        query = """
        EXPLAIN LARS MAP 'cascade.yaml' AS (
            brand VARCHAR,
            score DOUBLE
        )
        USING (SELECT * FROM products LIMIT 10)
        """
        # Should not raise
        result = rewrite_lars_syntax(query, duckdb_conn=None)
        assert "ERROR" in result or "SELECT" in result

    def test_distinct_with_schema(self):
        """Should handle DISTINCT with typed schema."""
        query = """
        LARS MAP DISTINCT 'cascade.yaml' AS (
            brand VARCHAR,
            category VARCHAR
        )
        USING (SELECT product FROM products)
        """
        stmt = _parse_lars_statement(query)

        assert stmt.with_options.get('distinct') == True
        assert stmt.output_columns is not None
        assert len(stmt.output_columns) == 2

    def test_all_features_combined(self):
        """Should parse query with all features."""
        query = """
        EXPLAIN LARS MAP DISTINCT 'cascade.yaml' AS (
            brand VARCHAR,
            confidence DOUBLE
        )
        USING (SELECT product FROM products)
        WITH (dedupe_by='product', cache='1d', infer_schema=false)
        """
        # Should not raise
        result = rewrite_lars_syntax(query, duckdb_conn=None)
        assert "ERROR" in result or "SELECT" in result

    def test_create_table_with_schema(self):
        """Should handle CREATE TABLE AS with typed schema."""
        query = """
        CREATE TABLE enriched AS
        LARS MAP 'cascade.yaml' AS (
            brand VARCHAR,
            score DOUBLE
        )
        USING (SELECT * FROM products)
        """
        stmt = _parse_lars_statement(query)

        assert stmt.with_options.get('as_table') == 'enriched'
        assert stmt.output_columns is not None


class TestErrorHandling:
    """Test error cases and edge conditions."""

    def test_missing_cascade_path(self):
        """Should raise on missing cascade path."""
        query = "LARS MAP USING (SELECT * FROM t)"

        with pytest.raises(LARSSyntaxError, match="Expected cascade path"):
            _parse_lars_statement(query)

    def test_missing_using(self):
        """Should raise on missing USING clause."""
        query = "LARS MAP 'cascade.yaml'"

        with pytest.raises(LARSSyntaxError, match="Expected USING"):
            _parse_lars_statement(query)

    def test_invalid_type_in_schema(self):
        """Should raise on invalid SQL type."""
        with pytest.raises(LARSSyntaxError, match="Unsupported SQL type"):
            _parse_output_schema("field INVALID_TYPE")

    def test_malformed_schema(self):
        """Should raise on malformed schema syntax."""
        with pytest.raises(LARSSyntaxError, match="Expected 'column_name TYPE'"):
            _parse_output_schema("field_without_type")

    def test_unbalanced_parens_using(self):
        """Should raise on unbalanced parentheses."""
        query = "LARS MAP 'cascade.yaml' USING (SELECT * FROM t"

        with pytest.raises(LARSSyntaxError, match="Unbalanced parentheses"):
            _parse_lars_statement(query)


class TestBackwardCompatibility:
    """Ensure new features don't break existing functionality."""

    def test_simple_map_still_works(self):
        """Simple MAP without new features should work."""
        query = "LARS MAP 'cascade.yaml' USING (SELECT * FROM t)"
        stmt = _parse_lars_statement(query)

        assert stmt.mode == 'MAP'
        assert stmt.cascade_path == 'cascade.yaml'
        assert stmt.output_columns is None  # No schema
        assert not stmt.with_options.get('distinct')

    def test_map_with_alias_still_works(self):
        """MAP with AS alias should still work."""
        query = "LARS MAP 'cascade.yaml' AS brand USING (SELECT * FROM t)"
        stmt = _parse_lars_statement(query)

        assert stmt.result_alias == 'brand'
        assert stmt.output_columns is None

    def test_map_run_unchanged(self):
        """LARS RUN should work unchanged."""
        query = """
        LARS RUN 'batch.yaml'
        USING (SELECT * FROM t)
        WITH (as_table='batch_data')
        """
        stmt = _parse_lars_statement(query)

        assert stmt.mode == 'RUN'
        assert stmt.with_options.get('as_table') == 'batch_data'

    def test_auto_limit_still_applied(self):
        """Auto-LIMIT should still be added."""
        query = "LARS MAP 'cascade.yaml' USING (SELECT * FROM t)"
        rewritten = rewrite_lars_syntax(query)

        assert 'LIMIT' in rewritten


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
