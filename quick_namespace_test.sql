-- QUICK TEST: Does the basic query even work?

-- Test 1: Simplest possible query
SELECT 'test' as name;

-- Test 2: UNION ALL test
SELECT 'row1' as name
UNION ALL
SELECT 'row2' as name;

-- Test 3: Check current database/schema
SELECT current_database();
SELECT current_schema();

-- Test 4: List all schemas
SELECT * FROM information_schema.schemata;

-- Test 5: Create pg_catalog schema with database prefix
CREATE SCHEMA IF NOT EXISTS memory.pg_catalog;  -- Try with database name
-- OR
CREATE SCHEMA IF NOT EXISTS pg_catalog;  -- Try without

-- Test 6: Simple view without pg_catalog prefix
CREATE OR REPLACE VIEW test_view AS
SELECT 'hello' as message;

SELECT * FROM test_view;

-- Test 7: View IN pg_catalog schema
CREATE OR REPLACE VIEW pg_catalog.test_view2 AS
SELECT 'world' as message;

SELECT * FROM pg_catalog.test_view2;

-- ============================================================
-- CRITICAL QUESTION TO ANSWER:
-- Can you create views in pg_catalog schema AT ALL?
-- If Step 7 fails → that's the root cause!
-- ============================================================
