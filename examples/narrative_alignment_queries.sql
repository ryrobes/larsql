-- ALIGNS OPERATOR - Narrative Alignment Analysis
-- Score how well tweets align with your product narrative/thesis
-- Returns 0.0 (contradicts) to 1.0 (perfect alignment)

-- ============================================================================
-- 1. BASIC ALIGNMENT FILTERING
-- ============================================================================

-- Find tweets that align with your product thesis
SELECT 
    author_name,
    text,
    text ALIGNS 'SQL is becoming the primary interface for AI workflows' as alignment_score,
    like_count,
    url
FROM tweets
WHERE text ALIGNS 'SQL is becoming the primary interface for AI workflows' > 0.7
ORDER BY alignment_score DESC, like_count DESC
LIMIT 20;

-- ============================================================================
-- 2. MULTI-NARRATIVE COMPARISON
-- ============================================================================

-- How do tweets align with different narratives?
SELECT 
    author_name,
    text,
    
    -- Score against multiple narratives
    text ALIGNS 'SQL is great for AI' as sql_narrative_score,
    text ALIGNS 'Python is better than SQL' as python_narrative_score,
    text ALIGNS 'NoSQL databases are the future' as nosql_narrative_score,
    
    -- Winner takes all
    CASE 
        WHEN text ALIGNS 'SQL is great for AI' > GREATEST(
            text ALIGNS 'Python is better than SQL',
            text ALIGNS 'NoSQL databases are the future'
        ) THEN 'Pro-SQL'
        WHEN text ALIGNS 'Python is better than SQL' > text ALIGNS 'NoSQL databases are the future' THEN 'Pro-Python'
        ELSE 'Pro-NoSQL'
    END as narrative_winner,
    
    like_count
FROM tweets
WHERE text ABOUT 'databases or data tools' > 0.6
LIMIT 20;

-- ============================================================================
-- 3. EVIDENCE STRENGTH BY INFLUENCER
-- ============================================================================

-- Which influencers align most with your narrative?
SELECT 
    author_name,
    COUNT(*) as tweet_count,
    AVG(text ALIGNS 'SQL interfaces are the future of AI') as avg_alignment,
    SUM(like_count) as total_reach,
    
    -- Categorize alignment strength
    CASE 
        WHEN AVG(text ALIGNS 'SQL interfaces are the future of AI') > 0.8 THEN 'Strong Advocate'
        WHEN AVG(text ALIGNS 'SQL interfaces are the future of AI') > 0.6 THEN 'Supporter'
        WHEN AVG(text ALIGNS 'SQL interfaces are the future of AI') > 0.4 THEN 'Neutral'
        WHEN AVG(text ALIGNS 'SQL interfaces are the future of AI') > 0.2 THEN 'Skeptic'
        ELSE 'Opponent'
    END as stance
FROM tweets
WHERE like_count > 100  -- Influential tweets only
GROUP BY author_name
HAVING COUNT(*) >= 3  -- Regular tweeters
ORDER BY avg_alignment DESC, total_reach DESC
LIMIT 30;

-- ============================================================================
-- 4. TEMPORAL NARRATIVE SHIFT DETECTION
-- ============================================================================

-- Is the narrative gaining or losing support over time?
SELECT 
    toStartOfMonth(created_at) as month,
    COUNT(*) as tweets,
    AVG(text ALIGNS 'AI tools need better data infrastructure') as avg_alignment,
    
    -- Month-over-month change
    AVG(text ALIGNS 'AI tools need better data infrastructure') - 
        LAG(AVG(text ALIGNS 'AI tools need better data infrastructure')) 
        OVER (ORDER BY month) as alignment_shift,
    
    SUM(like_count) as engagement
FROM tweets
WHERE text ABOUT 'AI tools or infrastructure' > 0.5
GROUP BY month
ORDER BY month DESC
LIMIT 12;

