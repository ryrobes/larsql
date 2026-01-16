import json
from typing import Optional

from .context import get_current_rag_context
from .store import list_sources, read_chunk, search_chunks

def _require_context():
    ctx = get_current_rag_context()
    if not ctx:
        raise ValueError("No active RAG context. Add a `rag` block to the cell to enable RAG tools.")
    return ctx

def rag_search(
    query: str,
    k: int = 5,
    score_threshold: Optional[float] = None,
    doc_filter: Optional[str] = None,
    smart: Optional[bool] = None
) -> str:
    """
    Semantic search over the indexed directory. Returns top matching chunks.

    Args:
        query: Natural language search query
        k: Number of results to return (default: 5)
        score_threshold: Minimum similarity score (0-1)
        doc_filter: Filter results by document path substring
        smart: Use LLM-powered filtering (default: from LARS_SMART_SEARCH config)

    Returns:
        JSON with search results. If smart=True, includes reasoning for each result
        and a synthesis of findings.
    """
    from .smart_search import smart_search_chunks, is_smart_search_enabled

    ctx = _require_context()

    # Determine if smart search should be used
    use_smart = smart if smart is not None else is_smart_search_enabled()

    if use_smart:
        # Use smart search with LLM filtering
        smart_result = smart_search_chunks(
            rag_ctx=ctx,
            query=query,
            k=k,
            explore_mode=False,
            synthesize=True,
            context_hint=f"searching RAG index: {ctx.directory or ctx.rag_id}",
            score_threshold=score_threshold,
            doc_filter=doc_filter
        )

        payload = {
            "rag_id": ctx.rag_id,
            "directory": ctx.directory,
            "results": smart_result.get("results", []),
            "synthesis": smart_result.get("synthesis"),
            "dropped_count": smart_result.get("dropped_count", 0),
            "smart_search_used": smart_result.get("smart_search_used", False)
        }

        if not smart_result.get("results"):
            payload["message"] = "No relevant matches found. Try a broader query or different keywords."

        return json.dumps(payload)

    else:
        # Use raw vector search
        results = search_chunks(ctx, query, k=k, score_threshold=score_threshold, doc_filter=doc_filter)
        payload = {
            "rag_id": ctx.rag_id,
            "directory": ctx.directory,
            "results": results,
            "smart_search_used": False
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
