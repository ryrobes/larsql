-- Migration: 027_add_missing_unified_logs_columns
-- Description: Add missing columns to unified_logs for genus_hash, content_type, TOON telemetry, and data shape
-- Author: LARS
-- Date: 2026-01-15
--
-- This migration adds columns that are expected by unified_logs.py but were not in the original schema.
-- These columns enable:
-- - genus_hash: Cascade-level identity for trending and analytics
-- - content_type: Content classification for filtering and specialized rendering
-- - TOON telemetry: Token savings tracking for data encoding optimization
-- - Data shape: Rows/columns tracking for analytics

-- Add genus_hash (cascade invocation identity)
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS genus_hash Nullable(String) AFTER species_hash;

-- Add index for genus_hash
ALTER TABLE unified_logs
ADD INDEX IF NOT EXISTS idx_genus_hash genus_hash TYPE bloom_filter GRANULARITY 1;

-- Add content_type for content classification
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS content_type LowCardinality(Nullable(String)) AFTER metadata_json;

-- Add index for content_type
ALTER TABLE unified_logs
ADD INDEX IF NOT EXISTS idx_content_type content_type TYPE set(100) GRANULARITY 1;

-- Add TOON telemetry columns (for tracking token savings from data encoding)
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS data_format LowCardinality(Nullable(String)) AFTER content_type;

ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS data_size_json Nullable(Int32) AFTER data_format;

ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS data_size_toon Nullable(Int32) AFTER data_size_json;

ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS data_token_savings_pct Nullable(Float32) AFTER data_size_toon;

ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS toon_encoding_ms Nullable(Float32) AFTER data_token_savings_pct;

ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS toon_decode_attempted Nullable(Bool) AFTER toon_encoding_ms;

ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS toon_decode_success Nullable(Bool) AFTER toon_decode_attempted;

-- Add data shape columns (for analytics on data volume)
ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS data_rows Nullable(Int32) AFTER toon_decode_success;

ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS data_columns Nullable(Int32) AFTER data_rows;

-- Verify columns were added (this will show in migration output)
-- SELECT name, type FROM system.columns WHERE table = 'unified_logs' AND database = currentDatabase() AND name IN ('genus_hash', 'content_type', 'data_format', 'data_size_json', 'data_size_toon', 'data_token_savings_pct', 'toon_encoding_ms', 'toon_decode_attempted', 'toon_decode_success', 'data_rows', 'data_columns');
