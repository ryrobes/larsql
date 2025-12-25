# Test ATTACH Discovery in DBeaver - Quick Guide

## 🧪 **Test if ATTACH'd Databases Appear as Schemas**

### **Step 1: Connect to RVBBIT in DBeaver**

(You should already be connected with Extended Query Protocol working!)

---

### **Step 2: ATTACH an in-memory database**

In DBeaver SQL Console:

```sql
-- ATTACH a new in-memory database
ATTACH ':memory:' AS external_db;

-- Create a table in it
CREATE TABLE external_db.main.external_users (
    id INTEGER,
    name VARCHAR,
    email VARCHAR
);

-- Insert test data
INSERT INTO external_db.main.external_users VALUES
    (1, 'Alice External', 'alice@external.com'),
    (2, 'Bob External', 'bob@external.com'),
    (3, 'Charlie External', 'charlie@external.com');
```

---

### **Step 3: Verify it works via SQL**

```sql
-- Query the attached database table
SELECT * FROM external_db.main.external_users;
-- Should return 3 rows!

-- Check if database appears in catalog
SELECT datname FROM pg_catalog.pg_database ORDER BY datname;
-- Should include: 'external_db', 'memory', etc.

-- Check if table appears in pg_class
SELECT relname, relnamespace
FROM pg_catalog.pg_class
WHERE relname = 'external_users';
-- Should return: external_users with some namespace OID

-- List all databases
SELECT database_name, type, readonly
FROM duckdb_databases()
WHERE NOT internal
ORDER BY database_name;
```

---

### **Step 4: Refresh DBeaver and Check Tree**

1. **Right-click connection** → **Invalidate/Reconnect**
2. **Expand:** Databases → default → **Schemas**
3. **Look for:** `external_db` in the schema list!

**Expected:**
```
📁 Schemas
  ├── 📁 main
  │   ├── test_demo
  │   └── my_test
  ├── 📁 external_db          ← NEW! Should appear!
  │   └── 📁 Tables
  │       └── external_users  ← Should appear!
  ├── 📁 information_schema
  └── 📁 pg_catalog
```

---

### **Step 5: If It Works - Test with Real Database!**

Try ATTACH'ing a real external database:

```sql
-- ATTACH external PostgreSQL (read-only for safety!)
ATTACH 'postgres://your-host/your-db' AS prod (TYPE POSTGRES, READ_ONLY);

-- List schemas in the attached database
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_catalog = 'prod'
ORDER BY table_schema, table_name;

-- Query external tables
SELECT * FROM prod.public.users LIMIT 10;
```

**Then refresh DBeaver** and see if `prod` schema appears with its tables!

---

## 🎯 **What We're Testing**

| Test | What It Proves |
|------|----------------|
| SQL queries work | ✅ ATTACH works at DuckDB level |
| pg_catalog shows database | ✅ DuckDB catalog includes ATTACH'd dbs |
| DBeaver shows schema | ✅ PostgreSQL wire protocol exposes it |
| DBeaver shows tables | ✅ Full schema introspection works |
| Can query from DBeaver | ✅ End-to-end working! |

---

## 📊 **Expected Results**

### **If It Works Out of the Box:**

✅ ATTACH'd databases appear as schemas in DBeaver
✅ Tables from external databases browsable
✅ Can query them normally
✅ **Zero additional code needed!** (DuckDB's pg_catalog handles it!)

### **If It Doesn't Work:**

We need to:
1. Update our pg_class bypass to not filter by namespace
2. Ensure pg_namespace includes all database names
3. Map DuckDB's `database_name` to PostgreSQL's `schema_name`

---

## 🔮 **Future Possibilities**

If this works, you could:

```sql
-- ATTACH production PostgreSQL
ATTACH 'postgres://prod.company.com/warehouse' AS prod (TYPE POSTGRES, READ_ONLY);

-- ATTACH analytics MySQL
ATTACH 'mysql://analytics.company.com/metrics' AS analytics (TYPE MYSQL, READ_ONLY);

-- ATTACH S3 Parquet
ATTACH 'parquet:///s3/data-lake/*.parquet' AS datalake (TYPE PARQUET);

-- Now enrich production data with LLM in DBeaver!
SELECT
    u.user_id,
    u.company_name,
    rvbbit_udf('Extract industry', u.company_name) as industry,
    a.event_count
FROM prod.public.users u
LEFT JOIN analytics.main.user_events a ON u.user_id = a.user_id
WHERE u.created_at > CURRENT_DATE - INTERVAL '30 days'
LIMIT 100;
```

**All browsable and query-able in DBeaver!** 🤯

---

## 🚀 **Try It Now**

Run the test queries above and tell me:

1. **Do the SQL queries work?** (SELECT from external_db)
2. **Does external_db appear in pg_catalog.pg_database?**
3. **Does external_db appear in DBeaver's schema tree?**
4. **Can you expand it to see tables?**

This will tell us if ATTACH discovery already works or needs implementation! 🎯
