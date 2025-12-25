"""
Deterministic phase execution for RVBBIT.

This module handles direct tool execution without LLM mediation,
enabling hybrid workflows that mix deterministic and intelligent phases.
"""

import asyncio
import importlib
import json
import os
import re
import time
from typing import Any, Callable, Dict, Optional, Tuple, Union

from rich.console import Console

from .cascade import CellConfig, RetryConfig
from .prompts import render_instruction
from .trait_registry import get_trait

console = Console()


class DeterministicExecutionError(Exception):
    """Raised when deterministic phase execution fails."""

    def __init__(self, message: str, cell_name: str, tool: str, inputs: Dict = None, original_error: Exception = None):
        super().__init__(message)
        self.cell_name = cell_name
        self.tool = tool
        self.inputs = inputs
        self.original_error = original_error


def parse_tool_target(tool_spec: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Parse a tool specification into its components.

    Supported formats:
    - "tool_name" -> ("registered", "tool_name", None)
    - "python:module.path.function" -> ("python", "module.path", "function")
    - "sql:path/to/query.sql" -> ("sql", "path/to/query.sql", None)
    - "shell:path/to/script.sh" -> ("shell", "path/to/script.sh", None)

    Returns:
        Tuple of (type, target, function_name)
    """
    if tool_spec.startswith("python:"):
        # python:module.path.function
        parts = tool_spec[7:]  # Remove "python:" prefix
        if "." not in parts:
            raise ValueError(f"Invalid Python tool spec: {tool_spec}. Expected 'python:module.path.function'")
        module_path, func_name = parts.rsplit(".", 1)
        return ("python", module_path, func_name)

    elif tool_spec.startswith("sql:"):
        # sql:path/to/query.sql
        return ("sql", tool_spec[4:], None)

    elif tool_spec.startswith("shell:"):
        # shell:path/to/script.sh
        return ("shell", tool_spec[6:], None)

    else:
        # Registered tool name
        return ("registered", tool_spec, None)


def import_python_function(module_path: str, function_name: str) -> Callable:
    """
    Dynamically import a Python function.

    Args:
        module_path: Dot-separated module path (e.g., "mypackage.transforms")
        function_name: Name of the function to import

    Returns:
        The imported function

    Raises:
        ImportError: If module cannot be imported
        AttributeError: If function doesn't exist in module
    """
    try:
        module = importlib.import_module(module_path)
        func = getattr(module, function_name)
        if not callable(func):
            raise TypeError(f"{module_path}.{function_name} is not callable")
        return func
    except ImportError as e:
        raise ImportError(f"Cannot import module '{module_path}': {e}")
    except AttributeError as e:
        raise AttributeError(f"Function '{function_name}' not found in module '{module_path}': {e}")


def resolve_tool_function(tool_spec: str, config_path: str = None) -> Callable:
    """
    Resolve a tool specification to a callable function.

    Args:
        tool_spec: Tool specification string
        config_path: Path to the cascade config (for relative path resolution)

    Returns:
        Callable function ready to execute

    Raises:
        ValueError: If tool cannot be resolved
    """
    tool_type, target, func_name = parse_tool_target(tool_spec)

    if tool_type == "registered":
        # Look up in tackle registry
        func = get_trait(target)
        if func is None:
            raise ValueError(f"Tool '{target}' not found in tackle registry")
        return func

    elif tool_type == "python":
        # Direct Python import
        return import_python_function(target, func_name)

    elif tool_type == "sql":
        # SQL query execution
        # Wrap in a function that executes the query
        def sql_executor(**kwargs) -> Dict[str, Any]:
            from .sql_tools.tools import smart_sql_run

            # Resolve path relative to config
            query_path = target
            if config_path and not os.path.isabs(query_path):
                query_path = os.path.join(os.path.dirname(config_path), query_path)

            # Read query file
            with open(query_path, "r") as f:
                query_template = f.read()

            # Render query with Jinja2
            query = render_instruction(query_template, {"inputs": kwargs})

            # Execute
            result = smart_sql_run(query)
            return {"data": result, "_route": "success"}

        return sql_executor

    elif tool_type == "shell":
        # Shell script execution
        def shell_executor(**kwargs) -> Dict[str, Any]:
            import subprocess

            # Resolve path relative to config
            script_path = target
            if config_path and not os.path.isabs(script_path):
                script_path = os.path.join(os.path.dirname(config_path), script_path)

            # Build environment with inputs
            env = os.environ.copy()
            for key, value in kwargs.items():
                env[f"RVBBIT_{key.upper()}"] = str(value)

            # Execute script
            result = subprocess.run(
                ["bash", script_path],
                capture_output=True,
                text=True,
                env=env,
                timeout=300  # 5 minute default timeout
            )

            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "_route": "success" if result.returncode == 0 else "error"
            }

        return shell_executor

    else:
        raise ValueError(f"Unknown tool type: {tool_type}")


def render_inputs(
    input_templates: Optional[Dict[str, str]],
    render_context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Render Jinja2-templated inputs for a deterministic phase.

    Args:
        input_templates: Dict of input_name -> Jinja2 template string
        render_context: Context for Jinja2 rendering (input, state, outputs, etc.)

    Returns:
        Dict of input_name -> rendered value
    """
    if not input_templates:
        return {}

    rendered = {}
    for name, template in input_templates.items():
        try:
            # Render the template
            rendered_value = render_instruction(template, render_context)

            # Try to parse as JSON if it looks like JSON
            stripped = rendered_value.strip()
            if stripped.startswith(("{", "[", '"')) or stripped in ("true", "false", "null"):
                try:
                    rendered[name] = json.loads(stripped)
                except json.JSONDecodeError:
                    rendered[name] = rendered_value
            else:
                rendered[name] = rendered_value

        except Exception as e:
            raise ValueError(f"Failed to render input '{name}': {e}")

    return rendered


def determine_routing(
    result: Any,
    routing_config: Optional[Dict[str, str]],
    handoffs: list
) -> Optional[str]:
    """
    Determine the next phase based on routing configuration and result.

    Routing is determined by (in order of priority):
    1. result["_route"] if present
    2. result["status"] if present
    3. "success" if no errors occurred
    4. First handoff target if routing not configured

    Args:
        result: The tool execution result
        routing_config: Maps route keys to handoff targets
        handoffs: List of valid handoff targets

    Returns:
        Name of the next phase, or None if no routing
    """
    # Extract route key from result
    route_key = None

    if isinstance(result, dict):
        route_key = result.get("_route") or result.get("status")

    if route_key is None:
        route_key = "success"

    # If routing config exists, use it
    if routing_config:
        if route_key in routing_config:
            return routing_config[route_key]
        # Check for default/fallback
        if "default" in routing_config:
            return routing_config["default"]

    # If single handoff, use it
    if len(handoffs) == 1:
        if isinstance(handoffs[0], str):
            return handoffs[0]
        return handoffs[0].target

    return None


def parse_timeout(timeout_str: Optional[str]) -> Optional[float]:
    """
    Parse timeout string to seconds.

    Supported formats: "30s", "5m", "1h", "1.5h"

    Args:
        timeout_str: Timeout specification string

    Returns:
        Timeout in seconds, or None if not specified
    """
    if not timeout_str:
        return None

    match = re.match(r"^(\d+(?:\.\d+)?)(s|m|h)$", timeout_str.strip())
    if not match:
        raise ValueError(f"Invalid timeout format: {timeout_str}. Use '30s', '5m', or '1h'")

    value = float(match.group(1))
    unit = match.group(2)

    if unit == "s":
        return value
    elif unit == "m":
        return value * 60
    elif unit == "h":
        return value * 3600


async def execute_with_timeout(func: Callable, args: Dict, timeout_seconds: Optional[float]) -> Any:
    """
    Execute a function with optional timeout.

    Handles both sync and async functions.

    Args:
        func: The function to execute
        args: Keyword arguments for the function
        timeout_seconds: Timeout in seconds, or None for no timeout

    Returns:
        Function result

    Raises:
        asyncio.TimeoutError: If execution exceeds timeout
    """
    # Check if function is async
    if asyncio.iscoroutinefunction(func):
        coro = func(**args)
    else:
        # Wrap sync function to run in executor
        loop = asyncio.get_event_loop()
        coro = loop.run_in_executor(None, lambda: func(**args))

    if timeout_seconds:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    else:
        return await coro


def execute_with_retry(
    func: Callable,
    args: Dict,
    retry_config: Optional[RetryConfig],
    timeout_seconds: Optional[float] = None
) -> Any:
    """
    Execute a function with retry logic.

    Args:
        func: The function to execute
        args: Keyword arguments for the function
        retry_config: Retry configuration
        timeout_seconds: Timeout per attempt in seconds

    Returns:
        Function result

    Raises:
        Exception: Last exception if all retries exhausted
    """
    max_attempts = retry_config.max_attempts if retry_config else 1
    last_error = None

    for attempt in range(max_attempts):
        try:
            # For sync execution (most common case)
            if asyncio.iscoroutinefunction(func):
                # If async, need to run in event loop
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(
                        execute_with_timeout(func, args, timeout_seconds)
                    )
                finally:
                    loop.close()
            else:
                # Sync function - direct call
                result = func(**args)

            return result

        except Exception as e:
            last_error = e

            if attempt + 1 < max_attempts:
                # Calculate backoff
                if retry_config and retry_config.backoff != "none":
                    if retry_config.backoff == "linear":
                        sleep_time = retry_config.backoff_base_seconds * (attempt + 1)
                    elif retry_config.backoff == "exponential":
                        sleep_time = retry_config.backoff_base_seconds * (2 ** attempt)
                    else:
                        sleep_time = retry_config.backoff_base_seconds

                    console.print(f"  [yellow]Retry {attempt + 1}/{max_attempts} after {sleep_time:.1f}s...[/yellow]")
                    time.sleep(sleep_time)
                else:
                    console.print(f"  [yellow]Retry {attempt + 1}/{max_attempts}...[/yellow]")

    raise last_error


def execute_deterministic_phase(
    phase: CellConfig,
    input_data: Dict[str, Any],
    echo: Any,  # Echo object
    config_path: str = None,
    depth: int = 0
) -> Tuple[Any, Optional[str]]:
    """
    Execute a deterministic (tool-based) phase.

    This is the main entry point for deterministic phase execution.

    Args:
        phase: Phase configuration
        input_data: Input data for the cascade
        echo: Echo object with state/history
        config_path: Path to cascade config (for relative paths)
        depth: Execution depth (for logging indentation)

    Returns:
        Tuple of (result, next_cell_name)

    Raises:
        DeterministicExecutionError: If execution fails and no error handling configured
    """
    indent = "  " * depth

    console.print(f"\n{indent}[bold blue]⚙️  Deterministic Phase: {phase.name}[/bold blue]")
    console.print(f"{indent}  [dim]Tool: {phase.tool}[/dim]")

    # Resolve the tool function
    try:
        tool_func = resolve_tool_function(phase.tool, config_path)
    except Exception as e:
        raise DeterministicExecutionError(
            f"Failed to resolve tool: {e}",
            cell_name=phase.name,
            tool=phase.tool,
            original_error=e
        )

    # Build render context
    # Filter lineage to only include actual tool outputs (not routing messages)
    # Routing messages are strings like "Dynamically routed to: cell_name"
    outputs = {}
    for item in echo.lineage:
        output = item.get("output")
        # Only include dict outputs (actual tool results), not string routing messages
        if isinstance(output, dict):
            outputs[item["cell"]] = output
    render_context = {
        "input": input_data,
        "state": echo.state,
        "outputs": outputs,
        "lineage": echo.lineage,
        "history": echo.history,
    }

    # Render inputs
    try:
        rendered_inputs = render_inputs(phase.tool_inputs, render_context)
        console.print(f"{indent}  [dim]Inputs: {list(rendered_inputs.keys())}[/dim]")
    except Exception as e:
        raise DeterministicExecutionError(
            f"Failed to render inputs: {e}",
            cell_name=phase.name,
            tool=phase.tool,
            original_error=e
        )

    # Inject context for ALL data tools (sql_data, python_data, js_data, clojure_data, rvbbit_data, bash_data)
    if phase.tool in ("sql_data", "python_data", "js_data", "clojure_data", "rvbbit_data", "bash_data"):
        rendered_inputs["_cell_name"] = phase.name
        rendered_inputs["_session_id"] = echo.session_id

        # Enable materialization by default for sql_data (creates _cell_name temp tables)
        if phase.tool == "sql_data" and "materialize" not in rendered_inputs:
            rendered_inputs["materialize"] = True

        # All polyglot tools need access to outputs and state (not just python_data)
        if phase.tool in ("python_data", "js_data", "clojure_data", "rvbbit_data", "bash_data"):
            rendered_inputs["_outputs"] = outputs  # Dict of cell_name -> output
            rendered_inputs["_state"] = echo.state
            rendered_inputs["_input"] = input_data

    # Parse timeout
    timeout_seconds = parse_timeout(phase.timeout)

    # Execute with retry logic
    start_time = time.time()
    try:
        result = execute_with_retry(
            tool_func,
            rendered_inputs,
            phase.retry,
            timeout_seconds
        )
        duration_ms = (time.time() - start_time) * 1000

        console.print(f"{indent}  [green]✓ Completed in {duration_ms:.0f}ms[/green]")

        # Log result preview
        result_preview = str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
        console.print(f"{indent}  [dim]Result: {result_preview}[/dim]")

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        console.print(f"{indent}  [red]✗ Failed after {duration_ms:.0f}ms: {e}[/red]")

        raise DeterministicExecutionError(
            f"Tool execution failed: {e}",
            cell_name=phase.name,
            tool=phase.tool,
            inputs=rendered_inputs,
            original_error=e
        )

    # Determine next phase (routing)
    handoffs = phase.handoffs or []
    next_cell = determine_routing(result, phase.routing, handoffs)

    if next_cell:
        console.print(f"{indent}  [magenta]→ Routing to: {next_cell}[/magenta]")

    return result, next_cell
