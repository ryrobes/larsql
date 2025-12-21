# Deterministic Execution Reference

**Tool-Based Phases Without LLM Mediation**

Deterministic execution allows Windlass phases to bypass the LLM and execute tools directly. This enables **hybrid workflows** that combine traditional programmatic execution with LLM-powered intelligence, giving you the best of both worlds: predictable performance for routine operations and creative problem-solving for complex tasks.

## Overview

Traditional Windlass phases use an **LLM-in-the-loop** pattern:
1. LLM receives instructions
2. LLM chooses tools and parameters
3. Tool executes
4. Results return to LLM
5. LLM decides next action

**Deterministic phases** skip the LLM entirely:
1. Phase config specifies exact tool and inputs
2. Tool executes directly
3. Results flow to next phase
4. Optional routing based on tool output

**Benefits**:
- **Faster**: No LLM latency (10-100x faster)
- **Cheaper**: No LLM API costs
- **Predictable**: Same inputs = same outputs
- **Reliable**: No LLM hallucinations or tool-calling errors

**Location**: `windlass/deterministic.py` (517 lines)

## Basic Usage

### Syntax

Instead of `instructions` (which requires an LLM), use `tool`:

```yaml
phases:
  - name: "fetch_data"
    tool: "sql_data"  # Direct tool invocation
    inputs:
      query: "SELECT * FROM users LIMIT 10"
```

**What happens**:
1. Windlass loads `sql_data` tool from registry
2. Renders `inputs` using Jinja2 (access to `{{ input }}`, `{{ state }}`, `{{ outputs }}`)
3. Calls tool directly with rendered inputs
4. Stores result in `outputs.fetch_data`
5. Routes to next phase

**No LLM involved**: The entire execution is programmatic.

## Tool Resolution

Deterministic execution supports **four tool types**:

### 1. Registered Tools

Use any tool from the ToolRegistry:

```yaml
- name: "run_query"
  tool: "sql_data"
  inputs:
    query: "SELECT COUNT(*) FROM logs WHERE timestamp > NOW() - INTERVAL 1 DAY"
```

**Available tools**: Any tool registered via `register_tackle()`:
- Built-in: `sql_data`, `python_data`, `js_data`, `clojure_data`, `linux_shell`, `run_code`, `create_chart`, etc.
- Custom: User-defined functions registered in `__init__.py`
- Cascade tools: Any cascade in `tackle/` directory with `inputs_schema`

### 2. Python Imports

Import and call any Python function:

```yaml
- name: "process_data"
  tool: "python:my_module.data_processor.transform"
  inputs:
    data: "{{ outputs.fetch_data }}"
    config:
      normalize: true
      remove_outliers: true
```

**Resolution**:
1. Parses `python:my_module.data_processor.transform`
2. Executes `from my_module.data_processor import transform`
3. Calls `transform(data=..., config=...)`

**Requirements**:
- Module must be importable (on `PYTHONPATH` or installed)
- Function must accept kwargs matching `inputs`
- Function should return JSON-serializable data

### 3. SQL Files

Execute SQL queries from files:

```yaml
- name: "complex_query"
  tool: "sql:queries/analytics/daily_report.sql"
  inputs:
    start_date: "{{ input.start_date }}"
    end_date: "{{ input.end_date }}"
```

**Resolution**:
1. Reads `queries/analytics/daily_report.sql` (relative to `WINDLASS_ROOT`)
2. Renders SQL as Jinja2 template with `inputs` as context
3. Executes via DuckDB (or configured connection)
4. Returns DataFrame

**SQL File Example** (`queries/analytics/daily_report.sql`):
```sql
-- Daily report for {{ start_date }} to {{ end_date }}
SELECT
  DATE(timestamp) as date,
  COUNT(*) as events,
  SUM(cost) as total_cost
FROM logs
WHERE timestamp BETWEEN '{{ start_date }}' AND '{{ end_date }}'
GROUP BY DATE(timestamp)
ORDER BY date DESC
```

### 4. Shell Scripts

Execute bash scripts:

```yaml
- name: "backup_db"
  tool: "shell:scripts/backup.sh"
  inputs:
    database: "production"
    output_path: "/backups/{{ input.date }}"
```

**Resolution**:
1. Reads `scripts/backup.sh`
2. Renders as Jinja2 template with `inputs` as context
3. Executes via bash
4. Returns `{"stdout": "...", "stderr": "...", "exit_code": 0}`

