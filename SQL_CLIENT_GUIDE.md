# Connecting SQL Clients to Windlass

*Use LLM-powered UDFs from DBeaver, Python, Jupyter, and any HTTP-capable client!*

---

## Quick Start

### **1. Start Windlass Dashboard** (if not already running)

```bash
cd dashboard/backend
python app.py

# Server starts on http://localhost:5001
# SQL API available at: http://localhost:5001/api/sql/execute
```

### **2. Choose Your Client**

- **Python** → Use WindlassClient library
- **DBeaver / DataGrip** → Use HTTP/REST data source
- **Jupyter Notebook** → Use Python client or %%sql magic
- **curl / Postman** → Direct HTTP POST requests

---

## Python Client (EASIEST)

### **Installation**

```python
# Already available if you have Windlass installed!
from windlass.client import WindlassClient
```

### **Basic Usage**

```python
from windlass.client import WindlassClient

# Connect to Windlass server
client = WindlassClient('http://localhost:5001')

# Execute SQL with LLM UDFs!
df = client.execute("""
    SELECT
      product_name,
      price,
      windlass_udf('Extract brand', product_name) as brand,
      windlass_udf('Classify category', product_name) as category
    FROM products
    LIMIT 100
""")

print(df)
#    product_name                      price  brand      category
# 0  Apple iPhone 15 Pro Max           1199   Apple      Electronics
# 1  Samsung Galaxy S24 Ultra          1299   Samsung    Electronics
# 2  Levis 501 Jeans                   59     Levis      Clothing
```

### **With Cascade UDF**

```python
# Run complete cascades per row!
df = client.execute("""
    SELECT
      customer_id,
      customer_name,

      windlass_cascade_udf(
        '/home/ryanr/repos/windlass/tackle/analyze_customer.yaml',
        json_object(
          'customer_id', CAST(customer_id AS VARCHAR),
          'customer_name', customer_name,
          'email', email
        )
      ) as analysis_json

    FROM customers
    LIMIT 10
""")

# Extract fields from cascade results
import json
df['risk_score'] = df['analysis_json'].apply(
    lambda x: json.loads(x)['outputs']['analyze']['risk_score']
)
```

### **Attach External Databases**

```python
# Attach your production Postgres
client.attach('postgres://user:pass@db.prod.com/mydb', 'prod')

# Now query with LLM enrichment!
df = client.execute("""
    SELECT
      customer_id,
      company_name,
      windlass_udf('Extract industry', company_name) as industry
    FROM prod.customers
    WHERE created_at > CURRENT_DATE - INTERVAL '30 days'
""")
```

### **Pandas-Compatible Interface**

```python
# Works like pandas.read_sql!
df = client.read_sql("""
    SELECT
      windlass_udf('Sentiment: positive/negative/neutral', review_text) as sentiment,
      COUNT(*) as count
    FROM reviews
    GROUP BY sentiment
""")
```

---

## DBeaver (SQL IDE)

### **Setup** (HTTP/REST Data Source)

DBeaver doesn't have native HTTP support, but we can use it via **Python bridge** or wait for **PostgreSQL protocol** (coming soon!).

**Current workaround**:

1. **Install Python extension in DBeaver**:
   - Tools → Driver Manager → New
   - Driver Name: "Windlass"
   - Class Name: `windlass.client.WindlassClient`
   - (This is experimental - PostgreSQL protocol is better)

2. **OR: Use Python script mode**:
   - File → New → SQL Script → Python
   - Use Python client code directly in DBeaver

3. **BEST: Wait for PostgreSQL protocol** (coming soon!)
   - Will work natively as PostgreSQL connection
   - Connection string: `postgresql://windlass@localhost:5432/default`

---

## Jupyter Notebook

### **Option 1: Python Client** (Recommended)

```python
# In Jupyter cell
from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

# Query and visualize!
df = client.execute("""
    SELECT
      DATE_TRUNC('month', order_date) as month,
      windlass_udf('Extract product category', product_name) as category,
      SUM(amount) as revenue
    FROM orders
    GROUP BY month, category
    ORDER BY month, revenue DESC
""")

# Visualize with plotly
import plotly.express as px
fig = px.bar(df, x='month', y='revenue', color='category')
fig.show()
```

