"""
Search API - Unified search interface for RAG, SQL, Memory, and Message search

Provides endpoints for:
- /api/search/rag - Semantic search over indexed documents
- /api/search/rag/sources - List available RAG indices and documents
- /api/search/sql - Semantic search over SQL schemas
- /api/search/memory - Search conversational memory banks
- /api/search/memory/banks - List available memory banks

Message search reuses existing /api/sextant/embedding-search endpoint
"""
import os
import sys
import json
from typing import Optional
from flask import Blueprint, jsonify, request

# Add windlass to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from rvbbit.db_adapter import get_db
from rvbbit.config import get_config
from rvbbit.rag.context import RagContext
from rvbbit.rag.store import search_chunks, list_sources
from rvbbit.sql_tools.tools import sql_search
from rvbbit.memory import get_memory_system
import math

search_bp = Blueprint('search', __name__, url_prefix='/api/search')


def sanitize_for_json(obj):
    """Recursively sanitize an object for JSON serialization.

    Converts NaN/Infinity to None, which becomes null in JSON.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj


@search_bp.route('/rag', methods=['POST'])
def rag_search_endpoint():
    """
    Semantic search over RAG-indexed documents.

    Request body:
        {
            "query": str,
            "rag_id": str,  # Which RAG index to search
            "k": int,  # Number of results (default: 5)
            "score_threshold": float,  # Optional minimum score
            "doc_filter": str  # Optional document path filter
        }

    Returns:
        {
            "results": [{
                "chunk_id": str,
                "doc_id": str,
                "source": str,  # File path
                "lines": str,  # Line range (e.g., "45-67")
                "score": float,  # Similarity score
                "snippet": str,  # Preview text
                "metadata": {...}  # Additional metadata
            }],
            "query": str,
            "rag_id": str,
            "directory": str
        }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        query = data.get('query')
        if not query:
            return jsonify({"error": "query is required"}), 400

        rag_id = data.get('rag_id')
        if not rag_id:
            return jsonify({"error": "rag_id is required"}), 400

        k = data.get('k', 5)
        score_threshold = data.get('score_threshold')
        doc_filter = data.get('doc_filter')

        # Get the embedding model and verify consistency
        db = get_db()
        model_query = f"""
            SELECT
                embedding_model,
                COUNT(*) as count,
                length(embedding) as embedding_dim
            FROM rag_chunks
            WHERE rag_id = '{rag_id}'
            GROUP BY embedding_model, length(embedding)
            ORDER BY count DESC
        """
        model_result = db.query(model_query)

        if not model_result:
            return jsonify({
                "error": f"No chunks found for RAG index: {rag_id}",
                "hint": "The index may be empty or not exist."
            }), 404

        # Check if there are multiple embedding models in this index
        if len(model_result) > 1:
            models_info = [f"{r['embedding_model']} ({r['count']} chunks, {r['embedding_dim']} dims)" for r in model_result]
            return jsonify({
                "error": f"Mixed embedding models in RAG index: {rag_id}",
                "hint": f"Found: {', '.join(models_info)}. Re-index with a single model."
            }), 400

        embed_model = model_result[0]['embedding_model']
        embedding_dim = model_result[0]['embedding_dim']

        # Create RAG context with the correct embedding model
        rag_ctx = RagContext(
            rag_id=rag_id,
            directory="",  # Not needed for search
            embed_model=embed_model,  # Use the model from the index!
            stats={},
            session_id="ui_search",
            cascade_id="search_ui",
            cell_name="rag_search",
            trace_id=None,
            parent_id=None
        )

        # Debug: Log what we're using and test the embedding
        print(f"[RAG Search Debug] Index: {rag_id}, Model: {embed_model}, Expected dims: {embedding_dim}")

        # Test: Embed the query to see what dimension we actually get
        from rvbbit.rag.indexer import embed_texts
        embed_result = embed_texts(
            texts=[query],
            model=embed_model,
            session_id="ui_search_test",
            trace_id=None,
            parent_id=None,
            cell_name="rag_search",
            cascade_id="search_ui"
        )
        actual_query_dim = embed_result["dim"]
        print(f"[RAG Search Debug] Query embedding dimension: {actual_query_dim}")

        if actual_query_dim != embedding_dim:
            return jsonify({
                "error": f"Cannot search - embedding dimension mismatch",
                "details": f"Index: {embedding_dim} dims | Current model '{embed_model}': {actual_query_dim} dims",
                "hint": "Your RAG index was created with different embeddings than what the model currently returns. This can happen if: (1) The model API changed, (2) A different model was actually used during indexing, or (3) Dimensions were truncated.",
                "solution": f"Re-index to fix: windlass rag index <directory> --rag-id {rag_id}"
            }), 400

        # Execute search
        try:
            results = search_chunks(
                rag_ctx=rag_ctx,
                query=query,
                k=k,
                score_threshold=score_threshold,
                doc_filter=doc_filter
            )
        except Exception as search_error:
            # Add more debug info
            error_str = str(search_error)
            print(f"[RAG Search Error] {error_str}")

            # Try to extract actual dimensions from error if possible
            if "equal sizes" in error_str or "cosineDistance" in error_str:
                return jsonify({
                    "error": f"Embedding dimension mismatch",
                    "hint": f"Index expects {embedding_dim} dims ({embed_model}). The query embedding returned a different size. Check if the model API is working correctly.",
                    "debug": error_str[:200]
                }), 400
            raise

        # Sanitize results to remove NaN values
        sanitized_results = sanitize_for_json(results)

        return jsonify({
            "results": sanitized_results,
            "query": query,
            "rag_id": rag_id,
            "directory": rag_ctx.directory
        })

    except ValueError as e:
        # Handle specific error cases with helpful messages
        error_msg = str(e)
        if "equal sizes" in error_msg or "cosineDistance" in error_msg:
            # Try to get the actual dimensions for debugging
            debug_info = f"Index model: {embed_model}, Index dimensions: {embedding_dim}"
            return jsonify({
                "error": "Embedding dimension mismatch",
                "hint": f"{debug_info}. The query embedding doesn't match the stored embeddings. This can happen if the model API changed or returned a different dimension."
            }), 400
        return jsonify({"error": f"RAG search failed: {error_msg}"}), 400
    except Exception as e:
        error_msg = str(e)
        if "equal sizes" in error_msg or "cosineDistance" in error_msg:
            return jsonify({
                "error": "Embedding dimension mismatch",
                "hint": f"Index model: {embed_model if 'embed_model' in locals() else 'unknown'}, Dims: {embedding_dim if 'embedding_dim' in locals() else 'unknown'}. The query embedding size doesn't match the stored embeddings."
            }), 400
        return jsonify({"error": f"RAG search failed: {error_msg}"}), 500


