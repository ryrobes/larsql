# Culling Fix Applied - 2025-12-06

## The Bug

**Session `ui_run_c84b1c4d57bc` revealed the culling wasn't working at all:**

- 22 images accumulated (should be 1!)
- 7 system messages mid-conversation
- Follow-up tokens: 1,527 → 38,824 (2443% growth!)
- Total cost: $2.34 (barely better than no culling)

**Root Cause:**

```python
# BEFORE (BROKEN):
culled_context = cull_old_conversation_history(self.context_messages, keep_recent_turns=10)
culled_context = cull_old_base64_images(culled_context, keep_recent=1)
follow_up = agent.run(None, context_messages=culled_context)  # ✅ Uses culled version

# But then...
self.context_messages.append(assistant_msg)  # ❌ Appends to ORIGINAL (unculled) context!
```

**The culling was TEMPORARY!** It only affected one API call, then we kept appending to the bloated original context. Next call saw ALL accumulated images again.

## The Fixes

### Fix #1: Make Culling Persistent (Agent Calls)

**File:** `windlass/runner.py` line 2564-2567

**Before:**
```python
culled_context = cull_old_conversation_history(self.context_messages, keep_recent_turns=keep_turns)
culled_context = cull_old_base64_images(culled_context, keep_recent=keep_images)
response_dict = agent.run(current_input, context_messages=culled_context)
```

**After:**
```python
# FIX: Actually update self.context_messages to make culling persistent
# This also handles system prompt positioning (moves to front, keeps only most recent)
self.context_messages = cull_old_conversation_history(self.context_messages, keep_recent_turns=keep_turns)
self.context_messages = cull_old_base64_images(self.context_messages, keep_recent=keep_images)
response_dict = agent.run(current_input, context_messages=self.context_messages)
```

### Fix #2: Make Culling Persistent (Follow-Up Calls)

**File:** `windlass/runner.py` line 2976-2983

**Before:**
```python
culled_context = cull_old_conversation_history(self.context_messages, keep_recent_turns=keep_turns)
culled_context = cull_old_base64_images(culled_context, keep_recent=1)
follow_up = agent.run(None, context_messages=culled_context)
```

**After:**
```python
# FIX: Actually update self.context_messages (not just temporary variable!)
# Previous bug: culling was temporary, never persisted, all images accumulated
self.context_messages = cull_old_conversation_history(self.context_messages, keep_recent_turns=keep_turns)
self.context_messages = cull_old_base64_images(self.context_messages, keep_recent=1)
follow_up = agent.run(None, context_messages=self.context_messages)
```

### Bonus Fix: System Prompt Positioning

The `cull_old_conversation_history()` function (utils.py:195-248) already handles system prompts correctly:

1. Keeps last N messages
2. Finds most recent tool definition system message
3. Moves it to the FRONT (line 246: `culled_messages.insert(0, all_tool_systems[-1])`)

**Result:**
- ✅ Only ONE system message (most recent tool defs)
- ✅ At the BEGINNING of message array (oldest position)
- ✅ Recent conversation takes priority
- ✅ No mid-conversation system message confusion

## Expected Impact

### Before Fix:
```
Iteration 1: Agent sees [Image A]
            Follow-up sees [Image A]

Iteration 2: Agent sees [Image A, Image B]  ← Both!
            Follow-up sees [Image A, Image B]  ← Both!

Iteration 3: Agent sees [Image A, Image B, Image C]  ← All 3!
            Follow-up sees [Image A, Image B, Image C]  ← All 3!

Result: Exponential growth, 22 images in final follow-up, 38k tokens
```

### After Fix:
```
Iteration 1: Agent sees [Image A]
            Follow-up sees [Image A]
            Context culled → [Image A] ✅

Iteration 2: Agent sees [Image A, Image B]  ← Before culling
            Culled to [Image B]  ← After culling ✅
            Follow-up sees [Image B]
            Context culled → [Image B] ✅

Iteration 3: Agent sees [Image B, Image C]  ← Before culling
            Culled to [Image C]  ← After culling ✅
            Follow-up sees [Image C]
            Context culled → [Image C] ✅

Result: Linear growth (constant 1 image), ~5-10k tokens per follow-up
```

