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

    Uses NativeEnvironment to properly evaluate Python expressions and return
    native Python objects (lists, dicts, etc.) instead of string representations.

    Args:
        input_templates: Dict of input_name -> Jinja2 template string
        render_context: Context for Jinja2 rendering (input, state, outputs, etc.)

    Returns:
        Dict of input_name -> rendered value (native Python objects)
    """
    if not input_templates:
        return {}

    from jinja2.nativetypes import NativeEnvironment
    from datetime import datetime
    import re

    # Use NativeEnvironment to get native Python objects from expressions
    jinja_env = NativeEnvironment(autoescape=False)

    # Register common filters
    jinja_env.filters['tojson'] = json.dumps

    # Register common global functions for templates
    jinja_env.globals['now'] = datetime.now
    jinja_env.globals['datetime'] = datetime

    rendered = {}
    for name, value in input_templates.items():
        try:
            if isinstance(value, str) and ('{{' in value or '{%' in value):
                # Remove | tojson from expressions since NativeEnvironment
                # returns native Python objects - tojson would convert to string
                # which then can't be used in Python operations
                processed_value = re.sub(r'\|\s*tojson\s*}}', '}}', value)

                template = jinja_env.from_string(processed_value)
                rendered_value = template.render(**render_context)
                rendered[name] = rendered_value
            else:
                # Not a template, use as-is
                rendered[name] = value

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

    # Inject context for ALL data tools (sql_data, python_data, js_data, clojure_data, rvbbit_data, bash_data, bodybuilder)
    if phase.tool in ("sql_data", "python_data", "js_data", "clojure_data", "rvbbit_data", "bash_data", "bodybuilder"):
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


# =============================================================================
# HITL Screen Execution (Calliope)
# =============================================================================

def execute_hitl_phase(
    phase: CellConfig,
    input_data: Dict[str, Any],
    echo: Any,  # Echo object
    session_id: str,
    trace: Any = None,  # TraceNode
    depth: int = 0
) -> Tuple[Any, Optional[str]]:
    """
    Execute a HITL screen phase - render HTML and block for user response.

    This is deterministic execution (no LLM) - the HTML template is rendered
    directly using Jinja2 and displayed via the checkpoint system.

    Args:
        phase: Phase configuration with hitl field containing HTML/HTMX
        input_data: Input data for the cascade
        echo: Echo object with state/history
        session_id: Current session ID
        trace: Optional TraceNode for logging
        depth: Execution depth (for logging indentation)

    Returns:
        Tuple of (response_dict, next_cell_name)

    The response from the user is stored in echo.state[phase.name] and
    can be used for routing via the response[action] or response[selected] fields.
    """
    from .checkpoints import get_checkpoint_manager, CheckpointType

    indent = "  " * depth

    console.print(f"\n{indent}[bold magenta]📺 HITL Screen: {phase.name}[/bold magenta]")

    # Build render context
    outputs = {}
    for item in echo.lineage:
        output = item.get("output")
        if isinstance(output, dict):
            outputs[item["cell"]] = output

    # Define HITL helper functions for templates
    def route_button(label: str, target: str, **attrs) -> str:
        """Create a button that routes to another cell."""
        attr_str = ' '.join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        return f'<button type="submit" name="_route" value="{target}" {attr_str}>{label}</button>'

    def submit_button(label: str, action: str = None, route: str = None, **attrs) -> str:
        """Create a submit button with action or route."""
        attr_str = ' '.join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        if route:
            return f'<button type="submit" name="_route" value="{route}" {attr_str}>{label}</button>'
        elif action:
            return f'<button type="submit" name="action" value="{action}" {attr_str}>{label}</button>'
        else:
            return f'<button type="submit" {attr_str}>{label}</button>'

    def tabs(items: list, current: str = None) -> str:
        """Create a tab bar. items: [(label, cell_name), ...]"""
        html = '<div class="app-tabs">'
        for item in items:
            if len(item) == 2:
                label, cell = item
                active = cell == current
            elif len(item) == 3:
                label, cell, active = item
            else:
                continue
            active_class = 'active' if active else ''
            html += f'<button type="submit" name="_route" value="{cell}" class="tab {active_class}">{label}</button>'
        html += '</div>'
        return html

    render_context = {
        "input": input_data,
        "state": echo.state,
        "outputs": outputs,
        "lineage": echo.lineage,
        "history": echo.history,
        "session_id": session_id,
        # HITL helper functions
        "route_button": route_button,
        "submit_button": submit_button,
        "tabs": tabs,
    }

    # Render the HITL HTML template
    # Use effective_htmx to support both hitl and htmx keys
    template_content = phase.effective_htmx
    try:
        rendered_html = render_instruction(template_content, render_context)
        console.print(f"{indent}  [dim]HTML template rendered ({len(rendered_html)} chars)[/dim]")
    except Exception as e:
        console.print(f"{indent}  [red]✗ Template rendering failed: {e}[/red]")
        return {"error": f"Template rendering failed: {e}", "_timeout": False}, None

    # Build UI spec compatible with request_decision format
    ui_spec = _build_hitl_ui_spec(
        html=rendered_html,
        title=phase.hitl_title or phase.name,
        description=phase.hitl_description,
    )

    # Create checkpoint
    checkpoint_manager = get_checkpoint_manager()

    # Determine timeout from phase config or default
    timeout_seconds = 3600  # 1 hour default
    if phase.timeout:
        parsed = parse_timeout(phase.timeout)
        if parsed:
            timeout_seconds = int(parsed)

    cascade_id = trace.name if trace else echo.cascade_id if hasattr(echo, 'cascade_id') else "unknown"

    checkpoint = checkpoint_manager.create_checkpoint(
        session_id=session_id,
        cascade_id=cascade_id,
        cell_name=phase.name,
        checkpoint_type=CheckpointType.DECISION,
        phase_output=phase.hitl_description or f"Screen: {phase.name}",
        ui_spec=ui_spec,
        echo_snapshot={},
        timeout_seconds=timeout_seconds,
    )

    console.print(f"{indent}  [cyan]⏳ Waiting for user response (checkpoint: {checkpoint.id[:8]}...)[/cyan]")

    # Block for response
    response = checkpoint_manager.wait_for_response(
        checkpoint_id=checkpoint.id,
        timeout=timeout_seconds,
        poll_interval=0.5,
    )

    if response is None:
        console.print(f"{indent}  [yellow]⚠ No response received (timeout)[/yellow]")
        result = {"error": "No response received (timeout)", "_timeout": True}
    else:
        console.print(f"{indent}  [green]✓ Response received[/green]")

        # Wrap response in consistent format
        if isinstance(response, dict):
            result = response
        else:
            result = {"response": response}

        # Log response preview
        response_preview = str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
        console.print(f"{indent}  [dim]Response: {response_preview}[/dim]")

    # Store response in echo state for downstream phases
    echo.state[phase.name] = result

    # Determine next phase (routing)
    # HITL screens use response["action"] or response["selected"] for routing
    handoffs = phase.handoffs or []
    next_cell = _determine_hitl_routing(result, phase.routing, handoffs)

    if next_cell:
        console.print(f"{indent}  [magenta]→ Routing to: {next_cell}[/magenta]")

    return result, next_cell


def _build_hitl_ui_spec(
    html: str,
    title: str,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build UI spec for HITL cell, matching request_decision format.

    The UI spec structure allows the frontend to render the HITL screen
    using the same components as request_decision.
    """
    sections = []

    if title:
        sections.append({
            "type": "header",
            "text": title,
            "level": 2,
        })

    if description:
        sections.append({
            "type": "text",
            "content": description,
        })

    # Main HTML content
    sections.append({
        "type": "html",
        "content": html,
        "allow_forms": True,
    })

    return {
        "layout": "vertical",
        "title": title,
        "sections": sections,
        "_meta": {
            "type": "hitl_screen",
            "generated_by": "deterministic",
        }
    }


def _determine_hitl_routing(
    result: Dict[str, Any],
    routing_config: Optional[Dict[str, str]],
    handoffs: list
) -> Optional[str]:
    """
    Determine next phase based on HITL response and routing config.

    HITL routing uses these fields from the response (in priority order):
    1. response["action"] - Common for button selections
    2. response["selected"] - Common for card/option selections
    3. response["_route"] - Explicit routing directive

    Args:
        result: The HITL response from the user
        routing_config: Maps response values to handoff targets
        handoffs: List of valid handoff targets

    Returns:
        Name of the next phase, or None if no routing
    """
    # Extract route key from response
    route_key = None

    if isinstance(result, dict):
        # Check common HITL response fields (in priority order)
        route_key = (
            result.get("action") or
            result.get("selected") or
            result.get("_route") or
            (result.get("response", {}).get("action") if isinstance(result.get("response"), dict) else None)
        )

    # If routing config exists, use it
    if routing_config and route_key:
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

    # If multiple handoffs but no routing, try to match route_key to handoff name
    if route_key:
        for handoff in handoffs:
            handoff_name = handoff if isinstance(handoff, str) else handoff.target
            if handoff_name == route_key:
                return handoff_name

    return None
