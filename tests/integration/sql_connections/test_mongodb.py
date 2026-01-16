"""
MongoDB integration tests for sql_tools.

Tests MongoDB connections via materialization into DuckDB.

Run with:
    pytest tests/integration/sql_connections/test_mongodb.py -v
"""

import os
import socket
import pytest


def is_mongodb_available() -> bool:
    """Check if MongoDB is running on localhost:27117."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect(("localhost", 27117))
        return True
    except (socket.timeout, socket.error):
        return False
    finally:
        sock.close()


skip_unless_mongodb = pytest.mark.skipif(
    not is_mongodb_available(),
    reason="MongoDB not available - start with: docker compose -f docker-compose.sql-tests.yml up -d"
)


@pytest.mark.docker
@skip_unless_mongodb
class TestMongoDBConnection:
    """Test MongoDB connector via materialization."""

    def test_mongodb_config_validation(self):
        """Test that MongoDB config validation works correctly."""
        from lars.sql_tools.config import SqlConnectionConfig, validate_connection_config

        # Valid config
        config = SqlConnectionConfig(
            connection_name="test_mongo",
            type="mongodb",
            mongodb_uri_env="TEST_MONGO_URI",
            database="testdb",
        )
        errors = validate_connection_config(config)
        assert len(errors) == 0, f"Unexpected validation errors: {errors}"

        # Missing mongodb_uri_env
        config_missing_uri = SqlConnectionConfig(
            connection_name="test_mongo",
            type="mongodb",
            database="testdb",
        )
        errors = validate_connection_config(config_missing_uri)
        assert any("mongodb_uri_env" in e for e in errors)

        # Missing database
        config_missing_db = SqlConnectionConfig(
            connection_name="test_mongo",
            type="mongodb",
            mongodb_uri_env="TEST_MONGO_URI",
        )
        errors = validate_connection_config(config_missing_db)
        assert any("database" in e for e in errors)

    def test_mongodb_direct_connection(self, mongodb_config):
        """Test direct MongoDB connection via pymongo."""
        try:
            from pymongo import MongoClient
        except ImportError:
            pytest.skip("pymongo not installed")

        client = MongoClient(mongodb_config['uri'], serverSelectionTimeoutMS=5000)
        db = client[mongodb_config['database']]

        # Test connection
        collections = db.list_collection_names()
        assert "customers" in collections, "customers collection should exist"
        assert "orders" in collections, "orders collection should exist"
        assert "products" in collections, "products collection should exist"

        # Test data
        customer_count = db.customers.count_documents({})
        assert customer_count > 0, "Expected customers in database"

        client.close()

    def test_mongodb_lazy_attach(self, duckdb_conn, mongodb_config):
        """Test MongoDB lazy attach with materialization."""
        try:
            from pymongo import MongoClient
            import pandas as pd
        except ImportError:
            pytest.skip("pymongo or pandas not installed")

        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.lazy_attach import LazyAttachManager

        # Set env var
        os.environ["TEST_MONGO_URI"] = mongodb_config['uri']

        config = SqlConnectionConfig(
            connection_name="mongo_test",
            type="mongodb",
            mongodb_uri_env="TEST_MONGO_URI",
            database=mongodb_config['database'],
            sample_row_limit=100,
        )

        try:
            manager = LazyAttachManager(duckdb_conn, {"mongo_test": config})

            # Trigger lazy attach
            manager.ensure_for_query("SELECT * FROM mongo_test.customers")

            # Verify schema was created
            schemas = duckdb_conn.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'mongo_test'"
            ).fetchall()
            assert len(schemas) == 1, "mongo_test schema should exist"

            # Verify tables were materialized
            tables = duckdb_conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'mongo_test'"
            ).fetchall()
            table_names = {t[0] for t in tables}
            assert "customers" in table_names, "customers table should be materialized"

            # Query the data
            result = duckdb_conn.execute(
                "SELECT COUNT(*) FROM mongo_test.customers"
            ).fetchone()
            assert result[0] > 0, "Expected rows in customers table"

        finally:
            del os.environ["TEST_MONGO_URI"]

    def test_mongodb_nested_documents(self, duckdb_conn, mongodb_config):
        """Test that nested MongoDB documents are flattened correctly."""
        try:
            from pymongo import MongoClient
            import pandas as pd
        except ImportError:
            pytest.skip("pymongo or pandas not installed")

        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.lazy_attach import LazyAttachManager

        os.environ["TEST_MONGO_URI"] = mongodb_config['uri']

        config = SqlConnectionConfig(
            connection_name="mongo_orders",
            type="mongodb",
            mongodb_uri_env="TEST_MONGO_URI",
            database=mongodb_config['database'],
            sample_row_limit=100,
        )

        try:
            manager = LazyAttachManager(duckdb_conn, {"mongo_orders": config})
            manager.ensure_for_query("SELECT * FROM mongo_orders.orders")

            # Orders have nested 'shipping' subdocument
            # The materialization should flatten it to shipping_method, shipping_address
            columns = duckdb_conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'mongo_orders' AND table_name = 'orders'"
            ).fetchall()
            column_names = {c[0] for c in columns}

            # Nested fields should be flattened with underscore
            assert "shipping_method" in column_names or "method" in column_names, \
                f"Expected flattened shipping fields, got: {column_names}"

        finally:
            del os.environ["TEST_MONGO_URI"]


@pytest.mark.docker
@skip_unless_mongodb
class TestMongoDBDatabaseConnector:
    """Test MongoDB via DatabaseConnector interface."""

    def test_connector_mongodb_attach(self, mongodb_config):
        """Test MongoDB attachment via DatabaseConnector."""
        try:
            from pymongo import MongoClient
            import pandas as pd
        except ImportError:
            pytest.skip("pymongo or pandas not installed")

        from lars.sql_tools.config import SqlConnectionConfig
        from lars.sql_tools.connector import DatabaseConnector

        os.environ["TEST_MONGO_URI"] = mongodb_config['uri']
        connector = None

        try:
            # Use in-memory connection to avoid file lock issues
            connector = DatabaseConnector(use_cache=False)

            config = SqlConnectionConfig(
                connection_name="mongo_conn_test",
                type="mongodb",
                mongodb_uri_env="TEST_MONGO_URI",
                database=mongodb_config['database'],
            )

            # This should materialize MongoDB collections
            connector._attach_mongodb(config, "mongo_conn_test")

            # Verify tables exist - use raw DuckDB query
            result = connector.conn.execute(
                "SELECT COUNT(*) as cnt FROM mongo_conn_test.customers"
            ).fetchone()
            assert result is not None
            assert result[0] > 0

        finally:
            del os.environ["TEST_MONGO_URI"]
            if connector:
                connector.close()
