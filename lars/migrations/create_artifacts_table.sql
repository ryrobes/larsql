-- Artifacts table for persistent rich UI outputs
-- Stores HTML/HTMX dashboards, reports, charts, and interactive content

CREATE TABLE IF NOT EXISTS artifacts (
    id String,
    session_id String,
    cascade_id String,
    cell_name String,
    title String,
    artifact_type String,  -- dashboard, report, chart, table, analysis, custom
    description String,
    html_content String,   -- Full HTML page content
    tags String,           -- JSON array of tags
    created_at DateTime,
    updated_at DateTime
)
ENGINE = MergeTree()
ORDER BY (cascade_id, created_at);

-- Indexes for common queries
-- Note: ClickHouse uses ORDER BY for primary index
-- Additional filtering on artifact_type and tags happens at query time
