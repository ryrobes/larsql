"""
Model tier configuration and resolution.

This module handles:
- Loading models.yaml configuration
- Resolving Jinja template references like {{ models.fast }}
- Provider configuration (OpenRouter, Ollama)
- Fallback chain: models.yaml → env vars (deprecated) → defaults
"""

import os
import re
import warnings
from pathlib import Path
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field

import yaml


# =============================================================================
# Default Model Tiers (require OpenRouter)
# =============================================================================

DEFAULT_MODELS = {
    "embedding": "qwen/qwen3-embedding-8b",
    "fast": "google/gemini-2.5-flash-lite",
    "standard": "google/gemini-3-flash-preview",
    "quality": "anthropic/claude-sonnet-4",
    "flagship": "anthropic/claude-opus-4",
}

# Mapping from old env vars to new tier names (for deprecation warnings)
LEGACY_ENV_MAPPING = {
    "LARS_DEFAULT_MODEL": "standard",
    "LARS_DEFAULT_EMBED_MODEL": "embedding",
    "LARS_EVAL_MODEL": "quality",
}

# Valid tier names
VALID_TIERS = {"embedding", "fast", "standard", "quality", "flagship"}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class OllamaHost:
    """Configuration for a single Ollama host."""
    alias: str
    url: str
    models: List[str] = field(default_factory=list)  # Populated during discovery


@dataclass
class ProvidersConfig:
    """Provider configuration."""
    openrouter_enabled: bool = False
    openrouter_api_key_env: str = "OPENROUTER_API_KEY"
    
    ollama_enabled: bool = False
    ollama_hosts: Dict[str, str] = field(default_factory=dict)  # alias -> url
    
    gemini_enabled: bool = False
    gemini_api_key_env: str = "GEMINI_API_KEY"
    
    bedrock_enabled: bool = False
    bedrock_region: str = "us-east-1"
    
    anthropic_direct_enabled: bool = False
    anthropic_oauth_token_env: str = "ANTHROPIC_OAUTH_TOKEN"
    
    @property
    def anthropic_oauth_token(self) -> Optional[str]:
        """Get the Anthropic OAuth token from environment."""
        return os.environ.get(self.anthropic_oauth_token_env) or os.environ.get("ANTHROPIC_API_KEY", "")
    
    @property
    def openrouter_api_key(self) -> Optional[str]:
        """Get the actual API key from environment."""
        return os.environ.get(self.openrouter_api_key_env)
    
    @property
    def gemini_api_key(self) -> Optional[str]:
        """Get the Gemini API key from environment."""
        return os.environ.get(self.gemini_api_key_env)
    
    @property
    def has_any_provider(self) -> bool:
        """Check if at least one provider is configured."""
        if self.openrouter_enabled and self.openrouter_api_key:
            return True
        if self.ollama_enabled and self.ollama_hosts:
            return True
        if self.gemini_enabled and self.gemini_api_key:
            return True
        if self.bedrock_enabled:
            return True  # Bedrock uses AWS credentials, not env var key
        if self.anthropic_direct_enabled and self.anthropic_oauth_token:
            return True
        return False


@dataclass  
class ModelsConfig:
    """Complete models.yaml configuration."""
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    models: Dict[str, str] = field(default_factory=dict)  # tier -> model_id
    capabilities: Dict[str, List[str]] = field(default_factory=dict)  # tier -> required capabilities
    
    # Metadata
    _source: str = "defaults"  # "yaml", "env", or "defaults"
    _path: Optional[Path] = None


# =============================================================================
# Loading Functions
# =============================================================================

def get_models_yaml_path(lars_root: Optional[Path] = None) -> Path:
    """Get the path to models.yaml."""
    if lars_root is None:
        lars_root = Path(os.environ.get("LARS_ROOT", Path.home() / ".lars"))
    return lars_root / "models.yaml"


