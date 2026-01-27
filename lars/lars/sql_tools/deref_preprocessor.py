"""
Cascade Deref Preprocessor

Evaluates @cascade() expressions in SQL before the normal rewriting pipeline.
The `@` prefix means "evaluate this cascade NOW, inject the result."

Example:
    SELECT * FROM sales WHERE region = @param_get('region', 'ALL')

Becomes (after preprocessing):
    SELECT * FROM sales WHERE region = 'US'

Supports:
    - Basic deref: @cascade_name('arg1', 'arg2')
    - Accessor syntax: @cascade()[0].field
    - Gather syntax: @cascade()[*].field  (maps over array, extracts field from each)
    - Nested deref: @outer(@inner('arg'))

Accessor Examples:
    @param_get('row').region           -> extract 'region' from stored row
    @params_get('rows')[0].name        -> get first row's 'name' field
    @params_get('rows')[*].region      -> ['North', 'East'] from array of rows
    @params_get('rows')[*].meta.id     -> deep extraction from nested objects
"""

import re
import logging
import time

logger = logging.getLogger(__name__)


def _get_value_type(value) -> str:
    """Determine the type of a resolved value for logging."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, (list, tuple)):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    return 'unknown'


def _log_deref(
    cascade_name: str,
    args: list,
    args_str: str,
    accessor: list | None,
    resolved_value,
    escaped_value: str,
    session_context: dict,
    cache_hit: bool = False,
    duration_ms: float = 0.0,
    error_message: str | None = None
):
    """Log a deref operation to ClickHouse asynchronously."""
    try:
        from lars.db_adapter import get_deref_logger
        deref_logger = get_deref_logger()
        if deref_logger is None:
            return

        # Build the full deref expression
        accessor_str = ''.join(
            f'[{a[1]}]' if a[0] == 'index' else
            '[*]' if a[0] == 'gather' else
            f'.{a[1]}' if a[0] == 'field' else ''
            for a in (accessor or [])
        )
        deref_expression = f"@{cascade_name}({args_str}){accessor_str}"

        deref_logger.log_deref(
            deref_expression=deref_expression,
            cascade_name=cascade_name,
            args=args,
            accessor_chain=accessor_str if accessor_str else None,
            resolved_value=escaped_value,
            resolved_value_type=_get_value_type(resolved_value),
            session_id=session_context.get('session_id', 'unknown'),
            protocol=session_context.get('protocol', 'unknown'),
            database_name=session_context.get('database_name', ''),
            user_name=session_context.get('user_name', ''),
            application_name=session_context.get('application_name', ''),
            client_address=session_context.get('client_address', ''),
            caller_id=session_context.get('caller_id'),
            cache_hit=cache_hit,
            duration_ms=duration_ms,
            error_message=error_message
        )
    except Exception as e:
        # Never let logging failures affect the main deref path
        logger.debug(f"Failed to log deref: {e}")


# Pattern to detect potential @cascade( starts
# We use this for quick scanning, then do token-aware parsing
DEREF_PATTERN = re.compile(r'@(\w+)\s*\(')


def preprocess_deref_cascades(sql: str, session_context: dict) -> str:
    """
    PRE-REWRITE phase: find @cascade() calls, execute, replace with values.

    Args:
        sql: Raw SQL with potential @cascade() calls
        session_context: Dict with session_id, connection info, etc.
            - session_id: str - identifies the session for param scoping
            - protocol: str - 'http' or 'pgwire' (optional, for logging)

    Returns:
        SQL with all @cascade() replaced by literal values

    Note:
        Uses per-query caching: identical @cascade(args) calls within the same
        query are executed once and the result is reused for all occurrences.
    """
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "[DEREF] preprocess (has_at=%s, session_id=%r, protocol=%r, caller_id=%r, sql_prefix=%r)",
            '@' in sql,
            session_context.get('session_id', 'unknown'),
            session_context.get('protocol', 'unknown'),
            session_context.get('caller_id'),
            sql[:120],
        )

    if '@' not in sql:
        return sql

    #print(f"[DEREF] Found @ in sql, checking for patterns...")

    # Per-query cache: key = "cascade_name|arg1|arg2|..." -> escaped result string
    # This avoids re-executing identical @cascade() calls within the same query
    deref_cache: dict[str, str] = {}

    # Recurse until no more @cascade patterns (handles nested derefs)
    max_iterations = 100  # Safety limit
    iterations = 0

    while has_deref_pattern(sql) and iterations < max_iterations:
        prev_sql = sql
        sql = _process_one_deref(sql, session_context, deref_cache)
        iterations += 1

        # If no change was made, stop iterating
        # (remaining @ patterns are inside strings or otherwise not processable)
        if sql == prev_sql:
            #print(f"[DEREF] No change made in iteration {iterations}, stopping")
            break

    if iterations >= max_iterations:
        logger.warning("Deref preprocessing hit iteration limit - possible infinite loop")

    # Log cache stats
    # if deref_cache:
    #     print(f"[DEREF] Cache stats: {len(deref_cache)} unique calls cached")

    return sql


def has_deref_pattern(sql: str) -> bool:
    """Check if SQL contains any @cascade() patterns."""
    result = bool(DEREF_PATTERN.search(sql))
    #print(f"[DEREF] has_deref_pattern: {result}")
    return result


def _process_one_deref(sql: str, session_context: dict, deref_cache: dict[str, str]) -> str:
    """Process the first (innermost) @cascade() found in SQL."""
    # Find all candidate positions
    matches = list(DEREF_PATTERN.finditer(sql))
    # print(f"[DEREF] _process_one_deref found {len(matches)} matches")
    # for m in matches:
    #     print(f"[DEREF]   match: {m.group(0)} at {m.start()}")
    if not matches:
        return sql

    # Process innermost first (rightmost match that doesn't contain other @)
    # This handles nested derefs like @outer(@inner())
    for match in reversed(matches):
        start = match.start()
        cascade_name = match.group(1)
        paren_open = match.end() - 1  # Position of '('

        #print(f"[DEREF] Processing @{cascade_name} at position {start}")

        # Check if this is inside a string literal
        if _is_inside_string(sql, start):
            #print(f"[DEREF]   SKIPPED: inside string literal")
            continue

        # Find matching close paren
        paren_close = _find_matching_paren(sql, paren_open)
        #print(f"[DEREF]   paren_open={paren_open}, paren_close={paren_close}")
        if paren_close < 0:
            #print(f"[DEREF]   SKIPPED: unmatched paren")
            logger.warning(f"Unmatched paren for @{cascade_name} at position {start}")
            continue

        # Extract args string
        args_str = sql[paren_open + 1:paren_close]
        #print(f"[DEREF]   args_str: {args_str[:50]}...")

        # Check for nested deref in args - if found, skip and let next iteration handle
        if '@' in args_str and DEREF_PATTERN.search(args_str):
            #print(f"[DEREF]   SKIPPED: nested deref in args")
            continue

        # Parse accessor suffix: [0].field
        expr_end = paren_close + 1
        accessor = None
        if expr_end < len(sql):
            accessor, expr_end = _parse_accessor(sql, expr_end)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[DEREF]   expr_end=%s, accessor=%s", expr_end, accessor)

        # Build cache key: cascade_name + args_str + accessor
        # This uniquely identifies the deref call
        accessor_str = str(accessor) if accessor else ''
        cache_key = f"{cascade_name}|{args_str}|{accessor_str}"

        # Check cache first
        if cache_key in deref_cache:
            escaped = deref_cache[cache_key]
            #print(f"[DEREF]   CACHE HIT: {escaped}")

            # Log cache hit (parse args for logging)
            try:
                cached_args = _parse_cascade_args(args_str)
                _log_deref(
                    cascade_name=cascade_name,
                    args=cached_args,
                    args_str=args_str,
                    accessor=accessor,
                    resolved_value=None,  # We don't have the original value, just escaped
                    escaped_value=escaped,
                    session_context=session_context,
                    cache_hit=True,
                    duration_ms=0.0
                )
            except Exception:
                pass  # Don't let logging fail affect the main path

            result = sql[:start] + escaped + sql[expr_end:]
            return result

        # Execute the cascade
        try:
            start_time = time.time()
            args = _parse_cascade_args(args_str)
            #print(f"[DEREF]   parsed args: {args}")
            raw_result = _execute_deref_cascade(cascade_name, args, session_context)
            #print(f"[DEREF]   raw_result: {raw_result}")

            # Apply accessor if present
            if accessor:
                final_value = _apply_accessor(raw_result, accessor)
            else:
                final_value = raw_result

            # SQL-escape and replace
            escaped = _sql_escape(final_value)
            duration_ms = (time.time() - start_time) * 1000
            #print(f"[DEREF]   escaped: {escaped}")

            # Store in cache for future identical calls in this query
            deref_cache[cache_key] = escaped
            #print(f"[DEREF]   CACHE STORE: {cache_key[:50]}...")

            # Log successful deref
            _log_deref(
                cascade_name=cascade_name,
                args=args,
                args_str=args_str,
                accessor=accessor,
                resolved_value=final_value,
                escaped_value=escaped,
                session_context=session_context,
                cache_hit=False,
                duration_ms=duration_ms
            )

            logger.debug(f"Deref @{cascade_name}({args_str}){accessor or ''} -> {escaped}")

            result = sql[:start] + escaped + sql[expr_end:]
            #print(f"[DEREF]   REPLACED: ...{result[max(0,start-20):start+len(escaped)+20]}...")
            return result

        except Exception as e:
            #print(f"[DEREF]   ERROR: {e}")
            import traceback
            traceback.print_exc()
            logger.error(f"Deref @{cascade_name} failed: {e}")

            # Log failed deref
            try:
                error_args = _parse_cascade_args(args_str) if args_str else []
            except Exception:
                error_args = []
            _log_deref(
                cascade_name=cascade_name,
                args=error_args,
                args_str=args_str,
                accessor=accessor,
                resolved_value=None,
                escaped_value='NULL',
                session_context=session_context,
                cache_hit=False,
                duration_ms=0.0,
                error_message=str(e)
            )

            # On error, replace with NULL to avoid infinite loop
            return sql[:start] + 'NULL' + sql[expr_end:]

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("[DEREF] No matches processed, returning unchanged")
    return sql


def _is_inside_string(sql: str, pos: int) -> bool:
    """Check if position is inside a string literal."""
    in_string = None
    i = 0
    while i < pos:
        char = sql[i]
        if char in ("'", '"') and (i == 0 or sql[i-1] != '\\'):
            if in_string is None:
                in_string = char
            elif in_string == char:
                in_string = None
        i += 1
    return in_string is not None


def _find_matching_paren(sql: str, open_pos: int) -> int:
    """
    Find matching close paren, respecting strings and comments.

    Args:
        sql: The SQL string
        open_pos: Position of the opening '('

    Returns:
        Position of matching ')' or -1 if not found
    """
    if sql[open_pos] != '(':
        return -1

    depth = 1
    pos = open_pos + 1
    in_string = None
    in_line_comment = False
    in_block_comment = False

    while pos < len(sql) and depth > 0:
        char = sql[pos]
        prev_char = sql[pos - 1] if pos > 0 else ''
        next_char = sql[pos + 1] if pos + 1 < len(sql) else ''

        # Handle comments
        if not in_string:
            if not in_block_comment and char == '-' and next_char == '-':
                in_line_comment = True
            elif in_line_comment and char == '\n':
                in_line_comment = False
            elif not in_line_comment and char == '/' and next_char == '*':
                in_block_comment = True
            elif in_block_comment and char == '*' and next_char == '/':
                in_block_comment = False
                pos += 1  # Skip the /

        # Skip if in comment
        if in_line_comment or in_block_comment:
            pos += 1
            continue

        # Handle strings
        if char in ("'", '"'):
            if in_string is None:
                in_string = char
            elif in_string == char and prev_char != '\\':
                # Check for doubled quote (SQL escape)
                if next_char == char:
                    pos += 1  # Skip the doubled quote
                else:
                    in_string = None

        # Track parens when not in string
        elif not in_string:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1

        pos += 1

    return pos - 1 if depth == 0 else -1


def _parse_accessor(sql: str, start: int) -> tuple[list, int]:
    """
    Parse accessor chain: [index], [*], .field

    Supports:
        - [0]     - index access (specific element)
        - [*]     - gather/map (extract from all elements in array)
        - .field  - field/property access

    Examples:
        @cascade()[0].name      -> get index 0, then 'name' field
        @cascade()[*].name      -> map over array, extract 'name' from each
        @cascade()[*].a.b       -> deep extraction: array -> .a -> .b for each

    Args:
        sql: The SQL string
        start: Position after the closing paren

    Returns:
        (accessor_parts, end_position)
        accessor_parts is list of tuples:
            ('index', n)   - access index n
            ('gather', None) - map over array (must be followed by more accessors)
            ('field', name) - access field/property
    """
    parts = []
    pos = start

    while pos < len(sql):
        # Array access: [0] or [*]
        if sql[pos] == '[':
            bracket_end = sql.find(']', pos)
            if bracket_end < 0:
                break
            bracket_content = sql[pos + 1:bracket_end]

            # Gather operator: [*]
            if bracket_content == '*':
                parts.append(('gather', None))
                pos = bracket_end + 1
            else:
                # Index access: [0]
                try:
                    index = int(bracket_content)
                    parts.append(('index', index))
                    pos = bracket_end + 1
                except ValueError:
                    break

        # Field access: .field_name
        elif sql[pos] == '.':
            match = re.match(r'\.(\w+)', sql[pos:])
            if match:
                parts.append(('field', match.group(1)))
                pos += len(match.group(0))
            else:
                break
        else:
            break

    return parts, pos


def _parse_cascade_args(args_str: str) -> list:
    """
    Parse cascade argument list.

    Handles:
        - String literals: 'hello', "world"
        - Numbers: 42, 3.14
        - Identifiers/expressions: column_name, func(x)
        - NULL

    Args:
        args_str: The arguments string (without outer parens)

    Returns:
        List of parsed argument values
    """
    args_str = args_str.strip()
    if not args_str:
        return []

    args = []
    current_arg = []
    depth = 0
    in_string = None
    i = 0

    while i < len(args_str):
        char = args_str[i]
        prev_char = args_str[i - 1] if i > 0 else ''

        # Handle strings
        if char in ("'", '"'):
            if in_string is None:
                in_string = char
            elif in_string == char and prev_char != '\\':
                # Check for doubled quote
                if i + 1 < len(args_str) and args_str[i + 1] == char:
                    current_arg.append(char)
                    i += 1
                else:
                    in_string = None
            current_arg.append(char)

        # Track nesting when not in string
        elif not in_string:
            if char in '([':
                depth += 1
                current_arg.append(char)
            elif char in ')]':
                depth -= 1
                current_arg.append(char)
            elif char == ',' and depth == 0:
                # Argument separator
                arg_value = ''.join(current_arg).strip()
                args.append(_parse_single_arg(arg_value))
                current_arg = []
            else:
                current_arg.append(char)
        else:
            current_arg.append(char)

        i += 1

    # Don't forget the last argument
    if current_arg:
        arg_value = ''.join(current_arg).strip()
        if arg_value:
            args.append(_parse_single_arg(arg_value))

    return args


def _parse_single_arg(arg_str: str) -> str | int | float | None:
    """Parse a single argument value."""
    arg_str = arg_str.strip()

    if not arg_str:
        return None

    # NULL
    if arg_str.upper() == 'NULL':
        return None

    # String literal
    if (arg_str.startswith("'") and arg_str.endswith("'")) or \
       (arg_str.startswith('"') and arg_str.endswith('"')):
        # Remove quotes and unescape
        inner = arg_str[1:-1]
        # Handle doubled quotes (SQL escape)
        quote = arg_str[0]
        inner = inner.replace(quote + quote, quote)
        return inner

    # Integer
    try:
        return int(arg_str)
    except ValueError:
        pass

    # Float
    try:
        return float(arg_str)
    except ValueError:
        pass

    # Return as-is (identifier, expression, etc.)
    return arg_str


def _execute_deref_cascade(name: str, args: list, session_context: dict):
    """
    Execute a cascade for deref.

    Args:
        name: Cascade name (e.g., 'param_get')
        args: Parsed arguments list
        session_context: Session context dict

    Returns:
        The cascade result (can be any JSON-serializable value)
    """
    # Import from auth module (ClickHouse-backed with L1/L2 caching)
    from lars.auth.param_store import (
        param_store_get,
        param_store_set,
        param_store_clear,
        params_store_get,
        params_store_set,
        params_store_clear,
    )

    session_id = session_context.get('session_id', 'default')

    # Built-in param operations (fast path, no cascade overhead)
    # Scalar operations: param_get, param_set, param_clear
    if name == 'param_get':
        key = args[0] if len(args) > 0 else None
        default = args[1] if len(args) > 1 else None
        if key is None:
            raise ValueError("param_get requires a key argument")
        return param_store_get(session_id, str(key), default)

    elif name == 'param_set':
        key = args[0] if len(args) > 0 else None
        value = args[1] if len(args) > 1 else None
        if key is None:
            raise ValueError("param_set requires a key argument")
        return param_store_set(session_id, str(key), str(value) if value is not None else None)

    elif name == 'param_clear':
        key = args[0] if len(args) > 0 else None
        if key is None:
            raise ValueError("param_clear requires a key argument")
        param_store_clear(session_id, str(key))
        return None

    # Array operations: params_get, params_set, params_clear (for multi-select)
    elif name == 'params_get':
        key = args[0] if len(args) > 0 else None
        if key is None:
            raise ValueError("params_get requires a key argument")
        return params_store_get(session_id, str(key))

    elif name == 'params_set':
        key = args[0] if len(args) > 0 else None
        value = args[1] if len(args) > 1 else None
        if key is None:
            raise ValueError("params_set requires a key argument")
        if value is None:
            raise ValueError("params_set requires a value argument")
        return params_store_set(session_id, str(key), str(value))

    elif name == 'params_clear':
        key = args[0] if len(args) > 0 else None
        if key is None:
            raise ValueError("params_clear requires a key argument")
        params_store_clear(session_id, str(key))
        return None

    else:
        # General cascade execution
        # TODO: Implement full cascade execution for arbitrary @cascade() calls
        # For now, only built-in param operations are supported
        raise NotImplementedError(
            f"Cascade @{name} not implemented. "
            f"Currently only @param_get, @param_set, @param_clear, "
            f"@params_get, @params_set, @params_clear are supported."
        )


def _apply_accessor(value, accessor: list):
    """
    Apply accessor chain to value.

    Supports:
        - ('index', n)    - access element at index n
        - ('gather', None) - map over array, apply rest of chain to each element
        - ('field', name) - access field/property by name

    Examples:
        [('index', 0), ('field', 'name')]  -> value[0]['name']
        [('gather', None), ('field', 'name')]  -> [v['name'] for v in value]
        [('gather', None), ('field', 'a'), ('field', 'b')]  -> [v['a']['b'] for v in value]

    Args:
        value: The value to access
        accessor: List of accessor tuples

    Returns:
        The accessed value (scalar or list depending on accessor chain)
    """
    if not accessor:
        return value

    result = value

    for i, (access_type, access_key) in enumerate(accessor):
        if result is None:
            return None

        if access_type == 'index':
            if isinstance(result, (list, tuple)):
                if 0 <= access_key < len(result):
                    result = result[access_key]
                else:
                    return None
            else:
                return None

        elif access_type == 'gather':
            # [*] - map over array, apply remaining accessor chain to each element
            if not isinstance(result, (list, tuple)):
                # Not an array - can't gather
                return None

            # Get remaining accessor chain after [*]
            remaining = accessor[i + 1:]

            if not remaining:
                # [*] with nothing after it just returns the array as-is
                return list(result)

            # Apply remaining chain to each element
            gathered = []
            for item in result:
                item_result = _apply_accessor(item, remaining)
                gathered.append(item_result)

            return gathered

        elif access_type == 'field':
            if isinstance(result, dict):
                result = result.get(access_key)
            elif hasattr(result, access_key):
                result = getattr(result, access_key)
            else:
                return None

    return result


def _sql_escape(value) -> str:
    """
    Escape a value for safe SQL injection.

    Args:
        value: The value to escape

    Returns:
        SQL-safe string representation
    """
    if value is None:
        return 'NULL'

    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, str):
        # Escape single quotes by doubling them
        escaped = value.replace("'", "''")
        return f"'{escaped}'"

    if isinstance(value, (list, tuple)):
        # Convert to SQL array - always preserve array structure
        # This ensures list_contains() and other array functions work correctly
        if len(value) == 0:
            return '[]'  # Empty array, not NULL
        elements = [_sql_escape(v) for v in value]
        return f"[{', '.join(elements)}]"

    if isinstance(value, dict):
        # Convert dict to JSON string
        import json
        json_str = json.dumps(value).replace("'", "''")
        return f"'{json_str}'"

    # Fallback: convert to string
    return _sql_escape(str(value))
