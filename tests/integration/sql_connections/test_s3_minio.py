"""
S3/MinIO integration tests for sql_tools.

Tests S3-compatible storage connections using MinIO docker container.

Run with:
    pytest tests/integration/sql_connections/test_s3_minio.py -v
"""

import os
import socket
import pytest


def is_minio_available() -> bool:
    """Check if MinIO is running on localhost:9100."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect(("localhost", 9100))
        return True
    except (socket.timeout, socket.error):
        return False
    finally:
        sock.close()


skip_unless_minio = pytest.mark.skipif(
    not is_minio_available(),
    reason="MinIO not available - start with: docker compose -f docker-compose.sql-tests.yml up -d"
)


@pytest.mark.docker
@skip_unless_minio
class TestMinioS3Connection:
    """Test S3-compatible storage via MinIO."""

    def test_s3_settings_applied(self, duckdb_conn, minio_config):
        """Test that S3 settings are correctly applied to DuckDB."""
        # Install and load httpfs extension
        duckdb_conn.execute("INSTALL httpfs;")
        duckdb_conn.execute("LOAD httpfs;")

        # Apply S3 settings for MinIO
        duckdb_conn.execute(f"SET s3_region='{minio_config['region']}';")
        duckdb_conn.execute(f"SET s3_access_key_id='{minio_config['access_key']}';")
        duckdb_conn.execute(f"SET s3_secret_access_key='{minio_config['secret_key']}';")

        # Set endpoint for MinIO
        endpoint = minio_config['endpoint_url'].replace('http://', '')
        duckdb_conn.execute(f"SET s3_endpoint='{endpoint}';")
        duckdb_conn.execute("SET s3_url_style='path';")
        duckdb_conn.execute("SET s3_use_ssl=false;")

        # Verify settings are applied (these should not raise)
        result = duckdb_conn.execute("SELECT current_setting('s3_endpoint')").fetchone()
        assert result is not None

    def test_read_parquet_from_minio(self, duckdb_conn, minio_config):
        """Test reading parquet files from MinIO."""
        # Install and load httpfs extension
        duckdb_conn.execute("INSTALL httpfs;")
        duckdb_conn.execute("LOAD httpfs;")

        # Apply S3 settings for MinIO
        duckdb_conn.execute(f"SET s3_region='{minio_config['region']}';")
        duckdb_conn.execute(f"SET s3_access_key_id='{minio_config['access_key']}';")
        duckdb_conn.execute(f"SET s3_secret_access_key='{minio_config['secret_key']}';")

        endpoint = minio_config['endpoint_url'].replace('http://', '')
        duckdb_conn.execute(f"SET s3_endpoint='{endpoint}';")
        duckdb_conn.execute("SET s3_url_style='path';")
        duckdb_conn.execute("SET s3_use_ssl=false;")

        # Try to read parquet file (assumes setup_minio.py has been run)
        try:
            result = duckdb_conn.execute(
                "SELECT COUNT(*) FROM read_parquet('s3://test-data/parquet/sales.parquet')"
            ).fetchone()
            assert result is not None
            assert result[0] > 0, "Expected at least one row in sales data"
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                pytest.skip("Test data not uploaded - run: python tests/fixtures/setup_minio.py")
            raise

    def test_read_csv_from_minio(self, duckdb_conn, minio_config):
        """Test reading CSV files from MinIO."""
        duckdb_conn.execute("INSTALL httpfs;")
        duckdb_conn.execute("LOAD httpfs;")

        duckdb_conn.execute(f"SET s3_region='{minio_config['region']}';")
        duckdb_conn.execute(f"SET s3_access_key_id='{minio_config['access_key']}';")
        duckdb_conn.execute(f"SET s3_secret_access_key='{minio_config['secret_key']}';")

        endpoint = minio_config['endpoint_url'].replace('http://', '')
        duckdb_conn.execute(f"SET s3_endpoint='{endpoint}';")
        duckdb_conn.execute("SET s3_url_style='path';")
        duckdb_conn.execute("SET s3_use_ssl=false;")

        try:
            result = duckdb_conn.execute(
                "SELECT COUNT(*) FROM read_csv_auto('s3://test-data/csv/events.csv')"
            ).fetchone()
            assert result is not None
            assert result[0] > 0
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                pytest.skip("Test data not uploaded - run: python tests/fixtures/setup_minio.py")
            raise

    def test_glob_files_from_minio(self, duckdb_conn, minio_config):
        """Test globbing multiple files from MinIO."""
        duckdb_conn.execute("INSTALL httpfs;")
        duckdb_conn.execute("LOAD httpfs;")

        duckdb_conn.execute(f"SET s3_region='{minio_config['region']}';")
        duckdb_conn.execute(f"SET s3_access_key_id='{minio_config['access_key']}';")
        duckdb_conn.execute(f"SET s3_secret_access_key='{minio_config['secret_key']}';")

        endpoint = minio_config['endpoint_url'].replace('http://', '')
        duckdb_conn.execute(f"SET s3_endpoint='{endpoint}';")
        duckdb_conn.execute("SET s3_url_style='path';")
        duckdb_conn.execute("SET s3_use_ssl=false;")

        try:
            # Glob all parquet files
            result = duckdb_conn.execute(
                "SELECT * FROM glob('s3://test-data/parquet/*.parquet')"
            ).fetchall()
            assert len(result) >= 1, "Expected at least one parquet file"
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                pytest.skip("Test data not uploaded - run: python tests/fixtures/setup_minio.py")
            raise


@pytest.mark.docker
@skip_unless_minio
class TestSqlConnectionsS3:
    """Test S3 connector via SqlConnectionConfig."""

    def test_s3_config_with_endpoint_url(self, duckdb_conn, minio_config):
        """Test that SqlConnectionConfig correctly handles endpoint_url."""
        from lars.sql_tools.config import SqlConnectionConfig

        config = SqlConnectionConfig(
            connection_name="test_minio",
            type="s3",
            bucket="test-data",
            access_key_env="TEST_MINIO_ACCESS_KEY",
            secret_key_env="TEST_MINIO_SECRET_KEY",
            endpoint_url=minio_config['endpoint_url'],
            region="us-east-1",
        )

        assert config.endpoint_url == minio_config['endpoint_url']
        assert config.bucket == "test-data"

    def test_lazy_attach_s3(self, duckdb_conn, minio_config):
        """Test lazy attach manager with S3 config."""
        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.lazy_attach import LazyAttachManager

        # Set env vars for test
        os.environ["TEST_MINIO_ACCESS_KEY"] = minio_config['access_key']
        os.environ["TEST_MINIO_SECRET_KEY"] = minio_config['secret_key']

        config = SqlConnectionConfig(
            connection_name="test_s3",
            type="s3",
            bucket="test-data",
            prefix="parquet/",
            access_key_env="TEST_MINIO_ACCESS_KEY",
            secret_key_env="TEST_MINIO_SECRET_KEY",
            endpoint_url=minio_config['endpoint_url'],
            region="us-east-1",
            file_pattern="*.parquet",
        )

        manager = LazyAttachManager(duckdb_conn, {"test_s3": config})

        try:
            # This should trigger lazy attachment
            manager.ensure_for_query("SELECT * FROM test_s3.sales")

            # Schema should exist
            schemas = duckdb_conn.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'test_s3'"
            ).fetchall()
            assert len(schemas) == 1, "test_s3 schema should exist"

        except Exception as e:
            if "not found" in str(e).lower() or "does not exist" in str(e).lower():
                pytest.skip("Test data not uploaded - run: python tests/fixtures/setup_minio.py")
            raise
        finally:
            # Cleanup env vars
            del os.environ["TEST_MINIO_ACCESS_KEY"]
            del os.environ["TEST_MINIO_SECRET_KEY"]
