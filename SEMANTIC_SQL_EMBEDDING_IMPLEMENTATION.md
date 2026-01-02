# Semantic SQL + Embeddings: Complete Implementation Plan

**Date:** 2026-01-02
**Status:** Detailed implementation roadmap
**Estimated Effort:** 2-3 weeks (Phase 1 complete system)

---

## Executive Summary

**Good news:** 95% of the infrastructure already exists! RVBBIT has:
- ✅ `Agent.embed()` - Production-ready embedding generation (batching, retry, logging)
- ✅ ClickHouse `cosineDistance()` - Native vector search
- ✅ Elasticsearch hybrid search - Vector + keyword (optional)
- ✅ RAG pipeline - Chunking, indexing, incremental updates
- ✅ 4096-dim embeddings - `qwen/qwen3-embedding-8b` standardized

**What's needed:** Wire it into SQL syntax via cascades (3 new operators, ~500 lines of code).

---

## Architecture Overview

### Current State (Works Today)

```python
# Python API
from rvbbit.agent import Agent
from rvbbit.db_adapter import get_db_connection

# Generate embeddings
result = Agent.embed(texts=["text1", "text2"])
embeddings = result["embeddings"]  # List of 4096-dim vectors

# Vector search in ClickHouse
db = get_db_connection()
results = db.vector_search(
    table="rag_chunks",
    embedding_col="embedding",
    query_vector=embeddings[0],
    limit=10
)
```

### Target State (SQL Interface)

```sql
-- Generate embeddings
SELECT id, text, EMBED(text) as embedding
FROM documents;

-- Vector search
SELECT * FROM VECTOR_SEARCH('eco-friendly products', 'documents', 10);

-- Similarity operator
SELECT * FROM products
WHERE description SIMILAR_TO 'sustainable' > 0.7;

-- Hybrid: Vector pre-filter + LLM reasoning
WITH candidates AS (
  SELECT * FROM VECTOR_SEARCH('eco products', 'products', 100)
)
SELECT *
FROM candidates c
JOIN products p ON p.id = c.id
WHERE p.description MEANS 'eco-friendly AND affordable'
ORDER BY c.similarity DESC
LIMIT 10;
```

---

## Phase 1: Core Embedding Operators

**Goal:** Add `EMBED()`, `VECTOR_SEARCH()`, and `SIMILAR_TO` to SQL.

**Estimated Time:** 1-2 weeks

### File 1: Embedding Storage Tools

**Path:** `rvbbit/traits/embedding_storage.py`

**Purpose:** Python tools that wrap existing `Agent.embed()` and `db.vector_search()`.

