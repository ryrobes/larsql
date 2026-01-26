"""
Shared Parquet Tables - Lock-free persistence for DuckDB sessions

Provides cross-session table visibility using Parquet files and views.
Unlike DuckLake (which uses SQLite catalog with locking issues), this approach:
- Uses Parquet files for data (immutable, no locks)
- Atomic writes via temp file + rename
- Views in each session pointing to shared files
- Directory-based discovery (no central catalog to lock)

Tables in 'shared' schema are backed by Parquet files, enabling:
- Multiple concurrent readers (no locks)
- Atomic writes (temp file + rename)
- Cross-session visibility
- Simple cleanup (just delete files)

Usage in SQL:
    -- Create a shared table (writes parquet, creates view)
    CREATE TABLE shared.my_analysis AS SELECT * FROM source_data;

    -- Query from any session (view auto-created on sync)
    SELECT * FROM shared.my_analysis;

    -- List shared tables
    SELECT * FROM shared_tables();

Configuration:
    LARS_SHARED_TABLES_DIR: Path to shared tables directory (default: {root}/shared_tables/)
    LARS_SHARED_TABLES_ENABLED: Set to '0' to disable (default: enabled)
"""

import os
import time
import logging
from pathlib import Path
from typing import Optional
from threading import Lock

logger = logging.getLogger(__name__)

# Module-level lock for write operations
_write_lock = Lock()


def get_shared_tables_dir() -> Path:
    """
    Get the shared tables directory.

    Returns:
        Path to shared tables directory
    """
    # Allow override via environment
    custom_dir = os.environ.get('LARS_SHARED_TABLES_DIR')
    if custom_dir:
        return Path(custom_dir)

    from ..config import get_config
    config = get_config()
    return Path(config.root_dir) / "shared_tables"


def is_shared_tables_enabled() -> bool:
    """Check if shared tables are enabled."""
    return os.environ.get('LARS_SHARED_TABLES_ENABLED', '1') != '0'


def ensure_shared_dirs() -> Path:
    """
    Ensure shared tables directories exist.

    Returns:
        Path to shared tables directory
    """
    shared_dir = get_shared_tables_dir()

    # Create default subdirectories
    for subdir in ['staging', 'results', 'user']:
        (shared_dir / subdir).mkdir(parents=True, exist_ok=True)

    return shared_dir


def sync_shared_views(connection, schema: str = 'shared') -> int:
    """
    Discover parquet files and create/update views.

    Call on session start to make all shared tables visible.
    Can also be called periodically to pick up new tables from other sessions.

    Args:
        connection: DuckDB connection
        schema: Schema name for views (default: 'shared')

    Returns:
        Number of views created/updated
    """
    if not is_shared_tables_enabled():
        logger.debug("Shared tables disabled via LARS_SHARED_TABLES_ENABLED=0")
        return 0

    shared_dir = get_shared_tables_dir()
    if not shared_dir.exists():
        return 0

    try:
        # Ensure schema exists
        connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    except Exception as e:
        if "already exists" not in str(e).lower():
            logger.warning(f"[shared_parquet] Could not create schema {schema}: {e}")
            return 0

    count = 0

    # Scan all subdirectories for parquet files
    for subdir in shared_dir.iterdir():
        if not subdir.is_dir() or subdir.name.startswith('.'):
            continue

        subdir_name = subdir.name.lower()
        for parquet_file in subdir.glob("*.parquet"):
            try:
                # View naming convention:
                # - staging/foo.parquet -> shared.foo (simple name, staging is default)
                # - results/foo.parquet -> shared.results_foo (prefixed)
                # - user/foo.parquet -> shared.user_foo (prefixed)
                if subdir_name == 'staging':
                    view_name = parquet_file.stem
                else:
                    view_name = f"{subdir_name}_{parquet_file.stem}"

                # Drop any existing table first to avoid type conflicts
                # (CREATE OR REPLACE VIEW fails if a TABLE with same name exists)
                try:
                    connection.execute(f"DROP TABLE IF EXISTS {schema}.{view_name}")
                except Exception:
                    pass

                # Create view pointing to parquet file
                # Use read_parquet for direct file access
                view_sql = f"""
                    CREATE OR REPLACE VIEW {schema}.{view_name} AS
                    SELECT * FROM read_parquet('{parquet_file}')
                """
                connection.execute(view_sql)
                count += 1
                logger.debug(f"[shared_parquet] Created view: {schema}.{view_name}")

            except Exception as e:
                logger.warning(f"[shared_parquet] Failed to create view for {parquet_file}: {e}")

    if count > 0:
        logger.info(f"[shared_parquet] Synced {count} shared table(s)")

    return count


