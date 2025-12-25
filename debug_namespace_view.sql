-- DEBUG: pg_namespace view creation
-- Run these one at a time in DBeaver SQL Console

-- Step 1: Test basic UNION ALL (should ALWAYS return 4 rows)
SELECT 'main' as nspname, 0 as oid
UNION ALL
SELECT 'pg_catalog' as nspname, 0 as oid
UNION ALL
SELECT 'information_schema' as nspname, 0 as oid
UNION ALL
SELECT 'public' as nspname, 0 as oid;

-- Expected: 4 rows (main, pg_catalog, information_schema, public)
-- If this returns NOTHING → DuckDB syntax issue!


-- Step 2: Test information_schema.tables query
SELECT DISTINCT table_schema as nspname, 0 as oid
FROM information_schema.tables
WHERE table_schema NOT IN ('main', 'pg_catalog', 'information_schema', 'public');

-- Expected: Empty or additional schemas (if you have any)


-- Step 3: Test combined query (what the view should be)
SELECT 'main' as nspname, 0 as oid
UNION ALL
SELECT 'pg_catalog' as nspname, 0 as oid
UNION ALL
SELECT 'information_schema' as nspname, 0 as oid
UNION ALL
SELECT 'public' as nspname, 0 as oid
UNION ALL
SELECT DISTINCT
    table_schema as nspname,
    0 as oid
FROM information_schema.tables
WHERE table_schema NOT IN ('main', 'pg_catalog', 'information_schema', 'public');

-- Expected: At least 4 rows
-- If this returns data BUT the view doesn't → view creation issue!


-- Step 4: Check if pg_catalog schema exists
SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'pg_catalog';

-- Expected: 1 row
-- If empty → need to create pg_catalog schema first!


-- Step 5: Create pg_catalog schema if needed
CREATE SCHEMA IF NOT EXISTS pg_catalog;


-- Step 6: Now try creating the view
CREATE OR REPLACE VIEW pg_catalog.pg_namespace AS
SELECT 'main' as nspname, 0 as oid
UNION ALL
SELECT 'pg_catalog' as nspname, 0 as oid
UNION ALL
SELECT 'information_schema' as nspname, 0 as oid
UNION ALL
SELECT 'public' as nspname, 0 as oid
UNION ALL
SELECT DISTINCT
    table_schema as nspname,
    0 as oid
FROM information_schema.tables
WHERE table_schema NOT IN ('main', 'pg_catalog', 'information_schema', 'public');


-- Step 7: Query the view
SELECT * FROM pg_catalog.pg_namespace ORDER BY nspname;

-- Expected: At least 4 rows
-- If empty → something is very wrong!


-- Step 8: Check if view actually exists
SELECT table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'pg_catalog' AND table_name = 'pg_namespace';

-- Expected: 1 row showing VIEW
-- If empty → view creation failed!


-- Step 9: Try querying with explicit schema
SELECT * FROM pg_catalog.pg_namespace;

-- vs

SELECT * FROM main.pg_catalog.pg_namespace;

-- One of these should work!


-- ============================================================
-- DIAGNOSTIC OUTPUT
-- ============================================================
-- Report back which steps WORKED and which FAILED
-- This will help identify the exact issue
