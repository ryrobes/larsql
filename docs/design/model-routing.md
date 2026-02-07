# LARS Model Auto-Routing: Design Sketch

> Cost-aware, data-driven model selection for semantic SQL operators.
> "Run the cheapest model that's good enough."

## Overview

LARS semantic operators (`valid()`, `MEANS`, `SUMMARIZE()`, etc.) currently use
a fixed model tier (`models.fast`, `models.standard`). But a 3B local model can
handle `valid('john@gmail.com', 'email')` just as well as Opus — at zero cost.

**Auto-routing** picks the cheapest model per-operator based on accumulated
benchmark data, with optional input complexity awareness.

---

## 1. Benchmark Table Schema

```sql
CREATE TABLE model_benchmarks (
    -- Identity
    benchmark_id    VARCHAR PRIMARY KEY,  -- UUID
    run_id          VARCHAR NOT NULL,     -- Groups a batch of benchmarks
    
    -- What was tested
    operator_id     VARCHAR NOT NULL,     -- cascade_id: "valid_single", "means", "summarize", etc.
    operator_name   VARCHAR NOT NULL,     -- SQL function name: "valid", "MEANS", "SUMMARIZE"
    model_id        VARCHAR NOT NULL,     -- "lmstudio/google/gemma-3-4b", "anthropic-direct/claude-sonnet-4.5"
    
    -- Input characteristics
    input_hash      VARCHAR,             -- Fingerprint of the input (for dedup)
    input_tokens    INTEGER,             -- Approximate input token count
    input_complexity FLOAT,              -- 0.0-1.0 difficulty score (see §3)
    input_sample    VARCHAR,             -- Truncated input for debugging
    
    -- Results
    passed          BOOLEAN NOT NULL,    -- Did it produce correct output?
    output_value    VARCHAR,             -- What the model returned
    expected_value  VARCHAR,             -- What was expected (if test case)
    
    -- Performance
    latency_ms      FLOAT,              -- Wall clock time
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost            FLOAT DEFAULT 0.0,   -- USD cost for this call
    
    -- Metadata
    created_at      TIMESTAMP DEFAULT now(),
    provider        VARCHAR,             -- "lmstudio", "ollama", "openrouter", etc.
    
    -- For aggregation
    INDEX idx_operator_model (operator_id, model_id),
    INDEX idx_routing (operator_id, input_complexity, passed)
);
```

## 2. Routing Table (Materialized View / Cached Query)

The routing table is the **decision surface** — derived from benchmarks:

```sql
CREATE TABLE model_routing AS
SELECT
    operator_id,
    operator_name,
    model_id,
    provider,
    
    -- Accuracy & reliability
    COUNT(*)                                    AS total_runs,
    SUM(CASE WHEN passed THEN 1 ELSE 0 END)    AS passed_count,
    ROUND(passed_count * 100.0 / total_runs, 1) AS accuracy_pct,
    
    -- Cost
    AVG(cost)           AS avg_cost,
    SUM(cost)           AS total_cost,
    
    -- Performance
    AVG(latency_ms)     AS avg_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms,
    
    -- Complexity buckets
    AVG(input_complexity) AS avg_complexity_tested,
    MIN(input_complexity) AS min_complexity_tested,
    MAX(input_complexity) AS max_complexity_tested,
    
    -- Freshness
    MAX(created_at)     AS last_tested,
    
FROM model_benchmarks
GROUP BY operator_id, operator_name, model_id, provider;
```

### Routing Query (at operator execution time)

```sql
-- "Give me the cheapest model for valid() with ≥90% accuracy"
SELECT model_id, accuracy_pct, avg_cost, avg_latency_ms
FROM model_routing
WHERE operator_id = 'valid_single'
  AND accuracy_pct >= :min_accuracy      -- default: 90
  AND total_runs >= :min_samples         -- default: 5 (statistical confidence)
ORDER BY avg_cost ASC, avg_latency_ms ASC
LIMIT 1;
```

## 3. Input Complexity Scoring

A fast, cheap heuristic computed **before** the LLM call:

```python
def compute_complexity(operator_id: str, inputs: dict) -> float:
    """
    Score 0.0 (trivial) to 1.0 (complex).
    Must be fast — no LLM calls, just string analysis.
    """
    scores = []
    
    for key, value in inputs.items():
        v = str(value)
        
        # Length factor (longer = harder)
        char_len = len(v)
        if char_len < 50:
            scores.append(0.1)
        elif char_len < 200:
            scores.append(0.3)
        elif char_len < 1000:
            scores.append(0.5)
        elif char_len < 5000:
            scores.append(0.7)
        else:
            scores.append(0.9)
        
        # Structural complexity
        if any(c in v for c in '{}[]<>'):  # JSON/HTML/structured
            scores.append(0.2)
        if v.count('\n') > 10:             # Multi-line
            scores.append(0.2)
        if len(v.split()) > 100:           # Many words
            scores.append(0.3)
    
    # Operator-specific adjustments
    OPERATOR_BASE_COMPLEXITY = {
        "valid_single":    0.0,   # Simple validation
        "fill_single":     0.1,   # Context-dependent fill
        "means":           0.2,   # Semantic comparison
        "implies":         0.3,   # Reasoning required
        "summarize":       0.5,   # Compression task
        "parse":           0.4,   # Structured extraction
        "ask_data":        0.6,   # SQL generation
        "research":        0.8,   # Multi-step research
    }
    base = OPERATOR_BASE_COMPLEXITY.get(operator_id, 0.3)
    scores.append(base)
    
    return min(1.0, sum(scores) / len(scores))
```

### Complexity-Aware Routing

With complexity scores, routing becomes tiered:

```python
def resolve_model(operator_id: str, complexity: float, min_accuracy: float = 0.90) -> str:
    """Pick cheapest model that meets accuracy threshold for this complexity."""
    
    # Bucket complexity into bands for lookup
    if complexity < 0.3:
        complexity_band = "simple"
    elif complexity < 0.6:
        complexity_band = "moderate"  
    else:
        complexity_band = "complex"
    
    # Query routing table for this operator + complexity band
    candidates = query_routing_table(
        operator_id=operator_id,
        complexity_range=(complexity - 0.15, complexity + 0.15),
        min_accuracy=min_accuracy,
        min_samples=5
    )
    
    if candidates:
        return candidates[0].model_id  # Cheapest passing model
    
    # Fallback: no benchmark data → use configured tier default
    return get_tier_default(operator_id)
```

## 4. Benchmark Runner

Extends the existing test system with multi-model sweeps:

```bash
# Run benchmarks for specific operators across model tiers
lars benchmark --operators valid,means,implies,fill \
               --models lmstudio/google/gemma-3-4b,ollama/llama3,anthropic-direct/claude-sonnet-4.5 \
               --samples 20

# Run benchmarks for ALL operators with all configured models
lars benchmark --all

# Run with custom test data (not just built-in test_cases)
lars benchmark --operators summarize \
               --input-sql "SELECT description FROM products LIMIT 50" \
               --models ollama/llama3:70b,openrouter/anthropic/claude-haiku

# Show current routing recommendations
lars benchmark --report
```

### Benchmark Flow

```
1. For each (operator, model, test_input):
   a. Compute input_complexity score
   b. Run the cascade cell with the specified model
   c. Check result against expected output (or judge model)
   d. Record: passed, latency, cost, tokens, complexity
   e. Write to model_benchmarks table

2. After all runs:
   a. Rebuild routing table (materialized view)
   b. Print summary report
   c. Optionally update cascade YAML defaults
```

### Report Output

