# RVBBIT PIPELINE (v0 Proposal)

## Intent

Make parallelism and mixed-scope semantic SQL approachable by providing an explicit, opaque, “staged query” construct that RVBBIT executes as a linear pipeline.

Key idea:
- Let DuckDB do **relational planning** within each stage.
- Let RVBBIT parallelize **row-scalar semantic work** when a stage is eligible.
- Avoid trying to parallelize mixed scalar+aggregate semantics inside one SQL statement in v0.

This is UX sugar; it does not change the long-term rewriter/parser plans, but it provides a clean v0 story.

---

## Syntax (explicit, non-standard SQL)

```sql
RVBBIT PIPELINE
  stage1 AS (
    -- any SQL query (may include semantic scalar operators)
    SELECT ...
  ),
  stage2 AS (
    -- may reference earlier stages by name
    SELECT ... FROM stage1 ...
  )
SELECT ... FROM stage2 ...;
```

Rules (v0):
- A pipeline contains **N named stages** and a **final SELECT**.
- Each stage query is a parenthesized SQL fragment.
- Stage names are identifiers.
- Later stages may reference earlier stage names as tables/views.
- RVBBIT executes stages **in order**, materializing each into a temp table.

---

## Execution Semantics

RVBBIT decomposes the pipeline into a deterministic execution plan:

1) For each stage `stage_k`:
   - Rewrite its SQL (semantic sugar → function calls, etc.)
   - Materialize it:
     - `CREATE TEMP TABLE __rvbbit_pipeline_<nonce>_stage_k AS (<stage_sql>)`
   - Replace references to `stage_k` in subsequent stages/final query with the temp table name.

2) Execute the final query against the last stage (or any referenced stage):
   - `(<final_sql>)`

3) Cleanup:
   - `DROP TABLE` for all stage tables in a `finally` block, unless explicitly retained.

Observability:
- The pipeline should share one `caller_id` so `sql_query_log` and runstream treat it as one “query”.
- Each stage can also emit stage-local metadata (stage name, row count, elapsed time).

---

## Parallelism Policy (v0 simplification)

Parallelism is only attempted when a stage is “row-scalar only”.

### Stage eligibility (v0)

Eligible:
- Stages whose semantic operations are exclusively row-scalar (per-row):
  - `ALIGNS`, `MEANS`, `EXTRACTS`, `ASK`, `SOUNDS_LIKE`, `SIMILAR_TO`, `IMPLIES`, `CONTRADICTS`, `ABOUT` (as a score)

Not eligible (v0):
- Semantic aggregates (`SUMMARIZE`, `THEMES/TOPICS`, `CONSENSUS`, etc.)
- Semantic grouping / mapping keys (`GROUP BY MEANING(...)`, `GROUP BY TOPICS(...)`)
- Structural transforms (`SEMANTIC JOIN`, `SEMANTIC DISTINCT`) unless explicitly implemented

If a stage is not eligible:
- Execute it serially as standard DuckDB SQL against already materialized upstream stages.
- Optionally log: “parallel skipped: reason”.

### User controls (optional)

Use existing hint style:

```sql
-- @ parallel: 8
-- @ batch_size: 50
-- @ use a fast model
RVBBIT PIPELINE ...
```

Semantics:
- `parallel`: max concurrent workers for semantic evaluation
- `batch_size`: max rows per chunk (backpressure)
- prompt/model hints: applied to semantic operators in that stage

---

## Why This Helps (v0)

This provides a single-query user experience while RVBBIT:
- safely materializes intermediate results,
- parallelizes scalar semantics where it actually matters (cascades/LLM work),
- avoids fragile “micro-queue per scalar call” execution,
- and keeps mixed-scope semantics understandable and debuggable.

---

## Examples

### 1) Parallel scalar semantics, then relational aggregate

```sql
RVBBIT PIPELINE
  scored AS (
    -- row-scalar semantic op (eligible for parallel batch eval)
    SELECT id, category, ALIGNS(text, 'SQL is good for AI') AS aligns_score
    FROM docs
  )
SELECT category, AVG(aligns_score) AS avg_align, COUNT(*) AS n
FROM scored
GROUP BY category
ORDER BY avg_align DESC;
```

### 2) Scalar filter stage, then summarize (v0 serial aggregate)

```sql
RVBBIT PIPELINE
  filtered AS (
    SELECT id, category, text
    FROM docs
    WHERE ALIGNS(text, 'SQL is good for AI') > 0.7
  )
SELECT category, SUMMARIZE(text) AS summary
FROM filtered
GROUP BY category;
```

### 3) “Artifact” workflow without extra user boilerplate

Instead of requiring users to manually `CREATE TEMP TABLE ...` and later drop it, PIPELINE handles:
- stage temp table creation
- naming collision avoidance
- cleanup (unless retained)

---

## Options / Extensions (future)

These are optional and can be added later without changing core syntax:

- `WITH (retain=true)` / `WITH (ttl='10m')` per stage
- Stage caching keys (`cache_key = '...'`) for expensive stages
- Explicit result schemas for stage tables
- Debug surface: `EXPLAIN RVBBIT PIPELINE ...` returning the decomposed plan
- “Batch semantic eval” operator:
  - rewrite scalar semantics within a stage into one coordinator call (instead of per-row UDFs)

---

## Implementation Notes (ties to Rewriter v2)

Parsing PIPELINE correctly requires:
- splitting stage definitions on commas **outside** parentheses/strings/comments
- locating the final SELECT boundary

This becomes straightforward once the token-based infrastructure exists (rewriter v2 tokenizer).

For v0, keep PIPELINE parsing separate from semantic operator rewriting:
- first parse PIPELINE structure
- then run the existing rewrite pipeline on each stage SQL fragment

---

## Limitations (v0)

- Stage definitions must be valid SQL fragments inside `(...)`.
- Pipeline execution is linear; only semantic work within eligible stages is parallelized.
- Nested PIPELINE blocks are not supported in v0.

