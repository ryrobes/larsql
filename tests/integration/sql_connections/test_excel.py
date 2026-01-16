"""
Excel integration tests for sql_tools.

Tests Excel file connections using DuckDB's spatial extension.

Run with:
    pytest tests/integration/sql_connections/test_excel.py -v
"""

import pytest


class TestExcelConnection:
    """Test Excel file connector."""

    def test_excel_config_validation(self):
        """Test that Excel config validation works correctly."""
        from lars.sql_tools.config import SqlConnectionConfig, validate_connection_config

        # Valid config
        config = SqlConnectionConfig(
            connection_name="test_excel",
            type="excel",
            file_path="/path/to/data.xlsx",
        )
        errors = validate_connection_config(config)
        assert len(errors) == 0, f"Unexpected validation errors: {errors}"

        # Missing file_path
        config_missing = SqlConnectionConfig(
            connection_name="test_excel",
            type="excel",
        )
        errors = validate_connection_config(config_missing)
        assert any("file_path" in e for e in errors)

    def test_excel_read_direct(self, duckdb_conn, test_excel_file):
        """Test reading Excel file directly with DuckDB."""
        # Install spatial extension (includes Excel support)
        try:
            duckdb_conn.execute("INSTALL spatial;")
            duckdb_conn.execute("LOAD spatial;")
        except Exception as e:
            pytest.skip(f"spatial extension not available: {e}")

        # Try to read using st_read (GDAL-based)
        try:
            result = duckdb_conn.execute(
                f"SELECT * FROM st_read('{test_excel_file}', layer='Sales')"
            ).fetchall()
            assert len(result) > 0, "Expected rows from Sales sheet"
        except Exception as e:
            # Fallback: some DuckDB versions use read_xlsx instead
            if "st_read" in str(e).lower() or "not found" in str(e).lower():
                pytest.skip(f"st_read/Excel not supported in this DuckDB version: {e}")
            raise

    def test_excel_lazy_attach(self, duckdb_conn, test_excel_file):
        """Test Excel lazy attach with all sheets."""
        try:
            import openpyxl
        except ImportError:
            pytest.skip("openpyxl not installed")

        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.lazy_attach import LazyAttachManager

        config = SqlConnectionConfig(
            connection_name="excel_test",
            type="excel",
            file_path=str(test_excel_file),
        )

        manager = LazyAttachManager(duckdb_conn, {"excel_test": config})

        try:
            # This should trigger lazy attachment of all sheets
            manager.ensure_for_query("SELECT * FROM excel_test.Sales")

            # Verify schema was created
            schemas = duckdb_conn.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'excel_test'"
            ).fetchall()
            assert len(schemas) == 1, "excel_test schema should exist"

            # Verify tables were created (one per sheet)
            tables = duckdb_conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'excel_test'"
            ).fetchall()
            assert len(tables) >= 1, "Expected at least one table (sheet)"

        except Exception as e:
            if "spatial" in str(e).lower() or "st_read" in str(e).lower():
                pytest.skip(f"Excel support not available: {e}")
            raise

    def test_excel_specific_sheet(self, duckdb_conn, test_excel_file):
        """Test reading a specific sheet from Excel."""
        try:
            import openpyxl
        except ImportError:
            pytest.skip("openpyxl not installed")

        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.lazy_attach import LazyAttachManager

        config = SqlConnectionConfig(
            connection_name="excel_customers",
            type="excel",
            file_path=str(test_excel_file),
            sheet_name="Customers",  # Only load this sheet
        )

        manager = LazyAttachManager(duckdb_conn, {"excel_customers": config})

        try:
            manager.ensure_for_query("SELECT * FROM excel_customers.Customers")

            # Query the specific sheet
            result = duckdb_conn.execute(
                "SELECT COUNT(*) FROM excel_customers.Customers"
            ).fetchone()
            assert result[0] > 0, "Expected rows in Customers sheet"

        except Exception as e:
            if "spatial" in str(e).lower() or "st_read" in str(e).lower():
                pytest.skip(f"Excel support not available: {e}")
            raise


class TestExcelDatabaseConnector:
    """Test Excel via DatabaseConnector interface."""

    def test_connector_excel_attach(self, test_excel_file):
        """Test Excel attachment via DatabaseConnector."""
        try:
            import openpyxl
        except ImportError:
            pytest.skip("openpyxl not installed")

        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.connector import DatabaseConnector

        connector = None
        try:
            # Use in-memory connection to avoid file lock issues
            connector = DatabaseConnector(use_cache=False)

            config = SqlConnectionConfig(
                connection_name="excel_conn_test",
                type="excel",
                file_path=str(test_excel_file),
            )

            # This should create views for all sheets
            connector._attach_excel(config, "excel_conn_test")

            # Verify we can query using raw DuckDB
            result = connector.conn.execute(
                "SELECT COUNT(*) as cnt FROM excel_conn_test.Sales"
            ).fetchone()
            assert result is not None
            assert result[0] > 0

        except Exception as e:
            if "spatial" in str(e).lower() or "st_read" in str(e).lower():
                pytest.skip(f"Excel support not available: {e}")
            raise
        finally:
            if connector:
                connector.close()
