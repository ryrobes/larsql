-- ============================================================================
-- RVBBIT SQL Syntax Examples (Cell 1: MAP)
-- ============================================================================
--
-- These examples demonstrate the new RVBBIT MAP syntax for row-wise processing.
-- Run these in DBeaver, psql, or via the Python client!
--
-- Connection: postgresql://rvbbit@localhost:15432/default
--

-- ============================================================================
-- Example 1: Basic Product Enrichment
-- ============================================================================

RVBBIT MAP 'skills/extract_brand.yaml'
USING (
  SELECT * FROM (VALUES
    ('Apple iPhone 15 Pro Max Space Black', 1199.99),
    ('Samsung Galaxy S24 Ultra Titanium Gray', 1299.99),
    ('Sony WH-1000XM5 Noise Canceling Headphones Black', 399.99)
  ) AS t(product_name, price)
);

-- Returns: Original columns + 'result' column with brand extraction


-- ============================================================================
-- Example 2: With AS Alias
-- ============================================================================

RVBBIT MAP 'skills/extract_brand.yaml' AS brand_info
USING (
  SELECT product_name FROM (VALUES
    ('Levis 501 Original Fit Jeans Blue'),
    ('Nike Air Max 97 Sneakers White'),
    ('KitchenAid Artisan Stand Mixer Red')
  ) AS t(product_name)
  LIMIT 10
);

-- Returns: product_name + 'brand_info' column (not 'result')


-- ============================================================================
-- Example 3: Auto-LIMIT Injection (Safety Feature)
-- ============================================================================

-- This query has NO explicit LIMIT
RVBBIT MAP 'skills/classify_sentiment.yaml'
USING (
  SELECT review_text FROM (VALUES
    ('This product is amazing! Best purchase ever.'),
    ('Terrible quality. Very disappointed.'),
    ('It works okay, nothing special.')
  ) AS t(review_text)
);

-- Auto-injects: LIMIT 1000 (default safety limit)


-- ============================================================================
-- Example 4: Complex Query with JOINs
-- ============================================================================

RVBBIT MAP 'cascades/customer_analysis.yaml' AS analysis
USING (
  SELECT
    c.customer_id,
    c.name,
    c.email,
    COUNT(o.order_id) as order_count,
    SUM(o.amount) as total_spent
  FROM (VALUES
    (1, 'Alice', 'alice@example.com'),
    (2, 'Bob', 'bob@example.com')
  ) AS c(customer_id, name, email)
  LEFT JOIN (VALUES
    (1, 1, 100.0),
    (2, 1, 250.0),
    (3, 2, 75.0)
  ) AS o(order_id, customer_id, amount)
    ON c.customer_id = o.customer_id
  GROUP BY c.customer_id, c.name, c.email
  LIMIT 50
);


-- ============================================================================
-- Example 5: WITH Options (Cache + Budget)
-- ============================================================================

RVBBIT MAP 'cascades/fraud_assess.yaml' AS fraud_risk
USING (
  SELECT charge_id, customer_id, amount, merchant
  FROM (VALUES
    (1, 'C123', 150000.00, 'Unusual Merchant LLC'),
    (2, 'C456', 5000.00, 'Normal Store Inc'),
    (3, 'C789', 500000.00, 'Suspicious Corp')
  ) AS t(charge_id, customer_id, amount, merchant)
  LIMIT 50
)
WITH (
  cache = true,
  budget_dollars = 2.50,
  key = 'charge_id'
);


-- ============================================================================
-- Example 6: Real-World Use Case - E-commerce Analytics
-- ============================================================================

RVBBIT MAP 'skills/extract_product_attributes.yaml' AS attributes
USING (
  WITH recent_products AS (
    SELECT
      product_id,
      product_name,
      description,
      price,
      category
    FROM (VALUES
      (1, 'Apple MacBook Pro 16" M3 Max', 'High-performance laptop', 3499.99, 'computers'),
      (2, 'Sony A7 IV Mirrorless Camera', 'Professional camera body', 2498.00, 'cameras'),
      (3, 'Bose QuietComfort 45 Headphones', 'Wireless noise cancellation', 329.00, 'audio')
    ) AS t(product_id, product_name, description, price, category)
  )
  SELECT * FROM recent_products
  LIMIT 100
);


-- ============================================================================
-- Example 7: Multi-Column Enrichment
-- ============================================================================

-- Note: This works because each row gets processed independently
RVBBIT MAP 'skills/enrich_contact.yaml' AS contact_data
USING (
  SELECT
    email,
    company_name,
    website
  FROM (VALUES
    ('contact@acme.com', 'Acme Industries', 'acme.com'),
    ('info@techstartup.io', 'Tech Startup LLC', 'techstartup.io')
  ) AS t(email, company_name, website)
  LIMIT 20
);


-- ============================================================================
-- Example 8: Filtering Before Enrichment
-- ============================================================================

