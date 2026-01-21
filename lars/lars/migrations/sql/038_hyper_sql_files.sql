-- Migration: 038_hyper_sql_files
-- Description: Create hyper_sql_files table for saved Hyper SQL queries
-- Author: LARS
-- Date: 2026-01-21

-- =============================================================================
-- hyper_sql_files: Stores saved SQL queries for the Hyper SQL client
-- =============================================================================
-- Enables saving and loading SQL queries with metadata like:
-- - Name and description for organization
-- - Database context for proper execution
-- - Favorites for quick access
-- - Timestamps for sorting by recency

CREATE TABLE IF NOT EXISTS hyper_sql_files (
    -- Primary identification
    id String,

    -- File metadata
    name String,
    sql String CODEC(ZSTD(3)),
    description Nullable(String),

    -- Execution context
    database LowCardinality(String) DEFAULT 'memory',

    -- Organization
    is_favorite Bool DEFAULT false,

    -- Timestamps
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Indexes for common query patterns
    INDEX idx_name name TYPE tokenbf_v1(512, 3, 0) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1,
    INDEX idx_favorite is_favorite TYPE set(2) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (id)
SETTINGS index_granularity = 8192;
