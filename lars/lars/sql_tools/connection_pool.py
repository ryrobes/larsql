"""
Pre-warmed Connection Pool for DuckDB

Maintains a pool of fully initialized DuckDB connections ready for immediate use.
Each connection has:
- Extensions loaded (duckpgq)
- All UDFs registered
- Shared tables attached (parquet-backed)
- External databases attached

This eliminates the ~2-3 second initialization overhead per request.

Usage:
    from lars.sql_tools.connection_pool import get_pooled_connection, return_to_pool

    conn = get_pooled_connection()  # Instant - pre-warmed
    try:
        result = conn.execute("SELECT * FROM shared.staging_my_table").fetchdf()
    finally:
        return_to_pool(conn)  # Return for reuse

Configuration:
    LARS_POOL_SIZE: Number of connections to pre-warm (default: 4)
    LARS_POOL_ENABLED: Set to '0' to disable pooling (default: enabled)
"""

import os
import duckdb
import logging
import threading
import atexit
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from ..stdlib_queue import Empty, Queue

log = logging.getLogger(__name__)

# Pool configuration
_DEFAULT_WARMUP_SIZE = 16   # Pre-warm this many connections at startup
_DEFAULT_MAX_SIZE = 64     # Pool can grow up to this size with demand
_pool: Optional[Queue] = None
_pool_lock = threading.Lock()
_pool_initialized = False
_warming_in_progress = False

# Pool statistics
_pool_stats = {
    'hits': 0,      # Successful get from pool
    'misses': 0,    # Pool empty when get requested
    'returns': 0,   # Successful returns to pool
    'discards': 0,  # Connections discarded (unhealthy or pool full)
    'peak_size': 0, # Highest pool size seen
}
_stats_lock = threading.Lock()


def _pool_debug_print(message: str) -> None:
    """Optional stdout logging for the pool (disabled by default)."""
    val = os.environ.get("LARS_POOL_DEBUG", "0").strip().lower()
    if val in ("1", "true", "yes", "on"):
        print(message)


def _get_warmup_size() -> int:
    """Get number of connections to pre-warm at startup."""
    try:
        return int(os.environ.get('LARS_POOL_SIZE', _DEFAULT_WARMUP_SIZE))
    except ValueError:
        return _DEFAULT_WARMUP_SIZE


def _get_max_size() -> int:
    """Get maximum pool size (pool can grow up to this with demand)."""
    try:
        return int(os.environ.get('LARS_POOL_MAX_SIZE', _DEFAULT_MAX_SIZE))
    except ValueError:
        return _DEFAULT_MAX_SIZE


def _is_pool_enabled() -> bool:
    """Check if connection pooling is enabled."""
    return os.environ.get('LARS_POOL_ENABLED', '1').lower() not in ('0', 'false', 'no')


def _create_warmed_connection() -> duckdb.DuckDBPyConnection:
    """
    Create a fully initialized in-memory DuckDB connection.

    This replicates the full initialization sequence but returns
    a ready-to-use connection.
    """
    conn = duckdb.connect(':memory:')
    conn.execute("SET threads TO 4")

    # Load extensions
    _load_extensions(conn)

    # Register UDFs
    _register_udfs(conn)

    # Attach shared tables
    _attach_shared_tables(conn)

    # Attach external databases
    _attach_external_databases(conn)

    # Create PG compat macros
    _create_pg_compat(conn)

    return conn


def _load_extensions(conn: duckdb.DuckDBPyConnection) -> None:
    """Load required extensions."""
    # DuckPGQ (graph queries)
    try:
        conn.execute("INSTALL duckpgq FROM community")
        conn.execute("LOAD duckpgq")
    except Exception as e:
        log.debug(f"[pool] duckpgq extension: {e}")


def _register_udfs(conn: duckdb.DuckDBPyConnection) -> None:
    """Register all LARS UDFs."""
    try:
        from .udf import register_lars_udf, register_dynamic_sql_functions
        register_lars_udf(conn)
        register_dynamic_sql_functions(conn)
    except Exception as e:
        log.warning(f"[pool] UDF registration failed: {e}")


