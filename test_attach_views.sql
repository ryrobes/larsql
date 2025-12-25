-- Test ATTACH Discovery with Views
-- Run this in DBeaver SQL Console (with preferQueryMode=simple)

-- Step 1: Check current state
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'main'
ORDER BY table_name;
-- Should show your existing tables

-- Step 2: ATTACH a cascade session
-- (Pick one that inspect_session_db.py showed has tables)
ATTACH 'session_dbs/agile-finch-4acdcc.duckdb' AS test_cascade;

-- Step 3: Refresh views
SELECT refresh_attached_views();
-- Should return: "Views refreshed for ATTACH'd databases"

-- Step 4: Check if views were created
SELECT table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'main'
  AND table_name LIKE 'test_cascade%'
ORDER BY table_name;
-- Should show views like: test_cascade___load_products, etc.

-- Step 5: Query a view
-- (Use actual view name from step 4)
SELECT * FROM test_cascade___load_products LIMIT 5;

-- Step 6: List ALL views created
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'main'
  AND table_type = 'VIEW'
  AND table_name LIKE '%__%'
ORDER BY table_name;

-- ============================================================
-- If this works:
-- 1. Views are queryable ✅
-- 2. Right-click connection → Invalidate/Reconnect
-- 3. Expand main → Tables → See test_cascade__* views!
-- ============================================================
