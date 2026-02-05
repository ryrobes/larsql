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
- Reads are lock-free (parquet files are immutable once written)
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
import glob
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _get_rag_path() -> str:
    """Get the RAG storage directory from config."""
    from ..config import get_config
    cfg = get_config()
    # Use a dedicated rag directory within the data path
    base = getattr(cfg, 'data_path', None) or os.path.expanduser("~/.lars/data")
    rag_path = os.path.join(os.path.abspath(os.path.expanduser(base)), "rag")
    os.makedirs(rag_path, exist_ok=True)
    return rag_path


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

_duckdb_conn: Any = None
_duckdb_lock = threading.Lock()


def _get_connection():
    """Get a DuckDB connection with VSS and FTS extensions loaded."""
    global _duckdb_conn
    
    if _duckdb_conn is not None:
        return _duckdb_conn
    
    with _duckdb_lock:
        if _duckdb_conn is not None:
            return _duckdb_conn
        
        import duckdb
        
        # Use in-memory connection - we read/write parquet files directly
        _duckdb_conn = duckdb.connect(":memory:")
        _duckdb_conn.execute("SET threads TO 4")  # Limit CPU usage
        
        # Install and load extensions
        _duckdb_conn.execute("INSTALL vss; LOAD vss")
        _duckdb_conn.execute("INSTALL fts; LOAD fts")
        
        logger.info("[RAG] DuckDB vector store initialized with VSS and FTS extensions")
        return _duckdb_conn


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
# Core operations
# ---------------------------------------------------------------------------

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
            "upsert_ts": int(time.time() * 1000),
        })

    with _write_lock:
        with _interprocess_lock(lock_path):
            conn = _get_connection()
            
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
            
            logger.debug(f"[RAG] Wrote {len(records)} chunks to {parquet_path}")


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
            conn = _get_connection()
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
            """, [rag_id, int(time.time() * 1000)])
            conn.execute(f"COPY _tombstone_tmp TO '{tombstone_path}' (FORMAT PARQUET)")
            conn.execute("DROP TABLE _tombstone_tmp")
            
            logger.debug(f"[RAG] Wrote tombstone for rag_id={rag_id}")


def delete_by_doc_id(embed_model: str, embedding_dim: int, rag_id: str, doc_id: str) -> None:
    """
    Delete all chunks for a given rag_id + doc_id combination.
    """
    coll_dir = _collection_dir(embed_model, embedding_dim)
    lock_path = os.path.join(coll_dir, ".write.lock")

    with _write_lock:
        with _interprocess_lock(lock_path):
            conn = _get_connection()
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
            """, [rag_id, doc_id, int(time.time() * 1000)])
            conn.execute(f"COPY _tombstone_tmp TO '{tombstone_path}' (FORMAT PARQUET)")
            conn.execute("DROP TABLE _tombstone_tmp")
            
            logger.debug(f"[RAG] Wrote tombstone for rag_id={rag_id}, doc_id={doc_id}")


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
    conn = _get_connection()
    
    # Build view of live chunks
    if not _build_chunks_view(conn, coll_dir, embedding_dim):
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    
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
    
    return {
        "ids": [ids],
        "documents": [documents],
        "metadatas": [metadatas],
        "distances": [distances],
    }


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
    conn = _get_connection()
    
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
    conn = _get_connection()
    
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
            conn = _get_connection()
            
            if not _build_chunks_view(conn, coll_dir, embedding_dim):
                return 0
            
            # Count live chunks
            count = conn.execute("SELECT COUNT(*) FROM _chunks").fetchone()[0]
            
            if count == 0:
                # No live chunks - delete all files
                for f in _get_parquet_files(coll_dir):
                    os.remove(f)
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
            
            logger.info(f"[RAG] Compacted {len(old_files)} files to 1, {count} live chunks")
            return count


# ---------------------------------------------------------------------------
# Backwards compatibility - alias for chromadb error
# ---------------------------------------------------------------------------

class ChromaUnavailableError(RuntimeError):
    """Kept for backwards compatibility - DuckDB store doesn't need this."""
    pass
