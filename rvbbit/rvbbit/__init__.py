from .runner import run_cascade
from .config import set_provider
from .trait_registry import register_trait, register_cascade_as_tool
from .checkpoints import get_checkpoint_manager, CheckpointStatus, CheckpointType, TraceContext
from .traits.base import create_eddy
from .echo import get_echo
from .visualizer import (
    generate_mermaid,
    generate_mermaid_string,
    generate_state_diagram,
    generate_state_diagram_string,
)

# Register batteries-included eddies
from .traits.sql import run_sql
from .traits.extras import run_code, take_screenshot, linux_shell, linux_shell_dangerous, curl_text, fetch_url_with_browser
from .traits.human import ask_human, ask_human_custom, request_decision
from .traits.display import show_ui
from .traits.artifacts import create_artifact, list_artifacts, get_artifact
from .traits.research_sessions import (
    save_research_session,
    list_research_sessions,
    get_research_session,
    _fetch_session_entries,
    _compute_session_metrics,
    _fetch_mermaid_graph,
    _fetch_checkpoints_for_session
)
from .traits.state_tools import set_state, append_state, get_state
from .traits.system import spawn_cascade, map_cascade
from .traits.cascade_builder import cascade_write, cascade_read
from .traits.bodybuilder import bodybuilder, execute_body, plan_and_execute
from .traits.research_db import research_query, research_execute
from .traits.chart import create_chart, create_vega_lite, create_plotly
from .traits.filesystem import read_file, write_file, append_file, list_files, file_info, read_image
# Image generation uses normal Agent.run() with modalities=["text", "image"]
# No separate tool needed - cells with image models are auto-detected
from .rag.tools import rag_search, rag_read_chunk, rag_list_sources
from .traits.embedding_storage import (
    agent_embed,
    clickhouse_store_embedding,
    clickhouse_vector_search,
    cosine_similarity_texts,
    elasticsearch_hybrid_search,
    agent_embed_batch
)

register_trait("smart_sql_run", run_sql)
register_trait("linux_shell", linux_shell)
register_trait("linux_shell_dangerous", linux_shell_dangerous)
register_trait("curl_text", curl_text)
register_trait("fetch_url_with_browser", fetch_url_with_browser)
register_trait("run_code", run_code)
register_trait("take_screenshot", take_screenshot)
register_trait("ask_human", ask_human)
register_trait("ask_human_custom", ask_human_custom)
register_trait("request_decision", request_decision)
register_trait("show_ui", show_ui)
register_trait("create_artifact", create_artifact)
register_trait("list_artifacts", list_artifacts)
register_trait("get_artifact", get_artifact)
register_trait("save_research_session", save_research_session)
register_trait("list_research_sessions", list_research_sessions)
register_trait("get_research_session", get_research_session)
register_trait("set_state", set_state)
register_trait("append_state", append_state)
register_trait("get_state", get_state)
register_trait("spawn_cascade", spawn_cascade)
register_trait("map_cascade", map_cascade)
register_trait("cascade_write", cascade_write)
register_trait("cascade_read", cascade_read)
register_trait("bodybuilder", bodybuilder)
register_trait("research_query", research_query)
register_trait("research_execute", research_execute)
register_trait("create_chart", create_chart)
register_trait("create_vega_lite", create_vega_lite)
register_trait("create_plotly", create_plotly)
register_trait("rag_search", rag_search)
register_trait("rag_read_chunk", rag_read_chunk)
register_trait("rag_list_sources", rag_list_sources)

# Filesystem operations
register_trait("read_file", read_file)
register_trait("write_file", write_file)
register_trait("append_file", append_file)
register_trait("list_files", list_files)
register_trait("file_info", file_info)
register_trait("read_image", read_image)

# SQL tools (multi-database discovery and querying)
from .sql_tools.tools import sql_search, sql_rag_search, run_sql as sql_run_sql, list_sql_connections, validate_sql
register_trait("sql_search", sql_search)  # Elasticsearch hybrid search (default)
register_trait("sql_rag_search", sql_rag_search)  # ClickHouse RAG fallback (legacy)
register_trait("sql_query", sql_run_sql)  # Named sql_query to avoid conflict with smart_sql_run
register_trait("list_sql_connections", list_sql_connections)
register_trait("validate_sql", validate_sql)  # SQL syntax/schema validator for wards

# Data Cascade tools (SQL notebooks / data pipelines)
from .traits.data_tools import sql_data, python_data, js_data, clojure_data, rvbbit_data
from .traits.bash_substrate import bash_data
register_trait("sql_data", sql_data)
register_trait("python_data", python_data)
register_trait("js_data", js_data)
register_trait("clojure_data", clojure_data)
register_trait("rvbbit_data", rvbbit_data)
register_trait("bash_data", bash_data)

# Conditional: ElevenLabs TTS (only if API key and voice ID are configured)
from .traits.tts import say as elevenlabs_say, is_available as elevenlabs_available
if elevenlabs_available():
    register_trait("say", elevenlabs_say)

