"""
Harbor - HuggingFace Spaces Discovery and Introspection

Discovers user's running HF Spaces and provides introspection capabilities.
Integrates with the tackle manifest to make Spaces available as tools.

Usage:
    from windlass.harbor import get_harbor_manifest, introspect_space, list_user_spaces

    # List user's spaces
    spaces = list_user_spaces()

    # Introspect a specific space
    api_info = introspect_space("user/space-name")

    # Get manifest of available HF Spaces as tools
    manifest = get_harbor_manifest()
"""

import os
import json
import time
from typing import Dict, Any, List, Optional
from functools import lru_cache
from dataclasses import dataclass

from .config import get_config


@dataclass
class SpaceInfo:
    """Information about an HF Space."""
    id: str
    author: str
    name: str
    status: str  # RUNNING, SLEEPING, BUILDING, etc.
    sdk: Optional[str]  # gradio, streamlit, docker, static
    hardware: Optional[str]
    url: Optional[str]
    private: bool = False


@dataclass
class EndpointInfo:
    """Information about a Gradio endpoint."""
    name: str
    parameters: Dict[str, Dict[str, Any]]  # param_name -> {type, description, default, ...}
    returns: Dict[str, Any]


def _get_hf_api():
    """Get an authenticated HfApi client."""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise ImportError("huggingface_hub package not installed. Run: pip install huggingface_hub")

    config = get_config()
    return HfApi(token=config.hf_token)


def _get_gradio_client(space_id: str):
    """Get a Gradio client for a space."""
    try:
        from gradio_client import Client
    except ImportError:
        raise ImportError("gradio_client package not installed. Run: pip install gradio_client")

    config = get_config()
    return Client(space_id, token=config.hf_token)


def list_user_spaces(author: str = None, include_sleeping: bool = False) -> List[SpaceInfo]:
    """
    List HuggingFace Spaces owned by the user (or specified author).

    Args:
        author: Filter by author. If None, uses the authenticated user.
        include_sleeping: Include spaces that are sleeping/paused.

    Returns:
        List of SpaceInfo objects.
    """
    config = get_config()

    if not config.hf_token:
        return []

    try:
        api = _get_hf_api()

        # Get current user if no author specified
        if author is None:
            try:
                whoami = api.whoami()
                author = whoami.get("name")
            except Exception:
                return []

        spaces = []

        for space in api.list_spaces(author=author):
            # Get runtime status
            try:
                runtime = api.get_space_runtime(space.id)
                status = runtime.stage if runtime else "UNKNOWN"
                hardware = runtime.hardware if runtime else None
            except Exception:
                status = "UNKNOWN"
                hardware = None

            # Filter out sleeping if not requested
            if not include_sleeping and status in ("SLEEPING", "PAUSED"):
                continue

            # Only include Gradio spaces (we can't introspect streamlit/docker easily)
            if space.sdk != "gradio":
                continue

            spaces.append(SpaceInfo(
                id=space.id,
                author=author,
                name=space.id.split("/")[-1] if "/" in space.id else space.id,
                status=status,
                sdk=space.sdk,
                hardware=hardware,
                url=f"https://huggingface.co/spaces/{space.id}",
                private=space.private if hasattr(space, 'private') else False
            ))

        return spaces

    except Exception as e:
        # Don't fail if HF API is unavailable
        return []


