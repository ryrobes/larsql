# Semantic SQL Rewriter v2 Plan (Token + AST)

## Goals (v0)

- Preserve the current YAML-driven operator surface area:
  - `sql_function.name`, `sql_function.args`, `sql_function.operators`, `returns`, `shape`
  - Support both **infix** (`text ALIGNS WITH 'x'`) and **function-style** (`ALIGNS(text, 'x')`) patterns when defined in YAML.
- Preserve `-- @ ...` comment hinting (model hints / prompt prefix / threshold / parallel) with clearer scoping and zero interaction with strings/comments.
- Improve robustness vs regex by:
  - Never rewriting inside string literals or comments.
  - Performing scope-aware transforms for nested subqueries/CTEs.
- Allow safe rollout:
  - New module with feature flag + fallback to legacy rewrite.
  - Optional “shadow mode” (compare v1/v2 rewrites for debugging without changing execution).

## Non-goals (v0)

- Writing or maintaining a full SQL grammar (Lark-based SQL parser).
- Perfect equivalence of rewritten SQL text to the legacy output; correctness + compatibility matter more than byte-for-byte diffs.

---

## Architecture Overview

### New module boundary

Create a new module (example path):

- `rvbbit/rvbbit/sql_tools/semantic_rewriter_v2.py`

Public API:

- `rewrite_semantic_sql_v2(sql: str, *, duckdb_dialect: str = "duckdb") -> RewriteResult`

`RewriteResult` fields:

- `sql_out: str`
- `changed: bool`
- `errors: list[str]`
- `applied: list[str]` (e.g., `["infix:ALIGNS WITH", "order_by:RELEVANCE TO", "cte:VECTOR_SEARCH"]`)
- `annotations_used: list[dict]` (optional, for debugging)

### Two-phase rewrite pipeline

1) **Token phase (desugar, expression-safe)**
   - Lexer/tokenizer identifies: strings, comments, identifiers, punctuation/operators, whitespace.
   - Parse and bind `-- @ ...` annotations to the next eligible operator/expression span.
   - Rewrite infix operators into ordinary SQL function calls using registry/YAML specs.
   - Output remains valid SQL text (still may need structural transforms later).

2) **AST phase (scope-sensitive)**
   - After desugaring, parse with `sqlglot` using DuckDB dialect.
   - Walk **every `SELECT` scope**, including nested subqueries/CTEs.
   - Apply structural transforms safely within the correct scope.
   - Emit DuckDB-compatible SQL.

Fallback strategy:

- If v2 fails to tokenize/parse confidently (errors), return `errors` and let caller fall back to legacy.

---

## Operator Spec Compilation (from existing YAML)

### Inputs

From `semantic_sql.registry.get_sql_function_registry()` entries:

- `name` (SQL function name)
- `args` (ordered list with arg `name` and `type`)
- `operators` (templated strings)
- `shape`, `returns`

### Output specs

Compile `sql_function.operators` into two categories:

- **Infix specs**: patterns like `{{ text }} ALIGNS WITH {{ narrative }}` or `{{ text }} EXTRACTS '{{ what }}'`
  - Extract operator phrase (`ALIGNS WITH`, `EXTRACTS`, `RELEVANCE TO`, `~`, `!~`, etc.)
  - Extract placeholder names left/right (e.g., `text`, `narrative`)
  - Map placeholders → concrete arg order using `sql_function.args`

- **Function-style alias specs** (optional):
  - patterns like `TLDR({{ text }})`, `SIMILAR_TO({{ text1 }}, {{ text2 }})`, `VECTOR_SEARCH(...)`
  - If function alias is already registered as a DuckDB UDF (via dynamic registration), **no rewrite is required**.
  - Optionally, normalize aliases → canonical names for consistency in logging (e.g., `ALIGNS(` → `semantic_aligns(`).

This preserves today’s YAML shapes and keeps YAML as the source of truth.

---

## Expression vs AST Rewrites (what moves where)

This is the key robustness decision for nested subqueries.

### A) Token-phase (Expression-safe, nesting-safe)

These rewrite to ordinary SQL function calls and therefore work correctly inside:

- subqueries
- CTEs
- SELECT lists
- WHERE/HAVING predicates
- ON clauses

**Operators / constructs:**

- Generic infix operators from YAML that are true expression-level sugar:
  - `MEANS`, `MATCHES`
  - `ALIGNS`, `ALIGNS WITH`
  - `EXTRACTS`
  - `ASK`
  - `SOUNDS_LIKE`
  - `IMPLIES`
  - `CONTRADICTS`
  - `SIMILAR_TO`
  - Symbol ops: `~`, `!~` (as defined in YAML)

