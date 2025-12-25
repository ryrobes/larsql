-- COMPREHENSIVE CLEANUP: Remove ALL old pg_* views
-- Run this in DBeaver SQL Console to clean your database

-- Drop double-prefix views (typo from earlier)
DROP VIEW IF EXISTS main.pg_pg_attribute CASCADE;
DROP VIEW IF EXISTS main.pg_pg_class CASCADE;
DROP VIEW IF EXISTS main.pg_pg_database CASCADE;
DROP VIEW IF EXISTS main.pg_pg_description CASCADE;
DROP VIEW IF EXISTS main.pg_pg_index CASCADE;
DROP VIEW IF EXISTS main.pg_pg_proc CASCADE;
DROP VIEW IF EXISTS main.pg_pg_settings CASCADE;
DROP VIEW IF EXISTS main.pg_pg_tables CASCADE;
DROP VIEW IF EXISTS main.pg_pg_type CASCADE;
DROP VIEW IF EXISTS main.pg_pg_namespace CASCADE;

-- Drop single-prefix views
DROP VIEW IF EXISTS main.pg_attribute CASCADE;
DROP VIEW IF EXISTS main.pg_class CASCADE;
DROP VIEW IF EXISTS main.pg_database CASCADE;
DROP VIEW IF EXISTS main.pg_description CASCADE;
DROP VIEW IF EXISTS main.pg_index CASCADE;
DROP VIEW IF EXISTS main.pg_proc CASCADE;
DROP VIEW IF EXISTS main.pg_settings CASCADE;
DROP VIEW IF EXISTS main.pg_tables CASCADE;
DROP VIEW IF EXISTS main.pg_type CASCADE;
DROP VIEW IF EXISTS main.pg_namespace CASCADE;

-- Verify EVERYTHING is gone
SELECT table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'main'
  AND table_name LIKE 'pg_%'
ORDER BY table_name;

-- Should return 0 rows!

-- Now show ONLY user tables
SELECT table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'main'
  AND table_name NOT LIKE 'pg_%'
ORDER BY table_name;

-- Should show ONLY: test_demo, my_test, diagnostic_test, etc.
