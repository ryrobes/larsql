# PostgreSQL Wire Protocol Server - Implementation Plan

*Enable native SQL client connections to Windlass DuckDB with LLM UDFs*

---

## Goal

Build a PostgreSQL wire protocol server that:
- ✅ Accepts connections from **any PostgreSQL client** (DBeaver, psql, DataGrip, Tableau)
- ✅ Routes queries to **Windlass session DuckDB** (with windlass_udf() already registered)
- ✅ Returns results in **PostgreSQL wire format**
- ✅ Supports **concurrent connections** (one DuckDB session per client)
- ⏸️ **No authentication** (for v1 - add later)

**When done**:
```bash
# Start server
windlass server --port 5432

# Connect from DBeaver
postgresql://windlass@localhost:5432/default

# Query with LLM UDFs!
SELECT windlass_udf('Extract brand', product_name) FROM products;
```

---

## PostgreSQL Wire Protocol - The Essentials

### **Message Flow**

```
Client                          Windlass Server
  │                                    │
  ├──────── Startup ────────────────→ │
  │                                    ├─ Create DuckDB session
  │                                    ├─ Register windlass_udf()
  │ ←──── AuthenticationOk ───────────┤
  │ ←──── ReadyForQuery ──────────────┤
  │                                    │
  ├──────── Query (SQL) ─────────────→│
  │                                    ├─ Parse SQL
  │                                    ├─ Execute on DuckDB
  │ ←──── RowDescription ─────────────┤ (column metadata)
  │ ←──── DataRow ────────────────────┤ (row 1)
  │ ←──── DataRow ────────────────────┤ (row 2)
  │ ←──── DataRow ────────────────────┤ (row 3)
  │ ←──── CommandComplete ────────────┤
  │ ←──── ReadyForQuery ──────────────┤
  │                                    │
  ├──────── Terminate ───────────────→│
  │                                    ├─ Cleanup session
  │ ←──────── Close ───────────────────┤
```

---

## Message Types (Minimal Implementation)

### **Client → Server** (what we must handle):

| Message | Code | Purpose | Required? |
|---------|------|---------|-----------|
| **Startup** | - | Initial connection, send DB + user | ✅ Yes |
| **Query** | 'Q' | Simple query protocol | ✅ Yes |
| **Terminate** | 'X' | Close connection | ✅ Yes |
| **Parse** | 'P' | Prepared statement (extended protocol) | ⚠️ Optional (v2) |
| **Bind** | 'B' | Bind parameters | ⚠️ Optional (v2) |
| **Execute** | 'E' | Execute prepared statement | ⚠️ Optional (v2) |
| **Sync** | 'S' | Sync point | ⚠️ Optional (v2) |

**For v1**: Just implement Startup, Query, Terminate!

---

### **Server → Client** (what we must send):

| Message | Code | Purpose | Required? |
|---------|------|---------|-----------|
| **AuthenticationOk** | 'R' | Auth successful | ✅ Yes |
| **ParameterStatus** | 'S' | Server params (client_encoding, etc.) | ✅ Yes |
| **BackendKeyData** | 'K' | Cancel key (can fake) | ⚠️ Optional |
| **ReadyForQuery** | 'Z' | Ready for next query | ✅ Yes |
| **RowDescription** | 'T' | Column metadata | ✅ Yes |
| **DataRow** | 'D' | Result row | ✅ Yes |
| **CommandComplete** | 'C' | Query finished | ✅ Yes |
| **ErrorResponse** | 'E' | Error message | ✅ Yes |

---

## Wire Format (Binary Protocol)

### **Message Structure**:
```
[1 byte: message type] [4 bytes: length] [N bytes: payload]
```

**Example**: Query message
```python
msg_type = b'Q'  # Query
payload = b'SELECT 1 as test\x00'  # Null-terminated SQL
length = len(payload) + 4  # Include length field itself
message = msg_type + struct.pack('!I', length) + payload
```

### **Data Types Mapping**:

| PostgreSQL Type | OID | DuckDB Equivalent | Python Type |
|-----------------|-----|-------------------|-------------|
| INTEGER | 23 | INTEGER | int |
| BIGINT | 20 | BIGINT | int |
| VARCHAR | 1043 | VARCHAR | str |
| DOUBLE | 701 | DOUBLE | float |
| BOOLEAN | 16 | BOOLEAN | bool |
| TIMESTAMP | 1114 | TIMESTAMP | datetime |
| JSON | 114 | JSON | str (serialized) |

**For v1**: Support INTEGER, BIGINT, VARCHAR, DOUBLE, BOOLEAN
**For v2**: Add TIMESTAMP, JSON, ARRAY, etc.

---

## Architecture

### **Components**:

