# RVBBIT Framework Analysis (Terse)

## How it runs (execution flow)
- Load cascade config (YAML/JSON) into typed models; merge inputs/overrides.
- Create session (Echo) with state/history/lineage; start tracing, logging, and heartbeat.
- For each cell, build context (explicit or auto; intra-phase compression if enabled).
- Execute by cell type:
  - LLM cell: render instructions, select tools (explicit or manifest), run turn loop, apply candidates/wards/loop_until.
  - Deterministic cell: resolve tool (python/sql/shell/HTTP/composite), render inputs, retry/timeout, route by result.
  - SQL mapping: fan-out per row into sub-cascades, collect into result tables.
- Save outputs to lineage/state, emit events/graphs/logs, handle handoffs or routing.
- Optional subsystems: audibles, narrator, HITL checkpoints, browser sessions, tool cache, token budget, memory.

## Core building blocks
- Cascade: workflow with inputs_schema, triggers, and ordered cells.
- Cells: LLM, deterministic tool, or SQL mapping (for_each_row).
- Traits/tools: python functions, declarative tools (.tool.json/.tool.yaml), cascades-as-tools, Harbor (Gradio/HF Spaces).
- Echo: persistent session store (state + history + lineage + metadata) + unified logging.
- Context system: explicit selectors, auto-selection, intra-phase masking/compression.

## Execution features (LLM + hybrid)
- Candidates (soundings): parallel attempts, evaluator selection or aggregate, multi-model, cost-aware, mutations.
- Reforge: iterative refinement of winners with validator thresholds.
- Wards: validation gates (blocking, advisory, retry) pre/post/turn.
- loop_until and retry controls (max_turns/max_attempts).
- Auto-fix for deterministic tool failures with LLM repair.
- Routing: handoffs + route_to tool; map_cascade; dynamic fan-out.

## Data/SQL layer
- Session-scoped DuckDB with temp tables for cross-cell data flow.
- SQL UDFs: rvbbit_udf (single call) + rvbbit_cascade_udf (full cascade per row).
- PostgreSQL wire-protocol server (DBeaver/psql/Tableau) + HTTP SQL client.
- Unified logs in Parquet with chDB/ClickHouse querying (all_data, all_evals).

## Observability + artifacts
- Trace tree with Mermaid graphs; SSE events for live UI.
- Cost/token tracking and model metadata in logs.
- Artifact capture: images, charts, audio, browser screenshots/DOM snapshots.
- Snapshot testing from real runs (freeze/validate).

## Integrations + modalities
- Browser automation (Rabbitize) with visual actions and captures.
- Voice: TTS/STT + transcription pipelines.
- RAG indexing and retrieval.
- Signals (await/fire) for cross-cascade coordination; triggers for cron/sensor/webhook/manual.
- Generative UI/HTMX for rich human-in-the-loop steps.

## Example-derived patterns (examples/)
- Candidates + multi-model eval: `examples/soundings_flow.yaml`, `examples/soundings_aggregate_demo.yaml`.
- Reforge + evaluation: `examples/reforge_*`.
- Context controls: `examples/context_*`, `examples/auto_context_demo.yaml`.
- Deterministic/data cascades: `examples/data_cascade_test.yaml`, `examples/notebook_*`.
- Mapping/fan-out: `examples/test_map_cascade.yaml`, `examples/test_sql_mapping.yaml`.
- HITL + generative UI: `examples/generative_ui_demo.yaml`, `examples/htmx_*`.
- Browser automation: `examples/rabbitize_*`.
- Signals + coordination: `examples/signal_*`.
- SQL + UDFs: `examples/test_windlass_udf.yaml`, `examples/sql_*`.
- Audio/voice: `examples/tts_test.yaml`, `examples/harbor_whisper_test.yaml`.
