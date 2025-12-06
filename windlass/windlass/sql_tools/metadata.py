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
        """
        alias = config.connection_name

        if config.type == "csv_folder":
            # For CSV folders, each file is a "table" in the alias schema
            schemas = self.conn.list_csv_schemas(alias)
            return [(alias, schema) for schema in schemas]

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

        # Build qualified table name
        if config.type == "csv_folder":
            # For CSV: csv_files.bigfoot_sightings
            full_table_name = f"{alias}.{table_name}"
            display_schema = alias
        elif schema:
            full_table_name = f"{alias}.{schema}.{table_name}"
            display_schema = schema
        else:
            full_table_name = f"{alias}.{table_name}"
            display_schema = None

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

            # Get sample rows
            sample_sql = f"SELECT * FROM {full_table_name} LIMIT {config.sample_row_limit}"
            sample_df = self.conn.fetch_df(sample_sql)
            sample_rows = sample_df.to_dict('records')

            return {
                "table_name": table_name,
                "schema": display_schema,
                "database": config.connection_name,
                "row_count": row_count,
                "columns": columns,
                "sample_rows": sample_rows
            }

        except Exception as e:
            print(f"    ⚠️  Error extracting metadata for {full_table_name}: {str(e)[:100]}")
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
