# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

RVBBIT is a declarative agent framework for Python that orchestrates multi-step LLM workflows. It has evolved from a pure LLM orchestration framework into a **full-stack AI-native data IDE** with visual workflow building, polyglot execution, and self-healing capabilities.

**Key Philosophy**: Workflows are defined as JSON/YAML "Cascades" composed of "Cells", where each cell can be:
- **LLM-powered**: Traditional agent execution with tool calling
- **Deterministic**: Direct tool invocation without LLM mediation
- **Polyglot**: Execute SQL, Python, JavaScript, Clojure, or nested LLM cells
- **HITL Screens**: Direct HTML rendering for human-in-the-loop checkpoints
- **Hybrid**: Mix all approaches in a single workflow

The framework handles context accumulation, state management, execution tracing, and provides CLI, TUI, and web-based interfaces.

**The Five Self-* Properties**:
1. **Self-Orchestrating** (Manifest/Quartermaster): Workflows pick their own tools based on context
2. **Self-Testing** (Snapshot System): Tests write themselves from real executions
3. **Self-Optimizing** (Passive Optimization): Prompts improve automatically from usage data
4. **Self-Healing** (Auto-Fix): Failed cells debug and repair themselves with LLM assistance
5. **Self-Building** (Calliope): Workflows constructed through natural language conversation

## Installation & Setup

```bash
pip install .
```

**Required Environment Variables**:
- `OPENROUTER_API_KEY`: API key for OpenRouter (default provider)

**Required Infrastructure**:
- **ClickHouse**: Required database backend (no embedded fallback)

**Optional Environment Variables**:
- `HF_TOKEN`: HuggingFace API token for Harbor (HF Spaces integration)
- `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID`: For TTS (`say` tool)
- `BRAVE_SEARCH_API_KEY`: For web search tool

**Workspace Configuration**:
- `RVBBIT_ROOT`: Workspace root (default: current directory) - all paths derived from this

**LLM Configuration**:
- `RVBBIT_PROVIDER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
- `RVBBIT_DEFAULT_MODEL` (default: `x-ai/grok-4.1-fast`)
- `RVBBIT_DEFAULT_EMBED_MODEL` (default: `qwen/qwen3-embedding-8b`)
- `RVBBIT_GENERATIVE_UI_MODEL` (default: `google/gemini-3-pro-preview`)
- `RVBBIT_CONTEXT_SELECTOR_MODEL` (default: `google/gemini-2.5-flash-lite`)
- `RVBBIT_STT_MODEL` (default: `google/gemini-2.5-flash-preview-09-2025`)

**ClickHouse Configuration** (required):
- `RVBBIT_CLICKHOUSE_HOST` (default: `localhost`)
- `RVBBIT_CLICKHOUSE_PORT` (default: `9000`)
- `RVBBIT_CLICKHOUSE_DATABASE` (default: `rvbbit`)
- `RVBBIT_CLICKHOUSE_USER` (default: `rvbbit`)
- `RVBBIT_CLICKHOUSE_PASSWORD` (default: `rvbbit`)

**Directory Structure**:
```
$RVBBIT_ROOT/
├── data/           # RAG index files (transitional)
├── logs/           # File-based logs
├── graphs/         # Mermaid execution graphs
├── states/         # Session state JSON files
├── images/         # Multi-modal image outputs
├── audio/          # Voice recordings and TTS outputs
├── videos/         # Video recordings (Rabbitize)
├── session_dbs/    # Session-scoped DuckDB files with temp tables
├── research_dbs/   # Research database DuckDB files per cascade
├── traits/         # Reusable tool cascades
├── cascades/       # User-defined cascades
│   └── examples/   # Example cascade definitions
└── sql_connections/ # SQL connection YAML files
```

## Common Commands

### Running Cascades
```bash
rvbbit run cascades/examples/simple_flow.json --input '{"data": "test"}'
rvbbit run cascades/examples/simple_flow.json --input input.json
rvbbit run cascades/examples/simple_flow.json --input '{"key": "value"}' --session my_session_123
# Legacy: rvbbit examples/simple_flow.json --input '...'  (also works)
```

### SQL Commands
```bash
# Query ClickHouse
rvbbit sql query "SELECT COUNT(*) FROM all_data"
rvbbit sql query "SELECT session_id, phase_name, cost FROM all_data WHERE cost > 0 LIMIT 10"
rvbbit sql query "SELECT * FROM all_data LIMIT 5" --format json

