# Lars

**Stop writing imperative glue code. Start orchestrating agents declaratively.**

Lars is a production-grade agent framework for **long-running, iterative workflows** - not chatbots. If you're building agents that generate and refine complex artifacts (dashboards, reports, charts), require vision-based feedback loops, or need validation to filter LLM errors, Lars gives you the primitives to **focus on prompts, not plumbing**.

## The Problem

Building production LLM systems inevitably leads to this:

```python
# It starts clean...
result = llm.call("Generate dashboard")

# Then you add retries...
for attempt in range(max_retries):
    result = llm.call(...)
    if validate(result): break

# Then validation...
global state, errors, history
for validator in validators:
    if not validator.check(result):
        errors.append(...)
        result = llm.call(f"Fix: {errors}")

# Then vision feedback...
for iteration in range(refinement_loops):
    image = render(result)
    feedback = vision_llm.call(image)
    result = llm.call(f"Improve: {feedback}")

# Six months later: unmaintainable spaghetti
```

**Result:** Global state, nested loops, unpredictable LLM errors propagating through your system, and debugging nightmares.

### This is What Imperative Agent Code Looks Like

![Complex workflow graph showing the chaos of imperative agent orchestration](./docs/complex_workflow.png)

*Actual execution graph from a data analytics autopilot: explores data, generates SQL queries, creates charts, validates everything (with vision), composes dashboards, and themes them. Notice the iteration loops, validation branches, and vision feedback cycles.*

**This was 2000+ lines of Python with global variables and nested loops.**

## The Solution

Lars turns that nightmare into **20 lines of declarative JSON**:

```json
{
  "cascade_id": "dashboard_autopilot",
  "phases": [{
    "name": "generate_dashboard",
    "instructions": "Create a sales dashboard from the database",
    "tackle": ["smart_sql_run", "create_chart"],
    "soundings": {
      "factor": 3,
      "evaluator_instructions": "Pick the most insightful dashboard",
      "reforge": {
        "steps": 2,
        "honing_prompt": "Improve: 1) Visual clarity 2) Data accuracy 3) Accessibility",
        "mutate": true
      }
    },
    "wards": {
      "post": [
        {"validator": "data_accuracy", "mode": "blocking"},
        {"validator": "accessibility_check", "mode": "retry", "max_attempts": 2}
      ]
    }
  }]
}
```

**What this does:**
1. **Soundings**: Generate 3 dashboard variations in parallel, pick the best
2. **Wards**: Block on data errors, retry on accessibility issues
3. **Reforge**: Iteratively refine the winner with vision feedback + mutations
4. **Observability**: Full execution trace in DuckDB, Mermaid graphs, real-time SSE events

**No Python loops. No global state. No debugging spaghetti.**

## Why Lars?

### Built for Iterative Artifact Generation

Unlike LangChain (chatbot-oriented) or AutoGen (agent-to-agent conversations), Lars is designed for **monolithic context agents** that iterate on complex tasks:

- **Data dashboards**: Query → Validate → Visualize → Refine
- **Report generation**: Research → Draft → Critique → Polish
- **Code generation**: Explore → Implement → Test → Optimize
- **Design systems**: Generate → Render → Critique → Iterate

### Soundings: Parallel Exploration That's Actually More Efficient

Counterintuitively, running multiple parallel attempts is often **faster and cheaper** than serial retries:

**Traditional (Serial Retries):**
```
Attempt 1 → Validate → FAIL →
Attempt 2 → Validate → FAIL →
Attempt 3 → Validate → SUCCESS
= 6 LLM calls
```

**Soundings (Parallel + Selection):**
```
Attempt 1 ┐
Attempt 2 ├→ Evaluate → Winner
Attempt 3 ┘
= 4 LLM calls (faster, fewer tokens, errors filtered)
```

**Why this works:**
- Random LLM errors get filtered out in evaluation
- Parallel execution is faster than serial (lower latency)
- Evaluator sees all options at once (better selection)

### Observable by Default

Every cascade execution produces:
- **DuckDB logs**: Query-able Parquet files with full history
- **Mermaid graphs**: Visual flowcharts with soundings/reforge visualization
- **Real-time events**: SSE streaming for live UIs
- **Cost tracking**: Token usage per phase/sounding/reforge
- **Trace hierarchy**: Parent-child relationships for nested cascades

**You never lose visibility into what happened.**

### Validation as a Primitive (Wards)

Three modes of validation for different use cases:

| Mode | Behavior | Use Case |
|------|----------|----------|
| **Blocking** 🛡️ | Abort immediately | Safety, compliance, critical errors |
| **Retry** 🔄 | Re-execute with feedback | Quality improvements (grammar, formatting) |
| **Advisory** ℹ️ | Warn but continue | Monitoring, optional checks |

**Example: Publishing Pipeline**
```json
{
  "wards": {
    "pre": [{"validator": "content_safety", "mode": "blocking"}],
    "post": [
      {"validator": "grammar_check", "mode": "retry", "max_attempts": 3},
      {"validator": "style_guide", "mode": "advisory"}
    ]
  }
}
```

Wards ensure bad outputs never propagate to downstream phases.

## Installation

```bash
pip install .
```

