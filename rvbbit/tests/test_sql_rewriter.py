"""
Unit tests for SQL rewriter module.

Tests RVBBIT MAP/RUN syntax parsing and rewriting.
"""

import pytest
from rvbbit.sql_rewriter import (
    rewrite_rvbbit_syntax,
    _is_rvbbit_statement,
    _parse_rvbbit_statement,
    _rewrite_map,
    _rewrite_run,
    _ensure_limit,
    _extract_balanced_parens,
    _parse_with_options,
    _parse_value,
    RVBBITSyntaxError,
    DEFAULT_MAP_LIMIT
)


# ============================================================================
# Detection Tests
# ============================================================================

def test_detect_rvbbit_map():
    """Should detect RVBBIT MAP statements."""
    assert _is_rvbbit_statement("RVBBIT MAP 'x' USING (SELECT 1)")
    assert _is_rvbbit_statement("rvbbit map 'x' using (select 1)")  # case-insensitive
    assert _is_rvbbit_statement("  RVBBIT MAP 'x' USING (SELECT 1)  ")  # whitespace


def test_detect_rvbbit_run():
    """Should detect RVBBIT RUN statements."""
    assert _is_rvbbit_statement("RVBBIT RUN 'x' USING (SELECT 1)")


def test_not_rvbbit_statement():
    """Should not detect regular SQL."""
    assert not _is_rvbbit_statement("SELECT * FROM t")
    assert not _is_rvbbit_statement("INSERT INTO t VALUES (1)")
    assert not _is_rvbbit_statement("-- RVBBIT MAP 'x' USING (SELECT 1)")  # comment


# ============================================================================
# Parsing Tests
# ============================================================================

def test_parse_basic_map():
    """Should parse basic MAP statement."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT MAP 'x.yaml' USING (SELECT a FROM t)"
    )
    assert stmt.mode == 'MAP'
    assert stmt.cascade_path == 'x.yaml'
    assert stmt.using_query == 'SELECT a FROM t'
    assert stmt.result_alias is None
    assert stmt.with_options == {}


def test_parse_map_with_as_alias():
    """Should parse AS alias."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT MAP 'x.yaml' AS enriched USING (SELECT a FROM t)"
    )
    assert stmt.result_alias == 'enriched'


def test_parse_map_with_options():
    """Should parse WITH options."""
    stmt = _parse_rvbbit_statement("""
        RVBBIT MAP 'x.yaml'
        USING (SELECT a FROM t)
        WITH (cache = true, budget_dollars = 5.0, key = 'customer_id')
    """)
    assert stmt.with_options == {
        'cache': True,
        'budget_dollars': 5.0,
        'key': 'customer_id'
    }


def test_parse_complex_using_query():
    """Should handle complex SQL in USING clause."""
    stmt = _parse_rvbbit_statement("""
        RVBBIT MAP 'x.yaml' USING (
            WITH sub AS (SELECT a, b FROM t WHERE x > 10)
            SELECT * FROM sub
            LEFT JOIN other ON sub.a = other.id
            LIMIT 100
        )
    """)
    assert 'WITH sub AS' in stmt.using_query
    assert 'LEFT JOIN' in stmt.using_query


def test_parse_map_with_parallel():
    """Should parse PARALLEL clause."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT MAP PARALLEL 5 'x.yaml' USING (SELECT a FROM t LIMIT 10)"
    )
    assert stmt.mode == 'MAP'
    assert stmt.parallel == 5
    assert stmt.cascade_path == 'x.yaml'


def test_parse_map_parallel_with_alias():
    """Should parse PARALLEL with AS alias."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT MAP PARALLEL 20 'x.yaml' AS enriched USING (SELECT a FROM t)"
    )
    assert stmt.parallel == 20
    assert stmt.result_alias == 'enriched'


def test_parse_error_missing_cascade():
    """Should raise error if cascade path missing."""
    with pytest.raises(RVBBITSyntaxError, match="Expected cascade path"):
        _parse_rvbbit_statement("RVBBIT MAP USING (SELECT 1)")


