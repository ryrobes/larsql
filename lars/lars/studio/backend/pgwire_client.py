"""
PGwire Client - Connect to LARS SQL server via PostgreSQL protocol.

This module allows Studio HTTP workers to execute SQL via a shared PGwire
server instead of opening direct DuckDB connections. This solves the
DuckDB file locking issue when running with multiple Gunicorn workers.

Architecture:
    Browser → Flask Workers (N) → psycopg → PGwire Server (1) → DuckDB
                                            ↑ single process, no lock conflicts

Note: psycopg3 blocks at the C level (libpq), which doesn't yield to gevent.
We use a thread pool to run psycopg operations in real threads, allowing
gevent to continue handling other requests while waiting for database I/O.
"""

import os
import socket
import time
import logging
from typing import Optional, Tuple, Any, Dict, List, Callable, TypeVar
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

# Thread pool for psycopg operations (psycopg3 blocks at C level, not gevent-friendly)
# Size matches typical Gunicorn worker count - each worker may have concurrent requests
_psycopg_thread_pool: Optional[ThreadPoolExecutor] = None

T = TypeVar('T')


def _get_thread_pool() -> ThreadPoolExecutor:
    """Get or create the thread pool for psycopg operations."""
    global _psycopg_thread_pool
    if _psycopg_thread_pool is None:
        # Pool size: enough for concurrent requests across all greenlets
        # 20 threads should handle typical Studio concurrency
        _psycopg_thread_pool = ThreadPoolExecutor(max_workers=20, thread_name_prefix='psycopg')
    return _psycopg_thread_pool


def _run_in_thread(fn: Callable[..., T], *args, **kwargs) -> T:
    """
    Run a blocking function in a thread pool thread.
    
    This allows gevent to yield while psycopg blocks on I/O.
    """
    pool = _get_thread_pool()
    future = pool.submit(fn, *args, **kwargs)
    return future.result()  # This will block the greenlet but not the gevent hub

# Default PGwire port (same as `lars serve sql`)
DEFAULT_PGWIRE_PORT = 15432

# Internal PGwire port when Studio spawns its own
INTERNAL_PGWIRE_PORT = 15433

# Environment variable to communicate PGwire port to workers
PGWIRE_PORT_ENV = 'LARS_STUDIO_PGWIRE_PORT'

_invalid_env_port_logged = False


def _parse_pgwire_port(value: str) -> Optional[int]:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        # Accept float-like strings (e.g. "15433.0") produced by some env/config paths.
        try:
            as_float = float(value)
        except ValueError:
            return None
        if as_float.is_integer():
            return int(as_float)
        return None


def check_pgwire_available(host: str = 'localhost', port: int = DEFAULT_PGWIRE_PORT, timeout: float = 1.0) -> bool:
    """
    Check if a PGwire server is listening on the given port.

    Uses a simple TCP connection check - fast and doesn't require psycopg.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error, OSError):
        return False


def get_pgwire_port() -> Optional[int]:
    """
    Get the PGwire port to use, checking in order:
    1. Environment variable (set by Studio master process)
    2. Default port 15432 (external server - preferred)
    3. Internal Studio port 15433 (fallback)
    4. None (no PGwire available)
    """
    global _invalid_env_port_logged

    # Check environment variable first (explicit override)
    env_port = os.environ.get(PGWIRE_PORT_ENV)
    if env_port:
        port = _parse_pgwire_port(env_port)
        if port is None:
            if not _invalid_env_port_logged:
                log.warning(f"Invalid {PGWIRE_PORT_ENV} value: {env_port!r}")
                _invalid_env_port_logged = True
        elif check_pgwire_available(port=port):
            return port

    # Check default port FIRST (external server is preferred - more reliable)
    if check_pgwire_available(port=DEFAULT_PGWIRE_PORT):
        return DEFAULT_PGWIRE_PORT

    # Fallback to internal port (Studio-spawned server)
    if check_pgwire_available(port=INTERNAL_PGWIRE_PORT):
        return INTERNAL_PGWIRE_PORT

    return None


# Connection pool for psycopg connections
_connection_pool: Dict[str, Any] = {}  # database -> connection


@contextmanager
def get_pgwire_connection(
    database: str = 'memory',
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
):
    """
    Get a connection to PGwire server for the given database.

    Args:
        database: Database name ('memory', 'workspace', etc.)
        port: PGwire port (auto-detected if not specified)
        username: Username for authentication (default: 'lars')
        password: Password or API key for authentication (default: '')

    Yields:
        psycopg connection

    Raises:
        RuntimeError: If PGwire is not available
    """
    import psycopg

    if port is None:
        port = get_pgwire_port()

    if port is None:
        raise RuntimeError("PGwire server not available")

    # Create connection with the database name
    # PGwire uses database name to select persistent vs in-memory
    # Credentials are passed through for authentication
    conn = psycopg.connect(
        host='localhost',
        port=port,
        dbname=database,
        user=username or 'lars',
        password=password or '',
        autocommit=True,
    )

    try:
        yield conn
    finally:
        conn.close()


def _execute_sql_blocking(
    query: str,
    database: str,
    port: int,
    username: Optional[str],
    password: Optional[str],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Internal blocking implementation - runs in thread pool.
    
    All psycopg operations (connect, execute, fetch) happen here,
    isolated in a real thread so gevent can yield.
    """
    import psycopg
    
    conn = psycopg.connect(
        host='localhost',
        port=port,
        dbname=database,
        user=username or 'lars',
        password=password or '',
        autocommit=True,
    )
    
    try:
        with conn.cursor() as cur:
            cur.execute(query)

            # Handle non-SELECT queries (CREATE, INSERT, etc.)
            if cur.description is None:
                return [], []

            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            # Convert to list of dicts
            data = [dict(zip(columns, row)) for row in rows]

            return columns, data
    finally:
        conn.close()