# Conditional: Speech-to-Text (only if API key is configured)
from .traits.stt import (
    transcribe_audio,
    listen as voice_listen,
    process_voice_recording,
    is_available as stt_available
)
if stt_available():
    register_trait("transcribe_audio", transcribe_audio)
    register_trait("listen", voice_listen)
    register_trait("process_voice_recording", process_voice_recording)

# Conditional: Brave Search (only if API key is configured)
from .traits.web_search import brave_web_search, is_available as brave_search_available
if brave_search_available():
    register_trait("brave_web_search", brave_web_search)

# UI Component Lookup - Basecoat component reference for HITL screen generation
from .traits.ui_components import lookup_ui_component, list_ui_components, get_ui_examples
register_trait("lookup_ui_component", lookup_ui_component)
register_trait("list_ui_components", list_ui_components)
register_trait("get_ui_examples", get_ui_examples)

# Browser automation - Visual browser control
from .traits.rabbitize import (
    rabbitize_start,
    rabbitize_close,
    control_browser,
    extract_page_content,
    get_browser_status,
    # Backward compatibility aliases
    rabbitize_execute,
    rabbitize_extract,
    rabbitize_status
)
# Register with new descriptive names
register_trait("control_browser", control_browser)
register_trait("extract_page_content", extract_page_content)
register_trait("get_browser_status", get_browser_status)

# Keep old session management tools (still relevant names)
register_trait("rabbitize_start", rabbitize_start)
register_trait("rabbitize_close", rabbitize_close)

# Backward compatibility (deprecated but still work)
register_trait("rabbitize_execute", rabbitize_execute)
register_trait("rabbitize_extract", rabbitize_extract)
register_trait("rabbitize_status", rabbitize_status)

# Browser session management (first-class browser integration)
from .browser_manager import (
    BrowserSession,
    BrowserSessionManager,
    BrowserArtifacts,
    BrowserStreams,
    create_browser_session,
    close_browser_session,
    close_all_browser_sessions,
    get_browser_manager
)
from .cascade import BrowserConfig

# Signals - Cross-cascade communication
from .traits.signal_tools import await_signal, fire_signal, list_signals as signal_list_signals
register_trait("await_signal", await_signal)
register_trait("fire_signal", fire_signal)
register_trait("list_signals", signal_list_signals)

# RLM-style context decomposition tools
from .traits.rlm_tools import rlm_exec, llm_analyze, llm_batch_analyze, chunk_text
register_trait("rlm_exec", rlm_exec)
register_trait("llm_analyze", llm_analyze)
register_trait("llm_batch_analyze", llm_batch_analyze)
register_trait("chunk_text", chunk_text)

# Universal trait executor - backend for SQL trait() operator
from .traits.trait_executor import trait_executor, list_available_traits
register_trait("trait_executor", trait_executor)
register_trait("list_traits", list_available_traits)

# Backward compatibility aliases (for old cascade definitions)
register_trait("run_sql", run_sql)  # Alias for smart_sql_run (from .traits.sql)

# Conditional: Local Models (HuggingFace transformers - only if installed)
# Install with: pip install rvbbit[local-models]
from .local_models import is_available as local_models_available
if local_models_available():
    from .local_models import (
        get_model_registry,
        local_model_tool,
        auto_device,
        get_device_info,
    )
    # Note: Local model tools are registered via .tool.yaml files in traits/
    # or programmatically using the @local_model_tool decorator
else:
    # Provide stubs that show helpful error messages
    def get_model_registry():
        """Local models not available. Install with: pip install rvbbit[local-models]"""
        raise ImportError("Local models not available. Install with: pip install rvbbit[local-models]")

    def local_model_tool(*args, **kwargs):
        """Local models not available. Install with: pip install rvbbit[local-models]"""
        raise ImportError("Local models not available. Install with: pip install rvbbit[local-models]")

    def auto_device():
        """Local models not available. Install with: pip install rvbbit[local-models]"""
        return "cpu"

    def get_device_info():
        """Local models not available. Install with: pip install rvbbit[local-models]"""
        return {"error": "Local models not available. Install with: pip install rvbbit[local-models]"}

__all__ = [
    "run_cascade",
    "set_provider",
    "register_trait",
    "register_cascade_as_tool",
    "create_eddy",
    "get_echo",
    "generate_mermaid",
    "generate_mermaid_string",
    "generate_state_diagram",
    "generate_state_diagram_string",
    # Browser session management
    "BrowserSession",
    "BrowserSessionManager",
    "BrowserArtifacts",
    "BrowserStreams",
    "BrowserConfig",
    "create_browser_session",
    "close_browser_session",
    "close_all_browser_sessions",
    "get_browser_manager",
    # Bodybuilder - meta-tool for raw LLM body execution
    "bodybuilder",
    "execute_body",
    "plan_and_execute",
    # Local Models (HuggingFace transformers)
    "local_models_available",
    "get_model_registry",
    "local_model_tool",
    "auto_device",
    "get_device_info",
]
