"""
Universal trait executor for SQL trait() operator.

This tool allows calling any registered trait from SQL via the cascade system,
providing full observability and logging.

Usage from SQL:
    SELECT * FROM trait('say', json_object('text', 'Hello world'))
    SELECT * FROM trait('brave_web_search', json_object('query', 'python tutorials'))
"""

import json
from typing import Any, Dict, List, Optional, Union

from .base import simple_eddy
from ..logs import log_message


@simple_eddy
def trait_executor(
    trait_name: str,
    args: Optional[Union[Dict[str, Any], str]] = None
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Execute any registered trait and return its result as a dict.

    This is the backend for the SQL trait() operator. It resolves a trait
    by name from the registry and calls it with the provided arguments.

    Args:
        trait_name: Name of the trait to call (e.g., 'say', 'brave_web_search')
        args: Arguments to pass to the trait. Can be a dict or JSON string.

    Returns:
        Dict containing the trait's result, normalized for JSON table output.
        Always includes '_trait' field with the trait name for debugging.

    Raises:
        ValueError: If trait is not found in registry
    """
    from ..trait_registry import get_trait, get_registry

    log_message(
        None, "system",
        f"trait_executor: calling '{trait_name}'",
        metadata={"trait_name": trait_name, "args": args}
    )

    # Resolve trait
    trait_func = get_trait(trait_name)
    if trait_func is None:
        available = list(get_registry().get_all_traits().keys())
        return {
            "_route": "error",
            "_trait": trait_name,
            "error": f"Trait '{trait_name}' not found",
            "available_traits": available[:20],  # First 20 for hint
            "total_available": len(available)
        }

    # Parse args if JSON string
    if isinstance(args, str):
        try:
            args = json.loads(args) if args else {}
        except json.JSONDecodeError as e:
            return {
                "_route": "error",
                "_trait": trait_name,
                "error": f"Invalid JSON in args: {e}"
            }
    elif args is None:
        args = {}

    # Call the trait
    try:
        result = trait_func(**args)
    except TypeError as e:
        # Likely wrong arguments - provide helpful error
        import inspect
        try:
            sig = inspect.signature(trait_func)
            params = list(sig.parameters.keys())
        except Exception:
            params = ["(unknown)"]

        return {
            "_route": "error",
            "_trait": trait_name,
            "error": f"Argument error: {e}",
            "expected_params": params,
            "provided_args": list(args.keys())
        }
    except Exception as e:
        return {
            "_route": "error",
            "_trait": trait_name,
            "error": f"{type(e).__name__}: {e}"
        }

    # Normalize result for JSON table output (may be dict or list)
    normalized = _normalize_result(result, trait_name)

    # Log completion
    if isinstance(normalized, list):
        log_message(
            None, "system",
            f"trait_executor: '{trait_name}' completed ({len(normalized)} rows)",
            metadata={"trait_name": trait_name, "row_count": len(normalized)}
        )
    else:
        log_message(
            None, "system",
            f"trait_executor: '{trait_name}' completed",
            metadata={"trait_name": trait_name, "result_keys": list(normalized.keys())}
        )

    return normalized


def _normalize_result(result: Any, trait_name: str) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Normalize a trait result for JSON table output.

    Handles various return types:
    - list of dicts: returned as-is (each dict becomes a row, _trait added to each)
    - dict: returned as single-item list (one row)
    - str that's JSON: parsed and handled as above
    - str: wrapped in {"result": str}
    - other: wrapped in {"result": value}

    Returns either a dict (single row) or list of dicts (multiple rows).
    The caller wraps single dicts in a list for JSON array output.
    """
    # Always include trait name for debugging
    base = {"_trait": trait_name}

    if result is None:
        return {**base, "result": None}

    # List of items - each becomes a row
    if isinstance(result, list):
        if not result:
            return {**base, "result": []}
        # Add _trait to each dict item, or wrap non-dicts
        rows = []
        for item in result:
            if isinstance(item, dict):
                rows.append({**base, **item})
            else:
                rows.append({**base, "value": item})
        return rows  # Return list directly - each item becomes a row

    if isinstance(result, dict):
        return {**base, **result}

    if isinstance(result, str):
        # Try to parse as JSON (many traits return JSON strings)
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return {**base, **parsed}
            elif isinstance(parsed, list):
                # Recursively handle parsed list
                return _normalize_result(parsed, trait_name)
            else:
                return {**base, "result": parsed}
        except json.JSONDecodeError:
            # Plain string result
            return {**base, "result": result}

    # Fallback for other types
    return {**base, "result": result}


def list_available_traits() -> List[Dict[str, Any]]:
    """
    List all available traits with their signatures.

    Returns a list of trait info dicts - each becomes a row in SQL output.
    """
    import inspect
    from ..trait_registry import get_registry

    registry = get_registry()
    all_traits = registry.get_all_traits()

    traits_info = []
    for name, func in sorted(all_traits.items()):
        info = {"name": name}

        # Get docstring
        doc = func.__doc__
        if doc:
            # First line only
            info["description"] = doc.strip().split('\n')[0]

        # Get signature
        try:
            sig = inspect.signature(func)
            params = []
            for pname, param in sig.parameters.items():
                if pname.startswith('_'):
                    continue  # Skip internal params
                p = {"name": pname}
                if param.annotation != inspect.Parameter.empty:
                    p["type"] = str(param.annotation.__name__) if hasattr(param.annotation, '__name__') else str(param.annotation)
                if param.default != inspect.Parameter.empty:
                    p["default"] = str(param.default)
                params.append(p)
            info["params"] = params
        except Exception:
            info["params"] = []

        traits_info.append(info)

    return traits_info  # Return list directly - each item becomes a row
