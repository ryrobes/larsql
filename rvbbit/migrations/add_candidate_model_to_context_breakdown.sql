-- Add model_requested and candidate_index to cell_context_breakdown table
-- This allows tracking which candidate and model each context breakdown belongs to

ALTER TABLE cell_context_breakdown
ADD COLUMN IF NOT EXISTS model_requested String DEFAULT '';

ALTER TABLE cell_context_breakdown
ADD COLUMN IF NOT EXISTS candidate_index Nullable(Int32);
