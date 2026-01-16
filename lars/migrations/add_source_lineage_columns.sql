-- Add SQL source lineage columns to unified_logs table
-- Safe to run multiple times (ALTER TABLE ADD COLUMN IF NOT EXISTS)
-- Date: 2026-01-09
-- Purpose: Track which SQL row/column triggered each cascade execution
--          Enables visualizations showing LLM processing per data cell

-- Add source column name (e.g., 'description' when processing description MEANS 'x')
ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS source_column_name Nullable(String)
    COMMENT 'Column name being processed by semantic SQL operator';

-- Add source row index (0-based, from LARS MAP operations)
ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS source_row_index Nullable(Int64)
    COMMENT 'Row index (0-based) in source SQL query';

-- Add source table name (if extractable from query context)
ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS source_table_name Nullable(String)
    COMMENT 'Source table name if known from SQL context';

-- Add index for source_column_name for efficient filtering
ALTER TABLE lars.unified_logs
    ADD INDEX IF NOT EXISTS idx_source_column source_column_name TYPE bloom_filter GRANULARITY 1;

-- Add index for source_row_index for range queries
ALTER TABLE lars.unified_logs
    ADD INDEX IF NOT EXISTS idx_source_row source_row_index TYPE minmax GRANULARITY 4;


-- Example queries:

-- Query 1: See which columns are being processed most often
-- SELECT
--     source_column_name,
--     COUNT(*) as operations,
--     SUM(cost) as total_cost,
--     AVG(duration_ms) as avg_duration_ms
-- FROM lars.unified_logs
-- WHERE source_column_name IS NOT NULL
-- GROUP BY source_column_name
-- ORDER BY operations DESC;

-- Query 2: Track processing per row in a LARS MAP operation
-- SELECT
--     source_row_index,
--     session_id,
--     cell_name,
--     cost,
--     duration_ms
-- FROM lars.unified_logs
-- WHERE caller_id = 'sql-your-caller-id'
--   AND source_row_index IS NOT NULL
-- ORDER BY source_row_index;

-- Query 3: Cost heatmap data - cost per row/column combination
-- SELECT
--     source_column_name,
--     source_row_index,
--     SUM(cost) as cell_cost,
--     COUNT(*) as llm_calls
-- FROM lars.unified_logs
-- WHERE caller_id = 'sql-your-caller-id'
--   AND source_column_name IS NOT NULL
-- GROUP BY source_column_name, source_row_index
-- ORDER BY source_row_index, source_column_name;

-- Query 4: Identify expensive rows (outliers)
-- SELECT
--     source_row_index,
--     source_column_name,
--     SUM(cost) as row_cost,
--     SUM(total_tokens) as row_tokens
-- FROM lars.unified_logs
-- WHERE caller_id = 'sql-your-caller-id'
--   AND source_row_index IS NOT NULL
-- GROUP BY source_row_index, source_column_name
-- HAVING row_cost > 0.01
-- ORDER BY row_cost DESC;

-- Query 5: Processing timeline per row
-- SELECT
--     source_row_index,
--     MIN(timestamp) as started,
--     MAX(timestamp) as completed,
--     dateDiff('millisecond', MIN(timestamp), MAX(timestamp)) as row_duration_ms,
--     COUNT(*) as messages
-- FROM lars.unified_logs
-- WHERE caller_id = 'sql-your-caller-id'
--   AND source_row_index IS NOT NULL
-- GROUP BY source_row_index
-- ORDER BY source_row_index;
