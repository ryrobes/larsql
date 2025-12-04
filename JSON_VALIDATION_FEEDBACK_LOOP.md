# JSON Validation Feedback Loop

## Your Idea

> "Can we add a step before tool generation that tests the tool call JSON to make sure it is valid, and if not send THAT error message back? This should work in our system and just use up a 'turn', which is fine."

**Brilliant!** Instead of silently fixing errors, **teach the agent to fix itself** within the max_turns loop!

---

## Implementation

### Parser Returns Errors (runner.py:164-255)

**Changed signature:**
```python
# OLD
def _parse_prompt_tool_calls(content: str) -> List[Dict]:
    return tool_calls

# NEW
def _parse_prompt_tool_calls(content: str) -> tuple[List[Dict], str]:
    return tool_calls, error_message
```

**Returns:**
- `(tool_calls, None)` - Success! Parsed valid JSON
- `([], error_message)` - Parsing failed, here's why
- `([], None)` - No JSON found (agent just talking)

### Detailed Error Messages

**When JSON parsing fails:**
```python
error_detail = f"Tool call {block_idx + 1}: Invalid JSON at position {e.pos}\n"
error_detail += f"  Error: {e.msg}\n"
error_detail += f"  Your JSON: {block[:100]}...\n"

# Diagnose common errors
if closes > opens:
    error_detail += f"  → You have {closes - opens} extra closing braces }}\n"
elif opens > closes:
    error_detail += f"  → You're missing {opens - closes} closing braces }}\n"

if block.count('"') % 2 != 0:
    error_detail += f"  → Unmatched quotes detected\n"
```

**Helpful, actionable feedback!**

### Send Error to Agent (runner.py:1956-1985)

**When parse_error occurs:**
```python
if parse_error:
    # Show error to user
    console.print(f"{indent}  [bold red]⚠️  JSON Parse Error:[/bold red] {parse_error}")

    # Add error message to context for NEXT turn
    error_msg = {
        "role": "user",
        "content": f"⚠️ Tool Call JSON Error:\n{parse_error}\n\nPlease fix the JSON and try again. Ensure proper brace matching: {{ and }}"
    }
    self.context_messages.append(error_msg)

    # Log it
    self.echo.add_history(error_msg, ..., node_type="validation_error")

    # Don't execute tools - continue to next turn
    json_parse_error = True
```

**Agent sees the error on next turn and fixes it!**

---

## How It Works

### Turn 1: Agent Makes JSON Error

**Agent outputs:**
```markdown
```json
{"tool": "run_code", "arguments": {"code": "print('hello')"}}}}
```
```

**Windlass:**
1. Tries to parse JSON
2. Detects 2 extra closing braces
3. **Sends error back:**
   ```
   ⚠️ Tool Call JSON Error:
   Tool call 1: Invalid JSON at position 74
     Error: Extra data
     Your JSON: {"tool": "run_code", "arguments": {"code": "print('hello')"}}}}
     → You have 2 extra closing braces }}

   Please fix the JSON and try again. Ensure proper brace matching: { and }
   ```
4. Continues to Turn 2 (doesn't execute tool)

### Turn 2: Agent Fixes JSON

**Agent sees error, responds:**
```markdown
I apologize for the extra braces. Here's the corrected JSON:

```json
{"tool": "run_code", "arguments": {"code": "print('hello')"}}
```
```

**Windlass:**
1. Parses JSON - **Success!** ✅
2. Executes run_code
3. Returns result
4. Agent sees output, validates it works

**The agent learned to fix its JSON!** 🎯

---

## Benefits

### 1. Agent Self-Correction

**Before (silent fixing):**
- Windlass auto-fixes JSON
- Agent doesn't learn
- Might make same error repeatedly
- No feedback loop

**After (validation feedback):**
- Agent sees the error
- Learns what went wrong
- Fixes it on next turn
- Gets better over time

**Uses max_turns iteration as designed!**

### 2. Actionable Error Messages

**Not just:**
> "Invalid JSON"

**But:**
> "Invalid JSON at position 74
>  Error: Extra data
>  Your JSON: {"tool": "run_code", ...}}}}
>  → You have 2 extra closing braces }}
>
>  Please fix the JSON and try again."

**Agent knows exactly what to fix!**

### 3. Validates Structure

**Also checks:**
- ✅ `"tool"` key exists
- ✅ `"arguments"` is a dict (not string, array, etc.)
- ✅ Properly balanced braces
- ✅ Matched quotes

**Catches errors early!**

### 4. Uses Existing max_turns

**No new mechanism needed:**
- Turn 1: JSON error → feedback sent
- Turn 2: Agent fixes → tool executes
- Turn 3: Agent validates result

**Already built-in!**

---

## Example Scenarios

### Scenario 1: Extra Braces