def execute_sql_via_pgwire(
    query: str,
    database: str = 'memory',
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Execute SQL query via PGwire and return results.
    
    Runs psycopg operations in a thread pool to avoid blocking gevent.

    Args:
        query: SQL query to execute
        database: Database name
        port: PGwire port (auto-detected if not specified)
        username: Username for authentication
        password: Password or API key for authentication

    Returns:
        Tuple of (column_names, rows_as_dicts)

    Raises:
        RuntimeError: If PGwire is not available
        Exception: SQL execution errors
    """
    if port is None:
        port = get_pgwire_port()

    if port is None:
        raise RuntimeError("PGwire server not available")

    # Run blocking psycopg operations in thread pool
    return _run_in_thread(
        _execute_sql_blocking,
        query, database, port, username, password
    )


def execute_sql_via_pgwire_df(
    query: str,
    database: str = 'memory',
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
):
    """
    Execute SQL query via PGwire and return pandas DataFrame.

    Args:
        query: SQL query to execute
        database: Database name
        port: PGwire port (auto-detected if not specified)
        username: Username for authentication
        password: Password or API key for authentication

    Returns:
        pandas DataFrame with results

    Raises:
        RuntimeError: If PGwire is not available
        Exception: SQL execution errors
    """
    import pandas as pd

    columns, data = execute_sql_via_pgwire(query, database, port, username, password)

    if not columns:
        return pd.DataFrame()

    return pd.DataFrame(data, columns=columns)


class PGwireServerManager:
    """
    Manages an internal PGwire server subprocess for Studio.

    Usage:
        manager = PGwireServerManager()
        port = manager.start()  # Returns port number
        # ... use port ...
        manager.stop()
    """

    def __init__(self, port: int = INTERNAL_PGWIRE_PORT):
        self.port = port
        self.process = None
        self._started = False

    def start(self, timeout: float = 10.0) -> int:
        """
        Start the internal PGwire server.

        Args:
            timeout: Max seconds to wait for server to be ready

        Returns:
            Port number the server is listening on

        Raises:
            RuntimeError: If server fails to start
        """
        import subprocess
        import sys

        if self._started:
            return self.port

        # Check if something is already on this port
        if check_pgwire_available(port=self.port, timeout=0.5):
            log.warning(f"Port {self.port} already in use, PGwire may already be running")
            self._started = True
            return self.port

        # Start PGwire server as subprocess
        cmd = [
            sys.executable, '-m', 'lars.cli',
            'serve', 'sql',
            '--port', str(self.port),
            '--host', '127.0.0.1',  # Only listen locally
        ]

        log.info(f"Starting internal PGwire server on port {self.port}")

        # Start process with stdout/stderr going to /dev/null to avoid noise
        # In production, might want to redirect to a log file
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent process group
        )

        # Wait for server to be ready
        start_time = time.time()
        while time.time() - start_time < timeout:
            if check_pgwire_available(port=self.port, timeout=0.5):
                self._started = True
                log.info(f"Internal PGwire server ready on port {self.port}")
                return self.port

            # Check if process died
            if self.process.poll() is not None:
                raise RuntimeError(f"PGwire server process died with code {self.process.returncode}")

            time.sleep(0.2)

        # Timeout - kill the process
        self.stop()
        raise RuntimeError(f"PGwire server failed to start within {timeout}s")

    def stop(self):
        """Stop the internal PGwire server."""
        if self.process is not None:
            log.info("Stopping internal PGwire server")
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                # Force kill if terminate doesn't work
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self._started = False

    def __del__(self):
        """Cleanup on garbage collection."""
        self.stop()


# Global server manager instance (for Studio master process)
_server_manager: Optional[PGwireServerManager] = None


def ensure_pgwire_server() -> int:
    """
    Ensure a PGwire server is available, starting one if needed.

    Called by Studio startup to guarantee PGwire is available for workers.

    Returns:
        Port number of available PGwire server
    """
    global _server_manager

    # First, check if external PGwire is already running
    if check_pgwire_available(port=DEFAULT_PGWIRE_PORT):
        log.info(f"Using existing PGwire server on port {DEFAULT_PGWIRE_PORT}")
        return DEFAULT_PGWIRE_PORT

    # Start internal server
    if _server_manager is None:
        _server_manager = PGwireServerManager()

    return _server_manager.start()


def shutdown_pgwire_server():
    """
    Shutdown the internal PGwire server if we started one.

    Called by Studio shutdown.
    """
    global _server_manager

    if _server_manager is not None:
        _server_manager.stop()
        _server_manager = None
