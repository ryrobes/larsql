"""
RVBBIT Server - PostgreSQL wire protocol server.

Exposes RVBBIT DuckDB sessions with LLM UDFs to external SQL clients.
"""

from .postgres_server import start_postgres_server, RVBBITPostgresServer
from .postgres_protocol import (
    PostgresMessage,
    MessageType,
    AuthenticationOk,
    ParameterStatus,
    ReadyForQuery,
    RowDescription,
    DataRow,
    CommandComplete,
    ErrorResponse
)

__all__ = [
    'start_postgres_server',
    'RVBBITPostgresServer',
    'PostgresMessage',
    'MessageType'
]
