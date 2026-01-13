"""
Model management for OpenRouter, Ollama, and Vertex AI models.

Handles fetching, verification, and querying of models in ClickHouse.
"""

import json
import time
import httpx
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from .config import get_config
from .db_adapter import get_db


console = Console()


def fetch_models_from_openrouter() -> List[Dict]:
    """
    Fetch all models from OpenRouter API.

    Returns:
        List of model dicts with metadata

    Raises:
        Exception: If API request fails
    """
    config = get_config()

    console.print("[cyan]Fetching models from OpenRouter API...[/cyan]")

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {config.provider_api_key}"}
            )
            response.raise_for_status()
            data = response.json()

        models = data.get("data", [])
        console.print(f"[green]✓[/green] Fetched {len(models)} models")
        return models

    except Exception as e:
        console.print(f"[red]✗ Failed to fetch models: {e}[/red]")
        raise


def scrape_ollama_model_metadata(model_name: str) -> Dict:
    """
    Scrape model metadata from ollama.com library page using regex.

    The page structure uses divs rather than traditional tables.
    We search for the model variant name and extract nearby GB/K values.

    Args:
        model_name: Model name without 'ollama/' prefix (e.g., 'gpt-oss:20b')

    Returns:
        Dict with context_length, parameters, size_gb
        Returns empty dict on error.
    """
    import re

    try:
        # Extract base model name (without tag)
        # e.g., "gpt-oss:20b" -> "gpt-oss"
        base_name = model_name.split(':')[0]

        url = f"https://ollama.com/library/{base_name}"

        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()

        html = response.text

        metadata = {
            'context_length': 0,
            'parameters': None,
            'size_gb': 0,
        }

        # Search for the model variant and extract data after it
        # Pattern: model_name followed by size (GB) and context (K)
        escaped_name = re.escape(model_name).replace('\\:', ':')
        pattern = rf'{escaped_name}.*?(\d+(?:\.\d+)?)\s*GB.*?(\d+)\s*K'

        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)

        if match:
            # Extract size and context from regex groups
            metadata['size_gb'] = float(match.group(1))
            context_k = int(match.group(2))
            metadata['context_length'] = context_k * 1000

            # Extract parameters from variant name (e.g., "20b" -> "20B")
            param_match = re.search(r'(\d+(?:\.\d+)?)\s*b\b', model_name, re.IGNORECASE)
            if param_match:
                metadata['parameters'] = f"{param_match.group(1)}B"

        return metadata

    except Exception as e:
        # Silently fail - metadata is optional
        return {}


def fetch_models_from_ollama(ollama_base_url: str = "http://localhost:11434") -> List[Dict]:
    """
    Fetch all models from local Ollama instance.

    Args:
        ollama_base_url: Base URL for Ollama API (default: http://localhost:11434)

    Returns:
        List of model dicts compatible with OpenRouter schema
    """
    console.print(f"[cyan]Fetching models from Ollama ({ollama_base_url})...[/cyan]")

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{ollama_base_url}/api/tags")
            response.raise_for_status()
            data = response.json()

        ollama_models = []
        raw_models = data.get("models", [])

        console.print(f"[cyan]Scraping metadata from ollama.com...[/cyan]")

        for m in raw_models:
            model_name = m.get("name", "")
            model_id = f"ollama/{model_name}"
            size_bytes = m.get("size", 0)

            # Format size as human-readable
            size_gb = size_bytes / (1024**3)

            # Scrape metadata from ollama.com
            metadata = scrape_ollama_model_metadata(model_name)
            context_length = metadata.get('context_length', 0)
            parameters = metadata.get('parameters', '')

            # Build description with parameters if available
            description_parts = [f"Local Ollama model ({size_gb:.1f}GB)"]
            if parameters:
                description_parts.append(f"{parameters} parameters")

            ollama_models.append({
                "id": model_id,
                "name": model_name,
                "description": " · ".join(description_parts),
                "context_length": context_length,
                "pricing": {
                    "prompt": "0",
                    "completion": "0",
                },
                "architecture": {
                    "modality": "text->text",
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
                "top_provider": {
                    "is_moderated": False,
                },
            })

        console.print(f"[green]✓[/green] Fetched {len(ollama_models)} Ollama models with metadata")
        return ollama_models

    except httpx.ConnectError:
        console.print("[yellow]⚠[/yellow] Ollama not running (skipping local models)")
        return []
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow] Failed to fetch Ollama models: {e}")
        return []


# ============================================================================
# Vertex AI / Google AI Model Discovery
# ============================================================================

# Pricing lookup table for Vertex AI models (per 1M tokens)
# Source: https://cloud.google.com/vertex-ai/generative-ai/pricing
# This is used to enrich dynamically discovered models with pricing info
VERTEX_PRICING_LOOKUP = {
    # Gemini 3 models
    "gemini-3-pro": {"input": 2.00, "output": 12.00, "tier": "flagship"},
    "gemini-3-flash": {"input": 0.50, "output": 3.00, "tier": "fast"},
    "gemini-3-pro-image": {"input": 2.00, "output": 120.00, "tier": "flagship", "type": "image"},
    # Gemini 2.5 models
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00, "tier": "flagship"},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50, "tier": "fast"},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40, "tier": "fast"},
    "gemini-2.5-flash-image": {"input": 0.30, "output": 30.00, "tier": "fast", "type": "image"},
    # Gemini 2.0 models
    "gemini-2.0-flash": {"input": 0.15, "output": 0.60, "tier": "fast"},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30, "tier": "fast"},
    "gemini-2.0-pro": {"input": 1.25, "output": 10.00, "tier": "flagship"},
    # Gemini 1.5 models
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00, "tier": "standard"},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30, "tier": "fast"},
    # Embedding models
    "embedding": {"input": 0.00002, "output": 0.0, "tier": "embedding", "type": "embedding"},
    "text-embedding": {"input": 0.00002, "output": 0.0, "tier": "embedding", "type": "embedding"},
    "gemini-embedding": {"input": 0.00002, "output": 0.0, "tier": "embedding", "type": "embedding"},
    # Imagen models
    "imagen-4": {"input": 0.0, "output": 40.00, "tier": "standard", "type": "image"},
    "imagen-3": {"input": 0.0, "output": 40.00, "tier": "standard", "type": "image"},
    # Veo models (video generation)
    "veo-2": {"input": 0.0, "output": 0.0, "tier": "standard", "type": "video"},
    "veo-3": {"input": 0.0, "output": 0.0, "tier": "standard", "type": "video"},
    # Gemma models (open source, typically free/low cost)
    "gemma": {"input": 0.0, "output": 0.0, "tier": "open"},
}