**Shell Script Example** (`scripts/backup.sh`):
```bash
#!/bin/bash
# Backup script
DATABASE="{{ database }}"
OUTPUT="{{ output_path }}"

echo "Backing up $DATABASE to $OUTPUT"
pg_dump $DATABASE | gzip > $OUTPUT/dump.sql.gz
echo "Backup complete"
```

## Input Templating

All `inputs` support **Jinja2 templating** with full context access:

### Available Context

```yaml
inputs:
  # Access initial cascade input
  user_id: "{{ input.user_id }}"

  # Access persistent state
  session_token: "{{ state.auth_token }}"

  # Access prior phase outputs
  data: "{{ outputs.fetch_data }}"

  # Access specific fields from outputs
  count: "{{ outputs.fetch_data.result.count }}"

  # Filters and expressions
  timestamp: "{{ now() }}"
  formatted_date: "{{ input.date | date_format('%Y-%m-%d') }}"

  # Conditionals
  threshold: "{% if state.is_premium %}1000{% else %}100{% endif %}"
```

### Complex Input Structures

Inputs can be nested objects or arrays:

```yaml
inputs:
  config:
    database:
      host: "{{ state.db_host }}"
      port: 5432
      name: "{{ input.db_name }}"
    options:
      - name: "max_connections"
        value: 100
      - name: "timeout"
        value: 30
  filters:
    - field: "created_at"
      op: ">"
      value: "{{ input.start_date }}"
    - field: "status"
      op: "="
      value: "active"
```

**Rendering**: All strings are rendered recursively (nested dicts/lists supported).

## Routing & Handoffs

Deterministic phases can route to next phases using **two methods**:

### 1. Explicit Handoffs

Standard handoff configuration (same as LLM phases):

```yaml
phases:
  - name: "validate"
    tool: "python:validators.check_data"
    inputs:
      data: "{{ outputs.fetch_data }}"
    handoffs:
      - "process_valid"
      - "handle_error"
```

**Default behavior**: If tool succeeds, routes to first handoff (`process_valid`).

### 2. Dynamic Routing via `_route`

Tools can return `{"_route": "phase_name"}` to control routing:

```yaml
phases:
  - name: "validate"
    tool: "python:validators.check_data"
    inputs:
      data: "{{ outputs.fetch_data }}"
    handoffs:
      - "process_valid"
      - "handle_error"
```

**Tool implementation**:
```python
def check_data(data):
    if validate(data):
        return {
            "status": "valid",
            "data": data,
            "_route": "process_valid"  # Explicit routing
        }
    else:
        return {
            "status": "invalid",
            "errors": get_errors(data),
            "_route": "handle_error"
        }
```

**Routing logic**:
1. Tool returns dict with `_route` key
2. Windlass checks if `_route` value is in `handoffs`
3. Routes to specified phase (or raises error if not in handoffs)
4. `_route` is removed from output before storing

## Retry Logic

Deterministic phases support **automatic retries** for transient failures:

```yaml
- name: "api_call"
  tool: "python:api.fetch_data"
  inputs:
    url: "https://api.example.com/data"
  retry:
    max_attempts: 3
    backoff: "exponential"  # or "linear"
    initial_delay: 1  # seconds
    max_delay: 30
```

**Retry Strategies**:

**Exponential backoff**:
```
Attempt 1: immediate
Attempt 2: wait 1s
Attempt 3: wait 2s
Attempt 4: wait 4s (capped at max_delay)
```

**Linear backoff**:
```
Attempt 1: immediate
Attempt 2: wait 1s
Attempt 3: wait 2s
Attempt 4: wait 3s
```

**Retry Conditions**:
- Tool raises an exception
- HTTP errors (5xx, timeouts, connection errors)
- Database connection errors
- Configurable via `retry_on` (list of exception types)

**Implementation** (`deterministic.py:132-187`):
```python
def execute_with_retry(tool_func, inputs, retry_config):
    max_attempts = retry_config.get('max_attempts', 1)
    backoff = retry_config.get('backoff', 'exponential')
    initial_delay = retry_config.get('initial_delay', 1)
    max_delay = retry_config.get('max_delay', 30)

    for attempt in range(max_attempts):
        try:
            return tool_func(**inputs)
        except Exception as e:
            if attempt == max_attempts - 1:
                raise  # Final attempt failed

            # Calculate delay
            if backoff == 'exponential':
                delay = min(initial_delay * (2 ** attempt), max_delay)
            else:  # linear
                delay = min(initial_delay * (attempt + 1), max_delay)

            time.sleep(delay)
```