def write_shared_table(
    connection,
    name: str,
    query: str,
    subdir: str = 'staging',
    schema: str = 'shared'
) -> Optional[str]:
    """
    Write query results to a shared parquet file.

    Uses atomic write (temp file + rename) to prevent corruption.
    Creates a view in the current connection after writing.

    Args:
        connection: DuckDB connection
        name: Table name (alphanumeric + underscores only)
        query: SELECT query to materialize
        subdir: Subdirectory (staging, results, user)
        schema: Schema for the view

    Returns:
        Full path to parquet file, or None on failure
    """
    if not is_shared_tables_enabled():
        logger.warning("[shared_parquet] Shared tables disabled")
        return None

    # Sanitize name
    safe_name = "".join(c for c in name if c.isalnum() or c == '_')
    if not safe_name:
        logger.error(f"[shared_parquet] Invalid table name: {name}")
        return None

    shared_dir = ensure_shared_dirs()
    target_dir = shared_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = target_dir / f"{safe_name}.parquet"
    temp_path = target_dir / f".{safe_name}.{time.time_ns()}.parquet.tmp"

    try:
        with _write_lock:
            # Write to temp file with ZSTD compression
            copy_sql = f"COPY ({query}) TO '{temp_path}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            connection.execute(copy_sql)

            # Atomic rename (POSIX guarantees atomicity for same-filesystem rename)
            temp_path.rename(parquet_path)

        # Create view in this connection
        view_name = f"{subdir}_{safe_name}"
        connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        connection.execute(f"""
            CREATE OR REPLACE VIEW {schema}.{view_name} AS
            SELECT * FROM read_parquet('{parquet_path}')
        """)

        logger.info(f"[shared_parquet] Created shared table: {schema}.{view_name}")
        return str(parquet_path)

    except Exception as e:
        logger.error(f"[shared_parquet] Failed to write {name}: {e}")
        # Clean up temp file if it exists
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
        return None


