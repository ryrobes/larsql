"""
RVBBIT Client Library

Provides remote access to RVBBIT DuckDB server with LLM UDFs.
"""

from .sql_client import RVBBITClient, execute_sql

__all__ = ['RVBBITClient', 'execute_sql']
