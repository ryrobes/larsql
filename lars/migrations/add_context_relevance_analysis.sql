-- Add context relevance analysis fields to cell_context_breakdown table
--
-- This enables tracking which context messages were actually useful in generating outputs.
-- A cheap LLM analyzes each message's contribution and scores its relevance (0-100).
--
-- Use case: Identify low-value, high-cost context that can be removed to save money.

-- Relevance score from LLM analysis (0-100)
-- Higher = more important/used in generating the response
ALTER TABLE cell_context_breakdown
ADD COLUMN IF NOT EXISTS relevance_score Nullable(Float32);

-- Why the LLM gave this score (human-readable explanation)
ALTER TABLE cell_context_breakdown
ADD COLUMN IF NOT EXISTS relevance_reasoning Nullable(String);

-- Cost of running the relevance analysis itself (meta-cost tracking!)
ALTER TABLE cell_context_breakdown
ADD COLUMN IF NOT EXISTS relevance_analysis_cost Nullable(Float64);

-- When the analysis was performed (different from created_at of the cell)
ALTER TABLE cell_context_breakdown
ADD COLUMN IF NOT EXISTS relevance_analyzed_at Nullable(DateTime);

-- Session ID of the relevance analysis cascade (for cost attribution)
ALTER TABLE cell_context_breakdown
ADD COLUMN IF NOT EXISTS relevance_analysis_session Nullable(String);
