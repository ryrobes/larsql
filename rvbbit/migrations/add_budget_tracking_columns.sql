-- Add token budget enforcement tracking columns to unified_logs
-- These columns track when context is pruned to stay within configured limits

ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS budget_strategy LowCardinality(Nullable(String));
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS budget_tokens_before Nullable(Int32);
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS budget_tokens_after Nullable(Int32);
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS budget_tokens_limit Nullable(Int32);
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS budget_tokens_pruned Nullable(Int32);
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS budget_percentage Nullable(Float32);
