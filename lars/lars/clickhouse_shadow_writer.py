"""
Optional ClickHouse shadow writer for parity validation during migration.

Primary writes continue to DuckDB/Parquet. When enabled, this module mirrors
selected tables to ClickHouse asynchronously.
"""

from __future__ import annotations

import atexit
import copy
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import get_config
from .lars_db import SYSTEM_TABLES


log = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off", "")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _env_csv(name: str, default: Sequence[str]) -> List[str]:
    value = os.environ.get(name)
    if value is None:
        return list(default)
    tokens = [part.strip() for part in value.split(",")]
    return [token for token in tokens if token]


def _parse_column_list(raw: str) -> List[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def _env_optional_int(name: str) -> Optional[int]:
    value = os.environ.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _qid(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def _duck_type_to_clickhouse(duck_type: str) -> str:
    t = (duck_type or "").strip().upper()
    if t.endswith("[]"):
        base = t[:-2]
        if base in {"FLOAT", "DOUBLE", "REAL"}:
            return "Array(Float64)"
        if base in {"INTEGER", "INT", "BIGINT", "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT"}:
            return "Array(Int64)"
        if base in {"BOOLEAN", "BOOL"}:
            return "Array(UInt8)"
        return "Array(String)"

    if t in {"TIMESTAMP", "DATETIME", "DATE", "TIME"}:
        return "Nullable(DateTime64(3, 'UTC'))"
    if t in {"BOOLEAN", "BOOL"}:
        return "Nullable(UInt8)"
    if t in {"FLOAT", "DOUBLE", "REAL"}:
        return "Nullable(Float64)"
    if t in {"INTEGER", "INT", "BIGINT", "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT"}:
        return "Nullable(Int64)"
    return "Nullable(String)"


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = f"{s[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except Exception:
            return None

    return None


def _to_json_string(value: Any) -> str:
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:
        return str(value)


def _coerce_scalar(value: Any, duck_type: str) -> Any:
    t = (duck_type or "").strip().upper()
    if value is None:
        return None

    if t in {"TIMESTAMP", "DATETIME", "DATE", "TIME"}:
        return _parse_timestamp(value)

    if t in {"BOOLEAN", "BOOL"}:
        if isinstance(value, str):
            s = value.strip().lower()
            if s in {"1", "true", "yes", "on"}:
                return 1
            if s in {"0", "false", "no", "off"}:
                return 0
        return 1 if bool(value) else 0

    if t in {"INTEGER", "INT", "BIGINT", "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT"}:
        try:
            return int(value)
        except Exception:
            return None

    if t in {"FLOAT", "DOUBLE", "REAL"}:
        try:
            return float(value)
        except Exception:
            return None

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat()

    if isinstance(value, (dict, list, tuple)):
        return _to_json_string(value)

    return str(value)


def _coerce_value(value: Any, duck_type: str) -> Any:
    t = (duck_type or "").strip().upper()
    if t.endswith("[]"):
        base = t[:-2]
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            return []
        out: List[Any] = []
        for item in value:
            coerced = _coerce_scalar(item, base)
            if coerced is None:
                continue
            out.append(coerced)
        return out
    return _coerce_scalar(value, t)


class ClickHouseShadowWriter:
    """
    Async shadow writer for selected tables.

    Controlled by environment:
    - LARS_CH_SHADOW_WRITE_ENABLED=1
    - LARS_CH_SHADOW_WRITE_TABLES=unified_logs_base,costs
      (set to * or all to mirror every table write)
    - LARS_CH_SHADOW_USE_UPSERT_FOR_DEDUP=1
      (for tables with SYSTEM_TABLES[table]["dedup"]["pk"], perform
       DELETE+INSERT by key instead of append-only inserts)
    - LARS_CH_SHADOW_UPSERT_TABLES=session_state,cascade_sessions
      (optional override; defaults to all dedup-configured tables when
       LARS_CH_SHADOW_USE_UPSERT_FOR_DEDUP=1, supports * or all)
    - LARS_CH_SHADOW_UPSERT_MUTATIONS_SYNC=1
      (wait level for DELETE mutation before INSERT)
    - LARS_CH_SHADOW_UPSERT_DELETE_KEY_BATCH=500
      (number of keys per DELETE statement)
    - LARS_CH_SHADOW_WRITE_NATIVE_PORT=19100
    - LARS_CH_SHADOW_WRITE_BATCH_SIZE=500
    - LARS_CH_SHADOW_WRITE_FLUSH_SECONDS=0.5
    - LARS_CH_SHADOW_WRITE_QUEUE_MAX=50000
    """

    DEFAULT_TABLES = ("unified_logs_base", "costs")
    ALL_TABLE_TOKENS = {"*", "all"}

    def __init__(self):
        self.enabled = _env_bool("LARS_CH_SHADOW_WRITE_ENABLED", False)
        raw_tables = _env_csv("LARS_CH_SHADOW_WRITE_TABLES", self.DEFAULT_TABLES)
        lowered = [token.strip().lower() for token in raw_tables]
        self._write_all_tables = any(token in self.ALL_TABLE_TOKENS for token in lowered)
        self._tables = {
            token
            for token in raw_tables
            if token.strip().lower() not in self.ALL_TABLE_TOKENS
        }
        self._upsert_key_columns_by_table = self._build_upsert_key_map()
        self._upsert_dedup_enabled = _env_bool("LARS_CH_SHADOW_USE_UPSERT_FOR_DEDUP", True)
        default_upsert_tables: Sequence[str] = (
            tuple(sorted(self._upsert_key_columns_by_table.keys()))
            if self._upsert_dedup_enabled
            else tuple()
        )
        raw_upsert_tables = _env_csv("LARS_CH_SHADOW_UPSERT_TABLES", default_upsert_tables)
        upsert_lowered = [token.strip().lower() for token in raw_upsert_tables]
        self._upsert_all_tables = any(token in self.ALL_TABLE_TOKENS for token in upsert_lowered)
        self._upsert_tables = {
            token
            for token in raw_upsert_tables
            if token.strip().lower() not in self.ALL_TABLE_TOKENS
        }
        self._upsert_mutations_sync = max(
            0, _env_int("LARS_CH_SHADOW_UPSERT_MUTATIONS_SYNC", 1)
        )
        self._upsert_delete_key_batch = max(
            1, _env_int("LARS_CH_SHADOW_UPSERT_DELETE_KEY_BATCH", 500)
        )
        self._batch_size = max(1, _env_int("LARS_CH_SHADOW_WRITE_BATCH_SIZE", 500))
        self._flush_interval_s = max(0.05, _env_float("LARS_CH_SHADOW_WRITE_FLUSH_SECONDS", 0.5))
        self._queue: queue.Queue[Tuple[str, List[Dict[str, Any]]]] = queue.Queue(
            maxsize=max(1000, _env_int("LARS_CH_SHADOW_WRITE_QUEUE_MAX", 50000))
        )

        self._cfg = get_config()
        self._db_name = self._cfg.clickhouse_database or "lars"
        self._connect_host = self._cfg.clickhouse_host or "127.0.0.1"
        self._connect_port = (
            _env_optional_int("LARS_CH_SHADOW_WRITE_NATIVE_PORT")
            or _env_optional_int("LARS_CLICKHOUSE_NATIVE_PORT")
            or self._cfg.clickhouse_port
            or 9000
        )
        self._connect_user = self._cfg.clickhouse_user or "default"
        self._connect_password = self._cfg.clickhouse_password or ""
        self._client = None
        self._client_lock = threading.Lock()
        self._tables_initialized: set[str] = set()
        self._views_initialized: set[str] = set()
        self._ensuring_support_objects = False
        self._seen_tables: set[str] = set()
        self._shutdown = False
        self._client_retry_after_ts = 0.0
        self._last_drop_log_ts = 0.0

        self._stats_lock = threading.Lock()
        self._rows_enqueued = 0
        self._rows_dropped = 0
        self._rows_written = 0
        self._rows_failed = 0
        self._flush_count = 0
        self._error_count = 0
        self._last_error: Optional[str] = None
        self._last_flush_ts = 0.0

        self._thread: Optional[threading.Thread] = None
        if self.enabled:
            self._thread = threading.Thread(
                target=self._flush_loop,
                name="lars-ch-shadow-writer",
                daemon=True,
            )
            self._thread.start()
            atexit.register(self.shutdown)

    @property
    def tables(self) -> set[str]:
        if self._write_all_tables:
            return set(SYSTEM_TABLES.keys()) | set(self._tables) | set(self._seen_tables)
        return set(self._tables) | set(self._seen_tables)

    def allows_table(self, table: str) -> bool:
        """Return True if the table should be mirrored to ClickHouse."""
        if self._write_all_tables:
            return True
        return table in self._tables

    def enqueue(self, table: str, rows: List[Dict[str, Any]]) -> None:
        if not self.enabled:
            return
        if not self.allows_table(table) or not rows:
            return

        payload = [copy.copy(row) for row in rows if isinstance(row, dict)]
        if not payload:
            return

        try:
            self._seen_tables.add(table)
            self._queue.put_nowait((table, payload))
            with self._stats_lock:
                self._rows_enqueued += len(payload)
        except queue.Full:
            with self._stats_lock:
                self._rows_dropped += len(payload)
            # Drop parity writes first; primary Duck path stays hot.
            now = time.time()
            if now - self._last_drop_log_ts >= 5.0:
                self._last_drop_log_ts = now
                log.warning("[CH Shadow] Queue full; dropping rows (table=%s)", table)
        except Exception as e:
            with self._stats_lock:
                self._rows_dropped += len(payload)
                self._error_count += 1
                self._last_error = str(e)
            log.warning("[CH Shadow] enqueue failed for %s: %s", table, e)

    def flush_now(self) -> None:
        if not self.enabled:
            return
        pending: Dict[str, List[Dict[str, Any]]] = {}
        self._drain_queue(pending, block=False)
        self._flush_pending(pending)

    def get_table_count(self, table: str) -> Optional[int]:
        if not self.enabled or not self.allows_table(table):
            return None

        client = self._get_client()
        if client is None:
            return None

        try:
            self._ensure_table(table)
            sql = f"SELECT count() FROM {_qid(self._db_name)}.{_qid(table)}"
            with self._client_lock:
                result = client.execute(sql)
            if not result:
                return 0
            return int(result[0][0])
        except Exception as e:
            self._record_error(e)
            log.warning("[CH Shadow] count query failed for %s: %s", table, e)
            return None

    def stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return {
                "enabled": self.enabled,
                "tables": sorted(self.tables),
                "write_all_tables": self._write_all_tables,
                "upsert_enabled_for_dedup": self._upsert_dedup_enabled,
                "upsert_all_tables": self._upsert_all_tables,
                "upsert_tables": sorted(self._upsert_tables),
                "queue_size": self._queue.qsize() if self.enabled else 0,
                "rows_enqueued": self._rows_enqueued,
                "rows_dropped": self._rows_dropped,
                "rows_written": self._rows_written,
                "rows_failed": self._rows_failed,
                "flush_count": self._flush_count,
                "error_count": self._error_count,
                "last_error": self._last_error,
                "last_flush_ts": self._last_flush_ts,
            }

    def truncate_table(self, table: str) -> bool:
        """Delete all rows from a shadow table (table is created if missing)."""
        if not self.enabled or not self.allows_table(table):
            return False
        client = self._get_client()
        if client is None:
            return False
        try:
            self._ensure_table(table)
            sql = f"TRUNCATE TABLE IF EXISTS {_qid(self._db_name)}.{_qid(table)}"
            with self._client_lock:
                client.execute(sql)
            return True
        except Exception as e:
            self._record_error(e)
            log.warning("[CH Shadow] truncate failed for %s: %s", table, e)
            return False

    def delete_by_keys(
        self,
        table: str,
        key_columns: Sequence[str],
        key_rows: Sequence[Dict[str, Any]],
    ) -> int:
        """
        Best-effort key-based delete for mirrored mutation paths.

        Returns number of unique key tuples targeted for deletion.
        """
        if not self.enabled or not self.allows_table(table):
            return 0

        normalized_cols = [str(col).strip() for col in key_columns if str(col).strip()]
        if not normalized_cols or not key_rows:
            return 0

        client = self._get_client()
        if client is None:
            return 0

        try:
            # Drain pending inserts first so delete ordering is deterministic.
            self.flush_now()
            sample_rows = [row for row in key_rows if isinstance(row, dict)]
            self._ensure_table(table, sample_rows=sample_rows)

            schema = self._table_schema(table, sample_rows)
            schema_cols = {name for name, _dtype in schema}
            key_cols = [col for col in normalized_cols if col in schema_cols]
            if not key_cols:
                return 0

            col_types = {name: dtype for name, dtype in schema}
            key_tuples: List[Tuple[Any, ...]] = []
            seen: set[Tuple[Any, ...]] = set()

            for row in key_rows:
                if not isinstance(row, dict):
                    continue
                values: List[Any] = []
                missing_key = False
                for key_col in key_cols:
                    key_value = row.get(key_col)
                    if key_value is None:
                        missing_key = True
                        break
                    values.append(_coerce_value(key_value, col_types.get(key_col, "VARCHAR")))
                if missing_key:
                    continue
                key_tuple = tuple(values)
                if key_tuple in seen:
                    continue
                seen.add(key_tuple)
                key_tuples.append(key_tuple)

            if not key_tuples:
                return 0

            self._delete_existing_keys(table, key_cols, key_tuples, client)
            return len(key_tuples)
        except Exception as e:
            self._record_error(e)
            log.warning("[CH Shadow] key delete failed for %s: %s", table, e)
            return 0

    def backfill_parquet_glob(
        self,
        table: str,
        parquet_glob: str,
        *,
        batch_rows: int = 2000,
        clear_target: bool = False,
    ) -> Dict[str, Any]:
        """
        Backfill a shadow table from parquet files.

        This is intended for one-time historical parity validation.
        """
        report: Dict[str, Any] = {
            "table": table,
            "status": "skipped",
            "rows_read": 0,
            "rows_written": 0,
            "batch_rows": batch_rows,
            "clear_target": clear_target,
            "parquet_glob": parquet_glob,
            "error": None,
        }
        if not self.enabled:
            report["error"] = "shadow writer disabled"
            return report
        if not self.allows_table(table):
            report["error"] = "table not configured for shadow writing"
            return report

        client = self._get_client()
        if client is None:
            report["error"] = "clickhouse client unavailable"
            return report

        try:
            self.flush_now()
            self._ensure_table(table)
            if clear_target:
                self.truncate_table(table)

            import duckdb

            batch_size = max(100, int(batch_rows))
            conn = duckdb.connect()
            try:
                reader = conn.execute(
                    f"SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true, hive_partitioning=true)"
                ).fetch_record_batch(rows_per_batch=batch_size)

                for batch in reader:
                    rows = batch.to_pylist()
                    if not rows:
                        continue
                    report["rows_read"] += len(rows)
                    self._insert_rows(table, rows)
                    report["rows_written"] += len(rows)
            finally:
                conn.close()

            report["status"] = "ok"
            return report
        except Exception as e:
            self._record_error(e)
            report["status"] = "failed"
            report["error"] = str(e)
            return report

    def shutdown(self) -> None:
        self._shutdown = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _flush_loop(self) -> None:
        pending: Dict[str, List[Dict[str, Any]]] = {}
        last_flush = time.time()

        while not self._shutdown:
            self._drain_queue(pending, block=True, timeout=0.1)
            now = time.time()
            pending_count = sum(len(v) for v in pending.values())
            should_flush = pending_count >= self._batch_size or (
                pending_count > 0 and (now - last_flush) >= self._flush_interval_s
            )
            if should_flush:
                self._flush_pending(pending)
                pending = {}
                last_flush = now

        self._drain_queue(pending, block=False)
        self._flush_pending(pending)

    def _drain_queue(
        self,
        pending: Dict[str, List[Dict[str, Any]]],
        *,
        block: bool,
        timeout: float = 0.0,
    ) -> None:
        try:
            if block:
                table, rows = self._queue.get(timeout=timeout)
                pending.setdefault(table, []).extend(rows)
            while True:
                table, rows = self._queue.get_nowait()
                pending.setdefault(table, []).extend(rows)
        except queue.Empty:
            return

    def _flush_pending(self, pending: Dict[str, List[Dict[str, Any]]]) -> None:
        if not pending:
            return

        for table, rows in pending.items():
            if not rows:
                continue
            self._insert_rows(table, rows)

        with self._stats_lock:
            self._flush_count += 1
            self._last_flush_ts = time.time()

    def _get_client(self):
        now = time.time()
        if now < self._client_retry_after_ts:
            return None

        if self._client is not None:
            return self._client

        try:
            import clickhouse_driver
        except Exception as e:
            self._record_error(e)
            self._client_retry_after_ts = time.time() + 5.0
            log.warning("[CH Shadow] clickhouse_driver import failed: %s", e)
            return None

        try:
            client = clickhouse_driver.Client(
                host=self._connect_host,
                port=self._connect_port,
                user=self._connect_user,
                password=self._connect_password,
                database="default",
                connect_timeout=1.0,
                send_receive_timeout=2.0,
            )
            with self._client_lock:
                client.execute("SELECT 1")
                client.execute(f"CREATE DATABASE IF NOT EXISTS {_qid(self._db_name)}")
            self._client = client
            return self._client
        except Exception as e:
            self._record_error(e)
            self._client_retry_after_ts = time.time() + 5.0
            log.warning("[CH Shadow] connect failed %s:%s: %s", self._connect_host, self._connect_port, e)
            self._client = None
            return None

    def _table_schema(self, table: str, sample_rows: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
        schema = SYSTEM_TABLES.get(table, {}).get("columns", [])
        if schema:
            return list(schema)

        # Fallback for non-system tables if configured later.
        discovered: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for row in sample_rows:
            for key in row.keys():
                if key in seen:
                    continue
                seen.add(key)
                discovered.append((key, "VARCHAR"))
        return discovered

    def _build_upsert_key_map(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for table_name, schema in SYSTEM_TABLES.items():
            dedup = schema.get("dedup", {})
            if not isinstance(dedup, dict):
                continue
            pk_raw = dedup.get("pk")
            if not pk_raw:
                continue
            key_cols = _parse_column_list(pk_raw)
            if key_cols:
                out[table_name] = key_cols
        return out

    def _upsert_key_columns(self, table: str) -> List[str]:
        return list(self._upsert_key_columns_by_table.get(table, []))

    def _uses_upsert(self, table: str) -> bool:
        if not self._upsert_dedup_enabled:
            return False
        if table not in self._upsert_key_columns_by_table:
            return False
        if self._upsert_all_tables:
            return True
        return table in self._upsert_tables

    def _build_unified_logs_view_query(self) -> Optional[str]:
        """
        Build ClickHouse SELECT for unified_logs view:
        unified_logs_base LEFT JOIN costs with cost/token coalesce semantics.
        """
        ul_schema = SYSTEM_TABLES.get("unified_logs_base", {}).get("columns", [])
        if not ul_schema:
            return None

        replace_cols = {"cost", "tokens_in", "tokens_out", "tokens_reasoning"}
        projection = [
            f"ul.{_qid(col_name)}"
            for col_name, _dtype in ul_schema
            if col_name not in replace_cols
        ]
        projection.extend(
            [
                f"coalesce(c.{_qid('cost')}, ul.{_qid('cost')}) AS {_qid('cost')}",
                f"coalesce(c.{_qid('tokens_in')}, ul.{_qid('tokens_in')}) AS {_qid('tokens_in')}",
                f"coalesce(c.{_qid('tokens_out')}, ul.{_qid('tokens_out')}) AS {_qid('tokens_out')}",
                f"coalesce(c.{_qid('tokens_reasoning')}, ul.{_qid('tokens_reasoning')}) AS {_qid('tokens_reasoning')}",
            ]
        )

        select_sql = ", ".join(projection)
        return (
            f"SELECT {select_sql} "
            f"FROM {_qid(self._db_name)}.{_qid('unified_logs_base')} AS ul "
            f"LEFT JOIN {_qid(self._db_name)}.{_qid('costs')} AS c "
            f"ON ul.{_qid('trace_id')} = c.{_qid('trace_id')}"
        )

    def _ensure_unified_logs_view(self, client) -> None:
        """Ensure ClickHouse unified_logs view exists with costs join semantics."""
        view_name = "unified_logs"
        if view_name in self._views_initialized:
            return
        if not {"unified_logs_base", "costs"}.issubset(self._tables_initialized):
            return

        query_sql = self._build_unified_logs_view_query()
        if not query_sql:
            return

        self._create_or_replace_view(client, view_name, query_sql)

    def _create_or_replace_view(self, client, view_name: str, query_sql: str) -> bool:
        """Best-effort CREATE OR REPLACE VIEW with fallback for older CH builds."""
        view_ref = f"{_qid(self._db_name)}.{_qid(view_name)}"
        try:
            with self._client_lock:
                client.execute(f"CREATE OR REPLACE VIEW {view_ref} AS {query_sql}")
            self._views_initialized.add(view_name)
            return True
        except Exception:
            # Older ClickHouse builds may not support CREATE OR REPLACE VIEW.
            pass

        try:
            with self._client_lock:
                client.execute(f"DROP VIEW IF EXISTS {view_ref}")
                client.execute(f"CREATE VIEW {view_ref} AS {query_sql}")
            self._views_initialized.add(view_name)
            return True
        except Exception as e:
            self._record_error(e)
            log.warning("[CH Shadow] failed creating %s view: %s", view_name, e)
            return False

    def _reconcile_table_columns(
        self,
        client,
        table: str,
        schema: List[Tuple[str, str]],
    ) -> None:
        """Add any missing columns so existing CH tables track current Duck schema."""
        table_ref = f"{_qid(self._db_name)}.{_qid(table)}"
        existing_cols: set[str] = set()
        try:
            with self._client_lock:
                desc_rows = client.execute(f"DESCRIBE TABLE {table_ref}")
            existing_cols = {str(row[0]) for row in (desc_rows or []) if row}
        except Exception as e:
            self._record_error(e)
            log.warning("[CH Shadow] could not inspect table schema for %s: %s", table, e)
            return

        for col_name, duck_type in schema:
            if col_name in existing_cols:
                continue
            add_sql = (
                f"ALTER TABLE {table_ref} "
                f"ADD COLUMN IF NOT EXISTS {_qid(col_name)} {_duck_type_to_clickhouse(duck_type)}"
            )
            try:
                with self._client_lock:
                    client.execute(add_sql)
            except Exception as e:
                self._record_error(e)
                log.warning(
                    "[CH Shadow] failed adding missing column %s.%s: %s",
                    table,
                    col_name,
                    e,
                )

    def _build_training_examples_mv_query(self) -> str:
        return (
            f"SELECT "
            f"trace_id, "
            f"session_id, "
            f"timestamp, "
            f"cascade_id, "
            f"cell_name, "
            f"if((full_request_json IS NOT NULL) AND (full_request_json != ''), substring(full_request_json, 1, 2000), '') AS user_input, "
            f"coalesce(content_json, '') AS assistant_output, "
            f"model, cost, tokens_in, tokens_out, duration_ms, caller_id, node_type, role "
            f"FROM {_qid(self._db_name)}.{_qid('unified_logs')} "
            f"WHERE role = 'assistant' "
            f"AND cascade_id IS NOT NULL AND cascade_id != '' "
            f"AND content_json IS NOT NULL AND content_json != '' "
            f"AND cascade_id != 'analyze_context_relevance'"
        )

    def _build_training_examples_with_annotations_query(self) -> str:
        return (
            "WITH latest_ts AS ("
            "  SELECT trace_id, max(annotated_at) AS annotated_at "
            f"  FROM {_qid(self._db_name)}.{_qid('training_annotations')} "
            "  GROUP BY trace_id"
            "), latest_annotations AS ("
            "  SELECT "
            "    ta.trace_id, "
            "    ta.trainable, "
            "    ta.verified, "
            "    ta.confidence, "
            "    ta.rating, "
            "    ta.notes, "
            "    ta.tags, "
            "    ta.annotated_at, "
            "    ta.annotated_by "
            f"  FROM {_qid(self._db_name)}.{_qid('training_annotations')} AS ta "
            "  INNER JOIN latest_ts AS lt "
            "    ON ta.trace_id = lt.trace_id "
            "   AND ta.annotated_at = lt.annotated_at"
            ") "
            "SELECT "
            "  mv.*, "
            "  coalesce(la.trainable, false) AS trainable, "
            "  coalesce(la.verified, false) AS verified, "
            "  la.confidence AS confidence, "
            "  la.rating AS rating, "
            "  coalesce(la.notes, '') AS notes, "
            "  la.tags AS tags, "
            "  la.annotated_at AS annotated_at, "
            "  coalesce(la.annotated_by, '') AS annotated_by "
            f"FROM {_qid(self._db_name)}.{_qid('training_examples_mv')} AS mv "
            "LEFT JOIN latest_annotations AS la ON mv.trace_id = la.trace_id"
        )

    def _build_training_stats_by_cascade_query(self) -> str:
        return (
            "SELECT "
            "  cascade_id, "
            "  cell_name, "
            "  countIf(trainable = true) AS trainable_count, "
            "  countIf(verified = true) AS verified_count, "
            "  avg(confidence) AS avg_confidence, "
            "  count() AS total_executions "
            f"FROM {_qid(self._db_name)}.{_qid('training_examples_with_annotations')} "
            "GROUP BY cascade_id, cell_name "
            "ORDER BY trainable_count DESC"
        )

    def _build_render_entries_query(self) -> str:
        return (
            "SELECT "
            "  session_id, trace_id, parent_id, timestamp_iso, cascade_id, cell_name, "
            "  content_type, content_json, metadata_json, candidate_index, role, node_type, "
            "  JSONExtractString(metadata_json, 'screenshot_path') AS screenshot_path, "
            "  JSONExtractString(metadata_json, 'screenshot_url') AS screenshot_url, "
            "  JSONExtractString(metadata_json, 'checkpoint_id') AS checkpoint_id "
            f"FROM {_qid(self._db_name)}.{_qid('unified_logs')} "
            "WHERE content_type LIKE 'render:%' "
            "ORDER BY timestamp_iso DESC"
        )

    def _build_request_decision_renders_query(self) -> str:
        return (
            "SELECT "
            "  session_id, trace_id, timestamp_iso, cascade_id, cell_name, "
            "  content_json AS ui_spec, "
            "  JSONExtractString(metadata_json, 'screenshot_path') AS screenshot_path, "
            "  JSONExtractString(metadata_json, 'screenshot_url') AS screenshot_url, "
            "  JSONExtractString(metadata_json, 'checkpoint_id') AS checkpoint_id, "
            "  JSONExtractString(metadata_json, 'question') AS question, "
            "  JSONExtractString(metadata_json, 'severity') AS severity, "
            "  JSONExtractBool(metadata_json, 'has_html') AS has_html, "
            "  JSONExtractInt(metadata_json, 'options_count') AS options_count, "
            "  candidate_index "
            f"FROM {_qid(self._db_name)}.{_qid('unified_logs')} "
            "WHERE content_type = 'render:request_decision' "
            "ORDER BY timestamp_iso DESC"
        )

    def _ensure_support_objects(self, client) -> None:
        """Create derived views/tables needed by CH read paths even when mostly empty."""
        if self._ensuring_support_objects:
            return
        self._ensuring_support_objects = True
        try:
            # Unified logs derived view.
            self._ensure_unified_logs_view(client)

            # Training views depend on training_annotations + unified_logs.
            if "training_annotations" not in self._tables_initialized:
                self._ensure_table_with_client(client, "training_annotations", sample_rows=[], ensure_support=False)
            if "unified_logs" in self._views_initialized and "training_annotations" in self._tables_initialized:
                if "training_examples_mv" not in self._views_initialized:
                    self._create_or_replace_view(
                        client,
                        "training_examples_mv",
                        self._build_training_examples_mv_query(),
                    )
                if "training_examples_with_annotations" not in self._views_initialized:
                    self._create_or_replace_view(
                        client,
                        "training_examples_with_annotations",
                        self._build_training_examples_with_annotations_query(),
                    )
                if "training_stats_by_cascade" not in self._views_initialized:
                    self._create_or_replace_view(
                        client,
                        "training_stats_by_cascade",
                        self._build_training_stats_by_cascade_query(),
                    )

                # UI render inspection views.
                if "render_entries" not in self._views_initialized:
                    self._create_or_replace_view(
                        client,
                        "render_entries",
                        self._build_render_entries_query(),
                    )
                if "request_decision_renders" not in self._views_initialized:
                    self._create_or_replace_view(
                        client,
                        "request_decision_renders",
                        self._build_request_decision_renders_query(),
                    )
        finally:
            self._ensuring_support_objects = False

    def _ensure_table_with_client(
        self,
        client,
        table: str,
        sample_rows: Optional[List[Dict[str, Any]]] = None,
        *,
        ensure_support: bool = True,
    ) -> None:
        schema = self._table_schema(table, sample_rows or [])
        if not schema:
            return

        if table not in self._tables_initialized:
            columns_sql = ", ".join(
                f"{_qid(name)} {_duck_type_to_clickhouse(duck_type)}"
                for name, duck_type in schema
            )
            order_by = "tuple()"
            use_nullable_key_setting = False
            if self._uses_upsert(table):
                key_cols = [col for col in self._upsert_key_columns(table) if col in {c[0] for c in schema}]
                if key_cols:
                    order_by = f"({', '.join(_qid(col) for col in key_cols)})"
                    # Keep schema permissive (Nullable columns) while allowing
                    # MergeTree sorting keys on those columns.
                    use_nullable_key_setting = True
            settings_sql = ""
            if use_nullable_key_setting:
                settings_sql = " SETTINGS allow_nullable_key = 1"
            ddl = (
                f"CREATE TABLE IF NOT EXISTS {_qid(self._db_name)}.{_qid(table)} ("
                f"{columns_sql}"
                f") ENGINE = MergeTree ORDER BY {order_by}"
                f"{settings_sql}"
            )
            with self._client_lock:
                client.execute(ddl)

            self._tables_initialized.add(table)

        # Keep existing tables in sync with current SYSTEM_TABLES columns.
        self._reconcile_table_columns(client, table, schema)

        if ensure_support:
            self._ensure_support_objects(client)

    def _ensure_table(self, table: str, sample_rows: Optional[List[Dict[str, Any]]] = None) -> None:
        client = self._get_client()
        if client is None:
            return
        self._ensure_table_with_client(client, table, sample_rows=sample_rows, ensure_support=True)

    def _insert_rows(self, table: str, rows: List[Dict[str, Any]]) -> None:
        client = self._get_client()
        if client is None:
            with self._stats_lock:
                self._rows_failed += len(rows)
            return

        try:
            self._ensure_table(table, sample_rows=rows)
            schema = self._table_schema(table, rows)
            if not schema:
                with self._stats_lock:
                    self._rows_failed += len(rows)
                return

            if self._uses_upsert(table):
                self._upsert_rows(table, rows, schema, client)
            else:
                self._insert_rows_append(table, rows, schema, client)
        except Exception as e:
            self._record_error(e)
            with self._stats_lock:
                self._rows_failed += len(rows)
            log.warning("[CH Shadow] insert failed for %s (%d rows): %s", table, len(rows), e)

    def _insert_rows_append(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        schema: List[Tuple[str, str]],
        client,
    ) -> None:
        if not rows:
            return
        col_names = [name for name, _ in schema]
        col_types = {name: dtype for name, dtype in schema}
        data: List[Tuple[Any, ...]] = []
        for row in rows:
            data.append(
                tuple(
                    _coerce_value(row.get(col_name), col_types[col_name])
                    for col_name in col_names
                )
            )

        cols_sql = ", ".join(_qid(c) for c in col_names)
        insert_sql = (
            f"INSERT INTO {_qid(self._db_name)}.{_qid(table)} "
            f"({cols_sql}) VALUES"
        )
        with self._client_lock:
            client.execute(insert_sql, data, types_check=False)
        with self._stats_lock:
            self._rows_written += len(rows)

    def _upsert_rows(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        schema: List[Tuple[str, str]],
        client,
    ) -> None:
        key_cols = self._upsert_key_columns(table)
        if not key_cols:
            self._insert_rows_append(table, rows, schema, client)
            return

        col_types = {name: dtype for name, dtype in schema}
        keyed_latest: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        passthrough_rows: List[Dict[str, Any]] = []

        for row in rows:
            key_values: List[Any] = []
            missing_key = False
            for key_col in key_cols:
                key_value = row.get(key_col)
                if key_value is None:
                    missing_key = True
                    break
                key_values.append(_coerce_value(key_value, col_types.get(key_col, "VARCHAR")))
            if missing_key:
                passthrough_rows.append(row)
                continue
            keyed_latest[tuple(key_values)] = row

        # Keep last-write-wins semantics for duplicate keys in the same batch.
        upsert_rows = list(keyed_latest.values())
        key_tuples = list(keyed_latest.keys())

        try:
            if key_tuples:
                self._delete_existing_keys(table, key_cols, key_tuples, client)
            if upsert_rows:
                self._insert_rows_append(table, upsert_rows, schema, client)
            if passthrough_rows:
                self._insert_rows_append(table, passthrough_rows, schema, client)
        except Exception as e:
            log.warning(
                "[CH Shadow] upsert failed for %s (%d rows), falling back to append: %s",
                table,
                len(rows),
                e,
            )
            self._insert_rows_append(table, rows, schema, client)

    def _delete_existing_keys(
        self,
        table: str,
        key_cols: List[str],
        key_tuples: List[Tuple[Any, ...]],
        client,
    ) -> None:
        if not key_tuples:
            return

        for start in range(0, len(key_tuples), self._upsert_delete_key_batch):
            batch = key_tuples[start : start + self._upsert_delete_key_batch]
            where_clause = self._build_delete_where_clause(key_cols, batch)
            delete_sql = (
                f"ALTER TABLE {_qid(self._db_name)}.{_qid(table)} "
                f"DELETE WHERE {where_clause} "
                f"SETTINGS mutations_sync = {int(self._upsert_mutations_sync)}"
            )
            with self._client_lock:
                client.execute(delete_sql)

    def _build_delete_where_clause(
        self,
        key_cols: List[str],
        key_tuples: List[Tuple[Any, ...]],
    ) -> str:
        if len(key_cols) == 1:
            literals = ", ".join(self._sql_literal(key_tuple[0]) for key_tuple in key_tuples)
            return f"{_qid(key_cols[0])} IN ({literals})"

        cols_sql = ", ".join(_qid(col) for col in key_cols)
        tuples_sql = ", ".join(
            "(" + ", ".join(self._sql_literal(v) for v in key_tuple) + ")"
            for key_tuple in key_tuples
        )
        return f"({cols_sql}) IN ({tuples_sql})"

    def _sql_literal(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            return f"toDateTime64('{value.strftime('%Y-%m-%d %H:%M:%S.%f')}', 3, 'UTC')"

        text = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{text}'"

    def _record_error(self, error: Exception) -> None:
        with self._stats_lock:
            self._error_count += 1
            self._last_error = str(error)
