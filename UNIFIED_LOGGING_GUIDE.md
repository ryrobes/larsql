# Unified Logging System - Migration Guide

## Overview

Windlass now uses a **single mega-table** approach for all logging, replacing the fragmented systems (logs.py, echoes.py, JSONL files, async cost tracking).

### Key Changes

1. **Single Parquet table** instead of multiple systems
2. **Per-message granularity** - one file per message
3. **Blocking cost tracking** - costs fetched immediately, not async
4. **Complete context per row** - full request/response, cascade config, phase config, all metadata
5. **Enriched fields** - unwrapped OpenRouter data, special indexes, parent tracking

---

## Architecture

### Old System (Deprecated)

```
logs.py          → Basic parquet logs (stringified content)
echoes.py        → Dual Parquet + JSONL (native JSON)
cost.py (async)  → Separate cost_update entries after 5s delay
```

**Problems:**
- Fragmented data across 3 systems
- Async cost tracking caused ordering issues
- Missing context (no full request/response blobs)
- Difficult queries across systems

### New System (Unified)

```
unified_logs.py  → Single mega-table with ALL context
├─ Per-message Parquet files (msg_TIMESTAMP_UUID.parquet)
├─ Blocking cost fetch (no async delay)
├─ Complete JSON blobs (request, response, cascade, phase)
└─ Ready for time-based compaction
```

**Benefits:**
- ✅ Single source of truth
- ✅ Immediate writes with complete data
- ✅ Cost data in same row as message
- ✅ Full request/response reconstruction
- ✅ Cascade and phase configs embedded
- ✅ Backward compatible queries

---

## Schema

### Mega Table Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | float | Unix timestamp (local timezone) |
| `timestamp_iso` | str | ISO 8601 format for readability |
| `session_id` | str | Cascade session ID |
| `trace_id` | str | Unique event ID |
| `parent_id` | str | Parent trace ID |
| `parent_session_id` | str | **NEW**: Parent session if sub-cascade |
| `parent_message_id` | str | **NEW**: Parent calling message trace ID |
| `node_type` | str | message, tool_call, agent, user, system, etc. |
| `role` | str | user, assistant, tool, system |
| `depth` | int | Nesting depth for sub-cascades |
| `sounding_index` | int | Sounding attempt (0-indexed, null if N/A) |
| `is_winner` | bool | True if winning sounding (null if N/A) |
| `reforge_step` | int | Reforge iteration (0=initial, null if N/A) |
| `attempt_number` | int | **NEW**: Retry/validation attempt |
| `turn_number` | int | **NEW**: Turn within phase |
| `cascade_id` | str | Cascade identifier |
| `cascade_file` | str | Full path to cascade JSON |
| `cascade_json` | str | **NEW**: JSON - Entire cascade config |
| `phase_name` | str | Current phase name |
| `phase_json` | str | **NEW**: JSON - Current phase config |
| `model` | str | Model name/ID |
| `request_id` | str | OpenRouter/provider request ID |
| `provider` | str | **NEW**: openrouter, anthropic, openai, etc. |
| `duration_ms` | float | Operation duration |
| `tokens_in` | int | **NEW**: Input tokens (unwrapped) |
| `tokens_out` | int | **NEW**: Output tokens (unwrapped) |
| `total_tokens` | int | **NEW**: tokens_in + tokens_out |
| `cost` | float | **NEW**: Dollar cost (blocking fetch!) |
| `content_json` | str | **NEW**: JSON - Latest message content only |
| `full_request_json` | str | **NEW**: JSON - Complete request with history |
| `full_response_json` | str | **NEW**: JSON - Complete LLM response |
| `tool_calls_json` | str | JSON - Tool call objects |
| `images_json` | str | JSON - Image file paths |
| `has_images` | bool | Whether images present |
| `has_base64` | bool | Whether content has base64 images |
| `metadata_json` | str | JSON - Additional metadata |

### Key Improvements

**Unwrapped OpenRouter Data:**
- `tokens_in`, `tokens_out`, `total_tokens` - direct fields (not buried in JSON)
- `cost` - dollar amount, immediately available
- `provider` - extracted from model string or API response

**Complete Context:**
- `full_request_json` - Entire request including all history
- `full_response_json` - Complete LLM response
- `cascade_json` - Full cascade config for this execution
- `phase_json` - Phase config for this execution

