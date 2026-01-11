-- Migration: 018_tag_definitions
-- Description: Create tag_definitions table - tag metadata for output tagging system
-- Author: RVBBIT
-- Date: 2026-01-10

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
