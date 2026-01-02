# RVBBIT Semantic SQL System

## Overview

RVBBIT's Semantic SQL extends standard SQL with LLM-powered operators that enable semantic queries on text data. Instead of exact string matching, you can filter, join, aggregate, and cluster data based on *meaning*.

**Core Philosophy**: Semantic SQL operators are "prompt sugar" - readable SQL syntax that rewrites to cascade invocations. Every semantic function is backed by a RVBBIT cascade YAML file, giving you full observability, caching, customization, and the ability to override any built-in behavior.

**Built-in operators live in user-space** (`cascades/semantic_sql/`) as standard cascades. You can edit them directly, version control them, and share customizations. There's no special module-level code - SQL is truly extensible.

```sql
-- Traditional SQL: exact match
SELECT * FROM products WHERE category = 'eco'

-- Semantic SQL: meaning-based match
SELECT * FROM products WHERE description MEANS 'sustainable or eco-friendly'
```

### Quick Reference: Available Operators

| Operator | Type | Example | Cascade File |
|----------|------|---------|--------------|
| `MEANS` | Scalar | `WHERE title MEANS 'visual contact'` | `matches.cascade.yaml` |
| `ABOUT` | Scalar | `WHERE content ABOUT 'AI' > 0.7` | `score.cascade.yaml` |
| `IMPLIES` | Scalar | `WHERE premise IMPLIES conclusion` | `implies.cascade.yaml` |
| `CONTRADICTS` | Scalar | `WHERE claim CONTRADICTS evidence` | `contradicts.cascade.yaml` |
| `~` | Scalar | `WHERE company ~ vendor` | *(inline rewrite to match_pair)* |
| `SUMMARIZE` | Aggregate | `SELECT SUMMARIZE(reviews) FROM products` | `summarize.cascade.yaml` |
| `THEMES` | Aggregate | `SELECT THEMES(text, 5) FROM docs` | `themes.cascade.yaml` |
| `CLUSTER` | Aggregate | `SELECT CLUSTER(category, 8) FROM items` | `cluster.cascade.yaml` |

All cascade files are in `cascades/semantic_sql/` - edit them to customize behavior!

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
├── cascades/semantic_sql/         # Built-in semantic SQL operators (user-overrideable)
│   ├── matches.cascade.yaml       # MEANS operator backend
│   ├── score.cascade.yaml         # ABOUT/SCORE operator backend
│   ├── implies.cascade.yaml       # IMPLIES operator backend
│   ├── contradicts.cascade.yaml   # CONTRADICTS operator backend
│   ├── classify_single.cascade.yaml  # Per-row classification
│   ├── summarize.cascade.yaml     # SUMMARIZE aggregate
│   ├── themes.cascade.yaml        # THEMES/TOPICS aggregate
│   └── cluster.cascade.yaml       # CLUSTER/MEANING aggregate
│
├── traits/semantic_sql/           # User custom operators (overrides cascades/)
│   └── (your custom operators here)
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
    └── executor.py                # Cascade runner wrapper
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

Returns clean JSON array of topic strings:
```json
["Customer Service", "Product Quality", "Shipping Speed"]
```

**Note**: Returns a proper JSON array, not wrapped in an object or markdown fences.

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

Built-in operators are now standard cascades in `cascades/semantic_sql/`.
To override any operator, you have two options:

**Option 1: Edit directly** (simple, recommended for tweaking prompts/models):
```bash
# Edit the cascade file directly
vim cascades/semantic_sql/matches.cascade.yaml
```

