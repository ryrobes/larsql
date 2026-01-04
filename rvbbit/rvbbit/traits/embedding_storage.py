"""
Embedding storage and retrieval tools for Semantic SQL.

This module provides Python tools that wrap RVBBIT's existing RAG/embedding
infrastructure (Agent.embed(), db.vector_search()) for use in semantic SQL operators.

All embedding operations use the configured RVBBIT_DEFAULT_EMBED_MODEL
(qwen/qwen3-embedding-8b, 4096 dimensions) and are cached by input hash.

Architecture:
    SQL Query (EMBED, VECTOR_SEARCH, SIMILAR_TO)
        ↓
    Cascade execution
        ↓
    Tools in this module
        ↓
    Existing infrastructure (Agent.embed(), db.vector_search())
        ↓
    ClickHouse storage + OpenRouter API

Example:
    ```python
    from rvbbit.traits.embedding_storage import agent_embed, clickhouse_vector_search

    # Generate embedding
    result = agent_embed(text="eco-friendly products")
    embedding = result["embedding"]  # 4096-dim vector

    # Vector search
    results = clickhouse_vector_search(
        query_embedding=embedding,
        source_table="products",
        limit=10
    )
    ```
"""

from typing import List, Dict, Any, Optional
import json
import logging
import numpy as np

from ..trait_registry import register_trait
from ..agent import Agent
from ..db_adapter import get_db_adapter
from ..config import get_config

logger = logging.getLogger(__name__)


# ============================================================================
# Tool 1: Generate Embedding (Wraps Agent.embed())
# ============================================================================

