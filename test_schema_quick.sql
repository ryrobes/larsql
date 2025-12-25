-- Quick test script for schema introspection
-- Run this in DBeaver SQL console after connecting

-- 1. Create a test table
CREATE TABLE IF NOT EXISTS test_users (
    id INTEGER,
    name VARCHAR,
    email VARCHAR,
    created_at TIMESTAMP
);

-- 2. Insert some test data
INSERT INTO test_users VALUES
    (1, 'Alice', 'alice@example.com', CURRENT_TIMESTAMP),
    (2, 'Bob', 'bob@example.com', CURRENT_TIMESTAMP),
    (3, 'Charlie', 'charlie@example.com', CURRENT_TIMESTAMP);

-- 3. Create another test table
CREATE TABLE IF NOT EXISTS test_products (
    id INTEGER,
    name VARCHAR,
    price DOUBLE,
    category VARCHAR
);

-- 4. Insert some test data
INSERT INTO test_products VALUES
    (1, 'Laptop', 999.99, 'Electronics'),
    (2, 'Mouse', 29.99, 'Electronics'),
    (3, 'Desk', 299.99, 'Furniture');

-- ============================================================
-- NOW TEST SCHEMA INTROSPECTION
-- ============================================================

-- Test 1: Check if pg_catalog schema exists
SELECT * FROM information_schema.schemata;

-- Test 2: List tables via DuckDB native command
SHOW TABLES;

-- Test 3: List tables via information_schema
SELECT table_schema, table_name, table_type
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
ORDER BY table_name;

-- Test 4: List tables via pg_catalog.pg_tables
SELECT schemaname, tablename
FROM pg_catalog.pg_tables
WHERE schemaname NOT IN ('information_schema', 'pg_catalog')
ORDER BY tablename;

-- Test 5: List columns via information_schema
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'main'
ORDER BY table_name, ordinal_position;

-- Test 6: List columns via pg_catalog.pg_attribute
SELECT table_name, attname, data_type, attnotnull
FROM pg_catalog.pg_attribute
WHERE table_schema = 'main'
ORDER BY table_name, attnum;

-- Test 7: List schemas
SELECT nspname FROM pg_catalog.pg_namespace ORDER BY nspname;

-- Test 8: Current database/schema
SELECT CURRENT_DATABASE() as db;
SELECT CURRENT_SCHEMA() as schema;

-- Test 9: Version
SELECT VERSION() as version;

-- ============================================================
-- If all these work, refresh DBeaver and check the tree!
-- ============================================================
