-- Migration: 017_hf_spaces
-- Description: Create hf_spaces table - Harbor system cache for HuggingFace Spaces
-- Author: LARS
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS hf_spaces (
    -- Core Identity
    space_id String,
    author String,
    space_name String,

    -- Status & Runtime
    status LowCardinality(String),
    hardware LowCardinality(Nullable(String)),
    sdk LowCardinality(Nullable(String)),

    -- Cost Information
    hourly_cost Nullable(Float64),
    is_billable Bool DEFAULT false,
    is_callable Bool DEFAULT false,

    -- API Schema (cached introspection)
    endpoints_json Nullable(String),

    -- Metadata
    private Bool DEFAULT false,
    space_url String DEFAULT '',
    sleep_time Nullable(Int32),
    requested_hardware Nullable(String),

    -- Tracking Timestamps
    first_seen DateTime64(3) DEFAULT now64(3),
    last_seen DateTime64(3) DEFAULT now64(3),
    last_refreshed DateTime64(3) DEFAULT now64(3),

    -- Usage Stats (computed from unified_logs)
    total_invocations Nullable(UInt64) DEFAULT 0,
    last_invocation Nullable(DateTime64(3)),

    -- Indexes
    INDEX idx_space_id space_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_author author TYPE bloom_filter GRANULARITY 1,
    INDEX idx_status status TYPE set(10) GRANULARITY 1,
    INDEX idx_hardware hardware TYPE set(50) GRANULARITY 1,
    INDEX idx_sdk sdk TYPE set(10) GRANULARITY 1,
    INDEX idx_is_billable is_billable TYPE set(2) GRANULARITY 1,
    INDEX idx_is_callable is_callable TYPE set(2) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(last_refreshed)
ORDER BY (space_id);