**Parent Tracking:**
- `parent_session_id` - Links sub-cascades to parent sessions
- `parent_message_id` - Links to specific calling message

**Special Indexes:**
- `sounding_index` - Which sounding attempt
- `is_winner` - Winning sounding flag
- `reforge_step` - Reforge iteration
- `attempt_number` - Retry attempt
- `turn_number` - Turn within phase

---

## Usage

### Basic Querying

```python
from windlass.unified_logs import query_unified

# All messages for a session
df = query_unified("session_id = 'session_123'")

# High-cost messages
df = query_unified("cost > 0.01")

# Specific phase
df = query_unified("cascade_id = 'blog_flow' AND phase_name = 'research'")

# All winning soundings
df = query_unified("is_winner = true")
```

### Parsing JSON Fields

```python
from windlass.unified_logs import query_unified_json_parsed

# Auto-parse JSON fields
df = query_unified_json_parsed(
    "session_id = 'abc'",
    parse_json_fields=['content_json', 'tool_calls_json', 'metadata_json']
)

# Access parsed objects directly
first_content = df['content_json'][0]  # Already a dict/list
```

### Helper Functions

```python
from windlass.unified_logs import (
    get_session_messages,
    get_cascade_costs,
    get_soundings_analysis,
    get_cost_timeline,
    get_model_usage_stats
)

# Get all messages for a session (auto-parsed)
messages = get_session_messages('session_123')

# Cost breakdown by phase
costs = get_cascade_costs('blog_flow')

# Analyze soundings
soundings = get_soundings_analysis('session_123', 'research')

# Cost over time
timeline = get_cost_timeline('blog_flow', group_by='day')

# Model usage stats
models = get_model_usage_stats()
```

### Backward Compatibility

Old code using `logs.query_logs()` or `echoes.query_echoes_parquet()` will automatically map to the new system:

```python
# Old code (still works!)
from windlass.logs import query_logs
df = query_logs("session_id = 'abc'")

# Old code (still works!)
from windlass.echoes import query_echoes_parquet
df = query_echoes_parquet("cost > 0")
```

---

## Migration Path

### For Developers

1. **New cascades** use the unified system automatically (agent.py and runner.py already updated)
2. **Old data** remains queryable via echoes fallback
3. **Queries** work with both old and new data via the `logs` view

### For UI/Analytics

The UI backend has been updated:
- `get_db_connection()` loads unified logs (with echoes fallback)
- All queries use `logs` view (maps to unified or echoes)
- Queries work identically for new and old data

### Data Coexistence

Both systems can coexist:

```
logs/
├── unified/              # NEW mega-table files
│   ├── msg_1701234567890_abc123.parquet
│   └── msg_1701234568910_def456.parquet
├── echoes/               # OLD dual logging (still queryable)
│   └── echoes_*.parquet
└── echoes_jsonl/         # OLD JSONL files (still readable)
    └── session_123.jsonl
```

Queries automatically use `unified` if available, fall back to `echoes` otherwise.

---

## Cost Tracking Changes

### Old System (Async)

```python
# Agent makes call
response = agent.run()
request_id = response['id']

# Track cost async (5s delay)
track_request(session_id, request_id, ...)

# Later, cost_update entry written
# (separate from agent message)
```

**Problems:**
- Cost and message in separate rows
- 5-second delay causes ordering issues
- Complex queries to join cost data

### New System (Blocking)

```python
# Agent makes call
response = agent.run()

# ✅ Cost fetched IMMEDIATELY with retries
# ✅ Merged into response dict
# ✅ Single log entry with everything

log_unified(
    session_id=...,
    content=response['content'],
    cost=response['cost'],  # Already fetched!
    tokens_in=response['tokens_in'],
    tokens_out=response['tokens_out'],
    ...
)
```

**Benefits:**
- Cost in same row as message
- No async delays
- Simple queries (no joins)
- Chronological ordering preserved

---

## Querying Examples

### Session Analysis

```python
from windlass.unified_logs import query_unified

# Get all agent responses with costs
df = query_unified("""
    session_id = 'session_123'
    AND role = 'assistant'
    AND cost IS NOT NULL
""")

# Calculate session total cost
total_cost = df['cost'].sum()
total_tokens = df['total_tokens'].sum()
```

### Soundings Comparison