```python
"""
Embedding storage and retrieval tools for Semantic SQL.

Wraps existing Agent.embed() and db.vector_search() for use in cascades.
"""

from typing import List, Dict, Any, Optional
from rvbbit import register_tackle
from rvbbit.agent import Agent
from rvbbit.db_adapter import get_db_connection
from rvbbit.config import get_config
import json

# ============================================================================
# Tool 1: Generate Embedding
# ============================================================================

def agent_embed(
    text: str,
    model: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate embedding using Agent.embed().

    Args:
        text: Text to embed
        model: Optional model override (default: RVBBIT_DEFAULT_EMBED_MODEL)
        session_id: Optional session ID for logging

    Returns:
        {
            "embedding": List[float],  # 4096-dim vector
            "model": str,
            "dim": int
        }
    """
    config = get_config()
    model = model or config.default_embed_model

    # Use Agent.embed() (handles batching, retry, logging)
    result = Agent.embed(
        texts=[text],
        model=model,
        session_id=session_id
    )

    return {
        "embedding": result["embeddings"][0],  # First embedding
        "model": result["model"],
        "dim": result["dim"]
    }


# ============================================================================
# Tool 2: Store Embedding in ClickHouse
# ============================================================================

def clickhouse_store_embedding(
    source_table: str,
    source_id: str,
    text: str,
    embedding: List[float],
    model: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Store embedding in ClickHouse rvbbit_embeddings table.

    Creates shadow table if needed, stores embedding for retrieval.

    Args:
        source_table: Name of source table (e.g., 'products')
        source_id: ID of source row (e.g., '42')
        text: Original text
        embedding: 4096-dim vector
        model: Model name used
        metadata: Optional additional metadata (JSON)

    Returns:
        {"success": True, "source_table": str, "source_id": str}
    """
    db = get_db_connection()

    # Create shadow table if not exists
    create_table_sql = """
        CREATE TABLE IF NOT EXISTS rvbbit_embeddings (
            source_table LowCardinality(String),
            source_id String,
            text String,
            embedding Array(Float32),
            embedding_model LowCardinality(String),
            embedding_dim UInt16,
            metadata String DEFAULT '{}',  -- JSON metadata
            created_at DateTime64(3) DEFAULT now64(3),

            INDEX idx_source_table source_table TYPE bloom_filter GRANULARITY 1,
            INDEX idx_source_id source_id TYPE bloom_filter GRANULARITY 1
        )
        ENGINE = ReplacingMergeTree(created_at)
        ORDER BY (source_table, source_id)
    """
    db.client.execute(create_table_sql)

    # Insert embedding
    insert_sql = """
        INSERT INTO rvbbit_embeddings
        (source_table, source_id, text, embedding, embedding_model, embedding_dim, metadata)
        VALUES
    """

    data = [{
        'source_table': source_table,
        'source_id': str(source_id),
        'text': text[:5000],  # Truncate very long text
        'embedding': embedding,
        'embedding_model': model,
        'embedding_dim': len(embedding),
        'metadata': json.dumps(metadata or {})
    }]

    db.client.execute(insert_sql, data)

    return {
        "success": True,
        "source_table": source_table,
        "source_id": source_id
    }


# ============================================================================
# Tool 3: Vector Search in ClickHouse
# ============================================================================

def clickhouse_vector_search(
    query_embedding: List[float],
    source_table: str,
    limit: int = 10,
    threshold: Optional[float] = None,
    metadata_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Semantic search using ClickHouse cosineDistance.

    Args:
        query_embedding: 4096-dim query vector
        source_table: Table to search (e.g., 'products')
        limit: Max results (default: 10)
        threshold: Min similarity threshold (0-1, optional)
        metadata_filter: SQL WHERE clause on metadata (optional)

    Returns:
        {
            "results": [
                {
                    "source_id": str,
                    "text": str,
                    "distance": float,
                    "similarity": float,
                    "metadata": dict
                },
                ...
            ],
            "count": int
        }
    """
    db = get_db_connection()

    # Build WHERE clause
    where_parts = [f"source_table = '{source_table}'"]

    if threshold is not None:
        # Note: similarity = 1 - distance
        max_distance = 1.0 - threshold
        where_parts.append(f"cosineDistance(embedding, {query_embedding}) <= {max_distance}")

    if metadata_filter:
        where_parts.append(metadata_filter)

    where_clause = " AND ".join(where_parts)

    # Use existing db.vector_search() method
    sql = f"""
        SELECT
            source_id,
            text,
            metadata,
            cosineDistance(embedding, {query_embedding}) AS distance,
            1 - cosineDistance(embedding, {query_embedding}) AS similarity
        FROM rvbbit_embeddings
        WHERE {where_clause}
        ORDER BY distance ASC
        LIMIT {limit}
    """

    rows = db.query(sql, output_format="dict")

    # Parse metadata JSON
    for row in rows:
        try:
            row['metadata'] = json.loads(row.get('metadata', '{}'))
        except:
            row['metadata'] = {}

    return {
        "results": rows,
        "count": len(rows)
    }


# ============================================================================
# Tool 4: Cosine Similarity Between Two Texts
# ============================================================================

def cosine_similarity_texts(
    text1: str,
    text2: str,
    model: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compute cosine similarity between two texts.

    Args:
        text1: First text
        text2: Second text
        model: Optional embedding model
        session_id: Optional session ID

    Returns:
        {"similarity": float}  # 0.0 to 1.0
    """
    config = get_config()
    model = model or config.default_embed_model

    # Embed both texts (batched in one API call)
    result = Agent.embed(
        texts=[text1, text2],
        model=model,
        session_id=session_id
    )

    emb1 = result["embeddings"][0]
    emb2 = result["embeddings"][1]

    # Cosine similarity
    import numpy as np
    similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))

    return {
        "similarity": float(similarity)
    }


# ============================================================================
# Tool 5: Elasticsearch Hybrid Search (Optional)
# ============================================================================

def elasticsearch_hybrid_search(
    query: str,
    query_embedding: List[float],
    index: str,
    limit: int = 10,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3
) -> Dict[str, Any]:
    """
    Hybrid search using Elasticsearch (vector + keyword).

    Requires Elasticsearch with dense_vector field configured.
    Falls back to ClickHouse if Elasticsearch unavailable.

    Args:
        query: Text query (for keyword matching)
        query_embedding: 4096-dim vector
        index: Elasticsearch index name
        limit: Max results
        semantic_weight: Vector similarity weight (0-1)
        keyword_weight: BM25 keyword weight (0-1)

    Returns:
        {
            "results": [
                {
                    "id": str,
                    "text": str,
                    "score": float
                },
                ...
            ],
            "backend": "elasticsearch" | "clickhouse"
        }
    """
    try:
        from rvbbit.elastic import get_elastic_client

        es = get_elastic_client()
        if not es.ping():
            raise Exception("Elasticsearch not available")

        # Elasticsearch query
        response = es.search(
            index=index,
            body={
                "query": {
                    "script_score": {
                        "query": {
                            "bool": {
                                "should": [
                                    {
                                        "match": {
                                            "text": {
                                                "query": query,
                                                "boost": keyword_weight
                                            }
                                        }
                                    }
                                ]
                            }
                        },
                        "script": {
                            "source": f"cosineSimilarity(params.query_vector, 'embedding') * {semantic_weight} + _score",
                            "params": {
                                "query_vector": query_embedding
                            }
                        }
                    }
                },
                "size": limit
            }
        )

        results = [
            {
                "id": hit["_id"],
                "text": hit["_source"]["text"],
                "score": hit["_score"]
            }
            for hit in response["hits"]["hits"]
        ]

        return {
            "results": results,
            "backend": "elasticsearch"
        }

    except Exception as e:
        # Fallback to ClickHouse
        import logging
        logging.warning(f"Elasticsearch hybrid search failed, using ClickHouse: {e}")

        # Use pure vector search as fallback
        ch_result = clickhouse_vector_search(
            query_embedding=query_embedding,
            source_table=index,
            limit=limit
        )

        return {
            "results": [
                {
                    "id": r["source_id"],
                    "text": r["text"],
                    "score": r["similarity"]
                }
                for r in ch_result["results"]
            ],
            "backend": "clickhouse"
        }


# ============================================================================
# Register Tools
# ============================================================================

register_tackle("agent_embed", agent_embed)
register_tackle("clickhouse_store_embedding", clickhouse_store_embedding)
register_tackle("clickhouse_vector_search", clickhouse_vector_search)
register_tackle("cosine_similarity_texts", cosine_similarity_texts)
register_tackle("elasticsearch_hybrid_search", elasticsearch_hybrid_search)
```

---

### File 2: EMBED() Cascade

**Path:** `cascades/semantic_sql/embed.cascade.yaml`

**Purpose:** Generate embedding for text via SQL.

```yaml
cascade_id: semantic_embed

description: |
  Generate text embeddings using Agent.embed().

  Uses RVBBIT_DEFAULT_EMBED_MODEL (qwen/qwen3-embedding-8b, 4096 dims).
  Results are cached by input hash for performance.

inputs_schema:
  text: Text to embed
  model: Optional model override (default: qwen/qwen3-embedding-8b)

sql_function:
  name: semantic_embed
  description: Generate 4096-dim embedding vector from text
  args:
    - {name: text, type: VARCHAR}
    - {name: model, type: VARCHAR, optional: true}
  returns: DOUBLE[]  # Array of floats (DuckDB)
  shape: SCALAR
  operators:
    - "EMBED({{ text }})"
    - "EMBED({{ text }}, '{{ model }}')"
  cache: true  # Cache embeddings by input hash

cells:
  - name: generate_embedding
    tool: agent_embed
    inputs:
      text: "{{ input.text }}"
      model: "{{ input.model }}"

  - name: format_output
    tool: python_data
    inputs:
      code: |
        # Return embedding as array for DuckDB
        return list(outputs.generate_embedding.embedding)
```

**Usage:**
```sql
-- Basic (uses default model)
SELECT id, text, EMBED(text) as embedding FROM documents;

-- Custom model
SELECT id, text, EMBED(text, 'openai/text-embedding-3-large') as embedding FROM documents;

-- Store embeddings
INSERT INTO documents_embeddings
SELECT id, EMBED(text) as embedding FROM documents;
```

---

### File 3: VECTOR_SEARCH() Cascade

**Path:** `cascades/semantic_sql/vector_search.cascade.yaml`

**Purpose:** Semantic search via table-valued function.

