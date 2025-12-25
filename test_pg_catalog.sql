-- Test if DuckDB's built-in pg_catalog actually has data

-- Test 1: pg_database
SELECT * FROM pg_catalog.pg_database;

-- Test 2: pg_database with WHERE
SELECT * FROM pg_catalog.pg_database WHERE datname = 'default';

-- Test 3: pg_settings
SELECT * FROM pg_catalog.pg_settings LIMIT 10;

-- Test 4: pg_settings with WHERE
SELECT * FROM pg_catalog.pg_settings WHERE name = 'standard_conforming_strings';

-- If these return 0 rows, DuckDB's pg_catalog is incomplete
-- and we need to create minimal views after all!
