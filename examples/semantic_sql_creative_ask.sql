-- ============================================================================
-- ASK Operator - Creative & Mind-Blowing Use Cases
-- ============================================================================
-- Showcasing the ULTIMATE flexibility of the ASK meta-operator.
-- These examples demonstrate use cases that would be impossible with
-- specialized operators or traditional SQL.
-- ============================================================================

-- ============================================================================
-- SECTION 1: CREATIVE CONTENT GENERATION
-- ============================================================================

CREATE TABLE movie_reviews (
    review_id INTEGER,
    movie VARCHAR,
    review_text VARCHAR
);

INSERT INTO movie_reviews VALUES
    (1, 'The Matrix', 'Mind-blowing sci-fi action. Keanu Reeves is perfect as Neo.'),
    (2, 'Titanic', 'Epic romance and tragedy. Amazing cinematography but too long.'),
    (3, 'Inception', 'Complex plot about dreams. Christopher Nolan genius.');

-- Generate creative content from reviews
SELECT
    movie,
    review_text ASK 'write a tweet promoting this movie (max 280 chars)' as tweet,
    review_text ASK 'write a haiku about this movie' as haiku,
    review_text ASK 'if this was a candy, what flavor?' as flavor,
    review_text ASK 'describe this in emoji only' as emoji_summary,
    review_text ASK 'what Spotify playlist would match this movie?' as playlist
FROM movie_reviews;


-- ============================================================================
-- SECTION 2: TRANSLATION MADNESS
-- ============================================================================

CREATE TABLE announcements (
    id INTEGER,
    message VARCHAR
);

INSERT INTO announcements VALUES
    (1, 'Server maintenance scheduled for Saturday 3am-5am EST. Please save your work.');

-- Translate to multiple languages/formats in one query!
SELECT
    message,
    message ASK 'translate to Spanish' as spanish,
    message ASK 'translate to French' as french,
    message ASK 'translate to German' as german,
    message ASK 'translate to Pirate speak' as pirate,
    message ASK 'translate to Gen Z slang' as genz,
    message ASK 'translate to Shakespearean English' as shakespeare,
    message ASK 'translate to emoji and symbols only' as emoji,
    message ASK 'explain like I am 5 years old' as eli5
FROM announcements;


-- ============================================================================
-- SECTION 3: PERSONALITY & PSYCHOLOGY ANALYSIS
-- ============================================================================

CREATE TABLE user_comments (
    user_id INTEGER,
    username VARCHAR,
    comment VARCHAR
);

INSERT INTO user_comments VALUES
    (1, 'alice_92', 'I love this feature! Been waiting forever. You guys rock!'),
    (2, 'bob_coder', 'Technically impressive but the UX needs work. Performance is subpar.'),
    (3, 'charlie_x', 'Whatever. It works I guess. Not like anyone asked my opinion anyway.');

-- Psychoanalyze users from their comments
SELECT
    username,
    comment ASK 'Myers-Briggs personality type (4 letters)' as mbti,
    comment ASK 'estimated age range' as age_range,
    comment ASK 'communication style: formal/casual/aggressive/passive' as style,
    comment ASK 'technical expertise: novice/intermediate/expert' as expertise,
    comment ASK 'likely profession or background' as profession,
    comment ASK 'emotional state when writing this' as emotion
FROM user_comments;


-- ============================================================================
-- SECTION 4: BUSINESS INTELLIGENCE WIZARDRY
-- ============================================================================

CREATE TABLE customer_feedback (
    feedback_id INTEGER,
    text VARCHAR,
    days_since_purchase INTEGER
);

INSERT INTO customer_feedback VALUES
    (1, 'Loved the product but shipping took forever. Won''t buy again.', 45),
    (2, 'Great quality! Already recommended to 3 friends. Will buy more.', 10),
    (3, 'Meh. It''s okay but I expected more for the price.', 30);

-- Predict customer behavior
SELECT
    text,
    text ASK 'will this customer buy again? yes/no' as will_rebuy,
    text ASK 'churn risk percentage (0-100)' as churn_risk,
    text ASK 'customer lifetime value potential: low/medium/high' as ltv_potential,
    text ASK 'what would convert this customer to loyal advocate?' as conversion_strategy,
    text ASK 'net promoter score (0-10)' as nps_estimate
FROM customer_feedback;


-- ============================================================================
-- SECTION 5: META-PROGRAMMING (SQL ANALYZING SQL!)
-- ============================================================================

CREATE TABLE query_log (
    query_id INTEGER,
    sql_query VARCHAR,
    execution_time_ms INTEGER
);

INSERT INTO query_log VALUES
    (1, 'SELECT * FROM users WHERE active = 1', 45),
    (2, 'SELECT u.*, o.* FROM users u, orders o WHERE u.id = o.user_id', 8500),
    (3, 'SELECT COUNT(*) FROM products', 12);

