# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windlass is a high-performance, declarative agent framework for Python that orchestrates complex, multi-step LLM workflows. It replaces imperative glue code with a robust JSON-based DSL, handling context persistence, tool orchestration, and observability automatically.

**Key Philosophy**: Workflows are defined as JSON "Cascades" composed of "Phases", where each phase has specific system prompts, available tools ("Tackle"), and routing logic. The framework automatically handles context accumulation ("Snowball" architecture), state management, and execution tracing.

**The Three Self-* Properties** - Windlass is a self-evolving system:

1. **Self-Orchestrating** (Manifest/Quartermaster): Workflows pick their own tools based on context
2. **Self-Testing** (Snapshot System): Tests write themselves from real executions
3. **Self-Optimizing** (Passive Optimization): Prompts improve automatically from usage data

All declarative. All observable. All data-driven.

## Installation & Setup

```bash
# Install from source
cd windlass
pip install .
```

**Required Environment Variables**:
- `OPENROUTER_API_KEY`: API key for OpenRouter (default provider)
- Optional overrides via `WINDLASS_` prefix:
  - `WINDLASS_PROVIDER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
  - `WINDLASS_DEFAULT_MODEL` (default: `x-ai/grok-4.1-fast:free`)
  - `WINDLASS_LOG_DIR` (default: `./logs`)
  - `WINDLASS_GRAPH_DIR` (default: `./graphs`)
  - `WINDLASS_STATE_DIR` (default: `./states`)
  - `WINDLASS_IMAGE_DIR` (default: `./images`)

## Common Development Commands

### Running Cascades
```bash
# Run a cascade with inline JSON input
windlass examples/simple_flow.json --input '{"data": "test"}'

# Run with a JSON file
windlass examples/simple_flow.json --input input.json

# Specify a custom session ID
windlass examples/simple_flow.json --input '{"key": "value"}' --session my_session_123
```

### Testing

**Snapshot Testing (Regression Tests):**
```bash
# 1. Run a cascade normally (uses real LLM)
windlass examples/simple_flow.json --input '{"data": "test"}' --session test_001

# 2. Verify it worked correctly (check outputs, logs, graph)

# 3. Freeze as a test (captures execution from DuckDB logs)
windlass test freeze test_001 --name simple_flow_works --description "Basic workflow"

# 4. Replay anytime (instant, no LLM calls)
windlass test replay simple_flow_works
# ✓ simple_flow_works PASSED

# 5. Run all snapshot tests
windlass test run

# 6. Or use pytest
pytest tests/test_snapshots.py -v

# List all snapshots
windlass test list
```

**What snapshot tests validate:**
- ✅ Phase execution order (routing logic)
- ✅ State management (persistence across phases)
- ✅ Tool orchestration (correct tools called)
- ✅ Ward behavior (validation fires correctly)
- ✅ Context flow (history accumulates)

**Important:** Snapshot tests validate **framework behavior**, not LLM quality. Even cascades that produce "wrong" outputs can be valid regression tests - they ensure the framework behaves consistently. If the LLM makes a weird decision but the framework correctly executes phases, validates wards, and manages state, that's a passing test. You're testing the plumbing, not the LLM.

**Traditional Unit Tests:**
```bash
cd windlass
python -m pytest tests/
```

## Core Architecture

### 1. Cascade DSL (JSON Schema)
Cascades are defined in JSON files located in `examples/`. The schema is validated via Pydantic models in `windlass/cascade.py`.

**Core Cascade Structure**:
```json
{
  "cascade_id": "unique_name",
  "description": "Optional description",
  "inputs_schema": {"param_name": "description"},
  "phases": [...]
}
```

**Phase Configuration** (`PhaseConfig` in `cascade.py`):
- `name`: Phase identifier
- `instructions`: Jinja2-templated system prompt (can reference `{{ input.key }}` or `{{ state.key }}`)
- `tackle`: List of tool names to inject, or `"manifest"` for Quartermaster auto-selection
- `manifest_context`: Context mode for Quartermaster (`"current"` or `"full"`, default: `"current"`)
- `handoffs`: List of next-phase targets (enables dynamic routing via `route_to` tool)
- `sub_cascades`: Blocking sub-cascade invocations with `context_in`/`context_out` merging
- `async_cascades`: Fire-and-forget background cascades with `trigger: "on_start"`
- `rules`: Contains `max_turns`, `max_attempts`, or `loop_until` conditions
- `soundings`: Phase-level Tree of Thought configuration for parallel attempts with evaluation (`factor`, `evaluator_instructions`, optional `reforge` for iterative refinement)
- `output_schema`: JSON schema for validating phase output with automatic retry on failure
- `wards`: Pre/post validation with three modes (blocking, retry, advisory)

**Cascade Configuration** (`CascadeConfig` in `cascade.py`):
- `cascade_id`: Unique identifier
- `description`: Optional description
- `inputs_schema`: Parameter descriptions
- `phases`: List of phase configurations
- `soundings`: Cascade-level Tree of Thought - runs entire multi-phase workflow N times and selects best execution (also supports `reforge` for iterative refinement)

### 2. Tool System ("Tackle")

**Two Types of Tackle:**

1. **Python Functions**: Fast, direct execution. Registered in tackle registry (`tackle.py`)
2. **Cascade Tools**: Complex multi-step operations as declarative cascades with `inputs_schema`

The framework automatically extracts function signatures using `inspect` and converts them to OpenAI-compatible JSON schemas via `utils.py:get_tool_schema()`.

**Built-in Tools** (registered in `__init__.py`):
- `smart_sql_run`: Execute DuckDB SQL queries on datasets (in `eddies/sql.py`)
- `run_code`: Execute Python code (in `eddies/extras.py`)
- `take_screenshot`: Capture web pages using Playwright (in `eddies/extras.py`)
- `ask_human`: Human-in-the-loop input (in `eddies/human.py`)
- `set_state`: Persist variables to session state (in `eddies/state_tools.py`)
- `spawn_cascade`: Programmatically launch cascades from tools (in `eddies/system.py`)
- `create_chart`: Generate matplotlib charts (in `eddies/chart.py`)

**Example Cascade Tools** (in `tackle/` directory):
- `text_analyzer`: Analyzes text for readability, tone, structure
- `brainstorm_ideas`: Generates creative ideas for topics
- `summarize_text`: Summarizes long text into key points
- `fact_check`: Evaluates claims for accuracy

**Validators** (in `tackle/` directory - used with Wards system):
- `simple_validator`: Basic content validation (non-empty, minimum length)
- `grammar_check`: Grammar and spelling validation
- `keyword_validator`: Required keyword presence validation
- `content_safety`: Safety and moderation checks
- `length_check`: Length constraint validation

All validators must return: `{"valid": true/false, "reason": "explanation"}`

**Dynamic Routing Tool**: When a phase has `handoffs` configured, a special `route_to` tool is auto-injected, allowing the agent to transition to the next phase based on reasoning.

**Manifest (Quartermaster Auto-Selection)**:
Instead of manually listing tools, set `tackle: "manifest"` to have a Quartermaster agent automatically select relevant tools based on the phase context. See section 2.5 below.

**Registering Custom Tools**:
```python
from windlass import register_tackle

