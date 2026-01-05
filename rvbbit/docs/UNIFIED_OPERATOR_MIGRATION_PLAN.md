# Unified Block Operator Migration Plan

## Problem Statement and Intent

### The Core Problem

RVBBIT's Semantic SQL system has grown organically, resulting in **multiple redundant, hardcoded rewriter systems** that duplicate logic and prevent the "cascades all the way down" philosophy from being fully realized.

**Today:** Adding a new semantic operator requires:
1. Adding a cascade file (execution logic)
2. Editing Python code to add hardcoded patterns (syntax recognition)
3. Potentially editing multiple files (`semantic_rewriter_v2.py`, `llm_agg_rewriter.py`, `semantic_operators.py`)

**Goal:** Adding a new semantic operator requires:
1. Adding a cascade file with `operators` declared - **DONE**

### Why This Matters

1. **Cascades should be self-describing** - A cascade defines WHAT it does (execution) AND HOW to invoke it (syntax)
2. **No code changes for new operators** - Drop in a cascade file, it just works
3. **Consistency** - All operators use the same matching/rewriting system
4. **Maintainability** - One system to understand, test, and debug
5. **User empowerment** - Users can create custom operators without touching Python

### The Insight

**Infix is just syntax sugar.** `col MEANS 'x'` and `semantic_means(col, 'x')` are the same cascade call. The cascade does the work; the syntax is cosmetic. ANY cascade should be able to declare ANY syntax patterns it wants.

---

## Current State (Problems)

### Multiple Redundant Systems

| System | File | What it does | Problem |
|--------|------|--------------|---------|
| Block operators | `block_operators.py` | Parses `SEMANTIC_CASE...END` | **Working, cascade-driven** |
| Dynamic operators | `dynamic_operators.py` | Detects operators from cascades | Detection works, **rewriting not wired up** |
| Dimension rewriter | `dimension_rewriter.py` | `GROUP BY topics(...)` | **Working, cascade-driven** |
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

### The Irony

Cascades ALREADY declare their operators:
```yaml
operators:
  - "{{ text }} MEANS {{ criterion }}"
  - "MEANS({{ text }}, {{ criterion }})"
```

But this metadata is only used for **detection** (`dynamic_operators.py`), not **rewriting**. The hardcoded rewriters shadow it.

---

## Target State

### Single Unified System

```
SQL Query
    ↓
unified_operator_rewriter.py
    ↓
loads operator patterns from cascades (inferred or explicit)
    ↓
token-aware pattern matching (no regex on user SQL)
    ↓
output template generation
    ↓
Rewritten SQL with function calls
    ↓
DuckDB executes, calls cascades via registry
```

### Cascade-Driven Everything

```yaml
# Simple case - patterns INFERRED from operators list
cascade_id: semantic_means
sql_function:
  name: semantic_means
  operators:
    - "{{ text }} MEANS {{ criterion }}"      # Inferred: infix binary
    - "{{ text }} ~ {{ criterion }}"          # Inferred: infix symbol
    - "MEANS({{ text }}, {{ criterion }})"    # Inferred: function call

# Complex case - explicit block_operator (only when needed)
cascade_id: semantic_case
sql_function:
  name: semantic_case
  block_operator:
    start: SEMANTIC_CASE
    end: END
    structure:
      - capture: text
        as: expression
      - repeat:
          min: 1
          pattern:
            - keyword: WHEN SEMANTIC
            - capture: condition
              as: string
            - keyword: THEN
            - capture: result
              as: string
      - optional:
          pattern:
            - keyword: ELSE
            - capture: default
              as: string
```

---

## Key Design Decision: Inferred Operators

### The Simpler Approach

Instead of requiring every cascade to define verbose `block_operator` specs, **infer them from the existing `operators` template syntax**.

The template syntax already contains structure:
- `{{ name }}` → capture a value
- `'{{ name }}'` → capture a string (quoted)
- Literal text → keyword to match
- Position → order of elements

### Inference Rules

