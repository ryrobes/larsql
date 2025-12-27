-- Migration: Create cell_context_breakdown table
-- Date: 2025-12-27
-- Purpose: Granular per-message context attribution for pinpointing bloat sources
--
-- Background:
-- While cell_analytics tells us "Cell X has 76% context cost", it doesn't tell us
-- WHICH specific messages in the context are causing the bloat.
--
-- This table provides message-level attribution:
-- - Which message contributed 42% of the context cost?
-- - Which cell produced the bloated message?
-- - Should we exclude this message from future context?
--
-- Example insights:
-- - "Message ABC123 from cell 'research' contributes 200 tokens (42% of cell cost)"
-- - "Removing the 'analyze' cell output from context saves 31%"
-- - "Top 3 context messages account for 85% of context cost"

CREATE TABLE IF NOT EXISTS cell_context_breakdown (
    -- ============================================
    -- IDENTITY
    -- ============================================
    session_id String,
    cascade_id String,
    cell_name String,                       -- Cell being analyzed
    cell_index UInt8,                       -- Position in cascade

    -- ============================================
    -- CONTEXT MESSAGE IDENTITY
    -- ============================================
    context_message_hash String,            -- content_hash of injected message
    context_message_cell String,            -- Which cell produced this message
    context_message_role LowCardinality(String),  -- Role of context message (user/assistant)
    context_message_index UInt8,            -- Order in context array (0, 1, 2...)

    -- ============================================
    -- TOKEN/COST ATTRIBUTION
    -- ============================================
    context_message_tokens UInt32,          -- Tokens from this specific message
    context_message_cost_estimated Float64, -- Estimated cost of this message
    context_message_pct Float32,            -- % of total cell cost from this message

    -- ============================================
    -- AGGREGATE CONTEXT
    -- ============================================
    total_context_messages UInt8,           -- Total messages in context for this cell
    total_context_tokens UInt32,            -- Total context tokens
    total_cell_cost Float64,                -- Total cell cost (for %)

    -- ============================================
    -- METADATA
    -- ============================================
    created_at DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (session_id, cell_name, context_message_index)
PARTITION BY toYYYYMM(created_at);

-- Indexes for quick queries
ALTER TABLE cell_context_breakdown ADD INDEX IF NOT EXISTS idx_session session_id TYPE bloom_filter GRANULARITY 1;
ALTER TABLE cell_context_breakdown ADD INDEX IF NOT EXISTS idx_cell cell_name TYPE bloom_filter GRANULARITY 1;
ALTER TABLE cell_context_breakdown ADD INDEX IF NOT EXISTS idx_source_cell context_message_cell TYPE bloom_filter GRANULARITY 1;

-- This enables queries like:
-- 1. "Which messages contribute most to cell X's context cost?"
--    SELECT * FROM cell_context_breakdown WHERE cell_name = 'summarize' ORDER BY context_message_pct DESC
--
-- 2. "Which cells produce bloated outputs that cost downstream?"
--    SELECT context_message_cell, SUM(context_message_cost_estimated) FROM cell_context_breakdown GROUP BY context_message_cell
--
-- 3. "Top 3 context messages causing 80% of cost"
--    SELECT * FROM cell_context_breakdown WHERE session_id = ? ORDER BY context_message_pct DESC LIMIT 3
