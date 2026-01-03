# Phase 3: What It Actually Does

**Great question!** Let me show you exactly what's happening now vs what Phase 3 will change.

---

## Current State: Two Different Execution Paths

### Path 1: AGGREGATE Functions (Already Using Cascades!) ✅

**Functions:** SUMMARIZE, THEMES, CLUSTER, DEDUPE, CONSENSUS, OUTLIERS, etc.

**Current execution:**
```
SQL: SELECT SUMMARIZE(reviews) FROM products
    ↓
llm_summarize_impl()
    ↓
_execute_cascade("semantic_summarize", {...})  ← Using cascades!
    ↓
execute_sql_function_sync()
    ↓
RVBBITRunner executes: cascades/semantic_sql/summarize.cascade.yaml
    ↓
✅ Full RVBBIT features: training, wards, logging, observability
```

**Evidence in code:**
```python
# llm_aggregates.py:271
def llm_summarize_impl(...):
    # Try cascade execution first
    try:
        result = _execute_cascade(
            "semantic_summarize",  ← Specific cascade!
            {"texts": values_json, "prompt": prompt},
            fallback=lambda **kw: _llm_summarize_fallback(...)
        )
```

### Path 2: SCALAR Functions (NOT Using Cascades!) ❌

**Functions:** MEANS, ABOUT, IMPLIES, CONTRADICTS, ASK, ALIGNS, EXTRACTS, etc.

**Current execution:**
```
SQL: WHERE description MEANS 'sustainable'
    ↓
llm_matches_impl()
    ↓
_call_llm_direct(prompt)  ← Direct LLM call!
    ↓
bodybuilder(cascade_id="sql_aggregate")  ← GENERIC cascade ID!
    ↓
❌ Does NOT execute cascades/semantic_sql/matches.cascade.yaml
❌ Misses: training, wards, specific cascade config
```

**Evidence in code:**
```python
# llm_aggregates.py:849
def llm_matches_impl(text: str, criteria: str, ...):
    # ... sanitization ...

    prompt = f"""Does the following text match this criteria: "{criteria}"?

    Text: {text[:2000]}

    Answer with ONLY "yes" or "no", nothing else."""

    result = _call_llm_direct(prompt, model=model, max_tokens=10)  ← Direct call!
```

**What _call_llm does:**
```python
# llm_aggregates.py:132-136
response = bodybuilder(
    request=request,
    _session_id=session_id,
    _cell_name=cell_name,
    _cascade_id="sql_aggregate",  ← GENERIC, not "semantic_matches"!
)
```

---

## The Problem

**SCALAR operators bypass their cascade YAMLs!**

This means:
- ❌ `use_training: true` in matches.cascade.yaml is IGNORED
- ❌ Wards/validation in cascades are IGNORED
- ❌ Logged to unified_logs with generic "sql_aggregate" instead of "semantic_matches"
- ❌ Can't customize behavior by editing the cascade YAML

**Example:**
```yaml
# cascades/semantic_sql/matches.cascade.yaml
cells:
  - name: evaluate
    use_training: true     # ← THIS IS IGNORED!
    training_limit: 5      # ← CURRENT CODE DOESN'T USE THIS
    model: google/gemini-2.5-flash-lite
```

The current code builds its own prompt and calls bodybuilder directly - it never executes this cascade!

---

## What Phase 3 Changes

### Update SCALAR functions to use cascades (like aggregates already do)

