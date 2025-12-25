-- Add request_path and page_ref columns to ui_sql_log table
-- These columns help track which API endpoint and browser page triggered each query

ALTER TABLE ui_sql_log ADD COLUMN IF NOT EXISTS request_path Nullable(String);
ALTER TABLE ui_sql_log ADD COLUMN IF NOT EXISTS page_ref Nullable(String);

-- Add index for page_ref to enable efficient filtering by page
ALTER TABLE ui_sql_log ADD INDEX IF NOT EXISTS idx_page_ref page_ref TYPE bloom_filter GRANULARITY 1;