```
┌─────────────────────────────────────────────┐
│         PostgreSQL Client                   │
│    (DBeaver, psql, DataGrip, etc.)          │
└────────────────┬────────────────────────────┘
                 │ PostgreSQL wire protocol
                 │ (TCP socket, binary format)
                 ▼
┌─────────────────────────────────────────────┐
│    WindlassPostgresServer                   │
│    - Listen on port 5432                    │
│    - Accept connections                     │
│    - Parse PG wire protocol                 │
│    - Create client session                  │
└────────────────┬────────────────────────────┘
                 │ DuckDB Python API
                 ▼
┌─────────────────────────────────────────────┐
│    Session DuckDB (existing!)               │
│    - get_session_db(client_session_id)      │
│    - windlass_udf() registered ✅           │
│    - windlass_cascade_udf() registered ✅   │
│    - ATTACH support ✅                      │
│    - Temp tables ✅                         │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│         Windlass Runner + LLMs              │
│    (Already implemented!)                   │
└─────────────────────────────────────────────┘
```

**Key insight**: We just need the protocol layer! Everything else already works!

---

## Implementation Plan

### **Phase 1: Minimal Protocol (Days 1-2)**

**Goal**: Accept connections, execute simple SELECT, return results

**Files to Create**:
1. `windlass/server/postgres_protocol.py` - Wire protocol parser
2. `windlass/server/postgres_server.py` - TCP server
3. `windlass/cli.py` - Add `windlass server` command

**Functionality**:
- ✅ Accept TCP connection on port 5432
- ✅ Handle Startup message (fake auth - accept all)
- ✅ Handle Query message (simple SQL)
- ✅ Execute on DuckDB session
- ✅ Return RowDescription + DataRow messages
- ✅ Handle Terminate

**Testing**:
```bash
windlass server --port 5432

# From another terminal:
psql postgresql://localhost:5432/default
> SELECT 1 as test;
 test
------
    1
```

**Code estimate**: ~300 lines

---

### **Phase 2: DuckDB Integration (Day 3)**

**Goal**: Connect to Windlass session DuckDB with UDFs

**Changes**:
1. Import `session_db.get_session_db()`
2. Import `udf.register_windlass_udf()`
3. Create session per client connection
4. Execute queries on session DuckDB

**Testing**:
```bash
psql postgresql://localhost:5432/default
> SELECT windlass_udf('Extract brand', 'Apple iPhone') as brand;
 brand
-------
 Apple
```

**Code estimate**: ~50 lines (integration)

---

### **Phase 3: Type System (Day 4)**

**Goal**: Proper type mapping (DuckDB → PostgreSQL)

**Type Conversion**:
- DuckDB BIGINT → PG BIGINT (OID 20)
- DuckDB VARCHAR → PG VARCHAR (OID 1043)
- DuckDB DOUBLE → PG FLOAT8 (OID 701)
- DuckDB BOOLEAN → PG BOOL (OID 16)

**Testing**:
```bash
psql
> SELECT
    1::bigint as big,
    'text' as str,
    1.5::double as num,
    true as bool;

# Should show correct types in psql
```

**Code estimate**: ~100 lines (type registry + conversion)

---

### **Phase 4: Error Handling (Day 5)**

**Goal**: Graceful error messages

**ErrorResponse Message**:
- Severity: ERROR
- SQLState: Code (e.g., '42P01' for undefined table)
- Message: Human-readable error
- Detail: Additional context

**Testing**:
```bash
psql
> SELECT * FROM nonexistent_table;
ERROR: relation "nonexistent_table" does not exist

> SELECT windlass_udf('Bad');
ERROR: windlass_udf requires 2 arguments
```

**Code estimate**: ~50 lines

---

### **Phase 5: CLI Integration (Day 6)**

**Goal**: Easy server startup

```bash
# Start server
windlass server --port 5432 --host 0.0.0.0

# With session prefix
windlass server --port 5432 --session-prefix "dbeaver_"

# With logging
windlass server --port 5432 --log-level debug
```

**Code estimate**: ~50 lines (CLI args + server startup)

---

### **Phase 6: Concurrent Connections (Day 7)**

**Goal**: Multiple clients can connect simultaneously

**Strategy**: Threading
- Main thread accepts connections
- Spawn thread per client
- Each thread gets isolated DuckDB session

**Testing**:
```bash
# Terminal 1
psql postgresql://localhost:5432/default

# Terminal 2 (while 1 is still connected!)
psql postgresql://localhost:5432/default

# Both work independently!
```

**Code estimate**: ~100 lines (threading + session management)

---

## Total Effort

| Phase | Days | Lines of Code | Cumulative LOC |
|-------|------|---------------|----------------|
| 1. Minimal Protocol | 2 | 300 | 300 |
| 2. DuckDB Integration | 1 | 50 | 350 |
| 3. Type System | 1 | 100 | 450 |
| 4. Error Handling | 1 | 50 | 500 |
| 5. CLI Integration | 1 | 50 | 550 |
| 6. Concurrent Connections | 1 | 100 | 650 |

**Total**: ~7 days, ~650 lines of code

---

## Detailed Implementation

### **File 1: postgres_protocol.py**

