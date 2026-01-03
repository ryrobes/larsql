-- ============================================================================
-- ASK Operator Demo - The Ultimate Meta-Operator
-- ============================================================================
-- ASK applies any arbitrary prompt to any SQL column. Total flexibility!
--
-- Instead of specialized operators (MEANS, EXTRACTS, ALIGNS), use ASK for
-- anything you can think of. Perfect for ad-hoc analysis and prototyping.
--
-- Created: 2026-01-02
-- Operator: {{ text }} ASK '{{ any_prompt }}'
-- Returns: VARCHAR (any response the LLM generates)
-- ============================================================================

-- Setup: Create demo data
CREATE TABLE product_reviews (
    review_id INTEGER,
    product VARCHAR,
    review_text VARCHAR,
    rating INTEGER
);

INSERT INTO product_reviews VALUES
    (1, 'Laptop', 'Great laptop! Battery lasts 12 hours. Highly recommend.', 5),
    (2, 'Phone', 'Terrible phone. Crashed 3 times this week. Returning it.', 1),
    (3, 'Tablet', 'Decent tablet for the price. Screen could be brighter.', 3),
    (4, 'Headphones', 'Amazing sound quality! Comfortable too. Worth every penny.', 5),
    (5, 'Laptop', 'Overpriced garbage. Slow and buggy. Do not buy!', 1);


-- ============================================================================
-- Use Case 1: Sentiment Analysis (replaces specialized operators)
-- ============================================================================

-- Instead of creating SENTIMENT operator, just ASK!
SELECT
    product,
    review_text ASK 'is this positive or negative?' as sentiment,
    review_text ASK 'rate sentiment 1-10' as sentiment_score,
    review_text ASK 'extract the main emotion' as emotion
FROM product_reviews
ORDER BY review_id;

-- Expected results show flexible sentiment analysis without specialized ops


-- ============================================================================
-- Use Case 2: Translation (any language!)
-- ============================================================================

SELECT
    review_text,
    review_text ASK 'translate to Spanish' as spanish,
    review_text ASK 'translate to French' as french,
    review_text ASK 'translate to emoji only' as emoji_version
FROM product_reviews
WHERE rating >= 4
LIMIT 3;

-- This would be impossible with a specialized TRANSLATE operator
-- (would need TRANSLATE_SPANISH, TRANSLATE_FRENCH, etc.)


-- ============================================================================
-- Use Case 3: Flexible Classification
-- ============================================================================

SELECT
    product,
    review_text ASK 'is this a complaint?' as is_complaint,
    review_text ASK 'what category: quality/price/performance/support' as issue_type,
    review_text ASK 'is this review helpful for buyers?' as is_helpful
FROM product_reviews
WHERE rating <= 2;


-- ============================================================================
-- Use Case 4: Content Transformation
-- ============================================================================

-- Rewrite content in different styles
SELECT
    review_text as original,
    review_text ASK 'rewrite this professionally' as professional,
    review_text ASK 'make this funny' as funny,
    review_text ASK 'write a haiku about this' as haiku
FROM product_reviews
WHERE review_id = 1;


-- ============================================================================
-- Use Case 5: Advanced Extraction (more flexible than EXTRACTS)
-- ============================================================================

CREATE TABLE support_tickets (
    ticket_id INTEGER,
    description VARCHAR
);

INSERT INTO support_tickets VALUES
    (1, 'Hi, I ordered product #A123 on Dec 15th but it never arrived. Called support twice.'),
    (2, 'The item cost $299 but I was charged $399. Need refund of $100 ASAP!'),
    (3, 'Received wrong item. Ordered blue shirt (SKU: BS-42) got red pants instead.');

-- Extract with context-aware prompts
SELECT
    ticket_id,
    description ASK 'what went wrong?' as problem,
    description ASK 'find product ID or SKU' as product_ref,
    description ASK 'find any dollar amounts' as amounts,
    description ASK 'how urgent is this? scale 1-5' as urgency,
    description ASK 'suggest resolution' as recommended_action
FROM support_tickets;


-- ============================================================================
-- Use Case 6: Code Analysis
-- ============================================================================

CREATE TABLE code_snippets (
    snippet_id INTEGER,
    language VARCHAR,
    code VARCHAR
);

INSERT INTO code_snippets VALUES
    (1, 'Python', 'def foo(x):\n    return x * 2'),
    (2, 'JavaScript', 'const bar = (x) => x.map(i => i * 2)'),
    (3, 'SQL', 'SELECT * FROM users WHERE active = 1');

-- Analyze code with arbitrary questions
SELECT
    snippet_id,
    language,
    code ASK 'what does this code do?' as explanation,
    code ASK 'find any bugs or issues' as bugs,
    code ASK 'rate code quality 1-10' as quality,
    code ASK 'suggest improvements' as improvements
FROM code_snippets;


-- ============================================================================
-- Use Case 7: Multi-Step Analysis in One Query
-- ============================================================================

-- Ask different questions about the same text
SELECT
    product,
    review_text ASK 'summarize in 5 words' as summary,
    review_text ASK 'who is the target audience?' as audience,
    review_text ASK 'what are the pros?' as pros,
    review_text ASK 'what are the cons?' as cons,
    review_text ASK 'would you recommend this? yes/no' as recommend
