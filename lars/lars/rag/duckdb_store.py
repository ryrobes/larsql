"""
DuckDB-backed vector store for RAG.

Replaces chromadb with native DuckDB vector similarity search (VSS extension)
and full-text search (FTS extension) for hybrid retrieval.

Data is stored in parquet files following LARS's append-merge pattern:
- Chunks are appended to timestamped parquet files
- Periodic compaction merges small files
- No external database process required

Concurrency notes
-----------------
Uses the same locking strategy as the rest of LARS:
- Process-wide threading lock for in-memory state
- Inter-process file lock for writes
- Serialized writes + pooled read connections for query concurrency
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
import glob
import atexit
import copy
from array import array
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import logging

logger = logging.getLogger(__name__)
_rag_path_cache_lock = threading.Lock()
_cached_rag_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _rag_path_has_data(rag_path: str) -> bool:
    """Return True when the rag directory already has parquet collection data."""
    if not os.path.isdir(rag_path):
        return False
    try:
        for entry in os.scandir(rag_path):
            if not entry.is_dir():
                continue
            if glob.glob(os.path.join(entry.path, "*.parquet")):
                return True
    except Exception:
        return False
    return False


def _get_rag_path() -> str:
    """Get the RAG storage directory from config."""
    global _cached_rag_path

    if _cached_rag_path:
        return _cached_rag_path

    with _rag_path_cache_lock:
        if _cached_rag_path:
            return _cached_rag_path

        from ..config import get_config

        cfg = get_config()
        # Prefer Config.data_dir; keep data_path fallback for older config objects.
        preferred_base = (
            getattr(cfg, "data_dir", None)
            or getattr(cfg, "data_path", None)
            or os.path.expanduser("~/.lars/data")
        )
        rag_path = os.path.join(os.path.abspath(os.path.expanduser(preferred_base)), "rag")

        legacy_rag_path = os.path.join(os.path.expanduser("~/.lars/data"), "rag")
        if os.path.abspath(rag_path) != os.path.abspath(legacy_rag_path):
            if _rag_path_has_data(legacy_rag_path) and not _rag_path_has_data(rag_path):
                logger.warning(
                    "[RAG] Preferred RAG path %s is empty; using legacy path %s until re-indexed.",
                    rag_path,
                    legacy_rag_path,
                )
                rag_path = legacy_rag_path

        os.makedirs(rag_path, exist_ok=True)
        _cached_rag_path = rag_path
        return _cached_rag_path


# ---------------------------------------------------------------------------
# Locking utilities (same pattern as chroma_store)
# ---------------------------------------------------------------------------

_write_lock = threading.RLock()


@contextmanager
def _interprocess_lock(lock_path: str):
    """
    Best-effort inter-process lock using flock on POSIX.
    Degrades to no-op on Windows or if flock unavailable.
    """
    try:
        import fcntl  # POSIX only
    except ImportError:
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


# ---------------------------------------------------------------------------
# DuckDB connection management
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """Read an integer env var with validation and fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        return max(minimum, value)
    except Exception:
        logger.warning(f"[RAG] Invalid {name}={raw!r}; using default={default}")
        return default


