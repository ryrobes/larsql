-- Alternative catalog view creation using DuckDB native commands
-- Run this in DBeaver if information_schema is broken

-- Check DuckDB version
SELECT version();

-- Check what DuckDB system tables are available
SELECT * FROM duckdb_tables();

-- Create pg_tables view using DuckDB native system
CREATE OR REPLACE VIEW pg_catalog.pg_tables AS
SELECT
    schema_name as schemaname,
    table_name as tablename,
    NULL::VARCHAR as tableowner,
    NULL::VARCHAR as tablespace,
    false as hasindexes,
    false as hasrules,
    false as hastriggers,
    false as rowsecurity
FROM duckdb_tables()
WHERE schema_name NOT IN ('information_schema', 'pg_catalog');

-- Test it
SELECT * FROM pg_catalog.pg_tables;

-- Create pg_namespace using DuckDB native
CREATE OR REPLACE VIEW pg_catalog.pg_namespace AS
SELECT 'main' as nspname, 0 as oid
UNION ALL
SELECT 'pg_catalog' as nspname, 0 as oid
UNION ALL
SELECT 'information_schema' as nspname, 0 as oid
UNION ALL
SELECT 'public' as nspname, 0 as oid
UNION ALL
SELECT DISTINCT schema_name as nspname, 0 as oid
FROM duckdb_tables()
WHERE schema_name NOT IN ('main', 'pg_catalog', 'information_schema', 'public');

-- Test it
SELECT * FROM pg_catalog.pg_namespace ORDER BY nspname;
