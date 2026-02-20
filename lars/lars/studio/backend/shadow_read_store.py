"""
Studio shadow DuckDB read store.

This module maintains a local DuckDB file populated from hot parquet-backed
system tables. A single process acquires a cross-process file lock and refreshes
the shadow DB; all processes can read from it.
"""

from __future__ import annotations

import atexit
import fcntl
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb

from lars.lars_db import SYSTEM_TABLES


log = logging.getLogger(__name__)


# Python-level feature flags / tuning knobs (no env required for defaults)
_SHADOW_ENABLED = True
_REFRESH_INTERVAL_SECONDS = 0.75
_LEADER_RETRY_SECONDS = 1.0
_STALE_AFTER_SECONDS = 5.0
_SHADOW_MAX_STALE_SECONDS = 15.0

_TRACKED_TABLES = (
    "unified_logs_base",
    "costs",
    "session_state",
    "cascade_analytics",
    "cell_analytics",
    "cascade_sessions",
)


def _resolve_data_root() -> Path:
    """Resolve the LARS data root using the same precedence as Studio backend."""
    data_dir = os.environ.get("LARS_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser().resolve()

    lars_root = os.environ.get("LARS_ROOT")
    if lars_root:
        return (Path(lars_root).expanduser().resolve() / "data")

    return (Path.home() / ".lars" / "data").resolve()


class ShadowReadStore:
    """Single-writer shadow DB refresher + multi-reader query access."""

    _instance: Optional["ShadowReadStore"] = None
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
        self._data_root = _resolve_data_root()
        self._system_dir = self._data_root / "system"
        self._db_path = self._system_dir / "studio_shadow.duckdb"
        self._leader_lock_path = self._system_dir / ".studio_shadow.lock"
        self._heartbeat_path = self._system_dir / ".studio_shadow.heartbeat"

        self._stop_event = threading.Event()
        self._refresh_thread: Optional[threading.Thread] = None
        self._leader_fd = None
        self._writer_conn: Optional[duckdb.DuckDBPyConnection] = None
        self._thread_local = threading.local()
        self._start_lock = threading.Lock()

        self._initialized = True
        atexit.register(self.stop)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self):
        """Start the background refresh thread (idempotent)."""
        if not self._enabled:
            return

        with self._start_lock:
            if self._refresh_thread and self._refresh_thread.is_alive():
                return

            self._system_dir.mkdir(parents=True, exist_ok=True)
            self._stop_event.clear()
            self._refresh_thread = threading.Thread(
                target=self._refresh_loop,
                daemon=True,
                name="studio-shadow-refresh",
            )
            self._refresh_thread.start()

    def stop(self):
        """Stop refresh loop and release resources."""
        self._stop_event.set()
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=2.0)
        self._refresh_thread = None
        self._close_writer_connection()
        self._release_leader_lock()
        self._clear_read_connection()

    def is_fresh(self, max_stale_seconds: float = _STALE_AFTER_SECONDS) -> bool:
        """Return True if shadow data was refreshed recently enough."""
        if not self._enabled:
            return False
        if max_stale_seconds <= 0:
            max_stale_seconds = _STALE_AFTER_SECONDS
        max_stale_seconds = min(max_stale_seconds, _SHADOW_MAX_STALE_SECONDS)

        if not self._db_path.exists():
            return False
        if not self._heartbeat_path.exists():
            return False

        try:
            age = time.time() - self._heartbeat_path.stat().st_mtime
            return age <= max_stale_seconds
        except Exception:
            return False

    def query(
        self,
        sql: str,
        params: Optional[list[Any]] = None,
        output_format: str = "dict",
        max_stale_seconds: float = _STALE_AFTER_SECONDS,
    ) -> Any | None:
        """
        Execute a read query against shadow DB.

        Returns None when shadow is unavailable/stale or query fails.
        """
        if not self.is_fresh(max_stale_seconds=max_stale_seconds):
            return None

        for attempt in range(2):
            conn = self._get_read_connection()
            if conn is None:
                return None

            try:
                if params:
                    result = conn.execute(sql, params)
                else:
                    result = conn.execute(sql)

                if output_format == "dataframe":
                    return result.fetchdf()
                if output_format == "raw":
                    return result.fetchall()
                return result.fetchdf().to_dict(orient="records")
            except Exception:
                self._clear_read_connection()
                if attempt == 1:
                    return None

        return None

    # ------------------------------------------------------------------
    # Refresh internals
    # ------------------------------------------------------------------

    def _refresh_loop(self):
        while not self._stop_event.is_set():
            if not self._ensure_leader_lock():
                self._stop_event.wait(_LEADER_RETRY_SECONDS)
                continue

            try:
                self._refresh_once()
                self._touch_heartbeat()
            except Exception as e:
                log.warning(f"[ShadowReadStore] refresh failed: {e}")
                self._close_writer_connection()
                self._release_leader_lock()
                self._stop_event.wait(_LEADER_RETRY_SECONDS)
                continue

            self._stop_event.wait(_REFRESH_INTERVAL_SECONDS)

    def _ensure_leader_lock(self) -> bool:
        """Try to become the single refresh leader process."""
        if self._leader_fd is not None:
            return True

        try:
            lock_fd = open(self._leader_lock_path, "a+")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._leader_fd = lock_fd
            log.info("[ShadowReadStore] refresh leader acquired")
            return True
        except (IOError, OSError):
            try:
                lock_fd.close()
            except Exception:
                pass
            return False

    def _release_leader_lock(self):
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

        self._system_dir.mkdir(parents=True, exist_ok=True)
        self._writer_conn = duckdb.connect(str(self._db_path))
        duckdb_threads = int(os.environ.get("LARS_DUCKDB_THREADS", "2"))
        self._writer_conn.execute(f"SET threads TO {duckdb_threads}")
        return self._writer_conn

    def _close_writer_connection(self):
        if self._writer_conn is not None:
            try:
                self._writer_conn.close()
            except Exception:
                pass
        self._writer_conn = None

    def _get_read_connection(self) -> duckdb.DuckDBPyConnection | None:
        conn = getattr(self._thread_local, "read_conn", None)
        if conn is not None:
            return conn
        if not self._db_path.exists():
            return None

        try:
            conn = duckdb.connect(str(self._db_path), read_only=True)
            duckdb_threads = int(os.environ.get("LARS_DUCKDB_THREADS", "2"))
            conn.execute(f"SET threads TO {duckdb_threads}")
            self._thread_local.read_conn = conn
            return conn
        except Exception:
            return None

    def _clear_read_connection(self):
        conn = getattr(self._thread_local, "read_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        self._thread_local.read_conn = None

    def _touch_heartbeat(self):
        try:
            self._heartbeat_path.touch(exist_ok=True)
            os.utime(self._heartbeat_path, None)
        except Exception:
            pass

    def _refresh_once(self):
        conn = self._get_writer_connection()
        self._ensure_shadow_metadata_tables(conn)

        changed_tables: set[str] = set()
        conn.execute("BEGIN")
        try:
            for table_name in _TRACKED_TABLES:
                if self._refresh_one_table(conn, table_name):
                    changed_tables.add(table_name)

            if changed_tables or self._shadow_view_missing(conn, "unified_logs"):
                self._rebuild_unified_logs_view(conn)

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def _refresh_one_table(self, conn: duckdb.DuckDBPyConnection, table_name: str) -> bool:
        source_files = self._scan_source_files(table_name)
        manifest_files = self._load_manifest_for_table(conn, table_name)

        raw_table = self._raw_table_name(table_name)
        raw_exists = self._shadow_table_exists(conn, raw_table)

        source_paths = set(source_files.keys())
        manifest_paths = set(manifest_files.keys())

        removed_paths = manifest_paths - source_paths
        added_paths = source_paths - manifest_paths
        changed_paths = {
            path
            for path in (source_paths & manifest_paths)
            if source_files[path] != manifest_files[path]
        }

        did_change = False
        needs_rebuild = (
            (not raw_exists)
            or bool(removed_paths)
            or bool(changed_paths)
        )

        if needs_rebuild:
            self._full_rebuild_raw_table(conn, table_name, source_files)
            did_change = True
        elif added_paths:
            added_sorted = sorted(added_paths)
            try:
                self._append_files_to_raw_table(conn, table_name, added_sorted)
            except Exception:
                self._full_rebuild_raw_table(conn, table_name, source_files)
            did_change = True

        if did_change:
            self._replace_manifest_for_table(conn, table_name, source_files)
            self._rebuild_materialized_table(conn, table_name)

        return did_change

    def _scan_source_files(self, table_name: str) -> Dict[str, tuple[int, int]]:
        """Return map[path] -> (size, mtime_ns) for source parquet files."""
        table_dir = self._system_dir / table_name
        if not table_dir.exists():
            return {}

        snapshot: Dict[str, tuple[int, int]] = {}
        for file_path in table_dir.glob("**/*.parquet"):
            if not file_path.is_file():
                continue
            try:
                stat = file_path.stat()
                mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
                snapshot[str(file_path.resolve())] = (int(stat.st_size), int(mtime_ns))
            except Exception:
                continue

        return snapshot

    def _full_rebuild_raw_table(
        self,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
        source_files: Dict[str, tuple[int, int]],
    ):
        raw_table = self._raw_table_name(table_name)
        self._drop_relation(conn, raw_table)

        if not source_files:
            self._create_empty_shadow_table(conn, raw_table, table_name)
            return

        parquet_glob = str((self._system_dir / table_name / "**" / "*.parquet")).replace("'", "''")
        conn.execute(
            f"""
            CREATE TABLE {raw_table} AS
            SELECT *
            FROM read_parquet('{parquet_glob}', union_by_name=true, hive_partitioning=true)
            """
        )

    def _append_files_to_raw_table(
        self,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
        added_paths: list[str],
    ):
        if not added_paths:
            return

        raw_table = self._raw_table_name(table_name)
        escaped_paths = ", ".join("'" + p.replace("'", "''") + "'" for p in added_paths)
        append_sql = (
            f"SELECT * FROM read_parquet([{escaped_paths}], union_by_name=true, hive_partitioning=true)"
        )

        try:
            conn.execute(f"INSERT INTO {raw_table} BY NAME {append_sql}")
        except Exception:
            conn.execute(f"INSERT INTO {raw_table} {append_sql}")

    def _rebuild_materialized_table(self, conn: duckdb.DuckDBPyConnection, table_name: str):
        dedup = SYSTEM_TABLES.get(table_name, {}).get("dedup")
        if not dedup:
            return

        raw_table = self._raw_table_name(table_name)
        final_table = table_name
        self._drop_relation(conn, final_table)

        pk_col = dedup["pk"]
        order_clause = self._dedup_order_clause(dedup.get("order_by", "updated_at"))
        conn.execute(
            f"""
            CREATE TABLE {final_table} AS
            SELECT * EXCLUDE (_rn)
            FROM (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY {pk_col}
                        ORDER BY {order_clause}
                    ) AS _rn
                FROM {raw_table}
            )
            WHERE _rn = 1
            """
        )

    def _rebuild_unified_logs_view(self, conn: duckdb.DuckDBPyConnection):
        self._drop_relation(conn, "unified_logs")

        try:
            conn.execute(
                """
                CREATE VIEW unified_logs AS
                SELECT
                    ul.* EXCLUDE (cost, tokens_in, tokens_out, tokens_reasoning, parent_session_id),
                    COALESCE(c.cost, ul.cost) AS cost,
                    COALESCE(c.tokens_in, ul.tokens_in) AS tokens_in,
                    COALESCE(c.tokens_out, ul.tokens_out) AS tokens_out,
                    COALESCE(c.tokens_reasoning, ul.tokens_reasoning) AS tokens_reasoning,
                    CAST(ul.parent_session_id AS VARCHAR) AS parent_session_id
                FROM unified_logs_base ul
                LEFT JOIN costs c ON ul.trace_id = c.trace_id
                """
            )
        except Exception:
            conn.execute("CREATE VIEW unified_logs AS SELECT * FROM unified_logs_base")

    def _raw_table_name(self, table_name: str) -> str:
        dedup = SYSTEM_TABLES.get(table_name, {}).get("dedup")
        if dedup:
            return f"_shadow_raw_{table_name}"
        return table_name

    def _dedup_order_clause(self, order_col: str) -> str:
        if "," in order_col:
            return order_col

        order_upper = order_col.upper()
        if " DESC" in order_upper or " ASC" in order_upper:
            return order_col

        if order_col == "updated_at":
            return (
                "COALESCE(TRY_CAST(updated_at AS TIMESTAMP), "
                "'1970-01-01'::TIMESTAMP) DESC NULLS LAST"
            )

        return f"{order_col} DESC NULLS LAST"

    def _drop_relation(self, conn: duckdb.DuckDBPyConnection, relation: str):
        conn.execute(f"DROP VIEW IF EXISTS {relation}")
        conn.execute(f"DROP TABLE IF EXISTS {relation}")

    def _shadow_view_missing(self, conn: duckdb.DuckDBPyConnection, view_name: str) -> bool:
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.views
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [view_name],
            ).fetchone()
            return not row or int(row[0]) == 0
        except Exception:
            return True

    def _shadow_table_exists(self, conn: duckdb.DuckDBPyConnection, table_name: str) -> bool:
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [table_name],
            ).fetchone()
            return bool(row and int(row[0]) > 0)
        except Exception:
            return False

    def _ensure_shadow_metadata_tables(self, conn: duckdb.DuckDBPyConnection):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _shadow_manifest (
                table_name VARCHAR,
                file_path VARCHAR,
                file_size BIGINT,
                file_mtime_ns BIGINT
            )
            """
        )

    def _load_manifest_for_table(
        self,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
    ) -> Dict[str, tuple[int, int]]:
        try:
            rows = conn.execute(
                """
                SELECT file_path, file_size, file_mtime_ns
                FROM _shadow_manifest
                WHERE table_name = ?
                """,
                [table_name],
            ).fetchall()
            return {str(path): (int(size), int(mtime_ns)) for path, size, mtime_ns in rows}
        except Exception:
            return {}

    def _replace_manifest_for_table(
        self,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
        source_files: Dict[str, tuple[int, int]],
    ):
        conn.execute("DELETE FROM _shadow_manifest WHERE table_name = ?", [table_name])
        if not source_files:
            return

        rows = [
            (table_name, path, int(size), int(mtime_ns))
            for path, (size, mtime_ns) in source_files.items()
        ]
        conn.executemany(
            """
            INSERT INTO _shadow_manifest (table_name, file_path, file_size, file_mtime_ns)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )

    def _create_empty_shadow_table(
        self,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
        source_table_name: str,
    ):
        schema_cols = SYSTEM_TABLES.get(source_table_name, {}).get("columns", [])
        if not schema_cols:
            conn.execute(f"CREATE TABLE {table_name} AS SELECT 1 AS _dummy WHERE false")
            return

        col_defs = ", ".join(
            f"CAST(NULL AS {dtype}) AS \"{col}\""
            for col, dtype in schema_cols
        )
        conn.execute(f"CREATE TABLE {table_name} AS SELECT {col_defs} WHERE false")


_shadow_store: Optional[ShadowReadStore] = None


def get_shadow_read_store() -> ShadowReadStore:
    global _shadow_store
    if _shadow_store is None:
        _shadow_store = ShadowReadStore()
    return _shadow_store


def start_shadow_read_store() -> ShadowReadStore:
    store = get_shadow_read_store()
    store.start()
    return store
