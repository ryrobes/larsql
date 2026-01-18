"""
LARS Configuration - Pure ClickHouse Implementation

This module provides centralized configuration for LARS.

Key changes from dual-mode:
- ClickHouse is now the ONLY database backend (no more chDB/Parquet)
- data_dir is kept for backward compatibility (RAG index files during transition)
- All log/analytics data goes to ClickHouse tables directly
"""
import os
import json
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, ConfigDict

# Get LARS_ROOT once at module load
_LARS_ROOT = os.getenv("LARS_ROOT", os.getcwd())

# Export as LARS_ROOT for backward compatibility with modules that import it directly
# (e.g., analytics_worker.py uses `from .config import LARS_ROOT`)
LARS_ROOT = _LARS_ROOT


# ============================================================================
# Builtin Resources - Package-bundled content
# ============================================================================
def _get_package_dir() -> str:
    """Get the directory containing the lars package."""
    return os.path.dirname(__file__)


def get_builtin_cascades_dir() -> str:
    """Get the package-bundled cascades directory."""
    return os.path.join(_get_package_dir(), "builtin_cascades")


def get_builtin_skills_dir() -> str:
    """Get the package-bundled skills directory."""
    return os.path.join(_get_package_dir(), "builtin_skills")


def get_builtin_cell_types_dir() -> str:
    """Get the package-bundled cell types directory."""
    return os.path.join(_get_package_dir(), "builtin_cell_types")

# ============================================================================
# Google Credentials Resolver
# ============================================================================
# Cache for resolved credentials path (avoids creating multiple temp files)
_resolved_google_credentials_path: Optional[str] = None
_google_credentials_temp_file: Optional[str] = None


def _resolve_google_credentials() -> Optional[str]:
    """
    Resolve GOOGLE_APPLICATION_CREDENTIALS to a file path.

    Supports two formats:
    1. File path: Traditional path to a JSON credentials file
    2. JSON string: Raw JSON content (common in containerized deployments)

    If JSON content is detected (starts with '{'), it will be written to a
    temporary file and that path will be returned. The temp file persists
    for the lifetime of the process and is cleaned up on exit.

    Returns:
        Path to credentials file, or None if not set
    """
    global _resolved_google_credentials_path, _google_credentials_temp_file

    # Return cached result if already resolved
    if _resolved_google_credentials_path is not None:
        return _resolved_google_credentials_path

    creds_value = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_value:
        return None

    creds_value = creds_value.strip()
    if not creds_value:
        return None

    # Check if it looks like JSON content (starts with '{')
    if creds_value.startswith("{"):
        # Validate it's actually valid JSON
        try:
            json.loads(creds_value)
        except json.JSONDecodeError as e:
            print(f"[Config] Warning: GOOGLE_APPLICATION_CREDENTIALS looks like JSON but failed to parse: {e}")
            # Fall back to treating it as a path
            _resolved_google_credentials_path = creds_value
            return creds_value

        # Write JSON to a temporary file
        import tempfile
        import atexit

        try:
            # Create temp file that persists (delete=False)
            # Using .json extension for clarity in logs/debugging
            fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="gcloud_creds_")
            with os.fdopen(fd, 'w') as f:
                f.write(creds_value)

            _google_credentials_temp_file = temp_path
            _resolved_google_credentials_path = temp_path

            # Register cleanup handler
            def _cleanup_temp_credentials():
                if _google_credentials_temp_file and os.path.exists(_google_credentials_temp_file):
                    try:
                        os.unlink(_google_credentials_temp_file)
                    except Exception:
                        pass  # Best effort cleanup

            atexit.register(_cleanup_temp_credentials)

            print(f"[Config] Resolved GOOGLE_APPLICATION_CREDENTIALS from JSON string to temp file")
            return temp_path

        except Exception as e:
            print(f"[Config] Warning: Failed to write credentials to temp file: {e}")
            # Can't proceed without valid credentials
            return None
    else:
        # Treat as file path
        if not os.path.exists(creds_value):
            print(f"[Config] Warning: GOOGLE_APPLICATION_CREDENTIALS file not found: {creds_value}")
        _resolved_google_credentials_path = creds_value
        return creds_value


