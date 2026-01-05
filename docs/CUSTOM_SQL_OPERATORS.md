# Creating Custom SQL Operators in RVBBIT

**New in 2026:** RVBBIT now supports **user-defined SQL operators** through cascade files. No Python code changes required!

The template inference system automatically converts operator patterns like `{{ text }} MEANS {{ criterion }}` into structured pattern matching, making it trivial to add new semantic SQL syntax.

---

## Quick Start: Your First Custom Operator

Let's create a `SIMILAR_TO` operator that checks if two texts are semantically similar.

### Step 1: Create a Cascade File

Create `cascades/my_operators/similar_to.cascade.yaml`:

```yaml
cascade_id: similar_to
description: Check if two texts are semantically similar

inputs_schema:
  text1: First text to compare
  text2: Second text to compare

sql_function:
  name: similar_to
  description: Returns true if texts are semantically similar
  args:
    - name: text1
      type: VARCHAR
    - name: text2
      type: VARCHAR
  returns: BOOLEAN
  shape: SCALAR
  operators:
    - "{{ text1 }} SIMILAR_TO {{ text2 }}"
    - "SIMILAR_TO({{ text1 }}, {{ text2 }})"
  cache: true

cells:
  - name: compare
    model: google/gemini-2.5-flash-lite
    instructions: |
      Are these two texts semantically similar or describing the same concept?

      TEXT 1: {{ input.text1 }}
      TEXT 2: {{ input.text2 }}

      Respond with ONLY "true" or "false".
    rules:
      max_turns: 1
```

### Step 2: Use It in SQL

That's it! Your operator now works in SQL:

```sql
-- Infix syntax (automatically inferred):
SELECT * FROM products
WHERE description SIMILAR_TO 'eco-friendly sustainable'

-- Function syntax (automatically inferred):
SELECT product_name, SIMILAR_TO(description, 'green products') as is_eco
FROM products
```

**No Python code changes required!** 🎉

---

## How Template Inference Works

The `operators` field uses template syntax with `{{ variable }}` placeholders. The system **automatically infers** the pattern structure:

### Pattern Types

| Template Pattern | Inferred Type | Example SQL |
|------------------|---------------|-------------|
| `{{ a }} KEYWORD {{ b }}` | Infix binary | `col MEANS 'x'` |
| `{{ a }} WORD1 WORD2 {{ b }}` | Multi-word infix | `col ALIGNS WITH 'narrative'` |
| `{{ a }} SYMBOL {{ b }}` | Symbol operator | `a ~ b` |
| `FUNC({{ a }})` | Function (1 arg) | `SUMMARIZE(col)` |
| `FUNC({{ a }}, {{ b }})` | Function (2 args) | `CLASSIFY(col, 'category')` |
| `FUNC({{ a }}, '{{ b }}')` | Quoted arg | `EXTRACT(col, 'pattern')` |

### Inference Rules

**Captures:**
- `{{ name }}` → Capture expression (column, identifier, etc.)
- `'{{ name }}'` → Capture string literal (forces quoted)

**Keywords:**
- Literal text between `{{ }}` markers → Keyword to match
- Multi-word keywords stay together: `ALIGNS WITH` → single keyword

**Output:**
- All patterns generate function call: `function_name({{ arg1 }}, {{ arg2 }})`

---

## Complete Examples

### Example 1: Multi-Word Infix Operator

```yaml
cascade_id: semantic_aligns
sql_function:
  name: semantic_aligns
  operators:
    - "{{ text }} ALIGNS WITH {{ narrative }}"
  args:
    - name: text
      type: VARCHAR
    - name: narrative
      type: VARCHAR
  returns: BOOLEAN

cells:
  - name: check_alignment
    instructions: |
      Does this text align with the given narrative?
      TEXT: {{ input.text }}
      NARRATIVE: {{ input.narrative }}
      Answer: true or false
```

**Usage:**
```sql
SELECT * FROM articles
WHERE content ALIGNS WITH 'climate action urgency'
```

### Example 2: Multiple Syntax Variations

One cascade can support **multiple syntaxes**:

```yaml
cascade_id: semantic_extract
sql_function:
  name: semantic_extract
  operators:
    - "{{ text }} EXTRACTS {{ pattern }}"
    - "EXTRACT({{ text }}, '{{ pattern }}')"
    - "GET({{ text }}, '{{ pattern }}')"
    # All three work!
  args:
    - name: text
      type: VARCHAR
    - name: pattern
      type: VARCHAR
  returns: VARCHAR
```