def test_parse_error_missing_using():
    """Should raise error if USING clause missing."""
    with pytest.raises(RVBBITSyntaxError, match="Expected USING"):
        _parse_rvbbit_statement("RVBBIT MAP 'x.yaml'")


def test_parse_error_unbalanced_parens():
    """Should raise error on unbalanced parentheses."""
    with pytest.raises(RVBBITSyntaxError, match="Unbalanced parentheses"):
        _parse_rvbbit_statement("RVBBIT MAP 'x' USING (SELECT a FROM t")


# ============================================================================
# Balanced Parentheses Tests
# ============================================================================

def test_extract_balanced_parens_simple():
    """Should extract content from balanced parens."""
    content, remaining = _extract_balanced_parens("(SELECT a FROM t) WITH ...")
    assert content == "SELECT a FROM t"
    assert remaining == " WITH ..."


def test_extract_balanced_parens_nested():
    """Should handle nested parentheses."""
    content, remaining = _extract_balanced_parens("(SELECT (a + b) FROM t) LIMIT")
    assert content == "SELECT (a + b) FROM t"
    assert remaining == " LIMIT"


def test_extract_balanced_parens_complex():
    """Should handle multiple levels of nesting."""
    content, remaining = _extract_balanced_parens(
        "(SELECT json_object('x', (SELECT COUNT(*) FROM t)) FROM t) WHERE"
    )
    assert "json_object" in content
    assert remaining == " WHERE"


# ============================================================================
# WITH Options Parsing Tests
# ============================================================================

def test_parse_with_boolean():
    """Should parse boolean values."""
    opts = _parse_with_options("cache = true, validate = false")
    assert opts == {'cache': True, 'validate': False}


def test_parse_with_numbers():
    """Should parse integer and float values."""
    opts = _parse_with_options("max_rows = 100, budget = 5.5")
    assert opts == {'max_rows': 100, 'budget': 5.5}


def test_parse_with_strings():
    """Should parse string values."""
    opts = _parse_with_options("key = 'customer_id', mode = 'aggressive'")
    assert opts == {'key': 'customer_id', 'mode': 'aggressive'}


def test_parse_with_mixed():
    """Should parse mixed value types."""
    opts = _parse_with_options(
        "cache = true, budget = 10.0, key = 'id', max_attempts = 3"
    )
    assert opts == {
        'cache': True,
        'budget': 10.0,
        'key': 'id',
        'max_attempts': 3
    }


# ============================================================================
# Value Parsing Tests
# ============================================================================

def test_parse_value_boolean():
    """Should parse boolean values."""
    assert _parse_value('true') is True
    assert _parse_value('TRUE') is True
    assert _parse_value('false') is False


def test_parse_value_string():
    """Should parse string literals."""
    assert _parse_value("'hello'") == 'hello'
    assert _parse_value('"world"') == 'world'


def test_parse_value_number():
    """Should parse numeric values."""
    assert _parse_value('42') == 42
    assert _parse_value('3.14') == 3.14
    assert _parse_value('0') == 0


# ============================================================================
# Auto-LIMIT Tests
# ============================================================================

def test_ensure_limit_missing():
    """Should auto-inject LIMIT if missing."""
    query = "SELECT * FROM t"
    result = _ensure_limit(query)
    assert f"LIMIT {DEFAULT_MAP_LIMIT}" in result


def test_ensure_limit_already_present():
    """Should not modify query if LIMIT already exists."""
    query = "SELECT * FROM t LIMIT 50"
    result = _ensure_limit(query)
    assert result == query
    assert "LIMIT 50" in result


def test_ensure_limit_with_semicolon():
    """Should strip semicolon before adding LIMIT."""
    query = "SELECT * FROM t;"
    result = _ensure_limit(query)
    assert f"LIMIT {DEFAULT_MAP_LIMIT}" in result
    assert result.count(';') == 0  # semicolon removed


# ============================================================================
# MAP Rewrite Tests
# ============================================================================

