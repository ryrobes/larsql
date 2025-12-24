# DuckDB Server Mode: Expose Windlass UDFs to External SQL Clients

*Turn your session DuckDB into a queryable server with LLM superpowers!*

---

## The Vision

```bash
# Start Windlass server
windlass server --port 5432 --protocol postgres

# From another terminal (or another machine!)
psql postgresql://windlass:password@localhost:5432/default

# Now you can use LLM UDFs from ANY SQL client!
windlass=> SELECT
  customer_name,
  windlass_udf('Extract industry', company_name) as industry,
  windlass_cascade_udf('tackle/fraud.yaml', json_object('id', customer_id)) as fraud_check
FROM customers
LIMIT 10;

 customer_name  | industry      | fraud_check
----------------+---------------+---------------------------
 Acme Corp      | Manufacturing | {"risk_score": 0.2, ...}
 Tech Startup   | Technology    | {"risk_score": 0.1, ...}
```

**ANY tool that speaks SQL can now use LLMs!**

---

## Architecture Options

### Option 1: PostgreSQL Wire Protocol (RECOMMENDED)

**Why**: Every SQL tool speaks PostgreSQL protocol!

```
External SQL Client (DataGrip, Tableau, psql, Python)
    ↓ PostgreSQL wire protocol (port 5432)
PostgreSQL Protocol Server (Python wrapper)
    ↓ DuckDB Python API
Session DuckDB with windlass_udf() + windlass_cascade_udf() registered
    ↓ On UDF call
Windlass Agent + Cascade Runner
    ↓
LLM APIs (OpenRouter, etc.)
```

**Benefits**:
- ✅ Works with ALL PostgreSQL clients (psql, DataGrip, DBeaver, pgAdmin, Python psycopg2, etc.)
- ✅ Standard connection strings: `postgresql://user:pass@host:5432/dbname`
- ✅ Tools think it's Postgres (full compatibility!)
- ✅ ATTACH works (DuckDB can attach real Postgres, MySQL, S3)

**Challenges**:
- ⚠️ Need to implement PostgreSQL protocol (wire format, authentication)
- ⚠️ Some Postgres-specific features won't work (triggers, stored procs)

---

### Option 2: HTTP/REST API (SIMPLEST)

**Why**: You already have Flask in the dashboard!

```python
# In dashboard/backend/app.py

@app.route('/api/sql/query', methods=['POST'])
def execute_sql():
    """
    Execute SQL query with windlass UDFs.

    POST body:
    {
      "query": "SELECT windlass_udf('...', col) FROM table",
      "session_id": "my_session_123"  # Optional
    }
    """
    query = request.json.get('query')
    session_id = request.json.get('session_id', f"api_{uuid.uuid4().hex[:8]}")

    # Get or create session DuckDB
    from windlass.sql_tools.session_db import get_session_db
    from windlass.sql_tools.udf import register_windlass_udf

    conn = get_session_db(session_id)
    register_windlass_udf(conn)

    # Execute query
    result = conn.execute(query).fetchdf()

    return jsonify({
        "columns": list(result.columns),
        "rows": result.to_dict('records'),
        "row_count": len(result),
        "session_id": session_id
    })
```

**Client Usage**:
```python
# From Python
import requests

response = requests.post('http://localhost:5001/api/sql/query', json={
    "query": """
        SELECT
          customer_name,
          windlass_udf('Extract industry', company_name) as industry
        FROM customers
        LIMIT 10
    """
})

data = response.json()
print(data['rows'])  # Results with LLM-enriched columns!
```

**Benefits**:
- ✅ Easy to implement (15 minutes!)
- ✅ Already have Flask server
- ✅ Works from anywhere (HTTP is universal)
- ✅ Can add authentication easily

**Limitations**:
- ❌ Not standard SQL protocol (custom HTTP API)
- ❌ Can't use with SQL GUIs (DataGrip, Tableau)
- ❌ Requires HTTP client (not standard DB drivers)

---

### Option 3: DuckDB with Network Access (FUTURE)

DuckDB is working on native server mode, but it's not production-ready yet.

**Current state**: Experimental HTTP API in DuckDB core

