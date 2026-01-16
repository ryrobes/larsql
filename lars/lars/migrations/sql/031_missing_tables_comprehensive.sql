-- Migration: 031_missing_tables_comprehensive
-- Description: Add all missing tables, materialized views, and views from legacy schema
-- Author: LARS
-- Date: 2026-01-16
--
-- This migration adds 20 missing objects identified from schema comparison:
-- - 12 base tables
-- - 3 materialized views
-- - 5 regular views

-- ============================================================================
-- PART 0: ADD MISSING COLUMNS TO EXISTING TABLES
-- ============================================================================

-- unified_logs: Add candidate_index and winning_candidate_index columns
ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS `candidate_index` Nullable(Int32) AFTER `is_winner`;

ALTER TABLE unified_logs ADD COLUMN IF NOT EXISTS `winning_candidate_index` Nullable(Int32) AFTER `candidate_index`;

-- ============================================================================
-- PART 1: BASE TABLES
-- ============================================================================

-- Table: artifacts - Rich UI outputs from cascades
CREATE TABLE IF NOT EXISTS artifacts (
    `id` String,
    `session_id` String,
    `cascade_id` String,
    `cell_name` String,
    `title` String,
    `artifact_type` String,
    `description` String,
    `html_content` String,
    `tags` String,
    `created_at` DateTime,
    `updated_at` DateTime
) ENGINE = MergeTree
ORDER BY (cascade_id, created_at)
SETTINGS index_granularity = 8192;

-- Table: cascade_analytics - Pre-computed cascade-level analytics
CREATE TABLE IF NOT EXISTS cascade_analytics (
    `session_id` String,
    `cascade_id` String,
    `genus_hash` String,
    `created_at` DateTime DEFAULT now(),
    `input_complexity_score` Float32,
    `input_category` LowCardinality(String),
    `input_fingerprint` String,
    `input_char_count` UInt32,
    `input_estimated_tokens` UInt32,
    `total_cost` Float64,
    `total_duration_ms` Float64,
    `total_tokens_in` UInt32,
    `total_tokens_out` UInt32,
    `total_tokens` UInt32,
    `message_count` UInt16,
    `cell_count` UInt8,
    `error_count` UInt8,
    `candidate_count` UInt8 DEFAULT 0,
    `winner_candidate_index` Nullable(Int8),
    `global_avg_cost` Float64,
    `global_avg_duration` Float64,
    `global_avg_tokens` Float64,
    `global_run_count` UInt32,
    `cluster_avg_cost` Float64,
    `cluster_stddev_cost` Float64,
    `cluster_avg_duration` Float64,
    `cluster_stddev_duration` Float64,
    `cluster_avg_tokens` Float64,
    `cluster_stddev_tokens` Float64,
    `cluster_run_count` UInt32,
    `genus_avg_cost` Nullable(Float64),
    `genus_avg_duration` Nullable(Float64),
    `genus_run_count` UInt16,
    `cost_z_score` Float32,
    `duration_z_score` Float32,
    `tokens_z_score` Float32,
    `is_cost_outlier` Bool,
    `is_duration_outlier` Bool,
    `is_tokens_outlier` Bool,
    `cost_per_message` Float32,
    `cost_per_token` Float32,
    `duration_per_message` Float32,
    `tokens_per_message` Float32,
    `models_used` Array(String),
    `primary_model` String,
    `model_switches` UInt8,
    `hour_of_day` UInt8,
    `day_of_week` UInt8,
    `is_weekend` Bool,
    `analyzed_at` DateTime DEFAULT now(),
    `analysis_version` UInt8 DEFAULT 1,
    `total_context_tokens` UInt32 DEFAULT 0,
    `total_new_tokens` UInt32 DEFAULT 0,
    `total_context_cost_estimated` Float64 DEFAULT 0,
    `total_new_cost_estimated` Float64 DEFAULT 0,
    `context_cost_pct` Float32 DEFAULT 0,
    `cells_with_context` UInt8 DEFAULT 0,
    `avg_cell_context_pct` Float32 DEFAULT 0,
    `max_cell_context_pct` Float32 DEFAULT 0,
    `take_count` UInt8 DEFAULT 0,
    `winner_take_index` Nullable(Int8),
    INDEX idx_genus genus_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_input_category input_category TYPE set(0) GRANULARITY 1,
    INDEX idx_cost_outlier is_cost_outlier TYPE set(0) GRANULARITY 1,
    INDEX idx_duration_outlier is_duration_outlier TYPE set(0) GRANULARITY 1
) ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (cascade_id, created_at, session_id)
SETTINGS index_granularity = 8192;