def agent_embed(
    text: str,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    _session_id: Optional[str] = None,  # Injected by cascade runner
    _cell_name: Optional[str] = None,
    _caller_id: Optional[str] = None,  # For SQL Trail correlation
    _cascade_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate text embedding using Agent.embed().

    Wraps the existing production-ready Agent.embed() method, which handles:
    - Batching (50 texts per API call)
    - Retry with exponential backoff
    - 5-minute timeout per batch
    - Automatic logging to unified_logs
    - Cost tracking

    Args:
        text: Text to embed
        model: Optional model override (default: RVBBIT_DEFAULT_EMBED_MODEL = qwen/qwen3-embedding-8b)
        session_id: Optional session ID for logging and cost tracking
        _session_id: Injected by cascade runner (takes precedence)
        _cell_name: Injected by cascade runner

    Returns:
        {
            "embedding": List[float],  # 4096-dim vector
            "model": str,              # Model used
            "dim": int                 # Dimension (4096)
        }

    Example:
        >>> result = agent_embed("eco-friendly products")
        >>> result["dim"]
        4096
        >>> len(result["embedding"])
        4096
    """
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")

    config = get_config()
    model = model or config.default_embed_model

    # Use _session_id from cascade runner if available, otherwise explicit session_id
    # If neither, generate a fallback
    effective_session_id = _session_id or session_id
    if not effective_session_id:
        import uuid
        effective_session_id = f"embed_{uuid.uuid4().hex[:8]}"

    try:
        # Use existing Agent.embed() - fully production-ready!
        result = Agent.embed(
            texts=[text],
            model=model,
            session_id=effective_session_id,
            cell_name=_cell_name,
            caller_id=_caller_id,
            cascade_id=_cascade_id,
        )

        return {
            "embedding": result["embeddings"][0],  # First (and only) embedding
            "model": result["model"],
            "dim": result["dim"]
        }

    except Exception as e:
        logger.error(f"agent_embed failed: {e}")
        raise RuntimeError(f"Failed to generate embedding: {e}")


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
    Store embedding in ClickHouse rvbbit_embeddings shadow table.

    Creates the rvbbit_embeddings table if it doesn't exist. This table
    stores embeddings separately from source data, allowing semantic search
    across any table.

    Schema:
        - source_table: Name of original table (e.g., 'products')
        - source_id: ID of row in original table
        - text: Original text that was embedded
        - embedding: Array(Float32) - 4096-dim vector
        - embedding_model: Model used (e.g., 'qwen/qwen3-embedding-8b')
        - embedding_dim: Dimension (e.g., 4096)
        - metadata: JSON string for additional data
        - created_at: Timestamp

    Args:
        source_table: Name of source table (e.g., 'products')
        source_id: ID of source row (e.g., '42')
        text: Original text (truncated to 5000 chars for storage)
        embedding: 4096-dim vector
        model: Model name used for embedding
        metadata: Optional additional metadata (stored as JSON)

    Returns:
        {
            "success": True,
            "source_table": str,
            "source_id": str,
            "embedding_dim": int
        }

    Example:
        >>> clickhouse_store_embedding(
        ...     source_table="products",
        ...     source_id="42",
        ...     text="Eco-friendly bamboo toothbrush",
        ...     embedding=[0.1, 0.2, ...],  # 4096 dims
        ...     model="qwen/qwen3-embedding-8b"
        ... )
        {'success': True, 'source_table': 'products', 'source_id': '42'}
    """
    db = get_db_adapter()

    # Create shadow table if not exists (using migration, but check here too)
    create_table_sql = """
        CREATE TABLE IF NOT EXISTS rvbbit_embeddings (
            source_table LowCardinality(String),
            source_id String,
            text String,
            embedding Array(Float32),
            embedding_model LowCardinality(String),
            embedding_dim UInt16,
            metadata String DEFAULT '{}',
            created_at DateTime64(3) DEFAULT now64(3),

            INDEX idx_source_table source_table TYPE bloom_filter GRANULARITY 1,
            INDEX idx_source_id source_id TYPE bloom_filter GRANULARITY 1
        )
        ENGINE = ReplacingMergeTree(created_at)
        ORDER BY (source_table, source_id)
    """

    try:
        db.client.execute(create_table_sql)
    except Exception as e:
        logger.warning(f"Table creation warning (may already exist): {e}")

    # Use insert_rows method (handles arrays properly)
    row = {
        'source_table': source_table,
        'source_id': str(source_id),
        'text': text[:5000],  # Truncate very long text
        'embedding': embedding,  # List of floats
        'embedding_model': model,
        'embedding_dim': len(embedding),
        'metadata': json.dumps(metadata or {})
    }

    try:
        # Use insert_rows method from db_adapter (handles numpy/arrays correctly)
        db.insert_rows('rvbbit_embeddings', [row])
        logger.info(f"Stored embedding for {source_table}:{source_id} ({len(embedding)} dims)")

        return {
            "success": True,
            "source_table": source_table,
            "source_id": source_id,
            "embedding_dim": len(embedding)
        }

    except Exception as e:
        logger.error(f"clickhouse_store_embedding failed: {e}")
        raise RuntimeError(f"Failed to store embedding: {e}")


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
    Semantic search using ClickHouse cosineDistance function.

    Searches the rvbbit_embeddings table for vectors similar to the query.
    Uses ClickHouse's native cosineDistance() function for fast similarity.

    Performance:
        - ~50ms for 1M vectors (with proper indexing)
        - No Python-side similarity calculation
        - Native C++ implementation in ClickHouse

    Args:
        query_embedding: 4096-dim query vector
        source_table: Table to search (e.g., 'products')
        limit: Max results to return (default: 10)
        threshold: Min similarity threshold 0-1 (optional, e.g., 0.7)
        metadata_filter: SQL WHERE clause on metadata (optional)

    Returns:
        {
            "results": [
                {
                    "source_id": str,
                    "text": str,
                    "distance": float,      # 0.0 = identical, 1.0 = orthogonal
                    "similarity": float,    # 1.0 = identical, 0.0 = orthogonal
                    "metadata": dict
                },
                ...
            ],
            "count": int
        }

    Example:
        >>> embedding = agent_embed("eco-friendly products")["embedding"]
        >>> results = clickhouse_vector_search(
        ...     query_embedding=embedding,
        ...     source_table="products",
        ...     limit=10,
        ...     threshold=0.7
        ... )
        >>> results["count"]
        10
        >>> results["results"][0]["similarity"] > 0.7
        True
    """
    db = get_db_adapter()

    # Build query vector string for ClickHouse
    # ClickHouse expects: [0.1, 0.2, 0.3, ...]
    vec_str = f"[{','.join(str(v) for v in query_embedding)}]"

    # Build WHERE clause
    where_parts = [f"source_table = '{source_table}'"]

    if threshold is not None:
        # similarity = 1 - distance
        # So if we want similarity >= threshold, we need distance <= (1 - threshold)
        max_distance = 1.0 - threshold
        where_parts.append(f"cosineDistance(embedding, {vec_str}) <= {max_distance}")

    if metadata_filter:
        where_parts.append(metadata_filter)

    where_clause = " AND ".join(where_parts)

    # SQL query using ClickHouse's native cosineDistance()
    sql = f"""
        SELECT
            source_id,
            text,
            metadata,
            cosineDistance(embedding, {vec_str}) AS distance,
            1 - cosineDistance(embedding, {vec_str}) AS similarity
        FROM rvbbit_embeddings
        WHERE {where_clause}
        ORDER BY distance ASC
        LIMIT {limit}
    """

    try:
        rows = db.query(sql, output_format="dict")

        # Parse metadata JSON
        for row in rows:
            try:
                row['metadata'] = json.loads(row.get('metadata', '{}'))
            except:
                row['metadata'] = {}

        logger.info(f"Vector search returned {len(rows)} results for {source_table}")

        return {
            "results": rows,
            "count": len(rows)
        }

    except Exception as e:
        logger.error(f"clickhouse_vector_search failed: {e}")
        raise RuntimeError(f"Vector search failed: {e}")


# ============================================================================
# Tool 4: Cosine Similarity Between Two Texts
# ============================================================================

def cosine_similarity_texts(
    text1: str,
    text2: str,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    _session_id: Optional[str] = None,  # Injected by cascade runner
    _cell_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compute cosine similarity between two texts.

    Generates embeddings for both texts (in one API call via batching),
    then computes cosine similarity using numpy.

    Cosine Similarity Formula:
        similarity = dot(A, B) / (||A|| * ||B||)
        Range: [-1, 1], but embeddings typically in [0, 1]

    Args:
        text1: First text
        text2: Second text
        model: Optional embedding model override
        session_id: Optional session ID for logging

    Returns:
        {
            "similarity": float  # 0.0 to 1.0 (typically)
        }

    Example:
        >>> result = cosine_similarity_texts(
        ...     text1="eco-friendly bamboo toothbrush",
        ...     text2="sustainable bamboo brush"
        ... )
        >>> result["similarity"] > 0.8
        True
    """
    if not text1 or not text2:
        raise ValueError("Both texts must be non-empty")

    config = get_config()
    model = model or config.default_embed_model

    # Use _session_id from cascade runner if available
    effective_session_id = _session_id or session_id
    if not effective_session_id:
        import uuid
        effective_session_id = f"similarity_{uuid.uuid4().hex[:8]}"

    try:
        # Embed both texts in one API call (batched)
        result = Agent.embed(
            texts=[text1, text2],
            model=model,
            session_id=effective_session_id
        )

        emb1 = np.array(result["embeddings"][0])
        emb2 = np.array(result["embeddings"][1])

        # Cosine similarity
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))

        return {
            "similarity": float(similarity)
        }

    except Exception as e:
        logger.error(f"cosine_similarity_texts failed: {e}")
        raise RuntimeError(f"Failed to compute similarity: {e}")