```python
"""
PostgreSQL wire protocol message encoding/decoding.

Reference: https://www.postgresql.org/docs/current/protocol-message-formats.html
"""

import struct
from typing import Tuple, Optional, List, Any
from enum import Enum


class MessageType(Enum):
    """PostgreSQL message type codes."""
    # Client → Server
    QUERY = ord('Q')
    TERMINATE = ord('X')
    PARSE = ord('P')
    BIND = ord('B')
    EXECUTE = ord('E')
    SYNC = ord('S')

    # Server → Client
    AUTHENTICATION = ord('R')
    PARAMETER_STATUS = ord('S')
    BACKEND_KEY_DATA = ord('K')
    READY_FOR_QUERY = ord('Z')
    ROW_DESCRIPTION = ord('T')
    DATA_ROW = ord('D')
    COMMAND_COMPLETE = ord('C')
    ERROR_RESPONSE = ord('E')


class PostgresMessage:
    """Base class for PostgreSQL wire protocol messages."""

    @staticmethod
    def read_message(sock) -> Tuple[Optional[int], bytes]:
        """
        Read one message from socket.

        Returns:
            (message_type, payload) or (None, b'') on error
        """
        # Startup message has no type byte (special case)
        # For now, read type + length + payload

        try:
            # Read message type (1 byte)
            type_byte = sock.recv(1)
            if not type_byte:
                return None, b''

            msg_type = type_byte[0]

            # Read length (4 bytes, network byte order)
            length_bytes = sock.recv(4)
            if len(length_bytes) < 4:
                return None, b''

            length = struct.unpack('!I', length_bytes)[0]

            # Length includes itself (4 bytes), so payload is length - 4
            payload_length = length - 4

            # Read payload
            payload = b''
            while len(payload) < payload_length:
                chunk = sock.recv(payload_length - len(payload))
                if not chunk:
                    return None, b''
                payload += chunk

            return msg_type, payload

        except Exception as e:
            print(f"Error reading message: {e}")
            return None, b''

    @staticmethod
    def read_startup_message(sock) -> Optional[dict]:
        """
        Read startup message (no type byte).

        Format: [4 bytes: length] [4 bytes: protocol] [key=value pairs]
        """
        try:
            # Read length
            length_bytes = sock.recv(4)
            if len(length_bytes) < 4:
                return None

            length = struct.unpack('!I', length_bytes)[0]
            payload_length = length - 4

            # Read payload
            payload = sock.recv(payload_length)

            # Parse protocol version (first 4 bytes)
            protocol = struct.unpack('!I', payload[:4])[0]

            # Parse key-value pairs (null-terminated strings)
            params = {}
            data = payload[4:]

            while data:
                # Find null terminator
                null_idx = data.find(b'\x00')
                if null_idx == -1 or null_idx == 0:
                    break

                key = data[:null_idx].decode('utf-8')
                data = data[null_idx + 1:]

                # Value
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
            print(f"Error reading startup: {e}")
            return None

    @staticmethod
    def build_message(msg_type: int, payload: bytes) -> bytes:
        """
        Build a PostgreSQL message.

        Args:
            msg_type: Message type code
            payload: Message payload

        Returns:
            Complete message (type + length + payload)
        """
        length = len(payload) + 4  # Length includes itself
        return bytes([msg_type]) + struct.pack('!I', length) + payload


class AuthenticationOk:
    """AuthenticationOk message."""

    @staticmethod
    def encode() -> bytes:
        """Build AuthenticationOk message (code 0 = success)."""
        payload = struct.pack('!I', 0)  # Auth type 0 = OK
        return PostgresMessage.build_message(MessageType.AUTHENTICATION.value, payload)


class ParameterStatus:
    """ParameterStatus message."""

    @staticmethod
    def encode(name: str, value: str) -> bytes:
        """Build ParameterStatus message."""
        payload = name.encode('utf-8') + b'\x00' + value.encode('utf-8') + b'\x00'
        return PostgresMessage.build_message(ord('S'), payload)


class ReadyForQuery:
    """ReadyForQuery message."""

    @staticmethod
    def encode(status: str = 'I') -> bytes:
        """
        Build ReadyForQuery message.

        Args:
            status: 'I' = idle, 'T' = in transaction, 'E' = failed transaction
        """
        payload = status.encode('utf-8')
        return PostgresMessage.build_message(MessageType.READY_FOR_QUERY.value, payload)


class RowDescription:
    """RowDescription message (column metadata)."""

    # PostgreSQL type OIDs (simplified)
    TYPES = {
        'BIGINT': 20,
        'INTEGER': 23,
        'VARCHAR': 1043,
        'TEXT': 25,
        'DOUBLE': 701,
        'FLOAT': 700,
        'BOOLEAN': 16,
        'TIMESTAMP': 1114,
        'DATE': 1082,
        'JSON': 114
    }

    @staticmethod
    def encode(columns: List[Tuple[str, str]]) -> bytes:
        """
        Build RowDescription message.

        Args:
            columns: List of (column_name, duckdb_type)
        """
        payload = struct.pack('!H', len(columns))  # Column count

        for name, duckdb_type in columns:
            # Column name (null-terminated)
            payload += name.encode('utf-8') + b'\x00'

            # Table OID (0 = unknown)
            payload += struct.pack('!I', 0)

            # Column attribute number (0)
            payload += struct.pack('!H', 0)

            # Type OID
            type_oid = RowDescription._get_pg_type_oid(duckdb_type)
            payload += struct.pack('!I', type_oid)

            # Type size (-1 = variable)
            payload += struct.pack('!H', 0xFFFF)  # -1 as unsigned

            # Type modifier (-1)
            payload += struct.pack('!I', 0xFFFFFFFF)  # -1 as unsigned

            # Format code (0 = text, 1 = binary)
            payload += struct.pack('!H', 0)  # Text format for simplicity

        return PostgresMessage.build_message(MessageType.ROW_DESCRIPTION.value, payload)

    @staticmethod
    def _get_pg_type_oid(duckdb_type: str) -> int:
        """Map DuckDB type to PostgreSQL OID."""
        duckdb_type_upper = duckdb_type.upper()

        if 'BIGINT' in duckdb_type_upper or 'INT64' in duckdb_type_upper:
            return RowDescription.TYPES['BIGINT']
        elif 'INTEGER' in duckdb_type_upper or 'INT' in duckdb_type_upper:
            return RowDescription.TYPES['INTEGER']
        elif 'DOUBLE' in duckdb_type_upper or 'FLOAT' in duckdb_type_upper:
            return RowDescription.TYPES['DOUBLE']
        elif 'BOOL' in duckdb_type_upper:
            return RowDescription.TYPES['BOOLEAN']
        elif 'TIMESTAMP' in duckdb_type_upper:
            return RowDescription.TYPES['TIMESTAMP']
        elif 'DATE' in duckdb_type_upper:
            return RowDescription.TYPES['DATE']
        elif 'JSON' in duckdb_type_upper:
            return RowDescription.TYPES['JSON']
        else:
            # Default to VARCHAR for unknown types
            return RowDescription.TYPES['VARCHAR']


class DataRow:
    """DataRow message."""

    @staticmethod
    def encode(values: List[Any]) -> bytes:
        """
        Build DataRow message.

        Args:
            values: List of column values (will be converted to strings)
        """
        payload = struct.pack('!H', len(values))  # Column count

        for value in values:
            if value is None:
                # Null value: length = -1
                payload += struct.pack('!i', -1)
            else:
                # Convert to string (text format)
                value_str = str(value).encode('utf-8')
                payload += struct.pack('!I', len(value_str))
                payload += value_str

        return PostgresMessage.build_message(MessageType.DATA_ROW.value, payload)


class CommandComplete:
    """CommandComplete message."""

    @staticmethod
    def encode(command_tag: str) -> bytes:
        """
        Build CommandComplete message.

        Args:
            command_tag: e.g., "SELECT 5" for SELECT returning 5 rows
        """
        payload = command_tag.encode('utf-8') + b'\x00'
        return PostgresMessage.build_message(ord('C'), payload)


class ErrorResponse:
    """ErrorResponse message."""

    @staticmethod
    def encode(severity: str, message: str, detail: str = None) -> bytes:
        """
        Build ErrorResponse message.

        Args:
            severity: 'ERROR', 'FATAL', 'WARNING'
            message: Error message
            detail: Optional detail
        """
        payload = b''

        # Severity
        payload += b'S' + severity.encode('utf-8') + b'\x00'

        # Message
        payload += b'M' + message.encode('utf-8') + b'\x00'

        # Detail (optional)
        if detail:
            payload += b'D' + detail.encode('utf-8') + b'\x00'

        # Terminator
        payload += b'\x00'

        return PostgresMessage.build_message(ord('E'), payload)
```

