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

**Workspace Configuration** (WINDLASS_ROOT-based):
- `WINDLASS_ROOT`: Workspace root directory (default: current directory)
  - All data and content paths are derived from this single variable
  - No need to set individual directory variables unless you want custom paths

**Optional Overrides**:
- Provider settings:
  - `WINDLASS_PROVIDER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
  - `WINDLASS_DEFAULT_MODEL` (default: `google/gemini-2.5-flash-lite`)
- Data directories (auto-derived from `WINDLASS_ROOT` if not set):
  - `WINDLASS_DATA_DIR` (default: `$WINDLASS_ROOT/data`)
  - `WINDLASS_LOG_DIR` (default: `$WINDLASS_ROOT/logs`)
  - `WINDLASS_GRAPH_DIR` (default: `$WINDLASS_ROOT/graphs`)
  - `WINDLASS_STATE_DIR` (default: `$WINDLASS_ROOT/states`)
  - `WINDLASS_IMAGE_DIR` (default: `$WINDLASS_ROOT/images`)
- Content directories (auto-derived from `WINDLASS_ROOT` if not set):
  - `WINDLASS_EXAMPLES_DIR` (default: `$WINDLASS_ROOT/examples`)
  - `WINDLASS_TACKLE_DIR` (default: `$WINDLASS_ROOT/tackle`)
  - `WINDLASS_CASCADES_DIR` (default: `$WINDLASS_ROOT/cascades`)

**Database Backend (chDB / ClickHouse):**
- Default: **chDB** (embedded ClickHouse) reads Parquet files in `./data/` - zero setup
- Production: **ClickHouse server** with automatic database/table creation
- Scale: Set 2 env vars to switch from embedded → distributed server

**Optional: ClickHouse Server Mode:**
- `WINDLASS_USE_CLICKHOUSE_SERVER` (default: `false`) - Enable ClickHouse server
- `WINDLASS_CLICKHOUSE_HOST` (default: `localhost`) - Server hostname
- `WINDLASS_CLICKHOUSE_PORT` (default: `9000`) - Native protocol port
- `WINDLASS_CLICKHOUSE_DATABASE` (default: `windlass`) - Database name (auto-created)
- `WINDLASS_CLICKHOUSE_USER` (default: `default`) - Username
- `WINDLASS_CLICKHOUSE_PASSWORD` (default: `""`) - Password

**Workspace Directory Structure**:
```
$WINDLASS_ROOT/
├── data/          # Unified logs (Parquet files) - chDB mode
├── logs/          # Old logs (backward compatibility)
├── graphs/        # Mermaid execution graphs
├── states/        # Session state JSON files
├── images/        # Multi-modal image outputs
├── examples/      # Example cascade definitions
├── tackle/        # Reusable tool cascades
└── cascades/      # User-defined cascades
```

**Note**: In ClickHouse server mode, logs write directly to the database instead of `./data/` parquet files.

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

### Querying Logs with SQL

Windlass includes a convenient SQL command that automatically translates magic table names to parquet scans:

```bash
# Simple count
windlass sql "SELECT COUNT(*) FROM all_data"

# Filter and project columns
windlass sql "SELECT session_id, phase_name, cost FROM all_data WHERE cost > 0 LIMIT 10"

# Aggregate queries
windlass sql "SELECT session_id, COUNT(*) as msg_count FROM all_data GROUP BY session_id"

# With table alias
windlass sql "SELECT a.session_id, a.phase_name FROM all_data a WHERE a.role = 'assistant'"

# Joins across data sources
windlass sql "SELECT * FROM all_data a JOIN all_evals e ON a.session_id = e.session_id"

# Different output formats
windlass sql "SELECT * FROM all_data LIMIT 5" --format json
windlass sql "SELECT * FROM all_data LIMIT 5" --format csv
windlass sql "SELECT * FROM all_data LIMIT 5" --format table  # default
```

**Magic Table Names:**
- `all_data` → `file('data/*.parquet', Parquet)` - main execution logs
- `all_evals` → `file('data/evals/*.parquet', Parquet)` - evaluation data

The SQL command automatically handles:
- ✅ Union by name (handles schema evolution across files)
- ✅ Case-insensitive table names (ALL_DATA, all_data work)
- ✅ Table aliases and joins
- ✅ Multiple output formats (table, json, csv)
- ✅ Result limiting with `--limit N`

This makes debugging and data exploration much easier - no need to type out the full `file()` scan syntax!

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
- `model`: Optional model override for this phase (e.g., `"anthropic/claude-opus-4.5"` for expensive phases)
- `use_native_tools`: Boolean (default: `false`) - Use provider native tool calling vs prompt-based (see section 2.9)
- `handoffs`: List of next-phase targets (enables dynamic routing via `route_to` tool); can include descriptions for routing menu
- `sub_cascades`: Blocking sub-cascade invocations with `context_in`/`context_out` merging
- `async_cascades`: Fire-and-forget background cascades with `trigger: "on_start"` or `"on_end"`
- `rules`: Contains `max_turns`, `max_attempts`, `turn_prompt` (custom prompt for turn 1+ iterations with Jinja2 support), `loop_until` (validator name to keep looping until it passes), `loop_until_prompt` (optional custom validation goal prompt), `loop_until_silent` (skip auto-injection for impartial validation), and `retry_instructions` (injected on retry)
- `soundings`: Phase-level Tree of Thought configuration for parallel attempts with evaluation (`factor`, `max_parallel`, `evaluator_instructions`, `mutate`, `mutation_mode`, optional `reforge` for iterative refinement)
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
- `linux_shell`: Execute shell commands in sandboxed Ubuntu Docker container (in `eddies/extras.py`)
- `run_code`: Execute Python code in Docker container (in `eddies/extras.py`) - uses linux_shell internally
- `smart_sql_run`: Execute DuckDB SQL queries on datasets (in `eddies/sql.py`)
- `take_screenshot`: Capture web pages using Playwright (in `eddies/extras.py`)
- `ask_human`: Human-in-the-loop input (in `eddies/human.py`)
- `ask_human_custom`: Generative UI for rich human-in-the-loop interactions (in `eddies/human.py`) - **NEW!**
- `set_state`: Persist variables to session state (in `eddies/state_tools.py`)
- `spawn_cascade`: Programmatically launch cascades from tools (in `eddies/system.py`)
- `create_chart`: Generate matplotlib charts (in `eddies/chart.py`)
- `rabbitize_start`: Start visual browser automation session (in `eddies/rabbitize.py`)
- `rabbitize_execute`: Execute browser actions with visual feedback (in `eddies/rabbitize.py`)
- `rabbitize_extract`: Extract page content as markdown (in `eddies/rabbitize.py`)
- `rabbitize_close`: Close browser session (in `eddies/rabbitize.py`)
- `rabbitize_status`: Get current session status (in `eddies/rabbitize.py`)

**Example Cascade Tools** (in `tackle/` directory):
- `text_analyzer`: Analyzes text for readability, tone, structure
- `brainstorm_ideas`: Generates creative ideas for topics
- `summarize_text`: Summarizes long text into key points
- `fact_check`: Evaluates claims for accuracy
- `web_navigator`: Navigate websites with visual feedback to accomplish goals - **NEW!**

**Validators** (in `tackle/` directory - used with Wards system):
- `simple_validator`: Basic content validation (non-empty, minimum length)
- `grammar_check`: Grammar and spelling validation
- `keyword_validator`: Required keyword presence validation
- `content_safety`: Safety and moderation checks
- `length_check`: Length constraint validation
- `web_goal_achieved`: Validates if web navigation goal was achieved - **NEW!**

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

### 2.6. Loop Until Validation - Automatic Goal Injection

When using `loop_until` for validation-based retries, Windlass automatically injects the validation goal into the phase instructions so the agent knows upfront what it needs to satisfy.

**Configuration**:
```json
{
  "name": "generate_content",
  "instructions": "Write a blog post about {{ input.topic }}",
  "rules": {
    "max_attempts": 3,
    "loop_until": "grammar_check"
  }
}
```

**Auto-Injection Behavior**:
The system automatically appends to the instructions:
```
---
VALIDATION REQUIREMENT:
Your output will be validated using 'grammar_check' which checks: Validates grammar and spelling in text
You have 3 attempt(s) to satisfy this validator.
---
```

**Custom Validation Prompt** (Optional):
Override the auto-generated prompt with a custom one:
```json
{
  "rules": {
    "loop_until": "grammar_check",
    "loop_until_prompt": "Custom instruction about what makes valid output"
  }
}
```

**Silent Mode - Impartial Validation**:

For subjective quality checks where you need an impartial third party, use `loop_until_silent: true` to skip auto-injection:

```json
{
  "name": "write_report",
  "instructions": "Write a report on the findings.",
  "rules": {
    "loop_until": "quality_check",
    "loop_until_silent": true  // Agent doesn't know it's being evaluated
  }
}
```

**The Self-Validation Paradox**:

Auto-injection works great for **objective validators** (grammar, code execution, format checks) but creates gaming risk for **subjective validators**:

| Mode | Validator Type | Example | Gaming Risk |
|------|---------------|---------|-------------|
| **Auto-Injection** (default) | Objective checks | `grammar_check`, `code_execution_validator` | ✅ Low - clear specs |
| **Silent** (`loop_until_silent: true`) | Subjective judgments | `satisfied`, `quality_check`, `readability` | ✅ Prevented - impartial |

**Why Silent Mode Matters**:

```json
// Without silent mode:
{
  "instructions": "Write a report.",
  "rules": { "loop_until": "satisfied" }
  // Auto-injects: "Ensure you state satisfaction"
  // ❌ Agent thinks: "I'll just say I'm satisfied"
}

