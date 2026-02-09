"""
LARS Configuration - DuckDB-compatible persistence

This module provides centralized configuration for LARS.

By default, LARS uses a DuckDB server as its persistence layer. For easier local
evaluation, LARS uses DuckDB + Parquet for persistence so
users don't need to run a DuckDB service.

Key notes:
- DuckDB is the persistence dialect.
- data_dir is kept for backward compatibility (RAG index files during transition).
- All log/analytics data goes to DuckDB tables directly.
"""
import os
import json
from pathlib import Path
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, ConfigDict
import yaml as _yaml

# Get LARS_ROOT once at module load
# Default to ~/.lars (cross-platform via Path.home())
_DEFAULT_LARS_ROOT = str(Path.home() / ".lars")
_LARS_ROOT = os.getenv("LARS_ROOT", _DEFAULT_LARS_ROOT)

# Export as LARS_ROOT for backward compatibility with modules that import it directly
# (e.g., analytics_worker.py uses `from .config import LARS_ROOT`)
LARS_ROOT = _LARS_ROOT

# Debug mode for verbose internal logging
_DEBUG = os.environ.get('LARS_DEBUG', '').lower() in ('1', 'true', 'yes')


# ============================================================================
# config.yaml Support
# ============================================================================

# Cached YAML config dict (loaded once at module init)
_yaml_config: Dict[str, Any] = {}


def _load_config_yaml(root: str = None) -> Dict[str, Any]:
    """Load config.yaml from LARS_ROOT if it exists. Returns flat + nested dict."""
    yaml_path = os.path.join(root or _LARS_ROOT, "config.yaml")
    if not os.path.exists(yaml_path):
        return {}
    try:
        with open(yaml_path, 'r') as f:
            data = _yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[Config] Warning: Failed to load {yaml_path}: {e}")
        return {}


def _yget(key: str, default=None, *, section: str = None, env: str = None):
    """Get a value from config.yaml, returning default if not found.
    
    Checks env var first (env always wins), then YAML, then default.
    
    Args:
        key: YAML key name
        default: Fallback value
        section: YAML nested section (e.g. "learning")
        env: Explicit env var name (e.g. "LARS_LEARN_INTERVAL"). 
             If not provided, auto-constructs from section + key.
    """
    # Build env var name
    if env:
        env_name = env
    elif section:
        env_name = f"LARS_{section.upper()}_{key.upper()}"
    else:
        env_name = f"LARS_{key.upper()}"
    
    env_val = os.environ.get(env_name)
    if env_val is not None:
        return env_val
    
    # Check YAML (nested or flat)
    if section and section in _yaml_config and isinstance(_yaml_config[section], dict):
        if key in _yaml_config[section]:
            return _yaml_config[section][key]
    elif key in _yaml_config:
        return _yaml_config[key]
    
    return default


# ============================================================================
# config.yaml Generation
# ============================================================================