**Usage (all equivalent):**
```sql
-- Pick your favorite syntax:
SELECT description EXTRACTS 'price information' FROM products
SELECT EXTRACT(description, 'price information') FROM products
SELECT GET(description, 'price information') FROM products
```

### Example 3: Symbol Operators

```yaml
cascade_id: semantic_matches
sql_function:
  name: semantic_matches
  operators:
    - "{{ text }} MEANS {{ criterion }}"
    - "{{ text }} ~ {{ criterion }}"
    - "{{ text }} ≈ {{ criterion }}"  # Unicode works!
  args:
    - name: text
      type: VARCHAR
    - name: criterion
      type: VARCHAR
  returns: BOOLEAN
```

**Usage:**
```sql
SELECT * FROM docs WHERE title ~ 'urgent matter'
SELECT * FROM docs WHERE title ≈ 'critical issue'
```

### Example 4: Aggregate Functions

For GROUP BY aggregates:

```yaml
cascade_id: semantic_consensus
sql_function:
  name: semantic_consensus
  shape: AGGREGATE  # Important!
  operators:
    - "CONSENSUS({{ texts }})"
    - "CONSENSUS({{ texts }}, '{{ prompt }}')"
  args:
    - name: texts
      type: JSON  # Will receive LIST() output
    - name: prompt
      type: VARCHAR
      optional: true
  returns: VARCHAR
  context_arg: texts  # Tells system this arg gets aggregated values

cells:
  - name: find_consensus
    instructions: |
      Find common themes in these texts:
      {{ input.texts }}

      {% if input.prompt %}
      Focus on: {{ input.prompt }}
      {% endif %}
```

**Usage:**
```sql
SELECT
  state,
  CONSENSUS(observations) as common_theme
FROM bigfoot
GROUP BY state
```

---

## Operator Types Reference

### SCALAR Functions

Process single values, return single values:

```yaml
shape: SCALAR  # or omit (SCALAR is default)
operators:
  - "{{ input }} OPERATOR {{ param }}"
```

### AGGREGATE Functions

Process groups of values, return single value per group:

```yaml
shape: AGGREGATE
context_arg: values  # Which arg receives the aggregated data
operators:
  - "AGGREGATE_FUNC({{ values }})"
```

**Note:** Aggregates receive JSON array from `LIST(col)` collection.

### DIMENSION Functions

Create semantic buckets for GROUP BY (advanced):

```yaml
shape: DIMENSION
operators:
  - "topics({{ column }}, {{ num_topics }})"
```

Automatically generates CTE-based execution for proper semantic bucketing.

---

## Advanced: Explicit Block Operators

For complex patterns that templates can't express (repeating elements, optional blocks):

```yaml
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

**Usage:**
```sql
SELECT SEMANTIC_CASE description
    WHEN SEMANTIC 'sustainability' THEN 'eco'
    WHEN SEMANTIC 'performance' THEN 'perf'
    ELSE 'standard'
END
FROM products
```

**99% of operators use simple templates. Only use `block_operator` for complex patterns!**

---

## Best Practices

### 1. Start Simple

```yaml
# Good (simple, clear):
operators:
  - "{{ text }} MY_OP {{ param }}"

# Avoid (over-engineered):
block_operator:
  start: MY_OP_START
  end: MY_OP_END
  # ... 50 lines of structure
```

### 2. Support Multiple Syntaxes

```yaml
# Let users pick their favorite:
operators:
  - "{{ a }} MATCHES {{ b }}"      # English
  - "{{ a }} ~ {{ b }}"            # Terse symbol
  - "MATCHES({{ a }}, {{ b }})"    # Function style
```

### 3. Use Meaningful Names

```yaml
# Good:
operators:
  - "{{ product_name }} BRANDED_AS {{ brand }}"

# Bad:
operators:
  - "{{ x }} OP {{ y }}"  # What does this mean?
```

### 4. Cache Aggressively

```yaml
sql_function:
  cache: true  # Same inputs → same output = cache it!
```

Semantic operations are expensive. Caching is critical.

### 5. Pick the Right Shape

- **SCALAR**: One value in → one value out (most operators)
- **AGGREGATE**: Many values in → one value out (GROUP BY)
- **DIMENSION**: Many values → determine buckets → classify each (GROUP BY with semantic bucketing)

---

## Testing Your Operator

### 1. Test the Cascade

```bash
# Run cascade directly:
rvbbit run cascades/my_operators/similar_to.yaml \
  --input '{"text1": "sustainable", "text2": "eco-friendly"}'
