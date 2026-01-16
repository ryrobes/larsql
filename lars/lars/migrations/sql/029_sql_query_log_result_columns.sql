-- Migration: 029_sql_query_log_result_columns
-- Description: Add result location columns to sql_query_log for background query result tracking
-- Author: LARS
-- Date: 2026-01-16
--
-- These columns track where background query results are materialized:
-- - result_db_name: The DuckDB database name (e.g., 'myproject')
-- - result_db_path: Full path to the DuckDB file (e.g., 'session_dbs/myproject.duckdb')
-- - result_schema: Schema within the database (e.g., '_results_20260116')
-- - result_table: Table name within the schema (e.g., 'job_swift_fox_abc123')

-- Add result location columns
ALTER TABLE sql_query_log ADD COLUMN IF NOT EXISTS result_db_name Nullable(String) AFTER error_message;

ALTER TABLE sql_query_log ADD COLUMN IF NOT EXISTS result_db_path Nullable(String) AFTER result_db_name;

ALTER TABLE sql_query_log ADD COLUMN IF NOT EXISTS result_schema Nullable(String) AFTER result_db_path;

ALTER TABLE sql_query_log ADD COLUMN IF NOT EXISTS result_table Nullable(String) AFTER result_schema;
