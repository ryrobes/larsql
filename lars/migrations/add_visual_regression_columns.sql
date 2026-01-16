-- Migration: Add visual regression test support
--
-- This migration adds columns to support visual regression testing:
-- - session_id: Browser session ID for this test run
-- - previous_session_id: Browser session ID of the comparison run
-- - overall_score: Average similarity score across all screenshots (0-1)
-- - is_baseline: Whether this is the first run (no comparison)
-- - screenshots_compared: JSON array of individual screenshot comparisons
--
-- Also updates the test_type enum to include 'visual_regression'.
--
-- Safe to run multiple times (uses IF NOT EXISTS pattern)

USE lars;

-- Add session_id column for linking to browser sessions
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS session_id String DEFAULT '';

-- Add previous_session_id for tracking what we compared against
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS previous_session_id String DEFAULT '';

-- Add overall_score (0-1 similarity score averaged across screenshots)
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS overall_score Float32 DEFAULT 0;

-- Add is_baseline flag (true for first run with no comparison)
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS is_baseline UInt8 DEFAULT 0;

-- Add screenshots_compared JSON array with per-screenshot results
-- Format: [{"name": "0-post-click.jpg", "similarity": 0.98, "passed": true, ...}, ...]
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS screenshots_compared String DEFAULT '';

-- Update the test_type enum to include visual_regression
-- ClickHouse requires modifying the column type to add new enum values
-- This is safe because we're only adding a new value, not changing existing ones
ALTER TABLE test_results MODIFY COLUMN test_type Enum8(
    'semantic_sql' = 1,
    'cascade_snapshot' = 2,
    'visual_regression' = 3
);

-- Verify the columns were added
SELECT
    name,
    type,
    default_expression
FROM system.columns
WHERE table = 'test_results'
  AND database = currentDatabase()
  AND name IN ('session_id', 'previous_session_id', 'overall_score', 'is_baseline', 'screenshots_compared', 'test_type')
ORDER BY name;
