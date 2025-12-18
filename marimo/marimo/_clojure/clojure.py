# Copyright 2024 Marimo. All rights reserved.
"""Clojure integration for Marimo.

This module provides the `clj()` function for executing Clojure code
within Marimo notebooks, with support for reactive dependencies.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal, Optional, Sequence

from marimo import _loggers
from marimo._clojure.nrepl import get_nrepl_connection, NReplClient, NReplResponse
from marimo._output.rich_help import mddoc
from marimo._runtime.context import ContextNotInitializedError, get_context

LOGGER = _loggers.marimo_logger()


# ============================================================================
# Python <-> Clojure Data Conversion
# ============================================================================

def python_to_edn(value: Any) -> str:
    """Convert a Python value to EDN (Clojure data) string.

    Supports: None, bool, int, float, str, list, dict, tuple, set
    """
    if value is None:
        return "nil"
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, int):
        return str(value)
    elif isinstance(value, float):
        if value != value:  # NaN
            return "##NaN"
        elif value == float('inf'):
            return "##Inf"
        elif value == float('-inf'):
            return "##-Inf"
        return str(value)
    elif isinstance(value, str):
        # Escape string for Clojure
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return f'"{escaped}"'
    elif isinstance(value, (list, tuple)):
        items = " ".join(python_to_edn(item) for item in value)
        return f"[{items}]"
    elif isinstance(value, set):
        items = " ".join(python_to_edn(item) for item in value)
        return f"#{{{items}}}"
    elif isinstance(value, dict):
        pairs = " ".join(
            f"{python_to_edn(k)} {python_to_edn(v)}"
            for k, v in value.items()
        )
        return f"{{{pairs}}}"
    else:
        # Try JSON serialization as fallback
        try:
            return python_to_edn(json.loads(json.dumps(value, default=str)))
        except Exception:
            # Last resort: convert to string
            return python_to_edn(str(value))


def edn_to_python(edn_str: str) -> Any:
    """Convert an EDN string to Python value.

    This is a simplified parser for common EDN values returned by nREPL.
    """
    edn_str = edn_str.strip()

    if not edn_str:
        return None

    # nil
    if edn_str == "nil":
        return None

    # Boolean
    if edn_str == "true":
        return True
    if edn_str == "false":
        return False

    # Special floats
    if edn_str == "##NaN":
        return float('nan')
    if edn_str == "##Inf":
        return float('inf')
    if edn_str == "##-Inf":
        return float('-inf')

    # Integer
    if re.match(r"^-?\d+$", edn_str):
        return int(edn_str)

    # Float (including scientific notation)
    if re.match(r"^-?\d+\.\d*([eE][+-]?\d+)?$", edn_str):
        return float(edn_str)
    if re.match(r"^-?\d+[eE][+-]?\d+$", edn_str):
        return float(edn_str)

    # Ratio (Clojure specific) - convert to float
    ratio_match = re.match(r"^(-?\d+)/(\d+)$", edn_str)
    if ratio_match:
        return int(ratio_match.group(1)) / int(ratio_match.group(2))

    # String
    if edn_str.startswith('"') and edn_str.endswith('"'):
        # Unescape string
        inner = edn_str[1:-1]
        inner = inner.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
        inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner

    # Keyword (Clojure-specific) - convert to string
    if edn_str.startswith(":"):
        return edn_str  # Keep as keyword string

    # Symbol - convert to string
    if re.match(r"^[a-zA-Z_][a-zA-Z0-9_\-\.\*\+\!\?\<\>\=]*$", edn_str):
        return edn_str

    # Vector/List
    if edn_str.startswith("[") and edn_str.endswith("]"):
        return _parse_edn_collection(edn_str[1:-1], list)

    if edn_str.startswith("(") and edn_str.endswith(")"):
        return _parse_edn_collection(edn_str[1:-1], list)

    # Set
    if edn_str.startswith("#{") and edn_str.endswith("}"):
        return _parse_edn_collection(edn_str[2:-1], set)

    # Map
    if edn_str.startswith("{") and edn_str.endswith("}"):
        return _parse_edn_map(edn_str[1:-1])

    # Unknown - return as string
    return edn_str


def _parse_edn_collection(content: str, container_type: type) -> Any:
    """Parse EDN collection content."""
    items = _tokenize_edn(content)
    return container_type(edn_to_python(item) for item in items)


def _parse_edn_map(content: str) -> dict:
    """Parse EDN map content."""
    tokens = _tokenize_edn(content)
    result = {}
    for i in range(0, len(tokens), 2):
        if i + 1 < len(tokens):
            key = edn_to_python(tokens[i])
            value = edn_to_python(tokens[i + 1])
            result[key] = value
    return result


def _tokenize_edn(content: str) -> list[str]:
    """Tokenize EDN content into individual elements."""
    tokens = []
    current = ""
    depth = 0
    in_string = False
    escape_next = False

    for char in content:
        if escape_next:
            current += char
            escape_next = False
            continue

        if char == "\\" and in_string:
            current += char
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            current += char
            continue

        if in_string:
            current += char
            continue

        if char in "([{#":
            if char == "#" and current == "":
                current += char
                continue
            depth += 1
            current += char
        elif char in ")]}":
            depth -= 1
            current += char
            if depth == 0 and current:
                tokens.append(current.strip())
                current = ""
        elif char in " \t\n\r," and depth == 0:
            if current.strip():
                tokens.append(current.strip())
            current = ""
        else:
            current += char

    if current.strip():
        tokens.append(current.strip())

    return tokens


# ============================================================================
# Clojure Execution
# ============================================================================

class ClojureError(Exception):
    """Error raised when Clojure code execution fails."""

    def __init__(self, message: str, clojure_output: str = "", clojure_error: str = ""):
        super().__init__(message)
        self.clojure_output = clojure_output
        self.clojure_error = clojure_error


def _inject_inputs(client: NReplClient, inputs: dict[str, Any]) -> None:
    """Inject Python values into Clojure namespace."""
    for name, value in inputs.items():
        edn_value = python_to_edn(value)
        # Use def to create var in user namespace
        code = f"(def {name} {edn_value})"
        result = client.eval(code)
        if result.is_error:
            raise ClojureError(
                f"Failed to inject input '{name}': {result.err or result.ex}",
                clojure_output=result.out,
                clojure_error=result.err,
            )


def _extract_outputs(client: NReplClient, outputs: Sequence[str]) -> dict[str, Any]:
    """Extract values from Clojure namespace."""
    result = {}
    for name in outputs:
        # Get the value of the var
        response = client.eval(f"(pr-str {name})")
        if response.is_error:
            LOGGER.warning(f"Failed to extract output '{name}': {response.err or response.ex}")
            continue
        if response.value:
            # The value is a string representation, need to parse EDN
            # pr-str returns a quoted string, so we need to unescape it
            edn_str = response.value
            if edn_str.startswith('"') and edn_str.endswith('"'):
                # Unescape the outer quotes from pr-str
                edn_str = edn_str[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            result[name] = edn_to_python(edn_str)
    return result


# Types that can be safely converted to EDN
SERIALIZABLE_TYPES = (type(None), bool, int, float, str, list, tuple, dict, set)


def _is_serializable(value: Any) -> bool:
    """Check if a Python value can be serialized to EDN."""
    if isinstance(value, SERIALIZABLE_TYPES):
        if isinstance(value, dict):
            return all(_is_serializable(k) and _is_serializable(v) for k, v in value.items())
        elif isinstance(value, (list, tuple, set)):
            return all(_is_serializable(item) for item in value)
        return True
    return False


def _get_available_python_vars(glbls: dict[str, Any]) -> dict[str, Any]:
    """Get Python variables that can be injected into Clojure.

    Filters to only include serializable types and non-private names.
    """
    result = {}
    for name, value in glbls.items():
        # Skip private/magic names
        if name.startswith('_'):
            continue
        # Skip modules, functions, classes
        if hasattr(value, '__module__') and callable(value):
            continue
        # Skip if not serializable
        if not _is_serializable(value):
            continue
        result[name] = value
    return result


@mddoc
def clj(
    code: str,
    *,
    inputs: Optional[Sequence[str]] = None,
    outputs: Optional[Sequence[str]] = None,
    auto: bool = False,
    output: bool = True,
) -> Any:
    """
    Execute Clojure code with reactive dependencies.

    This function allows you to write Clojure code in Marimo notebooks with full
    reactivity support. Variables defined in Python cells can be accessed in
    Clojure, and Clojure definitions can be used in subsequent Python cells.

    **Requires**: Clojure CLI tools (`clojure` command) installed.
    An nREPL server will be started automatically if not running.

    Args:
        code: The Clojure code to execute.
        inputs: List of Python variable names to make available in Clojure.
                These create Clojure vars with the same names.
                If `auto=True`, this is auto-detected from the code.
        outputs: List of Clojure var names to export back to Python.
                These become available as Python variables.
                If `auto=True`, this is auto-detected from def/defn forms.
        auto: If True, automatically detect inputs and outputs.
              Inputs are detected by analyzing which symbols in the code
              match available Python variables. Outputs are detected by
              finding def/defn forms in the code.
        output: Whether to display the result in the UI. Defaults to True.

    Returns:
        The result of evaluating the last expression in the Clojure code.

    Example (explicit mode):
        ```python
        # Python cell
        x = 10
        y = 20

        # Clojure cell (explicit inputs/outputs)
        result = mo.clj('''
        (def sum (+ x y))
        (def product (* x y))
        {:sum sum :product product}
        ''', inputs=["x", "y"], outputs=["sum", "product"])

        # Python cell - can now use sum and product
        print(f"Sum: {sum}, Product: {product}")
        ```

    Example (auto mode):
        ```python
        # Python cell
        x = 10
        y = 20

        # Clojure cell (auto-detect inputs/outputs)
        result = mo.clj('''
        (def sum (+ x y))
        (def product (* x y))
        {:sum sum :product product}
        ''', auto=True)

        # Python cell - sum and product are automatically exported
        print(f"Sum: {sum}, Product: {product}")
        ```
    """
    if code is None or code.strip() == "":
        return None

    # Get nREPL connection
    try:
        client = get_nrepl_connection(auto_start=True)
    except Exception as e:
        raise ClojureError(
            f"Failed to connect to nREPL server: {e}\n"
            "Make sure Clojure CLI tools are installed: https://clojure.org/guides/install_clojure"
        ) from e

    # Get marimo context for accessing/setting variables
    try:
        ctx = get_context()
        glbls = ctx.globals
    except ContextNotInitializedError:
        # Running outside marimo context (e.g., testing)
        glbls = {}

    # Auto-detect inputs and outputs if requested
    if auto:
        from marimo._clojure.analyzer import (
            detect_inputs,
            detect_outputs,
            get_namespace_vars,
        )

        # Get available Python vars that can be serialized
        available_vars = _get_available_python_vars(glbls)

        # Detect which Python vars are referenced in the Clojure code
        detected_inputs = detect_inputs(code, set(available_vars.keys()))
        inputs = list(detected_inputs) if not inputs else list(inputs)

        # Detect what will be defined
        detected_outputs = detect_outputs(code)
        outputs = list(detected_outputs) if not outputs else list(outputs)

        LOGGER.debug(f"Auto-detected inputs: {inputs}")
        LOGGER.debug(f"Auto-detected outputs: {outputs}")
    else:
        inputs = list(inputs) if inputs else []
        outputs = list(outputs) if outputs else []

    # Inject input variables from Python into Clojure
    input_values = {}
    for name in inputs:
        if name in glbls:
            value = glbls[name]
            if _is_serializable(value):
                input_values[name] = value
            else:
                LOGGER.warning(f"Input variable '{name}' is not serializable to EDN, skipping")
        else:
            LOGGER.warning(f"Input variable '{name}' not found in Python namespace")

    if input_values:
        _inject_inputs(client, input_values)

    # Get namespace vars before evaluation (for detecting new defs)
    if auto:
        from marimo._clojure.analyzer import get_namespace_vars
        vars_before = get_namespace_vars(client)

    # Execute the Clojure code
    result = client.eval(code)

    # Handle errors
    if result.is_error:
        error_msg = result.err or result.ex or "Unknown Clojure error"
        raise ClojureError(
            f"Clojure evaluation error:\n{error_msg}",
            clojure_output=result.out,
            clojure_error=result.err,
        )

    # Print any stdout from Clojure
    if result.out and output:
        print(result.out, end="")

    # Auto-detect outputs by namespace diff if in auto mode
    if auto:
        from marimo._clojure.analyzer import get_new_definitions_after_eval
        new_defs = get_new_definitions_after_eval(client, vars_before)
        # Merge with statically detected outputs
        outputs = list(set(outputs) | new_defs)
        LOGGER.debug(f"Final outputs after eval: {outputs}")

    # Extract output variables from Clojure to Python
    if outputs:
        output_values = _extract_outputs(client, outputs)
        for name, value in output_values.items():
            glbls[name] = value

    # Parse and return the result
    return_value = None
    if result.value:
        return_value = edn_to_python(result.value)

    # Display result if requested
    if output and return_value is not None:
        from marimo._runtime.output import replace
        from marimo._output.formatting import as_html
        replace(as_html(return_value))

    return return_value
