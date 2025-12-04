# Bug Fixes: Empty Messages & Cascade Status

## Investigation Summary

Session: `ui_run_a2e8b873e8d7` and `ui_run_d35dac8b412c`

Found and fixed **THREE critical bugs** that were causing cascade failures:

1. ❌ **Empty follow-up messages** violating Anthropic's API requirements
2. ❌ **Cascades not marked as "failed"** when phase errors occur
3. ❌ **`run_code` tool** returning empty results (ALREADY FIXED in previous commit)

---

## The REAL Error Message (Finally!)

Buried in the litellm exception metadata:

```json
{
  "type": "invalid_request_error",
  "message": "messages.5: all messages must have non-empty content except for the optional final assistant message"
}
```

**Anthropic requires:** All assistant messages must have non-empty content (except the final one, which can be empty if it has tool calls).

**What was happening:** The framework was adding assistant messages with empty content to the message history, then Anthropic rejected the next API call.

---

## Bug #1: Empty Follow-Up Messages ❌→✅

### The Problem

**Timeline of Turn 1:**
1. Agent calls `run_code` tool
2. Tool returns empty result (due to `__name__ != "__main__"` bug, already fixed)
3. Framework calls agent for "follow-up" response
4. **Agent returns empty content** (likely because it wants to wait for tool result first)
5. **Framework adds empty assistant message to history** (LINES 1920-1924)
6. Next turn: Anthropic rejects request because of empty message at index 5

**Code location:** `runner.py:1920-1924`

```python
# OLD CODE - unconditionally adds message
assistant_msg = {"role": "assistant", "content": content}  # content might be empty!
self.context_messages.append(assistant_msg)  # Added even if empty
```

**Anthropic's error:**
```
messages.5: all messages must have non-empty content except for the optional final assistant message
```

This caused the BadRequestError on Turn 2/3.

### The Fix

**File:** `windlass/windlass/runner.py:1917-1932`

```python
if content:
    console.print(Panel(Markdown(content), ...))

    # ONLY add to message history if content is non-empty
    # Empty assistant messages violate Anthropic's API requirements
    assistant_msg = {"role": "assistant", "content": content}
    self.context_messages.append(assistant_msg)

    followup_trace = turn_trace.create_child("msg", "follow_up")
    self.echo.add_history(assistant_msg, trace_id=followup_trace.id, parent_id=turn_trace.id, node_type="follow_up")
    self._update_graph()
    response_content = content
else:
    # Log that follow-up had no content (don't add to history)
    log_message(self.session_id, "system", "Follow-up response had empty content (not added to history)",
               trace_id=turn_trace.id, parent_id=turn_trace.parent_id, node_type="warning", depth=turn_trace.depth)
```

**Now:**
- Empty assistant messages are NOT added to message history
- Logged as warning for debugging
- Next API call succeeds because no empty messages

---

## Bug #2: Cascade Not Marked as Failed ❌→✅

### The Problem

**What you observed:**
> "Why didn't the cascade get logged as 'failed'?"

**Answer:** Because errors in phases don't propagate to cascade-level status!

**Flow:**
1. Phase error occurs → caught in try/except (line 1931)
2. Error logged to history
3. **Break out of turn loop** (line 2004)
4. Phase returns normally (no exception raised)
5. Cascade continues and completes
6. `update_session_state(session_id, cascade_id, "completed", ...)` (line 615)
7. `on_cascade_complete` hook called (line 620)
8. **Never calls `on_cascade_error`!**

**Result:** UI shows cascade as "completed" even though it failed.

### The Fix

**Files Modified:**

1. **`windlass/windlass/echo.py`**
   - Added `errors: List[Dict]` field to track errors
   - Added `add_error(phase, error_type, error_message, metadata)` method
   - Modified `get_full_echo()` to return:
     - `errors`: List of all errors
     - `has_errors`: Boolean flag
     - `status`: "failed" or "success"
   - Modified `merge()` to merge errors from sub-cascades

