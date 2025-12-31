-- ============================================================================
-- RVBBIT SQL New Features - Complete Examples (2025-12-27)
-- ============================================================================
--
-- This file demonstrates the new SQL features added to RVBBIT:
-- 1. Schema-Aware Outputs
-- 2. EXPLAIN RVBBIT MAP
-- 3. MAP DISTINCT
-- 4. Cache TTL
--
-- Prerequisites:
--   1. Start RVBBIT PostgreSQL server: rvbbit server --port 5432
--   2. Connect from DBeaver/psql: postgresql://rvbbit@localhost:5432/default
--   3. Create test data (see bottom of file)
--

-- ============================================================================
-- FEATURE 1: Schema-Aware Outputs
-- ============================================================================

-- OLD WAY: Single JSON result column
RVBBIT MAP 'examples/test_schema_output.yaml' AS result
USING (SELECT product_name FROM products LIMIT 5);
-- Returns: product_name | result (VARCHAR with JSON string)

-- NEW WAY: Typed columns extracted from JSON
RVBBIT MAP 'examples/test_schema_output.yaml' AS (
    brand VARCHAR,
    category VARCHAR,
    price_tier VARCHAR,
    confidence DOUBLE,
    is_luxury BOOLEAN
)
USING (SELECT product_name FROM products LIMIT 5);
-- Returns: product_name | brand | category | price_tier | confidence | is_luxury
--          All properly typed!


-- ============================================================================
-- FEATURE 2: Schema Inference from Cascade
-- ============================================================================

-- Automatically read output_schema from YAML file
RVBBIT MAP 'examples/test_schema_output.yaml'
USING (SELECT product_name FROM products LIMIT 3)
WITH (infer_schema = true);
-- Returns: Same typed columns as above, but schema came from YAML!


-- ============================================================================
-- FEATURE 3: EXPLAIN RVBBIT MAP - Cost Estimation
-- ============================================================================

-- Estimate cost BEFORE running
EXPLAIN RVBBIT MAP 'traits/extract_brand.yaml'
USING (SELECT product_name FROM products LIMIT 100);

-- Output shows:
-- → Query Plan:
--   ├─ Input Rows: 100
--   ├─ Cascade: traits/extract_brand.yaml
--   │  ├─ Cells: 1
--   │  ├─ Model: google/gemini-2.5-flash-lite
--   │  ├─ Cost Estimate: $0.000704 per row → $0.07 total
--   ├─ Cache Hit Rate: 0% (first run)
--   └─ Rewritten SQL: ...


-- EXPLAIN with typed schema
EXPLAIN RVBBIT MAP 'examples/test_schema_output.yaml' AS (
    brand VARCHAR,
    confidence DOUBLE,
    is_luxury BOOLEAN
)
USING (SELECT product_name FROM products LIMIT 1000);
-- Shows cost for 1000 rows with schema extraction


-- EXPLAIN with DISTINCT (shows dedupe impact)
EXPLAIN RVBBIT MAP DISTINCT 'traits/extract_brand.yaml'
USING (SELECT product_name FROM products);
-- Shows how many unique rows will be processed


-- ============================================================================
-- FEATURE 4: MAP DISTINCT - Deduplication
-- ============================================================================

-- First, create some duplicate products
INSERT INTO products VALUES
  (101, 'Apple iPhone 15 Pro Max 256GB Space Black', 1199.99, 'Electronics', true),
  (102, 'Apple iPhone 15 Pro Max 256GB Space Black', 1199.99, 'Electronics', true),
  (103, 'Samsung Galaxy S24 Ultra 512GB Titanium Gray', 1299.99, 'Electronics', true);

-- Without DISTINCT: Processes all rows (including duplicates)
RVBBIT MAP 'traits/extract_brand.yaml' AS brand
USING (SELECT product_name FROM products WHERE product_id >= 101);
-- Returns 3 rows (including 2 duplicates)