def my_tool(param: str) -> str:
    """Tool description for LLM."""
    return f"Result: {param}"

register_tackle("my_tool", my_tool)
```

### 2.5. Manifest - Dynamic Tool Selection (Quartermaster)

Instead of manually specifying tools for each phase, use `tackle: "manifest"` to have a Quartermaster agent automatically select relevant tools.

**Configuration**:
```json
{
  "name": "adaptive_task",
  "instructions": "Complete this task: {{ input.task }}",
  "tackle": "manifest",
  "manifest_context": "full"  // "current" or "full"
}
```

**How It Works**:
1. Quartermaster examines phase instructions and context
2. Views full tackle manifest (all Python functions + cascade tools)
3. Selects only relevant tools for this specific task
4. Main agent receives focused toolset
5. Selection reasoning logged (not in main snowball)

**Context Modes**:
- `"current"` (default): Phase instructions + input data only
- `"full"`: Entire conversation history (better for multi-phase flows)

**Discovery** (`tackle_manifest.py`):
- Scans Python function registry
- Scans directories configured in `tackle_dirs` (default: `["examples/", "cascades/", "tackle/"]`)
- Cascades with `inputs_schema` automatically become tools
- Unified manifest with type, description, schema

**Benefits**:
- Scales to unlimited tool libraries
- No prompt bloat
- Contextually relevant selection
- Hybrid Python/Cascade tools

**Example**:
Task: "Analyze readability" → Quartermaster selects `text_analyzer`
Task: "Brainstorm ideas" → Quartermaster selects `brainstorm_ideas`

All automatic, no manual tool listing required.

### 2.6. Wards - Validation & Guardrails System

Wards are protective barriers that validate inputs and outputs at the phase level. Implemented in Phase 3 of the Wards system.

**Configuration** (`wards` field in PhaseConfig):
```json
{
  "wards": {
    "pre": [{"validator": "input_sanitizer", "mode": "blocking"}],
    "post": [
      {"validator": "content_safety", "mode": "blocking"},
      {"validator": "grammar_check", "mode": "retry", "max_attempts": 3},
      {"validator": "style_check", "mode": "advisory"}
    ]
  }
}
```

**Ward Types:**
- **Pre-wards**: Run BEFORE phase execution to validate inputs
- **Post-wards**: Run AFTER phase execution to validate outputs
- **Turn-wards**: Run after each turn within a phase (optional)

**Ward Modes:**
1. **Blocking** 🛡️: Aborts phase immediately on validation failure. Use for critical safety/compliance checks.
2. **Retry** 🔄: Auto-retries phase with error feedback on failure. Use for quality checks that can be improved (grammar, formatting).
3. **Advisory** ℹ️: Logs warning but continues execution. Use for optional checks (style, monitoring).

**Execution Flow:**
```
Phase Start
    ↓
🛡️  PRE-WARDS (Input Validation)
    ↓ [blocking failure → abort]
    ↓ [advisory → warn & continue]
    ↓
Phase Execution (normal turn loop)
    ↓
🛡️  POST-WARDS (Output Validation)
    ↓ [blocking failure → abort]
    ↓ [retry failure → re-execute phase with feedback]
    ↓ [advisory → warn & continue]
    ↓
