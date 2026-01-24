"""
Performance logging system for LARS cascade execution.

Provides low-overhead timing instrumentation that logs to ClickHouse
for analysis and optimization tracking.

Usage:
    from lars.perf_logger import perf_timer

    with perf_timer("config_load", session_id=session_id):
        config = load_cascade_config(path)

    # Or for code blocks
    with perf_timer("agent_call", session_id=session_id, metadata={"model": model}):
        response = agent.run(...)
"""

import time
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any
from threading import Lock

logger = logging.getLogger(__name__)

# Global metrics buffer (thread-safe)
_metrics_buffer = []
_metrics_lock = Lock()
_buffer_threshold = 50  # Flush every N metrics


@contextmanager
def perf_timer(
    label: str,
    session_id: Optional[str] = None,
    cascade_id: Optional[str] = None,
    cell_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    auto_flush: bool = True
):
    """
    Context manager for timing code blocks with automatic ClickHouse logging.

    Args:
        label: Metric name (e.g., "config_load", "agent_call", "tool_execution")
        session_id: Optional session identifier
        cascade_id: Optional cascade identifier
        cell_name: Optional cell name
        metadata: Optional dict of additional metadata (will be JSON serialized)
        auto_flush: If True, periodically flush buffer to ClickHouse

    Example:
        with perf_timer("database_query", session_id=sid, metadata={"table": "users"}):
            result = db.query("SELECT * FROM users")
    """
    start_ns = time.perf_counter_ns()
    exception_occurred = False
    exception_type = None

    try:
        yield
    except Exception as e:
        exception_occurred = True
        exception_type = type(e).__name__
        raise
    finally:
        end_ns = time.perf_counter_ns()
        duration_ns = end_ns - start_ns
        duration_ms = duration_ns / 1_000_000  # Convert to milliseconds

        # Record metric
        metric = {
            "timestamp": time.time(),
            "label": label,
            "duration_ns": duration_ns,
            "duration_ms": duration_ms,
            "session_id": session_id or "",
            "cascade_id": cascade_id or "",
            "cell_name": cell_name or "",
            "metadata_json": _serialize_metadata(metadata) if metadata else "{}",
            "exception_occurred": exception_occurred,
            "exception_type": exception_type or ""
        }

        # Add to buffer (thread-safe)
        with _metrics_lock:
            _metrics_buffer.append(metric)
            should_flush = auto_flush and len(_metrics_buffer) >= _buffer_threshold

        # Flush if threshold reached
        if should_flush:
            flush_metrics()


def _serialize_metadata(metadata: Dict[str, Any]) -> str:
    """Safely serialize metadata dict to JSON string."""
    import json
    try:
        return json.dumps(metadata, default=str)
    except Exception as e:
        logger.warning(f"Failed to serialize perf metadata: {e}")
        return "{}"


def flush_metrics():
    """
    Flush buffered metrics to ClickHouse.

    This is called automatically when buffer reaches threshold,
    or can be called manually at cascade end.
    """
    global _metrics_buffer

    with _metrics_lock:
        if not _metrics_buffer:
            return

        # Grab current buffer and reset
        metrics_to_write = _metrics_buffer.copy()
        _metrics_buffer.clear()

    # Write to ClickHouse (non-blocking, best effort)
    try:
        from .db_adapter import get_db
        from datetime import datetime

        db = get_db()

        # Convert to ClickHouse-friendly format
        rows = []
        for m in metrics_to_write:
            rows.append({
                "timestamp": datetime.fromtimestamp(m["timestamp"]),
                "label": m["label"],
                "duration_ns": m["duration_ns"],
                "duration_ms": m["duration_ms"],
                "session_id": m["session_id"],
                "cascade_id": m["cascade_id"],
                "cell_name": m["cell_name"],
                "metadata_json": m["metadata_json"],
                "exception_occurred": 1 if m["exception_occurred"] else 0,
                "exception_type": m["exception_type"]
            })

        # Async insert (fire-and-forget, similar to unified_logs)
        db.insert_rows(
            'perf_metrics',
            rows,
            columns=[
                'timestamp', 'label', 'duration_ns', 'duration_ms',
                'session_id', 'cascade_id', 'cell_name', 'metadata_json',
                'exception_occurred', 'exception_type'
            ]
        )

        logger.debug(f"Flushed {len(rows)} perf metrics to ClickHouse")

    except Exception as e:
        # Don't fail cascades due to perf logging issues
        logger.debug(f"Failed to flush perf metrics: {e}")


def force_flush():
    """
    Force flush all buffered metrics immediately.

    Call this at cascade end or before process exit to ensure
    all metrics are persisted.
    """
    flush_metrics()


def get_buffer_size() -> int:
    """Get current buffer size (for monitoring/debugging)."""
    with _metrics_lock:
        return len(_metrics_buffer)


# Convenience function for one-off timing without context manager
def log_timing(
    label: str,
    duration_ms: float,
    session_id: Optional[str] = None,
    cascade_id: Optional[str] = None,
    cell_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Log a timing metric without using context manager.

    Useful when you already have the duration calculated.

    Args:
        label: Metric name
        duration_ms: Duration in milliseconds
        session_id: Optional session identifier
        cascade_id: Optional cascade identifier
        cell_name: Optional cell name
        metadata: Optional additional metadata
    """
    metric = {
        "timestamp": time.time(),
        "label": label,
        "duration_ns": int(duration_ms * 1_000_000),
        "duration_ms": duration_ms,
        "session_id": session_id or "",
        "cascade_id": cascade_id or "",
        "cell_name": cell_name or "",
        "metadata_json": _serialize_metadata(metadata) if metadata else "{}",
        "exception_occurred": False,
        "exception_type": ""
    }

    with _metrics_lock:
        _metrics_buffer.append(metric)
        should_flush = len(_metrics_buffer) >= _buffer_threshold

    if should_flush:
        flush_metrics()