def _env_float(name: str, default: float, minimum: float = 0.1) -> float:
    """Read a float env var with validation and fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
        return max(minimum, value)
    except Exception:
        logger.warning(f"[RAG] Invalid {name}={raw!r}; using default={default}")
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean env var with flexible truthy/falsey parsing."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    logger.warning(f"[RAG] Invalid {name}={raw!r}; using default={default}")
    return default


_QUERY_POOL_SIZE = _env_int("LARS_DUCKDB_QUERY_POOL_SIZE", 12, minimum=1)
_QUERY_CONN_THREADS = _env_int("LARS_DUCKDB_QUERY_CONN_THREADS", 1, minimum=1)
_WRITER_CONN_THREADS = _env_int("LARS_DUCKDB_WRITER_CONN_THREADS", 2, minimum=1)
_QUERY_POOL_WAIT_SECONDS = _env_float("LARS_DUCKDB_QUERY_POOL_WAIT_SECONDS", 30.0, minimum=0.5)
_QUERY_CACHE_ENABLED = _env_bool("LARS_RAG_QUERY_CACHE_ENABLED", True)
_QUERY_CACHE_TTL_SECONDS = _env_float("LARS_RAG_QUERY_CACHE_TTL_SECONDS", 45.0, minimum=0.1)
_QUERY_CACHE_MAX_ENTRIES = _env_int("LARS_RAG_QUERY_CACHE_MAX_ENTRIES", 512, minimum=1)
_AUTO_COMPACT_ENABLED = _env_bool("LARS_RAG_AUTO_COMPACT_ENABLED", False)
_AUTO_COMPACT_INTERVAL_SECONDS = _env_float("LARS_RAG_AUTO_COMPACT_INTERVAL_SECONDS", 300.0, minimum=10.0)
_AUTO_COMPACT_CHECK_INTERVAL_SECONDS = _env_float("LARS_RAG_AUTO_COMPACT_CHECK_INTERVAL_SECONDS", 30.0, minimum=1.0)
_AUTO_COMPACT_MIN_PARQUET_FILES = _env_int("LARS_RAG_AUTO_COMPACT_MIN_PARQUET_FILES", 128, minimum=2)
_AUTO_COMPACT_MIN_TOMBSTONES = _env_int("LARS_RAG_AUTO_COMPACT_MIN_TOMBSTONES", 32, minimum=0)
# Default-on for evaluation; can be disabled with LARS_RAG_SHADOW_ENABLED=0.
_RAG_SHADOW_ENABLED = _env_bool("LARS_RAG_SHADOW_ENABLED", True)

_writer_conn: Any = None
_writer_conn_lock = threading.Lock()

_query_pool: List[Any] = []
_query_pool_lock = threading.Lock()
_query_slots = threading.BoundedSemaphore(_QUERY_POOL_SIZE)

_extension_install_lock = threading.Lock()
_query_cache_lock = threading.Lock()
_query_result_cache: "OrderedDict[str, Tuple[float, Dict[str, Any]]]" = OrderedDict()
_collection_epochs_lock = threading.Lock()
_collection_epochs: Dict[str, int] = {}
_auto_compact_lock = threading.Lock()
_auto_compact_last_check: Dict[str, float] = {}
_auto_compact_last_run: Dict[str, float] = {}
_auto_compact_inflight: Set[str] = set()


def _is_connection_healthy(conn: Any) -> bool:
    """Check if a connection is still usable."""
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def _close_connection(conn: Any, label: str) -> None:
    """Close a connection, swallowing close-time errors."""
    if conn is None:
        return
    try:
        conn.close()
    except Exception as e:
        logger.debug(f"[RAG] Failed closing {label} DuckDB connection: {e}")


def _load_extension(conn: Any, extension_name: str) -> None:
    """Load a DuckDB extension, installing once when needed."""
    try:
        conn.execute(f"LOAD {extension_name}")
        return
    except Exception:
        pass

    with _extension_install_lock:
        try:
            conn.execute(f"INSTALL {extension_name}")
        except Exception:
            # Extension may already be installed by another thread/process.
            pass

    conn.execute(f"LOAD {extension_name}")


def _create_connection(*, threads: int) -> Any:
    """Create an in-memory DuckDB connection configured for RAG queries."""
    import duckdb

    conn = duckdb.connect(":memory:")
    conn.execute(f"SET threads TO {int(threads)}")
    _load_extension(conn, "vss")
    _load_extension(conn, "fts")
    return conn


def _get_writer_connection() -> Any:
    """Get or create the shared writer connection."""
    global _writer_conn

    if _is_connection_healthy(_writer_conn):
        return _writer_conn

    with _writer_conn_lock:
        if _is_connection_healthy(_writer_conn):
            return _writer_conn
        _close_connection(_writer_conn, "stale writer")
        _writer_conn = _create_connection(threads=_WRITER_CONN_THREADS)
        logger.info(
            "[RAG] DuckDB writer connection initialized "
            f"(threads={_WRITER_CONN_THREADS}, query_pool={_QUERY_POOL_SIZE}, "
            f"query_threads={_QUERY_CONN_THREADS})"
        )
        return _writer_conn


@contextmanager
def _query_connection():
    """Borrow a read connection from the pool (blocking when slots are full)."""
    if not _query_slots.acquire(timeout=_QUERY_POOL_WAIT_SECONDS):
        raise TimeoutError(
            f"Timed out waiting for DuckDB query connection after {_QUERY_POOL_WAIT_SECONDS:.1f}s"
        )

    conn: Any = None
    try:
        with _query_pool_lock:
            if _query_pool:
                conn = _query_pool.pop()

        if not _is_connection_healthy(conn):
            _close_connection(conn, "stale pooled")
            conn = _create_connection(threads=_QUERY_CONN_THREADS)

        yield conn
    finally:
        if _is_connection_healthy(conn):
            with _query_pool_lock:
                if len(_query_pool) < _QUERY_POOL_SIZE:
                    _query_pool.append(conn)
                else:
                    _close_connection(conn, "extra pooled")
        else:
            _close_connection(conn, "unhealthy pooled")
        _query_slots.release()


def _close_all_connections() -> None:
    """Close all pooled/writer DuckDB connections at interpreter exit."""
    global _writer_conn

    _query_cache_clear()

    with _query_pool_lock:
        pooled = list(_query_pool)
        _query_pool.clear()
    for conn in pooled:
        _close_connection(conn, "pooled")

    with _writer_conn_lock:
        writer = _writer_conn
        _writer_conn = None
    _close_connection(writer, "writer")


atexit.register(_close_all_connections)


# ---------------------------------------------------------------------------
# Chunk ID generation (compatible with chroma_store)
# ---------------------------------------------------------------------------

def chunk_id(rag_id: str, doc_id: str, chunk_index: int) -> str:
    """Generate a stable, unique ID for a chunk."""
    raw = f"{rag_id}\n{doc_id}\n{int(chunk_index)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Chunk:
    """A text chunk with its embedding and metadata."""
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

    def chunk_id(self) -> str:
        return chunk_id(self.rag_id, self.doc_id, self.chunk_index)

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


# Backwards compatibility alias
ChromaChunk = Chunk
chroma_chunk_id = chunk_id


# ---------------------------------------------------------------------------
# Parquet file management
# ---------------------------------------------------------------------------

def _collection_dir(embed_model: str, embedding_dim: int) -> str:
    """Get directory for a specific embedding model/dimension combination."""
    rag_path = _get_rag_path()
    # Hash the model name for a clean directory name
    model_hash = hashlib.sha1(embed_model.encode("utf-8")).hexdigest()[:12]
    coll_dir = os.path.join(rag_path, f"{model_hash}_{embedding_dim}")
    os.makedirs(coll_dir, exist_ok=True)
    return coll_dir


def _get_parquet_files(coll_dir: str) -> List[str]:
    """Get all parquet files in a collection directory."""
    pattern = os.path.join(coll_dir, "*.parquet")
    return sorted(glob.glob(pattern))


def _new_parquet_path(coll_dir: str) -> str:
    """Generate a new parquet file path with timestamp."""
    ts = int(time.time() * 1000)
    return os.path.join(coll_dir, f"chunks_{ts}.parquet")


# ---------------------------------------------------------------------------
# Query cache and auto-compaction helpers
# ---------------------------------------------------------------------------

def _query_embedding_fingerprint(query_embedding: List[float]) -> str:
    """Build a stable hash key for an embedding vector."""
    try:
        # Compact binary form is faster than string joins for large vectors.
        packed = array("f", (float(x) for x in query_embedding)).tobytes()
        return hashlib.sha1(packed).hexdigest()
    except Exception:
        fallback = ",".join(f"{float(x):.6f}" for x in query_embedding)
        return hashlib.sha1(fallback.encode("ascii", errors="ignore")).hexdigest()


def _collection_epoch(coll_dir: str) -> int:
    with _collection_epochs_lock:
        return int(_collection_epochs.get(coll_dir, 0))


def _bump_collection_epoch(coll_dir: str) -> None:
    with _collection_epochs_lock:
        _collection_epochs[coll_dir] = int(_collection_epochs.get(coll_dir, 0)) + 1
    _query_cache_clear()


def _make_query_cache_key(
    coll_dir: str,
    rag_id: str,
    n_results: int,
    query_embedding: List[float],
) -> str:
    epoch = _collection_epoch(coll_dir)
    embedding_key = _query_embedding_fingerprint(query_embedding)
    return f"{coll_dir}|{epoch}|{rag_id}|{int(n_results)}|{embedding_key}"


def _query_cache_get(cache_key: str) -> Optional[Dict[str, Any]]:
    if not _QUERY_CACHE_ENABLED:
        return None
    now = time.time()
    with _query_cache_lock:
        item = _query_result_cache.get(cache_key)
        if item is None:
            return None
        expires_at, payload = item
        if expires_at <= now:
            _query_result_cache.pop(cache_key, None)
            return None
        _query_result_cache.move_to_end(cache_key)
        return copy.deepcopy(payload)


def _query_cache_put(cache_key: str, payload: Dict[str, Any]) -> None:
    if not _QUERY_CACHE_ENABLED:
        return
    expires_at = time.time() + _QUERY_CACHE_TTL_SECONDS
    with _query_cache_lock:
        _query_result_cache[cache_key] = (expires_at, copy.deepcopy(payload))
        _query_result_cache.move_to_end(cache_key)
        while len(_query_result_cache) > _QUERY_CACHE_MAX_ENTRIES:
            _query_result_cache.popitem(last=False)


def _query_cache_clear() -> None:
    if not _QUERY_CACHE_ENABLED:
        return
    with _query_cache_lock:
        _query_result_cache.clear()


def _collection_file_counts(coll_dir: str) -> Tuple[int, int]:
    files = _get_parquet_files(coll_dir)
    tombstones = sum(1 for f in files if os.path.basename(f).startswith("tombstone_"))
    return len(files), tombstones


def _run_auto_compaction(embed_model: str, embedding_dim: int, coll_dir: str) -> None:
    """Background auto-compaction worker for one collection."""
    try:
        before_total, before_tombstones = _collection_file_counts(coll_dir)
        live_count = compact_collection(embed_model, embedding_dim)
        after_total, after_tombstones = _collection_file_counts(coll_dir)
        logger.info(
            "[RAG] Auto-compaction completed for %s: files %d->%d, tombstones %d->%d, live_chunks=%d",
            os.path.basename(coll_dir),
            before_total,
            after_total,
            before_tombstones,
            after_tombstones,
            live_count,
        )
    except Exception as e:
        logger.warning(f"[RAG] Auto-compaction failed for {coll_dir}: {e}")
    finally:
        now = time.time()
        with _auto_compact_lock:
            _auto_compact_last_run[coll_dir] = now
            _auto_compact_inflight.discard(coll_dir)


def _maybe_schedule_auto_compaction(
    embed_model: str,
    embedding_dim: int,
    coll_dir: str,
    *,
    force_check: bool = False,
) -> None:
    """Schedule background compaction if thresholds and interval are met."""
    if not _AUTO_COMPACT_ENABLED:
        return

    now = time.time()
    if not force_check:
        with _auto_compact_lock:
            last_check = float(_auto_compact_last_check.get(coll_dir, 0.0))
            if (now - last_check) < _AUTO_COMPACT_CHECK_INTERVAL_SECONDS:
                return
            _auto_compact_last_check[coll_dir] = now
    else:
        with _auto_compact_lock:
            _auto_compact_last_check[coll_dir] = now

    total_files, tombstone_files = _collection_file_counts(coll_dir)
    should_compact = (
        total_files >= _AUTO_COMPACT_MIN_PARQUET_FILES
        or tombstone_files >= _AUTO_COMPACT_MIN_TOMBSTONES
    )
    if not should_compact:
        return

    with _auto_compact_lock:
        last_run = float(_auto_compact_last_run.get(coll_dir, 0.0))
        if coll_dir in _auto_compact_inflight:
            return
        if (now - last_run) < _AUTO_COMPACT_INTERVAL_SECONDS:
            return
        _auto_compact_inflight.add(coll_dir)

    t = threading.Thread(
        target=_run_auto_compaction,
        args=(embed_model, int(embedding_dim), coll_dir),
        daemon=True,
        name=f"rag-auto-compact-{os.path.basename(coll_dir)}",
    )
    t.start()


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def _vector_collection_key(embed_model: str, embedding_dim: int) -> str:
    return f"{embed_model}:{int(embedding_dim)}"


def _mirror_to_clickhouse_shadow(
    table: str,
    rows: List[Dict[str, Any]],
    *,
    clear_table: bool = False,
    flush: bool = False,
    batch_rows: int = 500,
) -> None:
    """Best-effort mirror for vector writes that bypass db_adapter.insert_rows()."""
    if not rows and not clear_table:
        return
    try:
        from ..db_adapter import mirror_rows_to_shadow

        mirror_rows_to_shadow(
            table=table,
            rows=rows,
            clear_table=clear_table,
            flush=flush,
            batch_rows=batch_rows,
            normalize_rows=False,
        )
    except Exception as e:
        logger.debug("[RAG] Shadow mirror skipped for %s: %s", table, e)


def upsert_chunks(embed_model: str, embedding_dim: int, chunks: List[Chunk]) -> None:
    """
    Insert or update chunks in the vector store.
    
    Uses append-only writes: new chunks go to a new parquet file.
    Duplicates are handled at query time (latest file wins) or during compaction.
    """
    if not chunks:
        return

    coll_dir = _collection_dir(embed_model, embedding_dim)
    lock_path = os.path.join(coll_dir, ".write.lock")

    # Build records for parquet
    records = []
    collection_key = _vector_collection_key(embed_model, embedding_dim)
    for c in chunks:
        records.append({
            "chunk_id": c.chunk_id(),
            "rag_id": c.rag_id,
            "doc_id": c.doc_id,
            "chunk_index": c.chunk_index,
            "text": c.text,
            "embedding": c.embedding,
            "rel_path": c.rel_path,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "file_hash": c.file_hash,
            "embedding_model": c.embedding_model,
            "embedding_dim": c.embedding_dim,
            "collection_key": collection_key,
            "upsert_ts": int(time.time() * 1000),
        })

    with _write_lock:
        with _interprocess_lock(lock_path):
            conn = _get_writer_connection()

            # Create table from records and write to parquet
            parquet_path = _new_parquet_path(coll_dir)

            # Use DuckDB to write parquet efficiently
            conn.execute("DROP TABLE IF EXISTS _upsert_tmp")
            conn.execute("""
                CREATE TABLE _upsert_tmp (
                    chunk_id VARCHAR,
                    rag_id VARCHAR,
                    doc_id VARCHAR,
                    chunk_index INTEGER,
                    text VARCHAR,
                    embedding FLOAT[],
                    rel_path VARCHAR,
                    start_line INTEGER,
                    end_line INTEGER,
                    char_start INTEGER,
                    char_end INTEGER,
                    file_hash VARCHAR,
                    embedding_model VARCHAR,
                    embedding_dim INTEGER,
                    upsert_ts BIGINT
                )
            """)

            # Insert records
            for r in records:
                conn.execute("""
                    INSERT INTO _upsert_tmp VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    r["chunk_id"], r["rag_id"], r["doc_id"], r["chunk_index"],
                    r["text"], r["embedding"], r["rel_path"], r["start_line"],
                    r["end_line"], r["char_start"], r["char_end"], r["file_hash"],
                    r["embedding_model"], r["embedding_dim"], r["upsert_ts"]
                ])

            # Write to parquet
            conn.execute(f"COPY _upsert_tmp TO '{parquet_path}' (FORMAT PARQUET)")
            conn.execute("DROP TABLE _upsert_tmp")

            _bump_collection_epoch(coll_dir)
            _maybe_schedule_auto_compaction(embed_model, embedding_dim, coll_dir, force_check=True)
            logger.debug(f"[RAG] Wrote {len(records)} chunks to {parquet_path}")

    _mirror_to_clickhouse_shadow("rag_vector_chunks", records)