def test_rewrite_map_basic():
    """Should rewrite basic MAP to CTE + UDF with extraction."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT MAP 'x.yaml' USING (SELECT a FROM t LIMIT 10)"
    )
    rewritten = _rewrite_map(stmt)

    # Check structure
    assert 'WITH rvbbit_input AS' in rewritten
    assert 'rvbbit_raw AS' in rewritten
    assert "SELECT a FROM t LIMIT 10" in rewritten
    assert "rvbbit_run('x.yaml'" in rewritten
    assert 'to_json(i)' in rewritten
    assert 'COALESCE(' in rewritten
    assert 'json_extract_string' in rewritten
    assert '$.state.output_extract' in rewritten
    assert 'AS result' in rewritten


def test_rewrite_map_with_alias():
    """Should use AS alias for result column."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT MAP 'x.yaml' AS enriched USING (SELECT a FROM t LIMIT 10)"
    )
    rewritten = _rewrite_map(stmt)

    # Should have AS enriched at the end (for the final extracted column)
    assert 'AS enriched' in rewritten
    # Should not have 'AS result' (using custom alias)
    assert ' AS result' not in rewritten


def test_rewrite_map_auto_limit():
    """Should auto-inject LIMIT if missing."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT MAP 'x.yaml' USING (SELECT a FROM t)"
    )
    rewritten = _rewrite_map(stmt)

    assert f'LIMIT {DEFAULT_MAP_LIMIT}' in rewritten


def test_rewrite_map_with_parallel():
    """Should rewrite MAP PARALLEL using same pattern as sequential (for now)."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT MAP PARALLEL 5 'x.yaml' USING (SELECT a FROM t LIMIT 10)"
    )
    rewritten = _rewrite_map(stmt)

    # Phase 2 MVP: PARALLEL parses correctly but uses sequential execution
    # Threading optimization deferred to Phase 2B
    assert 'WITH rvbbit_input AS' in rewritten
    assert 'rvbbit_raw AS' in rewritten
    assert "rvbbit_run('x.yaml'" in rewritten
    assert 'COALESCE(' in rewritten
    # Should be same structure as sequential


# ============================================================================
# End-to-End Rewrite Tests
# ============================================================================

def test_rewrite_rvbbit_syntax_passthrough():
    """Should pass through non-RVBBIT queries unchanged."""
    query = "SELECT * FROM products LIMIT 10"
    result = rewrite_rvbbit_syntax(query)
    assert result == query


def test_rewrite_rvbbit_syntax_map():
    """Should rewrite RVBBIT MAP."""
    query = "RVBBIT MAP 'enrich.yaml' AS enriched USING (SELECT * FROM t LIMIT 10)"
    result = rewrite_rvbbit_syntax(query)

    assert 'WITH rvbbit_input AS' in result
    assert 'rvbbit_raw AS' in result
    assert 'SELECT * FROM t LIMIT 10' in result
    assert "rvbbit_run('enrich.yaml'" in result
    assert 'COALESCE(' in result
    assert 'json_extract_string' in result
    assert 'AS enriched' in result


def test_parse_basic_run():
    """Should parse basic RUN statement."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT RUN 'batch.yaml' USING (SELECT * FROM t LIMIT 500)"
    )
    assert stmt.mode == 'RUN'
    assert stmt.cascade_path == 'batch.yaml'
    assert 'SELECT * FROM t LIMIT 500' in stmt.using_query


def test_parse_run_with_as_table():
    """Should parse RUN with as_table option."""
    stmt = _parse_rvbbit_statement("""
        RVBBIT RUN 'batch.yaml'
        USING (SELECT * FROM t LIMIT 100)
        WITH (as_table = 'my_batch_data')
    """)
    assert stmt.mode == 'RUN'
    assert stmt.with_options['as_table'] == 'my_batch_data'


def test_rewrite_run_basic():
    """Should rewrite RUN to batch UDF call."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT RUN 'batch.yaml' USING (SELECT a, b FROM t LIMIT 100) WITH (as_table = 'batch_data')"
    )
    rewritten = _rewrite_run(stmt)

    assert 'rvbbit_run_batch(' in rewritten
    assert "'batch.yaml'" in rewritten
    assert 'json_group_array' in rewritten
    assert "'batch_data'" in rewritten
    assert 'SELECT a, b FROM t LIMIT 100' in rewritten