# PostgreSQL wire protocol server
rvbbit sql server --port 15432
# Or: rvbbit serve sql --port 15432

# Schema discovery
rvbbit sql crawl --session schema_discovery
```

**Magic Tables**: `all_data` (main logs), `all_evals` (evaluation data)

### Database Management
```bash
rvbbit db status   # Show ClickHouse status and statistics
rvbbit db init     # Initialize schema (create tables)
```

### Server Commands
```bash
# Studio web UI
rvbbit serve studio --port 5050
rvbbit serve studio --dev  # Development mode with hot reload

# PostgreSQL wire protocol
rvbbit serve sql --port 15432
```

### Session Management
```bash
rvbbit sessions list --status running
rvbbit sessions show <session_id>
rvbbit sessions cancel <session_id> --reason "manual cancellation"
rvbbit sessions cleanup --dry-run  # Find zombie sessions
```

### Signal Management (Cross-Cascade Communication)
```bash
rvbbit signals list --cascade my_cascade
rvbbit signals fire daily_data_ready --payload '{"row_count": 1000}'
rvbbit signals status signal_abc123
rvbbit signals cancel signal_abc123 --reason "timeout"
```

### Model Management
```bash
rvbbit models refresh --workers 10
rvbbit models list --type text --provider anthropic
rvbbit models verify --model-id anthropic/claude-sonnet-4
rvbbit models stats
```

### Local Models (HuggingFace Transformers)

Run ML models locally without API calls using HuggingFace transformers.

**Installation**:
```bash
pip install rvbbit[local-models]  # Installs transformers, torch, accelerate
```

**CLI Commands**:
```bash
rvbbit models local status              # Show device info, loaded models
rvbbit models local list                # List local model tools
rvbbit models local list --loaded       # Show only loaded models
rvbbit models local load MODEL --task TASK  # Preload a model
rvbbit models local unload MODEL        # Unload from cache
rvbbit models local clear               # Clear all cached models
rvbbit models local export MODEL --task TASK -o tool.yaml  # Generate tool definition
```

**Environment Variables**:
- `RVBBIT_LOCAL_MODEL_DEVICE`: Default device (`auto`, `cuda`, `mps`, `cpu`)
- `RVBBIT_LOCAL_MODEL_CACHE_SIZE_GB`: Max cache memory in GB (default: `8`)

### Tool Management
```bash
rvbbit tools sync --force
rvbbit tools list --type function
rvbbit tools usage --days 7
rvbbit tools search "sql query"
rvbbit tools find "parse PDF documents"  # Semantic search
```

### Embedding Management
```bash
rvbbit embed status
rvbbit embed run --batch-size 50 --dry-run
rvbbit embed costs
```

### Trigger Management
```bash
rvbbit triggers list cascades/etl.yaml
rvbbit triggers export cascades/etl.yaml --format cron
rvbbit triggers export cascades/etl.yaml --format kubernetes --image rvbbit:latest
rvbbit triggers check cascades/etl.yaml on_data_ready
```

### Harbor (HuggingFace Spaces)
```bash
rvbbit harbor list --author myusername
rvbbit harbor introspect user/space-name
rvbbit harbor export user/space-name -o traits/my_tool.tool.json
rvbbit harbor manifest
rvbbit harbor wake user/space-name
rvbbit harbor refresh
```

### MCP (Model Context Protocol) Servers
```bash
rvbbit mcp list                     # List configured MCP servers
rvbbit mcp status                   # Show server status and health
rvbbit mcp introspect filesystem    # List tools from specific server
rvbbit mcp manifest                 # Show all MCP tools in manifest
rvbbit mcp refresh                  # Re-discover tools from all servers
rvbbit mcp test filesystem read_file --args '{"path": "/tmp/test.txt"}'  # Test tool
```

**Configuration**:
MCP servers are configured via `config/mcp_servers.yaml` or `RVBBIT_MCP_SERVERS_YAML` env var.

Example `config/mcp_servers.yaml`:
```yaml
# Filesystem server
- name: filesystem
  transport: stdio
  command: npx
  args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
  enabled: true

