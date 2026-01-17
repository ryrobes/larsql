"""
Table metadata extraction with rich statistics and distributions.
"""

from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

from .connector import DatabaseConnector, sanitize_name
from .config import SqlConnectionConfig


class TableMetadata:
    """Extract and format table metadata."""

    def __init__(self, connector: DatabaseConnector):
        self.conn = connector

    def get_tables(self, config: SqlConnectionConfig) -> List[Tuple[Optional[str], str]]:
        """
        List all tables in database.

        Returns:
            List of (schema, table_name) tuples
            - For duckdb_folder: schema is "db_name" (e.g., "market_research")
            - For csv_folder: schema is the alias (e.g., "csv_files")
            - For databases: schema is the actual schema (e.g., "public")
        """
        alias = config.connection_name

        if config.type == "csv_folder":
            # For CSV folders, each file is a "table" in the alias schema
            schemas = self.conn.list_csv_schemas(alias)
            return [(alias, schema) for schema in schemas]

        elif config.type == "duckdb_folder":
            # For DuckDB folders, each .duckdb file is a separate attached database
            # Returns: [(db_name, table_name), ...]
            # DuckDB files have tables in db_name.main.table_name structure
            tables = []
            db_names = self.conn.list_duckdb_schemas(alias)
            for db_name in db_names:
                try:
                    # Use duckdb_tables() function instead of information_schema
                    sql = f"""
                        SELECT table_name
                        FROM duckdb_tables()
                        WHERE database_name = '{db_name}'
                        ORDER BY table_name
                    """
                    rows = self.conn.fetch_all(sql)
                    for row in rows:
                        tables.append((db_name, row[0]))
                except Exception as e:
                    print(f"    [WARN]  Failed to list tables in {db_name}: {str(e)[:100]}")
            return tables

        elif config.type == "postgres":
            sql = f"""
                SELECT table_schema, table_name
                FROM {alias}.information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                  AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name
            """
            rows = self.conn.fetch_all(sql)
            return [(row[0], row[1]) for row in rows]

        elif config.type == "mysql":
            sql = f"""
                SELECT table_schema, table_name
                FROM {alias}.information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'mysql', 'performance_schema')
                  AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name
            """
            rows = self.conn.fetch_all(sql)
            return [(row[0], row[1]) for row in rows]

        elif config.type == "sqlite":
            sql = f"SELECT name FROM {alias}.sqlite_master WHERE type='table'"
            rows = self.conn.fetch_all(sql)
            return [(None, row[0]) for row in rows]

        elif config.type == "duckdb":
            # For attached DuckDB files, query duckdb_tables() filtered by database
            sql = f"""
                SELECT table_name
                FROM duckdb_tables()
                WHERE database_name = '{alias}'
                  AND schema_name = 'main'
            """
            rows = self.conn.fetch_all(sql)
            return [(None, row[0]) for row in rows]

        # === Cloud Database Types ===
        elif config.type == "bigquery":
            # BigQuery attaches as a database
            # Use SHOW TABLES which works with BigQuery extension
            # Note: This doesn't give us dataset info, tables appear flat
            sql = f"SHOW TABLES FROM {alias}"
            try:
                rows = self.conn.fetch_all(sql)
                # SHOW TABLES returns (name,) tuples - deduplicate
                seen = set()
                tables = []
                for row in rows:
                    table_name = row[0]
                    if table_name not in seen:
                        seen.add(table_name)
                        tables.append((None, table_name))
                return tables
            except Exception as e:
                print(f"    [WARN]  Failed to list BigQuery tables: {str(e)[:80]}")
                return []

        elif config.type == "snowflake":
            # Snowflake attaches as a database
            sql = f"""
                SELECT table_schema, table_name
                FROM {alias}.information_schema.tables
                WHERE table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name
            """
            try:
                rows = self.conn.fetch_all(sql)
                return [(row[0], row[1]) for row in rows]
            except Exception as e:
                print(f"    [WARN]  Failed to list Snowflake tables: {str(e)[:80]}")
                return []

        elif config.type == "motherduck":
            # Motherduck uses DuckDB's table listing
            sql = f"""
                SELECT schema_name, table_name
                FROM duckdb_tables()
                WHERE database_name = '{alias}'
                ORDER BY schema_name, table_name
            """
            try:
                rows = self.conn.fetch_all(sql)
                return [(row[0], row[1]) for row in rows]
            except Exception as e:
                print(f"    [WARN]  Failed to list Motherduck tables: {str(e)[:80]}")
                return []

        # === Remote Filesystem Types (create views in a schema) ===
        elif config.type in ("s3", "azure", "gcs", "http"):
            # These create VIEWS in a schema named {alias}
            # Use duckdb_views() since S3 files are registered as views
            sql = f"""
                SELECT view_name
                FROM duckdb_views()
                WHERE schema_name = '{alias}'
                ORDER BY view_name
            """
            try:
                rows = self.conn.fetch_all(sql)
                return [(alias, row[0]) for row in rows]
            except Exception as e:
                print(f"    [WARN]  Failed to list {config.type} views: {str(e)[:80]}")
                return []

        # === Materialized Types (create tables in a schema) ===
        elif config.type in ("mongodb", "cassandra"):
            # These materialize collections/tables into a DuckDB schema
            # Use duckdb_tables() to avoid routing through attached databases
            sql = f"""
                SELECT table_name
                FROM duckdb_tables()
                WHERE schema_name = '{alias}'
                ORDER BY table_name
            """
            try:
                rows = self.conn.fetch_all(sql)
                return [(alias, row[0]) for row in rows]
            except Exception as e:
                print(f"    [WARN]  Failed to list {config.type} tables: {str(e)[:80]}")
                return []

        # === Scanner Types (create views in a schema) ===
        elif config.type in ("excel", "gsheets"):
            # These create VIEWS for sheets
            # Use duckdb_views() since these are registered as views
            sql = f"""
                SELECT view_name
                FROM duckdb_views()
                WHERE schema_name = '{alias}'
                ORDER BY view_name
            """
            try:
                rows = self.conn.fetch_all(sql)
                return [(alias, row[0]) for row in rows]
            except Exception as e:
                print(f"    [WARN]  Failed to list {config.type} views: {str(e)[:80]}")
                return []

        elif config.type == "odbc":
            # ODBC requires manual table discovery - skip for now
            print(f"    [WARN]  ODBC table discovery not implemented - use manual queries")
            return []

        # === Lakehouse Types ===
        elif config.type in ("delta", "iceberg"):
            # These create VIEWS in a schema
            # Use duckdb_views() since these are registered as views
            sql = f"""
                SELECT view_name
                FROM duckdb_views()
                WHERE schema_name = '{alias}'
                ORDER BY view_name
            """
            try:
                rows = self.conn.fetch_all(sql)
                return [(alias, row[0]) for row in rows]
            except Exception as e:
                print(f"    [WARN]  Failed to list {config.type} views: {str(e)[:80]}")
                return []

        # === ClickHouse (materialized into DuckDB schema) ===
        elif config.type == "clickhouse":
            # ClickHouse tables are materialized into a DuckDB schema
            # Use duckdb_tables() to list them
            sql = f"""
                SELECT table_name
                FROM duckdb_tables()
                WHERE schema_name = '{alias}'
                ORDER BY table_name
            """
            try:
                rows = self.conn.fetch_all(sql)
                return [(alias, row[0]) for row in rows]
            except Exception as e:
                print(f"    [WARN]  Failed to list ClickHouse tables: {str(e)[:80]}")
                return []

        else:
            raise ValueError(f"Unsupported database type: {config.type}")

    def extract_table_metadata(
        self,
        config: SqlConnectionConfig,
        schema: Optional[str],
        table_name: str
    ) -> Dict[str, Any]:
        """
        Extract comprehensive metadata for a single table.

        Returns:
        {
          "table_name": "users",
          "schema": "public",
          "database": "prod_db",
          "row_count": 12500,
          "columns": [
            {
              "name": "country",
              "type": "VARCHAR(50)",
              "nullable": true,
              "metadata": {
                "distinct_count": 50,
                "value_distribution": [
                  {"value": "USA", "count": 8234, "percentage": 67.2},
                  ...
                ]
              }
            }
          ],
          "sample_rows": [...]
        }
        """
        alias = config.connection_name

        # Build qualified table name based on connection type
        if config.type == "csv_folder":
            # For CSV: csv_files.bigfoot_sightings
            full_table_name = f"{alias}.{table_name}"
            display_schema = alias

        elif config.type == "duckdb_folder":
            # For DuckDB folder: schema is db_name (e.g., "market_research")
            # Query: market_research.table_name (direct, since db is attached)
            full_table_name = f"{schema}.{table_name}"
            display_schema = schema  # db_name

        elif config.type == "duckdb":
            # For single DuckDB file: alias.table_name
            full_table_name = f"{alias}.{table_name}"
            display_schema = alias

        elif config.type in ("s3", "azure", "gcs", "http", "mongodb", "cassandra",
                             "excel", "gsheets", "delta", "iceberg", "clickhouse"):
            # These create views/tables in a schema named after the alias
            # Query: alias.table_name
            full_table_name = f"{alias}.{table_name}"
            display_schema = alias

        elif config.type in ("bigquery", "snowflake", "motherduck"):
            # Cloud databases attach as databases - schema is the dataset/schema
            if schema and schema != alias:
                full_table_name = f"{alias}.{schema}.{table_name}"
                display_schema = schema
            else:
                full_table_name = f"{alias}.{table_name}"
                display_schema = None

        elif schema:
            # Default: alias.schema.table
            full_table_name = f"{alias}.{schema}.{table_name}"
            display_schema = schema
        else:
            full_table_name = f"{alias}.{table_name}"
            display_schema = None

        # For remote filesystem types, re-apply credentials before querying
        if config.type == "s3":
            self._ensure_s3_credentials(config)
        elif config.type == "gcs":
            self._ensure_gcs_credentials(config)
        elif config.type == "azure":
            self._ensure_azure_credentials(config)

        # BigQuery uses Storage Read API which requires special permissions
        # Fall back to schema-only extraction if data access fails
        if config.type == "bigquery":
            return self._extract_bigquery_metadata(config, full_table_name, table_name, display_schema)

        try:
            # Get row count
            row_count_sql = f"SELECT COUNT(*) as cnt FROM {full_table_name}"
            row_count = self.conn.fetch_one(row_count_sql)[0]

            # Get column info with metadata
            columns = self._extract_column_metadata(
                full_table_name,
                config.distinct_value_threshold,
                row_count
            )

            # Get sample rows in compact array-of-arrays format
            sample_sql = f"SELECT * FROM {full_table_name} LIMIT {config.sample_row_limit}"
            sample_df = self.conn.fetch_df(sample_sql)

            # Convert to array-of-arrays (columns defined once, rows are just value arrays)
            sample_columns = list(sample_df.columns)
            sample_rows = sample_df.values.tolist()

            return {
                "table_name": table_name,
                "schema": display_schema,
                "database": config.connection_name,
                "row_count": row_count,
                "columns": columns,
                "sample_columns": sample_columns,  # Column names (defined once)
                "sample_rows": sample_rows  # Array of arrays (no repeated keys!)
            }

        except Exception as e:
            print(f"    [WARN]  Error extracting metadata for {full_table_name}: {str(e)[:100]}")
            return None

    def _extract_column_metadata(
        self,
        full_table_name: str,
        threshold: int,
        total_rows: int
    ) -> List[Dict[str, Any]]:
        """Extract metadata for all columns including distributions."""

        # Get column names and types via DESCRIBE
        desc_sql = f"DESCRIBE {full_table_name}"
        desc_df = self.conn.fetch_df(desc_sql)

        columns = []
        for _, col_row in desc_df.iterrows():
            col_name = col_row['column_name']
            col_type = col_row['column_type']
            nullable = col_row.get('null', 'YES') == 'YES'

            # Skip if column name is problematic (contains special chars that break SQL)
            try:
                # Get distinct count
                distinct_sql = f'SELECT COUNT(DISTINCT "{col_name}") as cnt FROM {full_table_name}'
                distinct_count = self.conn.fetch_one(distinct_sql)[0]
            except Exception:
                # Skip this column if we can't query it
                continue

            metadata = {
                "distinct_count": distinct_count
            }

            # Low-cardinality: get value distribution with counts
            if distinct_count < threshold and distinct_count > 0:
                try:
                    dist_sql = f"""
                        SELECT
                            "{col_name}" as value,
                            COUNT(*) as count,
                            ROUND(100.0 * COUNT(*) / {total_rows}, 2) as percentage
                        FROM {full_table_name}
                        GROUP BY "{col_name}"
                        ORDER BY count DESC
                        LIMIT 100
                    """
                    dist_df = self.conn.fetch_df(dist_sql)
                    metadata["value_distribution"] = dist_df.to_dict('records')
                except Exception:
                    pass  # Skip distribution if query fails

            else:
                # High-cardinality: get min/max for numeric/date types
                if any(t in col_type.upper() for t in ['INT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC', 'DATE', 'TIME']):
                    try:
                        minmax_sql = f'SELECT MIN("{col_name}") as min_val, MAX("{col_name}") as max_val FROM {full_table_name}'
                        minmax = self.conn.fetch_one(minmax_sql)
                        if minmax[0] is not None:
                            metadata["min"] = str(minmax[0])
                        if minmax[1] is not None:
                            metadata["max"] = str(minmax[1])
                    except Exception:
                        pass

            columns.append({
                "name": col_name,
                "type": col_type,
                "nullable": nullable,
                "metadata": metadata
            })

        return columns

    def _ensure_s3_credentials(self, config: SqlConnectionConfig) -> None:
        """Re-apply S3 credentials before querying S3-backed views."""
        import os

        try:
            self.conn.execute("LOAD httpfs;")
        except Exception:
            pass

        if config.access_key_env:
            access_key = os.getenv(config.access_key_env, "")
            if access_key:
                self.conn.execute(f"SET s3_access_key_id='{access_key}';")

        if config.secret_key_env:
            secret_key = os.getenv(config.secret_key_env, "")
            if secret_key:
                self.conn.execute(f"SET s3_secret_access_key='{secret_key}';")

        if config.region:
            self.conn.execute(f"SET s3_region='{config.region}';")

        if config.endpoint_url:
            self.conn.execute(f"SET s3_endpoint='{config.endpoint_url.replace('http://', '').replace('https://', '')}';")
            self.conn.execute("SET s3_url_style='path';")
            # Disable SSL for local endpoints
            if 'localhost' in config.endpoint_url or '127.0.0.1' in config.endpoint_url:
                self.conn.execute("SET s3_use_ssl=false;")

    def _ensure_gcs_credentials(self, config: SqlConnectionConfig) -> None:
        """Re-apply GCS credentials before querying GCS-backed views."""
        from .config import resolve_google_credentials

        try:
            self.conn.execute("LOAD httpfs;")
        except Exception:
            pass

        # Resolve credentials (handles JSON string → temp file)
        creds_path = resolve_google_credentials(config.credentials_env or "GOOGLE_APPLICATION_CREDENTIALS")
        if creds_path:
            self.conn.execute(f"SET gcs_credentials_file='{creds_path}';")

    def _ensure_azure_credentials(self, config: SqlConnectionConfig) -> None:
        """Re-apply Azure credentials before querying Azure-backed views."""
        import os

        try:
            self.conn.execute("LOAD azure;")
        except Exception:
            pass

        if config.connection_string_env:
            conn_str = os.getenv(config.connection_string_env, "")
            if conn_str:
                self.conn.execute(f"SET azure_storage_connection_string='{conn_str}';")

    def _extract_bigquery_metadata(
        self,
        config: SqlConnectionConfig,
        full_table_name: str,
        table_name: str,
        display_schema: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Extract BigQuery metadata using schema-only approach.

        BigQuery's Storage Read API requires additional permissions that may not
        be available. This method falls back to DESCRIBE for schema info and
        skips row counts/samples if data access fails.
        """
        try:
            # Try DESCRIBE first - this often works even without Storage API
            desc_sql = f"DESCRIBE {full_table_name}"
            desc_df = self.conn.fetch_df(desc_sql)

            columns = []
            for _, col_row in desc_df.iterrows():
                col_name = col_row['column_name']
                col_type = col_row['column_type']
                nullable = col_row.get('null', 'YES') == 'YES'

                columns.append({
                    "name": col_name,
                    "type": col_type,
                    "nullable": nullable,
                    "metadata": {}  # Skip detailed metadata for BigQuery
                })

            # Try to get row count and samples, but don't fail if it doesn't work
            row_count = None
            sample_columns = []
            sample_rows = []

            try:
                row_count_sql = f"SELECT COUNT(*) as cnt FROM {full_table_name}"
                row_count = self.conn.fetch_one(row_count_sql)[0]

                sample_sql = f"SELECT * FROM {full_table_name} LIMIT {config.sample_row_limit}"
                sample_df = self.conn.fetch_df(sample_sql)
                sample_columns = list(sample_df.columns)
                sample_rows = sample_df.values.tolist()
            except Exception:
                # Storage API not available - that's OK, we have schema info
                pass

            return {
                "table_name": table_name,
                "schema": display_schema,
                "database": config.connection_name,
                "row_count": row_count,
                "columns": columns,
                "sample_columns": sample_columns,
                "sample_rows": sample_rows
            }

        except Exception as e:
            print(f"    [WARN]  Error extracting BigQuery metadata for {full_table_name}: {str(e)[:100]}")
            return None
