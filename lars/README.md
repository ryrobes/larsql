# LARS - AI That Speaks SQL

[![PyPI version](https://badge.fury.io/py/larsql.svg)](https://badge.fury.io/py/larsql)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: O'SASSY](https://img.shields.io/badge/license-O'SASSY%20(basically%20MIT)-8A2BE2)](https://osaasy.dev/)
[![Docs](https://img.shields.io/badge/docs-larsql.com-cyan)](https://larsql.com/)

**Your team knows SQL. Why learn Python for AI?**

**Add AI operators directly to your SQL queries** — from your existing SQL client, on your existing databases.

```sql
SELECT * FROM support_tickets
WHERE description MEANS 'urgent customer issue';
```

That's it. No notebooks. No orchestration code. No vector database to provision.
Just SQL with semantic understanding (and a declarative workflow engine underneath).
Express intent, not patterns — especially when you don't know what you're looking for.

- **Use your existing SQL client**: PostgreSQL wire protocol (`lars serve sql`)
- **Your data never moves**: DuckDB federation across Postgres/MySQL/BigQuery/Snowflake/S3/files
- **Cached + cost-attributed**: query LLM calls via `all_data` / `sql_query_log`
- **Optional Studio UI**: inspect runs, takes, costs, and "what the model saw" (not required)

## One line. That's all it takes.

**Before:** Regex, LIKE patterns, and brittle keyword matching.

```sql
SELECT * FROM tickets
WHERE description LIKE '%urgent%'
   OR description LIKE '%critical%'
   OR description LIKE '%asap%'
   -- still misses "need this fixed immediately"
```

**After:** One line that understands meaning.

```sql
SELECT * FROM tickets
WHERE description MEANS 'urgent customer issue'
```

## What Can You Do?

```sql
-- Filter by meaning, not keywords
SELECT * FROM products
WHERE description MEANS 'eco-friendly'

-- Score relevance (0.0 to 1.0)
SELECT title, description ABOUT 'sustainability' AS relevance
FROM reports
ORDER BY relevance DESC

-- Semantic deduplication
SELECT SEMANTIC DISTINCT company_name FROM leads

-- Find contradictions (compliance, fact-checking)
SELECT * FROM disclosures
WHERE statement CONTRADICTS 'no material changes'

-- Summarize groups
SELECT category, SUMMARIZE(reviews) AS summary
FROM feedback
GROUP BY category

-- Group by auto-discovered topics
SELECT TOPICS(title, 5) AS topic, COUNT(*) AS count
FROM articles
GROUP BY topic

-- Vector similarity search
SELECT * FROM docs
WHERE title SIMILAR_TO 'quarterly earnings report'
LIMIT 10

-- Ask arbitrary questions
SELECT
  product_name,
  ASK('Is this suitable for children? yes/no', description) AS kid_friendly
FROM products
```

**50+ built-in operators** for filtering, logic, transformation, aggregation, data quality, parsing, and more.

## Quick Start

```bash
# Install
pip install larsql

# Set your LLM API key (OpenRouter, or see docs for others)
export OPENROUTER_API_KEY=sk-or-v1-...

# Start the SQL server (PostgreSQL wire protocol)
lars serve sql --port 15432

# Connect with any SQL client
psql postgresql://localhost:15432/default
```

That's it. Run semantic queries from DBeaver, DataGrip, psql, Tableau, or any PostgreSQL client.
For a full end-to-end setup (ClickHouse + sample data + Studio UI), see the [Quickstart Guide](https://larsql.com/docs.html#quickstart).

<details>
<summary>Screenshot: DataGrip connected over pgwire</summary>

[![DataGrip querying LARS via PostgreSQL wire protocol](gh_jpg/datagrip.jpg)](gh_jpg/datagrip.jpg)
</details>

## How It Works

LARS uses **query rewriting** - your semantic SQL is transformed into standard SQL with UDF calls that execute LLM operations. Your database stays untouched.

```
WHERE description MEANS 'urgent'
         ↓
WHERE semantic_matches('urgent', description)
         ↓
UDF runs LLM → returns true/false
```

Results are **cached** - same query on same data costs zero after the first run.

Every semantic UDF call is also logged (model, tokens, cost, duration) into queryable "magic tables":

```sql
SELECT session_id, cell_name, model, cost, duration_ms
FROM all_data
WHERE is_sql_udf = true
ORDER BY timestamp DESC
LIMIT 20;
```

<details>
<summary>Screenshot: costs + context (optional Studio UI)</summary>

[![Studio showing context inspector, query logs, takes, and cost analytics](gh_jpg/gh-image1.jpg)](gh_jpg/gh-image1.jpg)
</details>

Every semantic operator is backed by a cascade file under `cascades/semantic_sql/` - edit YAML to change behavior or create your own operator.
If you want a visual view of the same execution data, Studio is a UI over these logs (optional).

## Wait, it gets weirder.

Semantic SQL is just the beginning. Under the hood, LARS is a **declarative agent framework** for building sophisticated LLM workflows.

### The Problem It Solves

Every LLM project eventually becomes this:

```python
for attempt in range(max_retries):
    try:
        result = llm.call(prompt)
        if validate(result):
            return result
        prompt += f"\nError: {validation.error}. Try again."
    except JSONDecodeError as e:
        prompt += f"\nFailed to parse: {e}"
# 47 lines later... still doesn't work reliably
```

### The LARS Solution

**Run multiple attempts in parallel. Filter errors naturally. Pick the best.**

```yaml
- name: generate_analysis
  instructions: "Analyze the sales data..."
  takes:
    factor: 3  # Run 3 times in parallel
    evaluator_instructions: "Pick the most thorough analysis"
```

Instead of serial retries hoping one succeeds, run N attempts simultaneously and select the winner. Same cost, faster execution, higher quality output.

### Declarative Workflows (Cascades)

Define multi-step agent workflows in YAML:

```yaml
cascade_id: analyze_data
cells:
  - name: query_data
    tool: sql_data
    tool_inputs:
      query: "SELECT * FROM sales WHERE date > '2024-01-01'"

  - name: analyze
    instructions: |
      Analyze this sales data: {{ outputs.query_data }}
      Create visualizations and summarize key trends.
    skills:
      - create_chart
      - smart_sql_run
    takes:
      factor: 3
      evaluator_instructions: "Pick the most insightful analysis"
    handoffs: [review]

  - name: review
    instructions: "Summarize the findings"
    context:
      from: [analyze]
```

### Key Concepts

| Concept | What It Does |
|---------|--------------|
| **Cascades** | Declarative YAML workflows |
| **Cells** | Execution stages (LLM, deterministic, or human-in-the-loop) |
| **Takes** | Parallel execution → filter errors → pick best |
| **Reforge** | Iterative refinement of winning output |
| **Wards** | Validation barriers (blocking, retry, advisory) |
| **Skills** | Tools available to agents (are also FULL multi-cell cascades!) |

## Database Support

LARS connects to your existing databases:

- **DuckDB** (default, in-memory or file)
- **PostgreSQL**, **MySQL**, **ClickHouse**
- **BigQuery**, **Snowflake**
- **S3**, **Azure**, **GCS** (Parquet, CSV, JSON)

Your data stays where it is. LARS queries it federated-style. Join across DB boundaries.

## LLM Providers

Works with any LLM via [LiteLLM](https://docs.litellm.ai/):

- **OpenRouter** (default) - access to 200+ models, excellently granular cost tracking
- **OpenAI**, **Anthropic**, **Google**
- **Ollama** (local & remote models, zero cost)
- **Azure OpenAI**, **AWS Bedrock**, **Vertex AI**

## Installation Options

```bash
# Basic
pip install larsql

# With browser automation (Playwright)
pip install larsql[browser]

# With local models (HuggingFace)
pip install larsql[local-models]

# Everything
pip install larsql[all]
```

## Running Cascades

```bash
# Run a workflow
lars run cascades/example.yaml --input '{"task": "analyze sales data"}'

# With model override
lars run cascades/example.yaml --model "anthropic/claude-sonnet-4"
```

## Studio Web UI (Optional)

```bash
# Launch the visual interface
lars serve studio

# Access at http://localhost:5050
# - SQL IDE with semantic operators
# - Cascade runner (incl. takes + winners)
# - Context inspector ("what the model saw")
# - Cost explorer (by query/cascade/model)
```

<details>
<summary>Screenshots: Studio overview</summary>

[![Studio overview screenshots](gh_jpg/gh-image2.jpg)](gh_jpg/gh-image2.jpg)
</details>

## Documentation

**Full documentation at [larsql.com](https://larsql.com/)**

- [Docs hub](https://larsql.com/docs.html) - Full reference

- [Quickstart Guide](https://larsql.com/docs.html#quickstart) - Get running in 10 minutes
- [Studio Web UI](https://larsql.com/docs.html#quickstart#studio) - Optional UI for debugging cost/context/takes
- [Semantic SQL](https://larsql.com/docs.html#semantic-sql) - Query rewriting, caching, annotations, observability
- [Built-in Operators](https://larsql.com/docs.html#operators) - All 50+ operators
- [Vector Search & Embedding](https://larsql.com/docs.html#embedding) - SIMILAR_TO, LARS EMBED, hybrid search
- [Cascade DSL](https://larsql.com/docs.html#cascade-dsl) - Workflow configuration
- [Takes & Evaluation](https://larsql.com/docs.html#candidates) - Parallel execution patterns
- [SQL Connections](https://larsql.com/docs.html#sql-connections) - Connect 18+ data sources via DuckDB
- [AI Providers](https://larsql.com/docs.html#providers) - OpenRouter, Vertex AI, Bedrock, Azure, Ollama
- [Tools Reference](https://larsql.com/docs.html#tools) - Available skills & integrations

## Example: Create Your Own Operator

Any cascade can become a SQL operator. No Python required.

```yaml
# cascades/semantic_sql/sentiment_score.cascade.yaml
cascade_id: sentiment_score
sql_function:
  name: SENTIMENT_SCORE
  operators:
    - "SENTIMENT_SCORE({{ text }})"
  returns: DOUBLE
  shape: SCALAR
cells:
  - name: score
    model: google/gemini-2.5-flash-lite
    instructions: |
      Rate the sentiment of this text from -1.0 to 1.0.
      TEXT: {{ input.text }}
      Return only the number.
```

Worried about the output? Me too. Run validations or multiple takes (on multiple models), all within a SQL call.

Now use it:

```sql
SELECT product_id, AVG(SENTIMENT_SCORE(review)) AS sentiment
FROM reviews
GROUP BY product_id
HAVING sentiment < -0.3
```

## Contributing

Issues welcome at [github.com/ryrobes/larsql](https://github.com/ryrobes/larsql)

## License

[O'SASSY License](https://osaasy.dev/) (basically MIT)
