-- Migration: 048_runtime_event_log_connection_id
-- Description: Add connection_id to runtime_event_log for correlating per-connection lifecycles
-- Author: LARS
-- Date: 2026-01-29

ALTER TABLE runtime_event_log
    ADD COLUMN IF NOT EXISTS connection_id String DEFAULT '' AFTER timestamp_iso;

ALTER TABLE runtime_event_log
    ADD INDEX IF NOT EXISTS idx_connection connection_id TYPE bloom_filter GRANULARITY 1;

