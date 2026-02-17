"""
Native input skill for RVBBIT companion.

Simplified blocking input that waits for text from the RVBBIT embedded server
instead of web checkpoints. No UI generation, no SSE, no web dependencies.

The flow:
1. Cascade calls `wait_for_input("What should I do?")`
2. Creates a lightweight checkpoint (just question + ID)
3. Blocks (polls) until RVBBIT posts the user's text response
4. Returns the text to the cascade

RVBBIT side:
- GET /companion/pending  → returns the pending question (if any)
- POST /companion/respond → sends user's text answer
"""

import os
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
    console = Console()

    manager = get_native_input_manager()
    request_id = manager.create(prompt)

    console.print(f"\n[bold cyan]{S.AGENT} Companion asks:[/bold cyan] {prompt}")
    console.print(f"[dim]Waiting for native input (id: {request_id}, timeout: {timeout_seconds}s)...[/dim]")

    deadline = time.time() + timeout_seconds

    while True:
        response = manager.poll(request_id)
        if response is not None:
            console.print(f"[green]{S.OK} Received: {response[:100]}{'...' if len(response) > 100 else ''}[/green]")
            
            # Store in state for downstream cells
            from .state_tools import get_current_cell_name, set_state_internal
            cell_name = get_current_cell_name()
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
