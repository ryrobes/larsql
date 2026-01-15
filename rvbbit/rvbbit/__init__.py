"""
RVBBIT - Declarative Agent Framework for Python

This module uses lazy loading to keep startup fast (~0.2s vs ~2.5s).
Heavy imports (litellm, pandas, torch) are deferred until first use.
"""

import importlib
from typing import TYPE_CHECKING

# Fast-loading modules that don't pull in heavy dependencies
from .skill_registry import register_skill, register_cascade_as_tool

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
    "create_eddy": (".skills.base", "create_eddy"),
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
    "bodybuilder": (".skills.bodybuilder", "bodybuilder"),
    "execute_body": (".skills.bodybuilder", "execute_body"),
    "plan_and_execute": (".skills.bodybuilder", "plan_and_execute"),
}

# Cache for lazy-loaded attributes
_LOADED_ATTRS = {}

# Deferred skill registration (happens once, on first skill access)
_SKILLS_REGISTERED = False

def _register_all_skills():
    """Register all built-in skills. Called lazily on first skill usage."""
    global _SKILLS_REGISTERED
    if _SKILLS_REGISTERED:
        return
    _SKILLS_REGISTERED = True

    # Import and register skills
    from .skills.sql import run_sql
    from .skills.extras import take_screenshot, linux_shell, curl_text, fetch_url_with_browser
    from .skills.human import ask_human, ask_human_custom, request_decision
    from .skills.display import show_ui
    from .skills.artifacts import create_artifact, list_artifacts, get_artifact
    from .skills.research_sessions import (
        save_research_session, list_research_sessions, get_research_session
    )
    from .skills.state_tools import set_state, append_state, get_state
    from .skills.system import spawn_cascade, map_cascade
    from .skills.cascade_builder import cascade_write, cascade_read
    from .skills.bodybuilder import bodybuilder
    from .skills.research_db import research_query, research_execute
    from .skills.chart import create_chart, create_vega_lite, create_plotly
    from .skills.filesystem import read_file, write_file, append_file, list_files, file_info, read_image, edit_file, search_files, tree, get_image_info, read_images, list_images, save_image, copy_image
    from .skills.image_gen import outpaint_image, generate_image, llm_outpaint, llm_generate
    from .rag.tools import rag_search, rag_read_chunk, rag_list_sources
    from .sql_tools.tools import sql_search, sql_rag_search, smart_sql_search, run_sql as sql_run_sql, list_sql_connections, validate_sql
    from .skills.data_tools import sql_data, python_data, js_data, clojure_data, rvbbit_data
    from .skills.bash_substrate import bash_data
    from .skills.ui_components import lookup_ui_component, list_ui_components, get_ui_examples
    from .skills.rabbitize import (
        rabbitize_start, rabbitize_close, control_browser, extract_page_content,
        get_browser_status, rabbitize_execute, rabbitize_extract, rabbitize_status
    )
    from .skills.signal_tools import await_signal, fire_signal, list_signals as signal_list_signals
    from .skills.rlm_tools import rlm_exec, llm_analyze, llm_batch_analyze, chunk_text
    from .skills.skill_executor import skill_executor, list_available_skills
    from .skills.cascade_validator import validate_cascade_overrides

    # Core tools
    register_skill("smart_sql_run", run_sql)
    register_skill("linux_shell", linux_shell)
    register_skill("curl_text", curl_text)
    register_skill("fetch_url_with_browser", fetch_url_with_browser)
    register_skill("take_screenshot", take_screenshot)
    register_skill("ask_human", ask_human)
    register_skill("ask_human_custom", ask_human_custom)
    register_skill("request_decision", request_decision)
    register_skill("show_ui", show_ui)
    register_skill("create_artifact", create_artifact)
    register_skill("list_artifacts", list_artifacts)
    register_skill("get_artifact", get_artifact)
    register_skill("save_research_session", save_research_session)
    register_skill("list_research_sessions", list_research_sessions)
    register_skill("get_research_session", get_research_session)
    register_skill("set_state", set_state)
    register_skill("append_state", append_state)
    register_skill("get_state", get_state)
    register_skill("spawn_cascade", spawn_cascade)
    register_skill("map_cascade", map_cascade)
    register_skill("cascade_write", cascade_write)
    register_skill("cascade_read", cascade_read)
    register_skill("validate_cascade_overrides", validate_cascade_overrides)
    register_skill("bodybuilder", bodybuilder)
    register_skill("research_query", research_query)
    register_skill("research_execute", research_execute)
    register_skill("create_chart", create_chart)
    register_skill("create_vega_lite", create_vega_lite)
    register_skill("create_plotly", create_plotly)
    register_skill("rag_search", rag_search)
    register_skill("rag_read_chunk", rag_read_chunk)
    register_skill("rag_list_sources", rag_list_sources)

    # Filesystem operations
    register_skill("read_file", read_file)
    register_skill("write_file", write_file)
    register_skill("edit_file", edit_file)
    register_skill("append_file", append_file)
    register_skill("list_files", list_files)
    register_skill("file_info", file_info)
    register_skill("read_image", read_image)
    register_skill("read_images", read_images)
    register_skill("get_image_info", get_image_info)
    register_skill("list_images", list_images)
    register_skill("save_image", save_image)
    register_skill("copy_image", copy_image)
    register_skill("outpaint_image", outpaint_image)
    register_skill("generate_image", generate_image)
    register_skill("llm_outpaint", llm_outpaint)
    register_skill("llm_generate", llm_generate)
    register_skill("search_files", search_files)
    register_skill("tree", tree)

    # SQL tools
    register_skill("sql_search", sql_search)
    register_skill("sql_rag_search", sql_rag_search)
    register_skill("smart_sql_search", smart_sql_search)
    register_skill("sql_query", sql_run_sql)
    register_skill("list_sql_connections", list_sql_connections)
    register_skill("validate_sql", validate_sql)

    # Data Cascade tools
    register_skill("sql_data", sql_data)
    register_skill("python_data", python_data)
    register_skill("js_data", js_data)
    register_skill("clojure_data", clojure_data)
    register_skill("rvbbit_data", rvbbit_data)
    register_skill("bash_data", bash_data)

    # UI Components
    register_skill("lookup_ui_component", lookup_ui_component)
    register_skill("list_ui_components", list_ui_components)
    register_skill("get_ui_examples", get_ui_examples)

    # Browser automation
    register_skill("control_browser", control_browser)
    register_skill("extract_page_content", extract_page_content)
    register_skill("get_browser_status", get_browser_status)
    register_skill("rabbitize_start", rabbitize_start)
    register_skill("rabbitize_close", rabbitize_close)
    register_skill("rabbitize_execute", rabbitize_execute)
    register_skill("rabbitize_extract", rabbitize_extract)
    register_skill("rabbitize_status", rabbitize_status)

    # Native Python browser tools (browser, control_browser, etc.)
    try:
        from .browser.tools import register_browser_tools
        register_browser_tools()
    except ImportError as e:
        # Browser dependencies not installed - tools won't be available
        pass

    # Signals
    register_skill("await_signal", await_signal)
    register_skill("fire_signal", fire_signal)
    register_skill("list_signals", signal_list_signals)

    # RLM tools
    register_skill("rlm_exec", rlm_exec)
    register_skill("llm_analyze", llm_analyze)
    register_skill("llm_batch_analyze", llm_batch_analyze)
    register_skill("chunk_text", chunk_text)

    # Skill executor
    register_skill("skill_executor", skill_executor)
    register_skill("list_skills", list_available_skills)

    # Backward compatibility
    register_skill("run_sql", run_sql)

    # Conditional: ElevenLabs TTS
    from .skills.tts import say as elevenlabs_say, is_available as elevenlabs_available
    if elevenlabs_available():
        register_skill("say", elevenlabs_say)

    # Conditional: Speech-to-Text
    from .skills.stt import (
        transcribe_audio, listen as voice_listen, process_voice_recording,
        is_available as stt_available
    )
    if stt_available():
        register_skill("transcribe_audio", transcribe_audio)
        register_skill("listen", voice_listen)
        register_skill("process_voice_recording", process_voice_recording)

    # Conditional: Brave Search
    from .skills.web_search import brave_web_search, is_available as brave_search_available
    if brave_search_available():
        register_skill("brave_web_search", brave_web_search)

    # Conditional: Embedding storage
    from .skills.embedding_storage import (
        agent_embed, clickhouse_store_embedding, clickhouse_vector_search,
        cosine_similarity_texts, elasticsearch_hybrid_search, agent_embed_batch
    )

    # Discover and register declarative tools (.tool.yaml/.tool.json)
    # This includes local model tools like local_sentiment, local_ner
    try:
        from .tool_definitions import discover_and_register_declarative_tools
        discover_and_register_declarative_tools()
    except Exception:
        pass  # Non-fatal if tool discovery fails


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


# Ensure skills are registered when run_cascade is called
_original_run_cascade = None

def _lazy_run_cascade(*args, **kwargs):
    """Wrapper that ensures skills are registered before running."""
    global _original_run_cascade
    _register_all_skills()
    if _original_run_cascade is None:
        from .runner import run_cascade as rc
        _original_run_cascade = rc
    return _original_run_cascade(*args, **kwargs)


# Override the lazy loader for run_cascade to include skill registration
_LAZY_IMPORTS_BACKUP = _LAZY_IMPORTS.copy()
del _LAZY_IMPORTS["run_cascade"]  # Remove from lazy registry
_LOADED_ATTRS["run_cascade"] = _lazy_run_cascade  # Use our wrapper


__all__ = [
    "run_cascade",
    "set_provider",
    "register_skill",
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
