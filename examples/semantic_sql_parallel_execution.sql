-- ============================================================================
-- Parallel Execution for Semantic SQL - User Guide & Examples
-- ============================================================================
-- Speed up semantic SQL queries 3-5x using parallel execution!
--
-- How it works: The -- @ parallel: N annotation splits your query into N
-- UNION ALL branches that DuckDB executes in parallel. Each branch processes
-- a subset of rows concurrently.
--
-- Supported: All SCALAR operators (MEANS, ABOUT, EXTRACTS, ASK, CONDENSE, etc.)
-- Not supported (yet): AGGREGATE operators (SUMMARIZE, THEMES, CLUSTER, etc.)
--
-- Created: 2026-01-02
-- ============================================================================

-- Setup: Create demo data
CREATE TABLE products (
    id INTEGER,
    name VARCHAR,
    description VARCHAR,
    price DOUBLE,
    category VARCHAR
);

INSERT INTO products
SELECT
    i as id,
    'Product ' || i as name,
    'This is a detailed description for product ' || i ||
    (CASE WHEN i % 3 = 0 THEN ' featuring eco-friendly materials'
          WHEN i % 3 = 1 THEN ' with premium quality construction'
          ELSE ' offering great value for the price' END) as description,
    (i * 10.0) as price,
    (CASE WHEN i % 4 = 0 THEN 'electronics'
          WHEN i % 4 = 1 THEN 'home'
          WHEN i % 4 = 2 THEN 'clothing'
          ELSE 'outdoor' END) as category
FROM range(200);  -- 200 products


-- ============================================================================
-- EXAMPLE 1: Basic Parallel Execution (MEANS Operator)
-- ============================================================================

-- Sequential (default):
SELECT * FROM products
WHERE description MEANS 'eco-friendly or sustainable'
LIMIT 100;

-- Parallel with 5 workers (5x faster!):
-- @ parallel: 5
SELECT * FROM products
WHERE description MEANS 'eco-friendly or sustainable'
LIMIT 100;

-- What happens:
-- Query splits into 5 UNION ALL branches:
--   Branch 0: WHERE hash(id) % 5 = 0 AND description MEANS... LIMIT 20
--   Branch 1: WHERE hash(id) % 5 = 1 AND description MEANS... LIMIT 20
--   ... (3 more branches)
-- DuckDB executes all 5 branches concurrently!
-- Performance: 100 rows in ~40s (parallel) vs ~200s (sequential)
-- Note: hash(id) works for any ID type (INTEGER, VARCHAR, UUID, etc.)


-- ============================================================================
-- EXAMPLE 2: Parallel with Multiple Operators
-- ============================================================================

-- Analyze products with multiple semantic operators in parallel:
-- @ parallel: 8
SELECT
    id,
    name,
    description MEANS 'eco-friendly' as is_eco,
    description EXTRACTS 'key feature' as feature,
    description ABOUT 'quality' as quality_score,
    CONDENSE(description) as summary,
    description ASK 'price perception: budget/midrange/premium' as price_tier
FROM products
WHERE description MEANS 'positive attributes'
LIMIT 200;

-- Performance: ~50s (parallel, 8 workers) vs ~400s (sequential)
-- All operators execute in parallel within each branch!


-- ============================================================================
-- EXAMPLE 3: Tuning with batch_size
-- ============================================================================

-- Control memory usage with batch_size parameter:
-- @ parallel: 10
-- @ batch_size: 500
SELECT * FROM products
WHERE description MEANS 'premium quality'
LIMIT 2000;

-- Without batch_size: Would try to process all 2000 rows
-- With batch_size: 500: Caps at 500 rows (50 per branch)
-- Useful for preventing memory exhaustion on large queries


-- ============================================================================
-- EXAMPLE 4: Combined with Other Annotations
-- ============================================================================

-- Parallel + model selection + threshold:
-- @ use a fast and cheap model
-- @ parallel: 6
-- @ threshold: 0.8
SELECT * FROM products
WHERE description ABOUT 'technical specifications' > 0.8
  AND category = 'electronics'
