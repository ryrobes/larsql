-- Debug ATTACH'd databases
-- Run this in DBeaver SQL Console

-- 1. What databases are currently attached?
SELECT database_name, path, internal
FROM duckdb_databases()
ORDER BY database_name;

-- 2. What tables exist across ALL databases?
SELECT database_name, schema_name, table_name
FROM duckdb_tables()
ORDER BY database_name, schema_name, table_name;

-- 3. Check information_schema for cascade_test
SELECT table_catalog, table_schema, table_name
FROM information_schema.tables
ORDER BY table_catalog, table_schema, table_name;

-- 4. Try to DETACH and re-ATTACH
DETACH cascade_test;

-- 5. Re-attach
ATTACH 'session_dbs/cascade_test.duckdb' AS cascade_test;

-- 6. Check what's in it NOW
SELECT database_name, schema_name, table_name
FROM duckdb_tables()
WHERE database_name = 'cascade_test';

-- 7. If still empty, check if the file itself has tables
-- (We'll check this in Python separately)
