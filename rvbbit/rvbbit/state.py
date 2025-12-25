import os
import json
import time
import glob
from typing import Optional, List, Dict, Any
from .config import get_config


class PhaseProgress:
    """Tracks detailed progress within a phase for visualization."""

    def __init__(self, cell_name: str):
        self.cell_name = cell_name
        self.stage = "starting"  # starting, pre_ward, main, post_ward, complete

        # Turn tracking
        self.current_turn = 0
        self.max_turns = 1

        # Attempt/retry tracking (loop_until)
        self.current_attempt = 0
        self.max_attempts = 1

        # Sounding tracking
        self.candidate_index: Optional[int] = None
        self.sounding_factor: Optional[int] = None
        self.sounding_stage: Optional[str] = None  # executing, evaluating, complete

        # Reforge tracking
        self.reforge_step: Optional[int] = None
        self.reforge_total_steps: Optional[int] = None

        # Ward tracking
        self.current_ward: Optional[str] = None
        self.ward_type: Optional[str] = None  # pre, post
        self.ward_index: Optional[int] = None
        self.total_wards: Optional[int] = None

        # Tool tracking
        self.current_tool: Optional[str] = None
        self.tools_called: List[str] = []

        # Timing
        self.started_at = time.time()
        self.stage_started_at = time.time()

    def to_dict(self) -> dict:
        return {
            "cell_name": self.cell_name,
            "stage": self.stage,
            "turn": {
                "current": self.current_turn,
                "max": self.max_turns
            },
            "attempt": {
                "current": self.current_attempt,
                "max": self.max_attempts
            },
            "candidate": {
                "index": self.candidate_index,
                "factor": self.sounding_factor,
                "stage": self.sounding_stage
            } if self.candidate_index is not None else None,
            "reforge": {
                "step": self.reforge_step,
                "total_steps": self.reforge_total_steps
            } if self.reforge_step is not None else None,
            "ward": {
                "name": self.current_ward,
                "type": self.ward_type,
                "index": self.ward_index,
                "total": self.total_wards
            } if self.current_ward else None,
            "tool": {
                "current": self.current_tool,
                "called": self.tools_called
            },
            "timing": {
                "phase_elapsed_ms": int((time.time() - self.started_at) * 1000),
                "stage_elapsed_ms": int((time.time() - self.stage_started_at) * 1000)
            }
        }


class StateManager:
    def __init__(self):
        self.state_dir = get_config().state_dir
        os.makedirs(self.state_dir, exist_ok=True)
        # In-memory phase progress tracking
        self._phase_progress: Dict[str, PhaseProgress] = {}

    def _get_path(self, session_id: str) -> str:
        return os.path.join(self.state_dir, f"{session_id}.json")

    def get_phase_progress(self, session_id: str, cell_name: str) -> PhaseProgress:
        """Get or create phase progress tracker."""
        key = f"{session_id}:{cell_name}"
        if key not in self._phase_progress:
            self._phase_progress[key] = PhaseProgress(cell_name)
        return self._phase_progress[key]

    def clear_phase_progress(self, session_id: str, cell_name: str):
        """Clear phase progress when phase completes."""
        key = f"{session_id}:{cell_name}"
        if key in self._phase_progress:
            del self._phase_progress[key]

    def update(self, session_id: str, cascade_id: str, status: str, phase: str = None, depth: int = 0, metadata: dict = None):
        """
        Updates the state file for a session.
        """
        # Get phase progress if available
        phase_progress = None
        if phase and status == "running":
            progress = self._phase_progress.get(f"{session_id}:{phase}")
            if progress:
                phase_progress = progress.to_dict()

        data = {
            "session_id": session_id,
            "cascade_id": cascade_id,
            "status": status,  # running, completed, error
            "current_cell": phase,
            "depth": depth,
            "last_update": time.time(),
            "last_update_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "metadata": metadata or {},
            # NEW: Detailed phase progress for visualization
            "phase_progress": phase_progress
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


def get_phase_progress(session_id: str, cell_name: str) -> PhaseProgress:
    """Get or create detailed phase progress tracker."""
    return _state_manager.get_phase_progress(session_id, cell_name)


def update_phase_progress(
    session_id: str,
    cascade_id: str,
    cell_name: str,
    depth: int = 0,
    *,
    stage: str = None,
    turn: int = None,
    max_turns: int = None,
    attempt: int = None,
    max_attempts: int = None,
    candidate_index: int = None,
    sounding_factor: int = None,
    sounding_stage: str = None,
    reforge_step: int = None,
    reforge_total_steps: int = None,
    ward_name: str = None,
    ward_type: str = None,
    ward_index: int = None,
    total_wards: int = None,
    tool_name: str = None
):
    """
    Update detailed phase progress and persist to state file.

    This enables real-time visualization of exactly where execution is
    within a phase (which turn, which attempt, which candidate, etc.)
    """
    progress = _state_manager.get_phase_progress(session_id, cell_name)

    # Update fields if provided
    if stage is not None:
        progress.stage = stage
        progress.stage_started_at = time.time()

    if turn is not None:
        progress.current_turn = turn
    if max_turns is not None:
        progress.max_turns = max_turns

    if attempt is not None:
        progress.current_attempt = attempt
    if max_attempts is not None:
        progress.max_attempts = max_attempts

    if candidate_index is not None:
        progress.candidate_index = candidate_index
    if sounding_factor is not None:
        progress.sounding_factor = sounding_factor
    if sounding_stage is not None:
        progress.sounding_stage = sounding_stage

    if reforge_step is not None:
        progress.reforge_step = reforge_step
    if reforge_total_steps is not None:
        progress.reforge_total_steps = reforge_total_steps

    if ward_name is not None:
        progress.current_ward = ward_name
        progress.ward_type = ward_type
        progress.ward_index = ward_index
        progress.total_wards = total_wards

    if tool_name is not None:
        progress.current_tool = tool_name
        if tool_name and tool_name not in progress.tools_called:
            progress.tools_called.append(tool_name)

    # Persist to state file
    _state_manager.update(session_id, cascade_id, "running", cell_name, depth)


def clear_phase_progress(session_id: str, cell_name: str):
    """Clear phase progress when phase completes."""
    _state_manager.clear_phase_progress(session_id, cell_name)


def get_session_state(session_id: str) -> dict:
    """
    Get the current state for a session.

    Returns:
        Dict with session state or None if not found/error.
        Keys: session_id, cascade_id, status, current_cell, depth, last_update, metadata
    """
    path = _state_manager._get_path(session_id)
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return None
