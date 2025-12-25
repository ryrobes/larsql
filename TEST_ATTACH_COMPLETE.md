# Complete ATTACH Discovery Test Guide

## 🧪 **Test the Complete ATTACH Feature**

### **Step 1: Restart Server**

```bash
# Stop server (Ctrl+C)
rvbbit sql server --port 15432
```

**Watch for startup logs:**
```
[pg_client_default]   🧹 Cleaned up N orphaned views (DETACH'd databases)
(or)
[pg_client_default]   ℹ️  No ATTACH'd databases to expose
[pg_client_default]   ✅ Registered refresh_attached_views() UDF
```

---

### **Step 2: Connect DBeaver**

With `preferQueryMode=simple` driver property

---

### **Step 3: ATTACH a Cascade Session**

```sql
-- Find a session with tables (500K+ file)
-- (You said agile-finch-4acdcc has data)

-- ATTACH it
ATTACH 'session_dbs/agile-finch-4acdcc.duckdb' AS test_cascade;

-- Create views
SELECT refresh_attached_views();
-- Returns: "Views refreshed for ATTACH'd databases"
```

**Watch server logs:**
```
✅ Created N views for ATTACH'd databases
```

---

### **Step 4: Verify Views Created**

```sql
-- List all views for this database
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'main'
  AND table_type = 'VIEW'
  AND table_name LIKE 'test_cascade__%'
ORDER BY table_name;
```

**Should return:**
```
test_cascade___load_products
test_cascade___transform_data
test_cascade___output
(or whatever tables exist in that session)
```

---

### **Step 5: Query a View**

```sql
-- Query via view (simple!)
SELECT * FROM test_cascade___load_products LIMIT 5;

-- Query via full path (also works!)
SELECT * FROM test_cascade.main._load_products LIMIT 5;

-- Both should return the same data!
```

---

### **Step 6: Refresh DBeaver and Browse**

1. **Right-click connection** → **Invalidate/Reconnect**
2. **Expand:** Schemas → main → Tables
3. **Look for:** Views with `test_cascade__` prefix!

**Expected:**
```
📁 main
  └── 📁 Tables
      ├── test_demo
      ├── my_test
      ├── test_cascade___load_products  ← ATTACH'd view!
      ├── test_cascade___transform_data  ← ATTACH'd view!
      └── test_cascade___output          ← ATTACH'd view!
```

**Click on a view → See columns!**

---

### **Step 7: Test DETACH Cleanup**

```sql
-- DETACH the database
DETACH test_cascade;
```

**Watch server logs:**
```
🗑️  DETACH test_cascade - cleaning up views...
   🧹 Dropped N views for test_cascade
✓ DETACH executed
```

**Verify views are gone:**
```sql
SELECT COUNT(*) FROM information_schema.tables
WHERE table_name LIKE 'test_cascade__%';
-- Should return 0! ✅
```

---

### **Step 8: Test Server Restart Cleanup**

```sql
-- Re-ATTACH
ATTACH 'session_dbs/agile-finch-4acdcc.duckdb' AS test_cascade;
SELECT refresh_attached_views();

-- Verify views exist
SELECT COUNT(*) FROM information_schema.tables
WHERE table_name LIKE 'test_cascade__%';
-- Returns N > 0

-- Now STOP the server (DON'T run DETACH)
```

**Stop server:**
```bash
# Ctrl+C
```

**Restart server:**
```bash
rvbbit sql server --port 15432
```

**Watch startup logs:**
```
🧹 Cleaned up N orphaned views (DETACH'd databases)
```

**Reconnect DBeaver and check:**
```sql
SELECT COUNT(*) FROM information_schema.tables
WHERE table_name LIKE 'test_cascade__%';
-- Should return 0! (auto-cleaned on startup) ✅
```

---

## ✅ **Success Criteria**

All of these should work:

- [ ] `refresh_attached_views()` creates views for ATTACH'd databases
- [ ] Views are queryable via SQL
- [ ] Views appear in DBeaver tree after Invalidate/Reconnect
- [ ] DETACH automatically drops views
- [ ] Server restart automatically cleans orphaned views
- [ ] Can ATTACH multiple databases and see all their tables
- [ ] View naming follows `database__table` pattern

---

## 🎁 **Bonus: Browse Multiple Cascade Sessions**

```sql
-- ATTACH several cascade runs
ATTACH 'session_dbs/run1.duckdb' AS run1;
ATTACH 'session_dbs/run2.duckdb' AS run2;
ATTACH 'session_dbs/run3.duckdb' AS run3;

-- Create all views
SELECT refresh_attached_views();

-- Refresh DBeaver
```

**DBeaver tree shows:**
```
📁 main
  └── 📁 Tables
      ├── run1___extract
      ├── run1___transform
      ├── run1___output
      ├── run2___extract
      ├── run2___transform
      ├── run2___output
      ├── run3___extract
      ├── run3___transform
      └── run3___output
```

**Compare runs visually in DBeaver!** 🎯

---

## 🚀 **Production Workflow**

### **For Debugging:**

```sql
-- 1. Find recent cascade sessions
-- (Need to implement session browser - future feature!)

-- 2. ATTACH the one you want to debug
ATTACH 'session_dbs/failed_cascade_abc123.duckdb' AS debug;

-- 3. Make browsable
SELECT refresh_attached_views();

-- 4. Refresh DBeaver → Browse debug__* tables

-- 5. When done
DETACH debug;  -- Auto-cleans views!
```

### **For External Data:**

```sql
-- 1. ATTACH production database (read-only!)
ATTACH 'postgres://prod.company.com/warehouse' AS prod (TYPE POSTGRES, READ_ONLY);

-- 2. Make browsable
SELECT refresh_attached_views();

-- 3. Query with LLM enrichment
SELECT
    user_id,
    company_name,
    rvbbit_udf('Classify industry', company_name) as industry
FROM prod__customers
LIMIT 100;

-- 4. When done
DETACH prod;  -- Auto-cleans views!
```

---

## 📊 **Implementation Summary**

| Component | Lines | Purpose |
|-----------|-------|---------|
| `_cleanup_orphaned_views()` | ~45 | Auto-cleanup on startup |
| `_create_attached_db_views()` | ~60 | Create views for ATTACH'd DBs |
| `_handle_detach()` | ~50 | Cleanup views on DETACH |
| `_register_refresh_views_udf()` | ~15 | SQL function for manual refresh |
| **Total** | **~170 lines** | **Complete lifecycle management!** |

---

## 🎊 **Result**

**ATTACH'd databases are now:**
- ✅ Browsable in DBeaver (as views)
- ✅ Queryable with simple names
- ✅ Auto-cleaned on DETACH
- ✅ Auto-cleaned on restart
- ✅ Manually refreshable

**No orphaned views, ever!** 🎉

---

**Restart the server and run through the test checklist!** 🚀