# Brave Search
- name: brave-search
  transport: stdio
  command: npx
  args: ["-y", "@modelcontextprotocol/server-brave-search"]
  env:
    BRAVE_API_KEY: ${BRAVE_API_KEY}
  enabled: true

# HTTP server example
- name: github
  transport: http
  url: http://localhost:3000/mcp
  headers:
    Authorization: Bearer ${GITHUB_TOKEN}
  enabled: false
```

**Environment Variables**:
- `RVBBIT_MCP_ENABLED`: Enable MCP integration (default: `true`)
- `RVBBIT_MCP_SERVERS_YAML`: YAML array of server configs (alternative to config file)

### Testing
```bash
# Run cascade, then freeze as test
rvbbit run examples/simple_flow.json --input '{"data": "test"}' --session test_001
rvbbit test freeze test_001 --name simple_flow_works --description "Basic workflow"

# Replay (instant, no LLM calls)
rvbbit test validate simple_flow_works  # or: rvbbit test replay

# Run all snapshot tests
rvbbit test run
rvbbit test list
```

### TUI Dashboard
```bash
rvbbit tui --cascade my_flow.yaml --session latest
rvbbit alice generate my_flow.yaml -o dashboard.yaml
rvbbit alice run my_flow.yaml --session auto
```

### Utilities
```bash
rvbbit render images/screenshot.png --width 80
rvbbit render-mermaid graph.mmd --mode kitty
rvbbit check --feature rabbitize
rvbbit analyze my_cascade.yaml --min-runs 10
```

## Web Dashboard (Studio)

RVBBIT includes a full-featured web-based IDE for building and executing cascades.

### Starting the Dashboard
```bash
# Production mode
rvbbit serve studio --port 5050

# Development mode (hot reload)
rvbbit serve studio --dev

# Or manually:
cd studio/backend && python app.py  # Backend on port 5050
cd studio/frontend && npm start      # Frontend on port 5550
```

### Main Interfaces

1. **SQL Query IDE** (`/sql-query`)
   - **Query Mode**: Traditional SQL editor with schema browser
   - **Notebook Mode** (`?mode=notebook`): Polyglot cells (SQL, Python, JS, Clojure, RVBBIT)
   - Multi-modal output rendering (tables, images, charts, JSON)
   - Auto-fix failed cells with LLM-powered debugging

2. **Playground Canvas** (`/playground`)
   - Visual cascade builder with drag-and-drop nodes
   - Two-sided cell cards (front: output, back: YAML config)
   - Stacked deck visualization for candidates
   - Real-time execution with SSE updates
   - Save/load cascades from traits/ or cascades/

3. **Session Explorer** (`/sessions`)
   - Browse all execution sessions
   - View session details, costs, and outputs
   - Visualize execution graphs
   - Cost analytics by session/cell/model

4. **Calliope** (`/calliope`)
   - Conversational cascade builder
   - Chat to design workflows
   - Live graph visualization as app is built
   - Instant test execution

## Core Architecture

### Cascade DSL

Cascades are JSON/YAML files validated via Pydantic models in `rvbbit/cascade.py`.

```yaml
cascade_id: unique_name
description: Optional description
inputs_schema:
  param_name: description

cells:
  - name: phase_name
    instructions: "Jinja2-templated prompt using {{ input.key }} or {{ state.key }}"
    traits: [tool_name]
    handoffs: [next_phase]
    rules:
      max_turns: 3
      max_attempts: 2
