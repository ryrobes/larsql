-- Cascade Sessions table for storing full cascade definitions and inputs per run
-- This enables perfect replay of historical runs with their exact cascade structure

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
    invocation_metadata_json String DEFAULT '{}' CODEC(ZSTD(3))  -- Full invocation context
)
ENGINE = MergeTree()
ORDER BY (cascade_id, created_at);

-- This table allows:
-- 1. Perfect replay: Load exact cascade definition from when it ran
-- 2. Versioning: See how cascade evolved over time
-- 3. Reproducibility: Re-run with exact same definition + inputs
-- 4. Debugging: Understand what the cascade looked like when an issue occurred

-- Query examples:
-- Get cascade definition for a specific session:
--   SELECT cascade_definition, input_data FROM cascade_sessions WHERE session_id = ?
--
-- Get all versions of a cascade over time:
--   SELECT session_id, created_at, cascade_definition
--   FROM cascade_sessions
--   WHERE cascade_id = ?
--   ORDER BY created_at DESC
--
-- Find sessions with specific input parameters:
--   SELECT * FROM cascade_sessions
--   WHERE cascade_id = ? AND input_data LIKE '%some_key%'
