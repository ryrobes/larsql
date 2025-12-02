from .base import simple_eddy
from ..echo import get_echo
from contextvars import ContextVar

# ContextVar to track current session context safely
current_session_context = ContextVar("current_session_context", default=None)

def set_current_session_id(sid):
    return current_session_context.set(sid)

@simple_eddy
def set_state(key: str, value: str) -> str:
    """
    Updates the session state with a key-value pair.
    Use this to persist information for future phases.
    """
    session_id = current_session_context.get()
    if not session_id:
        return "Error: No active session context found."
    
    echo = get_echo(session_id)
    echo.update_state(key, value)
    
    return f"State updated: {key} = {value}"
