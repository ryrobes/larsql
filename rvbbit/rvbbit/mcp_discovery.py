"""
MCP Tool Discovery and Registration

Discovers tools from MCP servers and registers them in trait_registry.

Pattern: Same as Harbor (HuggingFace Spaces) discovery
- Introspect MCP servers
- Extract tool schemas
- Create wrapper functions
- Register in trait_registry
- Tools work like any other RVBBIT tool

Progress messages are logged to unified_logs with role='mcp_progress'.
"""

import inspect
import json
from typing import Any, Dict, List, Optional, Callable
from .mcp_client import (
    MCPClient, MCPServerConfig, MCPTransport, MCPTool, MCPResource, MCPPrompt,
    get_mcp_client
)
from .trait_registry import register_trait
from .config import get_config


# ============================================================================
# Progress Logging to Unified Logs
# ============================================================================

def _create_progress_logger() -> Callable[[str], None]:
    """
    Create a progress callback that logs to unified_logs.

    Returns:
        Callback function that accepts progress message string
    """
    def log_progress(message: str):
        """Log MCP progress message to unified_logs."""
        try:
            from .unified_logs import log_message
            from .caller_context import get_caller_id

            # Try to get current execution context
            # Note: This may be None if tool is called outside cascade execution
            caller_id = get_caller_id()

            # Extract session_id from caller_id (format: "sql-word-word-sessionid" or just sessionid)
            session_id = None
            if caller_id:
                parts = caller_id.split('-')
                session_id = parts[-1] if len(parts) > 1 else caller_id

            # Log with special role for MCP progress
            log_message(
                session_id=session_id or "mcp_tool_call",
                cascade_id="mcp",
                cell_name="mcp_tool",
                role="mcp_progress",
                content=message,
                metadata={"source": "mcp"}
            )
        except Exception:
            # Silently fail if logging not available (e.g., during discovery)
            pass

    return log_progress


# ============================================================================
# Schema Conversion (JSON Schema → Python Signature)
# ============================================================================

def _json_schema_to_python_type(json_type: str, format_hint: Optional[str] = None) -> type:
    """
    Convert JSON Schema type to Python type annotation.

    Args:
        json_type: JSON Schema type ('string', 'integer', 'number', 'boolean', 'array', 'object')
        format_hint: Optional format hint (e.g., 'date-time', 'uri')

    Returns:
        Python type
    """
    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None)
    }
    return type_map.get(json_type, str)


def _build_signature_from_json_schema(input_schema: Dict[str, Any]) -> inspect.Signature:
    """
    Build Python function signature from JSON Schema.

    Args:
        input_schema: JSON Schema object with 'properties' and 'required'

    Returns:
        inspect.Signature for the tool
    """
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])

    params = []
    for param_name, param_schema in properties.items():
        param_type = _json_schema_to_python_type(
            param_schema.get("type", "string"),
            param_schema.get("format")
        )

        # Use default=None for optional parameters
        default = inspect.Parameter.empty if param_name in required else None

        param = inspect.Parameter(
            param_name,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=param_type,
            default=default
        )
        params.append(param)

    return inspect.Signature(params)


# ============================================================================
# Tool Wrapper Creation
# ============================================================================