**Required: Set your OpenRouter API key**
```bash
export OPENROUTER_API_KEY="your-key-here"
```

**Optional: Configure directories and model**
```bash
export LARS_DEFAULT_MODEL="anthropic/claude-3-5-sonnet"
export LARS_LOG_DIR="./logs"
export LARS_GRAPH_DIR="./graphs"
export LARS_STATE_DIR="./states"
export LARS_IMAGE_DIR="./images"
```

## Quick Start

### 1. Your First Cascade

Create `my_first_cascade.json`:

```json
{
  "cascade_id": "data_analyst",
  "inputs_schema": {
    "question": "The data analysis question to answer",
    "database": "Path to the database or CSV file"
  },
  "phases": [
    {
      "name": "explore",
      "instructions": "Explore the database to understand structure. Question: {{ input.question }}",
      "tackle": ["smart_sql_run"],
      "rules": {"max_turns": 2},
      "handoffs": ["answer"]
    },
    {
      "name": "answer",
      "instructions": "Answer the question with data and create visualizations.",
      "tackle": ["smart_sql_run", "create_chart"],
      "soundings": {
        "factor": 3,
        "evaluator_instructions": "Pick the clearest, most accurate answer"
      }
    }
  ]
}
```

Run it:
```bash
lars my_first_cascade.json --input '{"question": "What are the top sales regions?", "database": "sales.csv"}'
```

**What happens:**
1. Agent explores the database (up to 2 turns)
2. Routes to "answer" phase automatically
3. Generates 3 different answers with charts
4. Evaluator picks the best one
5. Full execution logged to DuckDB, graph generated

### 2. Add Vision Feedback

```json
{
  "name": "create_dashboard",
  "instructions": "Create a sales dashboard",
  "tackle": ["create_chart"],
  "soundings": {
    "factor": 3,
    "reforge": {
      "steps": 2,
      "honing_prompt": "Analyze the dashboard visually. Improve color accessibility and label clarity."
    }
  }
}
```

**What happens:**
1. Agent generates 3 dashboard variations
2. Best one selected by evaluator
3. **Winner rendered as image**
4. **Vision model sees image, gives feedback**
5. Agent refines (2 rounds with mutations)
6. Final polished dashboard with visual quality guaranteed

### 3. Add Validation

```json
{
  "name": "generate_report",
  "instructions": "Generate quarterly report",
  "wards": {
    "pre": [{"validator": "input_sanitizer", "mode": "blocking"}],
    "post": [
      {"validator": "fact_check", "mode": "blocking"},
      {"validator": "grammar_check", "mode": "retry", "max_attempts": 3}
    ]
  }
}
```

**What happens:**
1. Input sanitizer blocks malicious inputs
2. Report generated
3. Fact checker blocks if data is wrong
4. Grammar checker retries up to 3x if issues found
5. Only valid, well-written reports proceed

## Core Concepts

### Cascades & Phases

A **Cascade** is a workflow defined in JSON. Each **Phase** is a step with:
- Instructions (system prompt with Jinja2 templating)
- Tools (tackle) available to the agent
- Execution rules (max turns, loop conditions)
- Routing (handoffs to next phases)
- Advanced features (soundings, wards, sub-cascades)

**Phases execute sequentially** with full context accumulation (Snowball architecture) - agents in Phase 3 can reference decisions from Phase 1.

### Soundings (Tree of Thought)

Run the same phase/cascade **multiple times in parallel** and pick the best result.

**Two Levels:**

#### Phase-Level Soundings
Try multiple approaches to a **single step**:

```json
{
  "name": "solve_problem",
  "soundings": {
    "factor": 5,
    "evaluator_instructions": "Pick the most elegant solution"
  }
}
```

**Use when:** Uncertain about one specific step (e.g., "which algorithm?")

#### Cascade-Level Soundings
Run the **entire workflow** N times, each execution explores different paths:

```json
{
  "cascade_id": "product_strategy",
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the most feasible strategy"
  },
  "phases": [
    {"name": "research"},
    {"name": "analyze"},
    {"name": "recommend"}
  ]
}
```

**Use when:** Multiple valid approaches to complete problem (e.g., "which strategy works best?")

**Why soundings work:** Early decisions constrain later options. By exploring complete solution paths (not just individual steps), you find qualitatively different solutions.

### Reforge (Iterative Refinement)

After soundings pick a winner, **progressively polish it** through depth-first refinement:

```
🔱 Soundings (Breadth): 3 different approaches
  ↓
⚖️  Evaluate → Winner
  ↓
🔨 Reforge Step 1 (Depth): 2 refinements
  ↓
⚖️  Evaluate → Better Winner
  ↓
🔨 Reforge Step 2: 2 more refinements
  ↓
✅ Final polished output
```

**Configuration:**
```json
{
  "soundings": {
    "factor": 4,
    "evaluator_instructions": "Pick creative approach",
    "reforge": {
      "steps": 3,
      "honing_prompt": "Make this more actionable and specific",
      "factor_per_step": 2,
      "mutate": true
    }
  }
}
```

**Built-in Mutations** (applied when `mutate: true`):
1. Contrarian perspective
2. Edge cases focus
3. Practical implementation
4. First-principles thinking
5. UX/human factors
6. Simplicity optimization
7. Scalability focus
8. Devil's advocate

