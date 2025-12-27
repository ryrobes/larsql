# RVBBIT Framework - Complete Capabilities Catalog

**Date**: 2025-12-27
**Purpose**: Comprehensive inventory of all framework capabilities

---

## Executive Summary

RVBBIT is a **full-stack AI-native data IDE** that evolved from an LLM orchestration framework into a polyglot workflow engine with visual editing, self-healing capabilities, and SQL integration. Workflows are "Cascades" composed of "Cells" that can mix LLM-powered, deterministic, and polyglot execution in a single pipeline.

**Core Philosophy**: Declarative workflows (JSON/YAML) where each cell can be:
- **LLM-powered**: Traditional agent execution with tool calling
- **Deterministic**: Direct tool invocation without LLM mediation
- **Polyglot**: Execute SQL, Python, JavaScript, Clojure, or nested LLM cells
- **Hybrid**: Mix all approaches in a single workflow

---

## 1. EXECUTION ARCHITECTURE

### 1.1 Cascade DSL (Pydantic Models)

**Three Cell Types**:
1. **LLM Cells** - Use `instructions` field for agent execution
2. **Deterministic Cells** - Use `tool` field for direct tool invocation
3. **SQL Mapping Cells** - Use `for_each_row` for database row fan-out

**Common Cell Fields**:
- `name` - Cell identifier
- `handoffs` - Next cell targets (enables dynamic routing)
- `context` - Selective context system (explicit/auto mode)
- `human_input` - HITL checkpoints (confirmation, choice, rating, form, generative UI)
- `audibles` - Real-time feedback injection mid-execution
- `decision_points` - LLM-generated HITL decisions with XML blocks
- `callouts` - Semantic message tagging for UI/query retrieval
- `narrator` - Async voice commentary during execution
- `browser` - Dedicated Rabbitize browser subprocess lifecycle
- `intra_context` - Per-turn context management within phase

**LLM Cell Specific**:
- `instructions` - Jinja2-templated system prompt
- `traits` - Tool names to inject, or `"manifest"` for auto-selection
- `model` - Optional model override
- `use_native_tools` - Provider native vs prompt-based tool calling
- `rules` - max_turns, max_attempts, loop_until, turn_prompt, retry_instructions
- `candidates` - Tree of Thought with dynamic factor, evaluation, aggregation, reforge
- `wards` - Pre/post validation (blocking/advisory/retry modes)
- `output_schema` - JSON schema validation
- `output_extraction` - Extract structured data from output with regex
- `rag` - RAG configuration (directory, embedding model, chunking)
- `token_budget` - Token budget enforcement
- `image_config` - Image generation params
- `manifest_context` - "current" or "full" for Quartermaster
- `manifest_limit` - Max tools to send to Quartermaster
- `memory` - Conversational memory bank name

**Deterministic Cell Specific**:
- `tool` - Tool specification (name, python:module.func, sql:query.sql, shell:script.sh)
- `tool_inputs` / `inputs` - Jinja2-templated inputs
- `routing` - Maps result._route or result.status to handoff targets
- `on_error` - Error handler (cell_name, auto_fix, or inline LLM fallback)
- `retry` - Retry config (max_attempts, backoff: none/linear/exponential)
- `timeout` - Execution timeout (30s, 5m, 1h)

**SQL Mapping Specific**:
- `for_each_row.table` - Temp table name (e.g., "_customers")
- `for_each_row.cascade` - Cascade to spawn per row
- `for_each_row.inputs` - Jinja2 templates for cascade inputs ({{ row.column }})
- `for_each_row.max_parallel` - Concurrent executions
- `for_each_row.result_table` - Collect results into temp table
- `for_each_row.on_error` - continue/fail_fast/collect_errors

### 1.2 Execution Engine (RVBBITRunner)