```

### 2. Test in SQL

```bash
# Start SQL server:
rvbbit serve sql --port 15432

# Connect and test:
psql -h localhost -p 15432 -d mydb
```

```sql
-- Test basic rewrite:
SELECT 'test1' SIMILAR_TO 'test2';

-- Test with real data:
SELECT product_name, description SIMILAR_TO 'green products' as is_eco
FROM products
LIMIT 5;
```

### 3. Check Rewrite Output

```sql
-- See what the rewriter generates:
EXPLAIN SELECT * FROM t WHERE col SIMILAR_TO 'x';
```

This shows the rewritten SQL before execution.

---

## Troubleshooting

### Operator Not Detected

**Problem:** SQL query doesn't recognize your operator

**Solutions:**
1. Check cascade is in `cascades/` or `traits/` directory
2. Verify `sql_function.operators` field exists
3. Restart SQL server to reload registry
4. Check logs: `grep "Registered from cascades" logs/latest.log`

### Rewrite Not Working

**Problem:** Operator detected but not rewritten

**Debug:**
```python
from rvbbit.sql_tools.block_operators import load_block_operator_specs

specs = load_block_operator_specs(force=True)
print(f"Loaded {len(specs)} operator specs")

# Find yours:
my_spec = [s for s in specs if s.name == 'similar_to']
print(my_spec)
```

### Pattern Inference Issues

**Problem:** Template syntax doesn't match your intent

**Solution:** Use explicit `block_operator` config for complex patterns, or check template syntax:

```yaml
# Make sure captures are clearly marked:
"{{ text }} OP {{ value }}"  # Good
"text OP value"              # Bad - no captures!
```

---

## Real-World Example: Custom Business Logic

Let's create an operator for checking if product names comply with brand guidelines:

```yaml
cascade_id: brand_compliant
description: Check if product name follows brand guidelines

inputs_schema:
  product_name: Product name to check
  brand_guidelines: Brand guidelines to check against

sql_function:
  name: brand_compliant
  operators:
    - "{{ product_name }} COMPLIES_WITH {{ brand_guidelines }}"
    - "BRAND_CHECK({{ product_name }}, {{ brand_guidelines }})"
  args:
    - name: product_name
      type: VARCHAR
    - name: brand_guidelines
      type: VARCHAR
  returns: BOOLEAN
  shape: SCALAR
  cache: true

cells:
  - name: check_compliance
    model: google/gemini-2.5-flash-lite
    instructions: |
      Check if this product name follows the brand guidelines.

      PRODUCT NAME: {{ input.product_name }}

      BRAND GUIDELINES: {{ input.brand_guidelines }}

      Evaluate:
      - Does the name align with brand voice?
      - Does it follow naming conventions?
      - Is it appropriate for the brand?

      Respond with ONLY "true" or "false".
    rules:
      max_turns: 1
```

**Usage:**
```sql
-- Find non-compliant products:
SELECT product_id, product_name
FROM products
WHERE NOT (product_name COMPLIES_WITH 'luxury premium brand voice')

-- Batch check with different guidelines:
SELECT
  category,
  product_name,
  BRAND_CHECK(product_name, brand_guidelines) as is_compliant
FROM products
JOIN brand_rules USING (category)
WHERE NOT BRAND_CHECK(product_name, brand_guidelines)
```

---

## Advanced: Negation Support

The system automatically handles `NOT` prefix:

```yaml
operators:
  - "{{ text }} MEANS {{ criterion }}"
```

**Automatically works:**
```sql
-- Affirmative:
SELECT * FROM t WHERE col MEANS 'x'
→ semantic_matches(col, 'x')

-- Negation:
SELECT * FROM t WHERE col NOT MEANS 'x'
→ NOT semantic_matches(col, 'x')
```

---

## Advanced: Context-Sensitive Operators

For operators that only work in specific SQL contexts (e.g., GROUP BY only):

```yaml
sql_function:
  name: topics
  shape: DIMENSION  # This makes it GROUP BY aware
  operators:
    - "topics({{ column }}, {{ num_topics }})"
```

The rewriter automatically generates CTEs for proper semantic bucketing.

---

## Pattern Inference Details

### What Gets Inferred

From this template:
```yaml
operators:
  - "{{ text }} ALIGNS WITH {{ narrative }}"