def _attach_shared_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Attach shared parquet tables for cross-session visibility."""
    try:
        from .shared_parquet import attach_shared_tables, is_shared_tables_enabled
        if is_shared_tables_enabled():
            attach_shared_tables(conn)
    except Exception as e:
        log.warning(f"[pool] Shared tables attach failed: {e}")


def _attach_external_databases(conn: duckdb.DuckDBPyConnection) -> None:
    """Attach configured external databases (if LARS_POOL_ATTACH_ALL is set)."""
    try:
        # Skip heavy attach_all during pool warming by default
        # External DBs will be lazily attached when first referenced
        if os.environ.get('LARS_POOL_ATTACH_ALL', '0').lower() not in ('1', 'true', 'yes'):
            log.debug("[pool] Skipping external DB attach (lazy attach enabled)")
            return
            
        from .lazy_attach import LazyAttachManager
        from .config import load_sql_connections

        if os.environ.get('LARS_AUTO_ATTACH_ALL', '1').lower() in ('1', 'true', 'yes'):
            manager = LazyAttachManager(conn, load_sql_connections())
            manager.attach_all()
    except Exception as e:
        log.debug(f"[pool] External database attach: {e}")


def _create_pg_compat(conn: duckdb.DuckDBPyConnection) -> None:
    """Create PostgreSQL compatibility macros."""
    macros = [
        "CREATE OR REPLACE MACRO pg_get_userbyid(x) AS 'lars'",
        "CREATE OR REPLACE MACRO txid_current() AS (SELECT 1)",
        "CREATE OR REPLACE MACRO pg_backend_pid() AS (SELECT 1)",
    ]
    for macro in macros:
        try:
            conn.execute(macro)
        except Exception:
            pass


def _warm_pool_background() -> None:
    """Warm the pool in background threads."""
    global _pool, _warming_in_progress

    warmup_size = _get_warmup_size()
    log.info(f"[pool] Warming {warmup_size} connections in background...")

    def create_and_add():
        try:
            conn = _create_warmed_connection()
            _pool.put(conn)
            log.debug("[pool] Added warmed connection to pool")
        except Exception as e:
            log.warning(f"[pool] Failed to warm connection: {e}")

    # Use thread pool for parallel warming
    with ThreadPoolExecutor(max_workers=min(warmup_size, 4)) as executor:
        futures = [executor.submit(create_and_add) for _ in range(warmup_size)]
        for f in futures:
            try:
                f.result(timeout=30)
            except Exception as e:
                log.warning(f"[pool] Warming future failed: {e}")

    _warming_in_progress = False
    log.info(f"[pool] Pool warmed with {_pool.qsize()} connections")


def initialize_pool() -> None:
    """
    Initialize the connection pool.

    Call this at application startup to pre-warm connections.
    Safe to call multiple times (idempotent).
    """
    global _pool, _pool_initialized, _warming_in_progress

    if not _is_pool_enabled():
        log.info("[pool] Connection pooling disabled")
        return

    with _pool_lock:
        if _pool_initialized:
            return

        _pool = Queue()
        _pool_initialized = True
        _warming_in_progress = True

    # Warm in background thread to not block startup
    thread = threading.Thread(target=_warm_pool_background, daemon=True)
    thread.start()


def get_pooled_connection(timeout: float = 1.0) -> Optional[duckdb.DuckDBPyConnection]:
    """
    Get a pre-warmed connection from the pool.

    Args:
        timeout: How long to wait for a pooled connection (seconds)
                 If timeout expires, returns None (caller should create fresh)

    Returns:
        Pre-warmed DuckDB connection, or None if pool empty/disabled
    """
    global _pool, _pool_stats

    if not _is_pool_enabled() or _pool is None:
        return None

    try:
        conn = _pool.get(timeout=timeout)

        # Health check
        try:
            conn.execute("SELECT 1").fetchone()
            with _stats_lock:
                _pool_stats['hits'] += 1
                hits = _pool_stats['hits']
                misses = _pool_stats['misses']
            size = _pool.qsize()
            _pool_debug_print(f"[pool] GET: size={size}, hits={hits}, misses={misses}")
            return conn
        except Exception:
            # Connection is bad, discard and try again
            with _stats_lock:
                _pool_stats['discards'] += 1
            log.warning("[pool] Discarding bad pooled connection")
            try:
                conn.close()
            except Exception:
                pass
            return get_pooled_connection(timeout=0)  # Try once more, no wait

    except Empty:
        with _stats_lock:
            _pool_stats['misses'] += 1
            misses = _pool_stats['misses']
            hits = _pool_stats['hits']
        _pool_debug_print(f"[pool] MISS: pool empty, hits={hits}, misses={misses}")
        return None


def return_to_pool(conn: duckdb.DuckDBPyConnection) -> bool:
    """
    Return a connection to the pool for reuse.

    Args:
        conn: Connection to return

    Returns:
        True if returned to pool, False if pool full/disabled
    """
    global _pool, _pool_stats

    if not _is_pool_enabled() or _pool is None:
        try:
            conn.close()
        except Exception:
            pass
        return False

    max_size = _get_max_size()

    # Don't exceed max pool size
    if _pool.qsize() >= max_size:
        with _stats_lock:
            _pool_stats['discards'] += 1
        _pool_debug_print(f"[pool] DISCARD: pool at max (size={max_size})")
        try:
            conn.close()
        except Exception:
            pass
        return False

    # Health check before returning
    try:
        conn.execute("SELECT 1").fetchone()
        _pool.put(conn)
        size = _pool.qsize()
        with _stats_lock:
            _pool_stats['returns'] += 1
            returns = _pool_stats['returns']
            if size > _pool_stats['peak_size']:
                _pool_stats['peak_size'] = size
        _pool_debug_print(f"[pool] RETURN: size={size}, total_returns={returns}")
        return True
    except Exception:
        with _stats_lock:
            _pool_stats['discards'] += 1
        log.warning("[pool] Connection unhealthy, not returning to pool")
        try:
            conn.close()
        except Exception:
            pass
        return False


def refill_pool() -> None:
    """
    Refill the pool to warmup size.

    Call this periodically or after high load to maintain baseline pool size.
    """
    global _pool

    if not _is_pool_enabled() or _pool is None:
        return

    warmup_size = _get_warmup_size()
    current_size = _pool.qsize()
    needed = warmup_size - current_size

    if needed <= 0:
        return

    log.debug(f"[pool] Refilling pool with {needed} connections")

    def create_and_add():
        try:
            conn = _create_warmed_connection()
            _pool.put(conn)
        except Exception as e:
            log.warning(f"[pool] Failed to create connection for refill: {e}")

    # Refill in background
    thread = threading.Thread(target=lambda: [create_and_add() for _ in range(needed)], daemon=True)
    thread.start()


def pool_status() -> dict:
    """Get current pool status including stats."""
    with _stats_lock:
        stats = _pool_stats.copy()
    return {
        "enabled": _is_pool_enabled(),
        "initialized": _pool_initialized,
        "warming": _warming_in_progress,
        "size": _pool.qsize() if _pool else 0,
        "warmup_size": _get_warmup_size(),
        "max_size": _get_max_size(),
        "peak_size": stats['peak_size'],
        "hits": stats['hits'],
        "misses": stats['misses'],
        "returns": stats['returns'],
        "discards": stats['discards'],
        "hit_rate": f"{stats['hits'] / (stats['hits'] + stats['misses']) * 100:.1f}%" if (stats['hits'] + stats['misses']) > 0 else "N/A",
    }


@atexit.register
def _cleanup_pool():
    """Clean up pool on exit."""
    global _pool

    if _pool is None:
        return

    log.debug("[pool] Cleaning up connection pool")

    while not _pool.empty():
        try:
            conn = _pool.get_nowait()
            conn.close()
        except Exception:
            pass
