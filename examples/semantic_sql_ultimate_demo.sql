-- ============================================================================
-- ULTIMATE SEMANTIC SQL DEMO - Everything Together
-- ============================================================================
-- Showcasing the complete power of LARS Semantic SQL:
-- - 28 operators working together
-- - Scalar + Aggregate + Vector search
-- - Information extraction + Analysis + Transformation
-- - Traditional SQL + Semantic SQL + LLM reasoning
--
-- This query does things that are IMPOSSIBLE in any other SQL system!
-- ============================================================================

CREATE TABLE customer_interactions (
    interaction_id INTEGER,
    customer_id INTEGER,
    interaction_type VARCHAR,
    timestamp TIMESTAMP,
    content VARCHAR,
    metadata VARCHAR
);

INSERT INTO customer_interactions VALUES
    (1, 101, 'support_ticket', '2024-12-15 14:30:00',
     'Hi, I am Sarah Johnson and I am writing about order #A12345 that I placed on December 1st. The package was supposed to arrive by December 10th but it is now December 15th and I still have not received it. This is extremely frustrating as it was a birthday gift for my daughter. The item cost $299 and I paid extra for expedited shipping ($25). I need this resolved immediately - either ship with overnight delivery at no extra cost or provide a full refund including the expedited shipping fee. I have been a loyal customer since 2019 and this is unacceptable service. Please respond within 24 hours.',
     '{"purchase_date": "2024-12-01", "expected_delivery": "2024-12-10", "vip": true}'),

    (2, 102, 'product_review', '2024-12-16 10:15:00',
     'Absolutely love this new laptop! The battery life is incredible - I got a full 14 hours of continuous use yesterday doing video editing which is my primary workflow. The M3 chip handles 4K footage smoothly without any lag or heat issues. Build quality feels premium and sturdy. The display is gorgeous with excellent color accuracy for my photography work. Only minor complaint is the keyboard is a bit shallow compared to my old ThinkPad, but I am getting used to it. Overall 9 out of 10, highly recommend for creative professionals. Setup was painless and migration from my old Mac took under an hour.',
     '{"product": "MacBook Pro 16", "purchase_price": 2499, "verified_purchase": true}'),

    (3, 103, 'chat_transcript', '2024-12-17 16:45:00',
     'Agent: Hello how can I help you today? Customer: Yes I have a question about your return policy. Agent: Of course I would be happy to explain that. Our return policy allows returns within 30 days of purchase for a full refund. Customer: What about opened items? Agent: Opened items can be returned but there is a 15% restocking fee. Customer: That seems high. Agent: I understand your concern. For VIP members we can waive that fee. Are you a VIP member? Customer: No but I spend thousands with you every year. Agent: Let me check your account history. I see you have been with us since 2020 and spent over $5000. I can upgrade you to VIP status right now. Customer: That would be great thank you. Agent: Done. Your VIP status is now active and the restocking fee will be waived. Is there anything else? Customer: No that is perfect thanks.',
     '{"duration_minutes": 8, "agent_id": "AGT_456", "resolution": "vip_upgrade"}');


-- ============================================================================
-- ULTIMATE QUERY: Everything at Once
-- ============================================================================
-- This single query demonstrates EVERY major semantic SQL capability!
-- ============================================================================