@search_bp.route('/rag/sources', methods=['GET'])
def list_rag_sources():
    """
    List available RAG indices and optionally documents within an index.

    Query parameters:
        rag_id: str (optional) - If provided, list documents in this index

    Returns:
        If no rag_id:
            {
                "indices": [{
                    "rag_id": str,
                    "directory": str,
                    "doc_count": int,
                    "chunk_count": int
                }]
            }

        If rag_id provided:
            {
                "rag_id": str,
                "documents": [{
                    "doc_id": str,
                    "rel_path": str,
                    "chunk_count": int,
                    "size": int
                }]
            }
    """
    try:
        rag_id = request.args.get('rag_id')
        db = get_db()

        if rag_id:
            # List documents in specific index
            cfg = get_config()
            rag_ctx = RagContext(
                rag_id=rag_id,
                directory="",
                embed_model=cfg.default_embed_model,
                stats={},
                session_id="ui_search",
                cascade_id="search_ui",
                cell_name="list_sources",
                trace_id=None,
                parent_id=None
            )

            documents = list_sources(rag_ctx)

            return jsonify({
                "rag_id": rag_id,
                "documents": documents
            })
        else:
            # List all RAG indices
            indices_query = """
                SELECT
                    rag_id,
                    COUNT(DISTINCT doc_id) as doc_count,
                    COUNT(*) as chunk_count
                FROM rag_chunks
                GROUP BY rag_id
                ORDER BY rag_id
            """

            indices = db.query(indices_query)

            # Note: directory is not stored in ClickHouse, only file paths
            # We could derive a common prefix, but for now just return rag_id
            result_indices = [
                {
                    "rag_id": idx['rag_id'],
                    "doc_count": idx['doc_count'],
                    "chunk_count": idx['chunk_count']
                }
                for idx in indices
            ]

            return jsonify({"indices": result_indices})

    except Exception as e:
        return jsonify({"error": f"Failed to list RAG sources: {str(e)}"}), 500