def delete_by_rag_id(embed_model: str, embedding_dim: int, rag_id: str) -> None:
    """
    Delete all chunks for a given rag_id.
    
    Writes a tombstone file that marks chunks as deleted.
    Actual removal happens during compaction.
    """
    coll_dir = _collection_dir(embed_model, embedding_dim)
    lock_path = os.path.join(coll_dir, ".write.lock")

    with _write_lock:
        with _interprocess_lock(lock_path):
            # Write a tombstone parquet with just the rag_id to delete
            conn = _get_writer_connection()
            tombstone_ts = int(time.time() * 1000)
            tombstone_path = os.path.join(coll_dir, f"tombstone_rag_{int(time.time() * 1000)}.parquet")

            conn.execute("DROP TABLE IF EXISTS _tombstone_tmp")
            conn.execute("""
                CREATE TABLE _tombstone_tmp (
                    tombstone_type VARCHAR,
                    rag_id VARCHAR,
                    doc_id VARCHAR,
                    tombstone_ts BIGINT
                )
            """)
            conn.execute("""
                INSERT INTO _tombstone_tmp VALUES ('rag_id', ?, NULL, ?)
            """, [rag_id, tombstone_ts])
            conn.execute(f"COPY _tombstone_tmp TO '{tombstone_path}' (FORMAT PARQUET)")
            conn.execute("DROP TABLE _tombstone_tmp")

            _bump_collection_epoch(coll_dir)
            _maybe_schedule_auto_compaction(embed_model, embedding_dim, coll_dir, force_check=True)
            logger.debug(f"[RAG] Wrote tombstone for rag_id={rag_id}")

    _mirror_to_clickhouse_shadow(
        "rag_vector_tombstones",
        [
            {
                "tombstone_type": "rag_id",
                "rag_id": rag_id,
                "doc_id": None,
                "embedding_model": embed_model,
                "embedding_dim": int(embedding_dim),
                "collection_key": _vector_collection_key(embed_model, embedding_dim),
                "tombstone_ts": tombstone_ts,
            }
        ],
    )


