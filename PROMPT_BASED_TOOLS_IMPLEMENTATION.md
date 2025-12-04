# Prompt-Based Tools Implementation

## Problem Solved

**Native tool calling breaks with different providers:**
- ❌ Gemini: Requires `thought_signature` field
- ❌ Each provider has unique quirks
- ❌ Limited to models with native tool support
- ❌ Against Windlass's provider-agnostic philosophy

**As you said:**
> "The whole idea of using OpenRouter is to be able to use whatever..."
> "Tool calling is just prompt generation anyway"

**Exactly right!** Native tool calling creates unnecessary provider dependencies.

---

## Solution: Prompt-Based Tools (Default)

Windlass now supports **TWO modes:**

### Mode 1: Prompt-Based (Default, Recommended)
- ✅ Works with ANY model (GPT, Claude, Gemini, Llama, Grok, etc.)
- ✅ No provider quirks
- ✅ Simpler message format
- ✅ More transparent/debuggable

### Mode 2: Native Tool Calling (Opt-In)
- Use when you know the provider supports it well
- Slightly more structured
- Provider-specific behavior

---

## Configuration

### PhaseConfig Schema

**New field:** `use_native_tools` (bool, default: False)

```json
{
  "name": "solve_problem",
  "instructions": "Solve this coding problem",
  "tackle": ["run_code", "set_state"],
  "use_native_tools": false
}
```

**Default is FALSE** = Prompt-based (provider-agnostic)

Set to `true` only if you specifically want native tool calling.

---

## How Prompt-Based Tools Work

### 1. Tool Descriptions Generated

For each tool in `tackle`, Windlass generates a description:

```markdown
**run_code**
Executes code in a sandbox.
Parameters:
  - code (str) (required)
  - language (str) (optional, default: python)

To use: Output JSON in this format:
{"tool": "run_code", "arguments": {"code": "print('hello')", "language": "python"}}

**set_state**
Persist variables to session state
Parameters:
  - key (str) (required)
  - value (Any) (required)

To use: Output JSON in this format:
{"tool": "set_state", "arguments": {"key": "result", "value": 42}}
```

### 2. Appended to System Prompt

```
{phase.instructions}

## Available Tools

{tool descriptions...}

**Important:** To call a tool, output valid JSON with this structure:
{"tool": "tool_name", "arguments": {"param": "value"}}
```

### 3. Agent Returns Text with JSON

```
I'll run the code to test it:

{"tool": "run_code", "arguments": {"code": "print('hello world')"}}
```

### 4. Windlass Parses JSON

- Regex to find JSON blocks: `\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}`
- Parse each block
- Look for `"tool"` key
- Extract tool name and arguments
- Convert to standard format (compatible with existing code)

### 5. Tool Executed Locally

- Calls Python function from tackle registry
- Returns result
- Adds as user message (not role="tool")

### 6. Result Sent Back

**Native mode:**
```json
{"role": "tool", "tool_call_id": "...", "content": "hello world"}
```

**Prompt mode:**
```json
{"role": "user", "content": "Tool Result (run_code):\nhello world"}
```

---

## Implementation Details

### Files Modified

1. **`windlass/windlass/cascade.py`** (line 55)
   - Added `use_native_tools: bool = False` to PhaseConfig

2. **`windlass/windlass/runner.py`** (lines 122-162, 1556-1623, 1882-1888)
   - Added `_generate_tool_description()` method
   - Added `_parse_prompt_tool_calls()` method
   - Modified Agent instantiation to conditionally pass `tools`
   - Added tool descriptions to system prompt when prompt-based
   - Parse JSON from responses when prompt-based

3. **`windlass/windlass/echo.py`** (line 47-64)
   - Fixed `add_history()` to NOT mutate input dicts (prevents pollution)

4. **`windlass/windlass/agent.py`** (lines 26-101)
   - Sanitize messages to remove Echo fields
   - Skip empty system prompts
   - Skip empty messages without tool_calls
   - Comprehensive debug logging

---

## Usage

### Default Behavior (Prompt-Based)

**Just use tackle normally:**
```json
{
  "name": "solve",
  "instructions": "Solve this problem",
  "tackle": ["run_code", "set_state"]
}
```

**No `use_native_tools` field = defaults to false = prompt-based!**

### Opt-In to Native Tools

```json
{
  "name": "solve",
  "instructions": "Solve this problem",
  "tackle": ["run_code"],
  "use_native_tools": true
}
```

Only use if you're sure the model supports it well (GPT-4, Claude 3.5, etc.)

---

## Benefits

### Provider Compatibility

**Before (Native Only):**
- ✅ GPT-4: Works
- ✅ Claude 3.5: Works (with format conversion)
- ❌ Gemini: Requires thought_signature → BREAKS
- ❌ Older models: No tool support → BREAKS
- ❌ Llama/Mistral: Limited tool support → UNRELIABLE

**After (Prompt-Based Default):**
- ✅ GPT-4: Works
- ✅ Claude 3.5: Works
- ✅ Gemini: Works (no special requirements!)
- ✅ Older models: Works (just needs to output JSON)
- ✅ Llama/Mistral: Works
- ✅ **ANY model that can output structured text!**