**Core Features**:
- Hybrid execution (LLM + deterministic cells seamlessly)
- Context management (snowballing within cells, selective between)
- Dynamic routing (route_to tool injected with handoffs)
- Parallel phase execution (dependency analysis)
- Depth tracking (prevents infinite recursion, max: 5)
- Tracing (full execution tree with TraceNode hierarchy)

**Advanced Features**:
- Heartbeat system (zombie detection for durable execution)
- Session state management (persistent with cancellation support)
- Narrator service (event-driven voice commentary, poll/event modes)
- Audible system (mid-phase feedback injection with budget tracking)
- Memory system (conversational memory with callback-based persistence)
- Token budget management (context explosion prevention)
- Tool caching (content-addressed caching for deterministic tools)

### 1.3 State Management (Echo)

**Core Data**:
- `session_id` - Execution identifier
- `parent_session_id` - For sub-cascade tracking
- `state` - Persistent key-value store
- `history` - Message log with rich metadata
- `lineage` - Cell outputs for reference
- `errors` - Error tracking
- `genus_hash` - Cascade-level hash for all logs

**Rich Metadata**:
- `trace_id`, `parent_id` - Tree structure
- `node_type` - cascade/phase/turn/tool/soundings/evaluator
- `metadata` - Cell name, candidate index, model, mutation, semantic classification
- `species_hash` - Prompt DNA for evolution tracking
- `callouts` - Semantic tagging

**Automatic Outputs**:
- Unified logging to Parquet/ClickHouse
- Mermaid diagram generation (monotonically growing)
- SSE events for real-time UI updates
- Context card generation for auto-context

### 1.4 LLM Wrapper (Agent)

**Provider Support**:
- OpenRouter (default, 200+ models)
- Ollama (local GPU, automatic localhost routing)
- Reasoning models (extended thinking, e.g., "xai/grok-4::high(8000)")
- Image generation (FLUX, SDXL via modalities injection)
- Multimodal (vision, audio, image inputs)

**Features**:
- Message sanitization (removes Echo fields, ensures API compliance)
- Retry logic (rate limit handling, exponential backoff)
- Streaming (full request/response capture)
- Cost tracking (non-blocking via unified logger)
- Token tracking (immediate counts: prompt, completion, reasoning)
- Provider detection (automatic from model name)

**Special Methods**:
- `embed()` - Embedding generation with batching, retry, 5min timeout
- `transcribe()` - Audio transcription with webm→wav conversion
- `generate_image()` - Image generation with disk save
- `is_image_generation_model()` - Dynamic model registry

### 1.5 Deterministic Execution

**Tool Resolution**:
- Registered tools (lookup in tackle registry)
- Python imports (`python:module.path.function`)
- SQL queries (`sql:path/query.sql` with Jinja2 rendering)
- Shell scripts (`shell:path/script.sh` with env vars)

**Features**:
- Input rendering (Jinja2 templating with JSON parsing)
- Timeout support (per-phase timeouts)
- Retry logic (exponential backoff, per-attempt timeout)
- Routing (based on `_route` or `status` in result)
- Context injection (auto-inject _cell_name, _session_id for data tools)

---

## 2. TOOL SYSTEM ("Traits")

### 2.1 Tool Types

**Three Categories**:
1. **Python Functions** - Registered via `register_tackle("name", func)`
2. **Cascade Tools** - JSON/YAML cascades with `inputs_schema` in traits/
3. **Declarative Tools** - .tool.json/.tool.yaml files with 5 types:
   - Shell (commands with Docker sandbox option)
   - HTTP (REST API calls with jq-style extraction)
   - Python (direct function imports)
   - Composite (multi-step pipelines)
   - Gradio (HuggingFace Spaces integration)

### 2.2 Built-in Tools

**Core Execution**:
- `spawn_cascade` - Fire-and-forget cascade spawning
- `map_cascade` - Fan-out over arrays with parallel execution
- `set_state` - Persistent state updates
- `route_to` - Dynamic routing (auto-injected with handoffs)