// With silent mode:
{
  "instructions": "Write a report.",
  "rules": {
    "loop_until": "satisfied",
    "loop_until_silent": true
  }
  // No injection - agent writes honestly
  // ✅ Impartial validator judges actual quality
}
```

**How It Works**:
1. If `loop_until_silent: true` → skip auto-injection entirely
2. If `loop_until_prompt` is provided → use custom prompt
3. Otherwise → auto-generate from validator description in manifest
4. Validation prompt is injected **before** phase execution (proactive, not reactive)
5. Agent knows validation criteria upfront (unless silent), not just after failing

**Benefits**:
- ✅ No need to manually duplicate validator descriptions in instructions (auto mode)
- ✅ Reduces brittleness when changing validators (auto mode)
- ✅ Agent optimizes for validation criteria from the start (auto mode)
- ✅ Prevents gaming for subjective validators (silent mode)
- ✅ Fewer retry cycles needed (auto mode)
- ✅ Consistent with handoff auto-injection pattern
- ✅ Flexible - mix both modes in same cascade

**Example Cascades**:
- `examples/loop_until_auto_inject.json` - Auto-injection
- `examples/loop_until_silent_demo.json` - Silent mode for impartial validation

### 2.7. Turn Prompt - Guided Iteration for max_turns

When using `max_turns` for iterative refinement, you can provide custom guidance for subsequent turns instead of the default generic "Continue/Refine based on previous output."

**The Problem:** By default, `max_turns` just loops with a vague continuation prompt. The agent doesn't know what to focus on during iteration.

**The Solution:** `turn_prompt` gives the agent specific guidance for turns 1+ (after the initial turn).

**Configuration:**
```json
{
  "name": "solve_problem",
  "instructions": "Solve the coding problem: {{ input.problem }}",
  "tackle": ["run_code"],
  "rules": {
    "max_turns": 3,
    "turn_prompt": "Review your solution. Does it handle edge cases correctly? Test it and refine if needed."
  }
}
```

**How It Works:**
1. **Turn 0**: Uses the phase `instructions` (your main task)
2. **Turn 1+**: Uses `turn_prompt` for refinement guidance
3. **Jinja2 Support**: Full access to context variables like phase instructions

**Available Template Variables:**
```json
{
  "input": {...},           // Original cascade input
  "state": {...},           // Current session state
  "outputs": {...},         // Previous phase outputs
  "lineage": [...],         // Execution history
  "history": [...],         // Message history
  "turn": 2,               // Current turn number (1-indexed)
  "max_turns": 3           // Total turns configured
}
```

**Use Cases:**

**1. Code Generation with Self-Review:**
```json
{
  "rules": {
    "max_turns": 3,
    "turn_prompt": "Review your code:\n- Does it handle {{ input.edge_case }}?\n- Is it readable?\n- Are there any bugs?\nRefine if needed."
  }
}
```

**2. Content Writing with Quality Check:**
```json
{
  "rules": {
    "max_turns": 2,
    "turn_prompt": "Re-read your draft. Is it engaging? Any typos? Does it address the goal: {{ input.goal }}? Polish it."
  }
}
```

**3. Web Navigation with Goal Verification:**
```json
{
  "name": "find_pricing",
  "tackle": ["rabbitize_execute", "rabbitize_extract"],
  "rules": {
    "max_turns": 5,
    "turn_prompt": "Did you find: {{ input.goal }}? If not, try a different navigation strategy."
  }
}
```

**4. Dynamic Turn-Specific Prompts:**
```json
{
  "rules": {
    "max_turns": 3,
    "turn_prompt": "{% if turn == 1 %}First review: Check for major issues{% elif turn == 2 %}Second review: Polish and refine{% else %}Final review: Make it perfect{% endif %}"
  }
}
```

**5. Combo with Validation (Soft + Hard):**
```json
{
  "rules": {
    "max_turns": 3,
    "turn_prompt": "Check your grammar and clarity. Make improvements.",
    "loop_until": "grammar_check",  // Hard enforcement
    "max_attempts": 2
  }
}
```

**Comparison with Other Features:**

| Feature | Purpose | Enforcement | Cost |
|---------|---------|-------------|------|
| `turn_prompt` | Soft guidance for iteration | ❌ None (self-check) | ✅ Free |
| `loop_until` | Validation-based retry | ✅ Hard (validator) | 🟡 Medium |
| `output_schema` | Structure validation | ✅ Hard (schema) | ✅ Free |
| `wards` | Input/output validation | ✅ Configurable | 🟡 Medium |

**turn_prompt is "low-rent validation"** - lighter than full validation, better than blind iteration.

**Benefits:**
- ✅ Makes `max_turns` actually useful (not just generic looping)
- ✅ Zero cost (no extra LLM calls, just better prompting)
- ✅ Context-aware with Jinja2 templating
- ✅ Complements validation features (use both!)
- ✅ One line to add, immediate value

**Example Cascade:**
- `examples/turn_prompt_demo.json` - Demonstrates guided iteration with turn_prompt

### 2.8. Wards - Validation & Guardrails System

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

### 2.9. Prompt-Based vs Native Tool Calling

Windlass supports two modes for tool execution: **prompt-based (default, recommended)** and **native tool calling (opt-in)**.

#### Prompt-Based Tools (Default)

**Configuration:**
```json
{
  "name": "solve_problem",
  "instructions": "Solve this coding problem",
  "tackle": ["linux_shell", "run_code"],
  "use_native_tools": false  // Default
}
```

**How it works:**
1. Tool descriptions added to system prompt as text
2. Agent outputs JSON: `{"tool": "tool_name", "arguments": {"param": "value"}}`
3. Windlass parses JSON from response
4. Calls local Python function
5. Returns result as user message

**Benefits:**
- ✅ Works with ANY model (even those without native tool support)
- ✅ No provider-specific quirks (Gemini thought_signature, Anthropic formats, etc.)
- ✅ Simpler message format (just user/assistant)
- ✅ More transparent and debuggable
- ✅ Perfect for OpenRouter's multi-model approach

**Example agent sees:**
```markdown
## Available Tools

**linux_shell**
Execute a shell command in a sandboxed Ubuntu Docker container.
Parameters:
  - command (str) (required)

