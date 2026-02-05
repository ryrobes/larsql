"""
Provider discovery and model enumeration for bootstrap wizard.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import httpx


@dataclass
class DiscoveredModel:
    """A model discovered from a provider."""
    id: str                     # Full model ID (e.g., "ollama/llama3.3:70b")
    name: str                   # Display name
    provider: str               # "openrouter" or "ollama"
    host: Optional[str] = None  # Ollama host alias (if applicable)
    
    # Capabilities
    is_embedding: bool = False
    is_chat: bool = True
    supports_vision: bool = False
    supports_reasoning: bool = False
    
    # Metadata
    context_length: Optional[int] = None
    pricing_input: Optional[float] = None   # $ per 1M tokens
    pricing_output: Optional[float] = None  # $ per 1M tokens
    size_gb: Optional[float] = None         # Model size for Ollama
    
    @property
    def pricing_display(self) -> str:
        """Format pricing for display."""
        if self.pricing_input is not None:
            return f"${self.pricing_input:.2f}/1M"
        if self.provider == "ollama":
            return "free (local)"
        return ""
    
    @property
    def source_display(self) -> str:
        """Format source for display."""
        if self.provider == "ollama":
            return self.host or "localhost"
        return "OpenRouter"


def validate_openrouter_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate an OpenRouter API key.
    
    Returns:
        (is_valid, message)
    """
    try:
        resp = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            model_count = len(data.get("data", []))
            return True, f"Valid! {model_count} models available"
        elif resp.status_code == 401:
            return False, "Invalid API key"
        else:
            return False, f"HTTP {resp.status_code}"
    except httpx.TimeoutException:
        return False, "Timeout connecting to OpenRouter"
    except Exception as e:
        return False, str(e)


def fetch_openrouter_models(api_key: str) -> List[DiscoveredModel]:
    """
    Fetch available models from OpenRouter.
    
    Args:
        api_key: OpenRouter API key
    
    Returns:
        List of discovered models
    """
    try:
        resp = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        
        models = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            
            # Skip if no ID
            if not model_id:
                continue
            
            # Determine capabilities from model info
            architecture = m.get("architecture", {})
            modality = architecture.get("modality", "")
            
            is_embedding = "embedding" in model_id.lower() or modality == "embedding"
            supports_vision = "vision" in modality or "image" in modality
            
            # Check for reasoning models
            supports_reasoning = any(x in model_id.lower() for x in [
                "o1", "o3", "deepseek-r1", "qwq", "thinking"
            ])
            
            # Pricing
            pricing = m.get("pricing", {})
            pricing_input = None
            pricing_output = None
            try:
                # OpenRouter returns price per token, convert to per 1M
                prompt_price = float(pricing.get("prompt", 0))
                completion_price = float(pricing.get("completion", 0))
                pricing_input = prompt_price * 1_000_000
                pricing_output = completion_price * 1_000_000
            except:
                pass
            
            models.append(DiscoveredModel(
                id=model_id,
                name=m.get("name", model_id),
                provider="openrouter",
                is_embedding=is_embedding,
                is_chat=not is_embedding,
                supports_vision=supports_vision,
                supports_reasoning=supports_reasoning,
                context_length=m.get("context_length"),
                pricing_input=pricing_input,
                pricing_output=pricing_output,
            ))
        
        return models
    except Exception as e:
        print(f"Error fetching OpenRouter models: {e}")
        return []


def validate_ollama_host(url: str) -> Tuple[bool, str]:
    """
    Validate an Ollama host URL.
    
    Returns:
        (is_valid, message)
    """
    # Normalize URL
    if not url.startswith("http"):
        url = f"http://{url}"
    if not url.endswith("/"):
        url = url.rstrip("/")
    
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            model_count = len(data.get("models", []))
            return True, f"Connected! {model_count} models available"
        else:
            return False, f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        return False, "Connection refused - is Ollama running?"
    except httpx.TimeoutException:
        return False, "Timeout connecting to Ollama"
    except Exception as e:
        return False, str(e)


