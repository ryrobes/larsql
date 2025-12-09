# Tools Reference

This document covers the Windlass tool system ("Tackle") in detail.

## Tool System Overview

**Two Types of Tackle:**

1. **Python Functions**: Fast, direct execution. Registered in tackle registry (`tackle.py`)
2. **Cascade Tools**: Complex multi-step operations as declarative cascades with `inputs_schema`

The framework automatically extracts function signatures using `inspect` and converts them to OpenAI-compatible JSON schemas via `utils.py:get_tool_schema()`.

## Built-in Tools

Registered in `windlass/__init__.py`:

| Tool | Location | Description |
|------|----------|-------------|
| `linux_shell` | `eddies/extras.py` | Execute shell commands in sandboxed Ubuntu Docker container |
| `run_code` | `eddies/extras.py` | Execute Python code in Docker container |
| `smart_sql_run` | `eddies/sql.py` | Execute DuckDB SQL queries on datasets |
| `take_screenshot` | `eddies/extras.py` | Capture web pages using Playwright |
| `ask_human` | `eddies/human.py` | Human-in-the-loop input |
| `ask_human_custom` | `eddies/human.py` | Generative UI for rich human-in-the-loop |
| `set_state` | `eddies/state_tools.py` | Persist variables to session state |
| `spawn_cascade` | `eddies/system.py` | Programmatically launch cascades |
| `create_chart` | `eddies/chart.py` | Generate matplotlib charts |
| `rabbitize_start` | `eddies/rabbitize.py` | Start visual browser automation session |
| `rabbitize_execute` | `eddies/rabbitize.py` | Execute browser actions with visual feedback |
| `rabbitize_extract` | `eddies/rabbitize.py` | Extract page content as markdown |
| `rabbitize_close` | `eddies/rabbitize.py` | Close browser session |
| `rabbitize_status` | `eddies/rabbitize.py` | Get current session status |

## Example Cascade Tools

Located in `tackle/` directory:

- `text_analyzer`: Analyzes text for readability, tone, structure
- `brainstorm_ideas`: Generates creative ideas for topics
- `summarize_text`: Summarizes long text into key points
- `fact_check`: Evaluates claims for accuracy
- `web_navigator`: Navigate websites with visual feedback

## Validators

Used with Wards system (in `tackle/` directory):

- `simple_validator`: Basic content validation (non-empty, minimum length)
- `grammar_check`: Grammar and spelling validation
- `keyword_validator`: Required keyword presence validation
- `content_safety`: Safety and moderation checks
- `length_check`: Length constraint validation
- `web_goal_achieved`: Validates if web navigation goal was achieved

**All validators must return:** `{"valid": true/false, "reason": "explanation"}`

## Registering Custom Tools

```python
from windlass import register_tackle

def my_tool(param: str) -> str:
    """Tool description for LLM."""
    return f"Result: {param}"

register_tackle("my_tool", my_tool)
```

## Dynamic Routing Tool

When a phase has `handoffs` configured, a special `route_to` tool is auto-injected, allowing the agent to transition to the next phase based on reasoning.

---

## Declarative Tools (`.tool.json`)

Define tools in JSON without writing Python code. Perfect for CLI wrappers, API calls, and tool composition.

### Four Tool Types

| Type | Description | Use Case |
|------|-------------|----------|
| `shell` | Execute shell commands (Jinja2 templated) | CLI wrappers, scripts |
| `http` | Make HTTP requests | API integrations |
| `python` | Reference Python function by import path | Existing code |
| `composite` | Chain multiple tools together | Pipelines |

### Shell Tool Example

```json
{
  "tool_id": "search_files",
  "description": "Search for text patterns in files using grep",
  "inputs_schema": {
    "pattern": "Text or regex pattern to search for",
    "path": "Directory to search (default: current)"
  },
  "type": "shell",
  "command": "grep -rn '{{ pattern }}' {{ path | default('.') }} | head -50",
  "timeout": 30
}
```

### HTTP Tool Example

```json
{
  "tool_id": "weather_lookup",
  "description": "Get current weather for a city",
  "inputs_schema": {
    "city": "City name"
  },
  "type": "http",
  "method": "GET",
  "url": "https://api.weather.com/current?q={{ city }}",
  "headers": {
    "Authorization": "Bearer {{ env.WEATHER_API_KEY }}"
  },
  "response_jq": ".data.temperature"
}
```

