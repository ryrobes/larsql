"""
SQL Function Registry - discovers and manages cascade-based SQL functions.

Scans cascades/ and traits/ directories for cascades with sql_function config,
and provides execution interface for SQL queries.

Built-in semantic SQL operators (MEANS, ABOUT, etc.) are now stored in
cascades/semantic_sql/ as standard user-space cascades. Users can override
any operator by creating a cascade with the same function name.
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

# Cache is now managed by the persistent cache adapter
# See: rvbbit.sql_tools.cache_adapter.SemanticCache


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
    """Load a YAML file, returning None on error.

    Handles multi-document YAML files by taking the first document.
    Silently skips files with 'FUTURE' in the name (incomplete features).
    """
    # Skip FUTURE files - they're incomplete/experimental
    if 'FUTURE' in path.name:
        return None

    # Skip backup directories
    if 'backup' in str(path):
        return None

    try:
        import yaml
        with open(path, "r") as f:
            content = f.read()

        # Try single document first (most common)
        try:
            return yaml.safe_load(content)
        except yaml.scanner.ScannerError as e:
            # Multi-document file - take first document only
            if "found another document" in str(e):
                docs = list(yaml.safe_load_all(content))
                if docs:
                    return docs[0]
            raise
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

    Scans in priority order (later overwrites earlier):
    1. traits/ directory - For backwards compatibility and custom tools
    2. cascades/ directory - Highest priority, includes built-in semantic_sql/

    Built-in operators (MEANS, ABOUT, SUMMARIZE, etc.) are now in
    cascades/semantic_sql/ and can be overridden by user cascades.

    Args:
        force: If True, re-scan even if already initialized
    """
    global _initialized, _registry

    with _registry_lock:
        if _initialized and not force:
            return

        _registry.clear()

        # Scan traits directory first (lower priority)
        # For backwards compatibility and custom tools
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
        # Includes cascades/semantic_sql/ with built-in operators
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
    from ..sql_tools.cache_adapter import SemanticCache
    return SemanticCache.make_cache_key(name, args)


def get_cached_result(name: str, args: Dict[str, Any]) -> Tuple[bool, Any]:
    """
    Get a cached result for a function call.

    Uses the persistent SemanticCache (L1 in-memory + L2 ClickHouse).

    Returns (found, result) tuple.
    """
    fn = get_sql_function(name)
    if not fn or not fn.cache_enabled:
        return False, None

    from ..sql_tools.cache_adapter import get_cache
    cache = get_cache()
    found, result, _ = cache.get(name, args)
    return found, result


def set_cached_result(name: str, args: Dict[str, Any], result: Any) -> None:
    """
    Cache a function result.

    Uses the persistent SemanticCache (L1 in-memory + L2 ClickHouse).
    """
    fn = get_sql_function(name)
    if not fn or not fn.cache_enabled:
        return

    # Determine result type from function definition
    result_type = fn.returns if fn else "VARCHAR"

    # Get TTL from function config
    ttl_seconds = fn.cache_ttl if fn else None

    from ..sql_tools.cache_adapter import get_cache
    cache = get_cache()
    cache.set(name, args, result, result_type=result_type, ttl_seconds=ttl_seconds)