def fetch_ollama_models(url: str, host_alias: str = "default") -> List[DiscoveredModel]:
    """
    Fetch available models from an Ollama instance.
    
    Args:
        url: Ollama base URL
        host_alias: Alias for this host (for model ID prefix)
    
    Returns:
        List of discovered models
    """
    # Normalize URL
    if not url.startswith("http"):
        url = f"http://{url}"
    url = url.rstrip("/")
    
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            
            # Skip if no name
            if not name:
                continue
            
            # Build model ID
            if host_alias == "default":
                model_id = f"ollama/{name}"
            else:
                model_id = f"ollama@{host_alias}/{name}"
            
            # Determine capabilities from model name
            is_embedding = "embed" in name.lower() or "nomic" in name.lower()
            supports_vision = "vision" in name.lower() or "llava" in name.lower()
            supports_reasoning = any(x in name.lower() for x in [
                "deepseek-r1", "qwq", "thinking"
            ])
            
            # Size
            size_gb = None
            size_bytes = m.get("size")
            if size_bytes:
                size_gb = size_bytes / (1024 ** 3)
            
            models.append(DiscoveredModel(
                id=model_id,
                name=name,
                provider="ollama",
                host=host_alias,
                is_embedding=is_embedding,
                is_chat=not is_embedding,
                supports_vision=supports_vision,
                supports_reasoning=supports_reasoning,
                size_gb=size_gb,
            ))
        
        return models
    except Exception as e:
        print(f"Error fetching Ollama models from {url}: {e}")
        return []


def get_recommended_defaults() -> Dict[str, str]:
    """
    Get recommended default models for each tier (OpenRouter).
    These are used as defaults in the bootstrap wizard.
    """
    return {
        "embedding": "qwen/qwen3-embedding-8b",
        "fast": "google/gemini-2.5-flash-lite",
        "standard": "google/gemini-3-flash-preview",
        "quality": "anthropic/claude-sonnet-4",
        "flagship": "anthropic/claude-opus-4",
    }


def filter_models_for_tier(
    models: List[DiscoveredModel],
    tier: str
) -> List[DiscoveredModel]:
    """
    Filter models appropriate for a specific tier.
    
    Args:
        models: All available models
        tier: One of "embedding", "fast", "standard", "quality", "flagship"
    
    Returns:
        Filtered list of suitable models
    """
    if tier == "embedding":
        # Only embedding models
        return [m for m in models if m.is_embedding]
    else:
        # Chat models only (not embedding)
        return [m for m in models if m.is_chat and not m.is_embedding]


def sort_models_for_display(
    models: List[DiscoveredModel],
    tier: str,
    defaults: Dict[str, str]
) -> List[DiscoveredModel]:
    """
    Sort models for display in tier selection.
    
    Prioritizes:
    1. Default/recommended model first
    2. Then by provider (OpenRouter first for cloud tiers)
    3. Then alphabetically
    """
    default_id = defaults.get(tier, "")
    
    def sort_key(m: DiscoveredModel) -> tuple:
        # Default model first
        is_default = 0 if m.id == default_id else 1
        # Then by provider
        provider_order = 0 if m.provider == "openrouter" else 1
        # Then alphabetically
        return (is_default, provider_order, m.name.lower())
    
    return sorted(models, key=sort_key)


def format_model_choice(model: DiscoveredModel, max_name_len: int = 40) -> str:
    """Format a model for display in the selection UI."""
    name = model.name[:max_name_len].ljust(max_name_len)
    source = model.source_display.ljust(12)
    price = model.pricing_display.ljust(12)
    
    if model.size_gb:
        size = f"{model.size_gb:.1f}GB"
        return f"{name} {source} {size}"
    else:
        return f"{name} {source} {price}"
