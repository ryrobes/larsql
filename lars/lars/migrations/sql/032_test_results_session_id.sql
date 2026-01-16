-- Migration: Add missing columns to test_results table
-- These columns support session linking, visual regression, and baseline comparison

ALTER TABLE test_results ADD COLUMN IF NOT EXISTS session_id String DEFAULT '';
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS previous_session_id String DEFAULT '';
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS overall_score Nullable(Float32);
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS is_baseline UInt8 DEFAULT 0;
ALTER TABLE test_results ADD COLUMN IF NOT EXISTS screenshots_compared String DEFAULT '';