def delete_by_doc_id(embed_model: str, embedding_dim: int, rag_id: str, doc_id: str) -> None:
    """
    Delete all chunks for a given rag_id + doc_id combination.
    """
    coll_dir = _collection_dir(embed_model, embedding_dim)
    lock_path = os.path.join(coll_dir, ".write.lock")

    with _write_lock:
        with _interprocess_lock(lock_path):
            conn = _get_writer_connection()
            tombstone_ts = int(time.time() * 1000)
            tombstone_path = os.path.join(coll_dir, f"tombstone_doc_{int(time.time() * 1000)}.parquet")

            conn.execute("DROP TABLE IF EXISTS _tombstone_tmp")
            conn.execute("""
                CREATE TABLE _tombstone_tmp (
                    tombstone_type VARCHAR,
                    rag_id VARCHAR,
                    doc_id VARCHAR,
                    tombstone_ts BIGINT
                )
            """)
            conn.execute("""
                INSERT INTO _tombstone_tmp VALUES ('doc_id', ?, ?, ?)
            """, [rag_id, doc_id, tombstone_ts])
            conn.execute(f"COPY _tombstone_tmp TO '{tombstone_path}' (FORMAT PARQUET)")
            conn.execute("DROP TABLE _tombstone_tmp")

            _bump_collection_epoch(coll_dir)
            _maybe_schedule_auto_compaction(embed_model, embedding_dim, coll_dir, force_check=True)
            logger.debug(f"[RAG] Wrote tombstone for rag_id={rag_id}, doc_id={doc_id}")

    _mirror_to_clickhouse_shadow(
        "rag_vector_tombstones",
        [
            {
                "tombstone_type": "doc_id",
                "rag_id": rag_id,
                "doc_id": doc_id,
                "embedding_model": embed_model,
                "embedding_dim": int(embedding_dim),
                "collection_key": _vector_collection_key(embed_model, embedding_dim),
                "tombstone_ts": tombstone_ts,
            }
        ],
    )


