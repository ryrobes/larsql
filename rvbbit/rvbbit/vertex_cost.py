"""
Vertex AI Cost Calculator

Client-side cost calculation for Google Vertex AI models.
Unlike OpenRouter, Vertex AI doesn't have a per-request cost API,
so we calculate costs from token counts and known pricing.

Pricing source: https://cloud.google.com/vertex-ai/generative-ai/pricing
Last updated: 2025-01

Usage:
    from .vertex_cost import calculate_vertex_cost

    cost = calculate_vertex_cost(
        model="vertex_ai/gemini-2.5-flash",
        tokens_in=1000,
        tokens_out=500
    )
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Vertex AI Gemini Pricing (USD per 1M tokens)
# Updated: January 2026
# Source: https://cloud.google.com/vertex-ai/generative-ai/pricing
#
# Format: {
#     "model-name": {
#         "input": rate per 1M tokens,
#         "output": rate per 1M tokens,
#         "input_long": rate for >200K context (optional),
#         "output_long": rate for >200K context (optional),
#         "context_threshold": tokens at which long-context pricing kicks in (default 200000)
#     }
# }
VERTEX_PRICING = {
    # Gemini 3 models (preview)
    "gemini-3-pro-preview": {
        "input": 2.00,
        "output": 12.00,
        "input_long": 4.00,
        "output_long": 18.00,
        "context_threshold": 200000,
    },
    "gemini-3-flash-preview": {
        "input": 0.50,
        "output": 3.00,
        "context_threshold": 200000,
    },
    "gemini-3-pro-image-preview": {
        "input": 2.00,
        "output": 120.00,  # Image output pricing
        "context_threshold": 200000,
    },

    # Gemini 2.5 models (GA)
    "gemini-2.5-pro": {
        "input": 1.25,
        "output": 10.00,
        "input_long": 2.50,
        "output_long": 15.00,
        "context_threshold": 200000,
    },
    "gemini-2.5-pro-preview": {
        "input": 1.25,
        "output": 10.00,
        "input_long": 2.50,
        "output_long": 15.00,
        "context_threshold": 200000,
    },
    "gemini-2.5-flash": {
        "input": 0.30,
        "output": 2.50,
        "context_threshold": 200000,
    },
    "gemini-2.5-flash-preview": {
        "input": 0.30,
        "output": 2.50,
        "context_threshold": 200000,
    },
    "gemini-2.5-flash-lite": {
        "input": 0.10,
        "output": 0.40,
    },
    "gemini-2.5-flash-image": {
        "input": 0.30,
        "output": 30.00,  # Image output pricing
    },

    # Gemini 2.0 models
    "gemini-2.0-flash": {
        "input": 0.15,
        "output": 0.60,
        "context_threshold": 200000,
    },
    "gemini-2.0-flash-exp": {
        "input": 0.15,
        "output": 0.60,
    },
    "gemini-2.0-flash-lite": {
        "input": 0.075,
        "output": 0.30,
    },
    "gemini-2.0-pro": {
        "input": 1.25,
        "output": 10.00,
        "input_long": 2.50,
        "output_long": 15.00,
        "context_threshold": 200000,
    },

    # Gemini 1.5 models (legacy, still available)
    "gemini-1.5-pro": {
        "input": 1.25,
        "output": 5.00,
        "input_long": 2.50,
        "output_long": 10.00,
        "context_threshold": 128000,
    },
    "gemini-1.5-flash": {
        "input": 0.075,
        "output": 0.30,
        "input_long": 0.15,
        "output_long": 0.60,
        "context_threshold": 128000,
    },

    # Imagen models (image generation - per image pricing)
    # These use different pricing (per image, not per token)
    "imagen-3.0-generate": {
        "per_image": 0.04,  # $0.04 per image
    },
    "imagen-3.0-fast-generate": {
        "per_image": 0.02,  # $0.02 per image
    },

    # Embedding models
    "text-embedding-005": {
        "input": 0.00002,  # $0.00002 per 1K characters ≈ $0.00005 per 1K tokens
        "output": 0.0,
    },
    "text-multilingual-embedding-002": {
        "input": 0.00002,
        "output": 0.0,
    },
}

# Environment variable override for custom pricing
# Set RVBBIT_VERTEX_PRICING_JSON to override pricing table
_custom_pricing = None


def _load_custom_pricing():
    """Load custom pricing from environment variable if set."""
    global _custom_pricing
    if _custom_pricing is not None:
        return _custom_pricing

    pricing_json = os.getenv("RVBBIT_VERTEX_PRICING_JSON")
    if pricing_json:
        try:
            import json
            _custom_pricing = json.loads(pricing_json)
            logger.info(f"Loaded custom Vertex AI pricing: {list(_custom_pricing.keys())}")
        except Exception as e:
            logger.warning(f"Failed to parse RVBBIT_VERTEX_PRICING_JSON: {e}")
            _custom_pricing = {}
    else:
        _custom_pricing = {}

    return _custom_pricing


def get_pricing(model_name: str) -> dict:
    """
    Get pricing for a model, checking custom pricing first.

    Args:
        model_name: Model name without vertex_ai/ prefix

    Returns:
        Pricing dict with input/output rates
    """
    custom = _load_custom_pricing()

    # Check custom pricing first
    if model_name in custom:
        return custom[model_name]

    # Fall back to built-in pricing
    if model_name in VERTEX_PRICING:
        return VERTEX_PRICING[model_name]

    # Try partial match (e.g., "gemini-2.5-pro-001" -> "gemini-2.5-pro")
    for key in VERTEX_PRICING:
        if model_name.startswith(key):
            return VERTEX_PRICING[key]

    # Unknown model - return zeros (free tier or unknown)
    logger.debug(f"No pricing found for Vertex AI model: {model_name}")
    return {"input": 0.0, "output": 0.0}


def calculate_vertex_cost(
    model: str,
    tokens_in: int,
    tokens_out: int,
    context_length: Optional[int] = None,
    image_count: Optional[int] = None,
) -> float:
    """
    Calculate cost for a Vertex AI request based on token counts.

    Args:
        model: Full model string (e.g., "vertex_ai/gemini-2.5-flash")
        tokens_in: Number of input tokens
        tokens_out: Number of output tokens
        context_length: Total context length (for long-context pricing tiers)
        image_count: Number of images generated (for Imagen models)

    Returns:
        Cost in USD (rounded to 8 decimal places)
    """
    # Extract model name from vertex_ai/model-name format
    model_name = model
    if model_name.startswith("vertex_ai/"):
        model_name = model_name[10:]  # len("vertex_ai/") = 10

    # Remove version suffix if present (e.g., "gemini-2.5-pro-001" -> "gemini-2.5-pro")
    # But keep preview/exp suffixes
    parts = model_name.split("-")
    if parts and parts[-1].isdigit():
        model_name = "-".join(parts[:-1])

    pricing = get_pricing(model_name)

    # Handle image generation models
    if "per_image" in pricing and image_count:
        cost = pricing["per_image"] * image_count
        return round(cost, 8)

    # Handle text/chat models
    tokens_in = tokens_in or 0
    tokens_out = tokens_out or 0

    # Determine if we're in long-context pricing tier
    threshold = pricing.get("context_threshold", 128000)
    use_long_context = context_length and context_length > threshold

    if use_long_context:
        input_rate = pricing.get("input_long", pricing.get("input", 0.0))
        output_rate = pricing.get("output_long", pricing.get("output", 0.0))
    else:
        input_rate = pricing.get("input", 0.0)
        output_rate = pricing.get("output", 0.0)

    # Calculate cost (rates are per 1M tokens)
    cost = (tokens_in / 1_000_000 * input_rate) + (tokens_out / 1_000_000 * output_rate)

    return round(cost, 8)


def estimate_cost_from_chars(
    model: str,
    input_chars: int,
    output_chars: int,
    context_length: Optional[int] = None,
) -> float:
    """
    Estimate cost from character counts (using ~4 chars per token approximation).

    Useful for pre-flight cost estimation before making a request.

    Args:
        model: Full model string (e.g., "vertex_ai/gemini-2.5-flash")
        input_chars: Number of input characters
        output_chars: Number of output characters
        context_length: Total context length in tokens

    Returns:
        Estimated cost in USD
    """
    # Rough approximation: 4 characters per token
    tokens_in = input_chars // 4
    tokens_out = output_chars // 4

    return calculate_vertex_cost(model, tokens_in, tokens_out, context_length)


def get_available_models() -> list:
    """
    Get list of all Vertex AI models with known pricing.

    Returns:
        List of model names (without vertex_ai/ prefix)
    """
    custom = _load_custom_pricing()
    all_models = set(VERTEX_PRICING.keys()) | set(custom.keys())
    return sorted(all_models)


def format_cost(cost: float) -> str:
    """
    Format cost for display.

    Args:
        cost: Cost in USD

    Returns:
        Formatted string (e.g., "$0.0012" or "$1.23")
    """
    if cost < 0.01:
        return f"${cost:.6f}"
    elif cost < 1.0:
        return f"${cost:.4f}"
    else:
        return f"${cost:.2f}"
