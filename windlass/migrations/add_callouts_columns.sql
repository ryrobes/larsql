-- Migration: Add callouts columns to unified_logs table
-- Date: 2025-12-09
-- Description: Adds is_callout and callout_name columns for semantic message tagging

-- Add is_callout column (boolean, default false)
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS is_callout Bool DEFAULT false;

-- Add callout_name column (nullable string for the callout label)
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS callout_name Nullable(String);

-- Add index for is_callout to speed up callout queries
ALTER TABLE unified_logs
ADD INDEX IF NOT EXISTS idx_is_callout is_callout TYPE set(2) GRANULARITY 1;

-- Verify the changes
SELECT
    name,
    type
FROM system.columns
WHERE table = 'unified_logs'
  AND name IN ('is_callout', 'callout_name')
ORDER BY name;