**Token-phase rewrite behavior:**

- Convert: `lhs <op> rhs` → `function(lhs, rhs)` (arg order from YAML `args`)
- Preserve surrounding parentheses and operator precedence by operating on token spans, not raw substrings.
- Apply `-- @` hint injection to the intended operand (usually the criterion/prompt).

Notes:

- `ABOUT` and `NOT ABOUT` can be treated as expression-level if rewritten to `semantic_score(lhs, rhs)` and the threshold comparison is explicit.
- If v0 requires “default threshold insertion” (`WHERE x ABOUT 'y'` meaning `> 0.5`), that becomes context-sensitive and is best handled in AST phase.

### B) AST-phase (Scope-sensitive / structural)

These modify query structure or require clause context; they must be applied per-`SELECT` scope to be correct under nesting.

**ORDER BY clause transforms**

- `ORDER BY col RELEVANCE TO 'x' [ASC|DESC]`
- `ORDER BY col NOT RELEVANCE TO 'x' [ASC|DESC]`

AST transform:

- Replace `ORDER BY <expr> RELEVANCE TO <literal>` with `ORDER BY semantic_score(<expr>, <literal>) DESC` (default direction preserved).

**Threshold/default semantics**

- `WHERE col ABOUT 'x'` (if v0 keeps default `> 0.5`)
- `WHERE col NOT ABOUT 'x'` (default `<= 0.5`)

AST transform:

- If an ABOUT expression appears as a boolean predicate without explicit comparison, wrap with the default comparator.

**Join/query-structure transforms**

- `SEMANTIC JOIN ... ON ...` (rewrites to CROSS JOIN + WHERE or other expansion)
- `SEMANTIC DISTINCT` (dedupe expansion; likely CTE-based)
- `GROUP BY MEANING(...)`, `GROUP BY TOPICS(...)` (CTE + aggregate expansions)

**Embedding/query-level transforms**

- `EMBED(...)` context injection (table + id column + metadata column tracking)
  - Should be AST-based to find the correct `FROM` source and avoid mis-detecting in nested scopes.
- `VECTOR_SEARCH(...)` wrapper
  - Today it injects a `WITH __vsr_0 AS (...)` CTE; must become per-scope and collision-free in nested subqueries.

**Parallelization transforms (optional in v0)**

- `-- @ parallel:` UNION ALL splitting is inherently structural.
- If kept, apply in AST phase and only when the scope has a safe partition key, otherwise skip with a warning.

---

## Subqueries: Correctness Model (“Inside-out Lisp style”)

After token-phase desugaring, the core semantic operators are ordinary function calls.
SQL engines (DuckDB) naturally evaluate nested expressions “inside-out”, so nesting is correct.

The “gotchas” only exist for structural rewrites; AST-phase per-scope transforms address them:

- Each nested `SELECT` scope gets its own injected CTEs, with unique names.
- No accidental hoisting of CTEs or WHERE fixes across scope boundaries.
- No rewrite inside string literals or comments.

---

## Rollout Plan (safe + honest for v0)

1) Implement v2 module + unit tests (tokenizer, annotation binding, infix desugaring).
2) Wire feature flag in `rvbbit/sql_rewriter.py`:
   - `RVBBIT_SEMANTIC_REWRITE_V2=1` uses v2, else legacy.
   - `RVBBIT_SEMANTIC_REWRITE_SHADOW=1` runs both and logs diffs (no behavior change).
3) Incrementally migrate structural rewrites:
   - Start with `RELEVANCE TO` + `ABOUT` defaults (clause-level).
   - Then `VECTOR_SEARCH` (scope-local CTE injection).
   - Then `EMBED` context injection (AST-derived FROM + id inference).
   - Then `SEMANTIC JOIN`, `SEMANTIC DISTINCT`, `GROUP BY MEANING/TOPICS`.
4) Keep fallback always available in v0.

---

## LOE (rough)

- Tokenizer + annotation binding + generic infix desugar + tests: **~2–5 days**
- AST phase for `RELEVANCE TO` + ABOUT defaults + VECTOR_SEARCH scoping: **~3–7 days**
- AST phase for EMBED context injection + join/distinct/group transforms + hardening: **~1–2 weeks**

---

## Acceptance Criteria (v0)

- `-- @ ...` hinting works as it does today (but is token-scoped, not line fragile).
- Queries using newer operators (e.g., `ALIGNS(text, '...')`) reliably enter SQL Trail logging and are fingerprinted consistently.
- No rewrites occur inside strings/comments.
- Nested subqueries/CTEs containing semantic operators behave correctly.
- Feature-flagged fallback remains available and tested.

