"""
PostgreSQL wire protocol message encoding/decoding.

Implements the minimal subset of PostgreSQL protocol needed for:
- Client connections (Startup, AuthenticationOk)
- Simple query execution (Query, RowDescription, DataRow, CommandComplete)
- Clean disconnection (Terminate)

Reference: https://www.postgresql.org/docs/current/protocol-message-formats.html

For v1, we implement Simple Query Protocol (not Extended Query with prepared statements).
This is sufficient for 95% of SQL tools (DBeaver, psql, DataGrip, Tableau).
"""

import struct
from typing import Tuple, Optional, List, Any


class MessageType:
    """PostgreSQL message type codes (single-byte identifiers)."""
    # Client → Server
    QUERY = ord('Q')
    TERMINATE = ord('X')
    PARSE = ord('P')      # Extended query
    BIND = ord('B')       # Extended query
    DESCRIBE = ord('D')   # Extended query
    EXECUTE = ord('E')    # Extended query
    CLOSE = ord('C')      # Extended query
    SYNC = ord('S')       # Extended query
    FLUSH = ord('H')      # Extended query (optional)

    # Server → Client
    AUTHENTICATION = ord('R')
    PARAMETER_STATUS = ord('S')
    BACKEND_KEY_DATA = ord('K')
    READY_FOR_QUERY = ord('Z')
    ROW_DESCRIPTION = ord('T')
    DATA_ROW = ord('D')
    COMMAND_COMPLETE = ord('C')
    ERROR_RESPONSE = ord('E')
    NOTICE_RESPONSE = ord('N')


class PostgresMessage:
    """Base class for PostgreSQL wire protocol messages."""

    @staticmethod
    def read_message(sock) -> Tuple[Optional[int], bytes]:
        """
        Read one message from socket.

        PostgreSQL message format:
        [1 byte: type] [4 bytes: length (includes itself)] [N bytes: payload]

        Returns:
            (message_type, payload) or (None, b'') on error/disconnect
        """
        try:
            # Read message type (1 byte)
            type_byte = sock.recv(1)
            if not type_byte or len(type_byte) == 0:
                return None, b''  # Connection closed

            msg_type = type_byte[0]

            # Read length (4 bytes, network byte order = big-endian)
            length_bytes = sock.recv(4)
            if len(length_bytes) < 4:
                return None, b''

            length = struct.unpack('!I', length_bytes)[0]

            # Length includes the 4 bytes of the length field itself
            # So payload length = length - 4
            payload_length = length - 4

            # Read payload
            payload = b''
            while len(payload) < payload_length:
                chunk = sock.recv(payload_length - len(payload))
                if not chunk:
                    return None, b''  # Connection closed mid-message
                payload += chunk

            return msg_type, payload

        except Exception as e:
            print(f"[Protocol] Error reading message: {e}")
            return None, b''

    @staticmethod
    def read_startup_message(sock) -> Optional[dict]:
        """
        Read startup message (special case - no type byte).

        Startup message format:
        [4 bytes: length] [4 bytes: protocol version] [key=value pairs, null-terminated]

        Protocol version: 196608 (0x00030000) for PostgreSQL 3.0
        SSL request: 80877103 (0x04d2162f)

        Returns:
            {'protocol': version, 'params': {'user': '...', 'database': '...'}}
            OR {'ssl_request': True} if client is requesting SSL
        """
        try:
            # Read length (first 4 bytes)
            length_bytes = sock.recv(4)
            if len(length_bytes) < 4:
                return None

            length = struct.unpack('!I', length_bytes)[0]
            payload_length = length - 4

            # Read entire payload
            payload = b''
            while len(payload) < payload_length:
                chunk = sock.recv(payload_length - len(payload))
                if not chunk:
                    return None
                payload += chunk

            # Parse protocol version (first 4 bytes of payload)
            protocol = struct.unpack('!I', payload[:4])[0]

            # Check for SSL request (special protocol number)
            SSL_REQUEST_CODE = 80877103  # 0x04d2162f
            if protocol == SSL_REQUEST_CODE:
                return {'ssl_request': True}

            # Parse key-value pairs (rest of payload)
            # Format: key\0value\0key\0value\0\0 (double null terminates)
            params = {}
            data = payload[4:]

            while data and data != b'\x00':
                # Read key
                null_idx = data.find(b'\x00')
                if null_idx == -1 or null_idx == 0:
                    break

                key = data[:null_idx].decode('utf-8')
                data = data[null_idx + 1:]

                # Read value
                null_idx = data.find(b'\x00')
                if null_idx == -1:
                    break

                value = data[:null_idx].decode('utf-8')
                data = data[null_idx + 1:]

                params[key] = value

            return {
                'protocol': protocol,
                'params': params
            }

        except Exception as e:
            print(f"[Protocol] Error reading startup: {e}")
            return None

    @staticmethod
    def build_message(msg_type: int, payload: bytes) -> bytes:
        """
        Build a PostgreSQL message.

        Args:
            msg_type: Message type code (single byte)
            payload: Message payload

        Returns:
            Complete message: [type][length][payload]
        """
        length = len(payload) + 4  # Length includes the 4-byte length field
        return bytes([msg_type]) + struct.pack('!I', length) + payload


