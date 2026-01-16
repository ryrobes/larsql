-- Migration: Add Context Attribution Columns
-- Date: 2025-12-27
-- Purpose: Expose hidden costs from context injection
--
-- Background:
-- LARS's unique context_hashes tracking enables decomposing LLM costs into:
-- 1. Context cost (tokens from injected previous messages)
-- 2. New message cost (tokens from THIS cell's work)
--
-- This is CRITICAL because context often accounts for 60-80% of LLM costs,
-- but is completely invisible in traditional metrics!
--
-- Example:
--   Cell 'enrich' appears expensive at $0.015
--   BUT: $0.012 (80%) is context injection from 5 previous messages
--        $0.003 (20%) is the actual new work
--   Insight: Not a slow cell, just heavy context!
--   Action: Use selective context to save 60%

-- ============================================
-- CELL ANALYTICS - Context Attribution
-- ============================================

-- Context token counts
ALTER TABLE cell_analytics ADD COLUMN IF NOT EXISTS context_token_count UInt32 DEFAULT 0;
ALTER TABLE cell_analytics ADD COLUMN IF NOT EXISTS new_message_tokens UInt32 DEFAULT 0;

-- Context message tracking
ALTER TABLE cell_analytics ADD COLUMN IF NOT EXISTS context_message_count UInt8 DEFAULT 0;
ALTER TABLE cell_analytics ADD COLUMN IF NOT EXISTS has_context Bool DEFAULT false;

-- Context depth (messages per LLM call)
ALTER TABLE cell_analytics ADD COLUMN IF NOT EXISTS context_depth_avg Float32 DEFAULT 0;
ALTER TABLE cell_analytics ADD COLUMN IF NOT EXISTS context_depth_max UInt8 DEFAULT 0;

-- Cost attribution (the key insight!)
ALTER TABLE cell_analytics ADD COLUMN IF NOT EXISTS context_cost_estimated Float64 DEFAULT 0;
ALTER TABLE cell_analytics ADD COLUMN IF NOT EXISTS new_message_cost_estimated Float64 DEFAULT 0;
ALTER TABLE cell_analytics ADD COLUMN IF NOT EXISTS context_cost_pct Float32 DEFAULT 0;

-- ============================================
-- CASCADE ANALYTICS - Context Attribution Rollup
-- ============================================

-- Cascade-level context aggregates
ALTER TABLE cascade_analytics ADD COLUMN IF NOT EXISTS total_context_tokens UInt32 DEFAULT 0;
ALTER TABLE cascade_analytics ADD COLUMN IF NOT EXISTS total_new_tokens UInt32 DEFAULT 0;
ALTER TABLE cascade_analytics ADD COLUMN IF NOT EXISTS total_context_cost_estimated Float64 DEFAULT 0;
ALTER TABLE cascade_analytics ADD COLUMN IF NOT EXISTS total_new_cost_estimated Float64 DEFAULT 0;
ALTER TABLE cascade_analytics ADD COLUMN IF NOT EXISTS context_cost_pct Float32 DEFAULT 0;

-- Cell-level context statistics
ALTER TABLE cascade_analytics ADD COLUMN IF NOT EXISTS cells_with_context UInt8 DEFAULT 0;
ALTER TABLE cascade_analytics ADD COLUMN IF NOT EXISTS avg_cell_context_pct Float32 DEFAULT 0;
ALTER TABLE cascade_analytics ADD COLUMN IF NOT EXISTS max_cell_context_pct Float32 DEFAULT 0;

-- Indexes for context hotspot queries
ALTER TABLE cell_analytics ADD INDEX IF NOT EXISTS idx_has_context has_context TYPE set(0) GRANULARITY 1;
ALTER TABLE cell_analytics ADD INDEX IF NOT EXISTS idx_context_pct_high context_cost_pct TYPE minmax GRANULARITY 1;

-- Backward compatibility: Existing rows will have context metrics = 0/false
-- This correctly represents "no context analysis" for historical cells
