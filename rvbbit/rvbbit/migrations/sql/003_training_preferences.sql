-- Migration: 003_training_preferences
-- Description: Create training_preferences table - DPO/RLHF training data
-- Author: RVBBIT
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS training_preferences (
    -- Identity
    id String,
    created_at DateTime64(3) DEFAULT now64(3),

    -- Source tracking (for deduplication and provenance)
    session_id String,
    cascade_id String,
    cell_name String,
    checkpoint_id String,

    -- Prompt context (reconstructed for training)
    prompt_text String,
    prompt_messages String,
    system_prompt String,

    -- Preference type
    preference_type Enum8('pairwise' = 1, 'ranking' = 2, 'rating' = 3),

    -- Pairwise preferences (most common, used by DPO)
    chosen_response String,
    rejected_response String,
    chosen_model Nullable(String),
    rejected_model Nullable(String),
    chosen_cost Nullable(Float64),
    rejected_cost Nullable(Float64),
    chosen_tokens Nullable(Int32),
    rejected_tokens Nullable(Int32),
    margin Float32 DEFAULT 1.0,

    -- Ranking preferences (full ordering)
    all_responses Nullable(String),
    ranking_order Nullable(String),
    num_responses Nullable(Int32),

    -- Rating preferences (scored)
    ratings_json Nullable(String),
    rating_scale_max Nullable(Int32),

    -- Human signal
    human_reasoning Nullable(String),
    human_confidence Nullable(Float32),

    -- Mutation/model metadata
    chosen_mutation Nullable(String),
    rejected_mutation Nullable(String),
    model_comparison Bool DEFAULT false,

    -- Quality flags
    reasoning_quality Nullable(Float32),
    is_tie Bool DEFAULT false,
    is_rejection Bool DEFAULT false,

    -- Indexes
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_pref_type preference_type TYPE set(10) GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (created_at, session_id, preference_type)
PARTITION BY toYYYYMM(created_at);
