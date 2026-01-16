"""
SQL Function Registry - discovers and manages cascade-based SQL functions.

Scans cascades/ and skills/ directories for cascades with sql_function config,
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
# See: lars.sql_tools.cache_adapter.SemanticCache


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

    @property
    def output_mode(self) -> str:
        """Get output mode: 'value', 'sql_execute', 'sql_raw', or 'sql_statement'.

        - value: (default) Cascade returns final value directly
        - sql_execute: Cascade returns SQL expression for scalar result
        - sql_raw: Cascade returns SQL fragment as-is (debugging/composition)
        - sql_statement: Cascade returns full SQL statement for table results
        """
        return self.sql_function.get("output_mode", "value")

    @property
    def cache_key_config(self) -> Optional[Dict[str, Any]]:
        """Get cache key configuration."""
        return self.sql_function.get("cache_key")

    @property
    def structure_args(self) -> List[str]:
        """Get list of args that should use structure-based caching."""
        # Check cache_key.structure_args first
        cache_key = self.cache_key_config
        if cache_key and cache_key.get("strategy") == "structure":
            return cache_key.get("structure_args", [])

        # Fallback: check arg definitions for structure_source=True
        structure_args = []
        for arg in self.args:
            if arg.get("structure_source"):
                structure_args.append(arg.get("name"))
        return structure_args

    @property
    def fingerprint_args(self) -> List[str]:
        """Get list of args that should use fingerprint-based caching."""
        cache_key = self.cache_key_config
        if cache_key and cache_key.get("strategy") == "fingerprint":
            return cache_key.get("fingerprint_args", [])
        return []

    @property
    def fingerprint_config(self) -> Optional[Dict[str, Any]]:
        """Get fingerprint configuration."""
        cache_key = self.cache_key_config
        if cache_key:
            return cache_key.get("fingerprint_config")
        return None

    @property
    def cache_name(self) -> str:
        """Get the name to use for cache keys.

        Allows multiple functions to share a cache via cache_key.cache_as.
        For example, ask_data and ask_data_sql can both use cache_as: "ask_data"
        to share the same cache (since they generate the same SQL).
        """
        cache_key = self.cache_key_config
        if cache_key and cache_key.get("cache_as"):
            return cache_key.get("cache_as")
        return self.name

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


def _get_builtin_cascades_dir() -> Path:
    """Get the package-bundled cascades directory."""
    return Path(__file__).parent.parent / "builtin_cascades"


def _get_builtin_skills_dir() -> Path:
    """Get the package-bundled skills directory."""
    return Path(__file__).parent.parent / "builtin_skills"


def _get_skills_dir() -> Path:
    """Get the user skills directory path (from config or default)."""
    try:
        from ..config import get_config
        config = get_config()
        return Path(config.root_dir) / "skills"
    except Exception:
        return Path.cwd() / "skills"


def _get_cascades_dir() -> Path:
    """Get the user cascades directory path."""
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
    1. Package builtin_skills/ - Bundled skill cascades (lowest priority)
    2. Package builtin_cascades/ - Bundled semantic operators
    3. User skills/ directory - User custom skills
    4. User cascades/ directory - Highest priority, user overrides

    Built-in operators (MEANS, ABOUT, SUMMARIZE, etc.) are bundled in the
    package under builtin_cascades/semantic_sql/. Users can override any
    operator by creating a cascade with the same function name in their
    LARS_ROOT/cascades/ directory.

    Args:
        force: If True, re-scan even if already initialized
    """
    global _initialized, _registry

    with _registry_lock:
        if _initialized and not force:
            return

        _registry.clear()

        def _register_from_directory(directory: Path, source_name: str) -> int:
            """Scan a directory and register SQL functions. Returns count."""
            count = 0
            if not directory.exists():
                return count

            log.info(f"[sql_registry] Scanning {source_name}: {directory}")
            for path, config in _scan_directory(directory):
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
                count += 1
                log.debug(f"[sql_registry] Registered from {source_name}: {name}")

            return count

        # 1. Scan package builtin_skills (lowest priority)
        builtin_skills_dir = _get_builtin_skills_dir()
        builtin_skills_count = _register_from_directory(builtin_skills_dir, "builtin_skills")

        # 2. Scan package builtin_cascades (includes semantic_sql operators)
        builtin_cascades_dir = _get_builtin_cascades_dir()
        builtin_cascades_count = _register_from_directory(builtin_cascades_dir, "builtin_cascades")

        # 3. Scan user skills directory (can override builtins)
        skills_dir = _get_skills_dir()
        user_skills_count = _register_from_directory(skills_dir, "user_skills")

        # 4. Scan user cascades directory (highest priority - can override everything)
        cascades_dir = _get_cascades_dir()
        user_cascades_count = _register_from_directory(cascades_dir, "user_cascades")

        _initialized = True
        log.info(
            f"[sql_registry] Initialized with {len(_registry)} functions "
            f"(builtin: {builtin_skills_count + builtin_cascades_count}, "
            f"user: {user_skills_count + user_cascades_count})"
        )


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