**Use cases:**
- Code: Algorithm exploration → Polished implementation
- Content: Creative brainstorming → Refined copy
- Design: Initial mockup → Accessibility-polished final
- Strategy: Multiple approaches → Actionable plan

### Wards (Validation & Guardrails)

Protective barriers that validate inputs/outputs with three execution modes:

```json
{
  "wards": {
    "pre": [
      {"validator": "input_sanitizer", "mode": "blocking"}
    ],
    "post": [
      {"validator": "content_safety", "mode": "blocking"},
      {"validator": "grammar_check", "mode": "retry", "max_attempts": 3},
      {"validator": "style_check", "mode": "advisory"}
    ]
  }
}
```

**Execution Flow:**
```
Phase Start
    ↓
🛡️  PRE-WARDS (validate inputs)
    ↓ [blocking → abort if fail]
    ↓
Phase Execution
    ↓
🛡️  POST-WARDS (validate outputs)
    ↓ [blocking → abort if fail]
    ↓ [retry → re-run phase with feedback]
    ↓ [advisory → warn but continue]
    ↓
Next Phase
```

**Validator Protocol:** All validators return `{"valid": true/false, "reason": "..."}`

**Built-in validators** (in `tackle/` directory):
- `simple_validator`: Non-empty, minimum length
- `grammar_check`: Grammar and spelling
- `keyword_validator`: Required keywords present
- `content_safety`: Safety and moderation
- `length_check`: Length constraints

**Best practices:**
- Layer by severity: blocking → retry → advisory
- Use pre-wards to fail fast before expensive operations
- Combine with `output_schema` for structure + content validation

### Multi-Modal Vision & Images

Images are **first-class citizens** with automatic persistence and reforge integration.

**Tool Image Protocol:**
```python
# Tool returns:
return json.dumps({
    "content": "Chart created",
    "images": ["/path/to/chart.png"]
})
```

**Framework automatically:**
1. Detects `images` key
2. Encodes to Base64
3. Auto-saves to `images/{session_id}/{phase_name}/image_N.png`
4. Injects as multi-modal message in history
5. Agent can "see" and analyze in next turn

**Images flow through reforge:**
- Winner's images included in refinement context
- Vision model analyzes and provides feedback
- Agent iterates with visual understanding
- All iterations saved with session namespacing

**Example:** Chart refinement with vision
```json
{
  "name": "create_chart",
  "tackle": ["create_chart"],
  "soundings": {
    "factor": 3,
    "reforge": {
      "steps": 2,
      "honing_prompt": "Analyze visually: improve color contrast, label clarity, and layout"
    }
  }
}
```

Result: Production-quality charts refined through visual feedback loops.

### Manifest (Dynamic Tool Selection)

Instead of manually listing tools, let the **Quartermaster agent** auto-select relevant tools:

```json
{
  "name": "adaptive_task",
  "instructions": "Complete this task: {{ input.task }}",
  "tackle": "manifest",
  "manifest_context": "full"
}
```

**How it works:**
1. Quartermaster examines phase instructions and context
2. Views full manifest (all Python functions + cascade tools)
3. Selects only relevant tools for this specific task
4. Main agent receives focused toolset

**Why this matters:**
- **Scales to unlimited tools**: Library of 100+ tools? No problem.
- **No prompt bloat**: Only inject relevant tools
- **Context-aware**: Same phase can get different tools based on input
- **Two-stage architecture**: Quartermaster = planner, Main agent = executor

**Context modes:**
- `"current"`: Phase instructions + input only (fast, cheap)
- `"full"`: Entire conversation history (better for multi-phase)

**Discovery:**
- Scans Python function registry
- Scans directories: `examples/`, `cascades/`, `tackle/`
- Cascades with `inputs_schema` automatically become tools

**Example:** Task "Analyze readability" → Quartermaster selects `text_analyzer`

This is how you build agent systems with massive tool libraries.

### State Management & Context

**Snowball Architecture:** Full conversation history accumulates across phases.

**Set persistent state:**
```json
{
  "name": "setup",
  "instructions": "Set progress to 25%",
  "tackle": ["set_state"]
}
```

**Access state in later phases:**
```json
{
  "name": "continue",
  "instructions": "Current progress: {{ state.progress }}. Continue task."
}
```

**Sub-cascade context inheritance:**
```json
{
  "sub_cascades": [{
    "ref": "child.json",
    "context_in": true,   // Parent's state → child's input
    "context_out": true   // Child's state → merged into parent
  }]
}
```

Child cascade receives `{{ input.progress }}` and can modify parent's state.

### Dynamic Routing

When a phase has multiple `handoffs`, a `route_to` tool is auto-injected:

```json
{
  "name": "classifier",
  "instructions": "Classify sentiment",
  "handoffs": ["positive", "negative", "neutral"]
}
```

Agent calls `route_to(target="positive")` to transition.

### Async Cascades (Fire-and-Forget)

Launch background processes that don't block main workflow:

```json
{
  "name": "main_task",
  "instructions": "Do important work",
  "async_cascades": [{
    "ref": "audit_logger.json",
    "trigger": "on_start",
    "input_map": {"event": "main_task_started"}
  }]
}
```