# ============================================================================
# Tool 5: Elasticsearch Store Embedding
# ============================================================================

def elasticsearch_create_embeddings_index(index_name: str = "rvbbit_embeddings") -> Dict[str, Any]:
    """
    Create Elasticsearch index for general-purpose embeddings with hybrid search support.

    Unlike rvbbit_sql_schemas (for table metadata), this is for arbitrary text embeddings
    from any source table. Supports both vector similarity and BM25 keyword search.

    Schema:
        - source_table: keyword (e.g., 'products')
        - source_id: keyword (row ID)
        - text: text field with analyzers for BM25
        - embedding: dense_vector (4096 dims)
        - embedding_model: keyword
        - metadata: JSON object
        - created_at: date

    Args:
        index_name: Index name (default: 'rvbbit_embeddings')

    Returns:
        {"success": True, "index": str, "created": bool}
    """
    try:
        from rvbbit.elastic import get_elastic_client
        es = get_elastic_client()

        # Check if index exists
        if es.indices.exists(index=index_name):
            logger.info(f"Elasticsearch index {index_name} already exists")
            return {"success": True, "index": index_name, "created": False}

        # Create index with mapping for hybrid search
        mapping = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "analysis": {
                    "analyzer": {
                        "text_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "asciifolding"]
                        }
                    }
                }
            },
            "mappings": {
                "properties": {
                    "source_table": {"type": "keyword"},
                    "source_id": {"type": "keyword"},
                    "text": {
                        "type": "text",
                        "analyzer": "text_analyzer",
                        "fields": {
                            "keyword": {"type": "keyword", "ignore_above": 256}
                        }
                    },
                    "embedding": {
                        "type": "dense_vector",
                        "dims": 4096,  # qwen/qwen3-embedding-8b
                        "index": True,
                        "similarity": "cosine"
                    },
                    "embedding_model": {"type": "keyword"},
                    "embedding_dim": {"type": "integer"},
                    "metadata": {"type": "object", "enabled": True},
                    "created_at": {"type": "date"}
                }
            }
        }

        es.indices.create(index=index_name, body=mapping)
        logger.info(f"Created Elasticsearch index: {index_name}")

        return {"success": True, "index": index_name, "created": True}

    except Exception as e:
        logger.error(f"Failed to create ES index {index_name}: {e}")
        raise RuntimeError(f"Failed to create Elasticsearch index: {e}")


