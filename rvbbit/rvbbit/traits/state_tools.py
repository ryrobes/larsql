from .base import simple_eddy
from ..echo import get_echo
from contextvars import ContextVar

# ContextVar to track current session context safely
current_session_context = ContextVar("current_session_context", default=None)

# ContextVar to track current phase name
current_phase_context = ContextVar("current_phase_context", default=None)

# ContextVar to track current cascade ID
current_cascade_context = ContextVar("current_cascade_context", default=None)

# ContextVar to track current candidate index (for parallel candidate decisions)
current_sounding_context = ContextVar("current_sounding_context", default=None)

# ContextVar to track resolved model for current execution context (for downstream_model)
current_model_context = ContextVar("current_model_context", default=None)

# ContextVar to track whether to propagate model to downstream cascade tools
downstream_model_context = ContextVar("downstream_model_context", default=False)

def set_current_session_id(sid):
    return current_session_context.set(sid)

def get_current_session_id():
    return current_session_context.get()

def set_current_cell_name(cell_name):
    return current_phase_context.set(cell_name)

def get_current_cell_name():
    return current_phase_context.get()

def set_current_cascade_id(cascade_id):
    return current_cascade_context.set(cascade_id)

def get_current_cascade_id():
    return current_cascade_context.get()

def set_current_candidate_index(candidate_index):
    return current_sounding_context.set(candidate_index)

def get_current_candidate_index():
    return current_sounding_context.get()

def set_current_model(model):
    """Set the resolved model for current execution context."""
    return current_model_context.set(model)

def get_current_model():
    """Get the resolved model for current execution context."""
    return current_model_context.get()

def set_downstream_model(enabled: bool):
    """Set whether to propagate model to downstream cascade tools."""
    return downstream_model_context.set(enabled)

def get_downstream_model() -> bool:
    """Check if model should propagate to downstream cascade tools."""
    return downstream_model_context.get() or False

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
    cell_name = current_phase_context.get()

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
                'cell_name': cell_name or 'unknown',
                'created_at': datetime.now(),
                'value_type': value_type
            }],
            columns=['session_id', 'cascade_id', 'key', 'value', 'cell_name', 'created_at', 'value_type']
        )
    except Exception as e:
        # Don't fail cascade if state persistence fails (table might not exist yet)
        import logging
        logging.getLogger(__name__).debug(f"Could not persist state to cascade_state table: {e}")

    return f"State updated: {key} = {value}"


@simple_eddy
def append_state(key: str, value) -> str:
    """
    Appends a value to a list in session state.

    If the key doesn't exist, creates a new list with the value.
    If the key exists but isn't a list, converts it to a list first.

    This is the preferred way to accumulate items (expenses, messages, etc.)
    without manually handling the read-append-write pattern.

    Example:
        append_state("expenses", {"merchant": "Starbucks", "amount": 5.50})
        append_state("messages", "User clicked submit")
    """
    session_id = current_session_context.get()
    if not session_id:
        return "Error: No active session context found."

    cascade_id = current_cascade_context.get()
    cell_name = current_phase_context.get()

    # Get current state
    echo = get_echo(session_id)
    current = echo.state.get(key)

    # Ensure it's a list
    if current is None:
        new_list = [value]
    elif isinstance(current, list):
        new_list = current + [value]
    else:
        # Convert existing value to list, then append
        new_list = [current, value]

    # Update Echo state
    echo.update_state(key, new_list)

    # Persist to ClickHouse
    try:
        from ..db_adapter import get_db
        from datetime import datetime
        import json

        db = get_db()
        value_json = json.dumps(new_list)

        db.insert_rows(
            'cascade_state',
            [{
                'session_id': session_id,
                'cascade_id': cascade_id or 'unknown',
                'key': key,
                'value': value_json,
                'cell_name': cell_name or 'unknown',
                'created_at': datetime.now(),
                'value_type': 'array'
            }],
            columns=['session_id', 'cascade_id', 'key', 'value', 'cell_name', 'created_at', 'value_type']
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Could not persist state to cascade_state table: {e}")

    return f"Appended to {key}: now has {len(new_list)} item(s)"


@simple_eddy
def get_state(key: str, default=None):
    """
    Retrieves a value from session state.

    Returns the default value if key doesn't exist.
    Useful in deterministic cells that need to read state.

    Example:
        expenses = get_state("expenses", [])
        total = sum(e["amount"] for e in expenses)
    """
    session_id = current_session_context.get()
    if not session_id:
        return default

    echo = get_echo(session_id)
    return echo.state.get(key, default)
