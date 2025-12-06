# Follow-Up Cost Analysis: The Real Issue

**Date:** 2025-12-06
**Session:** `ui_run_bad682b0f785`
**Most Expensive Follow-Up:** 93,301 input tokens ($0.28)

## Executive Summary

**The problem is NOT that follow_up is broken - it's that message-count-based culling doesn't help when individual messages are MASSIVE (400k+ char base64 images). Even with `keep_recent_turns=10` and `keep_recent_images=2`, the recent messages contain enough images to balloon token counts.**

**Key Finding:** Follow_up calls don't need full visual context - images are already saved to disk. Dropping images from follow_up context would reduce costs by ~85%.

## The User's Question

> "I was already using 10 turns limit and the token count didn't change. Is it because follow_up isn't using history and is putting everything in one massive message? I also limited images to 2, same result."

**Answer:** Culling by message count doesn't help when the RECENT messages (within the 30-message window) contain 5 massive base64 images!

## The Data: What Culling Actually Did

**Session had 48 total messages before the expensive follow_up:**

### Messages 1-18: ❌ CULLED (dropped)
```
Message  4: 41,814 chars - Text tool result ✅ Successfully culled
Message  5: 238,477 chars - MASSIVE text tool result ✅ Successfully culled
```

### Messages 19-48: ✅ KEPT (last 30 messages)
```
Message 21: 426,665 chars - Base64 image ❌ KEPT (too recent!)
Message 23: 371,409 chars - Base64 image ❌ KEPT
Message 28: 283,057 chars - Base64 image ❌ KEPT
Message 39: 462,853 chars - Base64 image ❌ KEPT
Message 44: 452,629 chars - Base64 image ❌ KEPT

Total in kept messages: 5 images, ~2 MB of base64 data
```

**With `keep_recent_images=2`, should have removed 3 images:**
- 2 kept images × ~450k chars = ~900k chars
- Still massive!

**Summary of kept messages:**
- 30 messages kept
- 2,045,052 total characters (~2 MB)
- 5 base64 images (or 2 with image culling)
- ~511k estimated raw tokens (before compression)
- **Actual tokens_in reported by LLM: 93,301** (images compress well)

## Token Directionality Explained

### `tokens_in` = INPUT TO the LLM (what we SEND)
This is the context we send to the LLM API. We pay for this!

```
Agent call: 93,029 tokens_in (our request) → 197 tokens_out (LLM response)
Follow-up:  93,301 tokens_in (our request) → 310 tokens_out (LLM response)
```

**The 93k tokens is what we're SENDING to the API, not what comes back!**

### Cost Breakdown
```
tokens_in × input_price + tokens_out × output_price = total_cost
93,301 × $3/1M + 310 × $15/1M = $0.2799 + $0.0047 = $0.28
```

**95% of the cost is the INPUT context (images + history)!**

## Why These Are Outliers

### Progression Across Phases:

```
Phase 1: discover_schema
  follow_up: 71,545 tokens
  → Got massive 238k text tool result (later culled)

Phase 2: write_query
  agent:     72,452 tokens
  follow_up: 74,266 tokens
  → Still has some context accumulation

Phase 4: create_initial_chart (soundings + reforge)
  agent:     75,739 → 80,371 → 84,385 → 89,945 tokens (growing!)
  follow_up: 78,796 → 89,329 → 89,945 tokens
  → Each iteration adds more images to context

Phase 5: say_summary_summarize
  agent:     93,029 tokens
  follow_up: 93,301 tokens
  → Final phase has accumulated ALL images from Phase 4
```

**Pattern:** Token count grows as images accumulate in recent context!

### Why NOT Outliers Compared to Agent Calls

**Agent vs Follow-Up in same phase:**
- Agent call: 93,029 tokens
- Follow-up: 93,301 tokens
- **Difference: only 272 tokens** (one tool result)

**Both use the same context!** Follow_up isn't uniquely expensive - ALL calls in later phases are expensive when images are in recent context.

### Why Worse Than 15 Images in Other Cascades

Possible reasons:
1. **These images are HUGE** (450k chars each vs maybe 100k for smaller images)
2. **All 5 images are in the LAST 30 messages** (concentrated in recent context)
3. **Previous 15-image cascades** might have had images spread across more messages (older ones culled)
4. **Soundings/reforge multiplies images** - each iteration saves a new chart

## The Core Design Question

**Does follow_up actually NEED all that visual context?**

### What Follow-Up Does:
```python
# After tool execution, follow_up processes the tool result
agent.run(None, context_messages=culled_context)
```

The follow_up sees:
- ✅ Tool result (necessary)
- ✅ Previous conversation (useful for coherence)
- ❌ Base64 images from 3 phases ago? (unnecessary - already saved to disk!)
- ❌ Chart images from previous soundings? (unnecessary - only winner matters!)

### Follow-Up Response Sizes:
Looking at the actual follow_up outputs:
- 197-310 tokens (tiny responses!)
- Just acknowledging tool results
- Not doing deep visual analysis

**Conclusion: Follow_up doesn't need images!**

## Solutions