FROM product_reviews
WHERE rating IN (1, 5)  -- Extreme reviews
ORDER BY rating DESC;


-- ============================================================================
-- Use Case 8: Filtering with Custom Logic
-- ============================================================================

-- Filter based on arbitrary conditions
SELECT
    review_text,
    review_text ASK 'does this mention battery life?' as mentions_battery,
    review_text ASK 'is the reviewer technical or casual user?' as user_type
FROM product_reviews
WHERE review_text ASK 'does this mention battery life?' = 'yes';

-- Or even more complex:
SELECT
    ticket_id,
    description
FROM support_tickets
WHERE description ASK 'is this urgent?' = 'yes'
  AND description ASK 'is the customer angry?' = 'yes';


-- ============================================================================
-- Use Case 9: Competitive Analysis
-- ============================================================================

CREATE TABLE competitor_mentions (
    mention_id INTEGER,
    text VARCHAR
);

INSERT INTO competitor_mentions VALUES
    (1, 'Tried both ProductX and ProductY. ProductY is way better for price.'),
    (2, 'Switched from BrandA to BrandB because of better customer service.'),
    (3, 'CompanyC has similar features but costs 2x more.');

SELECT
    text,
    text ASK 'which products are mentioned?' as products,
    text ASK 'what are they being compared on?' as comparison_criteria,
    text ASK 'which product is favored?' as winner,
    text ASK 'why?' as reasoning
FROM competitor_mentions;


-- ============================================================================
-- Use Case 10: Combine ASK with Other Semantic Operators
-- ============================================================================

-- Hybrid: Use specialized operators + ASK for flexibility
SELECT
    review_text,
    review_text MEANS 'negative experience' as is_negative,  -- Specialized (fast)
    review_text ASK 'what specifically went wrong?' as issue  -- Flexible (slower)
FROM product_reviews
WHERE review_text MEANS 'negative experience'  -- Filter with fast operator
LIMIT 10;

-- Pre-filter with vector search, analyze with ASK
WITH candidates AS (
    SELECT * FROM VECTOR_SEARCH('battery complaints', 'product_reviews', 20)
)
SELECT
    p.review_text,
    p.review_text ASK 'what is the battery complaint?' as complaint,
    p.review_text ASK 'how severe? low/medium/high' as severity
FROM candidates c
JOIN product_reviews p ON p.review_id = c.id;


-- ============================================================================
-- Use Case 11: Creative / Unusual Prompts
-- ============================================================================

-- ASK can handle ANY prompt - get creative!
SELECT
    review_text,
    review_text ASK 'if this was a movie review, what rating?' as movie_rating,
    review_text ASK 'write a tweet about this' as tweet,
    review_text ASK 'what would the opposite review say?' as opposite,
    review_text ASK 'is the reviewer an early adopter or late majority?' as adopter_type,
    review_text ASK 'predict: will this reviewer buy again? yes/no' as will_rebuy
FROM product_reviews
WHERE rating = 5
LIMIT 2;


-- ============================================================================
-- Use Case 12: Prototyping Before Creating Specialized Operators
-- ============================================================================

-- When exploring data, use ASK to test different prompts
-- Once you find one that works well, create a dedicated operator

-- Prototyping phase:
SELECT
    review_text ASK 'is this spam?' as spam_v1,
    review_text ASK 'is this fake or bot-generated?' as spam_v2,
    review_text ASK 'does this seem authentic? yes/no' as spam_v3
FROM product_reviews
LIMIT 5;

-- After testing, you might create:
-- cascades/semantic_sql/is_authentic.cascade.yaml
-- with the best prompt from above


-- ============================================================================
-- Performance Notes
-- ============================================================================
-- ASK is very flexible but:
-- 1. Same cost as specialized operators (~$0.0001 per call)
-- 2. Cached like all semantic operators
-- 3. Can be slower than specialized ops (less optimized prompts)
-- 4. Response format varies (string output, not typed)
--
-- Best Practices:
-- ✅ Use ASK for ad-hoc analysis and prototyping
-- ✅ Use specialized operators (MEANS, EXTRACTS) for production queries
-- ✅ Cache ASK results for repeated queries
-- ✅ Combine with WHERE filters to reduce rows before ASK
--
-- Example: Good performance pattern
-- SELECT description ASK 'urgency?' FROM tickets
-- WHERE created_at > NOW() - INTERVAL '1 day'  -- Filter first
--   AND category = 'support'                    -- Reduce rows
--   LIMIT 100;                                  -- Cap ASK calls
-- ============================================================================


-- ============================================================================
-- Why ASK is Unique
-- ============================================================================
-- No other SQL system has this:
--
-- PostgresML:  ❌ No arbitrary prompt operator
-- pgvector:    ❌ No LLM integration at all
-- Supabase AI: ❌ No SQL operator syntax
-- Databricks:  ❌ Fixed AI functions only
--
-- RVBBIT ASK:  ✅ ANY prompt, ANY column, pure SQL
-- ============================================================================


-- ============================================================================
-- Cleanup
-- ============================================================================
DROP TABLE product_reviews;
DROP TABLE support_tickets;
DROP TABLE code_snippets;
DROP TABLE competitor_mentions;
