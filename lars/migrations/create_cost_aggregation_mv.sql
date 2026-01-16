-- Migration: Cost Aggregation Materialized View
-- Date: 2026-01-02
-- Issue: aggregate_query_costs() runs too early, before cost data arrives
-- Solution: Lazy aggregation via materialized view that auto-updates

-- Drop if exists (for idempotency)
DROP VIEW IF EXISTS lars.mv_sql_query_costs;

-- Create materialized view that aggregates costs by caller_id
CREATE MATERIALIZED VIEW IF NOT EXISTS lars.mv_sql_query_costs
ENGINE = SummingMergeTree()
ORDER BY (caller_id)
POPULATE
AS SELECT
    caller_id,
    sum(cost) as total_cost,
    sum(tokens_in) as total_tokens_in,
    sum(tokens_out) as total_tokens_out,
    count() as llm_calls_count
FROM lars.unified_logs
WHERE caller_id != ''
  AND caller_id LIKE 'sql-%'
  AND cost IS NOT NULL
GROUP BY caller_id;

-- Verify view exists
-- Run: clickhouse-client --database lars --query "SHOW TABLES LIKE 'mv_sql_query_costs'"
