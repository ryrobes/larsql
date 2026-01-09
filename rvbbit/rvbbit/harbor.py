"""
Harbor - HuggingFace Spaces Discovery and Introspection

Discovers user's running HF Spaces and provides introspection capabilities.
Integrates with the traits manifest to make Spaces available as tools.

Usage:
    from rvbbit.harbor import get_harbor_manifest, introspect_space, list_user_spaces

    # List user's spaces
    spaces = list_user_spaces()

    # Introspect a specific space
    api_info = introspect_space("user/space-name")

    # Get manifest of available HF Spaces as tools
    manifest = get_harbor_manifest()

    # Get all spaces with cost estimates
    spaces = list_all_user_spaces()
"""

import os
import json
import time
from typing import Dict, Any, List, Optional
from functools import lru_cache
from dataclasses import dataclass, field

from .config import get_config


# HuggingFace Spaces hardware pricing (USD per hour)
# Source: https://huggingface.co/docs/hub/en/spaces-gpus
HARDWARE_PRICING: Dict[str, float] = {
    "cpu-basic": 0.00,      # Free
    "cpu-upgrade": 0.03,
    "t4-small": 0.40,
    "t4-medium": 0.60,
    "l4x1": 0.80,
    "l4x4": 3.80,
    "l40s-1x": 1.80,
    "l40s-4x": 8.30,
    "l40s-8x": 23.50,
    "a10g-small": 1.00,
    "a10g-large": 1.50,
    "a10g-largex2": 3.00,
    "a10g-largex4": 5.00,
    "a100-large": 2.50,
    "h100": 4.50,
    "h100x8": 36.00,
}

# Hardware display names
HARDWARE_DISPLAY: Dict[str, str] = {
    "cpu-basic": "CPU Basic (Free)",
    "cpu-upgrade": "CPU Upgrade",
    "t4-small": "T4 Small",
    "t4-medium": "T4 Medium",
    "l4x1": "L4 x1",
    "l4x4": "L4 x4",
    "l40s-1x": "L40S x1",
    "l40s-4x": "L40S x4",
    "l40s-8x": "L40S x8",
    "a10g-small": "A10G Small",
    "a10g-large": "A10G Large",
    "a10g-largex2": "A10G Large x2",
    "a10g-largex4": "A10G Large x4",
    "a100-large": "A100 Large",
    "h100": "H100",
    "h100x8": "H100 x8",
}


def get_hardware_cost(hardware: str) -> float:
    """Get hourly cost for a hardware tier."""
    if not hardware:
        return 0.0
    # Normalize hardware name (handle variations)
    hw_lower = hardware.lower().replace("_", "-").replace(" ", "-")
    return HARDWARE_PRICING.get(hw_lower, 0.0)


def get_hardware_display(hardware: str) -> str:
    """Get display name for hardware tier."""
    if not hardware:
        return "Unknown"
    hw_lower = hardware.lower().replace("_", "-").replace(" ", "-")
    return HARDWARE_DISPLAY.get(hw_lower, hardware)


@dataclass
class SpaceInfo:
    """Information about an HF Space."""
    id: str
    author: str
    name: str
    status: str  # RUNNING, SLEEPING, BUILDING, PAUSED, STOPPED, RUNTIME_ERROR
    sdk: Optional[str]  # gradio, streamlit, docker, static
    hardware: Optional[str]
    url: Optional[str]
    private: bool = False
    sleep_time: Optional[int] = None  # seconds until auto-sleep
    requested_hardware: Optional[str] = None

    @property
    def hourly_cost(self) -> float:
        """Estimated hourly cost based on hardware."""
        return get_hardware_cost(self.hardware)

    @property
    def hardware_display(self) -> str:
        """Human-readable hardware name."""
        return get_hardware_display(self.hardware)

    @property
    def is_billable(self) -> bool:
        """True if currently incurring charges."""
        return self.status in ("RUNNING", "STARTING") and self.hourly_cost > 0

    @property
    def is_callable(self) -> bool:
        """True if can be called via Harbor (Gradio + running)."""
        return self.sdk == "gradio" and self.status == "RUNNING"

    @property
    def status_emoji(self) -> str:
        """Emoji indicator for status."""
        return {
            "RUNNING": "🟢",
            "SLEEPING": "😴",
            "BUILDING": "🔨",
            "PAUSED": "⏸️",
            "STOPPED": "⏹️",
            "RUNTIME_ERROR": "❌",
            "STARTING": "🚀",
        }.get(self.status, "❓")


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


