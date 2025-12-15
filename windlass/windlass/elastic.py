"""
Elasticsearch adapter for Windlass - Hybrid semantic + keyword search

Use cases:
- SQL schema search (structured documents with nested columns)
- RAG documents (when you want hybrid search)
- Code search (syntax + semantic)

Why Elastic for SQL schemas:
- Control result size (exclude sample_rows from _source)
- Hybrid search (BM25 keywords + vector similarity)
- Structured queries (filter by row_count, database, etc.)
- Better than chunked text for structured data
"""
import os
import logging
from typing import List, Dict, Any, Optional
from elasticsearch import Elasticsearch, helpers

logger = logging.getLogger(__name__)

# Global client instance
_es_client: Optional[Elasticsearch] = None


def get_elastic_client() -> Elasticsearch:
    """Get or create Elasticsearch client."""
    global _es_client

    if _es_client is None:
        es_host = os.getenv('WINDLASS_ELASTICSEARCH_HOST', 'http://localhost:9200')
        _es_client = Elasticsearch([es_host])

        # Verify connection
        if not _es_client.ping():
            raise ConnectionError(f"Cannot connect to Elasticsearch at {es_host}")

        logger.info(f"Connected to Elasticsearch at {es_host}")

    return _es_client


def create_sql_schema_index():
    """Create index for SQL schema documents with mapping for hybrid search."""
    es = get_elastic_client()

    index_name = "windlass_sql_schemas"

    # Delete existing index if it exists
    if es.indices.exists(index=index_name):
        es.indices.delete(index=index_name)
        logger.info(f"Deleted existing index: {index_name}")

    # Create index with mapping
    mapping = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "tokenizer": {
                    "edge_ngram_tokenizer": {
                        "type": "edge_ngram",
                        "min_gram": 2,
                        "max_gram": 20,
                        "token_chars": ["letter", "digit"]
                    }
                },
                "analyzer": {
                    "sql_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding"]
                    },
                    "sql_ngram_analyzer": {
                        "type": "custom",
                        "tokenizer": "edge_ngram_tokenizer",
                        "filter": ["lowercase"]
                    },
                    "sql_search_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase"]
                    }
                }
            }
        },
        "mappings": {
            "properties": {
                # Identifiers
                "qualified_name": {"type": "keyword"},
                "database": {"type": "keyword"},
                "schema": {"type": "keyword"},
                "table_name": {
                    "type": "text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "ngram": {
                            "type": "text",
                            "analyzer": "sql_ngram_analyzer",
                            "search_analyzer": "sql_search_analyzer"
                        }
                    },
                    "analyzer": "sql_analyzer"
                },

                # Metadata
                "description": {
                    "type": "text",
                    "analyzer": "sql_analyzer"
                },
                "row_count": {"type": "long"},
                "table_type": {"type": "keyword"},

                # Columns (nested for structured queries)
                "columns": {
                    "type": "nested",
                    "properties": {
                        "name": {
                            "type": "text",
                            "fields": {
                                "keyword": {"type": "keyword"},
                                "ngram": {
                                    "type": "text",
                                    "analyzer": "sql_ngram_analyzer",
                                    "search_analyzer": "sql_search_analyzer"
                                }
                            },
                            "analyzer": "sql_analyzer"
                        },
                        "type": {"type": "keyword"},
                        "nullable": {"type": "boolean"},
                        "distribution": {"type": "object", "enabled": False},  # Don't index distributions
                        "min_value": {"type": "keyword"},
                        "max_value": {"type": "keyword"}
                    }
                },

                # Sample data (stored but not indexed - exclude from search)
                "sample_rows": {"type": "object", "enabled": False},

                # Vector embedding for semantic search
                "embedding": {
                    "type": "dense_vector",
                    "dims": 4096,  # qwen/qwen3-embedding-8b
                    "index": True,
                    "similarity": "cosine"
                },
                "embedding_model": {"type": "keyword"},

                # Timestamps
                "indexed_at": {"type": "date"}
            }
        }
    }

    es.indices.create(index=index_name, body=mapping)
    logger.info(f"Created index: {index_name}")
    return index_name


