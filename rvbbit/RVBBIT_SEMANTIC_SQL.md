# RVBBIT Semantic SQL System

## Overview

RVBBIT's Semantic SQL extends standard SQL with LLM-powered operators that enable semantic queries on text data. Instead of exact string matching, you can filter, join, aggregate, and cluster data based on *meaning*.

**Core Philosophy**: Semantic SQL operators are "prompt sugar" - readable SQL syntax that rewrites to cascade invocations. Every semantic function is backed by a RVBBIT cascade YAML file, giving you full observability, caching, customization, and the ability to override any built-in behavior.

```sql
-- Traditional SQL: exact match
SELECT * FROM products WHERE category = 'eco'

-- Semantic SQL: meaning-based match
SELECT * FROM products WHERE description MEANS 'sustainable or eco-friendly'
```

## Architecture

### Query Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           User SQL Query                                     │
│  SELECT state, SUMMARIZE(title), COUNT(*)                                   │
│  FROM bigfoot WHERE title MEANS 'visual contact' GROUP BY state             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         sql_rewriter.py                                      │
│  Entry point: rewrite_rvbbit_syntax()                                       │
│  1. Process RVBBIT MAP/RUN statements                                       │
│  2. Delegate to semantic operators rewriter                                  │
│  3. Delegate to LLM aggregates rewriter                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌────────────────────────────────┐   ┌────────────────────────────────────────┐
│   semantic_operators.py        │   │   llm_agg_rewriter.py                   │
│   Rewrites:                    │   │   Rewrites:                             │
│   - MEANS → matches()          │   │   - SUMMARIZE() → llm_summarize_impl()  │
│   - ABOUT → score()            │   │   - THEMES() → llm_themes_impl()        │
│   - ~ → match_pair()           │   │   - SENTIMENT() → llm_sentiment_impl()  │
│   - IMPLIES → implies()        │   │   - CONSENSUS() → llm_consensus_impl()  │
│   - CONTRADICTS → contradicts()│   │   - OUTLIERS() → llm_outliers_impl()    │
│   - GROUP BY MEANING()         │   │   - DEDUPE() → llm_dedupe_impl()        │
│   - GROUP BY TOPICS()          │   │   - CLUSTER() → llm_cluster_impl()      │
│   - SEMANTIC DISTINCT          │   │   - LLM_CASE → semantic_case_N()        │
│   - SEMANTIC JOIN              │   │                                         │
│   - RELEVANCE TO               │   │                                         │
└────────────────────────────────┘   └────────────────────────────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Rewritten SQL Query                                  │
│  SELECT state, llm_summarize_1(LIST(title)::VARCHAR), COUNT(*)              │
│  FROM bigfoot WHERE matches('visual contact', title) GROUP BY state         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DuckDB Execution                                     │
│  UDFs registered:                                                            │
│  - matches(), score(), implies(), contradicts(), match_pair()               │
│  - llm_summarize_1(), llm_themes_2(), llm_consensus_1(), etc.               │
│  - semantic_case_N() for multi-branch classification                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Cascade Execution (via Registry)                         │
│  1. UDF calls _execute_cascade("semantic_xyz", {args})                      │
│  2. Registry finds cascade at traits/semantic_sql/xyz.cascade.yaml          │
│  3. RVBBITRunner executes cascade (LLM call with prompt)                    │
│  4. Result cached for future identical calls                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Three Function Shapes

Semantic SQL functions come in three shapes:

| Shape | Description | Example |
|-------|-------------|---------|
| **SCALAR** | Per-row evaluation | `WHERE title MEANS 'x'` |
| **ROW** | Multi-column per-row | `match_pair(a, b)` returning struct |
| **AGGREGATE** | Collection → single value | `SUMMARIZE(texts) GROUP BY category` |

### File Organization