**Future** (when DuckDB ships it):
```python
# Start DuckDB in server mode
conn = duckdb.connect(':memory:')
conn.execute("LOAD httpserver")
conn.execute("SELECT * FROM httpserver_start('0.0.0.0', 8080)")
```

**Status**: Not ready for production
**Timeline**: Unknown (DuckDB roadmap item)

---

## RECOMMENDED IMPLEMENTATION: Hybrid Approach

### **Phase 1: HTTP API** (Ship This Week)
Simple, works today, 15 minutes to implement

### **Phase 2: PostgreSQL Protocol** (Next Month)
Full SQL client compatibility, standard tooling

### **Phase 3: DuckDB Native Server** (When Available)
Replace custom solution with official DuckDB server

---

## Implementation: HTTP API (15 Minutes)

### **Backend Code**:

```python
# dashboard/backend/sql_api.py (NEW FILE)

from flask import Blueprint, request, jsonify
from windlass.sql_tools.session_db import get_session_db
from windlass.sql_tools.udf import register_windlass_udf
import uuid
import pandas as pd

sql_api = Blueprint('sql_api', __name__)


@sql_api.route('/api/sql/query', methods=['POST'])
def execute_query():
    """
    Execute SQL query with Windlass UDFs.

    POST /api/sql/query
    {
      "query": "SELECT windlass_udf('...', col) FROM table",
      "session_id": "optional_session_id",
      "format": "json|csv|arrow"  # Optional output format
    }

    Returns:
    {
      "columns": ["col1", "col2"],
      "rows": [{"col1": "val1", "col2": "val2"}, ...],
      "row_count": 10,
      "session_id": "session_123",
      "execution_time_ms": 1234
    }
    """
    import time
    start = time.time()

    query = request.json.get('query')
    session_id = request.json.get('session_id', f"api_{uuid.uuid4().hex[:8]}")
    output_format = request.json.get('format', 'json')

    if not query:
        return jsonify({"error": "No query provided"}), 400

    try:
        # Get session DuckDB and register UDFs
        conn = get_session_db(session_id)
        register_windlass_udf(conn)

        # Execute query
        result_df = conn.execute(query).fetchdf()

        execution_time_ms = (time.time() - start) * 1000

        # Format response based on requested format
        if output_format == 'csv':
            csv_data = result_df.to_csv(index=False)
            return csv_data, 200, {'Content-Type': 'text/csv'}

        elif output_format == 'arrow':
            import pyarrow as pa
            table = pa.Table.from_pandas(result_df)
            # Return Arrow IPC format
            sink = pa.BufferOutputStream()
            writer = pa.ipc.RecordBatchStreamWriter(sink, table.schema)
            writer.write_table(table)
            writer.close()
            return sink.getvalue().to_pybytes(), 200, {'Content-Type': 'application/vnd.apache.arrow.stream'}

        else:  # JSON (default)
            return jsonify({
                "columns": list(result_df.columns),
                "rows": result_df.to_dict('records'),
                "row_count": len(result_df),
                "session_id": session_id,
                "execution_time_ms": execution_time_ms
            })

    except Exception as e:
        return jsonify({
            "error": str(e),
            "session_id": session_id
        }), 500


@sql_api.route('/api/sql/sessions', methods=['GET'])
def list_sessions():
    """List active DuckDB sessions."""
    from windlass.sql_tools.session_db import _session_dbs

    sessions = []
    for session_id, conn in _session_dbs.items():
        # Get table count
        try:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = [t[0] for t in tables]
        except:
            table_names = []

        sessions.append({
            "session_id": session_id,
            "table_count": len(table_names),
            "tables": table_names
        })

    return jsonify({"sessions": sessions})


@sql_api.route('/api/sql/tables', methods=['GET'])
def list_tables():
    """List tables in a session."""
    session_id = request.args.get('session_id')

    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    try:
        conn = get_session_db(session_id)
        tables = conn.execute("SHOW TABLES").fetchdf()

        return jsonify({
            "session_id": session_id,
            "tables": tables.to_dict('records')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sql_api.route('/api/sql/schema', methods=['GET'])
def get_schema():
    """Get schema for a table."""
    session_id = request.args.get('session_id')
    table_name = request.args.get('table')

    if not session_id or not table_name:
        return jsonify({"error": "session_id and table required"}), 400

    try:
        conn = get_session_db(session_id)
        schema = conn.execute(f"DESCRIBE {table_name}").fetchdf()

        return jsonify({
            "session_id": session_id,
            "table": table_name,
            "columns": schema.to_dict('records')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

**Register in app.py**:
```python
from .sql_api import sql_api
app.register_blueprint(sql_api)
```

**Usage from Python**:
```python
import requests

