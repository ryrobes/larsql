-- Migration: Add render content types for request_decision UI rendering
-- Date: 2025-12-29
-- Description: Documents new render:* content types for specialized UI rendering
--              and creates a view for efficient querying of render entries.
--
-- New Content Types:
-- - render:request_decision - Clean ui_spec for request_decision tool, ready for frontend rendering
--
-- This enables:
-- - Direct rendering in /outputs page without parsing tool call content from markdown
-- - Association of screenshots with specific request_decision executions
-- - Clean separation between tool execution logs and renderable UI specs
--
-- The existing content_type column (String) already supports these values.
-- This migration is idempotent and safe to run multiple times.

-- Create a view for efficient querying of render entries
-- This view provides easy access to all render entries with their metadata
CREATE VIEW IF NOT EXISTS render_entries AS
SELECT
    session_id,
    trace_id,
    parent_id,
    timestamp_iso,
    cascade_id,
    cell_name,
    content_type,
    content_json,
    metadata_json,
    candidate_index,
    role,
    node_type,
    -- Extract screenshot path from metadata for convenience
    JSONExtractString(metadata_json, 'screenshot_path') AS screenshot_path,
    JSONExtractString(metadata_json, 'screenshot_url') AS screenshot_url,
    JSONExtractString(metadata_json, 'checkpoint_id') AS checkpoint_id
FROM unified_logs
WHERE content_type LIKE 'render:%'
ORDER BY timestamp_iso DESC;

-- Create a view specifically for request_decision renders
-- This provides direct access to all request_decision UI specs
CREATE VIEW IF NOT EXISTS request_decision_renders AS
SELECT
    session_id,
    trace_id,
    timestamp_iso,
    cascade_id,
    cell_name,
    content_json AS ui_spec,
    JSONExtractString(metadata_json, 'screenshot_path') AS screenshot_path,
    JSONExtractString(metadata_json, 'screenshot_url') AS screenshot_url,
    JSONExtractString(metadata_json, 'checkpoint_id') AS checkpoint_id,
    JSONExtractString(metadata_json, 'question') AS question,
    JSONExtractString(metadata_json, 'severity') AS severity,
    JSONExtractBool(metadata_json, 'has_html') AS has_html,
    JSONExtractInt(metadata_json, 'options_count') AS options_count,
    candidate_index
FROM unified_logs
WHERE content_type = 'render:request_decision'
ORDER BY timestamp_iso DESC;

-- Verify the views were created
SELECT
    name,
    engine
FROM system.tables
WHERE database = currentDatabase()
  AND name IN ('render_entries', 'request_decision_renders');

-- Sample query: Get recent request_decision renders with screenshots
-- SELECT * FROM request_decision_renders WHERE screenshot_path IS NOT NULL LIMIT 10;
