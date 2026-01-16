"""
LARS Client Library

Provides remote access to LARS DuckDB server with LLM UDFs.
"""

from .sql_client import LARSClient, execute_sql

__all__ = ['LARSClient', 'execute_sql']