---

### **File 2: postgres_server.py**

```python
"""
PostgreSQL wire protocol server for Windlass.

Accepts connections from any PostgreSQL client and routes queries to
Windlass DuckDB sessions with windlass_udf() and windlass_cascade_udf().
"""

import socket
import threading
import uuid
from typing import Optional
from .postgres_protocol import (
    PostgresMessage,
    AuthenticationOk,
    ParameterStatus,
    ReadyForQuery,
    RowDescription,
    DataRow,
    CommandComplete,
    ErrorResponse,
    MessageType
)


class ClientConnection:
    """Represents a single client connection."""

    def __init__(self, sock, addr, session_prefix='pg_client'):
        self.sock = sock
        self.addr = addr
        self.session_id = f"{session_prefix}_{uuid.uuid4().hex[:8]}"
        self.duckdb_conn = None
        self.running = True

    def setup_session(self):
        """Create DuckDB session and register UDFs."""
        from windlass.sql_tools.session_db import get_session_db
        from windlass.sql_tools.udf import register_windlass_udf

        # Get session DuckDB
        self.duckdb_conn = get_session_db(self.session_id)

        # Register Windlass UDFs
        register_windlass_udf(self.duckdb_conn)

        print(f"[{self.session_id}] Session created with windlass UDFs registered")

    def handle_startup(self, startup_params: dict):
        """Handle client startup."""
        database = startup_params.get('database', 'default')
        user = startup_params.get('user', 'windlass')

        print(f"[{self.session_id}] Client startup: user={user}, database={database}")

        # Send AuthenticationOk
        self.sock.sendall(AuthenticationOk.encode())

        # Send ParameterStatus messages
        self.sock.sendall(ParameterStatus.encode('client_encoding', 'UTF8'))
        self.sock.sendall(ParameterStatus.encode('server_version', '14.0 (Windlass/DuckDB)'))
        self.sock.sendall(ParameterStatus.encode('server_encoding', 'UTF8'))
        self.sock.sendall(ParameterStatus.encode('DateStyle', 'ISO, MDY'))

        # Send ReadyForQuery
        self.sock.sendall(ReadyForQuery.encode('I'))

    def handle_query(self, query: str):
        """Execute query on DuckDB and return results."""
        try:
            # Execute query
            result_df = self.duckdb_conn.execute(query).fetchdf()

            # Send RowDescription (column metadata)
            columns = []
            for col_name, dtype in zip(result_df.columns, result_df.dtypes):
                duckdb_type = str(dtype).upper()
                # Map numpy/pandas dtypes to DuckDB type names
                if 'int64' in duckdb_type.lower():
                    duckdb_type = 'BIGINT'
                elif 'int' in duckdb_type.lower():
                    duckdb_type = 'INTEGER'
                elif 'float' in duckdb_type.lower() or 'double' in duckdb_type.lower():
                    duckdb_type = 'DOUBLE'
                elif 'bool' in duckdb_type.lower():
                    duckdb_type = 'BOOLEAN'
                else:
                    duckdb_type = 'VARCHAR'

                columns.append((col_name, duckdb_type))

            self.sock.sendall(RowDescription.encode(columns))

            # Send DataRow for each row
            for idx, row in result_df.iterrows():
                values = [row[col] for col in result_df.columns]
                self.sock.sendall(DataRow.encode(values))

            # Send CommandComplete
            row_count = len(result_df)
            command_tag = f"SELECT {row_count}"
            self.sock.sendall(CommandComplete.encode(command_tag))

            # Send ReadyForQuery
            self.sock.sendall(ReadyForQuery.encode('I'))

            print(f"[{self.session_id}] Query executed: {row_count} rows")

        except Exception as e:
            # Send ErrorResponse
            error_msg = str(e)
            self.sock.sendall(ErrorResponse.encode('ERROR', error_msg))
            self.sock.sendall(ReadyForQuery.encode('E'))

            print(f"[{self.session_id}] Query error: {error_msg}")

    def handle(self):
        """Main client handling loop."""
        try:
            # Read startup message
            startup = PostgresMessage.read_startup_message(self.sock)
            if not startup:
                print(f"[{self.addr}] Failed to read startup message")
                return

            # Setup DuckDB session
            self.setup_session()

            # Send startup response
            self.handle_startup(startup['params'])

            # Message loop
            while self.running:
                msg_type, payload = PostgresMessage.read_message(self.sock)

                if msg_type is None:
                    # Connection closed
                    break

                if msg_type == MessageType.QUERY.value:
                    # Parse query (null-terminated string)
                    query = payload.rstrip(b'\x00').decode('utf-8')
                    print(f"[{self.session_id}] Query: {query[:100]}...")
                    self.handle_query(query)

                elif msg_type == MessageType.TERMINATE.value:
                    print(f"[{self.session_id}] Client requested termination")
                    break

                else:
                    print(f"[{self.session_id}] Unsupported message type: {msg_type}")
                    # Send error for unsupported messages
                    self.sock.sendall(ErrorResponse.encode(
                        'ERROR',
                        f'Unsupported message type: {msg_type}'
                    ))
                    self.sock.sendall(ReadyForQuery.encode('I'))

        except Exception as e:
            print(f"[{self.session_id}] Connection error: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # Cleanup
            self.cleanup()

    def cleanup(self):
        """Clean up connection and session."""
        print(f"[{self.session_id}] Cleaning up connection")

        try:
            self.sock.close()
        except:
            pass

        # Optional: cleanup DuckDB session
        # from windlass.sql_tools.session_db import cleanup_session_db
        # cleanup_session_db(self.session_id, delete_file=False)


class WindlassPostgresServer:
    """
    PostgreSQL wire protocol server backed by Windlass DuckDB.

    Clients connect as if it's PostgreSQL, but queries execute on DuckDB
    with windlass_udf() and windlass_cascade_udf() available.
    """

    def __init__(self, host='0.0.0.0', port=5432, session_prefix='pg_client'):
        self.host = host
        self.port = port
        self.session_prefix = session_prefix
        self.running = False

    def start(self):
        """Start server and accept connections."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind((self.host, self.port))
        except OSError as e:
            print(f"❌ Error: Could not bind to {self.host}:{self.port}")
            print(f"   {e}")
            print(f"\n💡 Tip: Port {self.port} might be in use. Try a different port:")
            print(f"   windlass server --port 5433")
            return

        sock.listen(5)
        self.running = True

        print("=" * 70)
        print("🌊 Windlass PostgreSQL Server Started!")
        print("=" * 70)
        print(f"📡 Listening on: {self.host}:{self.port}")
        print(f"🔗 Connection string: postgresql://windlass@localhost:{self.port}/default")
        print("\n✨ Available SQL functions:")
        print("   - windlass_udf('instructions', input_value)")
        print("   - windlass_cascade_udf('cascade_path', json_inputs)")
        print("\n📚 Connect from:")
        print(f"   - psql: psql postgresql://localhost:{self.port}/default")
        print(f"   - DBeaver: Add PostgreSQL connection → localhost:{self.port}")
        print(f"   - Python: psycopg2.connect('postgresql://localhost:{self.port}/default')")
        print("\n⏸️  Press Ctrl+C to stop")
        print("=" * 70)

        try:
            while self.running:
                # Accept connection
                client_sock, addr = sock.accept()
                print(f"\n🔌 Client connected from {addr}")

                # Handle in new thread
                client = ClientConnection(client_sock, addr, self.session_prefix)
                thread = threading.Thread(target=client.handle, daemon=True)
                thread.start()

        except KeyboardInterrupt:
            print("\n\n⏹️  Shutting down server...")

        finally:
            sock.close()
            print("✅ Server stopped")


def start_postgres_server(host='0.0.0.0', port=5432, session_prefix='pg_client'):
    """
    Start PostgreSQL wire protocol server.

    Args:
        host: Host to listen on (default: 0.0.0.0 = all interfaces)
        port: Port to listen on (default: 5432)
        session_prefix: Prefix for DuckDB session IDs
    """
    server = WindlassPostgresServer(host, port, session_prefix)
    server.start()
```

