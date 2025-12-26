"""
RVBBIT Configuration - Pure ClickHouse Implementation

This module provides centralized configuration for RVBBIT.

Key changes from dual-mode:
- ClickHouse is now the ONLY database backend (no more chDB/Parquet)
- data_dir is kept for backward compatibility (RAG index files during transition)
- All log/analytics data goes to ClickHouse tables directly
"""
import os
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

# Get RVBBIT_ROOT once at module load
_RVBBIT_ROOT = os.getenv("RVBBIT_ROOT", os.getcwd())


class Config(BaseModel):
    """
    RVBBIT configuration with ClickHouse as the primary database.

    Environment variable prefix: RVBBIT_
    Example: RVBBIT_CLICKHOUSE_HOST sets clickhouse_host
    """

    # =========================================================================
    # LLM Provider Configuration
    # =========================================================================
    provider_base_url: str = Field(default="https://openrouter.ai/api/v1")
    provider_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY")
    )
    default_model: str = Field(default="x-ai/grok-4.1-fast")

    # Default embedding model (used by RAG and Agent.embed())
    default_embed_model: str = Field(
        default_factory=lambda: os.getenv(
            "RVBBIT_DEFAULT_EMBED_MODEL", "qwen/qwen3-embedding-8b"
        )
    )

    # Model for generative UI generation (used by ask_human_custom)
    generative_ui_model: str = Field(
        default_factory=lambda: os.getenv(
            "RVBBIT_GENERATIVE_UI_MODEL", "google/gemini-3-pro-preview"
        )
    )

    # Model for auto-context selection (used by InterPhaseContextBuilder LLM strategy)
    # A fast, cheap model that can scan message summaries and select relevant context
    context_selector_model: str = Field(
        default_factory=lambda: os.getenv(
            "RVBBIT_CONTEXT_SELECTOR_MODEL", "google/gemini-2.5-flash-lite"
        )
    )

    # =========================================================================
    # Speech-to-Text (STT) Configuration
    # =========================================================================
    # STT model - uses OpenRouter's audio-capable models
    # Default: Voxtral (Mistral's audio model via OpenRouter)
    stt_model: str = Field(
        default_factory=lambda: os.getenv(
            "RVBBIT_STT_MODEL", "google/gemini-2.5-flash-preview-09-2025"
        )
    )
    # Alternative audio models:
    # - "google/gemini-2.5-flash-preview-09-2025" - Gemini with audio support
    # - "mistralai/voxtral-small-24b-2507" - Voxtral (requires wav/mp3, not webm)

    # STT uses the same provider as LLM calls (OpenRouter)
    # No separate API key needed - uses provider_api_key

    # =========================================================================
    # Directory Configuration
    # =========================================================================
    # Root directory - single source of truth
    root_dir: str = Field(default=_RVBBIT_ROOT)

    # Logging directory (for file-based logs, not the ClickHouse data)
    log_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "logs"))

    # Data directory - kept for:
    # - RAG index files (during transition period)
    # - Any other file-based data that hasn't been migrated
    data_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "data"))

    # Mermaid graph output directory
    graph_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "graphs"))

    # Session state snapshots (JSON files)
    state_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "states"))

    # Multi-modal artifact directories (these stay on disk)
    image_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "images"))
    audio_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "audio"))

    # Research databases directory (DuckDB files for cascade-specific data)
    research_db_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "research_dbs"))

    # Content directories - cascade/tool definitions
    examples_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "examples"))
    tackle_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "traits"))
    cascades_dir: str = Field(default=os.path.join(_RVBBIT_ROOT, "cascades"))

    # Tackle search paths (for manifest/quartermaster)
    tackle_dirs: List[str] = Field(
        default=[
            os.path.join(_RVBBIT_ROOT, "examples"),
            os.path.join(_RVBBIT_ROOT, "traits"),
            os.path.join(_RVBBIT_ROOT, "cascades"),
        ]
    )

    # =========================================================================
    # ClickHouse Configuration (Required)
    # =========================================================================
    # ClickHouse is now the only database backend - these are required settings
    clickhouse_host: str = Field(
        default_factory=lambda: os.getenv("RVBBIT_CLICKHOUSE_HOST", "localhost")
    )
    clickhouse_port: int = Field(
        default_factory=lambda: int(os.getenv("RVBBIT_CLICKHOUSE_PORT", "9000"))
    )
    clickhouse_database: str = Field(
        default_factory=lambda: os.getenv("RVBBIT_CLICKHOUSE_DATABASE", "rvbbit")
    )
    clickhouse_user: str = Field(
        default_factory=lambda: os.getenv("RVBBIT_CLICKHOUSE_USER", "default")
    )
    clickhouse_password: str = Field(
        default_factory=lambda: os.getenv("RVBBIT_CLICKHOUSE_PASSWORD", "")
    )

    # =========================================================================
    # Harbor (HuggingFace Spaces) Configuration
    # =========================================================================
    hf_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("HF_TOKEN")
    )
    harbor_enabled: bool = Field(
        default_factory=lambda: os.getenv("RVBBIT_HARBOR_ENABLED", "true").lower() == "true"
    )
    harbor_auto_discover: bool = Field(
        default_factory=lambda: os.getenv("RVBBIT_HARBOR_AUTO_DISCOVER", "true").lower() == "true"
    )
    harbor_cache_ttl: int = Field(
        default_factory=lambda: int(os.getenv("RVBBIT_HARBOR_CACHE_TTL", "300"))
    )

    # =========================================================================
    # Deprecated Settings (kept for backward compatibility)
    # =========================================================================
    # These are ignored but kept to avoid breaking code that references them
    use_clickhouse_server: bool = Field(
        default=True,
        description="DEPRECATED: ClickHouse is now always enabled. This field is ignored."
    )

    model_config = ConfigDict(env_prefix="RVBBIT_")


