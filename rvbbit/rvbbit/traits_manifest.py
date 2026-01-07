"""
Tackle Manifest - Unified discovery for both Python functions and Cascade tools.

Discovers:
- Python functions registered in traits registry
- Cascade files with inputs_schema (usable as tools)
- Declarative tools (.tool.json files)
- Memory banks (conversational memory with RAG search)
- Harbor tools (HuggingFace Spaces via Gradio)
"""
import os
import glob
import json
from typing import Dict, Any
from .trait_registry import get_registry
from .cascade import load_cascade_config
from .utils import get_tool_schema
from .config import get_config

_traits_manifest_cache: Dict[str, Any] = None
_declarative_tools_registered: bool = False
_mcp_tools_registered: bool = False

def get_trait_manifest(refresh: bool = False) -> Dict[str, Any]:
    """
    Get unified manifest of all available traits (tools).

    Discovers:
    - Python functions registered in traits registry
    - Declarative tools (.tool.json files) - shell, http, python, composite
    - Cascade files with inputs_schema (usable as tools)
    - Memory banks (conversational memory with RAG search)

    Returns dict: {tool_name: {type, description, schema/inputs, path?}}
    """
    global _traits_manifest_cache, _declarative_tools_registered

    if not refresh and _traits_manifest_cache is not None:
        return _traits_manifest_cache

    # Ensure declarative tools are registered before scanning
    if not _declarative_tools_registered:
        try:
            from .tool_definitions import discover_and_register_declarative_tools
            discover_and_register_declarative_tools()
            _declarative_tools_registered = True
        except Exception as e:
            # Don't fail if tool discovery has issues
            pass

    manifest = {}

    # 1. Scan Python function tools (includes registered declarative tools)
    for name, func in get_registry().get_all_traits().items():
        schema = get_tool_schema(func, name=name)

        # Check if this is a declarative tool
        tool_type = "function"
        extra_info = {}

        if hasattr(func, '_tool_definition'):
            tool_def = func._tool_definition
            tool_type = f"declarative:{tool_def.type}"
            if hasattr(func, '_source_path'):
                extra_info["path"] = func._source_path

        manifest[name] = {
            "type": tool_type,
            "description": func.__doc__ or "",
            "schema": schema,
            **extra_info
        }

    # 2. Scan cascade directories for cascade tools
    # Import registration function for cascade tools
    from .trait_registry import register_cascade_as_tool, get_trait

    config = get_config()
    for traits_dir in config.traits_dirs:
        # Support both absolute and relative paths
        if not os.path.isabs(traits_dir):
            # Try relative to cwd
            search_path = os.path.join(os.getcwd(), traits_dir)
            if not os.path.exists(search_path):
                # Try relative to rvbbit package (for installed package)
                package_dir = os.path.dirname(__file__)
                search_path = os.path.join(package_dir, traits_dir)
        else:
            search_path = traits_dir

        if not os.path.exists(search_path):
            continue

        # Find all JSON and YAML cascade files
        for ext in ('json', 'yaml', 'yml'):
            pattern = os.path.join(search_path, f"**/*.{ext}")
            for cascade_path in glob.glob(pattern, recursive=True):
                try:
                    cascade_config = load_cascade_config(cascade_path)

                    # Skip cascades without inputs_schema - they can't be called as tools
                    if not cascade_config.inputs_schema:
                        continue

                    # ALWAYS register cascade as callable tool (regardless of manifest visibility)
                    # This ensures cascades can call other cascades even if hidden from Quartermaster
                    if not get_trait(cascade_config.cascade_id):
                        try:
                            register_cascade_as_tool(cascade_path)
                        except Exception as reg_error:
                            # Log but don't fail - tool will be discoverable but not callable
                            pass

                    # Only add to manifest if explicitly marked with manifest: true
                    # This is opt-in - most cascades are internal workflow steps
                    if cascade_config.manifest:
                        # Build parameter description from inputs_schema
                        params_desc = []
                        for param_name, param_desc in cascade_config.inputs_schema.items():
                            params_desc.append(f"  - {param_name}: {param_desc}")

                        full_description = cascade_config.description or f"Cascade tool: {cascade_config.cascade_id}"
                        if params_desc:
                            full_description += f"\n\nParameters:\n" + "\n".join(params_desc)

                        manifest[cascade_config.cascade_id] = {
                            "type": "cascade",
                            "description": full_description,
                            "inputs": cascade_config.inputs_schema,
                            "path": cascade_path
                        }

                except Exception as e:
                    # Skip invalid cascade files
                    continue

    # 3. Scan memory banks
    from .memory import get_memory_system
    try:
        memory_system = get_memory_system()
        for memory_name in memory_system.list_all():
            metadata = memory_system.get_metadata(memory_name)
            summary = metadata.get('summary', f'Conversational memory bank: {memory_name}')

            # Build description with stats
            msg_count = metadata.get('message_count', 0)
            last_updated = metadata.get('last_updated', 'Never')
            cascades_using = metadata.get('cascades_using', [])

            description = f"{summary}\n\nMemory Stats:\n"
            description += f"  - Messages: {msg_count}\n"
            description += f"  - Last updated: {last_updated}\n"
            if cascades_using:
                description += f"  - Used by: {', '.join(cascades_using[:3])}"
                if len(cascades_using) > 3:
                    description += f" (+{len(cascades_using) - 3} more)"

            manifest[memory_name] = {
                "type": "memory",
                "description": description,
                "schema": {
                    "parameters": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 5)",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            }
    except Exception as e:
        # Memory system not available or error occurred
        pass

    # 4. Scan Harbor (HuggingFace Spaces)
    try:
        from .harbor import get_harbor_manifest
        harbor_manifest = get_harbor_manifest()

        for tool_name, tool_info in harbor_manifest.items():
            # Build inputs schema for quartermaster
            inputs = tool_info.get("inputs", {})
            params_desc = []
            for param_name, param_desc in inputs.items():
                params_desc.append(f"  - {param_name}: {param_desc}")

            space = tool_info.get("space", "unknown")
            endpoint = tool_info.get("api_name", "/predict")
            base_desc = f"HuggingFace Space: {space} ({endpoint})"

            if params_desc:
                full_description = base_desc + "\n\nParameters:\n" + "\n".join(params_desc)
            else:
                full_description = base_desc

            manifest[tool_name] = {
                "type": "harbor",
                "description": full_description,
                "space": space,
                "api_name": endpoint,
                "inputs": inputs,
            }
    except Exception as e:
        # Harbor not available or error occurred
        pass

    # 5. Scan MCP (Model Context Protocol) Servers
    global _mcp_tools_registered
    if getattr(config, "mcp_enabled", True) and not _mcp_tools_registered:
        try:
            from .mcp_discovery import discover_and_register_mcp_tools
            discover_and_register_mcp_tools()
            _mcp_tools_registered = True
        except Exception as e:
            # Don't fail if MCP discovery has issues
            print(f"[MCP Discovery] Warning: {e}")
            pass

    if getattr(config, "mcp_enabled", True):
        try:
            from .mcp_discovery import get_mcp_manifest
            mcp_manifest = get_mcp_manifest()

            for tool_name, tool_info in mcp_manifest.items():
                server_name = tool_info.get("mcp_server", "unknown")
                tool_type = tool_info.get("type", "mcp")
                schema = tool_info.get("schema", {})

                # Extract parameter descriptions from schema
                params = schema.get("function", {}).get("parameters", {}).get("properties", {})
                params_desc = []
                for param_name, param_info in params.items():
                    param_type = param_info.get("type", "string")
                    param_desc_text = param_info.get("description", "")
                    params_desc.append(f"  - {param_name} ({param_type}): {param_desc_text}")

                base_desc = tool_info.get("description", "")
                if not base_desc:
                    base_desc = f"MCP tool from server '{server_name}'"

                # Indicate tool type (tool, resource, prompt)
                if tool_type == "mcp_resource_list":
                    base_desc = f"[MCP Resource List] {base_desc}"
                elif tool_type == "mcp_resource_read":
                    base_desc = f"[MCP Resource Read] {base_desc}"
                elif tool_type == "mcp_prompt":
                    base_desc = f"[MCP Prompt] {base_desc}"

                if params_desc:
                    full_description = base_desc + "\n\nParameters:\n" + "\n".join(params_desc)
                else:
                    full_description = base_desc

                manifest[tool_name] = {
                    "type": tool_type,
                    "description": full_description,
                    "mcp_server": server_name,
                    "schema": schema,
                }
        except Exception as e:
            # MCP not available or error occurred
            pass

    _traits_manifest_cache = manifest
    return manifest

def format_manifest_for_quartermaster(manifest: Dict[str, Any]) -> str:
    """
    Format the manifest into a readable list for the Quartermaster agent.
    """
    lines = ["Available Tackle:\n"]

    for name, info in sorted(manifest.items()):
        traits_type = info["type"]
        description = info["description"].split("\n")[0]  # First line only
        lines.append(f"- {name} ({traits_type}): {description}")

    return "\n".join(lines)
