"""
SQL Macro Utilities for sql_execute mode.

This module provides utilities for:
1. Structure-based cache key generation
2. SQL fragment parameter binding
3. SQL fragment execution

When output_mode="sql_execute", cascades return SQL fragments that get executed
rather than final values. Combined with structure-based caching, this enables
efficient processing of consistent JSON structures.

Example flow:
1. User calls: smart_json('{"customer":{"name":"Alice"}}', 'customer name')
2. We extract structure: {"customer":{"name":"string"}}
3. Cache lookup by structure hash + description
4. Cache miss -> Run cascade -> LLM returns: json_extract_string(:data, '$.customer.name')
5. Cache the SQL fragment
6. Bind parameters: json_extract_string('{"customer":{"name":"Alice"}}', '$.customer.name')
7. Execute SQL, return "Alice"
"""

import json
import hashlib
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


def extract_structure(val, max_depth: int = 5, depth: int = 0):
    """
    Recursively extract structure from a value, replacing values with type indicators.

    Args:
        val: The value to extract structure from
        max_depth: Maximum recursion depth
        depth: Current depth

    Returns:
        Structure representation with type indicators
    """
    if depth >= max_depth:
        return "..."

    if val is None:
        return "null"
    elif isinstance(val, bool):
        return "boolean"
    elif isinstance(val, int):
        return "integer"
    elif isinstance(val, float):
        return "number"
    elif isinstance(val, str):
        return "string"
    elif isinstance(val, list):
        if not val:
            return []
        # Use first element as exemplar (assume homogeneous)
        return [extract_structure(val[0], max_depth, depth + 1)]
    elif isinstance(val, dict):
        return {k: extract_structure(v, max_depth, depth + 1)
                for k, v in sorted(val.items())}
    else:
        return str(type(val).__name__)


def structure_hash(value) -> str:
    """
    Compute a hash of the JSON structure.

    Two JSON values with the same structure but different content
    produce the same hash.

    Args:
        value: JSON value (string or parsed)

    Returns:
        MD5 hash of the structure (12 chars)
    """
    if value is None:
        return "null_struct"

    # Parse JSON string if needed
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            # Not valid JSON, hash the string type
            return hashlib.md5(f"string:{len(value)}".encode()).hexdigest()[:12]

    structure = extract_structure(value)
    structure_json = json.dumps(structure, sort_keys=True)
    return hashlib.md5(structure_json.encode()).hexdigest()[:12]


def make_structure_cache_key(
    function_name: str,
    args: Dict[str, Any],
    structure_args: List[str]
) -> str:
    """
    Create a cache key using structure hashing for specified args.

    Args:
        function_name: The SQL function name
        args: All function arguments
        structure_args: List of arg names to hash by structure

    Returns:
        Cache key string
    """
    key_parts = [function_name]

    for arg_name, arg_value in sorted(args.items()):
        if arg_name in structure_args:
            # Hash by structure, not content
            struct_hash = structure_hash(arg_value)
            key_parts.append(f"{arg_name}:struct:{struct_hash}")
        else:
            # Hash by content (default behavior)
            content_json = json.dumps(arg_value, sort_keys=True, default=str)
            content_hash = hashlib.md5(content_json.encode()).hexdigest()[:12]
            key_parts.append(f"{arg_name}:{content_hash}")

    combined = ":".join(key_parts)
    return hashlib.md5(combined.encode()).hexdigest()