**Data Tools**:
- `sql_data` - SQL execution with temp table materialization
- `python_data` - Pandas/NumPy with multi-modal outputs (DataFrames, matplotlib, PIL, Plotly)
- `js_data` - JavaScript via Node.js
- `clojure_data` - Clojure via Babashka
- `rvbbit_data` - Nested LLM cells in deterministic workflows
- `bash_data` - Bash execution with validation protocol

**SQL Tools**:
- `smart_sql_run` - LLM-powered query generation
- `rvbbit_udf()` - LLM-powered SQL UDF for inline enrichment
- `rvbbit_cascade_udf()` - Full cascade execution per database row

**Human-in-the-Loop**:
- `ask_human` - Simple text prompts
- `ask_human_custom` - Generative UI (LLM-generated HTMX interfaces)

**Visualization**:
- `create_chart` - Plotly chart generation
- `take_screenshot` - Screen capture

**Browser Automation**:
- `control_browser` - Visual browser commands (click, type, scroll)
- `extract_page_content` - DOM/text extraction
- Full lifecycle management (spawn, navigate, cleanup)

**Voice**:
- `say` - Text-to-speech via ElevenLabs
- `listen` - Speech-to-text streaming
- `transcribe_audio` - Audio file transcription

**Research & Data**:
- `research_query`, `research_execute` - Cascade-scoped DuckDB

### 2.3 Manifest (Quartermaster)

**Dynamic tool selection based on context**:
- Set `traits: "manifest"` in cell config
- LLM analyzes task and selects appropriate tools
- Semantic pre-filtering if embeddings available (manifest_limit: 30)
- Two modes: `current` (just this phase) or `full` (all prior context)
- Reduces prompt bloat, enables emergent tool usage

### 2.4 Harbor (HuggingFace Spaces)

**Gradio tool integration**:
- Auto-discover user's HF Spaces
- Introspect Gradio endpoints for input/output schemas
- Call Spaces as tools with full parameter binding
- Track hardware costs ($0.00 to $36.00/hour)
- Status monitoring (RUNNING, SLEEPING, etc.)
- Space lifecycle management

**Hardware Pricing**: T4 Small ($0.40/hr) to H100 x8 ($36.00/hr)

### 2.5 Tool Definitions (Declarative)

**Schema**:
```yaml
tool_id: search_code
description: Search codebase with ripgrep
inputs_schema:
  pattern: Search pattern (regex)
  path: Directory to search
type: shell
command: "rg --json '{{ pattern }}' {{ path | default('.') }}"
timeout: 30
sandbox: true
```

**Supported Types**:
- Shell (commands with Jinja2, Docker sandbox, timeout)
- HTTP (GET/POST/PUT/DELETE with headers, body, jq extraction)
- Python (import path with auto-discovery)
- Composite (multi-tool pipelines with conditional steps)
- Gradio (HF Spaces with introspection)

---

## 3. DATA & SQL FEATURES

### 3.1 Session-Scoped DuckDB

**Temp table system**:
- One DuckDB per session in `session_dbs/`
- Temp tables auto-created from cell outputs (`_cell_name`)
- Zero-copy data flow between polyglot cells
- Parquet materialization for persistence
- Auto-cleanup on session end

**Usage**:
```sql
SELECT * FROM _previous_cell WHERE amount > 100
```

### 3.2 SQL UDFs

**rvbbit_udf()** - LLM-powered SQL function:
```sql
SELECT
  product_name,
  rvbbit_udf('Extract brand', product_name) as brand
FROM products
```

**rvbbit_cascade_udf()** - Full cascade per row:
```sql
SELECT
  customer_id,
  rvbbit_cascade_udf('traits/fraud.yaml', json_object('id', id)) as analysis
FROM transactions
```

**Features**:
- Caching (same input → same output)
- Batching for efficiency
- Graceful error handling (returns NULL on failure)
- Full cascade features per row (soundings, wards, tools)

