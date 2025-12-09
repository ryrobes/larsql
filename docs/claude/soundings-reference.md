# Soundings Reference

This document covers Windlass's Tree of Thought implementation: Soundings, Reforge, Mutations, and Multi-Model support.

## Soundings Overview

Soundings run multiple parallel attempts at a phase or cascade level, then use an evaluator to select the best result.

**Two Levels:**
- **Phase-level**: Run a single phase N times, evaluator picks best
- **Cascade-level**: Run entire multi-phase workflow N times, evaluator picks best complete execution

All attempts are fully logged with `sounding_index` and `is_winner` metadata.

## Basic Configuration

### Phase-Level Soundings

```json
{
  "name": "generate_content",
  "instructions": "Write a blog post about {{ input.topic }}",
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the most engaging and well-structured post"
  }
}
```

### Cascade-Level Soundings

```json
{
  "cascade_id": "research_workflow",
  "soundings": {
    "factor": 3,
    "max_parallel": 3,
    "evaluator_instructions": "Pick the execution with best overall results"
  },
  "phases": [...]
}
```

## Soundings Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `factor` | int | 1 | Number of parallel attempts |
| `max_parallel` | int | 3 | Maximum concurrent executions |
| `evaluator_instructions` | str | required | Instructions for evaluator LLM |
| `mutate` | bool | false | Apply built-in mutation strategies |
| `mutation_mode` | str | "rewrite" | How to mutate: "rewrite", "augment", "approach" |
| `mutations` | list | null | Custom mutation templates |
| `models` | list/dict | null | Multi-model configuration |
| `validator` | str | null | Pre-evaluation validator name |
| `reforge` | object | null | Iterative refinement configuration |

## Execution Flow

```
Phase/Cascade Start
    ↓
🔱 Soundings (Breadth) - runs in parallel
  ├─ Attempt 0 ─┐
  ├─ Attempt 1 ─┼─ concurrent (up to max_parallel)
  └─ Attempt 2 ─┘
     ↓
  ⚖️  Evaluate → Winner selected
     ↓
✅ Winner continues (others logged but discarded)
```

---

## Reforge - Iterative Refinement

Reforge extends Soundings with iterative refinement: after soundings complete, the winner is refined through additional loops with honing prompts.

**Combines Two Search Strategies:**
- **Breadth-first** (soundings): Initial exploration with N parallel attempts
- **Depth-first** (reforge): Progressive refinement of the winner

### Configuration

```json
{
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the best initial approach",
    "reforge": {
      "steps": 2,
      "honing_prompt": "Refine and improve: focus on clarity and conciseness",
      "factor_per_step": 2,
      "mutate": true,
      "evaluator_override": "Pick the most polished version",
      "threshold": {"validator": "quality_check", "mode": "advisory"}
    }
  }
}
```

### Reforge Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `steps` | int | required | Number of refinement iterations |
| `honing_prompt` | str | required | Refinement instructions |
| `factor_per_step` | int | 2 | Refinement attempts per step |
| `mutate` | bool | false | Apply mutations to refinement |
| `evaluator_override` | str | null | Custom evaluator for refinement |
| `threshold` | object | null | Early stopping when quality target met |

### Execution Flow with Reforge

```
🔱 Soundings (Breadth)
  ├─ Attempt 0 ─┐
  ├─ Attempt 1 ─┼─ concurrent
  └─ Attempt 2 ─┘
     ↓
  ⚖️  Evaluate → Winner
     ↓
🔨 Reforge Step 1 (Depth)
  ├─ Refine 0 (winner + honing) ─┐
  └─ Refine 1 (winner + honing) ─┘ concurrent
     ↓
  ⚖️  Evaluate → New Winner
     ↓
🔨 Reforge Step 2
  ├─ Refine 0 ─┐
  └─ Refine 1 ─┘
     ↓
  ⚖️  Evaluate → Final Winner
     ↓
✅ Polished output
```

### Session ID Namespacing

Each iteration gets unique session ID for isolation:
- Main: `session_123`
- Reforge step 1, attempt 0: `session_123_reforge1_0`
- Reforge step 2, attempt 1: `session_123_reforge2_1`

### Use Cases

- **Code generation**: Broad algorithm exploration → polished implementation
- **Content creation**: Creative brainstorming → refined copy
- **Strategy development**: Multiple approaches → actionable plan
- **Image/chart refinement**: Initial design → accessibility-polished version

---

## Mutation System

Soundings support automatic prompt mutation to explore different formulations.

### Mutation Modes

**1. Rewrite (default, recommended for learning):**
- Uses an LLM to completely rewrite the prompt while preserving intent
- Discovers fundamentally different formulations
- Highest learning value - winner patterns inform optimization
- Rewrite LLM calls are tracked in logs/costs

**2. Augment (good for testing known patterns):**
- Prepends text fragments to the original prompt
- Good for A/B testing specific known patterns
- Lower cost (no LLM call for mutation)

**3. Approach (Tree of Thought sampling):**
- Appends thinking strategy hints to the prompt
- Changes HOW the agent thinks, not the prompt itself
- Good for diversity sampling across reasoning styles

### Configuration

```json
{
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the best response",
    "mutate": true,
    "mutation_mode": "rewrite"
  }
}
```

### Built-in Mutation Templates

**Rewrite mode** (LLM instructions):
- "Rewrite to be more specific and detailed..."
- "Rewrite to emphasize step-by-step reasoning..."
- "Rewrite to focus on concrete examples..."
- "Rewrite to be more concise and direct..."
- Plus 4 more variations

