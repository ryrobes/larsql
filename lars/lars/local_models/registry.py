"""
LocalModelRegistry - LRU cache for loaded transformers pipelines.

Manages model lifecycle, memory usage, and provides efficient model reuse
across multiple tool invocations.
"""

import os
import time
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from transformers import Pipeline

from .device import resolve_device, estimate_model_memory


@dataclass
class LoadedModel:
    """Metadata for a loaded model in the registry."""

    model_id: str
    task: str
    device: str
    pipeline: Any  # transformers.Pipeline
    loaded_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    estimated_memory: int = 0  # bytes
    use_count: int = 0

    def touch(self) -> None:
        """Update last_used timestamp and increment use count."""
        self.last_used = time.time()
        self.use_count += 1


class LocalModelRegistry:
    """
    Singleton registry for caching loaded transformers pipelines.

    Implements LRU eviction based on memory pressure. Models are kept
    in memory between tool invocations to avoid expensive reload times.

    Configuration via environment variables:
        LARS_LOCAL_MODEL_CACHE_SIZE_GB: Max cache size in GB (default: 8)
        LARS_LOCAL_MODEL_DEVICE: Default device (default: auto)
    """

    _instance: Optional["LocalModelRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "LocalModelRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._cache: OrderedDict[str, LoadedModel] = OrderedDict()
        self._cache_lock = threading.Lock()

        # Configuration
        self._max_cache_bytes = int(
            float(os.getenv("LARS_LOCAL_MODEL_CACHE_SIZE_GB", "8")) * 1024**3
        )
        self._current_memory = 0

        self._initialized = True

    def _make_cache_key(self, model_id: str, task: str, device: str) -> str:
        """Generate cache key for a model configuration."""
        return f"{model_id}::{task}::{device}"

    def _evict_if_needed(self, required_memory: int) -> None:
        """Evict oldest models if cache would exceed limit."""
        with self._cache_lock:
            while (
                self._current_memory + required_memory > self._max_cache_bytes
                and self._cache
            ):
                # Remove oldest (first) item
                oldest_key, oldest_model = self._cache.popitem(last=False)
                self._current_memory -= oldest_model.estimated_memory

                # Clean up the pipeline to free memory
                del oldest_model.pipeline
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

    def get_or_load(
        self,
        model_id: str,
        task: str,
        device: str = "auto",
        **model_kwargs: Any,
    ) -> "Pipeline":
        """
        Get a model from cache or load it.

        Args:
            model_id: HuggingFace model ID (e.g., "distilbert/distilbert-base-uncased-finetuned-sst-2-english")
            task: Pipeline task (e.g., "text-classification", "ner", "summarization")
            device: Device to load on ("auto", "cuda", "mps", "cpu")
            **model_kwargs: Additional kwargs passed to pipeline()

        Returns:
            Loaded transformers Pipeline
        """
        resolved_device = resolve_device(device)
        cache_key = self._make_cache_key(model_id, task, resolved_device)

        with self._cache_lock:
            if cache_key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(cache_key)
                loaded = self._cache[cache_key]
                loaded.touch()
                return loaded.pipeline

        # Load the model (outside lock to avoid blocking)
        estimated_memory = estimate_model_memory(model_id, task)
        self._evict_if_needed(estimated_memory)

        pipeline = self._load_pipeline(model_id, task, resolved_device, **model_kwargs)

        with self._cache_lock:
            # Double-check it wasn't loaded by another thread
            if cache_key not in self._cache:
                loaded = LoadedModel(
                    model_id=model_id,
                    task=task,
                    device=resolved_device,
                    pipeline=pipeline,
                    estimated_memory=estimated_memory,
                )
                self._cache[cache_key] = loaded
                self._current_memory += estimated_memory
            else:
                # Another thread loaded it, use that one
                self._cache.move_to_end(cache_key)
                loaded = self._cache[cache_key]
                loaded.touch()
                return loaded.pipeline

        return pipeline

    def _load_pipeline(
        self,
        model_id: str,
        task: str,
        device: str,
        **model_kwargs: Any,
    ) -> "Pipeline":
        """
        Load a transformers pipeline.

        Args:
            model_id: HuggingFace model ID
            task: Pipeline task
            device: Resolved device string
            **model_kwargs: Additional kwargs for pipeline

        Returns:
            Loaded Pipeline instance
        """
        from transformers import pipeline

        # Build kwargs
        kwargs = {
            "task": task,
            "model": model_id,
            **model_kwargs,
        }

        # Handle device assignment
        if device == "cpu":
            kwargs["device"] = -1  # CPU
        elif device.startswith("cuda"):
            if ":" in device:
                kwargs["device"] = int(device.split(":")[1])
            else:
                kwargs["device"] = 0
        elif device == "mps":
            kwargs["device"] = "mps"

        return pipeline(**kwargs)

    def unload(self, model_id: str, task: Optional[str] = None) -> bool:
        """
        Unload a model from the cache.

        Args:
            model_id: Model ID to unload
            task: Optional task to narrow which model to unload

        Returns:
            True if a model was unloaded
        """
        with self._cache_lock:
            to_remove = []
            for key, loaded in self._cache.items():
                if loaded.model_id == model_id:
                    if task is None or loaded.task == task:
                        to_remove.append(key)

            for key in to_remove:
                loaded = self._cache.pop(key)
                self._current_memory -= loaded.estimated_memory
                del loaded.pipeline

            if to_remove:
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

            return len(to_remove) > 0

    def list_loaded(self) -> List[Dict[str, Any]]:
        """
        List all loaded models.

        Returns:
            List of dicts with model info
        """
        with self._cache_lock:
            return [
                {
                    "model_id": loaded.model_id,
                    "task": loaded.task,
                    "device": loaded.device,
                    "loaded_at": loaded.loaded_at,
                    "last_used": loaded.last_used,
                    "use_count": loaded.use_count,
                    "estimated_memory_mb": round(loaded.estimated_memory / (1024**2)),
                }
                for loaded in self._cache.values()
            ]

    def clear(self) -> int:
        """
        Clear all loaded models from cache.

        Returns:
            Number of models cleared
        """
        with self._cache_lock:
            count = len(self._cache)
            for loaded in self._cache.values():
                del loaded.pipeline
            self._cache.clear()
            self._current_memory = 0

            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

            return count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats
        """
        with self._cache_lock:
            return {
                "loaded_models": len(self._cache),
                "current_memory_mb": round(self._current_memory / (1024**2)),
                "max_memory_mb": round(self._max_cache_bytes / (1024**2)),
                "memory_utilization": (
                    round(self._current_memory / self._max_cache_bytes * 100, 1)
                    if self._max_cache_bytes > 0
                    else 0
                ),
            }


def get_model_registry() -> LocalModelRegistry:
    """Get the singleton LocalModelRegistry instance."""
    return LocalModelRegistry()