```

**Cell Configuration** (key fields):

**LLM Cells** (use `instructions`):
- `name`: Cell identifier
- `instructions`: Jinja2-templated system prompt
- `traits`: Tool names to inject, or `"manifest"` for auto-selection
- `model`: Optional model override (e.g., `"anthropic/claude-sonnet-4"`)
- `handoffs`: Next-cell targets (enables dynamic `route_to` tool)
- `rules`: Contains `max_turns`, `max_attempts`, `loop_until`, `turn_prompt`
- `candidates`: Parallel execution config (`factor`, `evaluator_instructions`, `mode`, `human_eval`)
- `wards`: Pre/post validation (`blocking`, `retry`, `advisory` modes)
- `context`: Selective context from other cells
- `output_schema`: JSON schema for output validation
- `intra_context`: Per-turn context management (sliding window, observation masking)
- `callouts`: Semantic message tagging
- `token_budget`: Automatic context pruning

**Deterministic Cells** (use `tool` instead of `instructions`):
- `name`: Cell identifier
- `tool`: Direct tool invocation (e.g., `"sql_data"`, `"python:module.func"`)
- `inputs`: Jinja2-templated inputs for the tool
- `retry`: Retry configuration (max_attempts, backoff strategy)
- `timeout`: Execution timeout (e.g., `"5m"`, `"30s"`)
- `on_error`: Error handling (`"auto_fix"`, cell name, or inline config)
- `handoffs`: Next-cell targets (routing via `_route` in tool output)

**HITL Screen Cells** (use `hitl` for direct HTML):
- `hitl`: Raw HTML/HTMX template for human interaction
- `hitl_title`: Screen title
- `hitl_description`: Screen description
- `handoffs`: Next cells based on user response

### Tool System ("Traits")

**Six Types**:
1. **Python Functions**: Registered via `register_trait("name", func)`
2. **Cascade Tools**: YAML cascades with `inputs_schema` in `traits/` directory
3. **Gradio Tools (Harbor)**: HuggingFace Spaces as tools via `.tool.json`
4. **Memory Tools**: RAG-searchable knowledge bases
5. **Local Model Tools**: HuggingFace transformers via `.tool.yaml` with `type: local_model`
6. **MCP Tools**: Model Context Protocol servers (stdio/HTTP) with auto-discovery

**Built-in Tools**:
- **Core**: `linux_shell`, `run_code`, `set_state`, `spawn_cascade`, `map_cascade`
- **Data**: `sql_data`, `python_data`, `js_data`, `clojure_data`, `rvbbit_data`
- **SQL**: `smart_sql_run`, `rvbbit_udf()`, `rvbbit_cascade_udf()`
- **Human-in-the-loop**: `ask_human`, `ask_human_custom`
- **Visualization**: `create_chart`, `take_screenshot`, `show_ui`
- **Browser**: `rabbitize_*` (visual browser automation)
- **Voice**: `say` (TTS), `listen` (STT), `transcribe_audio`, `process_voice_recording`
- **Research**: `research_query`, `research_execute`
- **Artifacts**: `create_artifact`, `list_artifacts`, `get_artifact`
- **Signals**: `await_signal`, `fire_signal`, `list_signals`
- **Web Search**: `brave_web_search`
- **Cascade Building**: `cascade_write` (Calliope)

**Registering Custom Tools**:
```python
from rvbbit import register_trait

def my_tool(param: str) -> str:
    """Tool description for LLM."""
    return f"Result: {param}"

register_trait("my_tool", my_tool)
```

### Custom SQL Operators

**NEW (2026):** Create custom SQL operators through cascade files - no Python code needed!

The template inference system automatically converts operator patterns into structured matching:

```yaml
# cascades/my_operators/similar_to.cascade.yaml
sql_function:
  name: similar_to
  operators:
    - "{{ text }} SIMILAR_TO {{ reference }}"
    - "SIMILAR_TO({{ text }}, {{ reference }})"
  args:
    - name: text
      type: VARCHAR
    - name: reference
      type: VARCHAR
  returns: BOOLEAN

cells:
  - name: check_similarity
    instructions: |
      Are these semantically similar?
      TEXT: {{ input.text }}
      REFERENCE: {{ input.reference }}
      Answer: true or false