# ============================================================================
# Ollama Hosts Configuration Parser
# ============================================================================

def _parse_ollama_hosts() -> Dict[str, str]:
    """
    Parse LARS_OLLAMA_HOSTS environment variable.

    Supports both JSON and YAML formats for flexibility:
    - JSON: {"gpu1": "http://10.10.10.1:11434", "gpu2": "http://192.168.1.50:9999"}
    - YAML: gpu1: http://10.10.10.1:11434\\n gpu2: http://192.168.1.50:9999

    Returns:
        Dictionary mapping alias names to Ollama base URLs
    """
    hosts_str = os.getenv("LARS_OLLAMA_HOSTS", "")
    if not hosts_str:
        return {}

    # Try JSON first (most common for env vars)
    try:
        result = json.loads(hosts_str)
        if isinstance(result, dict):
            return result
        return {}
    except json.JSONDecodeError:
        pass

    # Try YAML as fallback
    try:
        import yaml
        result = yaml.safe_load(hosts_str)
        if isinstance(result, dict):
            return result
        return {}
    except Exception:
        pass

    return {}


# ============================================================================
# MCP Server Configuration Loader
# ============================================================================

def _load_mcp_servers_from_env() -> List[Any]:
    """
    Load MCP server configurations from environment variables or config file.

    Supports two methods:
    1. LARS_MCP_SERVERS_YAML - YAML string with array of server configs
    2. LARS_ROOT/config/mcp_servers.yaml - YAML file with server configs

    Returns:
        List of MCPServerConfig instances (or empty list if not configured)
    """
    # Try loading from environment variable first (supports both YAML and JSON for backwards compat)
    mcp_yaml = os.getenv("LARS_MCP_SERVERS_YAML")
    mcp_json = os.getenv("LARS_MCP_SERVERS_JSON")  # Legacy support

    if mcp_yaml or mcp_json:
        try:
            import yaml
            from .mcp_client import MCPServerConfig, MCPTransport

            # Prefer YAML, fallback to JSON
            servers_data = yaml.safe_load(mcp_yaml) if mcp_yaml else json.loads(mcp_json)

            return [
                MCPServerConfig(
                    name=s["name"],
                    transport=MCPTransport(s.get("transport", "stdio")),
                    command=s.get("command"),
                    args=s.get("args"),
                    env=s.get("env"),
                    url=s.get("url"),
                    headers=s.get("headers"),
                    timeout=s.get("timeout", 30),
                    enabled=s.get("enabled", True)
                )
                for s in servers_data
            ]
        except Exception as e:
            print(f"[Config] Warning: Failed to parse MCP servers from env: {e}")
            return []

    # Try loading from YAML config file
    config_file = os.path.join(_LARS_ROOT, "config", "mcp_servers.yaml")
    if os.path.exists(config_file):
        try:
            import yaml
            from .mcp_client import MCPServerConfig, MCPTransport

            with open(config_file, 'r') as f:
                servers_data = yaml.safe_load(f)

            return [
                MCPServerConfig(
                    name=s["name"],
                    transport=MCPTransport(s.get("transport", "stdio")),
                    command=s.get("command"),
                    args=s.get("args"),
                    env=s.get("env"),
                    url=s.get("url"),
                    headers=s.get("headers"),
                    timeout=s.get("timeout", 30),
                    enabled=s.get("enabled", True)
                )
                for s in servers_data
            ]
        except Exception as e:
            print(f"[Config] Warning: Failed to load {config_file}: {e}")
            return []

    # No MCP servers configured
    return []


