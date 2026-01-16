-- ============================================================================
-- Semantic SQL Test Queries for Bigfoot Dataset
-- ============================================================================

-- ============================================================================
-- Phase 1: Basic Semantic Operators
-- ============================================================================

-- 1. MEANS - Semantic boolean filter
-- @ use a fast and cheap model
SELECT title, county, state
FROM bigfoot
WHERE title MEANS 'happened at night'
LIMIT 10;

-- 2. NOT MEANS - Exclude semantic matches
SELECT title, county
FROM bigfoot
WHERE title NOT MEANS 'hoax or prank'
LIMIT 10;

-- 3. ABOUT - Semantic score threshold
SELECT title, observed
FROM bigfoot
WHERE observed ABOUT 'physical evidence found' > 0.6
LIMIT 10;

-- 4. NOT ABOUT - Exclude content scoring above threshold
-- @ threshold: 0.4
SELECT title, observed
FROM bigfoot
WHERE observed NOT ABOUT 'just heard sounds'
LIMIT 10;

-- 5. RELEVANCE TO - Order by semantic relevance
SELECT title, county, state
FROM bigfoot
ORDER BY title RELEVANCE TO 'credible eyewitness encounter'
LIMIT 10;

-- 6. NOT RELEVANCE TO - Find outliers (least relevant first)
SELECT title, county
FROM bigfoot
ORDER BY title NOT RELEVANCE TO 'typical bigfoot sighting in woods'
LIMIT 10;

-- ============================================================================
-- Phase 1: Combining Operators
-- ============================================================================

-- 7. Multiple semantic filters
-- @ use a fast and cheap model
SELECT title, county, state
FROM bigfoot
WHERE title MEANS 'daytime sighting'
  AND observed ABOUT 'clear view of creature' > 0.5
ORDER BY title RELEVANCE TO 'close encounter'
LIMIT 10;

-- 8. Semantic filter with aggregates
SELECT
  state,
  COUNT(*) as sightings,
  -- @ use a fast model
  summarize(title) as summary
FROM bigfoot
-- @ use a fast model
WHERE title MEANS 'multiple witnesses'
GROUP BY state
ORDER BY sightings DESC
LIMIT 10;

-- ============================================================================
-- Phase 2: SEMANTIC DISTINCT
-- ============================================================================

-- 9. Basic semantic distinct - dedupe similar county names
SELECT SEMANTIC DISTINCT county FROM bigfoot;

-- 10. Semantic distinct with criteria
SELECT SEMANTIC DISTINCT county AS 'same geographic area' FROM bigfoot;

-- 11. Semantic distinct on titles (find unique incident types)
-- @ use a fast model, focus on the type of encounter
SELECT SEMANTIC DISTINCT title AS 'same type of encounter' FROM bigfoot;

-- ============================================================================
-- Phase 2: GROUP BY MEANING
-- ============================================================================

-- 12. Basic GROUP BY MEANING - auto-cluster counties
SELECT county, COUNT(*) as sightings
FROM bigfoot
GROUP BY MEANING(county)
ORDER BY sightings DESC;

-- 13. GROUP BY MEANING with cluster count
SELECT county, COUNT(*) as sightings
FROM bigfoot
GROUP BY MEANING(county, 10)
ORDER BY sightings DESC;

-- 14. GROUP BY MEANING with criteria
SELECT county, COUNT(*) as sightings
FROM bigfoot
GROUP BY MEANING(county, 8, 'geographic region')
ORDER BY sightings DESC;

-- 15. GROUP BY MEANING on titles
SELECT title, COUNT(*) as incidents
FROM bigfoot
GROUP BY MEANING(title, 5, 'type of bigfoot encounter')
ORDER BY incidents DESC;

-- ============================================================================
-- Phase 2: GROUP BY TOPICS
-- ============================================================================

-- 16. Extract topics from observations
SELECT content, COUNT(*) as mentions
FROM bigfoot
GROUP BY TOPICS(observed, 5);

-- 17. Topics from titles
SELECT content, COUNT(*) as incidents
FROM bigfoot
GROUP BY TOPICS(title, 3);

-- ============================================================================
-- Complex Queries
-- ============================================================================

-- 18. Semantic filter + GROUP BY MEANING
SELECT county, COUNT(*) as credible_sightings
FROM bigfoot
WHERE observed ABOUT 'credible detailed description' > 0.5
GROUP BY MEANING(county, 10, 'region')
ORDER BY credible_sightings DESC;

-- 19. Multiple aggregates with semantic grouping
SELECT
  title as encounter_type,
  COUNT(*) as incidents,
  -- @ use a fast model
  summarize(observed) as typical_description
FROM bigfoot
WHERE title MEANS 'visual sighting'
GROUP BY MEANING(title, 5, 'encounter category')
ORDER BY incidents DESC;

-- 20. Semantic distinct + filter
SELECT SEMANTIC DISTINCT county AS 'same region'
FROM bigfoot
WHERE observed MEANS 'footprints or tracks found';

-- ============================================================================
-- IMPLIES and CONTRADICTS Operators
-- ============================================================================

-- 21. IMPLIES - Find sightings where title implies visual contact
SELECT title, observed
FROM bigfoot
WHERE title IMPLIES 'witness had visual contact with creature'
LIMIT 10;

-- 22. IMPLIES with column - Title implies what's in observation
SELECT title, observed
FROM bigfoot
WHERE title IMPLIES observed
LIMIT 10;

-- 23. CONTRADICTS - Find inconsistent reports
-- Where title contradicts what was observed
SELECT title, observed
FROM bigfoot
WHERE title CONTRADICTS observed
LIMIT 10;

-- 24. CONTRADICTS with string - Find titles that contradict "no sighting"
SELECT title, observed
FROM bigfoot
WHERE title CONTRADICTS 'no creature was actually seen'
LIMIT 10;

-- 25. Combined logical operators
SELECT title, observed
FROM bigfoot
WHERE title IMPLIES 'daytime encounter'
  AND observed NOT MEANS 'night time'
  AND NOT (title CONTRADICTS observed)
LIMIT 10;

-- 26. Find logically consistent high-credibility reports
-- @ use a fast model
SELECT title, observed, county
FROM bigfoot
WHERE title IMPLIES observed
  AND observed ABOUT 'detailed physical description' > 0.6
ORDER BY title RELEVANCE TO 'credible close encounter'
LIMIT 10;
