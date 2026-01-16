-- Add TOON telemetry columns to unified_logs table
-- Safe to run multiple times (ALTER TABLE ADD COLUMN IF NOT EXISTS)
-- Date: 2026-01-05
-- Purpose: Track token savings and TOON format usage for cost analysis

-- Add data format tracking (toon, json, or empty)
ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS data_format String DEFAULT ''
    COMMENT 'Data encoding format used: toon, json, or empty';

-- Add size metrics for comparison
ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS data_size_json Nullable(UInt32)
    COMMENT 'Data size in characters (JSON baseline for comparison)';

ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS data_size_toon Nullable(UInt32)
    COMMENT 'Data size in characters (TOON encoded, if used)';

-- Add token savings metric (most important for cost analysis)
ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS data_token_savings_pct Nullable(Float32)
    COMMENT 'Token savings percentage (TOON vs JSON baseline)';

-- Add encoding performance metric
ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS toon_encoding_ms Nullable(Float32)
    COMMENT 'Time to encode data as TOON in milliseconds';

-- Add decoder telemetry (track LLM responses in TOON format)
ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS toon_decode_attempted Nullable(Bool)
    COMMENT 'Whether TOON decoding was attempted on LLM response';

ALTER TABLE lars.unified_logs
    ADD COLUMN IF NOT EXISTS toon_decode_success Nullable(Bool)
    COMMENT 'Whether TOON decoding succeeded (if attempted)';

-- Note: Materialized view creation is commented out for now
-- You can create it manually after running this migration if needed:
--
-- CREATE MATERIALIZED VIEW IF NOT EXISTS lars.toon_savings_mv
-- ENGINE = SummingMergeTree()
-- ORDER BY (session_id, data_format, date)
-- AS
-- SELECT
--     session_id,
--     data_format,
--     toDate(timestamp_iso) as date,
--     count() as operations,
--     sum(data_size_json) as total_json_size,
--     sum(data_size_toon) as total_toon_size,
--     avg(data_token_savings_pct) as avg_savings_pct,
--     sum(toon_encoding_ms) as total_encoding_time_ms,
--     countIf(toon_decode_attempted = 1) as decode_attempts,
--     countIf(toon_decode_success = 1) as decode_successes
-- FROM lars.unified_logs
-- WHERE data_format != ''
-- GROUP BY session_id, data_format, date;

-- Example queries for TOON analytics:

-- Query 1: Overall TOON usage and savings
-- SELECT
--     data_format,
--     COUNT(*) as operations,
--     AVG(data_token_savings_pct) as avg_savings,
--     SUM(data_size_json) as total_json_chars,
--     SUM(data_size_toon) as total_toon_chars
-- FROM lars.unified_logs
-- WHERE data_format IN ('toon', 'json')
-- GROUP BY data_format;

-- Query 2: TOON savings by session
-- SELECT
--     session_id,
--     COUNT(*) as toon_operations,
--     AVG(data_token_savings_pct) as avg_savings,
--     SUM(data_size_json - data_size_toon) as total_chars_saved
-- FROM lars.unified_logs
-- WHERE data_format = 'toon'
-- GROUP BY session_id
-- ORDER BY total_chars_saved DESC
-- LIMIT 10;

-- Query 3: TOON decoding success rate
-- SELECT
--     COUNT(*) as decode_attempts,
--     COUNTIf(toon_decode_success = 1) as successful,
--     COUNTIf(toon_decode_success = 0) as failed,
--     (COUNTIf(toon_decode_success = 1) * 100.0 / COUNT(*)) as success_rate_pct
-- FROM lars.unified_logs
-- WHERE toon_decode_attempted = 1;

-- Query 4: Performance impact of TOON encoding
-- SELECT
--     quantile(0.5)(toon_encoding_ms) as median_ms,
--     quantile(0.95)(toon_encoding_ms) as p95_ms,
--     quantile(0.99)(toon_encoding_ms) as p99_ms,
--     MAX(toon_encoding_ms) as max_ms
-- FROM lars.unified_logs
-- WHERE toon_encoding_ms IS NOT NULL;

-- Query 5: Cost savings estimation (requires token pricing)
-- SELECT
--     data_format,
--     SUM(data_size_json - data_size_toon) as chars_saved,
--     SUM(data_size_json - data_size_toon) / 4.0 as estimated_tokens_saved,
--     (SUM(data_size_json - data_size_toon) / 4.0) * 0.01 / 1000 as estimated_cost_saved_usd
-- FROM lars.unified_logs
-- WHERE data_format = 'toon'
-- GROUP BY data_format;
