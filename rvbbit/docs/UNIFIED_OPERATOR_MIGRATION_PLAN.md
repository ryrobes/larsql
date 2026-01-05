# Unified Block Operator Migration Plan

## Executive Summary

Replace all hardcoded SQL operator rewriters with a single, cascade-driven block operator system. Cascades become fully self-describing - defining both execution logic AND SQL syntax patterns.

## Current State (Problems)

### Multiple Redundant Systems

| System | File | What it does | Problem |
|--------|------|--------------|---------|
| Block operators | `block_operators.py` | Parses `SEMANTIC_CASE...END` | Only one working, cascade-driven |
| Dynamic operators | `dynamic_operators.py` | Detects operators from cascades | Detection works, **rewriting not wired up** |
| Dimension rewriter | `dimension_rewriter.py` | `GROUP BY topics(...)` | Works, reads from registry |
| v2 rewriter | `semantic_rewriter_v2.py` | Infix operators (MEANS, ~) | **Hardcoded `_INFIX_SPECS`** |
| Aggregate rewriter | `llm_agg_rewriter.py` | SUMMARIZE, THEMES, etc. | **Hardcoded `LLM_AGG_FUNCTIONS`** |
| Semantic operators | `semantic_operators.py` | GROUP BY MEANING, SEMANTIC JOIN | **Hardcoded functions** |
| LLM aggregates | `llm_aggregates.py` | Implementation + fallbacks | **Duplicate fallback code** |

### Hardcoded Lists That Should Be Cascade Metadata

```python
# semantic_rewriter_v2.py - hardcoded
_INFIX_SPECS = [
    _InfixSpec("MEANS", ..., "semantic_means", ...),
    _InfixSpec("ABOUT", ..., "semantic_about", ...),
    # ... 15+ more
]

# llm_agg_rewriter.py - hardcoded
LLM_AGG_FUNCTIONS = {
    "LLM_SUMMARIZE": LLMAggFunction(...),
    "LLM_THEMES": LLMAggFunction(...),
    # ... 10+ more
}
LLM_AGG_ALIASES = {"SUMMARIZE": "LLM_SUMMARIZE", ...}

# semantic_operators.py - hardcoded functions
def _rewrite_group_by_meaning(query, ...): ...  # 100+ lines
def _rewrite_group_by_topics(query, ...): ...   # 80+ lines
def _rewrite_semantic_distinct(query, ...): ... # 60+ lines
```

## Target State

### Single Unified System

```
SQL Query
    ↓
unified_operator_rewriter.py
    ↓
reads block_operator definitions from all cascades
    ↓
token-aware pattern matching
    ↓
output template generation
    ↓
Rewritten SQL with function calls
    ↓
DuckDB executes, calls cascades via registry
```

### Cascade-Driven Everything

```yaml
# Every operator is defined in its cascade
cascade_id: semantic_means

sql_function:
  name: semantic_means
  returns: BOOLEAN

  # Multiple syntax patterns - ALL using block_operator
  patterns:
    - name: infix
      block_operator:
        inline: true
        structure:
          - capture: text
            as: expression
          - keyword: MEANS
          - capture: criterion
            as: string
        output: "semantic_means({{ text }}, {{ criterion }})"

    - name: function
      block_operator:
        start: "MEANS("
        end: ")"
        structure:
          - capture: text
            as: expression
          - keyword: ","
          - capture: criterion
            as: string
        output: "semantic_means({{ text }}, {{ criterion }})"

    - name: symbol
      block_operator:
        inline: true
        structure:
          - capture: text
            as: expression
          - keyword: "~"
          - capture: criterion
            as: string
        output: "semantic_means({{ text }}, {{ criterion }})"

cells:
  - name: evaluate
    instructions: ...
```

---

## Migration Phases

### Phase 1: Extend Block Operator System

**Goal:** Make `block_operators.py` capable of handling ALL pattern types.

#### 1.1 Add Inline Pattern Support

Currently block operators require `start`/`end` keywords for block structures. Add `inline: true` mode for patterns that appear inline in expressions.