To use: {"tool": "linux_shell", "arguments": {"command": "ls /tmp"}}
```

#### Native Tool Calling (Opt-In)

**Configuration:**
```json
{
  "name": "solve_problem",
  "tackle": ["run_code"],
  "use_native_tools": true  // Opt-in
}
```

**How it works:**
1. Tool schemas passed to LLM provider API
2. Provider's native tool calling used
3. Provider returns structured tool calls
4. Windlass calls Python functions
5. Results sent as `role="tool"` messages

**Use when:**
- Model has excellent native tool support (GPT-4, Claude 3.5)
- You want maximum structure/reliability
- You're committed to specific providers

**Drawbacks:**
- ❌ Provider-specific quirks (Gemini requires thought_signature, etc.)
- ❌ Limited to models with tool support
- ❌ More complex message formats
- ❌ Against provider-agnostic philosophy

**Recommendation:** Use prompt-based (default) unless you have a specific reason for native.

### 2.10. Docker Sandboxed Execution

Code execution tools (`linux_shell`, `run_code`) use Docker for safe, isolated execution.

#### Setup

**1. Start Ubuntu container:**
```bash
docker run -d --name ubuntu-container ubuntu:latest sleep infinity

# Install Python and tools
docker exec ubuntu-container bash -c "apt update && apt install -y python3 python3-pip curl wget"
```

**2. Verify:**
```bash
docker exec ubuntu-container python3 -c "print('Ready!')"
```

#### linux_shell Tool

**Execute arbitrary shell commands in isolated container:**

```json
{"tool": "linux_shell", "arguments": {"command": "curl https://api.example.com"}}
```

**Available in container:**
- Python 3 (python3, pip)
- Network tools (curl, wget)
- File operations (cat, echo, ls, grep, sed, awk)
- Text processing
- Package management (apt, pip)

**Use cases:**
- API calls (curl)
- File processing
- Installing packages dynamically
- Running scripts
- Testing network connectivity

#### run_code Tool

**Execute Python code using Docker:**

Internally uses `linux_shell` with Python heredoc for clean multi-line execution.

```json
{"tool": "run_code", "arguments": {"code": "import math\nprint(math.pi)"}}
```

**Benefits over exec():**
- ✅ Safe (isolated container)
- ✅ Can't access host filesystem
- ✅ Can't break Windlass
- ✅ Full Python standard library
- ✅ Can install packages with pip

#### Security

**Container provides:**
- Filesystem isolation
- Process isolation
- Can't access host
- Configurable resource limits

**Best practices:**
```bash
# Set memory/CPU limits
docker update ubuntu-container --memory=512m --cpus=0.5

# Periodic restart for clean state
docker restart ubuntu-container
```

### 2.11. Rabbitize - Visual Browser Automation

Rabbitize transforms Playwright into a stateful REST API service with **visual feedback at every step**. Unlike traditional browser automation that uses fragile DOM selectors, Rabbitize uses visual coordinates and captures screenshots/video automatically.

**Key Features:**
- **Stateful sessions**: Browser state persists between commands (no need to re-navigate)
- **Visual coordinates**: Click at (x, y) instead of CSS selectors (more robust)
- **Automatic capture**: Every action generates before/after screenshots + video recording
- **Rich metadata**: DOM snapshots (markdown), element coordinates (JSON), performance metrics
- **Multi-modal integration**: Screenshots automatically flow through Windlass image protocol

#### Setup

**1. Install Rabbitize:**
```bash
npm install -g rabbitize
sudo npx playwright install-deps
```

**2. Start Rabbitize server:**
```bash
npx rabbitize  # Runs on localhost:3037
```

**Or enable auto-start** (optional):
```bash
export RABBITIZE_AUTO_START=true
# Windlass will start Rabbitize when needed (default: false)
```

**Optional configuration:**
```bash
export RABBITIZE_SERVER_URL=http://localhost:3037
export RABBITIZE_RUNS_DIR=./rabbitize-runs
```

#### Core Tools

**rabbitize_start(url, session_name=None)**
- Start browser session and navigate to URL
- Returns initial screenshot
- Session ID stored in Windlass state

**rabbitize_execute(command, include_metadata=False)**
- Execute browser action
- Command format: JSON array string
- Returns before/after screenshots
- Optionally includes DOM/metrics metadata

**Command Examples:**
```python
# CRITICAL: Move mouse FIRST, then click (no args!)
rabbitize_execute('[":move-mouse", ":to", 400, 300]')
rabbitize_execute('[":click"]')  # NO ARGS - clicks at current cursor position

# Type text
rabbitize_execute('[":type", "hello world"]')

# Scroll down
rabbitize_execute('[":scroll-wheel-down", 5]')

# Press key
rabbitize_execute('[":keypress", "Enter"]')