---

### **File 3: Update cli.py**

```python
# In windlass/cli.py

def cmd_server(args):
    """Start Windlass PostgreSQL server."""
    from windlass.server.postgres_server import start_postgres_server

    print(f"Starting Windlass PostgreSQL server...")
    print(f"Host: {args.host}, Port: {args.port}")

    start_postgres_server(
        host=args.host,
        port=args.port,
        session_prefix=args.session_prefix
    )


# Add to argparse
server_parser = subparsers.add_parser('server', help='Start PostgreSQL wire protocol server')
server_parser.add_argument('--host', default='0.0.0.0', help='Host to listen on (default: 0.0.0.0)')
server_parser.add_argument('--port', type=int, default=5432, help='Port to listen on (default: 5432)')
server_parser.add_argument('--session-prefix', default='pg_client', help='Session ID prefix (default: pg_client)')
server_parser.set_defaults(func=cmd_server)
```

---

## Testing Strategy

### **Phase 1: Basic Connection**

```bash
# Start server
windlass server --port 5433  # Use non-standard port to avoid conflicts

# Test with psql
psql postgresql://localhost:5433/default

# Should connect and show:
# psql (14.x, server 14.0 Windlass/DuckDB)
# default=>
```

**Success criteria**: psql connects without error

---

### **Phase 2: Simple SELECT**

