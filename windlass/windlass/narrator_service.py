"""
Event-Driven Narrator Service

The narrator service subscribes to cascade events and spawns background
narrator cascades that use the 'say' tool to provide voice commentary.

Key design principles:
1. Event-driven: Subscribes to phase_complete, cascade_complete, etc.
2. Singleton per session: Only one narrator cascade runs at a time
3. Latest-wins: If events stack up, only the most recent gets processed
4. Proper logging: All activity tracked via unified_logs
5. LLM-formatted speech: The narrator cascade uses 'say' as a tool, so
   the LLM decides how to format text for speech (with [tags], etc.)

Usage:
    # In runner, on cascade start:
    if config.narrator:
        narrator_service = NarratorService(config.narrator, session_id, cascade_id)
        narrator_service.start(event_bus)

    # On cascade end:
    narrator_service.stop()
"""

import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty
from typing import TYPE_CHECKING, Optional, Dict, Any, Set, List

from .events import Event, EventBus
from .logs import log_message

if TYPE_CHECKING:
    from .cascade import NarratorConfig


# Default narrator cascade - speaks about recent activity
DEFAULT_NARRATOR_CASCADE = {
    "cascade_id": "_narrator_internal",
    "description": "Internal narrator cascade - generates and speaks status updates",
    "phases": [{
        "name": "speak",
        "instructions": """You are a concise narrator providing real-time voice updates during an AI workflow.

Current phase: {{ input.phase_name }}
Event: {{ input.event_type }}
{% if input.cascade_complete %}
The workflow has completed.
{% endif %}

Recent activity:
{{ input.context }}

{% if input.previous_narrations %}
## What you've already said (DO NOT REPEAT):
{% for narration in input.previous_narrations %}
- [{{ narration.event }}] "{{ narration.text }}"
{% endfor %}

Build on what you've said before. Reference earlier points if relevant. Maintain your voice/personality consistently.
{% endif %}

Generate a brief 1-2 sentence spoken synopsis, then call the 'say' tool to speak it aloud.
Use ElevenLabs v3 tags sparingly for expressiveness: [excited], [curious], [thoughtful], etc.
Keep it natural and informative. Focus on what's NEW or what was just accomplished.

{% if input.cascade_complete %}
This is the final update - give a brief wrap-up of the entire journey.
{% endif %}

IMPORTANT: You MUST call the 'say' tool with your synopsis. Do not just output text.""",
        "tackle": ["say"],
        "rules": {"max_turns": 1}
    }]
}


@dataclass
class PendingNarration:
    """A narration event waiting to be processed."""
    event: Event
    context: Dict[str, Any]
    received_at: float  # time.time()

    def age_seconds(self) -> float:
        return time.time() - self.received_at


