"""
Result Store - Fingerprint-based query result persistence.

Stores query results as parquet files organized by query fingerprint:
    $LARS_ROOT/data/results/{query_fingerprint}/{caller_id}.parquet

This enables:
- Historical query results grouped by "same" query shape
- Deterministic file paths (derivable from sql_query_log)
- UI integration for viewing past runs in /sql-trail
- No metadata storage needed — sql_query_log IS the index

Usage:
    from lars.result_store import store_result, get_result_path, load_result
    
    # Store a result
    path = store_result(df, query_fingerprint, caller_id)
    
    # Get path (without loading)
    path = get_result_path(query_fingerprint, caller_id)
    
    # Load a result
    df = load_result(query_fingerprint, caller_id)
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import pandas as pd

log = logging.getLogger(__name__)

# Default root for result storage
_results_root: Optional[Path] = None


def _get_results_root() -> Path:
    """Get the results storage root directory."""
    global _results_root
    
    if _results_root is not None:
        return _results_root
    
    # Try to get from lars_db
    try:
        from .lars_db import get_lars_db
        db = get_lars_db()
        _results_root = db.root / "results"
    except Exception:
        # Fallback to default
        lars_root = os.environ.get("LARS_ROOT", os.path.expanduser("~/.lars"))
        _results_root = Path(lars_root) / "data" / "results"
    
    return _results_root


def get_result_path(query_fingerprint: str, caller_id: str) -> Path:
    """
    Get the deterministic path for a query result.
    
    Args:
        query_fingerprint: AST-normalized query hash (from sql_query_log)
        caller_id: Unique caller identifier (e.g., 'sql-clever-fox-abc123')
        
    Returns:
        Path to the parquet file (may not exist yet)
    """
    root = _get_results_root()
    # Sanitize caller_id for filename (replace unsafe chars)
    safe_caller = caller_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    return root / query_fingerprint / f"{safe_caller}.parquet"


def store_result(
    df: pd.DataFrame,
    query_fingerprint: str,
    caller_id: str,
    query_preview: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Store a query result as a parquet file.
    
    Args:
        df: The pandas DataFrame to store
        query_fingerprint: AST-normalized query hash
        caller_id: Unique caller identifier
        query_preview: Optional query text for logging
        
    Returns:
        Dict with storage info:
        {
            'stored_in': 'parquet',
            'query_fingerprint': str,
            'caller_id': str,
            'path': str,
            'row_count': int,
            'column_count': int
        }
        Returns None if storage fails or df is empty.
    """
    if df is None or len(df) == 0:
        return None
    
    # Skip very large results (configurable)
    max_rows = int(os.environ.get("LARS_RESULT_MAX_ROWS", "100000"))
    if len(df) > max_rows:
        log.debug(f"[ResultStore] Skipping large result: {len(df)} rows > {max_rows} max")
        return None
    
    try:
        path = get_result_path(query_fingerprint, caller_id)
        
        # Create directory if needed
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write parquet with snappy compression
        df.to_parquet(path, compression="snappy", index=False)
        
        log.debug(f"[ResultStore] Stored {len(df)} rows to {path}")
        
        return {
            'stored_in': 'parquet',
            'query_fingerprint': query_fingerprint,
            'caller_id': caller_id,
            'path': str(path),
            'row_count': len(df),
            'column_count': len(df.columns),
        }
        
    except Exception as e:
        log.warning(f"[ResultStore] Failed to store result: {e}")
        return None


def load_result(query_fingerprint: str, caller_id: str) -> Optional[pd.DataFrame]:
    """
    Load a stored query result.
    
    Args:
        query_fingerprint: AST-normalized query hash
        caller_id: Unique caller identifier
        
    Returns:
        DataFrame or None if not found
    """
    path = get_result_path(query_fingerprint, caller_id)
    
    if not path.exists():
        return None
    
    try:
        return pd.read_parquet(path)
    except Exception as e:
        log.warning(f"[ResultStore] Failed to load {path}: {e}")
        return None


def result_exists(query_fingerprint: str, caller_id: str) -> bool:
    """Check if a result file exists."""
    return get_result_path(query_fingerprint, caller_id).exists()


def list_results_for_fingerprint(query_fingerprint: str) -> list[Dict[str, Any]]:
    """
    List all stored results for a query fingerprint.
    
    Returns list of dicts with caller_id and file info.
    """
    root = _get_results_root()
    fp_dir = root / query_fingerprint
    
    if not fp_dir.exists():
        return []
    
    results = []
    for f in fp_dir.glob("*.parquet"):
        try:
            stat = f.stat()
            results.append({
                'caller_id': f.stem,  # filename without .parquet
                'path': str(f),
                'size_bytes': stat.st_size,
                'created_at': stat.st_mtime,
            })
        except Exception:
            continue
    
    return sorted(results, key=lambda x: x['created_at'], reverse=True)


def get_fingerprint_stats() -> Dict[str, Any]:
    """Get statistics about stored results."""
    root = _get_results_root()
    
    if not root.exists():
        return {'fingerprints': 0, 'total_files': 0, 'total_size_bytes': 0}
    
    fingerprints = 0
    total_files = 0
    total_size = 0
    
    for fp_dir in root.iterdir():
        if fp_dir.is_dir():
            fingerprints += 1
            for f in fp_dir.glob("*.parquet"):
                total_files += 1
                try:
                    total_size += f.stat().st_size
                except Exception:
                    pass
    
    return {
        'fingerprints': fingerprints,
        'total_files': total_files,
        'total_size_bytes': total_size,
        'total_size_mb': round(total_size / (1024 * 1024), 2),
    }


def cleanup_old_results(max_age_hours: int = 24, dry_run: bool = False) -> Dict[str, Any]:
    """
    Clean up result files older than max_age_hours.
    
    Args:
        max_age_hours: Delete files older than this (default 24h)
        dry_run: If True, don't actually delete, just report
        
    Returns:
        Dict with cleanup stats
    """
    import time
    
    root = _get_results_root()
    if not root.exists():
        return {'deleted': 0, 'freed_bytes': 0}
    
    cutoff = time.time() - (max_age_hours * 3600)
    deleted = 0
    freed = 0
    
    for fp_dir in root.iterdir():
        if not fp_dir.is_dir():
            continue
            
        for f in fp_dir.glob("*.parquet"):
            try:
                stat = f.stat()
                if stat.st_mtime < cutoff:
                    if not dry_run:
                        f.unlink()
                    deleted += 1
                    freed += stat.st_size
            except Exception:
                continue
        
        # Remove empty fingerprint directories
        if not dry_run:
            try:
                if fp_dir.exists() and not any(fp_dir.iterdir()):
                    fp_dir.rmdir()
            except Exception:
                pass
    
    return {
        'deleted': deleted,
        'freed_bytes': freed,
        'freed_mb': round(freed / (1024 * 1024), 2),
        'dry_run': dry_run,
    }
