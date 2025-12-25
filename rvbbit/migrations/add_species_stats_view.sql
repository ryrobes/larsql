-- Migration: Add species_stats materialized view
-- Date: 2025-12-10
-- Description: Aggregated stats per species for fast Sextant queries
--
-- This view enables:
-- - Quick species comparison without scanning prompt_lineage
-- - Win rate, cost averages, and champion tracking per species
-- - Leaderboard queries for tournament system

CREATE MATERIALIZED VIEW IF NOT EXISTS species_stats
ENGINE = SummingMergeTree()
ORDER BY (species_hash, cascade_id, cell_name)
AS SELECT
    species_hash,
    cascade_id,
    cell_name,

    -- Counts
    count() AS total_prompts,
    countIf(is_winner = true) AS winner_count,
    countIf(is_winner = false OR is_winner IS NULL) AS loser_count,
    countDistinct(session_id) AS session_count,
    countDistinct(model) AS model_count,

    -- Cost aggregates
    sum(cost) AS total_cost,
    avg(cost) AS avg_cost,
    avgIf(cost, is_winner = true) AS avg_winner_cost,
    avgIf(cost, is_winner = false) AS avg_loser_cost,

    -- Generation tracking
    max(generation) AS max_generation,
    countIf(generation = 0) AS base_prompts,
    countIf(generation > 0) AS evolved_prompts,

    -- Time window
    min(created_at) AS first_seen,
    max(created_at) AS last_seen

FROM prompt_lineage
GROUP BY species_hash, cascade_id, cell_name;

-- Verify the view was created
SELECT
    name,
    engine
FROM system.tables
WHERE name = 'species_stats';
