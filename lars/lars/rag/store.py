"""
RAG Store - Vector Search Implementation

Provides semantic search over RAG chunks using DuckDB VSS.

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
    Semantic search using DuckDB VSS.

    Args:
        rag_ctx: RAG context with rag_id and session info
        query: Search query text
        k: Number of results to return
        score_threshold: Minimum similarity score (0-1, higher = more similar)
        doc_filter: Optional filter on rel_path (substring match)

    Returns:
        List of search results with chunk data and similarity scores
    """
    from .duckdb_store import query_chunks

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
    query_dim = int(embed_result.get("dim") or 0)

    expected_dim = int(rag_ctx.embedding_dim or 0) if getattr(rag_ctx, "embedding_dim", 0) else 0
    if expected_dim and query_dim and query_dim != expected_dim:
        raise ValueError(
            f"Embedding dimension mismatch (index {expected_dim} dims, query {query_dim} dims). "
            "Re-index with the current embedding model to fix."
        )

    embedding_dim = expected_dim or query_dim
    if not embedding_dim:
        raise ValueError("Could not determine embedding dimension for Chroma query.")

    # Pull more results up-front if we have post-filters.
    fetch_n = int(k)
    if score_threshold is not None or doc_filter:
        fetch_n = max(fetch_n * 4, fetch_n + 10)

    raw = query_chunks(
        embed_model=rag_ctx.embed_model,
        embedding_dim=embedding_dim,
        rag_id=rag_ctx.rag_id,
        query_embedding=query_vec,
        n_results=fetch_n,
    )

    # Chroma returns nested lists (one list per query vector).
    ids = (raw.get("ids") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]

    # Format results
    formatted = []
    for idx, meta in enumerate(metadatas):
        if not meta:
            continue

        rel_path = str(meta.get("rel_path") or "")
        if doc_filter and doc_filter not in rel_path:
            continue

        distance = None
        try:
            distance = float(distances[idx]) if distances and idx < len(distances) else None
        except Exception:
            distance = None

        similarity = None
        if distance is not None:
            # Default Chroma distance for cosine is (1 - cosine_similarity).
            similarity = 1.0 - distance
        else:
            similarity = 0.0

        if score_threshold is not None and similarity is not None and similarity < float(score_threshold):
            continue

        doc_id = str(meta.get("doc_id") or "")
        chunk_index = int(meta.get("chunk_index") or 0)
        chunk_id = f"{doc_id}_{chunk_index}"

        start_line = int(meta.get("start_line") or 0)
        end_line = int(meta.get("end_line") or 0)
        text = ""
        try:
            text = str(documents[idx]) if documents and idx < len(documents) and documents[idx] is not None else ""
        except Exception:
            text = ""

        formatted.append({
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "source": rel_path,
            "lines": [start_line, end_line],
            "score": float(similarity),
            "snippet": text[:400].strip(),
        })

        if len(formatted) >= int(k):
            break

    return formatted[: int(k)]


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
