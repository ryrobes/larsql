-- SEMANTIC SQL TWEET ANALYSIS QUERIES
-- Use case: Industry evidence mining, competitive intelligence, narrative tracking
-- Dataset: Liked/tagged tweets with engagement metrics and categories

-- ============================================================================
-- 1. EVIDENCE MINING - Find tweets supporting specific claims
-- ============================================================================

-- Which tweets support our product thesis?
SELECT 
    author_name,
    author_username,
    text,
    like_count,
    retweet_count,
    created_at,
    url
FROM tweets
WHERE text IMPLIES 'SQL is becoming the interface for AI/LLM workflows'
  AND like_count > 100  -- Filter for influential tweets first (cheap!)
ORDER BY like_count DESC
LIMIT 20;

-- Find counterarguments to our positioning
SELECT 
    author_name,
    text,
    like_count + retweet_count as engagement,
    SENTIMENT(text) as tone
FROM tweets  
WHERE text CONTRADICTS 'SQL is a good interface for LLM applications'
  AND like_count > 50
ORDER BY engagement DESC;

-- ============================================================================
-- 2. INFLUENCER ANALYSIS - Who's saying what?
-- ============================================================================

-- Group influencers by semantic stance (not follower count!)
WITH influential_tweets AS (
    SELECT * FROM tweets
    WHERE like_count > 500  -- High engagement
      AND text ABOUT 'LLM applications or AI agents' > 0.6
)
SELECT 
    LLM_CASE text
        WHEN SEMANTIC 'optimistic about AI future' THEN 'AI Bulls'
        WHEN SEMANTIC 'cautious about AI risks' THEN 'AI Skeptics'
        WHEN SEMANTIC 'focused on practical applications' THEN 'AI Pragmatists'
        WHEN SEMANTIC 'critical of AI hype' THEN 'AI Critics'
        ELSE 'AI Neutral'
    END as camp,
    
    groupArray(DISTINCT author_name) as voices,
    COUNT(*) as tweet_count,
    SUM(like_count) as total_likes,
    CONSENSUS(text) as shared_viewpoint,
    THEMES(text, 3) as main_topics
FROM influential_tweets
GROUP BY camp
ORDER BY total_likes DESC;

-- ============================================================================
-- 3. NARRATIVE TRACKING - How are themes evolving?
-- ============================================================================

-- Weekly sentiment on "AI coding assistants"
SELECT 
    toStartOfWeek(created_at) as week,
    COUNT(*) as tweet_volume,
    SENTIMENT(text) as avg_sentiment,
    THEMES(text, 5) as evolving_themes,
    SUM(like_count) as total_engagement
FROM tweets
WHERE text ABOUT 'AI coding assistants or copilots' > 0.7
GROUP BY week
ORDER BY week DESC
LIMIT 12;

-- ============================================================================
-- 4. COMPETITIVE INTELLIGENCE - What are rivals saying?
-- ============================================================================

-- Compare messaging across companies
SELECT 
    company,
    THEMES(text, 5) as their_messaging,
    CONSENSUS(text) as their_position,
    SUMMARIZE(text) as narrative_summary,
    
    -- How does it relate to our positioning?
    SUM(CASE WHEN text CONTRADICTS 'SQL is the best AI interface' THEN 1 END) as conflicts,
    SUM(CASE WHEN text IMPLIES 'SQL is the best AI interface' THEN 1 END) as validations,
    
    AVG(like_count) as avg_engagement
FROM tweets
WHERE author_name ~ (SELECT name FROM competitor_accounts)  -- Fuzzy match!
  AND created_at > NOW() - INTERVAL '90 days'
GROUP BY company
ORDER BY avg_engagement DESC;

-- ============================================================================
-- 5. QUOTE TWEET ANALYSIS - Response patterns
-- ============================================================================

-- What claims get the most supportive quote tweets?
SELECT 
    quoted_tweet_text as original_claim,
    quoted_tweet_author_name as original_author,
    
    COUNT(*) as quote_count,
    SUM(CASE WHEN text IMPLIES quoted_tweet_text THEN 1 END) as agreements,
    SUM(CASE WHEN text CONTRADICTS quoted_tweet_text THEN 1 END) as disagreements,
    
    SENTIMENT(text) as quote_sentiment,
    SUMMARIZE(text) as quote_summary
FROM tweets
WHERE quoted_tweet_text IS NOT NULL
  AND quoted_tweet_text ABOUT 'AI or machine learning' > 0.7