```bash
psql postgresql://localhost:5433/default
default=> SELECT 1 as one, 2 as two, 3 as three;
 one | two | three
-----+-----+-------
   1 |   2 |     3
(1 row)
```

**Success criteria**: Results display correctly

---

### **Phase 3: windlass_udf()**

```bash
default=> SELECT windlass_udf('Extract brand', 'Apple iPhone 15') as brand;
 brand
-------
 Apple
(1 row)
```

**Success criteria**: LLM UDF executes and returns result

---

### **Phase 4: DBeaver Connection**

1. Open DBeaver
2. Database → New Connection → PostgreSQL
3. Host: localhost, Port: 5433
4. User: windlass, Database: default
5. Test Connection → Should succeed!
6. Write SQL:
```sql
SELECT
  product,
  windlass_udf('Extract brand', product) as brand
FROM (VALUES
  ('Apple iPhone'),
  ('Samsung Galaxy')
) AS t(product);
```
7. Execute → Results appear!

**Success criteria**: DBeaver shows LLM-enriched results

---

## Implementation Checklist

### **Minimal (Days 1-3)**:
- [ ] Create `windlass/server/` directory
- [ ] Implement `postgres_protocol.py` (message parsing)
- [ ] Implement `postgres_server.py` (TCP server)
- [ ] Add `windlass server` CLI command
- [ ] Test with psql (basic connection)
- [ ] Test with psql (simple SELECT)

### **DuckDB Integration (Day 3)**:
- [ ] Import `session_db.get_session_db()`
- [ ] Import `udf.register_windlass_udf()`
- [ ] Create session per client
- [ ] Execute queries on session DuckDB
- [ ] Test windlass_udf() from psql