# Drag operation
rabbitize_execute('[":drag", ":from", 100, 200, ":to", 300, 400]')
```

**rabbitize_extract()**
- Extract page content as markdown
- Get DOM element coordinates
- Returns current screenshot

**rabbitize_close()**
- Close session, save video
- Returns metrics summary

**rabbitize_status()**
- Get current session info
- Show action count, metadata

#### Integration with Windlass

**Session Management:**
Session ID automatically tracked in Windlass Echo state. All tools use the same session across turns in a phase.

**Image Protocol:**
Screenshots automatically returned via `{"content": "...", "images": [path]}` protocol. Windlass saves them to `images/{session_id}/{phase}/` and injects into conversation as multi-modal messages. **Agent sees screenshots automatically!**

**Metadata Richness:**
Every action generates:
- `screenshots/before-*.jpg` + `screenshots/after-*.jpg`
- `dom_snapshots/*.md` - Page content as markdown
- `dom_coords/*.json` - Element positions for clicking
- `commands.json` - Audit trail
- `metrics.json` - Performance data
- `video.webm` - Full session recording

**With `include_metadata=True`, agent gets DOM content + coordinates for better decision-making.**

#### Usage Patterns

**Pattern 1: Simple Navigation**
```json
{
  "name": "check_website",
  "instructions": "Visit {{ input.url }} and describe what you see",
  "tackle": ["rabbitize_start", "rabbitize_extract", "rabbitize_close"]
}
```

**Pattern 2: Interactive Navigation with loop_until**
```json
{
  "name": "find_information",
  "instructions": "Navigate to find: {{ input.goal }}",
  "tackle": ["rabbitize_execute", "rabbitize_extract"],
  "rules": {
    "max_turns": 15,
    "loop_until": "satisfied",
    "loop_until_prompt": "Continue until you find: {{ input.goal }}"
  }
}
```

Agent takes actions → sees screenshots → adjusts strategy → repeats until goal achieved.

**Pattern 3: Form Filling with Validation**
```json
{
  "name": "fill_form",
  "instructions": "Fill form with {{ input.data }}",
  "tackle": ["rabbitize_execute", "rabbitize_extract"],
  "rules": {
    "loop_until": "web_goal_achieved",
    "max_attempts": 3
  }
}
```

Visual validation ensures form was filled correctly before submission.

**Pattern 4: Cascade Tool (web_navigator)**
```json
{
  "name": "research",
  "instructions": "Research pricing on {{ input.competitors }}",
  "tackle": ["web_navigator"],
  "rules": {"max_turns": 5}
}
```

`web_navigator` is a reusable cascade tool in `tackle/` that handles all navigation logic.

#### Rabbitize Files Structure

Each session creates:
```
rabbitize-runs/
  {session_id}/
    screenshots/
      before-click-001.jpg
      after-click-001.jpg
      before-type-002.jpg
      ...
    dom_snapshots/
      snapshot-001.md
      snapshot-002.md
    dom_coords/
      coords-001.json
    video.webm
    commands.json
    metrics.json
```

**Windlass automatically copies screenshots** to `images/{windlass_session_id}/{phase}/` for persistence and image protocol integration.

#### Advanced: Soundings for Navigation Strategies

Use soundings to try multiple navigation approaches:

```json
{
  "name": "find_pricing",
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the navigation that found pricing fastest"
  },
  "tackle": ["rabbitize_execute", "rabbitize_extract"]
}
```

Three parallel attempts → Evaluator picks winner based on screenshots/results → Only winner's path continues.

**Perfect for:**
- Exploring different search strategies
- Testing multiple form-filling approaches
- A/B testing navigation flows

#### Visual Loop-Until Feedback

The killer feature: **Visual validation loops**

1. Agent moves mouse: `rabbitize_execute('[":move-mouse", ":to", 400, 300]')`
2. Agent clicks: `rabbitize_execute('[":click"]')`
3. Gets screenshot back automatically (via image protocol)
4. Validator checks: "Did we reach the goal?"
5. If no → Agent sees the mistake in screenshot, adjusts strategy
6. If yes → Phase completes

**This is essentially giving Windlass agents eyes and hands for the web.**

All with full video recording + screenshot trail for debugging!

#### Example Cascades

- `examples/rabbitize_simple_demo.json` - Basic navigation + extraction
- `examples/rabbitize_navigation_demo.json` - Interactive navigation with loop_until
- `examples/rabbitize_form_fill_demo.json` - Form filling with validation
- `examples/rabbitize_research_assistant.json` - Multi-site research using web_navigator

#### Comparison: Rabbitize vs Traditional Automation

| Traditional (Selenium/Playwright) | Rabbitize + Windlass |
|----------------------------------|----------------------|
| DOM selectors (fragile) | Visual coordinates (robust) |
| Blind execution | Screenshot at every step |
| Stateless | Stateful sessions |
| Code-only | Declarative JSON cascades |
| No visual verification | Automatic multi-modal feedback |
| Manual debugging | Video + screenshot trails |

**Rabbitize gives agents visual perception** → loop_until provides iterative correction → Result: Robust web automation that can adapt and self-correct like a human.

### 2.12. Reforge - Iterative Refinement System

Reforge extends Soundings (Tree of Thought) with iterative refinement: after soundings complete and a winner is selected, the winner is refined through additional sounding loops with honing prompts.

**Combines Two Search Strategies:**
- **Breadth-first** (soundings): Initial exploration with N parallel attempts
- **Depth-first** (reforge): Progressive refinement of the winner

**Configuration** (`reforge` field in `SoundingsConfig`):
```json
{
  "soundings": {
    "factor": 3,
    "max_parallel": 3,
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

**Soundings Parameters:**
- `factor`: Number of parallel sounding attempts (default: 1)
- `max_parallel`: Maximum concurrent executions (default: 3) - controls thread pool size for cascade-level soundings and reforge
- `evaluator_instructions`: Instructions for the evaluator LLM to select winner
- `mutate`: Apply built-in mutation strategies (default: false)
- `mutation_mode`: How to mutate prompts: `"rewrite"` (default), `"augment"`, or `"approach"`
- `models`: Multi-model configuration for A/B testing across providers
- `validator`: Pre-evaluation validator to filter broken outputs
- `reforge`: Iterative refinement configuration (see below)

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
🔱 Soundings (Breadth) - runs in parallel (up to max_parallel workers)
  ├─ Attempt 1 ─┐
  ├─ Attempt 2 ─┼─ concurrent
  └─ Attempt 3 ─┘
     ↓
  ⚖️  Evaluate → Winner (waits for all to complete)
     ↓
🔨 Reforge Step 1 (Depth) - also runs in parallel
  ├─ Refine 1 (winner + honing + mutation_1) ─┐
  └─ Refine 2 (winner + honing + mutation_2) ─┘ concurrent
     ↓
  ⚖️  Evaluate → New Winner
     ↓
🔨 Reforge Step 2
  ├─ Refine 1 (prev winner + honing + mutation_3) ─┐
  └─ Refine 2 (prev winner + honing + mutation_4) ─┘ concurrent
     ↓
  ⚖️  Evaluate → Final Winner
     ↓
✅ Final polished output
```

**Parallel Execution:**
Cascade-level soundings and reforge refinements execute concurrently using `ThreadPoolExecutor` with `max_parallel` workers (default: 3). This significantly reduces wall-clock time for large sounding factors. Traces are pre-created sequentially for proper hierarchy, then executions run in parallel, and results are sorted by index before evaluation.

**Dream Mode:**
All intermediate sounding and reforge attempts are fully logged with `sounding_index`, `reforge_step`, and `is_winner` metadata but only the final winner's output continues in the main cascade flow.

**Use Cases:**
- **Code generation**: Broad algorithm exploration → polished implementation
- **Content creation**: Creative brainstorming → refined copy
- **Strategy development**: Multiple approaches → actionable plan
- **Image/chart refinement**: Initial design → accessibility-polished version

**Dual-Level Support:**
- **Phase-level reforge**: Refines single phase output
- **Cascade-level reforge**: Refines entire multi-phase workflow execution

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

### 2.13. Mutation System for Soundings

Soundings support automatic prompt mutation to explore different formulations and learn what works. Three mutation modes are available:

**Configuration** (`SoundingsConfig` fields):
```json
{
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the best response",
    "mutate": true,
    "mutation_mode": "rewrite",
    "mutations": null
  }
}
```

**Mutation Modes:**

1. **Rewrite** (default, recommended for learning):
   - Uses an LLM to completely rewrite the prompt while preserving intent
   - Discovers fundamentally different formulations you wouldn't think of
   - Each mutation template describes HOW to rewrite (e.g., "Rewrite to emphasize step-by-step reasoning")
   - Highest learning value - winner patterns can inform prompt optimization
   - Rewrite LLM calls are tracked in logs/costs like any other LLM call

2. **Augment** (good for testing known patterns):
   - Prepends text fragments to the original prompt
   - Good for A/B testing specific known patterns
   - Lower cost (no LLM call for mutation)
   - Less exploratory - only tests formulations you already know

3. **Approach** (Tree of Thought sampling):
   - Appends thinking strategy hints to the prompt
   - Changes HOW the agent thinks, not the prompt itself
   - Good for diversity sampling across reasoning styles
   - Low learning value - strategies are generic, not prompt-specific

**Built-in Mutation Templates:**

For **rewrite** mode (LLM instructions):
- "Rewrite this prompt to be more specific and detailed..."
- "Rewrite this prompt to emphasize step-by-step reasoning..."
- "Rewrite to focus on concrete examples..."
- "Rewrite to be more concise and direct..."
- Plus 4 more variations

For **augment** mode (prepended text):
- "Let's approach this step-by-step..."
- "Before answering, consider the key constraints..."
- "Think carefully about edge cases..."
- Plus 5 more patterns

For **approach** mode (appended strategy):
- "Approach this from a contrarian perspective..."
- "Focus on edge cases and failure modes..."
- "Think from first principles..."
- Plus 5 more strategies

**Custom Mutations:**

Provide your own templates via the `mutations` field:
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

**Logging:**

All mutation data is tracked in unified logs:
- `mutation_applied`: The actual mutation (rewritten prompt or augment text)
- `mutation_type`: "rewrite", "augment", "approach", or null for baseline
- `mutation_template`: For rewrite mode, the instruction used to generate the mutation

**Environment Variables:**
- `WINDLASS_REWRITE_MODEL`: Model used for prompt rewrites (default: `google/gemini-2.5-flash-lite`)

### 2.14. Multi-Model Soundings

Run soundings across different LLM providers to find the best cost/quality tradeoff. Three evaluation strategies available.

#### Phase 1: Simple Model Pool

Distribute soundings across multiple models with round-robin or random assignment.

**Array Format (round-robin):**
```json
{
  "soundings": {
    "factor": 6,
    "evaluator_instructions": "Pick the best response based on quality",
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

#### Phase 2: Cost-Aware Evaluation

Evaluator considers both quality and cost when selecting winner.

```json
{
  "soundings": {
    "factor": 3,
    "models": ["anthropic/claude-sonnet-4.5", "x-ai/grok-4.1-fast", "google/gemini-2.5-flash-lite"],
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

**How It Works:**
1. Soundings execute across different models
2. Costs retrieved from unified logs (or estimated if unavailable)
3. Evaluator prompt includes cost context if `show_costs_to_evaluator: true`
4. Quality/cost tradeoff influences winner selection

#### Phase 3: Pareto Frontier Analysis

Compute non-dominated solutions and select winner based on policy.

```json
{
  "soundings": {
    "factor": 6,
    "models": {
      "anthropic/claude-sonnet-4.5": {"factor": 2},
      "x-ai/grok-4.1-fast": {"factor": 2},
      "google/gemini-2.5-flash-lite": {"factor": 2}
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
- `interactive`: Present frontier to user for selection (future)

**How It Works:**
1. All soundings execute and get quality scores from evaluator
2. Pareto frontier computed (non-dominated solutions)
3. Winner selected based on policy
4. Frontier data logged to `graphs/pareto_{session_id}.json` for visualization

**Pareto Output Example:**
```json
{
  "frontier": [
    {"sounding_index": 1, "model": "anthropic/claude-sonnet-4.5", "quality": 98.0, "cost": 0.006},
    {"sounding_index": 3, "model": "x-ai/grok-4.1-fast", "quality": 92.0, "cost": 0.0003},
    {"sounding_index": 5, "model": "google/gemini-2.5-flash-lite", "quality": 85.0, "cost": 0.0002, "is_winner": true}
  ],
  "dominated": [
    {"sounding_index": 0, "dominated_by": 1, "quality": 96.0, "cost": 0.0062}
  ]
}
```

**Example Cascades:**
- `examples/multi_model_simple.json` - Phase 1: Round-robin across models
- `examples/multi_model_per_model_factors.json` - Phase 1: Per-model factor configuration
- `examples/multi_model_cost_aware.json` - Phase 2: Cost-aware evaluation
- `examples/multi_model_pareto.json` - Phase 3: Pareto frontier analysis

### 2.15. Pre-Evaluation Validator for Soundings

Filter soundings before they reach the evaluator. Useful for code execution (only evaluate code that runs) or format validation.

**Configuration:**
```json
{
  "soundings": {
    "factor": 5,
    "evaluator_instructions": "Pick the best solution",
    "validator": "code_execution_validator"
  }
}
```

**How It Works:**
1. All soundings execute normally
2. Validator runs on each sounding result
3. Only valid soundings go to evaluator
4. Saves evaluator LLM calls on broken outputs
5. If ALL fail validation, falls back to evaluating all (with validation info visible)

**Use Cases:**

**1. Code Execution Validation:**
```json
{
  "name": "solve_problem",
  "instructions": "Solve this coding problem and run your solution",
  "tackle": ["run_code"],
  "soundings": {
    "factor": 3,
    "evaluator_instructions": "Pick the best working solution",
    "validator": "code_execution_validator"
  }
}
```
Only solutions that execute without errors get evaluated.

**2. Format Validation:**
```json
{
  "soundings": {
    "factor": 5,
    "validator": "json_format_validator",
    "evaluator_instructions": "Pick the most complete JSON response"
  }
}
```
Only properly formatted outputs get evaluated.

**3. Combined with Multi-Model:**
```json
{
  "soundings": {
    "factor": 6,
    "models": ["anthropic/claude-sonnet-4.5", "google/gemini-2.5-flash-lite"],
    "validator": "code_execution_validator",
    "pareto_frontier": {"enabled": true, "policy": "balanced"}
  }
}
```
Pre-filter across multiple models, then compute Pareto frontier on valid results.

**Validator Protocol:**
Validators must return `{"valid": true/false, "reason": "..."}`. Can be:
- Python function registered with `register_tackle()`
- Cascade tool in `tackle/` directory

**Metadata Logging:**
Each sounding's validation result is logged:
```json
{
  "sounding_index": 0,
  "validation": {
    "valid": false,
    "reason": "Code execution error: NameError..."
  }
}
```

**Benefits:**
- Saves evaluator LLM calls on obviously broken outputs
- Cleaner evaluation (evaluator only sees working solutions)
- Works with all sounding features (multi-model, cost-aware, Pareto)

**Example Cascade:**
- `examples/soundings_with_validator.json` - Code generation with execution validation

### 2.16. Context System - Selective by Default

**Windlass uses a two-level context model:** selective between phases, automatic snowball within phases.

**The Philosophy**: Phases are encapsulation boundaries. Within a phase, context flows naturally. Between phases, context is explicitly configured.

#### Two-Level Context Model

```
Cascade
├── Phase A (clean slate - no context config)
│   ├── Turn 0 ─────────────────┐
│   ├── Turn 1 (sees turn 0) ───┤ ← Automatic snowball WITHIN phase
│   └── Turn 2 (sees 0-1) ──────┘
│
├── Phase B (context: {from: ["previous"]})  ← EXPLICIT declaration BETWEEN phases
│   ├── Turn 0 (sees Phase A output) ─┐
│   └── Turn 1 (sees turn 0) ─────────┘ ← Automatic snowball continues
│
└── Phase C (context: {from: ["all"]})
    └── ... sees everything from A and B
```

| Boundary | Context Behavior | Configuration |
|----------|------------------|---------------|
| **Between phases** | Selective by default | `context: {from: [...]}` - explicit declaration |
| **Within a phase** | Automatic snowball | None needed - always accumulates |

**Why this design?**

1. **Phases encapsulate complexity**: All the messy iteration, tool calls, and refinement happen INSIDE a phase. Only the output matters to other phases.

2. **Iterations need context**: When you set `max_turns: 5`, turn 3 MUST see turns 1-2 to refine. This happens automatically.

3. **Phases need control**: You don't want Phase D accidentally drowning in 50K tokens from verbose debugging in Phase B. Explicit context declarations prevent this.

**What accumulates within a phase (automatic):**
- All turn outputs (user inputs, assistant responses)
- All tool calls and results
- All image injections
- All retry messages (when `loop_until` fails)
- All validation feedback

**What crosses phase boundaries (only when declared):**
- Final phase output (`include: ["output"]`)
- Full message history (`include: ["messages"]`)
- Generated images (`include: ["images"]`)
- State variables (`include: ["state"]`)

#### Inter-Phase Context Patterns

| Pattern | Configuration | What Phase Sees |
|---------|---------------|-----------------|
| **Clean slate** (default) | No `context` field | Nothing from prior phases |
| **Previous only** | `context: {from: ["previous"]}` | Most recently completed phase |
| **All phases** | `context: {from: ["all"]}` | Everything (explicit snowball) |
| **Specific phases** | `context: {from: ["phase_a", "phase_c"]}` | Only named phases |

```
No config:    A runs → B runs fresh → C runs fresh → D runs fresh
Previous:     A runs → B sees A → C sees B → D sees C
All:          A runs → B sees A → C sees A,B → D sees A,B,C
```

#### Configuration

**Phase with no context config = clean slate:**
```json
{
  "name": "fresh_analysis",
  "instructions": "Analyze this data independently"
}
```

**Phase that needs previous phase:**
```json
{
  "name": "build_on_previous",
  "instructions": "Continue from where we left off",
  "context": {
    "from": ["previous"]
  }
}
```

**Phase that needs all prior context (explicit snowball):**
```json
{
  "name": "final_summary",
  "instructions": "Summarize everything we've done",
  "context": {
    "from": ["all"]
  }
}
```

**Detailed Configuration with artifact filtering:**
```json
{
  "name": "final_analysis",
  "context": {
    "from": [
      "generate_chart",
      {"phase": "validate_chart", "include": ["output"]},
      {"phase": "research", "include": ["messages"], "messages_filter": "last_turn"}
    ],
    "include_input": true
  }
}
```

**Use exclude to skip phases from "all":**
```json
{
  "name": "summary",
  "context": {
    "from": ["all"],
    "exclude": ["verbose_debug", "intermediate_step"]
  }
}
```

#### Context Source Options

```python
class ContextSourceConfig:
    phase: str                              # Source phase name (or keyword: "first", "previous")
    include: ["images", "output", "messages", "state"]  # What to include (default: images, output)
    images_filter: "all" | "last" | "last_n"           # Image filtering
    images_count: int = 1                              # For last_n mode
    messages_filter: "all" | "assistant_only" | "last_turn"  # Message filtering
    as_role: "user" | "system" = "user"               # Role for injected messages
```

#### Phase Reference Keywords (Sugar)

Instead of hardcoding phase names, use keywords that resolve at runtime:

| Keyword | Resolves To | Use Case |
|---------|-------------|----------|
| `"all"` | All completed phases | Final summaries, explicit snowball |
| `"first"` | First phase that executed (`lineage[0]`) | Original problem statement |
| `"previous"` / `"prev"` | Most recently completed phase (`lineage[-1]`) | What just happened |

**Examples:**
```json
// Hardcoded phase names (works but fragile)
{"context": {"from": ["gather_requirements", "review"]}}

// With sugar (cleaner, survives renames)
{"context": {"from": ["first", "previous"]}}

// All phases with exclusions
{"context": {"from": ["all"], "exclude": ["debug_phase"]}}
```

**Resolution Logic** (in `_resolve_phase_reference()`):
- `"all"` returns list of all completed phase names from lineage
- `"first"` returns first phase name, or None if lineage empty
- `"previous"` returns last phase name, or None if lineage empty
- Case-insensitive: `"First"`, `"FIRST"`, `"first"` all work
- Non-keywords pass through as literal phase names

**Implementation**: `runner.py:_resolve_phase_reference()` resolves keywords to actual phase names before context building.

#### What Gets Injected

| Include | Source | Injected As |
|---------|--------|-------------|
| `images` | `images/{session}/{phase}/` | Multimodal user message with base64 images |
| `output` | `echo.lineage[phase].output` | User message with final assistant response |
| `messages` | `echo.history` filtered by phase | Full message sequence with original roles |
| `state` | `echo.state` keys set during phase | Structured JSON in user message |

#### Example Use Cases

**1. Chart Analysis Pipeline (Token Efficiency):**
```json
{
  "phases": [
    {"name": "generate_chart", "instructions": "Create a chart..."},
    {"name": "validate_chart", "context": {"from": ["generate_chart"]}},
    {"name": "process_data", "context": {"from": []}},
    {"name": "final_report", "context": {
      "from": [
        {"phase": "generate_chart", "include": ["images"]},
        {"phase": "validate_chart", "include": ["output"]}
      ]
    }}
  ]
}
```
Phases 3-4 don't carry ~10K tokens of base64 image data.

**2. Research with Conversation Replay:**
```json
{
  "name": "synthesize",
  "instructions": "Create final report with access to full reasoning.",
  "context": {
    "from": [
      {"phase": "initial_research", "include": ["messages"]},
      {"phase": "fact_check", "include": ["messages"]}
    ]
  }
}
```
The synthesize phase sees full conversation history from both prior phases.

**3. Compare Versions (all phases with selection):**
```json
{
  "name": "compare",
  "instructions": "Compare v1 and v2 side by side.",
  "context": {
    "from": [
      {"phase": "generate_v1", "include": ["images"]},
      {"phase": "generate_v2", "include": ["images"]}
    ]
  }
}
```
The compare phase sees images from both versions - nothing else.

**4. Clean Slate with Input Only:**
```json
{
  "name": "fresh_perspective",
  "instructions": "Approach the problem from scratch.",
  "context": {"from": [], "include_input": true}
}
```
Phase sees ONLY the original cascade input - no prior phase context.

#### Migration Guide

**Existing Cascades (Legacy Snowball):**
Old cascades without context configs now get clean slate per phase. Add explicit context to restore prior behavior:

```json
// Before (implicit snowball - NO LONGER WORKS)
{"name": "phase_c", "instructions": "Analyze..."}

// After (explicit snowball)
{"name": "phase_c", "instructions": "Analyze...",
 "context": {"from": ["all"]}}

// Or chain from previous (most common pattern)
{"name": "phase_c", "instructions": "Analyze...",
 "context": {"from": ["previous"]}}
```

#### Logging & Observability

All context injection events are logged with metadata:
- `node_type: "context_injection"` - For context messages
- `metadata.selective_context: true`
- `metadata.context_from: [...]` - Which phases were requested

Query injection events:
```bash
windlass sql "SELECT * FROM all_data WHERE node_type = 'context_injection'"
```

**Example Cascades:**
- `examples/context_selective_demo.json` - Selective context demonstration
- `examples/context_messages_demo.json` - Message injection with full conversation replay
- `examples/context_sugar_demo.json` - Context keywords (first, previous, all)

### 2.17. Generative UI - Rich Human-in-the-Loop Interfaces

The Generative UI system enables agents to create rich, contextually-appropriate interfaces for human input using the `ask_human_custom` tool.

#### Core Concept

Instead of simple text prompts, agents can specify:
- **Images**: Display charts, screenshots, or generated visuals
- **Data Tables**: Show structured data with sorting and selection
- **Comparison Views**: Side-by-side option comparisons with pros/cons
- **Card Grids**: Rich option cards with images and metadata
- **Multi-Column Layouts**: Organized content in columns or sidebars

The system uses a two-phase generation approach:
1. **Intent Analysis**: Determine UI complexity (low/medium/high)
2. **UI Spec Generation**: Template-based for simple cases, LLM-powered for complex

#### ask_human_custom Tool

```python
ask_human_custom(
    question: str,           # The question to ask
    context: str = None,     # Background context for the human
    images: list = None,     # Image file paths to display
    data: dict = None,       # Structured data for tables
    options: list = None,    # Options for selection/comparison
    ui_hint: str = None,     # UI type hint: "simple", "image_review", "comparison", etc.
    layout_hint: str = None, # Layout hint: "vertical", "sidebar", "grid"
    auto_detect: bool = True # Auto-detect content from Echo context
)
```

#### Section Types

| Type | Description | Use Case |
|------|-------------|----------|
| `markdown` | Rich text content | Context, explanations |
| `input` | Text input field | Free-form responses |
| `select` | Dropdown or radio | Single choice |
| `multi_select` | Checkboxes | Multiple selections |
| `image` | Image display with lightbox | Visual content review |
| `data_table` | Interactive table | Data review, row selection |
| `code` | Syntax-highlighted code | Code review with diff |
| `card_grid` | Rich option cards | Visual option selection |
| `comparison` | Side-by-side comparison | A/B decisions with pros/cons |
| `accordion` | Collapsible sections | Detailed content organization |
| `tabs` | Tabbed content | Categorized information |

#### Layout Types

| Layout | Description |
|--------|-------------|
| `vertical` | Simple stacked sections (default) |
| `horizontal` | Side-by-side sections |
| `two-column` | Two equal columns |
| `three-column` | Three equal columns |
| `grid` | CSS Grid layout |
| `sidebar-left` | Sidebar on left, main content on right |
| `sidebar-right` | Main content on left, sidebar on right |

#### Usage Examples

**Image Review:**
```json
{
  "tool": "ask_human_custom",
  "arguments": {
    "question": "Does this chart accurately represent the data?",
    "images": ["/path/to/chart.png"],
    "options": [
      {"id": "approve", "label": "Looks good"},
      {"id": "revise", "label": "Needs changes"}
    ],
    "ui_hint": "image_review"
  }
}
```

**Data Table Review:**
```json
{
  "tool": "ask_human_custom",
  "arguments": {
    "question": "Select the rows that need attention",
    "data": {
      "columns": ["Task", "Status", "Priority"],
      "rows": [
        ["Task A", "Pending", "High"],
        ["Task B", "In Progress", "Medium"]
      ]
    },
    "ui_hint": "data_review"
  }
}
```

**Comparison View:**
```json
{
  "tool": "ask_human_custom",
  "arguments": {
    "question": "Which approach do you prefer?",
    "options": [
      {
        "id": "option_a",
        "title": "Conservative",
        "description": "Lower risk approach",
        "pros": ["Safe", "Predictable"],
        "cons": ["Slower"]
      },
      {
        "id": "option_b",
        "title": "Aggressive",
        "description": "Higher risk approach",
        "pros": ["Fast", "Innovative"],
        "cons": ["Risky"]
      }
    ],
    "ui_hint": "comparison"
  }
}
```

#### Auto-Detection

When `auto_detect=True` (default), the system automatically:
- Extracts recent images from the Echo context
- Parses JSON data from tool results
- Infers appropriate UI layout based on content

#### Implementation Files

- `windlass/generative_ui_schema.py` - Pydantic models for UI specs
- `windlass/generative_ui.py` - Intent analyzer and spec generator
- `windlass/eddies/human.py` - `ask_human_custom` tool implementation
- `extras/ui/frontend/src/components/sections/` - React section components
- `extras/ui/frontend/src/components/layouts/` - React layout components
- `extras/ui/frontend/src/components/DynamicUI.js` - Main rendering component

**Example Cascades:**
- `examples/generative_ui_demo.json` - Basic generative UI demonstration
- `examples/generative_ui_showcase.json` - All section types and layouts

### 3. Execution Flow (Runner)
The core execution engine is in `windlass/runner.py` (`WindlassRunner` class).

**Key Execution Concepts**:
- **Context Snowballing**: Full conversation history (user inputs, agent thoughts, tool results) accumulates across phases. An agent in Phase 3 has visibility into Phase 1's reasoning.
- **State Persistence**: The `Echo` object (`echo.py`) maintains:
  - `state`: Persistent key-value store (set via `set_state` tool)
  - `history`: Full message log with trace IDs
  - `lineage`: Phase-level output summary
  - `errors`: Track errors that occurred
  - **Auto-logging**: Echo automatically calls `log_unified()` when `add_history()` is invoked, ensuring all messages are logged to the unified system. The entry dict is **copied** to prevent trace metadata from polluting LLM API messages.
- **Sub-Cascade Context**:
  - `context_in: true`: Parent's `state` is flattened into child's `input`
  - `context_out: true`: Child's final `state` is merged back into parent's `state`
- **Async Cascades**: Spawned in background threads with linked trace IDs for observability
- **Soundings (Tree of Thought)**:
  - **Phase-level**: Run a single phase N times, evaluator picks best, only winner continues
  - **Cascade-level**: Run entire multi-phase workflow N times, each gets fresh Echo with unique session ID, evaluator picks best complete execution, only winner's state/history/lineage merged into main cascade
  - All attempts fully logged with `sounding_index` and `is_winner` metadata for querying

### 4. Multi-Modal Vision Protocol & Image Handling

Images are **first-class citizens** in Windlass with automatic persistence and reforge integration.

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
2. Images extracted and re-encoded for new API requests
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

**Unified Logging System (chDB/ClickHouse):**

All logging goes through a unified mega-table system (`unified_logs.py`) with **automatic scaling** from embedded to distributed:

- **Development Mode (chDB)**: Embedded ClickHouse reads Parquet files in `./data/` - zero setup, pure Python
- **Production Mode (ClickHouse Server)**: Set 2 env vars → automatic database/table creation → writes directly to ClickHouse
- **Query Compatibility**: Same query API works with both backends - seamless migration
- **Hybrid Mode**: Can read old Parquet files + new ClickHouse data simultaneously

**Logging Features:**
- **Buffered Writes**: 100 messages OR 10 seconds (whichever first)
- **Non-Blocking Cost Tracking**: Background worker fetches costs after ~3 seconds (OpenRouter delay)
- **Automatic Setup**: Database and table created automatically on first run (ClickHouse server mode)
- **Backward Compatibility**: Old `logs.py` is now a shim that routes to unified system
- **Mermaid Graphs** (`visualizer.py`): Real-time flowchart generation showing phase transitions, soundings, reforges
- **Trace Hierarchy** (`tracing.py`): `TraceNode` class creates parent-child relationships for nested cascades

**Switching to ClickHouse Server (2 environment variables):**
```bash
# Start ClickHouse server
docker run -d --name clickhouse-server \
  -p 9000:9000 -p 8123:8123 \
  clickhouse/clickhouse-server

# Enable server mode (database and table created automatically!)
export WINDLASS_USE_CLICKHOUSE_SERVER=true
export WINDLASS_CLICKHOUSE_HOST=localhost

# Run windlass - that's it!
windlass examples/simple_flow.json --input '{"data": "test"}'
```

See `CLICKHOUSE_SETUP.md` for complete guide.

**Unified Log Schema (34+ fields per message):**

| Category | Fields |
|----------|--------|
| **Core IDs** | `timestamp`, `timestamp_iso`, `session_id`, `trace_id`, `parent_id`, `parent_session_id`, `parent_message_id` |
| **Classification** | `node_type`, `role`, `depth` |
| **Execution Context** | `sounding_index`, `is_winner`, `reforge_step`, `attempt_number`, `turn_number` |
| **Cascade Context** | `cascade_id`, `cascade_file`, `cascade_json`, `phase_name`, `phase_json` |
| **LLM Provider** | `model`, `request_id`, `provider` |
| **Performance** | `duration_ms`, `tokens_in`, `tokens_out`, `total_tokens`, `cost` |
| **Content (JSON)** | `content_json`, `full_request_json`, `full_response_json`, `tool_calls_json` |
| **Images** | `images_json`, `has_images`, `has_base64` |
| **Metadata** | `metadata_json` |

**Query Helpers (Works with both chDB and ClickHouse server):**
```python
from windlass.unified_logs import query_unified, get_session_messages, get_cascade_costs

# Query unified logs (automatically uses chDB or ClickHouse server)
df = query_unified("session_id = 'session_123'")

# Get all messages for a session
messages = get_session_messages("session_123")

# Get cost breakdown by phase
costs = get_cascade_costs("blog_flow")

# Analyze soundings performance
from windlass.unified_logs import get_soundings_analysis
soundings = get_soundings_analysis("session_123", "generate")

# Advanced: Use ClickHouse JSON functions (server mode)
from windlass.unified_logs import query_unified
df = query_unified("""
    JSONExtractString(tool_calls_json, '0', 'tool') = 'route_to'
    AND cost > 0.01
""")
```

**Real-Time Event System:**

Windlass includes a built-in event bus for real-time cascade updates via Server-Sent Events (SSE).

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
            'data': {'label': 'Generate', 'event_count': 45}
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

### 6. LLM Integration
The `Agent` class (`agent.py`) wraps LiteLLM for flexible provider support.
- Default: OpenRouter with configurable base URL and API key
- Messages are sanitized to remove `tool_calls: None` fields
- Response includes request ID for cost tracking
- Automatic retry logic on API failures (2 retries)

### 7. Debug UI

Windlass includes a development debug UI for real-time cascade monitoring located in `extras/debug_ui/`.

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

Set environment variables to point to your Windlass data directories:

```bash
export WINDLASS_LOG_DIR=/path/to/logs
export WINDLASS_GRAPH_DIR=/path/to/graphs
export WINDLASS_STATE_DIR=/path/to/states
export WINDLASS_IMAGE_DIR=/path/to/images
```

**API Endpoints:**

```
GET  /api/cascades                    # List all cascade sessions
GET  /api/logs/<session_id>          # Get logs for session
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
- Backend: Flask + chDB/ClickHouse + SSE
- Frontend: React + Mermaid.js
- Real-time: EventSource API

See `extras/debug_ui/VISUALIZATION_GUIDE.md` for React Flow integration and advanced visualization patterns.

## Module Structure

```
windlass/
├── __init__.py          # Package entry point, tool registration
├── cascade.py           # Pydantic models for Cascade DSL
├── runner.py            # WindlassRunner execution engine
├── agent.py             # LLM wrapper (LiteLLM integration)
├── echo.py              # Echo class (state/history container) + auto-logging
├── tackle.py            # ToolRegistry for tool management
├── tackle_manifest.py   # Dynamic tool discovery for Quartermaster
├── config.py            # Global configuration management (WINDLASS_ROOT-based)
├── schema.py            # ClickHouse table DDL definitions
├── db_adapter.py        # Database adapter (chDB + ClickHouse server) with auto-setup
├── unified_logs.py      # Unified mega-table logging (chDB/ClickHouse)
├── logs.py              # Backward compatibility shim → routes to unified_logs.py
├── visualizer.py        # Mermaid graph generation (with soundings/reforge support)
├── tracing.py           # TraceNode hierarchy for observability
├── events.py            # Event bus for real-time updates
├── event_hooks.py       # EventPublishingHooks for lifecycle events
├── utils.py             # get_tool_schema, image encoding/decoding, extraction
├── cli.py               # Command-line interface
├── prompts.py           # Jinja2 prompt rendering
├── state.py             # Session state management
├── cost.py              # Cost tracking (legacy async, now mostly blocking in agent.py)
├── generative_ui_schema.py  # Pydantic models for Generative UI DSL
├── generative_ui.py     # Intent analyzer and UI spec generator
└── eddies/              # Built-in tools
    ├── base.py          # Eddy wrapper (retry logic)
    ├── sql.py           # DuckDB SQL execution (smart_sql_run)
    ├── extras.py        # linux_shell, run_code, take_screenshot
    ├── human.py         # ask_human, ask_human_custom HITL tools
    ├── state_tools.py   # set_state tool
    ├── system.py        # spawn_cascade tool
    └── chart.py         # create_chart tool

extras/
├── debug_ui/            # Development debug UI
│   ├── start_backend.sh # Backend startup script
│   ├── backend/
│   │   ├── app.py       # Flask API server
│   │   ├── checkpoint_api.py  # Checkpoint endpoints with image URL resolution
│   │   └── execution_tree.py  # Execution tree builder for React Flow
│   └── frontend/
│       └── src/
│           ├── App.js           # Main UI with SSE integration
│           ├── components/
│           │   ├── CascadeList.js
│           │   ├── MermaidViewer.js
│           │   └── LogsPanel.js
│           └── VISUALIZATION_GUIDE.md  # React Flow patterns
└── ui/                  # Production UI
    └── frontend/src/components/
        ├── DynamicUI.js       # Main generative UI renderer
        ├── sections/          # Section components (ImageSection, DataTableSection, etc.)
        └── layouts/           # Layout components (TwoColumnLayout, GridLayout, etc.)
```

## Important Implementation Details

### Jinja2 Templating
Phase instructions support Jinja2 syntax:
- `{{ input.variable_name }}`: Access initial cascade input
- `{{ state.variable_name }}`: Access persistent session state
- `{{ outputs.phase_name }}`: Access previous phase outputs by name
- `{{ lineage }}`: Full execution lineage array
- `{{ history }}`: Message history
- `{{ input | default('value') }}`: Default filters supported
- Rendered in `prompts.py:render_instruction()`

### Session and Trace IDs
- **Session ID**: Identifies a single cascade execution and its lineage (generated in CLI if not provided)
- **Trace ID**: Unique identifier for each node in the execution tree (cascade, phase, or tool)
- Both are threaded through logging and visualization for full traceability

**Session ID Namespacing:**
```
Main cascade:           session_123
Cascade-level sounding: session_123_sounding_0, session_123_sounding_1, ...
Phase-level sounding:   Uses main session_id with sounding_index metadata
Reforge iterations:     session_123_reforge1_0, session_123_reforge1_1, session_123_reforge2_0, ...
Sub-cascades:           Linked via parent_session_id field
```

This namespacing ensures image/state isolation between parallel sounding attempts and reforge iterations.

### Context Tokens
The runner uses `contextvars` (via `state_tools.py:set_current_session_id()` and `tracing.py:set_current_trace()`) to make session/trace data available to tools without explicit parameter passing.

### Hooks System & Real-Time Events
`WindlassRunner` accepts a `hooks` parameter (`WindlassHooks` class) allowing injection of custom logic at key lifecycle points:

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
- **soundings_rewrite_flow.json**: Soundings with LLM prompt rewriting (mutation_mode: rewrite)
- **soundings_augment_flow.json**: Soundings with prepended patterns (mutation_mode: augment)
- **soundings_approach_flow.json**: Soundings with thinking strategies (mutation_mode: approach)
- **soundings_code_flow.json**: Phase-level soundings applied to code generation with multiple algorithmic approaches
- **cascade_soundings_test.json**: Cascade-level Tree of Thought - runs entire multi-phase workflow N times and picks best execution
- **manifest_flow.json**: Quartermaster auto-selects tools based on task description
- **manifest_complex_flow.json**: Multi-phase workflow with full context manifest selection
- **ward_blocking_flow.json**: Wards in blocking mode for critical validations
- **ward_retry_flow.json**: Wards in retry mode for automatic quality improvement
- **ward_comprehensive_flow.json**: All three ward modes (blocking, retry, advisory) together
- **loop_until_auto_inject.json**: Automatic validation goal injection with loop_until (both auto-generated and custom prompts)
- **loop_until_silent_demo.json**: Silent mode for impartial validation (prevents gaming for subjective validators)
- **reforge_dashboard_metrics.json**: Phase-level reforge with mutation for metrics refinement
- **reforge_cascade_strategy.json**: Cascade-level reforge for complete workflow refinement
- **reforge_meta_optimizer.json**: META cascade that optimizes other cascade JSONs
- **reforge_image_chart.json**: Chart refinement with image context through reforge
- **reforge_feedback_chart.json**: Feedback loops with manual image injection and visual analysis

## Testing System (Snapshot Testing)

Windlass includes a powerful snapshot testing system that captures real cascade executions and replays them as regression tests **without calling LLMs**.

### How It Works

**1. Capture Phase:**
Run a cascade normally (uses real LLM):
```bash
windlass examples/routing_flow.json --input '{"text": "I love it!"}' --session test_001
```

**2. Verify Phase:**
Check that it did what you expected:
- Review output in terminal
- Check logs: Query `data/*.parquet` using DuckDB (logs are in `data/` not `logs/`)
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

**Philosophy:** You're testing that Windlass's plumbing works correctly, not that the LLM is smart. If the framework:
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

## Training Data & Evaluation Dataset Generation

**Windlass automatically captures rich training data from every execution.**

### Why ClickHouse is Perfect for Training Data

With millions of execution traces, you need serious query power. ClickHouse gives you:

**1. Scale Without Pain:**
- ✅ Handles petabytes of training data (Windlass captures EVERYTHING)
- ✅ Query millions of cascade executions in seconds
- ✅ Automatic partitioning by time (easy data retention)
- ✅ Distributed queries across multiple nodes

**2. Rich JSON Querying:**
```sql
-- Extract tool usage patterns for fine-tuning
SELECT
    JSONExtractString(tool_calls_json, '0', 'tool') as tool_used,
    JSONExtractString(tool_calls_json, '0', 'arguments') as args,
    cost,
    is_winner
FROM unified_logs
WHERE sounding_index IS NOT NULL
  AND JSONHas(tool_calls_json, '0', 'tool')
ORDER BY timestamp DESC
LIMIT 10000
```

**3. Training Dataset Queries:**
```python
from windlass.unified_logs import query_unified

# Get all winning soundings for fine-tuning data
winners = query_unified("""
    is_winner = true
    AND sounding_index IS NOT NULL
    AND cost > 0
""")

# Extract successful tool sequences
tool_sequences = query_unified("""
    phase_name = 'solve_problem'
    AND JSONExtractString(tool_calls_json, '0', 'tool') IN ('run_code', 'linux_shell')
    AND content_json NOT LIKE '%error%'
""")

# Get evaluation pairs (soundings + winner for ranking model)
eval_pairs = query_unified("""
    session_id IN (
        SELECT DISTINCT session_id
        FROM unified_logs
        WHERE sounding_index IS NOT NULL
    )
    ORDER BY session_id, sounding_index
""")
```

**4. Automatic Data Collection:**

Every cascade execution logs:
- ✅ Full conversation history (prompts + responses)
- ✅ Tool calls and results
- ✅ Sounding attempts (winners + losers for preference learning)
- ✅ Reforge iterations (progressive refinement traces)
- ✅ Cost and token counts (for efficiency training)
- ✅ Ward validation results (quality signals)
- ✅ Phase routing decisions (multi-step reasoning)

**5. Export Training Data:**
```python
# Export to JSONL for fine-tuning
import json
from windlass.unified_logs import query_unified

df = query_unified("is_winner = true AND role = 'assistant'")

with open('training_data.jsonl', 'w') as f:
    for _, row in df.iterrows():
        f.write(json.dumps({
            'prompt': json.loads(row['full_request_json']),
            'completion': json.loads(row['content_json']),
            'cost': row['cost'],
            'tokens': row['total_tokens']
        }) + '\n')
```

**6. Evaluation Dataset Generation:**
```python
# Create evaluation sets from real production traces
from windlass.unified_logs import query_unified

# Get diverse test cases
eval_set = query_unified("""
    node_type = 'phase_start'
    AND phase_name IN ('generate', 'analyze', 'solve_problem')
    ORDER BY RANDOM()
    LIMIT 1000
""")

# Export with ground truth (from actual execution)
eval_set.to_json('eval_dataset.jsonl', orient='records', lines=True)
```

**Migration Impact for Training Workflows:**

| Volume | Mode | Query Time | Cost |
|--------|------|------------|------|
| <100K rows | chDB (embedded) | Seconds | $0 |
| 100K-10M rows | chDB (embedded) | Minutes | $0 |
| 10M-1B rows | ClickHouse server | Seconds | ~$100/month |
| 1B+ rows | ClickHouse cluster | Seconds | ~$500/month |

**Just set 2 env vars when you outgrow embedded mode. Code stays the same.**

See `CLICKHOUSE_SETUP.md` for migration guide.

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