# ============================================================================
# Server → Client Messages
# ============================================================================

class AuthenticationOk:
    """AuthenticationOk message - sent after successful authentication."""

    @staticmethod
    def encode() -> bytes:
        """
        Build AuthenticationOk message.

        Payload: [4 bytes: 0] (0 = AuthenticationOk, no password needed)
        """
        payload = struct.pack('!I', 0)  # Auth type 0 = success
        return PostgresMessage.build_message(MessageType.AUTHENTICATION, payload)


class ParameterStatus:
    """ParameterStatus message - server configuration parameters."""

    @staticmethod
    def encode(name: str, value: str) -> bytes:
        """
        Build ParameterStatus message.

        Args:
            name: Parameter name (e.g., 'client_encoding')
            value: Parameter value (e.g., 'UTF8')
        """
        payload = name.encode('utf-8') + b'\x00' + value.encode('utf-8') + b'\x00'
        return PostgresMessage.build_message(ord('S'), payload)


class ReadyForQuery:
    """ReadyForQuery message - server is ready for next command."""

    @staticmethod
    def encode(status: str = 'I') -> bytes:
        """
        Build ReadyForQuery message.

        Args:
            status: Transaction status
                - 'I' = idle (not in transaction)
                - 'T' = in transaction block
                - 'E' = failed transaction
        """
        payload = status.encode('utf-8')
        return PostgresMessage.build_message(MessageType.READY_FOR_QUERY, payload)