```
RVBBIT_ROOT/
├── traits/semantic_sql/           # User-facing cascade definitions
│   ├── matches.cascade.yaml       # MEANS operator backend
│   ├── score.cascade.yaml         # ABOUT/SCORE operator backend
│   ├── implies.cascade.yaml       # IMPLIES operator backend
│   ├── contradicts.cascade.yaml   # CONTRADICTS operator backend
│   ├── classify_single.cascade.yaml  # Per-row classification
│   ├── summarize.cascade.yaml     # SUMMARIZE aggregate
│   ├── themes.cascade.yaml        # THEMES/TOPICS aggregate
│   ├── sentiment.cascade.yaml     # SENTIMENT aggregate
│   ├── consensus.cascade.yaml     # CONSENSUS aggregate
│   ├── outliers.cascade.yaml      # OUTLIERS aggregate
│   ├── dedupe.cascade.yaml        # DEDUPE aggregate
│   ├── cluster.cascade.yaml       # CLUSTER/MEANING aggregate
│   └── classify.cascade.yaml      # Collection CLASSIFY aggregate
│
rvbbit/
├── sql_rewriter.py                # Main entry point for query rewriting
├── sql_tools/
│   ├── semantic_operators.py      # Scalar operator rewriting (MEANS, ABOUT, etc.)
│   ├── llm_agg_rewriter.py        # Aggregate function rewriting
│   ├── llm_aggregates.py          # Aggregate UDF implementations
│   ├── udf.py                     # Core UDF infrastructure + caching
│   └── ...
└── semantic_sql/
    ├── registry.py                # Cascade discovery and execution
    ├── executor.py                # Cascade runner wrapper
    └── _builtin/                  # DEPRECATED: Legacy built-in cascades
```

## Operator Reference

### Scalar Operators (Per-Row)

#### MEANS - Semantic Boolean Filter

```sql
-- Basic usage
SELECT * FROM products WHERE description MEANS 'sustainable'

-- Negation
SELECT * FROM products WHERE description NOT MEANS 'contains plastic'

-- Rewrites to: matches('sustainable', description)
```

The LLM returns `true` or `false` based on whether the text semantically matches the criteria.

#### ABOUT - Score Threshold Filter

```sql
-- Default threshold (0.5)
SELECT * FROM articles WHERE content ABOUT 'machine learning'

-- Custom threshold
SELECT * FROM articles WHERE content ABOUT 'data science' > 0.7

-- Negation (exclude matches above threshold)
SELECT * FROM articles WHERE content NOT ABOUT 'politics' > 0.3

-- Rewrites to: score('machine learning', content) > 0.5
```

Returns a semantic similarity score from 0.0 to 1.0.

#### IMPLIES - Logical Implication Check

```sql
-- Column implies literal
SELECT * FROM bigfoot WHERE observed IMPLIES 'witness saw a creature'

-- Column implies column
SELECT * FROM claims WHERE premise IMPLIES conclusion

-- Rewrites to: implies(observed, 'witness saw a creature')
```

Returns `true` if the first statement logically implies the second.

#### CONTRADICTS - Contradiction Detection

```sql
-- Column contradicts literal
SELECT * FROM reviews WHERE claim CONTRADICTS 'product is reliable'

-- Column vs column
SELECT * FROM statements WHERE statement_a CONTRADICTS statement_b

-- Rewrites to: contradicts(claim, 'product is reliable')
```

Returns `true` if the two statements are contradictory.

#### ~ (Tilde) - Semantic Equality

```sql
-- Basic: same entity check
SELECT * FROM customers c, suppliers s
WHERE c.company ~ s.vendor

-- With explicit relationship
SELECT * FROM t1, t2
WHERE t1.name ~ t2.name AS 'same person'

-- Negation: different entities
SELECT * FROM products p1, products p2
WHERE p1.name !~ p2.name

-- Rewrites to: match_pair(c.company, s.vendor, 'same entity')
```

Perfect for fuzzy JOINs where entity names vary.

#### RELEVANCE TO - Semantic Ordering

```sql
-- Most relevant first (default)
SELECT * FROM documents
ORDER BY content RELEVANCE TO 'quarterly earnings'

-- Explicit direction
ORDER BY content RELEVANCE TO 'financial reports' ASC

-- Inverse: find least relevant (outliers)
ORDER BY content NOT RELEVANCE TO 'common patterns'

-- Rewrites to: ORDER BY score('quarterly earnings', content) DESC
```

### LLM_CASE - Multi-Branch Classification

Evaluate multiple semantic conditions in a single LLM call:

```sql
SELECT
  product_name,
  LLM_CASE description
    WHEN SEMANTIC 'mentions sustainability' THEN 'eco'
    WHEN SEMANTIC 'mentions performance' THEN 'performance'
    WHEN SEMANTIC 'mentions luxury' THEN 'premium'
    ELSE 'standard'
  END as segment
FROM products;
```

Much more efficient than chained `CASE WHEN matches(...) THEN` since it makes one LLM call per row evaluating all conditions together.

**Rewrites to:**
```sql
semantic_case_8(description,
  'mentions sustainability', 'eco',
  'mentions performance', 'performance',
  'mentions luxury', 'premium',
  'standard'
)
```

### Aggregate Functions

