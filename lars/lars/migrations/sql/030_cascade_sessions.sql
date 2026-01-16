-- Migration: 030_cascade_sessions
-- Description: Create cascade_sessions table for storing full cascade definitions and inputs per run
-- Author: LARS
-- Date: 2026-01-16
--
-- This enables perfect replay of historical runs with their exact cascade structure.
-- Also includes genus_hash for cascade-level identity and output column for quick Console access.

-- Create the base table
CREATE TABLE IF NOT EXISTS cascade_sessions (
    session_id String,
    cascade_id String,
    cascade_definition String,  -- Raw YAML/JSON file contents (preserved as-is, no Pydantic conversion)
    input_data String,           -- Input parameters passed to the run (JSON)
    config_path String,          -- Original file path if loaded from file
    created_at DateTime DEFAULT now(),
    parent_session_id String,    -- Parent session for sub-cascades (empty string if none)
    depth UInt8 DEFAULT 0,       -- Depth in cascade tree
    caller_id String DEFAULT '', -- Parent caller that initiated this cascade
    invocation_metadata_json String DEFAULT '{}' CODEC(ZSTD(3)),  -- Full invocation context
    -- Added in later migrations, included here for new installs:
    genus_hash String DEFAULT '' CODEC(ZSTD(1)),  -- Cascade-level identity hash
    output String DEFAULT '' CODEC(ZSTD(3))       -- Final cascade output
)
ENGINE = MergeTree()
ORDER BY (cascade_id, created_at);

-- Add indexes
ALTER TABLE cascade_sessions ADD INDEX IF NOT EXISTS idx_genus_hash genus_hash TYPE bloom_filter GRANULARITY 1;

ALTER TABLE cascade_sessions ADD INDEX IF NOT EXISTS idx_output_bloom output TYPE bloom_filter(0.01) GRANULARITY 1;

ALTER TABLE cascade_sessions ADD INDEX IF NOT EXISTS idx_session_id session_id TYPE bloom_filter GRANULARITY 1;