## Timeout Support

Set execution timeouts to prevent hanging:

```yaml
- name: "slow_query"
  tool: "sql_data"
  inputs:
    query: "SELECT * FROM huge_table"
  timeout: "5m"  # 5 minutes
```

**Timeout Formats**:
- Seconds: `30`, `"30s"`
- Minutes: `"5m"`
- Hours: `"2h"`
- Combined: `"1h30m45s"`

**Behavior**:
- Timeout triggers → raises `TimeoutError`
- Can be combined with retry (each attempt gets full timeout)
- Tool execution is terminated (thread interrupt or subprocess kill)

**Implementation** (`deterministic.py:245-289`):
```python
def parse_timeout(timeout_str):
    """Parse timeout string to seconds."""
    if isinstance(timeout_str, (int, float)):
        return timeout_str

    pattern = r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
    match = re.match(pattern, timeout_str)
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds
```

## Context Injection

Deterministic tools can access Windlass context via **special parameters**:

### Auto-Injected Parameters

These parameters are automatically added to tool inputs (if not already provided):

```python
def my_tool(data, _session_id, _phase_name, _outputs):
    """
    _session_id: Current session ID
    _phase_name: Current phase name
    _outputs: Dict of all prior phase outputs
    """
    # Access session-scoped resources
    db = get_session_db(_session_id)

    # Log with phase context
    log.info(f"[{_phase_name}] Processing {len(data)} records")

    # Reference prior outputs
    config = _outputs.get('load_config', {})
```

**Injection Rules**:
- Only injected if parameter name starts with `_`
- Won't override explicit values in `inputs`
- Available to all tool types (registered, Python imports, SQL, shell)

### Context Variables (ContextVars)

For more advanced use cases, use Python's `contextvars`:

```python
from windlass.runner import get_session_id, get_phase_outputs

def my_tool(data):
    # Access context without explicit parameters
    session_id = get_session_id()
    outputs = get_phase_outputs()

    # Your logic here
```

**Available Context Vars**:
- `get_session_id()`: Current session ID
- `get_trace_id()`: Current trace ID
- `get_phase_outputs()`: All prior phase outputs
- `get_state()`: Persistent session state
- `get_lineage()`: Full execution lineage

## Hybrid Workflows

**The power of deterministic execution**: Mix LLM and non-LLM phases in the same cascade.

### Example: Data Pipeline with LLM Classification

```yaml
cascade_id: "hybrid_data_pipeline"
inputs_schema:
  table_name: "Source table"

phases:
  # Deterministic: Fast SQL extraction
  - name: "extract"
    tool: "sql_data"
    inputs:
      query: "SELECT * FROM {{ input.table_name }} WHERE processed = false LIMIT 1000"

  # Deterministic: Python preprocessing
  - name: "preprocess"
    tool: "python:etl.clean_data"
    inputs:
      data: "{{ outputs.extract }}"

  # LLM: Intelligent classification
  - name: "classify"
    instructions: |
      Classify each record in the dataset.

      Data: {{ outputs.preprocess }}
    tackle:
      - "set_state"
    output_schema:
      type: array
      items:
        type: object
        properties:
          id: {type: integer}
          category: {type: string}
          confidence: {type: number}

  # Deterministic: Fast SQL load
  - name: "load"
    tool: "sql_data"
    inputs:
      query: |
        INSERT INTO classified_data (id, category, confidence)
        SELECT id, category, confidence FROM classify
```

**Performance**:
- Extract: ~50ms (DuckDB query)
- Preprocess: ~100ms (Python pandas)
- Classify: ~5s (LLM with 1000 records)
- Load: ~50ms (DuckDB insert)

**Total: ~5.2s** (vs ~15s if extract/preprocess/load were LLM-mediated)

### Example: Conditional LLM Routing

Use deterministic tools to decide **whether to use LLM**:

```yaml
phases:
  # Deterministic: Check cache
  - name: "check_cache"
    tool: "python:cache.lookup"
    inputs:
      key: "{{ input.query }}"
    handoffs:
      - "return_cached"
      - "generate_fresh"

  # Deterministic: Return cached result
  - name: "return_cached"
    tool: "python:cache.format_result"
    inputs:
      data: "{{ outputs.check_cache.value }}"

  # LLM: Generate fresh response (only if cache miss)
  - name: "generate_fresh"
    instructions: "Generate response for: {{ input.query }}"
    tackle:
      - "web_search"
      - "set_state"
```

