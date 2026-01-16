# Echo Logging Integration Guide

This guide shows how to integrate comprehensive echo logging into Lars runners.

## Overview

**Two logging systems working together:**

1. **logs.py** - Existing event stream (11 fields, stringified content)
2. **echoes.py** - NEW comprehensive storage (Parquet + JSONL with native JSON)

**Strategy:** Add echo logging alongside existing `log_message()` calls without removing them (backward compatibility).

## Integration Pattern

### Basic Pattern

Every time you call `log_message()`, also call `log_echo()` with enriched data:

```python
from .logs import log_message
from .echoes import log_echo
from .echo_enrichment import TimingContext, enrich_echo_with_llm_response, detect_base64_in_content

# Existing code
log_message(session_id, "agent", content, metadata, trace_id, parent_id, node_type, depth)

# NEW: Also log to echoes
log_echo(
    session_id=session_id,
    trace_id=trace_id,
    parent_id=parent_id,
    node_type=node_type,
    role="assistant",
    depth=depth,
    content=content,  # Full content (not stringified!)
    metadata=metadata,
    phase_name=phase_name,
    cascade_id=cascade_id,
)
```

### Agent Call with Timing

```python
from .echo_enrichment import TimingContext, enrich_echo_with_llm_response

# Track timing
with TimingContext() as timer:
    response = agent.run(prompt, context_messages)

# Extract message
msg_dict = {
    "role": response.get("role", "assistant"),
    "content": response.get("content", ""),
    "tool_calls": response.get("tool_calls"),
}

# Existing logging
echo.add_history(msg_dict, trace_id=trace.id, parent_id=parent.id, node_type="agent")
log_message(session_id, "agent", msg_dict["content"], {...}, trace_id, parent_id, "agent")

# NEW: Comprehensive echo logging
log_echo(
    session_id=session_id,
    trace_id=trace.id,
    parent_id=parent.id,
    node_type="agent",
    role="assistant",
    phase_name=current_phase,
    cascade_id=cascade_id,
    duration_ms=timer.get_duration_ms(),  # ← Timing!
    content=msg_dict["content"],  # Full content
    tool_calls=msg_dict.get("tool_calls"),  # Native JSON
    metadata={
        "model": agent.model,
        "turn_index": turn_idx,
    }
)
```

### LLM Response with Usage Tracking

```python
from .echo_enrichment import extract_usage_from_litellm, extract_request_id

# In agent.py or runner.py
response = litellm.completion(**args)  # Returns full response object

# Extract usage
usage = extract_usage_from_litellm(response)
request_id = extract_request_id(response)

msg_dict = {...}  # Build message from response

# NEW: Log with usage data
log_echo(
    session_id=session_id,
    trace_id=trace.id,
    content=msg_dict["content"],
    tool_calls=msg_dict.get("tool_calls"),
    tokens_in=usage["tokens_in"],  # ← Token tracking!
    tokens_out=usage["tokens_out"],
    request_id=request_id,  # ← Request ID for cost correlation
    duration_ms=timer.get_duration_ms(),
)
```

### Tool Call with Image Handling

```python
from .echo_enrichment import extract_image_paths_from_tool_result, detect_base64_in_content

# Execute tool
with TimingContext() as timer:
    result = tool_func(**args)

# Extract images if tool returned them
image_paths = extract_image_paths_from_tool_result(result)

# Log tool result
log_echo(
    session_id=session_id,
    trace_id=tool_trace.id,
    parent_id=turn_trace.id,
    node_type="tool_result",
    role="tool",
    phase_name=phase_name,
    content=result,  # Full tool result (dict/str/etc)
    metadata={
        "tool_name": tool_name,
        "arguments": args,  # Full arguments
    },
    images=image_paths,  # ← Link images to trace_id!
    duration_ms=timer.get_duration_ms(),
)
```

### Image Injection with Base64 Detection

