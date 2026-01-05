-- Add data shape columns to unified_logs table
-- Safe to run multiple times (ALTER TABLE ADD COLUMN IF NOT EXISTS)
-- Date: 2026-01-05
-- Purpose: Track rows and columns in JSON payloads for debugging and analytics

-- Add row count for detected JSON arrays
ALTER TABLE rvbbit.unified_logs
    ADD COLUMN IF NOT EXISTS data_rows Nullable(UInt32)
    COMMENT 'Number of rows in detected JSON array payloads';

-- Add column count for detected JSON arrays of objects
ALTER TABLE rvbbit.unified_logs
    ADD COLUMN IF NOT EXISTS data_columns Nullable(UInt32)
    COMMENT 'Number of columns (keys) in detected JSON array of objects';

-- Example queries:

-- Query 1: Data shape distribution
-- SELECT
--     data_rows,
--     data_columns,
--     COUNT(*) as occurrences,
--     AVG(data_token_savings_pct) as avg_toon_savings
-- FROM rvbbit.unified_logs
-- WHERE data_rows IS NOT NULL
-- GROUP BY data_rows, data_columns
-- ORDER BY occurrences DESC
-- LIMIT 20;

-- Query 2: Large payloads that might benefit from TOON
-- SELECT
--     session_id,
--     cell_name,
--     data_rows,
--     data_columns,
--     data_size_json,
--     data_format,
--     data_token_savings_pct
-- FROM rvbbit.unified_logs
-- WHERE data_rows >= 10
-- ORDER BY data_rows DESC
-- LIMIT 20;

-- Query 3: TOON effectiveness by data shape
-- SELECT
--     data_columns,
--     COUNT(*) as operations,
--     AVG(data_token_savings_pct) as avg_savings_pct,
--     MIN(data_token_savings_pct) as min_savings,
--     MAX(data_token_savings_pct) as max_savings
-- FROM rvbbit.unified_logs
-- WHERE data_format = 'toon' AND data_columns IS NOT NULL
-- GROUP BY data_columns
-- ORDER BY data_columns;

-- Query 4: Messages without structured data (for comparison)
-- SELECT
--     COUNT(*) as total_messages,
--     COUNTIf(data_rows IS NULL) as no_structured_data,
--     COUNTIf(data_rows IS NOT NULL) as has_structured_data,
--     COUNTIf(data_rows >= 5) as toon_eligible
-- FROM rvbbit.unified_logs
-- WHERE role = 'user';