All aggregates collect values via `LIST()`, convert to JSON, and process through a cascade.

#### SUMMARIZE - Text Summarization

```sql
-- Basic: summarize all texts in group
SELECT category, SUMMARIZE(review_text) as summary
FROM reviews GROUP BY category;

-- With custom prompt
SELECT state, SUMMARIZE(observed, 'Focus on creature descriptions:') as summary
FROM bigfoot GROUP BY state;
```

Returns a concise summary of all texts in the group.

#### THEMES / TOPICS - Topic Extraction

```sql
-- Extract 5 themes (default)
SELECT category, THEMES(review_text) as topics
FROM reviews GROUP BY category;

-- Custom count
SELECT category, TOPICS(comments, 3) as main_topics
FROM feedback GROUP BY category;
```

Returns JSON array of extracted topic strings.

#### SENTIMENT - Collective Sentiment Score

```sql
SELECT product_id, COUNT(*), SENTIMENT(review_text) as mood
FROM reviews GROUP BY product_id ORDER BY mood DESC;
```

Returns float from -1.0 (very negative) to 1.0 (very positive).

#### CLASSIFY - Collection Classification

```sql
SELECT product_id,
  CLASSIFY(review_text, 'positive,negative,mixed') as overall_sentiment
FROM reviews GROUP BY product_id;
```

Classifies the entire collection into one of the provided categories.

#### CONSENSUS - Find Common Ground

```sql
SELECT state, CONSENSUS(observed) as common_patterns
FROM bigfoot GROUP BY state;
```

Returns what most items agree on or have in common.

#### OUTLIERS - Find Unusual Items

```sql
-- Basic: find 5 outliers
SELECT OUTLIERS(observed, 3) as unusual_sightings FROM bigfoot;

-- With criteria
SELECT state, OUTLIERS(observed, 5, 'scientifically implausible')
FROM bigfoot GROUP BY state;
```

Returns JSON array of `{item, reason}` objects.

#### DEDUPE - Semantic Deduplication

```sql
-- Basic: same entity
SELECT DEDUPE(company_name) FROM suppliers;
-- Returns: ["IBM", "Microsoft"] not ["IBM", "IBM Corp", "International Business Machines"]

-- With criteria
SELECT DEDUPE(product_name, 'same product') FROM catalog;
```

Returns JSON array of unique representatives.

#### CLUSTER - Semantic Clustering

```sql
-- Basic clustering
SELECT CLUSTER(category, 5, 'by product type') FROM products;
```

Returns JSON mapping each value to its cluster label.

### Semantic GROUP BY

#### GROUP BY MEANING() - Cluster-Based Grouping

```sql
-- Auto-determine clusters
SELECT category, COUNT(*) FROM products
GROUP BY MEANING(category);

-- Fixed cluster count
SELECT category, COUNT(*) FROM products
GROUP BY MEANING(category, 5);

-- With semantic hint
SELECT county, COUNT(*) FROM bigfoot
GROUP BY MEANING(county, 8, 'geographic region');
```

Groups rows by semantic similarity rather than exact value match.

#### GROUP BY TOPICS() - Topic-Based Grouping

```sql
-- Extract N topics, classify each row into one
SELECT title, COUNT(*) FROM articles
GROUP BY TOPICS(content, 3);
```

First extracts topics from all values, then classifies each row into one topic, then groups.

### SEMANTIC DISTINCT

```sql
-- Deduplicate by semantic similarity
SELECT SEMANTIC DISTINCT company FROM suppliers;

-- With explicit criteria
SELECT SEMANTIC DISTINCT company AS 'same business' FROM suppliers;
```

### SEMANTIC JOIN

```sql
-- Fuzzy join on semantic similarity
SELECT c.*, s.*
FROM customers c
SEMANTIC JOIN suppliers s ON c.company ~ s.vendor
LIMIT 100;

-- Rewrites to:
SELECT c.*, s.*
FROM customers c
CROSS JOIN suppliers s
WHERE match_pair(c.company, s.vendor, 'same entity')
LIMIT 100;
```

**WARNING**: Always use LIMIT with SEMANTIC JOIN to avoid N×M LLM calls.

## Annotation Syntax

Use `-- @` comments to provide model hints and customization without cluttering function arguments:

```sql
-- @ use a fast and cheap model
-- @ threshold: 0.7
SELECT * FROM products
WHERE description MEANS 'sustainable';

-- Per-function annotations
SELECT
  category,
  -- @ Focus on complaints
  SUMMARIZE(negative_reviews) as complaints,
  -- @ Focus on praise
  SUMMARIZE(positive_reviews) as praise
FROM reviews GROUP BY category;

-- Model selection
-- @ model: google/gemini-2.5-flash-lite
SUMMARIZE(review_text) as quick_summary
```

