# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

Windlass is a declarative agent framework for Python that orchestrates multi-step LLM workflows. It has evolved from a pure LLM orchestration framework into a **full-stack AI-native data IDE** with visual workflow building, polyglot execution, and self-healing capabilities.

**Key Philosophy**: Workflows are defined as JSON/YAML "Cascades" composed of "Phases", where each phase can be:
- **LLM-powered**: Traditional agent execution with tool calling
- **Deterministic**: Direct tool invocation without LLM mediation
- **Polyglot**: Execute SQL, Python, JavaScript, Clojure, or nested LLM phases
- **Hybrid**: Mix all approaches in a single workflow

The framework handles context accumulation, state management, execution tracing, and provides both CLI and web-based interfaces.

**The Four Self-* Properties**:
1. **Self-Orchestrating** (Manifest/Quartermaster): Workflows pick their own tools based on context
2. **Self-Testing** (Snapshot System): Tests write themselves from real executions
3. **Self-Optimizing** (Passive Optimization): Prompts improve automatically from usage data
4. **Self-Healing** (Auto-Fix): Failed cells debug and repair themselves with LLM assistance

## Installation & Setup

```bash
pip install .
```

**Required Environment Variables**:
- `OPENROUTER_API_KEY`: API key for OpenRouter (default provider)