```

**Usage:**
```sql
-- Both syntaxes work automatically:
SELECT * FROM docs WHERE title SIMILAR_TO 'sustainability report'
SELECT SIMILAR_TO(title, 'eco-friendly') FROM products
```

**See:** `docs/CUSTOM_SQL_OPERATORS.md` for complete guide with examples, best practices, and troubleshooting.

**Creating Local Model Tools**:

Declarative (`.tool.yaml`):
```yaml
tool_id: local_sentiment
description: Analyze text sentiment using local DistilBERT model
inputs_schema:
  text: The text to analyze
type: local_model
model_id: distilbert/distilbert-base-uncased-finetuned-sst-2-english
task: text-classification
device: auto  # auto, cuda, mps, cpu
```

Programmatic (Python decorator):
```python
from rvbbit import local_model_tool

@local_model_tool(
    "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
    "text-classification",
    name="sentiment_with_threshold"
)
def sentiment_with_threshold(pipeline, text: str, threshold: float = 0.8) -> str:
    result = pipeline(text)
    if result[0]["score"] < threshold:
        return "uncertain"
    return result[0]["label"]
```

**Supported Local Model Tasks**:
- `text-classification` / `sentiment-analysis`
- `token-classification` / `ner`
- `summarization`
- `question-answering`
- `text-generation`
- `zero-shot-classification`
- `image-classification`

### Key Features

#### TOON Format Integration (Token Efficiency)

RVBBIT uses **TOON (Token-Oriented Object Notation)** as the preferred transport format for SQL data and large datasets sent to LLMs, achieving **45-60% token savings** compared to JSON.

**What is TOON?**
TOON combines YAML-style indentation with CSV-style tabular arrays for token-efficient data encoding:

```yaml
# JSON: 184 characters
[{"id": 1, "name": "Alice", "score": 95.5}, ...]

# TOON: 116 characters (37% savings)
[3]{id,name,score,status}:
  1,Alice,95.5,active
  2,Bob,87.2,active
  3,Carol,92,inactive
```

**Automatic TOON Encoding:**
- **SQL results**: `format="auto"` (default) uses TOON for >5 rows
- **Context injection**: Auto-detects and formats tabular data
- **Aggregate operators**: Auto-TOON for `summarize()`, `themes()`, etc.
- **Smart fallback**: Uses JSON for non-uniform or small datasets

**Jinja2 Filters:**
```yaml
cells:
  - name: analyze_data
    instructions: |
      Analyze this data:
      {{ outputs.load_data | totoon }}  # Explicit TOON
      {{ outputs.load_data | tojson }}  # Explicit JSON
      {{ outputs.load_data }}           # Auto-format
```

**Configuration:**
```bash
export RVBBIT_DATA_FORMAT=auto          # auto, toon, json (default: auto)
export RVBBIT_TOON_MIN_ROWS=5           # Minimum rows for TOON (default: 5)
```

**Cell-Level Override:**
```yaml
- name: load_data
  tool: sql_data
  inputs:
    query: "SELECT * FROM customers"
    format: toon  # Force TOON encoding
```

**Telemetry & Analytics:**
TOON usage and savings are tracked in ClickHouse `unified_logs` table:
```sql
-- View TOON savings
SELECT
    data_format,
    COUNT(*) as operations,
    AVG(data_token_savings_pct) as avg_savings_pct,
    SUM(data_size_json - data_size_toon) as total_chars_saved
FROM rvbbit.unified_logs
WHERE data_format = 'toon'
GROUP BY data_format;

-- Check decoder success rate
SELECT
    COUNT(*) as decode_attempts,
    COUNTIf(toon_decode_success) as successful,
    (COUNTIf(toon_decode_success) * 100.0 / COUNT(*)) as success_rate