### **Option 2: IPython SQL Magic**

```python
# Install ipython-sql
!pip install ipython-sql

# Load extension
%load_ext sql

# This requires PostgreSQL protocol (future)
# %sql postgresql://windlass@localhost:5432/default

# For now, use Python client:
from windlass.client import execute_sql

df = execute_sql("""
    SELECT windlass_udf('Extract sentiment', review_text) as sentiment
    FROM reviews
    LIMIT 100
""")
```

---

## curl / Postman (Direct HTTP)

### **Simple Query**

```bash
curl -X POST http://localhost:5001/api/sql/execute \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "SELECT windlass_udf(\"Extract brand\", \"Apple iPhone\") as brand"
  }'

# Response:
# {
#   "success": true,
#   "columns": ["brand"],
#   "data": [{"brand": "Apple"}],
#   "row_count": 1,
#   "execution_time_ms": 2145.3
# }
```

### **With Session ID** (for temp tables)

```bash
# Query 1: Create temp table
curl -X POST http://localhost:5001/api/sql/execute \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "CREATE TEMP TABLE my_products AS SELECT * FROM (VALUES (\"Apple iPhone\", 1199), (\"Samsung Galaxy\", 1299)) AS t(name, price)",
    "session_id": "my_analysis_session"
  }'

# Query 2: Use temp table (same session!)
curl -X POST http://localhost:5001/api/sql/execute \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "SELECT name, price, windlass_udf(\"Extract brand\", name) as brand FROM my_products",
    "session_id": "my_analysis_session"
  }'
```

### **CSV Output**

```bash
curl -X POST http://localhost:5001/api/sql/execute \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "SELECT windlass_udf(\"Brand\", name) as brand FROM products",
    "format": "csv"
  }' > results.csv
```

---

## API Reference

### **POST /api/sql/execute**

Execute SQL query with Windlass UDFs.

**Request Body**:
```json
{
  "query": "SELECT ...",
  "session_id": "optional_session_id",  // Default: auto-generated
  "format": "records"  // "records", "json", or "csv"
}
```

**Response** (format="records"):
```json
{
  "success": true,
  "columns": ["col1", "col2"],
  "data": [
    {"col1": "val1", "col2": "val2"},
    {"col1": "val3", "col2": "val4"}
  ],
  "row_count": 2,
  "session_id": "http_api_abc123",
  "execution_time_ms": 1234.5
}
```

**Error Response**:
```json
{
  "success": false,
  "error": "Error message",
  "error_type": "BinderException",
  "traceback": "...",
  "session_id": "http_api_abc123"
}
```

---

### **GET /api/sql/sessions**

List all active DuckDB sessions.

**Response**:
```json
{
  "sessions": [
    {
      "session_id": "my_session",
      "table_count": 3,
      "tables": ["_customers", "_orders", "_products"]
    }
  ],
  "count": 1
}
```

---

### **GET /api/sql/tables/{session_id}**

List tables in a specific session.

**Response**:
```json
{
  "session_id": "my_session",
  "tables": [
    {"name": "_customers", "row_count": 1000},
    {"name": "_orders", "row_count": 5000}
  ]
}
```

---

### **GET /api/sql/schema/{session_id}/{table_name}**

Get schema for a table.

**Response**:
```json
{
  "session_id": "my_session",
  "table": "_customers",
  "columns": [
    {"column_name": "customer_id", "column_type": "BIGINT", "null": "YES"},
    {"column_name": "name", "column_type": "VARCHAR", "null": "YES"}
  ]
}
```

---

### **GET /api/sql/health**

Health check endpoint.

**Response**:
```json
{
  "status": "ok",
  "windlass_udf_registered": true,
  "cascade_udf_registered": true,
  "version": "1.0.0"
}
```

---

## Example Workflows

### **1. Product Enrichment Pipeline**