| Template Pattern | Inferred Type | Example |
|------------------|---------------|---------|
| `{{ a }} KEYWORD {{ b }}` | `infix_binary` | `{{ text }} MEANS {{ criterion }}` |
| `{{ a }} KW1 KW2 {{ b }}` | `infix_binary` (multi-word) | `{{ text }} ALIGNS WITH {{ narrative }}` |
| `{{ a }} SYMBOL {{ b }}` | `infix_binary` (symbol) | `{{ text }} ~ {{ criterion }}` |
| `FUNC({{ a }})` | `function_1` | `SUMMARIZE({{ column }})` |
| `FUNC({{ a }}, {{ b }})` | `function_2` | `MEANS({{ text }}, {{ criterion }})` |
| `FUNC({{ a }}, '{{ b }}')` | `function_2` (string arg) | `SUMMARIZE({{ col }}, '{{ prompt }}')` |

### Implementation

```python
def infer_block_operator(template: str, func_name: str) -> BlockOperatorSpec:
    """
    Convert template syntax to BlockOperatorSpec.

    "{{ text }} MEANS {{ criterion }}" →
    BlockOperatorSpec(
        inline=True,
        structure=[
            {"capture": "text", "as": "expression"},
            {"keyword": "MEANS"},
            {"capture": "criterion", "as": "string"},
        ],
        output_template=f"{func_name}({{{{ text }}}}, {{{{ criterion }}}})"
    )
    """
    parts = parse_template(template)  # Regex here, but limited scope

    structure = []
    captures = []

    for part in parts:
        if part.is_capture:
            capture_type = "string" if part.is_quoted else "expression"
            structure.append({"capture": part.name, "as": capture_type})
            captures.append(part.name)
        else:
            structure.append({"keyword": part.text.strip()})

    # Determine if inline or function-style
    is_function = re.match(r'^\w+\s*\(', template.strip())

    # Build output template
    args = ", ".join(f"{{{{ {c} }}}}" for c in captures)
    output = f"{func_name}({args})"

    return BlockOperatorSpec(
        name=func_name,
        inline=not is_function,
        structure=structure,
        output_template=output,
    )
```

### Multiple Shapes Per Cascade

A single cascade can support ALL syntax variations:

```yaml
operators:
  # All inferred automatically, all work simultaneously
  - "{{ text }} MEANS {{ criterion }}"           # infix
  - "{{ text }} ~ {{ criterion }}"               # infix symbol
  - "{{ text }} SEMANTICALLY MATCHES {{ c }}"   # infix multi-word alias
  - "MEANS({{ text }}, {{ criterion }})"         # function
  - "matches({{ text }}, {{ criterion }})"       # function alias
```

User writes whichever they prefer - all resolve to the same cascade.

### When to Use Explicit block_operator

Only for patterns that can't be expressed as simple templates:

1. **Block structures** with `start`/`end` keywords (`SEMANTIC_CASE...END`)
2. **Repeating elements** (`WHEN...THEN` pairs)
3. **Optional elements** in complex arrangements
4. **Context-sensitive** patterns (GROUP BY specific)
5. **Complex output** (CTE generation)

**99% of operators use inference. 1% need explicit block_operator.**

---

## Regex Usage Strategy

| Where | Uses Regex? | When | Why OK |
|-------|-------------|------|--------|
| **Template parsing** | Yes | Once at server startup | Limited scope, simple patterns |
| **SQL rewriting** | **NO** | Every query | Token-based matching |
| **Pattern matching** | **NO** | Every query | Structured keyword/capture |

```python
# Template parsing - regex, but trivial and one-time
CAPTURE_PATTERN = re.compile(r"('?)(\{\{\s*(\w+)\s*\}\})('?)")

def parse_template(template: str) -> List[Part]:
    """Parse "{{ text }} MEANS {{ criterion }}" into structured parts."""
    # This regex runs ONCE per cascade at load time, not on user queries
```

**The main rewriting path is 100% regex-free.** Token-based, structured matching only.