class Config(BaseModel):
    """
    LARS configuration with ClickHouse as the primary database.

    Environment variable prefix: LARS_
    Example: LARS_CLICKHOUSE_HOST sets clickhouse_host
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
            "LARS_DEFAULT_EMBED_MODEL", "qwen/qwen3-embedding-8b"
        )
    )

    # Model for generative UI generation (used by ask_human_custom)
    generative_ui_model: str = Field(
        default_factory=lambda: os.getenv(
            "LARS_GENERATIVE_UI_MODEL", "google/gemini-3-pro-preview"
        )
    )

    # Model for auto-context selection (used by InterCellContextBuilder LLM strategy)
    # A fast, cheap model that can scan message summaries and select relevant context
    context_selector_model: str = Field(
        default_factory=lambda: os.getenv(
            "LARS_CONTEXT_SELECTOR_MODEL", "google/gemini-2.5-flash-lite"
        )
    )

    # =========================================================================
    # Speech-to-Text (STT) Configuration
    # =========================================================================
    # STT model - uses OpenRouter's audio-capable models
    # Default: Voxtral (Mistral's audio model via OpenRouter)
    stt_model: str = Field(
        default_factory=lambda: os.getenv(
            "LARS_STT_MODEL", "google/gemini-2.5-flash-preview-09-2025"
        )
    )
    # Alternative audio models:
    # - "google/gemini-2.5-flash-preview-09-2025" - Gemini with audio support
    # - "mistralai/voxtral-small-24b-2507" - Voxtral (requires wav/mp3, not webm)

    # STT uses the same provider as LLM calls (OpenRouter)
    # No separate API key needed - uses provider_api_key

    # =========================================================================
    # Ephemeral RAG Configuration (Auto-indexing for Large Inputs)
    # =========================================================================
    # Enable automatic indexing of large content that exceeds context limits
    # When enabled, large inputs/outputs are automatically chunked, embedded,
    # and searchable via injected tools instead of being passed inline
    ephemeral_rag_enabled: bool = Field(
        default_factory=lambda: os.getenv(
            "LARS_EPHEMERAL_RAG_ENABLED", "true"
        ).lower() == "true"
    )

    # Character threshold above which content is indexed instead of inline
    # Default: 25K chars ≈ 6K tokens - triggers for moderately large content
    # Content below this is passed inline as normal
    ephemeral_rag_threshold: int = Field(
        default_factory=lambda: int(os.getenv(
            "LARS_EPHEMERAL_RAG_THRESHOLD", "25000"
        ))
    )

    # Chunk size for splitting large content (characters)
    ephemeral_rag_chunk_size: int = Field(
        default_factory=lambda: int(os.getenv(
            "LARS_EPHEMERAL_RAG_CHUNK_SIZE", "1500"
        ))
    )

    # Overlap between consecutive chunks (characters)
    ephemeral_rag_chunk_overlap: int = Field(
        default_factory=lambda: int(os.getenv(
            "LARS_EPHEMERAL_RAG_CHUNK_OVERLAP", "200"
        ))
    )

    # =========================================================================
    # Smart Search Configuration (LLM-Powered RAG Filtering)
    # =========================================================================
    # Enable LLM-powered post-filtering of RAG/schema search results
    # When enabled, search results are evaluated by an LLM for TRUE relevance,
    # filtering out false positives and providing reasoning for each result.
    # This reduces context bloat by returning fewer, higher-quality results.
    smart_search_enabled: bool = Field(
        default_factory=lambda: os.getenv(
            "LARS_SMART_SEARCH", "true"
        ).lower() == "true"
    )

    # Model to use for smart search filtering (should be fast and cheap)
    smart_search_model: str = Field(
        default_factory=lambda: os.getenv(
            "LARS_SMART_SEARCH_MODEL", "google/gemini-2.5-flash-lite"
        )
    )

    # =========================================================================
    # Directory Configuration
    # =========================================================================
    # Root directory - single source of truth
    root_dir: str = Field(default=_LARS_ROOT)

    # Logging directory (for file-based logs, not the ClickHouse data)
    log_dir: str = Field(default=os.path.join(_LARS_ROOT, "logs"))

    # Data directory - kept for:
    # - RAG index files (during transition period)
    # - Any other file-based data that hasn't been migrated
    data_dir: str = Field(default=os.path.join(_LARS_ROOT, "data"))

    # Mermaid graph output directory
    graph_dir: str = Field(default=os.path.join(_LARS_ROOT, "graphs"))

    # Session state snapshots (JSON files)
    state_dir: str = Field(default=os.path.join(_LARS_ROOT, "states"))

    # Multi-modal artifact directories (these stay on disk)
    image_dir: str = Field(default=os.path.join(_LARS_ROOT, "images"))
    audio_dir: str = Field(default=os.path.join(_LARS_ROOT, "audio"))
    video_dir: str = Field(default=os.path.join(_LARS_ROOT, "videos"))

    # Research databases directory (DuckDB files for cascade-specific data)
    research_db_dir: str = Field(default=os.path.join(_LARS_ROOT, "research_dbs"))

    # Content directories - cascade/tool definitions
    examples_dir: str = Field(default=os.path.join(_LARS_ROOT, "cascades", "examples"))
    skills_dir: str = Field(default=os.path.join(_LARS_ROOT, "skills"))
    cascades_dir: str = Field(default=os.path.join(_LARS_ROOT, "cascades"))
    cell_types_dir: str = Field(default=os.path.join(_LARS_ROOT, "cell_types"))

    # Skills search paths (for manifest/quartermaster)
    skills_dirs: List[str] = Field(
        default=[
            os.path.join(_LARS_ROOT, "cascades", "examples"),
            os.path.join(_LARS_ROOT, "skills"),
            os.path.join(_LARS_ROOT, "cascades"),
        ]
    )

    # =========================================================================
    # ClickHouse Configuration (Required)
    # =========================================================================
    # ClickHouse is now the only database backend - these are required settings
    clickhouse_host: str = Field(
        default_factory=lambda: os.getenv("LARS_CLICKHOUSE_HOST", "localhost")
    )
    clickhouse_port: int = Field(
        default_factory=lambda: int(os.getenv("LARS_CLICKHOUSE_PORT", "9000"))
    )
    clickhouse_database: str = Field(
        default_factory=lambda: os.getenv("LARS_CLICKHOUSE_DATABASE", "lars")
    )
    clickhouse_user: str = Field(
        default_factory=lambda: os.getenv("LARS_CLICKHOUSE_USER", "lars")
    )
    clickhouse_password: str = Field(
        default_factory=lambda: os.getenv("LARS_CLICKHOUSE_PASSWORD", "lars")
    )

    # =========================================================================
    # Harbor (HuggingFace Spaces) Configuration
    # =========================================================================
    hf_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("HF_TOKEN")
    )
    harbor_enabled: bool = Field(
        default_factory=lambda: os.getenv("LARS_HARBOR_ENABLED", "true").lower() == "true"
    )
    harbor_auto_discover: bool = Field(
        default_factory=lambda: os.getenv("LARS_HARBOR_AUTO_DISCOVER", "true").lower() == "true"
    )
    harbor_cache_ttl: int = Field(
        default_factory=lambda: int(os.getenv("LARS_HARBOR_CACHE_TTL", "300"))
    )

    # =========================================================================
    # MCP (Model Context Protocol) Configuration
    # =========================================================================
    mcp_enabled: bool = Field(
        default_factory=lambda: os.getenv("LARS_MCP_ENABLED", "true").lower() == "true"
    )
    # MCP servers loaded from config/mcp_servers.yaml or LARS_MCP_SERVERS_YAML env var
    mcp_servers: List[Any] = Field(
        default_factory=lambda: _load_mcp_servers_from_env()
    )

    # =========================================================================
    # Google Vertex AI Configuration
    # =========================================================================
    # Enable Vertex AI as an additional provider (OpenRouter remains default)
    vertex_enabled: bool = Field(
        default_factory=lambda: os.getenv("LARS_VERTEX_ENABLED", "false").lower() == "true"
    )
    # Google Cloud Project ID for Vertex AI
    # Checks multiple env vars for compatibility with Google SDK conventions
    vertex_project: Optional[str] = Field(
        default_factory=lambda: (
            os.getenv("LARS_VERTEX_PROJECT") or
            os.getenv("VERTEXAI_PROJECT") or
            os.getenv("GOOGLE_CLOUD_PROJECT") or
            os.getenv("GCLOUD_PROJECT")
        )
    )
    # Vertex AI location/region (default: us-central1)
    vertex_location: str = Field(
        default_factory=lambda: os.getenv("LARS_VERTEX_LOCATION", "us-central1")
    )
    # Path to service account JSON credentials file
    # Supports BOTH file paths AND raw JSON content in GOOGLE_APPLICATION_CREDENTIALS
    # Falls back to Application Default Credentials (ADC) if not set
    vertex_credentials_path: Optional[str] = Field(
        default_factory=_resolve_google_credentials
    )

    # =========================================================================
    # Azure OpenAI Configuration
    # =========================================================================
    # Auto-enable if API key is set
    azure_enabled: bool = Field(
        default_factory=lambda: bool(
            os.getenv("AZURE_API_KEY") or os.getenv("LARS_AZURE_API_KEY")
        )
    )
    # Azure OpenAI API key for authentication
    # Used by LiteLLM's azure provider
    azure_api_key: Optional[str] = Field(
        default_factory=lambda: (
            os.getenv("AZURE_API_KEY") or
            os.getenv("LARS_AZURE_API_KEY")
        )
    )
    # Azure OpenAI endpoint base URL
    # Format: https://<resource-name>.openai.azure.com
    azure_api_base: Optional[str] = Field(
        default_factory=lambda: (
            os.getenv("AZURE_API_BASE") or
            os.getenv("LARS_AZURE_API_BASE")
        )
    )
    # Azure OpenAI API version (default: 2024-10-21)
    azure_api_version: str = Field(
        default_factory=lambda: os.getenv(
            "AZURE_API_VERSION",
            os.getenv("LARS_AZURE_API_VERSION", "2024-10-21")
        )
    )

    # =========================================================================
    # AWS Bedrock Configuration
    # =========================================================================
    # Auto-enable if AWS credentials are available
    # Uses standard AWS credential chain: env vars, ~/.aws/credentials, IAM role
    bedrock_enabled: bool = Field(
        default_factory=lambda: bool(
            os.getenv("AWS_ACCESS_KEY_ID") or
            os.getenv("AWS_PROFILE") or
            os.getenv("LARS_BEDROCK_ENABLED", "").lower() == "true"
        )
    )
    # AWS region for Bedrock (default: us-east-1)
    # Bedrock availability varies by region
    bedrock_region: str = Field(
        default_factory=lambda: (
            os.getenv("AWS_REGION") or
            os.getenv("AWS_DEFAULT_REGION") or
            os.getenv("LARS_BEDROCK_REGION") or
            "us-east-1"
        )
    )

    # =========================================================================
    # Ollama Configuration (Local/Remote LLM Servers)
    # =========================================================================
    # Enabled by default since Ollama is commonly used for local models
    ollama_enabled: bool = Field(
        default_factory=lambda: os.getenv("LARS_OLLAMA_ENABLED", "true").lower() == "true"
    )
    # Default Ollama base URL (used for ollama/model syntax)
    ollama_base_url: str = Field(
        default_factory=lambda: os.getenv("LARS_OLLAMA_BASE_URL", "http://localhost:11434")
    )
    # Named host aliases for remote Ollama servers
    # Format: {"alias": "http://host:port"} - use with ollama@alias/model syntax
    # Environment: LARS_OLLAMA_HOSTS='{"gpu1": "http://10.10.10.1:11434"}'
    ollama_hosts: Dict[str, str] = Field(
        default_factory=_parse_ollama_hosts
    )

    # =========================================================================
    # Parallel Execution Configuration
    # =========================================================================
    # Number of parallel workers for Arrow vectorized UDF execution
    # Used by semantic SQL operators (MEANS, ABOUT, etc.) for batch parallelism
    parallel_workers: int = Field(
        default_factory=lambda: int(os.getenv("LARS_PARALLEL_WORKERS", "8"))
    )

    # =========================================================================
    # Deprecated Settings (kept for backward compatibility)
    # =========================================================================
    # These are ignored but kept to avoid breaking code that references them
    use_clickhouse_server: bool = Field(
        default=True,
        description="DEPRECATED: ClickHouse is now always enabled. This field is ignored."
    )

    model_config = ConfigDict(env_prefix="LARS_")


def _ensure_directories(config: Config):
    """Create all required directories if they don't exist."""
    dirs_to_create = [
        config.data_dir,  # Keep for RAG files during transition
        config.log_dir,
        config.graph_dir,
        config.state_dir,
        config.image_dir,
        config.audio_dir,
        config.video_dir,
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
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None
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
    host: str | None = None,
    port: int | None = None,
    database: str | None = None,
    user: str | None = None,
    password: str | None = None
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


def set_vertex_provider(
    project: str | None = None,
    location: str | None = None,
    credentials_path: str | None = None,
    enabled: bool | None = None
):
    """
    Override Vertex AI settings at runtime.

    Args:
        project: Google Cloud project ID
        location: Vertex AI region (e.g., "us-central1")
        credentials_path: Path to service account JSON file, OR raw JSON content
        enabled: Enable/disable Vertex AI
    """
    global _global_config, _resolved_google_credentials_path, _google_credentials_temp_file

    if project:
        _global_config.vertex_project = project
    if location:
        _global_config.vertex_location = location
    if credentials_path:
        # Support both file path and raw JSON content
        if credentials_path.strip().startswith("{"):
            # JSON content - write to temp file
            import tempfile

            try:
                # Validate JSON
                json.loads(credentials_path)

                # Create temp file
                fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="gcloud_creds_")
                with os.fdopen(fd, 'w') as f:
                    f.write(credentials_path)

                # Clean up any previous temp file
                if _google_credentials_temp_file and os.path.exists(_google_credentials_temp_file):
                    try:
                        os.unlink(_google_credentials_temp_file)
                    except Exception:
                        pass

                _google_credentials_temp_file = temp_path
                _resolved_google_credentials_path = temp_path
                _global_config.vertex_credentials_path = temp_path

                print(f"[Config] set_vertex_provider: Resolved credentials from JSON string to temp file")

            except json.JSONDecodeError as e:
                print(f"[Config] Warning: credentials_path looks like JSON but failed to parse: {e}")
                _global_config.vertex_credentials_path = credentials_path
        else:
            # File path
            _global_config.vertex_credentials_path = credentials_path

    if enabled is not None:
        _global_config.vertex_enabled = enabled


def set_ollama_provider(
    base_url: str | None = None,
    hosts: Dict[str, str] | None = None,
    enabled: bool | None = None
):
    """
    Override Ollama settings at runtime.

    Args:
        base_url: Default Ollama server URL (e.g., "http://localhost:11434")
        hosts: Dictionary of named host aliases
               (e.g., {"gpu1": "http://10.10.10.1:11434"})
        enabled: Enable/disable Ollama integration
    """
    global _global_config

    if base_url:
        _global_config.ollama_base_url = base_url
    if hosts is not None:
        _global_config.ollama_hosts = hosts
    if enabled is not None:
        _global_config.ollama_enabled = enabled