-- Table: cascade_state - Key-value state storage for cascades
CREATE TABLE IF NOT EXISTS cascade_state (
    `session_id` String,
    `cascade_id` String,
    `key` String,
    `value` String,
    `cell_name` String,
    `created_at` DateTime DEFAULT now(),
    `value_type` String DEFAULT 'unknown'
) ENGINE = MergeTree
ORDER BY (cascade_id, session_id, key, created_at)
SETTINGS index_granularity = 8192;

-- Table: cell_analytics - Pre-computed cell-level analytics
CREATE TABLE IF NOT EXISTS cell_analytics (
    `session_id` String,
    `cascade_id` String,
    `cell_name` String,
    `species_hash` String,
    `genus_hash` String,
    `created_at` DateTime DEFAULT now(),
    `cell_type` LowCardinality(String),
    `tool` Nullable(String),
    `model` Nullable(String),
    `cell_cost` Float64,
    `cell_duration_ms` Float64,
    `cell_tokens_in` UInt32,
    `cell_tokens_out` UInt32,
    `cell_tokens` UInt32,
    `message_count` UInt16,
    `turn_count` UInt8,
    `candidate_count` UInt8 DEFAULT 0,
    `error_occurred` Bool DEFAULT false,
    `global_cell_avg_cost` Float64,
    `global_cell_avg_duration` Float64,
    `global_cell_run_count` UInt32,
    `species_avg_cost` Float64,
    `species_stddev_cost` Float64,
    `species_avg_duration` Float64,
    `species_stddev_duration` Float64,
    `species_run_count` UInt32,
    `cost_z_score` Float32,
    `duration_z_score` Float32,
    `is_cost_outlier` Bool,
    `is_duration_outlier` Bool,
    `cost_per_turn` Float32,
    `cost_per_token` Float32,
    `tokens_per_turn` Float32,
    `duration_per_turn` Float32,
    `cascade_total_cost` Float64,
    `cascade_total_duration` Float64,
    `cell_cost_pct` Float32,
    `cell_duration_pct` Float32,
    `cell_index` UInt8,
    `is_first_cell` Bool,
    `is_last_cell` Bool,
    `analyzed_at` DateTime DEFAULT now(),
    `analysis_version` UInt8 DEFAULT 1,
    `context_token_count` UInt32 DEFAULT 0,
    `new_message_tokens` UInt32 DEFAULT 0,
    `context_message_count` UInt8 DEFAULT 0,
    `has_context` Bool DEFAULT false,
    `context_depth_avg` Float32 DEFAULT 0,
    `context_depth_max` UInt8 DEFAULT 0,
    `context_cost_estimated` Float64 DEFAULT 0,
    `new_message_cost_estimated` Float64 DEFAULT 0,
    `context_cost_pct` Float32 DEFAULT 0,
    `take_count` UInt8 DEFAULT 0,
    INDEX idx_species species_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_genus genus_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell_name cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell_cost_outlier is_cost_outlier TYPE set(0) GRANULARITY 1,
    INDEX idx_cell_duration_outlier is_duration_outlier TYPE set(0) GRANULARITY 1,
    INDEX idx_cell_cascade_id cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_has_context has_context TYPE set(0) GRANULARITY 1,
    INDEX idx_context_pct_high context_cost_pct TYPE minmax GRANULARITY 1
) ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (cascade_id, cell_name, created_at, session_id)
SETTINGS index_granularity = 8192;

-- Table: cell_context_breakdown - Per-message context cost attribution
CREATE TABLE IF NOT EXISTS cell_context_breakdown (
    `session_id` String,
    `cascade_id` String,
    `cell_name` String,
    `cell_index` UInt8,
    `context_message_hash` String,
    `context_message_cell` String,
    `context_message_role` LowCardinality(String),
    `context_message_index` UInt8,
    `context_message_tokens` UInt32,
    `context_message_cost_estimated` Float64,
    `context_message_pct` Float32,
    `total_context_messages` UInt8,
    `total_context_tokens` UInt32,
    `total_cell_cost` Float64,
    `created_at` DateTime DEFAULT now(),
    `model_requested` String DEFAULT '',
    `candidate_index` Nullable(Int32),
    `relevance_score` Nullable(Float32),
    `relevance_reasoning` Nullable(String),
    `relevance_analysis_cost` Nullable(Float64),
    `relevance_analyzed_at` Nullable(DateTime),
    `relevance_analysis_session` Nullable(String),
    `take_index` Nullable(Int32),
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cell cell_name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_source_cell context_message_cell TYPE bloom_filter GRANULARITY 1
) ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (session_id, cell_name, context_message_index)
SETTINGS index_granularity = 8192;

