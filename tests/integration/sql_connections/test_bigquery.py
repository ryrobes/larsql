"""
BigQuery integration tests for sql_tools.

Tests BigQuery connections using real GCP credentials.
These tests require GOOGLE_APPLICATION_CREDENTIALS to be set.

Run with:
    pytest tests/integration/sql_connections/test_bigquery.py -v -m gcp
"""

import os
import pytest


def has_gcp_credentials() -> bool:
    """Check if GCP credentials are available."""
    return bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))


skip_unless_gcp = pytest.mark.skipif(
    not has_gcp_credentials(),
    reason="GCP credentials not available - set GOOGLE_APPLICATION_CREDENTIALS"
)


@pytest.mark.cloud
@pytest.mark.gcp
@skip_unless_gcp
class TestBigQueryConnection:
    """Test BigQuery connector via DuckDB bigquery extension."""

    def test_bigquery_config_validation(self):
        """Test that BigQuery config validation works correctly."""
        from lars.sql_tools.config import SqlConnectionConfig, validate_connection_config

        # Valid config
        config = SqlConnectionConfig(
            connection_name="test_bq",
            type="bigquery",
            project_id="my-project",
        )
        errors = validate_connection_config(config)
        assert len(errors) == 0, f"Unexpected validation errors: {errors}"

        # Missing project_id
        config_missing = SqlConnectionConfig(
            connection_name="test_bq",
            type="bigquery",
        )
        errors = validate_connection_config(config_missing)
        assert any("project_id" in e for e in errors)

    def test_google_credentials_resolver_file_path(self, tmp_path):
        """Test that credential resolver handles file paths."""
        from lars.sql_tools.config import resolve_google_credentials

        # Create a fake credentials file
        creds_file = tmp_path / "creds.json"
        creds_file.write_text('{"type": "service_account", "project_id": "test"}')

        # Set env var to file path
        os.environ["TEST_GCP_CREDS"] = str(creds_file)

        try:
            result = resolve_google_credentials("TEST_GCP_CREDS")
            assert result == str(creds_file)
        finally:
            del os.environ["TEST_GCP_CREDS"]

    def test_google_credentials_resolver_json_string(self, tmp_path):
        """Test that credential resolver handles JSON strings."""
        from lars.sql_tools.config import resolve_google_credentials

        # Set env var to JSON string (common in containerized deployments)
        json_creds = '{"type": "service_account", "project_id": "test-project", "private_key": "fake"}'
        os.environ["TEST_GCP_CREDS_JSON"] = json_creds

        try:
            result = resolve_google_credentials("TEST_GCP_CREDS_JSON")
            # Should return path to temp file
            assert result is not None
            assert result.endswith(".json")
            assert os.path.exists(result)

            # Verify contents
            with open(result) as f:
                content = f.read()
                assert "test-project" in content
        finally:
            del os.environ["TEST_GCP_CREDS_JSON"]

    def test_bigquery_extension_install(self, duckdb_conn):
        """Test that BigQuery extension can be installed."""
        try:
            duckdb_conn.execute("INSTALL bigquery;")
            duckdb_conn.execute("LOAD bigquery;")
        except Exception as e:
            pytest.skip(f"BigQuery extension not available: {e}")

    def test_bigquery_public_dataset(self, duckdb_conn):
        """Test querying a BigQuery public dataset."""
        from lars.sql_tools.config import resolve_google_credentials

        # This test queries a public dataset - requires a billing project
        billing_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
        if not billing_project:
            pytest.skip("No billing project - set GOOGLE_CLOUD_PROJECT or GCP_PROJECT_ID")

        # Resolve credentials (handles JSON string -> temp file)
        creds_path = resolve_google_credentials()
        if creds_path:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path

        try:
            duckdb_conn.execute("INSTALL bigquery FROM community;")
            duckdb_conn.execute("LOAD bigquery;")
        except Exception as e:
            pytest.skip(f"BigQuery extension not available: {e}")

        # Query public dataset using billing project
        try:
            result = duckdb_conn.execute(f"""
                SELECT COUNT(*) as cnt
                FROM bigquery_scan('bigquery-public-data.samples.shakespeare', billing_project='{billing_project}')
                LIMIT 1
            """).fetchone()
            assert result is not None
            assert result[0] > 0
        except Exception as e:
            error_str = str(e).lower()
            if "credentials" in error_str or "authentication" in error_str:
                pytest.skip("BigQuery authentication required")
            elif "billing" in error_str:
                pytest.skip("BigQuery billing not enabled")
            raise