Next Phase
```

**Implementation Details:**
- `_run_ward()` method in `runner.py` handles both function and cascade validators
- Ward execution creates child trace nodes for observability
- Retry mode injects `{{ validation_error }}` into retry instructions
- All ward results logged with validator name, mode, and pass/fail status
- Wards integrate with existing `loop_until` and `output_schema` validation

**Validator Protocol:**
All validators (function or cascade) must return:
```json
{
  "valid": true,  // or false
  "reason": "Explanation of validation result"
}
```

**Best Practices:**
- Layer wards by severity: blocking (critical) → retry (quality) → advisory (monitoring)
- Use pre-wards for early exit before expensive phase execution
- Combine wards with `output_schema` for structure + content validation
- Set appropriate `max_attempts` for retry wards (typically 2-3)

**Example Ward Cascades** (in `examples/`):
- `ward_blocking_flow.json`: Demonstrates blocking mode
- `ward_retry_flow.json`: Demonstrates retry mode with automatic improvement
- `ward_comprehensive_flow.json`: All three modes in one flow

### 2.7. Reforge - Iterative Refinement System

Reforge extends Soundings (Tree of Thought) with iterative refinement: after soundings complete and a winner is selected, the winner is refined through additional sounding loops with honing prompts.

**Combines Two Search Strategies:**
- **Breadth-first** (soundings): Initial exploration with N parallel attempts
- **Depth-first** (reforge): Progressive refinement of the winner

**Configuration** (`reforge` field in `SoundingsConfig`):
```json
{
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the best initial approach",
    "reforge": {
      "steps": 2,
      "honing_prompt": "Refine and improve: [specific directions]",
      "factor_per_step": 2,
      "mutate": true,
      "evaluator_override": "Pick the most refined version",
      "threshold": {"validator": "quality_check", "mode": "advisory"}
    }
  }
}
```

**Reforge Parameters:**
- `steps`: Number of refinement iterations (each step refines the previous winner)
- `honing_prompt`: Additional refinement instructions combined with winner's output
- `factor_per_step`: Number of refinement attempts per step (default: 2)
- `mutate`: Apply built-in mutation strategies to vary prompts (default: false)
- `evaluator_override`: Custom evaluator for refinement vs initial (optional)
- `threshold`: Ward-style early stopping when quality target met (optional)

**Built-in Mutation Strategies** (8 strategies that cycle):
1. Contrarian perspective
2. Edge cases focus
3. Practical implementation
4. First-principles thinking
5. UX/human factors
6. Simplicity optimization
7. Scalability focus
8. Devil's advocate

**Execution Flow:**
```
🔱 Soundings (Breadth)
  ├─ Attempt 1
  ├─ Attempt 2
  └─ Attempt 3
     ↓
  ⚖️  Evaluate → Winner
     ↓
🔨 Reforge Step 1 (Depth)
  ├─ Refine 1 (winner + honing + mutation_1)
  └─ Refine 2 (winner + honing + mutation_2)
     ↓
  ⚖️  Evaluate → New Winner
     ↓
🔨 Reforge Step 2
  ├─ Refine 1 (prev winner + honing + mutation_3)Windlass
  └─ Refine 2 (prev winner + honing + mutation_4)
     ↓
  ⚖️  Evaluate → Final Winner
     ↓
✅ Final polished output
```

**Dream Mode:**
All intermediate sounding and reforge attempts are fully logged with `sounding_index`, `reforge_step`, and `is_winner` metadata but only the final winner's output continues in the main cascade flow.

**Use Cases:**
- **Code generation**: Broad algorithm exploration → polished implementation
- **Content creation**: Creative brainstorming → refined copy
- **Strategy development**: Multiple approaches → actionable plan
- **Image/chart refinement**: Initial design → accessibility-polished version

**Dual-Level Support:**
- **Phase-level reforge**: Refines single phase output
- **Cascade-level reforge**: Refines enWindlassi-phase workflow execution

**Session ID Namespacing:**
Each reforge iteration gets unique session ID for image/state isolation:
- Main: `session_123`
- Reforge step 1, attempt 0: `session_123_reforge1_0`
- Reforge step 2, attempt 1: `session_123_reforge2_1`

**Example Reforge Cascades** (in `examples/`):
- `reforge_dashboard_metrics.json`: Phase-level reforge for metrics refinement
- `reforge_cascade_strategy.json`: Cascade-level reforge for complete workflow
- `reforge_meta_optimizer.json`: META - cascade that optimizes other cascades
- `reforge_image_chart.json`: Chart refinement with visual feedback
- `reforge_feedback_chart.json`: Feedback loops with manual image injection

### 3. Execution Flow (Runner)
The core execution engine is in `windlass/runner.py` (`SkelrigenRunner` class).

**Key Execution Concepts**:
- **Context Snowballing**: Full conversation history (user inputs, agent thoughts, tool results) accumulates across phases. An agent in Phase 3 has visibility into Phase 1's reasoning.
- **State Persistence**: The `Echo` object (`echo.py`) maintains:
  - `state`: Persistent key-value store (set via `set_state` tool)
  - `history`: Full message log with trace IDs
  - `lineage`: Phase-level output summary
- **Sub-Cascade Context**:
  - `context_in: true`: Parent's `state` is flattened into child's `input`
  - `context_out: true`: Child's final `state` is merged back into parent's `state`
- **Async Cascades**: Spawned in background threads with linked trace IDs for observability
- **Soundings (Tree of Thought)**:
  - **Phase-level**: Run a single phase N times, evaluator picks best, only winner continues
  - **Cascade-level**: Run entire multi-phase workflow N times, each gets fresh Echo with unique session ID, evaluator picks best complete execution, only winner's state/history/lineage merged into main cascade
  - All attempts fully logged with `sounding_index` and `is_winner` metadata for querying

### 4. Multi-Modal Vision Protocol & Image Handling

Images are **first-class citizens** in Skelrigen with automatic persistence and reforge integration.

**Tool Image Protocol**: If a tool returns `{"content": "...", "images": ["/path/to/file.png"]}`, the runner:
1. Detects the `images` key in the tool result
2. Reads the file and encodes it to Base64
3. Auto-saves to structured directory: `images/{session_id}/{phase_name}/image_{N}.{ext}`
4. Injects as multi-modal user message in chat history
5. Agent sees image in next turn

**Universal Image Auto-Save**: Images from ANY source are automatically saved:
- ✅ Tool outputs (via `{"images": [...]}` protocol)
- ✅ Manual injection (base64 data URLs in user messages)
- ✅ Feedback loops (validation with visual context)
- ✅ Any message format (string-embedded or multi-modal)

**Auto-save happens at strategic points:**
- After each turn completes
- Before phase completion
- Throughout reforge iterations

**Reforge Image Flow**: Images automatically flow through refinement:
1. Winner's context includes images (base64 in messages)
Windlass extracted and re-encoded for new API requests
3. Refinement context includes both honing prompt + images
4. Each reforge iteration can see and analyze previous images
5. All images saved with session namespacing to prevent collisions

**Directory Structure:**
```
images/
  {session_id}/
    {phase_name}/
      image_0.png
      image_1.png
  {session_id}_reforge1_0/
    {phase_name}/
      image_0.png
