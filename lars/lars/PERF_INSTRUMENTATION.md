# Performance Instrumentation Guide

This guide shows where to add `perf_timer` instrumentation to track cascade execution performance.

## Quick Start

```python
from lars.perf_logger import perf_timer, force_flush

# Wrap any code block
with perf_timer("operation_name", session_id=self.session_id, cascade_id=self.config.cascade_id):
    result = expensive_operation()

# Force flush at cascade end
force_flush()
```

## Recommended Instrumentation Points

### 1. Config Loading (CRITICAL)
**File:** `lars/lars/runner.py` - `LARSRunner.__init__()` or first use of config

```python
# Around line 500-530 in udf.py or runner.py __init__
with perf_timer("config_load", session_id=session_id, metadata={"path": str(cascade_path)}):
    config = load_cascade_config(cascade_path)
```

### 2. Agent Calls (CRITICAL)
**File:** `lars/lars/runner.py:11737`

```python
# Wrap the agent.run() call
with perf_timer("agent_call",
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                cell_name=cell.name,
                metadata={"model": agent.model, "turn": i}):
    response_dict = agent.run(current_input, context_messages=turn_context)
```

### 3. Tool Execution
**File:** `lars/lars/runner.py:12091`

```python
# Wrap each tool call
with perf_timer("tool_execution",
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                cell_name=cell.name,
                metadata={"tool": func_name, "args_size": len(json.dumps(args))}):
    result = tool_func(**args)
```

### 4. Token Counting
**File:** `lars/lars/runner.py:11682`

```python
# Wrap token counting
with perf_timer("token_counting",
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                cell_name=cell.name,
                metadata={"message_count": len(self.context_messages)}):
    budget_status = self.token_manager.check_budget(self.context_messages)
```

### 5. Jinja2 Template Rendering
**File:** `lars/lars/runner.py:10871` (in render_instruction)

```python
# Wrap template rendering
with perf_timer("template_render",
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                cell_name=cell.name,
                metadata={"template_size": len(cell.instructions)}):
    rendered = render_instruction(cell.instructions, context)
```

### 6. Database Writes
**File:** `lars/lars/session_state.py` - create_session_state, update_session_status

```python
# Wrap session state creation
with perf_timer("db_session_create", session_id=session_id, cascade_id=cascade_id):
    create_session_state(session_id, cascade_id, ...)
```

### 7. SQL UDF Cascade Invocation
**File:** `lars/lars/sql_tools/udf.py:561`

```python
# Wrap the entire cascade execution
with perf_timer("udf_cascade_run",
                session_id=session_id,
                metadata={"path": cascade_path, "cached": False}):
    result = run_cascade(resolved_path, inputs, session_id=session_id, ...)
```

### 8. Validation/Wards
**File:** `lars/lars/runner.py` - ward execution

```python
# Wrap validator execution
with perf_timer("ward_validation",
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                cell_name=cell.name,
                metadata={"validator": ward.validator, "mode": ward.mode}):
    result = execute_validator(ward.validator, ...)
```

### 9. Context Building
**File:** `lars/lars/runner.py:11723` (_build_turn_context)

```python
# Wrap context building
with perf_timer("context_build",
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                cell_name=cell.name,
                metadata={"turn": turn_number, "is_retry": is_loop_retry}):
    turn_context, context_stats = self._build_turn_context(cell, turn_number, is_loop_retry)
```

### 10. Full Cell Execution
**File:** `lars/lars/runner.py` - execute_cell

```python
# Wrap entire cell execution
with perf_timer("cell_execution",
                session_id=self.session_id,
                cascade_id=self.config.cascade_id,
                cell_name=cell.name,
                metadata={"cell_type": cell.type or "llm", "has_takes": bool(cell.takes)}):
    result = self._execute_cell_internal(cell, ...)
```

## Analysis Queries

Once instrumented, analyze performance with SQL:

### Slowest Operations by Label
```sql
SELECT
  label,
  COUNT(*) as calls,
  AVG(duration_ms) as avg_ms,
  MEDIAN(duration_ms) as median_ms,
  quantile(0.95)(duration_ms) as p95_ms,
  MAX(duration_ms) as max_ms,
  SUM(duration_ms) as total_ms,
  SUM(exception_occurred) as errors
FROM perf_metrics
WHERE timestamp >= now() - INTERVAL 1 HOUR
GROUP BY label
ORDER BY total_ms DESC
LIMIT 20;
```

