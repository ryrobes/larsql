#!/bin/bash
# Performance Analysis: PRE vs POST Config Caching
# Cutoff: 2026-01-23 23:01:19.003341

set -e

echo "==================================================================="
echo "LARS Performance Analysis: Config Caching Optimization"
echo "==================================================================="
echo ""
echo "PRE:  Before 2026-01-23 23:01:19.003341 (no caching)"
echo "POST: After  2026-01-23 23:01:19.003341 (DB-cached configs)"
echo ""

# ClickHouse connection (adjust if needed)
CH_HOST=${LARS_CLICKHOUSE_HOST:-localhost}
CH_PORT=${LARS_CLICKHOUSE_PORT:-9000}
CH_USER=${LARS_CLICKHOUSE_USER:-default}

echo "==================================================================="
echo "1. QUICK SUMMARY (Overall Improvement by Label)"
echo "==================================================================="
clickhouse-client --host=$CH_HOST --port=$CH_PORT --user=$CH_USER --query="
WITH phased AS (
    SELECT
        CASE WHEN timestamp <= '2026-01-23 23:01:19.003341' THEN 'PRE' ELSE 'POST' END as phase,
        label,
        duration_ms
    FROM perf_metrics
    WHERE timestamp >= '2026-01-23 22:00:00'
        AND timestamp <= '2026-01-24 01:00:00'
)
SELECT
    label,
    countIf(phase = 'PRE') as pre_calls,
    round(avgIf(duration_ms, phase = 'PRE'), 2) as pre_avg_ms,
    countIf(phase = 'POST') as post_calls,
    round(avgIf(duration_ms, phase = 'POST'), 2) as post_avg_ms,
    round(avgIf(duration_ms, phase = 'PRE') - avgIf(duration_ms, phase = 'POST'), 2) as improvement_ms,
    round((avgIf(duration_ms, phase = 'PRE') - avgIf(duration_ms, phase = 'POST')) / avgIf(duration_ms, phase = 'PRE') * 100, 1) as improvement_pct
FROM phased
GROUP BY label
HAVING pre_calls > 0 AND post_calls > 0
ORDER BY abs(improvement_ms) DESC
FORMAT PrettyCompact
"

echo ""
echo "==================================================================="
echo "2. CONFIG LOADING FOCUS (udf_cascade_execution)"
echo "==================================================================="
clickhouse-client --host=$CH_HOST --port=$CH_PORT --user=$CH_USER --query="
SELECT
    CASE WHEN timestamp <= '2026-01-23 23:01:19.003341' THEN 'PRE' ELSE 'POST' END as phase,
    COUNT(*) as calls,
    round(AVG(duration_ms), 2) as avg_ms,
    round(MEDIAN(duration_ms), 2) as median_ms,
    round(quantile(0.95)(duration_ms), 2) as p95_ms,
    round(MIN(duration_ms), 2) as min_ms,
    round(MAX(duration_ms), 2) as max_ms
FROM perf_metrics
WHERE label = 'udf_cascade_execution'
    AND timestamp >= '2026-01-23 22:00:00'
    AND timestamp <= '2026-01-24 01:00:00'
GROUP BY phase
ORDER BY phase
FORMAT PrettyCompact
"

echo ""
echo "==================================================================="
echo "3. TOTAL TIME SAVED"
echo "==================================================================="
clickhouse-client --host=$CH_HOST --port=$CH_PORT --user=$CH_USER --query="
WITH savings AS (
    SELECT
        AVG(CASE WHEN timestamp <= '2026-01-23 23:01:19.003341' THEN duration_ms ELSE NULL END) as pre_avg,
        COUNT(CASE WHEN timestamp > '2026-01-23 23:01:19.003341' THEN 1 ELSE NULL END) as post_calls,
        AVG(CASE WHEN timestamp > '2026-01-23 23:01:19.003341' THEN duration_ms ELSE NULL END) as post_avg
    FROM perf_metrics
    WHERE label = 'udf_cascade_execution'
        AND timestamp >= '2026-01-23 22:00:00'
)
SELECT
    round(pre_avg, 2) as pre_avg_ms,
    round(post_avg, 2) as post_avg_ms,
    round(pre_avg - post_avg, 2) as saved_per_call_ms,
    post_calls,
    round((pre_avg - post_avg) * post_calls, 0) as total_saved_ms,
    formatReadableTimeDelta((pre_avg - post_avg) * post_calls / 1000) as total_saved
FROM savings
FORMAT PrettyCompact
"

echo ""
echo "==================================================================="
echo "4. PER-CASCADE IMPROVEMENT (Top 10)"
echo "==================================================================="
clickhouse-client --host=$CH_HOST --port=$CH_PORT --user=$CH_USER --query="
WITH phased AS (
    SELECT
        cascade_id,
        CASE WHEN timestamp <= '2026-01-23 23:01:19.003341' THEN 'PRE' ELSE 'POST' END as phase,
        duration_ms
    FROM perf_metrics
    WHERE label = 'udf_cascade_execution'
        AND cascade_id != ''
        AND timestamp >= '2026-01-23 22:00:00'
)
SELECT
    cascade_id,
    countIf(phase = 'PRE') as pre_calls,
    round(avgIf(duration_ms, phase = 'PRE'), 2) as pre_avg_ms,
    countIf(phase = 'POST') as post_calls,
    round(avgIf(duration_ms, phase = 'POST'), 2) as post_avg_ms,
    round(avgIf(duration_ms, phase = 'PRE') - avgIf(duration_ms, phase = 'POST'), 2) as improvement_ms,
    round((avgIf(duration_ms, phase = 'PRE') - avgIf(duration_ms, phase = 'POST')) / avgIf(duration_ms, phase = 'PRE') * 100, 1) as improvement_pct
FROM phased
GROUP BY cascade_id
HAVING pre_calls > 0 AND post_calls > 0
ORDER BY improvement_ms DESC
LIMIT 10
FORMAT PrettyCompact
"

echo ""
echo "==================================================================="
echo "5. CHECK FOR REGRESSIONS (Operations that got SLOWER)"
echo "==================================================================="
clickhouse-client --host=$CH_HOST --port=$CH_PORT --user=$CH_USER --query="
WITH phased AS (
    SELECT
        label,
        CASE WHEN timestamp <= '2026-01-23 23:01:19.003341' THEN 'PRE' ELSE 'POST' END as phase,
        duration_ms
    FROM perf_metrics
    WHERE timestamp >= '2026-01-23 22:00:00'
)
SELECT
    label,
    round(avgIf(duration_ms, phase = 'PRE'), 2) as pre_avg_ms,
    round(avgIf(duration_ms, phase = 'POST'), 2) as post_avg_ms,
    round(avgIf(duration_ms, phase = 'POST') - avgIf(duration_ms, phase = 'PRE'), 2) as regression_ms,
    round((avgIf(duration_ms, phase = 'POST') - avgIf(duration_ms, phase = 'PRE')) / avgIf(duration_ms, phase = 'PRE') * 100, 1) as regression_pct
FROM phased
GROUP BY label
HAVING regression_ms > 1
ORDER BY regression_ms DESC
FORMAT PrettyCompact
"

echo ""
echo "==================================================================="
echo "Analysis complete!"
echo "==================================================================="
echo ""
echo "For more detailed analysis, run:"
echo "  clickhouse-client < analyze_perf_summary.sql"
echo "  clickhouse-client < analyze_perf_improvement.sql"
echo "  clickhouse-client < analyze_config_caching.sql"
echo ""