FROM rvbbit.unified_logs
WHERE toon_decode_attempted;
```

**When TOON Provides Benefits:**
- ✅ Uniform arrays of objects (SQL results)
- ✅ Wide tables (many columns)
- ✅ Large datasets (>10 rows)
- ❌ Simple string arrays (minimal savings)
- ❌ Deeply nested non-uniform objects
- ❌ Small datasets (<5 rows)

**See:** `examples/toon_demo.yaml` for a complete demonstration.

---

#### Auto-Fix (Self-Healing Cells)
When deterministic cells fail, use LLM to debug and retry:
```yaml
- name: risky_query
  tool: sql_data
  inputs:
    query: "SELECT * FROM {{ input.table }}"
  on_error: auto_fix  # Simple mode

# Or customized:
- name: risky_query
  tool: sql_data
  inputs:
    query: "SELECT * FROM {{ input.table }}"
  on_error:
    auto_fix:
      max_attempts: 3
      model: anthropic/claude-sonnet-4
      prompt: "Fix this SQL error: {{ error }}"
```

#### Human-Evaluated Candidates
Instead of LLM evaluator, humans pick winners:
```yaml
candidates:
  factor: 5
  evaluator: human  # or "hybrid" for LLM prefilter
  human_eval:
    presentation: side_by_side  # tabbed, carousel, diff, tournament
    selection_mode: pick_one    # rank_all, rate_each, tournament
    show_metadata: true
    require_reasoning: false
    capture_for_training: true
    timeout_seconds: 3600
    on_timeout: llm_fallback
  llm_prefilter: 3  # For hybrid: LLM picks top N, human picks winner
```

#### Signals (Cross-Cascade Communication)
Coordinate multiple cascades with signals:
```yaml
- name: wait_for_etl
  tool: await_signal
  inputs:
    signal_name: "daily_data_ready"
    timeout: "4h"
    description: "Wait for upstream ETL"

- name: notify_downstream
  tool: fire_signal
  inputs:
    signal_name: "preprocessing_complete"
    payload: '{"status": "success"}'
```

#### Auto-Context (Intelligent Token Management)
Automatic context pruning to reduce costs:
```yaml
intra_context:
  enabled: true
  window: 5                    # Last N turns full fidelity
  mask_observations_after: 3   # Mask older tool results
  compress_loops: true         # Special handling for loop_until
  preserve_reasoning: true     # Keep pure reasoning
  preserve_errors: true        # Always keep error messages
```

#### HITL Screen Cells
Direct HTML rendering without LLM:
```yaml
- name: review_screen
  hitl: |
    <h2>Review Items</h2>
    <div id="items">{{ outputs.load_data.result | tojson }}</div>
    <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond">
      <button name="response[action]" value="approve">Approve</button>
      <button name="response[action]" value="reject">Reject</button>
    </form>
  hitl_title: "Review Screen"
  handoffs: [process_approved, review_screen]
```

#### Polyglot Validators (Wards)
Validation in any language:
```yaml
wards:
  - mode: retry
    max_attempts: 3
    validator:
      python: |
        return {"valid": len(output) > 100, "reason": "OK" if len(output) > 100 else "Too short"}

  - mode: blocking
    validator:
      sql: |
        SELECT COUNT(*) > 0 as valid FROM parse_json(output)
        WHERE required_field IS NOT NULL
```

#### Triggers (Scheduling)
Declarative scheduling and event-based execution:
```yaml
triggers:
  - name: daily_run
    type: cron
    schedule: "0 6 * * *"
    timezone: America/New_York
    inputs: {mode: full}

  - name: on_data_ready
    type: sensor
    check: "python:sensors.table_freshness"
    args: {table: raw.events, max_age_minutes: 60}
    poll_interval: 5m

  - name: on_webhook
    type: webhook
    auth: "hmac:${WEBHOOK_SECRET}"
```

#### Research Database
Persistent DuckDB per cascade for research workflows:
```yaml
cascade_id: "market_research"
research_db: "market_research"  # Enables research_query, research_execute tools
```

#### Narrator Service
Event-driven voice commentary during execution:
```yaml
narrator:
  enabled: true
  mode: poll
  poll_interval_seconds: 3.0
  context_turns: 5
  instructions: "Brief 1-2 sentence update. Call say()."
