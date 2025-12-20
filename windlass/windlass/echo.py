import json
from typing import Any, Dict, List, Optional, Callable

class Echo:
    """
    Represents the state/history of a Cascade (session).

    The history entries contain rich metadata for visualization:
    - trace_id: Unique ID for this entry
    - parent_id: Parent trace ID for tree structure
    - node_type: cascade, phase, turn, tool, soundings, reforge, etc.
    - metadata: Dict with additional context (phase_name, sounding_index, etc.)
    """
    def __init__(self, session_id: str, initial_state: Dict[str, Any] = None, parent_session_id: str = None):
        self.session_id = session_id
        self.parent_session_id = parent_session_id
        self.state = initial_state or {}
        self.history: List[Dict[str, Any]] = []
        self.lineage: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []  # Track errors that occurred
        # Execution context for visualization
        self._current_cascade_id: Optional[str] = None
        self._current_phase_name: Optional[str] = None
        # Mermaid continuity - cache last successful generation to ensure every message has a chart
        self._last_mermaid_content: Optional[str] = None
        self._mermaid_failure_count: int = 0  # Track failures to avoid log spam
        # Memory callback for saving messages
        self._message_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    def set_cascade_context(self, cascade_id: str):
        """Set the current cascade context for metadata enrichment."""
        self._current_cascade_id = cascade_id

    def set_phase_context(self, phase_name: str):
        """Set the current phase context for metadata enrichment."""
        self._current_phase_name = phase_name

    def set_message_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set a callback to be called for each message added to history."""
        self._message_callback = callback

    def _should_generate_context_card(self, node_type: str, role: Optional[str]) -> bool:
        """
        Determine if a message should get a context card.

        Context cards are generated for substantive messages that would be
        useful for context selection. We skip system messages, framework
        internal messages, and structural entries.

        Args:
            node_type: Type of the message node
            role: Message role (user, assistant, tool, system)

        Returns:
            True if a context card should be generated
        """
        # Skip system messages
        if role == "system":
            return False

        # Skip structural/lifecycle entries
        if node_type in ("context_injection", "context_selection", "lifecycle",
                         "cascade", "phase", "turn", "structure"):
            return False

        # Skip validation infrastructure
        if node_type in ("validation_start", "validation_error"):
            return False

        # Generate for substantive content
        return node_type in ("agent", "tool", "tool_result", "tool_call",
                             "user", "message", "turn_input", "evaluator",
                             "sounding_attempt")

    def update_state(self, key: str, value: Any):
        self.state[key] = value

    def add_history(self, entry: Dict[str, Any], trace_id: str = None, parent_id: str = None,
                   node_type: str = "msg", metadata: Dict[str, Any] = None, skip_unified_log: bool = False):
        """
        Add an entry to the history with full metadata for visualization.

        Args:
            entry: The base entry dict (role, content, etc.)
            trace_id: Unique trace ID for this entry
            parent_id: Parent trace ID for tree structure
            node_type: Type of node (cascade, phase, turn, tool, etc.)
            metadata: Additional metadata dict (sounding_index, is_winner, phase_name, etc.)
            skip_unified_log: If True, skip automatic logging to unified_logs (caller already logged)
        """
        # CRITICAL: Create a COPY of the entry dict to avoid mutating the original
        # The caller may reuse the same dict (e.g., appending to context_messages)
        # If we mutate it, trace_id/metadata fields will pollute the LLM API messages!
        enriched_entry = entry.copy()

        enriched_entry["trace_id"] = trace_id
        enriched_entry["parent_id"] = parent_id
        enriched_entry["node_type"] = node_type

        # Build metadata with context
        meta = metadata or {}
        if self._current_cascade_id:
            meta.setdefault("cascade_id", self._current_cascade_id)
        if self._current_phase_name:
            meta.setdefault("phase_name", self._current_phase_name)

        enriched_entry["metadata"] = meta
        self.history.append(enriched_entry)

        # Skip unified logging if caller already logged (e.g., agent responses with full LLM data)
        if skip_unified_log:
            return

        # Also log to unified logging system automatically
        try:
            # Lazy import to avoid circular dependency
            from .unified_logs import log_unified
            from .echo_enrichment import detect_base64_in_content, extract_image_paths_from_tool_result, extract_audio_paths_from_tool_result
            from .visualizer import generate_state_diagram_string

            # Extract data from entry
            role = entry.get("role")
            content = entry.get("content")
            tool_calls = entry.get("tool_calls")

            # Detect images
            has_base64 = detect_base64_in_content(content) if content else False
            images = extract_image_paths_from_tool_result(content) if isinstance(content, dict) else None

            # Detect audio
            audio = extract_audio_paths_from_tool_result(content) if isinstance(content, dict) else None

            # Extract enrichment data from metadata
            sounding_index = meta.get("sounding_index")
            is_winner = meta.get("is_winner")
            reforge_step = meta.get("reforge_step")
            phase_name = meta.get("phase_name")
            cascade_id = meta.get("cascade_id")
            model = meta.get("model")  # Extract model from metadata
            mutation_applied = meta.get("mutation_applied")  # Extract mutation for soundings
            mutation_type = meta.get("mutation_type")  # 'augment', 'rewrite', or None
            mutation_template = meta.get("mutation_template")  # For rewrite: the instruction used

            # Semantic classification (human-readable roles for debugging)
            semantic_actor = meta.get("semantic_actor")    # WHO: main_agent, evaluator, validator, etc.
            semantic_purpose = meta.get("semantic_purpose") # WHAT: instructions, tool_response, etc.

            # Callouts (semantic message tagging)
            is_callout = meta.get("is_callout", False)
            callout_name = meta.get("callout_name")

            # Species hash (prompt DNA for evolution tracking)
            species_hash = meta.get("species_hash")

            # Generate mermaid diagram content (includes the newly added entry)
            # CRITICAL: Maintain continuity - never log NULL mermaid if we have a previous good one
            # The mermaid chart is monotonically growing, so previous state is always a valid subset
            mermaid_content = self._last_mermaid_content  # Start with cached value as fallback
            try:
                new_mermaid = generate_state_diagram_string(self)
                # Only update cache if we got valid content
                if new_mermaid and new_mermaid.strip() and len(new_mermaid) > 10:
                    self._last_mermaid_content = new_mermaid
                    mermaid_content = new_mermaid
                    # Reset failure count on success
                    if self._mermaid_failure_count > 0:
                        self._mermaid_failure_count = 0
            except Exception as mermaid_error:
                # Don't fail logging, but track failures for debugging
                self._mermaid_failure_count += 1
                # Log first failure and then every 10th to avoid spam
                if self._mermaid_failure_count == 1 or self._mermaid_failure_count % 10 == 0:
                    print(f"[Mermaid] Generation failed (using cached, failure #{self._mermaid_failure_count}): {type(mermaid_error).__name__}: {str(mermaid_error)[:100]}")
                # mermaid_content already set to cached value above

            # Log to unified system
            log_unified(
                session_id=self.session_id,
                parent_session_id=self.parent_session_id,
                trace_id=trace_id,
                parent_id=parent_id,
                node_type=node_type,
                role=role,
                semantic_actor=semantic_actor,    # WHO: main_agent, evaluator, validator, etc.
                semantic_purpose=semantic_purpose, # WHAT: instructions, tool_response, etc.
                content=content,  # Full content (NOT stringified!)
                tool_calls=tool_calls,
                metadata=meta,
                sounding_index=sounding_index,
                is_winner=is_winner,
                reforge_step=reforge_step,
                phase_name=phase_name,
                cascade_id=cascade_id,
                model=model,  # Pass model
                images=images,
                has_base64=has_base64,
                audio=audio,
                mermaid_content=mermaid_content,
                mutation_applied=mutation_applied,  # Pass mutation for soundings
                mutation_type=mutation_type,
                mutation_template=mutation_template,
                is_callout=is_callout,  # Pass callout info
                callout_name=callout_name,
                species_hash=species_hash,  # Pass species hash for prompt evolution tracking
            )

            # Emit SSE events for sounding-related entries so LiveStore can receive real-time data
            # This is critical for real-time UI updates during cascade execution
            if node_type == "sounding_attempt" and sounding_index is not None:
                try:
                    from .events import get_event_bus, Event
                    from datetime import datetime
                    bus = get_event_bus()
                    bus.publish(Event(
                        type="sounding_attempt",
                        session_id=self.session_id,
                        timestamp=datetime.now().isoformat(),
                        data={
                            "trace_id": trace_id,
                            "parent_id": parent_id,
                            "phase_name": phase_name,
                            "cascade_id": cascade_id,
                            "sounding_index": sounding_index,
                            "is_winner": is_winner,
                            "reforge_step": reforge_step,
                            "content": str(content)[:500] if content else None,
                            "model": model,
                        }
                    ))
                except Exception:
                    pass  # Don't fail if event emission has issues

            # Also emit evaluator entries for real-time eval reasoning display
            if node_type == "evaluator":
                try:
                    from .events import get_event_bus, Event
                    from datetime import datetime
                    bus = get_event_bus()
                    bus.publish(Event(
                        type="evaluator",
                        session_id=self.session_id,
                        timestamp=datetime.now().isoformat(),
                        data={
                            "trace_id": trace_id,
                            "parent_id": parent_id,
                            "phase_name": phase_name,
                            "cascade_id": cascade_id,
                            "reforge_step": reforge_step,
                            "content": str(content)[:1000] if content else None,
                            "model": model,
                        }
                    ))
                except Exception:
                    pass  # Don't fail if event emission has issues

            # Queue context card generation for auto-context system
            # Only for substantive messages that would be useful for context selection
            if self._should_generate_context_card(node_type, role):
                try:
                    from .context_cards import queue_context_card
                    from .unified_logs import compute_content_hash
                    from datetime import datetime

                    content_hash = compute_content_hash(role, content)

                    queue_context_card(
                        session_id=self.session_id,
                        content_hash=content_hash,
                        role=role or "",
                        content=content,
                        phase_name=phase_name,
                        cascade_id=cascade_id,
                        turn_number=meta.get("turn_number"),
                        is_callout=is_callout,
                        callout_name=callout_name,
                        message_timestamp=datetime.now()
                    )
                except Exception:
                    pass  # Don't fail if context card generation has issues

        except Exception as e:
            # Don't fail if logging has issues
            pass  # Silently ignore to avoid spam

        # Call message callback if set (for memory saving, etc.)
        if self._message_callback:
            try:
                self._message_callback(entry)
            except Exception as e:
                # Don't fail if callback has issues
                pass

    def add_lineage(self, phase: str, output: Any, trace_id: str = None):
        self.lineage.append({
            "phase": phase,
            "output": output,
            "trace_id": trace_id
        })

    def add_error(self, phase: str, error_type: str, error_message: str, metadata: Dict[str, Any] = None):
        """Track that an error occurred during execution."""
        self.errors.append({
            "phase": phase,
            "error_type": error_type,
            "error_message": error_message,
            "metadata": metadata or {}
        })

    def get_full_echo(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "history": self.history,
            "lineage": self.lineage,
            "errors": self.errors,
            "has_errors": len(self.errors) > 0,
            "status": "failed" if len(self.errors) > 0 else "success"
        }

    def merge(self, other_echo: 'Echo'):
        """Merge another echo (from a sub-cascade) into this one."""
        # Merge state (updates overwrite)
        self.state.update(other_echo.state)
        # Append lineage
        self.lineage.extend(other_echo.lineage)
        # Merge errors from sub-cascade
        self.errors.extend(other_echo.errors)
        # History might be tricky, let's append it with a marker
        self.history.append({"sub_echo": other_echo.session_id, "history": other_echo.history})

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Echo] = {}

    def get_session(self, session_id: str, parent_session_id: str = None) -> Echo:
        if session_id not in self.sessions:
            print(f"[SessionManager] Creating NEW Echo for {session_id}")
            self.sessions[session_id] = Echo(session_id, parent_session_id=parent_session_id)
        else:
            print(f"[SessionManager] REUSING existing Echo for {session_id}")
            print(f"[SessionManager]   State keys: {list(self.sessions[session_id].state.keys())}")
            print(f"[SessionManager]   History entries: {len(self.sessions[session_id].history)}")
        return self.sessions[session_id]

_session_manager = SessionManager()

def get_echo(session_id: str, parent_session_id: str = None) -> Echo:
    return _session_manager.get_session(session_id, parent_session_id)