def write_shared_table_with_view_name(
    connection,
    file_name: str,
    view_name: str,
    query: str,
    subdir: str = 'staging',
    schema: str = 'shared'
) -> Optional[str]:
    """
    Write query results to a shared parquet file with custom view name.

    Like write_shared_table but allows specifying a different view name
    than the file name. This enables cleaner SQL syntax:
        CREATE TABLE shared.sales AS SELECT ...  -> view: shared.sales

    Args:
        connection: DuckDB connection
        file_name: Name for the parquet file (alphanumeric + underscores only)
        view_name: Name for the SQL view (can differ from file_name)
        query: SELECT query to materialize
        subdir: Subdirectory (staging, results, user)
        schema: Schema for the view

    Returns:
        Full path to parquet file, or None on failure
    """
    if not is_shared_tables_enabled():
        logger.warning("[shared_parquet] Shared tables disabled")
        return None

    # Sanitize names
    safe_file_name = "".join(c for c in file_name if c.isalnum() or c == '_')
    safe_view_name = "".join(c for c in view_name if c.isalnum() or c == '_')
    if not safe_file_name:
        logger.error(f"[shared_parquet] Invalid file name: {file_name}")
        return None
    if not safe_view_name:
        logger.error(f"[shared_parquet] Invalid view name: {view_name}")
        return None

    shared_dir = ensure_shared_dirs()
    target_dir = shared_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = target_dir / f"{safe_file_name}.parquet"
    temp_path = target_dir / f".{safe_file_name}.{time.time_ns()}.parquet.tmp"

    try:
        with _write_lock:
            # Write to temp file with ZSTD compression
            copy_sql = f"COPY ({query}) TO '{temp_path}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            connection.execute(copy_sql)

            # Atomic rename (POSIX guarantees atomicity for same-filesystem rename)
            temp_path.rename(parquet_path)

        # Create view in this connection with the custom view name
        # Drop any existing table/view first to avoid type conflicts
        connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        try:
            connection.execute(f"DROP VIEW IF EXISTS {schema}.{safe_view_name}")
        except Exception:
            pass
        try:
            connection.execute(f"DROP TABLE IF EXISTS {schema}.{safe_view_name}")
        except Exception:
            pass
        connection.execute(f"""
            CREATE OR REPLACE VIEW {schema}.{safe_view_name} AS
            SELECT * FROM read_parquet('{parquet_path}')
        """)

        logger.info(f"[shared_parquet] Created shared table: {schema}.{safe_view_name} -> {parquet_path}")
        return str(parquet_path)

    except Exception as e:
        logger.error(f"[shared_parquet] Failed to write {file_name}: {e}")
        # Clean up temp file if it exists
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
        return None


def drop_shared_table(name: str, subdir: str = 'staging') -> bool:
    """
    Delete a shared parquet file.

    Note: Views in other sessions will fail until they sync again.

    Args:
        name: Table name
        subdir: Subdirectory

    Returns:
        True if deleted, False otherwise
    """
    shared_dir = get_shared_tables_dir()
    parquet_path = shared_dir / subdir / f"{name}.parquet"

    if parquet_path.exists():
        try:
            parquet_path.unlink()
            logger.info(f"[shared_parquet] Dropped shared table: {subdir}/{name}")
            return True
        except Exception as e:
            logger.error(f"[shared_parquet] Failed to drop {name}: {e}")
            return False
    return False


def list_shared_tables() -> list[dict]:
    """
    List all shared tables with metadata.

    Returns:
        List of dicts with name, subdir, size_bytes, modified, path
    """
    shared_dir = get_shared_tables_dir()
    if not shared_dir.exists():
        return []

    tables = []
    for parquet_file in shared_dir.rglob("*.parquet"):
        # Skip temp files
        if parquet_file.name.startswith('.'):
            continue

        try:
            stat = parquet_file.stat()
            rel_path = parquet_file.relative_to(shared_dir)
            subdir = rel_path.parent.as_posix() if rel_path.parent.as_posix() != '.' else 'root'

            tables.append({
                "name": parquet_file.stem,
                "subdir": subdir,
                "full_name": f"shared.{subdir}_{parquet_file.stem}",
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
                "path": str(parquet_file),
            })
        except Exception as e:
            logger.warning(f"[shared_parquet] Could not stat {parquet_file}: {e}")

    return sorted(tables, key=lambda t: (t['subdir'], t['name']))


def cleanup_old_tables(days_old: int = 7, subdir: str = 'staging') -> int:
    """
    Clean up shared tables older than specified days.

    Args:
        days_old: Delete files older than this many days
        subdir: Subdirectory to clean (default: staging)

    Returns:
        Number of files deleted
    """
    import time

    shared_dir = get_shared_tables_dir()
    target_dir = shared_dir / subdir

    if not target_dir.exists():
        return 0

    cutoff = time.time() - (days_old * 24 * 60 * 60)
    deleted = 0

    for parquet_file in target_dir.glob("*.parquet"):
        try:
            if parquet_file.stat().st_mtime < cutoff:
                parquet_file.unlink()
                deleted += 1
                logger.info(f"[shared_parquet] Cleaned up old table: {parquet_file.name}")
        except Exception as e:
            logger.warning(f"[shared_parquet] Could not delete {parquet_file}: {e}")

    return deleted


