"""
Semantic SQL - SQL functions backed by LARS cascades.

This package provides:
- Built-in semantic operators (MEANS, ABOUT, MEANING, TOPICS, etc.)
- SQL function registry for cascade-based UDFs
- Query rewriter for operator syntax sugar
- Cascade executor for running cascades from SQL

Philosophy:
    A "Semantic SQL Function" IS a LARS cascade with a `sql_function` key.
    Everything is prompt sugar - operators like MEANS, ABOUT, IMPLIES are just
    syntax that rewrites to cascade invocations with specific argument positions.

    Three shapes:
    - SCALAR: Per-row (single value → single output)
    - ROW: Multi-column per-row (multiple values → single output)
    - AGGREGATE: Collection function (table context → single output)

    Resolution is inside-out like Lisp:
    - Aggregates resolve first (become CTEs)
    - Scalars resolve inline per row
"""

from .registry import (
    get_sql_function_registry,
    register_sql_function,
    get_sql_function,
    list_sql_functions,
    initialize_registry,
    get_operator_patterns,
    SQLFunctionEntry,
)

from .executor import (
    execute_cascade_udf,
    register_cascade_udfs,
    set_use_cascade_udfs,
)

__all__ = [
    # Registry
    "get_sql_function_registry",
    "register_sql_function",
    "get_sql_function",
    "list_sql_functions",
    "initialize_registry",
    "get_operator_patterns",
    "SQLFunctionEntry",
    # Executor
    "execute_cascade_udf",
    "register_cascade_udfs",
    "set_use_cascade_udfs",
]
