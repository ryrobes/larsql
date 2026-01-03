# Semantic SQL Parallelism v0 (Supplement)

## Problem Statement

The current “UNION ALL parallelism” approach does not reliably yield true concurrency for semantic operators because:

- DuckDB may not parallelize the relevant parts of execution the way we want.
- The expensive work happens in Python/cascade execution and/or network calls (LLM/embedding providers), which do not automatically become parallel just because SQL has multiple branches.
- Scalar-per-row evaluation (`semantic_aligns(...)` in a WHERE/SELECT expression) is the worst possible shape for controllable throughput, caching, and backpressure.

**Goal:** Provide *real*, controllable parallel execution for Semantic SQL that:

- Parallelizes the **work** (cascades/LLM calls), not just the SQL text.
- Preserves SQL semantics (correctness under subqueries/CTEs).
- Preserves observability: `caller_id` propagation, `sql_query_log`, runstream.
- Allows safe rollout and fallback.

---

## Key Design Decision

Treat “semantic operator evaluation” as a **batchable execution primitive** (MAP-like), not as N independent scalar UDF calls.

That means the rewriter’s job is to reshape a query into an explicit *batch evaluation plan*, and a coordinator’s job is to run that plan concurrently with chunking and rate limiting.

---

## Recommended v0 Approach: Batch Evaluation UDF + Coordinator

### High-level shape

1) SQL produces a candidate row set (pure DuckDB work).
2) A single “batch semantic eval” call processes those rows in chunks, in parallel, using RVBBIT’s runner/executor.
3) Results are joined back into the query in DuckDB.

### Conceptual rewritten shape (example)

User SQL:

```sql
SELECT id, (ALIGNS(text, 'SQL is good for AI')) AS score
FROM docs
WHERE (ALIGNS(text, 'SQL is good for AI')) > 0.7;
```

Rewritten (hand-wavy):

```sql
WITH __base AS (
  SELECT id, text FROM docs
),
__semantic AS (
  -- Returns rows: (id, score)
  SELECT * FROM read_json_auto(
    rvbbit_semantic_batch_eval_json(
      'semantic_aligns',
      (SELECT to_json(list(struct_pack(id:=id, text:=text))) FROM __base),
      '{"criterion":"SQL is good for AI","parallel":8,"batch_size":50,"annotation":"use a fast model"}'
    )
  )
)
SELECT b.id, s.score
FROM __base b
JOIN __semantic s USING (id)
WHERE s.score > 0.7;
```

Notes:
- The coordinator behind `rvbbit_semantic_batch_eval_json` controls true parallelism.
- DuckDB just joins results and filters—cheap and deterministic.

### What the “coordinator” does

Given a batch of input rows, it:

- Splits into chunks (`batch_size`).
- Runs each chunk concurrently (`parallel`), via threadpool/async.
- Applies caching and dedupe at the chunk and/or row level.
- Applies retry/backoff, provider rate limits, and budgets.
- Emits per-row and per-chunk logs with `caller_id` propagation.

This solves the “tiny chunks inside a bigger chunk” issue by centralizing chunk control in one place.

---

## Alternative v0 Approach: “Temp Cascade” + MAP-Over-Rowset (Your Idea)

This is a very viable way to reuse your already-good `RVBBIT MAP PARALLEL ... USING (...)` execution path.

### Concept

If the semantic operator in the SQL can be expressed as a simple cascade spec (YAML), the rewriter can:

1) Generate a tiny “temporary cascade” for the operator invocation (or select an existing canonical cascade).
2) Materialize the input rowset (or a projected subset).
3) Execute **one** MAP PARALLEL over that rowset (chunked + concurrent).
4) Join results back into the original query.

### Why it’s attractive

- Leverages a proven parallel execution mechanism you already had working.
- Natural place to implement chunking/backpressure/logging.
- Keeps “semantic ops” as cascades, aligning with “cascades all the way down”.

### Key constraint (important)

DuckDB UDFs and pgwire sessions are typically “stateless” from SQL’s perspective.
To do “temp cascade” generation safely you need:

- A deterministic cache key for the generated cascade spec (so repeated queries reuse it).
- A safe storage location scoped by session/caller_id (and cleaned up).
- Or: keep a small set of canonical cascades and pass params as inputs (preferred in v0).

### v0 practical compromise

Instead of literally writing new YAML files at runtime, treat the “temp cascade” as:

- **an in-memory cascade definition** passed directly to the runner, or
- a **canonical cascade** (e.g., `semantic_aligns`) + **inputs** (criterion, etc.) that fully define the run.

This preserves the “shape” idea without introducing file lifecycle complexity.

---

## v0 UX Sugar: `RVBBIT PIPELINE` (Recommended)

To make staged execution approachable (especially when mixed scalar + non-scalar semantics are present),
introduce an explicit, opaque “pipeline” construct that RVBBIT decomposes into a linear sequence of
materialized stages plus a final query.

See: `RVBBIT_PIPELINE_V0.md`.

The key v0 simplification pairs naturally with PIPELINE:
- allow true parallelism only when a stage is row-scalar-only
- otherwise, run that stage serially as normal SQL against the materialized upstream artifacts

This avoids complex “micro-queue per scalar call” execution while still enabling real concurrency where it matters.

---

## Where This Integrates with the Rewriter v2 Plan

This parallelism design pairs best with the Token+AST rewriter v2:

### Token phase
- Detect semantic operator occurrences and bind `-- @` hints to them.

### AST phase
- For each `SELECT` scope:
  - Identify eligible semantic operator expressions (the ones to batch).
  - Extract required input columns/expressions.
  - Rewrite the query to:
    - compute the base rowset,
    - call batch eval once (per operator),
    - join results back, and
    - replace the original operator expression with the computed column.