def test_rewrite_run_auto_table_name():
    """Should auto-generate table name if not specified."""
    stmt = _parse_rvbbit_statement(
        "RVBBIT RUN 'batch.yaml' USING (SELECT * FROM t)"
    )
    rewritten = _rewrite_run(stmt)

    assert 'rvbbit_run_batch(' in rewritten
    assert "'_rvbbit_batch_" in rewritten  # Auto-generated name


def test_rewrite_rvbbit_syntax_run():
    """Should rewrite RVBBIT RUN end-to-end."""
    query = "RVBBIT RUN 'batch.yaml' USING (SELECT * FROM t LIMIT 100) WITH (as_table = 'data')"
    result = rewrite_rvbbit_syntax(query)

    assert 'rvbbit_run_batch(' in result
    assert "'batch.yaml'" in result
    assert "'data'" in result


# ============================================================================
# Complex Real-World Examples
# ============================================================================

def test_example_fraud_detection():
    """Example: Fraud detection enrichment."""
    query = """
        RVBBIT MAP 'cascades/fraud_assess.yaml' AS fraud_risk
        USING (
            SELECT charge_id, customer_id, amount, merchant
            FROM charges
            WHERE flagged = true
            LIMIT 50
        )
        WITH (cache = true, budget_dollars = 2.5)
    """

    result = rewrite_rvbbit_syntax(query)

    assert 'WITH rvbbit_input AS' in result
    assert 'rvbbit_raw AS' in result
    assert 'charge_id, customer_id' in result
    assert "rvbbit_run('cascades/fraud_assess.yaml'" in result
    assert 'COALESCE(' in result
    assert 'AS fraud_risk' in result
    assert 'LIMIT 50' in result


def test_example_product_enrichment():
    """Example: Product catalog enrichment."""
    query = """
        RVBBIT MAP 'traits/extract_brand.yaml'
        USING (
            SELECT product_id, product_name, price
            FROM products
            WHERE category = 'electronics'
            LIMIT 100
        )
    """

    result = rewrite_rvbbit_syntax(query)

    assert 'SELECT product_id, product_name, price' in result
    assert "rvbbit_run('traits/extract_brand.yaml'" in result
    assert 'AS result' in result  # default alias


def test_example_with_complex_join():
    """Example: Query with JOIN in USING clause."""
    query = """
        RVBBIT MAP 'analyze.yaml' AS analysis
        USING (
            SELECT
                c.customer_id,
                c.name,
                COUNT(o.order_id) as order_count,
                SUM(o.amount) as total_spent
            FROM customers c
            LEFT JOIN orders o ON c.customer_id = o.customer_id
            WHERE c.created_at >= current_date - INTERVAL '30 days'
            GROUP BY c.customer_id, c.name
            LIMIT 200
        )
    """

    result = rewrite_rvbbit_syntax(query)

    assert 'LEFT JOIN orders o' in result
    assert 'GROUP BY c.customer_id, c.name' in result
    assert 'LIMIT 200' in result
    assert "rvbbit_run('analyze.yaml'" in result


# ============================================================================
# Error Handling Tests
# ============================================================================

def test_error_invalid_syntax():
    """Should pass through unrecognized RVBBIT keywords (will fail at DuckDB)."""
    # RVBBIT INVALID doesn't match MAP or RUN, so it passes through
    result = rewrite_rvbbit_syntax("RVBBIT INVALID 'x' USING (SELECT 1)")
    assert result == "RVBBIT INVALID 'x' USING (SELECT 1)"


def test_error_missing_quote():
    """Should raise error for missing quote in cascade path."""
    with pytest.raises(RVBBITSyntaxError, match="Expected cascade path"):
        rewrite_rvbbit_syntax("RVBBIT MAP x.yaml USING (SELECT 1)")


def test_error_with_malformed_options():
    """Should raise error for malformed WITH options."""
    with pytest.raises(RVBBITSyntaxError, match="key = value"):
        rewrite_rvbbit_syntax("""
            RVBBIT MAP 'x' USING (SELECT 1) WITH (invalid_syntax)
        """)
