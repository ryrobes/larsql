# Context Accumulation Analysis: Why Follow-Up Messages Are Expensive

**Date:** 2025-12-06
**Analyzed Session:** `ui_run_bad682b0f785`
**Most Expensive Follow-Up:** 93,301 input tokens ($0.28)

## Executive Summary

**Follow-up messages are expensive because they inherit the FULL accumulated context from ALL previous phases in a cascade, including massive tool results (221k chars) and base64 images (426k chars). The default culling is disabled (`keep_recent_turns=0`), so nothing is removed.**

**Key Finding:** Follow-up messages aren't inherently more expensive than initial agent calls - **BOTH are expensive in later phases** due to context accumulation across the entire cascade.

## The Smoking Gun

Session `ui_run_bad682b0f785` progression across 5 phases:

| Phase | Agent Call Tokens | Follow-Up Tokens | Delta |
|-------|------------------|------------------|-------|
| 1. discover_schema | 345 | 71,545 | +71,200 |
| 2. write_query | 72,452 | 74,266 | +1,814 |
| 3. analyze_results | 74,622 | (none) | - |
| 4. create_initial_chart | 75,739 → 80,371 → 84,385 | 89,945 | +14,206 |
| 5. say_summary_summarize | 93,029 | **93,301** | +272 |

**Total cost for this cascade:** ~$2.15 (95% in later phases)

## Root Causes

### 1. `self.context_messages` Never Resets Between Phases

**File:** `windlass/runner.py:93`
```python
self.context_messages: List[Dict[str, str]] = []  # Initialized ONCE per cascade
```

This list accumulates **across ALL phases** and is **never cleared**.

### 2. Default Culling is Disabled

**File:** `windlass/runner.py:2560-2567`
```python
keep_images = int(os.getenv('WINDLASS_KEEP_RECENT_IMAGES', '0'))  # DEFAULT: 0
keep_turns = int(os.getenv('WINDLASS_KEEP_RECENT_TURNS', '0'))    # DEFAULT: 0
```

**File:** `windlass/utils.py:216`
```python
if not keep_recent_turns or keep_recent_turns <= 0:
    return messages  # ❌ RETURNS EVERYTHING - NO CULLING!
```

### 3. What Accumulates

Final phase (`say_summary_summarize`) context analysis:
- **23 messages** spanning all 5 phases
- **1,569,680 characters** (~1.5 MB)
- **93,029 input tokens**

**Content breakdown:**
```
Message  3: 37,936 chars   - Tool result (sql_search schema)
Message  4: 221,143 chars  - Tool result (sql_search property) ❌ MASSIVE!
Message 20: 8,969 chars    - Chart analysis
Plus: 2 base64 images from chart generation
```

**Accumulates:**
- System messages (tool definitions)
- User messages (phase tasks)
- Assistant responses
- **Tool results** (including 221k char schemas!)
- **Base64 images** (from chart generation - 426k chars!)
- Multiple turn iterations
- Soundings/reforge context

### 4. Follow-Up vs First Call - No Difference!

**Evidence from `say_summary_summarize` phase:**
- Agent call: 93,029 tokens
- Follow-up: 93,301 tokens
- **Difference: only 272 tokens** (one tool result added)

**Both calls use the SAME `culled_context` from `self.context_messages`!**

The reason follow_up appears expensive:
1. Happens AFTER tool calls (context already large)
2. Occurs in **later phases** (accumulated context)
3. Labeled distinctly in logs (`node_type='follow_up'`)

## Context Flow Diagram

```
Phase 1: discover_schema
  context_messages = []
    → System msg (tools)
    → User msg (task)
    → Agent call: 345 tokens ✅
    → Tool result: 37k chars
    → Tool result: 221k chars ❌ HUGE!
    → Follow-up: 71,545 tokens ❌ EXPLOSION!

Phase 2: write_query
  context_messages = [Phase 1 messages...] ← Still has 221k char result!
    → System msg (new tools)
    → User msg (new task)
    → Agent call: 72,452 tokens ❌ Already expensive!
    → Tool result
    → Follow-up: 74,266 tokens

Phase 3: analyze_results
  context_messages = [Phase 1 + Phase 2 messages...]
    → User msg
    → Agent call: 74,622 tokens ❌ Even more!

Phase 4: create_initial_chart (soundings + reforge)
  context_messages = [Phase 1 + 2 + 3 messages...]
    → Agent call: 75,739 tokens
    → Base64 image: 426k chars! ❌ MASSIVE IMAGE!
    → Follow-up: 80,371 tokens
    → More images...
    → Follow-up: 84,385 → 89,945 tokens

Phase 5: say_summary_summarize
  context_messages = [ALL previous phases + images...]
    → Agent call: 93,029 tokens ❌ MOST EXPENSIVE!
    → Follow-up: 93,301 tokens
```