def _make_structure_cache_key(
    fn: SQLFunctionEntry,
    args: Dict[str, Any]
) -> str:
    """
    Create a cache key using structure hashing for sql_execute mode.

    Args:
        fn: The SQL function entry
        args: Function arguments

    Returns:
        Cache key string
    """
    from .sql_macro import make_structure_cache_key

    # Use cache_name to allow cache sharing (e.g., ask_data + ask_data_sql)
    cache_name = fn.cache_name

    structure_args = fn.structure_args
    if structure_args:
        return make_structure_cache_key(cache_name, args, structure_args)
    else:
        # Fall back to content-based key
        return _make_cache_key(cache_name, args)


def _make_fingerprint_cache_key(
    fn: SQLFunctionEntry,
    args: Dict[str, Any]
) -> str:
    """
    Create a cache key using fingerprint hashing for patterned string data.

    Fingerprints capture the FORMAT of a string, not its content.
    Same format + same task = same parser = cache hit.

    Args:
        fn: The SQL function entry
        args: Function arguments

    Returns:
        Cache key string
    """
    from .fingerprint import compute_fingerprint, make_fingerprint_cache_key, FingerprintMethod

    # Use cache_name to allow cache sharing (e.g., ask_data + ask_data_sql)
    cache_name = fn.cache_name

    fingerprint_args = fn.fingerprint_args
    if not fingerprint_args:
        # Fall back to content-based key
        return _make_cache_key(cache_name, args)

    # Get fingerprint config
    fp_config = fn.fingerprint_config or {}
    method_str = fp_config.get("method", "hybrid")
    include_lengths = fp_config.get("include_lengths", False)

    try:
        method = FingerprintMethod(method_str)
    except ValueError:
        method = FingerprintMethod.HYBRID

    # Get the primary fingerprint arg
    fp_arg_name = fingerprint_args[0]
    fp_value = args.get(fp_arg_name, "")

    # Compute fingerprint of the value
    fingerprint = compute_fingerprint(str(fp_value), method, include_lengths)

    # Build task from non-fingerprint args
    task_parts = []
    for arg_name, arg_value in sorted(args.items()):
        if arg_name not in fingerprint_args:
            task_parts.append(str(arg_value))
    task = "|".join(task_parts)

    return make_fingerprint_cache_key(cache_name, fingerprint, task)


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

    Supports three output modes:
    - "value": (default) Cascade returns final value directly
    - "sql_execute": Cascade returns SQL fragment, which is executed to get the value
    - "sql_raw": Cascade returns SQL fragment as-is (for debugging/composition)

    The "sql_execute" mode enables structure-based caching: JSON with the same
    structure but different values shares cached SQL fragments. This is powerful
    for consistent JSON extraction - the LLM generates SQL once per structure.

    Supports cascade-level takes via SQL comment hints:
        -- @ takes.factor: 3
        -- @ takes.evaluator: Pick the most accurate response
        -- @ models: [claude-sonnet, gpt-4o, gemini-pro]
        SELECT description MEANS 'is eco-friendly' FROM products

    When takes config is detected (embedded in args as __LARS_TAKES:...__ prefix),
    the cascade is run multiple times and an evaluator picks the best result.

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
    from .executor import _extract_takes_from_inputs, _inject_takes_into_cascade

    fn = get_sql_function(name)
    if not fn:
        raise ValueError(f"SQL function not found: {name}")

    # Extract takes config from args (embedded as special prefix in criterion strings)
    cleaned_args, takes_config = _extract_takes_from_inputs(args)

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

    # Determine output mode
    output_mode = fn.output_mode  # "value", "sql_execute", or "sql_raw"

    # Determine cache key strategy
    cache_config = fn.cache_key_config or {}
    cache_strategy = cache_config.get("strategy", "content")

    # For sql_execute mode with structure caching, use structure-based cache key
    use_structure_cache = (
        cache_strategy == "structure" or
        (output_mode in ("sql_execute", "sql_raw") and fn.structure_args)
    )

    # For fingerprint strategy, use fingerprint-based cache key
    use_fingerprint_cache = cache_strategy == "fingerprint" and fn.fingerprint_args

    # Use cache_name to allow cache sharing (e.g., ask_data + ask_data_sql)
    cache_name = fn.cache_name

    # Build cache key based on strategy
    if use_fingerprint_cache:
        cache_key = _make_fingerprint_cache_key(fn, cleaned_args)
        log.debug(f"[sql_fn] Using fingerprint-based cache key: {cache_key[:16]}...")
    elif use_structure_cache:
        cache_key = _make_structure_cache_key(fn, cleaned_args)
        log.debug(f"[sql_fn] Using structure-based cache key: {cache_key[:16]}...")
    else:
        cache_key = _make_cache_key(cache_name, cleaned_args)

    # Check cache first (skip if takes - takes bypass cache for fresh sampling)
    if not takes_config and fn.cache_enabled:
        from ..sql_tools.cache_adapter import get_cache
        cache = get_cache()

        # For fingerprint strategy, check cache using fingerprint-based key
        if use_fingerprint_cache:
            found, cached, _ = cache.get(cache_name, {"__fingerprint_key__": cache_key})
            if found:
                log.debug(f"[sql_fn] Cache hit (fingerprint key) for {name} (cache_name={cache_name})")
        # For structure strategy, check cache using structure-based key
        elif use_structure_cache:
            found, cached, _ = cache.get(cache_name, {"__structure_key__": cache_key})
            if found:
                log.debug(f"[sql_fn] Cache hit (structure key) for {name} (cache_name={cache_name})")
        else:
            # Default: content-based cache key
            found, cached = get_cached_result(cache_name, cleaned_args)

        if found:
            log.debug(f"[sql_fn] Cache hit for {name}")
            # Track cache hit for SQL Trail
            if caller_id:
                try:
                    increment_cache_hit(caller_id)
                except Exception:
                    pass

            # For sql_execute mode, cached value is SQL fragment - execute it
            if output_mode == "sql_execute" and isinstance(cached, str):
                from .sql_macro import bind_sql_parameters, execute_sql_fragment
                sql_fragment = cached
                bound_sql = bind_sql_parameters(sql_fragment, cleaned_args, fn.args)
                log.debug(f"[sql_fn] Executing cached SQL: {bound_sql[:100]}...")
                return execute_sql_fragment(bound_sql, fn.returns)

            # For sql_statement mode, cached value is full SQL - execute it for table results
            if output_mode == "sql_statement" and isinstance(cached, str):
                from .sql_macro import bind_sql_parameters, execute_sql_statement
                sql_statement = cached
                bound_sql = bind_sql_parameters(sql_statement, cleaned_args, fn.args)
                log.debug(f"[sql_fn] Executing cached SQL statement: {bound_sql[:100]}...")
                results = execute_sql_statement(bound_sql)

                # Write results to temp file for read_json_auto() compatibility
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                    json.dump(results, f)
                    temp_path = f.name

                log.debug(f"[sql_fn] Wrote {len(results)} rows to {temp_path}")
                return temp_path

            # For VARCHAR return type, ensure dict/list outputs are JSON serialized
            if fn.returns == "VARCHAR" and isinstance(cached, (dict, list)):
                return json.dumps(cached)
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
                inputs=cleaned_args
            )
        except Exception as e:
            log.debug(f"[sql_fn] Failed to register cascade execution: {e}")

    # Import here to avoid circular imports
    from ..runner import LARSRunner

    # Ensure skills are registered before running any cascade
    # This is normally done by the run_cascade wrapper in __init__.py,
    # but SQL functions import LARSRunner directly
    from .. import _register_all_skills
    _register_all_skills()

    # Prepare cascade inputs based on output mode
    cascade_inputs = cleaned_args
    if output_mode in ("sql_execute", "sql_raw") and fn.structure_args:
        # For sql_execute mode, pass structure (schema) instead of content
        # for args marked as structure_source
        from .sql_macro import prepare_cascade_inputs_for_structure_mode
        cascade_inputs = prepare_cascade_inputs_for_structure_mode(
            cleaned_args,
            fn.structure_args
        )
        log.debug(f"[sql_fn] Prepared structure-mode inputs for {fn.structure_args}")

    # Determine what to run: original cascade or modified with takes
    if takes_config:
        # Inject takes into cascade config (in-memory, not modifying file)
        cascade_config = _inject_takes_into_cascade(fn.cascade_path, takes_config)
        log.info(f"[sql_fn] Running {name} with takes: factor={takes_config.get('factor', 'N/A')}")
        print(f"[sql_fn] [RUN] Running {name} WITH TAKES: {takes_config}")
        print(f"[sql_fn] [RUN] Injected cascade config has takes: {cascade_config.get('takes', 'NONE')}")

        # Create runner with modified config
        runner = LARSRunner(
            cascade_config,
            session_id=session_id,
            caller_id=caller_id
        )
    else:
        # Create runner with session_id AND caller_id for proper tracking
        print(f"[sql_fn] [EXEC] Running {name} (mode={output_mode})")
        runner = LARSRunner(
            fn.cascade_path,
            session_id=session_id,
            caller_id=caller_id  # Pass caller_id so Echo gets it and propagates to all logs!
        )

    # Execute cascade with prepared inputs
    result = runner.run(input_data=cascade_inputs)

    # Extract result from cascade output using proper parsing
    from .executor import _extract_cascade_output
    output = _extract_cascade_output(result)

    # Handle output based on mode
    if output_mode == "sql_raw":
        # Return SQL fragment as-is (for debugging/composition)
        if not takes_config and fn.cache_enabled:
            set_cached_result(cache_name, cleaned_args, output)
        return output

    if output_mode == "sql_execute":
        # Output is SQL fragment - execute it with bound parameters
        sql_fragment = str(output).strip()
        log.debug(f"[sql_fn] Generated SQL fragment: {sql_fragment[:200]}...")

        # Cache the SQL fragment (not the executed result)
        # This enables structure-based caching - same structure, different values
        if not takes_config and fn.cache_enabled:
            # Use appropriate cache key strategy
            if use_fingerprint_cache:
                # Store with fingerprint-based key
                from ..sql_tools.cache_adapter import get_cache
                cache = get_cache()
                result_type = fn.returns if fn else "VARCHAR"
                ttl_seconds = fn.cache_ttl if fn else None
                cache.set(cache_name, {"__fingerprint_key__": cache_key}, sql_fragment,
                          result_type=result_type, ttl_seconds=ttl_seconds)
                log.debug(f"[sql_fn] Cached SQL fragment with fingerprint key: {cache_key[:16]}...")
            elif use_structure_cache:
                # Store with structure-based key
                from ..sql_tools.cache_adapter import get_cache
                cache = get_cache()
                result_type = fn.returns if fn else "VARCHAR"
                ttl_seconds = fn.cache_ttl if fn else None
                cache.set(cache_name, {"__structure_key__": cache_key}, sql_fragment,
                          result_type=result_type, ttl_seconds=ttl_seconds)
                log.debug(f"[sql_fn] Cached SQL fragment with structure key: {cache_key[:16]}...")
            else:
                set_cached_result(cache_name, cleaned_args, sql_fragment)

        # Bind parameters and execute
        from .sql_macro import bind_sql_parameters, execute_sql_fragment
        bound_sql = bind_sql_parameters(sql_fragment, cleaned_args, fn.args)
        log.debug(f"[sql_fn] Bound SQL: {bound_sql[:200]}...")

        return execute_sql_fragment(bound_sql, fn.returns)

    if output_mode == "sql_statement":
        # Output is full SQL statement - execute and return table results
        sql_statement = str(output).strip()
        log.debug(f"[sql_fn] Generated SQL statement: {sql_statement[:200]}...")

        # Cache the SQL statement (exact match caching)
        if not takes_config and fn.cache_enabled:
            # For sql_statement, cache key is based on the question/input
            # Since user already has sql_search tool, caching is by exact question match
            from ..sql_tools.cache_adapter import get_cache
            cache = get_cache()
            result_type = "JSON"  # Table results are always JSON
            ttl_seconds = fn.cache_ttl if fn else None
            cache.set(cache_name, cleaned_args, sql_statement,
                      result_type=result_type, ttl_seconds=ttl_seconds)
            log.debug(f"[sql_fn] Cached SQL statement for: {list(cleaned_args.keys())} (cache_name={cache_name})")

        # Bind parameters if any exist in the statement
        from .sql_macro import bind_sql_parameters, execute_sql_statement
        bound_sql = bind_sql_parameters(sql_statement, cleaned_args, fn.args)
        log.debug(f"[sql_fn] Bound SQL statement: {bound_sql[:200]}...")

        # Execute and return table results
        results = execute_sql_statement(bound_sql)

        # Write results to temp file for read_json_auto() compatibility
        # This allows TABLE macros to wrap with: SELECT * FROM read_json_auto(_func_file(args))
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(results, f)
            temp_path = f.name

        log.debug(f"[sql_fn] Wrote {len(results)} rows to {temp_path}")
        return temp_path

    # Default mode: "value" - cascade returns final value directly
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

    # Cache result (but not takes runs - they're for fresh sampling)
    if not takes_config and fn.cache_enabled:
        # Use appropriate cache key strategy
        if use_fingerprint_cache:
            # Store with fingerprint-based key
            from ..sql_tools.cache_adapter import get_cache
            cache = get_cache()
            result_type = fn.returns if fn else "VARCHAR"
            ttl_seconds = fn.cache_ttl if fn else None
            cache.set(cache_name, {"__fingerprint_key__": cache_key}, output,
                      result_type=result_type, ttl_seconds=ttl_seconds)
            log.debug(f"[sql_fn] Cached result with fingerprint key: {cache_key[:16]}...")
        elif use_structure_cache:
            # Store with structure-based key
            from ..sql_tools.cache_adapter import get_cache
            cache = get_cache()
            result_type = fn.returns if fn else "VARCHAR"
            ttl_seconds = fn.cache_ttl if fn else None
            cache.set(cache_name, {"__structure_key__": cache_key}, output,
                      result_type=result_type, ttl_seconds=ttl_seconds)
            log.debug(f"[sql_fn] Cached result with structure key: {cache_key[:16]}...")
        else:
            # Default: content-based cache key
            set_cached_result(cache_name, cleaned_args, output)

    # IMPORTANT: For VARCHAR return type, ensure dict/list outputs are JSON serialized.
    # Without this, DuckDB uses Python's str() which produces {'key': ...} format
    # instead of valid JSON {"key": ...}, breaking read_json_auto() consumption.
    if fn.returns == "VARCHAR" and isinstance(output, (dict, list)):
        output = json.dumps(output)

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
