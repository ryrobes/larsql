-- ============================================================================
-- CONDENSE / TLDR Operator Demo - Scalar Text Summarization
-- ============================================================================
-- CONDENSE and TLDR are scalar operators that summarize individual texts.
-- Unlike SUMMARIZE (aggregate), these work per-row on single texts.
--
-- Created: 2026-01-02
-- Operators: CONDENSE(text), TLDR(text), CONDENSE(text, 'focus')
-- Returns: VARCHAR (concise summary, typically 1-3 sentences)
-- ============================================================================

-- Setup: Create demo data with verbose content
CREATE TABLE articles (
    article_id INTEGER,
    title VARCHAR,
    full_text VARCHAR,
    word_count INTEGER
);

INSERT INTO articles VALUES
    (1, 'Climate Report',
     'Climate change continues to impact global ecosystems at an alarming rate. Scientists have observed rising temperatures causing ice caps to melt in polar regions, which destroys the natural habitat of polar bears and other arctic species. The situation is urgent and requires immediate action from world governments to reduce carbon emissions and transition to renewable energy sources. Without intervention, we risk catastrophic consequences for future generations.',
     68),

    (2, 'Product Review',
     'I bought this laptop three weeks ago and I have to say I am really impressed with the overall quality and performance. The battery life is absolutely incredible - I can work for 10-12 hours straight without needing to charge, which is perfect for my long workdays. The screen is bright and sharp with excellent color accuracy, making it ideal for my design work. Setup was surprisingly easy and took about 15 minutes total. The only downside I noticed is that it is a bit heavy compared to other models, but that is to be expected with a 17-inch display. Overall I highly recommend this for professionals who need power and portability.',
     125),

    (3, 'Meeting Notes',
     'Q4 planning session held on Monday. Team discussed revenue targets for next year ($10M goal), hiring plans (need to bring on 15 new engineers across frontend, backend, and DevOps teams), and product roadmap milestones (launch mobile app by March 15th, redesign dashboard by May). Sarah raised concerns about the aggressive timeline and whether we have enough resources. Mike suggested we consider a phased rollout approach to reduce risk. Action items assigned: 1) Engineering team to provide revised timeline estimate by Friday, 2) Marketing to draft initial launch communication plan, 3) Finance to model revenue impact of delayed launch scenarios.',
     115);


-- ============================================================================
-- Use Case 1: Basic Summarization (CONDENSE vs TLDR - Same Function!)
-- ============================================================================

-- Both CONDENSE and TLDR call the same cascade - use whichever you prefer!
SELECT
    title,
    word_count,
    CONDENSE(full_text) as summary_condense,
    TLDR(full_text) as summary_tldr
FROM articles
ORDER BY article_id;

