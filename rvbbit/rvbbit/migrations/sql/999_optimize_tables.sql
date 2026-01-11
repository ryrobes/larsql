-- Migration: 999_optimize_tables
-- Description: Optimize ClickHouse tables - runs on every migration
-- Author: RVBBIT
-- Date: 2026-01-10
-- AlwaysRun: true

-- This migration runs every time to ensure tables are optimized.
-- ClickHouse's OPTIMIZE TABLE merges parts and deduplicates ReplacingMergeTree tables.

-- Core tables (most frequently written)
OPTIMIZE TABLE unified_logs FINAL;
OPTIMIZE TABLE session_state FINAL;
OPTIMIZE TABLE checkpoints FINAL;

-- Vector/embedding tables
OPTIMIZE TABLE rag_chunks FINAL;
OPTIMIZE TABLE rag_manifests FINAL;
OPTIMIZE TABLE tool_manifest_vectors FINAL;
OPTIMIZE TABLE cascade_template_vectors FINAL;
OPTIMIZE TABLE context_cards FINAL;

-- Analytics tables
OPTIMIZE TABLE context_shadow_assessments FINAL;
OPTIMIZE TABLE intra_context_shadow_assessments FINAL;
OPTIMIZE TABLE ui_sql_log FINAL;
OPTIMIZE TABLE sql_query_log FINAL;

-- Cache tables
OPTIMIZE TABLE semantic_sql_cache FINAL;
OPTIMIZE TABLE openrouter_models FINAL;
OPTIMIZE TABLE hf_spaces FINAL;

-- Training/evaluation tables
OPTIMIZE TABLE training_preferences FINAL;
OPTIMIZE TABLE evaluations FINAL;

-- Tagging tables
OPTIMIZE TABLE tag_definitions FINAL;
OPTIMIZE TABLE output_tags FINAL;

-- Research tables
OPTIMIZE TABLE research_sessions FINAL;
OPTIMIZE TABLE signals FINAL;

-- Schema migrations (self-optimize)
OPTIMIZE TABLE schema_migrations FINAL;
