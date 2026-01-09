"""
RVBBIT - Declarative Agent Framework for Python

This module uses lazy loading to keep startup fast (~0.2s vs ~2.5s).
Heavy imports (litellm, pandas, torch) are deferred until first use.
"""

import importlib
from typing import TYPE_CHECKING

# Fast-loading modules that don't pull in heavy dependencies
from .trait_registry import register_trait, register_cascade_as_tool

# Lazy-loaded module registry
_LAZY_IMPORTS = {
    # Core functionality
    "run_cascade": (".runner", "run_cascade"),
    # Database
    "SchemaNotInitializedError": (".db_adapter", "SchemaNotInitializedError"),
    "set_provider": (".config", "set_provider"),
    "get_checkpoint_manager": (".checkpoints", "get_checkpoint_manager"),
    "CheckpointStatus": (".checkpoints", "CheckpointStatus"),
    "CheckpointType": (".checkpoints", "CheckpointType"),
    "TraceContext": (".checkpoints", "TraceContext"),
    "create_eddy": (".traits.base", "create_eddy"),
    "get_echo": (".echo", "get_echo"),
    # Visualizer
    "generate_mermaid": (".visualizer", "generate_mermaid"),
    "generate_mermaid_string": (".visualizer", "generate_mermaid_string"),
    "generate_state_diagram": (".visualizer", "generate_state_diagram"),
    "generate_state_diagram_string": (".visualizer", "generate_state_diagram_string"),
    # Browser management
    "BrowserSession": (".browser_manager", "BrowserSession"),
    "BrowserSessionManager": (".browser_manager", "BrowserSessionManager"),
    "BrowserArtifacts": (".browser_manager", "BrowserArtifacts"),
    "BrowserStreams": (".browser_manager", "BrowserStreams"),
    "create_browser_session": (".browser_manager", "create_browser_session"),
    "close_browser_session": (".browser_manager", "close_browser_session"),
    "close_all_browser_sessions": (".browser_manager", "close_all_browser_sessions"),
    "get_browser_manager": (".browser_manager", "get_browser_manager"),
    "BrowserConfig": (".cascade", "BrowserConfig"),
    # Bodybuilder
    "bodybuilder": (".traits.bodybuilder", "bodybuilder"),
    "execute_body": (".traits.bodybuilder", "execute_body"),
    "plan_and_execute": (".traits.bodybuilder", "plan_and_execute"),
}

# Cache for lazy-loaded attributes
_LOADED_ATTRS = {}

# Deferred trait registration (happens once, on first trait access)
_TRAITS_REGISTERED = False

def _register_all_traits():
    """Register all built-in traits. Called lazily on first trait usage."""
    global _TRAITS_REGISTERED
    if _TRAITS_REGISTERED:
        return
    _TRAITS_REGISTERED = True

    # Import and register traits
    from .traits.sql import run_sql
    from .traits.extras import run_code, take_screenshot, linux_shell, linux_shell_dangerous, curl_text, fetch_url_with_browser
    from .traits.human import ask_human, ask_human_custom, request_decision
    from .traits.display import show_ui
    from .traits.artifacts import create_artifact, list_artifacts, get_artifact
    from .traits.research_sessions import (
        save_research_session, list_research_sessions, get_research_session
    )
    from .traits.state_tools import set_state, append_state, get_state
    from .traits.system import spawn_cascade, map_cascade
    from .traits.cascade_builder import cascade_write, cascade_read
    from .traits.bodybuilder import bodybuilder
    from .traits.research_db import research_query, research_execute
    from .traits.chart import create_chart, create_vega_lite, create_plotly
    from .traits.filesystem import read_file, write_file, append_file, list_files, file_info, read_image
    from .rag.tools import rag_search, rag_read_chunk, rag_list_sources
    from .sql_tools.tools import sql_search, sql_rag_search, run_sql as sql_run_sql, list_sql_connections, validate_sql
    from .traits.data_tools import sql_data, python_data, js_data, clojure_data, rvbbit_data
    from .traits.bash_substrate import bash_data
    from .traits.ui_components import lookup_ui_component, list_ui_components, get_ui_examples
    from .traits.rabbitize import (
        rabbitize_start, rabbitize_close, control_browser, extract_page_content,
        get_browser_status, rabbitize_execute, rabbitize_extract, rabbitize_status
    )
    from .traits.signal_tools import await_signal, fire_signal, list_signals as signal_list_signals
    from .traits.rlm_tools import rlm_exec, llm_analyze, llm_batch_analyze, chunk_text
    from .traits.trait_executor import trait_executor, list_available_traits

    # Core tools
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

    # SQL tools
    register_trait("sql_search", sql_search)
    register_trait("sql_rag_search", sql_rag_search)
    register_trait("sql_query", sql_run_sql)
    register_trait("list_sql_connections", list_sql_connections)
    register_trait("validate_sql", validate_sql)

    # Data Cascade tools
    register_trait("sql_data", sql_data)
    register_trait("python_data", python_data)
    register_trait("js_data", js_data)
    register_trait("clojure_data", clojure_data)
    register_trait("rvbbit_data", rvbbit_data)
    register_trait("bash_data", bash_data)

    # UI Components
    register_trait("lookup_ui_component", lookup_ui_component)
    register_trait("list_ui_components", list_ui_components)
    register_trait("get_ui_examples", get_ui_examples)

    # Browser automation
    register_trait("control_browser", control_browser)
    register_trait("extract_page_content", extract_page_content)
    register_trait("get_browser_status", get_browser_status)
    register_trait("rabbitize_start", rabbitize_start)
    register_trait("rabbitize_close", rabbitize_close)
    register_trait("rabbitize_execute", rabbitize_execute)
    register_trait("rabbitize_extract", rabbitize_extract)
    register_trait("rabbitize_status", rabbitize_status)

    # Signals
    register_trait("await_signal", await_signal)
    register_trait("fire_signal", fire_signal)
    register_trait("list_signals", signal_list_signals)

    # RLM tools
    register_trait("rlm_exec", rlm_exec)
    register_trait("llm_analyze", llm_analyze)
    register_trait("llm_batch_analyze", llm_batch_analyze)
    register_trait("chunk_text", chunk_text)

    # Trait executor
    register_trait("trait_executor", trait_executor)
    register_trait("list_traits", list_available_traits)

    # Backward compatibility
    register_trait("run_sql", run_sql)

    # Conditional: ElevenLabs TTS
    from .traits.tts import say as elevenlabs_say, is_available as elevenlabs_available
    if elevenlabs_available():
        register_trait("say", elevenlabs_say)

    # Conditional: Speech-to-Text
    from .traits.stt import (
        transcribe_audio, listen as voice_listen, process_voice_recording,
        is_available as stt_available
    )
    if stt_available():
        register_trait("transcribe_audio", transcribe_audio)
        register_trait("listen", voice_listen)
        register_trait("process_voice_recording", process_voice_recording)

    # Conditional: Brave Search
    from .traits.web_search import brave_web_search, is_available as brave_search_available
    if brave_search_available():
        register_trait("brave_web_search", brave_web_search)

    # Conditional: Embedding storage
    from .traits.embedding_storage import (
        agent_embed, clickhouse_store_embedding, clickhouse_vector_search,
        cosine_similarity_texts, elasticsearch_hybrid_search, agent_embed_batch
    )


