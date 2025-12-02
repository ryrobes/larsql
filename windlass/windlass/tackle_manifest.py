"""
Tackle Manifest - Unified discovery for both Python functions and Cascade tools.
"""
import os
import glob
import json
from typing import Dict, Any
from .tackle import get_registry
from .cascade import load_cascade_config
from .utils import get_tool_schema
from .config import get_config

_tackle_manifest_cache: Dict[str, Any] = None

def get_tackle_manifest(refresh: bool = False) -> Dict[str, Any]:
    """
    Get unified manifest of all available tackle (tools).

    Discovers:
    - Python functions registered in tackle registry
    - Cascade files with inputs_schema (usable as tools)

    Returns dict: {tool_name: {type, description, schema/inputs, path?}}
    """
    global _tackle_manifest_cache

    if not refresh and _tackle_manifest_cache is not None:
        return _tackle_manifest_cache

    manifest = {}

    # 1. Scan Python function tools
    for name, func in get_registry().get_all_tackle().items():
        schema = get_tool_schema(func, name=name)
        manifest[name] = {
            "type": "function",
            "description": func.__doc__ or "",
            "schema": schema
        }

    # 2. Scan cascade directories for cascade tools
    config = get_config()
    for tackle_dir in config.tackle_dirs:
        # Support both absolute and relative paths
        if not os.path.isabs(tackle_dir):
            # Try relative to cwd
            search_path = os.path.join(os.getcwd(), tackle_dir)
            if not os.path.exists(search_path):
                # Try relative to windlass package (for installed package)
                package_dir = os.path.dirname(__file__)
                search_path = os.path.join(package_dir, tackle_dir)
        else:
            search_path = tackle_dir

        if not os.path.exists(search_path):
            continue

        # Find all JSON files
        pattern = os.path.join(search_path, "**/*.json")
        for cascade_path in glob.glob(pattern, recursive=True):
            try:
                cascade_config = load_cascade_config(cascade_path)

                # Only include cascades with inputs_schema (usable as tools)
                if cascade_config.inputs_schema:
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

    _tackle_manifest_cache = manifest
    return manifest

def format_manifest_for_quartermaster(manifest: Dict[str, Any]) -> str:
    """
    Format the manifest into a readable list for the Quartermaster agent.
    """
    lines = ["Available Tackle:\n"]

    for name, info in sorted(manifest.items()):
        tackle_type = info["type"]
        description = info["description"].split("\n")[0]  # First line only
        lines.append(f"- {name} ({tackle_type}): {description}")

    return "\n".join(lines)
