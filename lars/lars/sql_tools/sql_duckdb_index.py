"""
Dedicated DuckDB index for SQL schema RAG search.

This module is intentionally scoped to SQL schema retrieval:
- writer: `lars sql crawl` (rebuilds full index)
- readers: `sql_rag_search` / `sql_search`

It does not use parquet/shadow RAG storage for primary reads/writes.
When ClickHouse shadow-write is enabled, snapshots are mirrored for parity checks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

try:
    import yaml as _yaml
except ImportError:
    _yaml = None

from ..config import get_config
from ..rag.indexer import embed_texts

log = logging.getLogger(__name__)


# Python flag (no ENV): dedicated SQL-only DuckDB RAG pathway.
USE_DEDICATED_SQL_DUCKDB_INDEX = True

_SQL_CHUNK_CHARS = 1200
_SQL_CHUNK_OVERLAP = 200
_DUCKDB_THREADS = max(1, int(float(os.getenv("LARS_DUCKDB_THREADS", "1"))))
_SQL_EMBED_BATCH_SIZE = 256
_SQL_INDEX_STRIP_SAMPLE_ROWS = True
_SQL_INDEX_STRIP_VALUE_DISTRIBUTION = True
_SQL_INDEX_STRIP_FIELD_SAMPLE_VALUES = True
_SQL_INDEX_MAX_FIELD_DESCRIPTION_CHARS = max(
    80, int(os.getenv("LARS_SQL_INDEX_MAX_FIELD_DESCRIPTION_CHARS", "320"))
)
_SQL_READER_POOL_ENABLED = True
_SQL_READER_POOL_SIZE = 12
_SQL_READER_POOL_WAIT_SECONDS = 2.0
_SQL_QUERY_EMBED_TIMEOUT_SECONDS = 12.0
_SQL_QUERY_EMBED_MAX_RETRIES = 1
_SQL_QUERY_EMBED_RETRY_BASE_DELAY = 0.5
_SQL_QUERY_EMBED_CACHE_MAX_ENTRIES = 4096
_SQL_QUERY_EMBED_CACHE_TTL_SECONDS = 1800.0
_SQL_RAG_SHADOW_TABLES = ("sql_rag_chunks", "sql_rag_manifests", "sql_rag_meta")
_INDEX_FILE_NAME = "sql_rag_index.duckdb"
_write_lock = threading.Lock()
_reader_pool_lock = threading.Lock()
_reader_pool: "queue.LifoQueue[duckdb.DuckDBPyConnection]" = queue.LifoQueue(
    maxsize=_SQL_READER_POOL_SIZE
)
_reader_pool_created = 0
_query_embed_cache_lock = threading.Lock()
_query_embed_cache: "OrderedDict[str, tuple[float, List[float], int]]" = OrderedDict()


@dataclass(frozen=True)
class _TextChunk:
    text: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int


def _text_for_indexing(path: Path, raw_text: str) -> str:
    """
    Build a retrieval-optimized text payload from SQL sample YAML.

    Keep source metadata files intact on disk, but remove high-volume payloads
    that add noise for semantic table discovery.
    """
    suffix = path.suffix.lower()
    if suffix not in (".yaml", ".yml"):
        return raw_text
    if _yaml is None:
        return raw_text

    try:
        parsed = _yaml.safe_load(raw_text)
    except Exception:
        return raw_text

    if not isinstance(parsed, dict):
        return raw_text

    # Table documents contain large sample rows and often noisy value distributions.
    if parsed.get("table_name"):
        if _SQL_INDEX_STRIP_SAMPLE_ROWS:
            parsed.pop("sample_rows", None)
            parsed.pop("sample_columns", None)

        if _SQL_INDEX_STRIP_VALUE_DISTRIBUTION:
            columns = parsed.get("columns")
            if isinstance(columns, list):
                for col in columns:
                    if not isinstance(col, dict):
                        continue
                    metadata = col.get("metadata")
                    if isinstance(metadata, dict):
                        metadata.pop("value_distribution", None)

        try:
            return _yaml.safe_dump(
                parsed,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        except Exception:
            return raw_text

    # Field index docs can contain long "Sample values: ..." strings.
    if isinstance(parsed.get("fields"), list):
        fields = parsed.get("fields")
        for field in fields:
            if not isinstance(field, dict):
                continue
            description = field.get("description")
            if not isinstance(description, str):
                continue

            if _SQL_INDEX_STRIP_FIELD_SAMPLE_VALUES:
                description = re.sub(
                    r"Sample values:\s.*?(?=(?:Range:|$))",
                    "",
                    description,
                    flags=re.IGNORECASE | re.DOTALL,
                )
            description = re.sub(r"\s+", " ", description).strip()
            if (
                _SQL_INDEX_MAX_FIELD_DESCRIPTION_CHARS > 0
                and len(description) > _SQL_INDEX_MAX_FIELD_DESCRIPTION_CHARS
            ):
                description = description[: _SQL_INDEX_MAX_FIELD_DESCRIPTION_CHARS - 3] + "..."
            field["description"] = description

        try:
            return _yaml.safe_dump(
                parsed,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        except Exception:
            return raw_text

    return raw_text


def sql_index_db_path() -> Path:
    cfg = get_config()
    sql_dir = Path(cfg.root_dir) / "sql_connections"
    sql_dir.mkdir(parents=True, exist_ok=True)
    return sql_dir / _INDEX_FILE_NAME


def _open_connection(*, read_only: bool) -> Optional[duckdb.DuckDBPyConnection]:
    db_path = sql_index_db_path()
    if read_only and not db_path.exists():
        return None
    conn = duckdb.connect(str(db_path), read_only=read_only)
    conn.execute(f"SET threads TO {_DUCKDB_THREADS}")
    return conn


def _close_reader_pool() -> None:
    """
    Close all idle pooled read connections.

    Called before opening a writer connection to avoid mixed-configuration
    connection errors if this process previously handled reads.
    """
    global _reader_pool_created

    closed = 0
    while True:
        try:
            conn = _reader_pool.get_nowait()
        except queue.Empty:
            break
        try:
            conn.close()
        except Exception:
            pass
        finally:
            closed += 1

    if closed <= 0:
        return

    with _reader_pool_lock:
        _reader_pool_created = max(0, int(_reader_pool_created) - closed)


def _open_reader_connection() -> Optional[duckdb.DuckDBPyConnection]:
    try:
        return _open_connection(read_only=True)
    except Exception as e:
        # Recover from "different configuration" by draining idle pooled readers once.
        if "different configuration" in str(e).lower():
            _close_reader_pool()
            return _open_connection(read_only=True)
        raise


def _acquire_reader_connection() -> tuple[Optional[duckdb.DuckDBPyConnection], bool]:
    """
    Acquire a read connection.

    Returns: (conn, pooled_slot)
      - pooled_slot=True: connection should be returned to pool on release
      - pooled_slot=False: one-off connection, close after use
    """
    global _reader_pool_created

    if not _SQL_READER_POOL_ENABLED:
        return _open_reader_connection(), False

    try:
        return _reader_pool.get_nowait(), True
    except queue.Empty:
        pass

    with _reader_pool_lock:
        if _reader_pool_created < _SQL_READER_POOL_SIZE:
            conn = _open_reader_connection()
            if conn is None:
                return None, False
            _reader_pool_created += 1
            return conn, True

    try:
        conn = _reader_pool.get(timeout=_SQL_READER_POOL_WAIT_SECONDS)
        return conn, True
    except queue.Empty:
        # Burst fallback: do not count in steady-state pool.
        return _open_reader_connection(), False


def _release_reader_connection(
    conn: duckdb.DuckDBPyConnection,
    *,
    pooled_slot: bool,
    reusable: bool = True,
) -> None:
    global _reader_pool_created

    if not pooled_slot or not _SQL_READER_POOL_ENABLED or not reusable:
        try:
            conn.close()
        finally:
            if pooled_slot:
                with _reader_pool_lock:
                    _reader_pool_created = max(0, int(_reader_pool_created) - 1)
        return

    try:
        _reader_pool.put_nowait(conn)
    except queue.Full:
        # Should be rare, but avoid leaking.
        try:
            conn.close()
        finally:
            with _reader_pool_lock:
                _reader_pool_created = max(0, int(_reader_pool_created) - 1)


@contextmanager
def _reader_connection() -> Any:
    conn, pooled_slot = _acquire_reader_connection()
    if conn is None:
        yield None
        return
    try:
        yield conn
        _release_reader_connection(conn, pooled_slot=pooled_slot, reusable=True)
    except Exception:
        _release_reader_connection(conn, pooled_slot=pooled_slot, reusable=False)
        raise


def _normalize_query_text(query: str) -> str:
    return " ".join((query or "").strip().split()).lower()


def _query_embed_cache_key(embed_model: str, query: str) -> str:
    normalized = _normalize_query_text(query)
    return f"{embed_model}\n{normalized}"


def _get_cached_query_embedding(embed_model: str, query: str) -> tuple[Optional[List[float]], int]:
    now = time.time()
    key = _query_embed_cache_key(embed_model, query)
    with _query_embed_cache_lock:
        entry = _query_embed_cache.get(key)
        if not entry:
            return None, 0
        expires_at, vec, dim = entry
        if now >= float(expires_at):
            _query_embed_cache.pop(key, None)
            return None, 0
        _query_embed_cache.move_to_end(key)
        return list(vec), int(dim or len(vec) or 0)


def _set_cached_query_embedding(embed_model: str, query: str, vec: List[float], dim: int) -> None:
    if not vec:
        return
    key = _query_embed_cache_key(embed_model, query)
    expires_at = time.time() + _SQL_QUERY_EMBED_CACHE_TTL_SECONDS
    with _query_embed_cache_lock:
        _query_embed_cache[key] = (expires_at, list(vec), int(dim or len(vec) or 0))
        _query_embed_cache.move_to_end(key)
        while len(_query_embed_cache) > _SQL_QUERY_EMBED_CACHE_MAX_ENTRIES:
            _query_embed_cache.popitem(last=False)


def _lexical_search_sql_index(
    *,
    rag_id: str,
    query: str,
    k: int,
    score_threshold: Optional[float],
) -> List[Dict[str, Any]]:
    """
    Fast fallback when query embedding fails (provider timeout/rate limit).

    Uses token overlap against chunk text and returns the same result shape as
    vector search so callers can continue without special handling.
    """
    tokens = []
    for token in re.findall(r"[A-Za-z0-9_]+", query.lower()):
        if len(token) < 2:
            continue
        if token in {"the", "and", "for", "with", "from", "into", "table", "tables"}:
            continue
        tokens.append(token)
    # De-dupe while preserving order.
    tokens = list(dict.fromkeys(tokens))[:12]
    if not tokens:
        return []

    score_threshold_value = float(score_threshold) if score_threshold is not None else None
    # Conservative lexical threshold to avoid very broad noise.
    if score_threshold_value is None:
        score_threshold_value = 0.15
    else:
        score_threshold_value = min(score_threshold_value, 0.15)

    conditions: List[str] = []
    like_args: List[str] = []
    for token in tokens:
        conditions.append("LOWER(text) LIKE ?")
        like_args.append(f"%{token}%")

    if not conditions:
        return []

    hit_count_expr = " + ".join([f"CASE WHEN {cond} THEN 1 ELSE 0 END" for cond in conditions])
    min_hits = max(1, int(len(tokens) * score_threshold_value))
    fetch_n = max(int(k) * 4, int(k) + 8)

    sql = f"""
        SELECT
            doc_id,
            chunk_index,
            rel_path,
            start_line,
            end_line,
            text,
            ({hit_count_expr}) AS hit_count
        FROM sql_rag_chunks
        WHERE rag_id = ?
          AND ({' OR '.join(conditions)})
        ORDER BY hit_count DESC, doc_id, chunk_index
        LIMIT ?
    """
    args: List[Any] = [*like_args, rag_id, *like_args, fetch_n]

    with _reader_connection() as conn:
        if conn is None:
            return []
        rows = conn.execute(sql, args).fetchall()

    results: List[Dict[str, Any]] = []
    for row in rows:
        hit_count = int(row[6] or 0)
        if hit_count < min_hits:
            continue
        score = hit_count / max(1, len(tokens))
        results.append(
            {
                "chunk_id": f"{row[0]}_{int(row[1] or 0)}",
                "doc_id": str(row[0] or ""),
                "source": str(row[2] or ""),
                "lines": [int(row[3] or 0), int(row[4] or 0)],
                "score": float(score),
                "snippet": str(row[5] or "")[:400].strip(),
            }
        )
        if len(results) >= int(k):
            break

    return results


def _embed_texts_in_batches(
    *,
    texts: List[str],
    model: str,
    session_id: Optional[str],
    trace_id: Optional[str],
    parent_id: Optional[str],
    cell_name: str,
    cascade_id: Optional[str],
) -> tuple[List[List[float]], str, int]:
    """
    Embed sequentially in batches for stability.

    Using a single process/model instance avoids parallel local-model startup
    overhead and reduces long-tail stalls during `lars sql crawl`.
    """
    if not texts:
        return [], model, 0

    all_embeddings: List[List[float]] = []
    model_used = model
    embedding_dim = 0

    for start in range(0, len(texts), _SQL_EMBED_BATCH_SIZE):
        batch = texts[start : start + _SQL_EMBED_BATCH_SIZE]
        result = embed_texts(
            texts=batch,
            model=model,
            session_id=session_id,
            trace_id=trace_id,
            parent_id=parent_id,
            cell_name=cell_name,
            cascade_id=cascade_id,
        )
        batch_embeddings = result.get("embeddings") or []
        if len(batch_embeddings) != len(batch):
            raise RuntimeError(
                f"Embedding batch mismatch: expected {len(batch)}, got {len(batch_embeddings)}"
            )

        current_dim = int(result.get("dim") or (len(batch_embeddings[0]) if batch_embeddings else 0))
        if embedding_dim and current_dim and embedding_dim != current_dim:
            raise RuntimeError(
                f"Embedding dimension changed across batches: {embedding_dim} -> {current_dim}"
            )

        if current_dim:
            embedding_dim = current_dim
        model_used = str(result.get("model") or model_used)
        all_embeddings.extend([[float(x) for x in vec] for vec in batch_embeddings])

    return all_embeddings, model_used, int(embedding_dim)


def _ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sql_rag_chunks (
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
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sql_rag_manifests (
            rag_id VARCHAR,
            doc_id VARCHAR,
            rel_path VARCHAR,
            file_hash VARCHAR,
            file_size BIGINT,
            mtime BIGINT,
            chunk_count INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sql_rag_meta (
            rag_id VARCHAR PRIMARY KEY,
            embed_model VARCHAR,
            embedding_dim INTEGER,
            samples_dir VARCHAR,
            doc_count INTEGER,
            chunk_count INTEGER,
            updated_at BIGINT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sql_rag_chunks_rag ON sql_rag_chunks(rag_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sql_rag_chunks_rel ON sql_rag_chunks(rag_id, rel_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sql_rag_manifest_rag ON sql_rag_manifests(rag_id)")


def _chunk_id(rag_id: str, doc_id: str, chunk_index: int) -> str:
    raw = f"{rag_id}\n{doc_id}\n{int(chunk_index)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _doc_id_for_path(rag_id: str, rel_path: str) -> str:
    digest = hashlib.sha1(f"{rag_id}:{rel_path}".encode()).hexdigest()
    return digest[:12]


def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[_TextChunk]:
    norm = text.replace("\r\n", "\n")
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 2)

    chunks: List[_TextChunk] = []
    start = 0
    total_len = len(norm)

    while start < total_len:
        end = min(total_len, start + chunk_size)
        chunk_text = norm[start:end]

        if not chunk_text.strip():
            if end >= total_len:
                break
            start = end
            continue

        start_line = norm.count("\n", 0, start) + 1
        end_line = norm.count("\n", 0, end) + 1
        chunks.append(
            _TextChunk(
                text=chunk_text,
                start_char=start,
                end_char=end,
                start_line=start_line,
                end_line=end_line,
            )
        )

        if end >= total_len:
            break

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def _collect_sample_files(samples_dir: str) -> List[Path]:
    base = Path(samples_dir)
    if not base.exists():
        return []
    files = sorted(base.rglob("*.yaml"))
    if files:
        return files
    # Legacy fallback.
    return sorted(base.rglob("*.yml"))


def _compute_sql_rag_id(samples_dir: str, embed_model: str) -> str:
    abs_dir = os.path.abspath(os.path.expanduser(samples_dir))
    settings_key = json.dumps(
        {
            "directory": abs_dir,
            "recursive": True,
            "include": ["*.yaml"],
            "exclude": [],
            "chunk_chars": _SQL_CHUNK_CHARS,
            "chunk_overlap": _SQL_CHUNK_OVERLAP,
            "embed_model": embed_model,
        },
        sort_keys=True,
    )
    return hashlib.sha1(settings_key.encode()).hexdigest()[:12]


def _mirror_sql_index_snapshot_to_shadow(
    *,
    rag_id: str,
    model_used: str,
    embedding_dim: int,
    abs_samples: str,
    chunk_rows: List[Tuple[Any, ...]],
    manifest_rows: List[Tuple[Any, ...]],
    updated_at_ms: int,
) -> None:
    """
    Best-effort mirror of SQL schema index snapshots to ClickHouse shadow tables.
    """
    try:
        from ..db_adapter import get_shadow_write_stats, mirror_rows_to_shadow

        stats = get_shadow_write_stats()
        if not stats.get("enabled"):
            return

        write_all_tables = bool(stats.get("write_all_tables"))
        configured_tables = set(stats.get("tables") or [])
        if not write_all_tables and configured_tables.isdisjoint(_SQL_RAG_SHADOW_TABLES):
            return

        chunk_dict_rows = [
            {
                "chunk_id": row[0],
                "rag_id": row[1],
                "doc_id": row[2],
                "chunk_index": row[3],
                "text": row[4],
                "embedding": row[5],
                "rel_path": row[6],
                "start_line": row[7],
                "end_line": row[8],
                "char_start": row[9],
                "char_end": row[10],
                "file_hash": row[11],
                "embedding_model": row[12],
                "embedding_dim": row[13],
                "upsert_ts": row[14],
            }
            for row in chunk_rows
        ]
        manifest_dict_rows = [
            {
                "rag_id": row[0],
                "doc_id": row[1],
                "rel_path": row[2],
                "file_hash": row[3],
                "file_size": row[4],
                "mtime": row[5],
                "chunk_count": row[6],
            }
            for row in manifest_rows
        ]
        meta_rows = [
            {
                "rag_id": rag_id,
                "embed_model": model_used,
                "embedding_dim": int(embedding_dim),
                "samples_dir": abs_samples,
                "doc_count": len(manifest_rows),
                "chunk_count": len(chunk_rows),
                "updated_at": updated_at_ms,
            }
        ]

        # Snapshot semantics: full-refresh each table on every crawl.
        mirror_rows_to_shadow(
            table="sql_rag_chunks",
            rows=chunk_dict_rows,
            clear_table=True,
            flush=True,
            batch_rows=500,
            normalize_rows=False,
        )
        mirror_rows_to_shadow(
            table="sql_rag_manifests",
            rows=manifest_dict_rows,
            clear_table=True,
            flush=True,
            batch_rows=1000,
            normalize_rows=False,
        )
        mirror_rows_to_shadow(
            table="sql_rag_meta",
            rows=meta_rows,
            clear_table=True,
            flush=True,
            batch_rows=100,
            normalize_rows=False,
        )
    except Exception as e:
        # Dedicated SQL index writes must not fail if shadow sink is unavailable.
        log.debug("[SQL RAG] Shadow snapshot mirror skipped: %s", e)


def rebuild_sql_index(
    *,
    samples_dir: str,
    embed_model: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    cell_name: str = "sql_crawl",
    cascade_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Rebuild the dedicated SQL schema vector index from sample YAML files.
    """
    cfg = get_config()
    model = str(embed_model or cfg.default_embed_model)
    abs_samples = os.path.abspath(os.path.expanduser(samples_dir))
    rag_id = _compute_sql_rag_id(abs_samples, model)

    files = _collect_sample_files(abs_samples)
    chunk_meta_rows: List[Tuple[Any, ...]] = []
    manifest_rows: List[Tuple[Any, ...]] = []
    all_texts: List[str] = []

    for path in files:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not raw_text.strip():
            continue

        text = _text_for_indexing(path, raw_text)
        if not text.strip():
            continue

        rel_path = path.relative_to(abs_samples).as_posix()
        # Track source file hash (not transformed index text hash).
        file_hash = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()
        stat = path.stat()
        mtime = int(stat.st_mtime)
        file_size = int(stat.st_size)
        doc_id = _doc_id_for_path(rag_id, rel_path)

        chunks = _chunk_text(text, _SQL_CHUNK_CHARS, _SQL_CHUNK_OVERLAP)
        if not chunks:
            continue

        manifest_rows.append(
            (
                rag_id,
                doc_id,
                rel_path,
                file_hash,
                file_size,
                mtime,
                len(chunks),
            )
        )

        for chunk_index, chunk in enumerate(chunks):
            all_texts.append(chunk.text)
            chunk_meta_rows.append(
                (
                    _chunk_id(rag_id, doc_id, chunk_index),
                    rag_id,
                    doc_id,
                    int(chunk_index),
                    chunk.text,
                    rel_path,
                    int(chunk.start_line),
                    int(chunk.end_line),
                    int(chunk.start_char),
                    int(chunk.end_char),
                    file_hash,
                )
            )

    embeddings: List[List[float]] = []
    embedding_dim = 0
    model_used = model

    if all_texts:
        embeddings, model_used, embedding_dim = _embed_texts_in_batches(
            texts=all_texts,
            model=model,
            session_id=session_id,
            trace_id=trace_id,
            parent_id=parent_id,
            cell_name=cell_name,
            cascade_id=cascade_id,
        )
        if len(embeddings) != len(chunk_meta_rows):
            raise RuntimeError(
                f"Embedding count mismatch: expected {len(chunk_meta_rows)}, got {len(embeddings)}"
            )

    ts = int(time.time() * 1000)
    chunk_rows: List[Tuple[Any, ...]] = []
    for idx, meta in enumerate(chunk_meta_rows):
        vec = embeddings[idx] if idx < len(embeddings) else []
        chunk_rows.append(
            (
                meta[0],  # chunk_id
                meta[1],  # rag_id
                meta[2],  # doc_id
                meta[3],  # chunk_index
                meta[4],  # text
                vec,      # embedding
                meta[5],  # rel_path
                meta[6],  # start_line
                meta[7],  # end_line
                meta[8],  # char_start
                meta[9],  # char_end
                meta[10], # file_hash
                model_used,
                int(embedding_dim),
                ts,
            )
        )

    with _write_lock:
        _close_reader_pool()
        try:
            conn = _open_connection(read_only=False)
        except Exception as e:
            if "different configuration" in str(e).lower():
                _close_reader_pool()
                conn = _open_connection(read_only=False)
            else:
                raise
        if conn is None:
            raise RuntimeError("Failed to open SQL index DuckDB database.")
        try:
            _ensure_schema(conn)
            conn.execute("BEGIN")
            # Full refresh: SQL schema index is disposable and rebuilt as a whole.
            conn.execute("DELETE FROM sql_rag_chunks")
            conn.execute("DELETE FROM sql_rag_manifests")
            conn.execute("DELETE FROM sql_rag_meta")

            if chunk_rows:
                conn.executemany(
                    """
                    INSERT INTO sql_rag_chunks (
                        chunk_id, rag_id, doc_id, chunk_index, text, embedding,
                        rel_path, start_line, end_line, char_start, char_end,
                        file_hash, embedding_model, embedding_dim, upsert_ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    chunk_rows,
                )

            if manifest_rows:
                conn.executemany(
                    """
                    INSERT INTO sql_rag_manifests (
                        rag_id, doc_id, rel_path, file_hash, file_size, mtime, chunk_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    manifest_rows,
                )

            conn.execute(
                """
                INSERT INTO sql_rag_meta (
                    rag_id, embed_model, embedding_dim, samples_dir, doc_count, chunk_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (rag_id) DO UPDATE SET
                    embed_model = EXCLUDED.embed_model,
                    embedding_dim = EXCLUDED.embedding_dim,
                    samples_dir = EXCLUDED.samples_dir,
                    doc_count = EXCLUDED.doc_count,
                    chunk_count = EXCLUDED.chunk_count,
                    updated_at = EXCLUDED.updated_at
                """,
                [
                    rag_id,
                    model_used,
                    int(embedding_dim),
                    abs_samples,
                    len(manifest_rows),
                    len(chunk_rows),
                    ts,
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    _mirror_sql_index_snapshot_to_shadow(
        rag_id=rag_id,
        model_used=model_used,
        embedding_dim=int(embedding_dim),
        abs_samples=abs_samples,
        chunk_rows=chunk_rows,
        manifest_rows=manifest_rows,
        updated_at_ms=ts,
    )

    return {
        "rag_id": rag_id,
        "embed_model": model_used,
        "embedding_dim": int(embedding_dim),
        "doc_count": len(manifest_rows),
        "chunk_count": len(chunk_rows),
        "db_path": str(sql_index_db_path()),
    }


def get_sql_index_meta(rag_id: str) -> tuple[bool, int]:
    with _reader_connection() as conn:
        if conn is None:
            return False, 0
        try:
            row = conn.execute(
                """
                SELECT chunk_count, embedding_dim
                FROM sql_rag_meta
                WHERE rag_id = ?
                LIMIT 1
                """,
                [rag_id],
            ).fetchone()
            if row:
                return int(row[0] or 0) > 0, int(row[1] or 0)

            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt, MAX(embedding_dim) AS embedding_dim
                FROM sql_rag_chunks
                WHERE rag_id = ?
                """,
                [rag_id],
            ).fetchone()
            if not row:
                return False, 0
            return int(row[0] or 0) > 0, int(row[1] or 0)
        except Exception:
            return False, 0


def search_sql_index(
    *,
    rag_id: str,
    embed_model: str,
    query: str,
    k: int = 10,
    score_threshold: Optional[float] = 0.3,
    index_embedding_dim: Optional[int] = None,
    query_embedding: Optional[List[float]] = None,
    query_embedding_model: Optional[str] = None,
    query_embedding_dim: Optional[int] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    cell_name: Optional[str] = None,
    cascade_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    index_dim = int(index_embedding_dim or 0)
    if index_dim <= 0:
        has_chunks, index_dim = get_sql_index_meta(rag_id)
        if not has_chunks:
            return []

    if query_embedding is not None:
        model_matches = (query_embedding_model is None) or (query_embedding_model == embed_model)
        vec = [float(x) for x in query_embedding]
        vec_dim = int(query_embedding_dim or len(vec) or 0)
        dim_matches = vec_dim <= 0 or index_dim <= 0 or vec_dim == int(index_dim)
        use_precomputed = model_matches and dim_matches
    else:
        vec = []
        vec_dim = 0
        use_precomputed = False

    fallback_to_lexical = False
    if not use_precomputed:
        cached_vec, cached_dim = _get_cached_query_embedding(embed_model, query)
        if cached_vec:
            vec = cached_vec
            vec_dim = int(cached_dim or len(vec) or 0)
        else:
            try:
                embed_result = embed_texts(
                    texts=[query],
                    model=embed_model,
                    session_id=session_id,
                    trace_id=trace_id,
                    parent_id=parent_id,
                    cell_name=cell_name,
                    cascade_id=cascade_id,
                    timeout_seconds=_SQL_QUERY_EMBED_TIMEOUT_SECONDS,
                    max_retries=_SQL_QUERY_EMBED_MAX_RETRIES,
                    retry_base_delay=_SQL_QUERY_EMBED_RETRY_BASE_DELAY,
                )
                vec = [float(x) for x in (embed_result.get("embeddings") or [[]])[0]]
                vec_dim = int(embed_result.get("dim") or len(vec) or 0)
                if vec:
                    _set_cached_query_embedding(embed_model, query, vec, vec_dim)
            except Exception:
                fallback_to_lexical = True

    if fallback_to_lexical:
        return _lexical_search_sql_index(
            rag_id=rag_id,
            query=query,
            k=k,
            score_threshold=score_threshold,
        )

    if not vec:
        return []

    if index_dim and vec_dim and int(index_dim) != int(vec_dim):
        raise ValueError(
            f"Embedding dimension mismatch (index {index_dim} dims, query {vec_dim} dims). "
            "Re-index SQL schemas with the current embedding model."
        )

    dim = int(index_dim or vec_dim)
    fetch_n = int(k)
    if score_threshold is not None:
        fetch_n = max(fetch_n * 4, fetch_n + 10)

    with _reader_connection() as conn:
        if conn is None:
            return []
        rows = conn.execute(
            f"""
            SELECT
                doc_id,
                chunk_index,
                rel_path,
                start_line,
                end_line,
                text,
                1.0 - array_cosine_similarity(
                    embedding::FLOAT[{dim}],
                    ?::FLOAT[{dim}]
                ) AS distance
            FROM sql_rag_chunks
            WHERE rag_id = ?
            ORDER BY distance ASC
            LIMIT ?
            """,
            [vec, rag_id, fetch_n],
        ).fetchall()

    formatted: List[Dict[str, Any]] = []
    for row in rows:
        doc_id = str(row[0] or "")
        chunk_index = int(row[1] or 0)
        rel_path = str(row[2] or "")
        start_line = int(row[3] or 0)
        end_line = int(row[4] or 0)
        text = str(row[5] or "")
        distance = float(row[6]) if row[6] is not None else None
        score = 1.0 - distance if distance is not None else 0.0

        if score_threshold is not None and score < float(score_threshold):
            continue

        formatted.append(
            {
                "chunk_id": f"{doc_id}_{chunk_index}",
                "doc_id": doc_id,
                "source": rel_path,
                "lines": [start_line, end_line],
                "score": float(score),
                "snippet": text[:400].strip(),
            }
        )
        if len(formatted) >= int(k):
            break

    return formatted
