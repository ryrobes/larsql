# Semantic SQL Dynamic Rewrite Tests

## Overview

`test_semantic_sql_rewrites_dynamic.py` is a **dynamic test generator** that automatically discovers all SQL operators from cascade definitions and generates comprehensive rewrite tests.

**Key Features:**
- ✅ **Zero maintenance** - Automatically discovers new operators as you add cascade files
- ✅ **No LLM calls** - Pure SQL syntax validation (fast, deterministic)
- ✅ **Multi-shape testing** - Tests SCALAR, AGGREGATE, and TABLE operators
- ✅ **Pattern coverage** - Tests all operator variations (infix, function, keywords)
- ✅ **93 tests generated** from 25 cascade definitions

## What It Tests

### Discovery Phase
1. Scans `cascades/semantic_sql/` for built-in operators
2. Scans `traits/` for user-defined operators with `sql_function` metadata
3. Extracts operator patterns from each cascade's `sql_function.operators` list

### Test Generation
For each operator pattern, generates test cases:
- **Infix operators**: `col MEANS 'x'`, `col ABOUT 'x' > 0.7`, `a SIMILAR_TO b`
- **Function calls**: `semantic_matches('x', col)`, `score('x', col)`
- **Aggregate functions**: `SUMMARIZE(texts)`, `THEMES(comments, 3)`
- **Table functions (explicit DuckDB form)**: `read_json_auto(vector_search_json_3('query', 'table', 10))`
- **Negation**: `NOT MEANS`, `NOT ABOUT`
- **Ordering**: `ORDER BY ... RELEVANCE TO`

### Validation
Verifies that rewritten SQL contains the expected UDF function name (accepts both `semantic_*` and short forms).

## Running the Tests

```bash
# Run all dynamic tests
pytest lars/tests/test_semantic_sql_rewrites_dynamic.py -v

# Run discovery summary
python lars/tests/test_semantic_sql_rewrites_dynamic.py

# Run specific operator test
pytest lars/tests/test_semantic_sql_rewrites_dynamic.py -k "means_operator" -v
```

## Current Coverage (2026-01-02)

**25 cascades discovered:**
- `semantic_matches` (MEANS, MATCHES, ~) - **3 operators** ✅ Tilde operator working!
- `semantic_score` (ABOUT, RELEVANCE TO) - **2 operators**
- `semantic_implies` (IMPLIES) - **1 operator**
- `semantic_contradicts` (CONTRADICTS) - **1 operator**
- `semantic_aligns` (ALIGNS, ALIGNS WITH) - **2 operators**
- `semantic_similar_to` (SIMILAR_TO, SIMILAR TO) - **2 operators**
- `semantic_sounds_like` (SOUNDS_LIKE) - **1 operator**
- `semantic_summarize` (SUMMARIZE) - **2 operators**
- `semantic_themes` (THEMES, TOPICS) - **4 operators**
- `semantic_cluster` (CLUSTER, MEANING) - **3-5 operators**
- `semantic_embed` (EMBED) - **2 operators**
- `semantic_embed_with_storage` - **1 operator**
- `semantic_vector_search` (VECTOR_SEARCH) - **3 operators**
- Plus: `semantic_dedupe`, `semantic_sentiment`, `semantic_consensus`, `semantic_outliers`, `semantic_classify_collection`, `semantic_summarize_urls`

**96 tests generated and passing** ✅ (including 3 new tilde operator tests)

## Known Issues

### 1. ~~Tilde Operator (~) Not Implemented~~ ✅ **FIXED (2026-01-02)**
**Status:** Fully implemented and tested

**Problem:** The tilde operator was defined in `matches.cascade.yaml` but wasn't detected or rewritten

**Root Causes:**
1. Dynamic operator discovery only detected alphanumeric keywords, not symbols
2. `has_any_semantic_operator()` used word boundary regex (`\b`) which doesn't work for symbols