This makes nesting/subqueries safe because the transformation is per-scope.

---

## Mixed Scalar + Non-scalar Semantic Ops (Unit-of-Work Model)

Mixed scalar and non-scalar semantic operations are where the “unit of work” becomes
hard to reason about unless we explicitly align with SQL’s evaluation phases and scope.

### Classify semantics by scope

1) **Row-scalar (per-row)**
   - One output per input row.
   - Examples: `ALIGNS`, `MEANS`, `EXTRACTS`, `ASK`, `SOUNDS_LIKE`, `SIMILAR_TO`, `IMPLIES`, `CONTRADICTS`, `ABOUT` (as a score).
   - Batchable by materializing a base rowset with a stable key (`id` or synthetic `row_id`).

2) **Group-scalar (per-group aggregate)**
   - One output per group.
   - Examples: `SUMMARIZE`, `THEMES/TOPICS`, `CONSENSUS`, `OUTLIERS`, etc.
   - Parallelism typically happens across groups (or map-reduce for large groups).

3) **Mapping / key derivation (used in GROUP BY / DISTINCT-like semantics)**
   - Produces a derived key per row, then relational SQL groups on that key.
   - Example: `GROUP BY MEANING(text)` (semantic clustering).

4) **Table-producing (candidate-set generation)**
   - Produces a derived relation.
   - Example: `VECTOR_SEARCH(...)`.

### A staged execution model per SELECT scope (v0-friendly)

For each `SELECT` (including nested subqueries/CTEs), construct a staged plan:

1) **Base rowset stage**
   - Pure relational work in DuckDB: project only the columns needed for semantic ops + final output.
   - Ensure a stable join key exists (`id` if present, else add a synthetic key).

2) **Row-scalar semantic stage**
   - Batch-evaluate all scalar semantic expressions over the base rowset in chunks with RVBBIT parallelism.
   - Join results back as computed columns.
   - After this stage, downstream SQL sees ordinary columns and can filter/order normally.

3) **Grouping / mapping stage (when present)**
   - If the query uses semantic grouping (e.g., `GROUP BY MEANING(...)`), compute the group key per row (batchable),
     join it back, then let DuckDB perform the GROUP BY.

4) **Group aggregate semantic stage**
   - For each group, run the semantic aggregate in parallel across groups (or hierarchical map-reduce if groups are large).
   - Join aggregate outputs back by group key.

5) **Final relational stage**
   - Ordinary SQL for SELECT / ORDER BY / LIMIT using computed columns.

This provides a clear, honest “unit of work”:
- **per row** for scalar ops,
- **per group** for aggregates,
- **per SELECT scope** for nesting correctness.

### v0 constraints (to keep behavior predictable)

Start conservative and expand:

- Allow unlimited scalar semantic columns/predicates (batchable).
- Allow semantic aggregates, but only when their inputs are relationally well-defined after scalar stages.
- Treat semantic grouping (`MEANING/TOPICS` as group keys) as a dedicated feature with explicit planning.
- If the planner detects a mixed pattern it can’t stage safely, fall back to serial execution for that scope and log why.

---

## “Materialize Everything” vs “Leverage the SQL Planner”

It’s tempting (especially from a functional/Lisp mindset) to resolve inner pieces by
materializing many temp tables and stitching them back together. That can work, but it
can also discard decades of SQL planner optimizations.

The recommended approach here is a hybrid:

- Let DuckDB do **relational planning** (joins, filters, projections, grouping) as much as possible.
- Materialize only where the SQL engine cannot help: the semantic operations themselves.
- Prefer ephemeral CTEs / temp views over persistent tables.
- Keep materialization local to the smallest scope that needs it (per-`SELECT` scope).

In practice, “different arbitrary scopes” become tractable because:
- the AST phase gives you accurate `SELECT` boundaries,
- and each boundary gets a small staged plan (base → scalar → grouping → aggregates → final).

---

## Eligibility Rules (v0)

Start conservative:

Eligible for batch parallelization:
- Scalar operators with per-row semantics (MEANS/ALIGNS/EXTRACTS/ASK/SOUNDS_LIKE/SIMILAR_TO/IMPLIES/CONTRADICTS/ABOUT if explicit comparison).

Not eligible in v0:
- Operators that require query-shape transforms already (SEMANTIC JOIN, GROUP BY MEANING, SEMANTIC DISTINCT) until specifically implemented.
- Aggregates that inherently operate over collections unless they have a dedicated batch strategy.

---

## Configuration / Annotation Surface (v0)

Reuse existing hinting style:

```sql
-- @ parallel: 8
-- @ batch_size: 50
-- @ use a fast model
SELECT id, ALIGNS(text, 'SQL is good for AI') AS score
FROM docs;
```

Semantics:
- `parallel`: max concurrent chunk workers
- `batch_size`: max rows per chunk (backpressure + memory control)
- free-form prompt: carried to the operator (criterion prefixing, etc.)

---

## LOE (rough)

If implemented as “batch eval UDF + coordinator”:
- v0 single-operator batching + join-back: ~1–2 weeks (depends on how much AST rewrite work is already done).

If implemented as “canonical cascade + MAP PARALLEL over materialized rowset”:
- Similar LOE, but shifts complexity into:
  - materialization + join-back correctness,
  - session scoping,
  - coordinating result schema.

---

## Acceptance Criteria (v0)

- `-- @ parallel` produces real concurrent cascade execution (observable via logs/timing).
- Works for `ALIGNS(text, '...')` in:
  - SELECT list
  - WHERE predicate (via computed column)
  - nested subqueries (per-scope handling)
- Preserves SQL Trail logging (`sql_query_log`) and runstream lineage under parallel execution.
- Feature-flagged and fallbacks gracefully when not eligible.