**Option 2: Override in traits/** (preserves originals, good for major changes):
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

**Registry Priority** (later overwrites earlier):
1. `RVBBIT_ROOT/traits/` (lower priority)
2. `RVBBIT_ROOT/cascades/` (highest priority, includes semantic_sql/)

Since built-ins are now in `cascades/semantic_sql/`, they have highest priority.
Override them by editing the cascade files directly, or create copies in `traits/semantic_sql/`
with the same `sql_function.name` to override (though editing directly is simpler).

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

## PostgreSQL Wire Protocol Server

### Connection Details

**Server Implementation**: `rvbbit/server/postgres_server.py` (2771 lines)
- Entry point: `start_postgres_server(host, port, session_prefix)`
- Each client connection spawns a `ClientConnection` handler
- Thread-per-connection model with isolated DuckDB instances
- Full PostgreSQL wire protocol via `postgres_protocol.py` (946 lines)

**Connection String**:
```bash
# In-memory (ephemeral)
postgresql://localhost:15432/default
postgresql://localhost:15432/memory

# Persistent (file-backed)
postgresql://localhost:15432/my_database
# → Creates session_dbs/my_database.duckdb
```

**Catalog Compatibility**:
For SQL client introspection (DBeaver, DataGrip, Tableau), the server creates these views:
- `pg_catalog.pg_namespace` - Schema metadata
- `pg_catalog.pg_class` - Tables/views/indexes
- `pg_catalog.pg_tables` - Simplified table listing
- `pg_catalog.pg_attribute` - Column definitions
- `pg_catalog.pg_type` - Data type catalog
- `pg_catalog.pg_proc` - Functions/procedures
- `pg_catalog.pg_database` - Database list
- `pg_catalog.pg_settings` - Configuration

**Protocol Support**:
- **Simple Query Protocol**: `QUERY` → `ROW_DESCRIPTION` → `DATA_ROW` → `COMMAND_COMPLETE`
- **Extended Query Protocol**: `PARSE` → `BIND` → `EXECUTE` → `CLOSE` (for prepared statements)
- **Authentication**: Accepts any credentials (no-op auth handler)
- **SSL/TLS**: Not implemented (plain TCP only)

### Thread Safety

**Per-Connection Isolation**:
- Each client gets unique `session_id` (e.g., `pg_client_mydb_abc123`)
- Isolated DuckDB connection (not shared between clients)
- Per-connection `db_lock` (threading.Lock) for query serialization
- Persistent databases use DuckDB's internal locking for multi-client safety

**UDF Registration**: Happens once per connection on first RVBBIT query
- `register_rvbbit_udfs(conn)` - Core scalar/cascade UDFs
- `register_llm_aggregates(conn)` - Aggregate functions with arity suffixes

### Caller Context Tracking

When RVBBIT statements execute, context flows through cascade calls:

```python
from rvbbit.caller_context import set_caller_context, build_sql_metadata

caller_id = f"sql-{generate_woodland_id()}"
metadata = build_sql_metadata(
    sql_query=query,
    protocol="postgresql_wire",
    triggered_by="postgres_server",
    database=db_name,
    connection_id=session_id
)
set_caller_context(caller_id, metadata)
```

**Enables**:
- Cost tracking across nested cascade calls
- SQL Trail analytics (query log with costs, cache stats, LLM calls)
- Debugging: All logs tagged with `caller_id` in ClickHouse `all_data` table
- Observability: Link SQL query → cascade sessions → LLM calls

### SQL Trail (Query Analytics)

**Not Yet Implemented in Code** (mentioned in docs but not found in implementation):
- Would track: `sql_query_log` table with query text, costs, cache hit rates
- Would enable: Cost dashboards, slow query analysis, semantic operator usage stats
- Current alternative: Query ClickHouse `all_data` filtered by `caller_id`

```sql
-- Find all LLM calls from SQL queries
SELECT phase_name, model, cost, tokens_in, tokens_out
FROM all_data
WHERE caller_id LIKE 'sql-%'
ORDER BY created_at DESC;
```

## Built-in Semantic Functions (Cascades)

All built-in semantic SQL operators are standard cascade files in `cascades/semantic_sql/`:

| File | SQL Operator | Function | Returns | Description |
|------|--------------|----------|---------|-------------|
| `matches.cascade.yaml` | `MEANS` | `semantic_matches()` | BOOLEAN | Semantic boolean filter |
| `score.cascade.yaml` | `ABOUT` | `semantic_score()` | DOUBLE | Semantic similarity score (0-1) |
| `implies.cascade.yaml` | `IMPLIES` | `semantic_implies()` | BOOLEAN | Logical implication check |
| `contradicts.cascade.yaml` | `CONTRADICTS` | `semantic_contradicts()` | BOOLEAN | Contradiction detection |
| `classify_single.cascade.yaml` | - | `semantic_classify_single()` | VARCHAR | Single-item classification |
| `summarize.cascade.yaml` | `SUMMARIZE` | `semantic_summarize()` | VARCHAR | Text summarization |
| `themes.cascade.yaml` | `THEMES`, `TOPICS` | `semantic_themes()` | JSON | Topic extraction (array) |
| `cluster.cascade.yaml` | `MEANING`, `CLUSTER` | `semantic_cluster()` | JSON | Semantic clustering |

**All cascades use**: `google/gemini-2.5-flash-lite` by default (fast, cheap)

**Customization**: Simply edit the cascade file directly:
```bash
vim cascades/semantic_sql/matches.cascade.yaml
# Change model, prompts, output_schema, etc.
```

**Version Control**: Commit your customizations to git:
```bash
git add cascades/semantic_sql/
git commit -m "Customize MEANS operator for our domain"
```

### Creating Custom Operators

Add new semantic SQL operators by creating cascades in `cascades/semantic_sql/`:

**Example: SOUNDS_LIKE operator for phonetic matching**

```yaml
# cascades/semantic_sql/phonetic.cascade.yaml
cascade_id: semantic_phonetic

description: Phonetic similarity matching

inputs_schema:
  text: Text to evaluate
  reference: Reference text for comparison

sql_function:
  name: semantic_phonetic
  description: Check if two words sound similar (phonetically)
  args:
    - {name: text, type: VARCHAR}
    - {name: reference, type: VARCHAR}
  returns: BOOLEAN
  shape: SCALAR
  operators:
    - "{{ text }} SOUNDS_LIKE {{ reference }}"
  cache: true

cells:
  - name: check_phonetic
    model: google/gemini-2.5-flash-lite
    instructions: |
      Do these two words sound similar when spoken?

      TEXT: {{ input.text }}
      REFERENCE: {{ input.reference }}

      Return ONLY "true" or "false" (no other text).
    rules:
      max_turns: 1
    output_schema:
      type: boolean
```

**Usage:**
```sql
-- Automatically available after creating the cascade!
SELECT * FROM customers
WHERE name SOUNDS_LIKE 'Smith';
```

The registry auto-discovers cascades with `sql_function` metadata on startup.

---

## Advanced RVBBIT MAP/RUN Features

### Schema-Aware Outputs

**From**: `SQL_FEATURES_REFERENCE.md` and `sql_rewriter.py`

Beyond basic RVBBIT MAP, you can extract typed columns:

```sql
-- Explicit schema (recommended)
RVBBIT MAP 'cascade.yaml' AS (
    brand VARCHAR,
    confidence DOUBLE,
    is_luxury BOOLEAN
)
USING (SELECT product_name FROM products);

-- Inferred from cascade output_schema
RVBBIT MAP 'cascade.yaml'
USING (SELECT product_name FROM products)
WITH (infer_schema = true);
```

**How It Works** (from `sql_rewriter.py`):
1. Detects `AS (col TYPE, ...)` clause
2. Wraps query with JSON extraction:
   ```sql
   SELECT input.*,
     json_extract_string(_raw_result, '$.state.validated_output.brand') AS brand,
     CAST(json_extract_string(..., '$.confidence') AS DOUBLE) AS confidence
   FROM rvbbit_raw
   ```
3. Cascade must have `output_schema` in YAML
4. LLM output validated against schema before extraction

### EXPLAIN Support

```sql
EXPLAIN RVBBIT MAP 'cascade.yaml'
USING (SELECT * FROM table LIMIT 100);
```

**Returns** (from `sql_explain.py` - not found in codebase but mentioned in docs):
- Input row count
- Model pricing estimates (hardcoded, should query OpenRouter API)
- Cache hit rate (samples first 10 rows)
- Total cost estimate
- Rewritten SQL query

**Cost Formula**:
```
cost_per_row = (prompt_tokens × input_price + output_tokens × output_price) × phases × candidates
total_cost = cost_per_row × input_rows × (1 - cache_hit_rate)
```

### MAP DISTINCT - Deduplication

```sql
-- Dedupe all columns
RVBBIT MAP DISTINCT 'cascade.yaml'
USING (SELECT product_name, category FROM products);

-- Dedupe by specific column
RVBBIT MAP 'cascade.yaml'
USING (SELECT * FROM table)
WITH (dedupe_by='customer_id');
```

**Rewrite Strategy** (from `sql_rewriter.py`):
- `DISTINCT` → wraps USING query with `SELECT DISTINCT ...`
- `dedupe_by` → `SELECT DISTINCT ON (column) ...`
- Reduces LLM calls by processing unique values only

### Cache TTL

```sql
RVBBIT MAP 'cascade.yaml'
USING (SELECT * FROM table)
WITH (cache='1d');  -- 1 day TTL
```

**Duration Formats**: `'60s'`, `'30m'`, `'2h'`, `'1d'` or raw seconds
**Cache Storage**: In-memory Python dict (`_cascade_udf_cache` in `udf.py`)
**Cache Key**: `md5(cascade_path|inputs_json|ttl)`
**Expiry Check**: `current_time - timestamp > ttl` → cache miss, re-execute

### MAP PARALLEL (Deferred)

```sql
RVBBIT MAP PARALLEL 10 'cascade.yaml'
USING (SELECT * FROM table LIMIT 100);
```

**Status**: Syntax parsed but not implemented
**Reason**: DuckDB connections are not thread-safe
**Workaround Needed**: Connection pool with thread-local connections
**When Available**: Would use ThreadPoolExecutor for concurrent cascade execution

## Bodybuilder Integration

**Model Selection via Annotations**:

```sql
-- @ model: google/gemini-2.5-flash-lite
-- @ threshold: 0.8
SELECT * FROM products
WHERE description MEANS 'sustainable';
```

**Annotation Parser** (from `semantic_operators.py`):
- Regex: `r'--\s*@\s*(.+)'`
- Extracts key-value pairs from comments
- Injects into prompt as structured metadata
- Bodybuilder's "request mode" reads annotations and routes to appropriate model

**Annotation Scope**: Applies to next semantic operator only (not query-wide)

## Implementation File Structure

### Core Query Processing

| File | Lines | Responsibility |
|------|-------|----------------|
| `sql_rewriter.py` | ~800 | Main entry point: `rewrite_rvbbit_syntax()` |
| `sql_tools/semantic_operators.py` | 1319 | Scalar operator rewriting (MEANS, ABOUT, ~, etc.) |
| `sql_tools/llm_agg_rewriter.py` | 200+ | Aggregate function rewriting |
| `sql_tools/llm_aggregates.py` | 2283 | Aggregate UDF implementations with caching |
| `sql_tools/udf.py` | 973 | Core UDF infrastructure (`rvbbit_udf`, `rvbbit_cascade_udf`) |

### Server Infrastructure

| File | Lines | Responsibility |
|------|-------|----------------|
| `server/postgres_server.py` | 2771 | PostgreSQL wire protocol server |
| `server/postgres_protocol.py` | 946 | Protocol message encoding/decoding |

### Cascade Integration

| File | Size | Responsibility |
|------|------|----------------|
| `semantic_sql/registry.py` | ~15KB | Cascade discovery and SQL function registration |
| `semantic_sql/executor.py` | ~15KB | Cascade execution wrapper for SQL context |

### Built-in & User Cascades

**Built-in Operators** (`RVBBIT_ROOT/cascades/semantic_sql/`):
- `matches.cascade.yaml` - MEANS operator
- `score.cascade.yaml` - ABOUT operator
- `implies.cascade.yaml` - IMPLIES operator
- `contradicts.cascade.yaml` - CONTRADICTS operator
- `classify_single.cascade.yaml` - Single-item classification
- `summarize.cascade.yaml` - SUMMARIZE aggregate
- `themes.cascade.yaml` - THEMES/TOPICS aggregate
- `cluster.cascade.yaml` - CLUSTER/MEANING aggregate

**User Overrides** (`RVBBIT_ROOT/traits/semantic_sql/`):
- Optional directory for preserving original built-ins while testing changes
- Same `sql_function.name` in traits/ will override cascades/ (but editing cascades/ directly is simpler)

**Registry Priority Order** (from `registry.py`):
1. `RVBBIT_ROOT/traits/` (scanned first, lower priority)
2. `RVBBIT_ROOT/cascades/` (scanned second, overwrites traits/, highest priority)

**Simplified Architecture**: No more special `_builtin/` directory in module internals. The registry now has clean 2-tier scanning:
- `traits/` for backwards compatibility and custom user tools
- `cascades/` for everything else (including built-in operators in `cascades/semantic_sql/`)

This makes the system more maintainable and user-friendly - built-ins are just regular cascades.

## Recent Improvements (2026-01-02)

✅ **Built-in cascades moved to user-space**:
- Migrated from `rvbbit/semantic_sql/_builtin/` to `cascades/semantic_sql/`
- Removed deprecated `_builtin/` directory entirely
- Updated registry to scan only `traits/` and `cascades/` (2-tier priority)
- All operators now fully customizable without touching module code

✅ **THEMES() return format fixed**:
- Now returns clean JSON array: `["topic1", "topic2", "topic3"]`
- Previously returned wrapped object with markdown fences
- Fixed at cascade level (no system-level hardcoding)

---

## What's Left to Complete

### Currently Broken or Incomplete

1. **RVBBIT RUN Implementation**:
   - Syntax: `RVBBIT RUN 'cascade.yaml' USING (SELECT ...)`
   - Status: Parser exists in `_rewrite_run()` but implementation incomplete
   - Issue: Should create temp table and pass to cascade, but unclear if working
   - Need to test and fix

2. **MAP PARALLEL**:
   - Syntax parsed but deferred due to DuckDB thread-safety
   - Need: Connection pooling strategy for multi-threaded execution
   - Workaround: Use `candidates` in cascade YAML for parallel model execution

3. **EXPLAIN RVBBIT MAP**:
   - Mentioned in docs (SQL_FEATURES_REFERENCE.md)
   - No `sql_explain.py` file found in codebase
   - Need: Implement cost estimation logic with model pricing lookup

4. **SQL Trail / Query Analytics**:
   - Mentioned in planning doc but no dedicated table/view found
   - Caller context tracking exists, but no `sql_query_log` table
   - Need: Create analytics views over `all_data` filtered by `caller_id LIKE 'sql-%'`

5. **Table Materialization**:
   - `WITH (as_table = 'name')` option parsed
   - Unclear if `CREATE TABLE AS RVBBIT MAP` works
   - Need to test and document

6. **GROUP BY MEANING/TOPICS**:
   - Syntax defined in `semantic_operators.py`
   - Complex rewriting logic with subqueries
   - Known issue: Edge cases with nested subqueries fail to parse
   - Need: More robust SQL parsing (consider sqlglot or sqlparse)

7. **LLM_CASE Multi-Branch Classification**:
   - Rewriter: `_rewrite_llm_case()` in `llm_agg_rewriter.py`
   - Creates `semantic_case_N()` UDF with all branches as args
   - Need: Verify it actually makes single LLM call per row (should batch conditions)

### Architecture Improvements Needed

1. **Lightweight Executor for Single-Cell Cascades**:
   - Current: All semantic functions go through full RVBBITRunner
   - Overhead: TraceNode creation, state persistence, event emission
   - Need: Fast path for simple LLM calls (bypass runner for SCALAR functions)

2. **Streaming Support**:
   - Current: Aggregates wait for full LLM response
   - UX Impact: Long delays for large summaries
   - Need: Streaming via SSE for SUMMARIZE, CONSENSUS, etc.

3. **Embedding-Based Pre-Filtering**:
   - Use case: Fuzzy JOINs on large tables
   - Strategy: Embed all values, use ANN for candidate filtering, then LLM for top-k
   - Need: Integration with embedding models (already have `RVBBIT_DEFAULT_EMBED_MODEL`)

4. **Query Optimizer**:
   - Auto-detect: Duplicate semantic predicates that can be cached
   - Auto-reorder: Cheap filters before expensive LLM calls
   - Auto-suggest: DISTINCT opportunities based on cardinality analysis

5. **Cost Budgets**:
   - SQL-level: `WITH (max_cost_dollars = 5.0)` to abort if estimate exceeds
   - Session-level: Track cumulative SQL session costs
   - Need: Real-time cost tracking and abort mechanism

### Known Bugs

1. **Double WHERE After SEMANTIC JOIN**:
   - Issue: `WHERE a ~ b WHERE other_condition` (malformed SQL)
   - Fix: `_fix_double_where()` in `semantic_operators.py`
   - Status: Fixed but edge cases may remain with complex queries

2. **Annotation Scope Too Narrow**:
   - Issue: `-- @ model: X` only affects next operator
   - Need: Query-wide defaults (e.g., `-- @@ global model: X`)

3. **ROW Function Type Inference**:
   - Issue: `match_pair()` returns struct, but type not auto-detected
   - Need: Manual schema or reflection from cascade `output_schema`

4. **Complex Subqueries in GROUP BY MEANING**:
   - Parser struggles with deeply nested CTEs and subqueries
   - Need: Better SQL AST manipulation (migrate to sqlglot?)

5. **UDF Arity Explosion**:
   - DuckDB doesn't support function overloading
   - Workaround: `llm_summarize_1`, `llm_summarize_2`, `llm_summarize_3` for different arg counts
   - Ugly but functional; no clean solution without UDF API changes

### Documentation Gaps

1. **No SQL client setup guide** - How to connect from DBeaver, DataGrip, psql, configure connection strings
2. ~~**No cascade authoring guide for SQL functions**~~ - ✅ Added custom operator example above
3. **No performance tuning guide** - LIMIT best practices, cache strategies, cost control, semantic JOIN warnings
4. **No security/auth docs** - Currently accepts any connection (fine for local dev, bad for production)
5. **No operator rewriting debug guide** - How to inspect rewritten SQL, debug annotation parsing

### Future Enhancements

1. **Multi-Modal Semantic Operators**:
   - `WHERE image_col DEPICTS 'sunset'`
   - `WHERE document_col MENTIONS 'quarterly earnings'`
   - Need: Multi-modal LLM integration (GPT-4V, Gemini Vision)

2. ~~**User-Defined Operators**~~ - ✅ **Already implemented!**
   - Users can define new operators purely in YAML (see "Creating Custom Operators" section)
   - Just create a cascade with `sql_function` metadata in `cascades/semantic_sql/`
   - Registry auto-discovers on startup - no Python code needed
   - Example: SOUNDS_LIKE, SIMILAR_TO, TRANSLATES_TO, etc.

3. **Incremental Aggregation**:
   - For collections > 1000 items, batch process and merge
   - SUMMARIZE in chunks, then meta-summarize
   - CLUSTER via hierarchical clustering

4. **Distributed Execution**:
   - For massive tables, shard across workers
   - Each worker processes subset, results merged
   - Need: Celery/RQ integration or Ray

5. **Query Result Caching**:
   - Cache full query results (not just UDF calls)
   - Invalidation: Time-based or on table changes
   - Need: DuckDB query fingerprinting

### Testing Needs

1. **Integration Tests**:
   - End-to-end: Connect via psql, run semantic query, verify results
   - Catalog queries: Test DBeaver/DataGrip introspection
   - Multi-client: Concurrent connections with persistent DB

2. **Rewriter Tests**:
   - Expand `tests/test_sql_rewriter.py` with edge cases
   - Test all operator combinations
   - Test annotation parsing and injection

3. **Cache Tests**:
   - Verify cache hits/misses are logged correctly
   - Test TTL expiry logic
   - Test cache key collision resistance

4. **Performance Benchmarks**:
   - Measure: Rewriter overhead, UDF call latency, cache speedup
   - Compare: With vs without DISTINCT, with vs without cache
   - Baseline: Pure DuckDB vs semantic SQL

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
