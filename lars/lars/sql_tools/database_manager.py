"""
Database Manager - Shared initialization logic for DuckDB connections.

This module provides the same database initialization that PGwire uses,
making it available to HTTP APIs and other entry points.

Features:
- List available persistent databases
- Full initialization (UDFs, auto-attach, metadata tables)
- Lazy attach support for external databases
- Thread-safe connection management
- Graceful handling of locked databases (snapshot fallback)
"""

import os
import shutil
import tempfile
import duckdb
from typing import Dict, List, Set, Any, Tuple
from threading import Lock
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import logging

log = logging.getLogger(__name__)

# Track which databases have been fully initialized (per-process)
_initialized_databases: Set[str] = set()
_init_db_lock = Lock()

# Cache of database connections (separate from session_db.py for clarity)
_database_connections: Dict[str, duckdb.DuckDBPyConnection] = {}
_database_locks: Dict[str, Lock] = {}

# Thread-local storage for file-based connections (one per thread per database)
# This enables parallel execution across threads without locking, while reusing
# connections within the same thread to avoid repeated UDF registration overhead.
_thread_local = threading.local()

# Track snapshot copies for cleanup
_snapshot_paths: Dict[str, str] = {}  # db_key -> snapshot_path

# Directory for snapshot copies
_SNAPSHOT_DIR = os.path.join(tempfile.gettempdir(), "lars_db_snapshots")

# Track which extensions have been installed (to avoid redundant installs)
_installed_extensions: Set[str] = set()


def list_databases() -> List[Dict[str, Any]]:
    """
    List all available databases.

    Returns:
        List of database info dicts with:
        - name: Database name
        - type: "memory" or "persistent"
        - path: File path (for persistent) or None
        - size_mb: File size in MB (for persistent)
    """
    from ..config import get_config
    config = get_config()
    session_db_dir = os.path.join(config.root_dir, 'session_dbs')

    databases = []

    # Always include workspace (default persistent database for Studio)
    workspace_path = os.path.join(session_db_dir, 'workspace.duckdb')
    workspace_size = None
    if os.path.exists(workspace_path):
        try:
            workspace_size = round(os.path.getsize(workspace_path) / (1024 * 1024), 2)
        except Exception:
            pass

    databases.append({
        "name": "workspace",
        "type": "persistent",
        "path": workspace_path,
        "size_mb": workspace_size,
    })

    # Always include memory/default options
    databases.append({
        "name": "memory",
        "type": "memory",
        "path": None,
        "size_mb": None,
    })

    # Scan session_dbs directory for other persistent databases

    if os.path.exists(session_db_dir):
        for filename in os.listdir(session_db_dir):
            if filename.endswith('.duckdb'):
                db_name = filename[:-7]  # Remove .duckdb extension
                db_path = os.path.join(session_db_dir, filename)

                # Skip internal/temp/ephemeral databases and workspace (already added above)
                if (db_name == 'workspace' or
                    db_name.startswith('http_api_') or
                    db_name.startswith('health_check_') or
                    db_name.startswith('cli-') or
                    db_name.startswith('inttest')):
                    continue

                try:
                    size_bytes = os.path.getsize(db_path)
                    size_mb = round(size_bytes / (1024 * 1024), 2)
                except Exception:
                    size_mb = None

                databases.append({
                    "name": db_name,
                    "type": "persistent",
                    "path": db_path,
                    "size_mb": size_mb,
                })

    # Sort: workspace first, then memory, then other persistent DBs alphabetically
    def sort_key(d):
        if d["name"] == "workspace":
            return (0, "")
        if d["type"] == "memory":
            return (1, "")
        return (2, d["name"])
    databases.sort(key=sort_key)

    return databases