### 3.3 PostgreSQL Wire Protocol Server

**Connect from any SQL client**:
- TCP server on port 5432
- PostgreSQL wire protocol implementation
- Message encoding/decoding (StartupMessage, Query, RowDescription, DataRow)
- SSL/TLS support
- Authentication (trust/password)

**Usage**:
```bash
rvbbit server --port 5432
psql postgresql://rvbbit@localhost:5432/default
```

### 3.4 SQL Client (HTTP API)

**RVBBITClient**:
```python
from rvbbit.client import RVBBITClient
client = RVBBITClient("http://localhost:5001")
results = client.query("SELECT * FROM all_data LIMIT 10")
```

### 3.5 Unified Logging

**chDB/ClickHouse backend**:

**Default (chDB)**:
- Embedded ClickHouse engine
- Reads Parquet files in ./data/
- Zero setup, zero servers
- 10-100x faster than CSV/JSON

**Production (ClickHouse Server)**:
- Set `RVBBIT_USE_CLICKHOUSE_SERVER=true`
- Scales to billions of rows
- Real-time queries

**Magic Tables**:
- `all_data` - Main logs (messages, tool calls, metadata)
- `all_evals` - Evaluation data

**Schema**:
- Full LLM metadata (model, tokens, cost, provider, request_id)
- Cascade context (session_id, cascade_id, cell_name, trace_id)
- Soundings data (candidate_index, is_winner, reforge_step)
- Mutations (mutation_applied, mutation_type, mutation_template)
- Semantic classification (semantic_actor, semantic_purpose)
- Callouts (is_callout, callout_name)
- Species hash (prompt DNA for evolution)
- Mermaid diagrams (execution graph)

---

## 4. ADVANCED FEATURES

### 4.1 Candidates (Tree of Thought)

**Basic Soundings**:
```yaml
candidates:
  factor: 5
  evaluator_instructions: "Pick the most creative response"
  mutate: true
  max_parallel: 3
```

**Dynamic Factor** (runtime-determined):
```yaml
candidates:
  factor: "{{ outputs.list_files.result | length }}"
  mode: aggregate
```

**Modes**:
- `evaluate` - Pick best (default)
- `aggregate` - Combine all outputs

**Mutation Types**:
- `rewrite` - LLM rewrites instructions
- `augment` - Prepend variation text
- `approach` - Append thinking strategy

**Multi-Model Soundings**:
```yaml
candidates:
  models:
    anthropic/claude-sonnet-4: {factor: 2}
    google/gemini-2.5-flash-lite: {factor: 3}
  model_strategy: round_robin  # or random, weighted
```

**Cost-Aware Evaluation**:
```yaml
candidates:
  cost_aware_evaluation:
    enabled: true
    quality_weight: 0.7
    cost_weight: 0.3
```

**Pareto Frontier**:
```yaml
candidates:
  pareto_frontier:
    enabled: true
    policy: balanced  # prefer_cheap, prefer_quality, interactive
```

**Pre-Evaluation Validator** (filter before evaluation):
```yaml
candidates:
  validator: "code_runs"
```

**Human Evaluation**:
```yaml
candidates:
  evaluator: human
  human_eval:
    presentation: side_by_side
    selection_mode: pick_one
    require_reasoning: true
```

### 4.2 Reforge (Iterative Refinement)

**Refine winning candidate**:
```yaml
candidates:
  factor: 5
  reforge:
    steps: 2
    honing_prompt: "Improve clarity and conciseness"
    factor_per_step: 3
    threshold:
      validator: quality_check
      mode: blocking
```

### 4.3 Wards (Validation)

**Modes**:
- `blocking` - Stop execution if validation fails
- `advisory` - Log warning, continue
- `retry` - Re-run cell if validation fails