@search_bp.route('/sql', methods=['POST'])
def sql_schema_search():
    """
    Semantic search over SQL database schemas.

    Request body:
        {
            "query": str,  # Natural language query (e.g., "tables with user data")
            "k": int,  # Number of results (default: 10)
            "score_threshold": float  # Minimum similarity (default: 0.3)
        }

    Returns:
        {
            "tables": [{
                "qualified_name": str,
                "database": str,
                "schema": str,
                "table_name": str,
                "row_count": int,
                "columns": [...],  # Column metadata
                "sample_rows": [...],  # Sample data
                "match_score": float
            }],
            "query": str,
            "rag_id": str,
            "total_results": int
        }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        query = data.get('query')
        if not query:
            return jsonify({"error": "query is required"}), 400

        k = data.get('k', 10)
        score_threshold = data.get('score_threshold', 0.3)

        # Use the sql_search tool directly (it returns JSON string)
        result_json = sql_search(query=query, k=k, score_threshold=score_threshold)
        result = json.loads(result_json)

        # Sanitize to remove NaN values
        sanitized_result = sanitize_for_json(result)

        return jsonify(sanitized_result)

    except Exception as e:
        return jsonify({"error": f"SQL search failed: {str(e)}"}), 500


@search_bp.route('/memory', methods=['POST'])
def memory_search():
    """
    Search conversational memory banks.

    Request body:
        {
            "memory_name": str,  # Which memory bank to search
            "query": str,
            "limit": int  # Number of results (default: 5)
        }

    Returns:
        {
            "results": [{
                "message_id": str,
                "content": str,
                "role": str,  # "user" or "assistant"
                "timestamp": str,
                "session_id": str,
                "cascade_id": str,
                "cell_name": str,
                "score": float
            }],
            "memory_name": str,
            "query": str
        }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        memory_name = data.get('memory_name')
        if not memory_name:
            return jsonify({"error": "memory_name is required"}), 400

        query = data.get('query')
        if not query:
            return jsonify({"error": "query is required"}), 400

        limit = data.get('limit', 5)

        # Get memory system
        memory_system = get_memory_system()

        # Check if memory exists
        if not memory_system.exists(memory_name):
            return jsonify({
                "error": f"Memory bank '{memory_name}' not found",
                "hint": "The memory bank may not exist or has no messages."
            }), 404

        # Get RAG context (will build index on-the-fly if needed)
        try:
            rag_ctx = memory_system._get_rag_context(memory_name)
            if not rag_ctx:
                return jsonify({
                    "error": "Failed to build memory index",
                    "hint": f"Memory bank '{memory_name}' has no messages or indexing failed."
                }), 500
        except Exception as index_error:
            error_str = str(index_error)
            print(f"[Memory Index Error] {error_str}")

            if "No successful provider responses" in error_str or "404" in error_str:
                return jsonify({
                    "error": "Cannot build memory index - embedding failed",
                    "hint": "The system needs to embed messages to make them searchable. Check your OPENROUTER_API_KEY and ensure the embedding model is available.",
                    "debug": error_str[:300]
                }), 500
            raise

        # Search using RAG store directly
        from rvbbit.rag.store import search_chunks
        search_results = search_chunks(rag_ctx, query, k=limit)

        # Convert search results to memory format with metadata
        results = []
        for r in search_results:
            # Parse the original message JSON from metadata
            try:
                msg_metadata = json.loads(r.get('metadata', '{}'))
                results.append({
                    "message_id": r.get('doc_id', ''),
                    "content": r.get('snippet', ''),
                    "score": r.get('score', 0.0),
                    "role": msg_metadata.get('role', 'unknown'),
                    "timestamp": msg_metadata.get('timestamp', ''),
                    "session_id": msg_metadata.get('session_id', ''),
                    "cascade_id": msg_metadata.get('cascade_id', ''),
                    "cell_name": msg_metadata.get('cell_name', '')
                })
            except Exception as e:
                # If metadata parsing fails, include what we have
                results.append({
                    "message_id": r.get('doc_id', ''),
                    "content": r.get('snippet', ''),
                    "score": r.get('score', 0.0),
                    "role": 'unknown',
                    "timestamp": '',
                    "session_id": '',
                    "cascade_id": '',
                    "cell_name": ''
                })

        # Sanitize results
        sanitized_results = sanitize_for_json(results)

        return jsonify({
            "results": sanitized_results,
            "memory_name": memory_name,
            "query": query
        })

    except json.JSONDecodeError as e:
        return jsonify({
            "error": "Failed to parse memory search results",
            "hint": f"Invalid JSON returned from memory system. Position: {e.pos}"
        }), 500
    except Exception as e:
        return jsonify({"error": f"Memory search failed: {str(e)}"}), 500