# The canonical config.yaml structure with comments, groups, and defaults.
# Each entry: (yaml_key, env_var_override, default, comment, section)
_CONFIG_YAML_SCHEMA = [
    # ─── General ─────────────────────────────
    ("_section", "General", None, None, None),
    ("debug", "LARS_DEBUG", False, "Enable verbose debug logging", None),
    # default_model is intentionally omitted — configure via models.yaml (standard tier)
    ("no_splash", "LARS_NO_SPLASH", False, "Disable startup splash art", None),
    ("session_id_style", "LARS_SESSION_ID_STYLE", "woodland", "Session naming style: woodland, uuid, short", None),
    ("data_format", "LARS_DATA_FORMAT", "auto", "Output format: auto, table, json, csv", None),
    ("show_cli_images", "LARS_SHOW_CLI_IMAGES", True, "Render images in CLI output", None),

    # ─── Server ──────────────────────────────
    ("_section", "Server", None, None, None),
    ("parallel_workers", "LARS_PARALLEL_WORKERS", 8, "Parallel workers for semantic SQL operators", None),
    ("result_max_rows", "LARS_RESULT_MAX_ROWS", 100000, "Maximum rows returned per query", None),
    ("studio_pgwire_port", "LARS_STUDIO_PGWIRE_PORT", 5444, "PostgreSQL wire-protocol port", None),

    # ─── Learning / Dreaming ─────────────────
    ("_section", "Learning / Dreaming", None, None, None),
    ("enabled", "LARS_LEARN_ENABLED", True, "Enable the self-optimization dream loop", "learning"),
    ("interval", "LARS_LEARN_INTERVAL", 3600, "Dream loop interval in seconds", "learning"),
    ("calibration_threshold", "LARS_LEARN_CALIBRATION_THRESHOLD", 5, "Min data points before calibrating", "learning"),
    ("accuracy_floor", "LARS_LEARN_ACCURACY_FLOOR", 0.90, "Minimum accuracy before mutations", "learning"),
    ("mutation_threshold", "LARS_LEARN_MUTATION_THRESHOLD", 10, "Min data points before mutating", "learning"),
    ("models", "LARS_LEARN_MODELS", [], "Model list for dreaming (empty = use default)", "learning"),

    # ─── Features ────────────────────────────
    ("_section", "Features", None, None, None),
    ("smart_search", "LARS_SMART_SEARCH", True, "LLM-powered post-filtering of search results", "features"),
    ("research_mode", "LARS_RESEARCH_MODE", False, "Enable research mode by default", "features"),
    ("embeddings", "LARS_ENABLE_EMBEDDINGS", False, "Enable embedding worker", "features"),
    ("context_cards", "LARS_CONTEXT_CARDS_ENABLED", False, "Enable context card generation", "features"),
    ("ephemeral_rag", "LARS_EPHEMERAL_RAG_ENABLED", True, "Auto-index large content for RAG", "features"),
    ("mcp", "LARS_MCP_ENABLED", True, "Enable Model Context Protocol servers", "features"),
    ("file_watcher", "LARS_ENABLE_FILE_WATCHER", True, "Watch for file changes in artifacts", "features"),
    ("relevance_analysis", "LARS_ENABLE_RELEVANCE_ANALYSIS", True, "Run relevance analysis on queries", "features"),
    ("confidence_assessment", "LARS_CONFIDENCE_ASSESSMENT_ENABLED", False, "Enable confidence scoring", "features"),
    ("shadow_assessment", "LARS_SHADOW_ASSESSMENT_ENABLED", False, "Enable shadow quality assessment", "features"),
    ("analytics", "LARS_DISABLE_ANALYTICS", False, "Disable analytics collection (set true to disable)", "features"),
    ("auto_save_research", "LARS_AUTO_SAVE_RESEARCH", True, "Auto-save research sessions", "features"),
    ("harbor", "LARS_HARBOR_ENABLED", True, "Enable HuggingFace Spaces integration", "features"),

    # ─── Display / UI ────────────────────────
    ("_section", "Display / UI", None, None, None),
    ("chart_theme", "LARS_CHART_THEME", "dark", "Chart color theme: dark, light", "display"),
    ("toon_transport", "LARS_TOON_TRANSPORT", True, "Enable rich table transport", "display"),
    ("toon_min_rows", "LARS_TOON_MIN_ROWS", 5, "Minimum rows for table rendering", "display"),

    # ─── Context Management ──────────────────
    ("_section", "Context Management", None, None, None),
    ("keep_recent_images", "LARS_KEEP_RECENT_IMAGES", 0, "Max recent images to keep in context (0=all)", "context"),
    ("keep_recent_turns", "LARS_KEEP_RECENT_TURNS", 0, "Max recent turns to keep in context (0=all)", "context"),

    # ─── Sync / File Watcher ─────────────────
    ("_section", "Sync / File Watcher", None, None, None),
    ("sync_poll_interval", "LARS_SYNC_POLL_INTERVAL", 30, "DB poll interval for artifact sync (seconds)", "sync"),
    ("sync_write_files", "LARS_SYNC_WRITE_FILES", True, "Write synced artifacts to disk", "sync"),
    ("watch_debounce_delay", "LARS_WATCH_DEBOUNCE_DELAY", 1.0, "File watcher debounce delay (seconds)", "sync"),
]