**Change:**
```python
# BEFORE (llm_aggregates.py:849):
def llm_matches_impl(text: str, criteria: str, ...) -> bool:
    # Build prompt manually
    prompt = f"""Does the following text match this criteria: "{criteria}"?
    Text: {text[:2000]}
    Answer with ONLY "yes" or "no", nothing else."""

    # Call LLM directly with generic cascade_id
    result = _call_llm_direct(prompt, model=model, max_tokens=10)
    # ❌ Bypasses matches.cascade.yaml!


# AFTER (Phase 3):
def llm_matches_impl(text: str, criteria: str, ...) -> bool:
    # Route through cascade YAML
    result = _execute_cascade(
        "semantic_matches",  # ← Use specific cascade!
        {"text": text, "criterion": criteria},
        fallback=lambda **kw: _llm_matches_fallback(...)
    )
    # ✅ Executes cascades/semantic_sql/matches.cascade.yaml!
    # ✅ Gets training examples!
    # ✅ Runs wards!
    # ✅ Proper logging!
```

---

## What Users Get From Phase 3

### 1. Training System Works ✅

**Before Phase 3:**
```yaml
# cascades/semantic_sql/matches.cascade.yaml
cells:
  - name: evaluate
    use_training: true  # ← IGNORED by current code
```

**After Phase 3:**
```yaml
# cascades/semantic_sql/matches.cascade.yaml
cells:
  - name: evaluate
    use_training: true  # ← ACTUALLY USED!
    training_limit: 5
```

**Result:** When you mark good results as trainable in Studio UI, future queries use them as few-shot examples!

### 2. Wards/Validation Works ✅

**Example:**
```yaml
# cascades/semantic_sql/matches.cascade.yaml
cells:
  - name: evaluate
    instructions: "..."
    wards:
      - mode: retry
        max_attempts: 3
        validator:
          python: |
            # Validate output is actually true/false
            return {"valid": output.lower() in ("true", "false"), "reason": "..."}
```

**Current code:** ❌ Wards ignored
**After Phase 3:** ✅ Wards execute!

### 3. Proper Observability ✅

**Before Phase 3:**
```sql
-- Query in unified_logs shows:
cascade_id: "sql_aggregate"  ← Generic!
```

**After Phase 3:**
```sql
-- Query shows specific cascade:
cascade_id: "semantic_matches"  ← Specific!
cascade_id: "semantic_score"
cascade_id: "semantic_aligns"
```

**Benefit:** Can filter logs by specific operator, track costs per operator, etc.

### 4. User Customization Works ✅

**Users can now customize operators by editing YAML:**

```yaml
# cascades/semantic_sql/matches.cascade.yaml
cells:
  - name: evaluate
    model: anthropic/claude-haiku  # ← Change model
    use_training: true             # ← Enable training
    training_verified_only: true   # ← Only use verified examples
    instructions: |
      # Custom prompt here!
```

**Current code:** ❌ Edits ignored (uses hardcoded prompt in llm_aggregates.py)
**After Phase 3:** ✅ Edits apply immediately!

---

## Summary

**What Phase 3 Does:**
Update SCALAR operators (MEANS, ABOUT, IMPLIES, ASK, ALIGNS, etc.) to route through their cascade YAMLs, just like AGGREGATE operators already do.

**Files to Change:**
- `rvbbit/rvbbit/sql_tools/llm_aggregates.py` - Update ~8 scalar functions

**Lines of Code:**
- ~50 lines (change direct `_call_llm()` to `_execute_cascade()`)

**Impact:**
- ✅ Training system works for ALL operators
- ✅ Wards/validation work
- ✅ Proper cascade observability
- ✅ User customization via YAML
- ✅ True "cascades all the way down"!

**Functions to Update:**
1. `llm_matches_impl()` → Use "semantic_matches" cascade
2. `llm_score_impl()` → Use "semantic_score" cascade
3. `llm_implies_impl()` → Use "semantic_implies" cascade
4. `llm_contradicts_impl()` → Use "semantic_contradicts" cascade
5. `llm_match_pair_impl()` → Need to create cascade YAML first
6. Plus any other scalar functions

---

## Why This Wasn't Done Before

**Good design!** The aggregate functions already show the pattern:
- They use `_execute_cascade()`
- They have fallback implementations
- They route through cascade YAMLs

**Phase 3 just applies the same pattern to scalar functions.**

The infrastructure is already there - we just need to use it!