```

The system infers:
```python
BlockOperatorSpec(
  inline=True,
  structure=[
    {"capture": "text", "as": "expression"},
    {"keyword": "ALIGNS WITH"},
    {"capture": "narrative", "as": "string"},
  ],
  output_template="semantic_aligns({{ text }}, {{ narrative }})"
)
```

### Template Syntax

| Syntax | Meaning | Example |
|--------|---------|---------|
| `{{ name }}` | Capture any expression | Column name, identifier, `col * 2` |
| `'{{ name }}'` | Capture string literal | Forces quoted string |
| `Literal Text` | Keyword to match | `MEANS`, `ALIGNS WITH` |
| `(` `)` `,` | Structural elements | Function call syntax |

### Capture Types

**Expression Captures** (unquoted `{{ }}`):
- Matches column names: `col`, `table.col`
- Matches expressions: `UPPER(col)`, `col * 2`
- Matches identifiers: `value_123`

**String Captures** (quoted `'{{ }}'`):
- Forces string literal: `'some text'`
- Used for prompts, patterns, criteria

---

## Multiple Operators Per Cascade

A single cascade can support unlimited syntax variations:

```yaml
sql_function:
  name: semantic_matches
  operators:
    # English variations:
    - "{{ text }} MEANS {{ criterion }}"
    - "{{ text }} MATCHES {{ criterion }}"
    - "{{ text }} REPRESENTS {{ criterion }}"

    # Symbol variations:
    - "{{ text }} ~ {{ criterion }}"
    - "{{ text }} ≈ {{ criterion }}"

    # Function variations:
    - "MEANS({{ text }}, {{ criterion }})"
    - "MATCHES({{ text }}, {{ criterion }})"

    # Verbose alias:
    - "{{ text }} SEMANTICALLY_MATCHES {{ criterion }}"
```

All resolve to the same cascade - users pick whichever syntax they prefer!

---

## Operator Priority

When multiple operators could match, priority is:

1. **Block operators** (SEMANTIC_CASE...END) - Highest
2. **Dimension operators** (GROUP BY context)
3. **Multi-word infix** (ALIGNS WITH) - Longer first
4. **Single-word infix** (MEANS)
5. **Symbol infix** (~)
6. **Function calls** (SUMMARIZE(...)) - Lowest

This prevents substring matches (e.g., matching "WITH" inside "ALIGNS WITH").

---

## Performance Considerations

### Caching

**Always enable caching** for semantic operators:

```yaml
sql_function:
  cache: true
```

Semantic operations are expensive (~100-500ms per LLM call). Caching makes repeated queries near-instant.

### Model Selection

Pick the right model for the job:

```yaml
cells:
  - name: simple_check
    model: google/gemini-2.5-flash-lite  # Fast, cheap (simple tasks)

  - name: complex_analysis
    model: anthropic/claude-sonnet-4     # Slower, expensive (complex reasoning)
```

### Token Budgets

For operators processing large texts:

```yaml
cells:
  - name: analyze
    token_budget: 50000  # Auto-prune context if exceeded
    instructions: |
      Analyze: {{ input.text }}
```

---

## Common Patterns Library

### Text Classification

```yaml
operators:
  - "{{ text }} IS_CATEGORY {{ category }}"
```

Usage: `SELECT * FROM products WHERE description IS_CATEGORY 'electronics'`

### Sentiment/Emotion

```yaml
operators:
  - "{{ text }} EXPRESSES {{ emotion }}"
```

Usage: `SELECT * FROM reviews WHERE review_text EXPRESSES 'frustration'`

### Entity Extraction

```yaml
operators:
  - "{{ text }} CONTAINS_ENTITY {{ entity_type }}"
```

Usage: `SELECT * FROM docs WHERE content CONTAINS_ENTITY 'person name'`

### Temporal Reasoning

```yaml
operators:
  - "{{ text }} HAPPENED_DURING {{ timeframe }}"
```

Usage: `SELECT * FROM events WHERE description HAPPENED_DURING 'summer 2024'`

### Compliance Checking

```yaml
operators:
  - "{{ text }} VIOLATES {{ policy }}"
```

Usage: `SELECT * FROM messages WHERE content VIOLATES 'harassment policy'`

---

## BACKGROUND & ANALYZE Integration

Your custom operators work seamlessly with async execution:

```sql
-- Long-running analysis in background:
BACKGROUND
SELECT
  category,
  product_name COMPLIES_WITH brand_guidelines as compliant,
  description EXTRACTS 'key features' as features