-- ============================================================================
-- 5. QUOTED TWEET ALIGNMENT (Do responses agree?)
-- ============================================================================

-- When people quote tweets, do they align with the original?
SELECT 
    quoted_tweet_author_name as original_author,
    quoted_tweet_text,
    
    COUNT(*) as quote_count,
    AVG(text ALIGNS quoted_tweet_text) as avg_quote_alignment,
    
    -- Classify response type
    SUM(CASE WHEN text ALIGNS quoted_tweet_text > 0.7 THEN 1 END) as supportive_quotes,
    SUM(CASE WHEN text ALIGNS quoted_tweet_text < 0.3 THEN 1 END) as critical_quotes,
    
    SUM(like_count) as total_engagement
FROM tweets
WHERE quoted_tweet_text IS NOT NULL
  AND quoted_tweet_like_count > 1000  -- Viral originals
GROUP BY quoted_tweet_author_name, quoted_tweet_text
HAVING quote_count >= 5
ORDER BY total_engagement DESC;

-- ============================================================================
-- 6. COMPETITIVE NARRATIVE ANALYSIS
-- ============================================================================

-- How do competitor narratives compare to ours?
WITH narratives AS (
    SELECT 'Databricks' as company, 'Lakehouse architecture is the future' as their_narrative
    UNION ALL
    SELECT 'Snowflake', 'Data cloud enables AI at scale'
    UNION ALL
    SELECT 'Our Product', 'SQL is the best interface for AI workflows'
)
SELECT 
    n.company,
    n.their_narrative,
    
    -- Industry alignment with each narrative
    AVG(t.text ALIGNS n.their_narrative) as industry_alignment,
    COUNT(*) as supporting_tweets,
    SUM(t.like_count) as narrative_reach,
    
    -- Find strongest proponents
    groupArray(t.author_name) as top_voices
FROM narratives n
CROSS JOIN tweets t
WHERE t.text ABOUT n.their_narrative > 0.5
  AND t.like_count > 50
GROUP BY n.company, n.their_narrative
ORDER BY industry_alignment DESC;

-- ============================================================================
-- 7. MULTI-CRITERIA NARRATIVE SCORING
-- ============================================================================

-- Score tweets against multiple aspects of your positioning
SELECT 
    author_name,
    text,
    
    -- Different narrative dimensions
    text ALIGNS 'SQL is powerful and flexible' as power_score,
    text ALIGNS 'SQL is accessible to non-developers' as accessibility_score,
    text ALIGNS 'SQL integrates well with AI/LLM tools' as integration_score,
    
    -- Combined alignment (average)
    (
        text ALIGNS 'SQL is powerful and flexible' +
        text ALIGNS 'SQL is accessible to non-developers' +
        text ALIGNS 'SQL integrates well with AI/LLM tools'
    ) / 3.0 as overall_alignment,
    
    like_count
FROM tweets
WHERE text ABOUT 'SQL or databases' > 0.6
  AND overall_alignment > 0.6
ORDER BY overall_alignment DESC, like_count DESC
LIMIT 20;

-- ============================================================================
-- 8. HYBRID: Vector Search + Narrative Alignment
-- ============================================================================

-- Fast vector search, then deep narrative analysis
WITH candidates AS (
    SELECT * FROM VECTOR_SEARCH(
        'SQL and AI integration',
        'tweets',
        300
    )
    WHERE similarity > 0.6
)
SELECT
    t.author_name,
    t.text,
    c.similarity as vector_match,
    
    t.text ALIGNS 'SQL is the future of AI workflows' as narrative_alignment,
    
    -- Combined score (vector similarity + narrative alignment)
    (c.similarity + t.text ALIGNS 'SQL is the future of AI workflows') / 2.0 as combined_score,
    
    t.like_count,
    t.url
FROM candidates c
JOIN tweets t ON t.id = c.id
WHERE t.text ALIGNS 'SQL is the future of AI workflows' > 0.65
ORDER BY combined_score DESC
LIMIT 20;

