-- Migration: 036_deref_log
-- Description: Create deref_log table for tracking @cascade() expression evaluations
-- Author: LARS
-- Date: 2026-01-21

-- =============================================================================
-- deref_log: Tracks @cascade() expression evaluations during SQL preprocessing
-- =============================================================================
-- Records each deref operation to enable:
-- - Debugging: See what values were injected into queries
-- - Analytics: Track usage patterns of param_get/param_set/etc.
-- - UI surfacing: Show deref values alongside query results
-- - Audit trail: Know which sessions/clients are using what parameters

CREATE TABLE IF NOT EXISTS deref_log (
    -- Deref identification
    deref_id String DEFAULT generateUUIDv4(),

    -- The deref expression as written in SQL
    -- e.g., '@param_get(''region'', ''ALL'')' or '@params_get(''selected_items'')[*].id'
    deref_expression String,

    -- Parsed components
    cascade_name LowCardinality(String),      -- e.g., 'param_get', 'params_set'
    args_json String CODEC(ZSTD(3)),          -- JSON array of parsed arguments
    accessor_chain String DEFAULT '',          -- e.g., '[0].field' or '[*].name'

    -- Resolved value
    resolved_value String CODEC(ZSTD(3)),     -- The SQL-escaped value that was injected
    resolved_value_type LowCardinality(String), -- 'string', 'number', 'boolean', 'null', 'array', 'object'

    -- Execution metadata
    cache_hit Bool DEFAULT false,              -- Was this served from per-query cache?
    duration_ms Float32 DEFAULT 0,             -- Time to resolve (excluding cache)
    error_message String DEFAULT '',           -- Error if resolution failed (empty = success)

    -- Session/client identification
    session_id String,
    protocol LowCardinality(String) DEFAULT 'pgwire',  -- 'pgwire' or 'http'
    database_name String DEFAULT '',
    user_name String DEFAULT '',
    application_name String DEFAULT '',
    client_address String DEFAULT '',          -- IP:port
    caller_id Nullable(String),                -- Pipeline caller ID if available

    -- Timestamp
    created_at DateTime64(3) DEFAULT now64(),

    -- Indexes for common query patterns
    INDEX idx_session session_id TYPE set(10000) GRANULARITY 1,
    INDEX idx_cascade cascade_name TYPE set(50) GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1,
    INDEX idx_protocol protocol TYPE set(10) GRANULARITY 1,
    INDEX idx_error error_message TYPE tokenbf_v1(10240, 3, 0) GRANULARITY 1
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (session_id, created_at, deref_id)
TTL created_at + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