**Use cases:**
- Long-running validation
- Audit logging
- Background telemetry
- Side-effect processes

Async cascades are fully traced with parent linkage.

### Deterministic Phases (Direct Tool Execution)

Not everything needs an LLM. **Deterministic phases** execute tools directly without LLM mediation - perfect for data operations, validations, and other predictable tasks.

```json
{
  "name": "validate_query",
  "tool": "python:lars.demo_tools.validate_sql",
  "inputs": {
    "query": "{{ input.query }}"
  },
  "routing": {
    "valid": "execute_query",
    "invalid": "fix_query"
  },
  "handoffs": ["execute_query", "fix_query"]
}
```

**Key differences from LLM phases:**
- Uses `tool` instead of `instructions`
- Uses `inputs` for templated tool arguments
- Uses `routing` for return-value-based branching
- No token costs, instant execution, fully predictable

**Return-value routing:**
Tools return a dict with `_route` key to determine next phase:
```python
def validate_sql(query: str) -> dict:
    if is_valid(query):
        return {"_route": "valid", "cleaned_query": clean(query)}
    else:
        return {"_route": "invalid", "error": "Syntax error"}
```

**Hybrid error handling:**
When deterministic phases fail, hand off to an LLM for intelligent recovery:
```json
{
  "name": "execute_query",
  "tool": "smart_sql_run",
  "inputs": {"query": "{{ input.query }}"},
  "on_error": {
    "instructions": "SQL failed: {{ state.last_deterministic_error.error }}\n\nDiagnose and fix.",
    "tackle": ["smart_sql_run"],
    "rules": {"max_turns": 3}
  }
}
```

**Use cases:**
- Data validation (schema checks, format validation)
- ETL operations (extract, transform, load)
- File operations (read, write, copy)
- API calls (when response handling is predictable)
- Any operation that doesn't need LLM judgment

### Signals (Cross-Cascade Communication)

**Signals** enable coordination between cascades and external systems - the "wait for condition" primitive.

```json
{
  "name": "wait_for_data",
  "instructions": "Wait for upstream data to be ready",
  "tackle": ["await_signal"],
  "handoffs": ["process_data", "handle_timeout"]
}
```

**Signal tools:**

`await_signal` - Block until a named signal fires:
```python
await_signal(
    signal_name="daily_data_ready",
    timeout="4h",
    description="Wait for ETL pipeline"
)
# Returns: {"status": "fired", "payload": {...}, "_route": "fired"}
# Or: {"status": "timeout", "_route": "timeout"}
```

`fire_signal` - Wake up all cascades waiting on a signal:
```python
fire_signal(
    signal_name="daily_data_ready",
    payload={"row_count": 50000, "quality": "verified"}
)
# Returns: {"status": "success", "fired_count": 3}
```

`list_signals` - See waiting signals:
```python
list_signals(signal_name="daily_data_ready")
# Returns: {"signals": [...], "count": 2}
```

**CLI commands:**
```bash
# List all waiting signals
lars signals list

# Fire a signal from external script
lars signals fire daily_data_ready --payload '{"ready": true}'

# Check signal status
lars signals status sig_abc123

# Cancel a waiting signal
lars signals cancel sig_abc123 --reason "Pipeline cancelled"
```

**Use cases:**
- Wait for upstream ETL pipelines
- Coordinate multiple parallel cascades
- Wait for webhook events
- Human approval gates
- External system integration

**Architecture:**
- Signals persist in ClickHouse for durability
- HTTP callbacks for sub-second wake-up
- Polling fallback for reliability
- Works across processes and machines

## Triggers & Scheduling

Define **when** cascades should run, directly in the cascade file:

```json
{
  "cascade_id": "daily_etl",
  "triggers": [
    {
      "name": "daily_morning",
      "type": "cron",
      "schedule": "0 6 * * *",
      "timezone": "America/New_York",
      "description": "Run every day at 6 AM Eastern",
      "inputs": {"mode": "incremental"}
    },
    {
      "name": "on_source_ready",
      "type": "sensor",
      "check": "python:lars.triggers.sensor_file_exists",
      "args": {"path": "/data/incoming/feed.csv"},
      "poll_interval": "5m",
      "timeout": "4h"
    },
    {
      "name": "manual_run",
      "type": "manual",
      "inputs_schema": {
        "mode": {"type": "string", "enum": ["full", "incremental"]}
      }
    }
  ],
  "phases": [...]
}
```

**Trigger types:**

| Type | Purpose | Key Fields |
|------|---------|------------|
| **cron** | Time-based scheduling | `schedule`, `timezone` |
| **sensor** | Condition-based polling | `check`, `poll_interval`, `timeout` |
| **webhook** | HTTP-triggered | `auth`, `path` |
| **manual** | User-initiated | `inputs_schema` |

**Export to schedulers:**

Lars generates configs for external schedulers:

```bash
# Export to crontab format
lars triggers export examples/scheduled_etl_demo.json --format cron

# Export to systemd timer/service
lars triggers export examples/scheduled_etl_demo.json --format systemd

# Export to Kubernetes CronJob
lars triggers export examples/scheduled_etl_demo.json --format kubernetes

# Export to Airflow DAG
lars triggers export examples/scheduled_etl_demo.json --format airflow
```

