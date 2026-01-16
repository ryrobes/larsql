"""
Google Cloud Storage integration tests for sql_tools.

Tests GCS connections using real GCP credentials.
These tests require GOOGLE_APPLICATION_CREDENTIALS to be set.

Run with:
    pytest tests/integration/sql_connections/test_gcs.py -v -m gcp
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
class TestGCSConnection:
    """Test Google Cloud Storage connector via DuckDB httpfs."""

    def test_gcs_config_validation(self):
        """Test that GCS config validation works correctly."""
        from lars.sql_tools.config import SqlConnectionConfig, validate_connection_config

        # Valid config
        config = SqlConnectionConfig(
            connection_name="test_gcs",
            type="gcs",
            bucket="my-bucket",
        )
        errors = validate_connection_config(config)
        assert len(errors) == 0, f"Unexpected validation errors: {errors}"

        # Missing bucket
        config_missing = SqlConnectionConfig(
            connection_name="test_gcs",
            type="gcs",
        )
        errors = validate_connection_config(config_missing)
        assert any("bucket" in e for e in errors)

    def test_gcs_with_credentials_resolver(self, tmp_path):
        """Test GCS config with credential resolver."""
        from lars.sql_tools.config import SqlConnectionConfig, resolve_google_credentials

        # Create fake credentials file
        creds_file = tmp_path / "gcs_creds.json"
        creds_file.write_text('{"type": "service_account", "project_id": "test"}')
        os.environ["TEST_GCS_CREDS"] = str(creds_file)

        try:
            config = SqlConnectionConfig(
                connection_name="test_gcs",
                type="gcs",
                bucket="test-bucket",
                credentials_env="TEST_GCS_CREDS",
            )

            # Resolve credentials
            creds_path = resolve_google_credentials(config.credentials_env)
            assert creds_path == str(creds_file)
        finally:
            del os.environ["TEST_GCS_CREDS"]

    def test_gcs_public_bucket(self, duckdb_conn):
        """Test reading from a public GCS bucket."""
        # Install httpfs extension
        duckdb_conn.execute("INSTALL httpfs;")
        duckdb_conn.execute("LOAD httpfs;")

        # For public buckets, we need to NOT use service account credentials
        # The httpfs extension will try to use HMAC auth if creds are set, which fails
        # Use HTTPS URL directly which allows anonymous access to public buckets
        try:
            # Use HTTPS URL instead of gs:// to access public data anonymously
            result = duckdb_conn.execute("""
                SELECT COUNT(*) as cnt
                FROM read_parquet('https://storage.googleapis.com/cloud-samples-data/bigquery/us-states/us-states.parquet')
            """).fetchone()
            # This should work for public buckets via HTTPS
            assert result is not None
            assert result[0] > 0
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "403" in error_str or "404" in error_str:
                pytest.skip("Public GCS bucket not accessible or data moved")
            if "credentials" in error_str or "authentication" in error_str:
                # Some public buckets still need valid GCP credentials
                pytest.skip("GCS requires credentials even for public buckets")
            raise


@pytest.mark.cloud
@pytest.mark.gcp
@skip_unless_gcp
class TestGCSLazyAttach:
    """Test GCS lazy attachment."""

    def test_lazy_attach_gcs(self, duckdb_conn):
        """Test GCS lazy attach with bucket config."""
        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.lazy_attach import LazyAttachManager

        # Use a well-known public bucket or skip if no bucket available
        test_bucket = os.environ.get("TEST_GCS_BUCKET", "cloud-samples-data")

        config = SqlConnectionConfig(
            connection_name="gcs_test",
            type="gcs",
            bucket=test_bucket,
            prefix="langtech/",
            file_pattern="*.json",
            read_only=True,
        )

        manager = LazyAttachManager(duckdb_conn, {"gcs_test": config})

        try:
            # This should trigger GCS schema creation
            manager.ensure_for_query("SELECT * FROM gcs_test.bard")

            # Verify schema was created
            schemas = duckdb_conn.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'gcs_test'"
            ).fetchall()
            assert len(schemas) == 1, "gcs_test schema should exist"

        except Exception as e:
            error_str = str(e).lower()
            if "credentials" in error_str or "authentication" in error_str:
                pytest.skip("GCS authentication required")
            if "not found" in error_str or "403" in error_str:
                pytest.skip("GCS bucket or file not accessible")
            raise


@pytest.mark.cloud
@pytest.mark.gcp
@skip_unless_gcp
class TestGCSDatabaseConnector:
    """Test GCS via DatabaseConnector interface."""

    def test_connector_gcs_with_own_bucket(self):
        """Test GCS attachment with user's own bucket."""
        # This test requires a real bucket that the user has access to
        bucket_name = os.environ.get("TEST_GCS_BUCKET")
        if not bucket_name:
            pytest.skip("TEST_GCS_BUCKET not set - provide your own GCS bucket for testing")

        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.connector import DatabaseConnector

        connector = DatabaseConnector(use_cache=False)

        try:
            config = SqlConnectionConfig(
                connection_name="gcs_conn_test",
                type="gcs",
                bucket=bucket_name,
                file_pattern="*.parquet",
                read_only=True,
            )

            # Try to attach GCS
            connector._attach_gcs(config, "gcs_conn_test")

            # Verify schema was created - use raw conn to get fetchall
            result = connector.conn.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'gcs_conn_test'"
            ).fetchall()
            assert len(result) > 0, "GCS schema should be created"

        except Exception as e:
            error_str = str(e).lower()
            if "credentials" in error_str or "authentication" in error_str:
                pytest.skip("GCS authentication failed")
            raise
        finally:
            connector.close()