```
╭──────────────────────────────────────────────────────────────────╮
│                    Model Routing Report                          │
├──────────────┬─────────────────────┬──────┬────────┬────────────┤
│ Operator     │ Recommended Model   │ Acc% │ Cost   │ Latency    │
├──────────────┼─────────────────────┼──────┼────────┼────────────┤
│ valid()      │ lmstudio/gemma-3-4b │  95% │ $0.000 │    180ms   │
│ fill()       │ ollama/llama3       │  90% │ $0.000 │    320ms   │
│ MEANS        │ ollama/llama3:70b   │  92% │ $0.000 │    890ms   │
│ implies()    │ claude-haiku        │  94% │ $0.001 │    650ms   │
│ SUMMARIZE()  │ claude-sonnet-4.5   │  98% │ $0.008 │   1200ms   │
│ ask_data()   │ claude-sonnet-4.5   │  96% │ $0.012 │   2100ms   │
├──────────────┼─────────────────────┼──────┼────────┼────────────┤
│ Total saved vs all-Sonnet:  ~$0.018/query avg → ~72% reduction  │
╰──────────────────────────────────────────────────────────────────╯
```

## 5. Cascade Integration

### New Model Resolution Mode

```yaml
# Current: fixed tier
cells:
  - name: validate
    model: "{{ models.fast }}"

# New: auto-route based on benchmarks
cells:
  - name: validate
    model: "{{ models.auto }}"              # cheapest with ≥90% accuracy
    
  - name: validate_strict
    model: "{{ models.auto(accuracy=0.98) }}" # cheapest with ≥98% accuracy

  - name: summarize
    model: "{{ models.auto(accuracy=0.95, max_cost=0.01) }}"  # with cost cap
```

### Resolution at Runtime

```python
# In runner.py, when resolving model for a cell:
if model_template == "{{ models.auto }}":
    complexity = compute_complexity(cell.cascade_id, cell_inputs)
    model = resolve_model(
        operator_id=cell.cascade_id,
        complexity=complexity,
        min_accuracy=0.90  # or from auto() params
    )
```

### Retry Escalation

When auto-routing picks a cheap model and it fails validation:

```python
# In runner.py retry logic:
if validation_failed and model_was_auto_routed:
    # Escalate to next tier instead of retrying same model
    next_model = resolve_model(
        operator_id=cell.cascade_id,
        complexity=complexity,
        min_accuracy=0.95,           # bump threshold
        exclude_models=[current_model]  # don't retry same
    )
```

This means cheap models get *tried first*, and failures auto-escalate —
no wasted money, no lost accuracy.

## 6. Data Flow

```
                    ┌──────────────┐
                    │  lars bench  │  ← runs operator × model × input sweeps
                    └──────┬───────┘
                           │ writes
                           ▼
                ┌─────────────────────┐
                │  model_benchmarks   │  ← raw results (DuckDB parquet)
                └──────────┬──────────┘
                           │ aggregates
                           ▼
                ┌─────────────────────┐
                │   model_routing     │  ← operator → cheapest model map
                └──────────┬──────────┘
                           │ reads at query time
                           ▼
    SELECT valid(email, 'email') FROM contacts
                           │
                    ┌──────┴───────┐
                    │ auto-router  │  → picks lmstudio/gemma-3-4b
                    └──────┬───────┘
                           │ on failure
                           ▼
                    ┌──────────────┐
                    │  escalation  │  → retries with claude-haiku
                    └──────────────┘
```

## 7. Future Extensions

- **Production feedback loop**: Track real query results (not just benchmarks)
  and continuously refine routing from live data
- **Per-column routing**: "For the `email` column, gemma works; for `legal_clause`,
  use sonnet" — driven by column-level benchmark data
- **Cost budgets**: `SET lars_query_budget = 0.05` → auto-router respects per-query
  cost caps and picks models accordingly
- **A/B testing mode**: Route X% of calls to a challenger model and compare
- **Cascade-level routing**: Different cells in the same cascade use different
  models based on their individual benchmark profiles

---

## Implementation Priority

1. **Benchmark table + runner** — Store results, run sweeps (`lars benchmark`)
2. **Routing table + report** — Aggregate, show recommendations
3. **`models.auto` resolver** — Wire into cascade execution
4. **Complexity scoring** — Input-aware routing
5. **Retry escalation** — Auto-tier-up on failure
6. **Production feedback loop** — Learn from real queries

Steps 1-3 are the MVP. Steps 4-6 make it smart.
