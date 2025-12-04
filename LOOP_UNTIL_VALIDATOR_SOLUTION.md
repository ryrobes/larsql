# loop_until Validator Solution

## Problem

> "Code runs fine and we keep sending refines until we run out of turns"

**Your instinct is correct!** Use `loop_until` with a validator to exit early when task is complete.

---

## The Issue

**Current behavior with just max_turns:**
```
Turn 1: Agent calls run_code → Success!
Turn 2: "Continue/Refine" → Agent explains result
Turn 3: "Continue/Refine" → Agent summarizes
Turn 4: "Continue/Refine" → Agent elaborates more
Turn 5: "Continue/Refine" → Agent concludes (max_turns exhausted)
```

**Wastes turns 2-5 on unnecessary elaboration!**

---

## The Solution: loop_until + Validator

### Created: code_execution_validator

**File:** `windlass/tackle/code_execution_validator.json`

**What it checks:**
1. ✅ Code was actually executed (has output)
2. ✅ No errors (no "Exit code", "Traceback", "Error:")
3. ✅ Results are present (numbers, data, etc.)

**Returns:**
- `{"valid": true, "reason": "Code executed successfully with output..."}` → Stop!
- `{"valid": false, "reason": "Errors present..."}` → Continue iterating

### Updated Cascade

**File:** `windlass/examples/soundings_code_flow.json`

**Added to test_solution phase:**
```json
{
  "name": "test_solution",
  "instructions": "...Once code executes successfully, you're done.",
  "tackle": ["run_code"],
  "rules": {
    "max_turns": 5,
    "loop_until": "code_execution_validator"  // ← NEW!
  }
}
```

---

## How It Works

### Turn 1: Execute Code

**Agent:**
```json
{"tool": "run_code", "arguments": {"code": "..."}}
```

**Result:**
```
Sum: 1346268
Divided by Pi: 428573.425757
Golden Ratio: 1.6180339887
```

**Validator runs:**
- Checks output
- No errors found ✅
- Has actual results ✅
- Returns: `{"valid": true, "reason": "Code executed successfully"}`

**Phase EXITS immediately!** ✅

**Turns 2-5:** Never happen! (saved)

### Turn 1: Execute Code (With Error)

**Agent:**
```json
{"tool": "run_code", "arguments": {"code": "..."}}
```

**Result:**
```
Exit code: 1
SyntaxError: unterminated f-string
```

**Validator runs:**
- Checks output
- Sees "Exit code: 1" ❌
- Sees "SyntaxError" ❌
- Returns: `{"valid": false, "reason": "Execution failed with errors"}`

**Continue to Turn 2** → Agent fixes code

---

## Validator Implementation

**code_execution_validator.json:**

```json
{
  "cascade_id": "code_execution_validator",
  "inputs_schema": {
    "content": "The phase output to validate"
  },
  "phases": [{
    "name": "validate",
    "instructions": "Check if code executed successfully...",
    "output_schema": {
      "type": "object",
      "properties": {
        "valid": {"type": "boolean"},
        "reason": {"type": "string"}
      },
      "required": ["valid", "reason"]
    }
  }]
}
```

**The validator:**
- Takes phase output as input
- Uses LLM to check for success indicators
- Returns structured JSON (enforced by output_schema)
- Must have `valid` and `reason` fields

---

## Benefits

### 1. Early Exit

**Before:**
- Uses all 5 turns even if Turn 1 succeeds
- Wastes 4 turns on elaboration
- More tokens = more cost

**After:**
- Turn 1 succeeds → Validator passes → Exit!
- Turns 2-5 never happen
- Saves tokens and time ✅

### 2. Error-Driven Iteration

**If code fails:**
- Turn 1: Error → Validator fails → Continue
- Turn 2: Agent fixes → Success → Validator passes → Exit!

**Uses turns only when needed!**

### 3. Clear Termination

**Agent knows:**
- "Once code runs successfully, I'm done"
- No need to elaborate
- Validator decides, not turn count

---

## Comparison

| Scenario | max_turns Only | max_turns + loop_until |
|----------|---------------|----------------------|
| **Success on Turn 1** | Uses all 5 turns talking | Exits after Turn 1 ✅ |
| **Error on Turn 1** | Uses all 5 turns | Exits when fixed ✅ |
| **Success on Turn 3** | Uses Turn 4-5 talking | Exits after Turn 3 ✅ |
| **Never succeeds** | Uses all 5 turns | Uses all 5 turns (same) |

---

## Testing

```bash
windlass windlass/examples/soundings_code_flow.json \
  --input '{"problem": "Print hello world"}' \
  --session test_loop_until
```

**Expected:**

**Turn 1:**
```
Agent: {"tool": "run_code", "arguments": {"code": "print('hello world')"}}
Tool result: hello world

🛡️  Running Validator: code_execution_validator
  ✓ Validation Passed: Code executed successfully with output
```

**Phase exits!** Turns 2-5 never happen. ✅

**If error on Turn 1:**
```
Tool result: Error: SyntaxError...

🛡️  Running Validator: code_execution_validator
  ✗ Validation Failed: Execution failed with errors

Turn 2...
```

Agent gets another chance to fix!

---

## Files Created/Modified

1. **`windlass/tackle/code_execution_validator.json`** (NEW)
   - Validator cascade
   - Checks for successful execution
   - Returns valid/reason

2. **`windlass/examples/soundings_code_flow.json`** (UPDATED)
   - Added `loop_until: "code_execution_validator"`
   - Updated instructions (tell agent to stop when done)

---

## Summary

**Your idea:**
> "Maybe in test_solution I should be using loop_until and a validator?"

**Exactly right!** This is the perfect use case for `loop_until`:
- ✅ Exit early when code works
- ✅ Continue iterating on errors
- ✅ Save turns/tokens
- ✅ Clear termination condition

**Plus fixed:**
- ✅ Shell escaping (array form)
- ✅ Smart JSON validation (only tool calls)

Test it now - should exit after first successful execution! 🎯