-- Migration: 000_schema_migrations
-- Description: Create schema_migrations table for tracking database migrations
-- Author: RVBBIT
-- Date: 2026-01-10

-- This is the bootstrap migration that creates the tracking table itself.
-- It must be idempotent since it may run before any tracking is possible.

CREATE TABLE IF NOT EXISTS schema_migrations (
    -- Identity
    version UInt32,
    name String,
    description String,

    -- Execution tracking
    checksum String,
    executed_at DateTime64(3) DEFAULT now64(3),
    execution_time_ms UInt32 DEFAULT 0,

    -- Status
    status Enum8('pending' = 1, 'applied' = 2, 'failed' = 3, 'rolled_back' = 4),

    -- Metadata
    author Nullable(String),
    migration_date Nullable(String),
    always_run Bool DEFAULT false,

    -- Error tracking
    error_message Nullable(String),

    -- Indexes
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_executed executed_at TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(executed_at)
ORDER BY (version)
SETTINGS index_granularity = 8192;
