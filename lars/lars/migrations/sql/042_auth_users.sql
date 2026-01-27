-- Migration: 042_auth_users
-- Description: Create auth_users table - user accounts for LARS authentication
-- Author: LARS
-- Date: 2026-01-26

CREATE TABLE IF NOT EXISTS auth_users (
    -- Identity
    user_id String,
    username String,
    email Nullable(String),
    display_name Nullable(String),

    -- Local auth (for username/password login)
    password_hash Nullable(String),

    -- Status
    is_active Bool DEFAULT true,
    is_admin Bool DEFAULT false,

    -- OAuth (for future extensibility - Google, GitHub, SSO)
    oauth_provider LowCardinality(Nullable(String)),
    oauth_subject Nullable(String),

    -- Timing
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),
    last_login_at Nullable(DateTime64(3)),

    -- Metadata (JSON for extensible fields)
    metadata_json String DEFAULT '{}' CODEC(ZSTD(3)),

    -- Indexes
    INDEX idx_username username TYPE bloom_filter GRANULARITY 1,
    INDEX idx_email email TYPE bloom_filter GRANULARITY 1,
    INDEX idx_active is_active TYPE set(2) GRANULARITY 1,
    INDEX idx_oauth oauth_provider TYPE set(20) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_id)
SETTINGS index_granularity = 8192;
