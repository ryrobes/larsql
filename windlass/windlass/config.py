import os
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

# Get WINDLASS_ROOT once at module load
_WINDLASS_ROOT = os.getenv("WINDLASS_ROOT", os.getcwd())

class Config(BaseModel):
    provider_base_url: str = Field(default="https://openrouter.ai/api/v1")
    provider_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY"))
    #default_model: str = Field(default="x-ai/grok-4.1-fast:free") # RIP
    default_model: str = Field(default="google/gemini-3-pro-preview")
    #default_model: str = Field(default="anthropic/claude-sonnet-4.5")
    #default_model: str = Field(default="x-ai/grok-4.1-fast")
    #default_model: str = Field(default="google/gemini-2.5-flash-lite")
    #default_model: str = Field(default="openai/gpt-5.1-codex-max")

    # Default embedding model (used by RAG and Agent.embed())
    default_embed_model: str = Field(
        default_factory=lambda: os.getenv("WINDLASS_DEFAULT_EMBED_MODEL", "qwen/qwen3-embedding-8b")
    )

    # Root directory - single source of truth
    root_dir: str = Field(default=_WINDLASS_ROOT)

    # Data directories - all derived from WINDLASS_ROOT
    log_dir: str = Field(default=os.path.join(_WINDLASS_ROOT, "logs"))
    data_dir: str = Field(default=os.path.join(_WINDLASS_ROOT, "data"))
    graph_dir: str = Field(default=os.path.join(_WINDLASS_ROOT, "graphs"))
    state_dir: str = Field(default=os.path.join(_WINDLASS_ROOT, "states"))
    image_dir: str = Field(default=os.path.join(_WINDLASS_ROOT, "images"))
    audio_dir: str = Field(default=os.path.join(_WINDLASS_ROOT, "audio"))

    # Content directories - all derived from WINDLASS_ROOT
    examples_dir: str = Field(default=os.path.join(_WINDLASS_ROOT, "examples"))
    tackle_dir: str = Field(default=os.path.join(_WINDLASS_ROOT, "tackle"))
    cascades_dir: str = Field(default=os.path.join(_WINDLASS_ROOT, "cascades"))

    # Tackle search paths (for manifest)
    tackle_dirs: List[str] = Field(default=[
        os.path.join(_WINDLASS_ROOT, "examples"),
        os.path.join(_WINDLASS_ROOT, "tackle"),
        os.path.join(_WINDLASS_ROOT, "cascades"),
    ])

    # Database backend settings (chDB by default, ClickHouse server optional)
    use_clickhouse_server: bool = Field(default=False)
    clickhouse_host: str = Field(default="localhost")
    clickhouse_port: int = Field(default=9000)
    clickhouse_database: str = Field(default="windlass")
    clickhouse_user: str = Field(default="default")
    clickhouse_password: str = Field(default="")

    model_config = ConfigDict(env_prefix="WINDLASS_")

def _ensure_directories(config: Config):
    """Create all data directories if they don't exist"""
    dirs_to_create = [
        config.data_dir,
        config.log_dir,
        config.graph_dir,
        config.state_dir,
        config.image_dir,
        config.audio_dir,
    ]
    for dir_path in dirs_to_create:
        os.makedirs(dir_path, exist_ok=True)

_global_config = Config()
_ensure_directories(_global_config)

def get_config() -> Config:
    return _global_config

def set_provider(base_url: str = None, api_key: str = None, model: str = None):
    global _global_config
    if base_url:
        _global_config.provider_base_url = base_url
    if api_key:
        _global_config.provider_api_key = api_key
    if model:
        _global_config.default_model = model
