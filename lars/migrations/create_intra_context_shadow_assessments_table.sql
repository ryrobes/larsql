-- Migration: Create intra_context_shadow_assessments table
-- Date: 2025-12-30
-- Purpose: Shadow assessment of intra-cell context management across multiple config scenarios
--
-- Background:
-- Intra-cell context management controls HOW messages within a cell's turn loop are
-- compressed/masked. This is purely local computation (no LLM calls), so we can cheaply
-- evaluate many config scenarios to suggest optimal settings.
--
-- Config parameters we vary:
--   - window: [3, 5, 7, 10, 15] - turns to keep in full fidelity
--   - mask_observations_after: [2, 3, 5, 7] - when to start masking tool results
--   - min_masked_size: [100, 200, 500] - minimum chars before masking
--
-- This enables:
-- 1. Comparing token usage under different intra-context configs
-- 2. Suggesting optimal config based on actual execution patterns
-- 3. Understanding which messages contribute most to context bloat
--
-- Controlled by: LARS_SHADOW_ASSESSMENT_ENABLED (same as inter-cell)

CREATE TABLE IF NOT EXISTS intra_context_shadow_assessments (
    -- ============================================
    -- IDENTITY
    -- ============================================
    assessment_id UUID DEFAULT generateUUIDv4(),
    timestamp DateTime64(6) DEFAULT now64(6),

    -- Session context
    session_id String,
    cascade_id String,
    cell_name String,
    take_index Nullable(Int16),       -- NULL if not in takes, else 0, 1, 2...
    turn_number UInt16,                    -- Turn within this cell (0-indexed)
    is_loop_retry Bool DEFAULT false,      -- Is this a loop_until retry turn?

    -- ============================================
    -- CONFIG SCENARIO BEING EVALUATED
    -- ============================================
    config_window UInt8,                   -- window parameter value
    config_mask_after UInt8,               -- mask_observations_after parameter value
    config_min_masked_size UInt16,         -- min_masked_size parameter value
    config_compress_loops Bool,            -- compress_loops parameter value
    config_preserve_reasoning Bool,        -- preserve_reasoning parameter value
    config_preserve_errors Bool,           -- preserve_errors parameter value

    -- ============================================
    -- TURN-LEVEL AGGREGATE METRICS
    -- ============================================
    full_history_size UInt16,              -- Total messages before context building
    context_size UInt16,                   -- Messages after context building
    tokens_before UInt32,                  -- Estimated tokens before
    tokens_after UInt32,                   -- Estimated tokens after
    tokens_saved UInt32,                   -- tokens_before - tokens_after
    compression_ratio Float32,             -- tokens_after / tokens_before
    messages_masked UInt16,                -- Count of masked messages
    messages_preserved UInt16,             -- Count of preserved messages
    messages_truncated UInt16,             -- Count of truncated messages

    -- ============================================
    -- PER-MESSAGE BREAKDOWN (JSON array)
    -- ============================================
    -- Each entry: {msg_index, role, original_tokens, action, result_tokens, reason}
    -- action: "keep" | "mask" | "truncate" | "exclude"
    message_breakdown String DEFAULT '[]',

    -- ============================================
    -- COMPARISON FLAGS (vs baseline/actual)
    -- ============================================
    -- Baseline = disabled (keep everything)
    tokens_vs_baseline_saved UInt32,       -- How much this config saves vs disabled
    tokens_vs_baseline_pct Float32,        -- Percentage saved vs disabled

    -- Actual = what config was actually used (if any)
    actual_config_enabled Bool,            -- Was intra-context enabled for this turn?
    actual_tokens_after Nullable(UInt32),  -- What tokens_after was in actual execution
    differs_from_actual Bool,              -- Would this config produce different result?

    -- ============================================
    -- ASSESSMENT METADATA
    -- ============================================
    assessment_batch_id String,            -- Groups assessments from same turn

    -- ============================================
    -- INDEXES
    -- ============================================
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_take take_index TYPE set(100) GRANULARITY 1,
    INDEX idx_turn turn_number TYPE set(100) GRANULARITY 1,
    INDEX idx_batch assessment_batch_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_compression compression_ratio TYPE minmax GRANULARITY 1,
    INDEX idx_window config_window TYPE set(20) GRANULARITY 1,
    INDEX idx_mask_after config_mask_after TYPE set(20) GRANULARITY 1
)
ENGINE = MergeTree()
ORDER BY (session_id, cell_name, turn_number, config_window, config_mask_after)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;

-- ============================================
-- USEFUL QUERIES
-- ============================================
--
-- 1. "Best config for this cascade (most token savings)"
--    SELECT config_window, config_mask_after, config_min_masked_size,
--           AVG(compression_ratio) as avg_compression,
--           SUM(tokens_saved) as total_tokens_saved
--    FROM intra_context_shadow_assessments
--    WHERE session_id = 'X'
--    GROUP BY config_window, config_mask_after, config_min_masked_size
--    ORDER BY total_tokens_saved DESC
--    LIMIT 5
--
-- 2. "Token savings by cell"
--    SELECT cell_name, config_window, config_mask_after,
--           SUM(tokens_saved) as tokens_saved,
--           AVG(compression_ratio) as avg_compression
--    FROM intra_context_shadow_assessments
--    WHERE session_id = 'X' AND config_window = 5 AND config_mask_after = 3
--    GROUP BY cell_name, config_window, config_mask_after
--    ORDER BY tokens_saved DESC
--
-- 3. "Compare configs for high-turn cells"
--    SELECT config_window, config_mask_after,
--           AVG(tokens_saved) as avg_saved,
--           MAX(turn_number) as max_turns
--    FROM intra_context_shadow_assessments
--    WHERE turn_number >= 5
--    GROUP BY config_window, config_mask_after
--    ORDER BY avg_saved DESC
--
-- 4. "Take comparison - which take had most bloat?"
--    SELECT take_index, cell_name,
--           SUM(tokens_before) as total_tokens,
--           AVG(compression_ratio) as avg_compression
--    FROM intra_context_shadow_assessments
--    WHERE session_id = 'X' AND config_window = 5
--    GROUP BY take_index, cell_name
--    ORDER BY total_tokens DESC
