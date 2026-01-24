-- ============================================
-- Hyper Cost Visualization Demo
-- ============================================
-- This file demonstrates the auto-explain and
-- cost tracking features in the Hyper SQL editor.
--
-- Open this file in /hyper and watch as cost
-- estimates appear automatically as you type!
-- ============================================

-- Setup: Create sample data
CREATE OR REPLACE TABLE products AS
SELECT * FROM (VALUES
  ('Apple iPhone 15', 'Latest smartphone with advanced camera', 'Electronics', 999.00),
  ('Samsung Galaxy S24', 'Flagship Android phone', 'Electronics', 899.00),
  ('MacBook Pro M3', 'Professional laptop for creators', 'Electronics', 2499.00),
  ('Patagonia Fleece', 'Eco-friendly outdoor jacket', 'Clothing', 149.00),
  ('Nike Running Shoes', 'Lightweight performance footwear', 'Clothing', 120.00),
  ('Organic Coffee Beans', 'Fair trade dark roast', 'Food', 15.00),
  ('Bamboo Water Bottle', 'Sustainable reusable bottle', 'Kitchen', 25.00),
  ('Recycled Notebook', 'Made from 100% recycled paper', 'Office', 8.00),
  ('Solar Phone Charger', 'Portable renewable energy', 'Electronics', 49.00),
  ('Compost Bin', 'Kitchen waste recycling', 'Kitchen', 35.00)
) AS t(product_name, description, category, price);

-- ============================================
-- QUERY 1: Free Tier (Plain SQL, no LLM calls)
-- Expected: ✓ Free ($0)
-- ============================================
SELECT * FROM products WHERE category = 'Electronics';

-- ============================================
-- QUERY 2: Low Cost (Small semantic query)
-- Expected: $ Low cost ($0.001 - $0.01)
-- ============================================
SELECT
  product_name,
  description MEANS 'eco-friendly' as is_sustainable
FROM products
LIMIT 5;

-- ============================================
-- QUERY 3: Moderate Cost (Larger semantic scan)
-- Expected: $$ Moderate ($0.01 - $0.10)
-- ============================================
SELECT
  product_name,
  description,
  ASK('Rate this product sustainability 1-10', description) as sustainability_score
FROM products;

-- ============================================
-- QUERY 4: Expensive (Aggregation with LLM)
-- Expected: ⚠ Expensive ($0.10 - $1.00)
-- ============================================
SELECT
  category,
  SUMMARIZE(description) as category_summary,
  SENTIMENT(description) as overall_sentiment,
  COUNT(*) as product_count
FROM products
GROUP BY category;

-- ============================================
-- QUERY 5: Multiple semantic operators
-- Expected: Variable cost based on operations
-- ============================================
SELECT
  product_name,
  category,
  description MEANS 'sustainable' as eco_friendly,
  description ABOUT 'technology' > 0.5 as is_tech,
  ASK('Extract the main benefit in 3 words', description) as key_benefit
FROM products
WHERE price < 500;

-- ============================================
-- TIPS:
-- ============================================
-- 1. Hover over gutter icons to see detailed
--    explain plans and optimization hints
--
-- 2. Watch the header for session totals as
--    you add/modify queries
--
-- 3. Run queries to see actual vs estimated
--    costs (appears after ~2 seconds)
--
-- 4. Try adding LIMIT clauses to reduce costs
--    on expensive queries
--
-- 5. Use caching! Re-run the same query to see
--    100% cache hit rate (cost drops to ~$0)
-- ============================================