**Example crontab output:**
```bash
# Lars triggers for daily_etl
# Generated at 2024-01-15T10:30:00

# Run every day at 6 AM Eastern
# Timezone: America/New_York (cron uses system timezone)
0 6 * * * lars run /path/to/daily_etl.json --input '{"mode": "incremental"}' --trigger daily_morning
```

**Example Kubernetes output:**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: lars-daily-etl-daily-morning
  namespace: default
spec:
  schedule: "0 6 * * *"
  timeZone: "America/New_York"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: lars
            image: lars:latest
            command: ["lars"]
            args: ["run", "/app/daily_etl.json", "--trigger", "daily_morning"]
```

**List triggers:**
```bash
lars triggers list examples/scheduled_etl_demo.json
```

## Built-in Tools (Tackle)

### `smart_sql_run`
Query CSV/Parquet/databases with DuckDB:
```python
smart_sql_run(query="SELECT region, SUM(sales) FROM data.csv GROUP BY region")
```

### `create_chart`
Generate matplotlib charts:
```python
create_chart(title="Sales Trends", data="10,20,30,40")
# Returns: {"content": "Chart created", "images": ["/path/to/chart.png"]}
```

### `run_code`
Execute Python code (use sandboxing in production):
```python
run_code(code="print(sum([1,2,3,4,5]))")
```

### `set_state`
Persist key-value pairs:
```python
set_state(key="progress", value="50%")
# Access later: {{ state.progress }}
```

### `ask_human`
Human-in-the-loop via CLI:
```python
ask_human(question="Should I proceed with deletion?")
```

### `spawn_cascade`
Programmatically launch cascades:
```python
spawn_cascade(cascade_path="validator.json", input_data='{"file": "output.txt"}')
```

### `take_screenshot`
Capture web pages (requires Playwright):
```python
take_screenshot(url="https://example.com")
# Returns: {"content": "Screenshot saved", "images": ["/path/to/screenshot.png"]}
```

### `await_signal`
Wait for cross-cascade signal:
```python
await_signal(signal_name="data_ready", timeout="1h", description="Wait for ETL")
# Returns: {"status": "fired", "payload": {...}} or {"status": "timeout"}
```

### `fire_signal`
Fire a signal to wake waiting cascades:
```python
fire_signal(signal_name="data_ready", payload={"rows": 1000})
# Returns: {"status": "success", "fired_count": N}
```

### `list_signals`
List waiting signals:
```python
list_signals(signal_name="data_ready")
# Returns: {"signals": [...], "count": N}
```

## Observability

### DuckDB Logs

All events → Parquet files in `./logs/` for high-performance querying:

```python
import duckdb
con = duckdb.connect()
result = con.execute("""
    SELECT timestamp, phase, role, content
    FROM './logs/*.parquet'
    WHERE session_id = 'session_123'
    ORDER BY timestamp
""").fetchdf()
```

**Schema includes:**
- `session_id`, `timestamp`, `phase`, `role`, `content`
- `trace_id`, `parent_id`, `depth` (nested cascades)
- `sounding_index`, `is_winner` (soundings)
- `reforge_step` (refinement iterations)
- `cost_usd` (token usage)

**Query examples:**
```sql
-- Compare sounding attempts
SELECT sounding_index, content, is_winner
FROM logs
WHERE phase = 'generate' AND sounding_index IS NOT NULL

-- Track reforge progression
SELECT reforge_step, content
FROM logs
WHERE is_winner = true
ORDER BY reforge_step
```

### Mermaid Graphs

Real-time flowcharts in `./graphs/` with enhanced visualization:

**Features:**
- **Soundings grouping**: Parallel attempts in blue containers with 🔱 icon
- **Winner highlighting**: Green borders with ✓ checkmarks
- **Loser dimming**: Gray dashed borders
- **Reforge steps**: Orange progressive refinement with 🔨 icon
- **Visual hierarchy**: Nested subgraphs

**View graphs:**
- Open `.mmd` files in Mermaid viewer
- GitHub (native Mermaid support)
- Mermaid Live Editor: https://mermaid.live

### Real-Time Events (SSE)

Built-in event bus for live monitoring:

```python
from lars.events import get_event_bus

bus = get_event_bus()
queue = bus.subscribe()

while True:
    event = queue.get(timeout=30)
    print(f"{event.type}: {event.data}")
```

**Lifecycle events:**
- `cascade_start`, `cascade_complete`, `cascade_error`
- `phase_start`, `phase_complete`
- `turn_start`
- `tool_call`, `tool_result`

**SSE Integration (Flask/FastAPI):**
```python
from lars.events import get_event_bus
from flask import Response, stream_with_context

@app.route('/api/events/stream')
def event_stream():
    def generate():
        bus = get_event_bus()
        queue = bus.subscribe()
        while True:
            event = queue.get(timeout=30)
            yield f"data: {json.dumps(event.to_dict())}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
