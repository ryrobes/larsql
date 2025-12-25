"""
OpenRouter Model Registry

Dynamic model discovery with 24-hour caching.
Automatically detects image generation models based on output_modalities.

Usage:
    from .model_registry import ModelRegistry

    # Check if a model generates images
    if ModelRegistry.is_image_output_model("google/gemini-2.5-flash-image"):
        # Route to image generation path

    # Get model metadata
    model = ModelRegistry.get_model("openai/gpt-5-image")
    print(model.name, model.description)

    # Get all image generation models (for palette)
    image_models = ModelRegistry.get_image_output_models()
"""

import os
import json
import time
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Metadata for a single model from OpenRouter."""
    id: str
    name: str
    description: str = ""
    modality: str = ""  # e.g., "text+image->text+image"
    input_modalities: List[str] = field(default_factory=list)  # e.g., ["text", "image"]
    output_modalities: List[str] = field(default_factory=list)  # e.g., ["text", "image"]
    context_length: int = 0
    pricing: Dict[str, Any] = field(default_factory=dict)
    top_provider: Dict[str, Any] = field(default_factory=dict)

    # Derived properties
    @property
    def can_output_images(self) -> bool:
        """Whether this model can generate images."""
        return "image" in self.output_modalities

    @property
    def can_input_images(self) -> bool:
        """Whether this model can accept image input (vision)."""
        return "image" in self.input_modalities

    @property
    def provider(self) -> str:
        """Extract provider from model ID (e.g., 'google' from 'google/gemini-2.5-flash')."""
        return self.id.split("/")[0] if "/" in self.id else ""

    @property
    def short_name(self) -> str:
        """Extract short name from model ID."""
        return self.id.split("/")[1] if "/" in self.id else self.id

    @property
    def is_local(self) -> bool:
        """Whether this is a local Ollama model."""
        return self.top_provider.get("is_local", False) or self.id.startswith("ollama/")


class ModelRegistry:
    """
    Registry of OpenRouter models with caching.

    Fetches model metadata from OpenRouter API and caches for 24 hours.
    Provides efficient lookups for model capabilities.
    """

    _instance = None
    _lock = threading.Lock()

    # Cache settings
    CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours
    CACHE_FILE = ".openrouter_models_cache.json"

    # Known unlisted image generation models
    # These work but don't appear in /models endpoint
    # NOTE: Defunct models removed 2025-12 after verification via /models/{id}/endpoints API:
    #   - black-forest-labs/flux-1-schnell (404)
    #   - black-forest-labs/flux-1-dev (404)
    #   - stability/sdxl (404)
    #   - stabilityai/stable-diffusion-xl (404)
    UNLISTED_IMAGE_MODELS = [
        # Black Forest Labs FLUX.2 models (verified active)
        "black-forest-labs/flux.2-max",
        "black-forest-labs/flux.2-pro",
        "black-forest-labs/flux.2-flex",
        # Sourceful Riverflow V2 models (verified active)
        "sourceful/riverflow-v2-max-preview",
        "sourceful/riverflow-v2-standard-preview",
        "sourceful/riverflow-v2-fast-preview",
    ]

    def __init__(self):
        self._models: Dict[str, ModelInfo] = {}
        self._image_output_models: set = set()
        self._last_fetch: float = 0
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "ModelRegistry":
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = ModelRegistry()
        return cls._instance

    def _get_cache_path(self) -> Path:
        """Get path to cache file in data directory."""
        from .config import get_config
        config = get_config()
        return Path(config.data_dir) / self.CACHE_FILE

    def _load_cache(self) -> bool:
        """Load cached models from disk. Returns True if valid cache found."""
        cache_path = self._get_cache_path()

        if not cache_path.exists():
            return False

        try:
            with open(cache_path, "r") as f:
                cache = json.load(f)

            # Check if cache is still valid
            cached_at = cache.get("cached_at", 0)
            if time.time() - cached_at > self.CACHE_TTL_SECONDS:
                logger.debug("Model cache expired")
                return False

            # Load models from cache
            models_data = cache.get("models", [])
            self._models = {}
            self._image_output_models = set()

            for m in models_data:
                model = ModelInfo(
                    id=m["id"],
                    name=m.get("name", m["id"]),
                    description=m.get("description", ""),
                    modality=m.get("modality", ""),
                    input_modalities=m.get("input_modalities", []),
                    output_modalities=m.get("output_modalities", []),
                    context_length=m.get("context_length", 0),
                    pricing=m.get("pricing", {}),
                    top_provider=m.get("top_provider", {}),
                )
                self._models[model.id] = model
                if model.can_output_images:
                    self._image_output_models.add(model.id)

            # Add unlisted models to the image set AND create placeholder ModelInfo
            for model_id in self.UNLISTED_IMAGE_MODELS:
                self._image_output_models.add(model_id)
                if model_id not in self._models:
                    self._models[model_id] = ModelInfo(
                        id=model_id,
                        name=model_id.split("/")[-1].replace("-", " ").title(),
                        description="Image generation model (unlisted)",
                        output_modalities=["image"],
                        input_modalities=["text"],
                    )

            self._last_fetch = cached_at
            logger.info(f"Loaded {len(self._models)} models from cache ({len(self._image_output_models)} image output)")
            return True

        except Exception as e:
            logger.warning(f"Failed to load model cache: {e}")
            return False

    def _save_cache(self, models_data: List[Dict]):
        """Save models to disk cache."""
        cache_path = self._get_cache_path()

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            cache = {
                "cached_at": time.time(),
                "models": models_data,
            }

            with open(cache_path, "w") as f:
                json.dump(cache, f)

            logger.debug(f"Saved {len(models_data)} models to cache")

        except Exception as e:
            logger.warning(f"Failed to save model cache: {e}")

    def _validate_unlisted_model(self, model_id: str) -> bool:
        """
        Check if an unlisted model actually exists on OpenRouter.

        Uses the /models/{id}/endpoints API which returns 404 for defunct models.
        This helps filter out models that have been removed from OpenRouter.

        Args:
            model_id: Full model ID (e.g., "black-forest-labs/flux.2-max")

        Returns:
            True if model exists (has endpoints), False if defunct (404)
        """
        import httpx

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    f"https://openrouter.ai/api/v1/models/{model_id}/endpoints"
                )

                if response.status_code == 404:
                    return False

                # Model exists if we get a successful response
                data = response.json()
                if "error" in data:
                    return False

                return True

        except Exception as e:
            # On error, assume model exists (don't filter it out)
            logger.debug(f"Could not validate model {model_id}: {e}")
            return True

    def _fetch_ollama_models(self, ollama_base_url: str = "http://localhost:11434") -> List[Dict]:
        """
        Fetch models from local Ollama instance.

        Args:
            ollama_base_url: Base URL for Ollama API (default: http://localhost:11434)

        Returns:
            List of model dicts compatible with ModelInfo format
        """
        import httpx

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{ollama_base_url}/api/tags")
                response.raise_for_status()
                data = response.json()

            ollama_models = []
            for m in data.get("models", []):
                # Ollama returns: {"name": "gpt-oss:20b", "size": 13GB, "modified_at": ...}
                model_name = m.get("name", "")

                # Format as ollama/model for consistency with LiteLLM
                model_id = f"ollama/{model_name}"

                ollama_models.append({
                    "id": model_id,
                    "name": model_name,
                    "description": f"Local Ollama model (size: {self._format_size(m.get('size', 0))})",
                    "modality": "text->text",
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                    "context_length": 0,  # Ollama doesn't expose this via API
                    "pricing": {"prompt": "0", "completion": "0"},  # Local = free!
                    "top_provider": {"name": "ollama", "is_local": True},
                })

            if ollama_models:
                logger.info(f"Fetched {len(ollama_models)} models from Ollama")

            return ollama_models

        except Exception as e:
            logger.debug(f"Could not fetch Ollama models (is Ollama running?): {e}")
            return []

    def _format_size(self, size_bytes: int) -> str:
        """Format byte size as human-readable string."""
        if size_bytes == 0:
            return "unknown"

        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f}PB"

    def _fetch_from_api(self) -> bool:
        """Fetch models from OpenRouter API and Ollama. Returns True on success."""
        import httpx
        from .config import get_config

        config = get_config()

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {config.provider_api_key}"}
                )
                response.raise_for_status()
                data = response.json()

            models_data = []
            self._models = {}
            self._image_output_models = set()

            # Fetch OpenRouter models
            for m in data.get("data", []):
                arch = m.get("architecture", {})

                model_data = {
                    "id": m.get("id"),
                    "name": m.get("name", m.get("id", "")),
                    "description": m.get("description", ""),
                    "modality": arch.get("modality", ""),
                    "input_modalities": arch.get("input_modalities", []),
                    "output_modalities": arch.get("output_modalities", []),
                    "context_length": m.get("context_length", 0),
                    "pricing": m.get("pricing", {}),
                    "top_provider": m.get("top_provider", {}),
                }
                models_data.append(model_data)

                model = ModelInfo(**model_data)
                self._models[model.id] = model
                if model.can_output_images:
                    self._image_output_models.add(model.id)

            # Fetch Ollama models (local GPU)
            ollama_models = self._fetch_ollama_models()
            for model_data in ollama_models:
                models_data.append(model_data)
                model = ModelInfo(**model_data)
                self._models[model.id] = model
                # Ollama models don't generate images (yet)

            # Add unlisted image models (with validation)
            # These are models that work but don't appear in /models endpoint
            validated_unlisted = 0
            defunct_unlisted = []

            for model_id in self.UNLISTED_IMAGE_MODELS:
                # Validate that the model still exists on OpenRouter
                if self._validate_unlisted_model(model_id):
                    validated_unlisted += 1
                    self._image_output_models.add(model_id)
                    # Create placeholder ModelInfo if not already present
                    if model_id not in self._models:
                        self._models[model_id] = ModelInfo(
                            id=model_id,
                            name=model_id.split("/")[-1].replace("-", " ").title(),
                            description="Image generation model (unlisted)",
                            output_modalities=["image"],
                            input_modalities=["text"],
                        )
                else:
                    defunct_unlisted.append(model_id)
                    logger.warning(f"Unlisted model no longer exists: {model_id}")

            if defunct_unlisted:
                logger.warning(
                    f"Filtered out {len(defunct_unlisted)} defunct unlisted models: {defunct_unlisted}"
                )

            self._last_fetch = time.time()
            self._save_cache(models_data)

            ollama_count = len(ollama_models)
            openrouter_count = len(self._models) - ollama_count

            logger.info(
                f"Fetched {len(self._models)} models total: "
                f"{openrouter_count} from OpenRouter, {ollama_count} from Ollama "
                f"({len(self._image_output_models)} image output, {validated_unlisted} unlisted)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to fetch models from API: {e}")
            return False

    def _ensure_initialized(self):
        """Ensure models are loaded (from cache or API)."""
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            # Try cache first
            if not self._load_cache():
                # Cache miss or expired - fetch from API
                if not self._fetch_from_api():
                    # API failed - use unlisted models only
                    logger.warning("Using unlisted models only (API fetch failed)")
                    for model_id in self.UNLISTED_IMAGE_MODELS:
                        self._image_output_models.add(model_id)

            self._initialized = True

    def refresh(self, force: bool = False):
        """Refresh model data from API."""
        if force or (time.time() - self._last_fetch > self.CACHE_TTL_SECONDS):
            self._fetch_from_api()

    # =========================================================================
    # Class methods for convenient access
    # =========================================================================

    @classmethod
    def is_image_output_model(cls, model_id: str) -> bool:
        """
        Check if a model can output images (image generation).

        Uses cached model metadata from OpenRouter API.
        Also handles unlisted models that are known to generate images.

        Args:
            model_id: Full model ID (e.g., "google/gemini-2.5-flash-image")

        Returns:
            True if this model generates images
        """
        instance = cls.get_instance()
        instance._ensure_initialized()

        # Check against known image output models
        model_lower = model_id.lower()

        # Direct match
        if model_id in instance._image_output_models:
            return True

        # Case-insensitive match
        for img_model in instance._image_output_models:
            if img_model.lower() == model_lower:
                return True

        # Prefix match for unlisted models
        # e.g., "black-forest-labs/flux" matches any FLUX variant
        unlisted_prefixes = [
            "black-forest-labs/flux",
            "sourceful/riverflow",
            "stability/",
            "stabilityai/",
        ]
        for prefix in unlisted_prefixes:
            if model_lower.startswith(prefix.lower()):
                return True

        return False

    @classmethod
    def get_model(cls, model_id: str) -> Optional[ModelInfo]:
        """Get metadata for a specific model."""
        instance = cls.get_instance()
        instance._ensure_initialized()
        return instance._models.get(model_id)

    @classmethod
    def get_image_output_models(cls) -> List[ModelInfo]:
        """
        Get all models that can output images.

        Useful for building dynamic palettes.

        Returns:
            List of ModelInfo for image generation models
        """
        instance = cls.get_instance()
        instance._ensure_initialized()

        return [
            model for model_id, model in instance._models.items()
            if model_id in instance._image_output_models
        ]

    @classmethod
    def get_all_models(cls) -> List[ModelInfo]:
        """Get all available models."""
        instance = cls.get_instance()
        instance._ensure_initialized()
        return list(instance._models.values())

    @classmethod
    def get_local_models(cls) -> List[ModelInfo]:
        """
        Get all local Ollama models.

        Returns:
            List of ModelInfo for Ollama models (free, local GPU)
        """
        instance = cls.get_instance()
        instance._ensure_initialized()

        return [
            model for model in instance._models.values()
            if model.is_local
        ]

    @classmethod
    def register_runtime_image_model(cls, model_id: str):
        """
        Register a model as an image generator based on runtime detection.

        Called when we receive a response with images but empty content,
        indicating an unlisted image generation model.
        """
        instance = cls.get_instance()
        instance._ensure_initialized()

        if model_id not in instance._image_output_models:
            logger.info(f"Registering runtime-detected image model: {model_id}")
            instance._image_output_models.add(model_id)

            # Create placeholder ModelInfo
            if model_id not in instance._models:
                instance._models[model_id] = ModelInfo(
                    id=model_id,
                    name=model_id.split("/")[-1].replace("-", " ").title(),
                    description="Image generation model (runtime detected)",
                    output_modalities=["image"],
                    input_modalities=["text"],
                )


# Convenience function for backwards compatibility
def is_image_generation_model(model: str) -> bool:
    """
    Check if a model is an image generation model.

    Replacement for Agent.is_image_generation_model() that uses
    dynamic model registry instead of hardcoded prefixes.
    """
    return ModelRegistry.is_image_output_model(model)
