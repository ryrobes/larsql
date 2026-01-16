"""
Local Model Tools - HuggingFace transformers integration for LARS.

This module provides support for running local ML models as first-class tools.
Install with: pip install lars[local-models]

Example usage:
    # Declarative (in .tool.yaml):
    tool_id: sentiment_analyzer
    type: local_model
    model_id: distilbert/distilbert-base-uncased-finetuned-sst-2-english
    task: text-classification
    inputs_schema:
      text: Text to analyze

    # Programmatic:
    from lars.local_models import local_model_tool

    @local_model_tool("distilbert/distilbert-base-uncased-finetuned-sst-2-english", "text-classification")
    def my_sentiment(pipeline, text: str) -> str:
        return pipeline(text)
"""

from typing import TYPE_CHECKING
import importlib.util

# Availability check - use find_spec to avoid actually importing heavy modules
# This saves ~1 second of startup time when torch/transformers are installed
_TRANSFORMERS_AVAILABLE = importlib.util.find_spec("transformers") is not None
_TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


def is_available() -> bool:
    """Check if local model support is available (transformers + torch installed)."""
    return _TRANSFORMERS_AVAILABLE and _TORCH_AVAILABLE


def get_install_instructions() -> str:
    """Get installation instructions for missing dependencies."""
    missing = []
    if not _TRANSFORMERS_AVAILABLE:
        missing.append("transformers")
    if not _TORCH_AVAILABLE:
        missing.append("torch")

    if missing:
        return f"Install missing packages: pip install {' '.join(missing)}\nOr: pip install lars[local-models]"
    return "All dependencies installed."


# Import or provide stubs for all public functions
if is_available():
    from .device import auto_device, get_device_info, resolve_device
    from .registry import LocalModelRegistry, get_model_registry
    from .executor import TransformersExecutor
    from .helpers import local_model_tool
else:
    # Provide stub functions that work for basic queries but raise on actual use
    import os

    def auto_device() -> str:
        """Returns 'cpu' when transformers not available."""
        return "cpu"

    def get_device_info():
        """Returns basic device info when transformers not available."""
        return {
            "current_device": "cpu",
            "cuda_available": False,
            "cuda_device_count": 0,
            "cuda_devices": [],
            "mps_available": False,
            "cpu_count": os.cpu_count() or 1,
            "error": "transformers/torch not installed",
        }

    def resolve_device(device: str) -> str:
        """Returns 'cpu' when transformers not available."""
        return "cpu"

    class LocalModelRegistry:
        """Stub registry when transformers not available."""
        def get_or_load(self, *args, **kwargs):
            raise ImportError("transformers/torch not installed. Run: pip install lars[local-models]")
        def unload(self, *args, **kwargs):
            return False
        def list_loaded(self):
            return []
        def clear(self):
            return 0
        def get_stats(self):
            return {"loaded_models": 0, "current_memory_mb": 0, "max_memory_mb": 0, "memory_utilization": 0}

    _stub_registry = None

    def get_model_registry():
        """Returns stub registry when transformers not available."""
        global _stub_registry
        if _stub_registry is None:
            _stub_registry = LocalModelRegistry()
        return _stub_registry

    class TransformersExecutor:
        """Stub executor when transformers not available."""
        def __init__(self, *args, **kwargs):
            raise ImportError("transformers/torch not installed. Run: pip install lars[local-models]")

    def local_model_tool(*args, **kwargs):
        """Stub decorator when transformers not available."""
        raise ImportError("transformers/torch not installed. Run: pip install lars[local-models]")

__all__ = [
    "is_available",
    "get_install_instructions",
    "auto_device",
    "get_device_info",
    "resolve_device",
    "LocalModelRegistry",
    "get_model_registry",
    "TransformersExecutor",
    "local_model_tool",
]
