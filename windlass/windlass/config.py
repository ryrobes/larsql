import os
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

class Config(BaseModel):
    provider_base_url: str = Field(default="https://openrouter.ai/api/v1")
    provider_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY"))
    #default_model: str = Field(default="x-ai/grok-4.1-fast:free") # RIP 
    #default_model: str = Field(default="google/gemini-3-pro-preview")
    #default_model: str = Field(default="anthropic/claude-sonnet-4.5")
    #default_model: str = Field(default="x-ai/grok-4.1-fast") 
    default_model: str = Field(default="google/gemini-2.5-flash-lite") 
    log_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_LOG_DIR", "./logs"))
    graph_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_GRAPH_DIR", "./graphs"))
    state_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_STATE_DIR", "./states"))
    image_dir: str = Field(default_factory=lambda: os.getenv("WINDLASS_IMAGE_DIR", "./images"))
    tackle_dirs: List[str] = Field(default=["examples/", "cascades/", "tackle/"])

    model_config = ConfigDict(env_prefix="WINDLASS_")

_global_config = Config()

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