**Augment mode** (prepended text):
- "Let's approach this step-by-step..."
- "Before answering, consider the key constraints..."
- "Think carefully about edge cases..."
- Plus 5 more patterns

**Approach mode** (appended strategy):
- "Approach this from a contrarian perspective..."
- "Focus on edge cases and failure modes..."
- "Think from first principles..."
- Plus 5 more strategies

### Custom Mutations

```json
{
  "soundings": {
    "factor": 3,
    "mutation_mode": "augment",
    "mutations": [
      "You are an expert in this domain...",
      "Consider the user's perspective carefully...",
      "Focus on actionable recommendations..."
    ]
  }
}
```

### Logging

All mutation data tracked in unified logs:
- `mutation_applied`: The actual mutation
- `mutation_type`: "rewrite", "augment", "approach", or null
- `mutation_template`: For rewrite mode, the instruction used

**Environment Variable:**
- `WINDLASS_REWRITE_MODEL`: Model for prompt rewrites (default: `google/gemini-2.5-flash-lite`)

---

## Multi-Model Soundings

Run soundings across different LLM providers to find the best cost/quality tradeoff.

### Phase 1: Simple Model Pool

Distribute soundings across multiple models.

**Array Format (round-robin):**
```json
{
  "soundings": {
    "factor": 6,
    "evaluator_instructions": "Pick the best response",
    "models": [
      "anthropic/claude-sonnet-4.5",
      "x-ai/grok-4.1-fast",
      "google/gemini-2.5-flash-lite"
    ],
    "model_strategy": "round_robin"
  }
}
```

**Dict Format (per-model factors):**
```json
{
  "soundings": {
    "factor": 7,
    "models": {
      "anthropic/claude-sonnet-4.5": {"factor": 2},
      "x-ai/grok-4.1-fast": {"factor": 2},
      "google/gemini-2.5-flash-lite": {"factor": 3}
    }
  }
}
```

**Model Assignment Strategies:**
- `round_robin` (default): Cycles through models in order
- `random`: Random assignment with replacement

### Phase 2: Cost-Aware Evaluation

Evaluator considers both quality and cost.

```json
{
  "soundings": {
    "factor": 3,
    "models": ["anthropic/claude-sonnet-4.5", "google/gemini-2.5-flash-lite"],
    "cost_aware_evaluation": {
      "enabled": true,
      "quality_weight": 0.7,
      "cost_weight": 0.3,
      "show_costs_to_evaluator": true,
      "cost_normalization": "min_max"
    }
  }
}
```

**Cost Normalization Methods:**
- `min_max`: Scale costs to 0-1 range
- `z_score`: Standardize using mean/std deviation
- `log_scale`: Logarithmic normalization for large cost differences

### Phase 3: Pareto Frontier Analysis

Compute non-dominated solutions and select based on policy.

```json
{
  "soundings": {
    "factor": 6,
    "models": {
      "anthropic/claude-sonnet-4.5": {"factor": 2},
      "google/gemini-2.5-flash-lite": {"factor": 4}
    },
    "pareto_frontier": {
      "enabled": true,
      "policy": "balanced",
      "show_frontier": true,
      "quality_metric": "evaluator_score",
      "include_dominated": true
    }
  }
}
```

**Pareto Policies:**
- `prefer_cheap`: Select lowest cost from frontier
- `prefer_quality`: Select highest quality from frontier
- `balanced`: Maximize quality/cost ratio

**Frontier data logged to:** `graphs/pareto_{session_id}.json`

---

## Pre-Evaluation Validator

Filter soundings before they reach the evaluator. Useful for code execution or format validation.

### Configuration

```json
{
  "soundings": {
    "factor": 5,
    "evaluator_instructions": "Pick the best solution",
    "validator": "code_execution_validator"
  }
}
```

### How It Works

1. All soundings execute normally
2. Validator runs on each sounding result
3. Only valid soundings go to evaluator
4. Saves evaluator LLM calls on broken outputs
5. If ALL fail validation, falls back to evaluating all

### Use Cases

**Code Execution Validation:**
```json
{
  "name": "solve_problem",
  "tackle": ["run_code"],
  "soundings": {
    "factor": 3,
    "validator": "code_execution_validator",
    "evaluator_instructions": "Pick the best working solution"
  }
}
```

**Format Validation:**
```json
{
  "soundings": {
    "factor": 5,
    "validator": "json_format_validator",
    "evaluator_instructions": "Pick the most complete JSON response"
  }
}
```

### Validator Protocol

Validators must return `{"valid": true/false, "reason": "..."}`. Can be:
- Python function registered with `register_tackle()`
- Cascade tool in `tackle/` directory

---

## Example Cascades

| File | Description |
|------|-------------|
| `soundings_flow.json` | Phase-level Tree of Thought |
| `soundings_rewrite_flow.json` | LLM prompt rewriting |
| `soundings_augment_flow.json` | Prepended patterns |
| `soundings_approach_flow.json` | Thinking strategies |
| `soundings_code_flow.json` | Code generation with soundings |
| `cascade_soundings_test.json` | Cascade-level soundings |
| `reforge_dashboard_metrics.json` | Phase-level reforge |
| `reforge_cascade_strategy.json` | Cascade-level reforge |
| `multi_model_simple.json` | Round-robin across models |
| `multi_model_cost_aware.json` | Cost-aware evaluation |
| `multi_model_pareto.json` | Pareto frontier analysis |
| `soundings_with_validator.json` | Pre-evaluation validation |