@pytest.mark.cloud
@pytest.mark.gcp
@skip_unless_gcp
class TestGoogleCredentialsResolver:
    """Test the Google credentials resolver in detail."""

    def test_resolver_caching(self, tmp_path):
        """Test that credential resolver caches results."""
        from lars.sql_tools.config import resolve_google_credentials, _google_creds_cache

        # Create fake credentials
        creds_file = tmp_path / "cached_creds.json"
        creds_file.write_text('{"type": "service_account"}')
        os.environ["TEST_CACHE_CREDS"] = str(creds_file)

        try:
            # Clear cache for this test
            _google_creds_cache.pop("TEST_CACHE_CREDS", None)

            # First call
            result1 = resolve_google_credentials("TEST_CACHE_CREDS")
            assert "TEST_CACHE_CREDS" in _google_creds_cache

            # Second call should use cache
            result2 = resolve_google_credentials("TEST_CACHE_CREDS")
            assert result1 == result2

        finally:
            del os.environ["TEST_CACHE_CREDS"]
            _google_creds_cache.pop("TEST_CACHE_CREDS", None)

    def test_resolver_invalid_json(self):
        """Test that resolver handles invalid JSON gracefully."""
        from lars.sql_tools.config import resolve_google_credentials, _google_creds_cache

        # Set env var to invalid JSON (starts with { but isn't valid)
        os.environ["TEST_INVALID_JSON"] = "{not valid json"

        try:
            _google_creds_cache.pop("TEST_INVALID_JSON", None)

            # Should return the value as-is (treated as file path)
            result = resolve_google_credentials("TEST_INVALID_JSON")
            assert result == "{not valid json"

        finally:
            del os.environ["TEST_INVALID_JSON"]
            _google_creds_cache.pop("TEST_INVALID_JSON", None)

    def test_resolver_empty_env_var(self):
        """Test that resolver handles empty/missing env vars."""
        from lars.sql_tools.config import resolve_google_credentials

        # Non-existent env var
        result = resolve_google_credentials("DEFINITELY_NOT_SET_ENV_VAR_12345")
        assert result is None

        # Empty env var
        os.environ["TEST_EMPTY"] = ""
        try:
            result = resolve_google_credentials("TEST_EMPTY")
            assert result is None
        finally:
            del os.environ["TEST_EMPTY"]