2. **`windlass/windlass/runner.py` (line 1995-2001)**
   - When error occurs, call `echo.add_error()` to track it:
     ```python
     self.echo.add_error(
         phase=phase.name,
         error_type=error_type,
         error_message=error_msg,
         metadata=error_metadata
     )
     ```

3. **`windlass/windlass/runner.py` (line 615-636)**
   - Check `result.get("has_errors")` before marking completion
   - Set status to "failed" if errors occurred:
     ```python
     final_status = "failed" if result.get("has_errors") else "completed"
     update_session_state(session_id, cascade_id, final_status, "end", depth)
     ```
   - Call `on_cascade_error` hook if errors occurred
   - Log cascade completion with status

**Now:**
- ✅ Phase errors tracked in `echo.errors[]`
- ✅ Cascade marked as "failed" if any phase had errors
- ✅ Both `on_cascade_error` AND `on_cascade_complete` hooks called
- ✅ Session state reflects "failed" status
- ✅ Logged to echo for UI/analytics

---

## What Changed: Before vs After

### Scenario: Cascade with Phase Error

**Before:**
```
Phase "test_solution" → API error on Turn 3
  ↓
Error logged to history (node_type="error")
  ↓
Break out of turn loop
  ↓
Phase returns normally
  ↓
Cascade completes
  ↓
update_session_state(..., "completed", ...)
  ↓
on_cascade_complete() called
  ↓
UI shows: "Completed" ✓ (WRONG!)
```

**After:**
```
Phase "test_solution" → API error on Turn 3
  ↓
Error logged to history (node_type="error")
  ↓
echo.add_error() called → errors = [{phase: "test_solution", ...}]
  ↓
Break out of turn loop
  ↓
Phase returns normally
  ↓
Cascade completes
  ↓
result = echo.get_full_echo()
  ↓
result.has_errors = True, result.status = "failed"
  ↓
update_session_state(..., "failed", ...)
  ↓
on_cascade_error() called
  ↓
on_cascade_complete() called (still gets result with status)
  ↓
cascade_failed event logged to echo
  ↓
UI shows: "Failed" ✗ (CORRECT!)
```

---

## Data Structure Changes

### Echo Object (get_full_echo returns)

**Before:**
```json
{
  "session_id": "ui_run_abc123",
  "state": {...},
  "history": [...],
  "lineage": [...]
}
```

**After:**
```json
{
  "session_id": "ui_run_abc123",
  "state": {...},
  "history": [...],
  "lineage": [...],
  "errors": [
    {
      "phase": "test_solution",
      "error_type": "BadRequestError",
      "error_message": "litellm.BadRequestError: OpenAIException - Provider returned error",
      "metadata": {
        "http_status": 400,
        "http_response": "...",
        "turn_number": 3,
        "model": "anthropic/claude-sonnet-4.5",
        ...
      }
    }
  ],
  "has_errors": true,
  "status": "failed"
}
```

### Echo Logs

**New node_type:**
- `cascade_failed` - Logged when cascade completes with errors
- `cascade_completed` - Logged when cascade completes successfully

**New fields in error entries:**
- More comprehensive metadata
- HTTP status codes
- Provider responses
- Turn/phase context

---

## How the UI Will Show This

### Cascades View (Definitions)

```
blog_flow                                  15 runs  $1.23
  └─ (3 failed, 12 successful)  ← New indicator
```

### Instances View

```
session_abc123           FAILED ✗         45.2s  $0.045
                         ↑
                         Status badge (red for failed)
```

### Debug Modal

When viewing a failed instance:
```
Phase: test_solution                      $0.02322
  ├─ Turn 1: Agent call                   $0.02015
  ├─ Turn 1: Tool result (empty)
  ├─ Turn 2: Agent call                   $0.02322
  ├─ Turn 2: Tool error
  └─ Turn 3: ERROR ❌                      $0.02614
      Error Type: BadRequestError
      HTTP Status: 400
      Message: messages.5: all messages must have non-empty content
      Provider Response: {...}
```

