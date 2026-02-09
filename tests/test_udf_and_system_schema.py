"""
Tests for clickhouse_scan UDFs and lars_system schema.

These tests verify:
1. UDF registration works correctly
2. lars_system schema is created with expected views
3. Live ClickHouse queries work (integration tests)

Run with: pytest tests/test_clickhouse_scan.py -v
"""
import pytest
import duckdb
import os


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fresh_connection():
    """Create a fresh in-memory DuckDB connection."""
    return duckdb.connect(':memory:')


@pytest.fixture
def connection_with_udfs(fresh_connection):
    """DuckDB connection with clickhouse_scan UDFs registered."""
    from lars.sql_tools.udf import register_clickhouse_scan_udfs, get_registered_functions

    existing = get_registered_functions(fresh_connection)
    register_clickhouse_scan_udfs(fresh_connection, existing)
    return fresh_connection


@pytest.fixture
def connection_with_lars_system():
    """DuckDB connection with full UDF registration including lars_system schema."""
    from lars.lars_db import get_lars_db
    from lars.sql_tools.udf import register_lars_udf
    
    # Use lars_db.connect() which includes lars_system views
    lars_db = get_lars_db()
    conn = lars_db.connect()
    
    # Also register UDFs for completeness
    register_lars_udf(conn)
    return conn


def _clickhouse_available():
    """Check if ClickHouse server is available for integration tests."""
    try:
        # Try to connect to actual ClickHouse server (not DuckDB adapter)
        from lars.config import get_config
        cfg = get_config()
        
        # Check if ClickHouse is configured
        if not cfg.clickhouse_host or cfg.clickhouse_host == "":
            return False
            
        # Try a direct connection
        import clickhouse_driver
        client = clickhouse_driver.Client(
            host=cfg.clickhouse_host,
            port=cfg.clickhouse_port or 9000,
            database=cfg.clickhouse_database or 'default',
            connect_timeout=2,
        )
        client.execute("SELECT 1")
        return True
    except Exception:
        return False


# =============================================================================
# UDF Registration Tests (No ClickHouse Required)
# =============================================================================

class TestClickhouseScanUDFRegistration:
    """Tests for clickhouse_scan UDF registration."""

    def test_clickhouse_scan_1_registered(self, connection_with_udfs):
        """clickhouse_scan_1 should be registered."""
        funcs = connection_with_udfs.execute("""
            SELECT function_name
            FROM duckdb_functions()
            WHERE function_name = 'clickhouse_scan_1'
        """).fetchall()

        assert len(funcs) == 1
        assert funcs[0][0] == 'clickhouse_scan_1'

    def test_clickhouse_scan_2_registered(self, connection_with_udfs):
        """clickhouse_scan_2 should be registered."""
        funcs = connection_with_udfs.execute("""
            SELECT function_name
            FROM duckdb_functions()
            WHERE function_name = 'clickhouse_scan_2'
        """).fetchall()

        assert len(funcs) == 1
        assert funcs[0][0] == 'clickhouse_scan_2'

    def test_clickhouse_query_1_registered(self, connection_with_udfs):
        """clickhouse_query_1 should be registered."""
        funcs = connection_with_udfs.execute("""
            SELECT function_name
            FROM duckdb_functions()
            WHERE function_name = 'clickhouse_query_1'
        """).fetchall()

        assert len(funcs) == 1
        assert funcs[0][0] == 'clickhouse_query_1'

    def test_all_clickhouse_udfs_registered(self, connection_with_udfs):
        """All three clickhouse UDFs should be registered."""
        funcs = connection_with_udfs.execute("""
            SELECT function_name
            FROM duckdb_functions()
            WHERE function_name LIKE 'clickhouse%'
            ORDER BY function_name
        """).fetchall()

        func_names = [f[0] for f in funcs]
        assert 'clickhouse_query_1' in func_names
        assert 'clickhouse_scan_1' in func_names
        assert 'clickhouse_scan_2' in func_names

    def test_udfs_return_varchar(self, connection_with_udfs):
        """clickhouse_scan UDFs should return VARCHAR (file path)."""
        # Check return type via function metadata
        funcs = connection_with_udfs.execute("""
            SELECT function_name, return_type
            FROM duckdb_functions()
            WHERE function_name LIKE 'clickhouse%'
        """).fetchall()

        for func_name, return_type in funcs:
            assert return_type == 'VARCHAR', f"{func_name} should return VARCHAR"


