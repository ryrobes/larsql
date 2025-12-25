# Extended Query Protocol Implementation Plan

## 🎯 **Goal**

Eliminate the need for `preferQueryMode=simple` by implementing PostgreSQL's Extended Query Protocol (prepared statements).

**Current state:** Simple Query Protocol only (requires `preferQueryMode=simple` in DBeaver)

**Target state:** Full Extended Query Protocol support (works with all clients without configuration)

---

## 📋 **What Extended Query Protocol Enables**

| Feature | Simple Query | Extended Query |
|---------|--------------|----------------|
| **Prepared statements** | ❌ Re-parse every time | ✅ Parse once, execute many times |
| **Parameter binding** | ❌ String concatenation | ✅ Type-safe binding |
| **SQL injection prevention** | ⚠️ Manual escaping | ✅ Automatic (parameters separated) |
| **Performance** | ⚠️ Parse overhead | ✅ Cached statements |
| **Type safety** | ❌ No type checking | ✅ Type validation |
| **Client support** | ⚠️ psql, some tools | ✅ **ALL tools** |
| **ORM support** | ❌ Limited | ✅ SQLAlchemy, Django, etc. |

---

## 🔍 **Protocol Deep Dive**

### **The Five Essential Messages**

#### **1. Parse ('P') - Prepare a Statement**

**Purpose:** Pre-parse SQL with parameter placeholders ($1, $2, ...)

**Client sends:**
```
Message type: 'P' (0x50)
Payload:
  - Statement name (string, null-terminated) - "" for unnamed
  - SQL query (string, null-terminated) - "SELECT * FROM users WHERE id = $1"
  - Parameter count (int16)
  - Parameter type OIDs (int32[]) - [23] for INTEGER
```

**Server responds:**
```
ParseComplete ('1')
```

**What we need to store:**
```python
self.prepared_statements = {
    "": {  # unnamed statement (most common)
        "query": "SELECT * FROM users WHERE id = $1",
        "param_types": [23],  # INTEGER
        "param_count": 1
    }
}
```

---

#### **2. Bind ('B') - Bind Parameters**

**Purpose:** Bind actual values to prepared statement, creating a "portal"

**Client sends:**
```
Message type: 'B' (0x42)
Payload:
  - Portal name (string, null-terminated) - "" for unnamed
  - Statement name (string, null-terminated)
  - Parameter format codes (int16[]) - [0] for text format
  - Parameter count (int16)
  - Parameter values:
      - Length (int32) - -1 for NULL
      - Value (bytes)
  - Result format codes (int16[]) - [0] for text format
```

**Example:**
```
Bind(
    portal="",
    statement="",
    param_formats=[0],  # text
    param_values=[b'1234'],  # The value "1234" for $1
    result_formats=[0]  # text results
)
```

**Server responds:**
```
BindComplete ('2')
```

**What we need to store:**
```python
self.portals = {
    "": {  # unnamed portal
        "statement_name": "",
        "params": [1234],  # Converted to Python int
        "result_format": 0
    }
}
```

---

#### **3. Describe ('D') - Get Metadata**

**Purpose:** Get parameter types and result columns before execution

**Client sends:**
```
Message type: 'D' (0x44)
Payload:
  - Type: 'S' (statement) or 'P' (portal)
  - Name (string, null-terminated)
```

**Server responds:**
```
ParameterDescription ('t') - List of parameter type OIDs
RowDescription ('T') - Column metadata (same as Simple Query)
  OR
NoData ('n') - No result set (for INSERT/UPDATE/DELETE)
```

---

#### **4. Execute ('E') - Execute Portal**

**Purpose:** Execute a bound portal and return results

**Client sends:**
```
Message type: 'E' (0x45)
Payload:
  - Portal name (string, null-terminated)
  - Max rows (int32) - 0 = all rows, N = fetch N rows (cursor support)
```

**Server responds:**
```
DataRow ('D') * N
CommandComplete ('C')
```

**Note:** Does NOT send ReadyForQuery! That comes after Sync.

---

#### **5. Sync ('S') - Synchronization Point**

**Purpose:** End of message batch, flush responses

**Client sends:**
```
Message type: 'S' (0x53)
Payload: (empty)
```