GROUP BY quoted_tweet_text, quoted_tweet_author_name
HAVING quote_count >= 5
ORDER BY quote_count DESC
LIMIT 20;

-- ============================================================================
-- 6. VIRAL PATTERN DETECTION - What goes viral and why?
-- ============================================================================

-- Semantic clustering of viral tweets
SELECT 
    viral_cluster,
    COUNT(*) as tweets_in_cluster,
    AVG(like_count) as avg_likes,
    SUMMARIZE(text) as cluster_narrative,
    THEMES(text, 3) as key_topics
FROM (
    SELECT 
        text,
        like_count,
        CLUSTER(text, 8, 'by core message') as viral_cluster
    FROM tweets
    WHERE like_count > 1000  -- Viral threshold
)
GROUP BY viral_cluster
ORDER BY avg_likes DESC;

-- What makes a tweet go viral? (Find common patterns)
SELECT 
    CONSENSUS(text) as viral_formula,
    THEMES(text, 5) as viral_topics,
    AVG(like_count) as avg_likes,
    COUNT(*) as sample_size
FROM tweets
WHERE like_count > 5000
  AND text ABOUT 'AI or technology' > 0.6;

-- ============================================================================
-- 7. DEDUPLICATION - Same message, different words
-- ============================================================================

-- How many unique messages exist in our saved tweets?
SELECT 
    category,
    COUNT(*) as total_tweets,
    array_length(DEDUPE(text, 'same core message')) as unique_messages,
    -- Compression ratio
    CAST(array_length(DEDUPE(text)) AS FLOAT) / COUNT(*) * 100 as uniqueness_pct
FROM tweets
GROUP BY category
ORDER BY uniqueness_pct ASC;  -- Categories with most repetition

-- ============================================================================
-- 8. RESEARCH TRIAGE - Which tweets need deeper analysis?
-- ============================================================================

-- Find tweets that are interesting but contradict our understanding
SELECT 
    id,
    author_name,
    text,
    like_count,
    url,
    
    -- Why is it interesting?
    CASE 
        WHEN text CONTRADICTS 'our core thesis' THEN 'Challenges our position'
        WHEN text IMPLIES 'emerging threat' THEN 'Potential risk'
        WHEN like_count > 10000 THEN 'Viral - needs attention'
        ELSE 'Review'
    END as research_priority
    
FROM tweets
WHERE needs_deeper_research IS NULL  -- Not yet triaged
  AND (
      text ABOUT 'our product category' > 0.8
      OR text CONTRADICTS 'our positioning'
      OR like_count > 5000
  )
ORDER BY like_count DESC
LIMIT 50;

-- ============================================================================
-- 9. SEMANTIC JOIN - Connect dots across datasets
-- ============================================================================

-- Match our internal product features to industry demand signals
SELECT 
    features.feature_name,
    features.description as our_feature,
    
    COUNT(*) as matching_tweets,
    SUM(t.like_count) as demand_signal,
    SUMMARIZE(t.text) as what_people_want,
    
    AVG(features.priority_score) as current_priority
FROM product_features features
CROSS JOIN tweets t
WHERE t.text ~ features.description  -- Semantic entity match!
  AND t.created_at > NOW() - INTERVAL '30 days'
GROUP BY features.feature_name, features.description
ORDER BY demand_signal DESC;

-- ============================================================================
-- 10. OUTLIER DETECTION - Find unique/contrarian takes
-- ============================================================================

-- What are the weirdest/most contrarian opinions about AI?
SELECT 
    topic,
    OUTLIERS(text, 5, 'unusual or contrarian perspective') as hot_takes,
    CONSENSUS(text) as mainstream_view,
    COUNT(*) as sample_size
FROM tweets
WHERE category = 'AI/ML'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY topic;

-- ============================================================================
-- 11. RELEVANCE RANKING - Sort by semantic match
-- ============================================================================

-- Most relevant tweets for a specific thesis
SELECT 
    author_name,
    text,
    like_count,
    text ABOUT 'SQL will become primary AI interface' as relevance_score
FROM tweets
WHERE text ABOUT 'SQL or database or data' > 0.5
ORDER BY text RELEVANCE TO 'SQL will become primary AI interface'
LIMIT 30;

-- ============================================================================
-- 12. HYBRID: Vector Search + Semantic Filtering
-- ============================================================================

