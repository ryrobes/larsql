-- Migration: Add Caller Tracking Columns
-- Purpose: Track invocation source (SQL query, CLI, UI) for cost rollup and debugging
--
-- Background:
-- Enables grouping related sessions by caller_id for:
-- - Cost rollup by SQL query (one query → many cascade sessions)
-- - Debugging: "What spawned this session?"
-- - Analytics: Usage by origin (SQL vs CLI vs UI)
--
-- New columns:
-- - caller_id: Parent identifier grouping related sessions
--   Examples: sql-clever-fox-abc123, cli-misty-owl-def456, ui-quick-rabbit-ghi789
-- - invocation_metadata_json: Full context (origin, SQL query, CLI command, UI component, etc.)
--
-- Hierarchy: All sub-cascades inherit the top-level caller_id for unified cost tracking.

-- Add columns to unified_logs
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS caller_id String DEFAULT '' AFTER parent_message_id;
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS invocation_metadata_json String DEFAULT '{}' CODEC(ZSTD(3)) AFTER caller_id;

-- Add index for fast caller_id queries
ALTER TABLE unified_logs ADD INDEX IF NOT EXISTS idx_caller_id caller_id TYPE bloom_filter GRANULARITY 1;

-- Add columns to session_state
ALTER TABLE session_state ADD COLUMN IF NOT EXISTS caller_id String DEFAULT '' AFTER parent_session_id;
ALTER TABLE session_state ADD COLUMN IF NOT EXISTS invocation_metadata_json String DEFAULT '{}' CODEC(ZSTD(3)) AFTER caller_id;

-- Add index for session_state
ALTER TABLE session_state ADD INDEX IF NOT EXISTS idx_caller_id caller_id TYPE bloom_filter GRANULARITY 1;

-- Add columns to cascade_sessions
ALTER TABLE cascade_sessions ADD COLUMN IF NOT EXISTS caller_id String DEFAULT '' AFTER parent_session_id;
ALTER TABLE cascade_sessions ADD COLUMN IF NOT EXISTS invocation_metadata_json String DEFAULT '{}' CODEC(ZSTD(3)) AFTER caller_id;

-- Add index for cascade_sessions
ALTER TABLE cascade_sessions ADD INDEX IF NOT EXISTS idx_caller_id caller_id TYPE bloom_filter GRANULARITY 1;

-- For backward compatibility: existing rows will have caller_id = '' and invocation_metadata_json = '{}'
-- This correctly represents "no tracking" for historical sessions.