def _build_chunks_view(conn, coll_dir: str, embedding_dim: int) -> bool:
    """
    Build a view of all chunks minus tombstones.
    Returns True if there are chunks, False if empty.
    """
    chunk_files = [f for f in _get_parquet_files(coll_dir) if not os.path.basename(f).startswith("tombstone_")]
    tombstone_files = [f for f in _get_parquet_files(coll_dir) if os.path.basename(f).startswith("tombstone_")]
    
    if not chunk_files:
        return False
    
    # Read all chunks
    chunk_globs = [f"'{f}'" for f in chunk_files]
    conn.execute(f"""
        CREATE OR REPLACE TEMP VIEW _all_chunks AS
        SELECT * FROM read_parquet([{', '.join(chunk_globs)}])
    """)
    
    # Apply tombstones if any exist
    if tombstone_files:
        tombstone_globs = [f"'{f}'" for f in tombstone_files]
        conn.execute(f"""
            CREATE OR REPLACE TEMP VIEW _tombstones AS
            SELECT * FROM read_parquet([{', '.join(tombstone_globs)}])
        """)
        
        # Filter out tombstoned chunks
        conn.execute("""
            CREATE OR REPLACE TEMP VIEW _live_chunks AS
            SELECT c.* FROM _all_chunks c
            WHERE NOT EXISTS (
                SELECT 1 FROM _tombstones t
                WHERE (t.tombstone_type = 'rag_id' AND t.rag_id = c.rag_id)
                   OR (t.tombstone_type = 'doc_id' AND t.rag_id = c.rag_id AND t.doc_id = c.doc_id)
            )
        """)
    else:
        conn.execute("""
            CREATE OR REPLACE TEMP VIEW _live_chunks AS
            SELECT * FROM _all_chunks
        """)
    
    # Deduplicate by chunk_id (latest upsert_ts wins)
    conn.execute("""
        CREATE OR REPLACE TEMP VIEW _chunks AS
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY chunk_id ORDER BY upsert_ts DESC) as rn
            FROM _live_chunks
        ) WHERE rn = 1
    """)
    
    return True


