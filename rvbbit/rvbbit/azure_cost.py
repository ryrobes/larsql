"""
Azure OpenAI Cost Calculator

Client-side cost calculation for Azure OpenAI models.
Similar to Vertex AI, Azure doesn't return per-request costs in the API response,
so we calculate costs from token counts and known pricing.

Pricing sources:
- https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/
Last updated: 2026-01

Usage:
    from .azure_cost import calculate_azure_cost

    cost = calculate_azure_cost(
        model="azure/gpt-4o",
        tokens_in=1000,
        tokens_out=500
    )
"""

import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


# Azure OpenAI Pricing (USD per 1M tokens)
# Updated: January 2026
# Source: https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/
#
# Format: {
#     "model-name": {
#         "input": rate per 1M tokens,
#         "output": rate per 1M tokens,
#         "tier": "flagship" | "standard" | "fast" | "open"
#     }
# }
#
# Note: Azure hosts models from multiple providers (OpenAI, Anthropic, Meta, Mistral, Cohere)
# Pricing varies by model family
AZURE_PRICING = {
    # =========================================================================
    # OpenAI Models (via Azure OpenAI)
    # =========================================================================
    # GPT-5 Series
    "gpt-5": {"input": 5.00, "output": 15.00, "tier": "flagship"},
    "gpt-5-turbo": {"input": 3.00, "output": 12.00, "tier": "flagship"},

    # GPT-4.1 Series
    "gpt-4.1": {"input": 2.00, "output": 8.00, "tier": "flagship"},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60, "tier": "standard"},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40, "tier": "fast"},

    # GPT-4o Series (Global deployment pricing)
    "gpt-4o": {"input": 2.50, "output": 10.00, "tier": "flagship"},
    "gpt-4o-2024": {"input": 2.50, "output": 10.00, "tier": "flagship"},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "tier": "fast"},

    # GPT-4 Series (Legacy)
    "gpt-4-turbo": {"input": 10.00, "output": 30.00, "tier": "flagship"},
    "gpt-4": {"input": 30.00, "output": 60.00, "tier": "flagship"},
    "gpt-4-32k": {"input": 60.00, "output": 120.00, "tier": "flagship"},

    # GPT-3.5 Series (Legacy)
    "gpt-35-turbo": {"input": 0.50, "output": 1.50, "tier": "standard"},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50, "tier": "standard"},

    # o-Series (Reasoning models)
    "o1": {"input": 15.00, "output": 60.00, "tier": "flagship"},
    "o1-mini": {"input": 3.00, "output": 12.00, "tier": "standard"},
    "o1-preview": {"input": 15.00, "output": 60.00, "tier": "flagship"},
    "o3": {"input": 20.00, "output": 80.00, "tier": "flagship"},
    "o3-mini": {"input": 1.10, "output": 4.40, "tier": "standard"},
    "o4-mini": {"input": 1.10, "output": 4.40, "tier": "standard"},

    # =========================================================================
    # Anthropic Claude Models (via Azure OpenAI)
    # =========================================================================
    "claude-opus-4": {"input": 15.00, "output": 75.00, "tier": "flagship"},
    "claude-opus-4-1": {"input": 15.00, "output": 75.00, "tier": "flagship"},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00, "tier": "standard"},
    "claude-3-7-sonnet": {"input": 3.00, "output": 15.00, "tier": "standard"},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00, "tier": "standard"},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00, "tier": "fast"},
    "claude-3-opus": {"input": 15.00, "output": 75.00, "tier": "flagship"},
    "claude-3-sonnet": {"input": 3.00, "output": 15.00, "tier": "standard"},
    "claude-3-haiku": {"input": 0.25, "output": 1.25, "tier": "fast"},

    # =========================================================================
    # Meta Llama Models
    # =========================================================================
    "llama-3-3-70b": {"input": 0.40, "output": 0.40, "tier": "open"},
    "llama-3-3-70b-instruct": {"input": 0.40, "output": 0.40, "tier": "open"},
    "llama-3-2-90b": {"input": 0.90, "output": 0.90, "tier": "open"},
    "llama-3-2-11b": {"input": 0.05, "output": 0.05, "tier": "open"},
    "llama-3-2-3b": {"input": 0.02, "output": 0.02, "tier": "open"},
    "llama-3-2-1b": {"input": 0.01, "output": 0.01, "tier": "open"},
    "llama-3-1-405b": {"input": 2.70, "output": 2.70, "tier": "open"},
    "llama-3-1-70b": {"input": 0.27, "output": 0.27, "tier": "open"},
    "llama-3-1-8b": {"input": 0.03, "output": 0.03, "tier": "open"},
    "llama-4-scout": {"input": 0.15, "output": 0.60, "tier": "open"},
    "llama-4-maverick": {"input": 0.20, "output": 0.80, "tier": "open"},

    # =========================================================================
    # Mistral AI Models
    # =========================================================================
    "mistral-large": {"input": 2.00, "output": 6.00, "tier": "flagship"},
    "mistral-large-latest": {"input": 2.00, "output": 6.00, "tier": "flagship"},
    "mistral-large-2411": {"input": 2.00, "output": 6.00, "tier": "flagship"},
    "mistral-medium": {"input": 2.70, "output": 8.10, "tier": "standard"},
    "mistral-small": {"input": 0.20, "output": 0.60, "tier": "fast"},
    "mistral-small-latest": {"input": 0.20, "output": 0.60, "tier": "fast"},
    "ministral-8b": {"input": 0.10, "output": 0.10, "tier": "fast"},
    "ministral-3b": {"input": 0.04, "output": 0.04, "tier": "fast"},
    "codestral": {"input": 0.30, "output": 0.90, "tier": "standard"},
    "codestral-latest": {"input": 0.30, "output": 0.90, "tier": "standard"},
    "pixtral-large": {"input": 2.00, "output": 6.00, "tier": "flagship"},
    "pixtral-12b": {"input": 0.15, "output": 0.15, "tier": "fast"},

    # =========================================================================
    # Cohere Models
    # =========================================================================
    "command-r-plus": {"input": 2.50, "output": 10.00, "tier": "flagship"},
    "command-r": {"input": 0.15, "output": 0.60, "tier": "standard"},
    "command-r-08-2024": {"input": 0.15, "output": 0.60, "tier": "standard"},
    "command": {"input": 1.00, "output": 2.00, "tier": "standard"},
    "embed-english-v3": {"input": 0.10, "output": 0.0, "tier": "embedding"},
    "embed-multilingual-v3": {"input": 0.10, "output": 0.0, "tier": "embedding"},
    "rerank-english-v3": {"input": 2.00, "output": 0.0, "tier": "standard"},
    "rerank-multilingual-v3": {"input": 2.00, "output": 0.0, "tier": "standard"},

    # =========================================================================
    # DeepSeek Models
    # =========================================================================
    "deepseek-v3": {"input": 0.27, "output": 1.10, "tier": "open"},
    "deepseek-r1": {"input": 0.55, "output": 2.19, "tier": "open"},
    "deepseek-chat": {"input": 0.14, "output": 0.28, "tier": "open"},
    "deepseek-coder": {"input": 0.14, "output": 0.28, "tier": "open"},

    # =========================================================================
    # AI21 Labs Models
    # =========================================================================
    "jamba-1-5-large": {"input": 2.00, "output": 8.00, "tier": "standard"},
    "jamba-1-5-mini": {"input": 0.20, "output": 0.40, "tier": "fast"},
    "jamba-instruct": {"input": 0.50, "output": 0.70, "tier": "standard"},

    # =========================================================================
    # Phi Models (Microsoft)
    # =========================================================================
    "phi-4": {"input": 0.07, "output": 0.14, "tier": "fast"},
    "phi-3-5-moe": {"input": 0.16, "output": 0.16, "tier": "fast"},
    "phi-3-5-mini": {"input": 0.03, "output": 0.03, "tier": "fast"},
    "phi-3-5-vision": {"input": 0.05, "output": 0.05, "tier": "fast"},
    "phi-3-medium": {"input": 0.07, "output": 0.07, "tier": "fast"},
    "phi-3-mini": {"input": 0.02, "output": 0.02, "tier": "fast"},

    # =========================================================================
    # Embedding Models
    # =========================================================================
    "text-embedding-3-large": {"input": 0.13, "output": 0.0, "tier": "embedding"},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0, "tier": "embedding"},
    "text-embedding-ada-002": {"input": 0.10, "output": 0.0, "tier": "embedding"},
}