# =============================================================================
# lars_system Schema Tests (No ClickHouse Required for Structure)
# =============================================================================

class TestLarsSystemSchema:
    """Tests for lars_system schema creation."""

    def test_lars_system_schema_created(self, connection_with_lars_system):
        """lars_system schema should be created."""
        schemas = connection_with_lars_system.execute("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name = 'lars_system'
        """).fetchall()

        assert len(schemas) == 1
        assert schemas[0][0] == 'lars_system'

    def test_lars_system_embeddings_view_exists(self, connection_with_lars_system):
        """lars_system.embeddings view should exist."""
        views = connection_with_lars_system.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'lars_system' AND table_name = 'embeddings'
        """).fetchall()

        assert len(views) == 1

    def test_lars_system_cache_view_exists(self, connection_with_lars_system):
        """lars_system.cache view should exist."""
        views = connection_with_lars_system.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'lars_system' AND table_name = 'cache'
        """).fetchall()

        assert len(views) == 1

    def test_lars_system_logs_view_exists(self, connection_with_lars_system):
        """lars_system.logs view should exist."""
        views = connection_with_lars_system.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'lars_system' AND table_name = 'logs'
        """).fetchall()

        assert len(views) == 1

    def test_lars_system_sql_log_view_exists(self, connection_with_lars_system):
        """lars_system.sql_log view should exist."""
        views = connection_with_lars_system.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'lars_system' AND table_name = 'sql_log'
        """).fetchall()

        assert len(views) == 1

    def test_lars_system_sessions_view_exists(self, connection_with_lars_system):
        """lars_system.sessions view should exist and map to session_state."""
        views = connection_with_lars_system.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'lars_system' AND table_name = 'sessions'
        """).fetchall()

        assert len(views) == 1

    def test_lars_system_all_expected_views(self, connection_with_lars_system):
        """lars_system should have all expected core views."""
        views = connection_with_lars_system.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'lars_system'
            ORDER BY table_name
        """).fetchall()

        view_names = [v[0] for v in views]

        # Core views that must exist for system observability
        expected_views = [
            # Core Execution
            'logs',         # → unified_logs
            'sessions',     # → session_state  
            'checkpoints',  # → checkpoints
            'cascades',     # → cascade_sessions
            # Cost & Query Tracking
            'costs',        # → costs
            'sql_log',      # → ui_sql_log
            # Placeholders (empty but schema-defined)
            'cache',        # semantic cache
            'embeddings',   # embedding storage
        ]
        for expected in expected_views:
            assert expected in view_names, f"Missing view: lars_system.{expected}"


# =============================================================================
# Integration Tests (Require ClickHouse)
# =============================================================================

@pytest.mark.skipif(
    not _clickhouse_available(),
    reason="ClickHouse not available"
)
class TestClickhouseScanIntegration:
    """Integration tests that require a running ClickHouse instance."""

    def test_clickhouse_scan_returns_file_path(self, connection_with_udfs):
        """clickhouse_scan should return a file path to JSON."""
        result = connection_with_udfs.execute("""
            SELECT clickhouse_scan_1('lars.unified_logs')
        """).fetchone()

        assert result is not None
        file_path = result[0]
        assert file_path.endswith('.json')
        assert os.path.exists(file_path)

    def test_clickhouse_scan_with_read_json_auto(self, connection_with_udfs):
        """clickhouse_scan with read_json_auto should return rows."""
        result = connection_with_udfs.execute("""
            SELECT COUNT(*)
            FROM read_json_auto(clickhouse_scan_2('lars.unified_logs', 10))
        """).fetchone()

        assert result is not None
        count = result[0]
        assert count <= 10  # Should respect limit

    def test_clickhouse_scan_limit_parameter(self, connection_with_udfs):
        """clickhouse_scan_2 should respect the limit parameter."""
        # Query with limit 5
        result_5 = connection_with_udfs.execute("""
            SELECT COUNT(*)
            FROM read_json_auto(clickhouse_scan_2('lars.unified_logs', 5))
        """).fetchone()[0]

        # Query with limit 10
        result_10 = connection_with_udfs.execute("""
            SELECT COUNT(*)
            FROM read_json_auto(clickhouse_scan_2('lars.unified_logs', 10))
        """).fetchone()[0]

        assert result_5 <= 5
        assert result_10 <= 10

    def test_clickhouse_query_arbitrary_sql(self, connection_with_udfs):
        """clickhouse_query_1 should execute arbitrary SQL."""
        result = connection_with_udfs.execute("""
            SELECT *
            FROM read_json_auto(clickhouse_query_1('SELECT 1 as num, ''hello'' as greeting'))
        """).fetchone()

        assert result is not None
        assert result[0] == 1
        assert result[1] == 'hello'

    def test_lars_system_logs_queryable(self, connection_with_lars_system):
        """lars_system.logs should be queryable."""
        result = connection_with_lars_system.execute("""
            SELECT COUNT(*) FROM lars_system.logs
        """).fetchone()

        assert result is not None
        # Should have some rows (or at least not error)
        assert result[0] >= 0

    def test_lars_system_cache_queryable(self, connection_with_lars_system):
        """lars_system.cache should be queryable."""
        result = connection_with_lars_system.execute("""
            SELECT COUNT(*) FROM lars_system.cache
        """).fetchone()

        assert result is not None
        assert result[0] >= 0

    def test_lars_system_embeddings_queryable(self, connection_with_lars_system):
        """lars_system.embeddings should be queryable."""
        result = connection_with_lars_system.execute("""
            SELECT COUNT(*) FROM lars_system.embeddings
        """).fetchone()

        assert result is not None
        assert result[0] >= 0

    def test_clickhouse_scan_handles_missing_table(self, connection_with_udfs):
        """clickhouse_scan should handle missing tables gracefully."""
        result = connection_with_udfs.execute("""
            SELECT *
            FROM read_json_auto(clickhouse_scan_1('nonexistent_table_xyz'))
        """).fetchall()

        # Should return error row, not crash
        assert len(result) >= 1
        # First row should contain error information (either as 'error' key or in the message)
        result_str = str(result[0]).lower()
        assert 'error' in result_str or 'does not exist' in result_str or 'doesn\'t exist' in result_str


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================

class TestClickhouseScanEdgeCases:
    """Tests for edge cases and error handling."""

    def test_udf_registration_idempotent(self, fresh_connection):
        """Registering UDFs multiple times should not error."""
        from lars.sql_tools.udf import register_clickhouse_scan_udfs, get_registered_functions

        existing = get_registered_functions(fresh_connection)

        # Register twice
        register_clickhouse_scan_udfs(fresh_connection, existing)
        register_clickhouse_scan_udfs(fresh_connection, existing)

        # Should still have exactly one of each
        funcs = fresh_connection.execute("""
            SELECT function_name
            FROM duckdb_functions()
            WHERE function_name LIKE 'clickhouse%'
        """).fetchall()

        func_names = [f[0] for f in funcs]
        assert func_names.count('clickhouse_scan_1') == 1
        assert func_names.count('clickhouse_scan_2') == 1
        assert func_names.count('clickhouse_query_1') == 1

    def test_lars_system_schema_idempotent(self, fresh_connection):
        """Attaching lars_system schema multiple times should not error."""
        from lars.sql_tools.udf import (
            register_clickhouse_scan_udfs,
            attach_lars_system_schema,
            get_registered_functions
        )

        existing = get_registered_functions(fresh_connection)
        register_clickhouse_scan_udfs(fresh_connection, existing)

        # Attach twice
        attach_lars_system_schema(fresh_connection)
        attach_lars_system_schema(fresh_connection)

        # Should still have exactly one schema
        schemas = fresh_connection.execute("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name = 'lars_system'
        """).fetchall()

        assert len(schemas) == 1
