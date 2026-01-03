# Semantic SQL Structural Rewriter v2 (Plan)

This plan covers the “structural” portion of Semantic SQL: rewrites that change query shape or scope (CTEs, derived tables, GROUP BY semantics, JOIN shape), as opposed to simple expression desugaring.

Expression-level v2 is already in place (`rvbbit/rvbbit/sql_tools/semantic_rewriter_v2.py`) and legacy expression rewrites have been removed so we have a clean separation.

## Goals

- Replace the remaining regex-heavy query-shape rewrites with a scope-aware implementation.
- Be explicit and honest for v0: reject/skip ambiguous cases rather than guessing.
- Preserve current YAML operator shapes (infix + function style) for **expression-level** operators.
- Keep `-- @ ...` comment hints working (model/prompt/threshold), with predictable scoping.
- Maintain a safe fallback path while structural v2 rolls out.

## Non-Goals (v0)

- No “magic” context inference (already removed for `EMBED(...)` / `VECTOR_SEARCH(...)` sugar).
- No attempt to outsmart DuckDB’s planner with ad-hoc parallelism hacks (UNION ALL splitting removed).
- No full SQL “optimizer” reimplementation.

## Current Structural Surface Area (Remaining)

In `rvbbit/rvbbit/sql_tools/semantic_operators.py`:

- `SEMANTIC DISTINCT ...` (query-shape rewrite with CTEs + dedupe)
- `GROUP BY MEANING(...)` (query-shape rewrite with clustering CTE)
- `GROUP BY TOPICS(...)` (query-shape rewrite with topic extraction + classification)
- `SEMANTIC JOIN ... ON ...` + `_fix_double_where(...)` (JOIN-to-CROSS-JOIN + WHERE condition surgery)

## Recommendation: Structural v2 as a Separate Module

Add a dedicated module, e.g.:

- `rvbbit/rvbbit/sql_tools/semantic_structural_rewriter_v2.py`

and wire it in from `rvbbit/rvbbit/sql_rewriter.py` after expression rewrite:

1) expression v2 (token-aware)  
2) structural v2 (scope-aware)  
3) legacy structural fallback for features not yet migrated (temporary)

## Parsing Strategy (Practical + Honest)

Structural rewrites need scope awareness (top-level vs subquery/CTE, GROUP BY list vs SELECT list, JOIN graph). Regex is fragile here.

### Use `sqlglot` where possible

`sqlglot` is already in the repo (`rvbbit/rvbbit/sql_trail.py`). For structural v2:

- Parse with DuckDB dialect when the input is valid SQL (after expression rewrite).
- Rewrite using AST transforms and re-render to SQL.

### Token-aware “custom keyword” handling where needed

Some constructs are not standard SQL keywords and may not parse cleanly:

- `SEMANTIC DISTINCT`
- `SEMANTIC JOIN`

For these, structural v2 should either:

- (Preferred) pre-tokenize and rewrite the custom syntax into a parseable form **before** AST parsing, or
- (Initially) implement a small scope-aware tokenizer matcher for the specific construct (no generic regex).

## Milestones

### Milestone 1 — `GROUP BY MEANING(...)` via AST

Why first:
- Parseable as a function call (`MEANING(...)`) inside `GROUP BY`.
- Highest “planner interaction” value; AST makes it less error-prone than regex.

Acceptance:
- Handles single-table, joins, and `WITH ...` queries.
- Respects aliases in SELECT list.
- Rejects or falls back when `MEANING(...)` appears in nested subqueries in ways that require planner-level coordination.

Tests:
- Add dedicated tests (not just string contains) that validate:
  - group-by key replacement
  - preservation of SELECT columns and ORDER BY
  - stable behavior under whitespace/comments

### Milestone 2 — `GROUP BY TOPICS(...)` via AST

Similar to Milestone 1, but:
- Needs deterministic mapping from topic assignment output to a grouping key.
- Should enforce constraints if output shape is ambiguous.

Acceptance:
- Same as Milestone 1 + explicit failure modes.

### Milestone 3 — `SEMANTIC DISTINCT` (scope-aware tokenizer + AST)

Why later:
- `SEMANTIC DISTINCT` is a custom SELECT modifier; might not parse as-is.

Approach:
- Detect `SELECT SEMANTIC DISTINCT <expr>` at top-level with a token stream (skip strings/comments).
- Rewrite into a canonical CTE form (current behavior), then parse/render with sqlglot for formatting/robustness.

Acceptance:
- Works for `FROM table` and `FROM (subquery)` at top-level.
- Rejects ambiguous multi-column distinct and nested variants (v0).

### Milestone 4 — `SEMANTIC JOIN`

Hardest:
- It’s a custom JOIN keyword + needs correct scoping for WHERE injection.
- Doing this honestly requires building/understanding the JOIN tree and WHERE clause scope.

Approach:
- Token-detect `SEMANTIC JOIN` at top-level FROM/JOIN chain.
- Convert to a standard JOIN shape in AST:
  - likely rewrite to `CROSS JOIN` + add conjunct to `WHERE`
  - preserve existing `WHERE` by AND’ing inside the same scope (no `_fix_double_where` hacks)

Acceptance:
- Works for single semantic join clause in simple queries.
- Explicitly rejects multi-line / deeply nested / multiple semantic joins until supported.

## Annotation Handling (Structural Phase)

Keep `-- @ ...` parsing centralized:
- One shared annotation parser that produces a stream of directives with scope boundaries.
- Expression rewriter consumes “next operator” annotations.
- Structural rewriter consumes “query-level” annotations only where explicitly supported.

Do not allow `-- @ parallel:` to affect SQL (already no-op).

## Rollout / Safety

- Keep legacy structural rewrites available behind an internal fallback while migrating features incrementally.
- Prefer “fail closed” for ambiguous constructs:
  - either return original SQL unchanged (and log)
  - or raise a clear syntax error telling the user the explicit alternative / supported subset

## Work Breakdown / LOE (Rough)

- Milestone 1: 1–2 days (AST transform + tests)
- Milestone 2: 1–3 days (depends on desired TOPICS output handling)
- Milestone 3: 1–2 days (token detection + canonical rewrite + tests)
- Milestone 4: 2–5 days (JOIN tree handling + careful scoping + tests)

## Concrete Next Action

Start with Milestone 1 (`GROUP BY MEANING`) in a new `semantic_structural_rewriter_v2.py`, wire it into `rvbbit/rvbbit/sql_rewriter.py` behind the existing v2 pipeline (with legacy fallback), and add a focused test suite:

- `rvbbit/tests/test_semantic_sql_structural_rewriter_v2.py`