@search_bp.route('/sql-elastic', methods=['POST'])
def sql_elastic_search():
    """
    Elasticsearch-based SQL schema search with hybrid ranking.

    Request body:
        {
            "query": str,
            "k": int,  # Number of results (default: 10)
            "min_row_count": int  # Optional filter
        }

    Returns:
        {
            "tables": [{...}],  # Same format as SQL search but with better ranking
            "query": str,
            "source": "elasticsearch",
            "total_results": int
        }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        query = data.get('query')
        if not query:
            return jsonify({"error": "query is required"}), 400

        k = data.get('k', 10)
        min_row_count = data.get('min_row_count')

        # Check if Elasticsearch is available
        try:
            from rvbbit.elastic import get_elastic_client, hybrid_search_sql_schemas
            from rvbbit.rag.indexer import embed_texts
            from rvbbit.config import get_config

            es = get_elastic_client()
            if not es.ping():
                return jsonify({
                    "error": "Elasticsearch not available",
                    "hint": "Start Elasticsearch with: ./scripts/start-elasticsearch.sh"
                }), 503

        except ImportError:
            return jsonify({
                "error": "Elasticsearch not configured",
                "hint": "Install: pip install elasticsearch"
            }), 503

        # Embed the query
        cfg = get_config()
        embed_result = embed_texts(
            texts=[query],
            model=cfg.default_embed_model,
            session_id="ui_search",
            trace_id=None,
            parent_id=None,
            cell_name="sql_elastic_search",
            cascade_id="search_ui"
        )
        query_embedding = embed_result['embeddings'][0]

        # Hybrid search
        results = hybrid_search_sql_schemas(
            query=query,
            query_embedding=query_embedding,
            k=k,
            min_row_count=min_row_count
        )

        # Sanitize
        sanitized_results = sanitize_for_json(results)

        return jsonify({
            "tables": sanitized_results,
            "query": query,
            "source": "elasticsearch",
            "total_results": len(sanitized_results)
        })

    except Exception as e:
        return jsonify({"error": f"Elasticsearch search failed: {str(e)}"}), 500


@search_bp.route('/memory/banks', methods=['GET'])
def list_memory_banks():
    """
    List available memory banks.

    Returns:
        {
            "banks": [{
                "name": str,
                "message_count": int,
                "last_updated": str,
                "summary": str,
                "cascades_using": [str]  # List of cascade IDs using this memory
            }]
        }
    """
    try:
        memory_system = get_memory_system()

        # List all memory banks
        memory_names = memory_system.list_all()

        banks = []
        for name in memory_names:
            metadata = memory_system.get_metadata(name)

            banks.append({
                "name": name,
                "message_count": metadata.get('message_count', 0),
                "last_updated": metadata.get('last_updated', 'Never'),
                "summary": metadata.get('summary', f'Conversational memory bank: {name}'),
                "cascades_using": metadata.get('cascades_using', [])
            })

        return jsonify({"banks": banks})

    except Exception as e:
        return jsonify({"error": f"Failed to list memory banks: {str(e)}"}), 500
