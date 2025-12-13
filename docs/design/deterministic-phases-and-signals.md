# Deterministic Phases & Signals System

> Design document for extending Windlass with deterministic execution and unified signal primitives.

## Executive Summary

This proposal adds two complementary capabilities to Windlass:

1. **Deterministic Phases** - Execute Python/SQL directly without LLM invocation
2. **Signals System** - Unified primitive for "wait until condition" (generalizes HITL)

These additions are **non-invasive** - existing LLM-based cascades work unchanged. The goal is to position Windlass as a **hybrid intelligent/deterministic workflow engine** suitable for data engineering use cases while preserving its LLM-native strengths.

---

## Table of Contents

1. [Design Philosophy](#design-philosophy)
2. [Deterministic Phases](#deterministic-phases)
3. [Signals System](#signals-system)
4. [Triggers (Cascade-Level)](#triggers-cascade-level)
5. [Implementation Plan](#implementation-plan)
6. [Schema Changes](#schema-changes)
7. [Examples](#examples)
8. [Future Possibilities](#future-possibilities)

---

## Design Philosophy

### The Hybrid Model

Traditional pipelines are fully deterministic - predictable but brittle. Pure LLM workflows are adaptive but unpredictable. The sweet spot is **hybrid**:

```
┌────────────────────────────────────────────────────────────────┐
│                      Windlass Phase Types                       │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Deterministic          Hybrid              LLM                │
│   ─────────────          ──────              ───                │
│   Pure function          Deterministic       Full agent         │
│   No LLM calls           with LLM fallback   reasoning          │
│   Predictable            Resilient           Adaptive           │
│   Cheap                  Cost-controlled     Expensive          │
│                                                                 │
│   Use for:               Use for:            Use for:           │
│   - ETL transforms       - Parsing with      - Error triage     │
│   - Schema validation      fallback          - Dynamic routing  │
│   - Data loading         - Validation with   - Content gen      │
│   - File operations        auto-fix          - Complex reasoning│
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### The Signal Abstraction

Windlass already has HITL tools (`ask_human`, `ask_human_custom`) that block execution until human input arrives. This is a specific case of a general pattern:

```
Signal = a condition that can be:
  - Checked  (poll)    → "is condition met?"
  - Awaited  (block)   → "wait until condition met"
  - Received (push)    → "external system says condition met"
```

By unifying HITL, sensors, and webhooks under "Signals", we get:
- Consistent timeout/fallback handling
- Unified state persistence (resume after crash)
- Single observability model
- Composable conditions

---

## Deterministic Phases

### Overview

A deterministic phase executes code directly without LLM invocation. It:
- Calls a Python function or SQL query
- Receives templated inputs (Jinja2, like LLM phases)
- Returns structured output to state/outputs
- Can route to next phase based on return value
- Logs to unified_logs (same observability as LLM phases)

### Phase Schema

```json
{
  "name": "transform_records",
  "type": "deterministic",
  "run": "python:mymodule.transforms.clean_records",
  "inputs": {
    "records": "{{ outputs.fetch_data.records }}",
    "schema_version": "{{ input.schema_version | default('v2') }}"
  },
  "outputs": {
    "cleaned": "$.cleaned_records",
    "error_count": "$.stats.errors"
  },
  "handoffs": ["load_warehouse", "handle_errors"],
  "routing": {
    "success": "load_warehouse",
    "has_errors": "handle_errors"
  },
  "on_error": "error_triage"
}
```

### Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Phase identifier |
| `type` | `"deterministic"` | yes | Marks as deterministic phase |
| `run` | string | yes | Execution target (see Run Targets below) |
| `inputs` | object | no | Jinja2 templates mapping param names to values |
| `outputs` | object | no | JSONPath mappings to extract from result |
| `handoffs` | array | no | Valid next phases |
| `routing` | object | no | Maps return status to handoff |
| `on_error` | string | no | Phase to route to on exception |
| `timeout` | string | no | Max execution time (e.g., "5m", "1h") |
| `retry` | object | no | Retry configuration |

### Run Targets

#### Python Functions

```
"run": "python:module.path.function_name"
```

- Module is imported dynamically
- Function receives `**inputs` as keyword arguments
- Function can be sync or async
- Return value becomes phase output

**Function signature options:**

```python
# Simple - just inputs
def transform(records: list, schema_version: str) -> dict:
    return {"cleaned_records": [...], "stats": {"errors": 0}}

# With context - receives echo for state access
def transform(records: list, *, _echo: Echo) -> dict:
    previous = _echo.state.get("last_run")
    return {...}

# Async
async def transform(records: list) -> dict:
    async with aiohttp.ClientSession() as session:
        ...
```

#### SQL Queries

```
"run": "sql:queries/transform.sql"
```

- Path relative to cascade file or WINDLASS_ROOT
- Query can use Jinja2 templating
- Executed via configured database backend
- Result returned as list of dicts

```sql
-- queries/transform.sql
SELECT
    id,
    cleaned_value,
    CASE WHEN error IS NOT NULL THEN 'has_errors' ELSE 'success' END as _route
FROM {{ inputs.source_table }}
WHERE date = '{{ inputs.date }}'
```

#### Shell Commands

```
"run": "shell:scripts/transform.sh"
```

- Script receives inputs as environment variables
- Exit code 0 = success, non-zero = error
- Stdout captured as output

### Routing Logic

Deterministic routing based on return value:

```json
{
  "routing": {
    "success": "next_phase",
    "has_errors": "error_handler",
    "empty": "skip_to_end"
  }
}
```

The routing key is determined by (in order):
1. `result["_route"]` if present
2. `result["status"]` if present
3. `"success"` if no errors
4. `"error"` on exception

### Hybrid Phases (Deterministic + LLM Fallback)

```json
{
  "name": "parse_invoice",
  "type": "deterministic",
  "run": "python:parsers.structured_parse",
  "inputs": {"document": "{{ input.document }}"},

  "on_error": {
    "type": "llm",
    "instructions": "Structured parsing failed: {{ error.message }}\n\nExtract invoice data from:\n{{ error.inputs.document }}",
    "tackle": ["extract_structured"],
    "output_schema": {"$ref": "schemas/invoice.json"}
  }
}
```

When the deterministic function raises an exception or returns an error status, the embedded LLM phase takes over. This gives you:
- Fast, cheap execution for well-formed inputs
- Intelligent fallback for edge cases
- Cost control (LLM only when needed)

---

## Signals System

### Overview

Signals unify all "wait for condition" patterns under one abstraction:

| Signal Type | Check Method | Current Windlass | Use Case |
|-------------|--------------|------------------|----------|
| `human` | UI interaction | `ask_human` tool | Approvals, reviews, input |
| `sensor` | Polling function | (new) | Data freshness, file existence |
| `webhook` | HTTP push | (new) | External system events |
| `time` | Cron/delay | (new) | Scheduled waits |
| `composite` | Multiple signals | (new) | Complex conditions |

### Signal Definitions

Signals are defined at cascade level and referenced by name:

```json
{
  "cascade_id": "approval_workflow",

  "signals": {
    "data_ready": {
      "type": "sensor",
      "check": "python:sensors.check_table_freshness",
      "args": {"table": "staging.prepared", "max_age_minutes": 60},
      "poll_interval": "5m"
    },

    "manager_approval": {
      "type": "human",
      "prompt": "Review the prepared data and approve for loading",
      "ui": "approval_form",
      "allowed_responses": ["approve", "reject", "request_changes"]
    },

    "downstream_ack": {
      "type": "webhook",
      "description": "Downstream system acknowledges receipt"
    },

    "business_hours": {
      "type": "time",
      "cron": "* 9-17 * * 1-5",
      "timezone": "America/New_York"
    },

    "ready_for_prod": {
      "type": "composite",
      "all": ["data_ready", "manager_approval", "business_hours"]
    }
  },

  "phases": [...]
}
```

### Signal Phase Type

A phase that purely waits for a signal:

```json
{
  "name": "await_approval",
  "type": "signal",
  "await": "manager_approval",
  "timeout": "24h",
  "on_timeout": "auto_escalate",
  "on_signal": {
    "approve": "load_to_prod",
    "reject": "archive_and_notify",
    "request_changes": "revision_phase"
  }
}
```

### Signal Tools (for LLM phases)

Signals can also be checked/awaited from within LLM phases:

```python
# Built-in signal tools
"tackle": ["check_signal", "await_signal", "emit_signal"]
```

```json
{
  "name": "intelligent_waiter",
  "type": "llm",
  "instructions": "Check if data is ready. If not, determine whether to wait or try alternative source.",
  "tackle": ["check_signal", "await_signal", "fetch_from_backup"],
  "handoffs": ["process_data", "use_backup"]
}
```

The LLM can decide whether to wait, how long, or whether to try an alternative.

### Signal Type Specifications

#### Human Signals

```json
{
  "type": "human",
  "prompt": "Review and approve the generated report",
  "ui": "approval_form",
  "ui_config": {
    "show_diff": true,
    "require_comment_on_reject": true
  },
  "allowed_responses": ["approve", "reject"],
  "notify": ["email:manager@company.com", "slack:#approvals"]
}
```

This generalizes and extends the existing `ask_human` / `ask_human_custom` tools. The existing tools become convenience wrappers around human signals.

#### Sensor Signals

```json
{
  "type": "sensor",
  "check": "python:sensors.table_freshness",
  "args": {
    "table": "{{ input.source_table }}",
    "max_age_minutes": 60
  },
  "poll_interval": "5m",
  "poll_jitter": "30s",
  "max_polls": 24
}
```

**Built-in sensor functions:**

```python
# windlass/sensors.py

def table_freshness(table: str, max_age_minutes: int) -> bool:
    """Check if table was updated within max_age_minutes."""

def file_exists(path: str, min_size_bytes: int = 0) -> bool:
    """Check if file exists and meets size threshold."""

def s3_object_exists(bucket: str, key: str) -> bool:
    """Check if S3 object exists."""

def http_healthy(url: str, expected_status: int = 200) -> bool:
    """Check if HTTP endpoint returns expected status."""

def query_returns_rows(query: str, min_rows: int = 1) -> bool:
    """Check if SQL query returns at least min_rows."""
```

#### Webhook Signals

```json
{
  "type": "webhook",
  "description": "Payment processor confirms transaction",
  "schema": {
    "type": "object",
    "properties": {
      "transaction_id": {"type": "string"},
      "status": {"enum": ["success", "failed"]}
    }
  },
  "auth": "hmac:{{ env.WEBHOOK_SECRET }}"
}
```

Webhook signals generate an endpoint:
```
POST /signals/{cascade_id}/{session_id}/{signal_name}
```

The endpoint:
- Validates auth (HMAC, API key, etc.)
- Validates payload against schema
- Fires the signal with payload as data
- Returns 200 OK

#### Time Signals

```json
{
  "type": "time",
  "delay": "30m"
}
```

```json
{
  "type": "time",
  "cron": "0 9 * * 1-5",
  "timezone": "America/New_York"
}
```

```json
{
  "type": "time",
  "after": "2024-01-15T09:00:00Z"
}
```

#### Composite Signals

```json
{
  "type": "composite",
  "all": ["data_ready", "manager_approval"]
}
```

```json
{
  "type": "composite",
  "any": ["primary_source_ready", "backup_source_ready"]
}
```

```json
{
  "type": "composite",
  "all": ["data_ready"],
  "any": ["auto_approval_window", "manual_approval"]
}
```

### Signal State Persistence

Signals must survive runner restarts. State stored in session state file:

```json
{
  "session_id": "abc123",
  "signal_state": {
    "data_ready": {
      "status": "waiting",
      "started_at": "2024-01-15T10:00:00Z",
      "polls": 5,
      "last_poll": "2024-01-15T10:25:00Z"
    },
    "manager_approval": {
      "status": "received",
      "received_at": "2024-01-15T10:30:00Z",
      "response": "approve",
      "responder": "manager@company.com"
    }
  }
}
```

On restart, runner checks signal state and resumes waiting or continues if already received.

---

## Triggers (Cascade-Level)

Triggers define what starts a cascade. They're separate from signals (which gate phases within a cascade).

```json
{
  "cascade_id": "daily_etl",

  "triggers": [
    {
      "name": "scheduled",
      "type": "cron",
      "schedule": "0 6 * * *",
      "timezone": "America/New_York",
      "inputs": {"mode": "full"}
    },
    {
      "name": "on_data_arrival",
      "type": "signal",
      "signal": "source_data_updated",
      "inputs": {"mode": "incremental"}
    },
    {
      "name": "manual",
      "type": "manual",
      "inputs_schema": {"mode": {"enum": ["full", "incremental"]}}
    }
  ],

  "signals": {
    "source_data_updated": {
      "type": "sensor",
      "check": "python:sensors.table_freshness",
      "args": {"table": "raw.events"}
    }
  },

  "phases": [...]
}
```

### Trigger Export

Windlass doesn't run a scheduler daemon. Instead, it exports trigger definitions to external schedulers:

```bash
# Export to cron
windlass triggers export daily_etl.json --format cron
# Output: 0 6 * * * cd /path && windlass daily_etl.json --input '{"mode":"full"}' --trigger scheduled

# Export to systemd timer
windlass triggers export daily_etl.json --format systemd > /etc/systemd/system/windlass-daily.timer

# Export to Kubernetes CronJob
windlass triggers export daily_etl.json --format kubernetes > k8s/cronjob.yaml

# Export to Airflow DAG (generates Python file)
windlass triggers export daily_etl.json --format airflow > dags/daily_etl.py
```

### Sensor Daemon Mode

For signal-based triggers, Windlass can run in sensor daemon mode:

```bash
# Run sensor checks for a cascade, execute when triggered
windlass daemon daily_etl.json --triggers on_data_arrival

# Run sensor checks for all cascades in directory
windlass daemon ./cascades/ --poll-interval 5m
```

The daemon:
1. Loads cascade definitions
2. Runs sensor checks at poll intervals
3. When sensor fires, executes cascade with trigger's inputs
4. Logs all activity to unified_logs

---

## Implementation Plan

### Phase 1: Deterministic Phases (Foundation)

**Goal:** Execute Python functions as phases without LLM.

**Files to modify:**
- `windlass/cascade.py` - Add `type`, `run`, `inputs`, `routing` fields to Phase model
- `windlass/runner.py` - Add branch for deterministic execution

**New files:**
- `windlass/deterministic.py` - Deterministic phase execution logic (~150 lines)

**Tasks:**
1. Extend Phase Pydantic model with deterministic fields
2. Add `_run_deterministic_phase()` method to WindlassRunner
3. Implement Python target parsing and execution
4. Implement input rendering (Jinja2)
5. Implement routing logic
6. Add deterministic flag to unified_logs entries
7. Write tests for deterministic phases

**Estimated scope:** ~200 lines new code, ~50 lines modified

### Phase 2: Hybrid Phases (Fallback)

**Goal:** Deterministic phases with LLM fallback on error.

**Files to modify:**
- `windlass/cascade.py` - Add `on_error` field supporting embedded LLM phase
- `windlass/runner.py` - Handle fallback logic
- `windlass/deterministic.py` - Error capture and fallback trigger

**Tasks:**
1. Extend Phase model for `on_error` embedded phase
2. Implement error capture with context preservation
3. Implement fallback phase execution
4. Add fallback events to observability
5. Write tests for hybrid phases

**Estimated scope:** ~100 lines new code, ~30 lines modified

### Phase 3: Triggers (Scheduling)

**Goal:** Declarative trigger definitions with export.

**Files to modify:**
- `windlass/cascade.py` - Add Trigger models and `triggers` field to Cascade
- `windlass/cli.py` - Add `triggers` subcommand

**New files:**
- `windlass/triggers.py` - Trigger parsing and export logic (~200 lines)

**Tasks:**
1. Define Trigger Pydantic models (CronTrigger, etc.)
2. Add triggers field to Cascade model
3. Implement export formatters (cron, systemd, k8s, airflow)
4. Add CLI commands for trigger management
5. Write tests for trigger export

**Estimated scope:** ~250 lines new code, ~30 lines modified

### Phase 4: Signals (Core)

**Goal:** Unified signal primitive for waiting on conditions.

**Files to modify:**
- `windlass/cascade.py` - Add Signal models and `signals` field
- `windlass/runner.py` - Signal phase handling
- `windlass/echo.py` - Signal state persistence

**New files:**
- `windlass/signals.py` - Signal checking, awaiting, state management (~300 lines)
- `windlass/sensors.py` - Built-in sensor functions (~100 lines)

**Tasks:**
1. Define Signal Pydantic models (HumanSignal, SensorSignal, etc.)
2. Add signals field to Cascade model
3. Implement signal phase type
4. Implement signal state persistence in Echo
5. Implement sensor polling logic
6. Add built-in sensor functions
7. Create signal tools for LLM phases
8. Write tests for signals

**Estimated scope:** ~400 lines new code, ~50 lines modified

### Phase 5: HITL Integration

**Goal:** Unify existing HITL tools with signal system.

**Files to modify:**
- `windlass/eddies/human.py` - Refactor to use signal primitives
- `windlass/signals.py` - Human signal handling

**Tasks:**
1. Refactor `ask_human` to use human signal internally
2. Refactor `ask_human_custom` to use human signal with UI config
3. Ensure backward compatibility with existing cascades
4. Add human signal UI components
5. Write migration tests

**Estimated scope:** ~100 lines modified, ~50 lines new

### Phase 6: Webhooks & Daemon

**Goal:** Webhook signal receivers and sensor daemon mode.

**New files:**
- `windlass/webhook.py` - Webhook endpoint handling (~150 lines)
- `windlass/daemon.py` - Sensor daemon mode (~200 lines)

**Files to modify:**
- `windlass/cli.py` - Add daemon command
- `windlass/signals.py` - Webhook signal type

**Tasks:**
1. Implement webhook endpoint server (lightweight, Flask/FastAPI)
2. Implement webhook auth (HMAC, API key)
3. Implement daemon mode for sensor polling
4. Add daemon CLI command
5. Write integration tests

**Estimated scope:** ~350 lines new code, ~50 lines modified

### Phase 7: Composite Signals & Polish

**Goal:** Complex signal conditions and production hardening.

**Tasks:**
1. Implement composite signal logic (all/any)
2. Add signal timeout handling
3. Add notification integrations (email, Slack)
4. Performance optimization for polling
5. Documentation and examples
6. Integration tests for complex workflows

**Estimated scope:** ~200 lines new code, comprehensive tests

---

## Schema Changes

### Extended Phase Model

```python
class Phase(BaseModel):
    name: str
    type: Literal["llm", "deterministic", "signal"] = "llm"

    # LLM phase fields (existing)
    instructions: Optional[str] = None
    model: Optional[str] = None
    tackle: Optional[Union[List[str], Literal["manifest"]]] = None
    handoffs: Optional[List[str]] = None
    rules: Optional[PhaseRules] = None
    soundings: Optional[SoundingsConfig] = None
    wards: Optional[WardsConfig] = None
    context: Optional[ContextConfig] = None
    output_schema: Optional[Dict] = None

    # Deterministic phase fields (new)
    run: Optional[str] = None
    inputs: Optional[Dict[str, str]] = None
    outputs: Optional[Dict[str, str]] = None
    routing: Optional[Dict[str, str]] = None
    on_error: Optional[Union[str, "Phase"]] = None
    timeout: Optional[str] = None
    retry: Optional[RetryConfig] = None

    # Signal phase fields (new)
    await_signal: Optional[str] = Field(None, alias="await")
    on_signal: Optional[Dict[str, str]] = None
    on_timeout: Optional[str] = None
```

### Signal Models

```python
class SensorSignal(BaseModel):
    type: Literal["sensor"] = "sensor"
    check: str
    args: Dict[str, Any] = {}
    poll_interval: str = "5m"
    poll_jitter: str = "0s"
    max_polls: Optional[int] = None

class HumanSignal(BaseModel):
    type: Literal["human"] = "human"
    prompt: str
    ui: Optional[str] = None
    ui_config: Optional[Dict] = None
    allowed_responses: Optional[List[str]] = None
    notify: Optional[List[str]] = None

class WebhookSignal(BaseModel):
    type: Literal["webhook"] = "webhook"
    description: Optional[str] = None
    schema: Optional[Dict] = None
    auth: Optional[str] = None

class TimeSignal(BaseModel):
    type: Literal["time"] = "time"
    delay: Optional[str] = None
    cron: Optional[str] = None
    after: Optional[str] = None
    timezone: str = "UTC"

class CompositeSignal(BaseModel):
    type: Literal["composite"] = "composite"
    all: Optional[List[str]] = None
    any: Optional[List[str]] = None

Signal = Union[SensorSignal, HumanSignal, WebhookSignal, TimeSignal, CompositeSignal]
```

### Trigger Models

```python
class CronTrigger(BaseModel):
    name: str
    type: Literal["cron"] = "cron"
    schedule: str
    timezone: str = "UTC"
    inputs: Optional[Dict[str, Any]] = None

class SignalTrigger(BaseModel):
    name: str
    type: Literal["signal"] = "signal"
    signal: str
    inputs: Optional[Dict[str, Any]] = None

class ManualTrigger(BaseModel):
    name: str
    type: Literal["manual"] = "manual"
    inputs_schema: Optional[Dict] = None

Trigger = Union[CronTrigger, SignalTrigger, ManualTrigger]
```

### Extended Cascade Model

```python
class Cascade(BaseModel):
    cascade_id: str
    description: Optional[str] = None
    inputs_schema: Optional[Dict[str, str]] = None

    # New fields
    signals: Optional[Dict[str, Signal]] = None
    triggers: Optional[List[Trigger]] = None

    # Existing
    phases: List[Phase]
```

---

## Examples

### Example 1: Data Pipeline with Intelligent Error Handling

```json
{
  "cascade_id": "sales_etl",
  "description": "Daily sales data pipeline with intelligent error handling",

  "triggers": [
    {"name": "daily", "type": "cron", "schedule": "0 6 * * *"},
    {"name": "on_source", "type": "signal", "signal": "source_ready"}
  ],

  "signals": {
    "source_ready": {
      "type": "sensor",
      "check": "python:sensors.table_freshness",
      "args": {"table": "raw.sales", "max_age_minutes": 60}
    }
  },

  "phases": [
    {
      "name": "extract",
      "type": "deterministic",
      "run": "python:etl.sales.extract",
      "inputs": {"date": "{{ input.date | default('yesterday') }}"},
      "routing": {"success": "transform", "error": "extract_triage"},
      "timeout": "10m"
    },
    {
      "name": "extract_triage",
      "type": "llm",
      "instructions": "Sales extraction failed:\n{{ outputs.extract.error }}\n\nDiagnose and attempt recovery.",
      "tackle": ["linux_shell", "smart_sql_run", "set_state"],
      "handoffs": ["extract", "alert_oncall"],
      "rules": {"max_turns": 5}
    },
    {
      "name": "transform",
      "type": "deterministic",
      "run": "python:etl.sales.transform",
      "inputs": {"raw_data": "{{ outputs.extract.data }}"},
      "routing": {"success": "validate"}
    },
    {
      "name": "validate",
      "type": "deterministic",
      "run": "python:etl.sales.validate",
      "inputs": {"data": "{{ outputs.transform.data }}"},
      "routing": {"valid": "load", "invalid": "validation_fix"}
    },
    {
      "name": "validation_fix",
      "type": "llm",
      "instructions": "Validation errors:\n{{ outputs.validate.errors | tojson }}\n\nFix the data issues.",
      "tackle": ["run_code", "set_state"],
      "handoffs": ["load"],
      "output_schema": {"$ref": "schemas/sales_record.json"}
    },
    {
      "name": "load",
      "type": "deterministic",
      "run": "python:etl.sales.load",
      "inputs": {
        "data": "{{ state.fixed_data | default(outputs.transform.data) }}"
      }
    }
  ]
}
```

### Example 2: Approval Workflow with HITL

```json
{
  "cascade_id": "content_approval",
  "description": "Content generation with human approval gates",

  "signals": {
    "editorial_review": {
      "type": "human",
      "prompt": "Review the generated content for accuracy and tone",
      "ui": "content_review_form",
      "allowed_responses": ["approve", "reject", "edit"],
      "notify": ["slack:#content-reviews"]
    },
    "legal_review": {
      "type": "human",
      "prompt": "Review for legal compliance",
      "allowed_responses": ["approve", "flag_issues"]
    },
    "all_approvals": {
      "type": "composite",
      "all": ["editorial_review", "legal_review"]
    }
  },

  "phases": [
    {
      "name": "generate_draft",
      "type": "llm",
      "instructions": "Generate content based on: {{ input.brief }}",
      "tackle": ["web_search", "run_code"],
      "model": "anthropic/claude-sonnet-4"
    },
    {
      "name": "await_editorial",
      "type": "signal",
      "await": "editorial_review",
      "timeout": "48h",
      "on_signal": {
        "approve": "await_legal",
        "reject": "revision_needed",
        "edit": "apply_edits"
      },
      "on_timeout": "escalate_editorial"
    },
    {
      "name": "apply_edits",
      "type": "llm",
      "instructions": "Apply editor feedback:\n{{ signals.editorial_review.comments }}",
      "handoffs": ["await_editorial"]
    },
    {
      "name": "await_legal",
      "type": "signal",
      "await": "legal_review",
      "timeout": "72h",
      "on_signal": {
        "approve": "publish",
        "flag_issues": "legal_revision"
      }
    },
    {
      "name": "publish",
      "type": "deterministic",
      "run": "python:publishing.publish_content",
      "inputs": {"content": "{{ outputs.generate_draft.content }}"}
    }
  ]
}
```

### Example 3: Multi-Source Data with Webhook Triggers

```json
{
  "cascade_id": "event_processor",
  "description": "Process events from multiple sources",

  "triggers": [
    {"name": "stripe_webhook", "type": "signal", "signal": "stripe_event"},
    {"name": "shopify_webhook", "type": "signal", "signal": "shopify_event"},
    {"name": "batch_catchup", "type": "cron", "schedule": "0 * * * *"}
  ],

  "signals": {
    "stripe_event": {
      "type": "webhook",
      "auth": "hmac:{{ env.STRIPE_WEBHOOK_SECRET }}",
      "schema": {"$ref": "schemas/stripe_event.json"}
    },
    "shopify_event": {
      "type": "webhook",
      "auth": "hmac:{{ env.SHOPIFY_WEBHOOK_SECRET }}"
    }
  },

  "phases": [
    {
      "name": "route_event",
      "type": "deterministic",
      "run": "python:events.route_by_source",
      "inputs": {
        "source": "{{ input._trigger }}",
        "payload": "{{ input._signal_data }}"
      },
      "routing": {
        "payment": "process_payment",
        "order": "process_order",
        "unknown": "triage_unknown"
      }
    },
    {
      "name": "process_payment",
      "type": "deterministic",
      "run": "python:events.process_payment",
      "on_error": "payment_recovery"
    },
    {
      "name": "payment_recovery",
      "type": "llm",
      "instructions": "Payment processing failed:\n{{ outputs.process_payment.error }}\n\nAttempt recovery.",
      "tackle": ["stripe_api", "set_state", "alert_ops"]
    },
    {
      "name": "triage_unknown",
      "type": "llm",
      "instructions": "Unknown event type received:\n{{ input | tojson }}\n\nClassify and determine handling.",
      "tackle": ["smart_sql_run", "set_state"],
      "handoffs": ["process_payment", "process_order", "log_and_skip"]
    }
  ]
}
```

---

## Future Possibilities

### 1. Signal Marketplace

Pre-built signals for common data sources:
- `windlass-signals-aws`: S3, SQS, SNS, Glue signals
- `windlass-signals-gcp`: GCS, Pub/Sub, BigQuery signals
- `windlass-signals-dbt`: dbt Cloud job completion signals
- `windlass-signals-airbyte`: Airbyte sync completion signals

### 2. Visual Signal Builder

Extend the Workshop UI to visually define signals and see their status in real-time.

### 3. Signal Analytics

Track signal patterns over time:
- Average time to human approval
- Sensor false positive rates
- Webhook reliability by source

### 4. Distributed Signals

Signals that span multiple cascade instances:
- "Wait for all shards to complete"
- "Proceed when quorum of reviewers approve"

### 5. Signal-Based Backfill

```bash
windlass backfill sales_etl --from 2024-01-01 --to 2024-01-31 --skip-signals
```

Run historical data without waiting for signals (sensors return true, HITL auto-approves with audit log).

---

## Backward Compatibility

All changes are **additive**:

1. **Existing cascades work unchanged** - `type` defaults to `"llm"`
2. **Existing HITL tools work unchanged** - They become wrappers around human signals
3. **No required migration** - New fields are optional
4. **Gradual adoption** - Add deterministic phases one at a time

The only breaking change consideration:
- If a cascade already has a field named `type`, `run`, `signals`, or `triggers` in unexpected places, there could be conflicts. This is unlikely given current schema.

---

## Summary

This design extends Windlass from "agent framework" to "intelligent workflow engine" by adding:

1. **Deterministic phases** - Direct code execution for predictable operations
2. **Hybrid phases** - Deterministic with LLM fallback for resilience
3. **Signals** - Unified primitive for all "wait for condition" patterns
4. **Triggers** - Declarative scheduling with export to external systems

The result is a system where:
- Simple operations run without LLM overhead
- Complex situations invoke LLM reasoning
- Human approval is a first-class workflow primitive
- Data dependencies are explicit and observable
- Scheduling integrates with existing infrastructure

This positions Windlass as a credible alternative to Airflow for teams that want intelligent error handling without abandoning deterministic execution where it matters.