**Types**:
```yaml
wards:
  pre:
    - validator: input_schema_check
      mode: blocking
  post:
    - validator: output_format_check
      mode: retry
      max_attempts: 3
  turn:
    - validator: safety_check
      mode: advisory
```

**Polyglot Validators**:
```yaml
wards:
  post:
    - validator:
        python: |
          result = {"valid": len(content) > 100, "reason": "Too short"}
      mode: blocking
```

### 4.4 loop_until (Retry Until Valid)

**Keep retrying until validator passes**:
```yaml
rules:
  loop_until: has_question
  loop_until_prompt: "You must formulate a clear question"
  loop_until_silent: false
  max_attempts: 5
```

### 4.5 Context System

**Explicit Mode**:
```yaml
context:
  from: ["all"]  # Explicit snowball
  # OR
  from: ["first", "previous", "specific_cell"]
  exclude: ["verbose_phase"]
  include_input: true
```

**Auto Mode** (LLM-assisted selection):
```yaml
context:
  mode: auto
  anchors:
    from_phases: ["research"]
    include: ["output", "callouts"]
  selection:
    strategy: hybrid  # heuristic, semantic, llm, hybrid
    max_tokens: 30000
```

**Intra-Phase Context** (per-turn within cell):
```yaml
intra_context:
  enabled: true
  window: 5  # Last N turns in full fidelity
  mask_observations_after: 3  # Mask tool results after N turns
  compress_loops: true  # Special handling for loop_until
```

**Context Source Config**:
```yaml
context:
  from:
    - cell: generate_chart
      include: ["images", "output"]
      images_filter: last
      as_role: user
```

### 4.6 Auto-Fix (Self-Healing)

**LLM-powered error recovery**:
```yaml
on_error: auto_fix
# OR
on_error:
  auto_fix:
    max_attempts: 2
    model: anthropic/claude-sonnet-4
    prompt: "Fix this code. Error: {{ error }}"
```

**Template Variables**: `{{ tool_type }}`, `{{ error }}`, `{{ original_code }}`, `{{ inputs }}`

### 4.7 Mapping Features

**1. Dynamic Candidates Factor**:
```yaml
candidates:
  factor: "{{ outputs.list_files.result | length }}"
  mode: aggregate
```

**2. map_cascade Tool**:
```yaml
- tool: map_cascade
  inputs:
    cascade: "traits/process_item.yaml"
    map_over: "{{ outputs.items }}"
    max_parallel: "10"
    mode: aggregate
```

**3. SQL-Native Mapping**:
```yaml
- for_each_row:
    table: _customers
    cascade: "traits/analyze_customer.yaml"
    inputs: {customer_id: "{{ row.id }}"}
    result_table: _results
```

**4. rvbbit_udf()**:
```sql
SELECT rvbbit_udf('Extract brand', product_name) FROM products
```

### 4.8 Human-in-the-Loop

**Basic Checkpoint**:
```yaml
human_input: true
```

**Custom UI**:
```yaml
human_input:
  type: choice
  prompt: "Which approach should I take?"
  options:
    - {label: "Approach A", value: "a"}
    - {label: "Approach B", value: "b"}
  timeout_seconds: 3600
  on_timeout: abort
```

**Generative UI** (LLM-generated interfaces):
```yaml
human_input:
  type: htmx
  hint: "Multi-step wizard for user onboarding"
```

**Decision Points** (LLM-driven):
```yaml
decision_points:
  enabled: true
  trigger: output  # or error, or both
  routing:
    _continue: next
    _retry: self
    escalate: manager_review
```

### 4.9 Audibles (Real-Time Feedback)

**Mid-phase steering**:
```yaml
audibles:
  enabled: true
  budget: 3
  allow_retry: true
  timeout_seconds: 120
```

### 4.10 Narrator (Voice Commentary)

**Poll Mode** (recommended):
```yaml
narrator:
  enabled: true
  mode: poll
  poll_interval_seconds: 3.0
  min_interval_seconds: 5.0
  context_turns: 5
  instructions: "Brief 1-2 sentence update. Call say()."
```