def _open_database_with_fallback(db_path: str, db_key: str) -> Tuple[duckdb.DuckDBPyConnection, bool]:
    """
    Open a DuckDB database with fallback for locked databases.

    Strategy:
    1. Try normal read/write open
    2. If locked, try read-only mode
    3. If still locked, create a snapshot copy and open that

    Args:
        db_path: Path to the database file
        db_key: Database key for logging/tracking

    Returns:
        Tuple of (connection, is_read_only)
    """
    # Strategy 1: Try normal read/write
    try:
        conn = duckdb.connect(db_path)
        conn.execute("SET threads TO 4")  # Limit CPU usage
        log.info(f"[database_manager] Opened persistent database: {db_path}")
        return conn, False
    except duckdb.IOException as e:
        if "lock" not in str(e).lower():
            raise  # Not a lock error, re-raise

        log.warning(f"[database_manager] Database {db_key} is locked, trying read-only mode")

    # Strategy 2: Try read-only mode
    try:
        conn = duckdb.connect(db_path, read_only=True)
        conn.execute("SET threads TO 4")  # Limit CPU usage
        log.info(f"[database_manager] Opened {db_key} in read-only mode (locked by another process)")
        return conn, True
    except duckdb.IOException as e:
        if "lock" not in str(e).lower():
            raise

        log.warning(f"[database_manager] Read-only also failed, creating snapshot copy")

    # Strategy 3: Create snapshot copy
    os.makedirs(_SNAPSHOT_DIR, exist_ok=True)
    snapshot_path = os.path.join(_SNAPSHOT_DIR, f"{db_key}_snapshot.duckdb")

    # Copy the database file (and WAL if present)
    shutil.copy2(db_path, snapshot_path)
    wal_path = db_path + ".wal"
    if os.path.exists(wal_path):
        shutil.copy2(wal_path, snapshot_path + ".wal")

    # Track for potential cleanup
    _snapshot_paths[db_key] = snapshot_path

    conn = duckdb.connect(snapshot_path)
    conn.execute("SET threads TO 4")  # Limit CPU usage
    log.info(f"[database_manager] Opened snapshot copy of {db_key} (original locked)")
    return conn, False  # Snapshot is writable but changes won't persist to original


def get_database_connection(
    database_name: str,
    initialize: bool = True
) -> duckdb.DuckDBPyConnection:
    """
    Get or create a fully initialized DuckDB connection.

    This replicates the PGwire initialization sequence:
    1. Create/open DuckDB connection (with lock fallback)
    2. Register UDFs (lars, lars_cascade_udf, etc.)
    3. Auto-attach external databases (if enabled)
    4. Create metadata tables

    If the database is locked by another process (e.g., PGwire), this will:
    1. Try read-only mode first
    2. Fall back to a snapshot copy if needed

    Args:
        database_name: Database name ("memory", "default", or persistent name)
        initialize: If True, run full initialization sequence

    Returns:
        Initialized DuckDB connection
    """
    # Normalize database name
    db_key = _normalize_database_name(database_name)
    is_memory = db_key in ('memory', 'default', ':memory:')

    with _init_db_lock:
        # Check for existing connection
        if db_key in _database_connections:
            conn = _database_connections[db_key]
            # Health check
            try:
                conn.execute("SELECT 1").fetchone()
                return conn
            except Exception as e:
                log.warning(f"[database_manager] Connection for {db_key} is bad: {e}")
                try:
                    conn.close()
                except:
                    pass
                del _database_connections[db_key]
                _initialized_databases.discard(db_key)

        # Create new connection
        if is_memory:
            conn = duckdb.connect(':memory:')
            log.info(f"[database_manager] Created in-memory connection")
        else:
            db_path = _get_database_path(db_key)
            conn, _is_readonly = _open_database_with_fallback(db_path, db_key)

        # Configure DuckDB
        conn.execute("SET threads TO 4")

        # Cache connection and create lock
        _database_connections[db_key] = conn
        if db_key not in _database_locks:
            _database_locks[db_key] = Lock()

        # Run initialization if requested
        if initialize:
            _initialize_database(conn, db_key, is_memory)

        return conn


def get_database_lock(database_name: str) -> Lock:
    """
    Get the lock for a database connection.

    Use this when executing queries to prevent concurrent access issues.
    """
    db_key = _normalize_database_name(database_name)
    with _init_db_lock:
        if db_key not in _database_locks:
            _database_locks[db_key] = Lock()
        return _database_locks[db_key]