```

**React/JavaScript:**
```javascript
const eventSource = new EventSource('/api/events/stream');
eventSource.onmessage = (e) => {
    const event = JSON.parse(e.data);
    if (event.type === 'phase_complete') {
        refreshUI(event.session_id);
    }
};
```

### Execution Tree API (React Flow)

For complex visualizations (soundings, reforges, parallel execution):

```python
from extras.debug_ui.backend.execution_tree import ExecutionTreeBuilder, build_react_flow_nodes

builder = ExecutionTreeBuilder(log_dir="./logs")
tree = builder.build_tree(session_id)

# Convert to React Flow format
graph = build_react_flow_nodes(tree)

# Returns nodes/edges with proper grouping:
# - Soundings in nested containers
# - Winner paths highlighted
# - Reforge steps with horizontal flow
```

See `extras/debug_ui/VISUALIZATION_GUIDE.md` for complete React Flow patterns.

### Cost Tracking

Asynchronous workers track token usage via OpenRouter APIs:

```sql
SELECT trace_id, phase, SUM(cost_usd) as total_cost
FROM './logs/*.parquet'
WHERE cost_usd IS NOT NULL
GROUP BY trace_id, phase
ORDER BY total_cost DESC
```

## Advanced Patterns

### Passive Prompt Optimization (Self-Evolving Prompts)

**Your prompts improve automatically, just by using the system.**

Soundings aren't just for getting better answers NOW - they're a **continuous optimization engine**:

```
Every Run with Soundings:
  ├─ Try 5 approaches (A/B test)
  ├─ Pick best (evaluator)
  ├─ Log all attempts (DuckDB)
  └─ Track: cost, time, quality

After 10-20 Runs:
  ├─ Patterns emerge (which approach wins most?)
  ├─ System analyzes (queries logs)
  └─ Suggests improvements (with impact estimates)

You Click "Apply":
  ├─ Cascade updated
  ├─ Git commit created
  └─ Evolution continues
```

**Example:**

```bash
# Week 1: Use cascade normally with soundings
lars examples/dashboard_gen.json --input '{...}'
# (run it 20 times for real work)

# Week 2: System has learned from 100 sounding attempts
lars analyze examples/dashboard_gen.json

# ======================================================================
# PROMPT IMPROVEMENT SUGGESTIONS
# ======================================================================
#
# Phase: generate_dashboard
#
# Current:
# "Create a dashboard from the data"
#
# Suggested:
# "First explore the data structure, then create 2-3 accessible
#  charts that best answer the question"
#
# Impact:
# • Cost: -32% ($0.22 → $0.15)
# • Quality: +25% (70% → 95% validation pass rate)
# • Confidence: High (sounding #2 wins 82% of runs)
#
# Rationale:
# - Winners follow sequential approach (explore first)
# - Winners create 2-3 charts (not 1 or 5+)
# - Winners mention accessibility
# - Winners pass validation 95% vs 70%
#
# To apply: lars analyze examples/dashboard_gen.json --apply

# Week 3+: Keep using improved prompt
# Soundings continue, new patterns emerge, cycle repeats
```

**Cost/Quality Trade-offs:**

The analyzer shows impact estimates, letting you decide:

```
Suggestion A: -40% cost, +10% quality  ← Cheaper, slightly better
Suggestion B: +20% cost, +50% quality  ← Expensive, much better

[Apply A] [Apply B] [Dismiss]
```

**You choose:** Save money or maximize quality. Data-driven decisions, not guessing.

**Why this works:**
- Soundings = automatic A/B testing (every run)
- DuckDB logs = training corpus (automatic collection)
- Winner analysis = pattern extraction (data science, not dark art)
- Git commits = evolution tracking (version-controlled prompts)

**Prompt engineering becomes data science.** Start rough, system refines over time, all from usage.

See `OPTIMIZATION.md` for complete details.

### The "Artifact Refinement Autopilot" Pattern

**Problem:** Generate complex artifacts (dashboards, reports, UI mockups) that must be:
- Visually coherent
- Data-accurate
- Accessible/compliant
- Iteratively refined based on feedback

**Solution:**
1. **Generate (Soundings)**: Create N variations, pick best
2. **Validate (Wards)**: Block on critical errors, retry fixable issues
3. **Render**: Convert to visual artifact (image, PDF)
4. **Feedback (Vision)**: Analyze artifact visually
5. **Refine (Reforge)**: Polish based on feedback with mutations
6. **Repeat**: Until quality threshold met

**Lars primitives map directly:**
- Soundings → exploration
- Wards → validation
- Image protocol → rendering
- Multi-modal → feedback
- Reforge → refinement

**Example cascade:**
```json
{
  "cascade_id": "dashboard_autopilot",
  "phases": [{
    "name": "create_dashboard",
    "instructions": "Generate sales dashboard from {{ input.database }}",
    "tackle": ["smart_sql_run", "create_chart"],
    "soundings": {
      "factor": 4,
      "evaluator_instructions": "Pick most insightful dashboard",
      "reforge": {
        "steps": 3,
        "honing_prompt": "Visual analysis: improve accessibility, clarity, and layout",
        "mutate": true,
        "threshold": {
          "validator": "accessibility_check",
          "mode": "advisory"
        }
      }
    },
    "wards": {
      "post": [
        {"validator": "data_accuracy", "mode": "blocking"},
        {"validator": "accessibility_check", "mode": "retry", "max_attempts": 2}
      ]
    }
  }]
}
```

**This pattern enables:**
- Data dashboards (original use case)
- Business reports with charts/tables
- Presentation slides
- UI mockups with design feedback
- Infographics with data viz

### Dynamic Cascade Generation (Python Escape Hatch)

For complex conditional logic, generate cascades programmatically:

```python
from lars import run_cascade