```yaml
# Block pattern (existing)
block_operator:
  start: SEMANTIC_CASE
  end: END
  structure: ...

# Inline pattern (new)
block_operator:
  inline: true  # No start/end wrapper
  structure:
    - capture: lhs
      as: expression
    - keyword: MEANS
    - capture: rhs
      as: string
```

**Changes to `block_operators.py`:**
- `BlockOperatorSpec`: Add `inline: bool = False` field
- `_find_block_match()`: For inline specs, scan for pattern anywhere in token stream
- Pattern matching: Match sequence without requiring start/end delimiters

#### 1.2 Add Output Template Support

Block operators currently generate function calls by positional argument assembly. Add explicit output templates.

```yaml
block_operator:
  structure: ...
  output: "semantic_means({{ text }}, '{{ criterion }}')"

  # Or structured output for complex cases
  output:
    function: semantic_means
    args:
      - "{{ text }}"
      - "'{{ criterion }}'"
```

**Changes:**
- `BlockOperatorSpec`: Add `output_template: Optional[str]` field
- `_generate_function_call()`: Use Jinja2 template if provided, fall back to positional

#### 1.3 Add Expression Capture Improvements

Current capture only handles simple identifiers. Need to handle:
- Qualified names: `table.column`
- Function calls: `LOWER(name)`
- Arithmetic: `price * quantity`
- Nested expressions with parens

**Changes to `_capture_value()`:**
- `as: expression` - capture until next keyword/operator (balanced parens)
- `as: qualified_name` - capture `identifier(.identifier)*`
- `as: string` - capture quoted string (existing)
- `as: number` - capture numeric literal

#### 1.4 Add Multiple Patterns Per Cascade

A cascade may support multiple syntaxes (infix, function, aliases).

```yaml
sql_function:
  patterns:
    - name: infix
      block_operator: ...
    - name: function
      block_operator: ...
    - name: alias
      block_operator: ...
```

**Changes:**
- `load_block_operator_specs()`: Extract multiple patterns per cascade
- `BlockOperatorSpec`: Add `pattern_name: str` for debugging

#### 1.5 Add Context Markers

Some patterns only apply in certain contexts (GROUP BY, ORDER BY, WHERE).

```yaml
block_operator:
  context: group_by  # Only match after GROUP BY
  structure:
    - keyword: MEANING(
    - capture: column
      as: expression
    - keyword: )
```

**Changes:**
- `BlockOperatorSpec`: Add `context: Optional[str]` field
- `_find_block_match()`: Check context before matching

---

### Phase 2: Create Block Operator Definitions

**Goal:** Add `block_operator` / `patterns` to all existing cascades.

#### 2.1 Infix Operators

| Operator | Pattern | Output |
|----------|---------|--------|
| MEANS | `{{ a }} MEANS {{ b }}` | `semantic_means(a, b)` |
| ABOUT | `{{ a }} ABOUT {{ b }}` | `semantic_about(a, b)` |
| ~ | `{{ a }} ~ {{ b }}` | `semantic_means(a, b)` |
| !~ | `{{ a }} !~ {{ b }}` | `NOT semantic_means(a, b)` |
| IMPLIES | `{{ a }} IMPLIES {{ b }}` | `semantic_implies(a, b)` |
| CONTRADICTS | `{{ a }} CONTRADICTS {{ b }}` | `semantic_contradicts(a, b)` |
| ALIGNS WITH | `{{ a }} ALIGNS WITH {{ b }}` | `semantic_aligns(a, b)` |
| ASK | `{{ a }} ASK '{{ b }}'` | `semantic_ask(a, b)` |

**Files to update:**
- `traits/semantic_sql/means.cascade.yaml`
- `traits/semantic_sql/about.cascade.yaml`
- `traits/semantic_sql/implies.cascade.yaml`
- etc.

#### 2.2 Aggregate Functions

