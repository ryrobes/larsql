"""
Windlass Client Library

Provides remote access to Windlass DuckDB server with LLM UDFs.
"""

from .sql_client import WindlassClient, execute_sql

__all__ = ['WindlassClient', 'execute_sql']
