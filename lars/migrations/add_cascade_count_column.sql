-- Migration: Add missing cascade_count column to sql_query_log
-- Date: 2026-01-02
-- Issue: cascade_count was defined in schema but never added to table
-- Impact: Enables cascade execution tracking for SQL queries

-- Add cascade_count column (safe - non-blocking ALTER in ClickHouse)
ALTER TABLE sql_query_log
ADD COLUMN IF NOT EXISTS cascade_count UInt16 DEFAULT 0
AFTER cascade_paths;

-- Verify column exists
-- Run: clickhouse-client --query "DESCRIBE TABLE sql_query_log" | grep cascade