```

**Use Cases:**
- Chart generation → visual analysis → accessibility refinement
- Screenshot capture → UI critique → design iteration
- Rasterized graphics → feedback loops → polished output
- Image analysis → enhancement suggestions → implementation

This allows tools to generate charts/screenshots that the agent can analyze visually, with full persistence and reforge support for iterative visual refinement.

### 5. Observability Stack

**Core Logging:**
- **DuckDB Logging** (`logs.py`): All events are logged to Parquet files in `./logs` for high-performance querying. Schema includes `sounding_index` (0-indexed, null if not a sounding), `reforge_step` (0=initial, 1+=refinement, null if no reforge), and `is_winner` (True/False/null) for soundings/reforge analysis.
- **Mermaid Graphs** (`visualizer.py`): Real-time flowchart generation (`.mmd` files in `./graphs`) showing phase transitions, soundings, and reforges with visual grouping
- **Cost Tracking** (`cost.py`): Asynchronous workers track token usage via OpenRouter APIs, associating costs with trace IDs
- **Trace Hierarchy** (`tracing.py`): `TraceNode` class creates parent-child relationships for nested cascades and soundings attempts

**Real-Time Event System:**

Skelrigen includes a built-in event bus for real-time cascade updates via Server-Sent Events (SSE).

**Event Bus** (`events.py`):
```python
from windlass.events import get_event_bus, Event

# Publish events
bus = get_event_bus()
bus.publish(Event(
    type="phase_complete",
    session_id="session_123",
    timestamp=datetime.now().isoformat(),
    data={"phase_name": "generate", "result": {...}}
))

# Subscribe to events
queue = bus.subscribe()
while True:
    event = queue.get(timeout=30)
    print(event.to_dict())
```

**Event Publishing Hooks** (`event_hooks.py`):

The CLI automatically enables event hooks for all lifecycle events:

```python
from windlass.event_hooks import EventPublishingHooks

hooks = EventPublishingHooks()
run_cascade(config_path, input_data, session_id, hooks=hooks)
```

**Available Lifecycle Events:**
- `cascade_start` - Cascade begins execution
- `cascade_complete` - Cascade finishes successfully
- `cascade_error` - Cascade encounters error
- `phase_start` - Phase begins
- `phase_complete` - Phase completes
- `turn_start` - Agent turn starts
- `tool_call` - Tool invoked
- `tool_result` - Tool returns result

**SSE Integration Example:**

```python
# Backend (Flask/FastAPI)
from windlass.events import get_event_bus
from flask import Response, stream_with_context
import json

@app.route('/api/events/stream')
def event_stream():
    def generate():
        bus = get_event_bus()
        queue = bus.subscribe()

        while True:
            event = queue.get(timeout=30)
            yield f"data: {json.dumps(event.to_dict())}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream'
    )

# Frontend (React)
useEffect(() => {
    const eventSource = new EventSource('/api/events/stream');

    eventSource.onmessage = (e) => {
        const event = JSON.parse(e.data);
        if (event.type === 'phase_complete') {
            refreshUI(event.session_id);
        }
    };

    return () => eventSource.close();
}, []);
```

**Execution Tree API:**

For complex visualization (soundings, reforges, parallel execution), use the execution tree builder:

```python
from windlass.visualizer import ExecutionTreeBuilder

# Build hierarchical execution tree
builder = ExecutionTreeBuilder(log_dir="/path/to/logs")
tree = builder.build_tree(session_id)

# Returns structured data:
{
    'session_id': 'session_123',
    'phases': [
        {
            'name': 'generate',
            'type': 'soundings',  # or 'simple', 'reforge'
            'soundings': [
                {'index': 0, 'is_winner': False, 'events': [...]},
                {'index': 1, 'is_winner': True, 'events': [...]},
                {'index': 2, 'is_winner': False, 'events': [...]}
            ],
            'winner_index': 1
        },
        {
            'name': 'optimize',
            'type': 'reforge',
            'reforge_steps': [
                {'step': 0, 'soundings': [...], 'winner_index': 1},
                {'step': 1, 'soundings': [...], 'winner_index': 0}
            ]
        }
    ]
}
```

**React Flow Integration:**

The execution tree can be converted to React Flow format for interactive visualization:

```python
from windlass.visualizer import build_react_flow_nodes

# Convert to React Flow nodes/edges
graph = build_react_flow_nodes(tree)

