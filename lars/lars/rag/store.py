"""
RAG Store - ClickHouse Vector Search Implementation

Provides semantic search over RAG chunks using ClickHouse's native cosineDistance().
No more Python cosine similarity - ClickHouse handles it natively.

Key functions:
- search_chunks(): Semantic search with optional filters
- read_chunk(): Get a specific chunk by ID
- list_sources(): List all indexed documents
"""
from typing import Any, Dict, List, Optional

from .context import RagContext
from .indexer import embed_texts


def list_sources(rag_ctx: RagContext) -> List[Dict[str, Any]]:
    """
    List all documents indexed in a RAG context.

    Args:
        rag_ctx: RAG context with rag_id

    Returns:
        List of document metadata dicts
    """
    from ..db_adapter import get_db

    db = get_db()
    results = db.query(f"""
        SELECT
            doc_id,
            rel_path,
            chunk_count,
            file_size as size,
            mtime
        FROM rag_manifests
        WHERE rag_id = '{rag_ctx.rag_id}'
        ORDER BY rel_path
    """)

    return results


def read_chunk(rag_ctx: RagContext, chunk_id: str) -> Dict[str, Any]:
    """
    Get a specific chunk by ID.

    Args:
        rag_ctx: RAG context with rag_id
        chunk_id: Chunk ID (format: {doc_id}_{chunk_index})

    Returns:
        Chunk data dict

    Raises:
        ValueError: If chunk not found
    """
    from ..db_adapter import get_db

    db = get_db()

    # Parse chunk_id to get doc_id and chunk_index
    parts = chunk_id.rsplit('_', 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid chunk_id format: {chunk_id}")

    doc_id = parts[0]
    try:
        chunk_index = int(parts[1])
    except ValueError:
        raise ValueError(f"Invalid chunk_id format: {chunk_id}")

    results = db.query(f"""
        SELECT
            doc_id,
            rel_path,
            chunk_index,
            start_line,
            end_line,
            text
        FROM rag_chunks
        WHERE rag_id = '{rag_ctx.rag_id}'
          AND doc_id = '{doc_id}'
          AND chunk_index = {chunk_index}
        LIMIT 1
    """)

    if not results:
        raise ValueError(f"Chunk {chunk_id} not found in rag_id={rag_ctx.rag_id}")

    rec = results[0]
    return {
        "chunk_id": chunk_id,
        "doc_id": rec["doc_id"],
        "source": rec["rel_path"],
        "lines": [int(rec["start_line"]), int(rec["end_line"])],
        "text": rec["text"],
    }


def search_chunks(
    rag_ctx: RagContext,
    query: str,
    k: int = 5,
    score_threshold: Optional[float] = None,
    doc_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Semantic search using ClickHouse cosineDistance.

    Args:
        rag_ctx: RAG context with rag_id and session info
        query: Search query text
        k: Number of results to return
        score_threshold: Minimum similarity score (0-1, higher = more similar)
        doc_filter: Optional filter on rel_path (substring match)

    Returns:
        List of search results with chunk data and similarity scores
    """
    from ..db_adapter import get_db

    db = get_db()

    # Embed query using Agent.embed() - same model as the index
    embed_result = embed_texts(
        texts=[query],
        model=rag_ctx.embed_model,
        session_id=rag_ctx.session_id,
        trace_id=rag_ctx.trace_id,
        parent_id=rag_ctx.parent_id,
        cell_name=rag_ctx.cell_name,
        cascade_id=rag_ctx.cascade_id,
    )
    query_vec = embed_result["embeddings"][0]

    # Build WHERE clause
    conditions = [f"rag_id = '{rag_ctx.rag_id}'"]
    if doc_filter:
        # Escape single quotes in filter
        safe_filter = doc_filter.replace("'", "''")
        conditions.append(f"rel_path LIKE '%{safe_filter}%'")

    where_clause = " AND ".join(conditions)

    # Use ClickHouse vector search
    results = db.vector_search(
        table='rag_chunks',
        embedding_col='embedding',
        query_vector=query_vec,
        limit=k * 2 if score_threshold else k,  # Fetch extra if filtering
        where=where_clause,
        select_cols="doc_id, rel_path, chunk_index, start_line, end_line, text"
    )

    # Filter by threshold if specified (similarity = 1 - distance)
    if score_threshold is not None:
        results = [r for r in results if r['similarity'] >= score_threshold]

    # Limit to k results
    results = results[:k]

    # Format results
    formatted = []
    for r in results:
        chunk_id = f"{r['doc_id']}_{r['chunk_index']}"
        formatted.append({
            "chunk_id": chunk_id,
            "doc_id": r["doc_id"],
            "source": r["rel_path"],
            "lines": [int(r["start_line"]), int(r["end_line"])],
            "score": float(r["similarity"]),
            "snippet": r["text"][:400].strip(),
        })

    return formatted


def get_chunk_by_id(rag_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific chunk by rag_id and chunk_id (convenience function).

    Args:
        rag_id: RAG index ID
        chunk_id: Chunk ID

    Returns:
        Chunk data dict or None if not found
    """
    from ..db_adapter import get_db

    db = get_db()

    # Parse chunk_id
    parts = chunk_id.rsplit('_', 1)
    if len(parts) != 2:
        return None

    doc_id = parts[0]
    try:
        chunk_index = int(parts[1])
    except ValueError:
        return None

    results = db.query(f"""
        SELECT
            doc_id,
            rel_path,
            chunk_index,
            start_line,
            end_line,
            text
        FROM rag_chunks
        WHERE rag_id = '{rag_id}'
          AND doc_id = '{doc_id}'
          AND chunk_index = {chunk_index}
        LIMIT 1
    """)

    if not results:
        return None

    rec = results[0]
    return {
        "chunk_id": chunk_id,
        "doc_id": rec["doc_id"],
        "source": rec["rel_path"],
        "lines": [int(rec["start_line"]), int(rec["end_line"])],
        "text": rec["text"],
    }


def clear_cache():
    """
    Clear any cached data.

    In the ClickHouse implementation, there's no local cache to clear.
    This function is kept for backward compatibility.
    """
    pass  # No-op - ClickHouse handles caching internally