Annotations are parsed and injected into the prompt, allowing the LLM router (bodybuilder) to pick appropriate models.

## Cascade Definition

Every semantic function is backed by a cascade YAML file. The `sql_function` key makes a cascade SQL-callable:

```yaml
# traits/semantic_sql/consensus.cascade.yaml
cascade_id: semantic_consensus

description: |
  Find consensus or common ground among a collection of texts.

inputs_schema:
  texts: JSON array of texts to analyze
  prompt: Optional custom prompt

sql_function:
  name: semantic_consensus           # Function name in SQL
  description: Finds common ground or consensus among texts
  args:
    - name: texts
      type: JSON
    - name: prompt
      type: VARCHAR
      optional: true
  returns: VARCHAR
  shape: AGGREGATE                   # SCALAR, ROW, or AGGREGATE
  context_arg: texts                 # Which arg provides context
  operators:                         # SQL syntax patterns
    - "CONSENSUS({{ texts }})"
    - "CONSENSUS({{ texts }}, '{{ prompt }}')"
  cache: true                        # Enable result caching

cells:
  - name: find_consensus
    model: google/gemini-2.5-flash-lite
    instructions: |
      Analyze these texts and identify what they have in common.

      TEXTS:
      {{ input.texts }}

      {% if input.prompt %}
      FOCUS ON: {{ input.prompt }}
      {% endif %}

      Return a concise summary of what most items agree on.
    rules:
      max_turns: 1
```

### Function Shapes

- **SCALAR**: Returns one value per input row (e.g., `matches(criteria, text)`)
- **ROW**: Returns multiple columns per row (e.g., `match_pair` returning struct)
- **AGGREGATE**: Takes a collection, returns single value (e.g., `SUMMARIZE(LIST(texts))`)

### Customizing Built-in Functions

To override a built-in function, create your own cascade at `RVBBIT_ROOT/traits/semantic_sql/`:

```yaml
# traits/semantic_sql/matches.cascade.yaml
cascade_id: semantic_matches

sql_function:
  name: semantic_matches
  # ... your custom definition

cells:
  - name: check_match
    model: your-preferred/model    # Use your own model
    instructions: |
      Your custom prompt logic here...
```

The registry prioritizes:
1. `RVBBIT_ROOT/cascades/` (highest)
2. `RVBBIT_ROOT/traits/` (medium)
3. Built-in `_builtin/` (deprecated, lowest)

## Caching

Semantic SQL functions cache results aggressively:

- **Cache key**: Function name + arguments (hashed)
- **Cache location**: In-memory TTL cache (configurable)
- **Cache hits**: Logged for observability

```python
# Manually clear cache if needed
from rvbbit.sql_tools.udf import clear_cache
clear_cache()
```

## Performance Tips

### 1. Always LIMIT Fuzzy JOINs

```sql
-- DANGEROUS: 1000 × 1000 = 1,000,000 LLM calls
SELECT * FROM big_table1, big_table2
WHERE match_pair(t1.name, t2.name, 'same');

-- SAFE: Evaluate at most 100 pairs
SELECT * FROM big_table1, big_table2
WHERE match_pair(t1.name, t2.name, 'same')
LIMIT 100;
```

### 2. Use Blocking for Large Tables

Pre-filter with cheap conditions before semantic matching:

```sql
-- First cheap filter, then LLM match
SELECT c.*, s.*
FROM customers c, suppliers s
WHERE LEFT(c.company_name, 2) = LEFT(s.vendor_name, 2)  -- Blocking
  AND match_pair(c.company_name, s.vendor_name, 'same company')
LIMIT 100;
```

### 3. Use LLM_CASE for Multi-Branch

Instead of multiple `matches()` calls:

```sql
-- SLOW: 3 LLM calls per row
SELECT
  CASE
    WHEN matches('sustainability', description) THEN 'eco'
    WHEN matches('performance', description) THEN 'perf'
    WHEN matches('luxury', description) THEN 'premium'
  END as segment
FROM products;

-- FAST: 1 LLM call per row
SELECT
  LLM_CASE description
    WHEN SEMANTIC 'sustainability' THEN 'eco'
    WHEN SEMANTIC 'performance' THEN 'perf'
    WHEN SEMANTIC 'luxury' THEN 'premium'
  END as segment
FROM products;
```