def generate_config_yaml(config: "Config" = None, include_comments: bool = True) -> str:
    """Generate a config.yaml string with current values and comments."""
    lines = [
        "# LARS Configuration",
        "# Environment variables (LARS_*) always override values in this file.",
        "",
    ]

    current_section = None
    active_nested = None  # Track which nested section key is currently open
    for entry in _CONFIG_YAML_SCHEMA:
        key, env_or_label, default, comment, section = entry

        # Section header (comment only)
        if key == "_section":
            if current_section is not None:
                lines.append("")
            current_section = env_or_label
            active_nested = None
            if include_comments:
                lines.append(f"# ─── {env_or_label} {'─' * max(1, 40 - len(env_or_label))}")
            continue

        # Determine effective value
        val = default
        if config:
            val = _resolve_effective_value(key, section, config, default)

        # Format the value
        if section:
            # Nested under section key - only emit the key once
            if active_nested != section:
                lines.append(f"{section}:")
                active_nested = section
            comment_str = f"  # {comment}" if include_comments and comment else ""
            lines.append(f"  {key}: {_yaml_format(val)}{comment_str}")
        else:
            active_nested = None
            comment_str = f"  # {comment}" if include_comments and comment else ""
            lines.append(f"{key}: {_yaml_format(val)}{comment_str}")

    lines.append("")
    return "\n".join(lines)


def _resolve_effective_value(key, section, config, default):
    """Resolve the effective value for a config key from the Config object."""
    # Map yaml keys to Config field names
    field_map = {
        ("debug", None): "debug",
        ("default_model", None): "default_model",
        ("parallel_workers", None): "parallel_workers",
        ("smart_search", "features"): "smart_search_enabled",
        ("ephemeral_rag", "features"): "ephemeral_rag_enabled",
        ("mcp", "features"): "mcp_enabled",
        ("harbor", "features"): "harbor_enabled",
    }
    mapped = field_map.get((key, section))
    if mapped and hasattr(config, mapped):
        return getattr(config, mapped)
    return default