```

#### Decision Points (LLM-Generated HITL)
LLM generates appropriate UI based on context:
```yaml
decision_points:
  enabled: true
  trigger: output  # error, both
  routing:
    _continue: next
    _retry: self
    escalate: manager_review
```

### Execution Flow

The core engine is `RVBBITRunner` in `runner.py`.

**Key Concepts**:
- **Context Snowballing**: Within a cell, full history accumulates automatically
- **Selective Context**: Between cells, context is explicit (`context: {from: ["previous"]}`)
- **State Persistence**: `Echo` object maintains `state`, `history`, `lineage`
- **Sub-Cascades**: `context_in`/`context_out` for state inheritance
- **Candidates**: Run cell/cascade N times, evaluator (LLM or human) picks best
- **Aggregate Mode**: Combine all candidate outputs instead of picking one

### Jinja2 Templating

Cell instructions support:
- `{{ input.variable_name }}`: Initial cascade input
- `{{ state.variable_name }}`: Persistent session state
- `{{ outputs.phase_name }}`: Previous cell outputs
- `{{ lineage }}`, `{{ history }}`: Execution context
- `{{ sounding_index }}`: Current candidate index (0, 1, 2...)
- `{{ sounding_factor }}`: Total number of candidates
- `{{ is_sounding }}`: True when running as a candidate
- `{{ checkpoint_id }}`: Current HITL checkpoint ID
- Rendered in `prompts.py:render_instruction()`

## Module Structure

```
rvbbit/
├── __init__.py          # Package entry point, tool registration
├── cascade.py           # Pydantic models for Cascade DSL
├── runner.py            # RVBBITRunner execution engine
├── deterministic.py     # Deterministic cell execution
├── agent.py             # LLM wrapper (LiteLLM integration)
├── echo.py              # Echo class (state/history container)
├── traits.py            # ToolRegistry for tool management
├── tackle_manifest.py   # Dynamic tool discovery for Quartermaster
├── tool_definitions.py  # Declarative tools (shell, http, python, composite, gradio)
├── harbor.py            # HuggingFace Spaces discovery and integration
├── config.py            # Global configuration (RVBBIT_ROOT-based)
├── unified_logs.py      # Unified logging (ClickHouse)
├── db_adapter.py        # ClickHouse database adapter
├── visualizer.py        # Mermaid graph generation
├── tracing.py           # TraceNode hierarchy
├── events.py            # Event bus for real-time updates
├── auto_context.py      # Intelligent context management
├── signals.py           # Cross-cascade signal backend
├── triggers.py          # Trigger/scheduling handling
├── narrator_service.py  # Event-driven voice narration
├── session_registry.py  # Durable session tracking
├── utils.py             # Tool schemas, image encoding
├── cli.py               # Command-line interface
├── prompts.py           # Jinja2 prompt rendering
├── traits/              # Built-in tools (was: eddies/)
│   ├── extras.py        # linux_shell, run_code, take_screenshot
│   ├── data_tools.py    # sql_data, python_data, js_data, clojure_data, rvbbit_data
│   ├── human.py         # ask_human, ask_human_custom
│   ├── state_tools.py   # set_state
│   ├── system.py        # spawn_cascade, map_cascade
│   ├── chart.py         # create_chart
│   ├── signal_tools.py  # await_signal, fire_signal, list_signals
│   ├── tts.py           # say (ElevenLabs TTS)
│   ├── stt.py           # listen, transcribe_audio, process_voice_recording
│   ├── research_db.py   # research_query, research_execute
│   ├── artifacts.py     # create_artifact, list_artifacts, get_artifact
│   ├── display.py       # show_ui
│   ├── web_search.py    # brave_web_search
│   ├── rabbitize.py     # Visual browser automation
│   ├── cascade_builder.py  # cascade_write (Calliope)
│   ├── branching.py     # Research session forking
│   └── bash_session.py  # Stateful bash sessions
├── sql_tools/           # SQL utilities
│   ├── session_db.py    # Session-scoped DuckDB
│   └── udf.py           # rvbbit_udf() + rvbbit_cascade_udf()
├── server/              # PostgreSQL wire protocol server
│   ├── postgres_protocol.py  # Message encoding/decoding
│   └── postgres_server.py    # TCP server
└── client/              # SQL client library
    └── sql_client.py    # RVBBITClient for HTTP API