| Function | Arities | Output |
|----------|---------|--------|
| SUMMARIZE | 1, 2, 3 | `llm_summarize_N(LIST(col)::VARCHAR, ...)` |
| THEMES | 1, 2 | `llm_themes_N(LIST(col)::VARCHAR, ...)` |
| CLASSIFY | 2, 3 | `llm_classify_N(LIST(col)::VARCHAR, ...)` |
| CONSENSUS | 1, 2 | `llm_consensus_N(LIST(col)::VARCHAR, ...)` |
| DEDUPE | 1, 2 | `llm_dedupe_N(LIST(col)::VARCHAR, ...)` |
| OUTLIERS | 1, 2, 3 | `llm_outliers_N(LIST(col)::VARCHAR, ...)` |

Multi-arity example:
```yaml
block_operator:
  start: "SUMMARIZE("
  end: ")"
  structure:
    - capture: column
      as: expression
    - optional:
        pattern:
          - keyword: ","
          - capture: prompt
            as: string
    - optional:
        pattern:
          - keyword: ","
          - capture: max_items
            as: number
  output:
    function: llm_summarize
    arity_suffix: true  # Appends _1, _2, _3 based on captured args
    args:
      - "LIST({{ column }})::VARCHAR"
      - "{{ prompt }}"
      - "{{ max_items }}"
```

**Files to update:**
- `traits/semantic_sql/summarize.cascade.yaml`
- `traits/semantic_sql/themes.cascade.yaml`
- etc.

#### 2.3 Structural/Dimension Operators

| Pattern | Context | Output |
|---------|---------|--------|
| `GROUP BY MEANING(col, n, hint)` | group_by | CTE with clustering |
| `GROUP BY TOPICS(col, n)` | group_by | CTE with topic extraction |
| `SEMANTIC DISTINCT col` | select | CTE with deduplication |
| `ORDER BY col RELEVANCE TO 'x'` | order_by | `ORDER BY score('x', col) DESC` |

These may need `shape: dimension` treatment or CTE generation templates.

```yaml
block_operator:
  context: group_by
  structure:
    - keyword: "MEANING("
    - capture: column
      as: expression
    - optional:
        pattern:
          - keyword: ","
          - capture: num_clusters
            as: number
    - optional:
        pattern:
          - keyword: ","
          - capture: criterion
            as: string
    - keyword: ")"

  # Complex output - generates CTE
  output_mode: dimension
  output_template: |
    WITH _clustered AS (
      SELECT *, meaning_fn({{ column }},
        (SELECT to_json(LIST({{ column }})) FROM {{ source_table }}),
        {{ num_clusters | default('NULL') }},
        {{ criterion | default('NULL') }}
      ) as _semantic_cluster
      FROM {{ source_table }}
    )
    -- rest of query uses _semantic_cluster
```

**Files to update:**
- `traits/semantic_sql/cluster_dimension.cascade.yaml` (new, replaces MEANING)
- Already have `topics_dimension.cascade.yaml`

---

### Phase 3: Wire Up Unified Rewriter

**Goal:** Single entry point replaces all hardcoded rewriters.

#### 3.1 Create `unified_operator_rewriter.py`

```python
"""
Unified Operator Rewriter.

Single system for all SQL operator rewriting, driven entirely by cascade metadata.
Replaces: semantic_rewriter_v2.py, llm_agg_rewriter.py, semantic_operators.py
"""

def rewrite_all_operators(sql: str) -> str:
    """
    Rewrite all semantic operators using block_operator definitions from cascades.

    Order:
    1. Block patterns (SEMANTIC_CASE...END)
    2. Dimension patterns (GROUP BY MEANING, GROUP BY TOPICS)
    3. Inline patterns (MEANS, ABOUT, ~)
    4. Function patterns (SUMMARIZE, THEMES)
    """
    result = sql

    # Load all patterns from registry
    patterns = load_all_operator_patterns()

    # Apply in priority order
    for pattern in sorted(patterns, key=lambda p: p.priority):
        result = apply_pattern(result, pattern)

    return result
```

#### 3.2 Update `sql_rewriter.py` Pipeline

```python
# Before (multiple hardcoded rewriters)
result = _rewrite_block_operators(result)      # cascade-driven
result = _rewrite_dimension_functions(result)  # cascade-driven
result = _rewrite_semantic_operators(result)   # HARDCODED
result = _rewrite_llm_aggregates(result)       # HARDCODED

# After (single unified rewriter)
result = rewrite_all_operators(result)  # ALL cascade-driven
```