-- SQL queries analyzing SQL queries!
SELECT
    sql_query,
    sql_query ASK 'is this query optimized? yes/no' as is_optimized,
    sql_query ASK 'what indexes would help?' as index_suggestions,
    sql_query ASK 'estimated result set size: small/medium/large' as estimated_size,
    sql_query ASK 'rewrite this query for better performance' as optimized_version,
    sql_query ASK 'what database features does this use?' as features_used
FROM query_log
WHERE execution_time_ms > 1000;


-- ============================================================================
-- SECTION 6: VISUAL/CREATIVE REIMAGINING
-- ============================================================================

-- Imagine product descriptions in different contexts
SELECT
    product,
    review_text ASK 'if this product was a person, describe their personality' as personality,
    review_text ASK 'if this product was a car, what make/model?' as as_car,
    review_text ASK 'if this was a video game, what genre?' as as_game,
    review_text ASK 'what song title captures this review?' as as_song,
    review_text ASK 'describe this review as a color' as as_color
FROM product_reviews
LIMIT 3;


-- ============================================================================
-- SECTION 7: COMPETITIVE INTELLIGENCE
-- ============================================================================

CREATE TABLE market_research (
    research_id INTEGER,
    finding VARCHAR
);

INSERT INTO market_research VALUES
    (1, 'Competitor A launched new feature X. Customers love it. We don''t have equivalent.'),
    (2, 'Our pricing is 20% higher than Competitor B but quality is better.'),
    (3, 'Industry moving toward AI integration. We are behind the curve.');

-- Extract strategic insights
SELECT
    finding,
    finding ASK 'strategic threat level: low/medium/high' as threat_level,
    finding ASK 'recommended response strategy' as strategy,
    finding ASK 'timeline urgency: immediate/quarterly/annual' as urgency,
    finding ASK 'required budget: small/medium/large' as budget_estimate,
    finding ASK 'who should own this? team name' as owner
FROM market_research
WHERE finding ASK 'strategic threat level: low/medium/high' IN ('high', 'medium')
ORDER BY
    CASE finding ASK 'timeline urgency: immediate/quarterly/annual'
        WHEN 'immediate' THEN 1
        WHEN 'quarterly' THEN 2
        ELSE 3
    END;


-- ============================================================================
-- SECTION 8: SOCIAL MEDIA ANALYSIS
-- ============================================================================

CREATE TABLE tweets (
    tweet_id INTEGER,
    text VARCHAR,
    likes INTEGER
);

INSERT INTO tweets VALUES
    (1, 'Just tried the new AI SQL thing. This is insane! 🤯 #semanticSQL #future', 156),
    (2, 'Another overhyped tech thing that nobody needs. Pass.', 12),
    (3, 'Interesting concept but execution needs work. Potential is there.', 43);

-- Deep social analysis
SELECT
    text,
    text ASK 'influencer tier: micro/mid/macro based on tone' as influencer_tier,
    text ASK 'viral potential: low/medium/high' as viral_potential,
    text ASK 'brand sentiment: positive/neutral/negative' as sentiment,
    text ASK 'engagement type: advocacy/criticism/observation' as engagement,
    text ASK 'demographic: tech-savvy/mainstream/skeptic' as demographic,
    text ASK 'should we respond? yes/no' as should_respond,
    text ASK 'suggested response strategy' as response_strategy
FROM tweets;


-- ============================================================================
-- SECTION 9: EDUCATIONAL CONTENT ANALYSIS
-- ============================================================================

CREATE TABLE student_essays (
    student_id INTEGER,
    essay TEXT
);

INSERT INTO student_essays VALUES
    (1, 'In this essay I will explore the impacts of climate change on polar bears. Rising temperatures cause ice melting which destroys their habitat. We must act now to prevent extinction.');

-- Automated essay grading
SELECT
    student_id,
    essay ASK 'grade this essay A-F' as grade,
    essay ASK 'writing quality: poor/fair/good/excellent' as writing_quality,
    essay ASK 'argument strength: weak/moderate/strong' as argument,
    essay ASK 'evidence quality: insufficient/adequate/strong' as evidence,
    essay ASK 'grammar and style: needs work/acceptable/good' as grammar,
    essay ASK 'originality: derivative/adequate/creative' as originality,
    essay ASK 'provide constructive feedback (2-3 sentences)' as feedback,
    essay ASK 'suggest 3 specific improvements' as improvements
FROM student_essays;


-- ============================================================================
-- SECTION 10: IMPOSSIBLE WITH TRADITIONAL SQL
-- ============================================================================

-- These queries would require external Python/AI services in any other system
-- With LARS ASK, they're pure SQL:

-- 1. Emotional journey mapping
SELECT
    long_review,
    long_review ASK 'describe the emotional arc: beginning → middle → end' as emotional_journey
FROM reviews WHERE LENGTH(review_text) > 500;

