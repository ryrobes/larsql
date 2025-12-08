# Windlass

**Stop writing imperative glue code. Start orchestrating agents declaratively.**

Windlass is a production-grade framework for **long-running, iterative workflows**—not chatbots. Build agents that generate and refine complex artifacts like dashboards, reports, or charts, with vision-based feedback, validation, and error filtering. Focus on prompts, not plumbing.

**NEW: Visual browser automation with Rabbitize!** Give agents eyes and hands for the web. See [RABBITIZE_INTEGRATION.md](RABBITIZE_INTEGRATION.md).

## The Retry Hell Problem

LLM projects start clean but devolve into nested loops, error handling, and global state:

```python
# Serial retry nightmare
for attempt in range(3):
    try:
        result = llm.call(prompt)
        if validate(result):
            return result
        prompt += f"Error: {validation.error}. Retry."
    except Exception as e:
        prompt += f"Failed: {e}"
```

**Issues:** Slow (sequential), brittle (one failure blocks all), complex (spaghetti code), and suboptimal (settles for "whatever works," not the best).

**The Insight:** LLMs fail randomly. Don't fight errors serially—run attempts in parallel and filter them out.

## The Solution: Declarative Phases with Encapsulated Complexity

Windlass uses JSON cascades: sequences of **phases** that encapsulate loops, validations, and explorations. Connect boxes, not wires—keep spaghetti contained.

- **Phases**: Steps with instructions, tools, rules, and routing.
- **Default Context**: Clean slate between phases; snowball within. Explicitly target what to propagate (e.g., "previous" or specific state keys)—no bloat.
- **Execution**: Sequential phases, full history accumulation where needed.

Example cascade for a dashboard autopilot:

```json
{
  "cascade_id": "dashboard_autopilot",
  "phases": [
    {
      "name": "explore_data",
      "instructions": "Explore {{ input.database }} for insights on {{ input.question }}",
      "tackle": ["smart_sql_run"],
      "rules": {"max_turns": 2},
      "handoffs": ["generate"]
    },
    {
      "name": "generate",
      "instructions": "Create visualizations and analysis",
      "tackle": ["smart_sql_run", "create_chart"],
      "soundings": {
        "factor": 4,
        "evaluator_instructions": "Pick the most insightful"
      },
      "reforge": {
        "steps": 2,
        "honing_prompt": "Improve clarity and accuracy via visual feedback"
      },
      "wards": {
        "post": [{"validator": "data_accuracy", "mode": "blocking"}]
      }
    }
  ]
}
```

Run it: `windlass dashboard_autopilot.json --input '{"question": "Top sales trends", "database": "sales.db"}'`

## Core Primitives

### Soundings: Parallel Exploration, Not Serial Retries

Run N attempts in parallel, evaluate, and pick the best. Filters errors naturally—no manual handling.

```json
{"soundings": {"factor": 4, "evaluator_instructions": "Pick the best"}}
```

- **Why Better?** Same cost as serial loops (e.g., 4 prompts vs. 3 retries + 1 validation), but 2x faster wall time. Bad outputs auto-filtered; get the *best* success, not the first. "Waste" tokens? Serial failures waste too—it's the price of reliability.
- **Mutations**: Add `mutate: true` for prompt variants (e.g., "step-by-step" or "concise"). Explores approaches systematically.
- **Levels**: Phase-level for single steps; cascade-level for full workflows.
- **Multi-Model**: Round-robin across models with Pareto frontiers for cost/quality.

| Metric | Serial Retries | Soundings |
|--------|---------------|-----------|
| Wall Time | 6s (sequential) | 3s (parallel) |
| Quality | First success | Best of successes |
| Complexity | Nested code | 4 lines JSON |
| Errors | Manual debug | Auto-filtered |

### Reforge: Iterative Polish with Feedback

After soundings, refine the winner depth-first.

```json
{"reforge": {"steps": 2, "honing_prompt": "Improve visually: clarity, accuracy"}}
```

- Renders artifacts (e.g., charts) as images.
- Uses multi-modal LLMs for vision feedback.
- Mutations for variants during refinement.
- Ideal for artifacts: dashboards, reports, UI mockups.

Combine with soundings: Breadth-first exploration, then depth polish—at similar cost to looped validation.

### Wards: Validation as Code

Protect phases with pre/post validators in modes:

| Mode | Behavior | Use |
|------|----------|-----|
| Blocking 🛡️ | Abort on fail | Critical (e.g., safety) |
| Retry 🔄 | Re-run with feedback | Quality (e.g., grammar) |
| Advisory ℹ️ | Warn, continue | Monitoring |

```json
{"wards": {"post": [{"validator": "accuracy_check", "mode": "blocking"}]}}
```

- **Loop Until**: Auto-injects goals into prompts (or silent for impartial checks).
- Filters upstream—prevents bad outputs propagating.

## Observable by Default

Every run generates:
- **DuckDB Logs**: Queryable Parquet for history, costs, traces.
- **Mermaid Graphs**: Visual flows with soundings/reforge branches.
- **Debug UI**: Linear timeline of winners, artifacts inline (charts/images), costs/durations. Freeze runs for self-testing.
- **SSE Events**: Real-time for live UIs.

![Debug UI Example](path/to/ui-screenshot.png)  
*Linear view of a SQL chart cascade: Phases collapsed, artifacts displayed, metrics tracked.*

## Self-Evolving System

Windlass improves passively:
- **Self-Orchestrating**: "Manifest" for dynamic tool selection via Quartermaster agent.
- **Self-Testing**: Freeze runs as snapshots for regressions—no mocks.
- **Self-Optimizing**: Analyze logs from soundings/mutations; suggests prompt tweaks with impact estimates (e.g., -32% cost, +25% quality). Git-committed evolution.

## Built for Artifact Refinement

- **Vision Loops**: Generate → Render → Critique → Refine.
- **Tools (Tackle)**: Built-ins like SQL RAG, charting, code exec. Register cascades as tools.
- **Context Management**: Token budgets (sliding_window/summarize), tool caching (TTL-based).
- **HITL**: Pause for user input in generative UI flows.
- **Providers**: LiteLLM for OpenRouter/OpenAI/Azure.

## Installation

```bash
pip install windlass
export OPENROUTER_API_KEY="your-key"
```

## Quick Start

1. Create `simple.json`:
   ```json
   {
     "cascade_id": "analyzer",
     "phases": [{"name": "analyze", "instructions": "Analyze {{ input.data }}", "soundings": {"factor": 3}}]
   }
   ```
2. Run: `windlass simple.json --input '{"data": "sales.csv"}'`
3. Explore logs/UI for traces.

See `examples/` for advanced: soundings with mutations, multi-model, vision reforges.

## Why Windlass?

- **For Iterative Workflows**: Unlike LangChain (chats) or AutoGen (swarms), optimized for refinement-heavy tasks.
- **Production-Ready**: Validation, observability, economics—scales to unlimited tools.
- **No Magic**: Prompts are prompts; tools are functions.
- **From Real Pain**: Born from data analytics pipelines—encapsulates chaos declaratively.

**Stop looping imperatively. Declare, explore, refine. Let the system evolve.**

## License

MIT