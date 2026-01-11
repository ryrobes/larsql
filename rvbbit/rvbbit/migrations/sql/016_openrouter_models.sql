-- Migration: 016_openrouter_models
-- Description: Create openrouter_models table - model verification and caching
-- Author: RVBBIT
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS openrouter_models (
    -- Core Identity
    model_id String,
    model_name String,
    provider String,

    -- Metadata
    description String DEFAULT '',
    context_length UInt32 DEFAULT 0,

    -- Classification
    tier LowCardinality(String),
    popular Bool DEFAULT false,
    model_type LowCardinality(String),

    -- Capabilities (from architecture.modality)
    input_modalities Array(String) DEFAULT [],
    output_modalities Array(String) DEFAULT [],

    -- Pricing (per token)
    prompt_price Float64 DEFAULT 0,
    completion_price Float64 DEFAULT 0,

    -- Availability
    is_active Bool DEFAULT true,
    last_verified DateTime64(3) DEFAULT now64(3),
    verification_error Nullable(String),

    -- Timestamps
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3),

    -- Additional metadata (JSON blob for extensibility)
    metadata_json String DEFAULT '{}',

    -- Indexes
    INDEX idx_provider provider TYPE bloom_filter GRANULARITY 1,
    INDEX idx_tier tier TYPE set(10) GRANULARITY 1,
    INDEX idx_model_type model_type TYPE set(10) GRANULARITY 1,
    INDEX idx_is_active is_active TYPE set(2) GRANULARITY 1,
    INDEX idx_popular popular TYPE set(2) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (model_id)
PARTITION BY model_type;
