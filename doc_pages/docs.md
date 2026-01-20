# LARS Documentation

LARS (Language-Augmented Relational SQL) adds AI operators to SQL. Use semantic operators like `WHERE description MEANS 'urgent'` directly in your SQL queries.

## Getting Started

- [Quickstart Guide](content/quickstart.md) - Install, configure, and run your first semantic query
- [Overview](content/overview.md) - What is LARS and how it works
- [Core Concepts](content/core-concepts.md) - Cascades, cells, state, and execution flow
- [AI Providers](content/providers.md) - OpenRouter, Vertex AI, Bedrock, Azure, Ollama

## Cascade DSL

- [DSL Reference](content/cascade-dsl.md) - Cascade-level properties, cell config, Jinja2 templating
- [Cell Types](content/cell-types.md) - LLM cells, deterministic cells, HITL screens, SQL mapping
- [Validation (Wards)](content/validation.md) - Validation modes, polyglot validators, loop until
- [Context Management](content/context.md) - Intra-cell, inter-cell, and auto context
- [Auto-Context Deep Dive](content/auto-context.md) - Token savings and configuration

## Features

- [SQL Connections](content/sql-connections.md) - PostgreSQL, MySQL, BigQuery, Snowflake, S3, and more
- [Semantic SQL](content/semantic-sql.md) - Query rewriting, UDF system, annotations, caching
- [Built-in Operators](content/operators.md) - 100+ operators for filtering, logic, aggregation, and more
- [Pipeline Cascades](content/pipelines.md) - Chained transformations with CHOOSE routing
- [Vector Search & Embedding](content/embedding.md) - Create embeddings, vector search, hybrid search
- [TOON Format](content/toon-format.md) - Structured output format for LLM responses
- [Tools (Skills)](content/tools.md) - Python functions, cascade tools, declarative tools
- [Eject Command](content/eject.md) - Export and customize built-in resources
- [skill:: SQL Syntax](content/skill-sql.md) - Table mode and scalar mode tool invocation
- [Memory System](content/memory.md) - Three-tier memory, named banks, research database
- [MCP Integration](content/mcp.md) - Model Context Protocol servers
- [Signals](content/signals.md) - Inter-cascade communication
- [Triggers](content/triggers.md) - Cron, sensor, and webhook triggers
- [Watches](content/watches.md) - File and semantic watches with actions

## Semantic SQL Operators

Quick reference for the most common operators:

### Filtering
```sql
-- Semantic boolean match
SELECT * FROM tickets WHERE description MEANS 'urgent customer issue';

-- Relevance scoring (0.0-1.0)
SELECT * FROM articles WHERE content ABOUT 'machine learning' > 0.7;

-- Vector similarity
SELECT * FROM docs WHERE title SIMILAR_TO 'quarterly earnings';
```

### Logic
```sql
-- Find contradictions
SELECT * FROM reports WHERE analysis CONTRADICTS 'company expects growth';

-- Check implications
SELECT * FROM claims WHERE statement IMPLIES 'regulatory compliance';
```

### Aggregation
```sql
-- Summarize text
SELECT category, SUMMARIZE(reviews) FROM products GROUP BY category;

-- Extract themes
SELECT THEMES(feedback) FROM customer_data;

-- Sentiment analysis
SELECT SENTIMENT(comments) FROM posts;
```

### Transformation
```sql
-- Flexible prompts
SELECT ASK('Is this suitable for children? yes/no', description) FROM products;

-- Classification
SELECT CLASSIFY(text, 'spam,ham,uncertain') FROM messages;

-- Extraction
SELECT EXTRACT(resume, 'skills as array') FROM candidates;
```

## Resources

- [Competitive Landscape](content/competitive-analysis.md) - Comparison with other tools
- [GitHub Repository](https://github.com/ryrobes/larsql)
- [Home Page](https://larsql.com)