### **Production Ready (Days 4-7)**:
- [ ] Type system (DuckDB → PostgreSQL type mapping)
- [ ] Error handling (proper ErrorResponse messages)
- [ ] Concurrent connections (threading)
- [ ] CLI options (port, host, session prefix)
- [ ] Test with DBeaver
- [ ] Test with DataGrip
- [ ] Test with Python psycopg2

### **Future Enhancements** (Optional):
- [ ] Extended query protocol (prepared statements)
- [ ] SSL/TLS support
- [ ] Authentication (md5, SCRAM)
- [ ] Transaction support (BEGIN, COMMIT, ROLLBACK)
- [ ] Cursor support (DECLARE CURSOR, FETCH)

---

## Code Structure

```
windlass/
├── server/                    # NEW
│   ├── __init__.py
│   ├── postgres_protocol.py  # Wire protocol messages (~300 lines)
│   └── postgres_server.py    # TCP server (~300 lines)
├── cli.py                     # Add 'server' command (~50 lines)
└── sql_tools/
    ├── session_db.py          # Already exists! ✅
    └── udf.py                 # Already exists! ✅
```

**Total new code**: ~650 lines

---

## Key Design Decisions

### **1. Session Management**

**One DuckDB session per client connection**:
```python
# Client 1 connects
session_1 = get_session_db("pg_client_abc123")
# Has its own temp tables, isolated

# Client 2 connects
session_2 = get_session_db("pg_client_def456")
# Different temp tables, isolated
```

**Cleanup**: When client disconnects, optionally delete session file

---

### **2. Query Protocol**

**Start with Simple Query Protocol**:
- Client sends: Query message with SQL string
- Server executes on DuckDB
- Server sends back: RowDescription + DataRow* + CommandComplete

**Skip Extended Query** (v1):
- Prepared statements (Parse/Bind/Execute)
- Parameter binding
- Cursors

**Reason**: Simple query is enough for 95% of tools!

---

### **3. Type Handling**

**Text format only** (v1):
- All values sent as strings
- Client parses based on type OID
- Simple to implement

**Binary format** (v2):
- Native encoding (faster, more precise)
- More complex (need to encode each type properly)

---

### **4. Error Handling**

**Map DuckDB errors to PostgreSQL**:
```python
try:
    result = conn.execute(query)
except Exception as e:
    error_message = str(e)

    # Send ErrorResponse
    send_error('ERROR', error_message)
```

**Good enough for v1!** Clients see error messages, can debug.

---

## Benefits Over HTTP API

| Feature | HTTP API | PostgreSQL Protocol |
|---------|----------|---------------------|
| **SQL Tools** | ❌ No (need Python bridge) | ✅ **All work natively!** |
| **DBeaver** | ⚠️ Python script | ✅ **Native connection** |
| **psql** | ❌ No | ✅ **Yes!** |
| **Tableau** | ❌ No | ✅ **Yes!** |
| **dbt** | ❌ Custom adapter | ✅ **Works as Postgres!** |
| **Python** | ✅ WindlassClient | ✅ **psycopg2 works!** |
| **Effort** | ✅ 1 hour (done!) | ⚠️ 1 week |

**Both are useful**:
- HTTP API: Programmatic access, REST integrations
- PG Protocol: SQL tools, BI dashboards, native clients

---

## Example Usage (After Implementation)

### **From psql**:
```bash
$ psql postgresql://localhost:5432/default

default=> SELECT
  product_name,
  windlass_udf('Extract brand', product_name) as brand,
  windlass_udf('Classify category', product_name) as category
FROM (VALUES
  ('Apple iPhone 15 Pro'),
  ('Samsung Galaxy S24')
) AS t(product_name);

 product_name           | brand   | category
------------------------+---------+-------------
 Apple iPhone 15 Pro    | Apple   | Electronics
 Samsung Galaxy S24     | Samsung | Electronics
(2 rows)
```

---

### **From DBeaver**:

**Connection**:
- Type: PostgreSQL
- Host: localhost
- Port: 5432
- Database: default
- User: windlass

**SQL Editor**:
```sql
-- Attach external database
ATTACH 'postgres://prod.db.com/warehouse' AS prod (TYPE POSTGRES);

-- Query with LLM enrichment
SELECT
  customer_id,
  company_name,
  windlass_udf('Extract industry', company_name) as industry
FROM prod.customers
WHERE created_at > CURRENT_DATE - INTERVAL '30 days'
LIMIT 100;
```

**Result**: 100 customers with LLM-extracted industries!

---

### **From Python** (standard psycopg2):

```python
import psycopg2
import pandas as pd

# Connect like any PostgreSQL database
conn = psycopg2.connect("postgresql://localhost:5432/default")
cur = conn.cursor()

# Execute query with LLM UDFs!
cur.execute("""
    SELECT
      product_name,
      windlass_udf('Extract brand', product_name) as brand
    FROM products
    LIMIT 10
""")

# Fetch results
for row in cur.fetchall():
    print(row)

# Or use pandas
df = pd.read_sql("""
    SELECT windlass_cascade_udf('tackle/fraud.yaml', json_object('id', id)) as check
    FROM transactions
""", conn)
```