---

## Migration Phases

### Phase 1: Add Template Inference to Block Operators

**Goal:** Make `block_operators.py` infer patterns from `operators` templates.

#### 1.1 Add Template Parser

```python
# block_operators.py or new inference module

@dataclass
class TemplatePart:
    text: str
    is_capture: bool
    is_quoted: bool = False
    name: Optional[str] = None

def parse_operator_template(template: str) -> List[TemplatePart]:
    """Parse "{{ text }} MEANS '{{ criterion }}'" into parts."""
    ...

def infer_block_operator(template: str, func_name: str) -> BlockOperatorSpec:
    """Convert template to BlockOperatorSpec."""
    ...
```

#### 1.2 Add Inline Pattern Support

Extend `BlockOperatorSpec` for patterns without `start`/`end`:

```python
@dataclass
class BlockOperatorSpec:
    name: str
    cascade_path: str
    structure: List[Dict[str, Any]]
    returns: str = "VARCHAR"

    # Existing (for SEMANTIC_CASE...END)
    start_keyword: Optional[str] = None
    end_keyword: Optional[str] = None

    # New (for infix/function patterns)
    inline: bool = False
    output_template: Optional[str] = None
```

#### 1.3 Update Pattern Loading

```python
def load_all_operator_specs() -> List[BlockOperatorSpec]:
    specs = []

    for entry in get_sql_function_registry().values():
        # Explicit block_operator takes priority
        if entry.block_operator:
            specs.append(parse_explicit_block_operator(entry))

        # Infer from operators templates
        for template in entry.operators:
            specs.append(infer_block_operator(template, entry.name))

    return specs
```

#### 1.4 Add Output Template Support

```python
def _generate_function_call(match: BlockMatch) -> str:
    """Generate function call from matched pattern."""
    if match.spec.output_template:
        # Use Jinja2 template
        return render_template(match.spec.output_template, match.captures)
    else:
        # Fall back to positional assembly (existing behavior)
        return assemble_positional(match)
```

---

### Phase 2: Wire Up Unified Rewriter

**Goal:** Single entry point uses inferred + explicit patterns.

#### 2.1 Create Unified Entry Point

```python
# unified_operator_rewriter.py

def rewrite_all_operators(sql: str) -> str:
    """
    Rewrite all semantic operators using patterns from cascades.

    Sources:
    1. Explicit block_operator definitions (complex patterns)
    2. Inferred from operators templates (simple patterns)

    Order:
    1. Block patterns (SEMANTIC_CASE...END) - must be first
    2. Dimension patterns (shape: dimension cascades)
    3. Inline patterns (infix operators)
    4. Function patterns (SUMMARIZE, etc.)
    """
    specs = load_all_operator_specs()

    # Sort by priority (block > dimension > inline > function)
    specs.sort(key=lambda s: s.priority)

    result = sql
    tokens = tokenize(sql)

    for spec in specs:
        result, tokens = apply_spec(result, tokens, spec)

    return result
```

#### 2.2 Update sql_rewriter.py Pipeline

```python
# Before: multiple hardcoded rewriters
result = _rewrite_block_operators(result)      # cascade-driven
result = _rewrite_dimension_functions(result)  # cascade-driven
result = _rewrite_semantic_operators(result)   # HARDCODED
result = _rewrite_llm_aggregates(result)       # HARDCODED

# After: single unified rewriter
from .sql_tools.unified_operator_rewriter import rewrite_all_operators
result = rewrite_all_operators(result)  # ALL cascade-driven
```

---

### Phase 3: Remove Hardcoded Code

**Goal:** Delete all legacy hardcoded operator definitions.

#### 3.1 Delete from `semantic_rewriter_v2.py`

- Delete `_INFIX_SPECS` list
- Delete `_InfixSpec` class
- Delete infix matching logic
- **Keep** tokenizer (`_tokenize`) - reused by unified rewriter

#### 3.2 Delete from `llm_agg_rewriter.py`

