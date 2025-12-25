# ATTACH Database Discovery Plan

## 🎯 **Goal**

Expose DuckDB ATTACH'd databases in DBeaver's schema browser so users can discover and query external databases.

## 🔍 **How DuckDB ATTACH Works**

### **Example Usage:**

```sql
-- ATTACH external PostgreSQL
ATTACH 'postgres://prod.db.com/warehouse' AS prod_db (TYPE POSTGRES);

-- ATTACH external MySQL
ATTACH 'mysql://analytics.db.com/metrics' AS analytics_db (TYPE MYSQL);

-- ATTACH SQLite file
ATTACH '/data/cache.sqlite' AS cache_db (TYPE SQLITE);

-- Query attached databases
SELECT * FROM prod_db.public.users;
SELECT * FROM analytics_db.main.events;
SELECT * FROM cache_db.main.cache_entries;
```

### **DuckDB's Internal Representation:**

From our test (`test_attach_discovery.py`):

```
duckdb_databases():
  - memory (main database, OID=592)
  - attached_db (ATTACH'd database, OID=2011)
  - system (internal, OID=0)
  - temp (internal, OID=1993)

pg_catalog.pg_database:
  - datname='memory', 'attached_db', 'system', 'temp'

pg_catalog.pg_class:
  - main_table1 (relnamespace=590, from 'memory')
  - attached_table (relnamespace=2009, from 'attached_db')
```

**Key insight:** Each database has a **unique namespace OID**!

---

## 🗺️ **Mapping Strategy**

### **DuckDB → PostgreSQL Mapping:**

| DuckDB Concept | PostgreSQL Equivalent | DBeaver Shows |
|----------------|------------------------|---------------|
| Database "memory" | Schema "main" | 📁 main (local tables) |
| Database "attached_db" | Schema "attached_db" | 📁 attached_db (external) |
| Database "prod_postgres" | Schema "prod_postgres" | 📁 prod_postgres (external) |

**Result in DBeaver:**

```
📁 default
  └── 📁 Schemas
      ├── 📁 main                    ← Local DuckDB tables
      │   ├── test_demo
      │   └── my_test
      ├── 📁 prod_postgres          ← ATTACH'd PostgreSQL
      │   ├── users
      │   ├── orders
      │   └── products
      ├── 📁 analytics_mysql        ← ATTACH'd MySQL
      │   ├── events
      │   └── metrics
      └── 📁 cache_sqlite           ← ATTACH'd SQLite
          └── cache_entries
```

**Users can now browse external databases in DBeaver!** 🎉

---

## 🛠️ **Implementation**

### **Option 1: Use DuckDB's Built-in pg_catalog (Recommended)**

**Good news:** `pg_catalog.pg_database` **already includes attached databases**!

**What we need to do:**

1. **pg_namespace:** Map database names to schema names
2. **pg_class bypass:** Show tables from ALL namespaces (not just 590)
3. **pg_attribute bypass:** Show columns from ALL tables

### **Option 2: Create Custom Views (If Built-in Doesn't Work)**

Create views that explicitly map databases → schemas.

---

## 📝 **Code Changes Needed**

### **1. Update pg_namespace to Include All Databases**

Currently, `pg_namespace` only shows schemas within the current database. We need to show ALL attached databases as schemas.

**Current behavior:**
```sql
SELECT * FROM pg_catalog.pg_namespace;
-- Result: main, pg_catalog, information_schema
```

**Target behavior:**
```sql
SELECT * FROM pg_catalog.pg_namespace;
-- Result: main, pg_catalog, information_schema, attached_db, prod_postgres, etc.
```

**Implementation:**

```python
# In _handle_catalog_query or as a custom view
SELECT database_name as nspname, database_oid as oid
FROM duckdb_databases()
WHERE database_name NOT IN ('system', 'temp')  -- Hide internal databases
UNION ALL
SELECT 'main' as nspname, 0 as oid
UNION ALL
SELECT 'pg_catalog' as nspname, 0 as oid
```

### **2. Update pg_class Bypass to Show ALL Tables**

Currently our bypass might filter to only one namespace (590 = main).

**Change:**

```python
# DON'T filter by specific namespace
safe_query = f"""
    SELECT
        c.oid,
        c.relname,
        c.relnamespace,
        c.relkind,
        ...
    FROM pg_catalog.pg_class c
    WHERE {extracted_where_clause}  # Use DBeaver's original WHERE
    LIMIT 1000
"""
```

