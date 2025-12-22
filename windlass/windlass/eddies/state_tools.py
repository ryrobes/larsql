from .base import simple_eddy
from ..echo import get_echo
from contextvars import ContextVar

# ContextVar to track current session context safely
current_session_context = ContextVar("current_session_context", default=None)

# ContextVar to track current phase name
current_phase_context = ContextVar("current_phase_context", default=None)

# ContextVar to track current cascade ID
current_cascade_context = ContextVar("current_cascade_context", default=None)

# ContextVar to track current sounding index (for parallel sounding decisions)
current_sounding_context = ContextVar("current_sounding_context", default=None)

def set_current_session_id(sid):
    return current_session_context.set(sid)

def get_current_session_id():
    return current_session_context.get()

def set_current_phase_name(phase_name):
    return current_phase_context.set(phase_name)

def get_current_phase_name():
    return current_phase_context.get()

def set_current_cascade_id(cascade_id):
    return current_cascade_context.set(cascade_id)

def get_current_cascade_id():
    return current_cascade_context.get()

def set_current_sounding_index(sounding_index):
    return current_sounding_context.set(sounding_index)

def get_current_sounding_index():
    return current_sounding_context.get()

def set_state_internal(key: str, value) -> None:
    """
    Internal function to set state without being a tool.
    Used by other tools (like ask_human) to store values.
    """
    session_id = current_session_context.get()
    if not session_id:
        return

    echo = get_echo(session_id)
    echo.update_state(key, value)

@simple_eddy
def set_state(key: str, value: str) -> str:
    """
    Updates the session state with a key-value pair.

    State is DURABLE and QUERYABLE:
    - Persisted to cascade_state table in ClickHouse
    - Queryable across sessions via SQL
    - Visible in Studio UI state panel during execution
    - Survives cascade completion

    Use this to:
    - Store insights/conclusions for later phases
    - Build incremental state across runs
    - Enable LLM memory (query past state)
    - Track metrics/KPIs over time

    Example:
        set_state("total_revenue", 125000)
        set_state("insights", json.dumps({"finding": "...", "confidence": 0.9}))
    """
    session_id = current_session_context.get()
    if not session_id:
        return "Error: No active session context found."

    cascade_id = current_cascade_context.get()
    phase_name = current_phase_context.get()

    # Update Echo state (backward compatibility)
    echo = get_echo(session_id)
    echo.update_state(key, value)

    # Persist to ClickHouse for durable storage
    try:
        from ..db_adapter import get_db
        from datetime import datetime
        import json

        db = get_db()

        # Serialize value to JSON if needed
        if isinstance(value, str):
            value_json = value
            value_type = 'string'
        elif isinstance(value, (int, float)):
            value_json = json.dumps(value)
            value_type = 'number'
        elif isinstance(value, bool):
            value_json = json.dumps(value)
            value_type = 'boolean'
        elif isinstance(value, dict):
            value_json = json.dumps(value)
            value_type = 'object'
        elif isinstance(value, list):
            value_json = json.dumps(value)
            value_type = 'array'
        elif value is None:
            value_json = 'null'
            value_type = 'null'
        else:
            value_json = str(value)
            value_type = 'unknown'

        # Insert into cascade_state table
        db.insert_rows(
            'cascade_state',
            [{
                'session_id': session_id,
                'cascade_id': cascade_id or 'unknown',
                'key': key,
                'value': value_json,
                'phase_name': phase_name or 'unknown',
                'created_at': datetime.now(),
                'value_type': value_type
            }],
            columns=['session_id', 'cascade_id', 'key', 'value', 'phase_name', 'created_at', 'value_type']
        )
    except Exception as e:
        # Don't fail cascade if state persistence fails (table might not exist yet)
        import logging
        logging.getLogger(__name__).debug(f"Could not persist state to cascade_state table: {e}")

    return f"State updated: {key} = {value}"