FROM products

-- Analyze results with LLM:
ANALYZE 'What compliance issues exist?'
SELECT * FROM products
WHERE NOT (product_name COMPLIES_WITH brand_guidelines)
```

**Whitespace handling:** Newlines work everywhere thanks to token-based parsing!

---

## Migration from Hardcoded Operators

If you previously had hardcoded operators in Python code:

### Old Way (Python Code)
```python
# semantic_operators.py
def _rewrite_my_operator(query):
    pattern = r'(\w+)\s+MY_OP\s+(\'[^\']*\')'
    return re.sub(pattern, r'my_op_impl(\1, \2)', query)

# Add to rewriter pipeline:
result = _rewrite_my_operator(result)
```

### New Way (Cascade File)
```yaml
# cascades/my_operator.cascade.yaml
sql_function:
  operators:
    - "{{ col }} MY_OP {{ value }}"
```

**That's it!** Delete the Python code. Inference handles everything.

---

## FAQ

### Q: Can I use regex in operators?

**A:** No need! Template syntax is more powerful and safer. Instead of regex, use captures:

```yaml
# Don't do this:
operators:
  - "REGEX_PATTERN_HERE"

# Do this:
operators:
  - "{{ expression }} KEYWORD {{ value }}"
```

### Q: What if my pattern is too complex for templates?

**A:** Use explicit `block_operator` config for patterns with:
- Repeating elements (WHEN...THEN multiple times)
- Optional blocks in specific positions
- Context-sensitive keywords
- Complex output (CTE generation)

See SEMANTIC_CASE in `cascades/semantic_sql/case.cascade.yaml` for an example.

### Q: Do operators slow down queries?

**A:** Pattern matching adds ~1-2ms (tokenization). LLM execution is the bottleneck (~100-500ms). Use caching!

### Q: Can I override built-in operators?

**A:** Yes! Create a cascade with the same `sql_function.name`. Your version takes priority.

### Q: How do I share custom operators?

**A:** Just share the cascade file! Users drop it in `cascades/` and it works.

---

## Examples in the Wild

Check `cascades/semantic_sql/` for production-ready examples:

| Cascade | Operators | Use Case |
|---------|-----------|----------|
| `matches.cascade.yaml` | `MEANS`, `~`, `MATCHES` | Semantic filtering |
| `score.cascade.yaml` | `ABOUT`, `RELEVANCE TO` | Relevance ranking |
| `aligns.cascade.yaml` | `ALIGNS WITH` | Narrative alignment |
| `extract.cascade.yaml` | `EXTRACTS` | Entity extraction |
| `case.cascade.yaml` | `SEMANTIC_CASE...END` | Multi-way classification |
| `consensus.cascade.yaml` | `CONSENSUS(...)` | Find common themes |
| `themes.cascade.yaml` | `THEMES(...)`, `TOPICS(...)` | Theme extraction |

---

## Next Steps

1. **Browse examples:** `ls cascades/semantic_sql/*.cascade.yaml`
2. **Create your operator:** Copy a similar example
3. **Test it:** Run the cascade directly, then try in SQL
4. **Share it:** Cascade files are portable and self-contained!

**Happy operator building!** 🚀

---

## Technical Details

### How Inference Works

1. **Startup:** Registry scans `cascades/` and `traits/` for files with `sql_function`
2. **Parse:** Template parser extracts captures and keywords from `operators` field
3. **Infer:** System generates `BlockOperatorSpec` with structure and output template
4. **Load:** All specs loaded into unified rewriter
5. **Runtime:** Token-based matching applies specs in priority order

### Tokenizer Benefits

Token-based parsing means:
- ✅ Never matches inside string literals
- ✅ Never matches inside comments
- ✅ Handles newlines/tabs/any whitespace
- ✅ Respects SQL structure
- ✅ Better error messages (token position tracking)

### Files Involved

```
sql_tools/
├── operator_inference.py       # Template parser, inference engine
├── unified_operator_rewriter.py # Single entry point
├── block_operators.py          # Pattern matching logic
├── sql_directives.py           # BACKGROUND/ANALYZE parsing
└── aggregate_registry.py       # Dynamic aggregate metadata

sql_rewriter.py                 # Main pipeline (calls unified rewriter)
server/postgres_server.py       # PostgreSQL wire protocol (uses directives)
```

---

**Questions?** Check `MIGRATION_FINAL_STATUS.md` for implementation details or `CLEANUP_SUMMARY.md` for what changed.