def quote_sql_value(value: Any, sql_type: str = "VARCHAR") -> str:
    """
    Quote a value for SQL insertion.

    Args:
        value: The value to quote
        sql_type: SQL type hint for proper quoting

    Returns:
        SQL-safe quoted string
    """
    if value is None:
        return "NULL"

    sql_type = sql_type.upper()

    if sql_type in ("INTEGER", "INT", "BIGINT", "SMALLINT"):
        try:
            return str(int(value))
        except (ValueError, TypeError):
            return "NULL"

    if sql_type in ("DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC"):
        try:
            return str(float(value))
        except (ValueError, TypeError):
            return "NULL"

    if sql_type == "BOOLEAN":
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, str):
            return "TRUE" if value.lower() in ("true", "yes", "1") else "FALSE"
        return "TRUE" if value else "FALSE"

    # String types (VARCHAR, TEXT, JSON, etc.)
    if isinstance(value, (dict, list)):
        # JSON encode
        value = json.dumps(value, default=str)
    else:
        value = str(value)

    # Escape single quotes by doubling them
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def bind_sql_parameters(
    sql_fragment: str,
    args: Dict[str, Any],
    arg_specs: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Bind named parameters in SQL fragment with actual values.

    Replaces :param_name placeholders with properly quoted values.

    Args:
        sql_fragment: SQL fragment with :param placeholders
        args: Dictionary of parameter values
        arg_specs: Optional list of arg specs with type info

    Returns:
        SQL fragment with bound parameters
    """
    result = sql_fragment

    # Build type lookup from arg specs
    type_lookup = {}
    if arg_specs:
        for spec in arg_specs:
            name = spec.get("name")
            sql_type = spec.get("type", "VARCHAR")
            if name:
                type_lookup[name] = sql_type

    # Find all :param_name patterns
    param_pattern = re.compile(r':(\w+)')

    # Replace in reverse order to handle overlapping names correctly
    matches = list(param_pattern.finditer(result))
    for match in reversed(matches):
        param_name = match.group(1)
        if param_name in args:
            sql_type = type_lookup.get(param_name, "VARCHAR")
            quoted = quote_sql_value(args[param_name], sql_type)
            result = result[:match.start()] + quoted + result[match.end():]
        else:
            log.warning(f"[sql_macro] Parameter :{param_name} not found in args")

    return result


def execute_sql_fragment(
    sql_fragment: str,
    return_type: str = "VARCHAR"
) -> Any:
    """
    Execute a SQL fragment and return the result.

    Wraps the fragment in SELECT if needed and executes via DuckDB.

    Args:
        sql_fragment: The SQL expression to execute
        return_type: Expected return type for casting

    Returns:
        The query result
    """
    import duckdb

    sql = sql_fragment.strip()

    # Wrap in SELECT if it's just an expression
    if not sql.upper().startswith("SELECT"):
        sql = f"SELECT {sql}"

    log.debug(f"[sql_macro] Executing: {sql[:200]}...")

    try:
        result = duckdb.sql(sql).fetchone()
        if result is None:
            return None

        value = result[0]

        # Type conversion based on return_type
        return_type = return_type.upper()

        if return_type == "BOOLEAN":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "yes", "1")
            return bool(value)

        if return_type in ("DOUBLE", "FLOAT"):
            if value is None:
                return 0.0
            return float(value)

        if return_type in ("INTEGER", "INT", "BIGINT"):
            if value is None:
                return 0
            return int(value)

        if return_type == "JSON":
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    pass
            return value

        # VARCHAR or other - return as string
        if value is None:
            return None
        return str(value)

    except Exception as e:
        log.error(f"[sql_macro] Execution failed: {e}")
        log.error(f"[sql_macro] SQL was: {sql}")
        raise


# SQL safety patterns - dangerous operations that should be blocked
DANGEROUS_SQL_PATTERNS = [
    (r'\bDROP\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW)\b', "DROP statements"),
    (r'\bTRUNCATE\s+TABLE\b', "TRUNCATE statements"),
    (r'\bDELETE\s+FROM\b', "DELETE statements"),
    (r'\bUPDATE\s+\w+\s+SET\b', "UPDATE statements"),
    (r'\bINSERT\s+INTO\b', "INSERT statements"),
    (r'\bALTER\s+(TABLE|DATABASE|SCHEMA)\b', "ALTER statements"),
    (r'\bCREATE\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW)\b', "CREATE statements"),
    (r'\bGRANT\s+', "GRANT statements"),
    (r'\bREVOKE\s+', "REVOKE statements"),
    (r'\bATTACH\s+', "ATTACH statements"),
    (r'\bDETACH\s+', "DETACH statements"),
    (r'\bCOPY\s+', "COPY statements"),
    (r'\bEXPORT\s+', "EXPORT statements"),
    (r'\bIMPORT\s+', "IMPORT statements"),
    (r'\bLOAD\s+', "LOAD statements"),
    (r'\bINSTALL\s+', "INSTALL extension statements"),
]


class SQLSafetyError(Exception):
    """Raised when SQL statement contains dangerous patterns."""
    pass


def validate_sql_safety(sql: str, allow_writes: bool = False) -> None:
    """
    Validate SQL statement for dangerous patterns.

    Args:
        sql: The SQL statement to validate
        allow_writes: If True, allow INSERT/UPDATE/DELETE (for future use)

    Raises:
        SQLSafetyError: If dangerous patterns are detected
    """
    sql_upper = sql.upper()

    for pattern, description in DANGEROUS_SQL_PATTERNS:
        if re.search(pattern, sql_upper, re.IGNORECASE):
            # Allow writes if explicitly enabled
            if allow_writes and pattern in [
                r'\bDELETE\s+FROM\b',
                r'\bUPDATE\s+\w+\s+SET\b',
                r'\bINSERT\s+INTO\b',
            ]:
                continue
            raise SQLSafetyError(f"SQL statement blocked: {description} not allowed")


def execute_sql_statement(
    sql: str,
    validate_safety: bool = True,
    max_rows: int = 10000,
    connection: Any = None,
) -> List[Dict[str, Any]]:
    """
    Execute a full SQL statement and return table results.

    Unlike execute_sql_fragment (which returns a scalar), this function
    returns multiple rows as a list of dictionaries - suitable for
    sql_statement output_mode where the LLM generates entire queries.

    Args:
        sql: The full SQL statement to execute
        validate_safety: If True, block dangerous SQL patterns
        max_rows: Maximum rows to return (safety limit)
        connection: Optional DuckDB connection to use. If None, tries to get
                   the user's registered connection from caller_context.

    Returns:
        List of dicts, one per row, with column names as keys

    Raises:
        SQLSafetyError: If dangerous patterns detected and validate_safety=True
    """
    import duckdb

    sql = sql.strip()

    # Remove markdown code block markers if LLM wrapped the SQL
    if sql.startswith("```sql"):
        sql = sql[6:]
    if sql.startswith("```"):
        sql = sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    sql = sql.strip()

    # Safety validation
    if validate_safety:
        validate_sql_safety(sql)

    # Ensure it's a SELECT statement
    if not sql.upper().startswith(("SELECT", "WITH")):
        raise SQLSafetyError(
            f"sql_statement mode only allows SELECT/WITH queries, got: {sql[:50]}..."
        )

    log.debug(f"[sql_macro] Executing statement: {sql[:200]}...")

    try:
        # Use run_sql which properly handles connection setup via DatabaseConnector
        # This avoids deadlocks (we don't reuse the busy connection) and properly
        # attaches databases based on sql_connections config
        from rvbbit.sql_tools.tools import run_sql
        from rvbbit.sql_tools.config import load_sql_connections

        # Extract connection name from first qualified table reference (e.g., csv_files.table)
        # Pattern: FROM/JOIN schema.table or FROM/JOIN "schema".table
        connection_name = None
        import re
        # Match: FROM csv_files.table or JOIN csv_files.table (with optional quotes)
        match = re.search(r'(?:FROM|JOIN)\s+["\']?(\w+)["\']?\s*\.', sql, re.IGNORECASE)
        if match:
            connection_name = match.group(1)
            log.debug(f"[sql_macro] Extracted connection name: {connection_name}")

        if connection_name:
            # Verify it's a valid connection
            connections = load_sql_connections()
            if connection_name not in connections:
                log.warning(f"[sql_macro] Connection '{connection_name}' not in config, trying direct execution")
                connection_name = None

        if connection_name:
            # Use run_sql which handles connection setup properly
            # Pass limit=None - run_sql's naive LIMIT append breaks on semicolons
            # The LLM-generated SQL should already have appropriate limits
            result_json = run_sql(sql, connection_name, limit=None)
            result_data = json.loads(result_json)

            if 'error' in result_data and result_data['error']:
                raise Exception(result_data['error'])

            return result_data.get('results', [])
        else:
            # Fallback: direct DuckDB execution (for queries not using attached DBs)
            log.debug("[sql_macro] No connection detected, using direct DuckDB execution")
            result = duckdb.sql(sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchmany(max_rows)
            return [dict(zip(columns, row)) for row in rows]

    except Exception as e:
        log.error(f"[sql_macro] Statement execution failed: {e}")
        log.error(f"[sql_macro] SQL was: {sql}")
        raise


def prepare_cascade_inputs_for_structure_mode(
    args: Dict[str, Any],
    structure_args: List[str]
) -> Dict[str, Any]:
    """
    Prepare cascade inputs for sql_execute mode.

    For args marked as structure_source, we pass the structure (schema)
    instead of the actual value. This lets the LLM generate SQL based
    on structure without seeing actual data.

    Args:
        args: Original function arguments
        structure_args: List of arg names to convert to structure

    Returns:
        Modified args dict for cascade execution
    """
    result = {}

    for arg_name, arg_value in args.items():
        if arg_name in structure_args:
            # Parse JSON if string
            if isinstance(arg_value, str):
                try:
                    arg_value = json.loads(arg_value)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Extract and format structure
            structure = extract_structure(arg_value)
            structure_json = json.dumps(structure, indent=2, sort_keys=True)

            # Pass structure as the arg value (LLM sees schema, not data)
            # Also add a _structure suffix version for explicit access
            result[arg_name] = structure_json
            result[f"{arg_name}_structure"] = structure_json
        else:
            result[arg_name] = arg_value

    return result