### Cost Projection:
```
Before: 38,824 tokens × $3/1M = $0.12 per follow-up
After:  ~5,000 tokens × $3/1M = $0.015 per follow-up

Savings: 87% cost reduction! 🎉
```

## What Changed in Behavior

### Agent Calls:
- **Before:** Saw ALL accumulated context (all images, all history)
- **After:** Sees culled context (respects `WINDLASS_KEEP_RECENT_TURNS` and `WINDLASS_KEEP_RECENT_IMAGES`)

### Follow-Up Calls:
- **Before:** Saw ALL accumulated context (22 images!)
- **After:** Sees only 1 most recent image (perfect for iterative feedback)

### System Prompts:
- **Before:** Multiple system messages mid-conversation (confusing)
- **After:** One system message at the BEGINNING (clean, clear)

### Context Accumulation:
- **Before:** Unbounded growth, nothing ever removed
- **After:** Bounded by culling limits, old content removed

## Testing

```bash
# Set culling limits
export WINDLASS_KEEP_RECENT_TURNS=10
export WINDLASS_KEEP_RECENT_IMAGES=2  # For agent calls
# (Follow-up hardcoded to 1)

# Run your cascade
windlass examples/chart_refinement.json --input '{"data": "..."}' --session test_fix

# Check results
python3 -c "
from windlass.unified_logs import query_unified
df = query_unified(\"session_id = 'test_fix' AND node_type IN ('agent', 'follow_up')\")
print('Token progression:')
print(df[['node_type', 'turn_number', 'tokens_in', 'tokens_out', 'cost']].to_string(index=False))
print()
print(f'Average follow-up tokens: {df[df[\"node_type\"] == \"follow_up\"][\"tokens_in\"].mean():.0f}')
print(f'Total cost: ${df[\"cost\"].sum():.2f}')
"
```

## What to Watch For

### Good Signs:
- ✅ Follow-up tokens stay relatively constant (~5-10k)
- ✅ Total cost much lower
- ✅ Agent still sees latest image for feedback
- ✅ No strange behavior or confusion

### Potential Issues:
- ⚠️ If culling is TOO aggressive, agent might lose important context
- ⚠️ If soundings need to compare multiple images, they won't see old ones
- ⚠️ System prompt might be outdated if tools change mid-cascade

### Adjustments:
```bash
# If agent needs more context:
export WINDLASS_KEEP_RECENT_TURNS=15  # Keep more turns

# If agent needs more images:
export WINDLASS_KEEP_RECENT_IMAGES=3  # Keep 3 images for agent (follow-up still gets 1)

# If you need to see ALL context (debugging):
export WINDLASS_KEEP_RECENT_TURNS=0  # Disables culling entirely
```

## Special Case: Soundings Evaluation

**Important:** When evaluating multiple sounding attempts, the evaluator needs to see ALL candidates to make a comparison.

**Current Behavior:** Each sounding uses a separate session ID (e.g., `session_123_sounding_0`, `session_123_sounding_1`), so they have independent contexts.

**Evaluator Context:** The evaluator runs AFTER soundings complete and sees the collected outputs, not the full image history.

**If you need visual comparison:**
- Soundings are evaluated on their TEXT outputs
- Images are saved to disk for each sounding
- Evaluator can reference saved images if needed
- But doesn't need base64 in context (would be massive!)

## Files Modified

1. **windlass/runner.py** (2 locations)
   - Line 2564-2567: Agent call culling (made persistent)
   - Line 2976-2983: Follow-up culling (made persistent)

No changes needed to:
- **windlass/utils.py** - Culling functions already correct
- **windlass/agent.py** - Just passes messages through
- **windlass/echo.py** - Just tracks history

## Rollback Instructions

If something goes wrong, revert the changes:

```bash
cd /home/ryanr/repos/windlass
git diff windlass/windlass/runner.py  # Review changes
git checkout windlass/windlass/runner.py  # Revert
```

Or manually change:
```python
# Change back to temporary culling:
culled_context = cull_old_conversation_history(self.context_messages, ...)
culled_context = cull_old_base64_images(culled_context, ...)
# Use culled_context instead of self.context_messages in agent.run()
```

## Next Steps

1. ✅ Test with your actual workload
2. ✅ Monitor token counts and costs
3. ✅ Adjust culling parameters if needed
4. ✅ Report results!

The fix is ready - give it a try! 🚀