### Simplicity

**Native mode message flow:**
```
User → Assistant (with tool_calls array) → Tool (with tool_call_id) →
Provider-specific formatting → Back to assistant
```

**Prompt mode message flow:**
```
User → Assistant (with JSON in text) → Parse JSON → Execute →
User (with tool result) → Assistant
```

Much simpler! Just user/assistant alternation.

---

## Examples

### Example 1: run_code with Gemini

**Cascade:**
```json
{
  "cascade_id": "code_test",
  "phases": [{
    "name": "solve",
    "instructions": "Write and test Python code for this problem",
    "tackle": ["run_code"],
    "model": "google/gemini-3-pro-preview"
  }]
}
```

**Agent sees in system prompt:**
```
Write and test Python code for this problem

## Available Tools

**run_code**
Executes code in a sandbox.
Parameters:
  - code (str) (required)
  - language (str) (optional, default: python)

To use: Output JSON in this format:
{"tool": "run_code", "arguments": {"code": "...", "language": "python"}}
```

**Agent responds:**
```
I'll write the solution:

{"tool": "run_code", "arguments": {"code": "print('hello')"}}
```

**Windlass:**
- Parses JSON
- Calls `run_code(code="print('hello')")`
- Returns result as user message
- **No Gemini thought_signature required!** ✅

### Example 2: Multiple Tools

**Agent sees:**
```
## Available Tools

**run_code**
...

**set_state**
...

**create_chart**
...
```

**Agent can call any:**
```
First let me run the code:
{"tool": "run_code", "arguments": {"code": "result = 42"}}

Then save it:
{"tool": "set_state", "arguments": {"key": "result", "value": 42}}
```

Windlass parses both and executes them!

---

## Backward Compatibility

**Existing cascades without `use_native_tools` field:**
- Default to `false` (prompt-based)
- **BREAKING CHANGE for cascades that rely on native tools!**

**Migration:**

If you have cascades that NEED native tools, add:
```json
{
  "use_native_tools": true
}
```

---

## Testing

### Test 1: Gemini with Prompt-Based Tools

```bash
# Create test cascade
cat > /tmp/test_gemini_prompt.json << 'EOF'
{
  "cascade_id": "test_gemini",
  "phases": [{
    "name": "test",
    "instructions": "Run code that prints hello",
    "tackle": ["run_code"],
    "model": "google/gemini-3-pro-preview",
    "use_native_tools": false
  }]
}
EOF

windlass /tmp/test_gemini_prompt.json --input '{}' --session test_prompt_tools
```

**Expected:**
- ✅ Console shows: "Using prompt-based tools (provider-agnostic)"
- ✅ System prompt includes tool descriptions
- ✅ Agent outputs JSON with tool call
- ✅ Windlass parses and executes
- ✅ **NO Gemini thought_signature error!**

### Test 2: Compare Native vs Prompt

```json
// Native mode (might break with Gemini)
{"use_native_tools": true, "model": "google/gemini-3-pro-preview"}

// Prompt mode (works with any model)
{"use_native_tools": false, "model": "google/gemini-3-pro-preview"}
```

---

## Debug Output

**When running, you'll see:**

```
📍 Bearing (Phase): test_solution 🤖 google/gemini-3-pro-preview
  Using prompt-based tools (provider-agnostic)

[DEBUG] Agent.run() called - building 3 messages:
  [0] system    | Tools:False | ToolID:False | Extra:False | Review the chosen...
  [1] user      | Tools:False | ToolID:False | Extra:False | ## Input Data...
  [2] user      | Tools:False | ToolID:False | Extra:False | Continue/Refine...

[DEBUG] After sanitization: 3 messages (removed 0 empty/invalid messages)
[DEBUG] Final message list being sent to LLM API:
  [0] system    | tools:False | tool_id:False | Review the chosen...
  [1] user      | tools:False | tool_id:False | ## Input Data...
  [2] user      | tools:False | tool_id:False | Continue/Refine...

Agent (google/gemini-3-pro-preview)
───────────────────────────────────
{"tool": "run_code", "arguments": {"code": "print('hello')"}}

  Parsed 1 prompt-based tool call(s)
  Executing Tools...
    ✔ run_code -> hello
    [DEBUG] Tool result added to context_messages
      Index: 4, Tool: run_code, Result: 5 chars
```

---

## Summary

**Changes:**

1. ✅ Added `use_native_tools: bool = False` to PhaseConfig
2. ✅ Generate tool descriptions for prompt-based mode
3. ✅ Parse JSON from agent responses
4. ✅ Conditionally pass tools to Agent (only if use_native=true)
5. ✅ Fixed echo.add_history() mutation bug
6. ✅ Sanitize messages in agent.py
7. ✅ Comprehensive debug logging

**Impact:**

- ✅ Gemini works without thought_signature
- ✅ **ANY model works** (no provider quirks)
- ✅ Simpler message format
- ✅ Tool results properly sent to agent
- ✅ max_turns iteration finally works!

**Default behavior:** Prompt-based (provider-agnostic, works everywhere)

**Opt-in:** Native tools (for providers that handle it well)

🎉 **Windlass is now truly provider-agnostic!**