def get_fresh_connection(
    database_name: str,
    initialize: bool = True,
    use_pool: bool = True
) -> Tuple[duckdb.DuckDBPyConnection, bool, bool]:
    """
    Get a database connection optimized for parallel execution.

    For in-memory databases: First tries to get a pre-warmed connection from
    the pool (instant). Falls back to cached shared connection if pool empty.

    For file-based databases: Uses thread-local connections. Each thread gets
    its own connection that persists across requests, avoiding repeated UDF
    registration overhead. Different threads can execute in parallel since
    DuckDB handles concurrency via WAL.

    Args:
        database_name: Database name ("memory", "default", or persistent name)
        initialize: If True, run full initialization sequence
        use_pool: If True, try to get a pre-warmed connection from pool (memory only)

    Returns:
        Tuple of (connection, is_memory, needs_lock)
        - connection: DuckDB connection
        - is_memory: True if this is an in-memory database
        - needs_lock: True if caller should use get_database_lock() for serialization
    """
    db_key = _normalize_database_name(database_name)
    is_memory = db_key in ('memory', 'default', ':memory:')

    if is_memory:
        # Try pre-warmed pool first (instant, no initialization needed)
        if use_pool:
            try:
                from .connection_pool import get_pooled_connection
                pooled = get_pooled_connection(timeout=0.05)
                if pooled:
                    log.debug("[database_manager] Using pre-warmed pooled connection")
                    # Pooled connections don't need lock since each request gets its own
                    return pooled, True, False
            except ImportError:
                pass
            except Exception as e:
                log.debug(f"[database_manager] Pool access failed: {e}")

        # Fallback: cached shared connection (requires lock)
        conn = get_database_connection(database_name, initialize)
        return conn, True, True  # needs_lock=True

    # File-based: use thread-local connection for efficiency
    # Each thread gets its own connection, reused across requests
    if not hasattr(_thread_local, 'connections'):
        _thread_local.connections = {}

    # Check for existing thread-local connection
    if db_key in _thread_local.connections:
        conn = _thread_local.connections[db_key]
        # Health check
        try:
            conn.execute("SELECT 1").fetchone()
            log.debug(f"[database_manager] Reusing thread-local connection for: {db_key}")
            return conn, False, False
        except Exception as e:
            log.warning(f"[database_manager] Thread-local connection for {db_key} is bad: {e}")
            try:
                conn.close()
            except:
                pass
            del _thread_local.connections[db_key]

    # Create new thread-local connection
    db_path = _get_database_path(db_key)

    try:
        conn = duckdb.connect(db_path)
        log.debug(f"[database_manager] Opened new thread-local connection to: {db_path}")
    except duckdb.IOException as e:
        if "lock" in str(e).lower():
            # Try read-only if write-locked
            conn = duckdb.connect(db_path, read_only=True)
            log.debug(f"[database_manager] Opened thread-local read-only connection to: {db_path}")
        else:
            raise

    # Configure DuckDB
    conn.execute("SET threads TO 4")

    # Run initialization
    if initialize:
        _initialize_database(conn, db_key, is_memory=False)

    # Cache in thread-local storage
    _thread_local.connections[db_key] = conn

    return conn, False, False  # needs_lock=False (DuckDB handles concurrency)


def release_connection(conn: duckdb.DuckDBPyConnection, is_pooled: bool = False) -> None:
    """
    Release a connection after use.

    For pooled connections: Returns to pool for reuse.
    For non-pooled connections: No-op (connection stays cached).

    Args:
        conn: Connection to release
        is_pooled: True if this connection came from the pool
    """
    if not is_pooled:
        return  # Non-pooled connections stay cached

    try:
        from .connection_pool import return_to_pool, refill_pool
        returned = return_to_pool(conn)
        if returned:
            log.debug("[database_manager] Returned connection to pool")
        # Trigger refill in background if pool is getting low
        refill_pool()
    except ImportError:
        pass
    except Exception as e:
        log.debug(f"[database_manager] Pool return failed: {e}")


def ensure_lazy_attach(conn: duckdb.DuckDBPyConnection, sql: str) -> None:
    """
    Ensure external databases referenced in SQL are attached.

    Call this before executing queries that may reference external databases.
    """
    try:
        from .lazy_attach import LazyAttachManager
        from .config import load_sql_connections

        # Get or create lazy attach manager for this connection
        manager = LazyAttachManager(conn, load_sql_connections())
        manager.ensure_for_query(sql)
    except ImportError:
        log.debug("[database_manager] lazy_attach not available, skipping")
    except Exception as e:
        log.warning(f"[database_manager] Lazy attach failed: {e}")