```python
from .echo_enrichment import detect_base64_in_content

# After image injection
injection_msg = {
    "role": "user",
    "content": [
        {"type": "text", "text": "Analyze this chart:"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]
}

echo.add_history(injection_msg, trace_id, parent_id, node_type="injection")

# NEW: Log with base64 detection
log_echo(
    session_id=session_id,
    trace_id=trace.id,
    node_type="image_injection",
    role="user",
    content=injection_msg["content"],  # Full multi-modal content
    has_base64=detect_base64_in_content(injection_msg["content"]),  # ← Auto-detect
    images=saved_image_paths,  # Link to filesystem copies
)
```

## Key Integration Points in runner.py

### 1. Cascade Start (line ~540)

```python
log_message(self.session_id, "system", f"Starting cascade {self.config.cascade_id}", ...)

# ADD:
log_echo(
    session_id=self.session_id,
    trace_id=self.trace.id,
    parent_id=self.trace.parent_id,
    node_type="cascade_start",
    role="system",
    cascade_id=self.config.cascade_id,
    cascade_file=self.config_path if isinstance(self.config_path, str) else None,
    content=f"Starting cascade {self.config.cascade_id}",
    metadata={"input": input_data, "depth": self.depth},
)
```

### 2. Phase Start (line ~1470)

```python
log_message(self.session_id, "system", f"Phase {phase.name} starting", ...)

# ADD:
log_echo(
    session_id=self.session_id,
    trace_id=phase_trace.id,
    parent_id=self.trace.id,
    node_type="phase_start",
    phase_name=phase.name,
    cascade_id=self.config.cascade_id,
    content=f"Starting phase: {phase.name}",
    metadata={"instructions": rendered_instruction},
)
```

### 3. Agent Turn (where agent.run() is called)

```python
# WRAP agent call with timing
with TimingContext() as timer:
    response = agent.run(prompt, context_messages)

usage = extract_usage_from_litellm(response)  # If you modify agent.py to return full response
request_id = extract_request_id(response)

# ADD:
log_echo(
    session_id=self.session_id,
    trace_id=turn_trace.id,
    parent_id=phase_trace.id,
    node_type="agent",
    role="assistant",
    phase_name=phase.name,
    content=msg_dict["content"],
    tool_calls=msg_dict.get("tool_calls"),
    duration_ms=timer.get_duration_ms(),
    tokens_in=usage.get("tokens_in"),
    tokens_out=usage.get("tokens_out"),
    request_id=request_id,
)
```

### 4. Tool Execution (line ~1796)

```python
with TimingContext() as timer:
    result = tool_eddy.run(**validated_args)

image_paths = extract_image_paths_from_tool_result(result)

# ADD:
log_echo(
    session_id=self.session_id,
    trace_id=tool_trace.id,
    parent_id=turn_trace.id,
    node_type="tool_result",
    role="tool",
    phase_name=phase.name,
    content=result,
    metadata={
        "tool_name": tool_name,
        "arguments": validated_args,
    },
    images=image_paths,
    duration_ms=timer.get_duration_ms(),
)
```

### 5. Soundings (line ~885)

```python
# ADD to each sounding attempt:
log_echo(
    session_id=sounding_session_id,  # Sub-session
    trace_id=sounding_trace.id,
    parent_id=soundings_trace.id,
    node_type="sounding_attempt",
    sounding_index=i,  # ← Track index
    is_winner=False,  # Updated later
    phase_name=phase.name,
    content=output,
    metadata={"attempt": i, "factor": factor},
)

# When winner selected:
log_echo(
    session_id=self.session_id,
    trace_id=winner_trace.id,
    sounding_index=winner_index,
    is_winner=True,  # ← Mark winner
    content=winner_output,
)
```

### 6. Reforge (line ~350)

```python
# ADD to each refinement step:
log_echo(
    session_id=refinement_session_id,
    trace_id=refinement_trace.id,
    sounding_index=attempt_idx,
    reforge_step=step_num,  # ← Track refinement step
    is_winner=False,  # Updated later
    content=refined_output,
    metadata={"honing_prompt": honing, "mutation": mutation_strategy},
)
```

## Agent.py Modification (Optional)

To capture full LiteLLM response with usage data:

