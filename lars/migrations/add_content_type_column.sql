-- Migration: Add content_type column to unified_logs table
-- Date: 2025-12-29
-- Description: Adds content_type column for semantic classification of message content
--
-- Content types are hierarchical:
-- - text: Plain text without special formatting
-- - markdown: Text with markdown syntax (headers, bold, lists, code blocks)
-- - json: Structured JSON data (objects/arrays)
-- - table: Tabular data with rows/columns
-- - image: Content with associated images
-- - chart: Visualization data (plotly, etc.)
-- - tool_call: LLM tool invocation (with sub-type like tool_call:request_decision)
-- - error: Error message
--
-- This enables:
-- - Server-side filtering by content type
-- - Analytics on content composition
-- - Specialized rendering in the UI

-- Add content_type column (nullable string, defaults to 'text')
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS content_type Nullable(String) DEFAULT 'text';

-- Add bloom filter index for fast content_type filtering
ALTER TABLE unified_logs
ADD INDEX IF NOT EXISTS idx_content_type content_type TYPE bloom_filter GRANULARITY 1;

-- Verify the changes
SELECT
    name,
    type,
    default_expression
FROM system.columns
WHERE table = 'unified_logs'
  AND database = currentDatabase()
  AND name = 'content_type';
