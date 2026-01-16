# LARS - AI That Speaks SQL

[![PyPI version](https://badge.fury.io/py/larsql.svg)](https://badge.fury.io/py/larsql)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

LARS is a **declarative agent framework** for building long-running, iterative LLM workflows with first-class SQL integration. It bridges natural language and databases through **Semantic SQL** - extending standard SQL with LLM-powered operators.

## Features

- **Semantic SQL** - Natural language operators embedded in SQL queries
- **Declarative Workflows** - Define agent cascades in YAML/JSON
- **Multi-Database Support** - DuckDB, PostgreSQL, MySQL, ClickHouse, and more
- **PostgreSQL Wire Protocol** - Connect with any SQL client (DBeaver, psql, Tableau)
- **Built-in Tools** - Charts, artifacts, human-in-the-loop, code execution
- **Vector Search** - Semantic search with embeddings via ClickHouse or Elasticsearch

## Installation

```bash
pip install larsql
```

With optional dependencies:

```bash
# Browser automation
pip install larsql[browser]

# Local models (transformers, torch)
pip install larsql[local-models]

# Everything
pip install larsql[all]
```

## Quick Start

### 1. Set up your environment

```bash
# Set your LLM API key (OpenRouter, OpenAI, etc.)
export OPENROUTER_API_KEY=sk-or-v1-...
```

### 2. Run a cascade

```bash
# Run a workflow
lars run cascades/example.yaml --input '{"task": "analyze sales data"}'

# With model override
lars run cascades/example.yaml --model "anthropic/claude-sonnet-4"
```

### 3. Start the SQL server

```bash
# Start PostgreSQL-compatible server
lars serve sql

# Connect with any PostgreSQL client
psql -h localhost -p 5432 -U lars -d memory
```

## Semantic SQL

LARS extends SQL with semantic operators powered by LLMs:

```sql
-- Filter by meaning, not exact match
SELECT * FROM products
WHERE description MEANS 'eco-friendly'

-- Score relevance
SELECT name, description ABOUT 'sustainability' as relevance
FROM products
ORDER BY relevance DESC

-- Semantic deduplication
SELECT SEMANTIC DISTINCT product_name FROM products

-- Ask arbitrary questions
SELECT
  product_name,
  ASK('Is this suitable for children? yes/no', description) as kid_friendly
FROM products

-- Summarize groups
SELECT category, SUMMARIZE(reviews) as summary
FROM products
GROUP BY category
```

## Cascade Workflows

Define declarative agent workflows in YAML:

```yaml
cascade_id: analyze_data
inputs_schema:
  question: "The question to answer"

phases:
  - name: analyze
    instructions: |
      Analyze the data to answer: {{ input.question }}
      Use SQL to query the database and create visualizations.
    tackle:
      - smart_sql_run
      - create_chart
    handoffs:
      - summarize

  - name: summarize
    instructions: |
      Summarize the findings from the analysis.
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Cascades** | Declarative workflows with sequential phases |
| **Phases** | Steps with LLM agents and available tools |
| **Soundings** | Parallel exploration (Tree of Thought) |
| **Wards** | Validation system (blocking, retry, advisory) |
| **Echoes** | State accumulation across phases |
| **Tackle** | Tools available to a phase |

## Documentation

- [Full Documentation](https://larsql.com/)
- [GitHub Repository](https://github.com/ryrobes/larsql)

## License

MIT License - see [LICENSE](LICENSE) for details.
