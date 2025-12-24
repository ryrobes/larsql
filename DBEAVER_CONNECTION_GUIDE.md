# Connecting DBeaver to Windlass

*Current: HTTP API via Python bridge | Future: Native PostgreSQL protocol*

---

## Current Status

✅ **HTTP API is LIVE** - Works from Python, curl, Jupyter
🚧 **PostgreSQL protocol** - Coming soon (native SQL IDE support)

**For now**: DBeaver connection requires a Python bridge since DBeaver doesn't natively support HTTP REST APIs for SQL.

**Recommendation**: Use Python client from Jupyter/VS Code for now, or help implement PostgreSQL protocol for native DBeaver support!

---

## Option 1: Python Client (WORKS NOW!)

### **Use Jupyter + Windlass Client in DBeaver**

DBeaver supports Jupyter notebooks! You can run Python code with the Windlass client:

1. **In DBeaver**: File → New → SQL Script → Select "Python" language
2. **Write Python code**:

```python
from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

# Query with LLM UDFs!
df = client.execute("""
    SELECT
      product_name,
      price,
      windlass_udf('Extract brand', product_name) as brand,
      windlass_udf('Classify category', product_name) as category
    FROM (VALUES
      ('Apple iPhone 15', 1199),
      ('Samsung Galaxy S24', 1299),
      ('Levis 501 Jeans', 59.99)
    ) AS t(product_name, price)
""")

# Display results
print(df.to_markdown(index=False))
```

3. **Execute** (Ctrl+Enter)
4. **Results** appear in DBeaver's output pane!

---

## Option 2: HTTP REST Data Source (Limited)

DBeaver has limited HTTP support via custom drivers.

**Steps**:

1. **Tools** → **Driver Manager** → **New**

