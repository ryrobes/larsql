-- Migration: Add inference type fields to openrouter_models
-- This helps track which models support on-demand vs require inference profiles
-- Especially important for AWS Bedrock where some models need inference profiles

-- Add inference_type column (ON_DEMAND, PROVISIONED, INFERENCE_PROFILE)
ALTER TABLE openrouter_models
    ADD COLUMN IF NOT EXISTS inference_type LowCardinality(String) DEFAULT 'ON_DEMAND';

-- Add is_inference_profile flag
ALTER TABLE openrouter_models
    ADD COLUMN IF NOT EXISTS is_inference_profile Bool DEFAULT false;

-- Add index for inference_type
ALTER TABLE openrouter_models
    ADD INDEX IF NOT EXISTS idx_inference_type inference_type TYPE set(10) GRANULARITY 1;