RVBBIT MAP 'cascades/risk_assessment.yaml' AS risk
USING (
  SELECT * FROM (VALUES
    (1, 'High', 50000, 'NEW'),
    (2, 'Low', 1000, 'VERIFIED'),
    (3, 'Medium', 10000, 'PENDING')
  ) AS t(transaction_id, priority, amount, account_status)
  WHERE priority IN ('High', 'Medium')  -- Only process high/medium priority
  LIMIT 100
);


-- ============================================================================
-- Example 9: Text Analysis Pipeline
-- ============================================================================

RVBBIT MAP 'skills/analyze_text_quality.yaml' AS quality_score
USING (
  SELECT
    post_id,
    title,
    content,
    LENGTH(content) as content_length
  FROM (VALUES
    (1, 'Great Product Review', 'This is an amazing product that I highly recommend...', 100),
    (2, 'Short Post', 'ok', 2),
    (3, 'Detailed Analysis', 'After extensive testing over 3 months...', 500)
  ) AS t(post_id, title, content, content_length)
  WHERE content_length > 10  -- Skip very short posts
  LIMIT 200
);


-- ============================================================================
-- Example 10: PARALLEL Processing (NEW! Cell 2)
-- ============================================================================

-- Process 100 products with only 5 concurrent LLM calls
-- Perfect for rate-limited APIs!
RVBBIT MAP PARALLEL 5 'skills/extract_brand.yaml' AS brand
USING (
  SELECT * FROM (VALUES
    ('Apple iPhone 15'),
    ('Samsung Galaxy S24'),
    ('Sony WH-1000XM5'),
    ('Google Pixel 8'),
    ('OnePlus 12')
  ) AS t(product_name)
  LIMIT 100
);

-- High concurrency for fast/cheap models
RVBBIT MAP PARALLEL 50 'skills/classify_sentiment.yaml' AS sentiment
USING (
  SELECT review_text FROM reviews LIMIT 1000
);

-- Conservative for expensive models
RVBBIT MAP PARALLEL 3 'cascades/deep_analysis.yaml' AS analysis
USING (
  SELECT * FROM customers WHERE tier = 'enterprise' LIMIT 20
);


-- ============================================================================
-- Example 11: RVBBIT RUN - Batch Processing (NEW! Cell 3)
-- ============================================================================

-- Process entire dataset as ONE cascade (vs MAP = once per row)
RVBBIT RUN 'skills/analyze_batch.yaml'
USING (
  SELECT * FROM (VALUES
    ('Apple iPhone 15', 1199.99),
    ('Samsung Galaxy S24', 1299.99),
    ('Sony WH-1000XM5', 399.99),
    ('Google Pixel 8', 899.99),
    ('OnePlus 12', 799.99)
  ) AS t(product_name, price)
)
WITH (as_table = 'products_batch');

-- Returns: Single row with metadata
-- {
--   "status": "success",
--   "session_id": "batch-clever-fox-abc123",
--   "table_created": "products_batch",
--   "row_count": 5,
--   "outputs": {...}
-- }


-- ============================================================================
-- Example 12: RUN with Auto-Generated Table Name
-- ============================================================================

-- If you don't specify as_table, one is auto-generated
RVBBIT RUN 'skills/analyze_batch.yaml'
USING (
  SELECT * FROM (VALUES
    ('Product A', 100),
    ('Product B', 200)
  ) AS t(name, price)
);

-- Auto-generates table like: _rvbbit_batch_a3f2e1b9


-- ============================================================================
-- Notes on Current Limitations
-- ============================================================================

-- ✅ SUPPORTED:
-- - RVBBIT MAP (sequential, row-by-row)
-- - RVBBIT MAP PARALLEL <n> (syntax accepted, sequential for now)
-- - RVBBIT RUN (batch processing - cascade runs ONCE over dataset)
-- - AS alias
-- - WITH options (cache, budget_dollars, as_table)
-- - Auto-LIMIT injection
--
-- ❌ NOT YET SUPPORTED (coming in later cells):
-- - Real threading for MAP PARALLEL (Cell 2B)
-- - RVBBIT MAP BATCH <n> (chunked processing)
-- - RETURNING (...) clause (field extraction)
-- - RETURNING TABLE (multi-table outputs)
-- - Nested RVBBIT statements


-- ============================================================================
-- How to Run These Examples
-- ============================================================================

-- Option 1: DBeaver
-- 1. Connect to: postgresql://rvbbit@localhost:15432/default
-- 2. Copy/paste any example above
-- 3. Press Ctrl+Enter to execute

-- Option 2: psql
-- $ psql postgresql://rvbbit@localhost:15432/default
-- default=# <paste query>

-- Option 3: Python Client
-- from rvbbit.client import RVBBITClient
-- client = RVBBITClient('http://localhost:5001')
-- df = client.execute("<query>")
-- print(df)
