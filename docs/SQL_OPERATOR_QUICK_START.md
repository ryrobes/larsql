# Custom SQL Operators - Quick Start

**One-page guide to creating custom semantic SQL operators.**

---

## Minimal Working Example

**File:** `cascades/my_ops/check_toxic.cascade.yaml`

```yaml
cascade_id: is_toxic
sql_function:
  name: is_toxic
  operators:
    - "{{ text }} IS_TOXIC"
    - "IS_TOXIC({{ text }})"
  args:
    - name: text
      type: VARCHAR
  returns: BOOLEAN
  cache: true

cells:
  - name: check
    model: google/gemini-2.5-flash-lite
    instructions: |
      Is this text toxic, offensive, or inappropriate?
      TEXT: {{ input.text }}
      Answer: true or false
    rules:
      max_turns: 1
```

**Usage:**
```sql
SELECT * FROM comments WHERE content IS_TOXIC
SELECT username, IS_TOXIC(comment) FROM user_posts
```

**That's it!** No Python code. Drop file in `cascades/`, restart SQL server, use it.

---

## Common Patterns

### Binary Check (true/false)

```yaml
operators:
  - "{{ text }} CONTAINS_SENSITIVE_INFO"
returns: BOOLEAN
```

### Scoring (0.0-1.0)

```yaml
operators:
  - "{{ text }} RELEVANCE_TO {{ topic }}"
returns: DOUBLE
```

### Extraction (pull out entities)

```yaml
operators:
  - "{{ text }} EXTRACT_EMAIL"
returns: VARCHAR
```

### Classification (multi-category)

```yaml
operators:
  - "{{ text }} CLASSIFY_AS {{ categories }}"
returns: VARCHAR
```

### Aggregation (GROUP BY)

```yaml
shape: AGGREGATE
operators:
  - "COMMON_THEMES({{ texts }})"
returns: VARCHAR
```

---

## Template Syntax Reference

| Template | SQL Example | What It Matches |
|----------|-------------|-----------------|
| `{{ a }} OP {{ b }}` | `col OP 'value'` | Infix operator |
| `{{ a }} WORD1 WORD2 {{ b }}` | `col ALIGNS WITH 'x'` | Multi-word infix |
| `{{ a }} ~ {{ b }}` | `a ~ b` | Symbol operator |
| `FUNC({{ a }})` | `FUNC(col)` | Function 1-arg |
| `FUNC({{ a }}, {{ b }})` | `FUNC(col, 'x')` | Function 2-arg |
| `FUNC({{ a }}, '{{ b }}')` | `FUNC(col, 'x')` | Forced string arg |

---

## Five-Minute Checklist

1. **Create cascade file** in `cascades/` or `traits/`
2. **Add `sql_function` config** with `operators` field
3. **Define `args`** (what the cascade receives)
4. **Set `returns`** type (BOOLEAN, VARCHAR, DOUBLE, JSON)
5. **Write `cells`** with LLM logic
6. **Restart SQL server** (loads new cascades)
7. **Use in SQL!**

---

## Multiple Syntaxes (All Equivalent)

```yaml
operators:
  - "{{ text }} MEANS {{ criterion }}"      # English
  - "{{ text }} ~ {{ criterion }}"          # Terse
  - "{{ text }} ≈ {{ criterion }}"          # Unicode
  - "MEANS({{ text }}, {{ criterion }})"    # Function
  - "MATCHES({{ text }}, {{ criterion }})"  # Alias
```

All call the same cascade. Users pick their favorite!

---

## Shape Types

| Shape | Use Case | Example |
|-------|----------|---------|
| `SCALAR` | One value → one value | `col MEANS 'x'` |
| `AGGREGATE` | Many values → one value | `SUMMARIZE(col)` in GROUP BY |
| `DIMENSION` | Semantic bucketing | `GROUP BY topics(col, 5)` |
| `ROW` | One row → multiple values | Rarely used |

---

## Common Mistakes

### ❌ Forgot to define operators
```yaml
sql_function:
  name: my_op
  # Missing operators field!
```

### ❌ No captures in template
```yaml
operators:
  - "text MY_OP value"  # Should be: "{{ text }} MY_OP {{ value }}"
```

### ❌ Wrong shape
```yaml
shape: SCALAR  # Using in GROUP BY aggregate context - should be AGGREGATE
```

### ❌ Didn't restart server
```bash
# After adding cascade:
pkill -f postgres_server  # Kill old server
lars serve sql          # Start fresh (loads new cascades)
```

---

## Test Your Operator

```bash
# 1. Test cascade directly:
lars run cascades/my_ops/is_toxic.yaml \
  --input '{"text": "you are terrible"}'

# 2. Test in SQL:
psql -h localhost -p 15432 -d mydb

# 3. Quick test:
SELECT 'test message' IS_TOXIC;

# 4. Real data:
SELECT * FROM comments WHERE content IS_TOXIC LIMIT 5;
```

---

## Performance Tips

### Enable Caching
```yaml
sql_function:
  cache: true  # Same input → instant result
```

### Choose Fast Models
```yaml
cells:
  - name: check
    model: google/gemini-2.5-flash-lite  # Fast & cheap
```

### Limit Token Usage
```yaml
cells:
  - name: analyze
    token_budget: 10000  # Auto-prune long inputs
```

---

## Real Examples

All built-in operators are just cascade files in `cascades/semantic_sql/`:

```bash
# Browse examples:
ls cascades/semantic_sql/*.cascade.yaml

# Great starting points:
- matches.cascade.yaml    # Binary matching (MEANS, ~)
- score.cascade.yaml      # Relevance scoring (ABOUT)
- extract.cascade.yaml    # Entity extraction (EXTRACTS)
- aligns.cascade.yaml     # Narrative alignment
- consensus.cascade.yaml  # Find common themes (aggregate)
```

Copy one, modify it, you're done!

---

## BACKGROUND & ANALYZE Support

Your custom operators work with async execution:

```sql
BACKGROUND
SELECT
  category,
  product_name IS_TOXIC as toxic,
  description EXTRACT_PRICE as price
FROM products

ANALYZE 'What toxic content exists?'
SELECT * FROM products WHERE product_name IS_TOXIC
```

Newlines work everywhere (token-based parsing).

---

## Full Documentation

**See:** `docs/CUSTOM_SQL_OPERATORS.md` for:
- Complete operator type reference
- Advanced block operators
- Migration from hardcoded operators
- Troubleshooting guide
- Real-world examples

**See:** `docs/TRAIT_SQL_SYNTAX.md` for:
- `trait::` namespace syntax for calling any tool from SQL
- Dot accessor syntax for scalar field extraction
- Examples with local models and search tools

---

## Summary

**Creating a custom operator:**
1. Create cascade file with `sql_function.operators`
2. Restart SQL server
3. Use it!

**No Python code. No regex. No hardcoded lists. Just YAML.** 🎉