def introspect_space(space_id: str, cache_ttl: int = None) -> Dict[str, Any]:
    """
    Introspect a Gradio space to get its API endpoints and parameters.

    Args:
        space_id: HF Space ID (e.g., "user/space-name")
        cache_ttl: Cache TTL in seconds. If None, uses config default.

    Returns:
        Dict with endpoints info from view_api().
    """
    config = get_config()
    cache_ttl = cache_ttl or config.harbor_cache_ttl

    # Use time-bucket caching
    bucket = int(time.time() // cache_ttl)
    return _cached_introspect(space_id, bucket)


@lru_cache(maxsize=100)
def _cached_introspect(space_id: str, time_bucket: int) -> Dict[str, Any]:
    """Cached introspection (time_bucket for TTL)."""
    client = _get_gradio_client(space_id)
    return client.view_api(return_format="dict")


def get_space_endpoints(space_id: str) -> List[EndpointInfo]:
    """
    Get structured endpoint information for a space.

    Args:
        space_id: HF Space ID

    Returns:
        List of EndpointInfo objects.
    """
    api_info = introspect_space(space_id)

    endpoints = []

    # Parse the named_endpoints from view_api result
    named_endpoints = api_info.get("named_endpoints", {})

    for endpoint_name, endpoint_data in named_endpoints.items():
        parameters = {}

        # Parse parameters
        for param in endpoint_data.get("parameters", []):
            param_name = param.get("parameter_name", param.get("label", "unknown"))
            parameters[param_name] = {
                "type": param.get("python_type", {}).get("type", "Any"),
                "description": param.get("label", ""),
                "component": param.get("component", ""),
            }

        # Parse returns
        returns = {}
        for ret in endpoint_data.get("returns", []):
            ret_name = ret.get("label", "output")
            returns[ret_name] = {
                "type": ret.get("python_type", {}).get("type", "Any"),
                "component": ret.get("component", ""),
            }

        endpoints.append(EndpointInfo(
            name=endpoint_name,
            parameters=parameters,
            returns=returns
        ))

    return endpoints


def get_harbor_manifest(refresh: bool = False) -> Dict[str, Any]:
    """
    Get manifest of available HF Spaces as tools.

    Auto-discovers user's running Gradio spaces and returns them in
    a format compatible with the tackle manifest.

    Args:
        refresh: Force refresh of cached data.

    Returns:
        Dict mapping tool_name -> {type, space, api_name, description, inputs, ...}
    """
    config = get_config()

    if not config.harbor_enabled or not config.hf_token:
        return {}

    if not config.harbor_auto_discover:
        return {}

    manifest = {}

    try:
        # Get user's running Gradio spaces
        spaces = list_user_spaces(include_sleeping=False)

        for space in spaces:
            if space.status != "RUNNING":
                continue

            try:
                # Introspect the space
                endpoints = get_space_endpoints(space.id)

                for endpoint in endpoints:
                    # Generate tool name: hf_author_spacename_endpoint
                    safe_space = space.id.replace("/", "_").replace("-", "_")
                    safe_endpoint = endpoint.name.strip("/").replace("/", "_")
                    tool_name = f"hf_{safe_space}_{safe_endpoint}" if safe_endpoint else f"hf_{safe_space}"

                    # Build inputs schema from parameters
                    inputs_schema = {}
                    for param_name, param_info in endpoint.parameters.items():
                        inputs_schema[param_name] = f"{param_info.get('description', param_name)} ({param_info.get('type', 'Any')})"

                    manifest[tool_name] = {
                        "type": "harbor",
                        "space": space.id,
                        "api_name": endpoint.name,
                        "description": f"HF Space: {space.id} - endpoint {endpoint.name}",
                        "inputs": inputs_schema,
                        "returns": endpoint.returns,
                        "hardware": space.hardware,
                        "private": space.private,
                    }

            except Exception as e:
                # Skip spaces that fail introspection
                continue

        return manifest

    except Exception as e:
        return {}


def format_harbor_manifest(manifest: Dict[str, Any] = None) -> str:
    """
    Format harbor manifest as human-readable text.

    Args:
        manifest: Harbor manifest dict. If None, fetches fresh.

    Returns:
        Formatted string for display.
    """
    if manifest is None:
        manifest = get_harbor_manifest()

    if not manifest:
        return "No HF Spaces available (check HF_TOKEN and running spaces)"

    lines = ["HuggingFace Spaces (Harbor):", ""]

    for tool_name, info in sorted(manifest.items()):
        space = info.get("space", "unknown")
        endpoint = info.get("api_name", "/predict")
        private = " [private]" if info.get("private") else ""
        hardware = f" ({info.get('hardware')})" if info.get("hardware") else ""

        lines.append(f"  {tool_name}")
        lines.append(f"    Space: {space}{private}{hardware}")
        lines.append(f"    Endpoint: {endpoint}")

        inputs = info.get("inputs", {})
        if inputs:
            lines.append("    Inputs:")
            for param, desc in inputs.items():
                lines.append(f"      - {param}: {desc}")

        lines.append("")

    return "\n".join(lines)


def export_tool_definition(space_id: str, api_name: str = None, tool_id: str = None) -> Dict[str, Any]:
    """
    Generate a .tool.json definition from a Space's API.

    Args:
        space_id: HF Space ID
        api_name: Specific endpoint (default: first endpoint)
        tool_id: Custom tool ID (default: derived from space)

    Returns:
        Dict suitable for writing to a .tool.json file.
    """
    endpoints = get_space_endpoints(space_id)

    if not endpoints:
        raise ValueError(f"No endpoints found for space {space_id}")

    # Find the requested endpoint
    if api_name:
        endpoint = next((e for e in endpoints if e.name == api_name), None)
        if not endpoint:
            raise ValueError(f"Endpoint {api_name} not found in {space_id}")
    else:
        endpoint = endpoints[0]

    # Generate tool ID if not provided
    if not tool_id:
        safe_space = space_id.replace("/", "_").replace("-", "_")
        safe_endpoint = endpoint.name.strip("/").replace("/", "_")
        tool_id = f"{safe_space}_{safe_endpoint}" if safe_endpoint else safe_space

    # Build inputs schema
    inputs_schema = {}
    for param_name, param_info in endpoint.parameters.items():
        inputs_schema[param_name] = param_info.get("description", param_name)

    return {
        "tool_id": tool_id,
        "description": f"Call {space_id} {endpoint.name} endpoint",
        "type": "gradio",
        "space": space_id,
        "api_name": endpoint.name,
        "inputs_schema": inputs_schema,
        "timeout": 60
    }


def wake_space(space_id: str) -> bool:
    """
    Wake up a sleeping HF Space.

    Args:
        space_id: HF Space ID

    Returns:
        True if wake request was sent successfully.
    """
    try:
        api = _get_hf_api()
        # Restart the space to wake it up
        api.restart_space(space_id)
        return True
    except Exception as e:
        return False