def _create_mcp_tool_wrapper(
    server_config: MCPServerConfig,
    tool: MCPTool,
    progress_logger: Callable[[str], None]
) -> Callable:
    """
    Create a wrapper function for an MCP tool.

    The wrapper:
    - Accepts keyword arguments matching the tool's input schema
    - Calls the MCP server's tool via MCPClient
    - Logs progress messages to unified_logs
    - Returns the tool result

    Args:
        server_config: MCP server configuration
        tool: MCPTool definition
        progress_logger: Progress callback

    Returns:
        Callable wrapper function
    """
    def mcp_tool_wrapper(**kwargs):
        # Get or create client with progress logging
        client = get_mcp_client(server_config, on_progress=progress_logger)

        # Call the tool
        try:
            result = client.call_tool(tool.name, kwargs)
            return result
        except Exception as e:
            # Log error and re-raise
            progress_logger(f"MCP tool '{tool.name}' failed: {str(e)}")
            raise

    # Set metadata for schema generation
    mcp_tool_wrapper.__name__ = tool.name
    mcp_tool_wrapper.__doc__ = tool.description or f"MCP tool: {tool.name} (server: {server_config.name})"

    # Build signature from JSON Schema
    mcp_tool_wrapper.__signature__ = _build_signature_from_json_schema(tool.input_schema)

    # Attach MCP metadata (for manifest)
    mcp_tool_wrapper._mcp_server = server_config.name
    mcp_tool_wrapper._mcp_tool = tool.name
    mcp_tool_wrapper._tool_type = "mcp"

    return mcp_tool_wrapper


# ============================================================================
# Resource Access Tools
# ============================================================================

def _create_mcp_resource_tools(
    server_config: MCPServerConfig,
    resources: List[MCPResource],
    progress_logger: Callable[[str], None]
):
    """
    Create resource access tools.

    Creates two tools:
    1. mcp_{server_name}_list_resources - List all resources
    2. mcp_{server_name}_read_resource - Read a specific resource by URI

    Args:
        server_config: MCP server configuration
        resources: List of MCPResource definitions
        progress_logger: Progress callback
    """
    server_safe_name = server_config.name.replace("-", "_").replace(".", "_")

    # Tool 1: List resources
    def list_resources_tool() -> str:
        """List all available resources from this MCP server."""
        client = get_mcp_client(server_config, on_progress=progress_logger)
        resources = client.list_resources()

        lines = [f"Available resources from MCP server '{server_config.name}':"]
        for res in resources:
            lines.append(f"- {res.uri}: {res.name}")
            if res.description:
                lines.append(f"  {res.description}")

        return "\n".join(lines)

    list_resources_tool.__name__ = f"mcp_{server_safe_name}_list_resources"
    list_resources_tool._mcp_server = server_config.name
    list_resources_tool._tool_type = "mcp_resource_list"

    register_trait(list_resources_tool.__name__, list_resources_tool)

    # Tool 2: Read resource
    def read_resource_tool(uri: str) -> str:
        """Read a resource from the MCP server by URI."""
        client = get_mcp_client(server_config, on_progress=progress_logger)
        return client.read_resource(uri)

    read_resource_tool.__name__ = f"mcp_{server_safe_name}_read_resource"
    read_resource_tool.__doc__ = f"Read a resource from MCP server '{server_config.name}' by URI"
    read_resource_tool._mcp_server = server_config.name
    read_resource_tool._tool_type = "mcp_resource_read"

    register_trait(read_resource_tool.__name__, read_resource_tool)


# ============================================================================
# Prompt Template Tools
# ============================================================================

def _create_mcp_prompt_tools(
    server_config: MCPServerConfig,
    prompts: List[MCPPrompt],
    progress_logger: Callable[[str], None]
):
    """
    Create prompt template access tools.

    Creates tools for each prompt template.

    Args:
        server_config: MCP server configuration
        prompts: List of MCPPrompt definitions
        progress_logger: Progress callback
    """
    server_safe_name = server_config.name.replace("-", "_").replace(".", "_")

    for prompt in prompts:
        prompt_safe_name = prompt.name.replace("-", "_").replace("/", "_")

        # Build dynamic function for this prompt
        def get_prompt_tool(**kwargs):
            client = get_mcp_client(server_config, on_progress=progress_logger)
            return client.get_prompt(prompt.name, kwargs)

        # Set metadata
        tool_name = f"mcp_{server_safe_name}_prompt_{prompt_safe_name}"
        get_prompt_tool.__name__ = tool_name
        get_prompt_tool.__doc__ = prompt.description or f"MCP prompt: {prompt.name} (server: {server_config.name})"
        get_prompt_tool._mcp_server = server_config.name
        get_prompt_tool._mcp_prompt = prompt.name
        get_prompt_tool._tool_type = "mcp_prompt"

        # Build signature from prompt arguments
        if prompt.arguments:
            params = []
            for arg in prompt.arguments:
                param = inspect.Parameter(
                    arg["name"],
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=str,  # Prompt args are typically strings
                    default=None if arg.get("required") else ""
                )
                params.append(param)
            get_prompt_tool.__signature__ = inspect.Signature(params)

        register_trait(tool_name, get_prompt_tool)