-- Stage 1: Fast vector search (10,000 tweets → 200 candidates in 50ms)
WITH candidates AS (
    SELECT * FROM VECTOR_SEARCH(
        'evidence that SQL is good for AI workflows',
        'tweets',
        200
    )
    WHERE similarity > 0.7
)
-- Stage 2: LLM semantic filtering (200 → 20 in 2 seconds)
SELECT
    t.author_name,
    t.text,
    c.similarity as vector_match,
    t.like_count + t.retweet_count as engagement,
    t.url
FROM candidates c
JOIN tweets t ON t.id = c.id
WHERE
    t.like_count > 50                           -- Cheap filter
    AND t.text IMPLIES 'SQL is useful for AI'   -- LLM reasoning
    AND t.text NOT MEANS 'sarcasm or criticism' -- Negative filter
ORDER BY c.similarity DESC, engagement DESC
LIMIT 20;

-- Cost: ~$0.01 (vs $50 for pure LLM on 10K tweets!)

-- ============================================================================
-- 13. CATEGORY VALIDATION - Check if auto-categorization is accurate
-- ============================================================================

-- Which tweets are miscategorized?
SELECT 
    id,
    category,
    category_confidence,
    text,
    
    -- Re-classify semantically
    LLM_CASE text
        WHEN SEMANTIC 'industry news or announcements' THEN 'Industry News'
        WHEN SEMANTIC 'technical tutorial or how-to' THEN 'Tutorial'
        WHEN SEMANTIC 'opinion or hot take' THEN 'Opinion'
        WHEN SEMANTIC 'product launch or release' THEN 'Product'
        ELSE 'Other'
    END as semantic_category,
    
    CASE WHEN category != semantic_category THEN 'MISMATCH' END as validation_status
FROM tweets
WHERE category_confidence < 0.7  -- Low confidence
LIMIT 100;

-- ============================================================================
-- 14. TEMPORAL SENTIMENT SHIFTS - Detect narrative changes
-- ============================================================================

-- How has sentiment about "open source AI" changed month-over-month?
SELECT 
    toStartOfMonth(created_at) as month,
    COUNT(*) as tweets,
    SENTIMENT(text) as avg_sentiment,
    THEMES(text, 3) as top_themes,
    
    -- Month-over-month change
    SENTIMENT(text) - lag(SENTIMENT(text)) OVER (ORDER BY month) as sentiment_shift
FROM tweets
WHERE text ABOUT 'open source AI models' > 0.7
GROUP BY month
ORDER BY month DESC;

-- ============================================================================
-- 15. AUTHOR SEMANTIC CLUSTERING - Group by viewpoint, not follower count
-- ============================================================================

-- Cluster authors by semantic similarity of their tweets
WITH author_corpus AS (
    SELECT 
        author_username,
        author_name,
        SUMMARIZE(text) as overall_message,
        SUM(like_count) as total_engagement
    FROM tweets
    GROUP BY author_username, author_name
    HAVING COUNT(*) >= 5  -- Authors with enough tweets
)
SELECT 
    opinion_cluster,
    groupArray(author_name) as authors_in_cluster,
    COUNT(*) as cluster_size,
    SUM(total_engagement) as cluster_reach,
    CONSENSUS(overall_message) as cluster_viewpoint
FROM (
    SELECT 
        author_name,
        overall_message,
        total_engagement,
        CLUSTER(overall_message, 6, 'by opinion on AI industry') as opinion_cluster
    FROM author_corpus
)
GROUP BY opinion_cluster
ORDER BY cluster_reach DESC;

-- ============================================================================
-- 16. QUOTED TWEET NARRATIVE ANALYSIS
-- ============================================================================

-- What claims get quoted most? What's the response sentiment?
SELECT 
    quoted_tweet_text as viral_claim,
    quoted_tweet_author_name as originator,
    
    COUNT(*) as times_quoted,
    AVG(like_count) as avg_quote_engagement,
    
    SENTIMENT(text) as quote_tweet_sentiment,
    THEMES(text, 3) as response_themes,
    
    -- Classify response type
    SUM(CASE WHEN text IMPLIES quoted_tweet_text THEN 1 END) as amplifications,
    SUM(CASE WHEN text CONTRADICTS quoted_tweet_text THEN 1 END) as challenges,
    
    SUMMARIZE(text) as response_summary
FROM tweets
WHERE quoted_tweet_text IS NOT NULL
  AND quoted_tweet_like_count > 1000  -- Viral original tweets
