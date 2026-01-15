# trait:: SQL Syntax Reference

**Call any registered tool/trait directly from SQL with namespace syntax and dot accessors.**

---

## Overview

The `trait::` syntax provides a clean, familiar way to invoke tools from SQL queries. Two modes are supported:

| Mode | Syntax | Returns | Use Case |
|------|--------|---------|----------|
| **Table** | `SELECT * FROM trait::tool(args)` | Table (multiple columns/rows) | Full result exploration |
| **Scalar** | `SELECT trait::tool(arg).field` | Single value | Inline field extraction |

---

## Quick Examples

### Table Mode (Full Results)

```sql
-- Search for tables related to "bigfoot"
SELECT * FROM trait::sql_search('bigfoot sightings');

-- Get all sentiment analysis fields
SELECT * FROM trait::local_sentiment('I love this product!');
```

### Scalar Mode (Field Extraction)

```sql
-- Extract just the label from sentiment analysis
SELECT
    title,
    trait::local_sentiment(title)[0].label as sentiment
FROM articles
LIMIT 10;

-- Multiple extractions in one query
SELECT
    title,
    trait::local_sentiment(title)[0].label as sentiment,
    trait::local_sentiment(title)[0].score as confidence
FROM products;
```

---

## Syntax Reference

### Basic Syntax

```sql
-- Table mode (returns all fields as columns)
trait::tool_name(arg1, arg2, ...)

-- Scalar mode (extracts specific field)
trait::tool_name(arg1, arg2, ...).field_name
trait::tool_name(arg1, arg2, ...)[index]
trait::tool_name(arg1, arg2, ...)[index].field_name
```

### Parameter Styles

```sql
-- Positional arguments (mapped to parameter names automatically)
trait::local_sentiment('analyze this text')

-- Named arguments with :=
trait::sql_search(query := 'bigfoot', use_smart := true)

-- Named arguments with =>
trait::sql_search(query => 'UFO sightings')

-- Mixed (positional first, then named)
trait::tool('first_arg', optional_param := 'value')
```

### Accessor Chains

```sql
-- Simple field access
trait::tool(x).field_name

-- Array index
trait::tool(x)[0]

-- Chained access
trait::api_call(endpoint).data[0].user.name

-- String key access
trait::tool(x)['special-key']
```

---

## How It Works

### Table Mode Rewriting

```sql
-- You write:
SELECT * FROM trait::sql_search('bigfoot')

-- Becomes:
SELECT * FROM read_json_auto(trait('sql_search', json_object('query', 'bigfoot')))
```

The `trait()` UDF returns a temp file path containing JSON, which `read_json_auto()` reads as a table.

### Scalar Mode Rewriting

```sql
-- You write:
SELECT trait::local_sentiment(title)[0].label FROM t

-- Becomes:
SELECT json_extract_string(trait_json('local_sentiment', json_object('text', title)), '$[0].label') FROM t
```

The `trait_json()` UDF returns JSON content directly (not a file path), allowing `json_extract_string()` to extract the value.

---

## Common Patterns

### Sentiment Analysis Per Row

```sql
SELECT
    id,
    title,
    trait::local_sentiment(title)[0].label as sentiment,
    trait::local_sentiment(title)[0].score as confidence
FROM articles
WHERE trait::local_sentiment(title)[0].label = 'POSITIVE'
LIMIT 100;
```

### Search and Filter

```sql
-- Find relevant tables, extract qualified names
SELECT
    trait::sql_search('customer data')[0].qualified_name as first_match,
    trait::sql_search('customer data')[1].qualified_name as second_match;
```

### Combining with Semantic Operators

```sql
SELECT
    title,
    trait::local_sentiment(title)[0].label as sentiment
FROM articles
WHERE title MEANS 'technology news'
ORDER BY title RELEVANCE TO 'AI breakthroughs'
LIMIT 20;
```

### Using in WHERE Clause

```sql
SELECT * FROM products
WHERE trait::local_sentiment(description)[0].label = 'POSITIVE'
  AND trait::local_sentiment(description)[0].score > 0.8;
```

---

## Available Tools

Any registered trait can be called via `trait::`. Common examples:

| Tool | Description | Example |
|------|-------------|---------|
| `local_sentiment` | Sentiment analysis (local HF model) | `trait::local_sentiment(text)[0].label` |
| `local_ner` | Named entity recognition | `trait::local_ner(text)` |
| `sql_search` | Search table metadata | `trait::sql_search('topic')` |
| `smart_sql_search` | LLM-enhanced table search | `trait::smart_sql_search('find customer tables')` |
| `list_traits` | List all available traits | `SELECT * FROM trait::list_traits()` |

