# Multi-Model Soundings: Implementation Guide

**Status:** Design Complete, Ready for Implementation
**Created:** 2025-12-07
**Estimated Effort:** 2-3 weeks full implementation

---

## Executive Summary

**The Vision:** Extend soundings to run across multiple models simultaneously, automatically discovering the Pareto frontier of cost vs quality.

**Why This Matters:**
- **Research tool**: Systematically discover which models work best for specific tasks
- **Cost optimization**: Find cheapest model that meets quality bar
- **Novel contribution**: Pareto frontier analysis for LLM outputs (potentially publishable)
- **Production ready**: Data-driven model selection, not guesswork

**The Insight:** Don't just "use cheap if it validates" - explore the entire cost/quality landscape and pick from the Pareto frontier.

---

## Three-Tier Design

### Tier 1: Simple Model Pool
**What:** Run soundings round-robin across multiple models.
**Complexity:** Low
**Use Case:** Discover which model is best for this task.

```json
{
  "soundings": {
    "factor": 6,
    "models": ["anthropic/claude-3-5-sonnet", "openai/gpt-4o", "google/gemini-2.0-flash"],
    "model_strategy": "round_robin"
  }
}
```

**Behavior:**
- 6 soundings total
- Models assigned: Claude, GPT-4, Gemini, Claude, GPT-4, Gemini
- Evaluator picks best (doesn't know which model produced what)
- All logged with model attribution

### Tier 2: Cost-Aware Evaluation
**What:** Evaluator considers both quality and cost when selecting winner.
**Complexity:** Medium
**Use Case:** Balance cost and quality explicitly.

```json
{
  "soundings": {
    "factor": 6,
    "models": ["expensive", "mid", "cheap"],
    "cost_aware_evaluation": {
      "enabled": true,
      "quality_weight": 0.7,
      "cost_weight": 0.3,
      "show_costs_to_evaluator": true
    }
  }
}
```

**Behavior:**
- Evaluator sees: output content, model name, actual cost
- Prompt: "Balance quality (70%) and cost (30%)"
- Composite scoring: `score = (quality * 0.7) - (normalized_cost * 0.3)`

### Tier 3: Pareto Frontier Analysis (Novel)
**What:** Plot cost vs quality, identify non-dominated solutions, pick from frontier.
**Complexity:** High
**Use Case:** Systematic exploration, research, production optimization.

```json
{
  "soundings": {
    "factor": 9,
    "models": ["expensive", "mid", "cheap"],
    "pareto_frontier": {
      "enabled": true,
      "policy": "balanced",
      "show_frontier": true,
      "quality_metric": "evaluator_score"
    }
  }
}
```

**Behavior:**
1. Run 9 soundings (3 per model)
2. Compute Pareto frontier (non-dominated solutions)
3. Apply policy to select from frontier:
   - `prefer_cheap`: Pick cheapest on frontier
   - `prefer_quality`: Pick highest quality on frontier
   - `balanced`: Maximize `quality/cost` ratio on frontier
   - `interactive`: Show frontier options, prompt user
4. Log all frontier members and dominated solutions

---

## Configuration Schema

### SoundingsConfig Extensions

```python
class ModelConfig(BaseModel):
    """Per-model configuration."""
    factor: int = 1  # How many soundings for this model
    temperature: Optional[float] = None  # Model-specific overrides
    max_tokens: Optional[int] = None

class CostAwareEvaluation(BaseModel):
    """Cost-aware evaluation settings."""
    enabled: bool = True
    quality_weight: float = 0.7  # 0-1, sum with cost_weight should be 1.0
    cost_weight: float = 0.3
    show_costs_to_evaluator: bool = True
    cost_normalization: str = "min_max"  # "min_max" | "z_score" | "log_scale"

class ParetoFrontier(BaseModel):
    """Pareto frontier analysis settings."""
    enabled: bool = False
    policy: str = "balanced"  # "prefer_cheap" | "prefer_quality" | "balanced" | "interactive"
    show_frontier: bool = True
    quality_metric: str = "evaluator_score"  # "evaluator_score" | "validator_name" | "custom"
    include_dominated: bool = True  # Log dominated solutions for analysis

class SoundingsConfig(BaseModel):
    """Extended soundings configuration."""
    # Existing fields
    factor: int
    evaluator_instructions: str
    mutate: bool = False
    mutation_mode: Optional[str] = None
    reforge: Optional[ReforgeConfig] = None

    # NEW: Multi-model fields
    models: Optional[Union[List[str], Dict[str, ModelConfig]]] = None
    model_strategy: str = "round_robin"  # "round_robin" | "random" | "weighted"
    cost_aware_evaluation: Optional[CostAwareEvaluation] = None
    pareto_frontier: Optional[ParetoFrontier] = None
```

### Dynamic Factor Calculation

When `models` is a dict with per-model factors:
```json
{
  "models": {
    "claude": {"factor": 2},
    "gpt-4": {"factor": 2},
    "gemini": {"factor": 3}
  }
}
```

**Effective `factor`:** 2 + 2 + 3 = 7 soundings total

The `factor` field in parent `SoundingsConfig` becomes optional when using per-model config.

---

## Implementation Plan

### Phase 1: Simple Model Pool (Week 1)

**Files to modify:**
- `windlass/cascade.py`: Add model fields to `SoundingsConfig`
- `windlass/runner.py`: Implement model assignment logic
- `windlass/unified_logs.py`: Add `model` field to schema

**Implementation:**

```python
# In runner.py
def _assign_models(self, soundings_config: SoundingsConfig) -> List[str]:
    """Assign models to sounding attempts."""
    if soundings_config.models is None:
        # No multi-model: use default for all
        return [self.default_model] * soundings_config.factor

    if isinstance(soundings_config.models, list):
        # Simple list: round-robin or random
        if soundings_config.model_strategy == "round_robin":
            return [soundings_config.models[i % len(soundings_config.models)]
                    for i in range(soundings_config.factor)]
        elif soundings_config.model_strategy == "random":
            return [random.choice(soundings_config.models)
                    for _ in range(soundings_config.factor)]

    elif isinstance(soundings_config.models, dict):
        # Per-model factors: expand
        models = []
        for model, config in soundings_config.models.items():
            models.extend([model] * config.factor)
        return models

def _run_soundings(self, phase_config, echo):
    """Run soundings with model assignment."""
    models = self._assign_models(phase_config.soundings)
    soundings = []

    # Run in parallel
    with ThreadPoolExecutor(max_workers=len(models)) as executor:
        futures = []
        for i, model in enumerate(models):
            future = executor.submit(
                self._execute_sounding,
                phase_config,
                echo.copy(),
                sounding_index=i,
                model=model  # NEW: pass model
            )
            futures.append(future)

        for future in as_completed(futures):
            soundings.append(future.result())

    # Evaluate (existing logic)
    winner = self._evaluate_soundings(soundings, phase_config.soundings)
    return winner
```

**Logging changes:**
```python
# In unified_logs.py
def log_unified(self, entry):
    """Log with model field."""
    entry["model"] = entry.get("model", self.default_model)  # NEW
    # ... existing logging
```

**Testing:**
- Create `examples/multi_model_simple.json`
- Run with 3 models, verify round-robin assignment
- Check logs have model attribution
- Verify evaluator picks best regardless of model

**Deliverable:** Basic multi-model soundings working, logged correctly.

---

### Phase 2: Cost-Aware Evaluation (Week 2)

**Files to modify:**
- `windlass/cascade.py`: Add `CostAwareEvaluation` model
- `windlass/runner.py`: Enhance evaluator prompt with cost data
- `windlass/unified_logs.py`: Add `quality_score`, `cost_aware_score` fields

**Implementation:**

```python
# In runner.py
def _evaluate_soundings_cost_aware(self, soundings, soundings_config):
    """Evaluator with cost awareness."""
    cost_config = soundings_config.cost_aware_evaluation

    # Wait for costs to be available (OpenRouter delay)
    self._wait_for_costs(soundings)

    # Normalize costs for comparison
    costs = [s.cost for s in soundings]
    normalized_costs = self._normalize_costs(costs, cost_config.cost_normalization)

    # Build evaluator prompt with cost context
    candidates = []
    for i, sounding in enumerate(soundings):
        cost_str = f", Cost: ${sounding.cost:.4f}" if cost_config.show_costs_to_evaluator else ""
        candidates.append(
            f"Candidate {i+1}:\n"
            f"Model: {sounding.model}{cost_str}\n"
            f"Output: {sounding.output}\n"
        )

    evaluator_prompt = f"""
{soundings_config.evaluator_instructions}

COST-QUALITY BALANCE:
Consider quality ({cost_config.quality_weight*100}%) and cost ({cost_config.cost_weight*100}%).
If two outputs have similar quality, prefer the cheaper one.
If one is significantly higher quality, it may justify higher cost.

{chr(10).join(candidates)}

Which candidate is best? Respond with the number only.
"""

    # Call evaluator LLM
    winner_index = self._call_evaluator(evaluator_prompt)

    # Compute quality scores for all (for Pareto analysis)
    for sounding in soundings:
        sounding.quality_score = self._assess_quality(sounding)
        sounding.cost_aware_score = (
            sounding.quality_score * cost_config.quality_weight -
            normalized_costs[sounding.index] * cost_config.cost_weight
        )

    return soundings[winner_index]

def _normalize_costs(self, costs, method):
    """Normalize costs for fair comparison."""
    if method == "min_max":
        min_c, max_c = min(costs), max(costs)
        if max_c == min_c:
            return [0.0] * len(costs)
        return [(c - min_c) / (max_c - min_c) for c in costs]
    elif method == "z_score":
        mean = sum(costs) / len(costs)
        std = (sum((c - mean)**2 for c in costs) / len(costs)) ** 0.5
        if std == 0:
            return [0.0] * len(costs)
        return [(c - mean) / std for c in costs]
    elif method == "log_scale":
        return [math.log(c + 1e-6) for c in costs]

def _wait_for_costs(self, soundings, timeout=10):
    """Wait for OpenRouter cost data to be available."""
    start = time.time()
    while time.time() - start < timeout:
        if all(s.cost is not None for s in soundings):
            return
        time.sleep(0.5)
    # Graceful degradation: use estimated costs
    for s in soundings:
        if s.cost is None:
            s.cost = self._estimate_cost(s.model, s.tokens)
```

**Testing:**
- Create `examples/multi_model_cost_aware.json`
- Run with expensive + cheap models
- Verify evaluator sees costs
- Check that cheap model wins when quality similar
- Verify expensive model wins when quality significantly better

**Deliverable:** Cost-aware evaluation working, balancing quality and cost.

---

### Phase 3: Pareto Frontier Analysis (Week 3-4)

**Files to modify:**
- `windlass/cascade.py`: Add `ParetoFrontier` model
- `windlass/runner.py`: Implement frontier computation
- `windlass/unified_logs.py`: Add `is_pareto_optimal`, `dominated_by`, `pareto_rank` fields
- `extras/debug_ui/backend/app.py`: Add Pareto endpoint
- `extras/debug_ui/frontend/`: Add Pareto visualization

**Implementation:**

```python
# In runner.py
def compute_pareto_frontier(self, soundings, quality_metric="evaluator_score"):
    """
    Compute Pareto frontier for cost vs quality.

    Returns:
        frontier: List of non-dominated soundings
        dominated_map: Dict mapping sounding_index -> dominating_sounding_index
    """
    # Extract quality scores
    qualities = []
    for s in soundings:
        if quality_metric == "evaluator_score":
            qualities.append(s.quality_score)
        elif quality_metric.startswith("validator:"):
            validator_name = quality_metric.split(":")[1]
            qualities.append(s.validator_scores.get(validator_name, 0))
        else:
            qualities.append(s.quality_score)

    # Compute dominated set
    frontier = []
    dominated_map = {}

    for i, si in enumerate(soundings):
        dominated = False
        dominator = None

        for j, sj in enumerate(soundings):
            if i == j:
                continue

            # Check if sj dominates si
            # Dominance: sj is better in all dimensions and strictly better in at least one
            quality_better = qualities[j] >= qualities[i]
            cost_better = sj.cost <= si.cost
            strictly_better = qualities[j] > qualities[i] or sj.cost < si.cost

            if quality_better and cost_better and strictly_better:
                dominated = True
                dominator = j
                break

        if not dominated:
            frontier.append(si)
        else:
            dominated_map[i] = dominator

    # Compute Pareto ranks (distance from frontier)
    pareto_ranks = {}
    for i, s in enumerate(soundings):
        if s in frontier:
            pareto_ranks[i] = 1
        else:
            # Rank 2 = dominated by frontier, 3 = dominated by rank 2, etc.
            rank = 2
            dominator = dominated_map.get(i)
            while dominator is not None and dominator not in [si.index for si in frontier]:
                rank += 1
                dominator = dominated_map.get(dominator)
            pareto_ranks[i] = rank

    return frontier, dominated_map, pareto_ranks

def select_from_frontier(self, frontier, policy):
    """Select winner from Pareto frontier based on policy."""
    if policy == "prefer_cheap":
        return min(frontier, key=lambda s: s.cost)

    elif policy == "prefer_quality":
        return max(frontier, key=lambda s: s.quality_score)

    elif policy == "balanced":
        # Maximize quality per dollar (on frontier only)
        max_quality = max(s.quality_score for s in frontier)
        max_cost = max(s.cost for s in frontier)

        # Normalize and compute score
        scores = []
        for s in frontier:
            norm_quality = s.quality_score / max_quality if max_quality > 0 else 0
            norm_cost = s.cost / max_cost if max_cost > 0 else 0
            score = norm_quality - norm_cost  # Higher is better
            scores.append(score)

        return frontier[scores.index(max(scores))]

    elif policy == "interactive":
        # Show options to user
        print("\nPareto Frontier (non-dominated solutions):")
        for i, s in enumerate(frontier):
            print(f"  [{i+1}] Model: {s.model}, Quality: {s.quality_score:.2f}, Cost: ${s.cost:.4f}")

        choice = int(input("Select winner (number): ")) - 1
        return frontier[choice]

def _run_soundings_with_pareto(self, phase_config, echo):
    """Run soundings with Pareto frontier analysis."""
    # Run soundings (Phase 1 logic)
    soundings = self._run_soundings_phase1(phase_config, echo)

    # Compute quality scores
    for s in soundings:
        s.quality_score = self._assess_quality(s)

    # Compute Pareto frontier
    pareto_config = phase_config.soundings.pareto_frontier
    frontier, dominated_map, pareto_ranks = self.compute_pareto_frontier(
        soundings,
        quality_metric=pareto_config.quality_metric
    )

    # Log frontier metadata
    for i, s in enumerate(soundings):
        s.is_pareto_optimal = (s in frontier)
        s.dominated_by = dominated_map.get(i)
        s.pareto_rank = pareto_ranks.get(i)

    # Select winner from frontier
    winner = self.select_from_frontier(frontier, pareto_config.policy)

    # Log frontier visualization data
    if pareto_config.show_frontier:
        self._log_pareto_frontier(frontier, dominated_map, winner)

    return winner

def _log_pareto_frontier(self, frontier, dominated_map, winner):
    """Log Pareto frontier for visualization."""
    log_data = {
        "frontier": [
            {
                "sounding_index": s.index,
                "model": s.model,
                "quality": s.quality_score,
                "cost": s.cost,
                "is_winner": (s == winner)
            }
            for s in frontier
        ],
        "dominated": [
            {
                "sounding_index": i,
                "dominated_by": j
            }
            for i, j in dominated_map.items()
        ]
    }

    # Write to special log file for visualization
    with open(f"{self.graph_dir}/pareto_{self.session_id}.json", "w") as f:
        json.dump(log_data, f, indent=2)
```

**Logging schema additions:**
```python
# In unified_logs.py
{
    # ... existing fields
    "model": "anthropic/claude-3-5-sonnet",
    "quality_score": 92.0,  # NEW: Numeric quality score
    "cost_aware_score": 85.5,  # NEW: Composite score (quality - cost)
    "is_pareto_optimal": true,  # NEW: Is on Pareto frontier
    "dominated_by": null,  # NEW: Index of dominating sounding (null if on frontier)
    "pareto_rank": 1,  # NEW: 1 = frontier, 2+ = dominated
}
```

**Testing:**
- Create `examples/multi_model_pareto.json`
- Run with 3 models, 3 attempts each (9 total)
- Verify frontier computation (plot manually)
- Check that winner is on frontier
- Verify dominated solutions marked correctly
- Test all policies (prefer_cheap, prefer_quality, balanced)

**Deliverable:** Full Pareto frontier analysis working, data logged for visualization.

---

### Phase 4: Visualization & UI (Week 4)

**Frontend component:**

```javascript
// In extras/debug_ui/frontend/src/components/ParetoFrontierChart.js

import React from 'react';
import { ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const ParetoFrontierChart = ({ paretoData }) => {
  const { frontier, dominated, all_soundings } = paretoData;

  // Prepare data for chart
  const frontierPoints = frontier.map(s => ({
    cost: s.cost,
    quality: s.quality,
    model: s.model,
    index: s.sounding_index,
    is_winner: s.is_winner,
    type: 'frontier'
  }));

  const dominatedPoints = all_soundings
    .filter(s => !frontier.find(f => f.sounding_index === s.index))
    .map(s => ({
      cost: s.cost,
      quality: s.quality,
      model: s.model,
      index: s.index,
      type: 'dominated'
    }));

  return (
    <ResponsiveContainer width="100%" height={400}>
      <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
        <XAxis dataKey="cost" name="Cost" unit="$" />
        <YAxis dataKey="quality" name="Quality" unit="%" />
        <ZAxis range={[60, 400]} />
        <Tooltip cursor={{ strokeDasharray: '3 3' }} />
        <Legend />

        {/* Dominated points (gray) */}
        <Scatter
          name="Dominated"
          data={dominatedPoints}
          fill="#cccccc"
          opacity={0.4}
        />

        {/* Frontier points (green) */}
        <Scatter
          name="Pareto Frontier"
          data={frontierPoints}
          fill="#00ff00"
          opacity={0.8}
        />

        {/* Winner (star) */}
        <Scatter
          name="Winner"
          data={frontierPoints.filter(p => p.is_winner)}
          fill="#ff0000"
          shape="star"
          size={200}
        />
      </ScatterChart>
    </ResponsiveContainer>
  );
};

export default ParetoFrontierChart;
```

**Backend API endpoint:**

```python
# In extras/debug_ui/backend/app.py

@app.route('/api/pareto/<session_id>')
def get_pareto_frontier(session_id):
    """Get Pareto frontier data for visualization."""
    pareto_file = f"{GRAPH_DIR}/pareto_{session_id}.json"

    if not os.path.exists(pareto_file):
        return jsonify({"error": "No Pareto data for this session"}), 404

    with open(pareto_file) as f:
        data = json.load(f)

    return jsonify(data)
```

**Deliverable:** Interactive Pareto frontier visualization in debug UI.

---

## Advanced Configurations

### Configuration 1: Research Mode
**Goal:** Explore model landscape systematically.

```json
{
  "soundings": {
    "factor": 12,
    "models": [
      "anthropic/claude-3-5-sonnet",
      "anthropic/claude-3-opus",
      "openai/gpt-4o",
      "openai/gpt-4o-mini",
      "google/gemini-2.0-flash",
      "meta/llama-3.3-70b"
    ],
    "model_strategy": "round_robin",
    "pareto_frontier": {
      "enabled": true,
      "policy": "balanced",
      "show_frontier": true
    }
  }
}
```

**Use case:** Run this 20 times on representative tasks, analyze which models consistently appear on frontier.

### Configuration 2: Production Cost Optimization
**Goal:** Minimize cost while maintaining quality floor.

```json
{
  "soundings": {
    "models": {
      "anthropic/claude-3-5-sonnet": {"factor": 1},
      "google/gemini-2.0-flash": {"factor": 4}
    },
    "cost_aware_evaluation": {
      "enabled": true,
      "quality_weight": 0.6,
      "cost_weight": 0.4
    }
  },
  "wards": {
    "post": [
      {"validator": "minimum_quality_check", "mode": "blocking"}
    ]
  }
}
```

**Use case:** Always prefer cheap model, but hard floor on quality via wards.

### Configuration 3: Multi-Model + Mutations
**Goal:** Explore model × prompt variation space.

```json
{
  "soundings": {
    "factor": 9,
    "models": ["claude", "gpt-4", "gemini"],
    "mutate": true,
    "mutation_mode": "rewrite",
    "pareto_frontier": {
      "enabled": true,
      "policy": "balanced"
    }
  }
}
```

**What happens:**
- 9 soundings: 3 models × 3 mutation variations
- Each model gets: baseline, mutation_1, mutation_2
- Frontier analysis reveals which model+mutation combos are optimal
- Passive optimization learns from both model and prompt patterns

**This is the ultimate exploration mode.**

---

## Potential Issues & Solutions

### Issue 1: OpenRouter Cost Delay
**Problem:** Costs available ~3 seconds after request.
**Solution:**
- Wait with timeout (10s max)
- Graceful degradation: estimate costs if not available
- Cache cost data for known request IDs

**Code:**
```python
def _wait_for_costs(self, soundings, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        if all(s.cost is not None for s in soundings):
            return
        time.sleep(0.5)

    # Estimate missing costs
    for s in soundings:
        if s.cost is None:
            s.cost = self._estimate_cost(s.model, s.tokens_in, s.tokens_out)
```

### Issue 2: Quality Metric Definition
**Problem:** What is "quality" for Pareto frontier?
**Options:**
1. **Evaluator score** (default): LLM judges quality 0-100
2. **Validator results**: Binary pass/fail or numeric score
3. **Custom metric**: User-defined function
4. **Composite**: Weighted combination

**Solution:** Make it configurable:
```json
{
  "pareto_frontier": {
    "quality_metric": "evaluator_score"  // or "validator:name" or "custom:func"
  }
}
```

### Issue 3: Free Models (Cost = 0)
**Problem:** Pareto frontier undefined if all costs equal.
**Solution:**
- Detect all-zero costs
- Fall back to quality-only evaluation
- Log warning

**Code:**
```python
if all(s.cost == 0 for s in soundings):
    logger.warning("All costs are zero, falling back to quality-only evaluation")
    return self._evaluate_by_quality_only(soundings)
```

### Issue 4: Evaluator Prompt Complexity
**Problem:** Cost-aware evaluation makes prompt long/complex.
**Solution:**
- Use structured format (JSON or markdown table)
- Separate quality assessment from cost consideration
- Provide clear scoring rubric

**Example prompt:**
```
Evaluate these candidates:

| # | Model | Quality (your assessment 0-100) | Cost |
|---|-------|--------------------------------|------|
| 1 | claude-3-5-sonnet | ? | $0.12 |
| 2 | gpt-4o | ? | $0.10 |
| 3 | gemini-flash | ? | $0.02 |

Step 1: Assess quality of each (ignore cost for now)
Step 2: Consider cost trade-offs (70% quality, 30% cost)
Step 3: Select winner

Respond: Winner is #[number]
```

### Issue 5: Mutation Distribution with Multi-Model
**Problem:** How to distribute mutations across models?
**Options:**
1. **Each model gets all mutations** (Cartesian product)
2. **Mutations distributed evenly** (baseline + mutations split across models)
3. **Model-specific mutations** (advanced)

**Recommendation:** Option 1 for exploration, Option 2 for production.

**Code:**
```python
def _assign_models_with_mutations(self, soundings_config):
    models = soundings_config.models
    mutations = self._generate_mutations(soundings_config)

    if soundings_config.mutation_strategy == "cartesian":
        # Each model × each mutation
        assignments = []
        for model in models:
            for mutation in mutations:
                assignments.append((model, mutation))
        return assignments

    elif soundings_config.mutation_strategy == "distributed":
        # Round-robin assign mutations to models
        assignments = []
        for i, mutation in enumerate(mutations):
            model = models[i % len(models)]
            assignments.append((model, mutation))
        return assignments
```

### Issue 6: Parallel Execution Fairness
**Problem:** Some models slower than others, affects parallel timing.
**Solution:**
- Use `ThreadPoolExecutor` or `asyncio` (already done)
- Track individual timing
- Don't penalize models for being slow (only cost/quality matter)

**Not an issue:** Parallel execution handles this naturally.

### Issue 7: Interactive Mode UX
**Problem:** Pausing execution for user input breaks automation.
**Solution:**
- Use `ask_human` tool (already exists)
- Only enable in debug/development mode
- Provide CLI flag: `--interactive-pareto`
- Alternative: Save frontier to file, let user choose later

**Recommendation:** Interactive mode only for research/development.

### Issue 8: Schema Evolution
**Problem:** Adding new fields to logs.
**Solution:**
- DuckDB's union by name handles schema evolution
- All new fields nullable
- Backward compatible: old logs work without new fields

**No issue:** Already handled by existing infrastructure.

---

## Testing Strategy

### Unit Tests
```bash
# Test model assignment
pytest tests/test_multi_model.py::test_round_robin_assignment
pytest tests/test_multi_model.py::test_per_model_factors
pytest tests/test_multi_model.py::test_random_assignment

# Test cost normalization
pytest tests/test_multi_model.py::test_min_max_normalization
pytest tests/test_multi_model.py::test_z_score_normalization

# Test Pareto computation
pytest tests/test_pareto.py::test_frontier_identification
pytest tests/test_pareto.py::test_dominated_detection
pytest tests/test_pareto.py::test_pareto_ranks
pytest tests/test_pareto.py::test_degenerate_cases
```

### Integration Tests
```bash
# Test full multi-model soundings
windlass examples/multi_model_simple.json --input '{"task": "test"}'

# Test cost-aware evaluation
windlass examples/multi_model_cost_aware.json --input '{"task": "test"}'

# Test Pareto frontier
windlass examples/multi_model_pareto.json --input '{"task": "test"}'

# Verify logs
windlass sql "SELECT model, is_pareto_optimal, cost, quality_score FROM all_data WHERE session_id = 'test_session'"
```

### Manual Testing Checklist
- [ ] Round-robin assignment works correctly
- [ ] Per-model factors calculate total correctly
- [ ] Costs logged accurately
- [ ] Evaluator prompt formatted correctly
- [ ] Cost normalization prevents extreme values
- [ ] Pareto frontier computed correctly (plot manually)
- [ ] All policies (prefer_cheap, prefer_quality, balanced) work
- [ ] Dominated solutions marked correctly
- [ ] Visualization renders correctly
- [ ] Backward compatibility (old cascades still work)

---

## SQL Queries for Analysis

### Query 1: Model Win Rates
```sql
SELECT
    model,
    COUNT(*) as wins,
    AVG(cost) as avg_cost,
    AVG(quality_score) as avg_quality
FROM all_data
WHERE is_winner = true
  AND sounding_index IS NOT NULL
GROUP BY model
ORDER BY wins DESC;
```

### Query 2: Pareto Frontier Frequency
```sql
SELECT
    model,
    COUNT(*) as frontier_appearances,
    AVG(quality_score) as avg_quality,
    AVG(cost) as avg_cost,
    AVG(quality_score / NULLIF(cost, 0)) as quality_per_dollar
FROM all_data
WHERE is_pareto_optimal = true
GROUP BY model
ORDER BY frontier_appearances DESC;
```

### Query 3: Cost vs Quality Correlation
```sql
SELECT
    model,
    CORR(cost, quality_score) as cost_quality_correlation,
    AVG(cost) as avg_cost,
    STDDEV(quality_score) as quality_variance
FROM all_data
WHERE sounding_index IS NOT NULL
GROUP BY model;
```

### Query 4: Dominated Analysis
```sql
SELECT
    d.model as dominated_model,
    f.model as dominator_model,
    AVG(f.quality_score - d.quality_score) as quality_gap,
    AVG(d.cost - f.cost) as cost_penalty
FROM all_data d
JOIN all_data f ON d.dominated_by = f.sounding_index
WHERE d.dominated_by IS NOT NULL
GROUP BY d.model, f.model;
```

### Query 5: Multi-Model + Mutation Analysis
```sql
SELECT
    model,
    mutation_type,
    COUNT(*) as appearances,
    SUM(is_winner::int) as wins,
    AVG(quality_score) as avg_quality
FROM all_data
WHERE sounding_index IS NOT NULL
  AND mutation_type IS NOT NULL
GROUP BY model, mutation_type
ORDER BY wins DESC;
```

---

## Migration Path

### For Existing Users
All changes are **backward compatible**:

1. **No `models` field?** → Use default model (existing behavior)
2. **No `cost_aware_evaluation`?** → Use standard evaluation (existing behavior)
3. **No `pareto_frontier`?** → No frontier analysis (existing behavior)

**Old cascade still works:**
```json
{
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the best"
  }
}
```

**New features are opt-in.**

### Gradual Adoption Path
1. **Week 1**: Add `models` field to explore different models
2. **Week 2**: Enable `cost_aware_evaluation` once comfortable
3. **Week 3**: Enable `pareto_frontier` for research/optimization

---

## Documentation Requirements

### User-Facing Docs
- [ ] Add multi-model soundings section to README.md
- [ ] Create example cascade files for each tier
- [ ] Add SQL query cookbook for analysis
- [ ] Document configuration options in CLAUDE.md
- [ ] Add troubleshooting guide

### Developer Docs
- [ ] Update API documentation with new fields
- [ ] Add architecture diagrams for Pareto computation
- [ ] Document testing procedures
- [ ] Add code comments for complex algorithms

---

## Success Metrics

### Technical Metrics
- **Correctness:** Pareto frontier computation verified manually on test cases
- **Performance:** Multi-model soundings no slower than sequential (parallel execution)
- **Reliability:** No crashes with missing cost data or edge cases
- **Backward compat:** All existing cascades still work

### User Metrics
- **Adoption:** 20% of soundings use multi-model within 3 months
- **Cost savings:** Users report 30-50% cost reduction when using Pareto mode
- **Research value:** 5+ case studies showing model discovery via frontier analysis

### Novel Contribution
- **Paper potential:** "Pareto Frontier Analysis for Multi-Model LLM Selection"
- **Citations:** Could cite game theory, multi-objective optimization literature
- **Differentiation:** No other framework does this (unique to Windlass)

---

## Timeline

### Week 1: Phase 1 (Simple Model Pool)
- Day 1-2: Schema changes, model assignment logic
- Day 3-4: Testing and example cascades
- Day 5: Documentation

### Week 2: Phase 2 (Cost-Aware Evaluation)
- Day 1-2: Evaluator prompt engineering
- Day 3-4: Cost normalization and scoring
- Day 5: Testing and documentation

### Week 3: Phase 3 (Pareto Frontier Core)
- Day 1-3: Frontier computation algorithm
- Day 4-5: Policy selection and logging

### Week 4: Phase 4 (Visualization & Polish)
- Day 1-2: Backend API
- Day 3-4: Frontend visualization
- Day 5: Integration testing and documentation

**Total:** 4 weeks to full implementation.

---

## Execution Time as a Pareto Dimension: Decision & Rationale

### Decision for V1: **EXCLUDE time from Pareto frontier**

**Why:**
1. ✅ **Simplicity**: 2D Pareto (cost vs quality) is easier to understand and visualize than 3D
2. ✅ **Parallel execution**: Soundings run simultaneously, so slow models don't penalize wall clock time
3. ✅ **Noise**: Time variance is high (network, queues, routing) making it less reliable than cost/quality
4. ✅ **Correlation**: Execution time typically correlates with model tier (expensive = fast, cheap = variable)
5. ✅ **Ship faster**: Reduced complexity allows faster initial implementation

**But:**
- ✅ **Always log `duration_ms`**: Capture execution time in all logs for analysis
- ✅ **Show as metadata**: Display time in UI tooltips/details (visible but not used in frontier computation)
- ✅ **Future enhancement**: Architecture flexible for adding 3D Pareto in V2 if users request it

### The Case FOR Including Time (Considered but Deferred)

**Scenarios where time matters:**
- **Interactive UX**: User waiting for chatbot response (latency-sensitive)
- **Real-time systems**: Trading, monitoring, alerts requiring fast decisions
- **Development iteration**: Faster feedback during testing/debugging
- **Cost per request**: In some cases, faster = higher throughput = lower amortized cost

**Three-dimensional Pareto would look like:**
```
Quality ↑
   │     ● High-quality, expensive, slow
   │   ● Medium-quality, mid-price, fast ← Might win if time critical
   │ ● Low-quality, cheap, very fast
   └────────────────────────────────────→ Cost
                 ↓ Time (minimize)
```

### The Case AGAINST Including Time (Why We Defer)

**Problem 1: Parallel Execution Makes Time Irrelevant**
```python
# Soundings run in parallel
with ThreadPoolExecutor() as executor:
    futures = [executor.submit(run_sounding, model) for model in models]
    # Wall clock = max(all_times), not sum(all_times)
```

**Result:** Slow model (12s) + Fast model (3s) = 12s total (not 15s)

The slow model doesn't penalize you because everything runs at once. Time only matters for the winner you select (affects subsequent phases), not for the soundings phase itself.

**Problem 2: Time is Highly Variable (Non-Deterministic)**
```
Same model, 5 consecutive runs:
Run 1: 3.2s
Run 2: 8.7s (routing delay)
Run 3: 2.1s
Run 4: 15.3s (rate limit queue)
Run 5: 3.5s

Variance >> Mean
```

Cost and quality are deterministic (same input → same result), but time depends on:
- Network conditions
- Provider load balancing
- Queue depth at provider
- Time of day
- Geographic routing

Including a noisy signal in Pareto frontier degrades quality of selection.

**Problem 3: Time Correlates with Model Choice (Redundant)**
```
Expensive models → Usually faster (priority infrastructure)
Mid-tier models → Medium speed
Cheap models → Variable (shared infrastructure, lower priority)

Correlation ≈ 0.6-0.8 (strong positive)
```

Time doesn't add independent information—it reinforces the existing cost dimension.

**Problem 4: Three-Dimensional Pareto is Cognitively Complex**

Users already need to balance cost vs quality (one trade-off). Adding time creates:
- Exponentially more trade-offs
- Harder to visualize (3D scatter plots are confusing)
- Unclear decision criteria ("Is 2x faster worth 1.5x cost for 5% less quality?")

### How Time is Still Captured (Even Though Not in Pareto)

**Logging:**
```python
{
    "duration_ms": 3247,  # Always logged
    "model": "gpt-4o",
    "quality_score": 90,
    "cost": 0.10,
    "is_pareto_optimal": true
}
```

**UI Display (Metadata):**
```
Pareto Frontier Options:
[1] Claude Opus: 95 quality, $0.15, 12s  ⭐ Winner (balanced policy)
[2] GPT-4o: 90 quality, $0.10, 3s       ← 4x faster if time matters!
[3] Gemini: 70 quality, $0.02, 1s       ← Cheapest + fastest
```

User can **manually override** based on time if needed (shown but not enforced).

**Analysis Queries:**
```sql
-- Time vs cost correlation
SELECT
    model,
    AVG(duration_ms) as avg_time,
    AVG(cost) as avg_cost,
    CORR(duration_ms, cost) as correlation
FROM all_data
WHERE sounding_index IS NOT NULL
GROUP BY model;

-- Find fast+cheap combinations
SELECT model, AVG(duration_ms), AVG(cost), AVG(quality_score)
FROM all_data
WHERE sounding_index IS NOT NULL
GROUP BY model
ORDER BY AVG(duration_ms) ASC, AVG(cost) ASC;
```

### Future Enhancement: V2 Could Add Time (If Users Request)

**When to add:**
- Multiple users request latency optimization
- Interactive use cases prove critical
- 3D visualization becomes standard

**Opt-in configuration:**
```json
{
  "pareto_frontier": {
    "enabled": true,
    "dimensions": ["quality", "cost", "time"],  // EXPLICIT OPT-IN
    "weights": {
      "quality": 0.5,
      "cost": 0.2,
      "time": 0.3
    }
  }
}
```

**Implementation for 3D Pareto:**
```python
def compute_pareto_frontier_3d(self, soundings):
    """Compute 3D Pareto frontier (quality, cost, time)."""
    for si in soundings:
        dominated = False
        for sj in soundings:
            # sj dominates si if better in all dimensions
            quality_better = sj.quality >= si.quality
            cost_better = sj.cost <= si.cost
            time_better = sj.duration <= si.duration

            # And strictly better in at least one
            strictly_better = (
                sj.quality > si.quality or
                sj.cost < si.cost or
                sj.duration < si.duration
            )

            if quality_better and cost_better and time_better and strictly_better:
                dominated = True
                break

        if not dominated:
            frontier.append(si)

    return frontier
```

### Context-Specific Time Policies (Future)

**Policy 1: Interactive (time critical)**
```json
{
  "dimensions": ["quality", "cost", "time"],
  "weights": {"quality": 0.4, "cost": 0.1, "time": 0.5}  // Time dominates
}
```

**Policy 2: Batch (time irrelevant)**
```json
{
  "dimensions": ["quality", "cost"],  // Time excluded entirely
  "weights": {"quality": 0.6, "cost": 0.4}
}
```

**Policy 3: Development (time + cost matter, quality flexible)**
```json
{
  "dimensions": ["quality", "cost", "time"],
  "weights": {"quality": 0.2, "cost": 0.4, "time": 0.4}  // Optimize for fast iteration
}
```

### Summary: Time Decision Matrix

| Factor | V1 Decision | V2 Possibility |
|--------|-------------|----------------|
| **Include in Pareto?** | ❌ No | 🟡 Optional (opt-in) |
| **Log duration?** | ✅ Yes (always) | ✅ Yes (always) |
| **Show in UI?** | ✅ Yes (metadata) | ✅ Yes (metadata or dimension) |
| **Used for selection?** | ❌ No | 🟡 Optional (if user enables) |
| **Complexity** | Low (2D) | High (3D) |
| **Value** | Unclear (most cases parallel) | Context-dependent |

**V1 Approach:** Log time, show time, but don't optimize for time (2D Pareto only).

**V2 Approach:** Add `dimensions` config option, support 3D Pareto when explicitly requested.

---

## Open Questions

1. **Evaluator model:** Use same model for evaluation, or always use high-quality model?
   - **Recommendation:** Always use high-quality model (claude-3-5-sonnet) for evaluation

2. **Mutation + Multi-model strategy:** Cartesian product or distributed?
   - **Recommendation:** Start with distributed (simpler), add Cartesian as advanced option

3. **Interactive mode UX:** CLI only or integrate with debug UI?
   - **Recommendation:** Both - CLI for headless, UI for visual mode

4. **Cost estimation:** What to do when OpenRouter doesn't return costs?
   - **Recommendation:** Token-based estimation with per-model pricing table

5. **Pareto rank computation:** Include in default logs or only when frontier enabled?
   - **Recommendation:** Only when frontier enabled (avoid schema bloat)

---

## Conclusion

**This is genuinely novel.** Pareto frontier analysis for multi-model LLM selection doesn't exist in any other framework.

**Implementation is feasible.** No fundamental blockers, all pieces build on existing infrastructure.

**Value is clear:**
- Research: Systematic model discovery
- Production: Cost optimization with quality guarantees
- Novel: Potential publication

**Complexity is justified.** The configuration surface grows, but the power justifies it.

**Ready to implement.** This design is complete and actionable.

---

## Next Steps

1. Review this design document
2. Approve/modify configuration schema
3. Start Phase 1 implementation
4. Create example cascade files
5. Ship incrementally (Phase 1 → 2 → 3 → 4)

**Let's build this.** 🚀
