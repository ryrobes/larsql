-- Migration: Create credit_snapshots table for OpenRouter credit tracking
-- Date: 2025-12-29
-- Purpose: Track OpenRouter account balance over time for cost analytics
--
-- Design: Headless-first - snapshots are logged by the runner on cascade
-- completion, so credit tracking works without any UI server running.
--
-- Snapshot triggers:
-- 1. Post-cascade completion (if data is stale or cost was significant)
-- 2. Manual refresh via API (when UI is available)
-- 3. Backend startup (when UI server starts)
--
-- Only logs when balance actually changes (per user requirement).

CREATE TABLE IF NOT EXISTS credit_snapshots (
    -- Timestamp of snapshot
    timestamp DateTime64(3) DEFAULT now64(3),

    -- ============================================
    -- OPENROUTER ACCOUNT STATE
    -- ============================================
    total_credits Float64,        -- Total credits ever purchased
    total_usage Float64,          -- Total credits consumed
    balance Float64,              -- Available credits (total - usage)

    -- ============================================
    -- CHANGE TRACKING
    -- ============================================
    delta Float64 DEFAULT 0,      -- Change since last snapshot (negative = spend)

    -- ============================================
    -- CONTEXT
    -- ============================================
    source LowCardinality(String), -- 'startup', 'post_cascade', 'poll', 'manual'
    cascade_id Nullable(String),   -- Which cascade triggered this snapshot
    session_id Nullable(String),   -- Which session triggered this snapshot

    -- ============================================
    -- COMPUTED METRICS (populated by analytics)
    -- ============================================
    burn_rate_1h Nullable(Float64),  -- $/hour over last hour
    burn_rate_24h Nullable(Float64), -- $/hour over last 24 hours
    burn_rate_7d Nullable(Float64)   -- $/hour over last 7 days
)
ENGINE = MergeTree()
ORDER BY (timestamp)
PARTITION BY toYYYYMM(timestamp);

-- Index for quick "latest snapshot" queries
ALTER TABLE credit_snapshots ADD INDEX IF NOT EXISTS idx_timestamp timestamp TYPE minmax GRANULARITY 1;

-- Index for source filtering (e.g., "show only post_cascade snapshots")
ALTER TABLE credit_snapshots ADD INDEX IF NOT EXISTS idx_source source TYPE set(0) GRANULARITY 1;