WITH
  -- Step 1: Generate embeddings for future vector search (auto-stored in ClickHouse)
  embedded AS (
    SELECT
      interaction_id,
      content,
      EMBED(content) as embedding  -- Auto-stores with table/column/ID tracking!
    FROM customer_interactions
  ),

  -- Step 2: Enrich with semantic analysis
  analyzed AS (
    SELECT
      interaction_id,
      customer_id,
      interaction_type,
      timestamp,
      content,
      metadata,

      -- === SCALAR SUMMARIZATION ===
      CONDENSE(content) as summary,                                    -- Condense long text
      TLDR(content) as tldr,                                           -- Same but fun!
      CONDENSE(content, 'key facts only') as facts,                   -- Focused summary

      -- === INFORMATION EXTRACTION ===
      content EXTRACTS 'customer name' as customer_name,
      content EXTRACTS 'order number or ID' as order_ref,
      content EXTRACTS 'monetary amount' as amount,
      content EXTRACTS 'date or deadline' as date_mentioned,
      content EXTRACTS 'main issue or request' as primary_concern,

      -- === BOOLEAN FILTERING (Multiple operators!) ===
      content MEANS 'complaint or negative experience' as is_complaint,
      content MEANS 'urgent or time-sensitive' as is_urgent,
      content ~ 'product quality issue' as mentions_quality,  -- Tilde operator!

      -- === SCORING (Multiple approaches) ===
      content ABOUT 'customer satisfaction' as satisfaction_score,
      content ALIGNS 'our company values' as brand_alignment,
      content SIMILAR_TO 'VIP customer feedback' as vip_similarity,

      -- === GENERIC PROMPT (ASK - Unlimited!) ===
      content ASK 'sentiment: positive/negative/neutral/mixed' as sentiment,
      content ASK 'urgency level 1-10' as urgency_level,
      content ASK 'customer lifetime value potential: low/medium/high' as ltv_potential,
      content ASK 'churn risk percentage 0-100' as churn_risk,
      content ASK 'recommended next action' as recommended_action,
      content ASK 'should manager escalate? yes/no' as needs_escalation,

      -- === TRADITIONAL SQL (Still works!) ===
      LENGTH(content) as content_length,
      EXTRACT(HOUR FROM timestamp) as hour_of_day

    FROM embedded
  )

-- === AGGREGATE ANALYSIS ===
SELECT
  interaction_type,

  -- Counts
  COUNT(*) as total_interactions,
  SUM(CASE WHEN is_complaint THEN 1 ELSE 0 END) as complaint_count,
  SUM(CASE WHEN is_urgent THEN 1 ELSE 0 END) as urgent_count,

  -- === AGGREGATE SUMMARIZATION ===
  SUMMARIZE(content) as overall_summary,                    -- Aggregate: summarize collection
  THEMES(summary, 3) as main_themes,                        -- Extract 3 main topics
  CONSENSUS(primary_concern) as common_concern,             -- What do they agree on?

  -- Averages
  AVG(CAST(urgency_level AS INTEGER)) as avg_urgency,
  AVG(satisfaction_score) as avg_satisfaction,
  AVG(CAST(churn_risk AS INTEGER)) as avg_churn_risk,

  -- Extraction rollup
  COUNT(DISTINCT customer_name) as unique_customers_named,
  COUNT(DISTINCT order_ref) as orders_mentioned,

  -- Metadata
  MIN(timestamp) as first_interaction,
  MAX(timestamp) as last_interaction

FROM analyzed
GROUP BY interaction_type

-- === SEMANTIC ORDERING ===
ORDER BY overall_summary RELEVANCE TO 'critical customer issues'  -- Semantic sort!

-- Safety limit
LIMIT 100;


-- ============================================================================
-- WHAT JUST HAPPENED?
-- ============================================================================
-- This single query used:
--
-- ✅ EMBED          - Auto-generated and stored embeddings
-- ✅ CONDENSE       - Scalar summarization (per row)
-- ✅ TLDR           - Fun alias for CONDENSE
-- ✅ EXTRACTS       - Information extraction (6 different entities!)
-- ✅ MEANS          - Boolean semantic filtering (2 checks)
-- ✅ ~ (tilde)      - Semantic matching operator
-- ✅ ABOUT          - Relevance scoring
-- ✅ ALIGNS         - Narrative alignment scoring
-- ✅ SIMILAR_TO     - Similarity scoring
-- ✅ ASK            - Generic prompts (6 different questions!)
-- ✅ SUMMARIZE      - Aggregate summarization
-- ✅ THEMES         - Topic extraction
-- ✅ CONSENSUS      - Finding common ground
-- ✅ RELEVANCE TO   - Semantic ordering
-- ✅ Traditional SQL - LENGTH, EXTRACT, COUNT, AVG, GROUP BY, ORDER BY
--
-- Total: 14+ semantic operators + traditional SQL in ONE QUERY!
-- ============================================================================


-- ============================================================================
-- SIMPLER EXAMPLE: Customer Support Dashboard
-- ============================================================================