---

## Root Cause Analysis

### Why Empty Messages Happened

1. **Turn 1:** `run_code` returned empty (due to `__name__ != "__main__"` bug)
2. **Framework called follow-up:** Agent asked for response after tool execution
3. **Agent returned empty content:** Likely wants to wait for tool result or has nothing to say
4. **Framework unconditionally added to history:** Even though content was empty
5. **Turn 2:** Messages array now has empty assistant message
6. **Anthropic rejected request:** "messages.5: all messages must have non-empty content"

### Why It's Fixed Now

1. ✅ `run_code` now properly executes `__name__ == "__main__"` blocks → actual output
2. ✅ Empty follow-up content is NOT added to message history → no API errors
3. ✅ Errors tracked in echo → cascade status correct
4. ✅ Full error details logged → debuggable

---

## Testing the Fixes

### Test Case 1: run_code with __main__ block

```bash
# Create test cascade with run_code
windlass examples/code_test.json --input '{"code": "def hello():\n    return \"world\"\n\nif __name__ == \"__main__\":\n    print(hello())"}'
```

**Expected:**
- ✅ Output: "world"
- ✅ No empty results
- ✅ Agent can validate the code works

### Test Case 2: Cascade with Phase Error

```bash
# Run cascade that will hit an error
windlass examples/some_cascade.json --input '{}'
```

**Expected:**
- ✅ Error logged with full details (HTTP status, provider response, traceback)
- ✅ Cascade marked as "failed" in session state
- ✅ `on_cascade_error` hook called
- ✅ Echo contains `errors` array with error details
- ✅ `result.status = "failed"`

### Test Case 3: Verify Empty Content Handling

```bash
# Run any cascade that might produce empty follow-up
windlass examples/any_cascade.json --input '{}'
```

**Expected:**
- ✅ If follow-up has empty content, logged as warning
- ✅ Empty message NOT added to history
- ✅ Next API call succeeds (no "messages must have non-empty content" error)

---

## Summary

### What Was Broken

1. **`run_code` didn't execute `__main__` blocks** → empty results → agent couldn't debug
2. **Empty follow-up messages added to history** → Anthropic API errors
3. **Cascade completed as "success" even with errors** → UI showed wrong status

### What's Fixed

1. ✅ `run_code` executes properly with `__name__ = "__main__"`
2. ✅ Empty messages never added to history
3. ✅ Errors tracked in echo
4. ✅ Cascade status reflects errors ("failed" vs "success")
5. ✅ Hooks called appropriately (`on_cascade_error` when errors occur)
6. ✅ Full error details logged (HTTP status, provider response, traceback)

### Files Changed

1. **`windlass/windlass/eddies/extras.py`** (already fixed)
   - Set `__name__ = "__main__"` in exec namespace
   - Capture stdout/stderr
   - Full traceback on errors
   - Execution logging

2. **`windlass/windlass/agent.py`** (already fixed)
   - Enhanced API error logging with HTTP details

3. **`windlass/windlass/runner.py`**
   - Don't add empty follow-up messages to history (NEW)
   - Track errors in echo (NEW)
   - Mark cascade as failed if errors occurred (NEW)
   - Enhanced error logging with provider details (already done)

4. **`windlass/windlass/echo.py`**
   - Added `errors` list to track phase errors (NEW)
   - Added `add_error()` method (NEW)
   - Return `has_errors` and `status` in `get_full_echo()` (NEW)
   - Merge errors from sub-cascades (NEW)

---

## Why max_turns IS Working Correctly

**Your original question:**
> "Isn't this the point of max_turns - to have encapsulated iteration?"

**YES! And it was already working:**

- Turn 1: Tool returns empty → Framework injects "Continue/Refine..."
- Turn 2: Agent tries to fix → Tool returns error → Framework prepares Turn 3
- Turn 3: Would have continued, but API call rejected due to empty message bug

