-- Migration: 006_evaluations
-- Description: Create evaluations table - Hot-or-Not ratings system
-- Author: LARS
-- Date: 2026-01-10

CREATE TABLE IF NOT EXISTS evaluations (
    id UUID DEFAULT generateUUIDv4(),
    created_at DateTime64(3) DEFAULT now64(3),

    -- Source context
    session_id String,
    cell_name String,
    take_index Int32,

    -- Evaluation
    evaluation_type Enum8('rating' = 0, 'preference' = 1, 'flag' = 2),
    rating Nullable(Float32),
    preferred_index Nullable(Int32),
    flag_reason Nullable(String),

    -- Evaluator
    evaluator_id Nullable(String),
    evaluator_type Enum8('human' = 0, 'model' = 1) DEFAULT 'human',

    -- Indexes
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_created created_at TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (created_at, session_id)
PARTITION BY toYYYYMM(created_at);
