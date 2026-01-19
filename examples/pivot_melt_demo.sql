-- ═══════════════════════════════════════════════════════════════════════════
-- PIVOT and MELT Pipeline Demo
-- Run these queries in DataGrip connected to LARS SQL Server
-- ═══════════════════════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════════════════════
-- SETUP: Create sample data tables
-- ═══════════════════════════════════════════════════════════════════════════

-- Long-format sales data (good for PIVOT)
CREATE OR REPLACE TABLE sales_by_region AS
SELECT * FROM (VALUES
    ('Widget',  'North', 2024, 1500),
    ('Widget',  'South', 2024, 2200),
    ('Widget',  'East',  2024, 1800),
    ('Widget',  'West',  2024, 1950),
    ('Gadget',  'North', 2024, 3200),
    ('Gadget',  'South', 2024, 2800),
    ('Gadget',  'East',  2024, 3100),
    ('Gadget',  'West',  2024, 2650),
    ('Gizmo',   'North', 2024, 950),
    ('Gizmo',   'South', 2024, 1100),
    ('Gizmo',   'East',  2024, 875),
    ('Gizmo',   'West',  2024, 1025)
) AS t(product, region, year, revenue);

-- Wide-format quarterly data (good for MELT)
CREATE OR REPLACE TABLE quarterly_sales AS
SELECT * FROM (VALUES
    ('Widget',  'Electronics', 1500, 1800, 2100, 2400),
    ('Gadget',  'Electronics', 3200, 3500, 3100, 3800),
    ('Gizmo',   'Accessories', 950,  1100, 1250, 1400),
    ('Thingamajig', 'Home',    2200, 2000, 2300, 2100),
    ('Doohickey', 'Garden',    800,  1200, 1500, 900)
) AS t(product, category, q1_revenue, q2_revenue, q3_revenue, q4_revenue);

-- Multi-metric wide data (more complex MELT scenario)
CREATE OR REPLACE TABLE product_metrics AS
SELECT * FROM (VALUES
    ('Widget',  100, 150, 200,   4.5, 4.7, 4.8),
    ('Gadget',  200, 180, 220,   4.2, 4.4, 4.6),
    ('Gizmo',   80,  95,  110,   4.8, 4.9, 4.9)
) AS t(product, jan_sales, feb_sales, mar_sales, jan_rating, feb_rating, mar_rating);

-- Verify data was created
SELECT 'sales_by_region' as table_name, COUNT(*) as rows FROM sales_by_region
UNION ALL
SELECT 'quarterly_sales', COUNT(*) FROM quarterly_sales
UNION ALL
SELECT 'product_metrics', COUNT(*) FROM product_metrics;


-- ═══════════════════════════════════════════════════════════════════════════
-- PIVOT EXAMPLES
-- ═══════════════════════════════════════════════════════════════════════════

-- Example 1: Basic pivot - revenue by region for each product
SELECT * FROM sales_by_region
THEN PIVOT 'show revenue by region for each product';

-- Example 2: Natural language pivot with analysis context
SELECT product, region, revenue
FROM sales_by_region
WHERE year = 2024
THEN PIVOT 'create a cross-tab showing products as rows and regions as columns with revenue values';

-- Example 3: Pivot with INTO to save results
SELECT * FROM sales_by_region
THEN PIVOT 'revenue by region per product'
INTO pivoted_sales;

-- Check the saved table
SELECT * FROM pivoted_sales;


-- ═══════════════════════════════════════════════════════════════════════════
-- MELT EXAMPLES
-- ═══════════════════════════════════════════════════════════════════════════

-- Example 1: Basic melt - convert quarterly columns to rows
SELECT * FROM quarterly_sales
THEN MELT 'convert the quarterly revenue columns into rows';

-- Example 2: Melt with custom column names
SELECT product, category, q1_revenue, q2_revenue, q3_revenue, q4_revenue
FROM quarterly_sales
THEN MELT 'unpivot quarterly columns into quarter and revenue columns';

-- Example 3: Melt specific columns only
SELECT * FROM quarterly_sales
THEN MELT 'melt q1_revenue, q2_revenue, q3_revenue, q4_revenue keeping product and category as identifiers';

-- Example 4: Melt with INTO to save results
SELECT * FROM quarterly_sales
THEN MELT 'convert quarterly columns to rows'
INTO melted_sales;

-- Check the saved table
SELECT * FROM melted_sales;


-- ═══════════════════════════════════════════════════════════════════════════
-- CHAINED EXAMPLES: PIVOT/MELT with other stages
-- ═══════════════════════════════════════════════════════════════════════════

-- Pivot then analyze the results
SELECT * FROM sales_by_region
THEN PIVOT 'revenue by region for each product'
THEN ANALYZE 'which product has the most balanced regional distribution?';

-- Melt then filter
SELECT * FROM quarterly_sales
THEN MELT 'quarterly revenue columns to rows'
THEN FILTER 'only quarters with revenue above 2000';

-- Full pipeline: Melt → Filter → Analyze → Save
SELECT * FROM quarterly_sales
THEN MELT 'convert quarters to rows'
THEN FILTER 'Q4 results only'
THEN ANALYZE 'summarize Q4 performance by category'
INTO q4_analysis;


-- ═══════════════════════════════════════════════════════════════════════════
-- ADVANCED: Round-trip test (MELT then PIVOT should approximate original)
-- ═══════════════════════════════════════════════════════════════════════════

-- Original wide format
SELECT * FROM quarterly_sales;

-- Melt to long format
SELECT * FROM quarterly_sales
THEN MELT 'quarterly columns to quarter and revenue'
INTO melted_quarterly;

-- Pivot back to wide format
SELECT * FROM melted_quarterly
THEN PIVOT 'revenue by quarter for each product';


-- ═══════════════════════════════════════════════════════════════════════════
-- CLEANUP (optional)
-- ═══════════════════════════════════════════════════════════════════════════

-- DROP TABLE IF EXISTS sales_by_region;
-- DROP TABLE IF EXISTS quarterly_sales;
-- DROP TABLE IF EXISTS product_metrics;
-- DROP TABLE IF EXISTS pivoted_sales;
-- DROP TABLE IF EXISTS melted_sales;
-- DROP TABLE IF EXISTS melted_quarterly;
-- DROP TABLE IF EXISTS q4_analysis;
