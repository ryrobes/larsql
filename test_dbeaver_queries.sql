-- Test the exact queries DBeaver uses for schema browsing
-- Run these in DBeaver SQL Console to see what works

-- Query 1: Basic pg_tables (what we know works)
SELECT * FROM pg_catalog.pg_tables WHERE schemaname = 'main';

-- Query 2: pg_class (tables/views)
SELECT * FROM pg_catalog.pg_class WHERE relkind = 'r' LIMIT 10;

-- Query 3: pg_class with pg_namespace JOIN (what DBeaver likely uses)
SELECT
    c.relname as table_name,
    n.nspname as schema_name,
    c.relkind
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
WHERE n.nspname = 'main' AND c.relkind = 'r';

-- Query 4: DBeaver's typical table list query
SELECT
    c.oid,
    c.relname,
    c.relnamespace,
    c.relkind,
    n.nspname
FROM pg_catalog.pg_class c
LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'v', 'm')  -- r=table, v=view, m=materialized view
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n.nspname, c.relname;

-- Query 5: Check if OID joining works
SELECT
    c.relname,
    c.relnamespace as namespace_oid,
    n.oid as actual_oid,
    n.nspname
FROM pg_catalog.pg_class c
LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relname = 'test_demo';

-- =================================================================
-- REPORT BACK:
-- Which queries return data?
-- Which queries return empty?
-- What's the value of relnamespace vs n.oid?
-- =================================================================