```yaml
cascade_id: semantic_vector_search

description: |
  Semantic search using ClickHouse cosineDistance.

  Returns table of (id, text, similarity) tuples.
  Pre-filters via vector similarity, can be combined with LLM operators.

inputs_schema:
  query: Search query text
  source_table: Table to search (must have embeddings in rvbbit_embeddings)
  limit: Max results (default: 10)
  threshold: Min similarity threshold 0-1 (optional)

sql_function:
  name: vector_search
  description: Find similar documents via vector search
  args:
    - {name: query, type: VARCHAR}
    - {name: source_table, type: VARCHAR}
    - {name: limit, type: INTEGER, optional: true}
    - {name: threshold, type: DOUBLE, optional: true}
  returns: TABLE  # Table-valued function
  shape: AGGREGATE
  operators:
    - "VECTOR_SEARCH('{{ query }}', '{{ source_table }}')"
    - "VECTOR_SEARCH('{{ query }}', '{{ source_table }}', {{ limit }})"
    - "VECTOR_SEARCH('{{ query }}', '{{ source_table }}', {{ limit }}, {{ threshold }})"
  cache: true  # Cache search results

cells:
  - name: embed_query
    tool: agent_embed
    inputs:
      text: "{{ input.query }}"

  - name: vector_search
    tool: clickhouse_vector_search
    inputs:
      query_embedding: "{{ outputs.embed_query.embedding }}"
      source_table: "{{ input.source_table }}"
      limit: "{{ input.limit | default(10) }}"
      threshold: "{{ input.threshold }}"

  - name: format_results
    tool: python_data
    inputs:
      code: |
        # Return as table (list of dicts for DuckDB)
        results = outputs.vector_search.results

        # Format for SQL
        return [
            {
                'id': row['source_id'],
                'text': row['text'],
                'similarity': row['similarity'],
                'distance': row['distance']
            }
            for row in results
        ]
```

**Usage:**
```sql
-- Basic semantic search
SELECT * FROM VECTOR_SEARCH('eco-friendly products', 'products', 10);
-- Returns: id | text | similarity | distance

-- Join with original table
SELECT p.*, vs.similarity
FROM products p
JOIN VECTOR_SEARCH('sustainable', 'products', 50) vs ON p.id = vs.id
WHERE p.price < 100
ORDER BY vs.similarity DESC;

-- Hybrid: Vector + LLM
WITH candidates AS (
  SELECT * FROM VECTOR_SEARCH('eco products', 'products', 100)
)
SELECT c.*, p.*
FROM candidates c
JOIN products p ON p.id = c.id
WHERE p.description MEANS 'eco-friendly AND affordable'
ORDER BY c.similarity DESC
LIMIT 10;
```

---

### File 4: SIMILAR_TO Cascade

**Path:** `cascades/semantic_sql/similar_to.cascade.yaml`

**Purpose:** Inline similarity operator.

```yaml
cascade_id: semantic_similar_to

description: |
  Compute cosine similarity between two texts.

  Returns similarity score 0.0 to 1.0.
  Useful for WHERE clauses and filtering.

inputs_schema:
  text1: First text
  text2: Second text (can be literal or column)

sql_function:
  name: similar_to
  description: Cosine similarity between two texts
  args:
    - {name: text1, type: VARCHAR}
    - {name: text2, type: VARCHAR}
  returns: DOUBLE  # Similarity 0.0 to 1.0
  shape: SCALAR
  operators:
    - "{{ text1 }} SIMILAR_TO {{ text2 }}"
    - "SIMILAR_TO({{ text1 }}, {{ text2 }})"
  cache: true

cells:
  - name: compute_similarity
    tool: cosine_similarity_texts
    inputs:
      text1: "{{ input.text1 }}"
      text2: "{{ input.text2 }}"

  - name: format_output
    tool: python_data
    inputs:
      code: |
        return outputs.compute_similarity.similarity
```

**Usage:**
```sql
-- Filter by similarity threshold
SELECT * FROM products
WHERE description SIMILAR_TO 'sustainable and eco-friendly' > 0.7;

-- Compare columns
SELECT c1.company, c2.company,
       c1.description SIMILAR_TO c2.description as similarity
FROM companies c1, companies c2
WHERE c1.id < c2.id
  AND c1.description SIMILAR_TO c2.description > 0.8;

-- Fuzzy JOIN
SELECT c.*, s.*
FROM customers c, suppliers s
WHERE c.company_name SIMILAR_TO s.vendor_name > 0.75
LIMIT 100;
```

---

### File 5: SQL Rewriter Extensions

**Path:** `rvbbit/sql_tools/semantic_operators.py` (append to existing file)

**Purpose:** Parse new embedding operators.

```python
# ============================================================================
# Embedding Operators (add to existing semantic_operators.py)
# ============================================================================

def _rewrite_embed(sql: str) -> str:
    """
    Rewrite EMBED() function calls.

    Before: SELECT EMBED(description) FROM products
    After:  SELECT semantic_embed(description) FROM products

    Before: SELECT EMBED(text, 'custom-model') FROM docs
    After:  SELECT semantic_embed(text, 'custom-model') FROM docs
    """
    import re

    # Pattern: EMBED(column) or EMBED(column, 'model')
    pattern = r'\bEMBED\s*\((.*?)\)'

    def replace_embed(match):
        args = match.group(1)
        return f"semantic_embed({args})"

    return re.sub(pattern, replace_embed, sql, flags=re.IGNORECASE)


def _rewrite_vector_search(sql: str) -> str:
    """
    Rewrite VECTOR_SEARCH() table function.

    Before: SELECT * FROM VECTOR_SEARCH('query', 'table', 10)
    After:  SELECT * FROM vector_search_impl('query', 'table', 10)

    Note: Table-valued functions in DuckDB require special handling.
    We'll use a workaround with temp tables.
    """
    import re

    # Pattern: VECTOR_SEARCH('query', 'table', limit, threshold)
    pattern = r'\bVECTOR_SEARCH\s*\((.*?)\)'

    def replace_vector_search(match):
        args = match.group(1)
        # For table-valued functions, we need to use a temp table approach
        # The UDF will return JSON, which we'll parse with json_to_table()
        return f"json_to_table(vector_search_json({args}))"

    return re.sub(pattern, replace_vector_search, sql, flags=re.IGNORECASE)


def _rewrite_similar_to(sql: str) -> str:
    """
    Rewrite SIMILAR_TO operator.

    Before: WHERE text SIMILAR_TO 'reference' > 0.7
    After:  WHERE similar_to(text, 'reference') > 0.7
    """
    import re

    # Pattern: column SIMILAR_TO 'reference'
    pattern = r'(\w+)\s+SIMILAR_TO\s+([\w\'"]+)'

    def replace_similar_to(match):
        col = match.group(1)
        ref = match.group(2)
        return f"similar_to({col}, {ref})"

    return re.sub(pattern, replace_similar_to, sql, flags=re.IGNORECASE)


# Add to main rewrite function in semantic_operators.py
def rewrite_semantic_operators(sql: str) -> str:
    """
    Main rewriter (extends existing function).
    """
    # Existing rewrites
    sql = _rewrite_means(sql)
    sql = _rewrite_about(sql)
    sql = _rewrite_implies(sql)
    # ... etc ...

    # New embedding rewrites
    sql = _rewrite_embed(sql)
    sql = _rewrite_vector_search(sql)
    sql = _rewrite_similar_to(sql)

    return sql
```