def load_models_config(lars_root: Optional[Path] = None) -> ModelsConfig:
    """
    Load model configuration with fallback chain:
    1. models.yaml (if exists)
    2. Legacy environment variables (with deprecation warning)
    3. Hardcoded defaults
    
    Args:
        lars_root: LARS root directory (defaults to LARS_ROOT env or ~/.lars)
    
    Returns:
        ModelsConfig with resolved tier assignments
    """
    yaml_path = get_models_yaml_path(lars_root)
    
    # Try loading from YAML first
    if yaml_path.exists():
        return _load_from_yaml(yaml_path)
    
    # Check for legacy env vars
    legacy_models = _load_from_legacy_env()
    if legacy_models:
        return legacy_models
    
    # Fall back to defaults
    return _load_defaults()


def _load_from_yaml(path: Path) -> ModelsConfig:
    """Load configuration from models.yaml."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    
    # Parse providers
    providers_data = data.get("providers", {})
    ad_data = providers_data.get("anthropic_direct", {})
    providers = ProvidersConfig(
        openrouter_enabled=providers_data.get("openrouter", {}).get("enabled", False),
        openrouter_api_key_env=providers_data.get("openrouter", {}).get("api_key_env", "OPENROUTER_API_KEY"),
        ollama_enabled=providers_data.get("ollama", {}).get("enabled", False),
        ollama_hosts=providers_data.get("ollama", {}).get("hosts", {}),
        anthropic_direct_enabled=ad_data.get("enabled", False),
        anthropic_oauth_token_env=ad_data.get("oauth_token_env", "ANTHROPIC_OAUTH_TOKEN"),
    )
    
    # Parse models
    models = data.get("models", {})
    
    # Validate tier names
    invalid_tiers = set(models.keys()) - VALID_TIERS
    if invalid_tiers:
        warnings.warn(f"Unknown model tiers in models.yaml: {invalid_tiers}")
    
    # Fill in defaults for missing tiers
    for tier in VALID_TIERS:
        if tier not in models:
            models[tier] = DEFAULT_MODELS[tier]
    
    # Parse capabilities
    capabilities = data.get("capabilities", {})
    
    return ModelsConfig(
        providers=providers,
        models=models,
        capabilities=capabilities,
        _source="yaml",
        _path=path,
    )


def _load_from_legacy_env() -> Optional[ModelsConfig]:
    """Load from legacy environment variables (with deprecation warning)."""
    found_legacy = False
    models = dict(DEFAULT_MODELS)
    
    for env_var, tier in LEGACY_ENV_MAPPING.items():
        value = os.environ.get(env_var)
        if value:
            found_legacy = True
            models[tier] = value
            warnings.warn(
                f"Environment variable {env_var} is deprecated. "
                f"Please migrate to models.yaml (tier: {tier}). "
                f"Run 'lars bootstrap' to generate models.yaml.",
                DeprecationWarning,
                stacklevel=3
            )
    
    if not found_legacy:
        return None
    
    # Check for Ollama config in legacy env vars
    ollama_hosts_str = os.environ.get("LARS_OLLAMA_HOSTS", "")
    ollama_hosts = {}
    if ollama_hosts_str:
        try:
            import json
            ollama_hosts = json.loads(ollama_hosts_str)
            warnings.warn(
                "LARS_OLLAMA_HOSTS is deprecated. Please migrate to models.yaml.",
                DeprecationWarning,
                stacklevel=3
            )
        except:
            pass
    
    # Determine provider status from what's configured
    has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY"))
    has_ollama = bool(ollama_hosts) or bool(os.environ.get("LARS_OLLAMA_BASE_URL"))
    
    providers = ProvidersConfig(
        openrouter_enabled=has_openrouter,
        ollama_enabled=has_ollama,
        ollama_hosts=ollama_hosts or {"default": os.environ.get("LARS_OLLAMA_BASE_URL", "http://localhost:11434")},
    )
    
    return ModelsConfig(
        providers=providers,
        models=models,
        _source="env",
    )


def _load_defaults() -> ModelsConfig:
    """Load hardcoded defaults."""
    # Check if OpenRouter key exists
    has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY"))
    
    return ModelsConfig(
        providers=ProvidersConfig(
            openrouter_enabled=has_openrouter,
        ),
        models=dict(DEFAULT_MODELS),
        _source="defaults",
    )


# =============================================================================
# Model Resolution
# =============================================================================

# Regex to match {{ models.tier_name }}
MODEL_TEMPLATE_PATTERN = re.compile(r'\{\{\s*models\.(\w+)\s*\}\}')


def resolve_model(model_spec: str, config: Optional[ModelsConfig] = None) -> str:
    """
    Resolve a model specification to an actual model ID.
    
    Args:
        model_spec: Either a Jinja template like "{{ models.fast }}" 
                    or a literal model ID like "ollama/mistral:7b"
        config: ModelsConfig instance (loads default if None)
    
    Returns:
        Resolved model ID (e.g., "google/gemini-3-flash-preview")
    
    Examples:
        >>> resolve_model("{{ models.fast }}")
        'google/gemini-2.5-flash-lite'
        
        >>> resolve_model("ollama/mistral:7b")
        'ollama/mistral:7b'
        
        >>> resolve_model("{{ models.standard }}")
        'google/gemini-3-flash-preview'
    """
    if config is None:
        config = load_models_config()
    
    # Check if it's a Jinja template
    match = MODEL_TEMPLATE_PATTERN.search(model_spec)
    if match:
        tier = match.group(1)
        
        # Look up in config
        resolved = config.models.get(tier)
        if resolved:
            return resolved
        
        # Fallback to defaults
        if tier in DEFAULT_MODELS:
            return DEFAULT_MODELS[tier]
        
        # Unknown tier - return as-is with warning
        warnings.warn(f"Unknown model tier: {tier}")
        return model_spec
    
    # Literal model ID - return as-is
    return model_spec


def get_model_for_tier(tier: str, config: Optional[ModelsConfig] = None) -> str:
    """
    Get the model assigned to a specific tier.
    
    Args:
        tier: One of "embedding", "fast", "standard", "quality", "flagship"
        config: ModelsConfig instance (loads default if None)
    
    Returns:
        Model ID for the tier
    """
    if config is None:
        config = load_models_config()
    
    return config.models.get(tier, DEFAULT_MODELS.get(tier, ""))


# =============================================================================
# Configuration Writing
# =============================================================================

def write_models_yaml(
    config: ModelsConfig,
    path: Optional[Path] = None,
) -> Path:
    """
    Write models.yaml configuration file.
    
    Args:
        config: ModelsConfig to write
        path: Output path (defaults to LARS_ROOT/models.yaml)
    
    Returns:
        Path to written file
    """
    if path is None:
        path = get_models_yaml_path()
    
    # Build YAML structure
    data = {
        "# Generated by": "lars bootstrap",
        "# Customize freely": "cascade Jinja templates reference these tiers",
        "providers": {
            "openrouter": {
                "enabled": config.providers.openrouter_enabled,
                "api_key_env": config.providers.openrouter_api_key_env,
            },
            "ollama": {
                "enabled": config.providers.ollama_enabled,
                "hosts": config.providers.ollama_hosts,
            },
        },
        "models": config.models,
    }
    
    if config.capabilities:
        data["capabilities"] = config.capabilities
    
    # Write with nice formatting
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, "w") as f:
        f.write("# LARS Model Configuration\n")
        f.write("# Generated by: lars bootstrap\n")
        f.write("# Customize freely - cascade Jinja templates reference these tiers\n")
        f.write("#\n")
        f.write("# Tiers:\n")
        f.write("#   embedding - Vector embeddings (RAG, SIMILAR_TO)\n")
        f.write("#   fast      - Quick/cheap (MEANS, CLASSIFY, parsing)\n")
        f.write("#   standard  - Balanced (default for most operators)\n")
        f.write("#   quality   - Complex analysis (SUMMARIZE, ANALYZE)\n")
        f.write("#   flagship  - Best available (critical decisions)\n")
        f.write("\n")
        
        # Write providers section
        f.write("providers:\n")
        f.write("  openrouter:\n")
        f.write(f"    enabled: {str(config.providers.openrouter_enabled).lower()}\n")
        f.write(f"    api_key_env: {config.providers.openrouter_api_key_env}\n")
        f.write("\n")
        f.write("  ollama:\n")
        f.write(f"    enabled: {str(config.providers.ollama_enabled).lower()}\n")
        f.write("    hosts:\n")
        for alias, url in config.providers.ollama_hosts.items():
            f.write(f"      {alias}: {url}\n")
        if not config.providers.ollama_hosts:
            f.write("      # default: http://localhost:11434\n")
        f.write("\n")
        
        if config.providers.anthropic_direct_enabled:
            f.write("  anthropic_direct:\n")
            f.write(f"    enabled: true\n")
            f.write(f"    oauth_token_env: {config.providers.anthropic_oauth_token_env}\n")
            f.write("\n")
        
        # Write models section
        f.write("models:\n")
        for tier in ["embedding", "fast", "standard", "quality", "flagship"]:
            model = config.models.get(tier, DEFAULT_MODELS.get(tier, ""))
            f.write(f"  {tier}: {model}\n")
        f.write("\n")
        
        # Write capabilities if present
        if config.capabilities:
            f.write("capabilities:\n")
            for tier, caps in config.capabilities.items():
                f.write(f"  {tier}:\n")
                for cap in caps:
                    f.write(f"    - {cap}\n")
    
    return path


# =============================================================================
# Validation
# =============================================================================

def validate_config(config: ModelsConfig) -> List[str]:
    """
    Validate a models configuration.
    
    Returns:
        List of warning/error messages (empty if valid)
    """
    issues = []
    
    # Check that at least one provider is configured
    if not config.providers.has_any_provider:
        issues.append(
            "No providers configured. Run 'lars bootstrap' to set up OpenRouter or Ollama."
        )
    
    # Check that all tiers have models
    for tier in VALID_TIERS:
        if tier not in config.models or not config.models[tier]:
            issues.append(f"No model assigned to tier '{tier}'")
    
    # Check OpenRouter key if enabled
    if config.providers.openrouter_enabled:
        if not config.providers.openrouter_api_key:
            issues.append(
                f"OpenRouter enabled but {config.providers.openrouter_api_key_env} not set"
            )
    
    # Check Ollama hosts if enabled
    if config.providers.ollama_enabled:
        if not config.providers.ollama_hosts:
            issues.append("Ollama enabled but no hosts configured")
    
    return issues


# =============================================================================
# Convenience Functions
# =============================================================================

# Global cached config
_cached_config: Optional[ModelsConfig] = None


def get_config() -> ModelsConfig:
    """Get the cached models config (loads once per process)."""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_models_config()
    return _cached_config


def reload_config() -> ModelsConfig:
    """Force reload of models config."""
    global _cached_config
    _cached_config = load_models_config()
    return _cached_config


def fast_model() -> str:
    """Shortcut to get the fast tier model."""
    return get_model_for_tier("fast")


def standard_model() -> str:
    """Shortcut to get the standard tier model."""
    return get_model_for_tier("standard")


def quality_model() -> str:
    """Shortcut to get the quality tier model."""
    return get_model_for_tier("quality")


def flagship_model() -> str:
    """Shortcut to get the flagship tier model."""
    return get_model_for_tier("flagship")


def embedding_model() -> str:
    """Shortcut to get the embedding tier model."""
    return get_model_for_tier("embedding")


def resolve_cell_model(cell_model: Optional[str], default_model: str) -> str:
    """
    Resolve a cell's model specification to an actual model ID.
    
    This is the main entry point for resolving model references in cascades.
    Handles:
    - None → use default_model
    - "{{ models.fast }}" → resolve tier template
    - "ollama/mistral:7b" → return as-is
    
    Args:
        cell_model: The model field from CellConfig (may be None or template)
        default_model: The fallback model (usually runner's self.model)
    
    Returns:
        Resolved model ID ready to use with LLM provider
    """
    if cell_model is None:
        return default_model
    
    # Check for tier template
    if "{{" in cell_model and "models." in cell_model:
        return resolve_model(cell_model)
    
    # Literal model ID
    return cell_model