# Environment variable override for custom pricing
# Set RVBBIT_AZURE_PRICING_JSON to override pricing table
_custom_pricing = None


def _load_custom_pricing() -> Dict:
    """Load custom pricing from environment variable if set."""
    global _custom_pricing
    if _custom_pricing is not None:
        return _custom_pricing

    pricing_json = os.getenv("RVBBIT_AZURE_PRICING_JSON")
    if pricing_json:
        try:
            import json
            _custom_pricing = json.loads(pricing_json)
            logger.info(f"Loaded custom Azure OpenAI pricing: {list(_custom_pricing.keys())}")
        except Exception as e:
            logger.warning(f"Failed to parse RVBBIT_AZURE_PRICING_JSON: {e}")
            _custom_pricing = {}
    else:
        _custom_pricing = {}

    return _custom_pricing


def get_pricing(model_name: str) -> Dict:
    """
    Get pricing for a model, checking custom pricing first.

    Args:
        model_name: Model name without azure_ai/ prefix

    Returns:
        Pricing dict with input, output, tier
    """
    custom = _load_custom_pricing()

    # Normalize model name (lowercase, handle common variations)
    model_lower = model_name.lower().strip()

    # Check custom pricing first
    if model_lower in custom:
        return custom[model_lower]

    # Try exact match in built-in pricing
    if model_lower in AZURE_PRICING:
        return AZURE_PRICING[model_lower]

    # Try prefix matching (most specific first)
    # Sort by length descending to match most specific prefix
    for prefix in sorted(AZURE_PRICING.keys(), key=len, reverse=True):
        if model_lower.startswith(prefix):
            return AZURE_PRICING[prefix]

    # Try suffix matching (for versioned models like "gpt-4o-2024-11-20")
    for key in AZURE_PRICING:
        if key in model_lower:
            return AZURE_PRICING[key]

    # Unknown model - return zeros and log
    logger.debug(f"No pricing found for Azure OpenAI model: {model_name}")
    return {"input": 0.0, "output": 0.0, "tier": "standard"}


