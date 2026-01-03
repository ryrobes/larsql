-- ============================================================================
-- EXTRACTS Operator Demo - Semantic Information Extraction
-- ============================================================================
-- The EXTRACTS operator pulls structured information from unstructured text.
-- It's like semantic grep - understanding meaning, not just patterns.
--
-- Created: 2026-01-02
-- Operator: {{ text }} EXTRACTS '{{ what }}'
-- Returns: VARCHAR (extracted info or NULL if not found)
-- ============================================================================

-- Setup: Create demo data
CREATE TABLE support_tickets (
    ticket_id INTEGER,
    subject VARCHAR,
    description VARCHAR,
    category VARCHAR
);

INSERT INTO support_tickets VALUES
    (1, 'Order Issue', 'Hi, I placed order #A12345 on Dec 15th but haven''t received it. My name is Sarah Johnson. Can you help?', 'shipping'),
    (2, 'Refund Request', 'The iPhone 15 Pro I bought for $999 is defective. I need a full refund ASAP. Order number is B67890.', 'returns'),
    (3, 'Product Question', 'Does the MacBook Air support dual 4K monitors? I''m considering buying one for $1,199.', 'pre-sales'),
    (4, 'Account Problem', 'I can''t login with my email john.smith@example.com. Please reset my password.', 'technical'),
    (5, 'Billing Inquiry', 'I was charged $49.99 on March 3rd but I cancelled my subscription. Transaction ID: TX-9876543.', 'billing');


-- ============================================================================
-- Use Case 1: Extract Key Entities from Support Tickets
-- ============================================================================
-- Pull customer names, order numbers, and prices from free-form text

SELECT
    ticket_id,
    subject,
    description EXTRACTS 'customer name' as customer,
    description EXTRACTS 'order number' as order_num,
    description EXTRACTS 'product mentioned' as product,
    description EXTRACTS 'price or amount' as amount
FROM support_tickets
ORDER BY ticket_id;

-- Expected Results:
-- ticket_id | subject          | customer        | order_num | product        | amount
-- ----------|------------------|-----------------|-----------|----------------|--------
-- 1         | Order Issue      | Sarah Johnson   | A12345    | NULL           | NULL
-- 2         | Refund Request   | NULL            | B67890    | iPhone 15 Pro  | $999
-- 3         | Product Question | NULL            | NULL      | MacBook Air    | $1,199
-- 4         | Account Problem  | NULL            | NULL      | NULL           | NULL
-- 5         | Billing Inquiry  | NULL            | NULL      | NULL           | $49.99


-- ============================================================================
-- Use Case 2: Filter by Extracted Information
-- ============================================================================
-- Find tickets that mention specific order numbers

SELECT
    ticket_id,
    subject,
    description EXTRACTS 'order number' as order_num
FROM support_tickets
WHERE description EXTRACTS 'order number' IS NOT NULL
ORDER BY ticket_id;

-- Expected: Returns only tickets 1, 2 (have order numbers)


-- ============================================================================
-- Use Case 3: Multi-Entity Extraction
-- ============================================================================
-- Extract multiple pieces of info in one query (efficient!)

SELECT
    ticket_id,
    category,
    description EXTRACTS 'date mentioned' as date_found,
    description EXTRACTS 'email address' as email,
    description EXTRACTS 'transaction or order ID' as reference_id
FROM support_tickets
WHERE category IN ('billing', 'technical', 'shipping')
ORDER BY ticket_id;


-- ============================================================================
-- Use Case 4: Classify Intent Based on Extracted Info
-- ============================================================================
-- Combine EXTRACTS with other semantic operators for powerful queries

SELECT
    ticket_id,
    subject,
    description EXTRACTS 'problem type' as issue,
    description EXTRACTS 'urgency indicator' as urgency,
    CASE
        WHEN description MEANS 'urgent or time-sensitive' THEN 'High'
        WHEN description MEANS 'question or inquiry' THEN 'Low'
        ELSE 'Medium'
    END as priority
FROM support_tickets
ORDER BY
    CASE priority
        WHEN 'High' THEN 1
        WHEN 'Medium' THEN 2
        ELSE 3
    END;


-- ============================================================================
-- Use Case 5: Product Review Analysis
-- ============================================================================

CREATE TABLE product_reviews (
    review_id INTEGER,
    product VARCHAR,
    review_text VARCHAR
);