**Turn 1:**
```
Agent: {"tool": "run_code", "arguments": {...}}}}
Error: You have 2 extra closing braces }}
```

**Turn 2:**
```
Agent: {"tool": "run_code", "arguments": {...}}
✅ Parsed! Executing...
Result: hello world
```

### Scenario 2: Missing Braces

**Turn 1:**
```
Agent: {"tool": "run_code", "arguments": {"code": "..."
Error: You're missing 2 closing braces }}
```

**Turn 2:**
```
Agent: {"tool": "run_code", "arguments": {"code": "..."}}
✅ Parsed! Executing...
```

### Scenario 3: Unmatched Quotes

**Turn 1:**
```
Agent: {"tool": "run_code", "arguments": {"code": "print("hello)}}
Error: Unmatched quotes detected
```

**Turn 2:**
```
Agent: {"tool": "run_code", "arguments": {"code": "print('hello')"}}
✅ Parsed! Executing...
```

### Scenario 4: Wrong Structure

**Turn 1:**
```
Agent: {"tool": "run_code", "arguments": "print('hello')"}
Error: 'arguments' must be a dict/object, got str
```

**Turn 2:**
```
Agent: {"tool": "run_code", "arguments": {"code": "print('hello')"}}
✅ Parsed! Executing...
```

---

## Error Message Format

**Sent to agent:**
```
⚠️ Tool Call JSON Error:
Found JSON block(s) but failed to parse:

Tool call 1: Invalid JSON at position 74
  Error: Extra data
  Your JSON: {"tool": "run_code", "arguments": {"code": "import math\nprint(math.pi)"}}}}...
  → You have 2 extra closing braces }}

Please fix the JSON and try again. Ensure proper brace matching: { and }
```

**Clear, actionable, helps agent fix it!**

---

## Logging

**New node_type:** `"validation_error"`

**Logged as:**
- Console: `[bold red]⚠️  JSON Parse Error:[/bold red] {error}`
- Echo: User message with error details
- Logs: `node_type="validation_error"` with metadata

**Visible in Debug Modal!**

---

## Why This is Better

### Silent Fixing (What I Did Initially)

**Pros:**
- Tools execute even with errors
- No extra turns needed

**Cons:**
- ❌ Agent doesn't learn
- ❌ Might make same error repeatedly
- ❌ Hides problems
- ❌ No feedback loop

### Validation Feedback (What We Just Did)

**Pros:**
- ✅ Agent learns from errors
- ✅ Gets better over time
- ✅ Uses max_turns as designed
- ✅ Clear error visibility
- ✅ Self-correcting system

**Cons:**
- Uses one turn for correction (but that's the point of max_turns!)

**Much better architecture!** 🎯

---

## Files Modified

1. **`windlass/windlass/runner.py`** (lines 164-255, 1956-1989)
   - Updated `_parse_prompt_tool_calls()` to return (tool_calls, error)
   - Detailed error messages with diagnostics
   - Send errors back to agent as user messages
   - Skip tool execution when JSON invalid
   - Log validation errors

2. **`extras/ui/backend/app.py`** (new endpoint)
   - Added `/api/session/<session_id>/dump`
   - Saves session to JSON file for debugging

3. **`extras/ui/frontend/src/components/DebugModal.js`** (dump button)
   - "Dump" button to save session

4. **`extras/ui/frontend/src/components/DebugModal.css`** (dump styling)

---

## Testing

### Test JSON Error Correction

```bash
# Run a cascade - agent might make JSON error
windlass windlass/examples/test_prompt_tools.json \
  --input '{"problem": "Print hello"}' \
  --session test_json_validation
```

**If agent makes error, you'll see:**
```
Agent (model)
─────────────
```json
{"tool": "run_code", ...}}}}
```

  ⚠️  JSON Parse Error:
  Tool call 1: Invalid JSON at position 74
    → You have 2 extra closing braces }}

Agent (model) - Turn 2
──────────────────────
I apologize! Here's the corrected JSON:

```json
{"tool": "run_code", "arguments": {"code": "print('hello')"}}
```

  Parsed 1 prompt-based tool call(s)
  Executing Tools...
    ✔ run_code -> hello world
```

**Agent fixes itself!** ✅

---

## Summary

**Your idea:**
> "Test the JSON and send errors back - uses up a turn, which is fine"

**Exactly right!** This is:
- ✅ Cleaner than silent fixing
- ✅ Uses max_turns as designed
- ✅ Agent learns from errors
- ✅ Self-correcting system

**Plus added:**
- ✅ Session dump feature (makes debugging trivial!)
- ✅ Dump button in Debug Modal
- ✅ Detailed error diagnostics

**Result:** Agents fix their own JSON errors within max_turns iteration! Perfect use of the encapsulated iteration loop. 🎉