def _get_google_ai_api_key() -> Optional[str]:
    """
    Get Google AI API key from environment variables.

    Checks multiple common env var names.
    """
    import os
    for key_name in ["GOOGLE_AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"]:
        key = os.getenv(key_name)
        if key:
            return key
    return None


def _get_oauth2_token() -> Optional[str]:
    """
    Get OAuth2 access token from service account credentials.

    Uses GOOGLE_APPLICATION_CREDENTIALS if available.
    Returns None if credentials aren't configured or google-auth isn't installed.
    """
    try:
        from google.oauth2 import service_account
        from google.auth import default as google_auth_default
        from google.auth.transport.requests import Request

        config = get_config()

        # Try service account credentials first
        if config.vertex_credentials_path:
            credentials = service_account.Credentials.from_service_account_file(
                config.vertex_credentials_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform",
                        "https://www.googleapis.com/auth/generative-language"]
            )
        else:
            # Fall back to Application Default Credentials
            credentials, _ = google_auth_default(
                scopes=["https://www.googleapis.com/auth/cloud-platform",
                        "https://www.googleapis.com/auth/generative-language"]
            )

        # Refresh to get token
        if not credentials.valid:
            credentials.refresh(Request())

        return credentials.token

    except ImportError:
        return None
    except Exception as e:
        # Silently fail - will fall back to API key
        return None


def _lookup_pricing(model_id: str) -> Dict:
    """
    Look up pricing info for a model ID using prefix matching.

    Args:
        model_id: Model ID like "gemini-2.5-flash-001"

    Returns:
        Pricing dict with input, output, tier, and optionally type
    """
    model_lower = model_id.lower()

    # Try exact match first
    if model_lower in VERTEX_PRICING_LOOKUP:
        return VERTEX_PRICING_LOOKUP[model_lower]

    # Try prefix matching (most specific first)
    # Sort by length descending to match most specific prefix
    for prefix in sorted(VERTEX_PRICING_LOOKUP.keys(), key=len, reverse=True):
        if model_lower.startswith(prefix):
            return VERTEX_PRICING_LOOKUP[prefix]

    # Default for unknown models
    return {"input": 0.0, "output": 0.0, "tier": "standard"}


def fetch_models_from_google_ai_api() -> List[Dict]:
    """
    Fetch models from Google AI (Generative Language) API.

    Uses the public API at generativelanguage.googleapis.com/v1beta/models
    which lists all available Gemini models.

    Authentication methods (tried in order):
    1. OAuth2 via GOOGLE_APPLICATION_CREDENTIALS (service account)
    2. API key via GOOGLE_AI_API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY

    Returns:
        List of model dicts with full metadata, or empty list on failure
    """
    # Try OAuth2 authentication first (uses GOOGLE_APPLICATION_CREDENTIALS)
    oauth_token = _get_oauth2_token()
    api_key = _get_google_ai_api_key()

    if not oauth_token and not api_key:
        console.print("[yellow]⚠[/yellow] No Google credentials found")
        console.print("    Set GOOGLE_APPLICATION_CREDENTIALS (service account) or GOOGLE_AI_API_KEY")
        return []

    console.print("[cyan]Fetching models from Google AI API...[/cyan]")

    try:
        # Build request based on available auth
        if oauth_token:
            url = "https://generativelanguage.googleapis.com/v1beta/models"
            headers = {"Authorization": f"Bearer {oauth_token}"}
            auth_method = "OAuth2 (service account)"
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            headers = {}
            auth_method = "API key"

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)

            # If OAuth2 fails with 401/403, try API key as fallback
            if response.status_code in (401, 403) and oauth_token and api_key:
                console.print(f"[yellow]⚠[/yellow] OAuth2 auth failed, trying API key...")
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                response = client.get(url)
                auth_method = "API key (fallback)"

            response.raise_for_status()
            data = response.json()

        if "error" in data:
            console.print(f"[yellow]⚠[/yellow] API error: {data['error'].get('message', data['error'])}")
            return []

        models = []
        for m in data.get("models", []):
            # Extract model ID from "models/gemini-2.5-flash" format
            name = m.get("name", "")
            model_id = name.replace("models/", "") if name.startswith("models/") else name

            if not model_id:
                continue

            # Get pricing info
            pricing = _lookup_pricing(model_id)

            # Determine model type from supported methods
            methods = m.get("supportedGenerationMethods", [])
            model_type = "text"
            if "predict" in methods or "predictLongRunning" in methods:
                # Imagen/Veo models use predict
                if "imagen" in model_id.lower():
                    model_type = "image"
                elif "veo" in model_id.lower():
                    model_type = "video"
            elif "image" in model_id.lower():
                model_type = "image"
            elif "embedding" in model_id.lower() or "embedContent" in methods:
                model_type = "embedding"

            # Override with pricing lookup type if specified
            if "type" in pricing:
                model_type = pricing["type"]

            # Determine input modalities from methods
            input_mods = ["text"]
            if "generateContent" in methods:
                input_mods = ["text", "image", "audio", "video"]  # Gemini models are multimodal
            elif model_type == "embedding":
                input_mods = ["text"]

            # Determine output modalities
            output_mods = ["text"]
            if model_type == "image":
                output_mods = ["image"]
            elif model_type == "video":
                output_mods = ["video"]
            elif model_type == "embedding":
                output_mods = ["embedding"]

            models.append({
                "model_id": model_id,
                "name": m.get("displayName", model_id),
                "description": m.get("description", ""),
                "context_length": m.get("inputTokenLimit", 0),
                "output_token_limit": m.get("outputTokenLimit", 0),
                "input_modalities": input_mods,
                "output_modalities": output_mods,
                "supported_methods": methods,
                "prompt_price": pricing.get("input", 0),
                "completion_price": pricing.get("output", 0),
                "tier": pricing.get("tier", "standard"),
                "model_type": model_type,
            })

        console.print(f"[green]✓[/green] Fetched {len(models)} models from Google AI API ({auth_method})")
        return models

    except httpx.HTTPStatusError as e:
        console.print(f"[yellow]⚠[/yellow] Google AI API HTTP error: {e.response.status_code}")
        return []
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow] Google AI API error: {e}")
        return []


