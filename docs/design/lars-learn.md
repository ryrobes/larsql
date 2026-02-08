# LARS Learn — Self-Optimizing SQL

> *"Use LARS normally. Flag what's right. Everything else is automatic."*

## The One-Sentence Pitch

Every 👍 or 👎 on a query result makes LARS cheaper, faster, and more accurate — automatically.

---

## Human Interface

The entire system is driven by **one interaction**:

```
Was this result correct?   [ 👍 Yes ]   [ 👎 No ]
```

That's it. Everything below happens automatically.

### Where the buttons appear

1. **Studio UI** — Inline on every operator result (MEANS, VALID, FILL, etc.)
2. **Hot or Not** — Rapid-fire card swiping for batch review (already built)
3. **pgwire clients** — Future: `COMMENT ON` or special SQL syntax for feedback
4. **API** — `POST /api/learn/feedback` for programmatic integration

### What the human sees

A single "Learn" dashboard in Studio showing:

```
┌─ LARS Learn ─────────────────────────────────────────┐
│                                                       │
│  📊 System Health                                     │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐        │
│  │  342   │ │  47%   │ │  97%   │ │ $44/mo │        │
│  │verified│ │cost ↓  │ │accuracy│ │est cost│        │
│  └────────┘ └────────┘ └────────┘ └────────┘        │
│                                                       │
│  🔄 Recent Activity                                   │
│  • Moved VALID operator to gemma3 (local) — $0/query │
│  • Updated MEANS prompt (mutation #12 won) — +3% acc │
│  • 14 new verified examples this week                │
│                                                       │
│  [ 🔥 Review Queue (23 unreviewed) ]                 │
│                                                       │
└───────────────────────────────────────────────────────┘
```

No configuration. No commands. Just a dashboard and a review queue.

---

## What Happens Behind the Scenes

A single piece of human feedback (👍/👎) triggers four optimization streams:

```
                     👍 or 👎
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │  REFINE  │  │CALIBRATE │  │  EVOLVE  │
    │          │  │          │  │          │
    │ Few-shot │  │ Test     │  │ Mutate   │
    │ examples │  │ models   │  │ prompts  │
    │ injected │  │ per op   │  │ via takes│
    │ into     │  │ pick     │  │ + reverse│
    │ prompts  │  │ cheapest │  │ prompting│
    └────┬─────┘  └────┬─────┘  └────┬─────┘
         │             │             │
         └─────────────┼─────────────┘
                       │
                       ▼
              ┌────────────────┐
              │   VALIDATE     │
              │                │
              │ Verified pairs │
              │ = regression   │
              │ tests. Nothing │
              │ ships without  │
              │ passing.       │
              └────────────────┘
```

### Stream 1: REFINE (Few-Shot Learning)

**Trigger:** 👍 on a result
**Action:** Verified input/output pair is stored and injected into future prompts for the same operator
**Mechanism:** Already built — `use_training: true` on cascade cells, `inject_training_examples_into_instructions()`

```yaml
# Example: matches.cascade.yaml
cells:
  - name: match
    use_training: true
    training_limit: 3
    training_strategy: semantic    # Find examples most similar to current input
    training_verified_only: true   # Only human-verified examples
    training_format: xml
```

What the model sees:
```xml
<examples>
  <example>
    <input>TEXT: bluetooth earbuds | CRITERION: wireless headphones</input>
    <output>true</output>
  </example>
  <example>
    <input>TEXT: wired mouse | CRITERION: wireless headphones</input>
    <output>false</output>
  </example>
</examples>

[original prompt instructions here]
```

**Impact:** Immediate accuracy improvement. Models perform dramatically better with relevant examples.

### Stream 2: CALIBRATE (Model Selection)

**Trigger:** Accumulated verified examples reach threshold (≥5 per operator)
**Action:** Run all configured models against verified examples, rank by accuracy × cost
**Mechanism:** Benchmark runner (just built) + routing table

```
Calibration runs automatically when:
  - 5+ new verified examples accumulate for an operator
  - A new model is added to the system
  - User triggers manual calibration via CLI or UI
  - Scheduled (e.g., weekly cron)
```

Routing table (auto-generated from calibration):
```sql
SELECT operator, model, accuracy, avg_cost, avg_latency
FROM model_routing
WHERE accuracy >= 0.90 AND sample_count >= 5
ORDER BY operator, avg_cost ASC;

-- Result:
-- valid    | gemma3 (local)      | 100% | $0.000  | 340ms
-- means    | gemini-2.5-flash    | 100% | $0.001  | 1.3s
-- fill     | gemma3 (local)      | 100% | $0.000  | 280ms
-- implies  | gemma3 (local)      | 100% | $0.000  | 310ms
```