# Execute query with LLM UDFs!
response = requests.post('http://localhost:5001/api/sql/query', json={
    "query": """
        SELECT
          product_name,
          windlass_udf('Extract brand', product_name) as brand,
          windlass_cascade_udf('tackle/fraud.yaml',
                              json_object('product_id', product_id)) as analysis
        FROM products
        LIMIT 100
    """
})

data = response.json()
for row in data['rows']:
    print(row)
```

---

## Implementation: PostgreSQL Wire Protocol (THE DREAM)

### **Using pg_wire Library**

```python
# windlass/server/postgres_server.py (NEW)

from pg_wire import PostgresServer, QueryResult
from windlass.sql_tools.session_db import get_session_db
from windlass.sql_tools.udf import register_windlass_udf
import duckdb


class WindlassPostgresServer(PostgresServer):
    """
    PostgreSQL wire protocol server backed by DuckDB with Windlass UDFs.

    Clients connect thinking it's PostgreSQL, but it's DuckDB with LLM superpowers!
    """

    def __init__(self, host='0.0.0.0', port=5432, session_id='server_default'):
        super().__init__(host, port)
        self.session_id = session_id

        # Get session DuckDB and register UDFs
        self.conn = get_session_db(session_id)
        register_windlass_udf(self.conn)

    def handle_query(self, query: str) -> QueryResult:
        """Execute query against DuckDB."""
        try:
            result = self.conn.execute(query).fetchdf()

            return QueryResult(
                columns=list(result.columns),
                rows=result.values.tolist(),
                row_count=len(result)
            )

        except Exception as e:
            raise Exception(f"Query error: {e}")

    def handle_connect(self, username: str, database: str):
        """Handle client connection."""
        # Could create per-user sessions here
        print(f"Client connected: {username}@{database}")
        return True  # Accept connection

    def handle_disconnect(self):
        """Handle client disconnect."""
        print("Client disconnected")


def start_postgres_server(host='0.0.0.0', port=5432):
    """Start PostgreSQL-compatible server."""
    server = WindlassPostgresServer(host, port)
    print(f"Windlass PostgreSQL server listening on {host}:{port}")
    print("Connect with: psql postgresql://windlass@localhost:5432/default")
    server.serve_forever()
```

**Start server**:
```bash
windlass server --protocol postgres --port 5432
```

**Connect from any client**:
```bash
# psql
psql postgresql://windlass@localhost:5432/default

# Python
import psycopg2
conn = psycopg2.connect("postgresql://windlass@localhost:5432/default")
cur = conn.cursor()
cur.execute("SELECT windlass_udf('Extract brand', 'Apple iPhone') as brand")
print(cur.fetchone())  # ('Apple',)

# DataGrip / DBeaver / Any SQL IDE
# Just add connection: postgresql://windlass@localhost:5432/default
```

**Challenges**:
- Need to implement PostgreSQL protocol (authentication, query parsing, result encoding)
- Some Postgres-specific features won't work (PL/pgSQL, triggers, etc.)
- Need library support (pg_wire, or build from scratch)

---

## Option 2: HTTP API (FAST TO SHIP)

### **Implementation** (Dashboard Already Has Flask!)

```python
# In dashboard/backend/app.py

@app.route('/api/sql/execute', methods=['POST'])
def execute_sql_api():
    """
    Execute SQL with Windlass UDFs via HTTP.

    curl -X POST http://localhost:5001/api/sql/execute \
      -H 'Content-Type: application/json' \
      -d '{
        "query": "SELECT windlass_udf(\"Extract brand\", product_name) FROM products LIMIT 5",
        "session": "my_session"
      }'
    """
    query = request.json.get('query')
    session_id = request.json.get('session', f"http_session_{uuid.uuid4().hex[:8]}")

    # Get session DuckDB
    from windlass.sql_tools.session_db import get_session_db
    from windlass.sql_tools.udf import register_windlass_udf

    conn = get_session_db(session_id)
    register_windlass_udf(conn)

    try:
        df = conn.execute(query).fetchdf()

        return jsonify({
            "success": True,
            "columns": list(df.columns),
            "data": df.to_dict('records'),
            "row_count": len(df),
            "session_id": session_id
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "session_id": session_id
        }), 400
