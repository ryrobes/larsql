"""
RVBBIT SQL Client - Query RVBBIT DuckDB server from Python.

This provides a pandas-like interface for executing SQL queries
with rvbbit_udf() and rvbbit_cascade_udf() from remote clients.

Usage:
    from rvbbit.client import RVBBITClient

    client = RVBBITClient('http://localhost:5001')

    # Execute SQL with LLM UDFs!
    df = client.execute('''
        SELECT
          product_name,
          rvbbit_udf('Extract brand', product_name) as brand
        FROM products
        LIMIT 10
    ''')

    print(df)
"""

import requests
import pandas as pd
from typing import Optional, Dict, Any, Union
import json


class RVBBITClient:
    """
    Client for querying RVBBIT DuckDB server via HTTP.

    Provides pandas-compatible interface for SQL execution with LLM UDFs.
    """

    def __init__(self, base_url: str = 'http://localhost:5001', session_id: Optional[str] = None):
        """
        Initialize RVBBIT SQL client.

        Args:
            base_url: RVBBIT server URL (default: http://localhost:5001)
            session_id: Optional session ID (default: auto-generated)
        """
        self.base_url = base_url.rstrip('/')
        self.session_id = session_id
        self._session_auto_generated = session_id is None

    def execute(self, query: str, session_id: Optional[str] = None, format: str = 'records') -> pd.DataFrame:
        """
        Execute SQL query and return results as pandas DataFrame.

        Args:
            query: SQL query to execute (can include rvbbit_udf, rvbbit_cascade_udf)
            session_id: Optional session ID override
            format: Response format ('records', 'json', 'csv')

        Returns:
            pandas DataFrame with query results

        Example:
            df = client.execute('''
                SELECT
                  product_name,
                  rvbbit_udf('Extract brand', product_name) as brand,
                  rvbbit_cascade_udf('tackle/fraud.yaml',
                                      json_object('id', product_id)) as fraud_check
                FROM products
                LIMIT 100
            ''')
        """
        # Use provided session_id, or instance session_id, or auto-generate
        import uuid
        sess_id = session_id or self.session_id or f"client_{uuid.uuid4().hex[:8]}"

        # Make request
        response = requests.post(
            f'{self.base_url}/api/sql/execute',
            json={
                'query': query,
                'session_id': sess_id,
                'format': format
            },
            timeout=600  # 10 minute timeout for long-running cascades
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get('error', 'Unknown error')
            raise Exception(f"Query failed: {error_msg}")

        # Parse response
        data = response.json()

        # Store session ID if it was auto-generated
        if self._session_auto_generated:
            self.session_id = data.get('session_id')

        # Convert to DataFrame
        if format == 'csv':
            import io
            return pd.read_csv(io.StringIO(response.text))
        else:
            return pd.DataFrame(data['data'])

    def read_sql(self, query: str, **kwargs) -> pd.DataFrame:
        """
        pandas.read_sql compatible interface.

        Args:
            query: SQL query
            **kwargs: Additional arguments (session_id, format)

        Returns:
            pandas DataFrame

        Example:
            df = client.read_sql("SELECT * FROM customers LIMIT 10")
        """
        return self.execute(query, **kwargs)

    def list_sessions(self) -> pd.DataFrame:
        """
        List all active DuckDB sessions.

        Returns:
            DataFrame with session_id, table_count, tables columns
        """
        response = requests.get(f'{self.base_url}/api/sql/sessions')
        data = response.json()

        return pd.DataFrame(data['sessions'])

    def list_tables(self, session_id: Optional[str] = None) -> pd.DataFrame:
        """
        List tables in a session.

        Args:
            session_id: Session ID (default: current session)

        Returns:
            DataFrame with table info
        """
        sess_id = session_id or self.session_id

        if not sess_id:
            raise ValueError("No session_id available. Execute a query first or provide session_id.")

        response = requests.get(f'{self.base_url}/api/sql/tables/{sess_id}')
        data = response.json()

        return pd.DataFrame(data['tables'])

    def get_schema(self, table_name: str, session_id: Optional[str] = None) -> pd.DataFrame:
        """
        Get schema for a table.

        Args:
            table_name: Table name
            session_id: Session ID (default: current session)

        Returns:
            DataFrame with column info
        """
        sess_id = session_id or self.session_id

        if not sess_id:
            raise ValueError("No session_id available. Execute a query first or provide session_id.")

        response = requests.get(f'{self.base_url}/api/sql/schema/{sess_id}/{table_name}')
        data = response.json()

        return pd.DataFrame(data['columns'])

    def attach(self, connection_string: str, alias: str):
        """
        Attach external database to current session.

        Args:
            connection_string: Database connection string
            alias: Alias for the attached database

        Example:
            client.attach('postgres://user:pass@host/db', 'prod')
            df = client.execute('SELECT * FROM prod.customers LIMIT 10')
        """
        # Detect database type from connection string
        if connection_string.startswith('postgres'):
            db_type = 'POSTGRES'
        elif connection_string.startswith('mysql'):
            db_type = 'MYSQL'
        elif connection_string.startswith('sqlite'):
            db_type = 'SQLITE'
        else:
            db_type = None

        # Build ATTACH statement
        if db_type:
            attach_query = f"ATTACH '{connection_string}' AS {alias} (TYPE {db_type})"
        else:
            attach_query = f"ATTACH '{connection_string}' AS {alias}"

        # Execute attach
        self.execute(attach_query)

        print(f"✓ Attached database as '{alias}'")

    def health_check(self) -> Dict[str, Any]:
        """
        Check if RVBBIT server is healthy and UDFs are registered.

        Returns:
            Dict with status, version, UDF registration status
        """
        response = requests.get(f'{self.base_url}/api/sql/health')
        return response.json()


# Convenience function for quick usage
def execute_sql(query: str, base_url: str = 'http://localhost:5001') -> pd.DataFrame:
    """
    Quick one-off query execution.

    Args:
        query: SQL query
        base_url: RVBBIT server URL

    Returns:
        pandas DataFrame

    Example:
        from rvbbit.client import execute_sql

        df = execute_sql("SELECT rvbbit_udf('Extract brand', 'Apple iPhone') as brand")
        print(df)
    """
    client = RVBBITClient(base_url)
    return client.execute(query)
