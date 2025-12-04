# Final Tool Parsing Solution - Smart Validation

## Problem Evolution

### Issue #1: Couldn't Parse ```json Fences
**Fixed:** Extract JSON from ` ```json ... ``` ` blocks

### Issue #2: Extra Closing Braces
**Fixed:** Brace balancing logic

### Issue #3: Too Greedy - Caught Everything
**Fixed:** Only parse ` ```json ` blocks, not raw `{...}`

### Issue #4: Validated ALL JSON (This One!)
**Your observation:** "We don't want to validate ALL JSON blocks! Only tool calls!"

**Exactly right!** We were validating every ```json block, even if it wasn't a tool call.

---

## The Smart Solution

### Only Validate Actual Tool Calls

**Logic flow:**

1. **Extract ` ```json ` blocks** (explicit JSON)

2. **Try to parse each block:**
   - **Parse succeeds** →
     - Has `"tool"` key? → It's a tool call! ✅
     - No `"tool"` key? → Just JSON, ignore ✅

   - **Parse fails** →
     - Contains `"tool"` string? → Broken tool call, send error ⚠️
     - No `"tool"` string? → Not a tool call, ignore ✅

3. **Return:**
   - `(tool_calls, None)` if found valid tool calls
   - `([], error)` if found broken tool calls
   - `([], None)` if no tool calls (normal!)

---

## Examples

### Example 1: Valid Tool Call

**Agent outputs:**
```markdown
```json
{"tool": "run_code", "arguments": {"code": "print('hello')"}}
```
```

**Processing:**
1. Extract from code fence ✅
2. Parse JSON → Success ✅
3. Has `"tool"` key? → Yes ✅
4. **Execute tool!** ✅

**Result:** `(tool_calls=[...], error=None)`

### Example 2: Non-Tool JSON (Ignore)

**Agent outputs:**
```markdown
The result will be:

```json
{
  "fibonacci": [0, 1, 1, 2, 3],
  "sum": 42,
  "result": 13.37
}
```

This shows the structure.
```

**Processing:**
1. Extract from code fence ✅
2. Parse JSON → Success ✅
3. Has `"tool"` key? → **No** ✅
4. **Ignore** (not a tool call) ✅

**Result:** `([], None)` - No error, agent just showing data

### Example 3: Malformed Tool Call

**Agent outputs:**
```markdown
```json
{"tool": "run_code", "arguments": {"code": "..."}}}}
```
```

**Processing:**
1. Extract from code fence ✅
2. Parse JSON → **Fails** (extra braces)
3. Contains `"tool"` string? → **Yes**
4. **Send error back** ⚠️

**Result:** `([], error="Tool call JSON is malformed: Extra data...")`

### Example 4: Malformed Non-Tool JSON (Ignore)

**Agent outputs:**
```markdown
Example output:

```json
{
  "result": 42,
  "note": "this is an example"
}}
```
```

**Processing:**
1. Extract from code fence ✅
2. Parse JSON → **Fails** (extra brace)
3. Contains `"tool"` string? → **No**
4. **Ignore** (not a tool call) ✅

**Result:** `([], None)` - No error, agent just showing example

---

## Why This is Perfect

### No False Positives

**Scenarios that are now handled correctly:**

**✅ Soundings with JSON examples:**
- Agent shows data structures in ```json blocks
- No `"tool"` key
- **Ignored** (no validation errors)

**✅ Agents explaining JSON:**
```markdown
The API returns:
```json
{"status": "success", "data": [...]}
```
```
- No `"tool"` key
- **Ignored**

**✅ Test data in JSON:**
```markdown
Test with:
```json
{"input": 123, "expected": 456}
```
```
- No `"tool"` key
- **Ignored**

**⚠️ Broken tool calls:**
```markdown
```json
{"tool": "run_code", "arguments": ...}}}}
```
```
- Has `"tool"` string
- **Validated and error sent**

---

## Implementation

### Smart Validation (runner.py:195-261)

```python
for block in all_json_blocks:
    # Try to parse
    try:
        data = json.loads(block)
    except JSONDecodeError:
        # Only report error if it looks like a tool call
        if '"tool"' in block or "'tool'" in block:
            # Broken tool call - send detailed error
            parse_errors.append(...)
        continue  # Otherwise ignore

    # Parsed successfully - check if it's a tool call
    if "tool" not in data:
        continue  # Just JSON, not a tool call, ignore

    # This IS a tool call - validate and execute
    tool_calls.append(...)
```

**Key insight:** Only validate if `"tool"` key is present (or string `"tool"` in malformed JSON).

---

## Benefits

### 1. No Boomeranging

**Before:**
- Agent outputs data example in ```json block
- Validated as tool call
- Fails (no `"tool"` key expected!)
- Error sent back
- Agent confused

**After:**
- Agent outputs data example
- Parsed successfully
- No `"tool"` key → **Ignore**
- Agent continues normally ✅

### 2. Only Real Tool Errors

**Only sends errors when:**
- Block contains `"tool"` string (looks like tool call)
- JSON parsing fails (malformed)

**Doesn't send errors for:**
- Valid JSON without `"tool"` key (not a tool call)
- Malformed JSON without `"tool"` string (not a tool call attempt)

### 3. Clean Iteration

**Soundings that write code:**
- No tools needed
- Agent writes Python + explains
- May include JSON examples
- **No validation errors** ✅
- Soundings complete successfully ✅

**Phases with tools:**
- Agent calls tools with ```json blocks
- Must have `"tool"` key
- Validated only if malformed
- Tools execute properly ✅

---

## Comparison

| Scenario | Before | After |
|----------|--------|-------|
| Valid tool call | ✅ Execute | ✅ Execute |
| Malformed tool call | ✅ Error | ✅ Error |
| JSON example (no "tool") | ❌ Error! | ✅ Ignore |
| Python code {...} | ❌ Error! | ✅ Ignore |
| Markdown JSON block | ❌ Error! | ✅ Ignore |

---

## Files Modified

**`windlass/windlass/runner.py`** (lines 195-261)
- Smart validation: Only validate if `"tool"` key present
- Ignore non-tool JSON blocks
- Only report errors for tool call attempts
- Clean separation

---

## Summary

**Your insight:**
> "We don't want to validate ALL JSON blocks! Only tool calls!"

**Exactly!** The fix:
- ✅ Parse only ` ```json ` blocks (explicit)
- ✅ Check if parsed JSON has `"tool"` key
- ✅ Only validate/report errors for actual tool calls
- ✅ Ignore everything else

**Result:**
- 🎯 Soundings work (no false validation errors)
- 🔧 Tools execute when intended
- 💬 Agents can use JSON for examples/explanations
- ✅ max_turns iteration works perfectly

**No more boomeranging!** 🎉