---

### File 6: DuckDB UDF Registration

**Path:** `rvbbit/sql_tools/udf.py` (append to existing file)

**Purpose:** Register embedding UDFs with DuckDB.

```python
# ============================================================================
# Embedding UDFs (add to existing udf.py)
# ============================================================================

def register_embedding_udfs(conn):
    """
    Register embedding-related UDFs with DuckDB.

    Called from register_rvbbit_udfs() during connection setup.
    """
    from rvbbit.semantic_sql.registry import _execute_cascade

    # -------------------------------------------------------------------------
    # UDF: semantic_embed(text, model?) -> DOUBLE[]
    # -------------------------------------------------------------------------

    def semantic_embed_udf(text: str, model: str = None):
        """Generate embedding via cascade."""
        if text is None:
            return None

        result = _execute_cascade(
            "semantic_embed",
            {"text": text, "model": model}
        )

        # Result is list of floats
        return result

    conn.create_function(
        "semantic_embed",
        semantic_embed_udf,
        return_type="DOUBLE[]"
    )

    # -------------------------------------------------------------------------
    # UDF: vector_search_json(query, table, limit?, threshold?) -> VARCHAR
    # -------------------------------------------------------------------------

    def vector_search_json_udf(
        query: str,
        source_table: str,
        limit: int = 10,
        threshold: float = None
    ):
        """
        Vector search returning JSON.

        DuckDB doesn't support table-valued UDFs directly, so we return JSON
        and use json_to_table() to convert to rows.
        """
        import json

        result = _execute_cascade(
            "semantic_vector_search",
            {
                "query": query,
                "source_table": source_table,
                "limit": limit,
                "threshold": threshold
            }
        )

        # Result is list of dicts
        # Convert to JSON string
        return json.dumps(result)

    conn.create_function(
        "vector_search_json",
        vector_search_json_udf,
        return_type="VARCHAR"
    )

    # -------------------------------------------------------------------------
    # UDF: similar_to(text1, text2) -> DOUBLE
    # -------------------------------------------------------------------------

    def similar_to_udf(text1: str, text2: str):
        """Cosine similarity between texts."""
        if text1 is None or text2 is None:
            return None

        result = _execute_cascade(
            "semantic_similar_to",
            {"text1": text1, "text2": text2}
        )

        return result

    conn.create_function(
        "similar_to",
        similar_to_udf,
        return_type="DOUBLE"
    )


# Update register_rvbbit_udfs() to call embedding UDFs
def register_rvbbit_udfs(conn):
    """
    Main UDF registration (extends existing function).
    """
    # Existing UDFs
    register_semantic_udfs(conn)  # MEANS, ABOUT, etc.

    # New embedding UDFs
    register_embedding_udfs(conn)
```

---

## Phase 2: Integration & Testing

**Estimated Time:** 3-5 days

### Test Suite

**Path:** `tests/test_semantic_sql_embeddings.py`

```python
"""
Tests for Semantic SQL embedding operators.
"""

import pytest
from rvbbit.sql_tools.session_db import get_session_db
from rvbbit.sql_rewriter import rewrite_rvbbit_syntax


def test_embed_basic():
    """Test basic EMBED() function."""
    db = get_session_db("test_embed")

    # Create test table
    db.conn.execute("""
        CREATE TABLE test_docs (
            id INTEGER,
            text VARCHAR
        )
    """)

    db.conn.execute("""
        INSERT INTO test_docs VALUES
        (1, 'The quick brown fox'),
        (2, 'jumps over the lazy dog')
    """)

    # Generate embeddings
    sql = "SELECT id, text, EMBED(text) as embedding FROM test_docs"
    rewritten = rewrite_rvbbit_syntax(sql)

    result = db.conn.execute(rewritten).fetchall()

    assert len(result) == 2
    # Each embedding should be 4096-dim array
    assert len(result[0][2]) == 4096
    assert all(isinstance(v, float) for v in result[0][2])


def test_vector_search():
    """Test VECTOR_SEARCH() table function."""
    db = get_session_db("test_vector_search")

    # First, create embeddings
    db.conn.execute("""
        CREATE TABLE products (
            id INTEGER,
            description VARCHAR
        )
    """)

    db.conn.execute("""
        INSERT INTO products VALUES
        (1, 'Eco-friendly bamboo toothbrush'),
        (2, 'Sustainable cotton t-shirt'),
        (3, 'Gas-powered leaf blower'),
        (4, 'Organic cotton bedsheets')
    """)

    # Generate and store embeddings
    sql_embed = "SELECT COUNT(*) FROM products WHERE EMBED(description)"
    db.conn.execute(rewrite_rvbbit_syntax(sql_embed))

    # Vector search
    sql_search = "SELECT * FROM VECTOR_SEARCH('eco-friendly products', 'products', 3)"
    rewritten = rewrite_rvbbit_syntax(sql_search)

    result = db.conn.execute(rewritten).fetchall()

    assert len(result) == 3
    # First result should be most similar (bamboo toothbrush or cotton t-shirt)
    assert result[0][2] > 0.7  # High similarity


def test_similar_to():
    """Test SIMILAR_TO operator."""
    db = get_session_db("test_similar_to")

    db.conn.execute("""
        CREATE TABLE companies (
            id INTEGER,
            name VARCHAR
        )
    """)

    db.conn.execute("""
        INSERT INTO companies VALUES
        (1, 'International Business Machines'),
        (2, 'IBM Corporation'),
        (3, 'Microsoft Corporation'),
        (4, 'IBM Corp')
    """)

    # Find similar company names
    sql = """
        SELECT c1.name, c2.name, c1.name SIMILAR_TO c2.name as similarity
        FROM companies c1, companies c2
        WHERE c1.id < c2.id
          AND c1.name SIMILAR_TO c2.name > 0.8
        ORDER BY similarity DESC
    """

    rewritten = rewrite_rvbbit_syntax(sql)
    result = db.conn.execute(rewritten).fetchall()

    # Should find IBM/IBM Corp, IBM/International Business Machines
    assert len(result) >= 2
    assert result[0][2] > 0.8  # High similarity


def test_hybrid_vector_llm():
    """Test hybrid vector pre-filter + LLM reasoning."""
    db = get_session_db("test_hybrid")

    # Setup products with embeddings
    db.conn.execute("""
        CREATE TABLE products (
            id INTEGER,
            name VARCHAR,
            description VARCHAR,
            price DOUBLE
        )
    """)

    db.conn.execute("""
        INSERT INTO products VALUES
        (1, 'Bamboo Toothbrush', 'Eco-friendly bamboo toothbrush, sustainable', 12.99),
        (2, 'Cotton T-Shirt', 'Organic cotton, fair trade certified', 29.99),
        (3, 'Leaf Blower', 'Gas-powered leaf blower, high performance', 199.99),
        (4, 'Cotton Sheets', 'Organic cotton bedsheets, chemical-free', 89.99),
        (5, 'Green Paint', 'Eco-friendly low-VOC paint', 45.00)
    """)

    # Embed all products
    db.conn.execute(rewrite_rvbbit_syntax(
        "SELECT COUNT(*) FROM products WHERE EMBED(description)"
    ))

    # Hybrid query: Vector search + LLM filtering
    sql = """
        WITH candidates AS (
          SELECT * FROM VECTOR_SEARCH('eco-friendly affordable products', 'products', 10)
        )
        SELECT p.id, p.name, p.price, c.similarity
        FROM candidates c
        JOIN products p ON p.id = c.id
        WHERE p.description MEANS 'eco-friendly AND affordable'
          AND p.price < 50
        ORDER BY c.similarity DESC
    """

    rewritten = rewrite_rvbbit_syntax(sql)
    result = db.conn.execute(rewritten).fetchall()

    # Should find bamboo toothbrush and maybe green paint
    assert len(result) >= 1
    assert result[0][2] < 50  # Price filter
    assert result[0][3] > 0.6  # Decent similarity


def test_performance_caching():
    """Test that embeddings are cached."""
    db = get_session_db("test_caching")

    db.conn.execute("CREATE TABLE docs (id INTEGER, text VARCHAR)")
    db.conn.execute("INSERT INTO docs VALUES (1, 'test text'), (2, 'test text'), (3, 'test text')")

    # First run: 3 unique texts (should be 1 API call due to identical text)
    sql = "SELECT id, EMBED(text) FROM docs"
    result1 = db.conn.execute(rewrite_rvbbit_syntax(sql)).fetchall()

    # Second run: Should use cache (no API calls)
    result2 = db.conn.execute(rewrite_rvbbit_syntax(sql)).fetchall()

    # Results should be identical
    assert result1 == result2

    # TODO: Check cache hit metrics from unified_logs


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

---

### Example Queries

**Path:** `examples/semantic_sql_embeddings_demo.sql`

```sql
-- ============================================================================
-- Semantic SQL + Embeddings Demo
-- ============================================================================

