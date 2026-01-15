"""
Universal skill executor for SQL skill() operator.

This tool allows calling any registered skill from SQL via the cascade system,
providing full observability and logging.

Usage from SQL:
    SELECT * FROM skill('say', json_object('text', 'Hello world'))
    SELECT * FROM skill('brave_web_search', json_object('query', 'python tutorials'))
"""

import json
from typing import Any, Dict, List, Optional, Union

from .base import simple_eddy
from ..logs import log_message


@simple_eddy
def skill_executor(
    skill_name: str,
    args: Optional[Union[Dict[str, Any], str]] = None
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Execute any registered skill and return its result as a dict.

    This is the backend for the SQL skill() operator. It resolves a skill
    by name from the registry and calls it with the provided arguments.

    Args:
        skill_name: Name of the skill to call (e.g., 'say', 'brave_web_search')
        args: Arguments to pass to the skill. Can be a dict or JSON string.

    Returns:
        Dict containing the skill's result, normalized for JSON table output.
        Always includes '_skill' field with the skill name for debugging.

    Raises:
        ValueError: If skill is not found in registry
    """
    from ..skill_registry import get_skill, get_registry

    log_message(
        None, "system",
        f"skill_executor: calling '{skill_name}'",
        metadata={"skill_name": skill_name, "args": args}
    )

    # Resolve skill
    skill_func = get_skill(skill_name)
    if skill_func is None:
        available = list(get_registry().get_all_skills().keys())
        return {
            "_route": "error",
            "_skill": skill_name,
            "error": f"Skill '{skill_name}' not found",
            "available_skills": available[:20],  # First 20 for hint
            "total_available": len(available)
        }

    # Parse args if JSON string
    if isinstance(args, str):
        try:
            args = json.loads(args) if args else {}
        except json.JSONDecodeError as e:
            return {
                "_route": "error",
                "_skill": skill_name,
                "error": f"Invalid JSON in args: {e}"
            }
    elif args is None:
        args = {}

    # Call the skill
    try:
        result = skill_func(**args)
    except TypeError as e:
        # Likely wrong arguments - provide helpful error
        import inspect
        try:
            sig = inspect.signature(skill_func)
            params = list(sig.parameters.keys())
        except Exception:
            params = ["(unknown)"]

        return {
            "_route": "error",
            "_skill": skill_name,
            "error": f"Argument error: {e}",
            "expected_params": params,
            "provided_args": list(args.keys())
        }
    except Exception as e:
        return {
            "_route": "error",
            "_skill": skill_name,
            "error": f"{type(e).__name__}: {e}"
        }

    # Normalize result for JSON table output (may be dict or list)
    normalized = _normalize_result(result, skill_name)

    # Log completion
    if isinstance(normalized, list):
        log_message(
            None, "system",
            f"skill_executor: '{skill_name}' completed ({len(normalized)} rows)",
            metadata={"skill_name": skill_name, "row_count": len(normalized)}
        )
    else:
        log_message(
            None, "system",
            f"skill_executor: '{skill_name}' completed",
            metadata={"skill_name": skill_name, "result_keys": list(normalized.keys())}
        )

    return normalized


def _normalize_result(result: Any, skill_name: str) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Normalize a skill result for JSON table output.

    Handles various return types:
    - list of dicts: returned as-is (each dict becomes a row, _skill added to each)
    - dict: returned as single-item list (one row)
    - str that's JSON: parsed and handled as above
    - str: wrapped in {"result": str}
    - other: wrapped in {"result": value}

    Returns either a dict (single row) or list of dicts (multiple rows).
    The caller wraps single dicts in a list for JSON array output.
    """
    # Always include skill name for debugging
    base = {"_skill": skill_name}

    if result is None:
        return {**base, "result": None}

    # List of items - each becomes a row
    if isinstance(result, list):
        if not result:
            return {**base, "result": []}
        # Add _skill to each dict item, or wrap non-dicts
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
        # Try to parse as JSON (many skills return JSON strings)
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return {**base, **parsed}
            elif isinstance(parsed, list):
                # Recursively handle parsed list
                return _normalize_result(parsed, skill_name)
            else:
                return {**base, "result": parsed}
        except json.JSONDecodeError:
            # Plain string result
            return {**base, "result": result}

    # Fallback for other types
    return {**base, "result": result}


def list_available_skills() -> List[Dict[str, Any]]:
    """
    List all available skills from the manifest (tools visible to Quartermaster).

    Returns a list of skill info dicts - each becomes a row in SQL output.
    Only includes tools in the manifest - cascades must have manifest: true to appear.
    """
    import inspect
    from ..skill_registry import get_skill
    from ..skills_manifest import get_skill_manifest

    # Get manifest - this is the filtered list of visible tools
    try:
        manifest = get_skill_manifest(refresh=False)
    except Exception:
        manifest = {}

    skills_info = []
    for name, manifest_entry in sorted(manifest.items()):
        info = {
            "name": name,
            "tool_type": manifest_entry.get("type", "function"),
            "path": manifest_entry.get("path", None),
        }

        # Get description from manifest or function docstring
        description = manifest_entry.get("description", "")
        if description:
            # First line only
            info["description"] = description.strip().split('\n')[0]
        else:
            # Fall back to function docstring
            func = get_skill(name)
            if func and func.__doc__:
                info["description"] = func.__doc__.strip().split('\n')[0]

        # Get signature from function if available
        func = get_skill(name)
        if func:
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
        else:
            # Use inputs from manifest for cascades/etc that aren't in registry
            inputs = manifest_entry.get("inputs", {})
            info["params"] = [{"name": k} for k in inputs.keys()] if inputs else []

        skills_info.append(info)

    return skills_info  # Return list directly - each item becomes a row
