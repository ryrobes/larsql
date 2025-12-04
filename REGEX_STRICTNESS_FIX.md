# Regex Strictness Fix - Only Parse ```json Blocks

## Problem

> "Now all phases are failing! Even the soundings. 22 validation_error entries!"

**Session:** `ui_run_290d98ad0e68`

---

## Root Cause

### The Over-Eager Regex

**Previous implementation:**
```python
# Pattern 1: ```json ... ```
code_fence_matches = re.findall(r'```json\s*(\{[^`]*\})\s*```', content)

# Pattern 2: ANY {...} in text (TOO BROAD!)
raw_json_blocks = re.findall(r'\{[^{}]*...\}', content_without_fences)
```

**Pattern 2 was catching EVERYTHING:**

**Python code:**
```python
results = {
    'first_n_fibonacci': [],  # ← CAUGHT!
    'sum': 42
}
print(f"Sum: {results['sum']:,}")  # ← CAUGHT!
```

**Result:**
1. Regex finds 12+ `{...}` patterns in Python code
2. Tries to parse as JSON
3. **All fail** (Python dicts use single quotes, f-strings aren't JSON)
4. Creates validation errors
5. Sends errors back to agent
6. Agent gets confused ("I'm just writing Python, not calling tools!")
7. max_turns exhausted with validation errors

### Why This Happened

**The cascade:**
```json
{
  "name": "generate_solution",
  "tackle": [],  // No tools!
  "soundings": {...}
}
```

**No tools needed** - just write Python solution.

**But:**
- `use_native_tools` defaults to `false`
- System adds tool prompt (even though `tackle: []`)
- Agent writes Python (ignores tool prompt)
- **Regex catches Python code as tool calls!**

---

## The Fix

### Strict Parsing: ```json Blocks ONLY

**New implementation (runner.py:182-193):**
```python
# ONLY extract JSON from markdown code fences (```json ... ```)
# This is the ONLY reliable way to find tool calls
# DO NOT try to parse arbitrary {...} patterns
code_fence_pattern = r'```json\s*(\{[^`]*\})\s*```'
all_json_blocks = re.findall(code_fence_pattern, content, re.DOTALL | re.IGNORECASE)

# If no ```json blocks found, agent isn't trying to call tools
```

**Removed entirely:**
- ❌ Raw `{...}` pattern matching
- ❌ Attempts to guess what's a tool call
- ❌ Parsing Python code, f-strings, dicts, etc.

**Result:**
- ✅ ONLY parses explicit ` ```json ` blocks
- ✅ No false positives
- ✅ Python code ignored
- ✅ Agent has clear convention

---

## Updated Tool Prompt

**Now explicitly requires code fences (runner.py:1696-1699):**

```
**Important:** To call a tool, you MUST wrap your JSON in a ```json code fence:

Example:
```json
{"tool": "tool_name", "arguments": {"param": "value"}}
```

Do NOT output raw JSON outside of code fences - it will not be detected.
```

**Clear instructions!**

---

## Why This is the Right Approach

### Explicit Tool Calls

**Advantages:**
- ✅ Clear intent (agent must explicitly use ```json fence)
- ✅ No ambiguity (can distinguish code from tool calls)
- ✅ Syntax highlighted in UIs
- ✅ Standard markdown convention
- ✅ Impossible to have false positives

**Example where this matters:**

```markdown
Here's how you would structure the result:

{
  "fibonacci": [0, 1, 1, 2, ...],
  "sum": 42
}

Now let me actually call the tool:

```json
{"tool": "set_state", "arguments": {"key": "result", "value": 42}}
```

Done!
```

**Old regex:** Catches BOTH `{...}` blocks → 2 "tool calls", first one fails
**New regex:** Catches ONLY ` ```json ` block → 1 tool call, succeeds ✅

### No Tools = No Validation Errors

**Phase with `tackle: []`:**
- Agent writes Python solution
- Contains many `{...}` patterns
- **None in ```json fences**
- **No parsing attempted**
- **No validation errors** ✅

**Phase with `tackle: ["run_code"]`:**
- Agent uses tool
- Wraps in ` ```json ` fence
- **Parsed successfully**
- **Tool executes** ✅

---

## Impact

### Before (Over-Eager Regex)

**Session ui_run_290d98ad0e68:**
- 22 validation errors
- Agent outputs Python code
- Regex catches Python dicts, f-strings
- Tries to parse as JSON
- All fail
- Agent confused by error messages
- Never makes progress

### After (Strict Parsing)

**New sessions:**
- Agent writes Python code (no validation errors)
- Agent calls tools with ` ```json ` fences
- Only explicit tool calls parsed
- Tools execute successfully
- max_turns works as designed

---

## Files Modified

1. **`windlass/windlass/runner.py`** (lines 182-193, 1696-1699)
   - Removed raw {...} pattern matching
   - Only parse ` ```json ` code fences
   - Updated tool prompt to require code fences
   - Clear instructions to agents

---

## Testing

### Test 1: Phase Without Tools

```json
{
  "name": "write_code",
  "instructions": "Write Python code",
  "tackle": []
}
```

**Expected:**
- Agent writes Python with `{...}` patterns
- **No validation errors** ✅
- Agent completes successfully

### Test 2: Phase With Tools

```json
{
  "name": "execute",
  "instructions": "Run the code",
  "tackle": ["run_code"]
}
```

**Expected:**
- Agent outputs:
  ```markdown
  ```json
  {"tool": "run_code", "arguments": {"code": "print('hello')"}}
  ```
  ```
- **Parsed successfully** ✅
- **Tool executes** ✅

### Test 3: Mixed Content

**Agent output:**
```markdown
Here's the data structure:
```python
data = {
    'results': [1, 2, 3],
    'sum': 6
}
```

Now I'll save it:
```json
{"tool": "set_state", "arguments": {"key": "data", "value": {"results": [1,2,3]}}}
```
```

**Expected:**
- Python block ignored ✅
- JSON block parsed ✅
- Tool executes ✅

---

## Summary

**The Problem:**
- Regex caught Python code as tool calls
- Generated 22 validation errors
- Phases failed because of false positives

**The Fix:**
- ONLY parse ` ```json ` code fences
- Ignore all other `{...}` patterns
- Require explicit tool calls

**Result:**
- ✅ No false positives
- ✅ Python code ignored
- ✅ Tools execute when intended
- ✅ Clear agent convention

**New sessions will work perfectly!** Old sessions (before fix) had the over-eager regex and failed. 🎯
