-- Migration: Backfill content_type for existing rows
-- Date: 2025-12-29
-- Description: Sets content_type based on heuristics for existing rows
--
-- This is a BEST-EFFORT backfill using SQL-only heuristics.
-- For more accurate classification, run the Python backfill script.
--
-- Priority order matches content_classifier.py:
-- 1. has_images = true -> 'image'
-- 2. metadata_json contains images -> 'image'
-- 3. metadata_json type = 'plotly' -> 'chart'
-- 4. metadata_json has rows + columns -> 'table'
-- 5. tool_calls_json is not empty -> 'tool_call'
-- 6. content_json looks like tool call JSON -> 'tool_call'
-- 7. content_json starts with # or has markdown patterns -> 'markdown'
-- 8. content_json is valid JSON object/array -> 'json'
-- 9. Default -> 'text'

-- Step 1: Images (highest priority)
ALTER TABLE unified_logs
UPDATE content_type = 'image'
WHERE content_type IS NULL OR content_type = 'text'
  AND (
    has_images = true
    OR position(metadata_json, '"images"') > 0
  );

-- Step 2: Charts (plotly)
ALTER TABLE unified_logs
UPDATE content_type = 'chart'
WHERE content_type IS NULL OR content_type = 'text'
  AND (
    position(metadata_json, '"type":"plotly"') > 0
    OR position(metadata_json, '"type": "plotly"') > 0
    OR (position(content_json, '"data"') > 0 AND position(content_json, '"layout"') > 0)
  );

-- Step 3: Tables
ALTER TABLE unified_logs
UPDATE content_type = 'table'
WHERE content_type IS NULL OR content_type = 'text'
  AND (
    (position(metadata_json, '"rows"') > 0 AND position(metadata_json, '"columns"') > 0)
    OR (position(content_json, '"rows"') > 0 AND position(content_json, '"columns"') > 0)
  );

-- Step 4: Tool calls (explicit tool_calls_json)
ALTER TABLE unified_logs
UPDATE content_type = 'tool_call'
WHERE content_type IS NULL OR content_type = 'text'
  AND tool_calls_json IS NOT NULL
  AND tool_calls_json != ''
  AND tool_calls_json != '[]'
  AND tool_calls_json != 'null';

-- Step 5: Tool calls embedded in content (JSON with "tool" and "arguments")
ALTER TABLE unified_logs
UPDATE content_type = 'tool_call'
WHERE content_type IS NULL OR content_type = 'text'
  AND position(content_json, '"tool"') > 0
  AND position(content_json, '"arguments"') > 0;

-- Step 6: Errors
ALTER TABLE unified_logs
UPDATE content_type = 'error'
WHERE content_type IS NULL OR content_type = 'text'
  AND (
    position(lower(content_json), '"error"') > 0
    OR position(content_json, 'Traceback (most recent call last)') > 0
    OR position(content_json, 'Exception:') > 0
  );

-- Step 7: Markdown (headers, bold, code blocks, lists)
-- Note: This is approximate - checks for common markdown patterns
ALTER TABLE unified_logs
UPDATE content_type = 'markdown'
WHERE content_type IS NULL OR content_type = 'text'
  AND (
    -- Starts with header
    content_json LIKE '"#%'
    OR content_json LIKE '"\n#%'
    -- Has bold text
    OR position(content_json, '**') > 0
    -- Has code blocks
    OR position(content_json, '```') > 0
    -- Has inline code
    OR position(content_json, '`') > 0
  )
  AND role = 'assistant';

-- Step 8: JSON (structured data that didn't match above patterns)
-- Only for assistant messages that look like JSON objects/arrays
ALTER TABLE unified_logs
UPDATE content_type = 'json'
WHERE content_type IS NULL OR content_type = 'text'
  AND role = 'assistant'
  AND (
    content_json LIKE '"{%'
    OR content_json LIKE '"[%'
  );

-- Verify the backfill results
SELECT
    content_type,
    count(*) as count
FROM unified_logs
WHERE role = 'assistant'
GROUP BY content_type
ORDER BY count DESC;