def _normalize_database_name(name: str) -> str:
    """Normalize database name for consistent key lookup."""
    name = name.lower().strip()
    if name in ('memory', 'default', ':memory:', ''):
        return 'memory'
    # Sanitize for filesystem
    return name.replace("/", "_").replace("\\", "_")


def _get_database_path(db_name: str) -> str:
    """Get filesystem path for a persistent database."""
    from ..config import get_config

    config = get_config()
    session_db_dir = os.path.join(config.root_dir, 'session_dbs')
    os.makedirs(session_db_dir, exist_ok=True)

    return os.path.join(session_db_dir, f"{db_name}.duckdb")


def _initialize_database(
    conn: duckdb.DuckDBPyConnection,
    db_key: str,
    is_memory: bool
) -> None:
    """
    Run full database initialization sequence.

    Replicates PGwire's setup_session_minimal() + setup_session_deferred().

    IMPORTANT: UDFs are per-connection, so _setup_minimal() must ALWAYS run
    for each new connection. Only _setup_deferred() (metadata tables, auto-attach)
    can be skipped for already-initialized file-based databases.
    """
    # Check if deferred setup already done (for persistent DBs)
    already_initialized = not is_memory and db_key in _initialized_databases

    log.info(f"[database_manager] Initializing connection for: {db_key} (deferred={'skip' if already_initialized else 'run'})")

    # Phase 1: Minimal setup (UDFs) - ALWAYS run for each connection
    # UDFs are registered per-connection, not persisted in the database file
    _setup_minimal(conn)

    # Phase 2: Deferred setup (auto-attach, metadata tables)
    # Only run once per database (persisted in the file)
    if not already_initialized:
        _setup_deferred(conn, db_key)

        # Mark as initialized
        if not is_memory:
            _initialized_databases.add(db_key)

    log.info(f"[database_manager] Connection initialization complete for: {db_key}")