**Server responds:**
```
ReadyForQuery ('Z')
```

**Critical:** Extended protocol allows **pipelining** (send multiple messages without waiting). Sync forces server to process all pending messages and report status.

---

#### **6. Close ('C') - Close Statement/Portal**

**Purpose:** Free resources for prepared statement or portal

**Client sends:**
```
Message type: 'C' (0x43)
Payload:
  - Type: 'S' (statement) or 'P' (portal)
  - Name (string, null-terminated)
```

**Server responds:**
```
CloseComplete ('3')
```

---

## 🔄 **Typical Extended Query Flow**

```
Client                              Server
  │
  ├─ Parse("", "SELECT * FROM users WHERE id = $1", [23])
  │                                    ├─ ParseComplete
  │
  ├─ Bind("", "", [1234])
  │                                    ├─ BindComplete
  │
  ├─ Execute("", max_rows=0)
  │                                    ├─ DataRow(1234, 'Alice', ...)
  │                                    ├─ CommandComplete("SELECT 1")
  │
  ├─ Sync
  │                                    ├─ ReadyForQuery('I')
  │
  ├─ Bind("", "", [5678])              ← Reuse same prepared statement!
  │                                    ├─ BindComplete
  │
  ├─ Execute("", max_rows=0)
  │                                    ├─ DataRow(5678, 'Bob', ...)
  │                                    ├─ CommandComplete("SELECT 1")
  │
  ├─ Sync
  │                                    ├─ ReadyForQuery('I')
  │
  ├─ Close('S', "")                    ← Close statement
  │                                    ├─ CloseComplete
  │
  ├─ Sync
  │                                    ├─ ReadyForQuery('I')
```

**Key advantage:** Statement parsed **once**, executed **twice** with different parameters!

---

## 🛠️ **Implementation Plan**

### **Phase 1: Message Decoders (Day 1-2)**

**File:** `rvbbit/rvbbit/server/postgres_protocol.py`

**Add these classes:**

```python
class ParseMessage:
    @staticmethod
    def decode(payload: bytes) -> dict:
        """Decode Parse message."""
        offset = 0

        # Statement name (null-terminated)
        null_idx = payload.find(b'\x00', offset)
        statement_name = payload[offset:null_idx].decode('utf-8')
        offset = null_idx + 1

        # Query string (null-terminated)
        null_idx = payload.find(b'\x00', offset)
        query = payload[offset:null_idx].decode('utf-8')
        offset = null_idx + 1

        # Parameter count (2 bytes)
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
    @staticmethod
    def decode(payload: bytes) -> dict:
        """Decode Bind message."""
        offset = 0

        # Portal name
        null_idx = payload.find(b'\x00', offset)
        portal_name = payload[offset:null_idx].decode('utf-8')
        offset = null_idx + 1

        # Statement name
        null_idx = payload.find(b'\x00', offset)
        statement_name = payload[offset:null_idx].decode('utf-8')
        offset = null_idx + 1

        # Parameter format codes count (int16)
        format_count = struct.unpack('!H', payload[offset:offset+2])[0]
        offset += 2

        # Parameter format codes (0=text, 1=binary)
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
            # Length (-1 = NULL)
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
    @staticmethod
    def decode(payload: bytes) -> dict:
        """Decode Describe message."""
        describe_type = chr(payload[0])  # 'S' or 'P'
        name = payload[1:].rstrip(b'\x00').decode('utf-8')
        return {
            'type': describe_type,
            'name': name
        }


class ExecuteMessage:
    @staticmethod
    def decode(payload: bytes) -> dict:
        """Decode Execute message."""
        null_idx = payload.find(b'\x00')
        portal_name = payload[:null_idx].decode('utf-8')
        max_rows = struct.unpack('!I', payload[null_idx+1:null_idx+5])[0]
        return {
            'portal_name': portal_name,
            'max_rows': max_rows
        }


class CloseMessage:
    @staticmethod
    def decode(payload: bytes) -> dict:
        """Decode Close message."""
        close_type = chr(payload[0])  # 'S' or 'P'
        name = payload[1:].rstrip(b'\x00').decode('utf-8')
        return {
            'type': close_type,
            'name': name
        }
```

**Response encoders:**