When `models.yaml` uses `models.auto`:
```yaml
models:
  fast: models.auto       # LARS picks per-operator
  standard: models.auto
```

The cascade executor consults the routing table and picks the cheapest model that meets the accuracy threshold for that specific operator.

### Stream 3: EVOLVE (Prompt Optimization)

**Trigger:** Sufficient verified examples exist (≥10 per operator)
**Action:** Generate prompt variants, test against verified corpus, adopt winners
**Mechanism:** Takes system (built) + directed mutation (new)

Two mutation strategies:

**A. Random Mutation (existing takes system)**
```yaml
cells:
  - name: match
    takes: 3                    # Run 3 prompt variants in parallel
    evaluator: best_of_n       # Pick the best result
```

The takes system already runs N variants and picks winners. With verified examples as ground truth, we can measure which variant actually performs best over time, not just per-query.

**B. Directed Mutation (new — reverse prompting)**
```
Given:
  - Current prompt for MEANS operator
  - 50 verified input/output pairs

Ask a model:
  "Here is a prompt and the correct outputs for these inputs.
   Rewrite the prompt to more reliably produce these outputs,
   while being shorter and more efficient."
```

The mutated prompt is tested against the full verified corpus. If it scores ≥ current prompt's accuracy, it's adopted. If not, it's discarded. Every change is logged.

### Stream 4: VALIDATE (Regression Testing)

**Trigger:** Any change to prompts or model assignments
**Action:** Run the full verified corpus as regression tests
**Mechanism:** Benchmark runner using verified examples as test cases

```
Before applying any change:
  1. Snapshot current prompt + model assignment
  2. Run all verified examples against proposed change
  3. Compare accuracy vs current baseline
  4. Only apply if accuracy >= baseline
  5. Log the change with before/after metrics
```

This is the safety net. No prompt mutation or model swap goes live without passing regression.

---

## Data Model

### One Table to Rule Them All

Everything flows through the existing `training_annotations` table + `unified_logs`:

```sql
-- Already exists: training_annotations
CREATE TABLE training_annotations (
    trace_id        VARCHAR,    -- Links to unified_logs
    trainable       BOOLEAN,    -- 👍 = true, 👎 = false
    verified        BOOLEAN,    -- Human-reviewed = true
    confidence      FLOAT,      -- 0.0-1.0 (auto or human)
    notes           VARCHAR,    -- Optional human notes
    tags            VARCHAR[],  -- Categories
    annotated_at    TIMESTAMP,
    annotated_by    VARCHAR     -- 'human' or 'auto'
);

-- Already exists: training_examples_with_annotations (VIEW)
-- Joins unified_logs with annotations to get full input/output + metadata

-- Already exists: model_benchmarks (from benchmark runner)
CREATE TABLE model_benchmarks (
    benchmark_id    VARCHAR,
    operator        VARCHAR,
    model           VARCHAR,
    test_input      VARCHAR,
    expected        VARCHAR,
    actual          VARCHAR,
    passed          BOOLEAN,
    latency_ms      FLOAT,
    cost            FLOAT,
    timestamp       TIMESTAMP
);

-- NEW: model_routing (materialized view / auto-updated)
CREATE VIEW model_routing AS
SELECT
    operator,
    model,
    COUNT(*) as sample_count,
    AVG(CASE WHEN passed THEN 1.0 ELSE 0.0 END) as accuracy,
    AVG(cost) as avg_cost,
    AVG(latency_ms) as avg_latency,
    -- Pick cheapest model with ≥90% accuracy and ≥5 samples
    ROW_NUMBER() OVER (
        PARTITION BY operator
        ORDER BY avg_cost ASC
    ) as cost_rank
FROM model_benchmarks
WHERE accuracy >= 0.90 AND sample_count >= 5
GROUP BY operator, model;

-- NEW: learn_changelog (audit trail)
CREATE TABLE learn_changelog (
    id              VARCHAR,
    timestamp       TIMESTAMP,
    change_type     VARCHAR,    -- 'model_swap', 'prompt_mutation', 'calibration'
    operator        VARCHAR,
    description     VARCHAR,    -- Human-readable: "Moved VALID to gemma3 (local)"
    before_state    VARCHAR,    -- JSON snapshot
    after_state     VARCHAR,    -- JSON snapshot
    accuracy_before FLOAT,
    accuracy_after  FLOAT,
    cost_before     FLOAT,
    cost_after      FLOAT,
    reverted        BOOLEAN DEFAULT FALSE
);
```

### Verified Examples as Test Cases

The bridge between training and calibration is trivial:

```python
def get_verified_test_cases(operator: str) -> list:
    """
    Pull verified examples from training_annotations
    and format them as benchmark test cases.
    """
    db = get_db()
    results = db.query(f"""
        SELECT user_input, assistant_output
        FROM training_examples_with_annotations
        WHERE cascade_id = '{operator}'
          AND verified = true
          AND trainable = true
        ORDER BY annotated_at DESC
    """)

    return [
        {
            "input": row["user_input"],
            "expected": row["assistant_output"],
            "source": "verified"
        }
        for row in results
    ]
```

The benchmark runner already accepts test cases. We just add "verified examples" as another test case source alongside the YAML-defined `test_cases`.

---

## Implementation Plan

### Phase 1: Wire the Feedback Loop (1-2 days)

**Goal:** 👍/👎 → few-shot examples → better results. Immediate value.

1. **Enable `use_training: true` on semantic SQL cascades**
   - `matches.cascade.yaml` (MEANS operator)
   - `valid.cascade.yaml` (VALID operator)
   - `fill_single.cascade.yaml` (FILL operator)
   - `implies.cascade.yaml` (IMPLIES operator)
   - Settings: `training_verified_only: true`, `training_strategy: recent`, `training_limit: 3`

2. **Add inline 👍/👎 to Studio operator results**
   - Small thumbs up/down buttons on every operator result in the existing UI
   - Calls existing `POST /api/training/mark-trainable` with `verified: true`
   - No new API needed

