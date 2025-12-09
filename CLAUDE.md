# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

Windlass is a declarative agent framework for Python that orchestrates multi-step LLM workflows. It replaces imperative glue code with a JSON-based DSL, handling context persistence, tool orchestration, and observability automatically.

**Key Philosophy**: Workflows are defined as JSON "Cascades" composed of "Phases", where each phase has specific system prompts, available tools ("Tackle"), and routing logic. The framework handles context accumulation, state management, and execution tracing.

**The Three Self-* Properties**:
1. **Self-Orchestrating** (Manifest/Quartermaster): Workflows pick their own tools based on context
2. **Self-Testing** (Snapshot System): Tests write themselves from real executions
3. **Self-Optimizing** (Passive Optimization): Prompts improve automatically from usage data

## Installation & Setup

```bash
pip install .
```

**Required Environment Variables**:
- `OPENROUTER_API_KEY`: API key for OpenRouter (default provider)

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
- `name`: Phase identifier
- `instructions`: Jinja2-templated system prompt
- `tackle`: Tool names to inject, or `"manifest"` for auto-selection
- `model`: Optional model override (e.g., `"anthropic/claude-opus-4.5"`)
- `handoffs`: Next-phase targets (enables dynamic `route_to` tool)
- `rules`: Contains `max_turns`, `max_attempts`, `loop_until`, `turn_prompt`
- `soundings`: Tree of Thought config (`factor`, `evaluator_instructions`)
- `wards`: Pre/post validation (`blocking`, `retry`, `advisory` modes)
- `context`: Selective context from other phases
- `output_schema`: JSON schema for output validation

### Tool System ("Tackle")

**Two Types**:
1. **Python Functions**: Registered via `register_tackle("name", func)`
2. **Cascade Tools**: JSON cascades with `inputs_schema` in `tackle/` directory

**Built-in Tools**: `linux_shell`, `run_code`, `smart_sql_run`, `take_screenshot`, `ask_human`, `ask_human_custom`, `set_state`, `spawn_cascade`, `create_chart`, `rabbitize_*`

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
- **Soundings**: Run phase/cascade N times, evaluator picks best

### Key Features Summary

| Feature | Purpose | Reference |
|---------|---------|-----------|
| **Soundings** | Parallel attempts, evaluator picks winner | `docs/claude/soundings-reference.md` |
| **Reforge** | Iterative refinement of soundings winner | `docs/claude/soundings-reference.md` |
| **Wards** | Pre/post validation (blocking/retry/advisory) | `docs/claude/validation-reference.md` |
| **loop_until** | Retry until validator passes | `docs/claude/validation-reference.md` |
| **Context System** | Selective context between phases | `docs/claude/context-reference.md` |
| **Manifest** | Quartermaster auto-selects tools | `docs/claude/tools-reference.md` |
| **Rabbitize** | Visual browser automation | `docs/claude/tools-reference.md` |
| **Generative UI** | Rich human-in-the-loop interfaces | `docs/claude/tools-reference.md` |

## Module Structure

```
windlass/
├── __init__.py          # Package entry point, tool registration
├── cascade.py           # Pydantic models for Cascade DSL
├── runner.py            # WindlassRunner execution engine
├── agent.py             # LLM wrapper (LiteLLM integration)
├── echo.py              # Echo class (state/history container)
├── tackle.py            # ToolRegistry for tool management
├── tackle_manifest.py   # Dynamic tool discovery for Quartermaster
├── config.py            # Global configuration (WINDLASS_ROOT-based)
├── unified_logs.py      # Unified logging (chDB/ClickHouse)
├── visualizer.py        # Mermaid graph generation
├── tracing.py           # TraceNode hierarchy
├── events.py            # Event bus for real-time updates
├── utils.py             # Tool schemas, image encoding
├── cli.py               # Command-line interface
├── prompts.py           # Jinja2 prompt rendering
└── eddies/              # Built-in tools
    ├── extras.py        # linux_shell, run_code, take_screenshot
    ├── human.py         # ask_human, ask_human_custom
    ├── state_tools.py   # set_state
    ├── system.py        # spawn_cascade
    └── chart.py         # create_chart

extras/
├── debug_ui/            # Development debug UI (Flask + React)
└── ui/                  # Production UI components
```

## Key Implementation Patterns

### Jinja2 Templating
Phase instructions support:
- `{{ input.variable_name }}`: Initial cascade input
- `{{ state.variable_name }}`: Persistent session state
- `{{ outputs.phase_name }}`: Previous phase outputs
- `{{ lineage }}`, `{{ history }}`: Execution context
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
**Validation**: `ward_*.json`, `loop_until_*.json`
**Context**: `context_selective_demo.json`, `context_sugar_demo.json`
**Tools**: `manifest_flow.json`, `rabbitize_*.json`, `hitl_flow.json`

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

## Extended Documentation

For detailed feature reference, see `docs/claude/`:

| Document | Contents |
|----------|----------|
| `tools-reference.md` | Tackle system, Manifest, Docker, Rabbitize, Generative UI |
| `soundings-reference.md` | Soundings, Reforge, Mutations, Multi-Model |
| `context-reference.md` | Selective context system, phase references |
| `validation-reference.md` | Wards, loop_until, turn_prompt, output_schema |
| `observability.md` | Logging, Events, Debug UI, Image Protocol |
| `testing.md` | Snapshot testing system |
| `optimization.md` | Training data, Passive prompt optimization |

Also see: `CLICKHOUSE_SETUP.md`, `TESTING.md`, `OPTIMIZATION.md`