def build_cascade(complexity_level):
    sounding_factor = 3 if complexity_level < 5 else 7
    reforge_steps = 1 if complexity_level < 5 else 3

    return {
        "cascade_id": "adaptive_workflow",
        "phases": [{
            "name": "generate",
            "soundings": {
                "factor": sounding_factor,
                "reforge": {"steps": reforge_steps}
            }
        }]
    }

# Generate cascade based on input
cascade_config = build_cascade(user_input.complexity)
result = run_cascade(cascade_config, user_input.data)
```

**Best practices:**
- Keep builders pure (no side effects)
- Version control builder functions
- Test builders independently
- Use for truly dynamic logic (not simple parameterization)

### Cascades as Composable Tools

Register entire cascades as callable tools:

```python
from lars import register_cascade_as_tool

# Register cascade as tool
register_cascade_as_tool("specialized_task.json")

# Now other cascades can use it:
# "tackle": ["specialized_task"]
```

Build tool libraries from cascades for unlimited composability.

## When to Use Lars

### ✅ Lars Excels At:

- **Long-running iterative workflows** (hours, not seconds)
- **Artifact generation with refinement** (dashboards, reports, code)
- **Vision-based feedback loops** (charts, UI, design)
- **Complex multi-phase workflows** (research → analyze → report)
- **Production systems requiring observability** (audit logs, compliance)
- **Validation and error filtering** (LLM outputs are unpredictable)
- **Exploring solution spaces** (soundings for multiple approaches)

### ❌ Consider Alternatives For:

- **Simple single-shot prompts** (use raw OpenAI SDK)
- **Pure chat/conversational agents** (LangChain might fit better)
- **GUI-based workflow builders** (if you prefer visual tools)
- **Tight coupling with specific LLM features** (function calling details, etc.)
- **Existing heavy Python investment** (if you can't adopt JSON configs)

### 🎯 Perfect For:

**Researchers:** Exploring prompt strategies, comparing approaches (soundings), reproducible experiments

**Enterprises:** Compliance requirements (wards, audit logs), cost tracking, observable AI systems

**Developers:** Building AI features that refine outputs, multi-modal applications, production LLM systems

## Configuration

### Provider Setup

Lars uses LiteLLM for flexible provider support.

**OpenRouter (default):**
```bash
export OPENROUTER_API_KEY="your-key"
export LARS_DEFAULT_MODEL="anthropic/claude-3-5-sonnet"
```

**OpenAI directly:**
```bash
export LARS_PROVIDER_BASE_URL="https://api.openai.com/v1"
export LARS_PROVIDER_API_KEY="sk-..."
export LARS_DEFAULT_MODEL="gpt-4"
```

**Azure OpenAI:**
```bash
export LARS_PROVIDER_BASE_URL="https://your-resource.openai.azure.com"
export LARS_PROVIDER_API_KEY="your-azure-key"
export LARS_DEFAULT_MODEL="azure/your-deployment"
```

### Runtime Overrides

**Programmatic configuration:**
```python
from lars import set_provider, run_cascade

set_provider(
    base_url="https://api.openai.com/v1",
    api_key="sk-...",
    model="gpt-4"
)

result = run_cascade("flow.json", {"data": "test"})
```

**Per-cascade overrides:**
```python
result = run_cascade(
    "flow.json",
    {"data": "test"},
    overrides={"model": "anthropic/claude-3-opus"}
)
```

## Python API

While Lars is designed for declarative workflows, full Python API available:

```python
from lars import run_cascade, register_tackle

# Register custom tools
def my_tool(param: str) -> str:
    """Tool description for LLM."""
    return f"Processed: {param}"

register_tackle("my_tool", my_tool)

# Run cascade
result = run_cascade(
    "my_flow.json",
    input_data={"key": "value"},
    session_id="custom_session"
)

