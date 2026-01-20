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
import logging

log = logging.getLogger(__name__)

# Track which databases have been fully initialized (per-process)
_initialized_databases: Set[str] = set()
_init_db_lock = Lock()

# Cache of database connections (separate from session_db.py for clarity)
_database_connections: Dict[str, duckdb.DuckDBPyConnection] = {}
_database_locks: Dict[str, Lock] = {}

# Track snapshot copies for cleanup
_snapshot_paths: Dict[str, str] = {}  # db_key -> snapshot_path

# Directory for snapshot copies
_SNAPSHOT_DIR = os.path.join(tempfile.gettempdir(), "lars_db_snapshots")


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

    databases = []

    # Always include memory/default options
    databases.append({
        "name": "memory",
        "type": "memory",
        "path": None,
        "size_mb": None,
    })

    # Scan session_dbs directory for persistent databases
    config = get_config()
    session_db_dir = os.path.join(config.root_dir, 'session_dbs')

    if os.path.exists(session_db_dir):
        for filename in os.listdir(session_db_dir):
            if filename.endswith('.duckdb'):
                db_name = filename[:-7]  # Remove .duckdb extension
                db_path = os.path.join(session_db_dir, filename)

                # Skip internal/temp/ephemeral databases
                if (db_name.startswith('http_api_') or
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

    # Sort by name (memory first, then alphabetical)
    databases.sort(key=lambda d: (0 if d["type"] == "memory" else 1, d["name"]))

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
        log.info(f"[database_manager] Opened persistent database: {db_path}")
        return conn, False
    except duckdb.IOException as e:
        if "lock" not in str(e).lower():
            raise  # Not a lock error, re-raise

        log.warning(f"[database_manager] Database {db_key} is locked, trying read-only mode")

    # Strategy 2: Try read-only mode
    try:
        conn = duckdb.connect(db_path, read_only=True)
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
    """
    # Skip if already initialized (for persistent DBs)
    if not is_memory and db_key in _initialized_databases:
        log.info(f"[database_manager] Database {db_key} already initialized, skipping")
        return

    log.info(f"[database_manager] Initializing database: {db_key}")

    # Phase 1: Minimal setup (UDFs)
    _setup_minimal(conn)

    # Phase 2: Deferred setup (auto-attach, metadata tables)
    _setup_deferred(conn, db_key)

    # Mark as initialized
    if not is_memory:
        _initialized_databases.add(db_key)

    log.info(f"[database_manager] Database {db_key} initialization complete")


def _setup_minimal(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Minimal setup - register UDFs and basic config.

    This is the fast path that must complete before responding to clients.
    """
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
