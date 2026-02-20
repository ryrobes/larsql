# Studio Shadow Read Store (v1)

## Goal

Provide a **single-writer, multi-reader** DuckDB mirror for Studio API read paths so
high-frequency polling no longer hits parquet globs/files directly.

Parquet remains the source of truth for writes.

## Current v1 shape

- File: `data/system/studio_shadow.duckdb`
- Leader lock: `data/system/.studio_shadow.lock`
- Freshness heartbeat: `data/system/.studio_shadow.heartbeat`
- Refresh cadence: ~`0.75s`
- Stale cutoff for read usage: `5s` (fallback to primary parquet-backed adapter)

## Source tables mirrored

- `unified_logs_base`
- `costs` (deduped by `trace_id`, latest `timestamp`)
- `session_state` (deduped by `session_id`, latest `updated_at`)
- `cascade_analytics`
- `cell_analytics`
- `cascade_sessions` (deduped by `session_id`, latest `created_at`)

Derived view:

- `unified_logs` = `unified_logs_base` LEFT JOIN deduped `costs`

## Refresh strategy

Per table:

1. Scan source parquet files under `data/system/<table>/**/*.parquet`
2. Compare file metadata against shadow manifest (`size`, `mtime_ns`)
3. Apply:
   - **append-only delta insert** when only new files appear
   - **full rebuild** when files were removed/changed (e.g., compaction rewrite)

This keeps normal append workloads fast while still recovering safely from
compaction/file rewrites.

## Why this handles append-only "mutation duplicates"

- Tables that use append-only update semantics are materialized with explicit
  dedup rules in shadow (`costs`, `session_state`, `cascade_sessions`).
- `unified_logs_base` remains raw append data (no aggressive dedup) to avoid
  accidentally removing legitimate log rows.

## Read routing behavior

For selected Studio endpoints (currently session stream):

1. Try shadow read
2. If shadow unavailable/stale/query-fails → fallback to primary DB adapter

This keeps reliability identical to current behavior while reducing parquet I/O.

## Compaction recommendation for this phase

For this experiment, keep runtime auto-compaction off and rely on manual/startup
compaction. This reduces concurrent rewrite churn while validating shadow-reader
behavior and latency impact.