def index_sql_schema(qualified_name: str, schema_data: Dict[str, Any]):
    """Index a SQL schema as a structured Elasticsearch document.

    Args:
        qualified_name: Unique ID (e.g., "postgres.public.users")
        schema_data: Dict with table, columns, row_count, description, embedding, etc.
    """
    es = get_elastic_client()
    index_name = "windlass_sql_schemas"

    # Ensure index exists
    if not es.indices.exists(index=index_name):
        create_sql_schema_index()

    # Prepare document
    doc = {
        "qualified_name": qualified_name,
        "database": schema_data.get('database', ''),
        "schema": schema_data.get('schema', ''),
        "table_name": schema_data.get('table_name', ''),
        "description": schema_data.get('description', ''),
        "row_count": schema_data.get('row_count', 0),
        "table_type": schema_data.get('table_type', 'TABLE'),
        "columns": schema_data.get('columns', []),
        "sample_rows": schema_data.get('sample_rows', []),  # Stored but excluded from search results
        "embedding": schema_data.get('embedding'),
        "embedding_model": schema_data.get('embedding_model', ''),
        "indexed_at": schema_data.get('indexed_at', None)
    }

    # Index document
    es.index(index=index_name, id=qualified_name, document=doc)
    logger.debug(f"Indexed SQL schema: {qualified_name}")


def bulk_index_sql_schemas(schemas: List[Dict[str, Any]]):
    """Bulk index multiple SQL schemas for efficiency."""
    es = get_elastic_client()
    index_name = "windlass_sql_schemas"

    # Ensure index exists
    if not es.indices.exists(index=index_name):
        create_sql_schema_index()

    # Prepare bulk actions
    actions = []
    for schema in schemas:
        action = {
            "_index": index_name,
            "_id": schema['qualified_name'],
            "_source": {
                "qualified_name": schema['qualified_name'],
                "database": schema.get('database', ''),
                "schema": schema.get('schema', ''),
                "table_name": schema.get('table_name', ''),
                "description": schema.get('description', ''),
                "row_count": schema.get('row_count', 0),
                "table_type": schema.get('table_type', 'TABLE'),
                "columns": schema.get('columns', []),
                "sample_rows": schema.get('sample_rows', []),
                "embedding": schema.get('embedding'),
                "embedding_model": schema.get('embedding_model', ''),
                "indexed_at": schema.get('indexed_at')
            }
        }
        actions.append(action)

    # Bulk index
    if actions:
        try:
            success_count, errors = helpers.bulk(es, actions, raise_on_error=False, stats_only=False)

            # errors is a list of tuples: (success, error_dict) where success is bool
            failed_items = [e for e in errors if not e[0]]

            if failed_items:
                logger.warning(f"Bulk indexing: {success_count} succeeded, {len(failed_items)} failed")
                # Log first few failures
                for item in failed_items[:5]:
                    logger.warning(f"  Failed: {item[1]}")
            else:
                logger.info(f"Bulk indexed {success_count} SQL schemas successfully")

            return success_count
        except Exception as e:
            logger.error(f"Bulk indexing error: {e}")
            # Try simple approach - index one by one to find the problem
            success_count = 0
            for action in actions:
                try:
                    es.index(
                        index=action['_index'],
                        id=action['_id'],
                        document=action['_source']
                    )
                    success_count += 1
                except Exception as index_error:
                    logger.warning(f"Failed to index {action['_id']}: {index_error}")

            return success_count

    return 0


