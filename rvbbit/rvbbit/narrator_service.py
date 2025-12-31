"""
Event-Driven Narrator Service

The narrator service subscribes to cascade events and spawns background
narrator cascades that use the 'say' tool to provide voice commentary.

Key design principles:
1. Event-driven: Subscribes to cell_complete, cascade_complete, etc.
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
    "cells": [{
        "name": "speak",
        "instructions": """You are a concise narrator providing real-time voice updates during an AI workflow.

Current cell: {{ input.cell_name }}
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
        "traits": ["say"],
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
    Narrator service with two modes:
    1. Event-driven: Subscribes to specific cascade events
    2. Polling: Checks echo.history periodically for changes

    Polling mode is more reliable as it catches ALL activity regardless of events.
    """

    def __init__(
        self,
        config: "NarratorConfig",
        session_id: str,
        cascade_id: str,
        parent_session_id: Optional[str] = None,
        cascade_input: Optional[Dict[str, Any]] = None,
        echo = None,  # For polling mode: direct access to Echo object
    ):
        self.config = config
        self.session_id = session_id
        self.cascade_id = cascade_id
        self.parent_session_id = parent_session_id or session_id
        self.cascade_input = cascade_input or {}  # Original cascade input for template access

        # Capture hooks from current context for UI mode detection
        # Must be captured here (main thread) because ContextVars don't cross thread boundaries
        from .runner import get_current_hooks
        self._parent_hooks = get_current_hooks()

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

        # Polling mode state
        self._mode = getattr(config, 'mode', 'event')  # 'event' or 'poll'
        self._echo = echo  # Reference to runner's Echo object (for polling)
        self._last_narrated_index = 0  # Track which echo.history index we last narrated
        self._poll_interval = getattr(config, 'poll_interval_seconds', 3.0)  # How often to check
        self._context_turns = getattr(config, 'context_turns', 5)  # How many messages to include

        # Map event types to our internal names
        self._event_map = {
            "cell_start": "cell_start",
            "cell_complete": "cell_complete",
            "cascade_start": "cascade_start",
            "cascade_complete": "cascade_complete",
            "turn_complete": "turn",
            "tool_complete": "tool_call",
        }

        # Which events we care about (from config.effective_on_events) - for event mode only
        self._subscribed_events: Set[str] = set()
        if self._mode == 'event':
            events_to_subscribe = config.effective_on_events if hasattr(config, 'effective_on_events') else ["cell_complete"]
            for evt in events_to_subscribe:
                # Map our config names to event bus names
                if evt == "turn":
                    self._subscribed_events.add("turn_complete")
                elif evt == "tool_call":
                    self._subscribed_events.add("tool_complete")
                elif evt in ("cell_start", "cell_complete", "cascade_start", "cascade_complete"):
                    self._subscribed_events.add(evt)

    def start(self, event_bus: EventBus):
        """Start narrator service (event or polling mode)."""
        if self._running:
            return

        self._running = True

        if self._mode == 'poll':
            # Polling mode: check echo.history periodically
            if not self._echo:
                log_message(self.session_id, "narrator_error",
                           "Polling mode requires echo object but none was provided")
                return

            self._worker_thread = threading.Thread(
                target=self._poll_loop,
                daemon=True,
                name=f"narrator-poll-{self.session_id[:8]}"
            )
            self._worker_thread.start()

            log_message(self.session_id, "narrator", "Narrator service started (polling mode)",
                       metadata={"poll_interval": self._poll_interval,
                                "min_interval": self.config.min_interval_seconds if self.config else 10.0})
        else:
            # Event mode: subscribe to event bus
            self._event_queue = event_bus.subscribe()

            self._worker_thread = threading.Thread(
                target=self._event_loop,
                daemon=True,
                name=f"narrator-event-{self.session_id[:8]}"
            )
            self._worker_thread.start()

            log_message(self.session_id, "narrator", "Narrator service started (event mode)",
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

    def _poll_loop(self):
        """Polling loop - checks echo.history for changes."""
        log_message(self.session_id, "narrator", "Poll loop started",
                   metadata={"poll_interval": self._poll_interval, "context_turns": self._context_turns})

        while self._running:
            try:
                time.sleep(self._poll_interval)

                if not self._running:
                    break

                # Check if history has new messages since last narration
                current_length = len(self._echo.history) if self._echo else 0

                if current_length <= self._last_narrated_index:
                    # No new messages
                    continue

                # New messages available! Check if enough time has passed
                time_since_last = time.time() - self._last_narration_time
                min_interval = self.config.min_interval_seconds if self.config else 10.0

                if time_since_last < min_interval:
                    # Too soon, will check again on next poll
                    log_message(self.session_id, "narrator",
                               f"New messages detected but waiting {min_interval - time_since_last:.1f}s more",
                               metadata={"new_messages": current_length - self._last_narrated_index})
                    continue

                # Ready to narrate! Check if we're already narrating
                with self._lock:
                    if self._is_narrating:
                        # Already narrating, will catch up on next poll
                        log_message(self.session_id, "narrator", "Skipping poll - already narrating")
                        continue

                    # Build context from recent echo history
                    context = self._build_context_from_echo()

                    # Log what we're about to narrate
                    log_message(self.session_id, "narrator",
                               f"Narrating messages {self._last_narrated_index} to {current_length}",
                               metadata={"message_count": current_length - self._last_narrated_index})

                    # Update index BEFORE starting narration (so we don't re-narrate if it fails)
                    self._last_narrated_index = current_length

                    # Create a synthetic event for the narration system
                    from .events import Event
                    from datetime import datetime
                    synthetic_event = Event(
                        type="history_changed",
                        session_id=self.session_id,
                        timestamp=datetime.now().isoformat(),
                        data=context
                    )

                    pending = PendingNarration(
                        event=synthetic_event,
                        context=context,
                        received_at=time.time()
                    )

                    self._start_narration(pending)

            except Exception as e:
                log_message(self.session_id, "narrator_error",
                           f"Poll loop error: {type(e).__name__}: {e}")

    def _handle_event(self, event: Event):
        """Handle an incoming event."""
        log_message(self.session_id, "narrator",
                   f"Narrator received event: {event.type}",
                   metadata={"event_type": event.type, "session_id": event.session_id})

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
        from .runner import RVBBITRunner
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
            "cell_name": context.get("cell_name", "unknown"),
            "event_type": event_type_friendly,
            "context": context.get("summary", "No context available"),
            "cascade_complete": event.type == "cascade_complete",
            "turn_number": context.get("turn_number"),
            "max_turns": context.get("max_turns"),  # Include max_turns for progress tracking
            "tools_used": context.get("tools_used", []),
            # Include previous narrations for continuity
            "previous_narrations": list(self._narration_history),
            # Include original cascade input for template access (e.g., {{ input.original_input.initial_query }})
            "original_input": self.cascade_input,
        }

        # Use custom cascade if configured, otherwise use default
        cascade_dict = DEFAULT_NARRATOR_CASCADE.copy()

        # Override instructions if custom ones provided
        if self.config and self.config.instructions:
            cascade_dict["cells"][0]["instructions"] = self.config.instructions

        # Override model if specified
        if self.config and self.config.model:
            cascade_dict["cells"][0]["model"] = self.config.model

        try:
            # Create runner for narrator cascade (pass dict directly to config_path)
            # CRITICAL: Pass hooks captured from parent context (ContextVars don't work across threads)
            runner = RVBBITRunner(
                config_path=cascade_dict,
                session_id=narrator_session,
                parent_session_id=self.parent_session_id,
                depth=1,  # Mark as sub-cascade
                hooks=self._parent_hooks,  # Use hooks captured in __init__ (main thread)
            )

            # Run the narrator cascade
            result = runner.run(narrator_input)

            # Extract what was said and add to history for continuity
            spoken_text = self._extract_spoken_text(result)
            if spoken_text:
                self._add_to_history(event_type_friendly, spoken_text)

            # Check if say tool was called in UI mode (browser playback)
            # If so, emit narration_audio event with parent session_id so ResearchCockpit receives it
            audio_info = self._extract_audio_info(result)
            if audio_info:
                from .events import get_event_bus, Event
                from datetime import datetime

                event_bus = get_event_bus()
                event_bus.publish(Event(
                    type="narration_audio",
                    session_id=self.parent_session_id,  # Use PARENT session_id so ResearchCockpit receives it
                    timestamp=datetime.now().isoformat(),
                    data={
                        "audio_path": audio_info["audio_path"],
                        "text": audio_info["text"],
                        "duration_seconds": audio_info["duration_seconds"]
                    }
                ))
                log_message(self.session_id, "narrator",
                           f"Emitted narration_audio event to parent session {self.parent_session_id}",
                           metadata={"audio_path": audio_info["audio_path"]})

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

    def _build_context_from_echo(self) -> Dict[str, Any]:
        """Build context directly from echo.history (polling mode)."""
        if not self._echo:
            return {
                "cell_name": "unknown",
                "cascade_id": self.cascade_id,
                "summary": "No echo history available",
            }

        # Get recent history based on context_turns setting
        # This gives us the last N "conversation turns" of context
        total_messages = len(self._echo.history)

        # Start from context_turns "turns" ago, but at minimum show last 20 messages
        # A "turn" might have multiple messages (tool calls, results, etc)
        messages_to_show = max(20, self._context_turns * 4)  # Assume ~4 messages per turn
        start_idx = max(0, total_messages - messages_to_show)

        recent_entries = self._echo.history[start_idx:]

        # Build detailed summary from ALL messages (don't filter, show everything)
        summary_parts = []
        tools_used = []
        current_cell = "unknown"
        turn_number = None
        max_turns = None

        for entry in recent_entries:
            role = entry.get("role")
            content = entry.get("content", "")
            metadata = entry.get("metadata", {})

            # Extract cell/turn info from metadata
            if "cell_name" in metadata:
                current_cell = metadata["cell_name"]
            if "turn_number" in metadata:
                turn_number = metadata["turn_number"]
            if "max_turns" in metadata:
                max_turns = metadata["max_turns"]

            # Skip ONLY structural entries (they're just markers)
            if role == "structure":
                continue

            # Show ALL other message types with their full content
            if role == "system":
                # System messages (usually cell instructions)
                content_preview = str(content)[:150]
                summary_parts.append(f"📋 System: {content_preview}")

            elif role == "user":
                # User input or tool results
                content_str = str(content)
                if "Tool Result" in content_str:
                    # Tool result - show it with more detail
                    result_preview = content_str[:400]
                    summary_parts.append(f"📥 {result_preview}")
                else:
                    # Regular user input
                    content_preview = content_str[:300]
                    summary_parts.append(f"👤 User: {content_preview}")

            elif role == "assistant":
                # Assistant's response - show full content
                content_preview = str(content)[:400]
                summary_parts.append(f"🤖 Assistant: {content_preview}")

            elif role == "tool_call":
                # Tool being called
                tool_name = entry.get("tool_name", "unknown")
                args = entry.get("arguments", {})
                tools_used.append(tool_name)

                # Format args with more detail
                args_items = list(args.items())
                if len(args_items) <= 2:
                    # Show all args if there are only 1-2
                    args_str = ", ".join(f"{k}={repr(v)[:50]}" for k, v in args_items)
                else:
                    # Show first 2 args + count
                    args_str = ", ".join(f"{k}={repr(v)[:50]}" for k, v in args_items[:2])
                    args_str += f" ... (+{len(args_items)-2} more)"

                summary_parts.append(f"🔧 {tool_name}({args_str})")

        # Include ALL summary parts (don't limit) so narrator has full context
        summary_text = "\n".join(summary_parts) if summary_parts else "Working..."

        log_message(self.session_id, "narrator",
                   f"Built context from echo: {len(summary_parts)} messages, {len(summary_text)} chars",
                   metadata={"message_count": len(summary_parts), "char_count": len(summary_text)})

        return {
            "cell_name": current_cell,
            "cascade_id": self.cascade_id,
            "turn_number": turn_number,
            "max_turns": max_turns,
            "tools_used": list(set(tools_used)),  # Unique tools
            "summary": summary_text,
            "message_count": len(summary_parts),  # How many messages we're showing
        }

    def _build_context(self, event: Event) -> Dict[str, Any]:
        """Build context dictionary from event data."""
        data = event.data or {}

        # Build a human-readable summary from recent history
        summary_parts = []

        cell_name = data.get("cell_name", "unknown")

        if event.type == "cell_start":
            summary_parts.append(f"Starting cell '{cell_name}'")
        elif event.type == "cell_complete":
            summary_parts.append(f"Completed cell '{cell_name}'")
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

            # Format recent history into a readable narrative
            recent_history = data.get("recent_history", [])
            if recent_history:
                # Filter to show only relevant messages (assistant, tool results, user messages)
                for entry in recent_history[-5:]:  # Last 5 entries for brevity
                    role = entry.get("role")
                    content = entry.get("content", "")

                    if role == "assistant":
                        # Assistant's response
                        content_preview = str(content)[:200]
                        summary_parts.append(f"Assistant: {content_preview}")
                    elif role == "tool_call":
                        # Tool being called
                        tool_name = entry.get("tool_name", "unknown")
                        args = entry.get("arguments", {})
                        summary_parts.append(f"Calling tool '{tool_name}' with args: {str(args)[:100]}")
                    elif role in ("tool", "user") and "Tool Result" in str(content):
                        # Tool result
                        result_preview = str(content)[:200]
                        summary_parts.append(f"Tool result: {result_preview}")
            else:
                # Fallback to basic summary if no history provided
                summary_parts.append(f"Turn {turn}/{max_turns} in cell '{cell_name}'")
                if data.get("assistant_response"):
                    response = str(data["assistant_response"])[:200]
                    summary_parts.append(f"Assistant said: {response}")
                if data.get("tool_calls"):
                    tools = [tc.get("name", "unknown") for tc in data["tool_calls"][:3]]
                    summary_parts.append(f"Will use tools: {', '.join(tools)}")

        elif event.type == "tool_complete":
            tool_name = data.get("tool_name", "unknown")
            tool_result = data.get("tool_result", "")
            summary_parts.append(f"Tool '{tool_name}' completed")
            if tool_result:
                summary_parts.append(f"Result: {tool_result[:200]}")

        return {
            "cell_name": cell_name,
            "cascade_id": data.get("cascade_id", self.cascade_id),
            "turn_number": data.get("turn_number"),
            "max_turns": data.get("max_turns"),
            "tools_used": data.get("tool_calls", []),
            "summary": "\n".join(summary_parts) if summary_parts else f"Event: {event.type}",
            "raw_data": data,
        }

    def _extract_audio_info(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract audio playback info from say tool result (UI mode).

        Returns dict with audio_path, text, duration_seconds if UI mode, else None.
        """
        import json

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
            try:
                # Find JSON blocks
                import re
                json_matches = re.findall(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
                for json_str in json_matches:
                    try:
                        tool_call = json.loads(json_str)
                        if tool_call.get("tool") == "say":
                            text = tool_call.get("arguments", {}).get("text")
                            if text:
                                # Look for corresponding tool result with ui_mode_playback flag
                                for hist_entry in history:
                                    if hist_entry.get("role") in ("user", "tool"):
                                        hist_content = hist_entry.get("content", "")
                                        if "Tool Result (say)" in hist_content or "say" in hist_content:
                                            # Try to parse JSON from result
                                            try:
                                                # Extract JSON from content
                                                result_json_match = re.search(r'\{.*?"ui_mode_playback"\s*:\s*true.*?\}', hist_content, re.DOTALL)
                                                if result_json_match:
                                                    result_data = json.loads(result_json_match.group(0))
                                                    if result_data.get("ui_mode_playback"):
                                                        return {
                                                            "audio_path": result_data.get("audio", [None])[0],
                                                            "text": result_data.get("text_spoken", text),
                                                            "duration_seconds": result_data.get("duration_seconds", 0)
                                                        }
                                            except:
                                                continue
                    except json.JSONDecodeError:
                        continue
            except Exception:
                continue

        return None

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
    from .traits.tts import is_available
    return is_available()
