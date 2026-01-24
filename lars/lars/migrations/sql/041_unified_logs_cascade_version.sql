-- Migration: 041_unified_logs_cascade_version
-- Description: Add cascade_version column to unified_logs for audit trail linking
-- Author: LARS
-- Date: 2026-01-23

ALTER TABLE unified_logs
ADD COLUMN IF NOT EXISTS cascade_version Nullable(UInt64) AFTER cascade_id;
