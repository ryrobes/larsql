"""
Async Narrator - Voice commentary during cascade execution.

The narrator generates spoken synopses of cascade activity without blocking
the main execution flow. It runs in background threads and charges all costs
(LLM + TTS) to the parent session for tracking.

Uses:
- Agent class for synopsis generation
- say tool for TTS (existing eddy)
"""

import os
import threading
import time
from typing import List, Dict, Optional, Any, TYPE_CHECKING

from ..logs import log_message

if TYPE_CHECKING:
    from ..cascade import NarratorConfig

# Default narrator instructions
DEFAULT_NARRATOR_INSTRUCTIONS = """You are a concise narrator providing real-time updates during an AI workflow.
Generate a 2-3 sentence spoken synopsis of what just happened.

Current phase: {{ phase_name }}
Model: {{ model }}
Turn: {{ turn_number }}/{{ max_turns }}

Recent activity:
{{ recent_activity }}

Keep it brief, informative, and natural for speech. Use [pauses], [emphasis],
and other ElevenLabs v3 tags sparingly for expressiveness. Output ONLY the narration text - no quotes, no prefixes, just the words to be spoken."""


class NarratorState:
    """Thread-safe narrator state tracking per session."""

    def __init__(self):
        self._last_narration_time: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._active_threads: Dict[str, threading.Thread] = {}  # session_id -> thread

    def is_narrating(self, session_id: str) -> bool:
        """Check if a narration is currently in progress for this session."""
        with self._lock:
            thread = self._active_threads.get(session_id)
            if thread and thread.is_alive():
                return True
            # Clean up dead thread reference
            if session_id in self._active_threads:
                del self._active_threads[session_id]
            return False

    def should_narrate(self, session_id: str, min_interval: float) -> bool:
        """Check if we should start a new narration (debounce + not already playing)."""
        with self._lock:
            # First check: is there already an active narration for this session?
            thread = self._active_threads.get(session_id)
            if thread and thread.is_alive():
                return False  # Still narrating, skip

            # Clean up dead thread reference
            if session_id in self._active_threads:
                del self._active_threads[session_id]

            # Second check: has enough time passed since last narration started?
            now = time.time()
            last = self._last_narration_time.get(session_id, 0)
            if now - last >= min_interval:
                self._last_narration_time[session_id] = now
                return True
            return False

    def register_thread(self, session_id: str, t: threading.Thread):
        """Track active narrator thread for a session."""
        with self._lock:
            self._active_threads[session_id] = t

    def active_count(self) -> int:
        """Get count of active narrator threads across all sessions."""
        with self._lock:
            # Clean up dead threads
            self._active_threads = {
                sid: t for sid, t in self._active_threads.items() if t.is_alive()
            }
            return len(self._active_threads)


# Global narrator state
_narrator_state = NarratorState()


def gather_narrator_context(
    context_messages: List[Dict],
    phase_name: str,
    turn_number: int,
    max_turns: int,
    tool_calls: Optional[List] = None,
    context_turns: int = 3
) -> Dict[str, Any]:
    """
    Gather recent context for narrator synopsis.

    Args:
        context_messages: Full conversation history
        phase_name: Current phase name
        turn_number: Current turn (1-indexed)
        max_turns: Total turns configured
        tool_calls: Recent tool calls from this turn
        context_turns: How many recent turns to include

    Returns:
        Dict with phase_name, turn_number, max_turns, recent_exchanges, tools_used
    """
    context = {
        "phase_name": phase_name,
        "turn_number": turn_number,
        "max_turns": max_turns,
        "recent_exchanges": [],
        "tools_used": [],
    }

    # Gather recent user/assistant exchanges
    msg_count = 0
    for msg in reversed(context_messages):
        if msg_count >= context_turns * 2:
            break
        role = msg.get("role")
        if role in ["user", "assistant"]:
            content = msg.get("content", "")
            if isinstance(content, str):
                # Truncate long messages
                preview = content[:200] + "..." if len(content) > 200 else content
                context["recent_exchanges"].insert(0, {"role": role, "preview": preview})
                msg_count += 1

    # Gather tool calls from this turn
    if tool_calls:
        for call in tool_calls[:5]:  # Max 5 tools
            func = call.get("function", {})
            tool_name = func.get("name", "unknown")
            context["tools_used"].append(tool_name)

    return context


def format_recent_activity(context: Dict[str, Any]) -> str:
    """Format gathered context into readable activity summary."""
    lines = []

    if context.get("tools_used"):
        lines.append(f"Tools called: {', '.join(context['tools_used'])}")

    for exchange in context.get("recent_exchanges", [])[-3:]:
        role = exchange["role"].upper()
        preview = exchange["preview"][:100]
        lines.append(f"{role}: {preview}")

    return "\n".join(lines) if lines else "No recent activity."