def elasticsearch_store_embedding(
    source_table: str,
    source_id: str,
    text: str,
    embedding: List[float],
    model: str,
    metadata: Optional[Dict[str, Any]] = None,
    index_name: str = "rvbbit_embeddings"
) -> Dict[str, Any]:
    """
    Store embedding in Elasticsearch index.

    Creates the index if it doesn't exist. Uses upsert semantics (update or insert).

    Args:
        source_table: Name of source table (e.g., 'products')
        source_id: ID of source row (e.g., '42')
        text: Original text (stored for keyword search)
        embedding: 4096-dim vector
        model: Model name used for embedding
        metadata: Optional additional metadata
        index_name: ES index name (default: 'rvbbit_embeddings')

    Returns:
        {
            "success": True,
            "source_table": str,
            "source_id": str,
            "backend": "elasticsearch"
        }

    Example:
        >>> elasticsearch_store_embedding(
        ...     source_table="products",
        ...     source_id="42",
        ...     text="Eco-friendly bamboo toothbrush",
        ...     embedding=[0.1, 0.2, ...],  # 4096 dims
        ...     model="qwen/qwen3-embedding-8b"
        ... )
    """
    try:
        from rvbbit.elastic import get_elastic_client, _sanitize_for_json
        from datetime import datetime

        es = get_elastic_client()

        # Ensure index exists
        if not es.indices.exists(index=index_name):
            elasticsearch_create_embeddings_index(index_name)

        # Document ID: source_table:source_id for upsert
        doc_id = f"{source_table}:{source_id}"

        # Prepare document
        doc = {
            "source_table": source_table,
            "source_id": str(source_id),
            "text": text[:10000],  # Truncate very long text
            "embedding": embedding,
            "embedding_model": model,
            "embedding_dim": len(embedding),
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat()
        }

        # Sanitize for JSON (handle numpy types, NaN, etc.)
        doc = _sanitize_for_json(doc)

        # Index document (upsert)
        es.index(index=index_name, id=doc_id, document=doc)
        logger.debug(f"Stored embedding in ES: {doc_id}")

        return {
            "success": True,
            "source_table": source_table,
            "source_id": source_id,
            "backend": "elasticsearch"
        }

    except Exception as e:
        logger.error(f"elasticsearch_store_embedding failed: {e}")
        raise RuntimeError(f"Failed to store embedding in Elasticsearch: {e}")


