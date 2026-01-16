-- Migration: Add model_requested column to unified_logs
-- Purpose: Store the originally requested model name separately from the resolved model name
--
-- Background:
-- When calling OpenRouter, users specify a model like "openai/gpt-4.1" but the API
-- may return the actual versioned model like "openai/gpt-4.1-2025-04-14".
-- Previously we only stored the resolved name, which made aggregation noisy.
--
-- Now we store both:
-- - model: The resolved/actual model name (what really ran)
-- - model_requested: The originally requested model name (what config specified)
--
-- This allows:
-- - Clean aggregation by model_requested for visualization
-- - Precise tracking via model for debugging/cost accuracy
-- - Model drift detection by comparing both fields

ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS model_requested Nullable(String) AFTER model;

-- For backward compatibility, existing rows will have model_requested = NULL
-- Queries should use: COALESCE(model_requested, model) as display_model
