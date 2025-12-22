-- Cascade State table for durable state persistence
-- Stores all set_state() calls for queryable state history

CREATE TABLE IF NOT EXISTS cascade_state (
    session_id String,
    cascade_id String,
    key String,              -- State key (e.g., 'total_revenue', 'user_count')
    value String,            -- JSON-serialized value
    phase_name String,       -- Which phase set this state
    created_at DateTime DEFAULT now(),
    -- Metadata for tracking
    value_type String DEFAULT 'unknown'  -- 'string', 'number', 'object', 'array', 'boolean', 'null'
)
ENGINE = MergeTree()
ORDER BY (cascade_id, session_id, key, created_at);

-- This table enables:
-- 1. State browsing during execution (Studio UI sidebar)
-- 2. State history queries (see how values changed over time)
-- 3. Cross-run analytics (compare state across sessions)
-- 4. LLM memory (query past state to inform current run)
-- 5. Debugging (inspect state at any point in execution)

-- Query examples:
-- Get current state for a session:
--   SELECT key, value, phase_name, created_at
--   FROM cascade_state
--   WHERE session_id = ?
--   ORDER BY created_at DESC
--
-- Get latest value for a specific key:
--   SELECT value FROM cascade_state
--   WHERE cascade_id = ? AND key = ?
--   ORDER BY created_at DESC
--   LIMIT 1
--
-- See state evolution over time:
--   SELECT session_id, created_at, value
--   FROM cascade_state
--   WHERE cascade_id = 'my_pipeline' AND key = 'insights'
--   ORDER BY created_at DESC
--
-- Count how many times state was set:
--   SELECT key, COUNT(*) as set_count
--   FROM cascade_state
--   WHERE session_id = ?
--   GROUP BY key