**The snowball effect is exponential!**

## Why This Architecture?

`context_messages` is **phase-local** within a single cascade execution, but accumulates across phases.

**The "snowball" works through:**
1. State variables (`{{ state.var }}`)
2. Lineage (previous phase outputs)
3. Instructions that reference Echo history

**BUT:** The actual LLM messages (`context_messages`) accumulate EVERYTHING!

**Question:** Was this intentional or a bug?

## Recommendations

### Immediate Fix (Minimal Code Change)

**Set environment variables to enable culling:**
```bash
export WINDLASS_KEEP_RECENT_TURNS=10  # Keep last 10 turns (~30 messages)
export WINDLASS_KEEP_RECENT_IMAGES=3   # Keep last 3 images
```

**Expected impact:** Reduce tokens from 93k → ~15-20k for later phases

### Short-Term Fixes

#### Option 1: Reset at Phase Boundaries
```python
# In runner.py, at start of execute_phase():
def execute_phase(self, phase, input_data, trace):
    # Keep only system message + essential recent context
    essential = [msg for msg in self.context_messages if msg.get('role') == 'system']
    essential += self.context_messages[-6:]  # Last 2 turns
    self.context_messages = essential
```

#### Option 2: Smart Tool Result Culling
```python
def cull_large_tool_results(messages, max_size=10000):
    """Truncate large tool results after processing."""
    for msg in messages:
        if msg.get('role') == 'user' and 'Tool Result' in str(msg.get('content', '')):
            content = msg['content']
            if len(content) > max_size:
                msg['content'] = content[:max_size] + f'\n[Truncated {len(content)-max_size} chars]'
    return messages
```

#### Option 3: Image Reference Instead of Embedding
```python
# After saving image to disk, don't keep base64 in context
# Replace base64 with reference: "[Image saved: images/session_123/phase_name/image_0.png]"
```

### Long-Term Architectural Improvements

#### 1. Explicit Context Control per Phase
Add `context_strategy` field to `PhaseConfig`:
```json
{
  "name": "expensive_phase",
  "context_strategy": "minimal",  // Options: "fresh", "minimal", "full", "sliding"
  "instructions": "..."
}
```

**Strategies:**
- `"fresh"` - No previous context (clean slate)
- `"minimal"` - System msg + last phase output only
- `"full"` - Current behavior (all context)
- `"sliding"` - Auto-cull based on token limits

#### 2. Separate Tool Result Storage
```python
# Don't keep large tool results in message history
# Store in Echo and reference by ID
{
  "role": "user",
  "content": "Tool Result (sql_search): [Stored as result_abc123 - 221k chars]"
}

# Inject full result only when explicitly needed:
{{ outputs.discover_schema.tool_results.result_abc123 }}
```

#### 3. Tiered Context Management
```
System Tier:    Tool definitions (always included)
Recent Tier:    Last N turns (high fidelity)
Archive Tier:   Older messages (summarized or referenced)
```

#### 4. Per-Phase Token Budget
```python
# Warn if phase exceeds expected token budget
if tokens_in > phase.max_input_tokens:
    console.print(f"[yellow]⚠️ Phase {phase.name} exceeds token budget![/yellow]")
    # Auto-cull to stay within budget
```

## Files Involved

- `windlass/runner.py:93` - `self.context_messages` initialization
- `windlass/runner.py:2556-2567` - Culling logic for agent calls
- `windlass/runner.py:2976-2986` - Culling logic for follow-up calls
- `windlass/utils.py:129-193` - `cull_old_base64_images()`
- `windlass/utils.py:195-248` - `cull_old_conversation_history()`
- `windlass/agent.py:23-53` - Agent.run() message construction

## Queries for Investigation

```python
# Find expensive follow_up messages
from windlass.unified_logs import query_unified
df = query_unified("node_type = 'follow_up' AND tokens_in > 50000")

# Analyze context accumulation per phase
df = query_unified("node_type = 'agent' AND session_id = 'session_id_here'")
print(df[['phase_name', 'tokens_in', 'tokens_out', 'cost']])

# Find sessions with large tool results
df = query_unified("node_type = 'tool_result' AND LENGTH(content_json) > 100000")
```

## Conclusion

**The problem:** `context_messages` accumulates indefinitely across phases with no culling by default, causing exponential token growth in multi-phase cascades.

**The fix:** Enable culling via environment variables OR reset context at phase boundaries.

**The opportunity:** Implement explicit context control strategy per phase for fine-grained management.

**Cost impact:** Could reduce cascade costs by 80-90% in multi-phase workflows.
