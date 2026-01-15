"""
Model Metadata Cache for RVBBIT - Context Limit Filtering

Fetches model metadata from OpenRouter API and caches it locally.
Used to filter models for multi-model takes based on context limits.

Key Features:
- Fetch model context limits from OpenRouter /api/v1/models endpoint
- TTL-based caching (default: 24 hours)
- Automatic filtering of models with insufficient context
- Event emission for observability
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import httpx

from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Model metadata from OpenRouter"""
    id: str
    name: str
    context_length: int
    pricing: Dict[str, Any]
    created: int
    description: Optional[str] = None
    max_completion_tokens: Optional[int] = None

    @classmethod
    def from_api_response(cls, data: Dict) -> 'ModelInfo':
        """Create ModelInfo from OpenRouter API response"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            context_length=data.get("context_length", 0),
            pricing=data.get("pricing", {}),
            created=data.get("created", 0),
            description=data.get("description"),
            max_completion_tokens=data.get("max_completion_tokens")
        )


class ModelMetadataCache:
    """
    Cache for OpenRouter model metadata with TTL support.

    Provides fast lookup of model context limits for filtering
    during multi-model takes execution.
    """

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        ttl_hours: int = 24,
        provider_base_url: Optional[str] = None,
        provider_api_key: Optional[str] = None
    ):
        """
        Initialize model metadata cache.

        Args:
            cache_path: Path to cache file (default: $RVBBIT_ROOT/data/.model_cache.json)
            ttl_hours: Cache TTL in hours (default: 24)
            provider_base_url: OpenRouter base URL (uses config if not provided)
            provider_api_key: OpenRouter API key (uses config if not provided)
        """
        cfg = get_config()
        self.cache_path = cache_path or Path(cfg.data_dir) / ".model_cache.json"
        self.ttl = timedelta(hours=ttl_hours)
        self.provider_base_url = provider_base_url or cfg.provider_base_url
        self.provider_api_key = provider_api_key or cfg.provider_api_key

        self._cache: Dict[str, ModelInfo] = {}
        self._cache_timestamp: Optional[datetime] = None

        # Load existing cache
        self._load_cache()

    def _load_cache(self):
        """Load cache from disk if it exists and is fresh"""
        if not self.cache_path.exists():
            logger.debug(f"Model cache not found at {self.cache_path}")
            return

        try:
            with open(self.cache_path, 'r') as f:
                data = json.load(f)

            # Check timestamp
            timestamp_str = data.get("timestamp")
            if not timestamp_str:
                logger.warning("Cache missing timestamp, will refresh")
                return

            timestamp = datetime.fromisoformat(timestamp_str)

            # Check if stale
            if datetime.now() - timestamp > self.ttl:
                logger.info(f"Model cache is stale (age: {datetime.now() - timestamp}), will refresh")
                return

            # Load models
            models_data = data.get("models", {})
            self._cache = {
                model_id: ModelInfo(**model_info)
                for model_id, model_info in models_data.items()
            }
            self._cache_timestamp = timestamp

            logger.info(f"Loaded {len(self._cache)} models from cache (age: {datetime.now() - timestamp})")

        except Exception as e:
            logger.warning(f"Failed to load model cache: {e}")
            self._cache = {}
            self._cache_timestamp = None

    def _save_cache(self):
        """Save cache to disk"""
        try:
            # Ensure directory exists
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "timestamp": self._cache_timestamp.isoformat() if self._cache_timestamp else datetime.now().isoformat(),
                "models": {
                    model_id: asdict(model_info)
                    for model_id, model_info in self._cache.items()
                }
            }

            with open(self.cache_path, 'w') as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved {len(self._cache)} models to cache at {self.cache_path}")

        except Exception as e:
            logger.warning(f"Failed to save model cache: {e}")

    def _is_stale(self) -> bool:
        """Check if cache needs refresh"""
        if not self._cache_timestamp:
            return True
        return datetime.now() - self._cache_timestamp > self.ttl

    async def _refresh_cache(self):
        """Fetch fresh model metadata from OpenRouter API"""
        if not self.provider_base_url or "openrouter" not in self.provider_base_url:
            logger.warning("Not using OpenRouter, skipping model cache refresh")
            return

        if not self.provider_api_key:
            logger.warning("No OpenRouter API key, skipping model cache refresh")
            return

        try:
            url = f"{self.provider_base_url.rstrip('/')}/models"
            headers = {
                "Authorization": f"Bearer {self.provider_api_key}",
                "Content-Type": "application/json"
            }

            logger.info(f"Fetching model metadata from {url}")

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            # Parse models
            models = data.get("data", [])
            self._cache = {
                model["id"]: ModelInfo.from_api_response(model)
                for model in models
                if "id" in model and "context_length" in model
            }
            self._cache_timestamp = datetime.now()

            logger.info(f"Fetched {len(self._cache)} models from OpenRouter")

            # Save to disk
            self._save_cache()

        except Exception as e:
            logger.error(f"Failed to refresh model cache: {e}")
            # Keep existing cache if available
            if not self._cache:
                raise

    async def get_context_limit(self, model_id: str) -> Optional[int]:
        """
        Get context window for a model.

        Args:
            model_id: Model ID (e.g., "anthropic/claude-opus-4.5")

        Returns:
            Context length in tokens, or None if unknown
        """
        # Refresh if stale
        if self._is_stale():
            await self._refresh_cache()

        model_info = self._cache.get(model_id)
        if model_info:
            return model_info.context_length

        # Not found in cache
        logger.debug(f"Model {model_id} not found in cache")
        return None

    async def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        """
        Get full model metadata.

        Args:
            model_id: Model ID

        Returns:
            ModelInfo or None if not found
        """
        if self._is_stale():
            await self._refresh_cache()

        return self._cache.get(model_id)

    async def filter_viable_models(
        self,
        models: List[str],
        estimated_tokens: int,
        buffer_factor: float = 1.15
    ) -> Dict[str, Any]:
        """
        Filter models based on context requirements.

        Returns both the viable models and detailed filtering info for observability.

        Args:
            models: List of model IDs to filter
            estimated_tokens: Estimated tokens needed for request
            buffer_factor: Safety buffer (default: 15% extra)

        Returns:
            Dict with:
                - viable_models: List of models with sufficient context
                - filtered_models: List of models that were filtered out
                - filter_details: Dict mapping filtered model -> reason
                - estimated_tokens: The input token estimate
                - required_tokens: Actual requirement with buffer
        """
        # Refresh cache if needed
        if self._is_stale():
            await self._refresh_cache()

        required_tokens = int(estimated_tokens * buffer_factor)
        viable = []
        filtered = []
        filter_details = {}

        for model in models:
            limit = await self.get_context_limit(model)

            if limit is None:
                # Unknown model - assume infinite context (don't filter)
                viable.append(model)
                logger.debug(f"Model {model} not in cache, assuming sufficient context")
            elif limit >= required_tokens:
                # Sufficient context
                viable.append(model)
            else:
                # Insufficient context
                filtered.append(model)
                filter_details[model] = {
                    "reason": "insufficient_context",
                    "required_tokens": required_tokens,
                    "model_limit": limit,
                    "shortfall": required_tokens - limit
                }
                logger.info(
                    f"Filtered {model} from take: "
                    f"needs {required_tokens} tokens, has {limit} "
                    f"(shortfall: {required_tokens - limit})"
                )

        # If ALL models filtered, return original list as fallback
        if not viable:
            logger.warning(
                f"All models filtered! Falling back to original list. "
                f"Required: {required_tokens} tokens"
            )
            viable = models
            # Clear filter details since we're using all models anyway
            filtered = []
            filter_details = {}

        # Collect model limits for all models (for console display)
        model_limits = {}
        for model in models:
            limit = await self.get_context_limit(model)
            if limit:
                model_limits[model] = limit

        return {
            "viable_models": viable,
            "filtered_models": filtered,
            "filter_details": filter_details,
            "estimated_tokens": estimated_tokens,
            "required_tokens": required_tokens,
            "buffer_factor": buffer_factor,
            "model_limits": model_limits
        }


# Global cache instance
_global_cache: Optional[ModelMetadataCache] = None


def get_model_cache() -> ModelMetadataCache:
    """Get or create the global model metadata cache"""
    global _global_cache
    if _global_cache is None:
        _global_cache = ModelMetadataCache()
    return _global_cache


def reset_model_cache():
    """Reset the global cache (useful for testing)"""
    global _global_cache
    _global_cache = None


def estimate_request_tokens(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None
) -> int:
    """
    Estimate total tokens for a complete LLM request.

    Includes:
    - System prompt
    - Message history
    - Tool schemas
    - Message overhead

    Args:
        messages: List of message dicts
        tools: List of tool schemas
        system_prompt: System prompt text
        model: Model name (for encoding selection)

    Returns:
        Estimated token count
    """
    from .token_budget import TokenBudgetManager
    from .cascade import TokenBudgetConfig

    # Create a temporary token budget manager for counting
    # Use a high limit since we're just counting, not enforcing
    dummy_config = TokenBudgetConfig(
        max_total=1_000_000,
        reserve_for_output=0
    )
    counter = TokenBudgetManager(dummy_config, model or "gpt-4")

    total = 0

    # Count system prompt
    if system_prompt:
        total += counter._count_text(system_prompt)
        total += 4  # Message overhead

    # Count messages
    total += counter.count_tokens(messages)

    # Count tool schemas (rough estimate)
    if tools:
        tools_json = json.dumps(tools)
        total += counter._count_text(tools_json)

    # Add 10% buffer for API formatting overhead
    total = int(total * 1.1)

    logger.debug(f"Estimated {total} tokens for request (messages={len(messages)}, tools={len(tools or [])})")

    return total