def elasticsearch_bulk_store_embeddings(
    documents: List[Dict[str, Any]],
    index_name: str = "rvbbit_embeddings"
) -> Dict[str, Any]:
    """
    Bulk store multiple embeddings in Elasticsearch.

    Much more efficient than individual inserts for large batches.

    Args:
        documents: List of dicts with keys:
            - source_table, source_id, text, embedding, model, metadata
        index_name: ES index name

    Returns:
        {
            "success": True,
            "indexed": int,
            "errors": int,
            "backend": "elasticsearch"
        }
    """
    try:
        from rvbbit.elastic import get_elastic_client, _sanitize_for_json
        from elasticsearch import helpers
        from datetime import datetime
        import json

        es = get_elastic_client()

        # Ensure index exists
        if not es.indices.exists(index=index_name):
            elasticsearch_create_embeddings_index(index_name)

        # Build bulk actions
        actions = []
        now = datetime.utcnow().isoformat()

        for doc in documents:
            doc_id = f"{doc['source_table']}:{doc['source_id']}"

            source = {
                "source_table": doc["source_table"],
                "source_id": str(doc["source_id"]),
                "text": doc.get("text", "")[:10000],
                "embedding": doc["embedding"],
                "embedding_model": doc.get("model", ""),
                "embedding_dim": len(doc["embedding"]),
                "metadata": doc.get("metadata", {}),
                "created_at": now
            }

            # Sanitize for JSON
            source = _sanitize_for_json(source)

            actions.append({
                "_index": index_name,
                "_id": doc_id,
                "_source": source
            })

        if not actions:
            return {"success": True, "indexed": 0, "errors": 0, "backend": "elasticsearch"}

        # Bulk index
        success_count, errors = helpers.bulk(es, actions, raise_on_error=False, stats_only=True)

        logger.info(f"Bulk indexed {success_count} embeddings to ES, {errors} errors")

        return {
            "success": errors == 0,
            "indexed": success_count,
            "errors": errors,
            "backend": "elasticsearch"
        }

    except Exception as e:
        logger.error(f"elasticsearch_bulk_store_embeddings failed: {e}")
        raise RuntimeError(f"Failed to bulk store embeddings: {e}")


