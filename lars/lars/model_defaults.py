"""
Smart default model selection based on configured providers.

At bootstrap time, for each tier we pick the FIRST model whose provider
is enabled. The embedding tier MUST always resolve (CPU fallback is last resort).
"""

from typing import Dict, List, Optional, Tuple

# Provider → model preferences for each tier.
# Order matters: first match for an enabled provider wins.
MODEL_PREFERENCES: Dict[str, List[Tuple[str, str]]] = {
    "fast": [
        ("anthropic-direct", "anthropic-direct/claude-haiku-4-20250414"),
        ("openrouter", "google/gemini-2.5-flash"),
        ("gemini", "gemini/gemini-2.5-flash"),
        ("ollama", "ollama/llama3"),
        ("bedrock", "bedrock/anthropic.claude-3-haiku"),
    ],
    "standard": [
        ("anthropic-direct", "anthropic-direct/claude-sonnet-4-20250514"),
        ("openrouter", "anthropic/claude-sonnet-4"),
        ("gemini", "gemini/gemini-2.5-pro"),
        ("ollama", "ollama/llama3:70b"),
        ("bedrock", "bedrock/anthropic.claude-3-sonnet"),
    ],
    "quality": [
        ("anthropic-direct", "anthropic-direct/claude-sonnet-4-20250514"),
        ("openrouter", "anthropic/claude-sonnet-4"),
        ("gemini", "gemini/gemini-2.5-pro"),
        ("bedrock", "bedrock/anthropic.claude-3-sonnet"),
    ],
    "flagship": [
        ("anthropic-direct", "anthropic-direct/claude-opus-4-0620"),
        ("openrouter", "anthropic/claude-opus-4"),
        ("gemini", "gemini/gemini-2.5-pro"),
        ("bedrock", "bedrock/anthropic.claude-3-opus"),
    ],
    "embedding": [
        ("openrouter", "openai/text-embedding-3-small"),
        ("ollama", "ollama/nomic-embed-text"),
        ("gemini", "gemini/text-embedding-004"),
        ("local", "fastembed/bge-small-en-v1.5"),
    ],
}

# The CPU fallback embedding model (always available)
LOCAL_EMBEDDING_MODEL = "fastembed/bge-small-en-v1.5"
LOCAL_EMBEDDING_FASTEMBED_NAME = "BAAI/bge-small-en-v1.5"
LOCAL_EMBEDDING_DIM = 384


def resolve_defaults_for_providers(
    enabled_providers: set,
    available_models: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, str]:
    """
    Resolve default models for each tier based on which providers are enabled.

    Args:
        enabled_providers: Set of enabled provider names, e.g. {"openrouter", "ollama"}.
                          "local" is always implicitly enabled for embeddings.
        available_models: Optional dict of provider → list of model IDs actually
                         available. Used to cross-check preferences.

    Returns:
        Dict mapping tier name → model ID.
    """
    available_models = available_models or {}
    result: Dict[str, str] = {}

    for tier, candidates in MODEL_PREFERENCES.items():
        resolved = None
        for provider, model_id in candidates:
            # "local" is always available (fastembed CPU fallback)
            if provider == "local":
                resolved = model_id
                break

            if provider not in enabled_providers:
                continue

            # If we have an enumerated model list for this provider, cross-check
            if provider in available_models:
                provider_models = available_models[provider]
                if provider_models and model_id not in provider_models:
                    continue

            resolved = model_id
            break

        if resolved:
            result[tier] = resolved
        else:
            # Should only happen for non-embedding tiers when no provider is enabled
            # Fall back to the first candidate unconditionally
            result[tier] = candidates[0][1] if candidates else ""

    return result


def is_local_embedding(model: str) -> bool:
    """Check if a model ID refers to the local fastembed CPU fallback."""
    return model.startswith("fastembed/")