GROUP BY quoted_tweet_text, quoted_tweet_author_name
HAVING times_quoted >= 3
ORDER BY times_quoted DESC
LIMIT 20;

-- ============================================================================
-- 17. DEEP RESEARCH QUEUE - Smart triage using multiple semantic signals
-- ============================================================================

-- Which tweets deserve deep research based on semantic signals?
WITH scored_tweets AS (
    SELECT 
        *,
        -- Multi-factor relevance scoring
        (like_count::FLOAT / 1000) * 0.3 +                                    -- Engagement weight
        (text ABOUT 'our product category' * 100) * 0.4 +                     -- Relevance weight
        (CASE WHEN text CONTRADICTS 'our assumptions' THEN 50 ELSE 0 END) +   -- Contradiction bonus
        (CASE WHEN text IMPLIES 'emerging trend' THEN 30 ELSE 0 END)          -- Trend bonus
        as research_score
    FROM tweets
    WHERE needs_deeper_research = 0
      AND created_at > NOW() - INTERVAL '14 days'
)
SELECT 
    author_name,
    text,
    research_score,
    like_count,
    
    -- Why should we research this?
    CONCAT_WS(', ',
        CASE WHEN text CONTRADICTS 'our thesis' THEN 'Challenges core thesis' END,
        CASE WHEN like_count > 10000 THEN 'Highly viral' END,
        CASE WHEN text IMPLIES 'market shift' THEN 'Signals change' END
    ) as research_reasons,
    
    url
FROM scored_tweets
WHERE research_score > 30
ORDER BY research_score DESC
LIMIT 50;

-- ============================================================================
-- 18. CATEGORY REFINEMENT - Find miscategorized tweets
-- ============================================================================

-- Tweets that don't semantically match their assigned category
SELECT 
    id,
    category,
    category_confidence,
    text,
    author_name,
    
    -- Semantic validation
    CASE 
        WHEN category = 'AI/ML' AND text NOT ABOUT 'AI or machine learning' > 0.7 THEN 'Wrong category'
        WHEN category = 'Industry News' AND text NOT ABOUT 'news or announcement' > 0.7 THEN 'Wrong category'  
        WHEN category = 'Tutorial' AND text NOT ABOUT 'how-to or tutorial' > 0.7 THEN 'Wrong category'
        ELSE 'OK'
    END as validation,
    
    -- Suggest better category
    LLM_CASE text
        WHEN SEMANTIC 'breaking news or announcement' THEN 'Industry News'
        WHEN SEMANTIC 'tutorial or how-to guide' THEN 'Tutorial'
        WHEN SEMANTIC 'opinion or commentary' THEN 'Opinion'
        WHEN SEMANTIC 'product or tool release' THEN 'Product'
        ELSE category
    END as suggested_category
    
FROM tweets
WHERE category_confidence < 0.8  -- Low confidence auto-categorization
  AND validation = 'Wrong category'
LIMIT 100;

-- ============================================================================
-- 19. ENGAGEMENT PREDICTION - What makes tweets viral?
-- ============================================================================

-- Find semantic patterns in highly-engaged tweets
SELECT 
    engagement_tier,
    COUNT(*) as tweet_count,
    
    THEMES(text, 5) as common_themes,
    CONSENSUS(text) as viral_formula,
    
    AVG(LENGTH(text)) as avg_length,
    AVG(like_count) as avg_likes,
    AVG(retweet_count) as avg_retweets
FROM (
    SELECT 
        text,
        like_count,
        retweet_count,
        CASE 
            WHEN like_count > 10000 THEN 'Mega Viral (10K+)'
            WHEN like_count > 1000 THEN 'Viral (1K-10K)'
            WHEN like_count > 100 THEN 'Popular (100-1K)'
            ELSE 'Normal (<100)'
        END as engagement_tier
    FROM tweets
    WHERE category = 'AI/ML'
)
GROUP BY engagement_tier
ORDER BY avg_likes DESC;

-- ============================================================================
-- 20. AUTHOR CREDIBILITY - Dedupe authors by semantic similarity
-- ============================================================================

-- Group authors who tweet about the same things (consolidate alts/duplicates)
SELECT 
    author_cluster,
    groupArray(DISTINCT author_username) as usernames,
    groupArray(DISTINCT author_name) as names,
    
    COUNT(*) as total_tweets,
    SUM(like_count) as total_engagement,
    
    SUMMARIZE(text) as what_they_discuss,
    THEMES(text, 3) as main_topics