### 4. Sample Large Collections

Aggregates automatically sample when collections are too large:

```python
# In llm_aggregates.py
if len(values) > 50:
    import random
    working_values = random.sample(values, 50)
```

## UDF Registration

Semantic SQL functions are registered as DuckDB UDFs at connection time:

```python
from rvbbit.sql_tools.llm_aggregates import register_llm_aggregates
from rvbbit.sql_tools.udf import register_rvbbit_udfs

# Register all UDFs
conn = duckdb.connect()
register_rvbbit_udfs(conn)
register_llm_aggregates(conn)
```

Functions are registered with arity suffixes (DuckDB doesn't support overloading):
- `llm_summarize_1(values)` - 1 arg
- `llm_summarize_2(values, prompt)` - 2 args
- `llm_summarize_3(values, prompt, max_items)` - 3 args

## Observability

### SQL Trail

All semantic function calls can be tracked via SQL Trail:

```sql
SELECT * FROM sql_query_log
WHERE has_semantic_ops = true
ORDER BY started_at DESC;
```

### Unified Logs

LLM calls from semantic functions are logged to `all_data`:

```sql
SELECT phase_name, model, cost, tokens_in, tokens_out
FROM all_data
WHERE caller_id = 'sql_query_xyz'
ORDER BY created_at;
```

## Example Queries

### Comprehensive Analysis

```sql
SELECT
  state,
  COUNT(*) as sightings,
  SUMMARIZE(observed) as what_happened,
  THEMES(title, 3) as main_topics,
  SENTIMENT(title) as mood,
  CONSENSUS(observed) as common_experience
FROM bigfoot
WHERE title MEANS 'visual contact with creature'
  AND observed ABOUT 'credible witness' > 0.6
GROUP BY state
HAVING COUNT(*) > 5
ORDER BY state RELEVANCE TO 'pacific northwest'
LIMIT 20;
```

### Entity Resolution

```sql
-- Find duplicate companies across tables
SELECT
  c.company_name as customer,
  s.vendor_name as supplier,
  score('same company', c.company_name || ' vs ' || s.vendor_name) as confidence
FROM customers c
SEMANTIC JOIN suppliers s ON c.company_name ~ s.vendor_name
LIMIT 100;
```

### Topic Discovery

```sql
-- Discover and count by topic
SELECT title, COUNT(*) as count
FROM articles
GROUP BY TOPICS(content, 5)
ORDER BY count DESC;
```

## What's Left to Complete

### Current Limitations

1. **Cascade execution overhead**: Full RVBBITRunner is used even for single-cell cascades. A lightweight executor for simple LLM calls would improve performance.

2. **No streaming support**: Aggregate results wait for full LLM response. Streaming would improve UX for large summaries.

3. **Limited type inference**: ROW functions that return structs need manual schema specification.

4. **No cost budgets**: No built-in way to limit total LLM spend per query.

### Future Enhancements

1. **True parallel execution**: `RVBBIT MAP PARALLEL N` syntax exists but doesn't use threading yet.

2. **Incremental aggregation**: For very large collections, process in batches and merge results.

3. **Embedding-based pre-filtering**: Use embeddings for cheap candidate filtering before LLM evaluation.

4. **Query optimization**: Automatic reordering of predicates to minimize LLM calls.

5. **Multi-modal support**: Semantic operators on image/document columns.

6. **User-defined operators**: Allow users to define new operators via YAML without Python.

### Known Issues

1. **GROUP BY MEANING/TOPICS with subqueries**: Complex nested subqueries may not parse correctly.

2. **Double WHERE after SEMANTIC JOIN**: Fixed with `_fix_double_where()` but edge cases may exist.

3. **Annotation scope**: Annotations apply to the next operator only; no way to set query-wide defaults.

## Debugging

Enable debug logging:

```python
import logging
logging.getLogger('rvbbit.sql_tools').setLevel(logging.DEBUG)
```

Inspect rewritten queries:

```python
from rvbbit.sql_rewriter import rewrite_rvbbit_syntax
original = "SELECT * FROM t WHERE x MEANS 'test'"
rewritten = rewrite_rvbbit_syntax(original)
print(rewritten)
# SELECT * FROM t WHERE matches('test', x)
```

Test cascade registration:

```python
from rvbbit.semantic_sql.registry import initialize_registry, list_sql_functions
initialize_registry(force=True)
print(list_sql_functions())
# ['semantic_matches', 'semantic_score', 'semantic_consensus', ...]
```
