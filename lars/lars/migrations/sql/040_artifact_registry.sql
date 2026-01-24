-- Migration: 040_artifact_registry
-- Description: Create artifact_registry table for versioned cascade/skill/tool storage with distributed sync
-- Author: LARS
-- Date: 2026-01-23

CREATE TABLE IF NOT EXISTS artifact_registry (
    -- Identity
    artifact_id String,
    artifact_type Enum8('cascade' = 1, 'skill' = 2, 'tool' = 3, 'validator' = 4, 'cell_type' = 5),
    version UInt64,

    -- Content (unified storage for YAML-based artifacts)
    content_yaml Nullable(String) CODEC(ZSTD(3)),
    content_parsed String CODEC(ZSTD(3)),  -- JSON of parsed structure (CascadeConfig, ToolDef, etc.)
    content_hash FixedString(32),  -- MD5 of content for deduplication

    -- Python-based artifacts (skills registered via @create_eddy)
    python_module Nullable(String),  -- e.g., 'lars.skills.sql'
    python_function Nullable(String),  -- e.g., 'smart_sql_run'
    python_source Nullable(String) CODEC(ZSTD(3)),  -- Source code for inspection

    -- File metadata
    source_file String,  -- Original file path (or 'builtin_seed' for seeded)
    file_mtime DateTime64(3),  -- File modification time
    folder_path String,  -- Relative path from root (e.g., 'semantic_sql/aggregates')
    tags Array(String),  -- Extracted from folder hierarchy

    -- Lifecycle tracking
    created_at DateTime64(3) DEFAULT now64(3),
    created_by String DEFAULT 'system',  -- 'system', 'file_watcher', 'api', 'user_id'
    source_instance String DEFAULT '',  -- hostname:pid that created this version
    is_active Bool DEFAULT true,  -- Current active version
    is_deleted Bool DEFAULT false,  -- Soft delete marker

    -- Change tracking
    change_type Enum8('seed' = 1, 'create' = 2, 'update' = 3, 'delete' = 4, 'restore' = 5),
    change_comment String DEFAULT '',  -- Optional note for API/UI updates

    -- Conflict tracking
    has_conflict Bool DEFAULT false,
    conflict_resolved_at Nullable(DateTime64(3)),

    -- Indexes for fast lookups
    INDEX idx_active (is_active, is_deleted) TYPE minmax GRANULARITY 1,
    INDEX idx_type artifact_type TYPE minmax GRANULARITY 1,
    INDEX idx_tags tags TYPE bloom_filter GRANULARITY 1,
    INDEX idx_hash content_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_instance source_instance TYPE bloom_filter GRANULARITY 1,
    INDEX idx_folder folder_path TYPE bloom_filter GRANULARITY 1

) ENGINE = ReplacingMergeTree(version)
ORDER BY (artifact_type, artifact_id)
PARTITION BY artifact_type
SETTINGS index_granularity = 8192;


-- View for querying current active artifacts (most common use case)
-- ReplacingMergeTree with FINAL gives us the latest version automatically
CREATE VIEW IF NOT EXISTS artifact_registry_current AS
SELECT
    artifact_id,
    artifact_type,
    version,
    content_yaml,
    content_parsed,
    content_hash,
    python_module,
    python_function,
    python_source,
    source_file,
    file_mtime,
    folder_path,
    tags,
    created_at,
    created_by,
    source_instance,
    is_active,
    is_deleted,
    change_type,
    change_comment
FROM artifact_registry
FINAL
WHERE is_active = true AND is_deleted = false;


-- Conflict log table
CREATE TABLE IF NOT EXISTS cascade_conflicts (
    -- Identity
    conflict_id UUID DEFAULT generateUUIDv4(),
    artifact_id String,
    artifact_type LowCardinality(String),

    -- Version info
    version_local UInt64,
    version_remote UInt64,
    hash_local FixedString(32),
    hash_remote FixedString(32),

    -- Instance tracking
    instance_id String,
    detected_at DateTime64(3) DEFAULT now64(3),

    -- Resolution
    resolved_at Nullable(DateTime64(3)),
    resolution_strategy LowCardinality(Nullable(String)),  -- 'keep_local', 'keep_remote', 'manual_merge'
    resolved_by Nullable(String),  -- User or instance that resolved

    -- Indexes
    INDEX idx_artifact artifact_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_resolved resolved_at TYPE minmax GRANULARITY 1

) ENGINE = MergeTree()
ORDER BY (detected_at, artifact_id)
PARTITION BY toYYYYMM(detected_at)
TTL detected_at + INTERVAL 1 YEAR;