-- Setup: Create sample product catalog
CREATE TABLE products (
    id INTEGER,
    name VARCHAR,
    description VARCHAR,
    category VARCHAR,
    price DOUBLE,
    reviews_json VARCHAR  -- JSON array of review texts
);

INSERT INTO products VALUES
(1, 'Bamboo Toothbrush', 'Eco-friendly bamboo toothbrush made from sustainable materials. Biodegradable and compostable.', 'Personal Care', 12.99, '["Great product!", "Love the eco-friendly design"]'),
(2, 'Organic Cotton T-Shirt', 'Fair trade certified organic cotton t-shirt. Soft, breathable, and ethically made.', 'Clothing', 29.99, '["Very comfortable", "A bit pricey but worth it"]'),
(3, 'Stainless Steel Water Bottle', 'Reusable insulated water bottle. Keeps drinks cold for 24 hours. BPA-free.', 'Kitchen', 34.99, '["Keeps drinks cold all day", "Sturdy and well-made"]'),
(4, 'Solar Phone Charger', 'Portable solar-powered charger. Perfect for camping and emergencies.', 'Electronics', 49.99, '["Works great in sunlight", "Charges slowly on cloudy days"]'),
(5, 'Recycled Notebook', 'Notebook made from 100% recycled paper. Vegan leather cover.', 'Office', 14.99, '["Good quality paper", "Nice design"]'),
(6, 'LED Light Bulbs', 'Energy-efficient LED bulbs. 75% less energy than incandescent. 25,000 hour lifespan.', 'Home', 19.99, '["Bright and efficient", "Saves money on electricity"]'),
(7, 'Reusable Grocery Bags', 'Set of 5 organic cotton grocery bags. Machine washable and durable.', 'Kitchen', 24.99, '["Strong and roomy", "Replaced all my plastic bags"]'),
(8, 'Compost Bin', 'Kitchen compost bin with charcoal filter. Reduces food waste and odors.', 'Kitchen', 39.99, '["No smell issues", "Good size for counter"]'),
(9, 'Natural Cleaning Spray', 'All-purpose cleaner made from plant-based ingredients. Non-toxic and biodegradable.', 'Home', 12.99, '["Smells great", "Cleans well without harsh chemicals"]'),
(10, 'Beeswax Food Wraps', 'Reusable alternative to plastic wrap. Made from organic cotton and beeswax.', 'Kitchen', 18.99, '["Works better than plastic wrap", "Easy to clean"]');

-- ----------------------------------------------------------------------------
-- Example 1: Generate Embeddings
-- ----------------------------------------------------------------------------

-- Generate embeddings for all products (stored in ClickHouse)
SELECT COUNT(*)
FROM products
WHERE EMBED(description);

-- View embeddings (first 5 dimensions)
SELECT
    id,
    name,
    EMBED(description)[1:5] as embedding_sample  -- First 5 dims
FROM products
LIMIT 3;

-- ----------------------------------------------------------------------------
-- Example 2: Basic Vector Search
-- ----------------------------------------------------------------------------

-- Find products semantically similar to "eco-friendly kitchen items"
SELECT * FROM VECTOR_SEARCH('eco-friendly kitchen items', 'products', 5);

-- Returns:
-- id | text (description) | similarity | distance
-- 8  | "Kitchen compost bin..." | 0.87 | 0.13
-- 3  | "Reusable insulated water bottle..." | 0.82 | 0.18
-- 7  | "Set of 5 organic cotton grocery bags..." | 0.79 | 0.21
-- ...

-- ----------------------------------------------------------------------------
-- Example 3: Vector Search + SQL JOINs
-- ----------------------------------------------------------------------------

-- Get full product details for similar items
SELECT
    p.id,
    p.name,
    p.category,
    p.price,
    vs.similarity
FROM products p
JOIN VECTOR_SEARCH('sustainable home products', 'products', 10) vs
    ON p.id = vs.id
