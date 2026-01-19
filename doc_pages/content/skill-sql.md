# skill:: SQL Syntax


Call any registered tool directly from SQL using the `skill::` namespace syntax.
  Extract scalar values with dot accessors or get full table results.
On This Page
- [Overview](#overview)
- [Table Mode](#table-mode)
- [Scalar Mode (Dot Accessor)](#scalar-mode)
- [Syntax Reference](#syntax-reference)
- [Common Patterns](#common-patterns)
- [Available Tools](#available-tools)
- [Performance](#performance)
- [Troubleshooting](#troubleshooting)


## Overview


The `skill::` syntax provides a clean way to invoke tools from SQL.
  Two modes are supported:


| Mode       | Syntax                            | Returns                       | Use Case                |
|------------|-----------------------------------|-------------------------------|-------------------------|
| **Table**  | `SELECT * FROM skill::tool(args)` | Table (multiple columns/rows) | Full result exploration |
| **Scalar** | `SELECT skill::tool(arg).field`   | Single value                  | Inline field extraction |


## Table Mode


Use table mode to get all fields from a tool result as columns:

```table mode examples
-- Search for tables related to "bigfoot"
SELECT * FROM skill::sql_search('bigfoot sightings');
-- Get all sentiment analysis fields
SELECT * FROM skill::local_sentiment('I love this product!');
-- List all available skills
SELECT * FROM skill::list_skills();
```


> **NOTE: How It Works**
>
> 
> Table mode rewrites to `read_json_auto(skill(...))`, which reads
>     the JSON result as a table with typed columns.
> 


## Scalar Mode (Dot Accessor)


Use dot accessors to extract specific fields inline without a full table scan:

```scalar mode examples
-- Extract just the label from sentiment analysis
SELECT
    title,
    skill::local_sentiment(title)[0].label AS sentiment
FROM articles
LIMIT 10;
-- Multiple extractions in one query
SELECT
    title,
    skill::local_sentiment(title)[0].label AS sentiment,
    skill::local_sentiment(title)[0].score AS confidence
FROM products;
-- Use in WHERE clause
SELECT * FROM reviews
WHERE skill::local_sentiment(body)[0].label = 'POSITIVE';
```


> **WARNING: Array Index Required**
>
> 
> Most tools return an array of results. Use `[0]` to access the first result,
>     then `.field` to extract the field.
> 


## Syntax Reference


### Parameter Styles


```parameter syntax
-- Positional arguments (mapped automatically)
skill::local_sentiment('analyze this text')
-- Named arguments with :=
skill::sql_search(query := 'bigfoot', use_smart := true)
-- Named arguments with =>
skill::sql_search(query => 'UFO sightings')
-- Mixed (positional first, then named)
skill::tool('first_arg', optional_param := 'value')
-- No arguments
skill::list_skills()
```

### Accessor Chains


| Accessor  | JSON Path  | Example                       |
|-----------|------------|-------------------------------|
| `.field`  | `$.field`  | `skill::fn(x)[0].label`       |
| `[0]`     | `$[0]`     | `skill::fn(x)[0]`             |
| `.a[0].b` | `$.a[0].b` | `skill::api(x).data[0].name`  |
| `['key']` | `$['key']` | `skill::fn(x)['special-key']` |


## Common Patterns


### Sentiment Analysis Per Row


```sentiment analysis
SELECT
    id,
    title,
    skill::local_sentiment(title)[0].label AS sentiment,
    skill::local_sentiment(title)[0].score AS confidence
FROM articles
WHERE skill::local_sentiment(title)[0].label = 'POSITIVE'
LIMIT 100;
```

### Combining with Semantic Operators


```combined with means and relevance to
SELECT
    title,
    skill::local_sentiment(title)[0].label AS sentiment
FROM articles
WHERE title MEANS 'technology news'
ORDER BY title RELEVANCE TO 'AI breakthroughs'
LIMIT 20;
```

### Mixed Table and Scalar Mode


```table + scalar in same query
-- Table mode for FROM, scalar mode for SELECT
SELECT
    r.*,
    skill::local_sentiment(r.title)[0].score AS sentiment_score
FROM skill::sql_search('customer data') r
LIMIT 5;
```

## Available Tools


Any registered skill can be called via `skill::`. Common examples:


| Tool               | Description                         | Example                                 |
|--------------------|-------------------------------------|-----------------------------------------|
| `local_sentiment`  | Sentiment analysis (local HF model) | `skill::local_sentiment(text)[0].label` |
| `local_ner`        | Named entity recognition            | `skill::local_ner(text)`                |
| `sql_search`       | Search table metadata               | `skill::sql_search('topic')`            |
| `smart_sql_search` | LLM-enhanced table search           | `skill::smart_sql_search('query')`      |
| `list_skills`      | List all available skills           | `skill::list_skills()`                  |


### Discovering Available Tools


```list all tools
-- List all registered skills
SELECT * FROM skill::list_skills();
-- Search for specific capabilities
SELECT * FROM skill::list_skills()
WHERE name LIKE '%sentiment%';
```

## Performance


### Caching


Tool results are cached by input. Repeated calls with the same input are instant:

```caching behavior
-- First call: executes model
SELECT skill::local_sentiment('test')[0].label;
-- Second call: cache hit (instant)
SELECT skill::local_sentiment('test')[0].score;
```

### Batch Processing


For large datasets, use `LIMIT` and process in batches:

```batch processing
-- Process in batches of 100
SELECT id, skill::local_sentiment(text)[0].label
FROM large_table
LIMIT 100 OFFSET 0;
```

### Local vs Remote Models


| Type              | Speed             | Example                        |
|-------------------|-------------------|--------------------------------|
| Local HuggingFace | Fast (no network) | `local_sentiment`, `local_ner` |
| LLM-based         | Slower (API call) | `smart_sql_search`             |


## Troubleshooting


### "Malformed JSON" Error


> **WARNING: Cause**
>
> 
> This happens if you manually use `skill()` with `json_extract_string()`.
>     The `skill::` syntax handles this automatically.
> 


```solution
-- Wrong: manual skill() with json_extract_string
SELECT json_extract_string(skill('fn', '{}'), '$.field');  -- ERROR
-- Right: use skill:: syntax (rewriter handles it)
SELECT skill::fn()[0].field;  -- Works!
```

### Empty Results


Debug by viewing the raw result:

```debug raw output
-- See what the tool actually returns
SELECT skill_json('tool_name', json_object('arg', 'value'));
```

### Tool Not Found


```find available tools
-- List all skills and search
SELECT * FROM skill::list_skills()
WHERE name LIKE '%search%';
```

## See Also
- [Tools (Skills)](#tools) - Tool registration and types
- [Semantic SQL](#semantic-sql) - SQL operators and UDFs
- [Built-in Operators](#operators) - Semantic operators reference
