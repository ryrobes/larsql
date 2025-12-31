import json
from typing import Optional

from .context import get_current_rag_context
from .store import list_sources, read_chunk, search_chunks

def _require_context():
    ctx = get_current_rag_context()
    if not ctx:
        raise ValueError("No active RAG context. Add a `rag` block to the cell to enable RAG tools.")
    return ctx

def rag_search(query: str, k: int = 5, score_threshold: Optional[float] = None, doc_filter: Optional[str] = None) -> str:
    """
    Semantic search over the indexed directory. Returns top matching chunks.
    """
    ctx = _require_context()
    results = search_chunks(ctx, query, k=k, score_threshold=score_threshold, doc_filter=doc_filter)
    payload = {
        "rag_id": ctx.rag_id,
        "directory": ctx.directory,
        "results": results
    }
    if not results:
        payload["message"] = "No matches found. Try a broader query or different keywords."
    return json.dumps(payload)

def rag_read_chunk(chunk_id: str) -> str:
    """
    Fetch the full text of a chunk by chunk_id along with source metadata.
    """
    ctx = _require_context()
    try:
        chunk = read_chunk(ctx, chunk_id)
        return json.dumps(chunk)
    except Exception as e:
        sources = list_sources(ctx)
        return json.dumps({
            "error": str(e),
            "rag_id": ctx.rag_id,
            "directory": ctx.directory,
            "hint": "Call rag_search and use a chunk_id from the search results.",
            "available_documents": [s["rel_path"] for s in sources][:10]
        })

def rag_list_sources() -> str:
    """
    List available documents in the RAG index with basic metadata.
    """
    ctx = _require_context()
    sources = list_sources(ctx)
    return json.dumps({
        "rag_id": ctx.rag_id,
        "directory": ctx.directory,
        "documents": sources
    })