def list_all_user_spaces(author: str | None = None) -> List[SpaceInfo]:
    """
    List ALL HuggingFace Spaces owned by the user (all SDKs, all statuses).

    This is useful for a dashboard view showing everything including
    sleeping, paused, and non-Gradio spaces.

    Args:
        author: Filter by author. If None, uses the authenticated user.

    Returns:
        List of SpaceInfo objects with full details.
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
                sleep_time = runtime.sleep_time if runtime else None
                requested_hardware = runtime.requested_hardware if runtime else None
            except Exception:
                status = "UNKNOWN"
                hardware = None
                sleep_time = None
                requested_hardware = None

            spaces.append(SpaceInfo(
                id=space.id,
                author=author,
                name=space.id.split("/")[-1] if "/" in space.id else space.id,
                status=status,
                sdk=space.sdk,
                hardware=hardware,
                url=f"https://huggingface.co/spaces/{space.id}",
                private=space.private if hasattr(space, 'private') else False,
                sleep_time=sleep_time,
                requested_hardware=requested_hardware
            ))

        return spaces

    except Exception as e:
        return []


def list_user_spaces(author: str | None = None, include_sleeping: bool = False) -> List[SpaceInfo]:
    """
    List HuggingFace Gradio Spaces owned by the user (or specified author).

    This is the filtered version for Harbor tool discovery - only returns
    Gradio spaces that can be introspected and called.

    Args:
        author: Filter by author. If None, uses the authenticated user.
        include_sleeping: Include spaces that are sleeping/paused.

    Returns:
        List of SpaceInfo objects (Gradio only).
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
            # Only include Gradio spaces (we can't introspect streamlit/docker easily)
            if space.sdk != "gradio":
                continue

            # Get runtime status
            try:
                runtime = api.get_space_runtime(space.id)
                status = runtime.stage if runtime else "UNKNOWN"
                hardware = runtime.hardware if runtime else None
                sleep_time = runtime.sleep_time if runtime else None
                requested_hardware = runtime.requested_hardware if runtime else None
            except Exception:
                status = "UNKNOWN"
                hardware = None
                sleep_time = None
                requested_hardware = None

            # Filter out sleeping if not requested
            if not include_sleeping and status in ("SLEEPING", "PAUSED"):
                continue

            spaces.append(SpaceInfo(
                id=space.id,
                author=author,
                name=space.id.split("/")[-1] if "/" in space.id else space.id,
                status=status,
                sdk=space.sdk,
                hardware=hardware,
                url=f"https://huggingface.co/spaces/{space.id}",
                private=space.private if hasattr(space, 'private') else False,
                sleep_time=sleep_time,
                requested_hardware=requested_hardware
            ))

        return spaces

    except Exception as e:
        # Don't fail if HF API is unavailable
        return []


def get_spaces_summary(author: str | None = None) -> Dict[str, Any]:
    """
    Get a summary of all user's spaces with cost estimates.

    Useful for dashboard display.

    Returns:
        Dict with:
        - spaces: List of all SpaceInfo objects
        - summary: {
            total: int,
            running: int,
            sleeping: int,
            callable: int (Gradio + running),
            estimated_hourly_cost: float,
            by_status: {status: count},
            by_sdk: {sdk: count}
          }
    """
    spaces = list_all_user_spaces(author=author)

    # Calculate summary stats
    running = sum(1 for s in spaces if s.status == "RUNNING")
    sleeping = sum(1 for s in spaces if s.status == "SLEEPING")
    callable_count = sum(1 for s in spaces if s.is_callable)
    hourly_cost = sum(s.hourly_cost for s in spaces if s.status == "RUNNING")

    # Group by status
    by_status: Dict[str, int] = {}
    for s in spaces:
        by_status[s.status] = by_status.get(s.status, 0) + 1

    # Group by SDK
    by_sdk: Dict[str, int] = {}
    for s in spaces:
        sdk = s.sdk or "unknown"
        by_sdk[sdk] = by_sdk.get(sdk, 0) + 1

    return {
        "spaces": spaces,
        "summary": {
            "total": len(spaces),
            "running": running,
            "sleeping": sleeping,
            "callable": callable_count,
            "estimated_hourly_cost": hourly_cost,
            "by_status": by_status,
            "by_sdk": by_sdk,
        }
    }


def pause_space(space_id: str) -> tuple[bool, str]:
    """
    Pause a running HF Space (stops billing).

    Args:
        space_id: HF Space ID

    Returns:
        Tuple of (success, error_message). error_message is empty on success.
    """
    try:
        api = _get_hf_api()
        api.pause_space(space_id)
        return True, ""
    except Exception as e:
        return False, str(e)


def set_space_sleep_time(space_id: str, sleep_time: int) -> bool:
    """
    Set auto-sleep time for a Space.

    Args:
        space_id: HF Space ID
        sleep_time: Seconds until auto-sleep (0 = never sleep)

    Returns:
        True if successful.
    """
    try:
        api = _get_hf_api()
        api.set_space_sleep_time(space_id, sleep_time)
        return True
    except Exception as e:
        return False


def introspect_space(space_id: str, cache_ttl: int | None = None) -> Dict[str, Any]:
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
    a format compatible with the traits manifest.

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


def format_harbor_manifest(manifest: Dict[str, Any] | None = None) -> str:
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


def export_tool_definition(space_id: str, api_name: str | None = None, tool_id: str | None = None) -> Dict[str, Any]:
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


def wake_space(space_id: str) -> tuple[bool, str]:
    """
    Wake up a sleeping HF Space.

    Args:
        space_id: HF Space ID

    Returns:
        Tuple of (success, error_message). error_message is empty on success.
    """
    try:
        api = _get_hf_api()
        # Restart the space to wake it up
        api.restart_space(space_id)
        return True, ""
    except Exception as e:
        return False, str(e)