class RowDescription:
    """RowDescription message - column metadata for query results."""

    # PostgreSQL type OIDs
    # Reference: https://www.postgresql.org/docs/current/datatype.html
    TYPES = {
        'BIGINT': 20,
        'INTEGER': 23,
        'SMALLINT': 21,
        'VARCHAR': 1043,
        'TEXT': 25,
        'CHAR': 18,
        'DOUBLE': 701,
        'FLOAT': 700,
        'REAL': 700,
        'BOOLEAN': 16,
        'TIMESTAMP': 1114,
        'DATE': 1082,
        'TIME': 1083,
        'JSON': 114,
        'JSONB': 3802,
        'UUID': 2950,
        'BYTEA': 17
    }

    # Type sizes in bytes (fixed-length types)
    TYPE_SIZES = {
        20: 8,    # BIGINT
        21: 2,    # SMALLINT
        23: 4,    # INTEGER
        16: 1,    # BOOLEAN
        700: 4,   # FLOAT/REAL
        701: 8,   # DOUBLE
        1082: 4,  # DATE
        1083: 8,  # TIME
        1114: 8,  # TIMESTAMP
        2950: 16, # UUID
    }

    @staticmethod
    def encode(columns: List[Tuple[str, str]]) -> bytes:
        """
        Build RowDescription message.

        Args:
            columns: List of (column_name, duckdb_type_string)

        Each column has:
        - name (null-terminated string)
        - table_oid (4 bytes, 0 = unknown)
        - column_attr_number (2 bytes, 0)
        - type_oid (4 bytes)
        - type_size (2 bytes, -1 = variable)
        - type_modifier (4 bytes, -1)
        - format_code (2 bytes, 0 = text, 1 = binary)
        """
        payload = struct.pack('!H', len(columns))  # Column count (2 bytes)

        for col_name, duckdb_type in columns:
            # Column name (null-terminated UTF-8 string)
            payload += col_name.encode('utf-8') + b'\x00'

            # Table OID (4 bytes) - 0 = not from a table
            payload += struct.pack('!I', 0)

            # Column attribute number (2 bytes) - 0
            payload += struct.pack('!H', 0)

            # Type OID (4 bytes)
            type_oid = RowDescription._get_pg_type_oid(duckdb_type)
            payload += struct.pack('!I', type_oid)

            # Type size (2 bytes) - use actual size for fixed-length types, -1 for variable
            type_size = RowDescription.TYPE_SIZES.get(type_oid, -1)
            payload += struct.pack('!h', type_size)  # Signed

            # Type modifier (4 bytes) - -1 = no modifier
            payload += struct.pack('!i', -1)  # Signed -1

            # Format code (2 bytes) - 0 = text format
            payload += struct.pack('!H', 0)

        return PostgresMessage.build_message(MessageType.ROW_DESCRIPTION, payload)

    @staticmethod
    def _get_pg_type_oid(duckdb_type: str) -> int:
        """
        Map DuckDB type to PostgreSQL type OID.

        Args:
            duckdb_type: DuckDB type string (e.g., 'BIGINT', 'VARCHAR', 'DOUBLE')

        Returns:
            PostgreSQL type OID
        """
        duckdb_type_upper = duckdb_type.upper()

        # Integer types
        if 'BIGINT' in duckdb_type_upper or 'INT64' in duckdb_type_upper:
            return RowDescription.TYPES['BIGINT']
        elif 'INTEGER' in duckdb_type_upper or 'INT32' in duckdb_type_upper or 'INT' in duckdb_type_upper:
            return RowDescription.TYPES['INTEGER']
        elif 'SMALLINT' in duckdb_type_upper or 'INT16' in duckdb_type_upper:
            return RowDescription.TYPES['SMALLINT']

        # Floating point
        elif 'DOUBLE' in duckdb_type_upper or 'FLOAT8' in duckdb_type_upper:
            return RowDescription.TYPES['DOUBLE']
        elif 'FLOAT' in duckdb_type_upper or 'REAL' in duckdb_type_upper or 'FLOAT4' in duckdb_type_upper:
            return RowDescription.TYPES['FLOAT']

        # Boolean
        elif 'BOOL' in duckdb_type_upper:
            return RowDescription.TYPES['BOOLEAN']

        # Temporal
        elif 'TIMESTAMP' in duckdb_type_upper:
            return RowDescription.TYPES['TIMESTAMP']
        elif 'DATE' in duckdb_type_upper:
            return RowDescription.TYPES['DATE']
        elif 'TIME' in duckdb_type_upper:
            return RowDescription.TYPES['TIME']

        # JSON
        elif 'JSON' in duckdb_type_upper:
            return RowDescription.TYPES['JSON']

        # UUID
        elif 'UUID' in duckdb_type_upper:
            return RowDescription.TYPES['UUID']

        # Blob/Binary
        elif 'BLOB' in duckdb_type_upper or 'BYTEA' in duckdb_type_upper:
            return RowDescription.TYPES['BYTEA']

        # Default to VARCHAR for everything else (including STRUCT, LIST, etc.)
        else:
            return RowDescription.TYPES['VARCHAR']