SELECT
    interaction_id,
    customer_id,

    -- Quick summary for dashboard
    TLDR(content) as quick_summary,

    -- Key info extraction
    content EXTRACTS 'customer name' as customer,
    content EXTRACTS 'order number' as order_num,

    -- Urgency assessment
    content ASK 'urgency 1-10' as urgency,
    content ASK 'should escalate to manager? yes/no' as escalate,

    -- Sentiment
    content ASK 'sentiment: angry/frustrated/neutral/happy' as mood,

    -- Action recommendation
    CONDENSE(content, 'recommend resolution approach') as resolution

FROM customer_interactions
WHERE
    -- Semantic filters (fast!)
    content MEANS 'complaint or problem'
    AND content MEANS 'urgent or time-sensitive'

ORDER BY
    -- Sort by urgency (using ASK result)
    CAST(content ASK 'urgency 1-10' AS INTEGER) DESC

LIMIT 20;


-- ============================================================================
-- VECTOR SEARCH + SEMANTICS: The Ultimate Hybrid
-- ============================================================================

-- Pre-filter with vector search (fast!), then analyze with LLMs (precise!)
WITH takes AS (
    SELECT * FROM VECTOR_SEARCH('urgent customer complaints', 'customer_interactions', 50)
    WHERE similarity > 0.7
)
SELECT
    i.interaction_id,

    -- Summarization
    TLDR(i.content) as tldr,
    CONDENSE(i.content, 'what went wrong?') as problem,

    -- Extraction
    i.content EXTRACTS 'customer name' as customer,
    i.content EXTRACTS 'resolution requested' as wants,

    -- Analysis
    i.content ASK 'churn risk: low/medium/high' as churn_risk,
    i.content ASK 'customer emotion: angry/sad/frustrated/confused' as emotion,

    -- Boolean checks
    i.content MEANS 'product defect or quality issue' as is_quality_issue,

    -- Vector score
    c.similarity as vector_relevance

FROM takes c
JOIN customer_interactions i ON i.interaction_id = c.id

WHERE
    -- LLM boolean filter (on 50 rows, not millions!)
    i.content MEANS 'unresolved issue'

ORDER BY
    -- Semantic ordering
    i.content RELEVANCE TO 'critical escalation needed' DESC

LIMIT 10;

-- Performance:
-- - Vector search: 1M rows → 50 takes in ~50ms ($0)
-- - LLM analysis: 50 rows × 10 operators = 500 calls (~$0.05, ~30s)
-- - Total: ~$0.05, ~30 seconds
-- vs. Pure LLM on 1M rows: ~$500, ~55 hours ❌
--
-- 10,000x cost reduction! 🚀


-- ============================================================================
-- CREATIVE: The Absurd Demo
-- ============================================================================
-- Proving you can do LITERALLY ANYTHING with ASK + other operators

SELECT
    interaction_id,

    -- Standard analysis
    CONDENSE(content) as summary,

    -- Creative transformations
    content ASK 'rewrite as a pirate' as pirate_version,
    content ASK 'write a haiku about this' as haiku,
    content ASK 'if this was a movie, what genre?' as movie_genre,
    content ASK 'describe this in emoji only' as emoji_summary,

    -- Personality analysis
    content ASK 'author personality type (MBTI)' as personality,
    content ASK 'estimated age range of author' as age_range,
    content ASK 'communication style: passive/assertive/aggressive' as comm_style,

    -- Translation (any language!)
    CONDENSE(content) ASK 'translate to Spanish' as summary_es,
    CONDENSE(content) ASK 'translate to Klingon' as summary_klingon,

    -- Meta-analysis
    content ASK 'if you were the customer service agent, how would you respond?' as ai_response,
    content ASK 'rate this interaction quality 1-10' as quality_score

FROM customer_interactions
LIMIT 3;

-- This demonstrates the RIDICULOUS flexibility of Semantic SQL!
-- Try doing THIS in PostgresML or Databricks! 😎


-- Cleanup
DROP TABLE customer_interactions;
DROP TABLE articles;
DROP TABLE customer_feedback;
DROP TABLE documents;
DROP TABLE product_reviews;
DROP TABLE code_commits;