studio/                  # Web UI
├── backend/
│   ├── app.py           # Main Flask application
│   ├── studio_api.py    # Combined API endpoints
│   ├── notebook_api.py  # Data Cascades notebook endpoints
│   ├── playground_api.py # Playground canvas endpoints
│   ├── session_api.py   # Session/logs endpoints
│   ├── signals_api.py   # Signal management endpoints
│   ├── artifacts_api.py # Artifact management
│   └── events.py        # SSE event streaming
└── frontend/
    └── src/
        ├── views/
        │   ├── sql-query/   # SQL Query IDE + Notebooks
        │   ├── playground/  # Visual cascade builder
        │   ├── sessions/    # Session explorer
        │   └── calliope/    # Conversational builder
        └── components/      # Shared UI components

alice/                   # TUI framework
├── looking_glass.py     # Core TUI engine
├── terminal.py          # Terminal dashboard
└── ...
```

## Key Implementation Patterns

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
**Candidates**: `soundings_flow.json`, `cascade_soundings_test.json`, `reforge_*.json`
**Aggregate Mode**: `soundings_aggregate_demo.json`, `soundings_fanout_demo.json`
**Human Evaluation**: `human_sounding_eval_demo.yaml`
**Validation**: `ward_*.json`, `loop_until_*.json`
**Context**: `context_selective_demo.json`, `context_sugar_demo.json`
**Tools**: `manifest_flow.json`, `rabbitize_*.json`, `hitl_flow.json`
**Voice**: `voice_transcription_demo.json`, `voice_assistant_demo.json`
**Signals**: `signal_*.yaml`
**Dynamic Mapping**: `test_dynamic_soundings.yaml`, `test_map_cascade.yaml`
**Data Cascades**: `notebook_polyglot_showcase.yaml`, `notebook_llm_*.yaml`
**HITL Screens**: `test_hitl_screens.yaml`

## Terminology (Nautical Theme)

- **Cascades**: The overall workflow/journey
- **Cells**: Stages within a Cascade
- **Traits**: Tools and functions (was: Tackle)
- **Echoes**: State and history accumulated during a session
- **Candidates**: Parallel attempts to find the best route (was: Soundings)
- **Reforge**: Iterative refinement of the winning candidate
- **Wards**: Protective validation barriers
- **Manifest**: List of available traits
- **Quartermaster**: Agent that selects appropriate traits
- **Harbor**: Registry/system for HuggingFace Spaces connections
- **Berth**: A specific HF Space connection (tool definition)
- **Signals**: Cross-cascade communication events
- **Calliope**: Conversational cascade builder (muse of epic poetry)

## Extended Documentation

For detailed feature reference, see `docs/claude/`:

| Document | Contents |
|----------|----------|
| `data-cascades-reference.md` | Polyglot notebooks: SQL, Python, JS, Clojure, LLM cells with auto-fix |
| `deterministic-reference.md` | Tool-based cells without LLM mediation, hybrid workflows |
| `playground-reference.md` | Visual cascade builder, stacked deck UI, two-sided cards |
| `dashboard-reference.md` | Web IDE: SQL notebooks, canvas, session explorer |
| `tools-reference.md` | Traits system, Manifest, Docker, Rabbitize, Generative UI |
| `candidates-reference.md` | Candidates, Reforge, Mutations, Multi-Model, Human Evaluation |
| `context-reference.md` | Selective context system, cell references, auto-context |
| `validation-reference.md` | Wards, loop_until, turn_prompt, output_schema |
| `observability.md` | Logging, Events, Debug UI, Image Protocol |
| `testing.md` | Snapshot testing system |
| `optimization.md` | Training data, Passive prompt optimization |

Also see: `CLICKHOUSE_SETUP.md`, `CONNECT_NOW.md`, `docs/harbor-design.md`, `docs/DATARABBIT_VISION.md`, `docs/TRAIT_SQL_SYNTAX.md`