class DataRow:
    """DataRow message - one row of query results."""

    @staticmethod
    def _to_pg_array(value) -> str:
        """Convert a Python list/tuple to PostgreSQL array format {a,b,c}."""
        if not value:
            return '{}'
        # Convert each element, handling nested arrays and special characters
        elements = []
        for item in value:
            if item is None:
                elements.append('NULL')
            elif isinstance(item, (list, tuple)):
                elements.append(DataRow._to_pg_array(item))
            elif isinstance(item, bool):
                elements.append('t' if item else 'f')
            elif isinstance(item, str):
                # Escape special characters in strings
                escaped = item.replace('\\', '\\\\').replace('"', '\\"')
                # Quote if contains special chars
                if any(c in item for c in [',', '{', '}', '"', '\\', ' ']):
                    elements.append(f'"{escaped}"')
                else:
                    elements.append(escaped)
            else:
                elements.append(str(item))
        return '{' + ','.join(elements) + '}'

    @staticmethod
    def encode(values: List[Any]) -> bytes:
        """
        Build DataRow message.

        Args:
            values: List of column values (will be converted to strings for text format)

        Format:
        [2 bytes: column count] [per column: [4 bytes: value length] [N bytes: value]]
        """
        payload = struct.pack('!H', len(values))  # Column count

        for value in values:
            # Check for various NULL representations
            is_null = (
                value is None or
                (isinstance(value, float) and str(value) == 'nan') or
                str(value) == '<NA>' or  # pandas NA
                str(value) == 'None' or
                str(value) == 'nan'
            )

            if is_null:
                # NULL value: length = -1
                payload += struct.pack('!i', -1)
            else:
                # Convert to string (text format)
                # Handle different Python types
                if isinstance(value, bool):
                    value_str = 't' if value else 'f'  # PostgreSQL boolean format
                elif isinstance(value, (int, float)):
                    value_str = str(value)
                elif isinstance(value, bytes):
                    value_str = value.decode('utf-8', errors='replace')
                elif isinstance(value, (list, tuple)):
                    # Convert Python list/tuple to PostgreSQL array format
                    value_str = DataRow._to_pg_array(value)
                else:
                    # Check for numpy array (DuckDB returns numpy.ndarray for array columns)
                    value_type = type(value).__name__
                    if value_type == 'ndarray':
                        # Convert numpy array to list, then to PostgreSQL array format
                        value_str = DataRow._to_pg_array(value.tolist())
                    else:
                        # Check if string looks like a Python list representation
                        value_str = str(value)
                        if value_str.startswith('[') and value_str.endswith(']'):
                            # Try to convert Python list string to PostgreSQL array format
                            try:
                                import ast
                                parsed = ast.literal_eval(value_str)
                                if isinstance(parsed, (list, tuple)):
                                    value_str = DataRow._to_pg_array(parsed)
                            except (ValueError, SyntaxError):
                                pass  # Keep original string if parsing fails

                value_bytes = value_str.encode('utf-8')
                payload += struct.pack('!I', len(value_bytes))
                payload += value_bytes

        return PostgresMessage.build_message(MessageType.DATA_ROW, payload)


class CommandComplete:
    """CommandComplete message - query execution finished."""

    @staticmethod
    def encode(command_tag: str) -> bytes:
        """
        Build CommandComplete message.

        Args:
            command_tag: Command completion tag
                - "SELECT n" for SELECT returning n rows
                - "INSERT 0 n" for INSERT of n rows
                - "UPDATE n" for UPDATE of n rows
                - etc.
        """
        payload = command_tag.encode('utf-8') + b'\x00'
        return PostgresMessage.build_message(ord('C'), payload)


class ErrorResponse:
    """ErrorResponse message - error occurred during query execution."""

    @staticmethod
    def encode(severity: str, message: str, detail: str | None = None, sqlstate: str = '42000') -> bytes:
        """
        Build ErrorResponse message.

        Args:
            severity: 'ERROR', 'FATAL', 'PANIC', 'WARNING', 'NOTICE', 'DEBUG', 'INFO', 'LOG'
            message: Human-readable error message
            detail: Optional additional detail
            sqlstate: SQL state code (5-char string, default '42000' = generic error)

        Error message fields:
        - S: Severity
        - C: SQL state code
        - M: Message
        - D: Detail (optional)
        - Terminated by null byte
        """
        payload = b''

        # Severity (required)
        payload += b'S' + severity.encode('utf-8') + b'\x00'

        # SQL state code (required, 5 characters)
        payload += b'C' + sqlstate.encode('utf-8') + b'\x00'

        # Message (required)
        payload += b'M' + message.encode('utf-8') + b'\x00'

        # Detail (optional)
        if detail:
            payload += b'D' + detail.encode('utf-8') + b'\x00'

        # Terminator (null byte)
        payload += b'\x00'

        return PostgresMessage.build_message(ord('E'), payload)


