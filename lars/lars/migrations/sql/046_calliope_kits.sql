-- Calliope Kits: Micro-app project management
-- Stores metadata for user-created kits (FastAPI + React apps)

CREATE TABLE IF NOT EXISTS calliope_kits (
    kit_id String,
    template String DEFAULT 'basic',
    port UInt16 DEFAULT 0,
    status Enum8('created'=1, 'starting'=2, 'running'=3, 'stopped'=4, 'error'=5) DEFAULT 'created',
    pid Nullable(UInt32),
    error_message Nullable(String),
    lars_url String DEFAULT 'postgresql://localhost:5432/default',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY kit_id;
