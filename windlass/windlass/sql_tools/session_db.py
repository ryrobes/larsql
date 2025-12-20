"""
Session-scoped DuckDB instances for data cascade temp tables.

Each cascade execution gets its own DuckDB instance where temp tables
persist across phases. Tables are named _<phase_name> by convention.
"""

import os
import duckdb
import atexit
from typing import Dict, Optional, List
from threading import Lock


# Global registry of session databases
_session_dbs: Dict[str, duckdb.DuckDBPyConnection] = {}
_session_db_lock = Lock()

# Directory for session database files
SESSION_DB_DIR = "/tmp/windlass_sessions"


def get_session_db(session_id: str) -> duckdb.DuckDBPyConnection:
    """
    Get or create a DuckDB connection for the given session.

    The database file persists at /tmp/windlass_sessions/<session_id>.duckdb
    and contains all temp tables created during the cascade execution.

    Args:
        session_id: Unique session identifier

    Returns:
        DuckDB connection for this session
    """
    with _session_db_lock:
        if session_id not in _session_dbs:
            # Ensure directory exists
            os.makedirs(SESSION_DB_DIR, exist_ok=True)

            # Sanitize session_id for filename (replace problematic chars)
            safe_session_id = session_id.replace("/", "_").replace("\\", "_")

            # Create or open session database
            db_path = os.path.join(SESSION_DB_DIR, f"{safe_session_id}.duckdb")
            conn = duckdb.connect(db_path)

            # Configure for our use case
            conn.execute("SET threads TO 4")

            _session_dbs[session_id] = conn

        return _session_dbs[session_id]


def cleanup_session_db(session_id: str, delete_file: bool = True):
    """
    Clean up a session's DuckDB resources.

    Called when a cascade completes to free resources.

    Args:
        session_id: Session to clean up
        delete_file: If True, delete the database file
    """
    with _session_db_lock:
        if session_id in _session_dbs:
            conn = _session_dbs.pop(session_id)
            try:
                conn.close()
            except Exception:
                pass

            if delete_file:
                # Sanitize session_id for filename
                safe_session_id = session_id.replace("/", "_").replace("\\", "_")
                db_path = os.path.join(SESSION_DB_DIR, f"{safe_session_id}.duckdb")
                try:
                    if os.path.exists(db_path):
                        os.remove(db_path)
                    # Also remove WAL file if present
                    wal_path = db_path + ".wal"
                    if os.path.exists(wal_path):
                        os.remove(wal_path)
                except Exception:
                    pass


def list_session_tables(session_id: str) -> List[str]:
    """
    List all tables in a session's DuckDB.

    Useful for debugging and introspection.

    Args:
        session_id: Session to inspect

    Returns:
        List of table names
    """
    try:
        conn = get_session_db(session_id)
        result = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        return [row[0] for row in result]
    except Exception:
        return []


def get_session_table(session_id: str, table_name: str):
    """
    Get a DataFrame from a session temp table.

    Args:
        session_id: Session ID
        table_name: Table name (with or without _ prefix)

    Returns:
        pandas DataFrame
    """
    conn = get_session_db(session_id)
    # Normalize table name
    if not table_name.startswith('_'):
        table_name = f"_{table_name}"
    return conn.execute(f"SELECT * FROM {table_name}").fetchdf()


def session_db_exists(session_id: str) -> bool:
    """
    Check if a session database exists (in memory or on disk).

    Args:
        session_id: Session to check

    Returns:
        True if session database exists
    """
    with _session_db_lock:
        if session_id in _session_dbs:
            return True

        safe_session_id = session_id.replace("/", "_").replace("\\", "_")
        db_path = os.path.join(SESSION_DB_DIR, f"{safe_session_id}.duckdb")
        return os.path.exists(db_path)


# Cleanup on process exit
@atexit.register
def _cleanup_all_sessions():
    """Clean up all session databases on process exit."""
    with _session_db_lock:
        for session_id in list(_session_dbs.keys()):
            try:
                conn = _session_dbs.pop(session_id)
                conn.close()
            except Exception:
                pass