- Delete `LLM_AGG_FUNCTIONS` dict
- Delete `LLM_AGG_ALIASES` dict
- Delete `LLMAggFunction` class
- Delete `_build_replacement()` function
- **Keep** `LLMAnnotation` parsing for `-- @` hints (move to shared module)

#### 3.3 Delete from `semantic_operators.py`

- Delete `_rewrite_group_by_meaning()`
- Delete `_rewrite_group_by_topics()`
- Delete `_rewrite_semantic_distinct()`
- Delete `_rewrite_semantic_join()`
- **Keep** `_parse_annotations()` for `-- @` hints

#### 3.4 Delete from `llm_aggregates.py`

- Delete all `_*_fallback()` functions
- Simplify `_execute_cascade()` - remove fallback parameter
- Cascades are the only execution path

#### 3.5 Consolidate Files

```
Before:
  sql_tools/
    block_operators.py
    dynamic_operators.py
    semantic_rewriter_v2.py
    llm_agg_rewriter.py
    semantic_operators.py
    dimension_rewriter.py

After:
  sql_tools/
    unified_operator_rewriter.py  # Main entry point
    block_operators.py            # BlockOperatorSpec, matching logic
    operator_inference.py         # Template parsing, inference
    tokenizer.py                  # Shared tokenizer (from v2)
    annotations.py                # -- @ hint parsing (shared)
    dimension_rewriter.py         # Keep for now, or merge later
```

---

### Phase 4: Testing and Validation

#### 4.1 Comprehensive Test Suite

```python
class TestInferredOperators:
    def test_infix_binary(self):
        spec = infer_block_operator("{{ text }} MEANS {{ criterion }}", "semantic_means")
        assert spec.inline == True
        assert len(spec.structure) == 3
        assert spec.output_template == "semantic_means({{ text }}, {{ criterion }})"

    def test_infix_symbol(self):
        spec = infer_block_operator("{{ a }} ~ {{ b }}", "semantic_means")
        assert spec.structure[1]["keyword"] == "~"

    def test_function_form(self):
        spec = infer_block_operator("SUMMARIZE({{ col }}, '{{ prompt }}')", "llm_summarize")
        assert spec.inline == False
        assert spec.structure[1]["as"] == "string"  # quoted capture

class TestUnifiedRewriter:
    def test_infix_rewrite(self):
        result = rewrite_all_operators("SELECT * FROM t WHERE col MEANS 'x'")
        assert "semantic_means(col, 'x')" in result

    def test_function_rewrite(self):
        result = rewrite_all_operators("SELECT SUMMARIZE(col) FROM t GROUP BY x")
        assert "llm_summarize" in result
        assert "LIST(col)" in result

    def test_block_rewrite(self):
        result = rewrite_all_operators("""
            SELECT SEMANTIC_CASE desc
                WHEN SEMANTIC 'eco' THEN 'green'
            END FROM t
        """)
        assert "semantic_case(" in result
```

#### 4.2 Regression Testing

```bash
# All existing tests must pass
pytest tests/test_semantic_sql*.py -v
pytest tests/test_llm_agg*.py -v
pytest tests/test_block_operators*.py -v
```

#### 4.3 Performance Validation

```python
def benchmark():
    queries = load_test_queries()  # 1000+ queries

    # Unified system should be same speed or faster
    # (token-based matching vs regex)
    old_time = timeit(lambda: [old_rewrite(q) for q in queries])
    new_time = timeit(lambda: [rewrite_all_operators(q) for q in queries])

    assert new_time <= old_time * 1.1  # No more than 10% slower
```

---

## Implementation Order

### Sprint 1: Inference Foundation
- [ ] Create `operator_inference.py` with template parser
- [ ] Add `infer_block_operator()` function
- [ ] Add `inline` and `output_template` to `BlockOperatorSpec`
- [ ] Unit tests for inference logic

### Sprint 2: Unified Rewriter
- [ ] Create `unified_operator_rewriter.py`
- [ ] Integrate inference with explicit block_operator loading
- [ ] Wire into `sql_rewriter.py` pipeline
- [ ] Integration tests

