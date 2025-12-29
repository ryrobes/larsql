-- Migration: Create output_tags and tag_definitions tables
-- Date: 2025-12-29
-- Description: Adds tagging system for outputs with support for instance and dynamic tags
--
-- Tag Modes:
-- - instance: Tags a specific message_id (frozen snapshot)
-- - dynamic: Tags latest output from cascade+cell combo (auto-updates)
--
-- This enables:
-- - Filtering outputs by tags in the UI
-- - Marking outputs for review/approval/production
-- - Creating dynamic dashboards that always show latest tagged outputs

-- Create tag_definitions table (stores tag metadata)
-- Uses ReplacingMergeTree for upsert semantics on tag updates
CREATE TABLE IF NOT EXISTS tag_definitions (
    tag_name String,
    tag_color String DEFAULT '#a78bfa',
    description Nullable(String),
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Indexes
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY tag_name;

-- Create output_tags table (cross-walk between tags and outputs)
-- Uses MergeTree since we need to support multiple tags per output
CREATE TABLE IF NOT EXISTS output_tags (
    -- Identity
    tag_id UUID DEFAULT generateUUIDv4(),
    tag_name String,

    -- Tag Mode: instance = specific message, dynamic = latest from cascade+cell
    tag_mode Enum8('instance' = 1, 'dynamic' = 2),

    -- Instance Mode: points to specific message
    message_id Nullable(UUID),

    -- Dynamic Mode: points to latest output from cascade+cell
    cascade_id Nullable(String),
    cell_name Nullable(String),

    -- Metadata
    created_at DateTime64(3) DEFAULT now64(3),
    created_by Nullable(String),
    note Nullable(String),

    -- Indexes for common query patterns
    INDEX idx_tag_name tag_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_message_id message_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell_name cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_tag_mode tag_mode TYPE set(2) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (tag_name, created_at)
PARTITION BY toYYYYMM(created_at);

-- Insert some default tags for common use cases
INSERT INTO tag_definitions (tag_name, tag_color, description) VALUES
    ('approved', '#34d399', 'Approved for production use'),
    ('review', '#fbbf24', 'Needs human review'),
    ('favorite', '#f472b6', 'Marked as favorite'),
    ('production', '#60a5fa', 'Currently used in production')
ON DUPLICATE KEY UPDATE updated_at = now64(3);

-- Verify the tables were created
SELECT
    name,
    engine,
    partition_key,
    sorting_key
FROM system.tables
WHERE database = currentDatabase()
  AND name IN ('tag_definitions', 'output_tags');