### Option 1: Zero-Image Follow-Up (Immediate Fix)

**Change in `runner.py` around line 2976:**

```python
# BEFORE:
keep_images = int(os.getenv('WINDLASS_KEEP_RECENT_IMAGES', '0'))
culled_context = cull_old_base64_images(culled_context, keep_recent=keep_images)

# AFTER:
# Follow-up doesn't need images (already saved to disk)
culled_context = cull_old_base64_images(culled_context, keep_recent=0)
```

**Expected impact:**
- Current: 93,301 tokens → $0.28
- With fix: ~15-20k tokens → $0.05
- **Savings: 85% cost reduction on follow-up calls!**

### Option 2: Phase-Scoped Follow-Up Context

**Only include messages from the current phase:**

```python
# Build minimal context for follow_up
follow_up_context = []

# 1. Keep system message (tool definitions)
for msg in culled_context:
    if msg.get('role') == 'system':
        follow_up_context.append(msg)
        break

# 2. Keep only current phase messages
current_phase_messages = [
    msg for msg in culled_context
    if msg.get('metadata', {}).get('phase_name') == phase.name
]
follow_up_context.extend(current_phase_messages)

# 3. Always drop images (saved to disk)
follow_up_context = cull_old_base64_images(follow_up_context, keep_recent=0)

follow_up = agent.run(None, context_messages=follow_up_context)
```

**Expected impact:**
- Even more aggressive - only ~5-10 messages
- ~5-10k tokens
- **Savings: 90%+ cost reduction!**

### Option 3: Content-Size-Aware Culling

**Cull based on total size, not message count:**

```python
def cull_to_token_budget(messages, max_tokens=50000):
    """Keep most recent messages within token budget."""
    total_tokens = 0
    culled = []

    for msg in reversed(messages):
        msg_tokens = estimate_tokens(msg)

        if total_tokens + msg_tokens > max_tokens:
            # Budget exceeded - stop here
            break

        culled.insert(0, msg)
        total_tokens += msg_tokens

    return culled
```

This would automatically drop expensive messages (images, large tool results) when they exceed budget.

### Option 4: Smarter Image Injection

**Don't inject images into context_messages at all:**

```python
# CURRENT: Injects base64 into conversation
self.context_messages.append({
    "role": "user",
    "content": [
        {"type": "text", "text": "Tool generated an image:"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_data}"}}
    ]
})

# BETTER: Just reference the saved file
self.context_messages.append({
    "role": "user",
    "content": f"Tool generated an image (saved to {image_path})"
})

# Then inject base64 ONLY when explicitly needed (e.g., reforge refinement)
```

## Recommended Immediate Action

**Implement Option 1 (zero-image follow-up):**

1. In `windlass/runner.py` line ~2976
2. Change: `culled_context = cull_old_base64_images(culled_context, keep_recent=0)`
3. Add comment: `# Follow-up doesn't need images - already saved to disk`

**Why this fix:**
- ✅ Zero code complexity - one line change
- ✅ No breaking changes
- ✅ Massive cost reduction (85%)
- ✅ Follow-up responses are tiny anyway - they don't analyze images
- ✅ Images are already saved and accessible if needed

## Testing the Fix

```bash
# Before fix: Run expensive cascade
windlass examples/your_cascade.json --input '{"question": "..."}' --session test_before

# Apply fix (zero-image follow-up)

# After fix: Run same cascade
windlass examples/your_cascade.json --input '{"question": "..."}' --session test_after

# Compare costs
python3 -c "
from windlass.unified_logs import query_unified
before = query_unified(\"session_id = 'test_before' AND node_type = 'follow_up'\")
after = query_unified(\"session_id = 'test_after' AND node_type = 'follow_up'\")
print(f'Before: {before[\"tokens_in\"].sum():.0f} tokens, ${before[\"cost\"].sum():.2f}')
print(f'After: {after[\"tokens_in\"].sum():.0f} tokens, ${after[\"cost\"].sum():.2f}')
print(f'Savings: {(1 - after[\"cost\"].sum()/before[\"cost\"].sum())*100:.0f}%')
"
```

## Files to Modify

1. **`windlass/runner.py`**
   - Line ~2976: Follow-up culling logic
   - Line ~2567: Agent call culling logic (consider same fix)

2. **`windlass/utils.py`**
   - Potentially add `cull_to_token_budget()` helper (Option 3)

3. **Environment Defaults**
   - Consider changing `WINDLASS_KEEP_RECENT_IMAGES` default from 0 to 2
   - Document that 0 = no culling, not zero images!

## Conclusion

**The problem:** Message-count-based culling keeps recent messages even when they're massive. With soundings/reforge creating multiple chart iterations, 5 huge images end up in the last 30 messages.

**The solution:** Follow-up doesn't need images (they're saved to disk). Drop them from follow-up context.

**The impact:** 85-90% cost reduction on follow-up calls, turning $0.28 calls into $0.05 calls.

**Why this matters:** In multi-phase cascades with visual outputs, follow-up costs can dominate total spend. This fix makes visual-heavy cascades economically viable.
