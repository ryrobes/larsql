"""
In-memory cell progress tracking for real-time visualization.

This module provides detailed cell progress tracking (turn, attempt, tool, ward, etc.)
for visualization purposes. The data is kept in-memory only - it's transient and only
relevant while a cascade is running.

For durable session state (status, heartbeat, blocked, etc.), see session_state.py
which uses ClickHouse as the coordination database.
"""

import time
from typing import Optional, List, Dict, Any


class CellProgress:
    """Tracks detailed progress within a cell for visualization."""

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
                "cell_elapsed_ms": int((time.time() - self.started_at) * 1000),
                "stage_elapsed_ms": int((time.time() - self.stage_started_at) * 1000)
            }
        }


class StateManager:
    """In-memory state manager for cell progress tracking."""

    def __init__(self):
        # In-memory cell progress tracking (keyed by session_id:cell_name)
        self._cell_progress: Dict[str, CellProgress] = {}
        # Track current cell per session for quick lookup
        self._current_cell: Dict[str, str] = {}

    def get_cell_progress(self, session_id: str, cell_name: str) -> CellProgress:
        """Get or create cell progress tracker."""
        key = f"{session_id}:{cell_name}"
        if key not in self._cell_progress:
            self._cell_progress[key] = CellProgress(cell_name)
        return self._cell_progress[key]

    def clear_cell_progress(self, session_id: str, cell_name: str):
        """Clear cell progress when cell completes."""
        key = f"{session_id}:{cell_name}"
        if key in self._cell_progress:
            del self._cell_progress[key]

    def set_current_cell(self, session_id: str, cell_name: str):
        """Track which cell is currently running for a session."""
        self._current_cell[session_id] = cell_name

    def clear_session(self, session_id: str):
        """Clear all state for a session when it completes."""
        if session_id in self._current_cell:
            del self._current_cell[session_id]
        # Clear any lingering cell progress for this session
        keys_to_remove = [k for k in self._cell_progress if k.startswith(f"{session_id}:")]
        for key in keys_to_remove:
            del self._cell_progress[key]

    def get_current_cell_progress(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the current cell progress for a session.

        Returns dict with cell_name and progress, or None if not found.
        """
        cell_name = self._current_cell.get(session_id)
        if not cell_name:
            return None

        key = f"{session_id}:{cell_name}"
        progress = self._cell_progress.get(key)
        if progress:
            return progress.to_dict()
        return None


_state_manager = StateManager()


def get_cell_progress(session_id: str, cell_name: str) -> CellProgress:
    """Get or create detailed cell progress tracker."""
    return _state_manager.get_cell_progress(session_id, cell_name)


def update_cell_progress(
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
    Update detailed cell progress (in-memory only).

    This enables real-time visualization of exactly where execution is
    within a cell (which turn, which attempt, which candidate, etc.)
    """
    progress = _state_manager.get_cell_progress(session_id, cell_name)

    # Track current cell for this session
    _state_manager.set_current_cell(session_id, cell_name)

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


def clear_cell_progress(session_id: str, cell_name: str):
    """Clear cell progress when cell completes."""
    _state_manager.clear_cell_progress(session_id, cell_name)


def clear_session_state(session_id: str):
    """Clear all in-memory state for a session."""
    _state_manager.clear_session(session_id)


def get_current_cell_progress(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the current cell progress for a session (in-memory).

    Returns dict with cell progress, or None if not found.
    Only works within the same process as the runner.
    """
    return _state_manager.get_current_cell_progress(session_id)


def get_session_state(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the current state for a session.

    Combines data from:
    - session_state.py (ClickHouse) for status/current_cell
    - In-memory cell progress (if available, same process only)

    Returns:
        Dict with session state or None if not found.
    """
    try:
        from .session_state import get_session_state_manager

        manager = get_session_state_manager()
        session = manager.get_session(session_id)

        if not session:
            return None

        # Build response dict
        result = {
            "session_id": session.session_id,
            "cascade_id": session.cascade_id,
            "status": session.status.value if session.status else None,
            "current_cell": session.current_cell,
            "depth": session.depth,
        }

        # Add in-memory cell progress if available (same process only)
        cell_progress = get_current_cell_progress(session_id)
        if cell_progress:
            result["cell_progress"] = cell_progress

        return result

    except Exception:
        return None
