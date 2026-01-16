-- Migration: 022_mv_session_summary
-- Description: Create mv_session_summary materialized view - auto-aggregated session metrics
-- Author: LARS
-- Date: 2026-01-10

-- Drop and recreate to ensure latest definition
-- (Materialized views can't be altered, only recreated)
DROP TABLE IF EXISTS mv_session_summary;

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_session_summary
ENGINE = SummingMergeTree()
ORDER BY (session_id, cascade_id_key)
AS SELECT
    session_id,
    coalesce(cascade_id, '') as cascade_id_key,
    cascade_id,
    min(timestamp) as start_time,
    max(timestamp) as end_time,
    sum(cost) as total_cost,
    sum(tokens_in) as total_tokens_in,
    sum(tokens_out) as total_tokens_out,
    sum(tokens_reasoning) as total_tokens_reasoning,
    count() as message_count,
    countIf(role = 'assistant') as assistant_messages,
    countIf(node_type = 'tool_call') as tool_calls,
    countIf(reasoning_enabled = true) as reasoning_calls
FROM unified_logs
GROUP BY session_id, cascade_id;