FROM (
    SELECT 
        author_username,
        author_name,
        text,
        like_count,
        CLUSTER(author_username || ' ' || text, 10, 'by author identity and content') as author_cluster
    FROM tweets
)
GROUP BY author_cluster
HAVING COUNT(DISTINCT author_username) > 1  -- Only clusters with multiple usernames
ORDER BY total_engagement DESC;

-- ============================================================================
-- 21. HYBRID SEARCH - The Killer App (10,000x cost reduction)
-- ============================================================================

-- Find evidence for "SQL is becoming important for AI workflows"
-- Stage 1: Vector search on 100K tweets → 500 candidates in 50ms (no LLM!)
WITH vector_candidates AS (
    SELECT * FROM VECTOR_SEARCH(
        'SQL is important for AI and LLM workflows',
        'tweets',
        500
    )
    WHERE similarity > 0.65
)
-- Stage 2: LLM semantic filtering on 500 tweets → 20 results in 3 seconds
SELECT
    t.author_name,
    t.text,
    c.similarity as vector_score,
    t.like_count,
    t.retweet_count,
    t.created_at,
    t.url
FROM vector_candidates c
JOIN tweets t ON t.id = c.id
WHERE
    -- Cheap SQL filters first
    t.like_count > 50
    AND t.created_at > NOW() - INTERVAL '60 days'
    
    -- Then expensive LLM filters
    AND t.text IMPLIES 'SQL is valuable for AI/LLM applications'
    AND t.text NOT MEANS 'sarcasm or irony'
    AND t.text ABOUT 'data workflows or data engineering' > 0.6
    
ORDER BY c.similarity DESC, t.like_count DESC
LIMIT 20;

-- Cost: $0.02 (500 LLM calls)
-- vs pure LLM: $200 (100K LLM calls)
-- Speedup: 10,000x! 🚀

-- ============================================================================
-- 22. TEMPORAL CONTRADICTION TRACKING
-- ============================================================================

-- Has an author contradicted themselves over time?
SELECT 
    t1.author_name,
    t1.created_at as earlier_tweet_date,
    t2.created_at as later_tweet_date,
    
    t1.text as earlier_position,
    t2.text as later_position,
    
    t1.url as earlier_url,
    t2.url as later_url
FROM tweets t1
JOIN tweets t2 ON t1.author_id = t2.author_id
WHERE t1.created_at < t2.created_at
  AND t1.text CONTRADICTS t2.text
  AND t1.text ABOUT 'AI or LLMs' > 0.7
  AND t2.text ABOUT 'AI or LLMs' > 0.7
  AND DATEDIFF('day', t1.created_at, t2.created_at) >= 30  -- At least 30 days apart
ORDER BY t1.like_count DESC
LIMIT 20;

-- ============================================================================
-- 23. COMPREHENSIVE EVIDENCE DASHBOARD
-- ============================================================================

-- Single query for complete industry sentiment analysis
SELECT 
    -- Time dimension
    toStartOfMonth(created_at) as month,
    
    -- Engagement metrics
    COUNT(*) as tweet_volume,
    SUM(like_count) as total_likes,
    SUM(retweet_count) as total_retweets,
    
    -- Semantic analysis
    SENTIMENT(text) as industry_sentiment,
    THEMES(text, 5) as trending_topics,
    CONSENSUS(text) as industry_consensus,
    
    -- Evidence breakdown
    SUM(CASE WHEN text IMPLIES 'SQL important for AI' THEN 1 END) as supporting_evidence,
    SUM(CASE WHEN text CONTRADICTS 'SQL important for AI' THEN 1 END) as contradicting_evidence,
    
    -- Key voices
    groupArray(DISTINCT author_name) as key_authors,
    
    -- Outliers (contrarian takes)
    OUTLIERS(text, 3, 'contrarian or unusual') as hot_takes
    
FROM tweets
WHERE text ABOUT 'SQL or databases or data infrastructure' > 0.6
  AND like_count > 20  -- Filter noise
GROUP BY month
ORDER BY month DESC
LIMIT 12;

-- This ONE query gives you:
-- - Temporal trends
-- - Sentiment shifts
-- - Topic evolution
-- - Evidence for/against your thesis
-- - Key influencers
-- - Outlier opinions
-- All in ~10 seconds, cached for instant re-run!