def _ensure_directories(config: Config):
    """Create all required directories if they don't exist."""
    dirs_to_create = [
        config.data_dir,  # Keep for RAG files during transition
        config.log_dir,
        config.graph_dir,
        config.state_dir,
        config.image_dir,
        config.audio_dir,
        config.research_db_dir,  # DuckDB research databases
    ]
    for dir_path in dirs_to_create:
        os.makedirs(dir_path, exist_ok=True)


# Global configuration instance
_global_config = Config()
_ensure_directories(_global_config)


def get_config() -> Config:
    """Get the global configuration instance."""
    return _global_config


def set_provider(
    base_url: str = None,
    api_key: str = None,
    model: str = None
):
    """
    Override provider settings at runtime.

    Args:
        base_url: Provider API base URL
        api_key: API key
        model: Default model name
    """
    global _global_config
    if base_url:
        _global_config.provider_base_url = base_url
    if api_key:
        _global_config.provider_api_key = api_key
    if model:
        _global_config.default_model = model


def set_clickhouse(
    host: str = None,
    port: int = None,
    database: str = None,
    user: str = None,
    password: str = None
):
    """
    Override ClickHouse settings at runtime.

    Args:
        host: ClickHouse server hostname
        port: Native protocol port
        database: Database name
        user: Username
        password: Password
    """
    global _global_config

    # Reset the adapter singleton to pick up new settings
    from .db_adapter import reset_adapter
    reset_adapter()

    if host:
        _global_config.clickhouse_host = host
    if port:
        _global_config.clickhouse_port = port
    if database:
        _global_config.clickhouse_database = database
    if user:
        _global_config.clickhouse_user = user
    if password is not None:
        _global_config.clickhouse_password = password


def get_clickhouse_url() -> str:
    """
    Get ClickHouse connection URL for display/debugging.

    Returns:
        URL string like "clickhouse://user@host:port/database"
    """
    c = _global_config
    return f"clickhouse://{c.clickhouse_user}@{c.clickhouse_host}:{c.clickhouse_port}/{c.clickhouse_database}"