-- With DISTINCT: Dedupes all columns
RVBBIT MAP DISTINCT 'traits/extract_brand.yaml' AS brand
USING (SELECT product_name FROM products WHERE product_id >= 101);
-- Returns 2 rows (duplicates removed!)


-- ============================================================================
-- FEATURE 5: Dedupe by Specific Column
-- ============================================================================

-- Dedupe by product_name only (keeps first occurrence)
RVBBIT MAP 'traits/extract_brand.yaml' AS brand
USING (
    SELECT product_id, product_name, price
    FROM products
)
WITH (dedupe_by='product_name');
-- Processes each unique product_name once, keeps all other columns from first row


-- ============================================================================
-- FEATURE 6: Cache TTL - Time-Based Expiry
-- ============================================================================

-- Cache results for 1 hour
RVBBIT MAP 'traits/extract_brand.yaml' AS brand
USING (SELECT product_name FROM products LIMIT 10)
WITH (cache='1h');

-- Cache for 1 day (good for stable reference data)
RVBBIT MAP 'traits/classify_category.yaml' AS category
USING (SELECT product_name FROM products)
WITH (cache='1d');

-- Short-lived cache (5 minutes for real-time data)
RVBBIT MAP 'traits/sentiment.yaml' AS sentiment
USING (SELECT review_text FROM reviews_stream)
WITH (cache='5m');

-- No cache (always fresh)
RVBBIT MAP 'cascade.yaml' AS result
USING (SELECT * FROM live_data)
WITH (cache='0s');


-- ============================================================================
-- FEATURE 7: Combining Everything
-- ============================================================================

-- EXPLAIN + DISTINCT + Schema + Cache
EXPLAIN RVBBIT MAP DISTINCT 'examples/test_schema_output.yaml' AS (
    brand VARCHAR,
    category VARCHAR,
    confidence DOUBLE
)
USING (SELECT product_name FROM products)
WITH (dedupe_by='product_name', cache='12h');

-- Shows:
-- - How many unique products after dedupe
-- - Cost estimate with cache hit rate
-- - Exact SQL that will run


-- Complex real-world example
RVBBIT MAP DISTINCT 'cascades/enrich_customer.yaml' AS (
    lifetime_value DOUBLE,
    churn_risk DOUBLE,
    segment VARCHAR,
    next_best_action VARCHAR
)
USING (
    SELECT
        c.customer_id,
        c.email,
        COUNT(o.order_id) as order_count,
        SUM(o.total) as total_spent,
        MAX(o.order_date) as last_order_date
    FROM customers c
    LEFT JOIN orders o ON c.customer_id = o.customer_id
    GROUP BY c.customer_id, c.email
    HAVING COUNT(o.order_id) > 5  -- Only engaged customers
)
WITH (
    dedupe_by='customer_id',
    cache='6h',
    infer_schema=false  -- Explicit schema above
);


-- ============================================================================
-- FEATURE 8: Downstream Analysis
-- ============================================================================

-- Enrich products, then analyze
WITH enriched AS (
    -- This is a CTE, so we need to use the old syntax with rvbbit_run
    SELECT
        p.product_id,
        p.product_name,
        p.price,
        rvbbit_run('traits/extract_brand.yaml', json_object('product_name', p.product_name)) as brand_json
    FROM products p
    LIMIT 100
)
SELECT
    json_extract_string(brand_json, '$.state.output_extract') as brand,
    COUNT(*) as product_count,
    AVG(price) as avg_price
FROM enriched
GROUP BY brand
ORDER BY product_count DESC;

-- NOTE: For full typed outputs in CTEs, wait for table materialization feature


-- ============================================================================
-- FEATURE 9: Error Handling
-- ============================================================================

-- Schema mismatch will return NULL for invalid fields
RVBBIT MAP 'examples/test_schema_output.yaml' AS (
    brand VARCHAR,
    confidence DOUBLE,
    nonexistent_field VARCHAR  -- Will be NULL
)
USING (SELECT product_name FROM products LIMIT 3);

