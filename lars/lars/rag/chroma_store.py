"""
Chroma-backed vector store for RAG.

This module is intentionally self-contained and uses lazy imports so the rest of
the codebase can import lars.rag.* without requiring chromadb to be installed
until RAG vector search/indexing is actually used.

Concurrency notes
-----------------
Chroma persistence implementations have historically been sensitive to
concurrent access (threads/processes) depending on storage backend/version.
For now we serialize all collection operations behind:
- a process-wide threading lock
- an inter-process file lock (best-effort) located inside the chroma directory

This matches the "single writer slot" philosophy used elsewhere in LARS.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..config import get_config

import logging

logger = logging.getLogger(__name__)


class ChromaUnavailableError(RuntimeError):
    """Raised when chromadb is not installed or cannot be initialized."""


_client: Any | None = None
_client_lock = threading.Lock()
_collection_cache: dict[tuple[str, int], Any] = {}
_collection_cache_lock = threading.Lock()

# Serialize all Chroma operations by default (reads + writes) for safety.
_chroma_op_lock = threading.RLock()


@contextmanager
def _interprocess_lock(lock_path: str):
    """
    Best-effort inter-process lock using flock on POSIX.

    If locking isn't available, this degrades to a no-op lock.
    """
    try:
        import fcntl  # POSIX only
    except Exception:  # pragma: no cover
        yield
        return

    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass


def _import_chromadb() -> Any:
    try:
        import chromadb  # type: ignore
        return chromadb
    except Exception as e:
        raise ChromaUnavailableError(
            "chromadb is required for RAG vector storage/search. "
            "Install it with: pip install chromadb"
        ) from e


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client

    cfg = get_config()
    chroma_path = os.path.abspath(os.path.expanduser(cfg.chroma_path))

    with _client_lock:
        if _client is not None:
            return _client

        chromadb = _import_chromadb()

        # Prefer modern API; fall back to Settings-based client for older versions.
        try:
            _client = chromadb.PersistentClient(path=chroma_path)
        except Exception:
            try:
                from chromadb.config import Settings  # type: ignore
            except Exception as e:
                raise ChromaUnavailableError(
                    "chromadb is installed but could not be initialized (missing Settings)."
                ) from e

            _client = chromadb.Client(
                Settings(chroma_db_impl="duckdb+parquet", persist_directory=chroma_path)
            )

        logger.info(f"[RAG] Chroma persistence path: {chroma_path}")
        return _client


def _collection_name(embed_model: str, embedding_dim: int) -> str:
    # Chroma collection names must be simple; keep them short and stable.
    digest = hashlib.sha1(embed_model.encode("utf-8")).hexdigest()[:12]
    return f"lars_rag_{digest}_{embedding_dim}"


def _get_collection(embed_model: str, embedding_dim: int) -> Any:
    key = (embed_model, int(embedding_dim))
    with _collection_cache_lock:
        coll = _collection_cache.get(key)
        if coll is not None:
            return coll

    client = _get_client()

    # Collection creation can race, so do it inside the serialized op lock.
    with _chroma_op_lock:
        with _collection_cache_lock:
            coll = _collection_cache.get(key)
            if coll is not None:
                return coll

            name = _collection_name(embed_model, int(embedding_dim))
            coll = client.get_or_create_collection(
                name=name,
                metadata={"embed_model": embed_model, "embedding_dim": int(embedding_dim)},
            )
            _collection_cache[key] = coll
            return coll


def chroma_chunk_id(rag_id: str, doc_id: str, chunk_index: int) -> str:
    # Stable, safe ID string for Chroma.
    raw = f"{rag_id}\n{doc_id}\n{int(chunk_index)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChromaChunk:
    rag_id: str
    doc_id: str
    chunk_index: int
    text: str
    embedding: List[float]
    rel_path: str
    start_line: int
    end_line: int
    char_start: int
    char_end: int
    file_hash: str
    embedding_model: str
    embedding_dim: int

    def chroma_id(self) -> str:
        return chroma_chunk_id(self.rag_id, self.doc_id, self.chunk_index)

    def metadata(self) -> Dict[str, Any]:
        return {
            "rag_id": self.rag_id,
            "doc_id": self.doc_id,
            "chunk_index": int(self.chunk_index),
            "rel_path": self.rel_path,
            "start_line": int(self.start_line),
            "end_line": int(self.end_line),
            "char_start": int(self.char_start),
            "char_end": int(self.char_end),
            "file_hash": self.file_hash,
            "embedding_model": self.embedding_model,
            "embedding_dim": int(self.embedding_dim),
        }


def _is_transient_lock_error(err: Exception) -> bool:
    s = str(err).lower()
    return (
        "database is locked" in s
        or "locked" in s and "database" in s
        or "timeout" in s and "lock" in s
    )


def _retry_chroma(fn, *, max_attempts: int = 7, base_delay_s: float = 0.05):
    delay = base_delay_s
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt >= max_attempts or not _is_transient_lock_error(e):
                raise
            time.sleep(delay)
            delay = min(delay * 2, 2.0)
    if last_err:
        raise last_err


def upsert_chunks(embed_model: str, embedding_dim: int, chunks: List[ChromaChunk]) -> None:
    if not chunks:
        return

    cfg = get_config()
    lock_path = os.path.join(os.path.abspath(os.path.expanduser(cfg.chroma_path)), ".lars_chroma.lock")

    # ChromaDB max batch size is 5461 — stay under it
    BATCH_SIZE = 5000

    ids = [c.chroma_id() for c in chunks]
    embeddings = [c.embedding for c in chunks]
    documents = [c.text for c in chunks]
    metadatas = [c.metadata() for c in chunks]

    with _chroma_op_lock:
        with _interprocess_lock(lock_path):
            coll = _get_collection(embed_model, int(embedding_dim))
            for start in range(0, len(ids), BATCH_SIZE):
                end = start + BATCH_SIZE
                batch_ids = ids[start:end]
                batch_embeddings = embeddings[start:end]
                batch_documents = documents[start:end]
                batch_metadatas = metadatas[start:end]

                def _do_upsert():
                    coll.upsert(
                        ids=batch_ids,
                        embeddings=batch_embeddings,
                        documents=batch_documents,
                        metadatas=batch_metadatas,
                    )

                _retry_chroma(_do_upsert)


def delete_by_rag_id(embed_model: str, embedding_dim: int, rag_id: str) -> None:
    cfg = get_config()
    lock_path = os.path.join(os.path.abspath(os.path.expanduser(cfg.chroma_path)), ".lars_chroma.lock")

    def _do_delete():
        coll = _get_collection(embed_model, int(embedding_dim))
        # Delete all chunks for this rag_id.
        coll.delete(where={"rag_id": rag_id})

    with _chroma_op_lock:
        with _interprocess_lock(lock_path):
            _retry_chroma(_do_delete)


def delete_by_doc_id(embed_model: str, embedding_dim: int, rag_id: str, doc_id: str) -> None:
    cfg = get_config()
    lock_path = os.path.join(os.path.abspath(os.path.expanduser(cfg.chroma_path)), ".lars_chroma.lock")

    def _do_delete():
        coll = _get_collection(embed_model, int(embedding_dim))
        # ChromaDB requires $and for compound where conditions
        coll.delete(where={"$and": [{"rag_id": rag_id}, {"doc_id": doc_id}]})

    with _chroma_op_lock:
        with _interprocess_lock(lock_path):
            _retry_chroma(_do_delete)


def query_chunks(
    embed_model: str,
    embedding_dim: int,
    rag_id: str,
    query_embedding: List[float],
    n_results: int,
) -> Dict[str, Any]:
    cfg = get_config()
    lock_path = os.path.join(os.path.abspath(os.path.expanduser(cfg.chroma_path)), ".lars_chroma.lock")

    def _do_query():
        coll = _get_collection(embed_model, int(embedding_dim))
        return coll.query(
            query_embeddings=[query_embedding],
            n_results=int(n_results),
            where={"rag_id": rag_id},
            include=["metadatas", "documents", "distances"],
        )

    with _chroma_op_lock:
        with _interprocess_lock(lock_path):
            return _retry_chroma(_do_query)


def get_chunk_by_id(
    embed_model: str,
    embedding_dim: int,
    rag_id: str,
    doc_id: str,
    chunk_index: int,
) -> Optional[Dict[str, Any]]:
    cfg = get_config()
    lock_path = os.path.join(os.path.abspath(os.path.expanduser(cfg.chroma_path)), ".lars_chroma.lock")
    chroma_id = chroma_chunk_id(rag_id, doc_id, int(chunk_index))

    def _do_get():
        coll = _get_collection(embed_model, int(embedding_dim))
        return coll.get(ids=[chroma_id], include=["metadatas", "documents"])

    with _chroma_op_lock:
        with _interprocess_lock(lock_path):
            res = _retry_chroma(_do_get)

    ids = res.get("ids") or []
    if not ids or not ids[0]:
        return None

    documents = res.get("documents") or [[]]
    metadatas = res.get("metadatas") or [[]]
    doc = (documents[0][0] if documents and documents[0] else None)
    meta = (metadatas[0][0] if metadatas and metadatas[0] else None)

    if meta is None:
        return None

    return {
        "text": doc or "",
        "metadata": meta,
    }