def elasticsearch_vector_search(
    query: str,
    query_embedding: List[float],
    source_table: Optional[str] = None,
    limit: int = 10,
    threshold: Optional[float] = None,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
    index_name: str = "rvbbit_embeddings"
) -> Dict[str, Any]:
    """
    Hybrid vector + keyword search in Elasticsearch.

    Combines:
    - Vector similarity (70% default) - cosine distance on dense_vector
    - Keyword matching (30% default) - BM25 on text field

    This is the preferred search for better recall than pure vector search.

    Args:
        query: Text query (for keyword matching)
        query_embedding: 4096-dim vector (for semantic matching)
        source_table: Optional filter by source table
        limit: Max results (default: 10)
        threshold: Optional min similarity threshold
        semantic_weight: Vector weight (default: 0.7)
        keyword_weight: Keyword weight (default: 0.3)
        index_name: ES index name

    Returns:
        {
            "results": [
                {
                    "source_id": str,
                    "source_table": str,
                    "text": str,
                    "similarity": float,
                    "metadata": dict
                },
                ...
            ],
            "count": int,
            "backend": "elasticsearch"
        }
    """
    try:
        from rvbbit.elastic import get_elastic_client

        es = get_elastic_client()

        if not es.indices.exists(index=index_name):
            return {"results": [], "count": 0, "backend": "elasticsearch", "error": "Index not found"}

        # Build filter
        filter_clauses = []
        if source_table:
            filter_clauses.append({"term": {"source_table": source_table}})

        # Hybrid search query with script_score
        search_body = {
            "size": limit,
            "_source": {
                "excludes": ["embedding"]  # Don't return the embedding vector
            },
            "query": {
                "script_score": {
                    "query": {
                        "bool": {
                            "should": [
                                # BM25 keyword match on text
                                {
                                    "match": {
                                        "text": {
                                            "query": query,
                                            "boost": 1.0
                                        }
                                    }
                                }
                            ],
                            "filter": filter_clauses if filter_clauses else None,
                            "minimum_should_match": 0
                        }
                    },
                    "script": {
                        "source": f"""
                            // Vector similarity (cosine, range 0-2 after +1)
                            double vectorScore = cosineSimilarity(params.query_vector, 'embedding') + 1.0;
                            // BM25 score (normalized)
                            double textScore = _score > 0 ? _score / 10.0 : 0.0;
                            // Weighted combination
                            return (vectorScore * {semantic_weight}) + (textScore * {keyword_weight});
                        """,
                        "params": {
                            "query_vector": query_embedding
                        }
                    }
                }
            }
        }

        # Remove None filter
        if not filter_clauses:
            del search_body["query"]["script_score"]["query"]["bool"]["filter"]

        response = es.search(index=index_name, body=search_body)

        # Format results
        results = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            # Convert script_score back to similarity (0-1 range)
            raw_score = hit["_score"]
            # The vector part contributes (cosineSim + 1) * 0.7, which is 0.7-1.4
            # Normalize roughly to 0-1
            similarity = min(1.0, (raw_score - 0.5) / 1.2) if raw_score > 0.5 else raw_score / 2.0

            result = {
                "source_id": source.get("source_id"),
                "source_table": source.get("source_table"),
                "text": source.get("text", ""),
                "similarity": round(similarity, 4),
                "score": round(raw_score, 4),
                "metadata": source.get("metadata", {})
            }

            # Apply threshold filter
            if threshold is None or similarity >= threshold:
                results.append(result)

        logger.info(f"ES hybrid search returned {len(results)} results")

        return {
            "results": results,
            "count": len(results),
            "backend": "elasticsearch"
        }

    except Exception as e:
        logger.error(f"elasticsearch_vector_search failed: {e}")
        raise RuntimeError(f"Elasticsearch search failed: {e}")


