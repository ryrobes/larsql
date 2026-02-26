"""
RAG shadow DuckDB read store.

Maintains a single writable DuckDB file that mirrors parquet-backed RAG
collections. One process becomes refresh leader via file lock; all processes
can read from the shadow file.
"""

from __future__ import annotations

import atexit
import fcntl
import glob
import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb


log = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _env_float(name: str, default: float, minimum: float = 0.1) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
        return max(minimum, value)
    except Exception:
        return default


# Default-on for evaluation; can be disabled with LARS_RAG_SHADOW_ENABLED=0.
_SHADOW_ENABLED = _env_bool("LARS_RAG_SHADOW_ENABLED", True)
_REFRESH_INTERVAL_SECONDS = _env_float("LARS_RAG_SHADOW_REFRESH_INTERVAL_SECONDS", 1.0, minimum=0.1)
_LEADER_RETRY_SECONDS = _env_float("LARS_RAG_SHADOW_LEADER_RETRY_SECONDS", 1.0, minimum=0.1)
_STALE_AFTER_SECONDS = _env_float("LARS_RAG_SHADOW_STALE_SECONDS", 10.0, minimum=1.0)
_MAX_STALE_SECONDS = _env_float("LARS_RAG_SHADOW_MAX_STALE_SECONDS", 60.0, minimum=1.0)
_DUCKDB_THREADS = max(1, int(float(os.getenv("LARS_DUCKDB_THREADS", "1"))))


def _has_collection_data(rag_path: Path) -> bool:
    if not rag_path.exists():
        return False
    try:
        for entry in rag_path.iterdir():
            if not entry.is_dir():
                continue
            if glob.glob(str(entry / "*.parquet")):
                return True
    except Exception:
        return False
    return False


def _resolve_rag_path() -> Path:
    from ..config import get_config

    cfg = get_config()
    preferred_base = (
        getattr(cfg, "data_dir", None)
        or getattr(cfg, "data_path", None)
        or os.path.expanduser("~/.lars/data")
    )
    preferred = Path(os.path.abspath(os.path.expanduser(preferred_base))) / "rag"
    legacy = Path(os.path.expanduser("~/.lars/data")) / "rag"

    if preferred.resolve() != legacy.resolve():
        if _has_collection_data(legacy) and not _has_collection_data(preferred):
            log.warning(
                "[RAG Shadow] Preferred RAG path %s is empty; using legacy path %s until re-indexed.",
                str(preferred),
                str(legacy),
            )
            preferred = legacy

    preferred.mkdir(parents=True, exist_ok=True)
    return preferred


def _collection_key(embed_model: str, embedding_dim: int) -> str:
    model_hash = hashlib.sha1(embed_model.encode("utf-8")).hexdigest()[:12]
    return f"{model_hash}_{int(embedding_dim)}"


def _collection_table_name(key: str) -> str:
    return f"chunks_{key}"


def _load_extension(conn: duckdb.DuckDBPyConnection, extension_name: str) -> None:
    try:
        conn.execute(f"LOAD {extension_name}")
        return
    except Exception:
        pass
    try:
        conn.execute(f"INSTALL {extension_name}")
    except Exception:
        pass
    conn.execute(f"LOAD {extension_name}")