-- Expected: Both columns should have similar brief summaries
-- CONDENSE: professional tone
-- TLDR: same output (they're aliases!)


-- ============================================================================
-- Use Case 2: Focused Summarization (With Hint Parameter)
-- ============================================================================

-- Guide the summary with a focus hint
SELECT
    title,
    CONDENSE(full_text, 'focus on action items and deadlines') as action_summary,
    CONDENSE(full_text, 'extract only technical details') as technical_summary,
    CONDENSE(full_text, 'summarize pros and cons') as pros_cons_summary
FROM articles
WHERE article_id = 2;  -- Product review


-- ============================================================================
-- Use Case 3: CONDENSE (scalar) vs SUMMARIZE (aggregate)
-- ============================================================================

CREATE TABLE customer_feedback (
    customer_id INTEGER,
    product VARCHAR,
    feedback_text VARCHAR
);

INSERT INTO customer_feedback VALUES
    (1, 'Laptop', 'Amazing laptop! Fast, reliable, great screen. Battery lasts all day.'),
    (2, 'Laptop', 'Good laptop but a bit pricey. Performance is solid though.'),
    (3, 'Laptop', 'Terrible experience. Broke after one week. Customer service unhelpful.'),
    (4, 'Phone', 'Love this phone! Camera is incredible, battery life is great.'),
    (5, 'Phone', 'Phone is okay. Nothing special but it works fine for basic use.');

-- Scalar: Summarize each individual review
SELECT
    customer_id,
    product,
    CONDENSE(feedback_text) as individual_summary
FROM customer_feedback
ORDER BY customer_id;

-- Aggregate: Summarize ALL reviews together per product
SELECT
    product,
    SUMMARIZE(feedback_text) as collective_summary
FROM customer_feedback
GROUP BY product;

-- Side-by-side comparison:
-- CONDENSE  : Per-row summarization (5 summaries, one per review)
-- SUMMARIZE : Per-group summarization (2 summaries, one per product)


-- ============================================================================
-- Use Case 4: Long Documents / Articles
-- ============================================================================

CREATE TABLE documents (
    doc_id INTEGER,
    doc_type VARCHAR,
    content VARCHAR
);

INSERT INTO documents VALUES
    (1, 'Email', 'Hi team, I wanted to follow up on yesterday''s discussion about the Q4 roadmap. We agreed to prioritize the mobile app launch but there are still some concerns about the timeline. Can we schedule a follow-up meeting next week to dive deeper into the technical requirements and resource allocation? Also, please review the attached budget proposal and send me your feedback by end of week. Thanks!'),

    (2, 'Contract', 'This agreement ("Agreement") is entered into as of January 1, 2024, by and between Company A ("Client") and Company B ("Vendor"). The Vendor agrees to provide software development services as outlined in Exhibit A. Payment terms are Net-30 upon invoice receipt. Either party may terminate with 30 days written notice. This Agreement shall be governed by the laws of the State of California.'),

    (3, 'Support Ticket', 'Customer John Smith (ID: 12345) called regarding order #ORD-99887 placed on Dec 15th. Item has not arrived despite promised delivery on Dec 20th. Customer is frustrated and requesting either immediate shipment with express delivery or full refund including shipping costs. Order total was $299.99. Customer mentioned he is a VIP member (since 2019) and expects better service.');

-- Condense different document types
SELECT
    doc_type,
    CONDENSE(content) as executive_summary,
    CONDENSE(content, 'extract key dates and deadlines') as timeline,
    CONDENSE(content, 'extract key people and roles') as stakeholders,
    CONDENSE(content, 'extract monetary amounts') as financial_info
FROM documents
ORDER BY doc_id;


-- ============================================================================
-- Use Case 5: Filtering by Summary Content
-- ============================================================================

-- Find articles where summary mentions specific topics
SELECT
    title,
    CONDENSE(full_text) as summary
FROM articles
WHERE CONDENSE(full_text) LIKE '%climate%'
   OR CONDENSE(full_text) LIKE '%urgent%';

-- Note: CONDENSE is cached, so using it in WHERE and SELECT is efficient!


-- ============================================================================
-- Use Case 6: Comparison with Other Operators
-- ============================================================================

CREATE TABLE product_reviews (
    review_id INTEGER,
    review_text VARCHAR
);

INSERT INTO product_reviews VALUES
    (1, 'This product exceeded all my expectations! The build quality is exceptional, performance is lightning fast, and the customer service team was incredibly helpful when I had a question about setup. The price is high but absolutely worth it for professionals who need reliability. I have recommended this to 5 colleagues already and they all love it too. Best purchase I have made this year without a doubt!'),

    (2, 'Worst product ever. Broke after 3 days. Support team was rude and unhelpful. Complete waste of money. Do NOT buy this garbage. Filing a complaint with consumer protection. Absolutely terrible experience from start to finish.');

-- Multi-dimensional analysis: CONDENSE + other semantic operators
SELECT
    review_id,

    -- Summarization
    CONDENSE(review_text) as summary,
    TLDR(review_text) as tldr,

    -- Extraction
    review_text EXTRACTS 'product quality mentioned' as quality,
    review_text EXTRACTS 'customer service experience' as service,

    -- Classification
    review_text ASK 'sentiment: positive/negative/neutral' as sentiment,

    -- Boolean filtering
    review_text MEANS 'positive experience' as is_positive,
    review_text MEANS 'complaint or problem' as is_complaint,

    -- Scoring
    review_text ABOUT 'product quality' as quality_score,
    review_text ABOUT 'customer service' as service_score

FROM product_reviews;


-- ============================================================================
-- Use Case 7: Condensing Code/Technical Content
-- ============================================================================

CREATE TABLE code_commits (
    commit_id INTEGER,
    commit_message VARCHAR,
    diff_text VARCHAR
);

INSERT INTO code_commits VALUES
    (1, 'Fix bug',
     'diff --git a/src/auth.py\n- def login(user, pass):\n-     return auth.check(user, pass)\n+ def login(user, password):\n+     if not user or not password:\n+         raise ValueError("Missing credentials")\n+     return auth.check(user, password)'),

    (2, 'Add feature',
     'diff --git a/src/api.py\n+ def export_data(format="json"):\n+     """Export user data in specified format (json/csv/xml)"""\n+     data = fetch_all_users()\n+     if format == "json":\n+         return json.dumps(data)\n+     elif format == "csv":\n+         return convert_to_csv(data)\n+     return data');

-- Summarize code changes
SELECT
    commit_id,
    commit_message,
    CONDENSE(diff_text) as change_summary,
    CONDENSE(diff_text, 'what problem does this solve?') as problem_solved,
    CONDENSE(diff_text, 'what are the technical implications?') as implications
FROM code_commits;


-- ============================================================================
-- Use Case 8: Windowed Summarization
-- ============================================================================

-- Per-row summary with context from neighboring rows
SELECT
    title,
    CONDENSE(full_text) as this_article_summary,
    CONDENSE(
        CONCAT(
            LAG(full_text, 1, '') OVER (ORDER BY article_id),
            ' | ',
            full_text,
            ' | ',
            LEAD(full_text, 1, '') OVER (ORDER BY article_id)
        ),
        'summarize the overall narrative across these connected articles'
    ) as contextual_summary
FROM articles;


-- ============================================================================
-- Use Case 9: Performance Comparison
-- ============================================================================

-- CONDENSE (scalar) can process any number of rows
-- SUMMARIZE (aggregate) best for groups, not individual rows

-- Efficient: Process 1000 individual reviews
SELECT review_id, CONDENSE(review_text) as summary
FROM reviews
LIMIT 1000;
-- Cost: 1000 × $0.0001 = $0.10 (if not cached)
-- Time: ~200ms per review = ~3-4 minutes total

-- Less efficient for this use case:
SELECT review_id,
       SUMMARIZE(ARRAY[review_text]) OVER (PARTITION BY review_id) as summary
FROM reviews
LIMIT 1000;
-- Same cost but awkward syntax (SUMMARIZE meant for aggregating multiple texts)


-- ============================================================================
-- Use Case 10: Hybrid Workflow
-- ============================================================================

-- Combine vector search pre-filter with scalar summarization
WITH candidates AS (
    SELECT * FROM VECTOR_SEARCH('climate change impacts', 'articles', 20)
)
SELECT
    a.title,
    a.word_count,
    CONDENSE(a.full_text) as summary,
    CONDENSE(a.full_text, 'focus on specific impacts mentioned') as impacts_summary,
    c.similarity as relevance_score
FROM candidates c
JOIN articles a ON a.article_id = c.id
WHERE a.word_count > 50  -- Only summarize longer articles
ORDER BY c.similarity DESC;


-- ============================================================================
-- Performance Tips
-- ============================================================================
-- 1. CONDENSE is cached - same text + same focus = instant retrieval
-- 2. Use LIMIT to cap LLM calls
-- 3. Filter before CONDENSE to reduce rows
-- 4. CONDENSE is cheaper than full text analysis (1-3 sentence output)
-- 5. Combine with VECTOR_SEARCH for massive cost savings:
--    - Vector pre-filter: 1M → 100 rows (fast, cheap)
--    - CONDENSE: 100 summaries (acceptable cost)
--    vs. CONDENSE on all 1M rows (very expensive!)
-- ============================================================================


-- ============================================================================
-- CONDENSE vs Other Operators
-- ============================================================================
-- When to use what:
--
-- CONDENSE(text)           : Summarize individual long text per row
-- SUMMARIZE(group)         : Summarize collection of texts together (aggregate)
-- text EXTRACTS 'x'        : Extract specific entity (returns fact, not summary)
-- text ASK 'summarize this': Generic (same as CONDENSE but less optimized)
-- text MEANS 'summary'     : Boolean check (not summarization)
--
-- Examples:
-- "Condense this review"          → CONDENSE(review)
-- "Summarize all reviews"         → SUMMARIZE(reviews) GROUP BY product
-- "Get customer name from review" → review EXTRACTS 'customer name'
-- "Is this a summary?"            → text MEANS 'summary or abstract'
-- ============================================================================


-- Cleanup
DROP TABLE articles;
DROP TABLE customer_feedback;
DROP TABLE documents;
DROP TABLE product_reviews;
DROP TABLE code_commits;