### Performance by Cascade
```sql
SELECT
  cascade_id,
  label,
  COUNT(*) as calls,
  AVG(duration_ms) as avg_ms,
  SUM(duration_ms) as total_ms
FROM perf_metrics
WHERE cascade_id != ''
  AND timestamp >= now() - INTERVAL 1 HOUR
GROUP BY cascade_id, label
ORDER BY cascade_id, total_ms DESC;
```

### Session Timeline
```sql
SELECT
  label,
  duration_ms,
  exception_occurred,
  metadata_json,
  timestamp
FROM perf_metrics
WHERE session_id = 'YOUR_SESSION_ID'
ORDER BY timestamp ASC;
```

### Total Time Breakdown (Waterfall)
```sql
SELECT
  label,
  SUM(duration_ms) as total_ms,
  (SUM(duration_ms) / (SELECT SUM(duration_ms) FROM perf_metrics WHERE session_id = 'YOUR_SESSION_ID')) * 100 as pct
FROM perf_metrics
WHERE session_id = 'YOUR_SESSION_ID'
GROUP BY label
ORDER BY total_ms DESC;
```

### Tool Performance Comparison
```sql
SELECT
  JSONExtractString(metadata_json, 'tool') as tool_name,
  COUNT(*) as calls,
  AVG(duration_ms) as avg_ms,
  MEDIAN(duration_ms) as median_ms,
  MAX(duration_ms) as max_ms
FROM perf_metrics
WHERE label = 'tool_execution'
  AND timestamp >= now() - INTERVAL 1 DAY
GROUP BY tool_name
ORDER BY total_ms DESC;
```

### Exception Rate by Operation
```sql
SELECT
  label,
  COUNT(*) as total_calls,
  SUM(exception_occurred) as failures,
  (SUM(exception_occurred) / COUNT(*)) * 100 as error_rate_pct,
  groupArray(exception_type) as exception_types
FROM perf_metrics
WHERE timestamp >= now() - INTERVAL 1 DAY
GROUP BY label
HAVING error_rate_pct > 0
ORDER BY error_rate_pct DESC;
```

### Before/After Optimization Comparison
```sql
-- Compare performance before and after a code change
WITH
  before AS (
    SELECT label, AVG(duration_ms) as avg_ms
    FROM perf_metrics
    WHERE timestamp BETWEEN '2026-01-20' AND '2026-01-21'
    GROUP BY label
  ),
  after AS (
    SELECT label, AVG(duration_ms) as avg_ms
    FROM perf_metrics
    WHERE timestamp BETWEEN '2026-01-23' AND '2026-01-24'
    GROUP BY label
  )
SELECT
  before.label,
  before.avg_ms as before_ms,
  after.avg_ms as after_ms,
  after.avg_ms - before.avg_ms as delta_ms,
  ((after.avg_ms - before.avg_ms) / before.avg_ms) * 100 as pct_change
FROM before
INNER JOIN after ON before.label = after.label
WHERE abs(pct_change) > 5  -- Only show significant changes
ORDER BY abs(delta_ms) DESC;
```

## Best Practices

1. **Label Naming Convention:**
   - Use snake_case
   - Be specific but concise: `config_load`, not `loading_configuration_file`
   - Group related operations: `db_session_create`, `db_session_update`

2. **Metadata Guidelines:**
   - Keep metadata small (< 1KB JSON)
   - Include context that helps debugging: model name, file path, row count
   - Don't include PII or sensitive data

3. **Overhead:**
   - `perf_timer` overhead is ~5-10μs (0.005-0.01ms)
   - Buffer flushes are async and non-blocking
   - Safe to instrument hot paths

4. **Flushing:**
   - Auto-flushes every 50 metrics by default
   - Call `force_flush()` at cascade end to ensure all metrics are saved
   - Add to runner.py cleanup/finally blocks

5. **Exception Safety:**
   - `perf_timer` still records timing even if exception occurs
   - Sets `exception_occurred=True` and captures exception type
   - Doesn't suppress exceptions - they still propagate

## Migration

Run migrations to create the table:

```bash
# Migrations are auto-applied on first DB connection
# Or manually:
lars db migrate
```

## Troubleshooting

**Metrics not appearing in ClickHouse:**
- Check that ClickHouse is running and accessible
- Call `force_flush()` to ensure buffer is written
- Check logs for DB write errors (will be logged as debug warnings)

**High overhead:**
- Reduce buffer threshold if flushing too frequently
- Check if ClickHouse writes are slow (could be network/DB issue)
- Verify `db.insert_rows()` is truly async

**Missing session_id context:**
- Pass session_id explicitly if not available in self
- For standalone functions, get from context: `from lars.trace import get_current_trace`