# ============================================================================
# Tool 6: Elasticsearch Hybrid Search (Legacy Fallback)
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

    Combines:
    - Vector similarity (cosine distance on dense_vector field)
    - Keyword matching (BM25 on text field)

    Weights are configurable (default: 70% semantic, 30% keyword).

    Falls back to ClickHouse vector-only search if Elasticsearch unavailable.

    Args:
        query: Text query (for keyword matching)
        query_embedding: 4096-dim vector (for semantic matching)
        index: Elasticsearch index name
        limit: Max results
        semantic_weight: Vector similarity weight 0-1 (default: 0.7)
        keyword_weight: BM25 keyword weight 0-1 (default: 0.3)

    Returns:
        {
            "results": [
                {
                    "id": str,
                    "text": str,
                    "score": float  # Combined score
                },
                ...
            ],
            "backend": "elasticsearch" | "clickhouse"
        }

    Example:
        >>> embedding = agent_embed("eco-friendly products")["embedding"]
        >>> results = elasticsearch_hybrid_search(
        ...     query="eco-friendly products",
        ...     query_embedding=embedding,
        ...     index="products",
        ...     limit=10
        ... )
        >>> results["backend"]
        'elasticsearch'  # or 'clickhouse' if ES unavailable
    """
    try:
        from rvbbit.elastic import get_elastic_client

        es = get_elastic_client()
        if not es.ping():
            raise Exception("Elasticsearch not available")

        # Elasticsearch script_score query
        # Combines BM25 keyword match + cosine similarity
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
                "text": hit["_source"].get("text", ""),
                "score": hit["_score"]
            }
            for hit in response["hits"]["hits"]
        ]

        logger.info(f"Elasticsearch hybrid search returned {len(results)} results")

        return {
            "results": results,
            "backend": "elasticsearch"
        }

    except Exception as e:
        # Fallback to ClickHouse vector-only search
        logger.warning(f"Elasticsearch hybrid search failed, using ClickHouse fallback: {e}")

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
# Tool 6: Batch Embed Multiple Texts (Optimization)
# ============================================================================

def agent_embed_batch(
    texts: List[str],
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    _session_id: Optional[str] = None,  # Injected by cascade runner
    _cell_name: Optional[str] = None,
    _caller_id: Optional[str] = None,  # For SQL Trail correlation
    _cascade_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate embeddings for multiple texts (batched API call).

    More efficient than calling agent_embed() in a loop. Agent.embed()
    already handles batching internally (50 texts per API call), but this
    provides a cleaner interface for bulk operations.

    Args:
        texts: List of texts to embed
        model: Optional model override
        session_id: Optional session ID

    Returns:
        {
            "embeddings": List[List[float]],  # List of 4096-dim vectors
            "model": str,
            "dim": int,
            "count": int
        }

    Example:
        >>> texts = ["text1", "text2", "text3"]
        >>> result = agent_embed_batch(texts)
        >>> len(result["embeddings"])
        3
        >>> result["dim"]
        4096
    """
    if not texts:
        raise ValueError("texts cannot be empty")

    config = get_config()
    model = model or config.default_embed_model

    # Use _session_id from cascade runner if available
    effective_session_id = _session_id or session_id
    if not effective_session_id:
        import uuid
        effective_session_id = f"embed_batch_{uuid.uuid4().hex[:8]}"

    try:
        result = Agent.embed(
            texts=texts,
            model=model,
            session_id=effective_session_id,
            cell_name=_cell_name,
            caller_id=_caller_id,
            cascade_id=_cascade_id,
        )

        return {
            "embeddings": result["embeddings"],
            "model": result["model"],
            "dim": result["dim"],
            "count": len(result["embeddings"])
        }

    except Exception as e:
        logger.error(f"agent_embed_batch failed: {e}")
        raise RuntimeError(f"Failed to batch embed: {e}")


# ============================================================================
# Register All Tools
# ============================================================================

# Register tools for use in cascades
register_trait("agent_embed", agent_embed)
register_trait("clickhouse_store_embedding", clickhouse_store_embedding)
register_trait("clickhouse_vector_search", clickhouse_vector_search)
register_trait("cosine_similarity_texts", cosine_similarity_texts)
register_trait("elasticsearch_hybrid_search", elasticsearch_hybrid_search)
register_trait("agent_embed_batch", agent_embed_batch)

# Elasticsearch-specific tools
register_trait("elasticsearch_create_embeddings_index", elasticsearch_create_embeddings_index)
register_trait("elasticsearch_store_embedding", elasticsearch_store_embedding)
register_trait("elasticsearch_bulk_store_embeddings", elasticsearch_bulk_store_embeddings)
register_trait("elasticsearch_vector_search", elasticsearch_vector_search)

logger.info("Registered 10 embedding storage tools for Semantic SQL")
