# Core Concepts


Understanding the fundamental building blocks of LARS: Cascades, Cells,
  State, Context, and the execution model.
On This Page
- [Cascades](#cascades)
- [Cells](#cells)
- [State & Echo](#state-echo)
- [Context System](#context)
- [Execution Flow](#execution)
- [Nautical Terminology](#terminology)


## Cascades


A **Cascade** is the top-level workflow definition. It's a declarative
  JSON or YAML file that describes a multi-step process composed of cells.

### Cascade Structure


```yaml structure
cascade_id: unique_workflow_name
description: Human-readable description (optional)

# Input schema defines expected parameters
inputs_schema:
  param_name: "Description of this parameter"
  another_param: "Another input parameter"

# Cells are the execution stages
cells:
  - name: first_cell
    instructions: "Do something with {{ input.param_name }}"
    skills: [tool_name]
    handoffs: [second_cell]

  - name: second_cell
    instructions: "Process results from previous cell"
    context:
      from: [first_cell]
```

### Key Properties


| Property        | Type   | Description                                     |
|-----------------|--------|-------------------------------------------------|
| `cascade_id`    | string | Unique identifier for the cascade (required)    |
| `description`   | string | Human-readable description (optional)           |
| `inputs_schema` | object | Expected input parameters with descriptions     |
| `cells`         | array  | List of execution cells (at least one required) |
| `research_db`   | string | Name for persistent DuckDB database (optional)  |
| `triggers`      | array  | Scheduling and event triggers (optional)        |
| `narrator`      | object | Voice narration config (optional)               |


> **TIP: Cascades as Tools**
>
> 
> If a cascade has an `inputs_schema`, it's automatically registered
>     as a callable tool! Other cascades can invoke it using the `spawn_cascade`
>     or `map_cascade` tools.
> 


## Cells


**Cells** are the atomic units of execution within a cascade.
  Each cell performs a single logical operation and can pass results to subsequent cells.

### Four Primary Cell Types


#### 1. LLM Cells (Agent Execution)


Traditional agentic cells powered by language models with tool calling.

```llm cell example
- name: research
  instructions: |
    Research {{ input.topic }} using available search tools.
    Summarize the key findings in 3-5 bullet points.
  
  skills:
    - brave_web_search
    - take_screenshot
  model: anthropic/claude-sonnet-4
  rules:
    max_turns: 5
    max_attempts: 2
```

#### 2. Deterministic Cells (Direct Tool Execution)


Execute tools directly without LLM mediation for predictable, fast operations.

```deterministic cell example
- name: load_data
  tool: sql_data
  tool_inputs:
    query: |
      SELECT * FROM {{ input.table_name }}
      WHERE created_at > '{{ input.start_date }}'
    
  timeout: 5m
  on_error: auto_fix
  routing:
    success: process_data
    error: handle_error
```

#### 3. HITL Screen Cells (Human Input)


Present HTML interfaces for human approval or input.

```hitl screen example
- name: review_results
  htmx: |
    <h2>Review Generated Report</h2>
    <div>{{ outputs.generate_report.content }}</div>
    <form hx-post="/api/checkpoints/{{ checkpoint_id }}/respond">
      <button name="response[action]" value="approve">Approve</button>
      <button name="response[action]" value="reject">Reject</button>
    </form>
  
  htmx_title: Review Report
  handoffs: [publish_report, regenerate]
```

#### 4. SQL Mapping Cells (Row Processing)


Process each row from a SQL query as a separate execution.

```sql mapping example
- name: process_users
  for_each_row:
    query: SELECT id, email FROM users WHERE active = true
    max_parallel: 5
  instructions: |
    Send welcome email to {{ row.email }}
    User ID: {{ row.id }}
  
  skills: [send_email]
```

### Cell Lifecycle
1. **Pre-validation**: Pre-execution wards check inputs (if configured)
2. **Execution**: LLM conversation loop or direct tool invocation
3. **Turn validation**: Per-turn wards validate each iteration (if configured)
4. **Post-validation**: Post-execution wards validate outputs (if configured)
5. **Routing**: Determine next cell based on handoffs and routing config
6. **State update**: Merge cell outputs into session state


## State & Echo


LARS maintains execution state through the **Echo** object,
  which tracks state, history, lineage, and metadata throughout a session.

### Echo Structure


```python - echo class
class Echo:
    """Container for session state and execution history."""

    state: Dict[str, Any]
        # Persistent key-value store across cells
        # Set via set_state() tool or cell outputs

    history: List[Dict]
        # Full message history (user, assistant, tool calls/results)
        # Accumulates within cells, selective between cells

    lineage: List[TraceNode]
        # Tree structure of all cells executed
        # Each node: cell name, inputs, outputs, cost, timing

    outputs: Dict[str, Any]
        # Latest output from each named cell
        # Accessible via {{ outputs.cell_name }}

    metadata: Dict[str, Any]
        # Session-level metadata (session_id, cascade_id, etc.)
```

### State Management


State can be modified in three ways:
- **Implicit**: Cell outputs automatically merge into `state`
- **Explicit**: Use `set_state()` tool to set specific keys
- **Sub-Cascade**: Child cascade state propagates via `context_out`


> **NOTE: State vs Outputs**
>
> 
> `{{ state.key }}` persists across the entire session,
>     while `{{ outputs.cell_name }}` references the specific output
>     of a named cell. State is for shared data, outputs are for cell-specific results.
> 


## Context System


LARS implements a two-level context management system to balance
  information availability with token efficiency.

### Level 1: Intra-Cell Context (Within a Cell)


Manages context accumulation during multi-turn conversations *within* a single cell.

```intra-cell context config
- name: research
  instructions: "Research the topic thoroughly"
  intra_context:
    enabled: true
    window: 5                    # Last 5 turns full fidelity
    mask_observations_after: 3  # Mask tool results after 3 turns
    compress_loops: true         # Compress retry attempts
    preserve_reasoning: true     # Keep thinking without tool calls
    preserve_errors: true        # Always keep error messages
```

### Level 2: Inter-Cell Context (Between Cells)


Controls what information from previous cells is included in subsequent cells.

#### Explicit Context (Default)


```explicit context
- name: analyze
  instructions: "Analyze the research findings"
  context:
    from: [research, data_load]  # Only include these cells
```

#### Auto Context (Intelligent Selection)


```auto context
- name: analyze
  instructions: "Analyze the research findings"
  context:
    mode: auto
    selection:
      strategy: hybrid         # heuristic, semantic, llm, hybrid
      max_tokens: 30000
      recency_weight: 0.3
      keyword_weight: 0.4
      similarity_threshold: 0.5
```

## Execution Flow


Understanding how LARS executes a cascade is key to building effective workflows.

### Execution Phases
1. **Initialization**
  - Load cascade definition
  - Validate configuration
  - Create session and Echo
  - Initialize ClickHouse logging
2. **Cell Execution Loop**
  - Select starting cell (first in list)
  - Render Jinja2 templates with context
  - Execute cell (LLM, deterministic, or HITL)
  - Run validation (wards)
  - Update Echo state and lineage
  - Determine next cell via routing
  - Repeat until completion or error
3. **Finalization**
  - Flush logs to ClickHouse
  - Generate execution graph (Mermaid)
  - Return final Echo with results


### Session & Trace IDs


Every execution is tracked with hierarchical IDs:
- **Session ID**: Top-level execution identifier (e.g., `session_123`)
- **Trace ID**: Unique per execution node, includes take/reforge suffixes:
  - `session_123` - Main session
  - `session_123_take_0` - First take
  - `session_123_reforge1_0` - First reforge attempt
  - `session_123_subcascade_analyze` - Sub-cascade named "analyze"


## Nautical Terminology


LARS uses a nautical theme for core concepts. Here's a quick reference:


| Term              | Meaning                                                    |
|-------------------|------------------------------------------------------------|
| **Cascade**       | The overall workflow/journey                               |
| **Cell**          | Individual execution stage (formerly "Phase")              |
| **Skills**        | Tools and functions available to cells (formerly "Tackle") |
| **Echo**          | State and history accumulated during execution             |
| **Takes**         | Parallel execution attempts (formerly "Takes")             |
| **Reforge**       | Iterative refinement of winning take                       |
| **Wards**         | Protective validation barriers                             |
| **Manifest**      | Registry of available tools                                |
| **Quartermaster** | Agent that dynamically selects appropriate tools           |
| **Harbor**        | HuggingFace Spaces integration system                      |
| **Berth**         | Specific HF Space connection (tool definition)             |
| **Calliope**      | Conversational cascade builder (muse of epic poetry)       |


> **TIP: Why Nautical Terms?**
>
> 
> The nautical theme reflects LARS's philosophy: workflows are journeys through
>     uncertain waters, with tools as tackle, validation as protective wards,
>     and parallel attempts as takes to find the best route.
> 


## Next: Cascade DSL Reference


Now that you understand the core concepts, dive into the complete
  [Cascade DSL Reference](#cascade-dsl) to learn about all
  available configuration options.