**Optional Environment Variables**:
- `HF_TOKEN`: HuggingFace API token for Harbor (HF Spaces integration)
- `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID`: For TTS (`say` tool)
- `WINDLASS_STT_API_KEY`: API key for speech-to-text (falls back to OPENROUTER_API_KEY)
- `WINDLASS_STT_BASE_URL`: STT API URL (default: https://api.openai.com/v1)
- `WINDLASS_STT_MODEL`: STT model (default: whisper-1)

**Workspace Configuration**:
- `WINDLASS_ROOT`: Workspace root (default: current directory) - all paths derived from this

**Optional Overrides**:
- `WINDLASS_PROVIDER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
- `WINDLASS_DEFAULT_MODEL` (default: `google/gemini-2.5-flash-lite`)
- Data dirs: `WINDLASS_DATA_DIR`, `WINDLASS_LOG_DIR`, `WINDLASS_GRAPH_DIR`, `WINDLASS_STATE_DIR`, `WINDLASS_IMAGE_DIR`
- Content dirs: `WINDLASS_EXAMPLES_DIR`, `WINDLASS_TACKLE_DIR`, `WINDLASS_CASCADES_DIR`

**Database Backend**:
- Default: chDB (embedded ClickHouse) reads Parquet files in `./data/` - zero setup
- Production: Set `WINDLASS_USE_CLICKHOUSE_SERVER=true` + `WINDLASS_CLICKHOUSE_HOST=localhost`

**Directory Structure**:
```
$WINDLASS_ROOT/
├── data/          # Unified logs (Parquet files)
├── graphs/        # Mermaid execution graphs
├── states/        # Session state JSON files
├── images/        # Multi-modal image outputs
├── audio/         # Voice recordings and TTS outputs
├── examples/      # Example cascade definitions
├── tackle/        # Reusable tool cascades
└── cascades/      # User-defined cascades
```

## Common Commands

### Running Cascades
```bash
windlass examples/simple_flow.json --input '{"data": "test"}'
windlass examples/simple_flow.json --input input.json
windlass examples/simple_flow.json --input '{"key": "value"}' --session my_session_123
```

### Querying Logs with SQL
```bash
windlass sql "SELECT COUNT(*) FROM all_data"
windlass sql "SELECT session_id, phase_name, cost FROM all_data WHERE cost > 0 LIMIT 10"
windlass sql "SELECT * FROM all_data LIMIT 5" --format json
```

**Magic Tables**: `all_data` → main logs, `all_evals` → evaluation data

### Testing
```bash
# Run cascade, then freeze as test
windlass examples/simple_flow.json --input '{"data": "test"}' --session test_001
windlass test freeze test_001 --name simple_flow_works --description "Basic workflow"

# Replay (instant, no LLM calls)
windlass test replay simple_flow_works

# Run all snapshot tests
windlass test run
pytest tests/test_snapshots.py -v
```

### Traditional Tests
```bash
python -m pytest tests/
```

## Web Dashboard

Windlass includes a full-featured web-based IDE for building and executing cascades.

### Starting the Dashboard
```bash
cd dashboard
python backend/app.py
# Backend runs on http://localhost:5001

# In another terminal:
cd dashboard/frontend
npm install
npm start
# Frontend runs on http://localhost:3000 (proxies to backend)
```

### Three Main Interfaces

1. **SQL Query IDE** (`/sql-query`)
   - **Query Mode**: Traditional SQL editor with schema browser and result viewer
   - **Notebook Mode** (`?mode=notebook`): Data Cascades with polyglot cells (SQL, Python, JS, Clojure, Windlass)
   - Multi-modal output rendering (tables, images, charts, JSON)
   - Auto-fix failed cells with LLM-powered debugging

2. **Playground Canvas** (`/playground`)
   - Visual cascade builder with drag-and-drop nodes
   - Two-sided phase cards (front: output, back: YAML config)
   - Stacked deck visualization for soundings
   - Real-time execution with SSE updates
   - Save/load cascades from tackle/ or cascades/

3. **Session Explorer** (`/sessions`)
   - Browse all execution sessions
   - View session details, costs, and outputs
   - Visualize execution graphs
   - Cost analytics by session/phase/model

See `docs/claude/dashboard-reference.md` for full documentation.

## Core Architecture

### Cascade DSL

Cascades are JSON files validated via Pydantic models in `windlass/cascade.py`.

```json
{
  "cascade_id": "unique_name",
  "description": "Optional description",
  "inputs_schema": {"param_name": "description"},
  "phases": [
    {
      "name": "phase_name",
      "instructions": "Jinja2-templated prompt using {{ input.key }} or {{ state.key }}",
      "tackle": ["tool_name"],
      "handoffs": ["next_phase"],
      "rules": {"max_turns": 3, "max_attempts": 2}
    }
  ]
}
```

**Phase Configuration** (key fields):

**LLM Phases** (use `instructions`):
- `name`: Phase identifier
- `instructions`: Jinja2-templated system prompt
- `tackle`: Tool names to inject, or `"manifest"` for auto-selection
- `model`: Optional model override (e.g., `"anthropic/claude-opus-4.5"`)
- `handoffs`: Next-phase targets (enables dynamic `route_to` tool)
- `rules`: Contains `max_turns`, `max_attempts`, `loop_until`, `turn_prompt`
- `soundings`: Tree of Thought config (`factor`, `evaluator_instructions`, `mode`, `aggregator_instructions`)
- `wards`: Pre/post validation (`blocking`, `retry`, `advisory` modes)
- `context`: Selective context from other phases
- `output_schema`: JSON schema for output validation

**Deterministic Phases** (use `tool` instead of `instructions`):
- `name`: Phase identifier
- `tool`: Direct tool invocation (e.g., `"sql_data"`, `"python:module.func"`, `"sql:path/query.sql"`)
- `inputs`: Jinja2-templated inputs for the tool
- `retry`: Retry configuration (max_attempts, backoff strategy)
- `timeout`: Execution timeout (e.g., `"5m"`, `"30s"`)
- `handoffs`: Next-phase targets (routing via `_route` in tool output)

### Tool System ("Tackle")

**Three Types**:
1. **Python Functions**: Registered via `register_tackle("name", func)`
2. **Cascade Tools**: JSON cascades with `inputs_schema` in `tackle/` directory
3. **Gradio Tools (Harbor)**: HuggingFace Spaces as tools via `.tool.json` with `type: "gradio"`

**Built-in Tools**:
- **Core**: `linux_shell`, `run_code`, `set_state`, `spawn_cascade`
- **Data**: `sql_data`, `python_data`, `js_data`, `clojure_data`, `windlass_data` (polyglot execution)
- **SQL**: `smart_sql_run` (LLM-powered query generation)
- **Human-in-the-loop**: `ask_human`, `ask_human_custom`
- **Visualization**: `create_chart`, `take_screenshot`
- **Browser**: `rabbitize_*` (visual browser automation)
- **Voice**: `say` (TTS), `listen` (STT), `transcribe_audio`

**Registering Custom Tools**:
```python
from windlass import register_tackle

def my_tool(param: str) -> str:
    """Tool description for LLM."""
    return f"Result: {param}"

register_tackle("my_tool", my_tool)
```

**Dynamic Routing**: When `handoffs` configured, `route_to` tool auto-injected.

**Manifest (Quartermaster)**: Set `tackle: "manifest"` for automatic tool selection based on context.

### Execution Flow

The core engine is `WindlassRunner` in `runner.py`.

**Key Concepts**:
- **Context Snowballing**: Within a phase, full history accumulates automatically
- **Selective Context**: Between phases, context is explicit (`context: {from: ["previous"]}`)
- **State Persistence**: `Echo` object maintains `state`, `history`, `lineage`
- **Sub-Cascades**: `context_in`/`context_out` for state inheritance
- **Soundings**: Run phase/cascade N times, evaluator picks best (or aggregate all with `mode: "aggregate"`)

### Key Features Summary

| Feature | Purpose | Reference |
|---------|---------|-----------|
| **Data Cascades** | Polyglot notebooks: SQL, Python, JS, Clojure, LLM cells | `docs/claude/data-cascades-reference.md` |
| **Deterministic Execution** | Tool-based phases without LLM mediation | `docs/claude/deterministic-reference.md` |
| **Playground Canvas** | Visual cascade builder with stacked deck UI | `docs/claude/playground-reference.md` |
| **Dashboard** | Web IDE for SQL notebooks, canvas, and sessions | `docs/claude/dashboard-reference.md` |
| **Auto-Fix** | Self-healing cells with LLM-powered debugging | `docs/claude/data-cascades-reference.md` |
| **Soundings** | Parallel attempts, evaluator picks winner OR aggregate all | `docs/claude/soundings-reference.md` |
| **Aggregate Mode** | Fan-out pattern: combine all outputs instead of picking one | `docs/claude/soundings-reference.md` |
| **Reforge** | Iterative refinement of soundings winner | `docs/claude/soundings-reference.md` |
| **Wards** | Pre/post validation (blocking/retry/advisory) | `docs/claude/validation-reference.md` |
| **loop_until** | Retry until validator passes | `docs/claude/validation-reference.md` |
| **Context System** | Selective context between phases | `docs/claude/context-reference.md` |
| **Manifest** | Quartermaster auto-selects tools | `docs/claude/tools-reference.md` |
| **Rabbitize** | Visual browser automation | `docs/claude/tools-reference.md` |
| **Generative UI** | Rich human-in-the-loop interfaces | `docs/claude/tools-reference.md` |
| **Harbor** | HuggingFace Spaces as tools | `docs/harbor-design.md` |

## Module Structure

```
windlass/
├── __init__.py          # Package entry point, tool registration
├── cascade.py           # Pydantic models for Cascade DSL
├── runner.py            # WindlassRunner execution engine
├── deterministic.py     # Deterministic phase execution (NEW)
├── agent.py             # LLM wrapper (LiteLLM integration)
├── echo.py              # Echo class (state/history container)
├── tackle.py            # ToolRegistry for tool management
├── tackle_manifest.py   # Dynamic tool discovery for Quartermaster
├── tool_definitions.py  # Declarative tools (shell, http, python, composite, gradio)
├── harbor.py            # HuggingFace Spaces discovery and integration
├── config.py            # Global configuration (WINDLASS_ROOT-based)
├── unified_logs.py      # Unified logging (chDB/ClickHouse)
├── visualizer.py        # Mermaid graph generation
├── tracing.py           # TraceNode hierarchy
├── events.py            # Event bus for real-time updates
├── utils.py             # Tool schemas, image encoding
├── cli.py               # Command-line interface
├── prompts.py           # Jinja2 prompt rendering
├── eddies/              # Built-in tools
│   ├── extras.py        # linux_shell, run_code, take_screenshot
│   ├── data_tools.py    # sql_data, python_data, js_data, clojure_data, windlass_data (NEW)
│   ├── human.py         # ask_human, ask_human_custom
│   ├── state_tools.py   # set_state
│   ├── system.py        # spawn_cascade
│   └── chart.py         # create_chart
└── sql_tools/           # SQL utilities (NEW)
    └── session_db.py    # Session-scoped DuckDB

dashboard/               # Web UI (NEW)
├── backend/
│   ├── app.py           # Main Flask application
│   ├── notebook_api.py  # Data Cascades notebook endpoints
│   ├── playground_api.py # Playground canvas endpoints
│   ├── session_api.py   # Session/logs endpoints
│   └── events.py        # SSE event streaming
└── frontend/
    └── src/
        ├── sql-query/   # SQL Query IDE + Notebooks
        ├── playground/  # Visual cascade builder
        ├── sessions/    # Session explorer
        └── components/  # Shared UI components
```

## Key Implementation Patterns

### Jinja2 Templating
Phase instructions support:
- `{{ input.variable_name }}`: Initial cascade input
- `{{ state.variable_name }}`: Persistent session state
- `{{ outputs.phase_name }}`: Previous phase outputs
- `{{ lineage }}`, `{{ history }}`: Execution context
- `{{ sounding_index }}`: Current sounding index (0, 1, 2...) for fan-out patterns
- `{{ sounding_factor }}`: Total number of soundings
- `{{ is_sounding }}`: True when running as a sounding
- Rendered in `prompts.py:render_instruction()`

### Tool Return Protocol
For multi-modal (images):
```python
return {"content": "Description", "images": ["/path/to/image.png"]}
```

### Validator Protocol
All validators must return:
```json
{"valid": true, "reason": "Explanation"}
```

### Session/Trace IDs
- **Session ID**: Identifies cascade execution (generated in CLI if not provided)
- **Trace ID**: Unique per execution tree node
- Namespacing: `session_123`, `session_123_sounding_0`, `session_123_reforge1_0`

### Context Tokens
Runner uses `contextvars` to make session/trace data available to tools without explicit parameter passing.

## Example Cascades

The `examples/` directory contains reference implementations:

**Basic**: `simple_flow.json`, `loop_flow.json`, `template_flow.json`
**Routing**: `nested_parent.json`, `context_demo_parent.json`
**Soundings**: `soundings_flow.json`, `cascade_soundings_test.json`, `reforge_*.json`
**Aggregate Mode**: `soundings_aggregate_demo.json`, `soundings_fanout_demo.json`
**Validation**: `ward_*.json`, `loop_until_*.json`
**Context**: `context_selective_demo.json`, `context_sugar_demo.json`
**Tools**: `manifest_flow.json`, `rabbitize_*.json`, `hitl_flow.json`
**Voice**: `voice_transcription_demo.json`, `voice_assistant_demo.json`, `voice_conversation_demo.json`
**Data Cascades (Notebooks)** (NEW):
- `notebook_polyglot_showcase.yaml` - SQL → Python → JS → Clojure → SQL pipeline
- `notebook_llm_classification.yaml` - LLM-powered data classification
- `notebook_etl_pipeline.yaml` - Full ETL workflow
- `notebook_llm_sentiment.yaml` - Sentiment analysis
- `notebook_llm_entity_extraction.yaml` - Named entity recognition
- `notebook_llm_data_cleaning.yaml` - LLM-powered data cleaning

## Terminology (Nautical Theme)

- **Cascades**: The overall workflow/journey
- **Phases**: Stages within a Cascade
- **Tackle**: Tools and functions
- **Eddies**: Smart tools with internal resilience
- **Echoes**: State and history accumulated during a session
- **Soundings**: Parallel attempts to find the best route
- **Reforge**: Iterative refinement of the winning sounding
- **Wards**: Protective validation barriers
- **Manifest**: List of available tackle
- **Quartermaster**: Agent that selects appropriate tackle
- **Harbor**: Registry/system for HuggingFace Spaces connections
- **Berth**: A specific HF Space connection (tool definition)

## Extended Documentation

For detailed feature reference, see `docs/claude/`:

| Document | Contents |
|----------|----------|
| **NEW FEATURES** | |
| `data-cascades-reference.md` | Polyglot notebooks: SQL, Python, JS, Clojure, LLM cells with auto-fix |
| `deterministic-reference.md` | Tool-based phases without LLM mediation, hybrid workflows |
| `playground-reference.md` | Visual cascade builder, stacked deck UI, two-sided cards |
| `dashboard-reference.md` | Web IDE: SQL notebooks, canvas, session explorer |
| **CORE FEATURES** | |
| `tools-reference.md` | Tackle system, Manifest, Docker, Rabbitize, Generative UI |
| `soundings-reference.md` | Soundings, Reforge, Mutations, Multi-Model |
| `context-reference.md` | Selective context system, phase references |
| `validation-reference.md` | Wards, loop_until, turn_prompt, output_schema |
| `observability.md` | Logging, Events, Debug UI, Image Protocol |
| `testing.md` | Snapshot testing system |
| `optimization.md` | Training data, Passive prompt optimization |

Also see: `CLICKHOUSE_SETUP.md`, `TESTING.md`, `OPTIMIZATION.md`, `docs/harbor-design.md`