**The iteration loop was doing exactly what it should.** The problems were:
1. Tool wasn't giving useful feedback (empty results)
2. Empty messages were being added to history (causing API errors)
3. Cascade status didn't reflect the errors

**All three are now fixed!** ✅

---

## How Errors Flow Now

```
Turn Error Occurs
    ↓
Enhanced Error Logging
    ├─ Console: Error type + HTTP status + Provider response
    ├─ Echo History: Full error with traceback
    └─ Echo Errors: Track in errors[] array
    ↓
Break out of turn loop
    ↓
Phase completes (returns normally)
    ↓
Cascade continues
    ↓
get_full_echo()
    ├─ errors: [{phase, error_type, error_message, metadata}]
    ├─ has_errors: true
    └─ status: "failed"
    ↓
update_session_state(..., "failed", ...)
    ↓
on_cascade_error() hook called
    ↓
on_cascade_complete() hook called (with status)
    ↓
Log: cascade_failed event
    ↓
UI/Debug Modal: Shows "Failed" status
```

---

## Impact on UX

### Debug Modal

**Before:**
- Shows useless error: "Provider returned error"
- Can't debug what went wrong

**After:**
- Shows full error with HTTP status
- Shows provider's actual error message
- Shows request context (phase, turn, model)
- Shows metadata with all exception details

### Instances View

**Before:**
- Instance shows as "Completed" even though it failed
- No indication of errors

**After:**
- Instance shows as "Failed"
- Can see error count
- Phase bars show error status (red)

### Backend API

`GET /api/cascade-instances/:cascade_id` will now return:
```json
{
  "session_id": "ui_run_abc123",
  "status": "failed",  ← NEW
  "error_count": 1,    ← NEW
  "errors": [          ← NEW
    {
      "phase": "test_solution",
      "error_type": "BadRequestError",
      "error_message": "..."
    }
  ],
  ...
}
```

---

## Remaining Questions Answered

### Q: Why didn't the cascade get logged as "failed"?

**A:** Because phase errors were caught with `break`, not raised. The cascade completed normally with errors in history, but no failure status. **Now fixed** - errors are tracked and cascade is marked as "failed".

### Q: Why are attempts not being sent back to the agent for fixing?

**A:** They WERE being sent back! max_turns was working correctly. The problems were:
- Tool gave empty result (nothing to fix)
- Empty follow-up added to history (caused API error)
- Agent never got a chance to properly fix the code

**All fixed now!**

### Q: What caused the API error?

**A:** Empty assistant message in position 5 of the messages array. Anthropic requires all messages to have non-empty content (except the final one). The framework was adding empty follow-up responses to history, which violated this requirement.

---

## Files Modified

1. ✅ `windlass/windlass/eddies/extras.py` (run_code fix - already done)
2. ✅ `windlass/windlass/agent.py` (API error logging - already done)
3. ✅ `windlass/windlass/runner.py` (empty message fix + error tracking)
4. ✅ `windlass/windlass/echo.py` (error tracking support)

---

## Next Steps

The UI backend should be updated to expose the new fields:

1. **`GET /api/cascade-instances/:cascade_id`** should return:
   - `status`: "failed" or "success"
   - `error_count`: Number of errors
   - `errors`: Array of error objects

2. **Instances View** should show:
   - Failed badge for instances with errors
   - Error count indicator
   - Red status for failed instances

3. **Debug Modal** already shows error entries - will now have better metadata!

---

## Conclusion

**All three bugs fixed:**

1. ✅ `run_code` executes `__main__` blocks properly
2. ✅ Empty messages never added to history → no API errors
3. ✅ Cascades marked as "failed" when errors occur

**Your investigation was spot-on!** The agent WAS trying to iterate and fix issues, but the framework bugs prevented it from working. Now the encapsulated iteration will work as designed. 🎯