class NarratorService:
    """
    Event-driven narrator service.

    Subscribes to cascade events and spawns narrator cascades to provide
    voice commentary. Handles debouncing, overlap prevention, and staleness.
    """

    def __init__(
        self,
        config: "NarratorConfig",
        session_id: str,
        cascade_id: str,
        parent_session_id: Optional[str] = None,
    ):
        self.config = config
        self.session_id = session_id
        self.cascade_id = cascade_id
        self.parent_session_id = parent_session_id or session_id

        # State
        self._running = False
        self._lock = threading.Lock()
        self._is_narrating = False
        self._pending: Optional[PendingNarration] = None
        self._last_narration_time: float = 0
        self._event_queue: Optional[Queue] = None
        self._worker_thread: Optional[threading.Thread] = None

        # Narration history for continuity (stores what was said)
        self._narration_history: List[Dict[str, str]] = []
        self._max_history_items = 5  # Keep last N narrations for context

        # Map event types to our internal names
        self._event_map = {
            "phase_start": "phase_start",
            "phase_complete": "phase_complete",
            "cascade_start": "cascade_start",
            "cascade_complete": "cascade_complete",
            "turn_complete": "turn",
            "tool_complete": "tool_call",
        }

        # Which events we care about (from config.effective_on_events)
        self._subscribed_events: Set[str] = set()
        events_to_subscribe = config.effective_on_events if hasattr(config, 'effective_on_events') else ["phase_complete"]
        for evt in events_to_subscribe:
            # Map our config names to event bus names
            if evt == "turn":
                self._subscribed_events.add("turn_complete")
            elif evt == "tool_call":
                self._subscribed_events.add("tool_complete")
            elif evt in ("phase_start", "phase_complete", "cascade_start", "cascade_complete"):
                self._subscribed_events.add(evt)

    def start(self, event_bus: EventBus):
        """Start listening for events."""
        if self._running:
            return

        self._running = True
        self._event_queue = event_bus.subscribe()

        # Start worker thread that processes events
        self._worker_thread = threading.Thread(
            target=self._event_loop,
            daemon=True,
            name=f"narrator-{self.session_id[:8]}"
        )
        self._worker_thread.start()

        log_message(self.session_id, "narrator", "Narrator service started",
                   metadata={"subscribed_events": list(self._subscribed_events)})

    def stop(self, wait_timeout: float = 30.0):
        """
        Stop the narrator service.

        Args:
            wait_timeout: Maximum seconds to wait for current narration to complete.
        """
        self._running = False

        # Wait for any current narration to complete (so audio finishes playing)
        if self._is_narrating:
            log_message(self.session_id, "narrator", "Waiting for narration to complete...")
            start_wait = time.time()
            while self._is_narrating and (time.time() - start_wait) < wait_timeout:
                time.sleep(0.5)

            if self._is_narrating:
                log_message(self.session_id, "narrator",
                           f"Narration still running after {wait_timeout}s, proceeding with shutdown")

        if self._event_queue:
            # Push a poison pill to wake up the worker
            try:
                self._event_queue.put_nowait(None)
            except:
                pass

        # Wait for worker thread to finish
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def _event_loop(self):
        """Main event processing loop."""
        while self._running:
            try:
                # Wait for events with timeout (allows checking _running)
                event = self._event_queue.get(timeout=1.0)

                if event is None:
                    # Poison pill - stop
                    break

                if not isinstance(event, Event):
                    continue

                # Only process events for our session
                if event.session_id != self.session_id:
                    continue

                # Only process events we're subscribed to
                if event.type not in self._subscribed_events:
                    continue

                # Process the event
                self._handle_event(event)

            except Empty:
                # Timeout - check if we should process pending
                self._check_pending()
            except Exception as e:
                log_message(self.session_id, "narrator_error",
                           f"Event loop error: {type(e).__name__}: {e}")

    def _handle_event(self, event: Event):
        """Handle an incoming event."""
        # Build context from event data
        context = self._build_context(event)

        pending = PendingNarration(
            event=event,
            context=context,
            received_at=time.time()
        )

        with self._lock:
            if self._is_narrating:
                # Replace any existing pending with this newer one (latest-wins)
                old_pending = self._pending
                self._pending = pending
                if old_pending:
                    log_message(self.session_id, "narrator",
                               f"Replaced stale pending event ({old_pending.event.type}) with {event.type}")
            else:
                # Check debounce
                time_since_last = time.time() - self._last_narration_time
                min_interval = self.config.min_interval_seconds if self.config else 10.0

                if time_since_last >= min_interval:
                    # Start narrating immediately
                    self._start_narration(pending)
                else:
                    # Store as pending, will be processed after interval
                    self._pending = pending
                    log_message(self.session_id, "narrator",
                               f"Debouncing event {event.type}, {min_interval - time_since_last:.1f}s remaining")

    def _check_pending(self):
        """Check if we should process pending narration."""
        with self._lock:
            if self._is_narrating or self._pending is None:
                return

            # Check debounce
            time_since_last = time.time() - self._last_narration_time
            min_interval = self.config.min_interval_seconds if self.config else 10.0

            if time_since_last >= min_interval:
                # Check if pending is too old (stale)
                max_age = min_interval * 3  # Events older than 3x interval are stale
                if self._pending.age_seconds() > max_age:
                    log_message(self.session_id, "narrator",
                               f"Discarding stale pending event ({self._pending.age_seconds():.1f}s old)")
                    self._pending = None
                    return

                pending = self._pending
                self._pending = None
                self._start_narration(pending)

    def _start_narration(self, pending: PendingNarration):
        """Start a narration in background thread."""
        self._is_narrating = True
        self._last_narration_time = time.time()

        def worker():
            try:
                self._run_narrator_cascade(pending)
            except Exception as e:
                log_message(self.session_id, "narrator_error",
                           f"Narration failed: {type(e).__name__}: {e}")
            finally:
                with self._lock:
                    self._is_narrating = False
                # Check if there's pending work
                self._check_pending()

        # Non-daemon thread so it can complete even if main thread finishes
        t = threading.Thread(target=worker, daemon=False,
                            name=f"narrator-speak-{self.session_id[:8]}")
        t.start()

    def _run_narrator_cascade(self, pending: PendingNarration):
        """Run the narrator cascade to generate and speak the synopsis."""
        from .runner import WindlassRunner
        from .config import get_config

        config = get_config()
        event = pending.event
        context = pending.context

        # Generate unique session ID for this narration
        narrator_session = f"{self.session_id}_narrator_{int(time.time())}_{uuid.uuid4().hex[:4]}"

        log_message(self.session_id, "narrator",
                   f"Starting narration for {event.type}",
                   metadata={"narrator_session": narrator_session})

        # Build input for narrator cascade
        event_type_friendly = self._event_map.get(event.type, event.type)
        narrator_input = {
            "phase_name": context.get("phase_name", "unknown"),
            "event_type": event_type_friendly,
            "context": context.get("summary", "No context available"),
            "cascade_complete": event.type == "cascade_complete",
            "turn_number": context.get("turn_number"),
            "tools_used": context.get("tools_used", []),
            # Include previous narrations for continuity
            "previous_narrations": list(self._narration_history),
        }

        # Use custom cascade if configured, otherwise use default
        cascade_dict = DEFAULT_NARRATOR_CASCADE.copy()

        # Override instructions if custom ones provided
        if self.config and self.config.instructions:
            cascade_dict["phases"][0]["instructions"] = self.config.instructions

        # Override model if specified
        if self.config and self.config.model:
            cascade_dict["phases"][0]["model"] = self.config.model

        try:
            # Create runner for narrator cascade (pass dict directly to config_path)
            runner = WindlassRunner(
                config_path=cascade_dict,
                session_id=narrator_session,
                parent_session_id=self.parent_session_id,
                depth=1,  # Mark as sub-cascade
            )

            # Run the narrator cascade
            result = runner.run(narrator_input)

            # Extract what was said and add to history for continuity
            spoken_text = self._extract_spoken_text(result)
            if spoken_text:
                self._add_to_history(event_type_friendly, spoken_text)

            log_message(self.session_id, "narrator",
                       f"Narration complete for {event.type}",
                       metadata={
                           "narrator_session": narrator_session,
                           "spoken_text": spoken_text[:100] if spoken_text else None,
                           "history_size": len(self._narration_history),
                       })

        except Exception as e:
            log_message(self.session_id, "narrator_error",
                       f"Narrator cascade failed: {type(e).__name__}: {e}")
            raise

    def _build_context(self, event: Event) -> Dict[str, Any]:
        """Build context dictionary from event data."""
        data = event.data or {}

        # Build a human-readable summary
        summary_parts = []

        phase_name = data.get("phase_name", "unknown")

        if event.type == "phase_start":
            summary_parts.append(f"Starting phase '{phase_name}'")
        elif event.type == "phase_complete":
            summary_parts.append(f"Completed phase '{phase_name}'")
            if data.get("output"):
                output = str(data["output"])[:300]
                summary_parts.append(f"Output: {output}")
        elif event.type == "cascade_complete":
            summary_parts.append(f"Workflow '{data.get('cascade_id', 'unknown')}' has completed")
            if data.get("final_output"):
                output = str(data["final_output"])[:300]
                summary_parts.append(f"Final result: {output}")
        elif event.type == "turn_complete":
            turn = data.get("turn_number", "?")
            max_turns = data.get("max_turns", "?")
            summary_parts.append(f"Turn {turn}/{max_turns} in phase '{phase_name}'")
            if data.get("tool_calls"):
                tools = [tc.get("name", "unknown") for tc in data["tool_calls"][:3]]
                summary_parts.append(f"Tools used: {', '.join(tools)}")
        elif event.type == "tool_complete":
            tool_name = data.get("tool_name", "unknown")
            summary_parts.append(f"Tool '{tool_name}' completed in phase '{phase_name}'")

        return {
            "phase_name": phase_name,
            "cascade_id": data.get("cascade_id", self.cascade_id),
            "turn_number": data.get("turn_number"),
            "max_turns": data.get("max_turns"),
            "tools_used": data.get("tool_calls", []),
            "summary": "\n".join(summary_parts) if summary_parts else f"Event: {event.type}",
            "raw_data": data,
        }

    def _extract_spoken_text(self, result: Dict[str, Any]) -> Optional[str]:
        """
        Extract the text that was spoken from the narrator cascade result.

        The narrator cascade calls the 'say' tool with text. We parse the
        cascade history to find the tool call and extract the text argument.
        """
        import json
        import re

        if not result or not isinstance(result, dict):
            return None

        history = result.get("history", [])

        # Look for assistant messages that contain tool calls to 'say'
        for entry in history:
            if entry.get("role") != "assistant":
                continue

            content = entry.get("content", "")
            if not content or "say" not in content:
                continue

            # Try to extract JSON tool call from the content
            # The format is usually: ```json\n{"tool": "say", "arguments": {"text": "..."}}\n```
            try:
                # Find JSON blocks
                json_matches = re.findall(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
                for json_str in json_matches:
                    try:
                        tool_call = json.loads(json_str)
                        if tool_call.get("tool") == "say":
                            text = tool_call.get("arguments", {}).get("text")
                            if text:
                                return text
                    except json.JSONDecodeError:
                        continue

                # Also try parsing the whole content as JSON (some models don't use code blocks)
                if content.strip().startswith("{"):
                    try:
                        tool_call = json.loads(content.strip())
                        if tool_call.get("tool") == "say":
                            text = tool_call.get("arguments", {}).get("text")
                            if text:
                                return text
                    except json.JSONDecodeError:
                        pass

            except Exception:
                continue

        return None

    def _add_to_history(self, event_type: str, spoken_text: str):
        """Add a narration to the history, maintaining max size."""
        with self._lock:
            self._narration_history.append({
                "event": event_type,
                "text": spoken_text,
                "timestamp": datetime.now().isoformat(),
            })

            # Trim to max size
            while len(self._narration_history) > self._max_history_items:
                self._narration_history.pop(0)


def check_tts_available() -> bool:
    """Check if TTS is configured and available."""
    from .eddies.tts import is_available
    return is_available()