def fetch_models_from_vertex() -> List[Dict]:
    """
    Fetch Vertex AI / Google AI models dynamically.

    Uses the Google AI API (generativelanguage.googleapis.com) to discover
    all available Gemini models. This is the same set of models available
    on Vertex AI.

    Requires one of these environment variables:
    - GOOGLE_AI_API_KEY
    - GEMINI_API_KEY
    - GOOGLE_API_KEY

    Also requires RVBBIT_VERTEX_PROJECT to be set for the models to be
    included in the catalog (indicating Vertex AI is configured).

    Returns:
        List of model dicts compatible with OpenRouter schema
    """
    config = get_config()

    # Check if Vertex AI is configured
    if not config.vertex_project:
        console.print("[yellow]⚠[/yellow] Vertex AI not configured (no RVBBIT_VERTEX_PROJECT)")
        return []

    console.print(f"[cyan]Discovering Vertex AI models (project: {config.vertex_project})...[/cyan]")

    # Fetch models from Google AI API
    api_models = fetch_models_from_google_ai_api()

    if not api_models:
        console.print("[yellow]⚠[/yellow] No models discovered - check GOOGLE_AI_API_KEY")
        return []

    # Filter to only include relevant models for Vertex AI
    # Skip internal/experimental models that aren't useful
    filtered_models = []
    skip_patterns = ["aqa", "gecko"]  # Skip legacy/internal models

    for m in api_models:
        model_id = m["model_id"].lower()

        # Skip models matching skip patterns
        if any(pattern in model_id for pattern in skip_patterns):
            continue

        # Skip models without useful generation methods
        methods = m.get("supported_methods", [])
        if not methods:
            continue

        filtered_models.append(m)

    # Transform to OpenRouter-compatible format
    vertex_models = []
    for m in filtered_models:
        model_type = m.get("model_type", "text")

        vertex_models.append({
            "id": f"vertex_ai/{m['model_id']}",
            "name": m["name"],
            "description": m.get("description", ""),
            "context_length": m.get("context_length", 0),
            "pricing": {
                "prompt": str(m.get("prompt_price", 0) / 1_000_000),  # Convert to per-token
                "completion": str(m.get("completion_price", 0) / 1_000_000),
            },
            "architecture": {
                "modality": f"{'text+image' if 'image' in m.get('input_modalities', []) else 'text'}->{'+'.join(m.get('output_modalities', ['text']))}",
                "input_modalities": m.get("input_modalities", ["text"]),
                "output_modalities": m.get("output_modalities", ["text"]),
            },
            "top_provider": {
                "is_moderated": False,
            },
            "_vertex_tier": m.get("tier", "standard"),
            "_model_type": model_type,
        })

    console.print(f"[green]✓[/green] Prepared {len(vertex_models)} Vertex AI models")
    return vertex_models


# ============================================================================
# Azure OpenAI Model Discovery
# ============================================================================

# Import pricing from azure_cost module (avoids duplication)
def _get_azure_pricing(model_name: str) -> Dict:
    """
    Get Azure OpenAI pricing for a model.

    Args:
        model_name: Model name without azure/ prefix

    Returns:
        Dict with input, output, tier
    """
    try:
        from .azure_cost import get_pricing, get_model_tier
        pricing = get_pricing(model_name)
        return {
            "input": pricing.get("input", 0.0),
            "output": pricing.get("output", 0.0),
            "tier": pricing.get("tier", "standard"),
        }
    except ImportError:
        return {"input": 0.0, "output": 0.0, "tier": "standard"}


def fetch_models_from_azure() -> List[Dict]:
    """
    Azure OpenAI model discovery.

    Note: Azure OpenAI deployments API requires Azure AD auth which we don't support.
    We cannot discover deployed models, so we don't add anything to the catalog.

    Users should use azure/<deployment-name> directly with their deployment name
    from Azure Portal. The inference routing in agent.py handles this.

    Returns:
        Empty list (deployment discovery not supported)
    """
    config = get_config()

    # Check if Azure OpenAI is configured
    if not config.azure_enabled:
        return []

    # Azure is configured but we can't discover deployments (requires Azure AD)
    # Just log that it's available for manual use
    console.print("[cyan]Azure OpenAI configured[/cyan]")
    console.print("[dim]Use azure/<your-deployment-name> directly (deployment discovery not supported)[/dim]")

    # Return empty - we can't discover what's actually deployed
    # The catalog would just show "maybe available" models which is misleading
    return []


# ============================================================================
# AWS Bedrock Model Discovery
# ============================================================================