---

## Phased Rollout

### **Week 1: Minimal Implementation**
- Startup, Query, Terminate messages
- Text-format results
- Single-threaded (one client at a time)
- **Goal**: psql connects and executes SELECT

### **Week 2: Production Features**
- Concurrent connections (threading)
- Type system (proper OIDs)
- Error handling
- **Goal**: DBeaver connects and works

### **Week 3: Polish**
- Extended query protocol (prepared statements)
- Better error messages (SQLState codes)
- CLI options (port, host, logging)
- **Goal**: Tableau/Metabase work

### **Month 2: Advanced** (Optional)
- SSL/TLS support
- Authentication (md5, SCRAM-SHA-256)
- Transaction support
- **Goal**: Production-ready

---

## Estimated Timeline

**Focused effort** (full-time):
- Days 1-2: Protocol implementation (~300 lines)
- Day 3: DuckDB integration (~50 lines)
- Day 4: Type system (~100 lines)
- Day 5: Error handling + CLI (~100 lines)
- Days 6-7: Threading + testing (~100 lines)

**Total**: 7 days, ~650 lines

**Part-time** (evenings/weekends):
- Week 1: Protocol basics
- Week 2: DuckDB integration + types
- Week 3: Concurrency + polish

**Total**: 3 weeks part-time

---

## References

### **PostgreSQL Protocol Spec**:
- https://www.postgresql.org/docs/current/protocol.html
- https://www.postgresql.org/docs/current/protocol-message-formats.html
- https://www.postgresql.org/docs/current/protocol-flow.html

### **Existing Implementations to Study**:
- **pg8000**: Pure Python PostgreSQL driver (client side, but shows protocol)
- **asyncpg**: Async PostgreSQL (client side)
- **CockroachDB**: PostgreSQL-compatible server (Go)
- **YugabyteDB**: PostgreSQL-compatible server (C++)

### **Python Libraries**:
- `struct`: Binary packing/unpacking
- `socket`: TCP networking
- `threading`: Concurrent connections

---

## Quick Wins

### **What Already Works**:
- ✅ Session DuckDB (session_db.py)
- ✅ UDF registration (udf.py)
- ✅ windlass_udf() and windlass_cascade_udf()
- ✅ ATTACH support (DuckDB built-in)
- ✅ Temp tables
- ✅ HTTP API (for programmatic access)

### **What We Need to Build**:
- PostgreSQL message encoding/decoding (~300 lines)
- TCP server with threading (~300 lines)
- CLI command (~50 lines)

**That's it!** Everything else is already working.

---

## Decision: Build It?

### **Pros**:
- 🎯 **Unlocks native SQL tool support** (DBeaver, Tableau, dbt)
- 🎯 **Standard connection strings** (postgresql://...)
- 🎯 **Industry standard** (everyone knows PG protocol)
- ✅ **Reuses existing Windlass infrastructure** (session DuckDB, UDFs)
- ✅ **Relatively simple** (~650 lines for minimal version)

### **Cons**:
- ⏰ **Time investment** (1 week focused OR 3 weeks part-time)
- 🐛 **Protocol complexity** (binary format, edge cases)
- 🔧 **Maintenance** (need to keep protocol compatible)

### **Alternatives**:
- HTTP API works today for Python/Jupyter (✅ shipped!)
- DuckDB UI server (limited, browser-only)
- Wait for DuckDB team (timeline unknown)

---

## My Recommendation

**Ship PostgreSQL protocol!** Here's why:

1. **High ROI**: ~650 lines of code → Tableau/DBeaver/DataGrip/dbt all work
2. **Leverage existing work**: Session DuckDB + UDFs already perfect
3. **Differentiation**: "Query Windlass with any SQL tool" is a killer feature
4. **Composable**: HTTP API + PG Protocol serve different use cases

**Phased approach**:
- ✅ **Already done**: HTTP API (Python clients, Jupyter)
- 🚧 **Week 1**: Basic PG protocol (psql works)
- 🚧 **Week 2**: Polish (DBeaver/DataGrip work)
- ⏸️ **Later**: Auth, SSL, prepared statements

---

## Let's Build It!

Want me to start implementing? We can do:

**Today**: Phase 1 (postgres_protocol.py - message encoding)
**Tomorrow**: Phase 2 (postgres_server.py - TCP server)
**Day 3**: Test with psql
**Day 4**: Test with DBeaver

**In one week, you'll have**:
```bash
windlass server --port 5432

# From DBeaver:
postgresql://localhost:5432/default

# Write SQL with LLMs:
SELECT windlass_udf('Extract brand', product_name) FROM products;
```

**Native. SQL. Tools. With. LLM. Superpowers!** 🚀

Ready to start? 😎