```python
from windlass.unified_logs import query_unified

# Compare sounding costs
df = query_unified("""
    session_id = 'session_123'
    AND phase_name = 'research'
    AND sounding_index IS NOT NULL
""")

# Group by sounding
soundings = df.groupby(['sounding_index', 'is_winner']).agg({
    'cost': 'sum',
    'total_tokens': 'sum'
}).reset_index()

# Find winner
winner = soundings[soundings['is_winner'] == True]
```

### Model Cost Analysis

```python
from windlass.unified_logs import query_unified

# Cost by model
df = query_unified("cost IS NOT NULL AND model IS NOT NULL")

model_stats = df.groupby('model').agg({
    'cost': ['sum', 'mean'],
    'total_tokens': 'sum',
    'session_id': 'nunique'  # Unique sessions
}).reset_index()
```

### Full Request Reconstruction

```python
from windlass.unified_logs import query_unified_json_parsed

# Get agent call with full context
df = query_unified_json_parsed(
    "trace_id = 'abc-123'",
    parse_json_fields=['full_request_json', 'full_response_json']
)

# Access complete request
full_request = df['full_request_json'][0]
messages = full_request['messages']  # All history

# Access complete response
full_response = df['full_response_json'][0]
usage = full_response['usage']
```

---

## File Structure

### Per-Message Files

Each message is written to its own Parquet file immediately:

```
logs/unified/
├── msg_1701234567890_abc123.parquet  # Timestamp + UUID
├── msg_1701234568910_def456.parquet
└── msg_1701234569920_ghi789.parquet
```

**Why individual files?**
- Immediate writes (no buffering delays)
- No locking issues (each file independent)
- Easy to compact later (merge into time buckets)
- Parallel writes possible

### Future: Compaction

Planned periodic compaction to merge files:

```python
# Future feature (not implemented yet)
windlass compact-logs --bucket hourly
# Merges msg_*.parquet → hour_2024-12-03_10.parquet
```

This will reduce file count while preserving all data.

---

## Testing

### Verify Unified Logs Working

```python
from windlass import run_cascade

# Run a cascade
result = run_cascade(
    "examples/simple_flow.json",
    {"data": "test"},
    "test_unified_001"
)

# Check unified logs were created
from windlass.unified_logs import get_session_messages
messages = get_session_messages("test_unified_001")

print(f"Messages logged: {len(messages)}")
print(f"Total cost: ${messages['cost'].sum():.4f}")
print(f"Total tokens: {messages['total_tokens'].sum()}")
```

### Compare Old vs New

```python
# If you have old echoes data
from windlass.echoes import query_echoes_parquet as old_query
from windlass.unified_logs import query_unified as new_query

# Same query, different systems
old_df = old_query("session_id = 'old_session_123'")
new_df = new_query("session_id = 'new_session_123'")

# Both work!
```

---

## Troubleshooting

### No cost data showing

**Check 1:** Verify request_id exists
```python
df = query_unified("node_type = 'agent'")
print(df[['request_id', 'cost', 'tokens_in', 'tokens_out']])
```

**Check 2:** Check blocking cost fetch logs
```
[Cost] Fetched for req_abc123: $0.0123 (500+200 tokens)
```

**Check 3:** Verify OPENROUTER_API_KEY set
```bash
echo $OPENROUTER_API_KEY
```

### Queries returning empty

**Check 1:** Verify unified logs exist
```bash
ls -la logs/unified/
```

**Check 2:** Check fallback to echoes
```python
conn = duckdb.connect()
conn.execute("SELECT COUNT(*) FROM logs").fetchone()
```

### JSON parsing errors

```python
# Use explicit JSON parsing
from windlass.unified_logs import query_unified_json_parsed
import json

df = query_unified("session_id = 'abc'")

# Manual parsing
df['content_parsed'] = df['content_json'].apply(
    lambda x: json.loads(x) if x else None
)
```

---

## Summary

✅ **Single mega-table** - All data in one place
✅ **Blocking costs** - No async delays
✅ **Complete context** - Full request/response/config per row
✅ **Backward compatible** - Old queries still work
✅ **Helper functions** - Common queries made easy
✅ **Ready for analytics** - Rich schema for analysis

The unified logging system provides a **solid foundation** for analytics, debugging, and future optimizations like the passive prompt optimization system.
