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
                                phase_name: str, message: str = None, cascade_id: str = None) -> dict:
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
                "cascade_id": cascade_id or self._current_cascade_id,
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
                                phase_name: str, message: str = None, cascade_id: str = None) -> dict:
        for hook in self.hooks:
            if hasattr(hook, 'on_checkpoint_suspended'):
                hook.on_checkpoint_suspended(session_id, checkpoint_id, checkpoint_type, phase_name, message, cascade_id)
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
        self._title_cache = {}  # Cache generated titles: {session_id: {"title": str, "checkpoint_count": int}}

    def _is_research_session(self, session_id: str) -> bool:
        """Check if this is a Research Cockpit session."""
        return session_id and session_id.startswith('research_')

    def _generate_session_title_async(self, session_id: str, checkpoints: list):
        """
        Generate an intelligent session title from checkpoint summaries.
        Uses a cheap model asynchronously to create a descriptive title.
        """
        import threading

        def generate():
            try:
                from .agent import Agent
                from .config import get_config
                from .db_adapter import get_db
                from .logs import log_message

                config = get_config()

                # Collect checkpoint summaries, phase_outputs, or responses
                checkpoint_texts = []
                for cp in checkpoints[:10]:  # Limit to first 10 checkpoints
                    # Prefer summary, fall back to phase_output, then response
                    text = cp.get('summary') or cp.get('phase_output') or ''

                    # If no text, try response
                    if not text and cp.get('response'):
                        response = cp.get('response')
                        if isinstance(response, dict):
                            text = response.get('text') or response.get('message') or response.get('input') or ''
                        elif isinstance(response, str):
                            text = response

                    if text and len(str(text).strip()) > 5:
                        checkpoint_texts.append(str(text)[:200])  # Truncate long texts

                if not checkpoint_texts:
                    print(f"[ResearchAutoSave] No checkpoint texts found for title generation")
                    return  # No content to generate title from

                print(f"[ResearchAutoSave] Generating title from {len(checkpoint_texts)} checkpoint texts")

                # Build context from checkpoint texts
                context = "\n".join([f"- {t}" for t in checkpoint_texts])

                # Create agent with cheap model
                agent = Agent(
                    model="google/gemini-2.5-flash-lite",
                    system_prompt="",
                    base_url=config.provider_base_url,
                    api_key=config.provider_api_key
                )

                # Generate title
                prompt = f"""Create a SHORT title (max 8 words) for this research session based on these checkpoint summaries:

{context}

The title should capture what the session is about. Be specific, not generic.
Return ONLY the title, nothing else."""

                response = agent.run(input_message=prompt)
                title = response.get("content", "").strip()

                # Clean up title (remove quotes if present)
                title = title.strip('"\'')

                if not title or len(title) < 3:
                    return  # Invalid title

                # Truncate if too long
                if len(title) > 100:
                    title = title[:97] + "..."

                # Log the LLM call
                log_message(
                    session_id=session_id,
                    cascade_id="session_title",
                    phase_name="title_generation",
                    role="assistant",
                    content=title,
                    model=response.get("model", "google/gemini-2.5-flash-lite"),
                    cost=response.get("cost", 0),
                    tokens_in=response.get("tokens_in", 0),
                    tokens_out=response.get("tokens_out", 0)
                )

                # Update the session title in database
                db = get_db()
                research_id = f"research_session_{session_id}"

                # Escape single quotes for SQL
                safe_title = title.replace("'", "''")

                # Update title in database
                # For ClickHouse: use ALTER TABLE UPDATE
                # For chDB: delete and re-insert (handled by caching + next save cycle)
                if hasattr(config, 'use_clickhouse_server') and config.use_clickhouse_server:
                    try:
                        db.execute(f"""
                            ALTER TABLE research_sessions UPDATE
                                title = '{safe_title}'
                            WHERE original_session_id = '{session_id}'
                        """)
                    except Exception as update_err:
                        print(f"[ResearchAutoSave] ⚠ ALTER UPDATE failed (will use cache): {update_err}")
                # Title is cached and will be used on next _save_or_update_session call

                # Cache the title with checkpoint count
                self._title_cache[session_id] = {
                    "title": title,
                    "checkpoint_count": len(checkpoints)
                }
                print(f"[ResearchAutoSave] ✨ Generated title for {session_id}: {title}")

            except Exception as e:
                print(f"[ResearchAutoSave] ⚠ Failed to generate title for {session_id}: {e}")
                import traceback
                traceback.print_exc()

        # Run in background thread
        thread = threading.Thread(target=generate, daemon=True)
        thread.start()

    def _get_smart_title(self, session_id: str, checkpoints: list) -> str:
        """
        Get a smart title for the session.
        Returns cached title if available, regenerates when checkpoint count increases.
        """
        current_count = len(checkpoints) if checkpoints else 0
        cached = self._title_cache.get(session_id)

        # Check if we have a valid cached title
        if cached:
            cached_title = cached.get("title", "")
            cached_count = cached.get("checkpoint_count", 0)

            # Regenerate if checkpoint count increased significantly (every 2 new checkpoints)
            should_regenerate = current_count > 0 and (current_count - cached_count) >= 2

            if should_regenerate:
                print(f"[ResearchAutoSave] Regenerating title: {cached_count} -> {current_count} checkpoints")
                self._generate_session_title_async(session_id, checkpoints)

            # Return cached title while regeneration happens in background
            if cached_title:
                return cached_title

        # Build fallback title from checkpoints
        if checkpoints and len(checkpoints) > 0:
            # Try to use first checkpoint's summary, phase_output, or response
            first_cp = checkpoints[0]
            first_text = first_cp.get('summary') or first_cp.get('phase_output') or ''

            # If no phase_output, try to use the user's response from the checkpoint
            if not first_text and first_cp.get('response'):
                response = first_cp.get('response')
                if isinstance(response, dict):
                    # Try to get text from common response fields
                    first_text = response.get('text') or response.get('message') or response.get('input') or str(response)[:100]
                elif isinstance(response, str):
                    first_text = response

            if first_text and len(first_text.strip()) > 5:
                # Clean up the text for title use
                fallback = first_text.strip()[:80]
                if len(first_text.strip()) > 80:
                    fallback += "..."
                print(f"[ResearchAutoSave] Using fallback title from checkpoint: {fallback[:50]}...")
            else:
                fallback = f"Research Session - {session_id[:12]}"
                print(f"[ResearchAutoSave] No checkpoint text found, using default title")

            # Trigger initial title generation
            self._generate_session_title_async(session_id, checkpoints)

            return fallback

        print(f"[ResearchAutoSave] No checkpoints yet, using default title")
        return f"Research Session - {session_id[:12]}"

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

            # Get cascade_id from entries if not provided or is None/unknown
            if (cascade_id is None or cascade_id == "unknown") and entries:
                cascade_id = entries[0].get('cascade_id') or 'unknown'
                print(f"[ResearchAutoSave] Detected cascade_id from entries: {cascade_id}")

            # Ensure cascade_id is never None (ClickHouse String columns don't accept None)
            if cascade_id is None:
                cascade_id = "unknown"

            checkpoints = _fetch_checkpoints_for_session(session_id)
            metrics = _compute_session_metrics(entries)
            mermaid = _fetch_mermaid_graph(session_id) or ""  # Ensure not None

            print(f"[ResearchAutoSave] Fetched data for {session_id}: {len(entries)} entries, {len(checkpoints)} checkpoints")

            # Get smart title (uses LLM to generate from checkpoint summaries)
            title = self._get_smart_title(session_id, checkpoints) or f"Research Session - {session_id[:12]}"
            description = f"Research session with {len(checkpoints)} interactions" if checkpoints else "Auto-saved research session"

            # Ensure all string fields have defaults (ClickHouse String columns don't accept None)
            title = title or f"Research Session - {session_id[:12]}"
            description = description or "Auto-saved research session"

            # Check if session already exists
            research_id = f"research_session_{session_id}"

            # Use unified db adapter
            now = datetime.utcnow()
            first_entry = entries[0] if entries else {}
            created_at = first_entry.get('timestamp') or now
            # Ensure created_at is a datetime
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except:
                    created_at = now

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
                                phase_name: str, message: str = None, cascade_id: str = None) -> dict:
        """Called when cascade is suspended waiting for checkpoint response."""
        if self._is_research_session(session_id):
            print(f"[ResearchAutoSave] Updating session {session_id} after checkpoint created (cascade_id={cascade_id})")
            # Update in background to capture the checkpoint
            import threading
            thread = threading.Thread(
                target=self._save_or_update_session,
                args=(session_id, cascade_id or "unknown", "active")  # Use cascade_id from checkpoint
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