-- 2. Counterfactual reasoning
SELECT
    event_description,
    event_description ASK 'what if this had happened differently? describe alternate outcome' as counterfactual
FROM historical_events;

-- 3. Analogical reasoning
SELECT
    product_description,
    product_description ASK 'what is this analogous to in nature?' as nature_analogy,
    product_description ASK 'what historical invention is this similar to?' as historical_analogy
FROM products;

-- 4. Future prediction
SELECT
    trend_data,
    trend_data ASK 'project this trend 12 months forward' as future_projection,
    trend_data ASK 'what black swan event could disrupt this?' as risk_factor
FROM market_trends;

-- 5. Philosophical analysis
SELECT
    ethical_dilemma,
    ethical_dilemma ASK 'from a utilitarian perspective, what is the right choice?' as utilitarian,
    ethical_dilemma ASK 'from a deontological perspective, what is the right choice?' as deontological,
    ethical_dilemma ASK 'from a virtue ethics perspective, what is the right choice?' as virtue_ethics
FROM case_studies;


-- ============================================================================
-- SECTION 11: COMBINING MULTIPLE ASK OPERATORS
-- ============================================================================

-- The power multiplies when you chain ASK with ASK
SELECT
    original_text,
    original_text ASK 'translate to French' as french,
    (original_text ASK 'translate to French') ASK 'is this translation accurate?' as translation_quality,
    original_text ASK 'summarize in 10 words' as summary,
    (original_text ASK 'summarize in 10 words') ASK 'is this summary complete?' as summary_quality
FROM documents
LIMIT 5;


-- ============================================================================
-- SECTION 12: PROTOTYPING TO PRODUCTION WORKFLOW
-- ============================================================================

-- DAY 1: Prototype with ASK
SELECT review ASK 'does this mention shipping speed?' FROM reviews LIMIT 10;

-- DAY 2: Refine prompt
SELECT review ASK 'does this mention shipping speed? consider: delivery, arrival, shipping' FROM reviews LIMIT 100;

-- DAY 3: Test different phrasings
SELECT
    review ASK 'mentions shipping speed? yes/no' as v1,
    review ASK 'discusses delivery time? yes/no' as v2,
    review ASK 'talks about how fast it arrived? yes/no' as v3
FROM reviews LIMIT 50;

-- DAY 4: Pick best, create specialized operator
-- Create: cascades/semantic_sql/mentions_shipping.cascade.yaml
-- Production query: WHERE review MENTIONS_SHIPPING


-- ============================================================================
-- SECTION 13: THE ULTIMATE DEMO QUERY
-- ============================================================================

-- Everything at once: filtering, extraction, transformation, analysis
WITH recent_tickets AS (
    SELECT * FROM support_tickets
    WHERE created_at > NOW() - INTERVAL '1 day'
      AND description ASK 'is this urgent?' = 'yes'  -- ASK filter
    LIMIT 50  -- Keep it reasonable
)
SELECT
    ticket_id,
    description,

    -- Extraction
    description ASK 'extract customer name' as customer,
    description ASK 'extract order number' as order_num,

    -- Classification
    description ASK 'category: billing/technical/shipping/other' as category,
    description ASK 'sentiment: angry/frustrated/neutral' as sentiment,

    -- Prediction
    description ASK 'will this escalate? yes/no' as will_escalate,
    description ASK 'churn risk: low/medium/high' as churn_risk,

    -- Recommendation
    description ASK 'suggested resolution' as resolution,
    description ASK 'estimated resolution time' as eta,

    -- Creative
    description ASK 'write empathetic response' as draft_response,
    description ASK 'give this ticket a creative name' as ticket_name

FROM recent_tickets
ORDER BY
    CASE description ASK 'will this escalate? yes/no'
        WHEN 'yes' THEN 1
        ELSE 2
    END,
    CAST(description ASK 'urgency 1-10' AS INTEGER) DESC
LIMIT 10;


-- ============================================================================
-- WHY THIS IS REVOLUTIONARY
-- ============================================================================
--
-- With ASK, SQL becomes a natural language interface to your data.
-- You don't need to learn specialized operators or functions.
-- Just... ask.
--
-- Traditional SQL:
--   "I need to filter WHERE condition = value"
--   → Limited to exact matching
--
-- Semantic SQL with specialized operators:
--   "I need to filter WHERE column MEANS 'concept'"
--   → Limited to predefined operators
--
-- Semantic SQL with ASK:
--   "I need to filter WHERE column ASK 'literally anything' = expected"
--   → Limited only by imagination
--
-- This is SQL as it should be: human-friendly, infinitely flexible,
-- and powerful beyond measure.
--
-- ============================================================================


-- Cleanup
DROP TABLE movie_reviews;
DROP TABLE announcements;
DROP TABLE user_comments;
DROP TABLE customer_feedback;
DROP TABLE query_log;
DROP TABLE market_research;
DROP TABLE tweets;
DROP TABLE student_essays;