class NoticeResponse:
    """NoticeResponse message - non-error notification."""

    @staticmethod
    def encode(severity: str, message: str) -> bytes:
        """Build NoticeResponse message (same format as ErrorResponse)."""
        payload = b''
        payload += b'S' + severity.encode('utf-8') + b'\x00'
        payload += b'M' + message.encode('utf-8') + b'\x00'
        payload += b'\x00'
        return PostgresMessage.build_message(ord('N'), payload)


class EmptyQueryResponse:
    """EmptyQueryResponse message - sent for empty query strings."""

    @staticmethod
    def encode() -> bytes:
        """
        Build EmptyQueryResponse message (code 'I').

        PostgreSQL protocol requires this response when a client sends
        an empty query string (whitespace only or zero-length).
        """
        return PostgresMessage.build_message(ord('I'), b'')


class BackendKeyData:
    """BackendKeyData message - used for query cancellation."""

    @staticmethod
    def encode(process_id: int, secret_key: int) -> bytes:
        """
        Build BackendKeyData message.

        Args:
            process_id: Backend process ID (can be fake for v1)
            secret_key: Secret key for cancellation (can be fake for v1)
        """
        payload = struct.pack('!II', process_id, secret_key)
        return PostgresMessage.build_message(MessageType.BACKEND_KEY_DATA, payload)


# ============================================================================
# Extended Query Protocol Messages (Parse, Bind, Execute, Describe, Close)
# ============================================================================

class ParseMessage:
    """Parse message - prepare a SQL statement with parameter placeholders."""

    @staticmethod
    def decode(payload: bytes) -> dict:
        """
        Decode Parse message from client.

        Args:
            payload: Message payload

        Returns:
            {
                'statement_name': str,
                'query': str,
                'param_types': List[int]  # Type OIDs
            }
        """
        offset = 0

        # Statement name (null-terminated string)
        null_idx = payload.find(b'\x00', offset)
        statement_name = payload[offset:null_idx].decode('utf-8')
        offset = null_idx + 1

        # Query string (null-terminated)
        null_idx = payload.find(b'\x00', offset)
        query = payload[offset:null_idx].decode('utf-8')
        offset = null_idx + 1

        # Parameter count (2 bytes, network order)
        param_count = struct.unpack('!H', payload[offset:offset+2])[0]
        offset += 2

        # Parameter type OIDs (4 bytes each)
        param_types = []
        for _ in range(param_count):
            oid = struct.unpack('!I', payload[offset:offset+4])[0]
            param_types.append(oid)
            offset += 4

        return {
            'statement_name': statement_name,
            'query': query,
            'param_types': param_types
        }


