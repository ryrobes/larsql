# Vector Search & Embedding


Index your data with embeddings and perform semantic similarity search.
  LARS integrates vector search directly into SQL queries.
On This Page
- [Overview](#overview)
- [Creating Embeddings](#creating)
- [Vector Search](#searching)
- [Hybrid Search](#hybrid)
- [CLI Commands](#cli)


## Overview


LARS's embedding system allows you to:
- Index text columns from any table with vector embeddings
- Search using natural language with `SIMILAR_TO` operator
- Combine vector search with traditional SQL filters
- Use hybrid search for best results


## Creating Embeddings


### Via SQL


```embed statement
-- Index a column for vector search
LARS EMBED articles.content
FROM articles
WHERE published = true;
-- With custom model and batch size
LARS EMBED documents.summary
FROM documents
WITH (
  model = 'qwen/qwen3-embedding-8b',
  batch_size = 100
);
```

### Via CLI


```cli
# Check embedding status
lars embed status

# Run embedding job
lars embed run --batch-size 50

# Preview without executing
lars embed run --dry-run

# Check costs
lars embed costs
```

## Vector Search


### SIMILAR_TO Operator


```vector search
-- Basic semantic search
SELECT * FROM docs
WHERE title SIMILAR_TO 'sustainability report'
LIMIT 10;
-- Combined with filters
SELECT * FROM articles
WHERE content SIMILAR_TO 'machine learning best practices'
  AND published_date > '2024-01-01'
  AND category = 'technology'
LIMIT 20;
```

### VECTOR_SEARCH Function


```function syntax
-- VECTOR_SEARCH(query, table.column, limit[, min_score])
SELECT *
FROM VECTOR_SEARCH('climate change impact', papers.abstract, 50, 0.7)
ORDER BY _score DESC;
```

## Hybrid Search


Combine vector search with keyword matching for best results:

```hybrid search
-- Hybrid combines vector + keyword scoring
SELECT *
FROM HYBRID_SEARCH('kubernetes deployment strategies', docs.content, 25);
-- Keyword-only search (when embeddings not needed)
SELECT *
FROM KEYWORD_SEARCH('error 503 timeout', logs.message, 100);
```

## CLI Commands


```embedding management
# View embedding status and statistics
lars embed status

# Run embedding jobs
lars embed run --batch-size 50 --dry-run
lars embed run

# View embedding costs
lars embed costs

# Clear embeddings for a table
lars embed clear --table articles
```

### Configuration


```environment variables
# Default embedding model
LARS_DEFAULT_EMBED_MODEL=qwen/qwen3-embedding-8b

# Batch size for embedding jobs
LARS_EMBED_BATCH_SIZE=50
```


> **TIP: Performance Tip**
>
> 
> For large datasets, run embedding jobs in batches during off-peak hours.
>     Use `--dry-run` first to estimate time and cost.
> 


## Next: Takes & Evaluation


Learn about parallel execution with [Takes](#takes).