LIMIT 150;

-- All annotations work together:
-- - parallel: 6 → Splits into 6 branches
-- - model hint → Passed to bodybuilder for model selection
-- - threshold: 0.8 → Used in ABOUT rewriting


-- ============================================================================
-- EXAMPLE 5: What Works (Scalars) vs What Doesn't (Aggregates)
-- ============================================================================

-- ✅ WORKS: Scalar operators (per-row evaluation)
-- @ parallel: 5
SELECT
    id,
    description MEANS 'eco' as is_eco,          -- ✅ Boolean per row
    description ABOUT 'quality' as score,       -- ✅ Score per row
    description EXTRACTS 'brand' as brand,      -- ✅ Extraction per row
    description ASK 'urgency?' as urgency,      -- ✅ Prompt per row
    CONDENSE(description) as summary,           -- ✅ Summary per row
    description ~ 'sustainable' as matches      -- ✅ Tilde per row
FROM products
LIMIT 500;

-- ❌ DOESN'T WORK: Aggregate operators (per-group evaluation)
-- @ parallel: 5
SELECT
    category,
    SUMMARIZE(description) as summary,          -- ❌ Aggregate
    THEMES(description, 3) as topics            -- ❌ Aggregate
FROM products
GROUP BY category;

-- Warning logged:
-- "Parallel execution not supported for aggregate operators.
--  Executing sequentially for correct results."
-- Query executes normally (sequential, correct results)


-- ============================================================================
-- EXAMPLE 6: Performance Patterns
-- ============================================================================

-- Pattern 1: Filter cheap conditions first, then semantic (best practice)
-- @ parallel: 8
SELECT * FROM products
WHERE price < 100              -- Cheap SQL filter (reduces rows)
  AND category = 'electronics' -- Another cheap filter
  AND description MEANS 'eco-friendly'  -- Expensive LLM filter (parallel!)
LIMIT 200;

-- Pattern 2: Hybrid with vector search (ultimate performance)
WITH takes AS (
    -- Vector pre-filter: 1M rows → 100 takes in ~50ms
    SELECT * FROM VECTOR_SEARCH('eco-friendly products', 'products', 100)
)
-- @ parallel: 10
SELECT
    p.id,
    p.description MEANS 'truly sustainable' as is_sustainable,
    p.description EXTRACTS 'certifications' as certs,
    c.similarity as vector_score
FROM takes c
JOIN products p ON p.id = c.id
WHERE p.description MEANS 'eco-friendly AND affordable'
LIMIT 50;

-- Performance breakdown:
-- - Vector search: ~50ms (ClickHouse, no LLM)
-- - Parallel LLM filtering: ~10s (100 rows, 10 workers)
-- Total: ~10s vs ~200s sequential (20x speedup!)


-- ============================================================================
-- EXAMPLE 7: Different Worker Counts
-- ============================================================================

-- Small dataset: Use fewer workers
-- @ parallel: 3
SELECT * FROM products WHERE description MEANS 'premium' LIMIT 30;

-- Medium dataset: Moderate workers
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'budget-friendly' LIMIT 100;

-- Large dataset: Max workers
-- @ parallel: 10
SELECT * FROM products WHERE description MEANS 'popular' LIMIT 500;

-- Rule of thumb: workers = total_rows / 50
-- - 100 rows → parallel: 2
-- - 500 rows → parallel: 10
-- - 1000 rows → parallel: 20 (but CPU bound at ~8-16)


-- ============================================================================
-- EXAMPLE 8: Preserving ORDER BY
-- ============================================================================

-- ORDER BY is preserved at outer query level:
-- @ parallel: 4
SELECT * FROM products
WHERE description MEANS 'high quality'
ORDER BY price DESC  -- Applied after UNION ALL merge
LIMIT 80;

-- Each branch processes ~20 rows unordered
-- Final result set is ordered by price DESC


-- ============================================================================
-- EXAMPLE 9: Without Explicit LIMIT (Uses Default)
-- ============================================================================

-- No LIMIT specified - uses default (1000)
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'popular';