# Returns:
{
    'nodes': [
        {
            'id': 'phase_0',
            'type': 'phaseNode',
            'position': {'x': 0, 'y': 0},
Windlass   'data': {'label': 'Generate', 'event_count': 45}
        },
        {
            'id': 'phase_1_sounding_0',
            'type': 'soundingNode',
            'parentNode': 'phase_1_group',
            'data': {'index': 0, 'is_winner': False}
        }
    ],
    'edges': [
        {
            'source': 'phase_0',
            'target': 'phase_1_group',
            'animated': True
        },
        {
            'source': 'phase_1_sounding_1',
            'target': 'phase_2',
            'style': {'stroke': '#00ff00', 'strokeWidth': 3}  # Winner path
        }
    ]
}
```

See `extras/debug_ui/VISUALIZATION_GUIDE.md` for complete visualization patterns and React Flow implementation examples.

### 6. LLM IntegrationWindlass
The `Agent` class (`agent.py`) wraps LiteLLM for flexible provider support.
- Default: OpenRouter with configurable base URL and API key
- Messages are sanitized to remove `tool_calls: None` fields
- Response includes request ID for cost tracking
- Automatic retry logic on API failures (2 retries)

### 7. Debug UI

Skelrigen includes a development debug UI for real-time cascade monitoring located in `extras/debug_ui/`.

**Features:**
- Real-time SSE updates (no polling required)
- Cascade list with status (running/completed/failed)
- Interactive Mermaid graph viewer (zoomable/pannable)
- Live event logs
- Run cascades from UI with input parameters
- Execution tree API for complex visualization

**Quick Start:**

```bash
# Terminal 1: Start backend
cd extras/debug_ui
./start_backend.sh

# Terminal 2: Start frontend
cd extras/debug_ui/frontend
npm start

# Open http://localhost:3000
```

**Backend Configuration:**

Set environment variables to point to your Skelrigen data directories:

```bash
export WINDLASS_LOG_DIR=/path/to/logs
export WINDLASS_GRAPH_DIR=/path/to/graphs
export WINDLASS_STATE_DIR=/path/to/states
export WINDLASS_IMAGE_DIR=/path/to/images
```

**API Endpoints:**

```
GET  /api/cascades                    # List all cascade sessions
GET  /api/logs/<session_id>Windlass  # Get logs for session
GET  /api/graph/<session_id>          # Get Mermaid graph
GET  /api/execution-tree/<session_id> # Get execution tree (JSON)
GET  /api/execution-tree/<session_id>?format=react-flow  # React Flow format
GET  /api/events/stream               # SSE event stream
POST /api/run-cascade                 # Execute cascade with inputs
```

**Event Stream Format:**

```javascript
{
  type: 'phase_complete',
  session_id: 'session_123',
  timestamp: '2025-12-02T04:00:00',
  data: {
    phase_name: 'generate',
    result: {...}
  }
}
```

**Tech Stack:**
- Backend: Flask + DuckDB + SSE
- Frontend: React + Mermaid.js
- Real-time: EventSource API

See `extras/debug_ui/VISUALIZATION_GUIDE.md` for React Flow integration and advanced visualization patterns.

## Module Structure

```
windlass/
├── __init__.py          # Package entry point, tool registration
├── cascade.py           # Pydantic models for Cascade DSL
├── runner.py            # SkelrigenRunner execution engine
├── agent.py             # LLM wrapper (LiteLLM integration)
├── echo.py              # Echo class (state/history container)
├── tackle.py            # ToolRegistry for tool management
├── config.py            # Global configuration management
├── logs.py              # DuckDB event logging
├── visualizer.py        # Mermaid graph generation (with soundings/reforge support)
├── tracing.py           # TraceNode hierarchy for observability
├── events.py            # Event bus for real-time updates
├── event_hooks.py       # EventPublishingHooks for lifecycle events
├── utils.py             # get_tool_schema, image encoding/decoding, extraction
├── cli.py               # Command-line interface
├── prompts.py           # Jinja2 prompt rendering
├── state.py             # Session state management
├── cost.py              # Async cost tracking
└── eddies/              # Built-in tools
    ├── base.py          # Eddy wrapper (retry logic)
    ├── sql.py           # DuckDB SQL execution
    ├── extras.py        # run_code, take_screenshot
    ├── human.py         # ask_human HITL tool
    ├── state_tools.py   # set_state tool
    ├── system.py        # spawn_cascade tool
 Windlassart.py         # create_chart toolWindlass

extras/
└── debug_ui/            # Development debug UI
    ├── start_backend.sh # Backend startup script
    ├── backend/
    │   ├── app.py       # Flask API server
    │   └── execution_tree.py  # Execution tree builder for React Flow
    └── frontend/
        └── src/
            ├── App.js           # Main UI with SSE integration
            ├── components/
            │   ├── CascadeList.js
            │   ├── MermaidViewer.js
            │   └── LogsPanel.js
            └── VISUALIZATION_GUIDE.md  # React Flow patterns
```

## Important Implementation Details

### Jinja2 Templating
Phase instructions support Jinja2 syntax:
- `{{ input.variable_name }}`: Access initial cascade input
- `{{ state.variable_name }}`: Access persistent session state
- Rendered in `prompts.py:render_instruction()`

### Session and Trace IDs
- **Session ID**: Identifies a single cascade execution and its lineage (generated in CLI if not provided)
- **Trace ID**: Unique identifier for each node in the execution tree (cascade, phase, or tool)
- Both are threaded through logging and visualization for full traceability

### Context Tokens
The runner uses `contextvars` (via `state_tools.py:set_current_session_id()` and `tracing.py:set_current_trace()`) to make session/trace data available to tools without explicit parameter passing.

### Hooks System & Real-Time Events
`SkelrigenRunner` accepts a `hooks` parameter (`SkelrigenHooks` class) allowing injection of custom logic at key lifecycle points:

**Lifecycle Hooks:**
- `on_cascade_start`: Called when cascade execution begins
- `on_cascade_complete`: Called when cascade execution completes successfully
- `on_cascade_error`: Called when cascade execution fails
- `on_phase_start`: Called when phase execution begins
- `on_phase_complete`: Called when phase execution completes
- `on_turn_start`: Called when a turn begins
- `on_tool_call`: Called when a tool is invoked
- `on_tool_result`: Called when a tool returns a result

Hooks can return `HookAction.CONTINUE`, `HookAction.PAUSE`, or `HookAction.INJECT` to control execution.

**Event Bus (Real-Time Updates):**
The framework includes an event bus (`windlass/events.py`) for real-time updates without polling:
- `EventPublishingHooks`: Built-in hook implementation that publishes all lifecycle events to an in-memory event bus
- SSE (Server-Sent Events) support for browser integration
- Thread-safe queue-based pub/sub system
- CLI automatically enables event hooks for real-time observability

**Example Usage:**
```python
from windlass import run_cascade
from windlass.event_hooks import EventPublishingHooks