```python
class ParseComplete:
    @staticmethod
    def encode() -> bytes:
        return PostgresMessage.build_message(ord('1'), b'')

class BindComplete:
    @staticmethod
    def encode() -> bytes:
        return PostgresMessage.build_message(ord('2'), b'')

class CloseComplete:
    @staticmethod
    def encode() -> bytes:
        return PostgresMessage.build_message(ord('3'), b'')

class ParameterDescription:
    @staticmethod
    def encode(param_types: List[int]) -> bytes:
        payload = struct.pack('!H', len(param_types))
        for oid in param_types:
            payload += struct.pack('!I', oid)
        return PostgresMessage.build_message(ord('t'), payload)

class NoData:
    @staticmethod
    def encode() -> bytes:
        return PostgresMessage.build_message(ord('n'), b'')
```

**Estimated:** ~300 lines

---

### **Phase 2: Server State Management (Day 2-3)**

**File:** `rvbbit/rvbbit/server/postgres_server.py`

**Extend ClientConnection class:**

```python
class ClientConnection:
    def __init__(self, sock, addr, session_prefix='pg_client'):
        # ... existing fields ...

        # Extended Query Protocol state
        self.prepared_statements = {}  # name → {query, param_types, ...}
        self.portals = {}               # name → {statement, params, ...}

    def handle_parse(self, msg: dict):
        """Handle Parse message."""
        stmt_name = msg['statement_name']
        query = msg['query']
        param_types = msg['param_types']

        print(f"[{self.session_id}]   🔧 Parse statement '{stmt_name}': {query[:80]}...")

        # Store prepared statement
        self.prepared_statements[stmt_name] = {
            'query': query,
            'param_types': param_types,
            'param_count': len(param_types)
        }

        # Send ParseComplete
        self.sock.sendall(ParseComplete.encode())

    def handle_bind(self, msg: dict):
        """Handle Bind message."""
        portal_name = msg['portal_name']
        stmt_name = msg['statement_name']
        param_values = msg['param_values']
        param_formats = msg['param_formats']

        print(f"[{self.session_id}]   🔗 Bind portal '{portal_name}' to '{stmt_name}'")

        # Get prepared statement
        if stmt_name not in self.prepared_statements:
            raise Exception(f"Prepared statement '{stmt_name}' does not exist")

        stmt = self.prepared_statements[stmt_name]

        # Convert parameter values from wire format to Python types
        params = []
        for i, value_bytes in enumerate(param_values):
            if value_bytes is None:
                params.append(None)
            else:
                # Get format (0=text, 1=binary)
                fmt = param_formats[i] if i < len(param_formats) else param_formats[0]

                if fmt == 0:  # Text format
                    value_str = value_bytes.decode('utf-8')

                    # Get parameter type OID
                    param_type = stmt['param_types'][i] if i < len(stmt['param_types']) else 0

                    # Cast based on type
                    if param_type == 23:  # INTEGER
                        params.append(int(value_str))
                    elif param_type == 20:  # BIGINT
                        params.append(int(value_str))
                    elif param_type == 701:  # DOUBLE
                        params.append(float(value_str))
                    elif param_type == 16:  # BOOLEAN
                        params.append(value_str.lower() in ('t', 'true', '1'))
                    else:  # VARCHAR, TEXT, etc.
                        params.append(value_str)
                else:
                    # Binary format (TODO: implement)
                    raise Exception("Binary parameter format not yet supported")

        # Store portal
        self.portals[portal_name] = {
            'statement_name': stmt_name,
            'params': params,
            'result_formats': msg['result_formats'],
            'query': stmt['query']
        }

        # Send BindComplete
        self.sock.sendall(BindComplete.encode())

    def handle_describe(self, msg: dict):
        """Handle Describe message."""
        describe_type = msg['type']
        name = msg['name']

        print(f"[{self.session_id}]   📋 Describe {describe_type} '{name}'")

        if describe_type == 'S':  # Statement
            if name not in self.prepared_statements:
                raise Exception(f"Statement '{name}' does not exist")

            stmt = self.prepared_statements[name]

            # Send ParameterDescription
            self.sock.sendall(ParameterDescription.encode(stmt['param_types']))

            # Send RowDescription or NoData
            # For now, send NoData (TODO: parse query to determine columns)
            self.sock.sendall(NoData.encode())

        elif describe_type == 'P':  # Portal
            if name not in self.portals:
                raise Exception(f"Portal '{name}' does not exist")

            # Send RowDescription or NoData
            self.sock.sendall(NoData.encode())

    def handle_execute(self, msg: dict):
        """Handle Execute message."""
        portal_name = msg['portal_name']
        max_rows = msg['max_rows']

        print(f"[{self.session_id}]   ▶️  Execute portal '{portal_name}' (max_rows={max_rows})")

        # Get portal
        if portal_name not in self.portals:
            raise Exception(f"Portal '{portal_name}' does not exist")

        portal = self.portals[portal_name]
        query = portal['query']
        params = portal['params']

        # Convert PostgreSQL placeholders ($1, $2) to DuckDB placeholders (?)
        duckdb_query = query
        for i in range(len(params), 0, -1):  # Reverse order to avoid conflicts
            duckdb_query = duckdb_query.replace(f'${i}', '?')

        # Execute with parameters
        result_df = self.duckdb_conn.execute(duckdb_query, params).fetchdf()

        # Limit rows if max_rows > 0
        if max_rows > 0:
            result_df = result_df.head(max_rows)

        # Send results (same as Simple Query, but NO ReadyForQuery yet!)
        send_execute_results(self.sock, result_df)

    def handle_close(self, msg: dict):
        """Handle Close message."""
        close_type = msg['type']
        name = msg['name']

        print(f"[{self.session_id}]   🗑️  Close {close_type} '{name}'")

        if close_type == 'S':  # Statement
            if name in self.prepared_statements:
                del self.prepared_statements[name]
        elif close_type == 'P':  # Portal
            if name in self.portals:
                del self.portals[name]

        # Send CloseComplete
        self.sock.sendall(CloseComplete.encode())

    def handle_sync(self):
        """Handle Sync message."""
        print(f"[{self.session_id}]   🔄 Sync")

        # Send ReadyForQuery with current transaction status
        self.sock.sendall(ReadyForQuery.encode(self.transaction_status))
```

