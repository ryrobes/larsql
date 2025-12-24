"""
Windlass Server - PostgreSQL wire protocol server.

Exposes Windlass DuckDB sessions with LLM UDFs to external SQL clients.
"""

from .postgres_server import start_postgres_server, WindlassPostgresServer
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
    'WindlassPostgresServer',
    'PostgresMessage',
    'MessageType'
]