class BindMessage:
    """Bind message - bind parameters to a prepared statement."""

    @staticmethod
    def decode(payload: bytes) -> dict:
        """
        Decode Bind message from client.

        Args:
            payload: Message payload

        Returns:
            {
                'portal_name': str,
                'statement_name': str,
                'param_formats': List[int],  # 0=text, 1=binary
                'param_values': List[bytes],  # Raw parameter values
                'result_formats': List[int]   # 0=text, 1=binary
            }
        """
        offset = 0

        # Portal name (null-terminated)
        null_idx = payload.find(b'\x00', offset)
        portal_name = payload[offset:null_idx].decode('utf-8')
        offset = null_idx + 1

        # Statement name (null-terminated)
        null_idx = payload.find(b'\x00', offset)
        statement_name = payload[offset:null_idx].decode('utf-8')
        offset = null_idx + 1

        # Parameter format codes count (int16)
        format_count = struct.unpack('!H', payload[offset:offset+2])[0]
        offset += 2

        # Parameter format codes
        param_formats = []
        for _ in range(format_count):
            fmt = struct.unpack('!H', payload[offset:offset+2])[0]
            param_formats.append(fmt)
            offset += 2

        # Parameter values count (int16)
        param_count = struct.unpack('!H', payload[offset:offset+2])[0]
        offset += 2

        # Parameter values
        param_values = []
        for _ in range(param_count):
            # Length (int32, -1 means NULL)
            length = struct.unpack('!i', payload[offset:offset+4])[0]
            offset += 4

            if length == -1:
                param_values.append(None)
            else:
                value = payload[offset:offset+length]
                param_values.append(value)
                offset += length

        # Result format codes count (int16)
        result_format_count = struct.unpack('!H', payload[offset:offset+2])[0]
        offset += 2

        # Result format codes
        result_formats = []
        for _ in range(result_format_count):
            fmt = struct.unpack('!H', payload[offset:offset+2])[0]
            result_formats.append(fmt)
            offset += 2

        return {
            'portal_name': portal_name,
            'statement_name': statement_name,
            'param_formats': param_formats,
            'param_values': param_values,
            'result_formats': result_formats
        }


class DescribeMessage:
    """Describe message - get metadata for statement or portal."""

    @staticmethod
    def decode(payload: bytes) -> dict:
        """
        Decode Describe message from client.

        Args:
            payload: Message payload

        Returns:
            {
                'type': str,  # 'S' (statement) or 'P' (portal)
                'name': str
            }
        """
        describe_type = chr(payload[0])  # 'S' or 'P'
        name = payload[1:].rstrip(b'\x00').decode('utf-8')

        return {
            'type': describe_type,
            'name': name
        }


class ExecuteMessage:
    """Execute message - execute a bound portal."""

    @staticmethod
    def decode(payload: bytes) -> dict:
        """
        Decode Execute message from client.

        Args:
            payload: Message payload

        Returns:
            {
                'portal_name': str,
                'max_rows': int  # 0 = all rows
            }
        """
        null_idx = payload.find(b'\x00')
        portal_name = payload[:null_idx].decode('utf-8')
        max_rows = struct.unpack('!I', payload[null_idx+1:null_idx+5])[0]

        return {
            'portal_name': portal_name,
            'max_rows': max_rows
        }


class CloseMessage:
    """Close message - close a prepared statement or portal."""

    @staticmethod
    def decode(payload: bytes) -> dict:
        """
        Decode Close message from client.

        Args:
            payload: Message payload

        Returns:
            {
                'type': str,  # 'S' (statement) or 'P' (portal)
                'name': str
            }
        """
        close_type = chr(payload[0])  # 'S' or 'P'
        name = payload[1:].rstrip(b'\x00').decode('utf-8')

        return {
            'type': close_type,
            'name': name
        }


class ParseComplete:
    """ParseComplete message - statement parsing successful."""

    @staticmethod
    def encode() -> bytes:
        """Build ParseComplete message (code '1')."""
        return PostgresMessage.build_message(ord('1'), b'')


class BindComplete:
    """BindComplete message - parameter binding successful."""

    @staticmethod
    def encode() -> bytes:
        """Build BindComplete message (code '2')."""
        return PostgresMessage.build_message(ord('2'), b'')


class CloseComplete:
    """CloseComplete message - statement/portal closed."""

    @staticmethod
    def encode() -> bytes:
        """Build CloseComplete message (code '3')."""
        return PostgresMessage.build_message(ord('3'), b'')


class ParameterDescription:
    """ParameterDescription message - describes statement parameters."""

    @staticmethod
    def encode(param_types: List[int]) -> bytes:
        """
        Build ParameterDescription message.

        Args:
            param_types: List of parameter type OIDs

        Returns:
            Encoded message
        """
        payload = struct.pack('!H', len(param_types))  # Parameter count
        for oid in param_types:
            payload += struct.pack('!I', oid)

        return PostgresMessage.build_message(ord('t'), payload)