def calculate_azure_cost(
    model: str,
    tokens_in: int,
    tokens_out: int,
    context_length: Optional[int] = None,
) -> float:
    """
    Calculate cost for an Azure OpenAI request based on token counts.

    Args:
        model: Full model string (e.g., "azure/gpt-4o")
        tokens_in: Number of input tokens
        tokens_out: Number of output tokens
        context_length: Total context length (not currently used, reserved for future)

    Returns:
        Cost in USD (rounded to 8 decimal places)
    """
    # Extract model name from azure/deployment-name format
    model_name = model
    if model_name.startswith("azure/"):
        model_name = model_name[6:]  # len("azure/") = 6

    # Remove deployment-specific suffixes if present
    # e.g., "gpt-4o-my-deployment" -> try to match "gpt-4o"
    # But keep version suffixes like "gpt-4o-2024-11-20"

    pricing = get_pricing(model_name)

    # Handle text/chat models
    tokens_in = tokens_in or 0
    tokens_out = tokens_out or 0

    input_rate = pricing.get("input", 0.0)
    output_rate = pricing.get("output", 0.0)

    # Calculate cost (rates are per 1M tokens)
    cost = (tokens_in / 1_000_000 * input_rate) + (tokens_out / 1_000_000 * output_rate)

    return round(cost, 8)


def estimate_cost_from_chars(
    model: str,
    input_chars: int,
    output_chars: int,
) -> float:
    """
    Estimate cost from character counts (using ~4 chars per token approximation).

    Useful for pre-flight cost estimation before making a request.

    Args:
        model: Full model string (e.g., "azure/gpt-4o")
        input_chars: Number of input characters
        output_chars: Number of output characters

    Returns:
        Estimated cost in USD
    """
    # Rough approximation: 4 characters per token
    tokens_in = input_chars // 4
    tokens_out = output_chars // 4

    return calculate_azure_cost(model, tokens_in, tokens_out)


def get_available_models() -> list:
    """
    Get list of all Azure OpenAI models with known pricing.

    Returns:
        List of model names (without azure/ prefix)
    """
    custom = _load_custom_pricing()
    all_models = set(AZURE_PRICING.keys()) | set(custom.keys())
    return sorted(all_models)


def get_model_tier(model: str) -> str:
    """
    Get the tier classification for a model.

    Args:
        model: Model name (with or without azure/ prefix)

    Returns:
        Tier string: 'flagship', 'standard', 'fast', 'open', or 'embedding'
    """
    model_name = model
    if model_name.startswith("azure/"):
        model_name = model_name[6:]

    pricing = get_pricing(model_name)
    return pricing.get("tier", "standard")


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
