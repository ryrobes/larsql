"""
Event Publishing Hooks - Publishes lifecycle events to the event bus
"""
from datetime import datetime
from typing import Any
from .runner import WindlassHooks, HookAction
from .events import get_event_bus, Event

class EventPublishingHooks(WindlassHooks):
    """
    Hooks implementation that publishes all lifecycle events to the event bus.
    Can be used standalone or combined with other hooks via CompositeHooks.
    """

    def __init__(self):
        self.bus = get_event_bus()

    def on_cascade_start(self, cascade_id: str, session_id: str, context: dict) -> dict:
        self.bus.publish(Event(
            type="cascade_start",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "cascade_id": cascade_id,
                "depth": context.get("depth", 0),
                "parent_session_id": context.get("parent_session_id")
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
                "result": result
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
                "error_type": type(error).__name__
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_phase_start(self, phase_name: str, context: dict) -> dict:
        session_id = context.get("echo").session_id if context.get("echo") else "unknown"
        self.bus.publish(Event(
            type="phase_start",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "phase_name": phase_name
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_phase_complete(self, phase_name: str, session_id: str, result: dict) -> dict:
        self.bus.publish(Event(
            type="phase_complete",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "phase_name": phase_name,
                "result": result
            }
        ))
        return {"action": HookAction.CONTINUE}

    def on_turn_start(self, phase_name: str, turn_index: int, context: dict) -> dict:
        session_id = context.get("echo").session_id if context.get("echo") else "unknown"
        self.bus.publish(Event(
            type="turn_start",
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            data={
                "phase_name": phase_name,
                "turn_index": turn_index
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
                "args": args
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
                "result_preview": result_str
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