**Solution:**
1. Added symbol operator detection in `dynamic_operators.py` (lines 97-104)
2. Updated `has_any_semantic_operator()` to handle non-alphanumeric operators (lines 181-193)
3. Updated `has_semantic_operator_in_line()` similarly (lines 207-221)
4. Modified `_rewrite_tilde()` and `_rewrite_not_tilde()` to use `matches()` instead of non-existent `match_pair()`

**Now working:**
```sql
-- String literal (most common):
SELECT * FROM docs WHERE title ~ 'visual contact'
→ SELECT * FROM docs WHERE matches('visual contact', title)

-- Column vs column:
SELECT * FROM customers c, suppliers s WHERE c.company ~ s.vendor
→ SELECT * FROM customers c, suppliers s WHERE matches(c.company, s.vendor)

-- Negation:
SELECT * FROM products WHERE name !~ 'discontinued'
→ SELECT * FROM products WHERE NOT matches('discontinued', name)
```

**Test Results:** ✅ 3/3 tilde operator tests passing

### 2. Missing Test Generators
Some operators have 0 generated tests because the test generator doesn't have patterns for them yet:

- `semantic_vector_search` - TABLE function (complex CTE rewriting)
- `semantic_summarize_urls` - Not in standard test patterns
- `semantic_classify_collection` - Not in standard test patterns
- `semantic_consensus` - Aggregate without specific test pattern
- `semantic_dedupe` - Aggregate without specific test pattern
- `semantic_sentiment` - Aggregate without specific test pattern
- `semantic_outliers` - Aggregate without specific test pattern

**To Fix:** Extend `_generate_*_tests()` functions in the test file

## Adding New Operators

When you create a new cascade with `sql_function` metadata:

1. **No code changes needed** - Tests auto-discover it
2. **Optionally add test pattern** - Edit `_generate_scalar_tests()` or `_generate_aggregate_tests()` to add specific test cases for your operator
3. **Run tests** - Verify rewriting works correctly

Example:
```yaml
# cascades/semantic_sql/custom.cascade.yaml
sql_function:
  name: semantic_custom
  operators:
    - "{{ text }} IS_CUSTOM {{ criterion }}"
  # ... rest of cascade definition
```

After adding this file, re-run tests - new test cases will be auto-generated!

## Test Structure

```
test_semantic_sql_rewrites_dynamic.py
├── discover_sql_cascades()        # Scan filesystem for cascades
├── generate_test_cases()           # Create test cases per cascade
│   ├── _generate_scalar_tests()   # SCALAR operator patterns
│   ├── _generate_aggregate_tests() # AGGREGATE operator patterns
│   └── _generate_table_tests()    # TABLE operator patterns
├── test_sql_operator_rewrite()    # Main parametrized test
├── test_all_cascades_discovered() # Discovery sanity check
├── test_generated_test_count()    # Coverage sanity check
└── test_spot_check_*()            # Manual verification tests
```

## Debugging Failed Tests

If a test fails, the assertion shows:
```
Expected function 'semantic_matches' (or short form) not found in rewrite.
Cascade: semantic_matches
Original:  SELECT * FROM docs WHERE title MEANS 'visual contact'
Rewritten: SELECT * FROM docs WHERE title MEANS 'visual contact'
Looking for any of: ['semantic_matches', 'matches']
```

This means the rewriter didn't transform the operator. Check:
1. Is the operator pattern registered in `dynamic_operators.py`?
2. Is the rewrite logic present in `semantic_operators.py`?
3. Is the pattern correctly specified in the cascade YAML?

## Performance

- **Discovery**: ~100ms (scans 25 cascades)
- **Test generation**: ~50ms (creates 93 test cases)
- **Test execution**: ~2.5 seconds (93 tests, no LLM calls)

**Total runtime: < 3 seconds** ⚡

## Future Enhancements

1. **Edge case testing**: Add malformed SQL, injection attempts, complex CTEs
2. **Negative testing**: Verify invalid syntax is rejected gracefully
3. **Integration tests**: Chain multiple operators in one query
4. **Snapshot testing**: Capture known-good rewrites and detect regressions
5. **Coverage metrics**: Track which cascade features are tested vs. untested
