import json
from typing import Any, Dict, List, Optional

class Echo:
    """
    Represents the state/history of a Cascade (session).

    The history entries contain rich metadata for visualization:
    - trace_id: Unique ID for this entry
    - parent_id: Parent trace ID for tree structure
    - node_type: cascade, phase, turn, tool, soundings, reforge, etc.
    - metadata: Dict with additional context (phase_name, sounding_index, etc.)
    """
    def __init__(self, session_id: str, initial_state: Dict[str, Any] = None):
        self.session_id = session_id
        self.state = initial_state or {}
        self.history: List[Dict[str, Any]] = []
        self.lineage: List[Dict[str, Any]] = []
        # Execution context for visualization
        self._current_cascade_id: Optional[str] = None
        self._current_phase_name: Optional[str] = None

    def set_cascade_context(self, cascade_id: str):
        """Set the current cascade context for metadata enrichment."""
        self._current_cascade_id = cascade_id

    def set_phase_context(self, phase_name: str):
        """Set the current phase context for metadata enrichment."""
        self._current_phase_name = phase_name

    def update_state(self, key: str, value: Any):
        self.state[key] = value

    def add_history(self, entry: Dict[str, Any], trace_id: str = None, parent_id: str = None,
                   node_type: str = "msg", metadata: Dict[str, Any] = None):
        """
        Add an entry to the history with full metadata for visualization.

        Args:
            entry: The base entry dict (role, content, etc.)
            trace_id: Unique trace ID for this entry
            parent_id: Parent trace ID for tree structure
            node_type: Type of node (cascade, phase, turn, tool, etc.)
            metadata: Additional metadata dict (sounding_index, is_winner, phase_name, etc.)
        """
        entry["trace_id"] = trace_id
        entry["parent_id"] = parent_id
        entry["node_type"] = node_type

        # Build metadata with context
        meta = metadata or {}
        if self._current_cascade_id:
            meta.setdefault("cascade_id", self._current_cascade_id)
        if self._current_phase_name:
            meta.setdefault("phase_name", self._current_phase_name)

        entry["metadata"] = meta
        self.history.append(entry)

    def add_lineage(self, phase: str, output: Any, trace_id: str = None):
        self.lineage.append({
            "phase": phase,
            "output": output,
            "trace_id": trace_id
        })

    def get_full_echo(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "history": self.history,
            "lineage": self.lineage
        }

    def merge(self, other_echo: 'Echo'):
        """Merge another echo (from a sub-cascade) into this one."""
        # Merge state (updates overwrite)
        self.state.update(other_echo.state)
        # Append lineage
        self.lineage.extend(other_echo.lineage)
        # History might be tricky, let's append it with a marker
        self.history.append({"sub_echo": other_echo.session_id, "history": other_echo.history})

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Echo] = {}

    def get_session(self, session_id: str) -> Echo:
        if session_id not in self.sessions:
            self.sessions[session_id] = Echo(session_id)
        return self.sessions[session_id]

_session_manager = SessionManager()

def get_echo(session_id: str) -> Echo:
    return _session_manager.get_session(session_id)
