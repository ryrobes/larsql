from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional


class RuntimeEventLogger:
    """
    Async, fire-and-forget runtime event logger to ClickHouse.

    This is intended for high-volume operational logs (e.g., pgwire chatter) that
    would otherwise spam stdout. It writes to the `runtime_event_log` table.

    Enabled by default; set `LARS_RUNTIME_EVENT_LOG_ENABLED=0` to disable.
    """

    _instance: Optional["RuntimeEventLogger"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._config_enabled = os.environ.get("LARS_RUNTIME_EVENT_LOG_ENABLED", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

        self._batch_size = _env_int("LARS_RUNTIME_EVENT_LOG_BATCH_SIZE", 200)
        self._flush_interval_s = _env_float("LARS_RUNTIME_EVENT_LOG_FLUSH_INTERVAL_S", 1.0)
        self._max_queue_size = _env_int("LARS_RUNTIME_EVENT_LOG_MAX_QUEUE", 10_000)
        self._max_message_chars = _env_int("LARS_RUNTIME_EVENT_LOG_MAX_MESSAGE_CHARS", 10_000)
        self._connect_backoff_base_s = _env_float("LARS_RUNTIME_EVENT_LOG_CONNECT_BACKOFF_S", 1.0)
        self._connect_backoff_max_s = _env_float("LARS_RUNTIME_EVENT_LOG_CONNECT_BACKOFF_MAX_S", 30.0)

        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=self._max_queue_size)
        self._dropped = 0

        self._client = None
        self._client_lock = threading.Lock()
        self._connect_failures = 0
        self._next_connect_time = 0.0
        self._last_error: str | None = None
        self._last_error_at: float | None = None
        self._shutdown = False

        self._flush_thread = None
        if self._config_enabled:
            self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._flush_thread.start()

        atexit.register(self.shutdown)
        self._initialized = True

    def log_event(
        self,
        *,
        source: str,
        level: str,
        message: str,
        event: str = "",
        connection_id: str | None = None,
        session_id: str | None = None,
        query_id: str | None = None,
        caller_id: str | None = None,
        user_name: str | None = None,
        auth_user_id: str | None = None,
        database_name: str | None = None,
        results_db: str | None = None,
        application_name: str | None = None,
        client_addr: str | None = None,
        thread_id: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not self._config_enabled:
            return

        try:
            now = datetime.now(timezone.utc)
            timestamp = now.replace(tzinfo=None)  # ClickHouse DateTime64 expects naive datetime
            timestamp_iso = now.isoformat()

            message = message or ""
            if self._max_message_chars > 0 and len(message) > self._max_message_chars:
                message = message[: self._max_message_chars] + "..."

            payload = {
                "timestamp": timestamp,
                "timestamp_iso": timestamp_iso,
                "source": source,
                "level": str(level or "").upper(),
                "event": event or "",
                "message": message,
                "extra_json": _safe_json(extra or {}),
                "connection_id": connection_id or "",
                "session_id": session_id,
                "query_id": query_id,
                "caller_id": caller_id,
                "user_name": user_name,
                "auth_user_id": auth_user_id,
                "database_name": database_name,
                "results_db": results_db,
                "application_name": application_name,
                "client_addr": client_addr,
                "thread_id": int(thread_id or 0),
            }

            self._queue.put_nowait(payload)
        except queue.Full:
            self._dropped += 1
        except Exception:
            # Never break the main execution path for logging.
            pass

    def shutdown(self) -> None:
        if getattr(self, "_shutdown", False):
            return
        self._shutdown = True
        try:
            if self._flush_thread is not None:
                self._flush_thread.join(timeout=2.0)
        except Exception:
            pass
        try:
            if self._client is not None:
                self._client.disconnect()
        except Exception:
            pass

    def _get_client(self):
        if self._client is not None:
            return self._client

        now = time.time()
        if now < self._next_connect_time:
            return None

        with self._client_lock:
            if self._client is not None:
                return self._client
            now = time.time()
            if now < self._next_connect_time:
                return None

        try:
            from .config import get_config
            config = get_config()
            from clickhouse_driver import Client

            self._client = Client(
                host=config.clickhouse_host,
                port=config.clickhouse_port,
                database=config.clickhouse_database,
                user=config.clickhouse_user,
                password=config.clickhouse_password,
                connect_timeout=5,
                send_receive_timeout=10,
                settings={
                    "use_numpy": False,
                    "max_execution_time": 10,
                },
            )

            # Ensure table exists.
            from .schema import RUNTIME_EVENT_LOG_SCHEMA

            self._client.execute(RUNTIME_EVENT_LOG_SCHEMA)
            # Keep table schema forward-compatible even if migrations haven't run yet.
            try:
                self._client.execute(
                    "ALTER TABLE runtime_event_log "
                    "ADD COLUMN IF NOT EXISTS connection_id String DEFAULT '' AFTER timestamp_iso"
                )
                self._client.execute(
                    "ALTER TABLE runtime_event_log "
                    "ADD INDEX IF NOT EXISTS idx_connection connection_id TYPE bloom_filter GRANULARITY 1"
                )
            except Exception:
                pass
            self._connect_failures = 0
            self._next_connect_time = 0.0
            self._last_error = None
            self._last_error_at = None
            return self._client
        except Exception as e:
            self._client = None
            self._connect_failures += 1
            backoff = min(self._connect_backoff_max_s, self._connect_backoff_base_s * (2 ** min(10, self._connect_failures)))
            self._next_connect_time = time.time() + backoff
            self._last_error = str(e)
            self._last_error_at = time.time()
            return None

    def _flush_loop(self) -> None:
        batch: list[dict[str, Any]] = []
        last_flush = time.time()

        while not self._shutdown:
            try:
                try:
                    item = self._queue.get(timeout=0.5)
                    batch.append(item)
                except queue.Empty:
                    pass

                now = time.time()
                should_flush = (
                    len(batch) >= self._batch_size
                    or (batch and now - last_flush >= self._flush_interval_s)
                )

                if should_flush and batch:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = now

            except Exception:
                # Never crash the flush thread.
                batch = []
                last_flush = time.time()

        # Final flush on shutdown.
        if batch:
            self._flush_batch(batch)
        try:
            while True:
                item = self._queue.get_nowait()
                batch.append(item)
                if len(batch) >= self._batch_size:
                    self._flush_batch(batch)
                    batch = []
        except queue.Empty:
            if batch:
                self._flush_batch(batch)

    def _flush_batch(self, batch: list[dict[str, Any]]) -> None:
        client = self._get_client()
        if client is None:
            return

        cols = (
            "timestamp",
            "timestamp_iso",
            "source",
            "level",
            "event",
            "message",
            "extra_json",
            "connection_id",
            "session_id",
            "query_id",
            "caller_id",
            "user_name",
            "auth_user_id",
            "database_name",
            "results_db",
            "application_name",
            "client_addr",
            "thread_id",
        )

        rows = [tuple(item.get(c) for c in cols) for item in batch]

        try:
            client.execute(
                f"INSERT INTO runtime_event_log ({', '.join(cols)}) VALUES",
                rows,
            )
        except Exception as e:
            # Don't disable permanently; this is best-effort logging.
            try:
                client.disconnect()
            except Exception:
                pass
            self._client = None
            self._last_error = str(e)
            self._last_error_at = time.time()


def get_runtime_event_logger() -> RuntimeEventLogger:
    return RuntimeEventLogger()


def _safe_json(data: dict[str, Any]) -> str:
    try:
        return json.dumps(data, default=str)
    except Exception:
        return "{}"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default