**Routing logic** (`cache.py`):
```python
def lookup(key):
    value = redis.get(key)
    if value:
        return {
            "hit": True,
            "value": value,
            "_route": "return_cached"
        }
    else:
        return {
            "hit": False,
            "_route": "generate_fresh"
        }
```

**Cost savings**: 90%+ if cache hit rate is high (no LLM calls for cached queries).

## Advanced Features

### Tool Composition

Deterministic tools can spawn sub-cascades:

```yaml
- name: "parallel_processing"
  tool: "spawn_cascade"
  inputs:
    cascade_id: "process_batch"
    input:
      batch: "{{ outputs.fetch_data }}"
    parallel: 10  # Run 10 instances in parallel
```

### Validation Without LLM

Use deterministic validators (no LLM cost):

```yaml
- name: "process_data"
  tool: "python:transform.process"
  inputs:
    data: "{{ outputs.fetch_data }}"
  wards:
    post:
      - validator: "python:validators.check_schema"
        mode: "blocking"
```

**Validator implementation**:
```python
def check_schema(data):
    """Validator must return {"valid": bool, "reason": str}"""
    try:
        validate_schema(data)
        return {"valid": True, "reason": "Schema valid"}
    except SchemaError as e:
        return {"valid": False, "reason": str(e)}
```

### Parallel Execution

Combine deterministic phases with soundings for parallel execution:

```yaml
- name: "fetch_multiple_apis"
  soundings:
    factor: 5  # 5 parallel attempts
    mode: "aggregate"  # Combine all results
  tool: "python:api.fetch"
  inputs:
    url: "https://api.example.com/endpoint{{ sounding_index }}"
```

**Result**: All 5 APIs fetched in parallel, results aggregated (no LLM evaluator needed).

## Performance Comparison

### Benchmark: Data Pipeline

**Scenario**: Extract 10K records → Transform → Load

**LLM-Mediated Phases**:
```yaml
phases:
  - name: "extract"
    instructions: "Query the database for all records"
    tackle: ["sql_data"]
  # LLM chooses tool, constructs query, executes → ~3s

  - name: "transform"
    instructions: "Clean and normalize the data"
    tackle: ["run_code"]
  # LLM writes Python code, executes → ~8s

  - name: "load"
    instructions: "Insert into target table"
    tackle: ["sql_data"]
  # LLM chooses tool, constructs query → ~3s

Total: ~14s, Cost: ~$0.15
```

**Deterministic Phases**:
```yaml
phases:
  - name: "extract"
    tool: "sql_data"
    inputs:
      query: "SELECT * FROM source"
  # Direct query execution → ~100ms

  - name: "transform"
    tool: "python:etl.clean_data"
    inputs:
      data: "{{ outputs.extract }}"
  # Direct function call → ~500ms

  - name: "load"
    tool: "sql_data"
    inputs:
      query: "INSERT INTO target SELECT * FROM transform"
  # Direct query execution → ~100ms

Total: ~700ms, Cost: $0
```

**Speedup**: 20x faster, 100% cost reduction

## Error Handling

### Exception Propagation

Deterministic phases propagate exceptions like normal Python:

```python
def my_tool(data):
    if not data:
        raise ValueError("Data cannot be empty")
    return process(data)
```

**Windlass behavior**:
1. Exception raised
2. If `retry` configured → retry with backoff
3. If all retries exhausted → phase fails
4. Error logged to unified_logs
5. Execution stops (unless `wards.mode: "retry"`)

### Graceful Degradation

Use handoffs for error handling:

```yaml
phases:
  - name: "try_api"
    tool: "python:api.fetch"
    inputs:
      url: "{{ input.url }}"
    handoffs:
      - "process_success"
      - "fallback_cache"

  - name: "process_success"
    tool: "python:process.handle_data"
    inputs:
      data: "{{ outputs.try_api }}"

  - name: "fallback_cache"
    tool: "python:cache.get_stale"
    inputs:
      key: "{{ input.url }}"
```