```python
from windlass.client import WindlassClient
import pandas as pd

client = WindlassClient('http://localhost:5001')

# Load raw product data
client.execute("""
    CREATE TEMP TABLE raw_products AS
    SELECT * FROM read_csv('products.csv')
""")

# Enrich with LLM UDFs
enriched = client.execute("""
    SELECT
      product_id,
      product_name,
      price,

      -- Extract structured attributes
      windlass_udf('Extract brand', product_name) as brand,
      windlass_udf('Extract color', product_name) as color,
      windlass_udf('Category: Electronics/Clothing/Home/Other', product_name) as category,
      windlass_udf('Price tier: budget/mid-range/premium/luxury', product_name || ' - $' || price) as price_tier

    FROM raw_products
""")

# Save enriched data
enriched.to_csv('products_enriched.csv', index=False)
```

---

### **2. Customer Risk Assessment**

```python
# Attach production database
client.attach('postgres://analyst:pass@db.prod.com/warehouse', 'prod')

# Run fraud checks with cascades
risk_scores = client.execute("""
    SELECT
      customer_id,
      company_name,
      transaction_amount,

      -- Run cascade UDF with soundings per customer!
      windlass_cascade_udf(
        '/home/ryanr/repos/windlass/tackle/fraud_assessment_with_soundings.yaml',
        json_object(
          'customer_id', customer_id,
          'customer_name', company_name,
          'transaction_amount', transaction_amount
        )
      ) as fraud_analysis_json

    FROM prod.high_value_transactions
    WHERE created_at > CURRENT_DATE - INTERVAL '7 days'
    LIMIT 100
""")

# Parse JSON results
import json
risk_scores['risk_score'] = risk_scores['fraud_analysis_json'].apply(
    lambda x: json.loads(x)['outputs']['assess_risk']['risk_score']
)

# High-risk transactions
high_risk = risk_scores[risk_scores['risk_score'] > 0.7]
print(f"Found {len(high_risk)} high-risk transactions!")
```

---

### **3. Incremental Data Enrichment** (with caching!)

```python
# Day 1: Enrich all customers (1000 LLM calls)
df_day1 = client.execute("""
    SELECT
      customer_id,
      windlass_udf('Extract industry', company_name) as industry
    FROM customers
""", session_id="industry_extraction")

# Day 2: Enrich new customers (only ~50 LLM calls - 950 cache hits!)
df_day2 = client.execute("""
    SELECT
      customer_id,
      windlass_udf('Extract industry', company_name) as industry
    FROM customers
""", session_id="industry_extraction")  # Same session = cache persists!

# 95% cost savings!
```

---

## PostgreSQL Protocol (Coming Soon!)

**Future State** (after implementing PG protocol):

### **DBeaver Connection**:

1. **Database** → **New Connection** → **PostgreSQL**
2. **Connection Settings**:
   - Host: `localhost`
   - Port: `5432`
   - Database: `default`
   - Username: `windlass`
   - Password: (optional)
3. **Test Connection** → Should show "Connected"

4. **Now just write SQL**:
```sql
SELECT
  product_name,
  windlass_udf('Extract brand', product_name) as brand
FROM products;
```

**It works like any PostgreSQL database!**

---

### **Tableau Connection**:

1. **Connect to Data** → **PostgreSQL**
2. Server: `localhost`, Port: `5432`
3. Database: `windlass`
4. **Create Calculated Field**:
   ```
   RAWSQL_STR("windlass_udf('Extract industry', %1)", [Company Name])
   ```
5. **Drag to visualization** → LLM-enriched dashboard!

---

### **Metabase / Superset**:

Add Windlass as PostgreSQL data source:
- Type: PostgreSQL
- Host: localhost
- Port: 5432
- Database: default

Create SQL Question:
```sql
SELECT
  windlass_udf('Extract category', product_name) as category,
  COUNT(*) as count,
  AVG(price) as avg_price
FROM products
GROUP BY category
ORDER BY count DESC;
```

**Result**: Real-time LLM analytics dashboard!

---

## HTTP API Usage (Current Implementation)

### **Python with requests**

```python
import requests
import pandas as pd

response = requests.post('http://localhost:5001/api/sql/execute', json={
    "query": """
        SELECT
          customer_name,
          windlass_udf('Extract industry', customer_name) as industry
        FROM customers
        LIMIT 10
    """
})

data = response.json()
df = pd.DataFrame(data['data'])
```

---

### **Python with SQLAlchemy (future)**

Once PostgreSQL protocol is implemented:

```python
from sqlalchemy import create_engine
import pandas as pd

engine = create_engine('postgresql://windlass@localhost:5432/default')

df = pd.read_sql("""
    SELECT
      product_name,
      windlass_udf('Extract brand', product_name) as brand
    FROM products
""", engine)
```

---

## Advanced Patterns

### **1. Multi-Tier Analysis**

```python
# Triage with simple UDF, escalate to cascade UDF
df = client.execute("""
    WITH triage AS (
      SELECT
        transaction_id,
        amount,
        windlass_udf('Risk level: low/medium/high', description) as risk_tier
      FROM transactions
    )

    SELECT
      transaction_id,
      risk_tier,

      CASE risk_tier
        WHEN 'low' THEN
          json_object('action', 'approve', 'method', 'auto')

        WHEN 'medium' THEN
          windlass_cascade_udf(
            '/home/ryanr/repos/windlass/tackle/analyze_customer.yaml',
            json_object('customer_id', CAST(transaction_id AS VARCHAR))
          )

        WHEN 'high' THEN
          windlass_cascade_udf(
            '/home/ryanr/repos/windlass/tackle/fraud_assessment_with_soundings.yaml',
            json_object('transaction_id', transaction_id)
          )

      END as decision

    FROM triage
""")
```

---

### **2. Cache Statistics**

```python
# Check cache effectiveness
from windlass.sql_tools.udf import get_udf_cache_stats

stats = get_udf_cache_stats()
print(f"Simple UDF cache: {stats['simple_udf']['cached_entries']} entries")
print(f"Cascade UDF cache: {stats['cascade_udf']['cached_entries']} entries")
print(f"Total cache size: {stats['total_entries']} entries")
```

---

### **3. Session Management**

```python
# List all sessions
sessions = client.list_sessions()
print(sessions)

# List tables in current session
tables = client.list_tables()
print(tables)

# Get table schema
schema = client.get_schema('_customers')
print(schema)
```

---

## Performance Tips

### **1. Use Session IDs for Caching**

```python
# Bad: New session each time (no cache reuse)
for i in range(10):
    client.execute("SELECT windlass_udf(...) FROM data")

# Good: Same session (cache persists!)
client = WindlassClient('http://localhost:5001', session_id='my_analysis')
for i in range(10):
    client.execute("SELECT windlass_udf(...) FROM data")  # Caches across calls!
```

---

### **2. Batch Queries**

```python
# Bad: 100 separate HTTP requests
for product in products:
    client.execute(f"SELECT windlass_udf('Brand', '{product}')")

# Good: One query, DuckDB handles parallelism
client.execute("""
    SELECT
      product_name,
      windlass_udf('Extract brand', product_name) as brand
    FROM (VALUES
      ('Apple iPhone'),
      ('Samsung Galaxy'),
      -- ... 100 products
    ) AS t(product_name)
""")
```

---

### **3. Use Temp Tables**

```python
# Load once, query many times (same session!)
client.execute("""
    CREATE TEMP TABLE products AS
    SELECT * FROM read_csv('products.csv')
""", session_id="analysis_001")

# Query 1: Brands
brands = client.execute("""
    SELECT windlass_udf('Extract brand', name) as brand, COUNT(*)
    FROM products
    GROUP BY brand
""", session_id="analysis_001")

# Query 2: Categories
categories = client.execute("""
    SELECT windlass_udf('Category', name) as category, AVG(price)
    FROM products
    GROUP BY category
""", session_id="analysis_001")

# Temp table persists across queries in same session!
```

---

## Security Considerations

### **Authentication** (TODO)

```python
# Future: API key authentication
client = WindlassClient(
    'http://localhost:5001',
    api_key='your_api_key_here'
)
```

### **Rate Limiting** (TODO)

```python
# Future: Rate limits per API key
# - 1000 queries/hour
# - 10,000 LLM calls/day
# - Cost limits per user
```

### **Query Validation** (TODO)

```python
# Future: Block dangerous operations
# - No DROP, DELETE, TRUNCATE (except for temp tables)
# - Read-only for attached databases
# - Sandboxed sessions per user
```

---

## Troubleshooting

### **"Connection refused"**

```bash
# Check if server is running
curl http://localhost:5001/api/sql/health

# If not running:
cd dashboard/backend
python app.py
```