def __getattr__(name: str):
    """Lazy-load attributes on first access."""
    global _LOADED_ATTRS

    # Check if already loaded
    if name in _LOADED_ATTRS:
        return _LOADED_ATTRS[name]

    # Check lazy import registry
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path, package=__name__)
        attr = getattr(module, attr_name)
        _LOADED_ATTRS[name] = attr
        return attr

    # Local models - special handling for availability check and stubs
    if name == "local_models_available":
        from .local_models import is_available
        _LOADED_ATTRS[name] = is_available
        return is_available

    if name in ("get_model_registry", "local_model_tool", "auto_device", "get_device_info"):
        from .local_models import is_available as local_models_available
        if local_models_available():
            from .local_models import (
                get_model_registry, local_model_tool, auto_device, get_device_info
            )
            _LOADED_ATTRS["get_model_registry"] = get_model_registry
            _LOADED_ATTRS["local_model_tool"] = local_model_tool
            _LOADED_ATTRS["auto_device"] = auto_device
            _LOADED_ATTRS["get_device_info"] = get_device_info
            return _LOADED_ATTRS[name]
        else:
            # Return stubs
            if name == "get_model_registry":
                def stub():
                    raise ImportError("Local models not available. Install with: pip install rvbbit[local-models]")
                _LOADED_ATTRS[name] = stub
                return stub
            elif name == "local_model_tool":
                def stub(*args, **kwargs):
                    raise ImportError("Local models not available. Install with: pip install rvbbit[local-models]")
                _LOADED_ATTRS[name] = stub
                return stub
            elif name == "auto_device":
                def stub():
                    return "cpu"
                _LOADED_ATTRS[name] = stub
                return stub
            elif name == "get_device_info":
                def stub():
                    return {"error": "Local models not available. Install with: pip install rvbbit[local-models]"}
                _LOADED_ATTRS[name] = stub
                return stub

    raise AttributeError(f"module 'rvbbit' has no attribute '{name}'")


def __dir__():
    """List available attributes for tab completion."""
    return list(__all__)


# Ensure traits are registered when run_cascade is called
_original_run_cascade = None

def _lazy_run_cascade(*args, **kwargs):
    """Wrapper that ensures traits are registered before running."""
    global _original_run_cascade
    _register_all_traits()
    if _original_run_cascade is None:
        from .runner import run_cascade as rc
        _original_run_cascade = rc
    return _original_run_cascade(*args, **kwargs)


# Override the lazy loader for run_cascade to include trait registration
_LAZY_IMPORTS_BACKUP = _LAZY_IMPORTS.copy()
del _LAZY_IMPORTS["run_cascade"]  # Remove from lazy registry
_LOADED_ATTRS["run_cascade"] = _lazy_run_cascade  # Use our wrapper


__all__ = [
    "run_cascade",
    "set_provider",
    "register_trait",
    "register_cascade_as_tool",
    "create_eddy",
    "get_echo",
    "get_checkpoint_manager",
    "CheckpointStatus",
    "CheckpointType",
    "TraceContext",
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
    # Bodybuilder
    "bodybuilder",
    "execute_body",
    "plan_and_execute",
    # Local Models
    "local_models_available",
    "get_model_registry",
    "local_model_tool",
    "auto_device",
    "get_device_info",
]
