from .runner import run_cascade
from .config import set_provider
from .tackle import register_tackle, register_cascade_as_tool
from .checkpoints import get_checkpoint_manager, CheckpointStatus, CheckpointType, TraceContext
from .eddies.base import create_eddy
from .echo import get_echo
from .visualizer import (
    generate_mermaid,
    generate_mermaid_string,
    generate_state_diagram,
    generate_state_diagram_string,
)

# Register batteries-included eddies
from .eddies.sql import run_sql
from .eddies.extras import run_code, take_screenshot, linux_shell
from .eddies.human import ask_human, ask_human_custom, request_decision
from .eddies.display import show_ui
from .eddies.artifacts import create_artifact, list_artifacts, get_artifact
from .eddies.state_tools import set_state
from .eddies.system import spawn_cascade
from .eddies.chart import create_chart, create_vega_lite, create_plotly
from .eddies.filesystem import read_file, write_file, append_file, list_files, file_info
from .rag.tools import rag_search, rag_read_chunk, rag_list_sources

register_tackle("smart_sql_run", run_sql)
register_tackle("linux_shell", linux_shell)
register_tackle("run_code", run_code)
register_tackle("take_screenshot", take_screenshot)
register_tackle("ask_human", ask_human)
register_tackle("ask_human_custom", ask_human_custom)
register_tackle("request_decision", request_decision)
register_tackle("show_ui", show_ui)
register_tackle("create_artifact", create_artifact)
register_tackle("list_artifacts", list_artifacts)
register_tackle("get_artifact", get_artifact)
register_tackle("set_state", set_state)
register_tackle("spawn_cascade", spawn_cascade)
register_tackle("create_chart", create_chart)
register_tackle("create_vega_lite", create_vega_lite)
register_tackle("create_plotly", create_plotly)
register_tackle("rag_search", rag_search)
register_tackle("rag_read_chunk", rag_read_chunk)
register_tackle("rag_list_sources", rag_list_sources)

# Filesystem operations
register_tackle("read_file", read_file)
register_tackle("write_file", write_file)
register_tackle("append_file", append_file)
register_tackle("list_files", list_files)
register_tackle("file_info", file_info)

# SQL tools (multi-database discovery and querying)
from .sql_tools.tools import sql_search, run_sql as sql_run_sql, list_sql_connections
register_tackle("sql_search", sql_search)
register_tackle("sql_query", sql_run_sql)  # Named sql_query to avoid conflict with smart_sql_run
register_tackle("list_sql_connections", list_sql_connections)

# Conditional: ElevenLabs TTS (only if API key and voice ID are configured)
from .eddies.tts import say as elevenlabs_say, is_available as elevenlabs_available
if elevenlabs_available():
    register_tackle("say", elevenlabs_say)

# Rabbitize - Visual browser automation
from .eddies.rabbitize import (
    rabbitize_start,
    rabbitize_execute,
    rabbitize_extract,
    rabbitize_close,
    rabbitize_status
)
register_tackle("rabbitize_start", rabbitize_start)
register_tackle("rabbitize_execute", rabbitize_execute)
register_tackle("rabbitize_extract", rabbitize_extract)
register_tackle("rabbitize_close", rabbitize_close)
register_tackle("rabbitize_status", rabbitize_status)

# Signals - Cross-cascade communication
from .eddies.signal_tools import await_signal, fire_signal, list_signals as signal_list_signals
register_tackle("await_signal", await_signal)
register_tackle("fire_signal", fire_signal)
register_tackle("list_signals", signal_list_signals)

__all__ = [
    "run_cascade",
    "set_provider",
    "register_tackle",
    "register_cascade_as_tool",
    "create_eddy",
    "get_echo",
    "generate_mermaid",
    "generate_mermaid_string",
    "generate_state_diagram",
    "generate_state_diagram_string",
]