def query_chunks(
    embed_model: str,
    embedding_dim: int,
    rag_id: str,
    query_embedding: List[float],
    n_results: int,
) -> Dict[str, Any]:
    """
    Query chunks by vector similarity.
    
    Returns results in chromadb-compatible format:
    {
        "ids": [[id1, id2, ...]],
        "documents": [[text1, text2, ...]],
        "metadatas": [[{...}, {...}, ...]],
        "distances": [[dist1, dist2, ...]]
    }
    """
    coll_dir = _collection_dir(embed_model, embedding_dim)
    cache_key = _make_query_cache_key(coll_dir, rag_id, n_results, query_embedding)
    cached = _query_cache_get(cache_key)
    if cached is not None:
        return cached

    if _RAG_SHADOW_ENABLED:
        try:
            from .shadow_store import start_rag_shadow_store

            shadow_store = start_rag_shadow_store()
            if shadow_store.enabled and shadow_store.serves_collection_dir(coll_dir):
                shadow_result = shadow_store.query_chunks(
                    embed_model=embed_model,
                    embedding_dim=int(embedding_dim),
                    rag_id=rag_id,
                    query_embedding=query_embedding,
                    n_results=int(n_results),
                )
                if shadow_result is not None:
                    _query_cache_put(cache_key, shadow_result)
                    return shadow_result
        except Exception as e:
            logger.debug(f"[RAG] Shadow query fallback to parquet path: {e}")

    with _query_connection() as conn:
        # Build view of live chunks
        if not _build_chunks_view(conn, coll_dir, embedding_dim):
            empty = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
            _query_cache_put(cache_key, empty)
            return empty

        # Convert query embedding to DuckDB array literal
        embedding_str = "[" + ", ".join(str(x) for x in query_embedding) + "]"

        # Query with vector similarity
        # Note: cosine similarity returns 1.0 for identical, 0.0 for orthogonal
        # chromadb uses distance (lower = better), so we convert: distance = 1 - similarity
        result = conn.execute(f"""
            SELECT 
                chunk_id,
                text,
                rag_id,
                doc_id,
                chunk_index,
                rel_path,
                start_line,
                end_line,
                char_start,
                char_end,
                file_hash,
                embedding_model,
                embedding_dim,
                1.0 - array_cosine_similarity(embedding::FLOAT[{embedding_dim}], {embedding_str}::FLOAT[{embedding_dim}]) as distance
            FROM _chunks
            WHERE rag_id = ?
            ORDER BY distance ASC
            LIMIT ?
        """, [rag_id, int(n_results)]).fetchall()
    
    # Format as chromadb-compatible response
    ids = []
    documents = []
    metadatas = []
    distances = []
    
    for row in result:
        ids.append(row[0])
        documents.append(row[1])
        metadatas.append({
            "rag_id": row[2],
            "doc_id": row[3],
            "chunk_index": row[4],
            "rel_path": row[5],
            "start_line": row[6],
            "end_line": row[7],
            "char_start": row[8],
            "char_end": row[9],
            "file_hash": row[10],
            "embedding_model": row[11],
            "embedding_dim": row[12],
        })
        distances.append(row[13])
    
    response = {
        "ids": [ids],
        "documents": [documents],
        "metadatas": [metadatas],
        "distances": [distances],
    }
    _query_cache_put(cache_key, response)
    return response