WHERE p.price < 40  -- Cheap filter after vector search
ORDER BY vs.similarity DESC;

-- ----------------------------------------------------------------------------
-- Example 4: SIMILAR_TO Operator
-- ----------------------------------------------------------------------------

-- Find products with similar descriptions
SELECT
    p1.name as product1,
    p2.name as product2,
    p1.description SIMILAR_TO p2.description as similarity
FROM products p1, products p2
WHERE p1.id < p2.id
  AND p1.description SIMILAR_TO p2.description > 0.7
ORDER BY similarity DESC;

-- Find products similar to a reference description
SELECT
    id,
    name,
    description SIMILAR_TO 'environmentally friendly and sustainable' as eco_score
FROM products
WHERE description SIMILAR_TO 'environmentally friendly and sustainable' > 0.6
ORDER BY eco_score DESC;

-- ----------------------------------------------------------------------------
-- Example 5: Hybrid Search (Vector + LLM Reasoning)
-- ----------------------------------------------------------------------------

-- Stage 1: Fast vector search (1000 products → 50 candidates in ~50ms)
-- Stage 2: LLM semantic filtering (50 → 10 in ~2 seconds)

WITH candidates AS (
    SELECT * FROM VECTOR_SEARCH('affordable eco-friendly products', 'products', 50)
    WHERE similarity > 0.6
)
SELECT
    p.id,
    p.name,
    p.price,
    c.similarity as vector_score,
    -- LLM operators (cached, fast on duplicates)
    p.description MEANS 'eco-friendly AND affordable AND high quality' as is_match,
    p.description NOT MEANS 'greenwashing or misleading claims' as is_genuine
FROM candidates c
JOIN products p ON p.id = c.id
WHERE
    p.price < 50  -- Cheap filter
    AND p.description MEANS 'eco-friendly AND affordable AND high quality'
    AND p.description NOT MEANS 'greenwashing'
ORDER BY c.similarity DESC
LIMIT 10;

-- ----------------------------------------------------------------------------
-- Example 6: Semantic Analytics with Embeddings
-- ----------------------------------------------------------------------------

-- Combine vector clustering with LLM summarization
WITH product_clusters AS (
    SELECT
        id,
        name,
        description,
        category,
        -- Cluster by semantic similarity (using embeddings)
        ntile(3) OVER (ORDER BY EMBED(description)[1]) as cluster_id
    FROM products
)
SELECT
    cluster_id,
    COUNT(*) as product_count,
    -- LLM operators for insights
    CONSENSUS(description) as cluster_theme,
    THEMES(description, 3) as main_topics,
    ARRAY_AGG(name) as products
FROM product_clusters
GROUP BY cluster_id
ORDER BY cluster_id;

-- ----------------------------------------------------------------------------
-- Example 7: Fuzzy JOIN with SIMILAR_TO
-- ----------------------------------------------------------------------------

-- Match customer orders with product catalog (fuzzy matching)
CREATE TEMP TABLE customer_orders (
    order_id INTEGER,
    product_description VARCHAR
);

INSERT INTO customer_orders VALUES
(1, 'bamboo brush for teeth'),
(2, 'cotton shirt organic'),
(3, 'water bottle steel');

SELECT
    o.order_id,
    o.product_description as customer_query,
    p.name as matched_product,
    p.description SIMILAR_TO o.product_description as match_score
FROM customer_orders o
CROSS JOIN products p
WHERE p.description SIMILAR_TO o.product_description > 0.65
ORDER BY o.order_id, match_score DESC;

-- ----------------------------------------------------------------------------
-- Example 8: Review Analysis with Embeddings
-- ----------------------------------------------------------------------------

-- Find products with similar review sentiments
WITH review_embeddings AS (
    SELECT
        id,
        name,
        reviews_json,
        EMBED(reviews_json) as review_embedding
    FROM products
)
SELECT
    r1.name as product1,
    r2.name as product2,
    -- Cosine similarity of review embeddings
    SIMILAR_TO(r1.reviews_json, r2.reviews_json) as review_similarity
FROM review_embeddings r1, review_embeddings r2
WHERE r1.id < r2.id
  AND SIMILAR_TO(r1.reviews_json, r2.reviews_json) > 0.75
ORDER BY review_similarity DESC;

-- Combine with LLM sentiment analysis
SELECT
    id,
    name,
    SENTIMENT(reviews_json) as overall_sentiment,
    THEMES(reviews_json, 2) as main_review_themes
FROM products
WHERE EMBED(reviews_json) IS NOT NULL  -- Ensure embedded
ORDER BY overall_sentiment DESC;

-- ----------------------------------------------------------------------------
-- Example 9: Performance: Caching Demo
-- ----------------------------------------------------------------------------

-- First run: Generates embeddings (API calls)
EXPLAIN ANALYZE
SELECT id, EMBED(description) FROM products;

-- Second run: Uses cache (instant)
EXPLAIN ANALYZE
SELECT id, EMBED(description) FROM products;