**Event Mode**:
```yaml
narrator:
  mode: event
  on_events: ["phase_complete", "cascade_complete"]
```

**Features**: Singleton (one narrator at time), debouncing, full context

### 4.11 Memory System

**Conversational memory banks**:
```yaml
memory: my_assistant
```

**Features**: Persistent across sessions, automatic message saving, skip losing soundings

### 4.12 Token Budget

**Context explosion prevention**:
```yaml
token_budget:
  max_total: 100000
  strategy: sliding_window  # or prune_oldest, summarize, fail
  warning_threshold: 0.8
```

### 4.13 Tool Caching

**Content-addressed caching**:
```yaml
tool_caching:
  enabled: true
  storage: memory  # or redis, sqlite
  global_ttl: 3600
  tools:
    sql_data:
      enabled: true
      key: sql_hash
```

### 4.14 RAG

**Context injection from documents**:
```yaml
rag:
  directory: docs
  recursive: true
  include: ["*.md", "*.txt"]
  chunk_chars: 1200
  model: "text-embedding-3-small"
```

### 4.15 Callouts (Semantic Tagging)

**Mark important messages**:
```yaml
callouts: "Key Result"  # Shorthand for output
# OR
callouts:
  output: "Research Summary for {{input.topic}}"
  messages: "Finding {{turn}}"
  messages_filter: assistant_only
```

### 4.16 Output Extraction

**Extract structured data from output**:
```yaml
output_extraction:
  pattern: "<scratchpad>(.*?)</scratchpad>"
  store_as: reasoning
  required: false
  format: text  # or json, code
```

### 4.17 Browser Automation

**Phase-scoped Rabbitize browser**:
```yaml
browser:
  url: "https://example.com"
  stability_detection: true
  show_overlay: true
  auto_screenshot_context: true
```

Injects tools: `control_browser`, `extract_page_content`

### 4.18 Triggers (Scheduling)

**Cron**:
```yaml
triggers:
  - name: daily_run
    type: cron
    schedule: "0 6 * * *"
    timezone: America/New_York
```

**Sensor** (polling):
```yaml
triggers:
  - name: on_data_ready
    type: sensor
    check: "python:sensors.table_freshness"
    poll_interval: 5m
```

**Webhook**:
```yaml
triggers:
  - name: on_payment
    type: webhook
    auth: "hmac:${WEBHOOK_SECRET}"
```

---

## 5. WEB DASHBOARD

### 5.1 Backend APIs

**Main App** (app.py - 271KB):
- Flask application with SSE streaming
- ~15 API modules integrated
- WebSocket support

**Key APIs**:
1. **sextant_api.py** (112KB) - Visual cascade builder
2. **studio_api.py** (62KB) - Advanced studio features
3. **browser_sessions_api.py** (53KB) - Rabbitize management
4. **execution_tree.py** (46KB) - Trace visualization
5. **artifacts_api.py** (38KB) - Multi-modal artifact handling
6. **message_flow_api.py** (30KB) - Message visualization
7. **notebook_api.py** (26KB) - Data Cascades notebook interface
8. **checkpoint_api.py** (25KB) - HITL checkpoint management
9. **sessions_api.py** (19KB) - Session management
10. **sql_query_api.py** (17KB) - SQL Query IDE

### 5.2 Frontend Views

**Three Main Interfaces**:

**1. SQL Query IDE** (`/sql-query`):
- **Query Mode**: Traditional SQL editor
  - Schema browser with table/column metadata
  - Result viewer (tables, JSON, CSV)
  - Query history
  - Export options
- **Notebook Mode** (`?mode=notebook`): Data Cascades
  - Polyglot cells (SQL, Python, JS, Clojure, RVBBIT)
  - Multi-modal output rendering
  - Auto-fix failed cells
  - Cell reordering
  - Real-time execution