```

**Python Client**:
```python
# windlass/client/sql_client.py (NEW)

import requests
import pandas as pd

class WindlassClient:
    """Client for querying Windlass DuckDB server via HTTP."""

    def __init__(self, base_url='http://localhost:5001', session_id=None):
        self.base_url = base_url
        self.session_id = session_id or f"client_{uuid.uuid4().hex[:8]}"

    def execute(self, query: str) -> pd.DataFrame:
        """Execute SQL query, return DataFrame."""
        response = requests.post(
            f'{self.base_url}/api/sql/execute',
            json={'query': query, 'session': self.session_id}
        )

        if response.status_code != 200:
            raise Exception(f"Query failed: {response.json()['error']}")

        data = response.json()
        return pd.DataFrame(data['data'])

    def read_sql(self, query: str) -> pd.DataFrame:
        """Pandas-compatible alias."""
        return self.execute(query)


# Usage
client = WindlassClient('http://localhost:5001')

# Use LLM UDFs from Python!
df = client.execute("""
    SELECT
      product_name,
      windlass_udf('Extract brand', product_name) as brand,
      windlass_cascade_udf('tackle/fraud.yaml',
                          json_object('product_id', product_id)) as fraud_check
    FROM products
    LIMIT 100
""")

print(df)
```

**Benefits**:
- ✅ Fast to implement (already have Flask)
- ✅ Works over network (remote access)
- ✅ Easy authentication (API keys, JWT)
- ✅ Can add rate limiting, logging

**Limitations**:
- ❌ Custom protocol (not standard SQL)
- ❌ Requires HTTP client library
- ❌ Won't work with SQL GUIs

---

## Option 3: SQLite HTTP Proxy Pattern

**Use SQLite's HTTP VFS** + DuckDB:

```python
# Expose DuckDB via HTTP, clients connect via SQLite driver
# (SQLite has httpvfs extension)

# Not ideal - adds another layer
```

**Verdict**: Skip this, too hacky

---

## Option 4: ADBC (Arrow Database Connectivity)

**Apache Arrow's standard** for database connectivity:

```python
# windlass/server/adbc_server.py

from adbc_driver_manager import AdbcConnection, AdbcDatabase
import duckdb

class WindlassADBCDriver:
    """ADBC driver for Windlass DuckDB."""

    def connect(self, session_id='default'):
        # Return DuckDB connection with UDFs registered
        conn = get_session_db(session_id)
        register_windlass_udf(conn)
        return conn
```

**Client**:
```python
import adbc_driver_windlass

conn = adbc_driver_windlass.connect("windlass://localhost:5432")
df = conn.execute("SELECT windlass_udf(...) FROM data").fetch_arrow_table().to_pandas()
```

**Status**: Requires building ADBC driver (complex)
**Benefit**: Standard Arrow ecosystem integration

---

## THE RECOMMENDED PATH: Start with HTTP, Upgrade to Postgres Protocol

### **Week 1: HTTP API** (⚡ FAST)

```bash
# Start dashboard server (already running)
cd dashboard && python backend/app.py

# Query from Python
from windlass.client import WindlassClient
client = WindlassClient('http://localhost:5001')
df = client.execute("SELECT windlass_udf('Extract brand', name) FROM products")
```

**Enables**:
- Python clients (Jupyter notebooks!)
- API integrations
- Remote access

---

### **Month 1: PostgreSQL Protocol** (🎯 THE DREAM)

**Library Options**:
1. **pg8000** - Pure Python PostgreSQL protocol implementation
2. **asyncpg** - Async PostgreSQL protocol (Pythonic)
3. **Build from scratch** - Full control

**Best: Use `pg8000` as reference, build minimal server**

```python
# windlass/server/pg_server.py

import socket
import struct
from windlass.sql_tools.session_db import get_session_db
from windlass.sql_tools.udf import register_windlass_udf


