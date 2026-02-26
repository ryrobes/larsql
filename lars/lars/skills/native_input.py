"""
Native input skill for RVBBIT companion.

Primary path uses the checkpoint system so input waits are durable across
multi-worker Studio deployments. A legacy in-memory fallback is kept for
interactive CLI sessions.

The flow:
1. Cascade calls `wait_for_input("What should I do?")`
2. Creates a lightweight checkpoint (just question + ID)
3. Blocks (polls) until RVBBIT posts the user's text response
4. Returns the text to the cascade

RVBBIT side:
- GET /companion/pending  → returns the pending question (if any)
- POST /companion/respond → sends user's text answer
"""

import json
import os
import sys
import time
import uuid
import threading
from typing import Optional
from .base import simple_eddy
from ..console_style import S
from ..skill_registry import register_skill


# ── In-memory input queue (singleton) ──
# Simple: one pending question at a time. The companion is a 1:1 conversation.

class _NativeInputManager:
    """Thread-safe manager for a single pending input request."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending_id: Optional[str] = None
        self._pending_question: Optional[str] = None
        self._response: Optional[str] = None

    def create(self, question: str) -> str:
        """Create a pending input request. Returns request ID."""
        with self._lock:
            rid = uuid.uuid4().hex[:12]
            self._pending_id = rid
            self._pending_question = question
            self._response = None
            return rid

    def get_pending(self) -> Optional[dict]:
        """Get the current pending question (if any). Called by RVBBIT server."""
        with self._lock:
            if self._pending_id and self._response is None:
                return {
                    "id": self._pending_id,
                    "question": self._pending_question,
                }
            return None

    def respond(self, request_id: str, text: str) -> bool:
        """Submit a response. Called by RVBBIT server. Returns True if matched."""
        with self._lock:
            if self._pending_id == request_id and self._response is None:
                self._response = text
                return True
            return False

    def poll(self, request_id: str) -> Optional[str]:
        """Check if a response has arrived. Returns text or None."""
        with self._lock:
            if self._pending_id == request_id and self._response is not None:
                return self._response
            return None

    def cancel(self, request_id: str) -> bool:
        """Cancel a pending request."""
        with self._lock:
            if self._pending_id == request_id:
                self._pending_id = None
                self._pending_question = None
                self._response = None
                return True
            return False

    def clear(self):
        """Clear everything."""
        with self._lock:
            self._pending_id = None
            self._pending_question = None
            self._response = None


# Singleton
_manager = _NativeInputManager()


def get_native_input_manager() -> _NativeInputManager:
    """Get the global native input manager."""
    return _manager


def _extract_response_text(response) -> str:
    """Normalize checkpoint response payloads into plain text."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ("text", "message", "value", "response"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in response.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = _extract_response_text(value)
                if nested:
                    return nested
        return json.dumps(response, ensure_ascii=False)
    return str(response)


# ── The skill ──

@simple_eddy
def wait_for_input(prompt: str = "What would you like to do?", timeout_seconds: int = 600) -> str:
    """
    Pause the cascade and wait for text input from the RVBBIT companion interface.
    
    This blocks the cascade thread (like an LLM API call) until the user speaks
    or types a response through RVBBIT's intent bar.
    
    Args:
        prompt: The question or prompt to show the user
        timeout_seconds: Max time to wait (default 10 minutes)
    
    Returns:
        The user's text response
    """
    from rich.console import Console
    from .state_tools import (
        get_current_cell_name,
        get_current_session_id,
        set_state_internal,
    )

    console = Console()
    cell_name = get_current_cell_name()
    session_id = get_current_session_id()
    timeout_seconds = max(1, int(timeout_seconds))

    use_checkpoint = os.environ.get("LARS_USE_CHECKPOINTS", "false").lower() == "true"
    if not sys.stdin.isatty():
        use_checkpoint = True

    if use_checkpoint and session_id:
        try:
            from ..checkpoints import get_checkpoint_manager, CheckpointType
            from ..human_ui import generate_ask_human_ui
            from ..tracing import get_current_trace

            trace = get_current_trace()
            checkpoint_manager = get_checkpoint_manager()
            ui_spec = generate_ask_human_ui(
                question=prompt,
                context=None,
                ui_hint="text",
                cell_name=cell_name or "wait_for_input",
                cascade_id=trace.name if trace else "unknown",
                session_id=session_id,
            )

            checkpoint = checkpoint_manager.create_checkpoint(
                session_id=session_id,
                cascade_id=trace.name if trace else "unknown",
                cell_name=cell_name or "wait_for_input",
                checkpoint_type=CheckpointType.FREE_TEXT,
                ui_spec=ui_spec,
                echo_snapshot={},
                cell_output=prompt,
                timeout_seconds=timeout_seconds,
            )

            console.print(f"\n[bold cyan]{S.AGENT} Companion asks:[/bold cyan] {prompt}")
            console.print(
                f"[dim]Waiting for checkpoint input (id: {checkpoint.id}, timeout: {timeout_seconds}s)...[/dim]"
            )

            response = checkpoint_manager.wait_for_response(
                checkpoint_id=checkpoint.id,
                timeout=float(timeout_seconds),
                poll_interval=0.15,
            )
            if response is None:
                console.print(f"[yellow]{S.WARN} Input timeout after {timeout_seconds}s[/yellow]")
                return "[No response - timeout]"

            answer = _extract_response_text(response).strip()
            if not answer:
                answer = "[No response]"

            console.print(f"[green]{S.OK} Received: {answer[:100]}{'...' if len(answer) > 100 else ''}[/green]")
            if cell_name:
                set_state_internal(cell_name, answer)
            return answer

        except Exception as checkpoint_err:
            console.print(
                f"[yellow]{S.WARN} Checkpoint input unavailable ({checkpoint_err}); falling back to in-memory bridge[/yellow]"
            )
    elif use_checkpoint and not session_id:
        console.print(
            f"[yellow]{S.WARN} No session ID available; falling back to in-memory bridge[/yellow]"
        )

    # Legacy in-memory fallback (single-process only).
    manager = get_native_input_manager()
    request_id = manager.create(prompt)

    console.print(f"\n[bold cyan]{S.AGENT} Companion asks:[/bold cyan] {prompt}")
    console.print(f"[dim]Waiting for native input (id: {request_id}, timeout: {timeout_seconds}s)...[/dim]")

    deadline = time.time() + timeout_seconds

    while True:
        response = manager.poll(request_id)
        if response is not None:
            console.print(f"[green]{S.OK} Received: {response[:100]}{'...' if len(response) > 100 else ''}[/green]")
            
            if cell_name:
                set_state_internal(cell_name, response)
            
            return response

        if time.time() > deadline:
            manager.cancel(request_id)
            console.print(f"[yellow]{S.WARN} Input timeout after {timeout_seconds}s[/yellow]")
            return "[No response - timeout]"

        time.sleep(0.3)  # Poll every 300ms


# Register the skill
register_skill("wait_for_input", wait_for_input)