---

### **"Function windlass_udf does not exist"**

This shouldn't happen (UDFs auto-register), but if it does:

```python
# Manually register UDFs
from windlass.sql_tools.session_db import get_session_db
from windlass.sql_tools.udf import register_windlass_udf

conn = get_session_db("my_session")
register_windlass_udf(conn)
```

---

### **Slow queries**

- **First run**: UDFs make LLM calls (1-3s each)
- **Second run**: Cache hits (<1ms each)
- **Solution**: Pre-warm cache by running query once

---

### **Path issues with cascade UDF**

Use absolute paths:
```python
# Bad: Relative path (depends on server cwd)
windlass_cascade_udf('tackle/fraud.yaml', inputs)

# Good: Absolute path
windlass_cascade_udf('/home/user/windlass/tackle/fraud.yaml', inputs)

# Better: Set WINDLASS_ROOT env var, use relative
# (Server resolves relative to WINDLASS_ROOT)
```

---

## Examples

### **1. Sentiment Analysis Dashboard**

```python
from windlass.client import WindlassClient
import plotly.express as px

client = WindlassClient('http://localhost:5001')

# Analyze reviews with LLM
df = client.execute("""
    SELECT
      DATE_TRUNC('day', created_at) as date,
      windlass_udf('Sentiment: positive/negative/neutral', review_text) as sentiment,
      COUNT(*) as count
    FROM reviews
    WHERE created_at > CURRENT_DATE - INTERVAL '30 days'
    GROUP BY date, sentiment
    ORDER BY date
""")

# Visualize
fig = px.line(df, x='date', y='count', color='sentiment',
              title='Review Sentiment Over Time')
fig.show()
```

---

### **2. Entity Extraction from Support Tickets**

```python
# Extract structured data from unstructured text
tickets = client.execute("""
    SELECT
      ticket_id,
      ticket_text,

      windlass_udf('Extract customer name', ticket_text) as customer_name,
      windlass_udf('Extract product mentioned', ticket_text) as product,
      windlass_udf('Extract issue type: billing/technical/shipping', ticket_text) as issue_type,
      windlass_udf('Urgency: low/medium/high', ticket_text) as urgency

    FROM support_tickets
    WHERE status = 'new'
    LIMIT 100
""")

# Route to appropriate team
high_urgency = tickets[tickets['urgency'] == 'high']
print(f"High urgency tickets: {len(high_urgency)}")
```

---

### **3. A/B Test Cascade Variants**

```python
# Test two different fraud models
results = client.execute("""
    SELECT
      transaction_id,
      amount,

      -- Random A/B assignment
      CASE WHEN random() < 0.5
        THEN 'model_v1'
        ELSE 'model_v2'
      END as variant,

      -- Run corresponding cascade
      windlass_cascade_udf(
        CASE WHEN random() < 0.5
          THEN '/home/ryanr/repos/windlass/tackle/analyze_customer.yaml'
          ELSE '/home/ryanr/repos/windlass/tackle/fraud_assessment_with_soundings.yaml'
        END,
        json_object('transaction_id', CAST(transaction_id AS VARCHAR))
      ) as fraud_check

    FROM transactions
    LIMIT 100
""")

# Analyze which model performed better
# (would need ground truth labels for real analysis)
```

---

## Next Steps

### **Implemented ✅**:
- HTTP API with POST /api/sql/execute
- Python client library (WindlassClient)
- Simple UDF support (windlass_udf)
- Cascade UDF support (windlass_cascade_udf)
- Session management
- Health checks

### **Coming Soon** 🚧:
- PostgreSQL wire protocol (native DB client support)
- Authentication & API keys
- Rate limiting
- Query logging & audit trail
- Persistent caching
- ATTACH database helpers

### **Try It Now!**

```python
from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

df = client.execute("""
    SELECT
      'Apple iPhone 15 Pro' as product,
      windlass_udf('Extract brand', 'Apple iPhone 15 Pro') as brand,
      windlass_udf('Extract model number', 'Apple iPhone 15 Pro') as model
""")

print(df)
```

---

**The future is here: SQL + LLMs + Zero-copy data enrichment!** 🚀
