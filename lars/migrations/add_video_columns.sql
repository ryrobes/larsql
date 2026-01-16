-- Migration: Add video tracking columns to unified_logs
--
-- This migration adds support for video artifacts from LLM responses.
-- Videos are stored similarly to images - paths tracked in JSON,
-- actual files saved to $LARS_ROOT/videos/{session_id}/{cell_name}/
--
-- Safe to run multiple times (uses IF NOT EXISTS pattern via ALTER TABLE ADD COLUMN IF NOT EXISTS)

-- Add videos JSON array column (stores paths to video files)
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS videos_json Nullable(String);

-- Add has_videos flag for quick filtering
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS has_videos Bool DEFAULT false;

-- Verify the columns were added
SELECT
    name,
    type,
    default_expression
FROM system.columns
WHERE table = 'unified_logs'
  AND database = currentDatabase()
  AND name IN ('videos_json', 'has_videos')
ORDER BY name;
