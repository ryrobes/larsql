# Semantic SQL Cascade Routing Plan

**Date:** 2026-01-02
**Status:** Analysis Complete - Ready for Implementation

---

## Executive Summary

The semantic SQL system claims "cascades all the way down," but core infix operators currently bypass cascade YAMLs and route directly to Python UDF implementations. Additionally, the dynamic operator system is only halfway wired—new YAML-defined operators (ASK, EXTRACTS, ALIGNS, SOUNDS_LIKE) are detected but don't have generic infix rewriting.

**Core Issues:**
1. **MEANS doesn't route to cascade** - Goes directly to `llm_matches_impl()` instead of `semantic_matches` cascade
2. **Argument order mismatch** - Cascades expect `(text, criterion)` but rewriter generates `(criterion, text)`
3. **No generic infix rewriting** - New operators require hardcoded rewrite rules

**Solution:**
- Implement generic infix operator rewriting using the cascade registry
- Route all operators through cascades (not direct UDFs)
- Standardize argument order across the entire system

---

## Current Architecture

### How It Works Today

```
SQL Query: "SELECT * FROM products WHERE description MEANS 'sustainable'"
    ↓
semantic_operators.py (rewriter)
    ↓ _rewrite_means() [HARDCODED]
    ↓
Rewritten: "SELECT * FROM products WHERE matches('sustainable', description)"
    ↓
UDF Registration (llm_aggregates.py:1989-1994)
    ↓
Direct function call: llm_matches_impl(criteria='sustainable', text=description)
    ↓
_call_llm() - Direct LLM call (bypasses cascade YAML!)
```

**Problem:** The cascade YAML at `cascades/semantic_sql/matches.cascade.yaml` is never executed!

### File Structure

```
rvbbit/
├── rvbbit/sql_tools/
│   ├── semantic_operators.py      # Query rewriter (hardcoded rewrites)
│   ├── llm_aggregates.py          # Direct UDF implementations (bypasses cascades)
│   └── dynamic_operators.py       # Dynamic operator detection (detects but doesn't rewrite)
│
├── rvbbit/semantic_sql/
│   └── registry.py                # Cascade registry
│
└── cascades/semantic_sql/         # Cascade YAML definitions
    ├── matches.cascade.yaml       # cascade_id: semantic_matches
    ├── ask.cascade.yaml           # cascade_id: semantic_ask
    ├── aligns.cascade.yaml        # cascade_id: semantic_aligns
    ├── extracts.cascade.yaml      # cascade_id: semantic_extracts
    ├── sounds_like.cascade.yaml   # cascade_id: semantic_sounds_like
    └── ... (19 total operators)
```

---

## Detailed Issue Analysis

### Issue 1: MEANS Doesn't Route to Cascade

**Current Behavior:**

```python
# semantic_operators.py:713-726
def _rewrite_means(line: str, annotation_prefix: str) -> str:
    fn_name = get_function_name("matches")  # Returns "matches" (not "semantic_matches")
    pattern = r'(\w+(?:\.\w+)?)\s+MEANS\s+\'([^\']+)\''

    def replacer(match):
        col = match.group(1)
        criteria = match.group(2)
        return f"{fn_name}('{criteria}', {col})"  # Generates: matches('criteria', col)
```

```python
# llm_aggregates.py:1989-1996
# UDF registration - routes directly to Python function
def matches_2(criteria: str, text: str) -> bool:
    return llm_matches_impl(criteria, text)

for name in ["llm_matches", "matches"]:
    connection.create_function(name, matches_2, return_type="BOOLEAN")
```

```python
# llm_aggregates.py:803-859
# Direct UDF implementation - calls LLM directly
def llm_matches_impl(criteria: str, text: str, ...) -> bool:
    # ... sanitization ...
    prompt = f"""Does the following text match this criteria: "{criteria}"?

    Text: {text[:2000]}

    Answer with ONLY "yes" or "no", nothing else."""

    result = _call_llm_direct(prompt, model=model, max_tokens=10)  # Bypasses cascade!
```