**Update message loop:**

```python
def handle(self):
    while self.running:
        msg_type, payload = PostgresMessage.read_message(self.sock)

        if msg_type is None:
            break

        # Simple Query Protocol (keep existing)
        if msg_type == MessageType.QUERY:
            query = payload.rstrip(b'\x00').decode('utf-8')
            self.handle_query(query)

        # Extended Query Protocol (NEW!)
        elif msg_type == MessageType.PARSE:
            msg = ParseMessage.decode(payload)
            self.handle_parse(msg)

        elif msg_type == MessageType.BIND:
            msg = BindMessage.decode(payload)
            self.handle_bind(msg)

        elif msg_type == MessageType.DESCRIBE:
            msg = DescribeMessage.decode(payload)
            self.handle_describe(msg)

        elif msg_type == MessageType.EXECUTE:
            msg = ExecuteMessage.decode(payload)
            self.handle_execute(msg)

        elif msg_type == MessageType.CLOSE:
            msg = CloseMessage.decode(payload)
            self.handle_close(msg)

        elif msg_type == MessageType.SYNC:
            self.handle_sync()

        elif msg_type == MessageType.TERMINATE:
            break

        else:
            print(f"[{self.session_id}]   ⚠️  Unknown message type: {msg_type}")
```

**Estimated:** ~250 lines

---

### **Phase 3: Helper Functions (Day 3)**

**Create new helper in postgres_protocol.py:**

```python
def send_execute_results(sock, result_df):
    """
    Send Execute results (like send_query_results but WITHOUT ReadyForQuery).

    Extended protocol sends ReadyForQuery only after Sync, not after Execute!
    """
    # 1. Send RowDescription
    columns = [...]  # Same as send_query_results
    sock.sendall(RowDescription.encode(columns))

    # 2. Send DataRows
    for idx, row in result_df.iterrows():
        values = [row[col] for col in result_df.columns]
        sock.sendall(DataRow.encode(values))

    # 3. Send CommandComplete
    row_count = len(result_df)
    command_tag = f"SELECT {row_count}"
    sock.sendall(CommandComplete.encode(command_tag))

    # 4. NO ReadyForQuery! (that comes after Sync)
```

