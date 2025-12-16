"""
Event Publishing Hooks - Publishes lifecycle events to the event bus

Enhanced to include sounding/turn context for proper UI rendering.
Includes auto-save for Research Cockpit sessions.
"""
from datetime import datetime
from typing import Any
from .runner import WindlassHooks, HookAction
from .events import get_event_bus, Event
import os
import json

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


class ResearchSessionAutoSaveHooks(WindlassHooks):
    """
    Auto-saves Research Cockpit sessions to research_sessions table.

    Triggers:
    - on_cascade_start: Create initial record (status="active")
    - on_checkpoint_resumed: Update with latest interaction
    - on_cascade_complete: Finalize (status="completed")

    Only saves sessions with session_id starting with "research_"
    """

    def __init__(self):
        self._auto_save_enabled = os.environ.get('WINDLASS_AUTO_SAVE_RESEARCH', 'true').lower() == 'true'

    def _is_research_session(self, session_id: str) -> bool:
        """Check if this is a Research Cockpit session."""
        return session_id and session_id.startswith('research_')

    def _save_or_update_session(self, session_id: str, cascade_id: str, status: str = "active", parent_session_id: str = None, branch_checkpoint_id: str = None):
        """Save or update research session in database."""
        if not self._auto_save_enabled:
            return

        try:
            from .eddies.research_sessions import _fetch_session_entries, _compute_session_metrics, _fetch_mermaid_graph, _fetch_checkpoints_for_session
            from .config import get_config
            from .db_adapter import get_db
            from uuid import uuid4
            from .echo import get_echo

            cfg = get_config()
            db = get_db()

            # Try to get Echo to extract parent info if not provided
            if not parent_session_id:
                try:
                    echo = get_echo(session_id)
                    if echo and hasattr(echo, 'parent_session_id'):
                        parent_session_id = echo.parent_session_id
                        print(f"[ResearchAutoSave] Detected parent from Echo: {parent_session_id}")
                except:
                    pass

            # Fetch session data
            entries = _fetch_session_entries(session_id)
            if not entries:
                print(f"[ResearchAutoSave] No entries yet for {session_id}, skipping")
                return

            # Get cascade_id from entries if not provided
            if cascade_id == "unknown" and entries:
                cascade_id = entries[0].get('cascade_id', 'unknown')
                print(f"[ResearchAutoSave] Detected cascade_id from entries: {cascade_id}")

            checkpoints = _fetch_checkpoints_for_session(session_id)
            metrics = _compute_session_metrics(entries)
            mermaid = _fetch_mermaid_graph(session_id)

            print(f"[ResearchAutoSave] Fetched data for {session_id}: {len(entries)} entries, {len(checkpoints)} checkpoints")

            # Auto-generate title from first checkpoint
            title = f"Research Session - {session_id[:12]}"
            description = f"Auto-saved research session"

            if checkpoints and len(checkpoints) > 0:
                first_question = checkpoints[0].get('phase_output', '')
                if first_question:
                    title = first_question[:80] + ("..." if len(first_question) > 80 else "")
                description = f"Research session with {len(checkpoints)} interactions"

            # Check if session already exists
            research_id = f"research_session_{session_id}"

            # Use unified db adapter
            now = datetime.utcnow()
            first_entry = entries[0] if entries else {}
            created_at = first_entry.get('timestamp', now)

            # Check if exists
            existing_result = db.query(f"SELECT id FROM research_sessions WHERE original_session_id = '{session_id}' LIMIT 1")
            existing = list(existing_result) if existing_result else []

            if existing:
                # Update existing - use simple UPDATE (ALTER TABLE is ClickHouse-specific)
                try:
                    # Delete old record and insert new one (safer than ALTER TABLE)
                    db.execute(f"DELETE FROM research_sessions WHERE original_session_id = '{session_id}'")

                    db.insert_rows('research_sessions', [{
                        'id': research_id,
                        'original_session_id': session_id,
                        'cascade_id': cascade_id,
                        'title': title,
                        'description': description,
                        'created_at': created_at,
                        'frozen_at': now,
                        'status': status,
                        'context_snapshot': json.dumps({}),
                        'checkpoints_data': json.dumps(checkpoints, default=str),
                        'entries_snapshot': json.dumps(entries, default=str),
                        'mermaid_graph': mermaid,
                        'screenshots': json.dumps([]),
                        'total_cost': metrics['total_cost'],
                        'total_turns': metrics['total_turns'],
                        'total_input_tokens': metrics['total_input_tokens'],
                        'total_output_tokens': metrics['total_output_tokens'],
                        'duration_seconds': metrics['duration_seconds'],
                        'phases_visited': json.dumps(metrics['phases_visited']),
                        'tools_used': json.dumps(metrics['tools_used']),
                        'tags': json.dumps([]),
                        'parent_session_id': parent_session_id,  # Capture parent!
                        'branch_point_checkpoint_id': branch_checkpoint_id,  # Capture branch point!
                        'updated_at': now
                    }])
                    print(f"[ResearchAutoSave] ✓ Updated session {session_id} (status={status})")
                except Exception as e:
                    print(f"[ResearchAutoSave] ⚠ Update failed, trying insert: {e}")

            else:
                # Insert new
                db.insert_rows('research_sessions', [{
                    'id': research_id,
                    'original_session_id': session_id,
                    'cascade_id': cascade_id,
                    'title': title,
                    'description': description,
                    'created_at': created_at,
                    'frozen_at': now,
                    'status': status,
                    'context_snapshot': json.dumps({}),
                    'checkpoints_data': json.dumps(checkpoints, default=str),
                    'entries_snapshot': json.dumps(entries, default=str),
                    'mermaid_graph': mermaid,
                    'screenshots': json.dumps([]),
                    'total_cost': metrics['total_cost'],
                    'total_turns': metrics['total_turns'],
                    'total_input_tokens': metrics['total_input_tokens'],
                    'total_output_tokens': metrics['total_output_tokens'],
                    'duration_seconds': metrics['duration_seconds'],
                    'phases_visited': json.dumps(metrics['phases_visited']),
                    'tools_used': json.dumps(metrics['tools_used']),
                    'tags': json.dumps([]),
                    'parent_session_id': parent_session_id,  # Capture parent!
                    'branch_point_checkpoint_id': branch_checkpoint_id,  # Capture branch point!
                    'updated_at': now
                }])

                if parent_session_id:
                    print(f"[ResearchAutoSave] ✓ Created BRANCH session {session_id} from parent {parent_session_id} (status={status})")
                else:
                    print(f"[ResearchAutoSave] ✓ Created session {session_id} (status={status})")

        except Exception as e:
            print(f"[ResearchAutoSave] ⚠ Failed to save session {session_id}: {e}")
            import traceback
            traceback.print_exc()

    def on_cascade_start(self, cascade_id: str, session_id: str, context: dict) -> dict:
        if self._is_research_session(session_id):
            print(f"[ResearchAutoSave] Creating initial record for {session_id}")
            # Create initial record in background (don't block cascade start)
            import threading
            thread = threading.Thread(
                target=self._save_or_update_session,
                args=(session_id, cascade_id, "active")
            )
            thread.daemon = True
            thread.start()

        return {"action": HookAction.CONTINUE}

    def on_checkpoint_suspended(self, session_id: str, checkpoint_id: str, checkpoint_type: str,
                                phase_name: str, message: str = None) -> dict:
        """Called when cascade is suspended waiting for checkpoint response."""
        if self._is_research_session(session_id):
            print(f"[ResearchAutoSave] Updating session {session_id} after checkpoint created")
            # Update in background to capture the checkpoint
            import threading
            thread = threading.Thread(
                target=self._save_or_update_session,
                args=(session_id, "unknown", "active")  # Will detect cascade_id from entries
            )
            thread.daemon = True
            thread.start()

        return {"action": HookAction.CONTINUE}

    def on_checkpoint_resumed(self, session_id: str, checkpoint_id: str, phase_name: str,
                              response: Any = None, cascade_id: str = None) -> dict:
        if self._is_research_session(session_id):
            print(f"[ResearchAutoSave] Updating session {session_id} after checkpoint response")
            # Update in background
            import threading
            thread = threading.Thread(
                target=self._save_or_update_session,
                args=(session_id, cascade_id or "unknown", "active")
            )
            thread.daemon = True
            thread.start()

        return {"action": HookAction.CONTINUE}

    def on_cascade_complete(self, cascade_id: str, session_id: str, result: dict) -> dict:
        if self._is_research_session(session_id):
            print(f"[ResearchAutoSave] Finalizing session {session_id}")
            # Finalize in background
            import threading
            thread = threading.Thread(
                target=self._save_or_update_session,
                args=(session_id, cascade_id, "completed")
            )
            thread.daemon = True
            thread.start()

        return {"action": HookAction.CONTINUE}