# Enable real-time event publishing
hooks = EventPublishingHooks()
result = run_cascade("cascade.json", {"input": "data"}, hooks=hooks)

# In another thread, subscribe to events
from windlass.events import get_event_bus
bus = get_event_bus()
queue = bus.subscribe()

while True:
    event = queue.get()  # Blocks until event received
    print(f"{event.type}: {event.data}")
```

The Debug UI uses SSE to receive real-time updates as cascades execute, eliminating the need for polling.

## Example Cascades

The `examples/` directory contains reference implementations:

- **simple_flow.json**: Basic two-phase linear workflow
- **loop_flow.json**: Demonstrates `max_turns` for iterative refinement
- **nested_parent.json** / **nested_child.json**: Sub-cascade composition
- **context_demo_parent.json** / **context_demo_child.json**: State inheritance via `context_in`/`context_out`
- **side_effect_flow.json**: Async cascade spawning with `trigger: "on_start"`
- **image_flow.json**: Multi-modal vision protocol demonstration
- **memory_flow.json**: Conversation history persistence across phases
- **tool_flow.json**: Dynamic tool usage demonstration
- **template_flow.json**: Jinja2 templating in instructions
- **hitl_flow.json**: Human-in-the-loop with `ask_human`
- **soundings_flow.json**: Phase-level Tree of Thought with multiple parallel attempts and evaluation
- **soundings_code_flow.json**: Phase-level soundings applied to code generation with multiple algorithmic approaches
- **cascade_soundings_test.json**: Cascade-level Tree of Thought - runs entire multi-phase workflow N times and picks best execution
- **manifest_flow.json**: Quartermaster auto-selects tools based on task description
- **manifest_complex_flow.json**: Multi-phase workflow with full context manifest selection
- **ward_blocking_flow.json**: Wards in blocking mode for critical validations
- **ward_retry_flow.json**: Wards in retry mode for automatic quality improvement
- **ward_comprehensive_flow.json**: All three ward modes (blocking, retry, advisory) together
- **reforge_dashboard_metrics.json**: Phase-level reforge with mutation for metrics refinement
- **reforge_cascade_strategy.json**: Cascade-level reforge for complete workflow refinement
- **reforge_meta_optimizer.json**: META cascade that optimizes other cascade JSONs
- **reforge_image_chart.json**: Chart refinement with image context through reforge
- **reforge_feedback_chart.json**: Feedback loops with manual image injection and visual analysis

## Testing System (Snapshot Testing)

Skelrigen includes a powerful snapshot testing system that captures real cascade executions and replays them as regression tests **without calling LLMs**.

### How It Works

**1. Capture Phase:**
Run a cascade normally (uses real LLM):
```bash
windlass examples/routing_flow.json --input '{"text": "I love it!"}' --session test_001
```

**2. Verify Phase:**
Check that it did what you expected:
- Review output in terminal
- Check logs: `cat logs/*.parquet | grep test_001`
- Check graph: `cat graphs/test_001.mmd`
- View in debug UI

**3. Freeze Phase:**
Capture the execution from DuckDB logs as a test snapshot:
```bash
windlass test freeze test_001 \
  --name routing_handles_positive \
  --description "Tests routing to positive handler based on sentiment"
```

This creates `tests/cascade_snapshots/routing_handles_positive.json` containing:
- All LLM responses (frozen)
- All tool calls and results
- Phase execution order
- Final state
- Expectations (phases executed, state values)

**4. Replay Phase:**
Replay the snapshot instantly (no LLM calls):
```bash
windlass test replay routing_handles_positive
# ✓ routing_handles_positive PASSED
```

Framework replays the frozen responses and validates:
- Same phases executed in same order
- Same state at the end
- Same tool calls made

### Test Commands

```bash
# Freeze a session as a test
windlass test freeze <session_id> --name <snapshot_name> [--description "..."]

# Replay a single test
windlass test replay <snapshot_name> [--verbose]

# Run all snapshot tests
windlass test run [--verbose]

# List all snapshots
windlass test list

# Pytest integration (auto-discovers all snapshots)
pytest tests/test_snapshots.py -v
```

### What Gets Tested

**✅ Framework Behavior (Plumbing):**
- Phase execution order and routing logic
- State management (persistence across phases)
- Tool orchestration (correct tools called at right times)
- Ward behavior (validation runs, blocks/retries correctly)
- Context accumulation (history flows through phases)
- Handoffs and dynamic routing
- Sub-cascade context inheritance
- Async cascade spawning

**❌ NOT Tested (Intentionally):**
- LLM quality (responses are frozen from original run)
- Tool implementations (results are mocked from original run)
- New edge cases (only tests captured scenarios)

### Key Insight: "Wrong" Can Still Be a Valid Test

**Important:** Snapshot tests validate **framework behavior**, not LLM correctness.

Even if the LLM produces a "wrong" answer, the snapshot test can still be valuable:

```bash
# Example: LLM made a weird routing decision
windlass examples/routing.json --input '{"edge_case": "..."}' --session weird_001

# Output: LLM routed to unexpected phase, but framework executed correctly
# - State persisted ✓
# - Wards validated ✓
# - Context accumulated ✓
# - No crashes ✓

# Freeze it anyway!
windlass test freeze weird_001 --name routing_edge_case_handling

# This test now ensures:
# - Framework handles this edge case without crashing
# - Behavior is consistent (won't change unexpectedly)
# - If framework changes break this flow, test catches it
```

**Philosophy:** You're testing that Skelrigen's plumbing works correctly, not that the LLM is smart. If the framework:
- Routes to the correct phase based on tool calls
- Persists state properly
- Validates with wards as configured
- Accumulates context correctly

...then it's doing its job, regardless of LLM quality.

### Use Cases

**1. Regression Tests for Bug Fixes:**
```bash
# Bug: Routing breaks with empty input
# Fix cascade, test it
windlass examples/routing.json --input '{"text": ""}' --session bug_fix_001

# Freeze as regression test
windlass test freeze bug_fix_001 --name routing_handles_empty_input
# Now this bug can never come back
```

**2. Feature Development:**
```bash
# New feature: soundings with reforge
windlass examples/new_soundings_flow.json --input '{}' --session feat_001

# Works! Freeze it
windlass test freeze feat_001 --name soundings_with_reforge_works
# Now you have instant regression test for this feature
```

**3. CI/CD Integration:**
```bash
# In GitHub Actions / CI pipeline
windlass test run
pytest tests/test_snapshots.py -v
# Catches if framework changes break existing cascades
```

**4. Documenting Expected Behavior:**
```bash
# Snapshots serve as executable documentation
windlass test list
# Shows all tested scenarios with descriptions
```

### Snapshot File Format

Each snapshot is stored in `tests/cascade_snapshots/<name>.json`:

```json
{
  "snapshot_name": "routing_handles_positive",
  "description": "Tests routing to positive handler",
  "captured_at": "2025-12-02T05:30:00Z",
  "session_id": "test_001",
  "cascade_file": "examples/routing_flow.json",
  "input": {"text": "I love it!"},

  "execution": {
    "phases": [
      {
        "name": "classify",
        "turns": [
          {
            "turn_number": 1,
            "assistant_response": {
              "content": "This is positive sentiment.",
              "tool_calls": [
                {"tool": "route_to", "arguments": "{\"target\": \"handle_positive\"}"}
              ]
            },
            "tool_calls": [
              {"tool": "route_to", "result": "Routing to handle_positive"}
            ]
          }
        ]
      },
      {
        "name": "handle_positive",
        "turns": [...]
      }
    ]
  },

  "expectations": {
    "phases_executed": ["classify", "handle_positive"],
    "final_state": {},
    "completion_status": "success"
  }
}
```

### Implementation

**Core Files:**
- `windlass/testing.py` - Snapshot capture and replay logic
- `tests/test_snapshots.py` - Pytest integration
- `tests/cascade_snapshots/` - Directory for snapshot JSON files

**How Replay Works:**
1. Load snapshot JSON
2. Monkey-patch `Agent.call()` to return frozen responses
3. Run cascade normally (framework executes, but LLM responses are mocked)
4. Validate expectations (phases, state, etc.)

**Benefits:**
- ⚡ **Fast** - No LLM calls, instant execution
- 💰 **Free** - No API costs for test runs
- 🔒 **Deterministic** - Same frozen responses every time
- 📊 **Coverage** - Build test suite organically by freezing interesting runs
- 🐛 **Regression Prevention** - Catches framework changes that break existing flows

### Best Practices

**When to create snapshots:**
- ✅ After fixing a bug (regression test)
- ✅ New feature that uses multiple framework capabilities
- ✅ Edge cases you want to prevent from breaking
- ✅ Critical production workflows

**When NOT to create snapshots:**
- ❌ Every single test run (only freeze the "golden" ones)
- ❌ Experimental cascades that change frequently
- ❌ Trivial single-phase cascades (unless testing specific behavior)

**Naming conventions:**
- Use descriptive names: `routing_handles_positive_sentiment`
- Group by feature: `ward_*`, `routing_*`, `soundings_*`
- Add descriptions: `--description "Tests retry ward fixes grammar in 2 attempts"`

**Updating snapshots:**
If behavior intentionally changes:
```bash
# Re-run with new structure
windlass examples/updated_flow.json --input '{}' --session update_001

# Freeze with same name (overwrites old snapshot)
windlass test freeze update_001 --name existing_test_name
```

For complete documentation, see `TESTING.md`.

## Passive Prompt Optimization (Self-Evolving Prompts)

Windlass includes a passive optimization system that improves prompts automatically from usage data.

### The Concept

**Soundings = Continuous A/B Testing + Training Data Generation**

Every time you run a cascade with soundings:
1. Multiple variations execute (N attempts)
2. Best one wins (evaluator selects)
3. All attempts logged with metrics (cost, time, quality)
4. Winner patterns tracked in DuckDB

After 10-20 runs (50-100 sounding attempts), the system can:
- Identify which sounding approaches win most often
- Calculate cost/quality differences between winners and losers
- Extract patterns from winning responses
- Generate improved prompts
- Estimate impact (cost savings, quality improvements)

**This happens automatically - prompts improve just from using the system.**

### How It Works

**1. Use Soundings (You're Already Doing This):**
```json
{
  "name": "generate_dashboard",
  "instructions": "Create a dashboard from the data",
  "soundings": {
    "factor": 5,
    "evaluator_instructions": "Pick the most insightful dashboard"
  }
}
```

Every run = 5 sounding attempts logged with:
- Content (what the agent said/did)
- Cost (token usage)
- Winner flag (is_winner: true/false)
- Validation results (ward pass rates)

**2. System Analyzes Winners:**
```bash
windlass analyze examples/dashboard_generator.json --min-runs 10

# Queries DuckDB logs:
# - Which sounding index wins most often?
# - What's the cost difference?
# - What patterns appear in winning responses?
```

**3. Pattern Extraction:**

System analyzes winning responses for:
- Sequential patterns ("first X, then Y")
- Length characteristics (concise vs detailed)
- Structural patterns (step-by-step, exploration-first)
- Keywords (accessibility, validation, data, etc.)
- Tool usage patterns

**4. Suggestion Generation:**

Uses an LLM to synthesize improved instruction:
```
Current: "Create a dashboard from the data"

Analyzed: 20 runs, 100 sounding attempts
- Sounding #2 wins 82% of time (16/20 runs)
- Avg cost: $0.15 (vs $0.22 for losers) = -32%
- Validation pass: 95% (vs 70% for losers) = +25%

Patterns in winners:
- Start with data exploration
- Create 2-3 charts (not 1 or 5+)
- Mention accessibility
- Use step-by-step reasoning

Suggested: "First explore the data structure, then create 2-3
            accessible charts that best answer the question"

Impact: -32% cost, +25% quality, High confidence
```

**5. Apply Suggestion:**
```bash
windlass analyze examples/dashboard_generator.json --apply

# Updates cascade JSON
# Creates git commit with analysis
# New prompt becomes baseline
# Soundings continue with improved prompt
# Cycle repeats
```

### Commands

```bash
# Analyze cascade (needs 10+ runs with soundings)
windlass analyze examples/my_cascade.json

# Analyze specific phase
windlass analyze examples/my_cascade.json --phase generate

# Auto-apply improvements
windlass analyze examples/my_cascade.json --apply

# Set minimum runs threshold
windlass analyze examples/my_cascade.json --min-runs 20

# Save suggestions to file
windlass analyze examples/my_cascade.json --output suggestions.json
```

### Implementation

**Core Files:**
- `windlass/analyzer.py` - SoundingAnalyzer and PromptSuggestionManager classes
- CLI command: `windlass analyze`
- Queries DuckDB logs for sounding data
- Uses LLM to synthesize improved instructions
- Auto-commits to git with analysis

**Status: Foundation complete (CLI working)**

Future enhancements:
- UI integration (💡 Suggestions badge in debug UI)
- Side-by-side comparison view
- Cost/quality trade-off selector
- Multi-phase optimization
- Synthetic training mode (offline optimization)
- Few-shot injection from winners

### Cost/Quality Trade-offs

The analyzer can detect multiple valid improvements with different trade-offs:

```
Suggestion A (efficiency):
  • Cost: -40% cheaper
  • Quality: +10% better
  • Approach: More concise, focused

Suggestion B (quality):
  • Cost: +20% more expensive
  • Quality: +50% better
  • Approach: More thorough, detailed
```

**User chooses** based on budget vs quality needs. Data-driven decisions.

### Why This is Simpler Than DSPy

**DSPy requires:**
- Manual example collection
- Typed Python signatures
- Metric function definitions
- Batch optimization passes
- Imperative code

**Windlass requires:**
- Just use soundings (already doing this!)
- Data auto-collected (logs)
- Metrics auto-tracked (cost, wards, time)
- Continuous optimization (not batch)
- Declarative JSON (git-diffable)

**The key insight:** Soundings generate training data as a side effect of normal usage. Every run improves the system's understanding.

### Evolution Tracking

Since cascades are JSON and improvements are git commits:

```bash
git log examples/dashboard_generator.json

commit abc123 (Dec 2025) - Auto-optimize: Iteration 3
  Based on 50 runs: Added validation emphasis
  Cost: -15%, Quality: +12%

commit def456 (Nov 2025) - Auto-optimize: Iteration 2
  Based on 40 runs: Specified 2-3 charts
  Cost: -20%, Quality: +18%

commit ghi789 (Oct 2025) - Auto-optimize: Iteration 1
  Based on 20 runs: Added exploration step
  Cost: -32%, Quality: +25%

commit jkl012 (Sep 2025) - Initial version
  Basic prompt
```

**Your prompts' evolution is version-controlled and auditable.**

### Synthetic Training (Future)

For accelerated optimization, run training offline:

```bash
windlass train examples/dashboard_generator.json \
  --snapshots good_example_1,good_example_2 \
  --mutations 10 \
  --offline

# Takes snapshots with known-good inputs
# Mutates prompt 10 ways
# Runs cascades overnight
# Logs everything
# No output used (just training)

# Result: 30 extra data points for analysis
# Better confidence in suggestions
```

**Training happens while you sleep.**

For complete documentation, see `OPTIMIZATION.md`.

## Terminology (Nautical Theme)

- **Cascades**: The overall workflow/journey
- **Bearings/Phases**: Stages within a Cascade
- **Eddies**: Smart tools with internal resilience (retries, error handling)
- **Tackle**: Basic tools and functions
- **Echoes**: State and history accumulated during a session
- **Wakes**: Execution trails (visualized in graphs)
- **Soundings**: Depth measurements - multiple parallel attempts at phase-level (single step) or cascade-level (entire workflow) to find the best route forward
- **Reforge**: Iterative refinement - progressively polishing the winning sounding through depth-first exploration with honing prompts and mutations
- **Wards**: Protective barriers that validate inputs and outputs with three modes (blocking, retry, advisory)
- **Manifest**: The list of available tackle (tools), charted by the Quartermaster
- **Quartermaster**: Agent that selects appropriate tackle based on mission requirements