def query_chunks_hybrid(
    embed_model: str,
    embedding_dim: int,
    rag_id: str,
    query_embedding: List[float],
    query_text: str,
    n_results: int,
    vector_weight: float = 0.7,
) -> Dict[str, Any]:
    """
    Hybrid query combining vector similarity and BM25 text search.
    
    Args:
        vector_weight: Weight for vector similarity (0-1). Text weight = 1 - vector_weight.
    """
    coll_dir = _collection_dir(embed_model, embedding_dim)
    fallback_to_vector_only = False
    with _query_connection() as conn:
        if not _build_chunks_view(conn, coll_dir, embedding_dim):
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        embedding_str = "[" + ", ".join(str(x) for x in query_embedding) + "]"
        text_weight = 1.0 - vector_weight

        # Create FTS index on the chunks view
        # Note: FTS index is transient (in-memory), rebuilt each query
        # For large datasets, consider persisting the index
        try:
            conn.execute("PRAGMA create_fts_index('_chunks', 'chunk_id', 'text', overwrite=1)")

            result = conn.execute(f"""
                WITH scored AS (
                    SELECT 
                        c.*,
                        array_cosine_similarity(c.embedding::FLOAT[{embedding_dim}], {embedding_str}::FLOAT[{embedding_dim}]) as vec_sim,
                        COALESCE(fts_main__chunks.match_bm25(c.chunk_id, ?), 0) as bm25_score
                    FROM _chunks c
                    WHERE c.rag_id = ?
                ),
                normalized AS (
                    SELECT *,
                        -- Normalize scores to 0-1 range
                        vec_sim as vec_score,
                        bm25_score / NULLIF(MAX(bm25_score) OVER (), 0) as text_score
                    FROM scored
                )
                SELECT 
                    chunk_id, text, rag_id, doc_id, chunk_index,
                    rel_path, start_line, end_line, char_start, char_end,
                    file_hash, embedding_model, embedding_dim,
                    1.0 - (vec_score * {vector_weight} + COALESCE(text_score, 0) * {text_weight}) as distance
                FROM normalized
                ORDER BY distance ASC
                LIMIT ?
            """, [query_text, rag_id, int(n_results)]).fetchall()
        except Exception as e:
            # Fall back to vector-only if FTS fails
            logger.warning(f"[RAG] Hybrid search failed, falling back to vector-only: {e}")
            fallback_to_vector_only = True
            result = []

    if fallback_to_vector_only:
        return query_chunks(embed_model, embedding_dim, rag_id, query_embedding, n_results)
    
    # Format response
    ids, documents, metadatas, distances = [], [], [], []
    for row in result:
        ids.append(row[0])
        documents.append(row[1])
        metadatas.append({
            "rag_id": row[2], "doc_id": row[3], "chunk_index": row[4],
            "rel_path": row[5], "start_line": row[6], "end_line": row[7],
            "char_start": row[8], "char_end": row[9], "file_hash": row[10],
            "embedding_model": row[11], "embedding_dim": row[12],
        })
        distances.append(row[13])
    
    return {"ids": [ids], "documents": [documents], "metadatas": [metadatas], "distances": [distances]}