@pytest.mark.cloud
@pytest.mark.gcp
@skip_unless_gcp
class TestBigQueryLazyAttach:
    """Test BigQuery lazy attachment."""

    def test_lazy_attach_bigquery(self, duckdb_conn):
        """Test BigQuery lazy attach with project config."""
        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.lazy_attach import LazyAttachManager

        # Get project ID from credentials if available
        project_id = os.environ.get("GCP_PROJECT_ID", "bigquery-public-data")

        config = SqlConnectionConfig(
            connection_name="bq_test",
            type="bigquery",
            project_id=project_id,
            read_only=True,
        )

        manager = LazyAttachManager(duckdb_conn, {"bq_test": config})

        try:
            # This should trigger BigQuery attachment
            manager.ensure_for_query("SELECT * FROM bq_test.samples.shakespeare LIMIT 1")

            # Verify database was attached
            databases = duckdb_conn.execute(
                "SELECT database_name FROM duckdb_databases() WHERE NOT internal"
            ).fetchall()
            db_names = {d[0] for d in databases}
            assert "bq_test" in db_names, f"bq_test should be attached, got: {db_names}"

        except Exception as e:
            error_str = str(e).lower()
            if "bigquery" in error_str and "extension" in error_str:
                pytest.skip("BigQuery extension not available")
            if "credentials" in error_str or "authentication" in error_str:
                pytest.skip("BigQuery authentication failed")
            raise


@pytest.mark.cloud
@pytest.mark.gcp
@skip_unless_gcp
class TestBigQueryDatabaseConnector:
    """Test BigQuery via DatabaseConnector interface."""

    def test_connector_bigquery_attach(self):
        """Test BigQuery attachment via DatabaseConnector."""
        from lars.sql_tools.config import SqlConnectionConfig, resolve_google_credentials
        from lars.sql_tools.connector import DatabaseConnector

        # Resolve credentials (handles JSON string -> temp file)
        creds_path = resolve_google_credentials()
        if creds_path:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path

        # Get billing project - queries execute in YOUR project, not the public data project
        billing_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
        if not billing_project:
            pytest.skip("No billing project - set GOOGLE_CLOUD_PROJECT or GCP_PROJECT_ID")

        connector = None
        try:
            # Use in-memory connection to avoid file lock issues
            connector = DatabaseConnector(use_cache=False)

            # Attach YOUR billing project - this is where queries execute
            config = SqlConnectionConfig(
                connection_name="bq_billing",
                type="bigquery",
                project_id=billing_project,
                read_only=True,
            )

            # Attach the billing project
            connector._attach_bigquery(config, "bq_billing")

            # Query public dataset via bigquery_scan with explicit billing_project
            # Public data lives in bigquery-public-data, but query runs in your project
            result = connector.conn.execute(f"""
                SELECT COUNT(*) as cnt
                FROM bigquery_scan('bigquery-public-data.samples.shakespeare', billing_project='{billing_project}')
                LIMIT 1
            """).fetchone()
            assert result is not None
            assert result[0] > 0

        except Exception as e:
            error_str = str(e).lower()
            if "bigquery" in error_str and "extension" in error_str:
                pytest.skip("BigQuery extension not available")
            if "credentials" in error_str or "authentication" in error_str:
                pytest.skip("BigQuery authentication failed")
            if "permission" in error_str:
                pytest.skip(f"BigQuery permission denied: {e}")
            raise
        finally:
            if connector:
                connector.close()
