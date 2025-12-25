# Quick Start: Schema Introspection in RVBBIT

## 🚀 Get Started in 60 Seconds

### 1. Start the Server

```bash
rvbbit server --port 5432
```

You should see:
```
🌊 WINDLASS POSTGRESQL SERVER
📡 Listening on: 0.0.0.0:5432
✨ Available SQL functions:
   • rvbbit_udf(instructions, input_value)
   • rvbbit_cascade_udf(cascade_path, json_inputs)
```

### 2. Connect with DBeaver

**No configuration needed!**

1. Open DBeaver
2. **Database → New Database Connection**
3. Select **PostgreSQL**
4. Enter connection details:
   - Host: `localhost`
   - Port: `5432`
   - Database: `default`
   - Username: `rvbbit`
5. **Test Connection** → ✅ Success!
6. **Finish**

### 3. Browse Your Data

**Database Navigator** (left panel):
```
📁 default
  └── 📁 Schemas
      └── 📁 main
          ├── 📁 Tables
          │   ├── 📋 your_table_1
          │   ├── 📋 your_table_2
          │   └── 📋 your_table_3
          └── 📁 Views
```

**Click any table** → See columns, types, constraints!

### 4. Use Auto-Complete

Open **SQL Editor** (SQL button or Ctrl+Enter):

```sql
SELECT *
FROM u  -- Press Ctrl+Space → See "users", "user_sessions", etc.
```

Type `.` after table name:
```sql
SELECT users.  -- Press Ctrl+Space → See all columns!
```

---

## 💡 Common Queries

### List All Tables
```sql
SELECT tablename
FROM pg_catalog.pg_tables
WHERE schemaname = 'main'
ORDER BY tablename;
```

### Get Table Schema
```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'users'
ORDER BY ordinal_position;
```

### Count Rows in All Tables
```sql
SELECT
    table_name,
    (SELECT COUNT(*) FROM main[table_name]) as row_count
FROM information_schema.tables
WHERE table_schema = 'main'
ORDER BY row_count DESC;
```

---

## 🧪 Test It Works

### Option 1: Quick psql Test

```bash
psql postgresql://localhost:5432/default

# List tables
\dt

# Describe a table
\d users

# List schemas
\dn

# Quit
\q
```

### Option 2: Automated Test

```bash
python test_schema_introspection.py
```

Expected output:
```
✅ Found 5 user tables
✅ Found 23 columns
✅ Current database: default
✅ Current schema: main
🎉 All tests passed!
```

---

## 🎯 What You Can Do Now

### ✅ In DBeaver/DataGrip

1. **Browse tables** in tree view
2. **View table structure** (right-click → View Table)
3. **Auto-complete** SQL queries
4. **Generate SQL** (INSERT, UPDATE, DELETE)
5. **Export data** to CSV, JSON, Excel
6. **Build queries** with drag-and-drop
7. **Create ER diagrams**

### ✅ In Python

```python
import psycopg2

conn = psycopg2.connect("postgresql://localhost:5432/default")
cur = conn.cursor()

# Discover all tables
cur.execute("""
    SELECT tablename
    FROM pg_catalog.pg_tables
    WHERE schemaname = 'main'
""")

for (table,) in cur.fetchall():
    print(f"Table: {table}")
```

### ✅ With LLM UDFs

```sql
-- Discover products table
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'products';

-- Now use LLM to enrich it!
SELECT
    product_name,
    rvbbit_udf('Extract brand', product_name) as brand,
    rvbbit_udf('Categorize', product_name) as category
FROM products;
```

---

## 📚 Learn More

- **Full Documentation:** [SCHEMA_INTROSPECTION.md](SCHEMA_INTROSPECTION.md)
- **Test Suite:** [test_schema_introspection.py](test_schema_introspection.py)
- **Main README:** [README.md](README.md)

---

## 🐛 Troubleshooting

### Tables Don't Appear in DBeaver

**Try:**
1. Right-click connection → **Refresh**
2. Restart DBeaver
3. Check server logs for errors

**Test manually:**
```sql
SELECT * FROM pg_catalog.pg_tables;
```

If this returns tables but DBeaver doesn't show them, it's a DBeaver caching issue.

### "pg_catalog schema does not exist"

**Cause:** Server failed to create catalog views

**Fix:**
1. Check server logs during connection
2. Ensure DuckDB session has permissions
3. Restart server

### Auto-Complete Not Working

**Cause:** DBeaver hasn't loaded schema metadata

**Fix:**
1. Right-click connection → **Invalidate/Reconnect**
2. Wait for metadata load to complete (bottom-right progress bar)
3. Try auto-complete again

---

## 🎉 You're Done!

Schema introspection is now working! Your SQL editors can:

- ✅ Browse tables and columns
- ✅ Auto-complete queries
- ✅ Generate SQL statements
- ✅ Export data
- ✅ All while using LLM UDFs!

**No more `preferQueryMode=simple` hacks!** (Well, you still need that for Extended Query Protocol, but schema introspection works!)

---

## Next Steps

1. **Create some tables** and watch them appear in DBeaver instantly
2. **Try LLM-powered queries** with `rvbbit_udf()`
3. **Build dashboards** in Tableau/Metabase (they work too!)
4. **Explore the full catalog** with PostgreSQL queries

**Happy querying! 🚀**