**Expected Behavior:**

```
SQL: WHERE description MEANS 'sustainable'
    ↓
Rewrite to: semantic_matches(description, 'sustainable')
    ↓
Execute cascade: cascades/semantic_sql/matches.cascade.yaml
    ↓
Full RVBBIT features: training, wards, observability, logging, cost tracking
```

**Root Causes:**

1. **Line 68 in semantic_operators.py:** `USE_CASCADE_FUNCTIONS = False`
   - When False: Uses direct UDF names like `matches`
   - When True: Uses cascade names like `cascade_matches` (but these aren't registered!)

2. **UDF registration in llm_aggregates.py:1886-2269:**
   - Registers direct Python functions (`matches_2()`) that call `llm_matches_impl()`
   - No cascade routing - just direct LLM calls via `_call_llm()`

3. **Hardcoded rewrite rules:**
   - `_rewrite_means()`, `_rewrite_about()`, `_rewrite_implies()` etc. are hardcoded
   - Don't use the dynamic operator registry
   - Can't discover new operators from YAML files

---

### Issue 2: Argument Order Mismatch

**The Conflict:**

```yaml
# cascades/semantic_sql/matches.cascade.yaml:17-19
inputs_schema:
  text: The text to evaluate          # FIRST parameter
  criterion: The semantic criterion   # SECOND parameter
```

```python
# semantic_operators.py:724
return f"{fn_name}('{criteria}', {col})"  # Generates: matches('criteria', text)
                                           # ORDER: (criterion, text) - REVERSED!
```

```python
# llm_aggregates.py:803
def llm_matches_impl(criteria: str, text: str, ...) -> bool:
    # Signature: (criteria, text) - matches rewriter but NOT cascade!
```

**Why This Matters:**

When we enable cascade routing, the rewriter output must match the cascade's `inputs_schema` order:
- Cascade expects: `text` (first), `criterion` (second)
- Rewriter generates: `criterion` (first), `text` (second)
- This will break when routing through cascades!

**Recommended Standard:**

Use the cascade order `(text, criterion)` because:
1. It's more semantic - "check if THIS TEXT matches THIS CRITERION"
2. Consistent with SQL convention: `column OPERATOR value`
3. Already defined in all cascade YAMLs

**Required Changes:**

1. Update all cascade YAMLs to use consistent order (most already do)
2. Update rewriter to generate cascade order
3. Update direct UDF implementations to match (for backwards compat)

---

### Issue 3: No Generic Infix Rewriting

**What Works:**

```python
# dynamic_operators.py:40-139
def initialize_dynamic_patterns(force: bool = False) -> Dict[str, Set[str]]:
    """
    Initialize dynamic operator patterns from cascade registry.

    Extracts all operator keywords from cascades and caches them.
    """
    # Scans cascades/semantic_sql/*.cascade.yaml
    # Extracts operators from sql_function.operators:
    #   - "{{ text }} MEANS {{ criterion }}"  → Detects "MEANS"
    #   - "{{ text }} ASK '{{ prompt }}'"     → Detects "ASK"
    #   - "{{ text }} ALIGNS {{ narrative }}" → Detects "ALIGNS"

    return {
        "infix": {"MEANS", "ABOUT", "ASK", "ALIGNS", "EXTRACTS", ...},
        "function": {"EMBED", "VECTOR_SEARCH", "SIMILAR_TO", ...},
        "all_keywords": {...}
    }
```

**What Doesn't Work:**

```python
# semantic_operators.py:289-339
def rewrite_infix_operators(line: str) -> str:
    """
    Generic rewriter for infix operators using cascade registry.

    ❌ THIS FUNCTION EXISTS BUT IS NEVER CALLED! ❌
    """
    # Perfect implementation - detects operators, looks up SQL function name
    # But semantic_operators.py still uses hardcoded _rewrite_means(), etc.
```

**The Problem:**

```python
# semantic_operators.py:639-700
def _rewrite_line(line: str, annotation: Optional[SemanticAnnotation]) -> str:
    """Rewrite semantic operators in a single line."""
    result = line

    # ORDER MATTERS: Process compound operators before simple ones
    result = _rewrite_semantic_join(result, annotation_prefix)     # Hardcoded
    result = _rewrite_not_relevance_to(result, annotation_prefix) # Hardcoded
    result = _rewrite_relevance_to(result, annotation_prefix)     # Hardcoded
    result = _rewrite_not_means(result, annotation_prefix)        # Hardcoded
    result = _rewrite_means(result, annotation_prefix)            # Hardcoded ← Issue here!
    result = _rewrite_not_about(result, annotation_prefix)        # Hardcoded
    result = _rewrite_about(result, annotation_prefix)            # Hardcoded
    # ... more hardcoded rewrites ...

    # ❌ MISSING: Generic rewrite using dynamic_operators.py
```

**Why New Operators Don't Work:**

1. **ASK operator:**
   ```sql
   SELECT text ASK 'translate to Spanish' FROM docs;
   ```
   - Cascade exists: `cascades/semantic_sql/ask.cascade.yaml`
   - Dynamic detector finds it: `initialize_dynamic_patterns()` returns `"ASK"` in infix set
   - But no rewrite rule in `_rewrite_line()` - syntax doesn't work!
   - Must call function directly: `SELECT semantic_ask(text, 'translate to Spanish')`

2. **ALIGNS operator:**
   ```sql
   SELECT * FROM policies WHERE description ALIGNS 'customer-first values';
   ```
   - Cascade exists: `cascades/semantic_sql/aligns.cascade.yaml`
   - Dynamic detector finds it
   - No rewrite rule - syntax doesn't work!

3. **EXTRACTS operator:**
   ```sql
   SELECT document EXTRACTS 'email addresses' as emails FROM contracts;
   ```
   - Cascade exists: `cascades/semantic_sql/extracts.cascade.yaml`
   - Dynamic detector finds it
   - No rewrite rule - syntax doesn't work!

**Root Cause:**

The dynamic operator system (`dynamic_operators.py`) detects operators but doesn't integrate with the rewriter (`semantic_operators.py`). The generic `rewrite_infix_operators()` function exists but is never called!

---

## Solution Architecture

### Goal: True "Cascades All the Way Down"

```
SQL Query: "SELECT * FROM products WHERE description MEANS 'sustainable'"
    ↓
semantic_operators.py (generic rewriter)
    ↓ _rewrite_dynamic_operators() [NEW]
    ↓ Looks up operator "MEANS" in registry
    ↓ Finds: function_name="semantic_matches", args=["text", "criterion"]
    ↓
Rewritten: "SELECT * FROM products WHERE semantic_matches(description, 'sustainable')"
    ↓
UDF Registration (NEW)
    ↓
Cascade executor: _execute_cascade("semantic_matches", {"text": description, "criterion": "sustainable"})
    ↓
RVBBITRunner executes: cascades/semantic_sql/matches.cascade.yaml
    ↓
Full features: training examples, wards, logging, cost tracking, observability
```

### Implementation Plan

#### Phase 1: Fix Argument Order (Foundation)

**Goal:** Standardize on `(text, criterion)` order everywhere

**Files to Change:**

1. **Update cascade YAMLs** (verify they all use `text` first):
   ```bash
   # Check current order in all cascades
   grep -A 3 "inputs_schema:" cascades/semantic_sql/*.cascade.yaml
   ```

2. **Update semantic_operators.py rewrite functions:**
   ```python
   # OLD (line 724):
   return f"{fn_name}('{criteria}', {col})"  # (criterion, text)

   # NEW:
   return f"{fn_name}({col}, '{criteria}')"  # (text, criterion)
   ```

3. **Update llm_aggregates.py UDF signatures:**
   ```python
   # OLD (line 803):
   def llm_matches_impl(criteria: str, text: str, ...) -> bool:

   # NEW:
   def llm_matches_impl(text: str, criteria: str, ...) -> bool:
   ```

4. **Update UDF registration:**
   ```python
   # llm_aggregates.py:1989
   # OLD:
   def matches_2(criteria: str, text: str) -> bool:
       return llm_matches_impl(criteria, text)

   # NEW:
   def matches_2(text: str, criteria: str) -> bool:
       return llm_matches_impl(text, criteria)
   ```

**Impact:**
- Backwards compatibility break for direct function calls
- SQL syntax unchanged (transparent to users)
- Foundation for cascade routing

---

#### Phase 2: Implement Generic Infix Rewriting

**Goal:** Use cascade registry to rewrite ALL infix operators dynamically

**New Function:**

```python
# semantic_operators.py (new function)
def _rewrite_dynamic_infix_operators(
    line: str,
    annotation_prefix: str,
    patterns_cache: Dict[str, Set[str]]
) -> str:
    """
    Generic rewriter for all infix operators using cascade registry.

    Handles operators like:
        col OPERATOR 'value' → sql_function_name(col, 'value')

    Automatically works with user-created cascades!
    """
    from rvbbit.semantic_sql.registry import get_sql_function_registry

    result = line
    registry = get_sql_function_registry()

    # Process each infix operator found by dynamic detection
    for operator_keyword in patterns_cache['infix']:
        # Find SQL function for this operator
        matching_funcs = [
            (name, entry) for name, entry in registry.items()
            if any(operator_keyword.upper() in op.upper() for op in entry.operators)
        ]

        if not matching_funcs:
            continue

        func_name, entry = matching_funcs[0]

        # Extract argument order from cascade
        arg_names = [arg['name'] for arg in entry.args]

        # Pattern: col OPERATOR 'value' or col OPERATOR other_col
        pattern = rf'(\w+(?:\.\w+)?)\s+{operator_keyword}\s+(\'[^\']*\'|"[^"]*"|\w+(?:\.\w+)?)'

        def replace_operator(match):
            col = match.group(1)
            value = match.group(2)

            # Inject annotation prefix if specified
            if annotation_prefix and value.startswith(("'", '"')):
                quote = value[0]
                inner = value[1:-1]
                value = f"{quote}{annotation_prefix}{inner}{quote}"

            # Generate function call with correct argument order
            # For MEANS: arg_names = ['text', 'criterion']
            # Pattern matched: description MEANS 'sustainable'
            # col = 'description', value = "'sustainable'"
            # Result: semantic_matches(description, 'sustainable')
            return f"{func_name}({col}, {value})"

        result = re.sub(pattern, replace_operator, result, flags=re.IGNORECASE)

    return result
```

**Update _rewrite_line():**

```python
# semantic_operators.py:639
def _rewrite_line(line: str, annotation: Optional[SemanticAnnotation]) -> str:
    """Rewrite semantic operators in a single line."""
    result = line

    # Get annotation prefix
    annotation_prefix = ""
    if annotation and annotation.prompt:
        annotation_prefix = annotation.prompt + " - "
    elif annotation and annotation.model:
        annotation_prefix = f"Use {annotation.model} - "

    # Get dynamic patterns
    from .dynamic_operators import get_operator_patterns_cached
    patterns_cache = get_operator_patterns_cached()

    # ===== NEW: Generic dynamic rewriting (replaces all hardcoded rewrites) =====
    result = _rewrite_dynamic_infix_operators(result, annotation_prefix, patterns_cache)

    # Keep embedding operators (EMBED, VECTOR_SEARCH, SIMILAR_TO)
    # These need special query-level rewriting
    from rvbbit.sql_tools.embedding_operator_rewrites import rewrite_embedding_operators
    result = rewrite_embedding_operators(result, annotation_prefix)

    return result
```

**Remove all hardcoded rewrites:**

```python
# DELETE these functions (no longer needed):
# - _rewrite_means()
# - _rewrite_not_means()
# - _rewrite_about()
# - _rewrite_not_about()
# - _rewrite_implies()
# - _rewrite_contradicts()
# - _rewrite_tilde()
# - _rewrite_not_tilde()
# - _rewrite_relevance_to()
# - _rewrite_not_relevance_to()
```

**Benefits:**

✅ ASK operator now works: `text ASK 'translate to Spanish'`
✅ ALIGNS operator now works: `description ALIGNS 'customer-first'`
✅ EXTRACTS operator now works: `document EXTRACTS 'email addresses'`
✅ SOUNDS_LIKE operator now works: `name SOUNDS_LIKE 'Smith'`
✅ User-created operators automatically work (true extensibility!)

---

#### Phase 3: Enable Cascade Routing

**Goal:** Route UDF calls through cascade execution instead of direct `_call_llm()`

**Update UDF Registration:**

```python
# llm_aggregates.py:1886-2269
def register_llm_aggregates(connection, config: Dict[str, Any] = None):
    """
    Register LLM aggregate helper functions as DuckDB UDFs.

    NEW: Routes through cascade execution instead of direct implementations.
    """
    from rvbbit.semantic_sql.registry import execute_sql_function_sync

    # ========== SCALAR LLM FUNCTIONS (CASCADE-BACKED) ==========

    # MATCHES (MEANS operator)
    def matches_2(text: str, criterion: str) -> bool:
        # NEW: Route through cascade
        result = execute_sql_function_sync(
            "semantic_matches",
            {"text": text, "criterion": criterion}
        )
        # Result is "true" or "false" string from cascade
        return result.lower() == "true" if isinstance(result, str) else bool(result)

    for name in ["llm_matches", "matches", "semantic_matches"]:
        connection.create_function(name, matches_2, return_type="BOOLEAN")

    # SCORE (ABOUT operator)
    def score_2(text: str, criterion: str) -> float:
        # NEW: Route through cascade
        result = execute_sql_function_sync(
            "semantic_score",
            {"text": text, "criterion": criterion}
        )
        return float(result) if result else 0.0

    for name in ["llm_score", "score", "semantic_score"]:
        connection.create_function(name, score_2, return_type="DOUBLE")

    # IMPLIES operator
    def implies_2(text: str, conclusion: str) -> bool:
        result = execute_sql_function_sync(
            "semantic_implies",
            {"text": text, "conclusion": conclusion}
        )
        return result.lower() == "true" if isinstance(result, str) else bool(result)

    for name in ["implies", "semantic_implies"]:
        connection.create_function(name, implies_2, return_type="BOOLEAN")

    # CONTRADICTS operator
    def contradicts_2(text1: str, text2: str) -> bool:
        result = execute_sql_function_sync(
            "semantic_contradicts",
            {"statement1": text1, "statement2": text2}
        )
        return result.lower() == "true" if isinstance(result, str) else bool(result)

    for name in ["contradicts", "semantic_contradicts"]:
        connection.create_function(name, contradicts_2, return_type="BOOLEAN")

    # ASK operator (NEW!)
    def ask_2(text: str, prompt: str) -> str:
        result = execute_sql_function_sync(
            "semantic_ask",
            {"text": text, "prompt": prompt}
        )
        return str(result) if result else ""

    for name in ["semantic_ask", "ask"]:
        connection.create_function(name, ask_2, return_type="VARCHAR")

    # ALIGNS operator (NEW!)
    def aligns_2(text: str, narrative: str) -> float:
        result = execute_sql_function_sync(
            "semantic_aligns",
            {"text": text, "narrative": narrative}
        )
        return float(result) if result else 0.0

    for name in ["semantic_aligns", "aligns"]:
        connection.create_function(name, aligns_2, return_type="DOUBLE")

    # EXTRACTS operator (NEW!)
    def extracts_2(text: str, target: str) -> str:
        result = execute_sql_function_sync(
            "semantic_extracts",
            {"text": text, "target": target}
        )
        return str(result) if result else ""

    for name in ["semantic_extracts", "extracts"]:
        connection.create_function(name, extracts_2, return_type="VARCHAR")

    # ... (continue for all operators)
```

**Keep Direct Implementations as Fallback:**

```python
# llm_aggregates.py:803-1129
# Keep llm_matches_impl(), llm_score_impl(), etc. as fallback
# They're used by _execute_cascade() if cascade fails
```

**Remove CASCADE_FUNCTIONS Flag:**

```python
# semantic_operators.py:68
# DELETE:
USE_CASCADE_FUNCTIONS = False

# DELETE:
OPERATOR_FUNCTIONS = {...}

# DELETE:
def get_function_name(operator: str) -> str:
def set_use_cascade_functions(enabled: bool) -> None:
```

**Benefits:**

✅ Full RVBBIT features for all operators (training, wards, logging)
✅ Cascade YAMLs are actually executed
✅ Users can override operators by creating custom cascades
✅ "Cascades all the way down" philosophy achieved

---

## Testing Strategy

### Unit Tests

1. **Argument order:**
   ```python
   # Test that rewriter generates correct order
   query = "SELECT * FROM t WHERE col MEANS 'test'"
   rewritten = rewrite_semantic_operators(query)
   assert "semantic_matches(col, 'test')" in rewritten
   ```

2. **Generic rewriting:**
   ```python
   # Test new operators work
   query = "SELECT text ASK 'translate to Spanish' FROM docs"
   rewritten = rewrite_semantic_operators(query)
   assert "semantic_ask(text, 'translate to Spanish')" in rewritten
   ```

3. **Cascade routing:**
   ```python
   # Test that cascade is executed
   from rvbbit.semantic_sql.registry import execute_sql_function_sync
   result = execute_sql_function_sync(
       "semantic_matches",
       {"text": "eco-friendly bamboo", "criterion": "sustainable"}
   )
   assert result in ["true", "false", True, False]
   ```

### Integration Tests

1. **End-to-end SQL query:**
   ```sql
   -- Test MEANS routes to cascade
   SELECT * FROM products WHERE description MEANS 'sustainable';

   -- Test ASK operator works
   SELECT text ASK 'translate to Spanish' FROM docs LIMIT 5;

   -- Test ALIGNS operator works
   SELECT * FROM policies WHERE description ALIGNS 'customer-first' > 0.7;
   ```

2. **Verify cascade execution:**
   ```python
   # Check unified_logs to see cascade_id = semantic_matches
   # Verify full RVBBIT context (session_id, trace_id, costs)
   ```

3. **Training system:**
   ```python
   # Verify that use_training: true in matches.cascade.yaml works
   # Run query, mark as trainable, verify next query uses examples
   ```

---

## Migration Strategy

### Phase 1: Non-Breaking Changes (Safe)

1. ✅ Fix argument order in new code only
2. ✅ Implement generic rewriting alongside existing hardcoded rules
3. ✅ Add cascade routing as opt-in feature
4. ✅ Test extensively with new operators (ASK, ALIGNS, EXTRACTS)

### Phase 2: Enable Cascade Routing (Default)

1. ✅ Set cascade routing as default
2. ✅ Keep direct implementations as fallback
3. ✅ Monitor logs for cascade execution
4. ✅ Verify training system works

### Phase 3: Remove Hardcoded Rewrites (Cleanup)

1. ✅ Switch to generic rewriting completely
2. ✅ Remove deprecated hardcoded functions
3. ✅ Update documentation

---

## Success Criteria

✅ **Issue 1 RESOLVED:** MEANS operator routes through `semantic_matches` cascade YAML
✅ **Issue 2 RESOLVED:** Argument order is consistent: `(text, criterion)` everywhere
✅ **Issue 3 RESOLVED:** New operators (ASK, ALIGNS, EXTRACTS, SOUNDS_LIKE) work with infix syntax
✅ **Extensibility:** Users can add custom operators by creating YAML files (no code changes)
✅ **Observability:** All semantic operators logged to `unified_logs` with full RVBBIT context
✅ **Training:** `use_training: true` works for all operators
✅ **Performance:** Cascade execution performance is acceptable (caching helps)

---

## Implementation Checklist

### Phase 1: Foundation (Argument Order)

- [ ] Audit all cascade YAMLs for `inputs_schema` order
- [ ] Update `semantic_operators.py` rewrite functions to generate `(text, criterion)` order
- [ ] Update `llm_aggregates.py` UDF signatures to match
- [ ] Update UDF registration to match
- [ ] Run unit tests to verify argument order consistency
- [ ] Test end-to-end with existing operators (MEANS, ABOUT, IMPLIES)

### Phase 2: Generic Rewriting

- [ ] Implement `_rewrite_dynamic_infix_operators()` in `semantic_operators.py`
- [ ] Update `_rewrite_line()` to call generic rewriter
- [ ] Test with new operators: ASK, ALIGNS, EXTRACTS, SOUNDS_LIKE
- [ ] Verify all 19 operators are detected and rewritten correctly
- [ ] Run integration tests with SQL queries
- [ ] Keep hardcoded rewrites as fallback (remove in Phase 3)

### Phase 3: Cascade Routing

- [ ] Update `register_llm_aggregates()` to route through `execute_sql_function_sync()`
- [ ] Register all operators with cascade routing
- [ ] Test cascade execution for all operators
- [ ] Verify `unified_logs` contains cascade execution records
- [ ] Test training system with `use_training: true`
- [ ] Monitor performance and add caching if needed

### Phase 4: Cleanup

- [ ] Remove hardcoded rewrite functions
- [ ] Remove `USE_CASCADE_FUNCTIONS` flag
- [ ] Remove direct UDF implementations (keep as private fallback)
- [ ] Update documentation
- [ ] Update examples

---

## Risk Assessment

### Low Risk

✅ Generic rewriting is additive (doesn't break existing code)
✅ Cascade routing can be tested incrementally (one operator at a time)
✅ Direct implementations remain as fallback

### Medium Risk

⚠️ **Argument order change:** May break users calling functions directly
   - Mitigation: Register both old and new signatures during migration
   - Deprecation warning for old order

⚠️ **Performance:** Cascade execution adds overhead
   - Mitigation: Cascade caching enabled by default
   - Profile and optimize if needed

### High Risk

❌ **None identified** - Changes are well-isolated and testable

---

## Next Steps

1. **Review this plan** with stakeholders
2. **Start with Phase 1** (argument order) - foundation for everything else
3. **Implement Phase 2** (generic rewriting) - enables new operators
4. **Test Phase 3** (cascade routing) - achieves "cascades all the way down"
5. **Document and ship** - update docs and examples

**Estimated Effort:**
- Phase 1: 2-3 hours
- Phase 2: 3-4 hours
- Phase 3: 4-5 hours
- Phase 4: 1-2 hours
**Total: ~10-14 hours**

---

## References

**Key Files:**
- `rvbbit/rvbbit/sql_tools/semantic_operators.py` - Query rewriter
- `rvbbit/rvbbit/sql_tools/llm_aggregates.py` - Direct UDF implementations
- `rvbbit/rvbbit/sql_tools/dynamic_operators.py` - Dynamic operator detection
- `rvbbit/rvbbit/semantic_sql/registry.py` - Cascade registry
- `cascades/semantic_sql/*.cascade.yaml` - Operator definitions

**Documentation:**
- `rvbbit/RVBBIT_SEMANTIC_SQL.md` - Main semantic SQL docs
- `rvbbit/CLICKHOUSE_SETUP.md` - Database setup

---

**END OF ANALYSIS**
