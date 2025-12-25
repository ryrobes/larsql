"""
Helpers for enriching echo entries with performance metrics.

Extracts timing, tokens, and cost data from LLM responses and other sources.
"""

import time
from typing import Dict, Optional, Any


class TimingContext:
    """Context manager for tracking execution duration."""

    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.duration_ms = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000  # Convert to ms
        return False  # Don't suppress exceptions

    def get_duration_ms(self) -> Optional[float]:
        """Get duration in milliseconds."""
        return self.duration_ms


def extract_usage_from_litellm(response: Any) -> Dict[str, Optional[int]]:
    """
    Extract token usage from LiteLLM response object.

    Args:
        response: LiteLLM completion response

    Returns:
        Dict with tokens_in, tokens_out, total_tokens (None if not available)
    """
    usage = {
        "tokens_in": None,
        "tokens_out": None,
        "total_tokens": None,
    }

    if not response:
        return usage

    # LiteLLM standardizes usage across providers
    if hasattr(response, "usage") and response.usage:
        usage_obj = response.usage

        if hasattr(usage_obj, "prompt_tokens"):
            usage["tokens_in"] = usage_obj.prompt_tokens

        if hasattr(usage_obj, "completion_tokens"):
            usage["tokens_out"] = usage_obj.completion_tokens

        if hasattr(usage_obj, "total_tokens"):
            usage["total_tokens"] = usage_obj.total_tokens

    return usage


def extract_request_id(response: Any) -> Optional[str]:
    """
    Extract request/generation ID from LiteLLM response.

    Args:
        response: LiteLLM completion response

    Returns:
        Request ID string or None
    """
    if hasattr(response, "id"):
        return response.id
    return None


def estimate_cost_from_tokens(
    model: str,
    tokens_in: int,
    tokens_out: int
) -> Optional[float]:
    """
    Estimate cost based on model and token counts.

    This is a rough estimate - actual costs should come from provider APIs.

    Args:
        model: Model name
        tokens_in: Input tokens
        tokens_out: Output tokens

    Returns:
        Estimated cost in USD or None if model pricing unknown
    """
    # Rough pricing estimates (as of 2025) - update as needed
    # Format: (input_price_per_1M, output_price_per_1M)
    pricing = {
        # OpenAI
        "gpt-4": (30.0, 60.0),
        "gpt-4-turbo": (10.0, 30.0),
        "gpt-3.5-turbo": (0.5, 1.5),

        # Anthropic
        "claude-3-opus": (15.0, 75.0),
        "claude-3-sonnet": (3.0, 15.0),
        "claude-3-haiku": (0.25, 1.25),
        "claude-sonnet-4": (3.0, 15.0),

        # Meta
        "llama-3": (0.0, 0.0),  # Often free on OpenRouter

        # Google
        "gemini-pro": (0.5, 1.5),
    }

    if tokens_in is None or tokens_out is None:
        return None

    # Find matching pricing (partial match on model name)
    for model_key, (in_price, out_price) in pricing.items():
        if model_key.lower() in model.lower():
            cost_in = (tokens_in / 1_000_000) * in_price
            cost_out = (tokens_out / 1_000_000) * out_price
            return cost_in + cost_out

    return None  # Unknown model


def enrich_echo_with_llm_response(
    echo_kwargs: Dict,
    response: Any,
    duration_ms: Optional[float] = None
) -> Dict:
    """
    Enrich echo entry dict with data from LLM response.

    Args:
        echo_kwargs: Base echo entry dict
        response: LiteLLM response object
        duration_ms: Optional duration override

    Returns:
        Enriched echo entry dict
    """
    # Extract usage
    usage = extract_usage_from_litellm(response)
    echo_kwargs["tokens_in"] = usage["tokens_in"]
    echo_kwargs["tokens_out"] = usage["tokens_out"]

    # Extract request ID
    echo_kwargs["request_id"] = extract_request_id(response)

    # Add duration if provided
    if duration_ms is not None:
        echo_kwargs["duration_ms"] = duration_ms

    # Estimate cost (will be updated by async cost tracker with real data)
    if "model" in echo_kwargs and usage["tokens_in"] and usage["tokens_out"]:
        echo_kwargs["cost"] = estimate_cost_from_tokens(
            echo_kwargs["model"],
            usage["tokens_in"],
            usage["tokens_out"]
        )

    return echo_kwargs


def detect_base64_in_content(content: Any) -> bool:
    """
    Detect if content contains base64 image data.

    Args:
        content: Message content (can be str, list, dict)

    Returns:
        True if base64 image data detected
    """
    if isinstance(content, str):
        return "data:image/" in content and ";base64," in content

    elif isinstance(content, list):
        # OpenAI multi-modal format: [{"type": "image_url", "image_url": {"url": "data:..."}}]
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if "data:image/" in url and ";base64," in url:
                        return True
        return False

    elif isinstance(content, dict):
        # Check recursively
        for value in content.values():
            if detect_base64_in_content(value):
                return True
        return False

    return False


def extract_image_paths_from_tool_result(result: Any) -> list:
    """
    Extract image file paths from tool result.

    Looks for {"images": ["/path/to/file.png", ...]} pattern.

    Args:
        result: Tool result (can be dict, str, etc.)

    Returns:
        List of image file paths (empty if none found)
    """
    if isinstance(result, dict) and "images" in result:
        images = result["images"]
        if isinstance(images, list):
            return [str(img) for img in images]
        elif isinstance(images, str):
            return [images]

    return []


def extract_audio_paths_from_tool_result(result: Any) -> list:
    """
    Extract audio file paths from tool result.

    Looks for {"audio": ["/path/to/file.mp3", ...]} pattern.

    Args:
        result: Tool result (can be dict, str, etc.)

    Returns:
        List of audio file paths (empty if none found)
    """
    if isinstance(result, dict) and "audio" in result:
        audio = result["audio"]
        if isinstance(audio, list):
            return [str(aud) for aud in audio]
        elif isinstance(audio, str):
            return [audio]

    return []
