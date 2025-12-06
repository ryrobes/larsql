import json
import math
import os
from typing import Any, Dict, List, Optional

import pandas as pd

from .context import RagContext
from .indexer import embed_texts

_INDEX_CACHE: Dict[str, Dict[str, Any]] = {}

def _load_meta(meta_path: str) -> Dict[str, Any]:
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"RAG meta file missing: {meta_path}")
    with open(meta_path, "r") as f:
        return json.load(f)

def _get_index(rag_ctx: RagContext) -> Dict[str, Any]:
    """Load manifest, chunks, and meta (cached by rag_id)."""
    if rag_ctx.rag_id in _INDEX_CACHE:
        return _INDEX_CACHE[rag_ctx.rag_id]

    manifest = pd.read_parquet(rag_ctx.manifest_path) if os.path.exists(rag_ctx.manifest_path) else pd.DataFrame()
    chunks = pd.read_parquet(rag_ctx.chunks_path) if os.path.exists(rag_ctx.chunks_path) else pd.DataFrame()
    meta = _load_meta(rag_ctx.meta_path)

    _INDEX_CACHE[rag_ctx.rag_id] = {"manifest": manifest, "chunks": chunks, "meta": meta}
    return _INDEX_CACHE[rag_ctx.rag_id]

def list_sources(rag_ctx: RagContext) -> List[Dict[str, Any]]:
    idx = _get_index(rag_ctx)
    manifest = idx["manifest"]
    if manifest.empty:
        return []
    return manifest[["doc_id", "rel_path", "chunk_count", "size", "mtime"]].to_dict("records")

def read_chunk(rag_ctx: RagContext, chunk_id: str) -> Dict[str, Any]:
    idx = _get_index(rag_ctx)
    chunks = idx["chunks"]
    if chunks.empty:
        raise ValueError("RAG index is empty.")
    row = chunks[chunks["chunk_id"] == chunk_id]
    if row.empty:
        raise ValueError(f"Chunk {chunk_id} not found.")
    rec = row.iloc[0].to_dict()
    return {
        "chunk_id": rec["chunk_id"],
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
    idx = _get_index(rag_ctx)
    chunks = idx["chunks"]
    meta = idx["meta"]

    if chunks.empty:
        return []

    df = chunks
    if doc_filter:
        mask = df["rel_path"].str.contains(doc_filter, case=False, na=False)
        df = df[mask]
    if df.empty:
        return []

    # Embed query using Agent.embed() - same model as the index
    # Pass session context from rag_ctx so query embeddings are properly logged
    embed_result = embed_texts(
        texts=[query],
        model=meta.get("embed_model"),
        session_id=rag_ctx.session_id,
        trace_id=rag_ctx.trace_id,
        parent_id=rag_ctx.parent_id,
        phase_name=rag_ctx.phase_name,
        cascade_id=rag_ctx.cascade_id,
    )
    query_vecs = embed_result["embeddings"]

    # Build dense matrix lazily to avoid a hard numpy dependency
    try:
        import numpy as np  # type: ignore

        matrix = np.vstack(df["embedding"].to_list()).astype(float)
        query_vec = np.array(query_vecs[0], dtype=float)
        norms = (np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query_vec) or 1.0)) + 1e-9
        scores = matrix.dot(query_vec) / norms
    except Exception:
        # Pure-Python fallback (slower, but avoids dependency issues)
        def _dot(a, b):
            return sum(x * y for x, y in zip(a, b))

        q = query_vecs[0]
        q_norm = math.sqrt(_dot(q, q)) or 1.0
        scores_list = []
        for emb in df["embedding"]:
            denom = (math.sqrt(_dot(emb, emb)) * q_norm) or 1.0
            scores_list.append(_dot(emb, q) / denom)
        scores = scores_list

    df = df.copy()
    df["score"] = scores
    if score_threshold is not None:
        df = df[df["score"] >= score_threshold]

    df = df.sort_values("score", ascending=False).head(k)

    results = []
    for _, row in df.iterrows():
        results.append({
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "source": row["rel_path"],
            "lines": [int(row["start_line"]), int(row["end_line"])],
            "score": float(row["score"]),
            "snippet": row["text"][:400].strip(),
        })
    return results

def clear_cache():
    """Clear cached manifests/chunks."""
    _INDEX_CACHE.clear()