**2. Playground Canvas** (`/playground`):
- Visual cascade builder
- Two-sided cell cards (front: output, back: YAML config)
- Stacked deck visualization for candidates
- Drag-and-drop node positioning
- Real-time execution with SSE updates
- Save/load cascades
- Mermaid diagram rendering
- Cost analytics overlay

**3. Session Explorer** (`/sessions`):
- Browse all execution sessions
- Filter by date, cascade, status
- View session details (inputs, outputs, cost)
- Execution graphs (Mermaid)
- Message flow visualization
- Candidate comparison
- Cost breakdown by session/cell/model

**Shared Components**:
- Checkpoint UI renderer
- Artifact viewer (images, charts, audio)
- Callout highlighter
- Species hash tracker (prompt evolution)

---

## 6. EXAMPLE CASCADES

**Basic Patterns**:
- simple_flow.json - Linear workflow
- loop_flow.yaml - Max turns demonstration
- template_flow.yaml - Jinja2 templating

**Routing & Context**:
- nested_parent.json - Sub-cascade spawning
- context_demo_parent.yaml - Selective context
- context_sugar_demo.yaml - "all", "previous", "first" keywords

**Candidates & Evaluation**:
- soundings_flow.yaml - Basic soundings with evaluator
- soundings_aggregate_demo.yaml - Aggregate mode
- reforge_*.json - Iterative refinement
- human_sounding_eval_demo.yaml - Human evaluation

**Validation**:
- ward_*.json - Pre/post validation
- loop_until_*.yaml - Retry until valid
- grammar_validation_flow.yaml - Output schema validation

**Tools & Manifest**:
- manifest_flow.yaml - Quartermaster auto-selection
- rabbitize_*.yaml - Browser automation
- hitl_flow.yaml - Human-in-the-loop
- declarative_tools_demo.yaml - .tool.json usage

**Voice**:
- voice_transcription_demo.yaml - Audio transcription
- voice_assistant_demo.yaml - TTS/STT integration
- voice_conversation_demo.yaml - Full conversation loop

**Dynamic Mapping**:
- test_dynamic_soundings.yaml - Dynamic candidates factor
- test_map_cascade.yaml - map_cascade tool
- map_with_soundings_demo.yaml - Candidates-as-mapping
- test_sql_mapping.yaml - for_each_row SQL mapping
- test_windlass_udf.yaml - rvbbit_udf() demonstration

**Data Cascades** (Notebooks):
- notebook_polyglot_showcase.yaml - SQL → Python → JS → Clojure → SQL
- notebook_llm_classification.yaml - LLM-powered classification
- notebook_etl_pipeline.yaml - Full ETL workflow
- notebook_llm_sentiment.yaml - Sentiment analysis
- notebook_llm_entity_extraction.yaml - NER

**Hybrid Workflows**:
- deterministic_demo.yaml - Tool-based cells
- hybrid_etl_demo.yaml - Mix LLM and deterministic
- signal_etl_hybrid.yaml - Deterministic ETL with LLM validation

**Generative UI**:
- htmx_demo.yaml - Basic HTMX generation
- htmx_wizard_demo.yaml - Multi-step wizard
- htmx_interactive_table.yaml - Interactive data table
- generative_ui_showcase.yaml - Full UI generation demo

---

## 7. EXECUTION FLOW