def _install_community_extensions(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Install and load community extensions needed for LARS features.

    Currently installs:
    - duckpgq: SQL/PGQ graph queries for property graphs (used by TO_PROPERTY_GRAPH)

    Note: Installation is done with a timeout to prevent blocking on network issues.
    """
    global _installed_extensions

    # DuckPGQ - Property Graph Queries (SQL:2023 standard)
    # Used by RICH_TRIPLES -> TO_PROPERTY_GRAPH pipeline
    if 'duckpgq' not in _installed_extensions:
        def install_extension():
            conn.execute("INSTALL duckpgq FROM community;")

        try:
            # Use ThreadPoolExecutor with timeout to prevent blocking on network issues
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(install_extension)
                future.result(timeout=5.0)  # 5 second timeout for network install
            _installed_extensions.add('duckpgq')
            log.debug("[database_manager] Installed duckpgq extension")
        except FuturesTimeoutError:
            log.warning("[database_manager] duckpgq install timed out (network issue?), skipping")
        except Exception as e:
            # Extension might already be installed globally
            if "already installed" not in str(e).lower():
                log.debug(f"[database_manager] duckpgq install note: {e}")

    # Load duckpgq for this connection (only if installed)
    if 'duckpgq' in _installed_extensions:
        try:
            conn.execute("LOAD duckpgq;")
            log.debug("[database_manager] Loaded duckpgq extension")
        except Exception as e:
            log.warning(f"[database_manager] Failed to load duckpgq: {e}")


def _setup_minimal(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Minimal setup - register UDFs and basic config.

    This is the fast path that must complete before responding to clients.
    """
    # Install community extensions for graph queries
    _install_community_extensions(conn)

    # Register LARS UDFs
    try:
        from .udf import register_lars_udf
        register_lars_udf(conn)
        log.debug("[database_manager] Registered LARS UDFs")
    except Exception as e:
        log.warning(f"[database_manager] Failed to register LARS UDFs: {e}")

    # Register dynamic SQL functions (semantic operators)
    try:
        from .udf import register_dynamic_sql_functions
        register_dynamic_sql_functions(conn)
        log.debug("[database_manager] Registered dynamic SQL functions")
    except Exception as e:
        log.warning(f"[database_manager] Failed to register dynamic SQL functions: {e}")

    # Create PostgreSQL compatibility macros
    _create_pg_compat_macros(conn)


def _setup_deferred(conn: duckdb.DuckDBPyConnection, db_key: str) -> None:
    """
    Deferred setup - auto-attach, metadata tables, etc.

    This runs after minimal setup and handles heavier initialization.
    """
    log.debug(f"[database_manager] Running deferred setup for {db_key}")

    # Attach shared parquet tables for cross-session visibility
    # Tables in 'shared' schema are backed by parquet files (no locking issues)
    try:
        from .shared_parquet import attach_shared_tables, is_shared_tables_enabled
        if is_shared_tables_enabled():
            if attach_shared_tables(conn):
                log.info(f"[database_manager] Shared tables attached (parquet-backed 'shared' schema)")
    except Exception as e:
        log.warning(f"[database_manager] Shared tables attachment failed: {e}")

    # Auto-attach external databases (if enabled)
    try:
        if _auto_attach_enabled():
            from .lazy_attach import LazyAttachManager
            from .config import load_sql_connections
            manager = LazyAttachManager(conn, load_sql_connections())
            results = manager.attach_all()
            attached = [r for r in results if r.get("status") == "attached"]
            if attached:
                log.info(f"[database_manager] Auto-attached {len(attached)} databases")
    except ImportError:
        log.debug("[database_manager] lazy_attach not available")
    except Exception as e:
        log.warning(f"[database_manager] Auto-attach failed: {e}")

    # Create metadata tables
    _create_metadata_tables(conn)

    # Replay previous attachments (for persistent DBs)
    _replay_attachments(conn)


def _auto_attach_enabled() -> bool:
    """Check if auto-attach is enabled via environment variable."""
    return os.environ.get('LARS_AUTO_ATTACH_ALL', '1').lower() in ('1', 'true', 'yes')


def _create_pg_compat_macros(conn: duckdb.DuckDBPyConnection) -> None:
    """Create PostgreSQL compatibility macros for client tools."""
    macros = [
        "CREATE OR REPLACE MACRO pg_get_userbyid(x) AS 'lars'",
        "CREATE OR REPLACE MACRO txid_current() AS (SELECT 1)",
        "CREATE OR REPLACE MACRO pg_backend_pid() AS (SELECT 1)",
    ]

    for macro in macros:
        try:
            conn.execute(macro)
        except Exception:
            pass  # Ignore if already exists or fails


def _create_metadata_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create metadata tables for tracking attachments and results."""
    try:
        # Attachments tracking table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _lars_attachments (
                id INTEGER PRIMARY KEY,
                database_alias VARCHAR NOT NULL,
                database_path VARCHAR NOT NULL,
                attached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(database_alias)
            )
        """)

        # Results registry table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _lars_results (
                query_id VARCHAR PRIMARY KEY,
                schema_name VARCHAR NOT NULL,
                table_name VARCHAR NOT NULL,
                full_table_name VARCHAR NOT NULL,
                query_fingerprint VARCHAR,
                row_count INTEGER,
                column_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        log.debug("[database_manager] Created metadata tables")
    except Exception as e:
        log.warning(f"[database_manager] Failed to create metadata tables: {e}")


def _replay_attachments(conn: duckdb.DuckDBPyConnection) -> None:
    """Replay previous ATTACH commands from _lars_attachments table."""
    try:
        # Check if table exists
        result = conn.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = '_lars_attachments'
        """).fetchone()

        if not result:
            return

        # Get previously attached databases
        attachments = conn.execute("""
            SELECT database_alias, database_path FROM _lars_attachments
        """).fetchall()

        for alias, path in attachments:
            try:
                # Check if already attached
                catalogs = [r[0] for r in conn.execute("SHOW DATABASES").fetchall()]
                if alias in catalogs:
                    continue

                # Re-attach
                conn.execute(f"ATTACH '{path}' AS {alias}")
                log.debug(f"[database_manager] Replayed attachment: {alias}")
            except Exception as e:
                log.warning(f"[database_manager] Failed to replay attachment {alias}: {e}")

    except Exception as e:
        log.debug(f"[database_manager] Replay attachments skipped: {e}")