-- ============================================================================
-- 9. ALIGNMENT vs ENGAGEMENT (What resonates?)
-- ============================================================================

-- Do aligned tweets get more engagement?
SELECT 
    CASE 
        WHEN text ALIGNS 'our narrative' > 0.8 THEN 'Strongly Aligned (0.8-1.0)'
        WHEN text ALIGNS 'our narrative' > 0.6 THEN 'Aligned (0.6-0.8)'
        WHEN text ALIGNS 'our narrative' > 0.4 THEN 'Neutral (0.4-0.6)'
        WHEN text ALIGNS 'our narrative' > 0.2 THEN 'Opposed (0.2-0.4)'
        ELSE 'Strongly Opposed (0.0-0.2)'
    END as alignment_tier,
    
    COUNT(*) as tweet_count,
    AVG(like_count) as avg_likes,
    AVG(retweet_count) as avg_retweets,
    MAX(like_count) as max_likes
FROM tweets
WHERE category = 'AI/ML'
GROUP BY alignment_tier
ORDER BY avg_likes DESC;

-- ============================================================================
-- 10. COMPREHENSIVE NARRATIVE DASHBOARD
-- ============================================================================

-- Complete analysis of how the industry aligns with your narrative
WITH narrative_analysis AS (
    SELECT 
        *,
        text ALIGNS 'SQL is becoming essential for AI workflows' as alignment_score
    FROM tweets
    WHERE text ABOUT 'SQL or data tools or AI' > 0.5
      AND created_at > NOW() - INTERVAL '90 days'
)
SELECT 
    -- Time period
    toStartOfMonth(created_at) as month,
    
    -- Volume
    COUNT(*) as total_tweets,
    
    -- Alignment metrics
    AVG(alignment_score) as avg_alignment,
    MIN(alignment_score) as min_alignment,
    MAX(alignment_score) as max_alignment,
    
    -- Distribution
    SUM(CASE WHEN alignment_score > 0.7 THEN 1 END) as aligned_tweets,
    SUM(CASE WHEN alignment_score < 0.3 THEN 1 END) as opposed_tweets,
    
    -- Engagement weighted alignment
    SUM(alignment_score * like_count) / SUM(like_count) as weighted_alignment,
    
    -- Key themes
    THEMES(text, 3) as trending_topics,
    
    -- Total reach
    SUM(like_count + retweet_count) as total_engagement
FROM narrative_analysis
GROUP BY month
ORDER BY month DESC;

-- ============================================================================
-- KILLER QUERY: Find Your Champions
-- ============================================================================

-- Who are the top voices aligned with your narrative?
SELECT 
    author_name,
    
    -- Alignment stats
    COUNT(*) as relevant_tweets,
    AVG(text ALIGNS 'SQL interfaces are transforming AI development') as avg_alignment,
    
    -- Find their best aligned tweet
    argMax(text, text ALIGNS 'SQL interfaces are transforming AI development') as best_tweet,
    argMax(url, text ALIGNS 'SQL interfaces are transforming AI development') as best_tweet_url,
    MAX(text ALIGNS 'SQL interfaces are transforming AI development') as best_alignment_score,
    
    -- Reach
    SUM(like_count) as total_likes,
    AVG(like_count) as avg_likes,
    
    -- Consistency check
    STDDEV(text ALIGNS 'SQL interfaces are transforming AI development') as alignment_consistency
FROM tweets
WHERE text ABOUT 'SQL or databases or data infrastructure' > 0.6
  AND like_count > 20
GROUP BY author_name
HAVING avg_alignment > 0.7  -- Only strong aligners
  AND relevant_tweets >= 3   -- Consistent voice
ORDER BY (avg_alignment * LOG(total_likes + 1)) DESC  -- Alignment × reach
LIMIT 30;
