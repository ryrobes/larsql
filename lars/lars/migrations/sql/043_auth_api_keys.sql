-- Migration: 043_auth_api_keys
-- Description: Create auth_api_keys table - API keys for LARS authentication
-- Author: LARS
-- Date: 2026-01-26

CREATE TABLE IF NOT EXISTS auth_api_keys (
    -- Identity
    key_id String,
    user_id String,

    -- Key data (we store hash for revocation lookup, prefix for display)
    key_hash String,
    key_prefix String,

    -- Metadata
    name String,
    scopes Array(String) DEFAULT [],

    -- Status
    is_active Bool DEFAULT true,
    expires_at Nullable(DateTime64(3)),

    -- Usage tracking
    last_used_at Nullable(DateTime64(3)),
    use_count UInt64 DEFAULT 0,
    last_used_ip Nullable(String),

    -- Audit
    created_at DateTime64(3) DEFAULT now64(3),
    created_by_ip Nullable(String),
    revoked_at Nullable(DateTime64(3)),
    revoked_reason Nullable(String),

    -- Indexes
    INDEX idx_user user_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_active is_active TYPE set(2) GRANULARITY 1,
    INDEX idx_key_hash key_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_key_prefix key_prefix TYPE set(1000) GRANULARITY 1,
    INDEX idx_expires expires_at TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (key_id)
SETTINGS index_granularity = 8192;