#### 3.3 Maintain Backwards Compatibility

During transition, support BOTH old cascade format (no `block_operator`) and new format:

```python
def load_all_operator_patterns():
    patterns = []

    for cascade in get_all_cascades():
        # New format: explicit block_operator
        if cascade.has_block_operators():
            patterns.extend(cascade.get_block_operators())

        # Legacy format: infer from operators list
        elif cascade.has_operators():
            patterns.extend(infer_patterns_from_operators(cascade))

    return patterns
```

---

### Phase 4: Remove Hardcoded Code

**Goal:** Delete all legacy hardcoded operator definitions.

#### 4.1 Delete from `semantic_rewriter_v2.py`

- Delete `_INFIX_SPECS` list
- Delete `_InfixSpec` class (or keep for backwards compat)
- Delete infix matching logic (replaced by block operator matching)
- Keep tokenizer (`_tokenize`) - reused by block operators

#### 4.2 Delete from `llm_agg_rewriter.py`

- Delete `LLM_AGG_FUNCTIONS` dict
- Delete `LLM_AGG_ALIASES` dict
- Delete `LLMAggFunction` class
- Delete `_build_replacement()` function
- Delete `rewrite_llm_aggregates()` function
- Keep `LLMAnnotation` parsing if still needed for `-- @` hints

#### 4.3 Delete from `semantic_operators.py`

- Delete `_rewrite_group_by_meaning()`
- Delete `_rewrite_group_by_topics()`
- Delete `_rewrite_semantic_distinct()`
- Delete `_rewrite_semantic_join()`
- Keep `_parse_annotations()` for `-- @` hint parsing

#### 4.4 Delete from `llm_aggregates.py`

- Delete all `_*_fallback()` functions (cascades are the only path)
- Simplify `_execute_cascade()` - remove fallback parameter

#### 4.5 Consolidate Files

Consider merging:
- `block_operators.py` + `dynamic_operators.py` → `unified_operator_rewriter.py`
- Keep `dimension_rewriter.py` or merge into unified system

---

### Phase 5: Testing and Validation

#### 5.1 Create Comprehensive Test Suite

```python
# tests/test_unified_operators.py

class TestInfixOperators:
    def test_means_basic(self):
        assert rewrite("SELECT * FROM t WHERE col MEANS 'x'") == \
               "SELECT * FROM t WHERE semantic_means(col, 'x')"

    def test_means_with_annotation(self):
        assert rewrite("""
            -- @ model: claude-haiku
            SELECT * FROM t WHERE col MEANS 'x'
        """) == ...

    def test_about_with_threshold(self):
        assert rewrite("SELECT * FROM t WHERE col ABOUT 'x' > 0.7") == \
               "SELECT * FROM t WHERE semantic_about(col, 'x') > 0.7"

class TestAggregateOperators:
    def test_summarize_arity_1(self):
        assert rewrite("SELECT SUMMARIZE(col) FROM t GROUP BY x") == \
               "SELECT llm_summarize_1(LIST(col)::VARCHAR) FROM t GROUP BY x"

    def test_summarize_arity_2(self):
        assert rewrite("SELECT SUMMARIZE(col, 'prompt') FROM t GROUP BY x") == \
               "SELECT llm_summarize_2(LIST(col)::VARCHAR, 'prompt') FROM t GROUP BY x"

class TestDimensionOperators:
    def test_group_by_meaning(self):
        result = rewrite("SELECT col, COUNT(*) FROM t GROUP BY MEANING(col, 5)")
        assert "WITH _clustered AS" in result
        assert "meaning" in result.lower()

class TestBlockOperators:
    def test_semantic_case(self):
        result = rewrite("""
            SELECT SEMANTIC_CASE description
                WHEN SEMANTIC 'eco' THEN 'green'
                WHEN SEMANTIC 'fast' THEN 'performance'
                ELSE 'standard'
            END FROM products
        """)
        assert "semantic_case(" in result
```

