"""
Scratch DB - Ephemeral SQLite attached to DuckDB as 'scratch' schema.

Location: /dev/shm/lars_scratch.db (RAM-backed tmpfs)
Mode: WAL (concurrent reads, serialized writes)

Auto-attached on every DuckDB connection, provides:
- scratch.kv - Key-value store for @param_get/@param_set
- Any user-created tables for temp storage

Usage in SQL:
    -- Read params (works from DuckDB)
    SELECT value FROM scratch.kv WHERE user_id = '...' AND key = 'cat';
    
    -- Write params: use @param_set cascade or direct SQLite
    -- (DuckDB's SQLite extension doesn't support INSERT OR REPLACE)
    
    -- Create temp tables (works from DuckDB)
    CREATE TABLE scratch.my_cache AS SELECT * FROM big_table;
    INSERT INTO scratch.my_cache VALUES (...);  -- Regular INSERT works
    
Note: Data survives process restarts but NOT system reboots (tmpfs).
"""

import sqlite3
import threading
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Path to the scratch database (RAM-backed via tmpfs)
SCRATCH_DB_PATH = "/dev/shm/lars_scratch.db"

# SQL to initialize the scratch database
# Note: No DEFAULT for updated_at - DuckDB doesn't understand SQLite's unixepoch()
# when pushing down inserts. The Python code handles timestamps.
SCRATCH_INIT_SQL = """
-- Key-value table for param store (@param_get/@param_set)
CREATE TABLE IF NOT EXISTS kv (
    user_id TEXT NOT NULL,
    database TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at REAL,
    PRIMARY KEY (user_id, database, key)
);

-- Index for fast lookups (SQLite uses the PK index, but this helps with partial matches)
CREATE INDEX IF NOT EXISTS idx_kv_user_db ON kv(user_id, database);

-- Caller context table for cross-thread SQL query tracking
CREATE TABLE IF NOT EXISTS caller_context (
    connection_id TEXT PRIMARY KEY,
    caller_id TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    created_at REAL
);

-- Index for caller_id lookups (debugging/analytics)
CREATE INDEX IF NOT EXISTS idx_caller_context_caller ON caller_context(caller_id);
"""

_initialized = False
_init_lock = threading.Lock()


def ensure_scratch_db() -> str:
    """
    Ensure the scratch database exists and is initialized.
    
    Returns:
        Path to the scratch database file
    """
    global _initialized
    
    if _initialized:
        return SCRATCH_DB_PATH
    
    with _init_lock:
        if _initialized:
            return SCRATCH_DB_PATH
        
        try:
            # Create/open the database with timeout for lock contention
            conn = sqlite3.connect(SCRATCH_DB_PATH, timeout=5.0)
            
            # Enable WAL mode for concurrent access
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            # Wait up to 5 seconds if locked (unlikely with WAL, but defensive)
            conn.execute("PRAGMA busy_timeout=5000")
            
            # Initialize tables
            conn.executescript(SCRATCH_INIT_SQL)
            conn.commit()
            conn.close()
            
            _initialized = True
            log.debug(f"[ScratchDB] Initialized at {SCRATCH_DB_PATH}")
            
        except Exception as e:
            log.warning(f"[ScratchDB] Failed to initialize: {e}")
            # Don't raise - let the system continue without scratch
    
    return SCRATCH_DB_PATH


def attach_scratch_db(duckdb_conn) -> bool:
    """
    Attach the scratch database to a DuckDB connection.
    
    Args:
        duckdb_conn: DuckDB connection object
        
    Returns:
        True if successfully attached, False otherwise
    """
    try:
        # Ensure scratch DB exists
        db_path = ensure_scratch_db()
        
        # Check if already attached
        try:
            duckdb_conn.execute("SELECT 1 FROM scratch.kv LIMIT 0")
            return True  # Already attached
        except Exception:
            pass  # Not attached yet
        
        # Attach SQLite database as 'scratch' schema
        duckdb_conn.execute(f"ATTACH '{db_path}' AS scratch (TYPE SQLITE)")
        log.debug("[ScratchDB] Attached to DuckDB connection")
        return True
        
    except Exception as e:
        log.warning(f"[ScratchDB] Failed to attach: {e}")
        return False


def get_scratch_connection() -> sqlite3.Connection:
    """
    Get a direct SQLite connection to the scratch database.
    
    Use this for operations that need direct SQLite access
    (e.g., from param_store when not going through DuckDB).
    
    Returns:
        SQLite connection with WAL mode and busy timeout
    """
    ensure_scratch_db()
    conn = sqlite3.connect(SCRATCH_DB_PATH, timeout=5.0, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s on lock
    conn.row_factory = sqlite3.Row  # Return rows as dicts
    return conn


# Singleton connection for param store operations
_param_conn: sqlite3.Connection | None = None
_param_conn_lock = threading.Lock()


def get_param_connection() -> sqlite3.Connection:
    """
    Get a shared SQLite connection for param store operations.
    
    This connection is reused across calls for efficiency.
    Thread-safe via SQLite's internal locking + WAL mode.
    """
    global _param_conn
    
    if _param_conn is not None:
        return _param_conn
    
    with _param_conn_lock:
        if _param_conn is None:
            _param_conn = get_scratch_connection()
    
    return _param_conn