### Sprint 3: Cleanup
- [ ] Delete hardcoded specs from all files
- [ ] Delete fallback implementations
- [ ] Consolidate files
- [ ] Update imports across codebase

### Sprint 4: Validation
- [ ] Full regression test suite
- [ ] Performance benchmarks
- [ ] Edge case testing
- [ ] Documentation updates

**Estimated Total: 1.5-2 weeks** (simplified from original 2-3 weeks)

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Inference edge cases | Medium | Extensive test suite; explicit block_operator as escape hatch |
| Template parsing bugs | Low | Limited regex scope; well-tested patterns |
| Performance regression | Low | Token-based matching is fast; profile early |
| Breaking existing queries | High | Full regression suite; gradual rollout |

---

## Success Criteria

1. **Zero hardcoded operator lists** in Python code
2. **Existing `operators` fields work** - no cascade changes needed
3. **Single unified rewriter** handles all pattern types
4. **100% backwards compatibility** with existing queries
5. **Performance parity** or better with old system
6. **Adding new operator = adding cascade file only** (with `operators` declared)
7. **Complex patterns use explicit block_operator** - escape hatch available

---

## Appendix A: Inference Examples

### Infix Binary
```yaml
operators:
  - "{{ text }} MEANS {{ criterion }}"
```
Inferred:
```python
BlockOperatorSpec(
    inline=True,
    structure=[
        {"capture": "text", "as": "expression"},
        {"keyword": "MEANS"},
        {"capture": "criterion", "as": "string"},
    ],
    output_template="semantic_means({{ text }}, {{ criterion }})"
)
```

### Infix Symbol
```yaml
operators:
  - "{{ a }} ~ {{ b }}"
```
Inferred:
```python
BlockOperatorSpec(
    inline=True,
    structure=[
        {"capture": "a", "as": "expression"},
        {"keyword": "~"},
        {"capture": "b", "as": "string"},
    ],
    output_template="semantic_means({{ a }}, {{ b }})"
)
```

### Function with Optional Args
```yaml
operators:
  - "SUMMARIZE({{ col }})"
  - "SUMMARIZE({{ col }}, '{{ prompt }}')"
```
Inferred as TWO specs (one per template), or merged with optional handling.

### Multi-word Keyword
```yaml
operators:
  - "{{ text }} ALIGNS WITH {{ narrative }}"
```
Inferred:
```python
BlockOperatorSpec(
    inline=True,
    structure=[
        {"capture": "text", "as": "expression"},
        {"keyword": "ALIGNS WITH"},  # Multi-word keyword
        {"capture": "narrative", "as": "string"},
    ],
    output_template="semantic_aligns({{ text }}, {{ narrative }})"
)
```

---

## Appendix B: When Explicit block_operator is Needed

### 1. Block Structures (START...END)
```yaml
block_operator:
  start: SEMANTIC_CASE
  end: END
  structure: ...
```

### 2. Repeating Elements
```yaml
block_operator:
  structure:
    - repeat:
        min: 1
        pattern:
          - keyword: WHEN SEMANTIC
          - capture: condition
            as: string
```

### 3. Complex Optional Arrangements
```yaml
block_operator:
  structure:
    - capture: col
      as: expression
    - optional:
        pattern:
          - keyword: ","
          - capture: n
            as: number
    - optional:
        pattern:
          - keyword: ","
          - capture: hint
            as: string
```

### 4. Context-Sensitive (GROUP BY)
```yaml
block_operator:
  context: group_by
  structure:
    - keyword: MEANING(
    - capture: col
      as: expression
    - keyword: )
```

### 5. Complex Output (CTE Generation)
```yaml
block_operator:
  output_mode: dimension
  output_template: |
    WITH _clustered AS (
      SELECT *, meaning_fn({{ column }}, ...) as _cluster
      FROM {{ source }}
    )
    ...
```