def register_shared_tables_udf(connection) -> None:
    """
    Register a table-valued function to list shared tables from SQL.

    Usage:
        SELECT * FROM shared_tables();
    """
    try:
        # Create a Python UDF that returns shared tables info
        def _shared_tables_udf():
            import pandas as pd
            tables = list_shared_tables()
            if not tables:
                return pd.DataFrame(columns=['name', 'subdir', 'full_name', 'size_bytes', 'modified_ts'])
            return pd.DataFrame([
                {
                    'name': t['name'],
                    'subdir': t['subdir'],
                    'full_name': t['full_name'],
                    'size_bytes': t['size_bytes'],
                    'modified_ts': t['modified'],
                }
                for t in tables
            ])

        connection.create_function('shared_tables', _shared_tables_udf, [], 'TABLE')
        logger.debug("[shared_parquet] Registered shared_tables() UDF")
    except Exception as e:
        logger.debug(f"[shared_parquet] Could not register shared_tables UDF: {e}")


def resolve_shared_table(
    connection,
    table_name: str,
    schema: str = 'shared'
) -> bool:
    """
    Try to resolve a missing table from shared parquet files.

    Call this when a query fails with "table not found" for a shared.* table.
    Useful for lazy view creation instead of syncing all views upfront.

    Args:
        connection: DuckDB connection
        table_name: Table name (e.g., 'staging_my_analysis' or just 'my_analysis')
        schema: Schema name

    Returns:
        True if table was resolved and view created, False otherwise
    """
    shared_dir = get_shared_tables_dir()
    if not shared_dir.exists():
        return False

    # Try to find matching parquet file
    # First, check if table_name has subdir prefix (e.g., staging_foo)
    for subdir in ['staging', 'results', 'user']:
        prefix = f"{subdir}_"
        if table_name.startswith(prefix):
            # Table name includes subdir prefix
            actual_name = table_name[len(prefix):]
            parquet_path = shared_dir / subdir / f"{actual_name}.parquet"
            if parquet_path.exists():
                try:
                    connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                    connection.execute(f"""
                        CREATE OR REPLACE VIEW {schema}.{table_name} AS
                        SELECT * FROM read_parquet('{parquet_path}')
                    """)
                    logger.info(f"[shared_parquet] Resolved: {schema}.{table_name}")
                    return True
                except Exception as e:
                    logger.warning(f"[shared_parquet] Failed to resolve {table_name}: {e}")
                    return False

    # Try without prefix - search all subdirs
    for subdir in ['staging', 'results', 'user']:
        parquet_path = shared_dir / subdir / f"{table_name}.parquet"
        if parquet_path.exists():
            view_name = f"{subdir}_{table_name}"
            try:
                connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                connection.execute(f"""
                    CREATE OR REPLACE VIEW {schema}.{view_name} AS
                    SELECT * FROM read_parquet('{parquet_path}')
                """)
                logger.info(f"[shared_parquet] Resolved: {schema}.{view_name}")
                return True
            except Exception as e:
                logger.warning(f"[shared_parquet] Failed to resolve {table_name}: {e}")
                return False

    return False


def attach_shared_tables(connection) -> bool:
    """
    Set up shared tables for a DuckDB connection.

    This is the main entry point - call this when initializing a session.
    It syncs views and registers helper UDFs.

    Args:
        connection: DuckDB connection

    Returns:
        True if setup succeeded, False otherwise
    """
    if not is_shared_tables_enabled():
        logger.debug("Shared tables disabled via LARS_SHARED_TABLES_ENABLED=0")
        return False

    try:
        # Ensure directories exist
        ensure_shared_dirs()

        # Sync all existing shared tables as views
        count = sync_shared_views(connection)

        # Register helper UDF
        register_shared_tables_udf(connection)

        logger.info(f"[shared_parquet] Attached shared tables ({count} tables synced)")
        return True

    except Exception as e:
        logger.warning(f"[shared_parquet] Failed to attach: {e}")
        return False