class RagShadowStore:
    """Single-writer shadow DB refresher + multi-process readers."""

    _instance: Optional["RagShadowStore"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._enabled = _SHADOW_ENABLED
        self._rag_path = _resolve_rag_path()
        self._shadow_dir = self._rag_path / ".shadow"
        self._db_path = self._shadow_dir / "rag_shadow.duckdb"
        self._leader_lock_path = self._shadow_dir / ".rag_shadow.lock"
        self._heartbeat_path = self._shadow_dir / ".rag_shadow.heartbeat"

        self._stop_event = threading.Event()
        self._refresh_thread: Optional[threading.Thread] = None
        self._leader_fd: Optional[Any] = None
        self._writer_conn: Optional[duckdb.DuckDBPyConnection] = None
        self._start_lock = threading.Lock()
        self._conn_lock = threading.Lock()

        self._initialized = True
        atexit.register(self.stop)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def rag_path(self) -> Path:
        return self._rag_path

    def serves_collection_dir(self, collection_dir: str | Path) -> bool:
        """
        Return True only if this shadow store is responsible for collection_dir.

        This guards against mismatched roots (e.g., tests patching duckdb_store
        path while shadow store resolves its own path).
        """
        try:
            coll_path = Path(collection_dir).resolve()
            return coll_path.parent == self._rag_path.resolve()
        except Exception:
            return False

    def start(self) -> None:
        if not self._enabled:
            return

        with self._start_lock:
            if self._refresh_thread and self._refresh_thread.is_alive():
                return
            self._shadow_dir.mkdir(parents=True, exist_ok=True)
            self._stop_event.clear()
            self._refresh_thread = threading.Thread(
                target=self._refresh_loop,
                daemon=True,
                name="rag-shadow-refresh",
            )
            self._refresh_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=2.0)
        self._refresh_thread = None
        self._close_writer_connection()
        self._release_leader_lock()

    def is_fresh(self, max_stale_seconds: float = _STALE_AFTER_SECONDS) -> bool:
        if not self._enabled:
            return False
        if max_stale_seconds <= 0:
            max_stale_seconds = _STALE_AFTER_SECONDS
        max_stale_seconds = min(max_stale_seconds, _MAX_STALE_SECONDS)

        if not self._db_path.exists():
            return False
        if not self._heartbeat_path.exists():
            return False

        try:
            age = time.time() - self._heartbeat_path.stat().st_mtime
            return age <= max_stale_seconds
        except Exception:
            return False

    def query_chunks(
        self,
        embed_model: str,
        embedding_dim: int,
        rag_id: str,
        query_embedding: list[float],
        n_results: int,
        *,
        max_stale_seconds: float = _STALE_AFTER_SECONDS,
    ) -> Optional[Dict[str, Any]]:
        if not self.is_fresh(max_stale_seconds=max_stale_seconds):
            return None
        # Avoid read/write mode conflicts in the current leader process:
        # the leader is responsible for refresh writes only.
        if self._leader_fd is not None:
            return None

        table_name = _collection_table_name(_collection_key(embed_model, int(embedding_dim)))
        collection_key = _collection_key(embed_model, int(embedding_dim))

        for attempt in range(2):
            with self._conn_lock:
                conn = self._open_read_connection()
                if conn is None:
                    return None

                try:
                    if not self._collection_manifest_matches_source(conn, collection_key):
                        return None

                    # Verify relation exists before querying.
                    exists = conn.execute(
                        """
                        SELECT COUNT(*) AS cnt
                        FROM information_schema.tables
                        WHERE table_schema = 'main' AND table_name = ?
                        """,
                        [table_name],
                    ).fetchone()
                    if not exists or int(exists[0]) == 0:
                        return None

                    embedding_str = "[" + ", ".join(str(float(x)) for x in query_embedding) + "]"
                    rows = conn.execute(
                        f"""
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
                            1.0 - array_cosine_similarity(
                                embedding::FLOAT[{int(embedding_dim)}],
                                {embedding_str}::FLOAT[{int(embedding_dim)}]
                            ) AS distance
                        FROM {table_name}
                        WHERE rag_id = ?
                        ORDER BY distance ASC
                        LIMIT ?
                        """,
                        [rag_id, int(n_results)],
                    ).fetchall()

                    ids: list[str] = []
                    docs: list[str] = []
                    metas: list[Dict[str, Any]] = []
                    distances: list[float] = []
                    for row in rows:
                        ids.append(row[0])
                        docs.append(row[1])
                        metas.append(
                            {
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
                            }
                        )
                        distances.append(row[13])

                    return {
                        "ids": [ids],
                        "documents": [docs],
                        "metadatas": [metas],
                        "distances": [distances],
                    }
                except Exception:
                    if attempt == 1:
                        return None
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

        return None

    # ------------------------------------------------------------------
    # Refresh internals
    # ------------------------------------------------------------------

    def _refresh_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._ensure_leader_lock():
                self._stop_event.wait(_LEADER_RETRY_SECONDS)
                continue

            try:
                self._refresh_once()
                self._touch_heartbeat()
                # Release DuckDB file lock between refresh cycles so other
                # processes can open read connections to the shadow snapshot.
                self._close_writer_connection()
            except Exception as e:
                log.warning(f"[RAG Shadow] refresh failed: {e}")
                self._close_writer_connection()
                self._stop_event.wait(_LEADER_RETRY_SECONDS)
                continue

            self._stop_event.wait(_REFRESH_INTERVAL_SECONDS)

    def _ensure_leader_lock(self) -> bool:
        if self._leader_fd is not None:
            return True
        try:
            fd = open(self._leader_lock_path, "a+")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._leader_fd = fd
            return True
        except (IOError, OSError):
            try:
                fd.close()
            except Exception:
                pass
            return False

    def _release_leader_lock(self) -> None:
        if self._leader_fd is None:
            return
        try:
            fcntl.flock(self._leader_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self._leader_fd.close()
        except Exception:
            pass
        self._leader_fd = None

    def _get_writer_connection(self) -> duckdb.DuckDBPyConnection:
        if self._writer_conn is not None:
            return self._writer_conn
        self._shadow_dir.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(self._db_path))
        conn.execute(f"SET threads TO {_DUCKDB_THREADS}")
        _load_extension(conn, "vss")
        _load_extension(conn, "fts")
        self._writer_conn = conn
        return self._writer_conn

    def _close_writer_connection(self) -> None:
        if self._writer_conn is not None:
            try:
                self._writer_conn.close()
            except Exception:
                pass
        self._writer_conn = None

    def _open_read_connection(self) -> Optional[duckdb.DuckDBPyConnection]:
        if not self._db_path.exists():
            return None

        try:
            # Read-only connections avoid taking writer-capable file locks.
            conn = duckdb.connect(str(self._db_path), read_only=True)
            conn.execute(f"SET threads TO {_DUCKDB_THREADS}")
            _load_extension(conn, "vss")
            _load_extension(conn, "fts")
            return conn
        except Exception:
            return None

    def _touch_heartbeat(self) -> None:
        try:
            self._heartbeat_path.touch(exist_ok=True)
            os.utime(self._heartbeat_path, None)
        except Exception:
            pass

    def _refresh_once(self) -> None:
        with self._conn_lock:
            conn = self._get_writer_connection()
            self._ensure_metadata_tables(conn)

            collection_dirs = self._scan_collections()
            conn.execute("BEGIN")
            try:
                for key, coll_dir, dim in collection_dirs:
                    try:
                        self._refresh_collection(conn, key, coll_dir, dim)
                    except Exception as table_err:
                        log.warning(f"[RAG Shadow] collection refresh failed ({key}): {table_err}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _scan_collections(self) -> list[tuple[str, Path, int]]:
        out: list[tuple[str, Path, int]] = []
        if not self._rag_path.exists():
            return out
        for entry in self._rag_path.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            name = entry.name
            if "_" not in name:
                continue
            suffix = name.rsplit("_", 1)[1]
            if not suffix.isdigit():
                continue
            out.append((name, entry, int(suffix)))
        return out

    def _source_files(self, coll_dir: Path) -> Dict[str, tuple[int, int]]:
        out: Dict[str, tuple[int, int]] = {}
        for file_path in coll_dir.glob("*.parquet"):
            if not file_path.is_file():
                continue
            try:
                stat = file_path.stat()
                mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
                out[str(file_path.resolve())] = (int(stat.st_size), int(mtime_ns))
            except Exception:
                continue
        return out

    def _refresh_collection(
        self,
        conn: duckdb.DuckDBPyConnection,
        key: str,
        coll_dir: Path,
        embedding_dim: int,
    ) -> None:
        source_files = self._source_files(coll_dir)
        manifest_files = self._load_manifest_for_collection(conn, key)
        if source_files == manifest_files:
            return

        table_name = _collection_table_name(key)
        self._drop_table_or_view(conn, table_name)

        chunk_files = sorted(
            [p for p in source_files.keys() if not Path(p).name.startswith("tombstone_")]
        )
        tombstone_files = sorted(
            [p for p in source_files.keys() if Path(p).name.startswith("tombstone_")]
        )

        if not chunk_files:
            self._create_empty_collection_table(conn, table_name)
        else:
            chunk_globs = ", ".join("'" + p.replace("'", "''") + "'" for p in chunk_files)
            conn.execute(
                f"""
                CREATE OR REPLACE TEMP VIEW _rag_shadow_all_chunks AS
                SELECT * FROM read_parquet([{chunk_globs}], union_by_name=true)
                """
            )

            if tombstone_files:
                tombstone_globs = ", ".join("'" + p.replace("'", "''") + "'" for p in tombstone_files)
                conn.execute(
                    f"""
                    CREATE OR REPLACE TEMP VIEW _rag_shadow_tombstones AS
                    SELECT * FROM read_parquet([{tombstone_globs}], union_by_name=true)
                    """
                )
                conn.execute(
                    """
                    CREATE OR REPLACE TEMP VIEW _rag_shadow_live_chunks AS
                    SELECT c.*
                    FROM _rag_shadow_all_chunks c
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM _rag_shadow_tombstones t
                        WHERE (t.tombstone_type = 'rag_id' AND t.rag_id = c.rag_id)
                           OR (t.tombstone_type = 'doc_id' AND t.rag_id = c.rag_id AND t.doc_id = c.doc_id)
                    )
                    """
                )
            else:
                conn.execute(
                    """
                    CREATE OR REPLACE TEMP VIEW _rag_shadow_live_chunks AS
                    SELECT * FROM _rag_shadow_all_chunks
                    """
                )

            conn.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT * EXCLUDE (_rn)
                FROM (
                    SELECT *,
                        ROW_NUMBER() OVER (PARTITION BY chunk_id ORDER BY upsert_ts DESC) AS _rn
                    FROM _rag_shadow_live_chunks
                )
                WHERE _rn = 1
                """
            )

        self._replace_manifest_for_collection(conn, key, source_files)
        conn.execute(
            """
            INSERT INTO _rag_shadow_collections (collection_key, embedding_dim, refreshed_at)
            VALUES (?, ?, now())
            ON CONFLICT (collection_key) DO UPDATE SET
                embedding_dim = EXCLUDED.embedding_dim,
                refreshed_at = EXCLUDED.refreshed_at
            """,
            [key, int(embedding_dim)],
        )

    def _drop_table_or_view(self, conn: duckdb.DuckDBPyConnection, relation: str) -> None:
        for stmt in (
            f"DROP VIEW IF EXISTS {relation}",
            f"DROP TABLE IF EXISTS {relation}",
        ):
            try:
                conn.execute(stmt)
            except Exception:
                continue

    def _create_empty_collection_table(self, conn: duckdb.DuckDBPyConnection, table_name: str) -> None:
        conn.execute(
            f"""
            CREATE TABLE {table_name} AS
            SELECT
                CAST(NULL AS VARCHAR) AS chunk_id,
                CAST(NULL AS VARCHAR) AS rag_id,
                CAST(NULL AS VARCHAR) AS doc_id,
                CAST(NULL AS INTEGER) AS chunk_index,
                CAST(NULL AS VARCHAR) AS text,
                CAST(NULL AS FLOAT[]) AS embedding,
                CAST(NULL AS VARCHAR) AS rel_path,
                CAST(NULL AS INTEGER) AS start_line,
                CAST(NULL AS INTEGER) AS end_line,
                CAST(NULL AS INTEGER) AS char_start,
                CAST(NULL AS INTEGER) AS char_end,
                CAST(NULL AS VARCHAR) AS file_hash,
                CAST(NULL AS VARCHAR) AS embedding_model,
                CAST(NULL AS INTEGER) AS embedding_dim,
                CAST(NULL AS BIGINT) AS upsert_ts
            WHERE false
            """
        )

    def _collection_manifest_matches_source(
        self,
        conn: duckdb.DuckDBPyConnection,
        collection_key: str,
    ) -> bool:
        """
        Verify shadow manifest for one collection exactly matches source parquet files.

        This prevents serving partial/stale shadow data for a collection if refresh
        is behind or a collection refresh previously failed.
        """
        coll_dir = self._rag_path / collection_key
        source_files = self._source_files(coll_dir)
        shadow_files = self._load_manifest_for_collection(conn, collection_key)
        return source_files == shadow_files

    def _ensure_metadata_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _rag_shadow_manifest (
                collection_key VARCHAR,
                file_path VARCHAR,
                file_size BIGINT,
                file_mtime_ns BIGINT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _rag_shadow_collections (
                collection_key VARCHAR PRIMARY KEY,
                embedding_dim INTEGER,
                refreshed_at TIMESTAMP
            )
            """
        )

    def _load_manifest_for_collection(
        self,
        conn: duckdb.DuckDBPyConnection,
        collection_key: str,
    ) -> Dict[str, tuple[int, int]]:
        rows = conn.execute(
            """
            SELECT file_path, file_size, file_mtime_ns
            FROM _rag_shadow_manifest
            WHERE collection_key = ?
            """,
            [collection_key],
        ).fetchall()
        return {str(path): (int(size), int(mtime_ns)) for path, size, mtime_ns in rows}

    def _replace_manifest_for_collection(
        self,
        conn: duckdb.DuckDBPyConnection,
        collection_key: str,
        source_files: Dict[str, tuple[int, int]],
    ) -> None:
        conn.execute(
            "DELETE FROM _rag_shadow_manifest WHERE collection_key = ?",
            [collection_key],
        )
        if not source_files:
            return
        rows = [
            (collection_key, file_path, int(size), int(mtime_ns))
            for file_path, (size, mtime_ns) in source_files.items()
        ]
        conn.executemany(
            """
            INSERT INTO _rag_shadow_manifest (collection_key, file_path, file_size, file_mtime_ns)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )


_shadow_store: Optional[RagShadowStore] = None


def get_rag_shadow_store() -> RagShadowStore:
    global _shadow_store
    if _shadow_store is None:
        _shadow_store = RagShadowStore()
    return _shadow_store


def start_rag_shadow_store() -> RagShadowStore:
    store = get_rag_shadow_store()
    store.start()
    return store