### Composite Tool Example

```json
{
  "tool_id": "lint_and_test",
  "description": "Run linter then tests if linting passes",
  "inputs_schema": {
    "path": "Path to check"
  },
  "type": "composite",
  "steps": [
    {"tool": "eslint", "args": {"file": "{{ input.path }}"}},
    {"tool": "run_tests", "args": {"path": "{{ input.path }}"}, "condition": "{{ steps[0].success }}"}
  ]
}
```

### Template Context

- `{{ input.param }}` - Tool inputs from LLM
- `{{ env.VAR }}` - Environment variables
- `{{ steps[n].result }}` - Previous step results (composite only)

### Discovery

- Place `.tool.json` files in `tackle/` directory
- Auto-discovered by manifest system
- Available immediately in cascades: `"tackle": ["search_files", "weather_lookup"]`

**Implementation:** `windlass/tool_definitions.py`

---

## Manifest - Dynamic Tool Selection (Quartermaster)

Instead of manually specifying tools for each phase, use `tackle: "manifest"` to have a Quartermaster agent automatically select relevant tools.

### Configuration

```json
{
  "name": "adaptive_task",
  "instructions": "Complete this task: {{ input.task }}",
  "tackle": "manifest",
  "manifest_context": "full"
}
```

### How It Works

1. Quartermaster examines phase instructions and context
2. Views full tackle manifest (all Python functions + cascade tools)
3. Selects only relevant tools for this specific task
4. Main agent receives focused toolset
5. Selection reasoning logged (not in main snowball)

### Context Modes

- `"current"` (default): Phase instructions + input data only
- `"full"`: Entire conversation history (better for multi-phase flows)

### Discovery (`tackle_manifest.py`)

- Scans Python function registry
- Scans directories configured in `tackle_dirs` (default: `["examples/", "cascades/", "tackle/"]`)
- Cascades with `inputs_schema` automatically become tools
- Unified manifest with type, description, schema

### Benefits

- Scales to unlimited tool libraries
- No prompt bloat
- Contextually relevant selection
- Hybrid Python/Cascade tools

---

## Prompt-Based vs Native Tool Calling

Windlass supports two modes for tool execution.

### Prompt-Based Tools (Default, Recommended)

```json
{
  "name": "solve_problem",
  "instructions": "Solve this coding problem",
  "tackle": ["linux_shell", "run_code"],
  "use_native_tools": false
}
```

**How it works:**
1. Tool descriptions added to system prompt as text
2. Agent outputs JSON: `{"tool": "tool_name", "arguments": {"param": "value"}}`
3. Windlass parses JSON from response
4. Calls local Python function
5. Returns result as user message

**Benefits:**
- Works with ANY model (even those without native tool support)
- No provider-specific quirks
- Simpler message format (just user/assistant)
- More transparent and debuggable
- Perfect for OpenRouter's multi-model approach

### Native Tool Calling (Opt-In)

```json
{
  "name": "solve_problem",
  "tackle": ["run_code"],
  "use_native_tools": true
}
```

**Use when:**
- Model has excellent native tool support (GPT-4, Claude 3.5)
- You want maximum structure/reliability
- You're committed to specific providers

**Recommendation:** Use prompt-based (default) unless you have a specific reason for native.

---

## Docker Sandboxed Execution

Code execution tools (`linux_shell`, `run_code`) use Docker for safe, isolated execution.

### Setup

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

### linux_shell Tool

Execute arbitrary shell commands in isolated container:

```json
{"tool": "linux_shell", "arguments": {"command": "curl https://api.example.com"}}
```

**Available in container:**
- Python 3 (python3, pip)
- Network tools (curl, wget)
- File operations (cat, echo, ls, grep, sed, awk)
- Text processing
- Package management (apt, pip)

### run_code Tool

Execute Python code using Docker. Internally uses `linux_shell` with Python heredoc.

```json
{"tool": "run_code", "arguments": {"code": "import math\nprint(math.pi)"}}
```

### Security

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

---

## Rabbitize - Visual Browser Automation

Rabbitize transforms Playwright into a stateful REST API service with visual feedback at every step.

### Key Features

- **Stateful sessions**: Browser state persists between commands
- **Visual coordinates**: Click at (x, y) instead of CSS selectors (more robust)
- **Automatic capture**: Every action generates before/after screenshots + video recording
- **Rich metadata**: DOM snapshots (markdown), element coordinates (JSON), performance metrics
- **Multi-modal integration**: Screenshots automatically flow through Windlass image protocol