class PostgresProtocolServer:
    """
    Minimal PostgreSQL wire protocol server.

    Implements just enough of the protocol for:
    - Authentication (simple, no SSL for v1)
    - Query execution (extended query protocol)
    - Result streaming (row data + column metadata)
    """

    def __init__(self, host='0.0.0.0', port=5432):
        self.host = host
        self.port = port
        self.sessions = {}  # session_id -> DuckDB connection

    def start(self):
        """Start server."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(5)

        print(f"PostgreSQL-compatible server listening on {self.host}:{self.port}")
        print("Connect with: psql postgresql://windlass@localhost:5432/default")

        while True:
            client_sock, addr = sock.accept()
            self.handle_client(client_sock, addr)

    def handle_client(self, sock, addr):
        """Handle client connection."""
        print(f"Client connected: {addr}")

        # Send startup response (authentication OK)
        self.send_auth_ok(sock)

        # Create session DuckDB for this client
        import uuid
        session_id = f"pg_client_{uuid.uuid4().hex[:8]}"
        conn = get_session_db(session_id)
        register_windlass_udf(conn)

        # Message loop
        while True:
            try:
                msg_type, msg_data = self.recv_message(sock)

                if msg_type == 'Q':  # Simple query
                    query = msg_data.decode('utf-8').strip('\x00')
                    self.handle_query(sock, conn, query)

                elif msg_type == 'X':  # Terminate
                    break

            except Exception as e:
                print(f"Error: {e}")
                break

        sock.close()

    def handle_query(self, sock, conn, query):
        """Execute query and return results."""
        try:
            # Execute with DuckDB
            result = conn.execute(query).fetchdf()

            # Send row description (column metadata)
            self.send_row_description(sock, result)

            # Send data rows
            for _, row in result.iterrows():
                self.send_data_row(sock, row)

            # Send command complete
            self.send_command_complete(sock, len(result))

        except Exception as e:
            self.send_error(sock, str(e))

    # Protocol implementation methods...
    # (send_auth_ok, recv_message, send_row_description, etc.)
```

**This is ~300-500 lines for minimal implementation.**

---

## Client Usage (Once Postgres Protocol Works)

### **psql (Command Line)**:
```bash
psql postgresql://windlass@localhost:5432/default

windlass=> SELECT
  product_name,
  windlass_udf('Extract brand', product_name) as brand
FROM products
LIMIT 5;

 product_name                              | brand
-------------------------------------------+--------
 Apple iPhone 15 Pro Max                   | Apple
 Samsung Galaxy S24 Ultra                  | Samsung
 Sony WH-1000XM5 Headphones                | Sony
```

---

### **DataGrip / DBeaver (SQL IDE)**:

**Connection Settings**:
- Host: localhost
- Port: 5432
- Database: default
- User: windlass
- Password: (optional)

**Then just write SQL**:
```sql
SELECT
  customer_id,
  company_name,
  windlass_udf('Extract industry', company_name) as industry,
  windlass_cascade_udf(
    'tackle/fraud_check.yaml',
    json_object('customer_id', customer_id, 'name', company_name)
  ) as fraud_analysis
FROM customers;
```

**Works in the IDE like any other function!**

---

### **Tableau (BI Tool)**:

**Connect to Data Source**:
- Server: localhost
- Port: 5432
- Database: windlass

**Create Calculated Field**:
```
RAWSQL("windlass_udf('Extract industry', %1)", [Company Name])
```

**Now you can drag-and-drop LLM-enriched columns in Tableau!**

---

### **Python (pandas)**:
```python
import pandas as pd
from sqlalchemy import create_engine

# Connect to Windlass server
engine = create_engine('postgresql://windlass@localhost:5432/default')

# Query with LLM UDFs!
df = pd.read_sql("""
    SELECT
      customer_name,
      windlass_udf('Extract industry', company_name) as industry,
      windlass_cascade_udf('tackle/customer_360.yaml',
                          json_object('customer_id', customer_id)) as analysis
    FROM customers
    LIMIT 1000
