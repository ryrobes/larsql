"""
Event Publishing Hooks - Publishes lifecycle events to the event bus

Enhanced to include sounding/turn context for proper UI rendering.
"""
from datetime import datetime
from typing import Any
from .runner import WindlassHooks, HookAction
from .events import get_event_bus, Event

class EventPublishingHooks(WindlassHooks):
    """
    Hooks implementation that publishes all lifecycle events to the event bus.
    Can be used standalone or combined with other hooks via CompositeHooks.

    Tracks sounding and turn context for proper phase bar visualization.
    """

    def __init__(self):
        self.bus = get_event_bus()
        # Track current context for events that don't receive full context
        self._current_sounding_index = None
        self._current_turn_number = None
        self._current_cascade_id = None

    def _get_echo_context(self, context: dict) -> dict:
        """Extract useful context from echo if available."""
        echo = context.get("echo")
        if not echo:
            return {}

        return {
            "cascade_id": getattr(echo, "_cascade_id", None) or self._current_cascade_id,
        }

    def on_cascade_start(self, cascade_id: str, session_id: str, context: dict) -> dict:
        self._current_cascade_id = cascade_id
        self._current_sounding_index = context.get("sounding_index")

        self.bus.publish(Event(
            type="cascade_start",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "cascade_id": cascade_id,
                "depth": context.get("depth", 0),
                "parent_session_id": context.get("parent_session_id"),
                "sounding_index": context.get("sounding_index"),
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_cascade_complete(self, cascade_id: str, session_id: str, result: dict) -> dict:
        self.bus.publish(Event(
            type="cascade_complete",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "cascade_id": cascade_id,
                "result": result,
                "sounding_index": self._current_sounding_index,
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_cascade_error(self, cascade_id: str, session_id: str, error: Exception) -> dict:
        self.bus.publish(Event(
            type="cascade_error",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "cascade_id": cascade_id,
                "error": str(error),
                "error_type": type(error).__name__,
                "sounding_index": self._current_sounding_index,
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_phase_start(self, phase_name: str, context: dict) -> dict:
        echo = context.get("echo")
        session_id = echo.session_id if echo else "unknown"

        # Extract sounding context if available
        sounding_index = context.get("sounding_index") or self._current_sounding_index
        if sounding_index is not None:
            self._current_sounding_index = sounding_index

        self.bus.publish(Event(
            type="phase_start",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "phase_name": phase_name,
                "cascade_id": self._current_cascade_id,
                "sounding_index": sounding_index,
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_phase_complete(self, phase_name: str, session_id: str, result: dict) -> dict:
        # Extract is_winner from result if available
        is_winner = result.get("is_winner") if isinstance(result, dict) else None

        self.bus.publish(Event(
            type="phase_complete",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "phase_name": phase_name,
                "result": result,
                "cascade_id": self._current_cascade_id,
                "sounding_index": self._current_sounding_index,
                "is_winner": is_winner,
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_turn_start(self, phase_name: str, turn_index: int, context: dict) -> dict:
        echo = context.get("echo")
        session_id = echo.session_id if echo else "unknown"

        # Track turn number
        self._current_turn_number = turn_index

        # Extract sounding context
        sounding_index = context.get("sounding_index") or self._current_sounding_index

        self.bus.publish(Event(
            type="turn_start",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "phase_name": phase_name,
                "turn_number": turn_index,  # Use turn_number for consistency
                "turn_index": turn_index,   # Keep for backward compat
                "cascade_id": self._current_cascade_id,
                "sounding_index": sounding_index,
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_tool_call(self, tool_name: str, phase_name: str, session_id: str, args: dict) -> dict:
        self.bus.publish(Event(
            type="tool_call",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "tool_name": tool_name,
                "phase_name": phase_name,
                "args": args,
                "cascade_id": self._current_cascade_id,
                "sounding_index": self._current_sounding_index,
                "turn_number": self._current_turn_number,
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_tool_result(self, tool_name: str, phase_name: str, session_id: str, result: Any) -> dict:
        # Sanitize result for JSON serialization
        result_str = str(result)[:500]  # Truncate large results

        self.bus.publish(Event(
            type="tool_result",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "tool_name": tool_name,
                "phase_name": phase_name,
                "result_preview": result_str,
                "result": result_str,  # Also include as 'result' for consistency
                "cascade_id": self._current_cascade_id,
                "sounding_index": self._current_sounding_index,
                "turn_number": self._current_turn_number,
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_checkpoint_suspended(self, session_id: str, checkpoint_id: str, checkpoint_type: str,
                                phase_name: str, message: str = None) -> dict:
        """Called when cascade is suspended waiting for human input."""
        self.bus.publish(Event(
            type="checkpoint_suspended",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "checkpoint_id": checkpoint_id,
                "checkpoint_type": checkpoint_type,
                "phase_name": phase_name,
                "message": message,
                "cascade_id": self._current_cascade_id,
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_checkpoint_resumed(self, session_id: str, checkpoint_id: str, phase_name: str,
                              response: Any = None, cascade_id: str = None) -> dict:
        """Called when a checkpoint is resumed with human input."""
        # Use provided cascade_id or fall back to tracked one
        effective_cascade_id = cascade_id or self._current_cascade_id
        self.bus.publish(Event(
            type="checkpoint_resumed",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "checkpoint_id": checkpoint_id,
                "phase_name": phase_name,
                "response": str(response)[:500] if response else None,  # Truncate for safety
                "cascade_id": effective_cascade_id,
            }
        ))
        return {"action": HookAction.CONTINUE}


class CompositeHooks(WindlassHooks):
    """
    Combines multiple hook implementations.
    Calls all hooks in sequence.
    """

    def __init__(self, *hooks: WindlassHooks):
        self.hooks = hooks

    def on_cascade_start(self, cascade_id: str, session_id: str, context: dict) -> dict:
        for hook in self.hooks:
            hook.on_cascade_start(cascade_id, session_id, context)
        return {"action": HookAction.CONTINUE}

    def on_cascade_complete(self, cascade_id: str, session_id: str, result: dict) -> dict:
        for hook in self.hooks:
            hook.on_cascade_complete(cascade_id, session_id, result)
        return {"action": HookAction.CONTINUE}

    def on_cascade_error(self, cascade_id: str, session_id: str, error: Exception) -> dict:
        for hook in self.hooks:
            hook.on_cascade_error(cascade_id, session_id, error)
        return {"action": HookAction.CONTINUE}

    def on_phase_start(self, phase_name: str, context: dict) -> dict:
        for hook in self.hooks:
            hook.on_phase_start(phase_name, context)
        return {"action": HookAction.CONTINUE}

    def on_phase_complete(self, phase_name: str, session_id: str, result: dict) -> dict:
        for hook in self.hooks:
            hook.on_phase_complete(phase_name, session_id, result)
        return {"action": HookAction.CONTINUE}

    def on_turn_start(self, phase_name: str, turn_index: int, context: dict) -> dict:
        for hook in self.hooks:
            hook.on_turn_start(phase_name, turn_index, context)
        return {"action": HookAction.CONTINUE}

    def on_tool_call(self, tool_name: str, phase_name: str, session_id: str, args: dict) -> dict:
        for hook in self.hooks:
            hook.on_tool_call(tool_name, phase_name, session_id, args)
        return {"action": HookAction.CONTINUE}

    def on_tool_result(self, tool_name: str, phase_name: str, session_id: str, result: Any) -> dict:
        for hook in self.hooks:
            hook.on_tool_result(tool_name, phase_name, session_id, result)
        return {"action": HookAction.CONTINUE}

    def on_checkpoint_suspended(self, session_id: str, checkpoint_id: str, checkpoint_type: str,
                                phase_name: str, message: str = None) -> dict:
        for hook in self.hooks:
            if hasattr(hook, 'on_checkpoint_suspended'):
                hook.on_checkpoint_suspended(session_id, checkpoint_id, checkpoint_type, phase_name, message)
        return {"action": HookAction.CONTINUE}

    def on_checkpoint_resumed(self, session_id: str, checkpoint_id: str, phase_name: str,
                              response: Any = None, cascade_id: str = None) -> dict:
        for hook in self.hooks:
            if hasattr(hook, 'on_checkpoint_resumed'):
                hook.on_checkpoint_resumed(session_id, checkpoint_id, phase_name, response, cascade_id)
        return {"action": HookAction.CONTINUE}