```python
# In agent.py, modify run() method:
def run(self, input_message: str = None, context_messages: List[Dict] = None) -> Dict[str, Any]:
    # ... existing code ...

    response = litellm.completion(**args)
    message = response.choices[0].message

    # Build message dict
    msg_dict = {
        "role": message.role,
        "content": message.content if message.content is not None else "",
        "id": response.id,
    }

    # ADD: Include usage data in return
    if hasattr(response, "usage") and response.usage:
        msg_dict["usage"] = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    # ADD: Include raw response for advanced use cases (optional)
    msg_dict["_raw_response"] = response

    return msg_dict
```

## Cost Enrichment

Cost data arrives asynchronously from OpenRouter. To enrich echoes:

```python
# In cost.py, after fetching cost:
from .echoes import log_echo

# After logging to logs.py (line 71):
log_message(...)

# ADD: Also update echo entry
log_echo(
    session_id=item["session_id"],
    trace_id=item["trace_id"],  # Same trace_id as original message
    parent_id=item["parent_id"],
    node_type="cost_update",
    role="system",
    cost=cost,  # ← Actual cost from OpenRouter
    tokens_in=data.get("native_tokens_prompt"),
    tokens_out=data.get("native_tokens_completion"),
    metadata={"provider_id": item["request_id"]},
)
```

**Note:** This creates a second echo entry with the same trace_id. You can join on trace_id to enrich the original entry.

Alternatively, modify echoes.py to support UPDATE operations (update existing entry by trace_id).

## Querying Examples

### Query Parquet with DuckDB

```python
from lars.echoes import query_echoes_parquet

# All agent messages with timing
df = query_echoes_parquet("node_type = 'agent' AND duration_ms IS NOT NULL")

# Soundings that won
df = query_echoes_parquet("is_winner = true")

# Phase-specific messages
df = query_echoes_parquet("phase_name = 'generate'")

# Expensive calls (by tokens)
df = query_echoes_parquet("tokens_out > 1000 ORDER BY tokens_out DESC")
```

### Query JSONL

```python
from lars.echoes import query_echoes_jsonl, query_echoes_jsonl_duckdb

# Load single session
entries = query_echoes_jsonl("session_123")
for entry in entries:
    if entry["has_images"]:
        print(f"Images: {entry['image_paths']}")

# Query across all sessions with DuckDB
df = query_echoes_jsonl_duckdb("has_images = true")
```

### JSON Field Queries (DuckDB)

```python
# Query nested content (DuckDB JSON syntax)
df = query_echoes_parquet("""
    json_extract_string(metadata, '$.tool_name') = 'create_chart'
""")

# Query tool calls
df = query_echoes_parquet("""
    tool_calls IS NOT NULL AND
    json_array_length(tool_calls) > 0
""")
```

## Rollout Strategy

1. **Phase 1:** Add echo logging to critical paths (agent calls, tool executions)
2. **Phase 2:** Add timing tracking with `TimingContext`
3. **Phase 3:** Enrich with usage data (modify agent.py)
4. **Phase 4:** Add cost correlation (modify cost.py)
5. **Phase 5:** Full coverage (all log_message calls mirrored)

**Incremental approach** - no need to do everything at once!

## Storage Locations

```
logs/
  echoes/                           # Parquet files
    echoes_1733112000_abc123.parquet
    echoes_1733112100_def456.parquet
    ...

  echoes_jsonl/                     # JSONL files (one per session)
    session_123.jsonl
    session_124.jsonl
    ...

  log_1733112000_abc123.parquet     # Existing logs (kept for backward compat)
  ...
```

## Benefits

- ✅ **Dual format:** Parquet for analytics, JSONL for debugging
- ✅ **Full content:** No stringification, native JSON preserved
- ✅ **Performance metrics:** Timing, tokens, cost all linked
- ✅ **Image tracking:** Base64 detected, file paths linked to trace_ids
- ✅ **Backward compatible:** Existing logs.py unchanged
- ✅ **Queryable:** DuckDB works with both formats
- ✅ **Human readable:** JSONL files can be viewed with cat/jq/less