print(result["lineage"])  # Phase outputs
print(result["state"])    # Final state
print(result["history"])  # Full message history
```

## Examples

The `examples/` directory contains reference implementations:

**Basics:**
- `simple_flow.json`: Two-phase workflow
- `loop_flow.json`: Iterative refinement
- `memory_flow.json`: Context persistence
- `tool_flow.json`: Using built-in tools

**Advanced:**
- `soundings_flow.json`: Phase-level Tree of Thought
- `cascade_soundings_test.json`: Cascade-level ToT
- `reforge_dashboard_metrics.json`: Iterative refinement with mutations
- `reforge_image_chart.json`: Visual feedback loops

**Composition:**
- `context_demo_parent.json` + `context_demo_child.json`: State inheritance
- `side_effect_flow.json`: Async background cascades

**Validation:**
- `ward_blocking_flow.json`: Critical validation
- `ward_retry_flow.json`: Quality improvement with retries
- `ward_comprehensive_flow.json`: All three ward modes

**Multi-Modal:**
- `image_flow.json`: Vision protocol demonstration
- `reforge_feedback_chart.json`: Manual image injection with feedback

**Deterministic & Hybrid:**
- `deterministic_demo.json`: Tool-based phases mixed with LLM phases
- `hybrid_etl_demo.json`: ETL pipeline with intelligent error recovery
- `scheduled_etl_demo.json`: Triggers and scheduling definitions

**Signals & Coordination:**
- `signal_quick_test.json`: Basic signal wait/fire test
- `signal_consumer_demo.json`: Cascade that waits for signals
- `signal_producer_demo.json`: Cascade that fires signals
- `signal_etl_pipeline.json`: Complete ETL using signals for coordination

**Meta:**
- `reforge_meta_optimizer.json`: Cascade that optimizes other cascades
- `manifest_flow.json`: Quartermaster auto-tool-selection

## Development

### Running Tests

```bash
cd lars
python -m pytest tests/
```

### Project Structure

```
lars/
├── lars/                # Core framework
│   ├── runner.py           # Execution engine
│   ├── agent.py            # LLM wrapper (LiteLLM)
│   ├── cascade.py          # Pydantic models for DSL
│   ├── tackle.py           # Tool registry
│   ├── echo.py             # State/history container
│   ├── logs.py             # DuckDB logging
│   ├── visualizer.py       # Mermaid graphs
│   ├── tracing.py          # Trace hierarchy
│   ├── events.py           # Event bus (SSE)
│   └── eddies/             # Built-in tools
├── examples/               # Reference cascades
├── tackle/                 # Validators and cascade tools
├── tests/                  # Test suite
└── extras/debug_ui/        # Development UI
    ├── backend/
    │   ├── app.py          # Flask API with SSE
    │   └── execution_tree.py  # React Flow builder
    └── frontend/           # React UI
```

## Terminology (Nautical Theme)

- **Cascades**: The overall workflow/journey
- **Phases**: Stages within a cascade
- **Tackle**: Tools and functions available to agents
- **Eddies**: Smart tools with internal resilience
- **Echoes**: State and history accumulated during session
- **Wakes**: Execution trails visualized in graphs
- **Soundings**: Depth measurements - parallel exploration to find best route
- **Reforge**: Iterative refinement - polishing the winner
- **Wards**: Protective barriers for validation
- **Manifest**: Tool library, charted by the Quartermaster
- **Quartermaster**: Agent that selects appropriate tools
- **Signals**: Cross-cascade communication - "wait for condition" primitives
- **Triggers**: Scheduling definitions (cron, sensor, webhook, manual)
- **Deterministic Phases**: Direct tool execution without LLM mediation

## License

MIT

---

## The Three Self-* Properties

Lars isn't just a framework - it's a **self-evolving system**:

### 1. **Self-Orchestrating** (Manifest/Quartermaster)
Workflows pick their own tools based on context.

```json
{
  "name": "adaptive_task",
  "tackle": "manifest"  // Quartermaster auto-selects relevant tools
}
```

**No manual tool lists.** Agent examines the task and chooses appropriate tools from unlimited library.

### 2. **Self-Testing** (Snapshot System)
Tests write themselves from real executions.

```bash
# Run cascade, verify it works
lars examples/flow.json --session test_001

# Freeze as test (one command)
lars test freeze test_001 --name flow_works

# Forever regression-proof (instant, no LLM calls)
lars test validate flow_works
```

**No manual mocking.** Click a button (or run one command), test created. Validates framework behavior without expensive LLM calls.

### 3. **Self-Optimizing** (Passive Optimization)
Prompts improve automatically from usage data.

```bash
# Use system normally with soundings (A/B tests every run)
# After 10-20 runs...

lars analyze examples/flow.json

# Output:
# 💡 Prompt could be 32% cheaper, 25% better
# Based on: Sounding #2 wins 82% of runs
#
# Apply? [Yes]

# Prompt updated, committed to git
# Evolution continues
```

**No manual tuning.** Soundings generate training data automatically. System learns winner patterns. Suggests improvements with impact estimates.

---

## What Makes Lars Different?

**Not just another agent framework.** Lars provides:

1. **Infrastructure as Code for AI** - Agent behaviors as version-controlled configs
2. **Observable by Default** - Full traces, queryable logs, visual graphs, real-time events
3. **Production-Grade Primitives** - Wards for validation, cost tracking, error filtering
4. **Parallel Universe Execution** - Cascade-level soundings explore complete solution spaces
5. **Vision-First Multi-Modal** - Images as first-class citizens, automatic persistence
6. **Scales to Unlimited Tools** - Manifest system for dynamic tool selection
7. **Self-Evolving** - Workflows orchestrate themselves, tests write themselves, prompts optimize themselves
8. **No Magic** - Prompts are prompts, tools are functions, no framework magic

**Built from production experience, not academic research.** Lars emerged from building a data analytics autopilot that required orchestrating complex, iterative workflows with vision feedback, validation, and error filtering.

**The insight:** Soundings aren't just for better answers NOW - they're a continuous optimization engine that makes your prompts better over time, automatically, just from usage.

**Stop fighting imperative Python loops. Start declaring what you want. Let the system evolve itself.**