def _yaml_format(val) -> str:
    """Format a Python value as YAML inline."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        if not val:
            return "[]"
        return _yaml.dump(val, default_flow_style=True).strip()
    if isinstance(val, str):
        # Quote strings that might be ambiguous
        if val in ("true", "false", "null", "yes", "no", "") or not val.replace("-", "").replace("/", "").replace(".", "").replace("_", "").isalnum():
            return f'"{val}"'
        return f'"{val}"'
    return str(val)


def write_config_yaml(config: "Config" = None, path: str = None) -> str:
    """Write config.yaml to disk. Returns the path written."""
    if path is None:
        # Use config's root_dir (which respects LARS_ROOT env) over module-level default
        root = config.root_dir if config and hasattr(config, 'root_dir') else _LARS_ROOT
        path = os.path.join(root, "config.yaml")
    content = generate_config_yaml(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    return path


def get_config_yaml_path() -> str:
    """Return the path to config.yaml."""
    return os.path.join(_global_config.root_dir if _global_config else _LARS_ROOT, "config.yaml")


# Load YAML config at module init
_yaml_config = _load_config_yaml()


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

            if _DEBUG:
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

    # Try simple comma-separated format: default=http://localhost:11434,gpu=http://10.0.0.5:11434
    try:
        hosts = {}
        for part in hosts_str.split(','):
            part = part.strip()
            if '=' in part:
                alias, url = part.split('=', 1)
                hosts[alias.strip()] = url.strip()
        if hosts:
            return hosts
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
    LARS configuration with DuckDB as the primary database.

    Environment variable prefix: LARS_
    Example: LARS_CLICKHOUSE_HOST sets clickhouse_host
    """

    # =========================================================================
    # LLM Provider Configuration
    # =========================================================================
    provider_base_url: str = Field(default="https://openrouter.ai/api/v1")
    provider_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    )
    # Anthropic OAuth token for anthropic-direct/ provider (Claude Pro/Max subscriptions)
    anthropic_oauth_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("ANTHROPIC_OAUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY", "")
    )
    # Default model — set via models.yaml (standard tier). Hardcoded fallback only if models.yaml missing.
    default_model: str = Field(default="x-ai/grok-4.1-fast")
    #default_model: str = Field(default="arcee-ai/trinity-large-preview:free")

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
            "LARS_STT_MODEL", "openai/gpt-audio"
        )
    ## "LARS_STT_MODEL", "google/gemini-2.5-flash-preview-09-2025"
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
        default_factory=lambda: str(_yget("ephemeral_rag", True, section="features")).lower() not in ("0", "false", "no")
    )

    # Character threshold above which content is indexed instead of inline
    # Default: 25K chars ≈ 6K tokens - triggers for moderately large content
    # Content below this is passed inline as normal
    ephemeral_rag_threshold: int = Field(
        default_factory=lambda: int(os.getenv(
            "LARS_EPHEMERAL_RAG_THRESHOLD", "2125000"
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
        default_factory=lambda: str(_yget("smart_search", True, section="features")).lower() not in ("0", "false", "no")
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

    # Logging directory (for file-based logs, not the DuckDB data)
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
    # Persistence Backend (DuckDB server or CHDB)
    # =========================================================================
    # In auto mode, LARS will attempt to connect to DuckDB server and fall
    # back to CHDB if it is not reachable.
    db_mode: str = Field(
        default_factory=lambda: os.getenv("LARS_DB_MODE", "auto"),
        description="Persistence backend mode (deprecated): auto|clickhouse|chdb",
    )
    chdb_path: str = Field(
        default_factory=lambda: os.getenv("LARS_CHDB_PATH", os.path.join(_LARS_ROOT, "data", "lars.chdb")),
        description="CHDB storage path (directory/file). Used when db_mode=chdb or auto fallback.",
    )
    chroma_path: str = Field(
        default_factory=lambda: os.getenv("LARS_CHROMA_PATH", os.path.join(_LARS_ROOT, "data", "chroma")),
        description="Chroma persistence directory for vector/RAG storage.",
    )

    # =========================================================================
    # DuckDB Server Configuration
    # =========================================================================
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
        default_factory=lambda: str(_yget("mcp", True, section="features")).lower() not in ("0", "false", "no")
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
    # LM Studio Configuration
    # =========================================================================
    lmstudio_enabled: bool = Field(
        default=False, description="Enable LM Studio provider"
    )
    lmstudio_host: str = Field(
        default="http://localhost:1234", description="LM Studio server URL"
    )

    # =========================================================================
    # Parallel Execution Configuration
    # =========================================================================
    # Number of parallel workers for Arrow vectorized UDF execution
    # Used by semantic SQL operators (MEANS, ABOUT, etc.) for batch parallelism
    parallel_workers: int = Field(
        default_factory=lambda: int(_yget("parallel_workers", 8))
    )

    # =========================================================================
    # Deprecated Settings (kept for backward compatibility)
    # =========================================================================
    # DEPRECATED: DuckDB removed. Always returns False (uses DuckDB/Parquet instead)
    use_clickhouse_server: bool = Field(
        default=False,
        description="DEPRECATED: ClickHouse removed. Now uses DuckDB/Parquet for persistence."
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
        config.chroma_path,
    ]
    # CHDB persistence path (if enabled) needs its parent directory present.
    try:
        if config.chdb_path and config.chdb_path not in (":memory:", ":memory"):
            dirs_to_create.append(os.path.dirname(os.path.abspath(config.chdb_path)))
    except Exception:
        pass
    for dir_path in dirs_to_create:
        os.makedirs(dir_path, exist_ok=True)


# Normalize CHDB path once at startup so subprocesses with different CWDs still
# point at the same storage when LARS_CHDB_PATH is relative.
def _normalize_chdb_path(config: Config) -> None:
    try:
        path = getattr(config, "chdb_path", "") or ""
        if not path or path in (":memory:", ":memory"):
            return

        # Expand ~ and resolve relative paths relative to LARS_ROOT/root_dir (not CWD).
        path = os.path.expanduser(path)
        if not os.path.isabs(path):
            base = getattr(config, "root_dir", "") or _LARS_ROOT or os.getcwd()
            path = os.path.join(base, path)

        config.chdb_path = os.path.abspath(path)
    except Exception:
        # Never fail config import for a best-effort normalization.
        pass


# Global configuration instance
_global_config = Config()
_normalize_chdb_path(_global_config)
_ensure_directories(_global_config)


def _apply_models_yaml(config: Config):
    """
    Apply settings from models.yaml to config.
    
    models.yaml is the primary source of truth for model configuration.
    This overrides default/env-var values with models.yaml settings.
    """
    from pathlib import Path
    
    models_yaml_path = Path(config.root_dir) / "models.yaml"
    if not models_yaml_path.exists():
        return
    
    try:
        from .models import load_models_config
        models_config = load_models_config(Path(config.root_dir))
        
        # Apply model tiers
        if models_config.models.get("embedding"):
            config.default_embed_model = models_config.models["embedding"]
            from .model_defaults import is_local_embedding
            if is_local_embedding(config.default_embed_model):
                import logging
                logging.getLogger(__name__).info(
                    "Using local CPU embeddings (fastembed). "
                    "Configure an embedding provider for better performance."
                )
        if models_config.models.get("standard"):
            config.default_model = models_config.models["standard"]
        
        # Apply Ollama settings
        config.ollama_enabled = models_config.providers.ollama_enabled
        if models_config.providers.ollama_hosts:
            config.ollama_hosts = models_config.providers.ollama_hosts
            # Set default ollama URL from 'default' host
            if "default" in models_config.providers.ollama_hosts:
                config.ollama_base_url = models_config.providers.ollama_hosts["default"]
        
        # Apply LM Studio settings
        config.lmstudio_enabled = models_config.providers.lmstudio_enabled
        config.lmstudio_host = models_config.providers.lmstudio_host
    except Exception as e:
        import warnings
        warnings.warn(f"Failed to load models.yaml: {e}")


# Apply models.yaml settings
_apply_models_yaml(_global_config)


def get_config() -> Config:
    """Get the global configuration instance."""
    return _global_config


def reload_config():
    """
    Reload the global configuration from environment variables, config.yaml, and models.yaml.
    
    Call this after modifying os.environ, config.yaml, or models.yaml to pick up new values.
    Typically used after bootstrap wizard writes configuration.
    """
    global _global_config, _yaml_config
    _yaml_config = _load_config_yaml()
    _global_config = Config()
    _normalize_chdb_path(_global_config)
    _ensure_directories(_global_config)
    _apply_models_yaml(_global_config)


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
    Override DuckDB settings at runtime.

    Args:
        host: DuckDB server hostname
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
    Get database connection URL for display/debugging.

    Returns:
        URL string showing DuckDB/Parquet data path
    """
    c = _global_config
    return f"duckdb+parquet://{c.data_dir}"


def get_chdb_url() -> str:
    """
    Get database "connection URL" for display/debugging.
    
    DEPRECATED: Now returns DuckDB/Parquet path.

    Returns:
        URL string showing data directory
    """
    c = _global_config
    return f"duckdb+parquet://{c.data_dir}"


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

                if _DEBUG:
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