**Estimated:** ~50 lines

---

### **Phase 4: Testing (Day 4-5)**

**Test cases:**

#### **Test 1: Basic prepared statement (psycopg2)**

```python
import psycopg2

# Connect WITHOUT preferQueryMode=simple
conn = psycopg2.connect("postgresql://localhost:15432/default")
cur = conn.cursor()

# This will use Extended protocol automatically!
cur.execute("SELECT * FROM users WHERE id = %s", (123,))
rows = cur.fetchall()
```

**Expected:** Works without configuration!

#### **Test 2: Reuse prepared statement**

```python
# Execute same query multiple times (should reuse Parse)
for user_id in [123, 456, 789]:
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    print(cur.fetchone())
```

**Expected:** Parse happens once, Execute happens 3 times (faster!)

#### **Test 3: Named prepared statement**

```sql
PREPARE user_lookup AS SELECT * FROM users WHERE id = $1;
EXECUTE user_lookup(123);
EXECUTE user_lookup(456);
DEALLOCATE user_lookup;
```

**Expected:** Works like PostgreSQL!

#### **Test 4: DBeaver without preferQueryMode**

1. Delete old connection in DBeaver
2. Create new connection: `postgresql://localhost:15432/default`
3. **Don't add** `preferQueryMode=simple`!
4. Execute queries normally

**Expected:** Everything works!

---

## 🎯 **Implementation Effort Estimate**

| Phase | Task | Lines of Code | Time | Difficulty |
|-------|------|---------------|------|------------|
| 1 | Message decoders/encoders | ~300 | 1-2 days | Medium |
| 2 | Server handlers (Parse/Bind/Execute) | ~250 | 1-2 days | Medium |
| 3 | Helper functions | ~50 | 0.5 days | Easy |
| 4 | Testing & debugging | ~100 | 1-2 days | Medium |
| **Total** | | **~700 lines** | **3-5 days** | **Medium** |

---

## 🚀 **Benefits After Implementation**

### **User Experience:**

| Feature | Before | After |
|---------|--------|-------|
| DBeaver setup | Need `preferQueryMode=simple` | ✅ **Zero configuration!** |
| ORMs (SQLAlchemy) | Don't work | ✅ **Work natively!** |
| Parameter binding | Manual escaping | ✅ **Type-safe!** |
| Performance | Re-parse every query | ✅ **Cached statements!** |
| Security | SQL injection risk | ✅ **Safe by design!** |

### **Developer Experience:**

**Before:**
```python
# Have to use Simple Query mode
conn = psycopg2.connect("postgresql://localhost:15432/default?preferQueryMode=simple")

# Manual string formatting (SQL injection risk!)
user_id = "123"
cur.execute(f"SELECT * FROM users WHERE id = {user_id}")
```

**After:**
```python
# Just works!
conn = psycopg2.connect("postgresql://localhost:15432/default")

# Safe parameter binding!
user_id = 123
cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
```

---

## 🗺️ **Implementation Roadmap**

### **Week 1: Core Protocol**

**Days 1-2:** Message decoders (Parse, Bind, Execute, Describe, Close, Sync)
- Add to `postgres_protocol.py`
- Unit tests for each decoder
- Verify payload parsing

**Days 3-4:** Server handlers
- Add to `postgres_server.py`
- State management (prepared_statements, portals)
- Message loop integration

**Day 5:** Helper functions
- `send_execute_results()` (without ReadyForQuery)
- Parameter conversion (text → Python types)
- Placeholder conversion (PostgreSQL $1 → DuckDB ?)

### **Week 2: Integration & Testing**

**Days 6-7:** Testing with psycopg2
- Basic prepared statements
- Parameter binding
- Statement reuse
- Error handling

**Days 8-9:** Testing with DBeaver
- Remove `preferQueryMode=simple`
- Verify all queries work
- Edge cases

**Day 10:** Polish & documentation
- Error messages
- Logging
- Documentation updates

---

## 🔬 **Technical Challenges**

### **Challenge 1: Placeholder Conversion**

PostgreSQL uses `$1, $2, $3`, DuckDB uses `?`.