2. **Driver Settings**:
   - Driver Name: `Windlass HTTP`
   - Class Name: `org.duckdb.DuckDBDriver`  (we'll fake it)
   - URL Template: `jdbc:duckdb::memory:`

3. **Connection Script** (custom):
   ```javascript
   // This won't work perfectly - DBeaver expects JDBC
   // Better to wait for PostgreSQL protocol
   ```

**Verdict**: Not ideal. PostgreSQL protocol is the right solution.

---

## Option 3: REST Client Plugin

DBeaver has a REST Client plugin:

1. **Help** → **Install New Software**
2. Search for "REST Client"
3. Install and restart

4. **Create REST Connection**:
   - Method: POST
   - URL: `http://localhost:5001/api/sql/execute`
   - Body:
     ```json
     {
       "query": "SELECT windlass_udf('Extract brand', 'Apple iPhone') as brand"
     }
     ```

5. **Execute** → See JSON response

**Limitations**: Not a SQL editor - just API testing. Can't write SQL interactively.

---

## Option 4: External SQL Editor → Python

Use DBeaver for writing SQL, Python for execution:

1. **Write SQL in DBeaver** (syntax highlighting!)
2. **Save as .sql file**: `query.sql`
3. **Run from Python**:

```python
from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

# Load SQL from file
with open('query.sql') as f:
    query = f.read()

# Execute
df = client.execute(query)
print(df)
```

**Workflow**:
- DBeaver: Write and refine SQL
- Python: Execute with LLM UDFs
- Jupyter: Analyze results

---

## THE REAL SOLUTION: PostgreSQL Protocol (Coming Soon!)

### **What We Need to Build** (1 week of work):

Implement PostgreSQL wire protocol server so Windlass appears as a real PostgreSQL database to ALL SQL clients.

**Implementation**:
```python
# windlass/server/postgres_server.py
class WindlassPostgresServer:
    """PostgreSQL wire protocol backed by DuckDB + Windlass UDFs."""

    def handle_query(self, query):
        conn = get_session_db(client_session_id)
        register_windlass_udf(conn)
        return conn.execute(query).fetchdf()
```

**Start server**:
```bash
windlass server --protocol postgres --port 5432
```

**Then DBeaver works natively**:

1. **Database** → **New Connection** → **PostgreSQL**
2. **Settings**:
   - Host: `localhost`
   - Port: `5432`
   - Database: `default`
   - User: `windlass`
3. **Test Connection** → ✅ Connected!

4. **Write SQL directly in DBeaver**:
```sql
SELECT
  product_name,
  windlass_udf('Extract brand', product_name) as brand
FROM products;
```

5. **Execute** (Ctrl+Enter) → Results appear instantly!

**All DBeaver features work**:
- ✅ Autocomplete
- ✅ Query history
- ✅ Visual query builder
- ✅ Data export
- ✅ Schema browser
- ✅ Result filtering/sorting

---

## Temporary DBeaver Workflow (Until PG Protocol Ships)

### **Method 1: Python Scripts in DBeaver**

Create `.py` files in DBeaver:

```python
# analysis.py - Run in DBeaver as Python script
from windlass.client import WindlassClient
import sys

client = WindlassClient('http://localhost:5001')

# Your SQL query
query = """
SELECT
  customer_name,
  windlass_udf('Extract industry', customer_name) as industry,
  windlass_cascade_udf(
    '/home/ryanr/repos/windlass/tackle/analyze_customer.yaml',
    json_object('customer_id', CAST(customer_id AS VARCHAR),
                'customer_name', customer_name,
                'email', email)
  ) as analysis
FROM customers
LIMIT 20
"""

df = client.execute(query)

# Pretty print for DBeaver console
print(df.to_markdown(index=False))

# Or save to CSV for DBeaver import
df.to_csv('/tmp/windlass_results.csv', index=False)
print(f"\n✅ Results saved to /tmp/windlass_results.csv")
print(f"Import in DBeaver: Right-click on connection → Import Data")
```

---

### **Method 2: Jupyter Notebooks (Best Current Option!)**

1. **Install Jupyter**: `pip install jupyter notebook`
2. **Start Jupyter**: `jupyter notebook`
3. **Create notebook**:

```python
# Cell 1: Setup
from windlass.client import WindlassClient
import pandas as pd

client = WindlassClient('http://localhost:5001')

# Cell 2: Your queries
df = client.execute("""
    SELECT
      product_name,
      windlass_udf('Extract brand', product_name) as brand,
      windlass_udf('Extract category', product_name) as category
    FROM products
    LIMIT 100
""")

# Cell 3: Explore
df.head()

# Cell 4: Visualize
import matplotlib.pyplot as plt
df['category'].value_counts().plot(kind='bar')
plt.title('Products by LLM-Extracted Category')
plt.show()
```

**This gives you**:
- Interactive SQL development
- Instant visualization
- LLM UDFs fully supported
- Better than DBeaver for this use case!

---

## When PostgreSQL Protocol is Ready

**You'll be able to**:

```sql
-- From DBeaver, connected to postgresql://windlass@localhost:5432

-- Attach your production database
ATTACH 'postgres://prod.db.com/warehouse' AS prod (TYPE POSTGRES);

-- Query prod with LLM enrichment!
SELECT
  c.customer_id,
  c.company_name,

  -- Extract industry from company name
  windlass_udf('Extract industry', c.company_name) as industry,

  -- Run fraud check cascade with soundings per customer!
  windlass_cascade_udf(
    'tackle/fraud_assessment_with_soundings.yaml',
    json_object(
      'customer_id', c.customer_id,
      'customer_name', c.company_name,
      'total_revenue', r.revenue
    )
  ) as fraud_check

FROM prod.customers c
JOIN prod.revenue_summary r ON c.customer_id = r.customer_id
WHERE c.created_at > CURRENT_DATE - INTERVAL '30 days';
```

**All in DBeaver's native SQL editor!**

---

## Contributing: Help Build PostgreSQL Protocol!

Want native DBeaver support? Here's what we need:

### **Implementation Checklist**:

- [ ] PostgreSQL wire protocol parser (startup, authentication, query)
- [ ] Result encoding (DataRow messages with proper types)
- [ ] Error handling (ErrorResponse messages)
- [ ] Transaction support (BEGIN, COMMIT, ROLLBACK)
- [ ] Extended query protocol (prepared statements)
- [ ] SSL/TLS support (optional for v1)

**Effort**: ~1 week for minimal implementation
**Libraries**: `struct` for binary encoding, `socket` for networking
**Reference**: PostgreSQL protocol spec: https://www.postgresql.org/docs/current/protocol.html

**Once this is done**:
- DBeaver works natively
- DataGrip works natively
- pgAdmin works natively
- Tableau works natively
- **ANY PostgreSQL client works!**

---

## Current Capabilities (HTTP API)

### ✅ **Works Today From**:
- Python (WindlassClient library)
- Jupyter notebooks
- curl / Postman / HTTP clients
- Any programming language with HTTP support

### 🚧 **Coming Soon**:
- DBeaver native connection (PostgreSQL protocol)
- DataGrip native connection
- Tableau native connection
- pgAdmin native connection

### **Workaround For Now**:
Use Jupyter notebooks or Python scripts - they're actually BETTER for iterative LLM development than SQL IDEs!

---

## Test It Yourself!

```bash
# Run test suite
python test_sql_api.py

# Expected output:
# ✅ Status: ok
# ✅ Simple UDF works!
# ✅ Multi-UDF enrichment works!
# ✅ Cascade UDF works!
# ✅ Session persistence works!
# 🎉 ALL TESTS PASSED!
```

Then try from Python:

```python
from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

# Your first LLM-powered query!
df = client.execute("""
    SELECT
      'Apple iPhone 15 Pro Max' as product,
      windlass_udf('Extract brand', 'Apple iPhone 15 Pro Max') as brand,
      windlass_udf('Extract model', 'Apple iPhone 15 Pro Max') as model,
      windlass_udf('Extract color if mentioned', 'Apple iPhone 15 Pro Max') as color
""")

print(df)
```

---

## Summary

**Today**: HTTP API + Python client = LLM SQL from anywhere!
**Soon**: PostgreSQL protocol = DBeaver + all SQL tools work natively!

**You can use windlass_udf() and windlass_cascade_udf() RIGHT NOW from Python!** 🚀

For DBeaver native support, we need to implement the PostgreSQL wire protocol (estimated: 1 week of focused work).

Ready to build that next? 😎