class NoData:
    """NoData message - statement produces no result set."""

    @staticmethod
    def encode() -> bytes:
        """Build NoData message (code 'n')."""
        return PostgresMessage.build_message(ord('n'), b'')


# ============================================================================
# Helper Functions
# ============================================================================

def send_startup_response(sock):
    """
    Send standard startup response sequence.

    Sequence:
    1. AuthenticationOk
    2. ParameterStatus messages (server config)
    3. BackendKeyData (for cancellation)
    4. ReadyForQuery

    This tells the client we're ready to receive queries.
    """
    # 1. Authentication successful (no password required for v1)
    sock.sendall(AuthenticationOk.encode())

    # 2. Parameter status messages (tell client about server config)
    sock.sendall(ParameterStatus.encode('client_encoding', 'UTF8'))
    sock.sendall(ParameterStatus.encode('server_encoding', 'UTF8'))
    sock.sendall(ParameterStatus.encode('server_version', '14.0'))
    sock.sendall(ParameterStatus.encode('DateStyle', 'ISO, MDY'))
    sock.sendall(ParameterStatus.encode('TimeZone', 'UTC'))
    sock.sendall(ParameterStatus.encode('integer_datetimes', 'on'))

    # 3. Backend key data (fake values for v1 - not implementing cancel yet)
    import os
    process_id = os.getpid()
    secret_key = 12345678  # Fake secret for v1
    sock.sendall(BackendKeyData.encode(process_id, secret_key))

    # 4. Ready for queries!
    sock.sendall(ReadyForQuery.encode('I'))


def _convert_pg_booleans(result_df):
    """
    Convert PostgreSQL-style boolean values to integers (1/0).

    DuckDB's pg_catalog returns boolean columns as 't'/'f' text values or
    Python bool values, but JDBC expects integer values. This function converts them.
    """
    import pandas as pd
    import numpy as np

    # Make a copy to avoid modifying the original
    df = result_df.copy()

    for col in df.columns:
        dtype_str = str(df[col].dtype).lower()

        # Convert boolean dtype columns to integers
        if 'bool' in dtype_str:
            df[col] = df[col].astype(int)
            continue

        # Only convert object (string) columns
        if df[col].dtype == 'object':
            try:
                # Get non-null values and check if they're all simple strings
                non_null = df[col].dropna()
                if len(non_null) == 0:
                    continue

                # Check first value type
                first_val = non_null.iloc[0]

                # Handle Python bool values in object columns
                if isinstance(first_val, (bool, np.bool_)):
                    df[col] = df[col].map(lambda x: 1 if x is True else (0 if x is False else x))
                    continue

                # Check if values are simple strings (not arrays or other complex types)
                if not isinstance(first_val, str):
                    continue

                # Check if the column only contains 't', 'f', or None
                unique_vals = set(non_null.unique())
                if unique_vals <= {'t', 'f'}:
                    # Convert 't' -> 1, 'f' -> 0, None -> None
                    df[col] = df[col].map(lambda x: 1 if x == 't' else (0 if x == 'f' else x))
            except (TypeError, ValueError):
                # Skip columns with unhashable types (arrays, etc.)
                continue

    return df


