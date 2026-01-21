-- Migration: 037_latest_cell_output_view
-- Description: Create view for looking up latest cell outputs from unified_logs
-- Author: LARS
-- Date: 2026-01-21

-- View that provides the latest output for each cascade+cell combination
-- Used by the LATEST() SQL function to retrieve historical cell outputs
--
-- This view filters for assistant messages (the actual cell outputs)
-- and orders by timestamp descending so LIMIT 1 gets the most recent.
--
-- The LATEST() cascade function queries this view with specific
-- cascade_id and cell_name filters.

CREATE OR REPLACE VIEW v_latest_cell_outputs AS
SELECT
    cascade_id,
    cell_name,
    session_id,
    timestamp,
    content_json,
    model,
    tokens_in,
    tokens_out,
    cost,
    duration_ms,
    trace_id,
    toString(message_id) as message_id
FROM unified_logs
WHERE
    role = 'assistant'
    AND cascade_id IS NOT NULL
    AND cascade_id != ''
    AND cell_name IS NOT NULL
    AND cell_name != ''
    AND content_json IS NOT NULL
    AND content_json != ''
ORDER BY timestamp DESC;