3. **Fix ClickHouse artifacts in training code**
   - `OPTIMIZE TABLE ... FINAL` → remove (DuckDB doesn't need it)
   - `positionCaseInsensitiveUTF8` → `position` or `ILIKE`

4. **Implement semantic similarity strategy**
   - Currently a stub that falls back to recent
   - Use existing embedding infrastructure to find examples most similar to current input
   - Makes few-shot examples much more relevant

**Result:** Users start 👍/👎-ing results. Accuracy improves immediately via few-shot injection.

### Phase 2: Auto-Calibration (1-2 days)

**Goal:** Verified examples automatically become test cases. Models get ranked and routed.

1. **Bridge verified examples → benchmark test cases**
   - `get_verified_test_cases()` function (shown above)
   - Add as test case source in `benchmark.py`

2. **Auto-calibration trigger**
   - When verified count for an operator crosses threshold (5, 10, 25...):
     - Automatically run benchmark for that operator across all configured models
     - Update routing table
   - Background thread, non-blocking

3. **`models.auto` resolver**
   - When cascade execution sees `models.auto` as the model:
     - Look up operator in routing table
     - Return cheapest qualifying model
     - Fall back to configured tier default if no routing data

4. **Routing report in CLI + Studio**
   - `lars learn --status` shows current routing decisions
   - Studio Learn dashboard shows which model is assigned to which operator and why

**Result:** LARS automatically picks the cheapest working model per operator. Cost drops.

### Phase 3: Prompt Evolution (2-3 days)

**Goal:** Prompts get better over time without human intervention.

1. **Directed mutation via reverse prompting**
   - New function: `generate_prompt_mutation(cascade_id, current_prompt, verified_examples)`
   - Uses a strong model to suggest prompt improvements
   - Tests mutation against verified corpus before adopting

2. **Automatic prompt A/B testing**
   - When a mutation is generated:
     - Run current prompt vs mutated prompt against verified corpus
     - If mutation wins on accuracy (and doesn't regress on cost/latency): adopt
     - Log everything to `learn_changelog`

3. **Changelog + rollback UI**
   - Studio shows every automatic change with before/after metrics
   - One-click rollback to any previous state
   - "This change saved $X/month" or "This change improved accuracy by Y%"

**Result:** Prompts improve automatically. Full auditability.

### Phase 4: Unified Dashboard (1-2 days)

**Goal:** One screen that shows the full flywheel.

1. **Learn Dashboard in Studio**
   - Review queue (unreviewed operator results, prioritized by uncertainty)
   - System health KPIs (verified count, accuracy, cost trend, savings)
   - Recent changes (what LARS changed automatically + impact)
   - Operator breakdown (per-operator: model, accuracy, cost, example count)

2. **Savings calculator**
   - Track what model was used vs what model would have been used without routing
   - `savings = sum(default_model_cost - routed_model_cost)` per query
   - Display as running total: "LARS Learn has saved $142 this month"

3. **Proactive review suggestions**
   - Surface low-confidence results for human review
   - "We have 12 MEANS results with <70% confidence — review to improve accuracy"
   - Prioritize operators with few verified examples (highest marginal value per review)

---

## Observability

Every automatic action is logged and reversible:

```
learn_changelog entries:

[2026-02-08 14:30] MODEL_SWAP
  Operator: VALID
  Change: anthropic/claude-sonnet-4 → ollama/gemma3
  Reason: gemma3 scored 100% accuracy on 23 verified examples at $0/query
  Cost impact: -$0.04/query (~$28/mo savings at current volume)

[2026-02-08 14:32] PROMPT_MUTATION
  Operator: MEANS
  Change: Prompt variant #12 adopted (mutation via reverse-prompting)
  Accuracy: 94% → 97% (+3%)
  Cost impact: neutral (same model)
  Diff: [link to prompt diff]

[2026-02-08 15:00] CALIBRATION_RUN
  Triggered by: 5 new verified examples for FILL operator
  Models tested: gemma3, gemini-2.5-flash, claude-sonnet-4
  Result: gemma3 retained (100% accuracy, lowest cost)
  No changes applied.
```

### CLI Access

```bash
# See what LARS has learned
lars learn --status

# See recent automatic changes
lars learn --changelog

# See savings estimate
lars learn --savings

# Manually trigger calibration
lars learn --calibrate

# Rollback a change
lars learn --rollback <change_id>

# Export verified examples (for backup or sharing)
lars learn --export verified_examples.json
```

---

## Key Design Principles

1. **Minimum viable human input.** One button: 👍 or 👎. Everything else is automatic.

2. **Observable, not opaque.** Every automatic change is logged with reasoning, before/after metrics, and one-click rollback. Business users need to trust the system.

3. **Conservative by default.** No change is applied unless it passes regression against verified examples. Accuracy can only go up (or stay flat). Cost can only go down (or stay flat).

4. **Incremental value.** Each phase delivers standalone value:
   - Phase 1: Better accuracy via few-shot (no auto-routing needed)
   - Phase 2: Lower cost via model routing (no prompt evolution needed)
   - Phase 3: Better prompts automatically (compounds with 1 + 2)
   - Phase 4: Visibility into the whole flywheel

5. **SQL-native.** All data lives in DuckDB tables queryable via LARS itself. Users can write SQL against their own learning data. `SELECT * FROM model_routing WHERE operator = 'MEANS'` just works.

---

## What Already Exists vs What's New

| Component | Status | Work Needed |
|-----------|--------|-------------|
| Training annotations table | ✅ Built | Fix CH artifacts |
| Training API (CRUD) | ✅ Built | Add `/api/learn/feedback` shortcut |
| Hot or Not swipe UI | ✅ Built | Rename/reposition as "Review Queue" |
| Training grid + detail panel | ✅ Built | Add to Learn dashboard |
| KPI cards | ✅ Built | Add savings + cost trend |
| Few-shot injection (`use_training`) | ✅ Built | Enable on cascade YAMLs |
| Injection function | ✅ Built | No changes needed |
| Confidence worker | ✅ Built | Wire into review prioritization |
| Benchmark runner | ✅ Built | Add verified examples as test source |
| Takes system | ✅ Built | No changes needed |
| `model_benchmarks` table | ✅ Built | No changes needed |
| Semantic similarity strategy | 🔨 Stub | Implement with existing embeddings |
| `models.auto` resolver | 🆕 New | ~100 lines in executor |
| `model_routing` view | 🆕 New | ~20 lines SQL |
| `learn_changelog` table | 🆕 New | Schema + write path |
| Directed prompt mutation | 🆕 New | Reverse-prompting function |
| Auto-calibration trigger | 🆕 New | Background check on feedback count |
| Savings calculator | 🆕 New | Compare routed vs default model cost |
| Learn CLI commands | 🆕 New | Wire into `cli.py` |
| Learn dashboard (Studio) | 🆕 New | React view (reuses existing components) |
| Inline 👍/👎 on results | 🆕 New | Small UI addition to existing views |

**Estimated new code:** ~500-800 lines Python, ~300 lines React (mostly wiring existing components)
**Existing code leveraged:** ~2500+ lines (training system, benchmark runner, takes, cascades, Studio UI)

---

## The Flywheel in Practice

**Week 1:** User runs queries normally. Reviews 50 results in Hot or Not (5 minutes).
LARS now has few-shot examples. Accuracy improves ~5-10%.

**Week 2:** Verified examples hit threshold. Auto-calibration runs. Discovers that gemma3 handles VALID and FILL at 100% accuracy for $0. Swaps those operators to local. Cost drops 40%.

**Week 3:** Prompt mutation generates a tighter MEANS prompt. Tests against 30 verified examples. Wins by 3% accuracy. Adopted automatically. Changelog shows the diff.

**Month 2:** 200+ verified examples. LARS routes 70% of operator calls to local models. Prompts have been refined 4 times. Cost is 60% lower than month 1. Accuracy is 97%+.

**The human spent:** ~15 minutes total reviewing results. Everything else was automatic.

---

*"The best optimization is the one the user doesn't have to think about."*
