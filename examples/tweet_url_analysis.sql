-- SUMMARIZE_URLS() OPERATOR - Tweet URL Analysis Examples
-- Auto-discovers URLs in text, fetches content, returns summaries
-- Perfect for enriching social media posts with linked content context

-- ============================================================================
-- 1. BASIC USAGE - Enrich tweets with URL summaries
-- ============================================================================

-- Get URL summaries for all tweets with links
SELECT 
    author_name,
    text,
    SUMMARIZE_URLS(text) as article_summary,
    like_count,
    url as tweet_url
FROM tweets
WHERE text LIKE '%http%'  -- Only tweets with URLs
LIMIT 10;

-- ============================================================================
-- 2. FILTER BY URL CONTENT - Find tweets linking to specific topics
-- ============================================================================

-- Find tweets that link to articles about "database innovation"
SELECT 
    author_name,
    text,
    SUMMARIZE_URLS(text) as linked_content
FROM tweets
WHERE text LIKE '%http%'
  AND SUMMARIZE_URLS(text) ABOUT 'database or SQL innovation' > 0.7
ORDER BY like_count DESC
LIMIT 20;

-- ============================================================================
-- 3. QUOTED TWEET + URL CONTEXT
-- ============================================================================

-- Analyze quoted tweets WITH the context of linked articles
SELECT 
    author_name,
    text as quote_tweet,
    quoted_tweet_text as original_tweet,
    SUMMARIZE_URLS(text) as quote_url_context,
    SUMMARIZE_URLS(quoted_tweet_text) as original_url_context,
    
    -- Do the quote and original align?
    CASE 
        WHEN text IMPLIES quoted_tweet_text THEN 'Supporting'
        WHEN text CONTRADICTS quoted_tweet_text THEN 'Challenging'
        ELSE 'Discussing'
    END as response_type
FROM tweets
WHERE quoted_tweet_text IS NOT NULL
  AND (text LIKE '%http%' OR quoted_tweet_text LIKE '%http%')
LIMIT 20;

-- ============================================================================
-- 4. EVIDENCE AGGREGATION - What are people linking to?
-- ============================================================================

-- Group tweets by the semantic content they link to
SELECT 
    url_topic_cluster,
    COUNT(*) as tweet_count,
    SUM(like_count) as total_engagement,
    
    groupArray(DISTINCT author_name) as who_shared,
    THEMES(SUMMARIZE_URLS(text), 3) as link_themes,
    CONSENSUS(SUMMARIZE_URLS(text)) as what_links_discuss
FROM (
    SELECT 
        *,
        CLUSTER(SUMMARIZE_URLS(text), 5, 'by article topic') as url_topic_cluster
    FROM tweets
    WHERE text LIKE '%http%'
      AND SUMMARIZE_URLS(text) != ''  -- Has fetchable URL
)
GROUP BY url_topic_cluster
ORDER BY total_engagement DESC;

-- ============================================================================
-- 5. INDUSTRY EVIDENCE - Find supporting/contradicting sources
-- ============================================================================

-- What external sources support or challenge our claims?
WITH our_claims AS (
    SELECT 'SQL is becoming important for AI workflows' as claim
    UNION ALL
    SELECT 'LLMs need better data infrastructure'
    UNION ALL  
    SELECT 'Semantic search is replacing keyword search'
)
SELECT 
    c.claim,
    
    COUNT(*) as tweets_with_evidence,
    SUM(like_count) as evidence_weight,
    
    SUM(CASE WHEN SUMMARIZE_URLS(t.text) IMPLIES c.claim THEN 1 END) as supporting_sources,
    SUM(CASE WHEN SUMMARIZE_URLS(t.text) CONTRADICTS c.claim THEN 1 END) as contradicting_sources,
    
    SUMMARIZE(SUMMARIZE_URLS(t.text)) as meta_summary,
    groupArray(DISTINCT t.url) as example_tweet_urls
FROM our_claims c
CROSS JOIN tweets t
WHERE t.text LIKE '%http%'
  AND SUMMARIZE_URLS(t.text) ABOUT c.claim > 0.6
GROUP BY c.claim
ORDER BY evidence_weight DESC;

-- ============================================================================
-- 6. CONTENT TYPE CLASSIFICATION
-- ============================================================================

-- What types of content are people linking to?
SELECT 
    LLM_CASE SUMMARIZE_URLS(text)
        WHEN SEMANTIC 'research paper or academic study' THEN 'Research'
        WHEN SEMANTIC 'blog post or opinion piece' THEN 'Blog'
        WHEN SEMANTIC 'news article or press release' THEN 'News'
        WHEN SEMANTIC 'product documentation or tutorial' THEN 'Docs'
        WHEN SEMANTIC 'GitHub repository or code' THEN 'Code'
        WHEN SEMANTIC 'video or multimedia content' THEN 'Video'
        ELSE 'Other'
    END as content_type,
    
    COUNT(*) as count,
    AVG(like_count) as avg_engagement,
    THEMES(text, 3) as tweet_themes
