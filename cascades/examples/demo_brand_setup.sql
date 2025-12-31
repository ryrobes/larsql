-- Demo: Brand Extraction Setup
--
-- This creates the demo_products table for the SQL mic-drop demo.
-- Run this ONCE before running the cascade_udf demo.
--
-- USAGE:
--   1. Start the RVBBIT PostgreSQL server: rvbbit server --port 5432
--   2. Connect with any SQL client: psql postgresql://rvbbit@localhost:5432/default
--   3. Run this file to create the demo table
--   4. Run the cascade queries below

-- ============================================================
-- Create demo products table
-- ============================================================
-- 6 products: 5 normal, 1 outlier (USB-C Cable)
-- The outlier will trigger the context leak in v0

CREATE TABLE IF NOT EXISTS demo_products (
  id INTEGER,
  product_name VARCHAR,
  expected_brand VARCHAR,
  notes VARCHAR
);

-- Clear and reload
DELETE FROM demo_products;

INSERT INTO demo_products VALUES
  (1, 'Sony WH-1000XM5 Wireless Noise Cancelling Headphones', 'Sony', 'Clear brand in name'),
  (2, 'Apple AirPods Pro (2nd Generation)', 'Apple', 'Clear brand in name'),
  (3, 'Samsung Galaxy Buds2 Pro', 'Samsung', 'Clear brand in name'),
  (4, 'Bose QuietComfort Ultra Earbuds', 'Bose', 'Clear brand in name'),
  (5, 'JBL Tune 760NC Wireless Headphones', 'JBL', 'Clear brand in name'),
  (6, 'USB-C Cable 6ft Black Fast Charging', 'Unknown', 'OUTLIER: No clear brand, triggers broad search');

-- Verify
SELECT * FROM demo_products ORDER BY id;


-- ============================================================
-- Demo Queries
-- ============================================================

-- Query 1: Simple scalar UDF (one-shot extraction)
-- This uses rvbbit_udf for a quick LLM call
/*
SELECT
  product_name,
  rvbbit_udf('Extract the brand name from this product. Return just the brand name, nothing else.', product_name) as brand
FROM demo_products
ORDER BY id;
*/

-- Query 2: Full cascade UDF (v0 - leaky)
-- This runs the full cascade with candidates + validation
-- Watch the receipts - row 6 (USB-C Cable) will spike!
/*
SELECT
  id,
  product_name,
  rvbbit_cascade_udf(
    'examples/demo_brand_extract_v0.yaml',
    json_object('product_name', product_name)
  ) as result
FROM demo_products
ORDER BY id;
*/

-- Query 3: Full cascade UDF (v1 - fixed)
-- Same cascade but with the LIMIT fix
-- Row 6 should now have similar cost to the others
/*
SELECT
  id,
  product_name,
  rvbbit_cascade_udf(
    'examples/demo_brand_extract_v1.yaml',
    json_object('product_name', product_name)
  ) as result
FROM demo_products
ORDER BY id;
*/


-- ============================================================
-- Receipts Analysis Queries
-- ============================================================

-- After running the cascades, analyze costs in the logs

-- Find the outlier runs
/*
SELECT
  session_id,
  cell_name,
  cost,
  tokens_in,
  tokens_out,
  duration_ms
FROM all_data
WHERE cascade_id LIKE 'demo_brand_extract%'
ORDER BY cost DESC
LIMIT 20;
*/

-- Compare v0 vs v1 costs
/*
SELECT
  cascade_id,
  AVG(cost) as avg_cost,
  MAX(cost) as max_cost,
  SUM(cost) as total_cost
FROM all_data
WHERE cascade_id IN ('demo_brand_extract_v0', 'demo_brand_extract_v1')
GROUP BY cascade_id;
*/