def narrate_async(
    session_id: str,
    parent_session_id: str,
    cascade_id: str,
    narrator_config: "NarratorConfig",
    context: Dict[str, Any],
    trace_id: str,
    parent_trace_id: Optional[str] = None,
) -> None:
    """
    Fire-and-forget async narrator call.

    Spawns background thread that:
    1. Generates synopsis via LLM (litellm)
    2. Speaks it via say tool
    3. Logs to unified_logs

    Never blocks calling code.
    """
    trigger = context.get("trigger", "unknown")
    phase = context.get("phase_name", "unknown")
    print(f"[Narrator] narrate_async called: trigger={trigger}, phase={phase}, session={session_id}")

    # Check debounce
    min_interval = narrator_config.min_interval_seconds if narrator_config else 10.0
    if not _narrator_state.should_narrate(session_id, min_interval):
        print(f"[Narrator] SKIP: debounce/already playing (min_interval={min_interval}s)")
        return  # Too soon since last narration

    # Check TTS availability
    from .tts import is_available as tts_available
    if not tts_available():
        print(f"[Narrator] SKIP: TTS not configured (missing ELEVENLABS keys)")
        return

    print(f"[Narrator] Spawning narrator thread...")

    def worker():
        print(f"[Narrator] Worker thread started for trigger={trigger}")
        try:
            _run_narration(
                session_id=session_id,
                parent_session_id=parent_session_id,
                cascade_id=cascade_id,
                narrator_config=narrator_config,
                context=context,
                trace_id=trace_id,
                parent_trace_id=parent_trace_id,
            )
        except Exception as e:
            # Never crash main execution
            import traceback
            print(f"[Narrator] ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()

    # Spawn daemon thread (one per session - prevents audio overlap)
    t = threading.Thread(target=worker, daemon=True)
    _narrator_state.register_thread(session_id, t)
    t.start()


def _run_narration(
    session_id: str,
    parent_session_id: str,
    cascade_id: str,
    narrator_config: "NarratorConfig",
    context: Dict[str, Any],
    trace_id: str,
    parent_trace_id: Optional[str],
) -> None:
    """
    Internal narration logic (runs in background thread).

    Simple fire-and-forget: generate synopsis with Agent, speak with say().
    No session management - narrator is just a side-effect.
    """
    from ..prompts import render_instruction
    from ..agent import Agent
    from ..config import get_config
    from .tts import say

    config = get_config()
    print(f"[Narrator] _run_narration started")

    # Determine model (use cheap model by default)
    narrator_model = narrator_config.model if narrator_config and narrator_config.model else \
                     os.environ.get("WINDLASS_NARRATOR_MODEL", config.default_model)
    print(f"[Narrator] Using model: {narrator_model}")

    # Render narrator instructions
    instructions = DEFAULT_NARRATOR_INSTRUCTIONS
    if narrator_config and narrator_config.instructions:
        instructions = narrator_config.instructions

    # Start with the full render context from runner (has input, state, outputs, etc.)
    render_context = context.get("render_context", {}).copy()

    # Add narrator-specific variables
    render_context.update({
        "phase_name": context.get("phase_name", "unknown"),
        "model": context.get("model", "unknown"),
        "turn_number": context.get("turn_number", 1),
        "max_turns": context.get("max_turns", 1),
        "recent_activity": format_recent_activity(context),
        "tools_used": context.get("tools_used", []),
        "trigger": context.get("trigger", "turn"),
    })

    rendered_instructions = render_instruction(instructions, render_context)

    # Generate synopsis using Agent
    agent = Agent(
        model=narrator_model,
        system_prompt=rendered_instructions,
        tools=None,
        base_url=config.provider_base_url,
        api_key=config.provider_api_key,
    )

    print(f"[Narrator] Calling Agent.run()...")
    response = agent.run("Generate a brief spoken synopsis.")
    synopsis = response.get("content", "")
    print(f"[Narrator] Agent returned: {synopsis[:100] if synopsis else '(empty)'}...")

    if not synopsis or not synopsis.strip():
        print(f"[Narrator] SKIP: Empty synopsis returned")
        return  # Silent fail - narrator is optional

    # Clean up synopsis
    synopsis = synopsis.strip()
    if synopsis.startswith('"') and synopsis.endswith('"'):
        synopsis = synopsis[1:-1]

    # Speak it - that's all narrator does
    print(f"[Narrator] Calling say() with: {synopsis[:50]}...")
    say(synopsis)
    print(f"[Narrator] say() completed")


def get_narrator_state() -> NarratorState:
    """Get the global narrator state (for monitoring/debugging)."""
    return _narrator_state