-- Check for errors in result column
RVBBIT MAP 'cascade_that_might_fail.yaml' AS result
USING (SELECT data FROM mixed_quality_data)
WITH (cache='1h');

SELECT * FROM (/* above query */)
WHERE result NOT LIKE 'ERROR:%';  -- Filter out failures


-- ============================================================================
-- TEST DATA SETUP
-- ============================================================================

-- Create sample products table
CREATE TEMP TABLE products AS
SELECT * FROM (VALUES
  (1, 'Apple iPhone 15 Pro Max 256GB Space Black', 1199.99, 'Electronics', true),
  (2, 'Samsung Galaxy S24 Ultra 512GB Titanium Gray', 1299.99, 'Electronics', true),
  (3, 'Sony WH-1000XM5 Wireless Noise Canceling Headphones Black', 399.99, 'Electronics', true),
  (4, 'Apple MacBook Pro 16" M3 Max 48GB RAM', 3499.99, 'Computers', true),
  (5, 'Dell XPS 15 Intel i7 16GB RAM', 1599.99, 'Computers', true),
  (6, 'Nike Air Max 270 Running Shoes Black White', 150.00, 'Footwear', true),
  (7, 'Adidas Ultraboost 22 Men''s Running Shoes', 180.00, 'Footwear', true),
  (8, 'Levi''s 501 Original Fit Jeans Dark Blue 32x32', 69.99, 'Clothing', true),
  (9, 'North Face Summit Series Gore-Tex Jacket', 599.00, 'Clothing', true),
  (10, 'KitchenAid Artisan Stand Mixer 5Qt Red', 449.99, 'Appliances', true),
  (11, 'Dyson V15 Detect Cordless Vacuum Cleaner', 749.99, 'Appliances', true),
  (12, 'Bose QuietComfort 45 Bluetooth Headphones', 329.00, 'Electronics', true),
  (13, 'Canon EOS R6 Mark II Mirrorless Camera Body', 2499.00, 'Electronics', true),
  (14, 'Sony PlayStation 5 Console Digital Edition', 449.99, 'Gaming', true),
  (15, 'Microsoft Xbox Series X 1TB Console', 499.99, 'Gaming', false),
  (16, 'Generic Wireless Mouse 2.4GHz', 12.99, 'Electronics', true),
  (17, 'Logitech MX Master 3S Wireless Mouse Graphite', 99.99, 'Electronics', true),
  (18, 'Herman Miller Aeron Office Chair Size B', 1445.00, 'Furniture', true),
  (19, 'IKEA Markus Office Chair Black', 199.00, 'Furniture', true),
  (20, 'Patagonia Better Sweater Fleece Jacket Navy', 139.00, 'Clothing', true)
) AS t(product_id, product_name, price, category, in_stock);

-- Verify
SELECT COUNT(*) as total_products FROM products;
SELECT category, COUNT(*) as count FROM products GROUP BY category ORDER BY count DESC;


-- ============================================================================
-- Try it yourself!
-- ============================================================================

-- 1. Run the test data setup above
-- 2. Try EXPLAIN first to see estimated cost:
EXPLAIN RVBBIT MAP 'examples/test_schema_output.yaml'
USING (SELECT product_name FROM products LIMIT 5);

-- 3. If cost is acceptable, run with schema:
RVBBIT MAP 'examples/test_schema_output.yaml' AS (
    brand VARCHAR,
    category VARCHAR,
    price_tier VARCHAR,
    confidence DOUBLE,
    is_luxury BOOLEAN
)
USING (SELECT product_name FROM products LIMIT 5);

-- 4. Run again - should be cached!
-- (Check EXPLAIN again to see cache hit rate)

-- 5. Try with DISTINCT:
RVBBIT MAP DISTINCT 'traits/extract_brand.yaml' AS brand
USING (SELECT product_name FROM products);