FROM tweets
WHERE text LIKE '%http%'
  AND SUMMARIZE_URLS(text) != ''
GROUP BY content_type
ORDER BY avg_engagement DESC;

-- ============================================================================
-- 7. VIRAL LINK ANALYSIS - What content goes viral when shared?
-- ============================================================================

-- Which linked articles get the most engagement?
SELECT 
    SUMMARIZE_URLS(text) as article_summary,
    COUNT(DISTINCT id) as times_shared,
    SUM(like_count) as total_likes,
    SUM(retweet_count) as total_retweets,
    
    groupArray(DISTINCT author_name) as shared_by,
    SENTIMENT(text) as tweet_sentiment,
    
    any(text) as example_tweet
FROM tweets
WHERE text LIKE '%http%'
  AND SUMMARIZE_URLS(text) != ''
GROUP BY DEDUPE(SUMMARIZE_URLS(text), 'same article')  -- Group by semantic content!
HAVING times_shared >= 3
ORDER BY total_likes DESC
LIMIT 20;

-- ============================================================================
-- 8. RESEARCH DEPTH - URL content vs tweet sentiment
-- ============================================================================

-- Do tweets accurately represent the content they link to?
SELECT 
    id,
    author_name,
    text as tweet_text,
    SUMMARIZE_URLS(text) as actual_article_content,
    
    -- Does the tweet match the article?
    CASE 
        WHEN text IMPLIES SUMMARIZE_URLS(text) THEN 'Accurate'
        WHEN text CONTRADICTS SUMMARIZE_URLS(text) THEN 'Misleading'
        WHEN SENTIMENT(text) - SENTIMENT(SUMMARIZE_URLS(text)) > 0.5 THEN 'Sensationalized'
        ELSE 'Neutral'
    END as tweet_accuracy,
    
    like_count,
    url
FROM tweets
WHERE text LIKE '%http%'
  AND SUMMARIZE_URLS(text) != ''
  AND like_count > 500  -- Influential tweets
ORDER BY like_count DESC;

-- ============================================================================
-- 9. WEEKLY URL TREND ANALYSIS
-- ============================================================================

-- What are people linking to each week?
SELECT 
    toStartOfWeek(created_at) as week,
    COUNT(*) as tweets_with_urls,
    
    THEMES(SUMMARIZE_URLS(text), 5) as trending_link_topics,
    CONSENSUS(SUMMARIZE_URLS(text)) as common_narrative,
    
    SUM(like_count) as total_engagement
FROM tweets
WHERE text LIKE '%http%'
  AND SUMMARIZE_URLS(text) != ''
  AND created_at > NOW() - INTERVAL '90 days'
GROUP BY week
ORDER BY week DESC;

-- ============================================================================
-- 10. HYBRID: Vector Search + URL Context
-- ============================================================================

-- Find tweets about "AI infrastructure" AND check what they link to
WITH relevant_tweets AS (
    SELECT * FROM VECTOR_SEARCH(
        'AI infrastructure and data platforms',
        'tweets',
        200
    )
    WHERE similarity > 0.7
)
SELECT
    t.author_name,
    t.text,
    c.similarity as relevance,
    
    SUMMARIZE_URLS(t.text) as linked_content,
    
    -- Does the linked content support our thesis?
    CASE 
        WHEN SUMMARIZE_URLS(t.text) IMPLIES 'better data infrastructure needed' THEN 'Supports thesis'
        ELSE 'Neutral'
    END as evidence_type,
    
    t.like_count,
    t.url
FROM relevant_tweets c
JOIN tweets t ON t.id = c.id
WHERE t.text LIKE '%http%'
ORDER BY c.similarity DESC
LIMIT 20;

-- ============================================================================
-- KILLER QUERY: Complete URL Intelligence Dashboard
-- ============================================================================

SELECT 
    category,
    
    -- URL metrics
    COUNT(*) as tweets_with_urls,
    COUNT(DISTINCT SUMMARIZE_URLS(text)) as unique_articles,
    
    -- What are they linking to?
    THEMES(SUMMARIZE_URLS(text), 5) as article_themes,
    CONSENSUS(SUMMARIZE_URLS(text)) as common_article_type,
    
    -- How do tweets frame the links?
    SENTIMENT(text) as tweet_sentiment,
    THEMES(text, 3) as tweet_themes,
    
    -- Engagement
    AVG(like_count) as avg_likes,
    SUM(like_count + retweet_count) as total_engagement,
    
    -- Top voices
    groupArray(DISTINCT author_name) as key_sharers
FROM tweets
WHERE text LIKE '%http%'
  AND SUMMARIZE_URLS(text) != ''
  AND created_at > NOW() - INTERVAL '30 days'
GROUP BY category
ORDER BY total_engagement DESC;