""", engine)

# Results include LLM-enriched columns!
print(df['industry'].value_counts())
```

---

### **Metabase / Superset (Analytics Dashboard)**:

Add Windlass as PostgreSQL data source, then:

```sql
-- Create dashboard with LLM-enriched metrics
SELECT
  windlass_udf('Extract industry', company_name) as industry,
  COUNT(*) as customer_count,
  AVG(revenue) as avg_revenue
FROM customers
GROUP BY industry
ORDER BY customer_count DESC;
```

**Real-time LLM analytics in your dashboard!**

---

## Security Considerations

### **Authentication**:

```python
# Simple API key auth
@app.route('/api/sql/execute', methods=['POST'])
@require_api_key
def execute_sql():
    ...

# Or JWT tokens
@app.route('/api/sql/execute', methods=['POST'])
@jwt_required
def execute_sql():
    user_id = get_jwt_identity()
    session_id = f"user_{user_id}_{uuid.uuid4().hex[:6]}"
    ...
```

### **Rate Limiting**:
```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=lambda: request.headers.get('X-API-Key'))

@app.route('/api/sql/execute', methods=['POST'])
@limiter.limit("100 per hour")  # Prevent abuse
def execute_sql():
    ...
```

### **Query Validation**:
```python
# Block dangerous operations
BLOCKED_KEYWORDS = ['DROP', 'DELETE', 'TRUNCATE', 'ALTER']

def validate_query(query):
    query_upper = query.upper()
    for keyword in BLOCKED_KEYWORDS:
        if keyword in query_upper:
            raise ValueError(f"Forbidden operation: {keyword}")
```

### **Sandboxing**:
```python
# Per-user isolated sessions
@app.route('/api/sql/execute', methods=['POST'])
def execute_sql():
    user_id = authenticate_user(request)
    session_id = f"user_{user_id}_sandbox"

    # Each user gets isolated DuckDB
    conn = get_session_db(session_id)

    # They can only see their own temp tables!
    ...
```

---

## The Killer Feature Stack

Once server mode is working:

**From Tableau**:
```sql
-- Connect Tableau to Windlass server
-- Create viz with LLM-enriched data!
SELECT
  DATE_TRUNC('month', order_date) as month,
  windlass_udf('Extract product category', product_name) as category,
  SUM(amount) as revenue
FROM orders
GROUP BY month, category;
```

**From Jupyter**:
```python
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine('postgresql://windlass@localhost:5432/default')

# Attach external database
engine.execute("ATTACH 'postgres://prod...' AS prod (TYPE POSTGRES)")

# Query prod DB with LLM enrichment!
df = pd.read_sql("""
    SELECT
      customer_id,
      company_name,
      windlass_udf('Extract industry', company_name) as industry,
      windlass_cascade_udf('tackle/churn_prediction.yaml',
                          json_object('customer_id', customer_id)) as churn_analysis
    FROM prod.customers
    WHERE last_purchase > CURRENT_DATE - INTERVAL '30 days'
""", engine)

# All your pandas/scikit-learn pipelines can use LLM-enriched data!
```

**From Metabase**:
- Add Windlass as PostgreSQL data source
- Create Questions with windlass_udf() in SQL
- Build dashboards with LLM-powered metrics
- Schedule daily refreshes (with caching!)

---

## Implementation Roadmap

### **Phase 1: HTTP API** (THIS WEEK - 1 hour)

```python
# Add to dashboard/backend/app.py
@app.route('/api/sql/execute', methods=['POST'])
def execute_sql():
    # 30 lines of code
    ...
```

**Enables**:
- Python clients
- API integrations
- Remote queries

**Test**:
```bash
curl -X POST http://localhost:5001/api/sql/execute \
  -H 'Content-Type: application/json' \
  -d '{"query": "SELECT windlass_udf(\"Extract brand\", \"Apple iPhone\") as brand"}'

# Returns:
# {"columns": ["brand"], "data": [{"brand": "Apple"}]}
```

---

### **Phase 2: Python Client Library** (NEXT WEEK - 2 hours)

```python
# windlass/client/sql_client.py
class WindlassClient:
    def execute(query) -> pd.DataFrame
    def read_sql(query, **kwargs) -> pd.DataFrame  # Pandas-compatible!
    def attach(connection_string, alias)  # Attach external DBs
```

**Usage**:
```python
from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

# Pandas-like interface!
df = client.read_sql("""
    SELECT windlass_udf('Extract sentiment', review_text) as sentiment
    FROM reviews
