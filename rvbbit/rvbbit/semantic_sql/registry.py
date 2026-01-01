"""
SQL Function Registry - discovers and manages cascade-based SQL functions.

Scans _builtin/ and traits/ directories for cascades with sql_function config,
and provides execution interface for SQL queries.
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple
from threading import Lock
import logging

log = logging.getLogger(__name__)

# Global registry
_registry: Dict[str, "SQLFunctionEntry"] = {}
_registry_lock = Lock()
_initialized = False

# Cache for function results
_result_cache: Dict[str, Any] = {}
_cache_lock = Lock()


class SQLFunctionEntry:
    """An entry in the SQL function registry."""

    def __init__(
        self,
        name: str,
        cascade_path: str,
        cascade_id: str,
        config: Dict[str, Any],
        sql_function: Dict[str, Any],
    ):
        self.name = name
        self.cascade_path = cascade_path
        self.cascade_id = cascade_id
        self.config = config
        self.sql_function = sql_function

    @property
    def shape(self) -> str:
        """Get function shape: SCALAR, ROW, or AGGREGATE."""
        return self.sql_function.get("shape", "SCALAR")

    @property
    def returns(self) -> str:
        """Get return type."""
        return self.sql_function.get("returns", "VARCHAR")

    @property
    def args(self) -> List[Dict[str, Any]]:
        """Get argument definitions."""
        return self.sql_function.get("args", [])

    @property
    def description(self) -> Optional[str]:
        """Get function description."""
        return self.sql_function.get("description") or self.config.get("description")

    @property
    def operators(self) -> List[str]:
        """Get operator syntax patterns."""
        return self.sql_function.get("operators", [])

    @property
    def cache_enabled(self) -> bool:
        """Check if caching is enabled."""
        return self.sql_function.get("cache", True)

    @property
    def cache_ttl(self) -> Optional[int]:
        """Get cache TTL in seconds."""
        return self.sql_function.get("cache_ttl")

    def __repr__(self):
        return f"SQLFunctionEntry(name={self.name}, shape={self.shape}, cascade={self.cascade_id})"


def _load_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """Load a YAML file, returning None on error."""
    try:
        import yaml
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        log.warning(f"Failed to load {path}: {e}")
        return None


def _scan_directory(directory: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    """Scan a directory for cascade files with sql_function config."""
    results = []

    if not directory.exists():
        return results

    for path in directory.glob("**/*.yaml"):
        config = _load_yaml(path)
        if config and "sql_function" in config and config.get("cascade_id"):
            results.append((path, config))

    for path in directory.glob("**/*.cascade.yaml"):
        if path in [p for p, _ in results]:
            continue
        config = _load_yaml(path)
        if config and "sql_function" in config and config.get("cascade_id"):
            results.append((path, config))

    return results


def _get_builtin_dir() -> Path:
    """Get the _builtin directory path."""
    return Path(__file__).parent / "_builtin"


def _get_traits_dir() -> Path:
    """Get the traits directory path (from config or default)."""
    try:
        from ..config import get_config
        config = get_config()
        return Path(config.root_dir) / "traits"
    except Exception:
        return Path.cwd() / "traits"


def _get_cascades_dir() -> Path:
    """Get the cascades directory path."""
    try:
        from ..config import get_config
        config = get_config()
        return Path(config.root_dir) / "cascades"
    except Exception:
        return Path.cwd() / "cascades"


def initialize_registry(force: bool = False) -> None:
    """
    Initialize the SQL function registry by scanning for cascade files.

    Args:
        force: If True, re-scan even if already initialized
    """
    global _initialized, _registry

    with _registry_lock:
        if _initialized and not force:
            return

        _registry.clear()

        # Scan built-in directory first (lowest priority)
        builtin_dir = _get_builtin_dir()
        log.info(f"[sql_registry] Scanning built-ins: {builtin_dir}")
        for path, config in _scan_directory(builtin_dir):
            sql_fn = config["sql_function"]
            name = sql_fn.get("name") or config["cascade_id"]

            if not sql_fn.get("enabled", True):
                continue

            _registry[name] = SQLFunctionEntry(
                name=name,
                cascade_path=str(path),
                cascade_id=config["cascade_id"],
                config=config,
                sql_function=sql_fn,
            )
            log.info(f"[sql_registry] Registered built-in: {name}")

        # Scan traits directory (medium priority - overwrites built-ins)
        traits_dir = _get_traits_dir()
        if traits_dir.exists():
            log.info(f"[sql_registry] Scanning traits: {traits_dir}")
            for path, config in _scan_directory(traits_dir):
                sql_fn = config["sql_function"]
                name = sql_fn.get("name") or config["cascade_id"]

                if not sql_fn.get("enabled", True):
                    continue

                _registry[name] = SQLFunctionEntry(
                    name=name,
                    cascade_path=str(path),
                    cascade_id=config["cascade_id"],
                    config=config,
                    sql_function=sql_fn,
                )
                log.info(f"[sql_registry] Registered from traits: {name}")

        # Scan cascades directory (highest priority)
        cascades_dir = _get_cascades_dir()
        if cascades_dir.exists():
            log.info(f"[sql_registry] Scanning cascades: {cascades_dir}")
            for path, config in _scan_directory(cascades_dir):
                sql_fn = config["sql_function"]
                name = sql_fn.get("name") or config["cascade_id"]

                if not sql_fn.get("enabled", True):
                    continue

                _registry[name] = SQLFunctionEntry(
                    name=name,
                    cascade_path=str(path),
                    cascade_id=config["cascade_id"],
                    config=config,
                    sql_function=sql_fn,
                )
                log.info(f"[sql_registry] Registered from cascades: {name}")

        _initialized = True
        log.info(f"[sql_registry] Initialized with {len(_registry)} functions")


def get_sql_function_registry() -> Dict[str, SQLFunctionEntry]:
    """Get the full registry of SQL functions."""
    initialize_registry()
    return _registry.copy()


def register_sql_function(entry: SQLFunctionEntry) -> None:
    """Manually register a SQL function (for dynamic registration)."""
    with _registry_lock:
        _registry[entry.name] = entry
        log.info(f"[sql_registry] Dynamically registered: {entry.name}")


def get_sql_function(name: str) -> Optional[SQLFunctionEntry]:
    """Get a SQL function by name."""
    initialize_registry()
    return _registry.get(name)


def list_sql_functions() -> List[str]:
    """List all registered SQL function names."""
    initialize_registry()
    return list(_registry.keys())


def _make_cache_key(name: str, args: Dict[str, Any]) -> str:
    """Create a cache key from function name and arguments."""
    args_json = json.dumps(args, sort_keys=True, default=str)
    key_data = f"{name}:{args_json}"
    return hashlib.md5(key_data.encode()).hexdigest()


def get_cached_result(name: str, args: Dict[str, Any]) -> Tuple[bool, Any]:
    """
    Get a cached result for a function call.

    Returns (found, result) tuple.
    """
    fn = get_sql_function(name)
    if not fn or not fn.cache_enabled:
        return False, None

    key = _make_cache_key(name, args)
    with _cache_lock:
        if key in _result_cache:
            return True, _result_cache[key]
    return False, None


def set_cached_result(name: str, args: Dict[str, Any], result: Any) -> None:
    """Cache a function result."""
    fn = get_sql_function(name)
    if not fn or not fn.cache_enabled:
        return

    key = _make_cache_key(name, args)
    with _cache_lock:
        _result_cache[key] = result


def clear_cache(name: Optional[str] = None) -> int:
    """
    Clear the function result cache.

    Args:
        name: If provided, only clear cache for this function.
              If None, clear entire cache.

    Returns:
        Number of entries cleared.
    """
    with _cache_lock:
        if name is None:
            count = len(_result_cache)
            _result_cache.clear()
            return count
        else:
            # Would need to track which keys belong to which function
            # For now, just clear all
            count = len(_result_cache)
            _result_cache.clear()
            return count


async def execute_sql_function(
    name: str,
    args: Dict[str, Any],
    session_id: Optional[str] = None,
) -> Any:
    """
    Execute a SQL function by running its backing cascade.

    Args:
        name: Function name
        args: Function arguments (mapped to cascade inputs)
        session_id: Optional session ID for cascade execution

    Returns:
        Function result (from cascade output)

    Raises:
        ValueError: If function not found
        Exception: If cascade execution fails
    """
    fn = get_sql_function(name)
    if not fn:
        raise ValueError(f"SQL function not found: {name}")

    # Check cache first
    found, cached = get_cached_result(name, args)
    if found:
        log.debug(f"[sql_fn] Cache hit for {name}")
        return cached

    # Import here to avoid circular imports
    from ..runner import RVBBITRunner

    # Create runner and execute cascade
    runner = RVBBITRunner(fn.cascade_path)

    # Generate session ID if not provided
    if not session_id:
        import uuid
        session_id = f"sql_fn_{name}_{uuid.uuid4().hex[:8]}"

    # Execute cascade with args as input
    result = await runner.run(
        inputs=args,
        session_id=session_id,
    )

    # Extract result from cascade output
    # The last cell's output is typically the function result
    output = result.get("result") or result.get("output") or result

    # Handle structured output based on return type
    if fn.returns == "BOOLEAN":
        if isinstance(output, str):
            output = output.lower().strip() in ("true", "yes", "1")
        elif isinstance(output, (int, float)):
            output = bool(output)
    elif fn.returns == "DOUBLE":
        if isinstance(output, str):
            try:
                output = float(output)
            except ValueError:
                output = 0.0
    elif fn.returns == "INTEGER":
        if isinstance(output, str):
            try:
                output = int(float(output))
            except ValueError:
                output = 0
    elif fn.returns == "JSON":
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                pass

    # Cache result
    set_cached_result(name, args, output)

    return output


def execute_sql_function_sync(
    name: str,
    args: Dict[str, Any],
    session_id: Optional[str] = None,
) -> Any:
    """
    Synchronous wrapper for execute_sql_function.

    For use in DuckDB UDFs which are synchronous.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're in an async context, need to run in a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                execute_sql_function(name, args, session_id)
            )
            return future.result()
    else:
        return asyncio.run(execute_sql_function(name, args, session_id))


def get_operator_patterns() -> Dict[str, List[Tuple[str, str]]]:
    """
    Get all operator patterns for query rewriting.

    Returns dict mapping operator pattern → list of (function_name, pattern).
    """
    initialize_registry()

    patterns = {}
    for name, entry in _registry.items():
        for operator in entry.operators:
            # Extract the operator keyword (e.g., "MEANS", "ABOUT")
            # from patterns like "{{ text }} MEANS {{ criterion }}"
            import re
            match = re.search(r'\}\}\s*(\w+)', operator)
            if match:
                keyword = match.group(1).upper()
                if keyword not in patterns:
                    patterns[keyword] = []
                patterns[keyword].append((name, operator))

    return patterns