def hybrid_search_sql_schemas(
    query: str,
    query_embedding: List[float],
    k: int = 10,
    min_row_count: Optional[int] = None,
    database_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Hybrid search: Combine BM25 keyword + vector similarity.

    Args:
        query: Natural language query
        query_embedding: Query vector (4096 dims for qwen)
        k: Number of results
        min_row_count: Filter tables with at least this many rows
        database_filter: Filter by database name

    Returns:
        List of matching tables with controlled fields (no huge sample_rows)
    """
    es = get_elastic_client()
    index_name = "windlass_sql_schemas"

    # Build query with hybrid search
    search_body = {
        "size": k,
        "_source": {
            # CRITICAL: Exclude heavy fields to reduce result size
            "excludes": ["sample_rows", "embedding"]
        },
        "query": {
            "script_score": {
                "query": {
                    "bool": {
                        "should": [
                            # Wildcard substring match on table name (matches anywhere)
                            {
                                "wildcard": {
                                    "table_name": {
                                        "value": f"*{query.lower()}*",
                                        "boost": 10.0
                                    }
                                }
                            },
                            # N-gram prefix match
                            {
                                "match": {
                                    "table_name.ngram": {
                                        "query": query,
                                        "boost": 5.0
                                    }
                                }
                            },
                            # Wildcard on qualified name (full path)
                            {
                                "wildcard": {
                                    "qualified_name": {
                                        "value": f"*{query.lower()}*",
                                        "boost": 8.0
                                    }
                                }
                            },
                            # Fuzzy match on table name (typo tolerance)
                            {
                                "match": {
                                    "table_name": {
                                        "query": query,
                                        "fuzziness": "AUTO",
                                        "boost": 3.0
                                    }
                                }
                            },
                            # Match in description
                            {
                                "match": {
                                    "description": {
                                        "query": query,
                                        "fuzziness": "AUTO",
                                        "boost": 2.0
                                    }
                                }
                            },
                            # Nested column name wildcard
                            {
                                "nested": {
                                    "path": "columns",
                                    "query": {
                                        "wildcard": {
                                            "columns.name": {
                                                "value": f"*{query.lower()}*",
                                                "boost": 4.0
                                            }
                                        }
                                    }
                                }
                            }
                        ],
                        "filter": []
                    }
                },
                "script": {
                    "source": """
                        // Check if embedding exists
                        if (doc['embedding'].size() == 0) {
                            // No embedding - use text score only
                            return _score > 0 ? _score : 0.1;
                        }
                        // Vector similarity (70% weight)
                        double vectorScore = cosineSimilarity(params.query_vector, 'embedding') + 1.0;
                        // BM25 score (30% weight) - _score from the query
                        double textScore = _score > 0 ? _score / 10.0 : 0.0;
                        // Combine: 70% vector + 30% keyword
                        return (vectorScore * 0.7) + (textScore * 0.3);
                    """,
                    "params": {
                        "query_vector": query_embedding
                    }
                }
            }
        }
    }

    # Add filters
    filters = search_body["query"]["script_score"]["query"]["bool"]["filter"]

    if min_row_count:
        filters.append({"range": {"row_count": {"gte": min_row_count}}})

    if database_filter:
        filters.append({"term": {"database": database_filter}})

    # Execute search
    response = es.search(index=index_name, body=search_body)

    # Format results
    results = []
    for hit in response['hits']['hits']:
        source = hit['_source']
        results.append({
            "qualified_name": source.get('qualified_name'),
            "database": source.get('database'),
            "schema": source.get('schema'),
            "table_name": source.get('table_name'),
            "description": source.get('description'),
            "row_count": source.get('row_count'),
            "columns": source.get('columns', []),
            "match_score": hit['_score'],
            # Notice: NO sample_rows! Much smaller payload to LLM
        })

    return results


def get_index_stats(index_name: str = "windlass_sql_schemas") -> Dict[str, Any]:
    """Get statistics about an index."""
    es = get_elastic_client()

    if not es.indices.exists(index=index_name):
        return {"exists": False}

    stats = es.indices.stats(index=index_name)
    index_stats = stats['indices'].get(index_name, {})

    return {
        "exists": True,
        "doc_count": index_stats.get('total', {}).get('docs', {}).get('count', 0),
        "size_bytes": index_stats.get('total', {}).get('store', {}).get('size_in_bytes', 0)
    }