### Setup

```bash
# Install
npm install -g rabbitize
sudo npx playwright install-deps

# Start server
npx rabbitize  # Runs on localhost:3037
```

**Optional auto-start:**
```bash
export RABBITIZE_AUTO_START=true
```

### Core Tools

| Tool | Description |
|------|-------------|
| `rabbitize_start(url, session_name)` | Start browser session, navigate to URL, return initial screenshot |
| `rabbitize_execute(command, include_metadata)` | Execute browser action, return before/after screenshots |
| `rabbitize_extract()` | Extract page content as markdown, get DOM coordinates |
| `rabbitize_close()` | Close session, save video, return metrics |
| `rabbitize_status()` | Get current session info |

### Command Examples

```python
# CRITICAL: Move mouse FIRST, then click (no args!)
rabbitize_execute('[":move-mouse", ":to", 400, 300]')
rabbitize_execute('[":click"]')  # Clicks at current cursor position

# Type text
rabbitize_execute('[":type", "hello world"]')

# Scroll down
rabbitize_execute('[":scroll-wheel-down", 5]')

# Press key
rabbitize_execute('[":keypress", "Enter"]')

# Drag operation
rabbitize_execute('[":drag", ":from", 100, 200, ":to", 300, 400]')
```

### Integration with Windlass

**Session Management:** Session ID automatically tracked in Echo state.

**Image Protocol:** Screenshots automatically returned via `{"content": "...", "images": [path]}` protocol. Windlass saves them to `images/{session_id}/{phase}/` and injects into conversation as multi-modal messages.

**Metadata generated per action:**
- `screenshots/before-*.jpg` + `screenshots/after-*.jpg`
- `dom_snapshots/*.md` - Page content as markdown
- `dom_coords/*.json` - Element positions for clicking
- `commands.json` - Audit trail
- `metrics.json` - Performance data
- `video.webm` - Full session recording

### Usage Patterns

**Simple Navigation:**
```json
{
  "name": "check_website",
  "instructions": "Visit {{ input.url }} and describe what you see",
  "tackle": ["rabbitize_start", "rabbitize_extract", "rabbitize_close"]
}
```

**Interactive Navigation with loop_until:**
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

**Example Cascades:**
- `examples/rabbitize_simple_demo.json`
- `examples/rabbitize_navigation_demo.json`
- `examples/rabbitize_form_fill_demo.json`

---

## Generative UI - Rich Human-in-the-Loop

The Generative UI system enables agents to create rich interfaces for human input using `ask_human_custom`.

### ask_human_custom Tool

```python
ask_human_custom(
    question: str,           # The question to ask
    context: str = None,     # Background context
    images: list = None,     # Image file paths to display
    data: dict = None,       # Structured data for tables
    options: list = None,    # Options for selection/comparison
    ui_hint: str = None,     # UI type hint
    layout_hint: str = None, # Layout hint
    auto_detect: bool = True # Auto-detect content from Echo context
)
```

### Section Types

| Type | Description |
|------|-------------|
| `markdown` | Rich text content |
| `input` | Text input field |
| `select` | Dropdown or radio |
| `multi_select` | Checkboxes |
| `image` | Image display with lightbox |
| `data_table` | Interactive table |
| `code` | Syntax-highlighted code |
| `card_grid` | Rich option cards |
| `comparison` | Side-by-side comparison |
| `accordion` | Collapsible sections |
| `tabs` | Tabbed content |

### Layout Types

`vertical`, `horizontal`, `two-column`, `three-column`, `grid`, `sidebar-left`, `sidebar-right`

### Example Usage

```json
{
  "tool": "ask_human_custom",
  "arguments": {
    "question": "Which approach do you prefer?",
    "options": [
      {"id": "option_a", "title": "Conservative", "pros": ["Safe"], "cons": ["Slower"]},
      {"id": "option_b", "title": "Aggressive", "pros": ["Fast"], "cons": ["Risky"]}
    ],
    "ui_hint": "comparison"
  }
}
```

**Implementation Files:**
- `windlass/generative_ui_schema.py` - Pydantic models
- `windlass/generative_ui.py` - Intent analyzer and spec generator
- `windlass/eddies/human.py` - Tool implementation
