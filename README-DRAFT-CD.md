# Windlass

**Micro-FBP, macro-linear.** Complex AI workflows without the spaghetti.

![4 phases, each containing full parallel exploration](./docs/workflow_diagram.png)

*Four phases. Each one contains 8 parallel attempts, evaluation, mutations, and refinement. You define the 4 boxes. Windlass handles everything inside them.*

## The Problem

Every non-trivial LLM system ends up the same way: nested retry loops, validation chains, error accumulation, global state. You start clean and end up with 2000 lines of imperative glue code.

Traditional "workflow orchestration" doesn't help—it just gives you a prettier way to draw spaghetti. Every retry becomes a node. Every validation check becomes an edge. The graph *is* the complexity.

## The Insight

**Stop retrying. Start filtering.**

Running 4 prompts in parallel and picking the winner costs the same as running 3 validation loops on a single artifact. But it's faster (parallel vs. sequential), simpler (no error handling), and produces better results (best-of-N vs. first-success).

"Wasted" tokens on failed attempts? You were already wasting them on retry loops that accumulate errors and often get thrown away anyway. This is just what reliable LLM output costs. The question is whether you pay that cost fighting errors or filtering them.

```json
{
  "soundings": {
    "factor": 4,
    "evaluator_instructions": "Pick the best"
  }
}
```

**What happens:**
1. Run 4 attempts in parallel
2. Random LLM errors filtered out naturally
3. Evaluator picks the best success (not just "whatever worked")
4. Zero error handling code

## The Abstraction

**The phase is the unit of encapsulation, not the LLM call.**

All the messy retry/validate/feedback stuff happens *inside* the phase boundary. What you connect is the clean interface between phases. Spaghetti stays in the bowl.

```
phase₁ → phase₂ → phase₃ → phase₄
```

Each phase can contain soundings, mutations, reforge loops, validation wards, vision feedback—but at the orchestration level, it's just four boxes in sequence.

## Context Propagation

Default is *nothing*. Each phase explicitly declares what context it needs:

```json
{
  "name": "refine_chart",
  "context": {
    "from_phases": ["create_chart"],
    "include": ["artifacts", "tool_results"]
  }
}
```

No more "accumulate everything and shed at the right moment." You declare what you want, from where, and which parts. The mental model inverts from defensive (what do I exclude?) to intentional (what do I need?).

## Full Observability

![Debug UI showing cost per model, winning soundings, generated artifacts](./docs/debug_ui.png)

- **Multi-model cost tracking**: See spend per model across soundings in real-time
- **Winner visualization**: Which sounding won each phase and why
- **Artifact inspection**: View all generated outputs side-by-side
- **One-click test snapshots**: Freeze any run as a regression test

## Soundings → Mutations → Optimization

Add `mutate: true` and each sounding explores a different prompt formulation:

```json
{
  "soundings": {
    "factor": 5,
    "mutate": true
  }
}
```

Every run is silently an A/B test. After 10-20 runs, you have statistical evidence for which formulations win. Prompt engineering becomes empirical.

```bash
windlass analyze my_flow.json

# 💡 Mutation #2 wins 82% of runs
# Suggested: Update base prompt (est. -32% cost, +25% quality)
# Apply? [y/n]
```

## Reforge: Polish the Winner

Soundings find the best attempt. Reforge iteratively improves it:

```json
{
  "soundings": { "factor": 4 },
  "reforge": {
    "steps": 3,
    "honing_prompt": "Improve clarity and visual hierarchy"
  }
}
```

For vision workflows, reforge can screenshot the artifact and critique it each iteration. The refinement loop is contained—you don't see it at the orchestration level.

## Wards: Validation as a Primitive

```json
{
  "wards": {
    "post": [
      {"validator": "data_accuracy", "mode": "blocking"},
      {"validator": "accessibility", "mode": "retry", "max_attempts": 2}
    ]
  }
}
```

Three modes: `blocking` (hard stop), `retry` (fix and continue), `info` (log only). Validation concerns stay inside the phase.

## Multi-Model Pareto Frontier

With OpenRouter, soundings can span models with real-time cost data:

```json
{
  "soundings": {
    "models": ["claude-sonnet", "gpt-4o", "gemini-2.5-flash"],
    "evaluation_strategy": "pareto",
    "quality_weight": 0.7,
    "cost_weight": 0.3
  }
}
```

Find the optimal quality/cost tradeoff automatically.

## Installation

```bash
pip install windlass
```

## Quick Start

```json
{
  "cascade_id": "my_workflow",
  "phases": [
    {
      "name": "research",
      "instructions": "Research the topic",
      "tackle": ["web_search"],
      "soundings": { "factor": 3 }
    },
    {
      "name": "draft",
      "instructions": "Write a report based on research",
      "context": { "from_phases": ["research"] },
      "soundings": { "factor": 3 },
      "reforge": { "steps": 2 }
    }
  ]
}
```

```bash
windlass my_workflow.json
```

## Why Windlass?

| | Serial Retry Loops | Windlass Soundings |
|---|---|---|
| **Speed** | Sequential (wait for each failure) | Parallel (all at once) |
| **Quality** | First success | Best of successes |
| **Complexity** | Error handling, state management | 4 lines of JSON |
| **Cost** | ~Same (retries aren't free) | ~Same (but faster, better) |
| **Debugging** | Nested loops, accumulated context | Flat phases, explicit context |

**Built from production.** Windlass emerged from building data analytics pipelines that required orchestrating complex, iterative workflows with vision feedback, SQL generation, chart creation, and multi-step validation. The patterns encoded here are the ones that survived contact with real workloads.

## License

MIT