### Discovering Available Tools

```sql
-- List all registered traits
SELECT * FROM trait::list_traits();

-- Search for specific capabilities
SELECT * FROM trait::list_traits() WHERE name LIKE '%sentiment%';
```

---

## Result Structure

Most tools return results as an array of objects. Use `[0]` to access the first result:

```sql
-- Tool returns: [{"label": "POSITIVE", "score": 0.95}]
-- Access with:
trait::local_sentiment(text)[0].label  -- "POSITIVE"
trait::local_sentiment(text)[0].score  -- 0.95
```

### Checking Result Structure

```sql
-- View full JSON structure
SELECT trait_json('local_sentiment', json_object('text', 'I love it!'));

-- Returns: [{"label":"POSITIVE","score":0.9998}]
```

---

## Performance Considerations

### Caching

Tool results are cached by input. Repeated calls with same input are instant:

```sql
-- First call: executes model
SELECT trait::local_sentiment('test')[0].label;

-- Second call: cache hit (instant)
SELECT trait::local_sentiment('test')[0].score;
```

### Batch Processing

For large datasets, consider using `LIMIT` and batching:

```sql
-- Process in batches
SELECT id, trait::local_sentiment(text)[0].label
FROM large_table
LIMIT 100 OFFSET 0;
```

### Model Selection

Local models (like `local_sentiment`) are faster than LLM-based tools:

```sql
-- Fast (local HuggingFace model)
SELECT trait::local_sentiment(text)[0].label FROM t;

-- Slower (calls LLM API)
SELECT trait::smart_sql_search('complex query')[0].qualified_name FROM dual;
```

---

## Error Handling

### Missing Field

If you access a field that doesn't exist, you get `NULL`:

```sql
SELECT trait::tool(x)[0].nonexistent_field;  -- Returns NULL
```

### Tool Errors

Errors are returned in the result structure:

```sql
-- If tool fails:
-- Returns: [{"_trait": "tool_name", "error": "error message"}]

-- Check for errors:
SELECT trait_json('broken_tool', '{}');
```

---

## Troubleshooting

### "Malformed JSON" Error

**Cause:** Using `trait()` instead of `trait_json()` with scalar extraction.

**Solution:** The rewriter should handle this automatically. If you see this error, ensure you're using the dot accessor syntax:

```sql
-- Wrong (manually using trait with json_extract_string):
SELECT json_extract_string(trait('fn', '{}'), '$.field');  -- ERROR

-- Right (use trait:: syntax, rewriter handles it):
SELECT trait::fn()[0].field;  -- Works
```

### Empty Results

**Cause:** Tool returns empty array or `NULL`.

**Solution:** Check the raw result:

```sql
-- Debug: see what the tool actually returns
SELECT trait_json('tool_name', json_object('arg', 'value'));
```

### Tool Not Found

**Cause:** Trait not registered or misspelled.

**Solution:** List available traits:

```sql
SELECT * FROM trait::list_traits() WHERE name LIKE '%search%';
```

---

## Technical Details

### UDF Functions

| Function | Returns | Use Case |
|----------|---------|----------|
| `trait(name, args)` | File path (VARCHAR) | Table mode with `read_json_auto()` |
| `trait_json(name, args)` | JSON string (VARCHAR) | Scalar mode with `json_extract_string()` |

### Rewrite Pipeline

1. `trait::name(args)` parsed by token-based rewriter
2. Arguments mapped to parameter names via trait introspection
3. If dot accessor present: use `trait_json()` + `json_extract_string()`
4. If no accessor: use `trait()` + `read_json_auto()` wrapper

### JSON Path Syntax

The accessor chain is converted to JSON path format:

| Accessor | JSON Path |
|----------|-----------|
| `.field` | `$.field` |
| `[0]` | `$[0]` |
| `.a[0].b` | `$.a[0].b` |
| `['key']` | `$['key']` |

---

## See Also

- **Custom SQL Operators**: `docs/CUSTOM_SQL_OPERATORS.md`
- **SQL Features Reference**: `docs/SQL_FEATURES_REFERENCE.md`
- **Tools Reference**: `docs/claude/tools-reference.md`
- **Local Models**: See CLAUDE.md section on local model tools