-- Table: prompt_lineage - Prompt evolution tracking for Sextant
CREATE TABLE IF NOT EXISTS prompt_lineage (
    `lineage_id` UUID DEFAULT generateUUIDv4(),
    `session_id` String,
    `cascade_id` String,
    `cell_name` String,
    `trace_id` String,
    `species_hash` String,
    `candidate_index` Int32,
    `generation` Int32 DEFAULT 0,
    `parent_lineage_id` Nullable(UUID),
    `mutation_type` LowCardinality(Nullable(String)),
    `mutation_template` Nullable(String),
    `full_prompt_text` String CODEC(ZSTD(3)),
    `prompt_hash` String,
    `prompt_embedding` Array(Float32) DEFAULT [],
    `embedding_model` LowCardinality(Nullable(String)),
    `embedding_dim` Nullable(UInt16),
    `bigrams` Array(String) DEFAULT [],
    `trigrams` Array(String) DEFAULT [],
    `quadgrams` Array(String) DEFAULT [],
    `fingerprint` Array(String) DEFAULT [],
    `is_winner` Bool DEFAULT false,
    `evaluator_score` Nullable(Float32),
    `cost` Nullable(Float64),
    `duration_ms` Nullable(Float64),
    `tokens_in` Nullable(Int32),
    `tokens_out` Nullable(Int32),
    `model` LowCardinality(Nullable(String)),
    `created_at` DateTime64(3) DEFAULT now64(3),
    `take_index` Int32 DEFAULT 0,
    INDEX idx_species species_hash TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_trace trace_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_is_winner is_winner TYPE set(2) GRANULARITY 1,
    INDEX idx_generation generation TYPE minmax GRANULARITY 1
) ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (species_hash, cascade_id, cell_name, created_at)
TTL created_at + toIntervalYear(1)
SETTINGS index_granularity = 8192;

