from .runner import run_cascade
from .config import set_provider
from .tackle import register_tackle, register_cascade_as_tool
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
from .eddies.human import ask_human
from .eddies.state_tools import set_state
from .eddies.system import spawn_cascade
from .eddies.chart import create_chart, create_vega_lite, create_plotly
from .eddies.filesystem import read_file, write_file, append_file, list_files, file_info

register_tackle("smart_sql_run", run_sql)
register_tackle("linux_shell", linux_shell)
register_tackle("run_code", run_code)
register_tackle("take_screenshot", take_screenshot)
register_tackle("ask_human", ask_human)
register_tackle("set_state", set_state)
register_tackle("spawn_cascade", spawn_cascade)
register_tackle("create_chart", create_chart)
register_tackle("create_vega_lite", create_vega_lite)
register_tackle("create_plotly", create_plotly)

# Filesystem operations
register_tackle("read_file", read_file)
register_tackle("write_file", write_file)
register_tackle("append_file", append_file)
register_tackle("list_files", list_files)
register_tackle("file_info", file_info)

# Conditional: ElevenLabs TTS (only if API key and voice ID are configured)
from .eddies.tts import say as elevenlabs_say, is_available as elevenlabs_available
if elevenlabs_available():
    register_tackle("say", elevenlabs_say)

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