# Fallback pricing table for Bedrock (used when Pricing API is not accessible)
# Prices per 1M tokens, updated periodically
# Source: https://aws.amazon.com/bedrock/pricing/
BEDROCK_FALLBACK_PRICING = {
    # Anthropic Claude models
    "anthropic.claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "anthropic.claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "anthropic.claude-3-sonnet": {"input": 3.00, "output": 15.00},
    "anthropic.claude-3-haiku": {"input": 0.25, "output": 1.25},
    "anthropic.claude-3-opus": {"input": 15.00, "output": 75.00},
    "anthropic.claude-v2": {"input": 8.00, "output": 24.00},
    "anthropic.claude-instant": {"input": 0.80, "output": 2.40},
    # Amazon Titan models
    "amazon.titan-text-premier": {"input": 0.50, "output": 1.50},
    "amazon.titan-text-express": {"input": 0.20, "output": 0.60},
    "amazon.titan-text-lite": {"input": 0.15, "output": 0.20},
    "amazon.titan-embed": {"input": 0.10, "output": 0.0},
    # Meta Llama models
    "meta.llama3-2-90b": {"input": 2.00, "output": 2.00},
    "meta.llama3-2-11b": {"input": 0.35, "output": 0.35},
    "meta.llama3-2-3b": {"input": 0.15, "output": 0.15},
    "meta.llama3-2-1b": {"input": 0.10, "output": 0.10},
    "meta.llama3-1-405b": {"input": 5.32, "output": 16.00},
    "meta.llama3-1-70b": {"input": 2.65, "output": 3.50},
    "meta.llama3-1-8b": {"input": 0.30, "output": 0.60},
    "meta.llama3-70b": {"input": 2.65, "output": 3.50},
    "meta.llama3-8b": {"input": 0.30, "output": 0.60},
    # Mistral models
    "mistral.mistral-large": {"input": 4.00, "output": 12.00},
    "mistral.mistral-small": {"input": 1.00, "output": 3.00},
    "mistral.mixtral-8x7b": {"input": 0.45, "output": 0.70},
    "mistral.mistral-7b": {"input": 0.15, "output": 0.20},
    # Cohere models
    "cohere.command-r-plus": {"input": 3.00, "output": 15.00},
    "cohere.command-r": {"input": 0.50, "output": 1.50},
    "cohere.command-text": {"input": 1.50, "output": 2.00},
    "cohere.command-light": {"input": 0.30, "output": 0.60},
    "cohere.embed": {"input": 0.10, "output": 0.0},
    # AI21 models
    "ai21.jamba-1-5-large": {"input": 2.00, "output": 8.00},
    "ai21.jamba-1-5-mini": {"input": 0.20, "output": 0.40},
    "ai21.j2-ultra": {"input": 18.80, "output": 18.80},
    "ai21.j2-mid": {"input": 12.50, "output": 12.50},
    # Stability AI models
    "stability.stable-diffusion": {"input": 0.0, "output": 0.04},  # Per image
    "stability.sd3-large": {"input": 0.0, "output": 0.08},
}


def _fetch_bedrock_pricing(region: str = "us-east-1") -> Dict[str, Dict]:
    """
    Fetch current Bedrock pricing from AWS Pricing API.

    The Pricing API is only available in us-east-1 and ap-south-1.
    Prices are returned per 1000 input/output tokens (or per 1M for some).

    Args:
        region: AWS region (pricing API queries us-east-1 regardless)

    Returns:
        Dict mapping model ID to pricing info: {model_id: {"input": float, "output": float}}
    """
    try:
        import boto3

        # Show which AWS identity we're using
        try:
            sts = boto3.client('sts')
            identity = sts.get_caller_identity()
            console.print(f"[dim]AWS Identity: {identity.get('Arn', 'unknown')}[/dim]")
        except Exception as e:
            console.print(f"[dim]Could not get AWS identity: {e}[/dim]")

        # Pricing API is only available in us-east-1
        pricing_client = boto3.client('pricing', region_name='us-east-1')

        pricing_data = {}

        # Get all Bedrock products
        paginator = pricing_client.get_paginator('get_products')

        page_count = 0
        item_count = 0

        for page in paginator.paginate(
            ServiceCode='AmazonBedrock',
            MaxResults=100
        ):
            page_count += 1
            price_list = page.get('PriceList', [])
            item_count += len(price_list)

            for price_item_json in price_list:
                try:
                    import json
                    price_item = json.loads(price_item_json)

                    # Extract model ID from attributes
                    attrs = price_item.get('product', {}).get('attributes', {})
                    model_id = attrs.get('inferenceType', '')
                    usage_type = attrs.get('usagetype', '')

                    # Get model name from 'model' attribute (cleaner than parsing usagetype)
                    model_name = attrs.get('model', '')

                    # Parse the pricing terms
                    terms = price_item.get('terms', {}).get('OnDemand', {})
                    for _, term_data in terms.items():
                        price_dimensions = term_data.get('priceDimensions', {})
                        for _, dim_data in price_dimensions.items():
                            price_per_unit = float(dim_data.get('pricePerUnit', {}).get('USD', 0))

                            # Skip zero prices and non-token pricing
                            if price_per_unit == 0:
                                continue

                            # Use 'model' attribute if available, else extract from usagetype
                            # Format: REGION-ModelName-input-token-count
                            usage_lower = usage_type.lower()

                            # Get model key from 'model' attribute or extract from usagetype
                            if model_name:
                                model_key = model_name.lower()
                            else:
                                # Extract model name from usagetype (after region prefix)
                                parts = usage_type.split('-')
                                if len(parts) >= 2:
                                    # Skip region prefix (e.g., "USW2", "EUS1")
                                    # Find where model name starts
                                    model_parts = []
                                    for part in parts[1:]:
                                        if 'input' in part.lower() or 'output' in part.lower():
                                            break
                                        model_parts.append(part)
                                    model_key = '-'.join(model_parts).lower() if model_parts else ''
                                else:
                                    model_key = ''

                            if not model_key:
                                continue

                            # Check for input/output token pricing (lowercase patterns)
                            if 'input-token' in usage_lower or 'input token' in usage_lower:
                                if model_key not in pricing_data:
                                    pricing_data[model_key] = {"input": 0, "output": 0}
                                # Price is per 1000 tokens, convert to per 1M
                                pricing_data[model_key]["input"] = price_per_unit * 1000

                            elif 'output-token' in usage_lower or 'output token' in usage_lower:
                                if model_key not in pricing_data:
                                    pricing_data[model_key] = {"input": 0, "output": 0}
                                pricing_data[model_key]["output"] = price_per_unit * 1000

                except Exception as e:
                    # Skip malformed pricing entries
                    continue

        if page_count == 0:
            console.print("[dim]Pricing API returned no pages[/dim]")
        else:
            console.print(f"[dim]Pricing API total: {item_count} items, parsed {len(pricing_data)} model prices[/dim]")

        return pricing_data

    except ImportError:
        console.print("[yellow]⚠[/yellow] boto3 not installed - cannot fetch Bedrock pricing")
        return {}
    except Exception as e:
        error_str = str(e)
        if "AccessDeniedException" in error_str or "not authorized" in error_str:
            console.print(f"[yellow]⚠[/yellow] Pricing API access denied - need pricing:GetProducts permission")
        else:
            console.print(f"[yellow]⚠[/yellow] Failed to fetch Bedrock pricing: {e}")
        return {}