-- Check cache stats
SELECT
    COUNT(*) as total_calls,
    SUM(CASE WHEN cached THEN 1 ELSE 0 END) as cache_hits,
    ROUND(SUM(CASE WHEN cached THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as cache_hit_rate
FROM unified_logs
WHERE session_id LIKE 'sql-%'
  AND phase_name = 'semantic_embed';

-- ----------------------------------------------------------------------------
-- Example 10: Multi-Stage Semantic Pipeline
-- ----------------------------------------------------------------------------

-- Complete semantic analysis pipeline
WITH
-- Stage 1: Vector pre-filter (fast)
vector_candidates AS (
    SELECT * FROM VECTOR_SEARCH('sustainable eco-friendly products', 'products', 30)
    WHERE similarity > 0.65
),
-- Stage 2: LLM filtering (intelligent)
llm_filtered AS (
    SELECT p.*, vc.similarity
    FROM vector_candidates vc
    JOIN products p ON p.id = vc.id
    WHERE
        p.description MEANS 'eco-friendly AND sustainable'
        AND p.description NOT MEANS 'greenwashing'
        AND p.price < 60
),
-- Stage 3: Semantic analytics
analytics AS (
    SELECT
        lf.*,
        SUMMARIZE(lf.reviews_json, 'Focus on eco-friendly aspects') as eco_review_summary,
        SENTIMENT(lf.reviews_json) as review_sentiment,
        THEMES(lf.reviews_json, 2) as review_themes
    FROM llm_filtered lf
)
-- Final results with full semantic intelligence
SELECT
    id,
    name,
    category,
    price,
    similarity as vector_score,
    eco_review_summary,
    review_sentiment,
    review_themes
FROM analytics
ORDER BY similarity DESC, review_sentiment DESC
LIMIT 10;
```

---

## Phase 3: Documentation & Examples

**Estimated Time:** 2-3 days

### User Documentation

**Path:** `docs/SEMANTIC_SQL_EMBEDDINGS.md`

```markdown
# Semantic SQL Embeddings Guide

## Overview

RVBBIT Semantic SQL now supports embedding-based operators for fast vector search combined with deep LLM reasoning.

**New operators:**
- `EMBED(text)` - Generate 4096-dim embeddings
- `VECTOR_SEARCH(query, table, limit)` - Semantic search
- `text1 SIMILAR_TO text2` - Cosine similarity

**Key benefits:**
- ✅ Fast vector pre-filtering (50ms for 1M items)
- ✅ Deep LLM reasoning (MEANS, IMPLIES, SUMMARIZE, etc.)
- ✅ Hybrid search (vector + keyword via Elasticsearch)
- ✅ Automatic caching (90%+ hit rates)
- ✅ Cost optimization (vector eliminates 99% of LLM calls)

## Quick Start

### 1. Generate Embeddings

```sql
-- Embed all documents (stored in ClickHouse)
SELECT COUNT(*) FROM products WHERE EMBED(description);
```

### 2. Vector Search

```sql
-- Find semantically similar items
SELECT * FROM VECTOR_SEARCH('eco-friendly products', 'products', 10);
```

### 3. Hybrid: Vector + LLM

```sql
WITH candidates AS (
  SELECT * FROM VECTOR_SEARCH('sustainable products', 'products', 100)
)
SELECT *
FROM candidates c
JOIN products p ON p.id = c.id
WHERE p.description MEANS 'eco-friendly AND affordable'
ORDER BY c.similarity DESC
LIMIT 10;
```

## Architecture

**Vector storage:** ClickHouse (or optionally Elasticsearch for hybrid search)

**Embedding model:** `qwen/qwen3-embedding-8b` (4096 dimensions)

**Caching:** Automatic by input hash (UDF cache + cascade cache)

**Cost:** ~$0.005 per 1,000 embeddings (OpenRouter pricing)

## Performance

**Vector search:**
- 1M items → 100 candidates in ~50ms (ClickHouse `cosineDistance()`)
- No LLM calls (pure vector similarity)

**Hybrid search:**
- Stage 1: Vector pre-filter (50ms)
- Stage 2: LLM semantic filtering (2 seconds, cached)
- **Total: ~2 seconds** (vs. 15 minutes for pure LLM)

**Cost savings:**
- Pure LLM: 1M calls × $0.0005 = **$500**
- Hybrid: 100 calls × $0.0005 = **$0.05**
- **10,000x cost reduction!**

## Use Cases

### Semantic Search
```sql
SELECT * FROM VECTOR_SEARCH('machine learning papers', 'research_db', 20);
```

### Entity Resolution
```sql
SELECT c.*, s.*
FROM customers c, suppliers s
WHERE c.company_name SIMILAR_TO s.vendor_name > 0.8
LIMIT 100;
```

### Content Clustering
```sql
SELECT
  cluster_id,
  CONSENSUS(description) as theme,
  COUNT(*) as items
FROM (
  SELECT *, ntile(5) OVER (ORDER BY EMBED(description)[1]) as cluster_id
  FROM products
)
GROUP BY cluster_id;
```

### Review Analysis
```sql
SELECT
  product_id,
  SUMMARIZE(reviews),
  THEMES(reviews, 3),
  SENTIMENT(reviews)
FROM reviews
WHERE reviews SIMILAR_TO 'quality and durability' > 0.6
GROUP BY product_id;
```

## Configuration

**Environment variables:**
```bash
# Embedding model (default: qwen/qwen3-embedding-8b)
export RVBBIT_DEFAULT_EMBED_MODEL="qwen/qwen3-embedding-8b"

# Embedding backend (default: openrouter)
# export RVBBIT_EMBED_BACKEND="deterministic"  # For testing (no API calls)

# Batch size (default: 50)
# export RVBBIT_EMBED_BATCH_SIZE=100

# Elasticsearch (optional, for hybrid search)
# export ELASTICSEARCH_URL="http://localhost:9200"
```

**Cascade overrides:**

Edit `cascades/semantic_sql/embed.cascade.yaml` to:
- Change embedding model
- Add custom pre/post-processing
- Modify output format

## Troubleshooting

**Q: Embeddings are slow**
A: Increase `RVBBIT_EMBED_BATCH_SIZE` (default: 50 → try 100)

**Q: High API costs**
A: Check cache hit rate in `unified_logs`. Should be >90% for typical workloads.

**Q: Vector search returns poor results**
A: Lower the similarity threshold (e.g., `VECTOR_SEARCH(query, table, limit, 0.5)`)

**Q: Want keyword + semantic search**
A: Enable Elasticsearch for hybrid search (vector + BM25 keyword matching)

## Advanced

### Custom Embedding Models

Edit `cascades/semantic_sql/embed.cascade.yaml`:

```yaml
cells:
  - name: generate_embedding
    tool: agent_embed
    inputs:
      text: "{{ input.text }}"
      model: "openai/text-embedding-3-large"  # Override default
```

### Elasticsearch Hybrid Search

```python
# Enable Elasticsearch in discovery.py
from rvbbit.elastic import get_elastic_client

es = get_elastic_client()
if es.ping():
    # Hybrid search available (vector + keyword)
    create_sql_schema_index()
```

### Manual Embedding Storage

```sql
-- Create custom embedding table
CREATE TABLE custom_embeddings (
    id INTEGER,
    text VARCHAR,
    embedding DOUBLE[]
);

-- Generate and store
INSERT INTO custom_embeddings
SELECT id, text, EMBED(text) as embedding
FROM source_table;

-- Search custom table
SELECT * FROM VECTOR_SEARCH('query', 'custom_embeddings', 10);
```

## See Also

- [RVBBIT_SEMANTIC_SQL.md](../RVBBIT_SEMANTIC_SQL.md) - Core semantic operators
- [SEMANTIC_SQL_RAG_VISION.md](../SEMANTIC_SQL_RAG_VISION.md) - Architecture vision
- [examples/semantic_sql_embeddings_demo.sql](../examples/semantic_sql_embeddings_demo.sql) - Full examples
```

---

## Implementation Checklist

### Week 1: Core Infrastructure

- [ ] **Day 1-2:** Create `rvbbit/traits/embedding_storage.py`
  - [ ] Implement `agent_embed()` wrapper
  - [ ] Implement `clickhouse_store_embedding()`
  - [ ] Implement `clickhouse_vector_search()`
  - [ ] Implement `cosine_similarity_texts()`
  - [ ] Implement `elasticsearch_hybrid_search()` (optional fallback)
  - [ ] Register all tools

- [ ] **Day 3:** Create cascade YAML files
  - [ ] `cascades/semantic_sql/embed.cascade.yaml`
  - [ ] `cascades/semantic_sql/vector_search.cascade.yaml`
  - [ ] `cascades/semantic_sql/similar_to.cascade.yaml`

- [ ] **Day 4:** Extend SQL rewriter
  - [ ] Add `_rewrite_embed()` to `semantic_operators.py`
  - [ ] Add `_rewrite_vector_search()` to `semantic_operators.py`
  - [ ] Add `_rewrite_similar_to()` to `semantic_operators.py`
  - [ ] Wire into main `rewrite_semantic_operators()` function

- [ ] **Day 5:** Register DuckDB UDFs
  - [ ] Add `register_embedding_udfs()` to `udf.py`
  - [ ] Implement `semantic_embed_udf()`
  - [ ] Implement `vector_search_json_udf()`
  - [ ] Implement `similar_to_udf()`
  - [ ] Wire into `register_rvbbit_udfs()`

### Week 2: Testing & Examples

- [ ] **Day 1-2:** Write test suite
  - [ ] `test_embed_basic()` - Basic embedding generation
  - [ ] `test_vector_search()` - Vector search
  - [ ] `test_similar_to()` - Similarity operator
  - [ ] `test_hybrid_vector_llm()` - Hybrid search
  - [ ] `test_performance_caching()` - Cache validation
  - [ ] Run all tests, fix bugs

- [ ] **Day 3:** Create demo queries
  - [ ] `examples/semantic_sql_embeddings_demo.sql`
  - [ ] 10+ example queries covering all operators
  - [ ] Validate on real data (bigfoot dataset?)

- [ ] **Day 4:** Performance benchmarking
  - [ ] Benchmark: Pure vector vs. pure LLM vs. hybrid
  - [ ] Benchmark: Cache hit rates
  - [ ] Benchmark: Cost comparison (embedding vs. LLM calls)
  - [ ] Document results

- [ ] **Day 5:** Documentation
  - [ ] `docs/SEMANTIC_SQL_EMBEDDINGS.md` user guide
  - [ ] Update `RVBBIT_SEMANTIC_SQL.md` with new operators
  - [ ] Add to README.md
  - [ ] Create migration guide (if needed)

### Week 3: Polish & Integration

- [ ] **Day 1:** Integration with existing features
  - [ ] Test with PostgreSQL wire protocol server
  - [ ] Test with DBeaver, DataGrip, Tableau
  - [ ] Test with `rvbbit sql query` CLI
  - [ ] Validate cost tracking in `unified_logs`

- [ ] **Day 2:** Edge cases & error handling
  - [ ] Handle empty embeddings gracefully
  - [ ] Handle mismatched dimensions (error message)
  - [ ] Handle missing ClickHouse table (auto-create)
  - [ ] Handle Elasticsearch unavailable (fallback to ClickHouse)

- [ ] **Day 3:** Optimization
  - [ ] Batch embedding generation where possible
  - [ ] Optimize cache key generation
  - [ ] Add EXPLAIN support for embedding operators
  - [ ] Profile and optimize slow queries

- [ ] **Day 4:** Advanced features (optional)
  - [ ] Support for custom embedding models
  - [ ] Support for image embeddings (CLIP)
  - [ ] Support for multi-modal search
  - [ ] Integration with existing RAG tools

- [ ] **Day 5:** Final polish
  - [ ] Code review
  - [ ] Update CHANGELOG
  - [ ] Tag release (e.g., v0.7.0-semantic-sql-embeddings)
  - [ ] Prepare demo for announcement

---

## Success Metrics

**Phase 1 Complete When:**
- ✅ All 3 operators work (`EMBED`, `VECTOR_SEARCH`, `SIMILAR_TO`)
- ✅ Embeddings stored in ClickHouse `rvbbit_embeddings` table
- ✅ Vector search returns correct results (cosine similarity)
- ✅ Hybrid search (vector + LLM) works end-to-end
- ✅ Caching works (>90% hit rate on duplicates)
- ✅ Test suite passes (all green)

**Performance Targets:**
- ✅ Embedding generation: <2 seconds per 100 texts (batched)
- ✅ Vector search: <100ms for 1M vectors
- ✅ Hybrid search: <3 seconds for 100 candidates
- ✅ Cache hit rate: >90% on typical workloads
- ✅ Cost reduction: >1000x vs. pure LLM

**Documentation Complete When:**
- ✅ User guide with 10+ examples
- ✅ Architecture doc updated
- ✅ Demo queries working
- ✅ Troubleshooting section complete

---

## Next Steps After Phase 1

**Phase 2: Advanced Features** (2-4 weeks)
- Multi-modal embeddings (text + images via CLIP)
- Semantic clustering with `GROUP BY EMBED()`
- Automatic re-embedding on text changes
- Embedding drift detection
- Integration with PostgresML (use as backend option)

**Phase 3: Ecosystem Integration** (2-3 weeks)
- Weaviate/Pinecone backend support
- LlamaIndex/LangChain compatibility
- BI tool guides (Tableau, Metabase)
- Benchmark vs. competitors (publish results)

**Phase 4: Production Hardening** (1-2 weeks)
- SSL/TLS support
- Authentication & authorization
- Rate limiting
- Cost budgets
- Audit logging

---

## Summary

**Estimated Total Time:** 2-3 weeks for complete Phase 1

**Lines of Code:** ~500-700 lines
- `embedding_storage.py`: ~250 lines
- Cascade YAML files: ~150 lines (3 files × 50 lines)
- SQL rewriter extensions: ~100 lines
- UDF registration: ~100 lines
- Tests: ~200 lines
- Examples: ~300 lines (SQL)
- Documentation: ~200 lines (markdown)

**Infrastructure Reuse:** 95%
- ✅ `Agent.embed()` - already built
- ✅ ClickHouse `cosineDistance()` - already built
- ✅ Elasticsearch hybrid search - already built
- ✅ RAG pipeline - already built
- ✅ Cascade registry - already built
- ✅ SQL rewriter - already built

**What's New:** 5%
- 🔨 Python tools wrapping existing functions
- 🔨 Cascade YAML definitions
- 🔨 SQL rewriter patterns (EMBED, VECTOR_SEARCH, SIMILAR_TO)
- 🔨 DuckDB UDF wrappers

**This is totally doable.** You have all the hard infrastructure already. It's just wiring!

**Ready to start?** I recommend beginning with `embedding_storage.py` (Day 1-2), then cascades (Day 3), then rewriter (Day 4), then UDFs (Day 5). Ship Phase 1 by end of Week 2. 🚀