""")
```

---

### **Phase 3: PostgreSQL Protocol Server** (MONTH 1 - 1 week)

**Research needed**:
- Survey existing libraries (pg8000, asyncpg, custom)
- Decide: Build minimal or use library

**Enables**:
- ANY PostgreSQL client
- SQL IDEs (DataGrip, DBeaver)
- BI tools (Tableau, Metabase, Looker)
- Standard connection strings

**Implementation**: ~500 lines for minimal protocol support

---

## What This Unlocks

### **1. Jupyter Notebooks with LLM SQL**

```python
%%sql postgresql://windlass@localhost:5432/default

SELECT
  customer_name,
  windlass_udf('Extract industry', company_name) as industry,
  windlass_cascade_udf('tackle/ltv_prediction.yaml',
                      json_object('customer_id', customer_id)) as ltv
FROM customers;
```

---

### **2. BI Dashboards with Real-Time LLM Enrichment**

**Tableau Dashboard**:
- Chart 1: Revenue by LLM-extracted industry
- Chart 2: Customer count by LLM-classified size
- Chart 3: Fraud risk heatmap (cascade UDF scores)
- **All auto-refresh with caching!**

---

### **3. Multi-User Analytics Platform**

```python
# Each analyst gets isolated session
@app.route('/api/sql/execute')
@authenticate
def execute_sql():
    user_id = get_current_user()
    session_id = f"analyst_{user_id}"

    # User's isolated DuckDB with their temp tables
    conn = get_session_db(session_id)
    ...
```

**Each user can**:
- Create temp tables
- Use LLM UDFs
- Run cascades
- Attach their own data sources
- **Isolated from other users!**

---

### **4. External Tools Integration**

**dbt (Data Build Tool)**:
```yaml
# models/enriched_customers.sql
{{ config(materialized='table') }}

SELECT
  customer_id,
  company_name,

  -- Use Windlass UDFs in dbt models!
  windlass_udf('Extract industry', company_name) as industry,
  windlass_udf('Classify size', company_name) as size_category

FROM {{ source('raw', 'customers') }}
```

**Run dbt against Windlass server** → LLM-enriched data warehouse!

---

## My Recommendation

### **SHIP ALL THREE PHASES!**

**This Week** (1 hour):
```python
# Add HTTP endpoint to dashboard
@app.route('/api/sql/execute', methods=['POST'])
def execute_sql():
    # Get session DB, register UDFs, execute query, return JSON
```

**Next Week** (2 hours):
```python
# Build Python client library
from windlass.client import WindlassClient
client = WindlassClient('http://localhost:5001')
df = client.read_sql("SELECT windlass_udf(...) FROM data")
```

**Next Month** (1 week):
```python
# Build PostgreSQL protocol server
windlass server --protocol postgres --port 5432

# Now ANYONE can connect:
psql postgresql://windlass@localhost:5432/default
# DataGrip, Tableau, Metabase, dbt - ALL work!
```

---

## The End State

**Windlass becomes a QUERYABLE LLM DATA SERVICE**:

```
┌─────────────────────────────────────────┐
│       External SQL Clients              │
│  (Tableau, DataGrip, Python, dbt, etc.) │
└─────────────┬───────────────────────────┘
              │ PostgreSQL protocol (port 5432)
              │ OR HTTP API (port 5001)
              ▼
┌─────────────────────────────────────────┐
│         Windlass Server                 │
│  - Session DuckDB instances             │
│  - windlass_udf() registered            │
│  - windlass_cascade_udf() registered    │
│  - ATTACH support (Postgres/MySQL/S3)   │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│      LLM Orchestration Layer            │
│  - Simple UDFs → Agent.run()            │
│  - Cascade UDFs → run_cascade()         │
│  - Caching layer                        │
│  - Cost tracking                        │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│         LLM Providers                   │
│  (OpenRouter, Anthropic, OpenAI, etc.)  │
└─────────────────────────────────────────┘
```

**Users query with standard SQL tools, get LLM-powered results!**

**This is a PRODUCT!** Not just a framework - a queryable LLM service accessible via SQL. 🚀

Want me to implement the HTTP API endpoint right now? It's literally 30 minutes of work and we can test it immediately!