def clear_cache(name: Optional[str] = None) -> int:
    """
    Clear the function result cache.

    Uses the persistent SemanticCache (L1 in-memory + L2 ClickHouse).

    Args:
        name: If provided, only clear cache for this function.
              If None, clear entire cache.

    Returns:
        Number of entries cleared.
    """
    from ..sql_tools.cache_adapter import get_cache
    cache = get_cache()
    return cache.clear(function_name=name)


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

    # Get caller_id from context (set by postgres_server for SQL queries)
    # Try ALL storage layers: contextvar → thread-local → global registry
    try:
        from ..caller_context import get_caller_id, _global_caller_registry
        from ..sql_trail import register_cascade_execution, increment_cache_hit, increment_cache_miss

        # First try normal get_caller_id (checks contextvar + thread-local)
        caller_id = get_caller_id()

        # If still None, try ALL keys in global registry (brute force search)
        if not caller_id and _global_caller_registry:
            log.debug(f"[sql_fn] Trying global registry, {len(_global_caller_registry)} entries")
            # Get any caller_id from registry (all postgres connections for this server)
            caller_id = next(iter(_global_caller_registry.values()))[0] if _global_caller_registry else None

        log.debug(f"[sql_fn] {name}: caller_id={caller_id!r}")
    except Exception as e:
        log.debug(f"[sql_fn] get_caller_id() failed: {e}")
        caller_id = None

    # Check cache first
    found, cached = get_cached_result(name, args)
    if found:
        log.debug(f"[sql_fn] Cache hit for {name}")
        # Track cache hit for SQL Trail
        if caller_id:
            try:
                increment_cache_hit(caller_id)
            except Exception:
                pass
        return cached

    # Track cache miss for SQL Trail
    if caller_id:
        try:
            increment_cache_miss(caller_id)
        except Exception:
            pass

    # Generate session ID if not provided
    if not session_id:
        import uuid
        session_id = f"sql_fn_{name}_{uuid.uuid4().hex[:8]}"

    # Register cascade execution for SQL Trail
    if caller_id:
        try:
            register_cascade_execution(
                caller_id=caller_id,
                cascade_id=name,
                cascade_path=fn.cascade_path,
                session_id=session_id,
                inputs=args
            )
        except Exception as e:
            log.debug(f"[sql_fn] Failed to register cascade execution: {e}")

    # Import here to avoid circular imports
    from ..runner import RVBBITRunner

    # Create runner with session_id AND caller_id for proper tracking
    runner = RVBBITRunner(
        fn.cascade_path,
        session_id=session_id,
        caller_id=caller_id  # Pass caller_id so Echo gets it and propagates to all logs!
    )

    # Execute cascade with args as input_data
    result = runner.run(input_data=args)

    # Extract result from cascade output using proper parsing
    from .executor import _extract_cascade_output
    output = _extract_cascade_output(result)

    # Unwrap JSON-wrapped scalar outputs
    # LLMs in JSON mode often return {"value": X} or {"result": X} instead of raw values
    if isinstance(output, str) and fn.returns in ("BOOLEAN", "DOUBLE", "INTEGER"):
        try:
            parsed = json.loads(output)
            if isinstance(parsed, dict):
                # Extract from common wrapper keys
                # Note: "type" included because LLMs misinterpret `output_schema: type: X`
                # as "return an object with a field called type"
                for key in ("value", "result", "type", "year", "score", "output", "answer"):
                    if key in parsed:
                        output = parsed[key]
                        break
                else:
                    # Single-key dict: extract the value
                    if len(parsed) == 1:
                        output = next(iter(parsed.values()))
            elif isinstance(parsed, (int, float, bool)):
                # Direct JSON scalar (rare but valid)
                output = parsed
        except (json.JSONDecodeError, TypeError):
            pass  # Not JSON, continue with string conversion

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
        elif isinstance(output, (int, float)):
            output = float(output)
    elif fn.returns == "INTEGER":
        if isinstance(output, str):
            try:
                output = int(float(output))
            except ValueError:
                output = 0
        elif isinstance(output, (int, float)):
            output = int(output)
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
    Preserves caller_context across thread boundaries.
    """
    import asyncio
    import contextvars

    # Capture current context (includes caller_id)
    ctx = contextvars.copy_context()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're in an async context, need to run in a thread
        # CRITICAL: Run in copied context to preserve caller_id!
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                lambda: ctx.run(lambda: asyncio.run(execute_sql_function(name, args, session_id)))
            )
            return future.result()
    else:
        # Run directly in current context
        return ctx.run(lambda: asyncio.run(execute_sql_function(name, args, session_id)))


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