**Solution:**
```python
# Convert placeholders (reverse order to avoid conflicts!)
query = "SELECT * FROM users WHERE id = $1 AND status = $2"
for i in range(param_count, 0, -1):
    query = query.replace(f'${i}', '?')
# Result: "SELECT * FROM users WHERE id = ? AND status = ?"
```

### **Challenge 2: Type Conversion**

Parameters come as bytes, need to convert to Python types based on OID.

**Solution:**
```python
def convert_param(value_bytes: bytes, type_oid: int, format: int):
    if format == 0:  # Text format
        value_str = value_bytes.decode('utf-8')
        if type_oid == 23:  # INTEGER
            return int(value_str)
        elif type_oid == 701:  # DOUBLE
            return float(value_str)
        # ... etc
    else:  # Binary format (phase 2)
        # Decode binary representation
        pass
```

### **Challenge 3: Statement Lifecycle**

Must track when to free resources.

**Solution:**
```python
# Unnamed statements/portals are reused
if stmt_name == "":
    # Overwrite previous unnamed statement
    self.prepared_statements[""] = new_stmt

# Named statements persist until Close
if stmt_name:
    self.prepared_statements[stmt_name] = new_stmt
```

---

## 📊 **Success Metrics**

After implementation:

- [ ] psycopg2 works without `preferQueryMode=simple`
- [ ] DBeaver works without driver properties
- [ ] SQLAlchemy can connect and query
- [ ] Django ORM can use RVBBIT as database
- [ ] Parameter binding prevents SQL injection
- [ ] Prepared statement reuse improves performance
- [ ] All existing tests still pass

---

## 🎓 **References**

### **PostgreSQL Documentation**
- https://www.postgresql.org/docs/current/protocol-flow.html#PROTOCOL-FLOW-EXT-QUERY
- https://www.postgresql.org/docs/current/protocol-message-formats.html

### **Example Implementations**
- **pg8000** (Python PostgreSQL driver) - Shows client-side Extended protocol
- **CockroachDB** - PostgreSQL-compatible server implementation
- **YugabyteDB** - Another PostgreSQL-compatible server

### **Testing Tools**
- **psycopg2** - Will use Extended protocol by default
- **DBeaver** - Can toggle between Simple and Extended
- **pgbench** - PostgreSQL benchmarking tool (uses prepared statements)

---

## 🚦 **Go/No-Go Decision**

### **Reasons to Implement:**

✅ **High ROI:** ~700 lines → Full PostgreSQL compatibility
✅ **User value:** Zero configuration for all clients
✅ **Security:** Parameter binding prevents SQL injection
✅ **Performance:** Prepared statement caching
✅ **Ecosystem:** ORMs, BI tools, all work natively

### **Reasons to Wait:**

⚠️ **Time investment:** 1-2 weeks focused development
⚠️ **Complexity:** Binary protocol, edge cases
⚠️ **Current workaround:** `preferQueryMode=simple` works fine

### **Recommendation:**

**Implement it!** You've already invested in PostgreSQL wire protocol. Extended Query is the natural next step to complete the implementation.

**Current state:** 75% PostgreSQL compatibility
**After Extended Query:** 95% PostgreSQL compatibility

The final 5% (SSL, SCRAM auth, etc.) can wait!

---

## 📅 **Proposed Timeline**

**If starting today:**

- **Week 1 (Dec 26 - Jan 1):** Core implementation (message handling)
- **Week 2 (Jan 2 - Jan 8):** Testing, debugging, polish
- **Target completion:** January 8, 2025

**Part-time (evenings/weekends):**

- **Week 1-2:** Message decoders
- **Week 3-4:** Server handlers
- **Week 5-6:** Testing & polish
- **Target completion:** Early February 2025

---

## ✅ **Ready to Start?**

When you're ready to implement, we'll:

1. Start with `ParseMessage.decode()` in `postgres_protocol.py`
2. Add unit tests for message parsing
3. Implement `handle_parse()` in `postgres_server.py`
4. Test with simple psycopg2 script
5. Iterate through Bind, Execute, Sync
6. Full integration testing
7. Remove `preferQueryMode=simple` from all docs!

---

**This plan is ready to execute whenever you are!** 🚀