def send_query_results(sock, result_df, transaction_status='I'):
    """
    Send query results to client.

    Sequence:
    1. RowDescription (column metadata)
    2. DataRow (one per result row)
    3. CommandComplete
    4. ReadyForQuery

    Args:
        sock: Client socket
        result_df: pandas DataFrame with query results
        transaction_status: 'I' = idle, 'T' = in transaction, 'E' = error (default: 'I')
    """
    import pandas as pd

    # Convert PostgreSQL-style boolean text values ('t'/'f') to integers (1/0)
    result_df = _convert_pg_booleans(result_df)

    # 1. Send RowDescription (column metadata)
    columns = []
    for col_name, dtype in zip(result_df.columns, result_df.dtypes):
        # Map pandas dtype to DuckDB type name
        dtype_str = str(dtype).upper()

        if 'INT64' in dtype_str:
            duckdb_type = 'BIGINT'
        elif 'INT32' in dtype_str or 'INT' in dtype_str:
            duckdb_type = 'INTEGER'
        elif 'FLOAT64' in dtype_str or 'FLOAT' in dtype_str:
            duckdb_type = 'DOUBLE'
        elif 'BOOL' in dtype_str:
            duckdb_type = 'BOOLEAN'
        elif 'DATETIME' in dtype_str:
            duckdb_type = 'TIMESTAMP'
        elif 'OBJECT' in dtype_str:
            duckdb_type = 'VARCHAR'
        else:
            duckdb_type = 'VARCHAR'

        columns.append((col_name, duckdb_type))

    sock.sendall(RowDescription.encode(columns))

    # 2. Send DataRow for each row
    for idx, row in result_df.iterrows():
        values = [row[col] for col in result_df.columns]
        sock.sendall(DataRow.encode(values))

    # 3. Send CommandComplete
    row_count = len(result_df)
    command_tag = f"SELECT {row_count}"
    sock.sendall(CommandComplete.encode(command_tag))

    # 4. Send ReadyForQuery
    sock.sendall(ReadyForQuery.encode(transaction_status))


def send_error(sock, message: str, detail: str | None = None, severity: str = 'ERROR', transaction_status='E'):
    """
    Send error response to client.

    Args:
        sock: Client socket
        message: Error message
        detail: Optional error detail
        severity: Error severity (default: ERROR)
        transaction_status: Transaction status after error (default: 'E' = error)
    """
    sock.sendall(ErrorResponse.encode(severity, message, detail))
    sock.sendall(ReadyForQuery.encode(transaction_status))


def send_execute_results(sock, result_df, send_row_description=True):
    """
    Send Execute message results to client (Extended Query Protocol).

    In Extended Query Protocol:
    - If Describe Portal sent RowDescription → Execute sends only DataRows
    - If Describe Portal sent NoData → Execute must send RowDescription + DataRows

    Sequence (if send_row_description=True):
    1. RowDescription (column metadata)
    2. DataRow (one per result row)
    3. CommandComplete
    (NO ReadyForQuery - that comes after Sync!)

    Sequence (if send_row_description=False):
    1. DataRow (one per result row) - RowDescription was sent by Describe
    2. CommandComplete
    (NO ReadyForQuery - that comes after Sync!)

    Args:
        sock: Client socket
        result_df: pandas DataFrame with query results
        send_row_description: If True, send RowDescription (default)
    """
    import pandas as pd

    # Convert PostgreSQL-style boolean text values ('t'/'f') to integers (1/0)
    result_df = _convert_pg_booleans(result_df)

    # 1. Optionally send RowDescription (if Describe didn't send it)
    if send_row_description:
        columns = []
        for col_name, dtype in zip(result_df.columns, result_df.dtypes):
            dtype_str = str(dtype).upper()
            if 'INT64' in dtype_str:
                duckdb_type = 'BIGINT'
            elif 'INT32' in dtype_str or 'INT' in dtype_str:
                duckdb_type = 'INTEGER'
            elif 'FLOAT64' in dtype_str or 'FLOAT' in dtype_str:
                duckdb_type = 'DOUBLE'
            elif 'BOOL' in dtype_str:
                duckdb_type = 'BOOLEAN'
            elif 'DATETIME' in dtype_str:
                duckdb_type = 'TIMESTAMP'
            elif 'OBJECT' in dtype_str:
                duckdb_type = 'VARCHAR'
            else:
                duckdb_type = 'VARCHAR'
            columns.append((col_name, duckdb_type))

        sock.sendall(RowDescription.encode(columns))

    # 2. Send DataRow for each row
    for idx, row in result_df.iterrows():
        values = [row[col] for col in result_df.columns]
        sock.sendall(DataRow.encode(values))

    # 3. Send CommandComplete
    row_count = len(result_df)
    command_tag = f"SELECT {row_count}"
    sock.sendall(CommandComplete.encode(command_tag))

    # 4. NO ReadyForQuery! (Extended Query Protocol sends that after Sync)
