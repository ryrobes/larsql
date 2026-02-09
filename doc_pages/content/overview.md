# Docs


Stop writing imperative glue code. Start orchestrating agents declaratively.


> **TIP: Quick Start**
>
> 
> Install with `pip install larsql`, run `lars bootstrap`, then try your first cascade
>     with `lars run cascades/examples/hello_world.yaml --input '{"data": "test"}'`
> 


## The Problem Everyone Faces


You start with clean code. Six months later, you're debugging this:

```the retry hell
# The retry loop that ruins every LLM project
for attempt in range(max_retries):
    try:
        result = llm.call(prompt)
        validation = validate(result)
        if validation.passed:
            return result
        # Error feedback accumulation
        prompt += f"\n\nError: {validation.error}. Try again."
    except JSONDecodeError as e:
        prompt += f"\nFailed to parse JSON: {e}"
    except ToolCallError as e:
        prompt += f"\nTool call failed: {e}"

# 47 lines later... still doesn't work reliably
```


This is the trajectory of every LLM project. You start clean, add a retry loop,
  add error handling, add context accumulation, add nested conditionals... and suddenly
  you have 2000+ lines of Python with global variables, nested loops, and debugging nightmares.


(and your cool flow-based graph UI won't help much either - it just visualizes the spaghetti to be more spaghetti like)


#### Slow


Sequential execution - wait for each failure before trying again


#### Complex


Error handling, context accumulation, nested loops, global state


#### Brittle


One random LLM hiccup blocks everything


#### Low Quality


Get whatever attempt N produces, not the best attempt


**The fundamental truth:** LLMs fail randomly. JSON parsing errors. Context confusion.
  Tool calling mistakes. You can't eliminate these failures - you have to *filter* them.

## The Insight: Stop Retrying, Start Filtering


Instead of fighting errors serially, **run multiple attempts in parallel and filter errors
  out naturally**. This is the core insight behind LARS.

```lars solution
{
  "takes": {
    "factor": 3,
    "evaluator_instructions": "Pick the best"
  }
}
```


**What happens:**
1. Run 3 attempts **in parallel** (not sequential)
2. Random LLM errors **naturally filtered out** by evaluator
3. Evaluator picks **THE BEST** of the successes (not just "whatever worked")
4. Zero error handling code needed


**This is genetic algorithms for LLM outputs.** Errors become noise to filter,
  not bugs to debug. The complexity is *contained* in declarative configuration -
  the spaghetti stays in the bowl.

### The Counterintuitive Economics


> **NOTE: Why Takes Are Faster AND Cheaper**
>
> 

| Metric                  | Serial Retries             | Takes                      |
|-------------------------|----------------------------|----------------------------|
| **Wall time**           | 6 seconds (sequential)     | 3 seconds (parallel)       |
| **Success probability** | 97.3% (compound)           | 97.3% (independent trials) |
| **Quality**             | "Whatever worked"          | "Best of successes"        |
| **Complexity**          | 47 lines of error handling | 4 lines of JSON            |
| **Error handling**      | Manual (nested try/catch)  | Automatic (filter noise)   |


With 70% LLM success rate, serial retries give you "the result from attempt 3."
  Takes give you "the best of the 2-3 that succeeded." Same cost, higher quality,
  faster execution.

## What is LARS?


LARS is a Python framework for building multi-step LLM workflows called **Cascades**.
  Unlike traditional agentic frameworks, LARS treats workflows as **declarative configurations**
  that can mix LLM-powered intelligence with deterministic execution, human-in-the-loop checkpoints,
  and polyglot code cells.

### Key Philosophy: Encapsulated Complexity


The complexity of agent orchestration is inevitable. The question is where it lives.
  Traditional approaches spread complexity across your codebase - retry loops, error handlers,
  context managers, state machines. LARS *encapsulates* that complexity inside
  declarative cells.


**No Python loops. No global state. No debugging spaghetti.**


Workflows (Cascades) are composed of **Cells**, where each cell can be:
- **LLM-Powered**: Traditional agent execution with tool calling and multi-turn conversations
- **Deterministic**: Direct tool invocation without LLM mediation (10-100x faster, $0 cost)
- **Polyglot**: Execute SQL, Python, JavaScript, Clojure, or nested cascades
- **HITL Screens**: Direct HTML rendering for human-in-the-loop checkpoints
- **Hybrid**: Mix all approaches in a single workflow


### Built for Iterative Artifact Generation


Unlike LangChain (chatbot-oriented) or AutoGen (agent-to-agent conversations), LARS is designed
  for **monolithic context agents** that iterate on complex tasks:


#### Data Dashboards


Query → Validate → Visualize → Refine


#### Report Generation


Research → Draft → Critique → Polish


#### Code Generation


Explore → Implement → Test → Optimize


#### Design Systems


Generate → Render → Critique → Iterate

## The Five Self-* Properties


LARS implements five self-improving capabilities:


#### Self-Orchestrating


**Manifest/Quartermaster** - workflows dynamically select tools based on context


#### Self-Testing


**Snapshot system** - tests write themselves from real executions


#### Self-Optimizing


**Passive optimization** - prompts improve automatically from usage data


#### Self-Healing


**Auto-fix** - failed cells debug and repair themselves with LLM assistance


#### Self-Building


**Calliope** - workflows constructed through natural language conversation

## Core Architecture


### Cascades (Workflows)


Cascades are JSON/YAML files that define multi-step workflows. Each cascade consists of:
- **Metadata**: ID, description, and input schema
- **Cells**: Individual execution stages with their own configuration
- **State**: Shared session state accessible across cells
- **Handoffs**: Dynamic routing between cells


```yaml example
cascade_id: dashboard_autopilot
description: Generate and refine data dashboards

cells:
  - name: generate_dashboard
    instructions: "Create a sales dashboard from the database"
    skills:
      - smart_sql_run
      - create_chart
    takes:
      factor: 3
      evaluator_instructions: "Pick the most insightful dashboard"
      reforge:
        steps: 2
        honing_prompt: "Improve visual clarity, data accuracy, accessibility"
    wards:
      post:
        - validator: data_accuracy
          mode: blocking
        - validator: accessibility_check
          mode: retry
          max_attempts: 2
    handoffs: [review]

  - name: review
    instructions: "Present dashboard for final approval"
    context:
      from: [generate_dashboard]
```


**What this does:**
1. **Takes:** Generate 3 dashboard variations in parallel, pick the best
2. **Wards:** Block on data errors, retry on accessibility issues
3. **Reforge:** Iteratively refine the winner with vision feedback + mutations
4. **Observability:** Full execution trace, Mermaid graphs, real-time SSE events


### Cell Types


Cells are the atomic units of execution. LARS supports four primary cell types:


| Cell Type               | Configuration             | Use Case                          |
|-------------------------|---------------------------|-----------------------------------|
| **LLM Cells**           | `instructions` + `skills` | Agent tasks with tool calling     |
| **Deterministic Cells** | `tool` + `tool_inputs`    | Direct tool execution without LLM |
| **HITL Screen Cells**   | `htmx` (HTML template)    | Human approval checkpoints        |
| **SQL Mapping Cells**   | `for_each_row`            | Process each row from a query     |


## Installation


```bash
# Basic installation
pip install larsql

# With local models support
pip install larsql[local-models]

# From source
git clone https://github.com/ryrobes/larsql
cd lars/lars
pip install -e .
```

### Required Environment Variables


```environment
# LLM Provider (OpenRouter is default)
OPENROUTER_API_KEY=sk-or-...

# Optional: Workspace location (defaults to ~/.lars)
LARS_ROOT=~/.lars

# Optional: Customize models
LARS_DEFAULT_MODEL=x-ai/grok-4.1-fast
LARS_DEFAULT_EMBED_MODEL=qwen/qwen3-embedding-8b
```


> **NOTE: No External Database Required**
>
> 
> LARS uses **DuckDB + Parquet** for all storage. No need to install
>     any external database. Just run `lars bootstrap` to get started.
> 


## Quick Start Examples


### 1. Run a Cascade


```cli
# Run with inline JSON input
lars run examples/simple_flow.json --input '{"data": "test"}'

# Run with input file
lars run examples/simple_flow.json --input input.json

# Run with specific session ID
lars run examples/simple_flow.json \
  --input '{"key": "value"}' \
  --session my_session_123
```

### 2. Query Execution Logs


```sql via cli
# Query system data via CLI
lars sql query "SELECT COUNT(*) FROM unified_logs"

# View recent sessions with costs
lars sql query "SELECT session_id, phase_name, cost
  FROM all_data
  WHERE cost > 0
  LIMIT 10"

# Export to JSON
lars sql query "SELECT * FROM all_data LIMIT 5" --format json
```

### 3. Launch Studio Web UI


```web dashboard
# Production mode
lars serve studio --port 5050

# Development mode (hot reload)
lars serve studio --dev

# Access at http://localhost:5050
# Features:
#   - /sql-query: SQL IDE + Polyglot Notebooks
#   - /playground: Visual cascade builder
#   - /sessions: Session explorer
#   - /calliope: Conversational cascade builder
```

## Training UI


LARS Studio includes a built-in **training interface** for improving cascade outputs over time:

- **Thumbs up/down rating** — Rate cascade outputs directly in Studio to signal quality
- **Confidence assessment** — LARS can auto-assess output confidence scores
- **LARS Learn integration** — Ratings feed into the self-optimization dream loop (LARS Learn),
  which uses your feedback to calibrate prompts, adjust model selections, and mutate cascade
  configurations for better results

Enable confidence assessment with:

```yaml
# In config.yaml
features:
  confidence_assessment: true
```

The learning system runs periodically (configurable via `learning.interval` in config.yaml),
  analyzing accumulated ratings to improve cascade performance automatically.


## Semantic SQL


One of LARS's most powerful features is **Semantic SQL** -
  the ability to use natural language and LLM-powered functions directly in SQL queries.

```semantic sql examples
-- Vector search with natural language
SELECT * FROM docs
WHERE title SIMILAR_TO 'sustainability report'
LIMIT 10;
-- LLM aggregation
SELECT
  category,
  LLM_SUMMARIZE(text) AS summary
FROM articles
GROUP BY category;
-- Semantic grouping
SELECT
  topics(title, 5) AS topic,
  COUNT(*) AS count
FROM documents
GROUP BY topic;
```


These operators are powered by **cascade-driven rewrites**.
  You can even create custom operators without modifying Python code -
  just define a cascade file with operator patterns!

## Next Steps


Explore the documentation to learn more:
- [Core Concepts](#core-concepts) - Understand Cascades, Cells, State, and Context
- [Cascade DSL Reference](#cascade-dsl) - Complete configuration guide
- [Cell Types](#cell-types) - Deep dive into LLM, Deterministic, HITL, and Polyglot cells
- [Semantic SQL](#semantic-sql) - Learn about SQL operators and rewrites
- [Takes & Evaluation](#takes) - Parallel execution and multi-model benchmarking
- [Tools (Skills)](#tools) - Six types of tools and how to create custom ones