**High-Level**:
```
run_cascade()
  ├─ Load Cascade Config (Pydantic validation)
  ├─ Get/Create Echo (session state)
  ├─ Initialize Token Budget, Tool Cache, Memory
  ├─ Start Heartbeat, Narrator
  │
  ├─ For each cell:
  │   ├─ Build context (selective/auto)
  │   ├─ Execute cell:
  │   │   ├─ LLM Cell: run_cell()
  │   │   │   ├─ Render instructions (Jinja2)
  │   │   │   ├─ Get tools (Quartermaster or explicit)
  │   │   │   ├─ Turn loop (max_turns)
  │   │   │   └─ Check loop_until/wards
  │   │   │
  │   │   ├─ Deterministic Cell: execute_deterministic_phase()
  │   │   │   ├─ Resolve tool function
  │   │   │   ├─ Render inputs (Jinja2)
  │   │   │   ├─ Execute with retry/timeout
  │   │   │   └─ Determine routing
  │   │   │
  │   │   ├─ SQL Mapping: execute_sql_mapping()
  │   │   │   ├─ Query temp table rows
  │   │   │   ├─ Spawn cascade per row (parallel)
  │   │   │   └─ Materialize result_table
  │   │   │
  │   │   └─ Candidates: run_soundings()
  │   │       ├─ Spawn N parallel executions
  │   │       ├─ Apply mutations
  │   │       ├─ Run evaluator (pick winner OR aggregate)
  │   │       └─ Reforge (optional)
  │   │
  │   ├─ Save output to Echo.lineage
  │   ├─ Check wards (post)
  │   ├─ Handle human_input checkpoints
  │   └─ Route to next cell (handoffs)
  │
  └─ Return final result
```

**Data Flow**:
```
Input → Cell 1 (LLM) → state/lineage
                    ↓
     Cell 2 (deterministic) → temp table (_cell1)
                    ↓
     Cell 3 (SQL) reads _cell1 → temp table (_cell3)
                    ↓
     Cell 4 (LLM) references {{ outputs.cell3 }}
                    ↓
                 Final Output
```

**Logging Pipeline**:
```
Echo.add_history()
  ├─ Enrich with metadata
  ├─ Generate Mermaid diagram
  ├─ Emit SSE events
  ├─ Queue context card generation
  └─ log_unified() → Parquet → chDB/ClickHouse
```

---

## 8. TERMINOLOGY (Nautical Theme)

- **Cascades** - Workflows/journeys
- **Cells** - Phases/stages
- **Traits** - Tools and functions
- **Eddies** - Smart tools with resilience
- **Echoes** - State/history
- **Candidates** (formerly Soundings) - Parallel attempts
- **Reforge** - Iterative refinement
- **Wards** - Validation barriers
- **Manifest** - List of available traits
- **Quartermaster** - Agent that selects traits
- **Harbor** - HuggingFace Spaces registry
- **Berth** - Specific HF Space connection

---

## 9. CONFIGURATION

**Required Environment Variables**:
- `OPENROUTER_API_KEY` - OpenRouter API key

**Optional Overrides**:
- `RVBBIT_ROOT` - Workspace root (default: current directory)
- `RVBBIT_PROVIDER_BASE_URL` - API base URL
- `RVBBIT_DEFAULT_MODEL` - Default model (default: gemini-2.5-flash-lite)
- `RVBBIT_DEFAULT_EMBED_MODEL` - Embedding model

**Data Directories** (derived from RVBBIT_ROOT):
- `RVBBIT_DATA_DIR` - Unified logs (Parquet)
- `RVBBIT_LOG_DIR` - Legacy logs
- `RVBBIT_GRAPH_DIR` - Mermaid diagrams
- `RVBBIT_STATE_DIR` - Session state JSON
- `RVBBIT_IMAGE_DIR` - Multi-modal images

**Voice**:
- `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` - TTS
- `RVBBIT_STT_API_KEY`, `RVBBIT_STT_BASE_URL`, `RVBBIT_STT_MODEL` - STT

**Database**:
- `RVBBIT_USE_CLICKHOUSE_SERVER=true` - Use ClickHouse server
- `RVBBIT_CLICKHOUSE_HOST` - ClickHouse server host

**HuggingFace**:
- `HF_TOKEN` - HuggingFace API token for Harbor

---

This catalog covers all major capabilities of the RVBBIT framework as of 2025-12-27.
