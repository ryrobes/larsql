from .base import simple_eddy
import threading
import time
import uuid
from typing import Optional
from ..tracing import get_current_trace, TraceNode
from ..config import get_config
import os

@simple_eddy
def spawn_cascade(cascade_ref: str, input_data: dict = None, parent_trace: Optional[TraceNode] = None, parent_session_id: str = None) -> str:
    """
    Spawns a cascade in the background (fire-and-forget).
    Returns the new session ID immediately.

    Args:
        cascade_ref: The path to the cascade JSON file.
        input_data: Optional dictionary of input data for the spawned cascade.
        parent_trace: The TraceNode of the calling cascade for lineage.
        parent_session_id: The session_id of the parent cascade.
    """
    # Resolve path. Assume cascade_ref is either absolute or relative to the project root.
    resolved_cascade_ref = cascade_ref
    if not os.path.isabs(cascade_ref):
        # Assume cascade_ref is relative to the project root (where run_cascade is called)
        resolved_cascade_ref = os.path.join(os.getcwd(), cascade_ref)

    if not os.path.exists(resolved_cascade_ref) and os.path.exists(resolved_cascade_ref + ".json"):
         resolved_cascade_ref = resolved_cascade_ref + ".json"

    session_id = f"spawned_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    def worker():
        # Import locally to avoid circular dependency
        from ..runner import run_cascade

        # Run in separate thread
        try:
            # We use a new runner instance, passing the parent trace AND parent_session_id
            run_cascade(resolved_cascade_ref, input_data or {}, session_id=session_id, parent_trace=parent_trace, parent_session_id=parent_session_id)
        except Exception as e:
            print(f"[Spawn Error] {e}")

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    return f"Spawned cascade '{cascade_ref}' with Session ID: {session_id}"