**This already uses extracted WHERE clause - should work!**

### **3. Update pg_attribute Bypass to Show Columns from All Tables**

Same as pg_class - use extracted WHERE clause.

**This already does this - should work!**

---

## 🧪 **Testing Plan**

### **Test 1: Create ATTACH'd database**

In DBeaver SQL Console:

```sql
-- ATTACH an in-memory database
ATTACH ':memory:' AS external_db;

-- Create tables in it
CREATE TABLE external_db.main.external_table (
    id INTEGER,
    name VARCHAR,
    value DOUBLE
);

INSERT INTO external_db.main.external_table VALUES
    (1, 'External Row 1', 99.9),
    (2, 'External Row 2', 88.8);
```

### **Test 2: Query attached database**

```sql
-- Query directly
SELECT * FROM external_db.main.external_table;
```

Should return 2 rows!

### **Test 3: Check if it appears in catalogs**

```sql
-- Check pg_database
SELECT datname FROM pg_catalog.pg_database ORDER BY datname;
-- Should include: 'external_db', 'memory', 'system', 'temp', etc.

-- Check duckdb_databases
SELECT database_name FROM duckdb_databases() ORDER BY database_name;
-- Should include: 'external_db'

-- Check pg_class
SELECT relname, relnamespace FROM pg_catalog.pg_class WHERE relname = 'external_table';
-- Should return: external_table with some relnamespace OID
```

### **Test 4: Refresh DBeaver and check tree**

1. Right-click connection → **Invalidate/Reconnect**
2. Expand: Schemas → Should see `external_db` in the list!
3. Expand `external_db` → Tables → `external_table`

---

## 🎯 **Expected Result**

**DBeaver shows:**

```
📁 default
  └── 📁 Schemas
      ├── 📁 main
      │   ├── test_demo
      │   └── my_test
      ├── 📁 external_db          ← NEW! ATTACH'd database!
      │   └── external_table      ← Table from external database!
      ├── 📁 information_schema
      └── 📁 pg_catalog
```

**When you click external_table:**
- Shows columns (id, name, value)
- Can query it: `SELECT * FROM external_db.external_table`

---

## 💡 **The Brilliant Part**

**This means:**

```sql
-- ATTACH your production PostgreSQL
ATTACH 'postgres://prod.company.com/warehouse' AS prod (TYPE POSTGRES, READ_ONLY);

-- ATTACH your analytics MySQL
ATTACH 'mysql://analytics.company.com/metrics' AS analytics (TYPE MYSQL, READ_ONLY);
```

**DBeaver will show:**
```
📁 default (RVBBIT)
  └── 📁 Schemas
      ├── 📁 main (local RVBBIT tables)
      ├── 📁 prod (production PostgreSQL!)      │   ├── users
      │   ├── orders
      │   └── products
      └── 📁 analytics (analytics MySQL!)          ├── events
          └── metrics
```

**You can browse and query EVERYTHING from DBeaver!**

And use LLM UDFs on external data:

```sql
SELECT
    user_id,
    company_name,
    rvbbit_udf('Extract industry', company_name) as industry
FROM prod.public.customers
LIMIT 100;
```

**LLM-powered queries on your production PostgreSQL, browsable in DBeaver!** 🤯

---

## 🚀 **Implementation Steps**

### **Step 1: Test if it already works** (5 mins)

Run the test above - ATTACH a database and see if DBeaver shows it!

### **Step 2: If not working, debug** (30 mins)

Check:
- Does `pg_namespace` include attached database names?
- Does our pg_class bypass filter them out?
- Does DBeaver filter by specific schema?

### **Step 3: Fix if needed** (1 hour)

Most likely:
- Our bypasses are working fine
- Just need to ensure pg_namespace shows all databases
- Might need to map database names to schemas explicitly

---

## 🎊 **Potential Impact**

**This feature would enable:**

✅ Browse external PostgreSQL/MySQL/SQLite in DBeaver
✅ Join local and external data visually
✅ Use LLM UDFs on external data
✅ Build dashboards combining multiple sources
✅ **Zero-copy federation** (DuckDB's ATTACH is super efficient!)

**Use cases:**

- "Browse production PostgreSQL read-only in DBeaver"
- "Join local enrichment table with production data"
- "Run LLM classification on MySQL analytics data"
- "Query S3 Parquet files as if they were tables"

---

**Want to test if this already works?** Run the test queries above and see if DBeaver shows the attached database! 🎯