-- Table: lars_embeddings - General-purpose embedding storage (renamed from rvbbit_embeddings)
CREATE TABLE IF NOT EXISTS lars_embeddings (
    `source_table` LowCardinality(String),
    `source_id` String,
    `text` String,
    `embedding` Array(Float32),
    `embedding_model` LowCardinality(String),
    `embedding_dim` UInt16,
    `metadata` String DEFAULT '{}',
    `created_at` DateTime64(3) DEFAULT now64(3),
    INDEX idx_source_table source_table TYPE bloom_filter GRANULARITY 1,
    INDEX idx_source_id source_id TYPE bloom_filter GRANULARITY 1
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (source_table, source_id)
SETTINGS index_granularity = 8192;

-- Table: sql_cascade_executions - Track cascade invocations from SQL UDFs
CREATE TABLE IF NOT EXISTS sql_cascade_executions (
    `caller_id` String,
    `session_id` String,
    `cascade_id` String,
    `cascade_path` String,
    `inputs_summary` String DEFAULT '',
    `timestamp` DateTime64(3) DEFAULT now64(3),
    INDEX idx_caller caller_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_session session_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_cascade cascade_id TYPE bloom_filter GRANULARITY 1
) ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (caller_id, timestamp)
TTL timestamp + toIntervalDay(90)
SETTINGS index_granularity = 8192;

-- Table: test_events - Test event logging
CREATE TABLE IF NOT EXISTS test_events (
    `event_id` String DEFAULT generateUUIDv4(),
    `event_type` String,
    `severity` String DEFAULT 'info',
    `message` String,
    `value` Float64 DEFAULT 0,
    `created_at` DateTime64(3) DEFAULT now64()
) ENGINE = MergeTree
ORDER BY (created_at, event_id)
SETTINGS index_granularity = 8192;

-- Table: training_annotations - Human annotations for training data
CREATE TABLE IF NOT EXISTS training_annotations (
    `trace_id` String,
    `trainable` Bool DEFAULT false,
    `verified` Bool DEFAULT false,
    `confidence` Nullable(Float32) DEFAULT NULL,
    `notes` String DEFAULT '',
    `tags` Array(String) DEFAULT [],
    `annotated_at` DateTime64(3) DEFAULT now64(3),
    `annotated_by` String DEFAULT 'human',
    INDEX idx_trainable trainable TYPE set(0) GRANULARITY 1,
    INDEX idx_verified verified TYPE set(0) GRANULARITY 1
) ENGINE = ReplacingMergeTree(annotated_at)
ORDER BY trace_id
SETTINGS index_granularity = 8192;

-- Table: watches - Scheduled SQL watch definitions
CREATE TABLE IF NOT EXISTS watches (
    `watch_id` String,
    `name` String,
    `query` String,
    `action_type` Enum8('cascade' = 1, 'signal' = 2, 'sql' = 3),
    `action_spec` String,
    `poll_interval_seconds` UInt32 DEFAULT 300,
    `enabled` Bool DEFAULT true,
    `last_result_hash` Nullable(String),
    `last_checked_at` Nullable(DateTime64(3)),
    `last_triggered_at` Nullable(DateTime64(3)),
    `trigger_count` UInt64 DEFAULT 0,
    `consecutive_errors` UInt32 DEFAULT 0,
    `last_error` Nullable(String),
    `created_at` DateTime64(3) DEFAULT now64(),
    `updated_at` DateTime64(3) DEFAULT now64(),
    `created_by` String DEFAULT '',
    `description` String DEFAULT '',
    `inputs_template` String DEFAULT '{"trigger_rows": {{ rows | tojson }}, "watch_name": "{{ watch_name }}"}',
    INDEX idx_watch_name name TYPE bloom_filter GRANULARITY 1,
    INDEX idx_watch_enabled enabled TYPE set(2) GRANULARITY 1
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY watch_id
SETTINGS index_granularity = 8192;

-- Table: watch_executions - Watch execution history
CREATE TABLE IF NOT EXISTS watch_executions (
    `execution_id` String,
    `watch_id` String,
    `watch_name` String,
    `triggered_at` DateTime64(3),
    `completed_at` Nullable(DateTime64(3)),
    `duration_ms` Nullable(UInt32),
    `row_count` UInt32,
    `result_hash` String,
    `result_preview` String,
    `action_type` Enum8('cascade' = 1, 'signal' = 2, 'sql' = 3),
    `cascade_session_id` Nullable(String),
    `signal_fired` Nullable(String),
    `status` Enum8('triggered' = 1, 'running' = 2, 'success' = 3, 'failed' = 4, 'skipped' = 5),
    `error_message` Nullable(String),
    `cost` Nullable(Decimal(18, 6)),
    `tokens_in` Nullable(UInt32),
    `tokens_out` Nullable(UInt32),
    INDEX idx_exec_watch_id watch_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_exec_status status TYPE set(8) GRANULARITY 1,
    INDEX idx_exec_cascade_session cascade_session_id TYPE bloom_filter GRANULARITY 1
) ENGINE = MergeTree
PARTITION BY toYYYYMM(triggered_at)
ORDER BY (watch_name, triggered_at)
TTL triggered_at + toIntervalDay(90)
SETTINGS index_granularity = 8192;

-- ============================================================================
-- PART 2: MATERIALIZED VIEWS
-- ============================================================================

-- MV: species_stats - Aggregated prompt lineage statistics
CREATE MATERIALIZED VIEW IF NOT EXISTS species_stats
ENGINE = SummingMergeTree
ORDER BY (species_hash, cascade_id, cell_name)
SETTINGS index_granularity = 8192
AS SELECT
    species_hash,
    cascade_id,
    cell_name,
    count() AS total_prompts,
    countIf(is_winner = true) AS winner_count,
    countIf((is_winner = false) OR (is_winner IS NULL)) AS loser_count,
    countDistinct(session_id) AS session_count,
    countDistinct(model) AS model_count,
    sum(cost) AS total_cost,
    avg(cost) AS avg_cost,
    avgIf(cost, is_winner = true) AS avg_winner_cost,
    avgIf(cost, is_winner = false) AS avg_loser_cost,
    max(generation) AS max_generation,
    countIf(generation = 0) AS base_prompts,
    countIf(generation > 0) AS evolved_prompts,
    min(created_at) AS first_seen,
    max(created_at) AS last_seen
FROM prompt_lineage
GROUP BY species_hash, cascade_id, cell_name;

-- MV: mv_sql_query_costs - SQL query cost aggregation
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_sql_query_costs
ENGINE = SummingMergeTree
ORDER BY caller_id
SETTINGS index_granularity = 8192
AS SELECT
    caller_id,
    sum(cost) AS total_cost,
    sum(tokens_in) AS total_tokens_in,
    sum(tokens_out) AS total_tokens_out,
    count() AS llm_calls_count
FROM unified_logs
WHERE (caller_id != '') AND (caller_id LIKE 'sql-%%') AND (cost IS NOT NULL)
GROUP BY caller_id;

-- MV: mv_watch_stats - Watch execution statistics
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_watch_stats
ENGINE = SummingMergeTree
ORDER BY watch_name
SETTINGS index_granularity = 8192
AS SELECT
    watch_name,
    count() AS execution_count,
    countIf(status = 'success') AS success_count,
    countIf(status = 'failed') AS failed_count,
    sum(coalesce(cost, 0)) AS total_cost,
    sum(coalesce(tokens_in, 0)) AS total_tokens_in,
    sum(coalesce(tokens_out, 0)) AS total_tokens_out,
    avg(duration_ms) AS avg_duration_ms,
    max(triggered_at) AS last_triggered_at
FROM watch_executions
GROUP BY watch_name;

-- ============================================================================
-- PART 3: REGULAR VIEWS
-- ============================================================================

-- View: render_entries - Render content from unified_logs
CREATE VIEW IF NOT EXISTS render_entries AS
SELECT
    session_id,
    trace_id,
    parent_id,
    timestamp_iso,
    cascade_id,
    cell_name,
    content_type,
    content_json,
    metadata_json,
    candidate_index,
    role,
    node_type,
    JSONExtractString(metadata_json, 'screenshot_path') AS screenshot_path,
    JSONExtractString(metadata_json, 'screenshot_url') AS screenshot_url,
    JSONExtractString(metadata_json, 'checkpoint_id') AS checkpoint_id
FROM unified_logs
WHERE content_type LIKE 'render:%%'
ORDER BY timestamp_iso DESC;

-- View: request_decision_renders - Decision request renders
CREATE VIEW IF NOT EXISTS request_decision_renders AS
SELECT
    session_id,
    trace_id,
    timestamp_iso,
    cascade_id,
    cell_name,
    content_json AS ui_spec,
    JSONExtractString(metadata_json, 'screenshot_path') AS screenshot_path,
    JSONExtractString(metadata_json, 'screenshot_url') AS screenshot_url,
    JSONExtractString(metadata_json, 'checkpoint_id') AS checkpoint_id,
    JSONExtractString(metadata_json, 'question') AS question,
    JSONExtractString(metadata_json, 'severity') AS severity,
    JSONExtractBool(metadata_json, 'has_html') AS has_html,
    JSONExtractInt(metadata_json, 'options_count') AS options_count,
    candidate_index
FROM unified_logs
WHERE content_type = 'render:request_decision'
ORDER BY timestamp_iso DESC;

-- View: training_examples_mv - Training examples from logs
CREATE VIEW IF NOT EXISTS training_examples_mv AS
SELECT
    trace_id,
    session_id,
    timestamp,
    cascade_id,
    cell_name,
    if((full_request_json IS NOT NULL) AND (full_request_json != ''), substring(full_request_json, 1, 2000), '') AS user_input,
    coalesce(content_json, '') AS assistant_output,
    model,
    cost,
    tokens_in,
    tokens_out,
    duration_ms,
    caller_id,
    node_type,
    role
FROM unified_logs
WHERE (role = 'assistant') AND (cascade_id != '') AND (content_json IS NOT NULL) AND (content_json != '');

-- View: training_examples_with_annotations - Training examples joined with annotations
CREATE VIEW IF NOT EXISTS training_examples_with_annotations AS
SELECT
    mv.*,
    coalesce(ta.trainable, false) AS trainable,
    coalesce(ta.verified, false) AS verified,
    ta.confidence AS confidence,
    ta.notes,
    ta.tags,
    ta.annotated_at,
    ta.annotated_by
FROM training_examples_mv AS mv
LEFT JOIN training_annotations AS ta ON mv.trace_id = ta.trace_id;

-- View: training_stats_by_cascade - Training statistics by cascade
CREATE VIEW IF NOT EXISTS training_stats_by_cascade AS
SELECT
    cascade_id,
    cell_name,
    countIf(trainable = true) AS trainable_count,
    countIf(verified = true) AS verified_count,
    avg(confidence) AS avg_confidence,
    count() AS total_executions
FROM training_examples_with_annotations
GROUP BY cascade_id, cell_name
ORDER BY trainable_count DESC;