INSERT INTO product_reviews VALUES
    (1, 'Laptop', 'Great laptop! Battery lasts 12 hours and the screen is crystal clear. Setup took 15 minutes.'),
    (2, 'Phone', 'Terrible phone. Crashed 3 times in the first week. Camera quality is mediocre at best.'),
    (3, 'Tablet', 'Love the 10-inch display and lightweight design (only 1.2 lbs). Worth every penny of the $499.'),
    (4, 'Headphones', 'Noise cancellation is excellent. Comfortable for 8+ hour flights. Battery died after 6 months though.');

-- Extract specific attributes mentioned in reviews
SELECT
    product,
    review_text EXTRACTS 'battery life mentioned' as battery,
    review_text EXTRACTS 'weight or size' as dimensions,
    review_text EXTRACTS 'price' as price,
    review_text EXTRACTS 'main complaint' as issue,
    review_text EXTRACTS 'standout feature' as highlight
FROM product_reviews
ORDER BY review_id;


-- ============================================================================
-- Use Case 6: Email/Message Parsing
-- ============================================================================

CREATE TABLE customer_emails (
    email_id INTEGER,
    body VARCHAR
);

INSERT INTO customer_emails VALUES
    (1, 'Meeting scheduled for March 15th at 2pm in Conference Room B. Please bring Q4 sales reports.'),
    (2, 'Your package will arrive on Friday, Jan 12th between 9am-5pm. Tracking: 1Z999AA1234567890'),
    (3, 'Invoice #INV-2024-001 for $2,450.00 is due by end of month. Payment via wire transfer preferred.'),
    (4, 'Call me at 555-123-4567 regarding the Johnson account. Available Mon-Fri 9-5 EST.');

-- Parse structured data from emails
SELECT
    email_id,
    body EXTRACTS 'date' as date_mentioned,
    body EXTRACTS 'time' as time_mentioned,
    body EXTRACTS 'location' as location,
    body EXTRACTS 'phone number' as phone,
    body EXTRACTS 'tracking number' as tracking,
    body EXTRACTS 'invoice or reference number' as invoice_num
FROM customer_emails
ORDER BY email_id;


-- ============================================================================
-- Use Case 7: Aggregate Extracted Data
-- ============================================================================
-- Combine extraction with aggregation for analytics

SELECT
    category,
    COUNT(*) as ticket_count,
    COUNT(description EXTRACTS 'order number') as orders_mentioned,
    COUNT(description EXTRACTS 'price or amount') as amounts_mentioned,
    COUNT(description EXTRACTS 'customer name') as names_provided
FROM support_tickets
GROUP BY category
ORDER BY ticket_count DESC;


-- ============================================================================
-- Use Case 8: Hybrid Extraction + LLM Reasoning
-- ============================================================================
-- Extract data, then filter semantically

SELECT
    ticket_id,
    subject,
    description EXTRACTS 'product mentioned' as product,
    description EXTRACTS 'price or amount' as price
FROM support_tickets
WHERE
    -- Extract product info
    description EXTRACTS 'product mentioned' IS NOT NULL
    -- AND use semantic filter
    AND description MEANS 'complaint or problem'
ORDER BY ticket_id;


-- ============================================================================
-- Performance Notes
-- ============================================================================
-- 1. EXTRACTS is cached - identical extraction requests return instantly
-- 2. Multiple EXTRACTS in one query = one row scan, multiple LLM calls
-- 3. Use WHERE with IS NOT NULL to filter before expensive operations
-- 4. Extraction is more expensive than MEANS/ABOUT (returns text vs boolean)
--
-- Cost Optimization:
-- - GOOD: SELECT x EXTRACTS 'y' FROM t LIMIT 100
-- - BAD:  SELECT x EXTRACTS 'y' FROM million_row_table (very expensive!)
--
-- Best Practice: Combine with traditional SQL filters
-- SELECT description EXTRACTS 'order' FROM tickets
-- WHERE created_at > '2024-01-01'  -- Cheap filter first!
--   AND category = 'shipping'       -- Further reduce rows
--   LIMIT 1000;                     -- Always limit!
-- ============================================================================


-- ============================================================================
-- Cleanup
-- ============================================================================
DROP TABLE support_tickets;
DROP TABLE product_reviews;
DROP TABLE customer_emails;