def get_chunk_by_id(
    embed_model: str,
    embedding_dim: int,
    rag_id: str,
    doc_id: str,
    chunk_index: int,
) -> Optional[Dict[str, Any]]:
    """Get a specific chunk by its composite ID."""
    coll_dir = _collection_dir(embed_model, embedding_dim)
    with _query_connection() as conn:
        if not _build_chunks_view(conn, coll_dir, embedding_dim):
            return None

        target_id = chunk_id(rag_id, doc_id, chunk_index)

        result = conn.execute("""
            SELECT text, rag_id, doc_id, chunk_index, rel_path,
                   start_line, end_line, char_start, char_end,
                   file_hash, embedding_model, embedding_dim
            FROM _chunks
            WHERE chunk_id = ?
            LIMIT 1
        """, [target_id]).fetchone()

    if not result:
        return None
    
    return {
        "text": result[0],
        "metadata": {
            "rag_id": result[1],
            "doc_id": result[2],
            "chunk_index": result[3],
            "rel_path": result[4],
            "start_line": result[5],
            "end_line": result[6],
            "char_start": result[7],
            "char_end": result[8],
            "file_hash": result[9],
            "embedding_model": result[10],
            "embedding_dim": result[11],
        },
    }


def compact_collection(embed_model: str, embedding_dim: int) -> int:
    """
    Compact a collection by merging all parquet files and applying tombstones.
    
    Returns the number of live chunks after compaction.
    """
    coll_dir = _collection_dir(embed_model, embedding_dim)
    lock_path = os.path.join(coll_dir, ".write.lock")
    
    with _write_lock:
        with _interprocess_lock(lock_path):
            conn = _get_writer_connection()

            if not _build_chunks_view(conn, coll_dir, embedding_dim):
                # No live chunk view means there are no chunk files left. Clean any
                # remaining tombstones/partials to keep directory fanout low.
                files = _get_parquet_files(coll_dir)
                for f in files:
                    os.remove(f)
                if files:
                    _bump_collection_epoch(coll_dir)
                return 0

            # Count live chunks
            count = conn.execute("SELECT COUNT(*) FROM _chunks").fetchone()[0]

            if count == 0:
                # No live chunks - delete all files
                for f in _get_parquet_files(coll_dir):
                    os.remove(f)
                _bump_collection_epoch(coll_dir)
                return 0

            # Write compacted file
            compacted_path = os.path.join(coll_dir, f"compacted_{int(time.time() * 1000)}.parquet")
            conn.execute(f"""
                COPY (
                    SELECT chunk_id, rag_id, doc_id, chunk_index, text, embedding,
                           rel_path, start_line, end_line, char_start, char_end,
                           file_hash, embedding_model, embedding_dim, upsert_ts
                    FROM _chunks
                ) TO '{compacted_path}' (FORMAT PARQUET)
            """)

            # Remove old files
            old_files = _get_parquet_files(coll_dir)
            for f in old_files:
                if f != compacted_path:
                    os.remove(f)

            _bump_collection_epoch(coll_dir)
            logger.info(f"[RAG] Compacted {len(old_files)} files to 1, {count} live chunks")
            return count


# ---------------------------------------------------------------------------
# Backwards compatibility - alias for chromadb error
# ---------------------------------------------------------------------------

class ChromaUnavailableError(RuntimeError):
    """Kept for backwards compatibility - DuckDB store doesn't need this."""
    pass