# ============================================================================
# Discovery & Registration
# ============================================================================

def discover_and_register_mcp_tools(server_configs: Optional[List[MCPServerConfig]] = None):
    """
    Discover tools from MCP servers and register in trait_registry.

    This is the main entry point for MCP integration.
    Called by traits_manifest.py during manifest building.

    Args:
        server_configs: Optional list of server configs. If None, loads from global config.
    """
    if server_configs is None:
        config = get_config()
        server_configs = config.mcp_servers

    if not server_configs:
        return

    # Create progress logger
    progress_logger = _create_progress_logger()

    for server_config in server_configs:
        if not server_config.enabled:
            continue

        try:
            # Get client (will connect if needed)
            client = get_mcp_client(server_config, on_progress=progress_logger)

            # Discover tools
            tools = client.list_tools()
            for tool in tools:
                # Create and register wrapper
                wrapper = _create_mcp_tool_wrapper(server_config, tool, progress_logger)
                register_trait(tool.name, wrapper)

            # Discover resources (create resource access tools)
            try:
                resources = client.list_resources()
                if resources:
                    _create_mcp_resource_tools(server_config, resources, progress_logger)
            except Exception:
                # Some servers may not support resources
                pass

            # Discover prompts (create prompt tools)
            try:
                prompts = client.list_prompts()
                if prompts:
                    _create_mcp_prompt_tools(server_config, prompts, progress_logger)
            except Exception:
                # Some servers may not support prompts
                pass

        except Exception as e:
            # Log error but don't fail the entire discovery
            print(f"[MCP Discovery] Failed to discover tools from server '{server_config.name}': {e}")
            continue


def get_mcp_manifest(refresh: bool = False) -> Dict[str, Any]:
    """
    Get manifest of MCP tools (for traits_manifest integration).

    Returns dict mapping tool_name -> {type, server, description, schema, ...}

    Args:
        refresh: Force refresh of MCP server discovery

    Returns:
        Dict of MCP tools in manifest format
    """
    from .trait_registry import get_registry
    from .utils import get_tool_schema

    manifest = {}

    # Get all registered traits
    for name, func in get_registry().get_all_traits().items():
        # Check if this is an MCP tool
        if hasattr(func, '_tool_type') and func._tool_type in ('mcp', 'mcp_resource_list', 'mcp_resource_read', 'mcp_prompt'):
            tool_type = func._tool_type
            server_name = getattr(func, '_mcp_server', 'unknown')

            manifest[name] = {
                "type": tool_type,
                "mcp_server": server_name,
                "description": func.__doc__ or "",
                "schema": get_tool_schema(func, name=name)
            }

    return manifest


def format_mcp_manifest(manifest: Dict[str, Any] = None) -> str:
    """
    Format MCP manifest as human-readable text.

    Args:
        manifest: MCP manifest dict. If None, fetches fresh.

    Returns:
        Formatted string for display
    """
    if manifest is None:
        manifest = get_mcp_manifest()

    if not manifest:
        return "No MCP tools available"

    lines = ["MCP Tools:\n"]
    for name, info in sorted(manifest.items()):
        server = info.get("mcp_server", "unknown")
        tool_type = info.get("type", "mcp")
        desc = info.get("description", "").split("\n")[0]
        lines.append(f"- {name} ({tool_type}, server: {server}): {desc}")

    return "\n".join(lines)