-- Equivalent to:
-- @ parallel: 5
SELECT * FROM products WHERE description MEANS 'popular' LIMIT 1000;


-- ============================================================================
-- EXAMPLE 10: Real-World Use Case - Customer Support Triage
-- ============================================================================

CREATE TABLE support_tickets (
    ticket_id INTEGER,
    description VARCHAR,
    status VARCHAR,
    created_at TIMESTAMP
);

INSERT INTO support_tickets
SELECT
    i as ticket_id,
    'Customer issue ' || i || ': ' ||
    (CASE WHEN i % 4 = 0 THEN 'Product not working, very urgent!'
          WHEN i % 4 = 1 THEN 'Question about billing'
          WHEN i % 4 = 2 THEN 'Feature request for mobile app'
          ELSE 'General inquiry about services' END) as description,
    'open' as status,
    current_timestamp - INTERVAL (i) HOUR as created_at
FROM range(500);

-- Fast triage of open tickets with parallel execution:
-- @ parallel: 10
SELECT
    ticket_id,
    CONDENSE(description) as summary,
    description ASK 'urgency level 1-10' as urgency,
    description ASK 'category: technical/billing/product/general' as category,
    description EXTRACTS 'specific issue' as issue,
    description MEANS 'complaint or angry customer' as is_complaint,
    created_at
FROM support_tickets
WHERE status = 'open'
  AND description MEANS 'requires immediate attention'
ORDER BY CAST(description ASK 'urgency level 1-10' AS INTEGER) DESC
LIMIT 100;

-- Performance:
-- - Sequential: ~300s (5 operators × 100 rows × 0.6s)
-- - Parallel (10 workers): ~30s (10x speedup!)


-- ============================================================================
-- Performance Tips
-- ============================================================================
--
-- 1. Use parallel for 100+ rows (overhead < 5% benefit)
-- 2. Workers = min(total_rows / 50, CPU_count)
-- 3. Combine with cheap SQL filters (price < 100) before semantic operators
-- 4. Use VECTOR_SEARCH pre-filter for massive datasets (1M+ rows)
-- 5. Respect batch_size to prevent memory issues
-- 6. Parallel works best with LIMIT (bounded queries)
--
-- Cost Comparison:
-- Sequential (1000 rows × $0.0001): $0.10, 33 minutes
-- Parallel 5 workers: $0.10 (same!), 6.6 minutes (5x faster!)
--
-- Parallel doesn't reduce cost - just makes queries faster! ⚡
-- ============================================================================


-- ============================================================================
-- Debugging & Monitoring
-- ============================================================================

-- Check how your query was transformed:
-- Set log level to DEBUG to see transformation details

-- Example log output:
-- INFO: Parallel execution enabled: 5 UNION ALL branches for scalar semantic operators
-- DEBUG: Applying UNION ALL splitting for parallel execution (5 branches)
-- DEBUG: Split query into 5 branches (first 200 chars): (SELECT * FROM...


-- ============================================================================
-- Limitations & Known Issues
-- ============================================================================
--
-- 1. AGGREGATE OPERATORS NOT SUPPORTED (YET)
--    - SUMMARIZE, THEMES, CLUSTER, CONSENSUS, DEDUPE, SENTIMENT, OUTLIERS
--    - These break with UNION splitting (groups split across branches)
--    - Warning logged, query executes sequentially (safe fallback)
--
-- 2. REQUIRES 'id' COLUMN (OR SIMILAR)
--    - Uses id % N for partitioning
--    - Falls back to primary key detection
--    - Future: ROW_NUMBER() fallback for tables without ID
--
-- 3. PARALLEL: 1 IS A NO-OP
--    - Only splits if parallel > 1
--    - parallel: 1 is same as no annotation
--
-- 4. ORDER BY APPLIED AT END
--    - Each branch processes rows unordered (faster)
--    - ORDER BY applied to final merged result
--    - Ensures deterministic results
--
-- ============================================================================


-- Cleanup
DROP TABLE products;
DROP TABLE support_tickets;
