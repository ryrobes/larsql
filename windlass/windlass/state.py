import os
import json
import time
import glob
from .config import get_config

class StateManager:
    def __init__(self):
        self.state_dir = get_config().state_dir
        os.makedirs(self.state_dir, exist_ok=True)

    def _get_path(self, session_id: str) -> str:
        return os.path.join(self.state_dir, f"{session_id}.json")

    def update(self, session_id: str, cascade_id: str, status: str, phase: str = None, depth: int = 0, metadata: dict = None):
        """
        Updates the state file for a session.
        """
        data = {
            "session_id": session_id,
            "cascade_id": cascade_id,
            "status": status, # running, completed, error
            "current_phase": phase,
            "depth": depth,
            "last_update": time.time(),
            "metadata": metadata or {}
        }
        
        path = self._get_path(session_id)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def get_active_sessions(self):
        """
        Returns a list of session states that are 'running'.
        Checks for staleness (optional, e.g. > 1 hour).
        """
        sessions = []
        files = glob.glob(os.path.join(self.state_dir, "*.json"))
        for fpath in files:
            try:
                with open(fpath, 'r') as f:
                    data = json.load(f)
                
                # We can filter by status
                if data.get("status") == "running":
                    sessions.append(data)
            except Exception:
                pass
        
        # Sort by recency
        sessions.sort(key=lambda x: x["last_update"], reverse=True)
        return sessions

_state_manager = StateManager()

def update_session_state(session_id: str, cascade_id: str, status: str, phase: str = None, depth: int = 0):
    _state_manager.update(session_id, cascade_id, status, phase, depth)

def list_running_sessions():
    return _state_manager.get_active_sessions()