**Tool implementation**:
```python
def fetch(url):
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return {
            "data": response.json(),
            "_route": "process_success"
        }
    except requests.RequestException:
        return {
            "error": "API unavailable",
            "_route": "fallback_cache"
        }
```

## Testing

### Unit Tests

Test tools in isolation:

```python
def test_my_tool():
    result = my_tool(data={"foo": "bar"})
    assert result["status"] == "success"
```

### Integration Tests

Test deterministic phases with snapshot testing:

```bash
# Run cascade
windlass examples/deterministic_pipeline.yaml \
  --input '{"user_id": 123}' \
  --session test_det

# Freeze as snapshot
windlass test freeze test_det \
  --name deterministic_pipeline

# Replay (should be instant - no LLM calls)
windlass test replay deterministic_pipeline
```

**Replay performance**: Deterministic phases replay at full speed (no LLM mocking needed).

## Best Practices

### When to Use Deterministic Phases

**Use deterministic phases for**:
- Data extraction/transformation/loading (ETL)
- API calls with known schemas
- Business logic with clear rules
- Performance-critical operations
- Operations that must be predictable/auditable

**Use LLM phases for**:
- Natural language understanding
- Content generation
- Complex decision-making
- Handling ambiguity
- Creative tasks

### Naming Conventions

Use descriptive tool names:

```yaml
# Good
tool: "sql:queries/analytics/daily_active_users.sql"
tool: "python:etl.transformers.normalize_addresses"

# Bad
tool: "sql:query1.sql"
tool: "python:utils.do_stuff"
```

### Input Validation

Validate inputs at the tool level:

```python
def my_tool(data, config):
    # Validate inputs
    if not isinstance(data, list):
        raise TypeError("data must be a list")
    if "required_key" not in config:
        raise ValueError("config.required_key is required")

    # Process
    return transform(data, config)
```

### Error Messages

Provide clear error messages for debugging:

```python
def fetch_user(user_id):
    user = db.get_user(user_id)
    if not user:
        raise ValueError(
            f"User {user_id} not found. "
            f"Available users: {db.get_user_ids()}"
        )
    return user
```

## Implementation Details

**Location**: `windlass/deterministic.py`

### Key Functions

#### `execute_deterministic_phase(phase, echo)`

Main entry point for deterministic execution.

**Steps**:
1. Resolve tool (registered, Python import, SQL file, shell script)
2. Render inputs using Jinja2
3. Inject context parameters (`_session_id`, etc.)
4. Execute tool (with retry/timeout if configured)
5. Process output (extract `_route`, store result)
6. Determine next phase

**Signature**:
```python
def execute_deterministic_phase(
    phase: Phase,
    echo: Echo
) -> Tuple[Any, Optional[str]]:
    """
    Returns:
        (output, next_phase_name)
    """
```

#### `resolve_tool(tool_spec)`

Parses tool specification and returns callable.

**Supported formats**:
- `"tool_name"` → ToolRegistry lookup
- `"python:module.path.func"` → Python import
- `"sql:path/to/query.sql"` → SQL file
- `"shell:path/to/script.sh"` → Shell script

**Returns**: `(tool_callable, tool_type)`

#### `render_inputs(inputs, context)`

Recursively renders all strings in inputs dict using Jinja2.

**Context**:
- `input`: Initial cascade input
- `state`: Persistent session state
- `outputs`: Prior phase outputs
- `lineage`: Execution lineage
- Custom variables (soundings, etc.)

#### `execute_with_timeout(func, timeout)`

Wraps function execution with timeout.

**Implementation**: Uses `concurrent.futures.ThreadPoolExecutor` with timeout.

## Limitations

### Current Limitations

1. **No streaming**: Tools must return complete results (no streaming responses)
2. **No dynamic tool selection**: Tool must be specified at definition time
3. **Limited parallelism**: Use soundings for parallel execution (not thread pools)
4. **No interactive tools**: Tools cannot prompt for user input mid-execution

### Planned Enhancements

1. **Streaming support**: Yield partial results for long-running tools
2. **Conditional tool selection**: Choose tool based on template expression
3. **Batch execution**: Process arrays with automatic parallelism
4. **Tool marketplace**: Registry of community-contributed deterministic tools

## Related Documentation

- **Data Cascades**: `docs/claude/data-cascades-reference.md`
- **Tool System**: `docs/claude/tools-reference.md`
- **Validation**: `docs/claude/validation-reference.md`
- **Testing**: `docs/claude/testing.md`