#### 5.2 Regression Testing

Run all existing tests to ensure backwards compatibility:
```bash
pytest tests/test_semantic_sql*.py -v
pytest tests/test_llm_agg*.py -v
```

#### 5.3 Performance Validation

Block operator parsing should be similar or faster than regex-based rewriters:
```python
def benchmark_rewriter():
    queries = load_test_queries()

    # Old system
    old_times = [time_rewrite_old(q) for q in queries]

    # New system
    new_times = [time_rewrite_new(q) for q in queries]

    assert mean(new_times) <= mean(old_times) * 1.1  # No more than 10% slower
```

---

## Implementation Order

### Sprint 1: Foundation (Phase 1)
- [ ] Add `inline: true` support to block operators
- [ ] Add output template support
- [ ] Add expression capture improvements
- [ ] Add multiple patterns per cascade support
- [ ] Unit tests for new block operator features

### Sprint 2: Cascade Definitions (Phase 2)
- [ ] Add block_operator to infix cascade files
- [ ] Add block_operator to aggregate cascade files
- [ ] Create cluster_dimension.cascade.yaml (replaces MEANING)
- [ ] Verify existing dimension cascades work

### Sprint 3: Unified Rewriter (Phase 3)
- [ ] Create unified_operator_rewriter.py
- [ ] Wire into sql_rewriter.py pipeline
- [ ] Add backwards compatibility for old format
- [ ] Integration tests

### Sprint 4: Cleanup (Phase 4)
- [ ] Delete hardcoded specs from semantic_rewriter_v2.py
- [ ] Delete hardcoded specs from llm_agg_rewriter.py
- [ ] Delete hardcoded functions from semantic_operators.py
- [ ] Delete fallback implementations from llm_aggregates.py
- [ ] Consolidate files

### Sprint 5: Validation (Phase 5)
- [ ] Full regression test suite
- [ ] Performance benchmarks
- [ ] Documentation updates
- [ ] Edge case testing

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Expression capture edge cases | Medium | Extensive test suite, fall back to old parser |
| Performance regression | Low | Block operators already tokenize; profile early |
| Breaking existing queries | High | Full regression suite, canary deployment |
| Complex CTE generation | Medium | Keep dimension_rewriter.py for now, migrate later |

---

## Success Criteria

1. **Zero hardcoded operator lists** in Python code
2. **All operators defined in cascade YAML files**
3. **Single unified rewriter** handles all pattern types
4. **100% backwards compatibility** with existing queries
5. **Performance parity** or better with old system
6. **Adding new operator = adding cascade file only**

---

## Appendix: Example Cascade After Migration

```yaml
cascade_id: semantic_about
description: Score how well text relates to a topic (0.0-1.0)

sql_function:
  name: semantic_about
  returns: DOUBLE

  patterns:
    # col ABOUT 'topic'
    - name: infix_about
      block_operator:
        inline: true
        structure:
          - capture: text
            as: expression
          - keyword: ABOUT
          - capture: topic
            as: string
        output: "semantic_about({{ text }}, {{ topic }})"

    # col REGARDING 'topic' (alias)
    - name: infix_regarding
      block_operator:
        inline: true
        structure:
          - capture: text
            as: expression
          - keyword: REGARDING
          - capture: topic
            as: string
        output: "semantic_about({{ text }}, {{ topic }})"

    # ABOUT(col, 'topic') (function form)
    - name: function
      block_operator:
        start: "ABOUT("
        end: ")"
        structure:
          - capture: text
            as: expression
          - keyword: ","
          - capture: topic
            as: string
        output: "semantic_about({{ text }}, {{ topic }})"

    # score('topic', col) (direct function - no rewrite needed)

inputs_schema:
  text: The text to evaluate
  topic: The topic to score against

cells:
  - name: score
    instructions: |
      Score how well this text relates to the given topic.
      Return a number from 0.0 (completely unrelated) to 1.0 (perfect match).

      Text: {{ input.text }}
      Topic: {{ input.topic }}
    output_schema:
      type: number
      minimum: 0.0
      maximum: 1.0
```