def _match_bedrock_pricing(model_id: str, pricing_data: Dict[str, Dict]) -> Dict:
    """
    Match a Bedrock model ID to pricing data.

    Uses dynamic pricing if available, falls back to static table.

    Args:
        model_id: Bedrock model ID (e.g., "anthropic.claude-3-sonnet-20240229-v1:0")
        pricing_data: Dict from _fetch_bedrock_pricing() (may be empty)

    Returns:
        Pricing dict with input/output per 1M tokens
    """
    model_lower = model_id.lower()

    # Try dynamic pricing first (from AWS Pricing API)
    if pricing_data:
        if model_lower in pricing_data:
            return pricing_data[model_lower]
        for key in pricing_data:
            if model_lower.startswith(key) or key in model_lower:
                return pricing_data[key]

    # Fall back to static pricing table
    # Try exact match first
    for key in BEDROCK_FALLBACK_PRICING:
        if model_lower.startswith(key) or key in model_lower:
            return BEDROCK_FALLBACK_PRICING[key]

    # Default pricing (unknown model)
    return {"input": 0.0, "output": 0.0}


def fetch_models_from_bedrock() -> List[Dict]:
    """
    Fetch available models from AWS Bedrock.

    Uses boto3 to:
    1. List foundation models available in the account
    2. Fetch dynamic pricing from AWS Pricing API
    3. Combine into model catalog

    Requires AWS credentials (via env vars, ~/.aws/credentials, or IAM role).

    Returns:
        List of model dicts compatible with OpenRouter schema
    """
    config = get_config()

    if not config.bedrock_enabled:
        return []

    try:
        import boto3
    except ImportError:
        console.print("[yellow]⚠[/yellow] boto3 not installed - run: pip install boto3")
        return []

    console.print(f"[cyan]Fetching models from AWS Bedrock (region: {config.bedrock_region})...[/cyan]")

    try:
        # Create Bedrock client
        bedrock = boto3.client('bedrock', region_name=config.bedrock_region)

        # List all foundation models
        response = bedrock.list_foundation_models()
        foundation_models = response.get('modelSummaries', [])

        if not foundation_models:
            console.print("[yellow]⚠[/yellow] No Bedrock models found - check AWS credentials and region")
            return []

        # Also fetch inference profiles (these are directly callable, even for models
        # that don't support ON_DEMAND on the base model ID)
        inference_profiles = []
        try:
            profiles_response = bedrock.list_inference_profiles()
            inference_profiles = profiles_response.get('inferenceProfileSummaries', [])
            if inference_profiles:
                console.print(f"[dim]Found {len(inference_profiles)} inference profiles[/dim]")
        except Exception as e:
            console.print(f"[dim]Could not fetch inference profiles: {e}[/dim]")

        # Fetch dynamic pricing
        console.print("[cyan]Fetching Bedrock pricing from AWS Pricing API...[/cyan]")
        pricing_data = _fetch_bedrock_pricing(config.bedrock_region)

        if pricing_data:
            console.print(f"[green]✓[/green] Fetched dynamic pricing for {len(pricing_data)} model variants")
        else:
            console.print(f"[yellow]⚠[/yellow] Using fallback pricing table ({len(BEDROCK_FALLBACK_PRICING)} models)")
            console.print("[dim]Grant pricing:GetProducts permission for dynamic pricing[/dim]")

        bedrock_models = []
        skipped_no_ondemand = 0

        # First, add inference profiles (these are always callable)
        for profile in inference_profiles:
            profile_id = profile.get('inferenceProfileId', '')
            profile_name = profile.get('inferenceProfileName', profile_id)

            if not profile_id:
                continue

            # Extract base model info from the profile
            # Profile IDs look like: us.amazon.nova-premier-v1:0 or amazon.nova-premier-v1:0:1000k
            provider = "amazon"
            if "anthropic" in profile_id.lower():
                provider = "anthropic"
            elif "meta" in profile_id.lower():
                provider = "meta"
            elif "mistral" in profile_id.lower():
                provider = "mistral"
            elif "cohere" in profile_id.lower():
                provider = "cohere"

            # Get pricing for the base model
            pricing = _match_bedrock_pricing(profile_id, pricing_data)

            bedrock_models.append({
                "id": f"bedrock/{profile_id}",
                "name": f"{profile_name} (Inference Profile)",
                "description": f"AWS Bedrock Inference Profile - {provider}",
                "context_length": 200000,  # Inference profiles typically have large context
                "pricing": {
                    "prompt": str(pricing.get("input", 0) / 1_000_000),
                    "completion": str(pricing.get("output", 0) / 1_000_000),
                },
                "architecture": {
                    "modality": "text->text",
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
                "top_provider": {
                    "is_moderated": True,
                },
                "_bedrock_tier": "standard",
                "_model_type": "text",
                "_provider": provider.lower(),
                "_is_active": True,
                "_is_inference_profile": True,
            })

        # Then add foundation models that support ON_DEMAND inference
        for model in foundation_models:
            model_id = model.get('modelId', '')
            model_name = model.get('modelName', model_id)
            provider = model.get('providerName', 'unknown')

            if not model_id:
                continue

            # Check if model supports ON_DEMAND inference
            inference_types = model.get('inferenceTypesSupported', [])
            if 'ON_DEMAND' not in inference_types:
                skipped_no_ondemand += 1
                continue  # Skip models that require provisioned throughput or inference profiles

            # Get input/output modalities
            input_modalities = model.get('inputModalities', ['TEXT'])
            output_modalities = model.get('outputModalities', ['TEXT'])

            # Normalize modality names
            input_mods = [m.lower() for m in input_modalities]
            output_mods = [m.lower() for m in output_modalities]

            # Determine model type
            model_type = "text"
            if "image" in output_mods:
                model_type = "image"
            elif "embedding" in output_mods or model.get('modelLifecycle', {}).get('status') == 'EMBEDDING':
                model_type = "embedding"

            # Get pricing (dynamic from API)
            pricing = _match_bedrock_pricing(model_id, pricing_data)

            # Determine tier based on provider and pricing
            tier = "standard"
            if pricing.get("input", 0) > 10:
                tier = "flagship"
            elif pricing.get("input", 0) < 1:
                tier = "fast"
            if "lite" in model_id.lower() or "instant" in model_id.lower():
                tier = "fast"
            if "opus" in model_id.lower() or "large" in model_id.lower():
                tier = "flagship"

            # Check if model is active/available
            lifecycle = model.get('modelLifecycle', {})
            is_active = lifecycle.get('status', 'ACTIVE') == 'ACTIVE'

            # Build modality string
            modality_str = f"{'+'.join(input_mods)}->{'+'.join(output_mods)}"

            bedrock_models.append({
                "id": f"bedrock/{model_id}",
                "name": f"{model_name} ({provider})",
                "description": f"AWS Bedrock - {provider}",
                "context_length": model.get('responseStreamingSupported', False) and 200000 or 100000,
                "pricing": {
                    "prompt": str(pricing.get("input", 0) / 1_000_000),  # Convert to per-token
                    "completion": str(pricing.get("output", 0) / 1_000_000),
                },
                "architecture": {
                    "modality": modality_str,
                    "input_modalities": input_mods,
                    "output_modalities": output_mods,
                },
                "top_provider": {
                    "is_moderated": True,  # Bedrock has content moderation
                },
                "_bedrock_tier": tier,
                "_model_type": model_type,
                "_provider": provider.lower(),
                "_is_active": is_active,
            })

        if skipped_no_ondemand > 0:
            console.print(f"[dim]Skipped {skipped_no_ondemand} models requiring provisioned throughput[/dim]")
        console.print(f"[green]✓[/green] Fetched {len(bedrock_models)} Bedrock models")
        return bedrock_models

    except Exception as e:
        error_msg = str(e)
        if "credentials" in error_msg.lower() or "UnauthorizedAccess" in error_msg:
            console.print("[yellow]⚠[/yellow] AWS credentials not configured or insufficient permissions")
            console.print("[dim]Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or configure ~/.aws/credentials[/dim]")
        elif "Could not connect" in error_msg:
            console.print(f"[yellow]⚠[/yellow] Could not connect to Bedrock in {config.bedrock_region}")
        else:
            console.print(f"[yellow]⚠[/yellow] Bedrock API error: {e}")
        return []


def classify_tier(pricing: Dict, context_length: int, model_id: str) -> str:
    """
    Classify model into tier based on pricing and characteristics.

    Args:
        pricing: Pricing dict with 'prompt' and 'completion' keys (price per token)
        context_length: Model context window size
        model_id: Full model ID

    Returns:
        Tier string: 'local', 'flagship', 'standard', 'fast', 'open', or 'embedding'
    """
    # Check if it's a local Ollama model
    if model_id.startswith("ollama/"):
        return "local"

    # Check if it's a Vertex AI model (use pricing lookup for tier)
    if model_id.startswith("vertex_ai/"):
        # Extract model name without prefix
        model_name = model_id[10:]  # len("vertex_ai/") = 10
        pricing_info = _lookup_pricing(model_name)
        return pricing_info.get("tier", "standard")

    # Check if it's an Azure OpenAI model (use pricing lookup for tier)
    if model_id.startswith("azure/"):
        # Extract model name without prefix
        model_name = model_id[6:]  # len("azure/") = 6
        pricing_info = _get_azure_pricing(model_name)
        return pricing_info.get("tier", "standard")

    # Check if it's a Bedrock model (tier determined during fetch)
    if model_id.startswith("bedrock/"):
        # Bedrock tier is determined dynamically from pricing during model fetch
        # Fall through to price-based classification
        pass

    prompt_price = float(pricing.get("prompt", 0))

    # Check if it's an open-source model
    open_indicators = ["llama", "mixtral", "mistral", "qwen", "deepseek", "yi"]
    if any(indicator in model_id.lower() for indicator in open_indicators):
        return "open"

    # Price-based classification (per token, so multiply by 1M for per-million-tokens)
    if prompt_price > 0.00001:  # > $10/M tokens
        return "flagship"
    elif prompt_price > 0.0000001:  # > $0.10/M tokens
        return "standard"
    else:
        return "fast"


def determine_model_type(arch: Dict) -> str:
    """
    Determine if model is text or image based on output modalities.

    Args:
        arch: Architecture dict with 'output_modalities' key

    Returns:
        'image' if model can generate images, else 'text'
    """
    output_mods = arch.get("output_modalities", [])
    return "image" if "image" in output_mods else "text"


def verify_model_active(model_id: str, api_key: str) -> Tuple[bool, Optional[str]]:
    """
    Verify that a model is active by making a minimal completion request.

    Args:
        model_id: Full model ID (e.g., 'openai/gpt-4o')
        api_key: OpenRouter API key

    Returns:
        Tuple of (is_active, error_message)
        - is_active=True if model endpoint responds (even with error about request format)
        - is_active=False if model is unavailable (404, 503, etc.)
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "x"}],
                    "max_tokens": 1
                }
            )

            # Any successful response (200) or bad request (400) means model is active
            # 400 is fine - it means the model endpoint exists but our request was invalid
            if response.status_code in (200, 400):
                return (True, None)

            # 404 or 503 means model is unavailable
            if response.status_code in (404, 503):
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", "Model unavailable")
                except:
                    error_msg = f"HTTP {response.status_code}"
                return (False, error_msg)

            # Other errors - assume active (conservative approach to avoid false negatives)
            return (True, None)

    except httpx.TimeoutException:
        return (False, "Verification timeout")
    except Exception as e:
        # On unexpected error, assume active (conservative approach)
        return (True, None)


def verify_models_parallel(
    models: List[Dict],
    api_key: str,
    workers: int = 10
) -> Dict[str, Tuple[bool, Optional[str]]]:
    """
    Verify models in parallel using ThreadPoolExecutor.

    Args:
        models: List of model dicts with 'id' key
        api_key: OpenRouter API key
        workers: Number of parallel workers

    Returns:
        Dict mapping model_id -> (is_active, error_message)
    """
    results = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:

        task = progress.add_task(
            "[cyan]Verifying models...",
            total=len(models)
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all verification tasks
            future_to_model = {
                executor.submit(verify_model_active, m["id"], api_key): m["id"]
                for m in models
            }

            # Collect results as they complete
            for future in as_completed(future_to_model):
                model_id = future_to_model[future]
                try:
                    is_active, error = future.result()
                    results[model_id] = (is_active, error)
                    progress.advance(task)

                    # Rate limiting: small delay between completions
                    time.sleep(0.01)

                except Exception as e:
                    # On exception, mark as active (conservative)
                    results[model_id] = (True, None)
                    progress.advance(task)

    return results


def refresh_models(skip_verification: bool = False, workers: int = 10):
    """
    Main refresh function: fetch models from OpenRouter, Ollama, Vertex AI, and Bedrock, then populate ClickHouse.

    Note: Azure OpenAI deployment discovery requires Azure AD auth which we don't support.
    Use azure/<deployment-name> directly with your deployment name from Azure Portal.

    Args:
        skip_verification: If True, skip verification step (faster but less accurate)
        workers: Number of parallel verification workers
    """
    config = get_config()
    db = get_db()

    console.print("\n[bold cyan]╔════════════════════════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║  Model Refresh (OpenRouter + Ollama + Vertex AI + Bedrock)     ║[/bold cyan]")
    console.print("[bold cyan]╚════════════════════════════════════════════════════════════════╝[/bold cyan]\n")

    # Step 1a: Fetch models from OpenRouter
    try:
        openrouter_models = fetch_models_from_openrouter()
    except Exception:
        console.print("\n[red]✗ OpenRouter fetch failed - keeping existing data[/red]")
        return

    # Step 1b: Fetch models from Ollama (non-fatal if unavailable)
    ollama_models = fetch_models_from_ollama()

    # Step 1c: Fetch models from Vertex AI (non-fatal if not configured)
    vertex_models = fetch_models_from_vertex()

    # Step 1d: Check Azure OpenAI (discovery not supported, just logs status)
    fetch_models_from_azure()

    # Step 1e: Fetch models from AWS Bedrock (non-fatal if not configured)
    bedrock_models = fetch_models_from_bedrock()

    # Combine all models (Azure returns empty - discovery requires Azure AD)
    raw_models = openrouter_models + ollama_models + vertex_models + bedrock_models
    console.print(f"\n[green]✓[/green] Total models: {len(raw_models)} "
                 f"(OpenRouter: {len(openrouter_models)}, Ollama: {len(ollama_models)}, "
                 f"Vertex AI: {len(vertex_models)}, Bedrock: {len(bedrock_models)})\n")

    # Step 2: Verify OpenRouter models only (Ollama models are always active)
    verification_results = {}
    if not skip_verification:
        verification_results = verify_models_parallel(
            openrouter_models,  # Only verify OpenRouter models
            config.provider_api_key,
            workers=workers
        )

        active_count = sum(1 for is_active, _ in verification_results.values() if is_active)
        console.print(f"[green]✓[/green] Verified {len(verification_results)} models "
                     f"({active_count} active, {len(verification_results) - active_count} inactive)")

    # Step 3: Transform to table rows
    console.print("[cyan]Transforming model data...[/cyan]")

    popular_models = {
        # OpenRouter models
        'anthropic/claude-sonnet-4', 'anthropic/claude-opus-4', 'anthropic/claude-haiku',
        'openai/gpt-4o', 'openai/gpt-4o-mini', 'openai/o1', 'openai/o1-mini',
        'google/gemini-2.5-flash', 'google/gemini-2.5-pro',
        'meta-llama/llama-3.3-70b-instruct', 'deepseek/deepseek-chat',
        # Vertex AI models
        'vertex_ai/gemini-2.5-pro', 'vertex_ai/gemini-2.5-flash', 'vertex_ai/gemini-2.5-flash-lite',
        'vertex_ai/gemini-3-pro-preview', 'vertex_ai/gemini-3-flash-preview',
        # Azure OpenAI models
        'azure/gpt-4o', 'azure/gpt-4o-mini', 'azure/gpt-4.1',
        'azure/o1', 'azure/o1-mini', 'azure/o3-mini',
    }

    rows = []
    current_time = datetime.now(timezone.utc)

    for model in raw_models:
        model_id = model.get("id", "")
        provider = model_id.split("/")[0] if "/" in model_id else "other"
        pricing = model.get("pricing", {})
        arch = model.get("architecture", {})

        # Get verification result
        is_active = True
        verification_error = None
        if model_id in verification_results:
            is_active, verification_error = verification_results[model_id]

        # Determine inference type for Bedrock models
        is_inference_profile = model.get("_is_inference_profile", False)
        inference_type = "INFERENCE_PROFILE" if is_inference_profile else "ON_DEMAND"

        row = {
            "model_id": model_id,
            "model_name": model.get("name", model_id),
            "provider": provider,
            "description": model.get("description", ""),
            "context_length": model.get("context_length", 0),
            "tier": classify_tier(pricing, model.get("context_length", 0), model_id),
            "popular": model_id in popular_models,
            "model_type": determine_model_type(arch),
            "input_modalities": arch.get("input_modalities", []),
            "output_modalities": arch.get("output_modalities", []),
            "prompt_price": float(pricing.get("prompt", 0)),
            "completion_price": float(pricing.get("completion", 0)),
            "is_active": is_active,
            "verification_error": verification_error,
            "inference_type": inference_type,
            "is_inference_profile": is_inference_profile,
            "metadata_json": json.dumps({
                "top_provider": model.get("top_provider", {}),
                "architecture": arch
            }),
            "updated_at": current_time
        }

        rows.append(row)

    # Step 4: Truncate existing data and insert fresh models
    console.print(f"[cyan]Replacing models in ClickHouse...[/cyan]")

    try:
        # Truncate table to avoid duplicates
        db.execute("TRUNCATE TABLE openrouter_models")

        # Insert fresh data
        db.insert_rows("openrouter_models", rows)
        console.print(f"[green]✓[/green] Successfully inserted {len(rows)} models")
    except Exception as e:
        console.print(f"[red]✗ Failed to insert models: {e}[/red]")
        raise

    # Step 5: Show summary
    console.print("\n[bold green]✓ Refresh complete![/bold green]\n")
    show_stats()


def list_models(
    include_inactive: bool = False,
    model_type: str = "all",
    provider: Optional[str] = None,
    limit: int = 50
):
    """
    List models from database with Rich table formatting.

    Args:
        include_inactive: If True, include inactive models
        model_type: Filter by 'text', 'image', or 'all'
        provider: Filter by provider name
        limit: Max models to show
    """
    db = get_db()

    # Build query
    where_clauses = []
    if not include_inactive:
        where_clauses.append("is_active = true")
    if model_type != "all":
        where_clauses.append(f"model_type = '{model_type}'")
    if provider:
        where_clauses.append(f"provider = '{provider}'")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    query = f"""
        SELECT
            model_id,
            model_name,
            provider,
            tier,
            model_type,
            is_active,
            prompt_price,
            context_length,
            last_verified
        FROM openrouter_models FINAL
        WHERE {where_sql}
        ORDER BY popular DESC, tier, model_id
        LIMIT {limit}
    """

    results = db.query(query)

    # Display with Rich table
    table = Table(title=f"OpenRouter Models (showing {len(results)})")
    table.add_column("Model ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Provider", style="magenta")
    table.add_column("Tier", style="yellow")
    table.add_column("Type", style="blue")
    table.add_column("Active", style="green")
    table.add_column("Price/M", justify="right", style="green")
    table.add_column("Context", justify="right")

    for row in results:
        table.add_row(
            row["model_id"],
            row["model_name"][:40] if len(row["model_name"]) > 40 else row["model_name"],
            row["provider"],
            row["tier"],
            row["model_type"],
            "✓" if row["is_active"] else "✗",
            f"${row['prompt_price']*1000000:.2f}",
            f"{row['context_length']:,}"
        )

    console.print(table)


def verify_models(workers: int = 10, model_id: Optional[str] = None):
    """
    Re-verify existing models without re-fetching from API.

    Args:
        workers: Number of parallel workers
        model_id: If specified, verify only this model
    """
    config = get_config()
    db = get_db()

    console.print("\n[bold cyan]Re-verifying models...[/bold cyan]\n")

    # Get models to verify
    if model_id:
        query = f"SELECT model_id FROM openrouter_models FINAL WHERE model_id = '{model_id}'"
    else:
        query = "SELECT model_id FROM openrouter_models FINAL"

    results = db.query(query)
    model_ids = [{"id": r["model_id"]} for r in results]

    if not model_ids:
        console.print("[yellow]No models found to verify[/yellow]")
        return

    # Verify
    verification_results = verify_models_parallel(
        model_ids,
        config.provider_api_key,
        workers=workers
    )

    # Update database
    console.print(f"[cyan]Updating {len(verification_results)} models...[/cyan]")

    current_time = datetime.now(timezone.utc)
    update_rows = []
    for mid, (is_active, error) in verification_results.items():
        update_rows.append({
            "model_id": mid,
            "is_active": is_active,
            "verification_error": error,
            "last_verified": current_time,
            "updated_at": current_time
        })

    db.insert_rows("openrouter_models", update_rows)

    active_count = sum(1 for is_active, _ in verification_results.values() if is_active)
    console.print(f"\n[green]✓[/green] Updated {len(verification_results)} models "
                 f"({active_count} active, {len(verification_results) - active_count} inactive)")


def show_stats():
    """Show model statistics."""
    db = get_db()

    # Overall stats
    stats_query = """
        SELECT
            count() as total,
            countIf(is_active) as active,
            countIf(NOT is_active) as inactive,
            countIf(model_type = 'text') as text_models,
            countIf(model_type = 'image') as image_models
        FROM openrouter_models FINAL
    """

    stats = db.query(stats_query)

    if not stats or stats[0]['total'] == 0:
        console.print("[yellow]No models in database. Run 'rvbbit models refresh' first.[/yellow]")
        return

    stats = stats[0]

    # Provider breakdown
    provider_query = """
        SELECT
            provider,
            count() as total,
            countIf(is_active) as active
        FROM openrouter_models FINAL
        GROUP BY provider
        ORDER BY total DESC
        LIMIT 10
    """

    providers = db.query(provider_query)

    # Display
    console.print("\n[bold]Model Statistics[/bold]\n")
    console.print(f"Total models:       {stats['total']:>5}")
    console.print(f"  Active:           {stats['active']:>5} ([green]{stats['active']/stats['total']*100:.1f}%[/green])")
    console.print(f"  Inactive:         {stats['inactive']:>5}")
    console.print(f"\nBy type:")
    console.print(f"  Text models:      {stats['text_models']:>5}")
    console.print(f"  Image models:     {stats['image_models']:>5}")

    table = Table(title="\nTop Providers")
    table.add_column("Provider", style="cyan")
    table.add_column("Total", justify="right")
    table.add_column("Active", justify="right", style="green")

    for row in providers:
        table.add_row(
            row["provider"],
            str(row["total"]),
            str(row["active"])
        )

    console.print(table)
    console.print()
