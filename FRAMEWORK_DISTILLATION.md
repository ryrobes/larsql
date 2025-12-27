# RVBBIT Distillation (Terse)

## Core story (what matters)
- Declarative cascades that replace imperative retry glue with structured workflows.
- Parallel candidates + evaluation as the default reliability/quality mechanism.
- Hybrid execution: LLM cells, deterministic tools, and polyglot data pipelines in one graph.
- SQL-first interface to LLMs (UDFs + Postgres wire protocol) for data teams.
- Full-stack runtime with observability: state, traces, logs, artifacts, UI.

## Novel or strongly differentiated
- Candidates + evaluator + reforge loops as first-class primitives (with mutation lineage).
- Session-scoped DuckDB temp tables as the data bus between cells.
- SQL UDFs that execute full cascades per row (rvbbit_cascade_udf).
- Manifest/Quartermaster tool selection to shrink prompts and enable emergent tooling.
- Audibles (mid-flight feedback injection) and generative HTMX UIs.
- Signals system with durable store + callback wakeups for cross-cascade coordination.
- Snapshot testing from real executions (freeze/validate).

## Distinctive combinations (each exists elsewhere, the bundle is rare)
- Visual cascade builder + live execution + stacked-deck candidate comparison.
- RAG + auto-context + token budgets + tool cache in one runtime.
- Browser automation + vision artifacts + LLM-driven evaluation/refinement.
- Data notebooks + LLM cells + deterministic ETL + SQL mapping in one format.

## Table-stakes / widely available
- Multi-model provider support, tool calling, basic retries.
- RAG/embeddings, memory, prompt templating, output schemas.
- Human-in-the-loop checkpoints and validation hooks.
- Browser automation, voice I/O, dashboards, SSE/event streams.
- Scheduling via cron/webhooks/sensors.

## Likely messaging focus
- Lead with: parallel candidates + evaluation, hybrid data cascades, SQL interface, and the IDE/observability story.
- Treat long-tail features as proof of breadth, not the headline.
