# Signals


Signals enable cross-cascade communication, allowing workflows to coordinate with each other
  through a durable event system. Wait for upstream processes, notify downstream consumers,
  and build complex orchestration patterns.
On This Page
- [Overview](#overview)
- [Signal Tools](#tools)
- [Common Patterns](#patterns)
- [CLI Commands](#cli)
- [Signal Storage](#storage)


## Overview


Signals are named events that cascades can wait for or fire. They're stored durably in DuckDB
  and support payloads for passing data between workflows.


#### Durable


Signals survive restarts and are tracked in DuckDB


#### Timeout Support


Configure timeouts for waiting cascades


#### Payload Data


Pass structured data with signal events

## Signal Tools


### await_signal


Wait for a named signal before continuing execution:

```wait for signal
- name: wait_for_data
  tool: await_signal
  inputs:
    signal_name: "daily_data_ready"
    timeout: "4h"                    # Wait up to 4 hours
    description: "Waiting for upstream ETL to complete"
```

#### Timeout Format


Timeouts support human-readable durations:
- `30s` - 30 seconds
- `5m` - 5 minutes
- `2h` - 2 hours
- `1d` - 1 day


### fire_signal


Fire a signal to wake up waiting cascades:

```fire signal
- name: notify_downstream
  tool: fire_signal
  inputs:
    signal_name: "preprocessing_complete"
    payload: '{"row_count": {{ state.row_count }}, "status": "success"}'
```

### list_signals


List signals for a cascade:

```list signals
- name: check_signals
  tool: list_signals
  inputs:
    cascade_id: "{{ input.cascade }}"
    status: "pending"  # pending, fired, expired
```

## Common Patterns


### ETL Pipeline Coordination


```upstream: cascades/etl_extract.yaml
cascade_id: etl_extract
cells:
  - name: extract_data
    tool: sql_data
    inputs:
      query: "SELECT * FROM source_table"

  - name: notify_transform
    tool: fire_signal
    inputs:
      signal_name: "extract_complete"
      payload: '{"rows": {{ outputs.extract_data.row_count }}}'
```

```downstream: cascades/etl_transform.yaml
cascade_id: etl_transform
cells:
  - name: wait_for_extract
    tool: await_signal
    inputs:
      signal_name: "extract_complete"
      timeout: "1h"

  - name: transform_data
    instructions: |
      Transform the extracted data.
      Source had {{ outputs.wait_for_extract.payload.rows }} rows.
```

### Fan-Out/Fan-In


```coordinator
cells:
  - name: spawn_workers
    tool: map_cascade
    inputs:
      cascade: "worker.yaml"
      items: "{{ input.work_items }}"

  - name: wait_for_all
    tool: await_signal
    inputs:
      signal_name: "all_workers_complete"
      timeout: "30m"
```

## CLI Commands


```signal management
# List signals for a cascade
lars signals list --cascade my_cascade

# Fire a signal manually
lars signals fire daily_data_ready --payload '{"row_count": 1000}'

# Check signal status
lars signals status signal_abc123

# Cancel a pending signal
lars signals cancel signal_abc123 --reason "timeout"
```

## Signal Storage


Signals are stored in DuckDB with the following properties:
- **Durability** - Survives process restarts
- **HTTP callbacks** - Sub-second wake-up latency
- **Polling fallback** - Reliability if callbacks are missed
- **TTL** - Signals expire after configured timeout


> **NOTE: Signal Lifecycle**
>
> 
> When a cascade calls `await_signal`, it registers a pending signal and
>     either blocks (in sync mode) or suspends (in async mode). When another cascade
>     calls `fire_signal` with the matching name, the waiting cascade resumes
>     with the payload data.
> 


## Next: Triggers


Learn about scheduling cascades: [Triggers](#triggers).
