# Final Fix: max_args Override for Backwards Compatibility

## Problem

After server restart, aggregate functions were rejecting args they used to accept:

```
Error: LLM_SUMMARIZE accepts at most 1 argument(s), got 2
Error: consensus(VARCHAR, STRING_LITERAL) - No function matches
```

## Root Cause

The cascade declarations only define **required** args, not the full impl function signature:

```yaml
# semantic_summarize.cascade.yaml
args:
  - name: texts      # Only 1 arg declared
    type: JSON

# But Python impl accepts:
def llm_summarize_impl(values_json, prompt=None, max_items=200, ...):
    # 3 args total!
```

Old hardcoded system had:
```python
LLM_SUMMARIZE: max_args=3  # Accepted 3 args
```

New cascade-driven system was using:
```python
max_args=1  # Only what cascade declared
```

## Solution

Override `max_args` in the compatibility layer to match **impl function signatures**:

```python
cascade_to_legacy = {
    'semantic_summarize': ('LLM_SUMMARIZE', 'llm_summarize_impl', 3),  # ← max_args=3
    'semantic_consensus': ('LLM_CONSENSUS', 'llm_consensus_impl', 2),  # ← max_args=2
    # ...
}
```

This preserves backwards compatibility with old SQL that passed extra args:
```sql
-- These now all work:
SUMMARIZE(col)                      -- 1 arg
SUMMARIZE(col, 'custom prompt')     -- 2 args (prompt used by impl, not cascade)
SUMMARIZE(col, 'prompt', 50)        -- 3 args (max_items used by impl)

CONSENSUS(col)                      -- 1 arg
CONSENSUS(col, 'find common themes') -- 2 args (prompt passed to cascade!)
```

## The Philosophical Issue

You asked: **"If we're cascade-based, why accept args the cascade doesn't use?"**

**You're absolutely right!** The pure cascade approach would be:

```yaml
# Cascade declares what it accepts:
args:
  - name: texts
    type: JSON
  # No prompt arg!

# SQL should only allow what cascade accepts:
SUMMARIZE(col)           ← Valid
SUMMARIZE(col, 'prompt') ← Should ERROR (cascade doesn't accept prompt)
```

**Current hybrid approach:**
- Pattern matching: Cascade-driven ✅
- Arg validation: Impl function signatures (backwards compat)
- Execution: Extra args go to impl, which ignores them or uses fallback

## The Truth About Extra Args

| Function | Extra Args Used? | How? |
|----------|------------------|------|
| **SUMMARIZE** | ❌ **IGNORED** | Cascade doesn't use prompt arg! |
| **CONSENSUS** | ✅ **USED** | Cascade checks `{% if input.prompt %}` |
| **CLASSIFY** | ✅ **USED** | Cascade uses prompt for classification |

So old queries like `SUMMARIZE(col, 'custom prompt')` were **silently ignoring** the prompt!

## Future Pure Approach

To make this fully cascade-driven:

1. **Update cascades** to declare all args they accept:
   ```yaml
   args:
     - name: texts
     - name: prompt
       optional: true
   ```

2. **Reject invalid args** in rewriter:
   ```python
   if len(args) > max_args_from_cascade:
       raise ValueError(f"Too many args")
   ```

3. **Remove numbered UDFs**, use single generic:
   ```python
   SUMMARIZE(...) → rvbbit_cascade_udf('semantic_summarize', json_obj)
   ```

But for now, we preserve backwards compatibility with old SQL.

## Test Status After Fix

```
✅ 90/99 SQL tests pass (91%)
✅ SUMMARIZE with 1-3 args works
✅ CONSENSUS with 1-2 args works
✅ BACKGROUND + newlines works
```

**Your query should work now after restart!** 🚀
