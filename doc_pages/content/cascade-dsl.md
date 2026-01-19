# Cascade DSL Reference


Complete reference for the Cascade configuration DSL. All properties, types,
  and examples for defining workflows.
On This Page
- [Cascade-Level Properties](#cascade-level)
- [Cell Configuration](#cell-config)
- [Jinja2 Templating](#jinja2)
- [Routing & Handoffs](#routing)
- [Triggers](#triggers)


## Cascade-Level Properties


| Property        | Type   | Required | Description                             |
|-----------------|--------|----------|-----------------------------------------|
| `cascade_id`    | string | Yes      | Unique identifier for the cascade       |
| `description`   | string | No       | Human-readable description              |
| `inputs_schema` | object | No       | Parameter definitions with descriptions |
| `cells`         | array  | Yes      | List of cell configurations             |
| `research_db`   | string | No       | DuckDB database name for research tools |
| `triggers`      | array  | No       | Scheduling/event triggers               |
| `narrator`      | object | No       | Voice narration configuration           |


## Cell Configuration


### Common Properties


```cell structure
cells:
  - name: cell_name           # Required: unique identifier
    instructions: "..."       # LLM cells: system prompt
    tool: tool_name            # Deterministic cells: direct tool
    skills: [tool1, tool2]     # Available tools for this cell
    model: "provider/model"   # Override default model
    handoffs: [next1, next2]   # Possible next cells
    rules:                     # Execution constraints
      max_turns: 5
      max_attempts: 2
    context:                   # Inter-cell context
      from: [other_cell]
    wards: []                  # Validation rules
    takes: {}             # Parallel execution config
```

### LLM Cell Properties


| Property           | Type               | Description                                        |
|--------------------|--------------------|----------------------------------------------------|
| `instructions`     | string             | Jinja2-templated system prompt                     |
| `skills`           | array | "manifest" | Tools available or dynamic selection               |
| `model`            | string             | Model override (e.g., "anthropic/claude-sonnet-4") |
| `rules.max_turns`  | integer            | Max conversation turns (default: 10)               |
| `rules.loop_until` | string             | Condition to repeat cell execution                 |
| `intra_context`    | object             | Within-cell context management                     |
| `output_schema`    | object             | JSON schema for structured output                  |


### Deterministic Cell Properties


| Property      | Type            | Description                                       |
|---------------|-----------------|---------------------------------------------------|
| `tool`        | string          | Tool to invoke directly                           |
| `tool_inputs` | object          | Jinja2-templated inputs for the tool              |
| `timeout`     | string          | Execution timeout (e.g., "5m", "30s")             |
| `on_error`    | string | object | Error handling ("auto_fix", cell name, or config) |
| `retry`       | object          | Retry configuration (max_attempts, backoff)       |


## Jinja2 Templating


All string values support Jinja2 templating with these variables:

```available variables
# Input data (from cascade invocation)
{{ input.variable_name }}

# Persistent session state
{{ state.variable_name }}

# Previous cell outputs
{{ outputs.cell_name }}
{{ outputs.cell_name.field }}

# Execution context
{{ lineage }}
{{ history }}

# Take context
{{ take_index }}      # Current take (0, 1, 2...)
{{ take_factor }}     # Total takes
{{ is_take }}         # True when running as take

# HITL context
{{ checkpoint_id }}
```

## Routing & Handoffs


### Static Handoffs


```static routing
handoffs: [analyze, report]  # LLM chooses via route_to tool
```

### Conditional Routing


```conditional routing
routing:
  success: process_data
  error: handle_error
  default: fallback_cell
```

## Triggers


```trigger types
triggers:
  # Cron-based scheduling
  - name: daily_run
    type: cron
    schedule: "0 6 * * *"
    timezone: America/New_York
    inputs: {mode: full}

  # Sensor-based (polling)
  - name: on_data_ready
    type: sensor
    check: "python:sensors.table_freshness"
    args: {table: raw.events, max_age_minutes: 60}
    poll_interval: 5m

  # Webhook
  - name: on_webhook
    type: webhook
    auth: "hmac:${WEBHOOK_SECRET}"
```

## Next: Cell Types


Learn more about the different [Cell Types](#cell-types)
  and their specific configurations.
