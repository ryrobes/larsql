"""
Human-in-the-Loop (HITL) Checkpoint Management for LARS.

This module handles cascade suspension and resume for human input.
Checkpoints can be:
1. Cell-level input: Pause after a cell for human confirmation/input
2. Take evaluation: Present multiple take attempts for human selection

Key features:
- Persistent storage (survives server restart)
- SSE notifications for real-time UI updates
- Timeout handling with configurable behavior
- Automatic training data collection
"""

from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List
from datetime import datetime, timedelta
from enum import Enum
import json
import uuid
import threading

from .db_adapter import get_db_adapter, query_source_context


class CheckpointStatus(str, Enum):
    """Status of a checkpoint."""
    PENDING = "pending"
    RESPONDED = "responded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class CheckpointType(str, Enum):
    """Type of checkpoint."""
    CELL_INPUT = "cell_input"      # Cell-level HITL config
    TAKE_EVAL = "take_eval"  # Take evaluation
    FREE_TEXT = "free_text"          # Free-form text input (ask_human tool)
    CHOICE = "choice"                # Single choice selection (radio buttons)
    MULTI_CHOICE = "multi_choice"    # Multiple choice selection (checkboxes)
    CONFIRMATION = "confirmation"    # Yes/no confirmation
    RATING = "rating"                # Star rating (1-5)
    AUDIBLE = "audible"              # Real-time feedback injection mid-cell
    DECISION = "decision"            # LLM-generated decision point (<decision> block)


@dataclass
class TraceContext:
    """
    Trace context captured at checkpoint creation for proper resume linkage.

    This allows resumed cascades to connect back to the original trace hierarchy,
    maintaining visualization continuity and data lineage.
    """
    trace_id: str              # Current trace ID at suspension
    parent_id: Optional[str]   # Parent trace ID for reconstruction
    cascade_trace_id: str      # Root cascade trace ID
    cell_trace_id: str        # Cell trace ID where suspended
    depth: int                 # Trace depth at suspension
    node_type: str             # Node type of suspended trace
    name: str                  # Name of suspended trace node

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "cascade_trace_id": self.cascade_trace_id,
            "cell_trace_id": self.cell_trace_id,
            "depth": self.depth,
            "node_type": self.node_type,
            "name": self.name
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TraceContext':
        return cls(
            trace_id=data.get("trace_id", ""),
            parent_id=data.get("parent_id"),
            cascade_trace_id=data.get("cascade_trace_id", ""),
            cell_trace_id=data.get("cell_trace_id", ""),
            depth=data.get("depth", 0),
            node_type=data.get("node_type", "unknown"),
            name=data.get("name", "unknown")
        )


@dataclass
class Checkpoint:
    """Represents a suspension point waiting for human input."""
    id: str
    session_id: str
    cascade_id: str
    cell_name: str
    checkpoint_type: CheckpointType
    status: CheckpointStatus
    ui_spec: Dict[str, Any]
    echo_snapshot: Dict[str, Any]
    cell_output: str
    cascade_config: Optional[Dict[str, Any]] = None  # Full cascade config for resume
    trace_context: Optional[TraceContext] = None  # Trace hierarchy for proper resume linkage
    created_at: datetime = field(default_factory=datetime.utcnow)
    timeout_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    take_outputs: Optional[List[str]] = None
    take_metadata: Optional[List[Dict]] = None
    response: Optional[Dict[str, Any]] = None
    response_reasoning: Optional[str] = None
    response_confidence: Optional[float] = None
    winner_index: Optional[int] = None
    rankings: Optional[List[int]] = None
    ratings: Optional[Dict[str, float]] = None
    summary: Optional[str] = None  # AI-generated one-sentence summary of the checkpoint

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "cascade_id": self.cascade_id,
            "cell_name": self.cell_name,
            "checkpoint_type": self.checkpoint_type.value,
            "status": self.status.value,
            "ui_spec": self.ui_spec,
            "echo_snapshot": self.echo_snapshot,
            "cell_output": self.cell_output,
            "cascade_config": self.cascade_config,
            "trace_context": self.trace_context.to_dict() if self.trace_context else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "timeout_at": self.timeout_at.isoformat() if self.timeout_at else None,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
            "take_outputs": self.take_outputs,
            "take_metadata": self.take_metadata,
            "response": self.response,
            "response_reasoning": self.response_reasoning,
            "response_confidence": self.response_confidence,
            "winner_index": self.winner_index,
            "rankings": self.rankings,
            "ratings": self.ratings,
            "summary": self.summary,
        }


class CheckpointManager:
    """
    Manages cascade suspension and resume for human input.

    Provides:
    - Checkpoint creation and persistence
    - Status tracking and timeout handling
    - SSE event publishing for UI notifications
    - Response recording with training data extraction
    """

    def __init__(self, use_db: bool = True):
        """
        Initialize the CheckpointManager.

        Args:
            use_db: If True, persist checkpoints to database.
                   If False, use in-memory storage only (for testing).
        """
        self.use_db = use_db

        # In-memory cache for fast access (keyed by checkpoint_id)
        self._cache: Dict[str, Checkpoint] = {}
        self._cache_lock = threading.Lock()

        # Initialize database table if using DB
        if use_db:
            self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Ensure the checkpoints table exists in the database."""
        try:
            # LarsDB/Parquet creates known system tables on first write.
            # Initializing the adapter here is enough to ensure writes succeed.
            _ = get_db_adapter()
        except Exception as e:
            print(f"[LARS] Warning: Could not ensure checkpoints table exists: {e}")

    @staticmethod
    def _decode_json(raw: Any, default: Any) -> Any:
        """Decode JSON-ish values from parquet rows, with safe fallback."""
        if raw is None:
            return default
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return default
            try:
                return json.loads(text)
            except Exception:
                return default
        return default

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                return None
        return None

    def _checkpoint_to_row(
        self,
        checkpoint: Checkpoint,
        *,
        updated_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Serialize checkpoint to append-only parquet row."""
        return {
            "id": checkpoint.id,
            "session_id": checkpoint.session_id,
            "cascade_id": checkpoint.cascade_id,
            "cell_name": checkpoint.cell_name,
            "status": checkpoint.status.value,
            "created_at": checkpoint.created_at,
            "updated_at": updated_at or checkpoint.created_at or datetime.utcnow(),
            "responded_at": checkpoint.responded_at,
            "timeout_at": checkpoint.timeout_at,
            "checkpoint_type": checkpoint.checkpoint_type.value,
            "ui_spec": json.dumps(checkpoint.ui_spec or {}),
            "echo_snapshot": json.dumps(checkpoint.echo_snapshot or {}),
            "cell_output": checkpoint.cell_output,
            "trace_context": json.dumps(checkpoint.trace_context.to_dict()) if checkpoint.trace_context else None,
            "take_outputs": json.dumps(checkpoint.take_outputs) if checkpoint.take_outputs is not None else None,
            "take_metadata": json.dumps(checkpoint.take_metadata) if checkpoint.take_metadata is not None else None,
            "response": json.dumps(checkpoint.response) if checkpoint.response is not None else None,
            "response_reasoning": checkpoint.response_reasoning,
            "response_confidence": checkpoint.response_confidence,
            "winner_index": checkpoint.winner_index,
            "rankings": json.dumps(checkpoint.rankings) if checkpoint.rankings is not None else None,
            "ratings": json.dumps(checkpoint.ratings) if checkpoint.ratings is not None else None,
        }

    def _checkpoint_from_row(self, row: Dict[str, Any]) -> Optional[Checkpoint]:
        """Deserialize a checkpoint row from parquet-backed view."""
        try:
            trace_context = None
            trace_payload = self._decode_json(row.get("trace_context"), None)
            if isinstance(trace_payload, dict):
                trace_context = TraceContext.from_dict(trace_payload)

            response_payload = self._decode_json(row.get("response"), None)
            if response_payload is not None and not isinstance(response_payload, dict):
                response_payload = {"value": response_payload}

            return Checkpoint(
                id=row.get("id", ""),
                session_id=row.get("session_id", ""),
                cascade_id=row.get("cascade_id", ""),
                cell_name=row.get("cell_name", ""),
                checkpoint_type=CheckpointType(row.get("checkpoint_type", CheckpointType.FREE_TEXT.value)),
                status=CheckpointStatus(row.get("status", CheckpointStatus.PENDING.value)),
                ui_spec=self._decode_json(row.get("ui_spec"), {}),
                echo_snapshot=self._decode_json(row.get("echo_snapshot"), {}),
                cell_output=row.get("cell_output") or "",
                trace_context=trace_context,
                created_at=self._parse_datetime(row.get("created_at")) or datetime.utcnow(),
                timeout_at=self._parse_datetime(row.get("timeout_at")),
                responded_at=self._parse_datetime(row.get("responded_at")),
                take_outputs=self._decode_json(row.get("take_outputs"), None),
                take_metadata=self._decode_json(row.get("take_metadata"), None),
                response=response_payload,
                response_reasoning=row.get("response_reasoning"),
                response_confidence=row.get("response_confidence"),
                winner_index=row.get("winner_index"),
                rankings=self._decode_json(row.get("rankings"), None),
                ratings=self._decode_json(row.get("ratings"), None),
                summary=row.get("summary"),
            )
        except Exception as row_err:
            print(f"[LARS] Warning: Could not parse checkpoint row: {row_err}")
            return None

    def _query_rows(self, sql: str) -> List[Dict[str, Any]]:
        """Run checkpoint reads against the freshest store (skip stale UI shadow cache)."""
        db = get_db_adapter()
        token = query_source_context.set("checkpoint_manager")
        try:
            return db.query(sql, output_format="dict")
        finally:
            query_source_context.reset(token)

    def create_checkpoint(
        self,
        session_id: str,
        cascade_id: str,
        cell_name: str,
        checkpoint_type: CheckpointType,
        ui_spec: Dict[str, Any],
        echo_snapshot: Dict[str, Any],
        cell_output: str,
        cascade_config: Optional[Dict[str, Any]] = None,
        trace_context: Optional[TraceContext] = None,
        take_outputs: Optional[List[str]] = None,
        take_metadata: Optional[List[Dict]] = None,
        timeout_seconds: Optional[int] = None
    ) -> Checkpoint:
        """
        Create a new checkpoint and notify UI.

        Args:
            session_id: Current cascade session ID
            cascade_id: Cascade identifier
            cell_name: Name of the cell creating this checkpoint
            checkpoint_type: Type of checkpoint (cell_input or take_eval)
            ui_spec: UI specification for rendering the checkpoint
            echo_snapshot: Full Echo state snapshot for resume
            cell_output: Output from the cell (for preview)
            cascade_config: Full cascade configuration JSON for resume
            trace_context: Trace hierarchy context for proper resume linkage
            take_outputs: List of take outputs (for take_eval type)
            take_metadata: Metadata for each take attempt
            timeout_seconds: Optional timeout in seconds

        Returns:
            Created Checkpoint object
        """
        checkpoint_id = f"cp_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        timeout_at = now + timedelta(seconds=timeout_seconds) if timeout_seconds else None

        checkpoint = Checkpoint(
            id=checkpoint_id,
            session_id=session_id,
            cascade_id=cascade_id,
            cell_name=cell_name,
            checkpoint_type=checkpoint_type,
            status=CheckpointStatus.PENDING,
            ui_spec=ui_spec,
            echo_snapshot=echo_snapshot,
            cell_output=cell_output,
            cascade_config=cascade_config,
            trace_context=trace_context,
            take_outputs=take_outputs,
            take_metadata=take_metadata,
            created_at=now,
            timeout_at=timeout_at
        )

        # Cache it
        with self._cache_lock:
            self._cache[checkpoint_id] = checkpoint

        # Persist to database
        print(f"[Checkpoints] Created checkpoint {checkpoint_id}, use_db={self.use_db}")
        if self.use_db:
            print(f"[Checkpoints] Attempting to save checkpoint {checkpoint_id} to database...")
            self._save_checkpoint(checkpoint)
        else:
            print(f"[Checkpoints] Skipping DB save (use_db=False)")

        # Generate summary asynchronously (non-blocking)
        self._generate_summary_async(checkpoint_id, session_id, cell_output)

        # Call hooks if available (for auto-save etc.)
        try:
            from .runner import get_current_hooks
            hooks = get_current_hooks()
            if hooks and hasattr(hooks, 'on_checkpoint_suspended'):
                hooks.on_checkpoint_suspended(
                    session_id, checkpoint_id, checkpoint_type.value, cell_name,
                    cell_output[:500] if cell_output else None,
                    cascade_id=cascade_id  # Pass cascade_id for auto-save
                )
        except Exception as hook_err:
            print(f"[Checkpoints] Warning: Hook call failed: {hook_err}")

        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """
        Retrieve checkpoint by ID.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            Checkpoint object or None if not found
        """
        # Check cache first
        with self._cache_lock:
            if checkpoint_id in self._cache:
                return self._cache[checkpoint_id]

        # Fall back to database
        if self.use_db:
            return self._load_checkpoint(checkpoint_id)

        return None

    def get_pending_checkpoints(self, session_id: Optional[str] = None) -> List[Checkpoint]:
        """
        Get all pending checkpoints.

        Checks both in-memory cache and database to ensure checkpoints
        persist across server restarts.

        Args:
            session_id: Optional filter by session ID

        Returns:
            List of pending Checkpoint objects
        """
        pending = []
        seen_ids = set()

        # First check in-memory cache (fastest)
        with self._cache_lock:
            for checkpoint in self._cache.values():
                if checkpoint.status == CheckpointStatus.PENDING:
                    if session_id is None or checkpoint.session_id == session_id:
                        pending.append(checkpoint)
                        seen_ids.add(checkpoint.id)

        # Then check database for any checkpoints not in cache
        if self.use_db:
            db_pending = self._load_pending_checkpoints(session_id)
            for cp in db_pending:
                if cp.id not in seen_ids:
                    # Add to cache for future fast access
                    with self._cache_lock:
                        self._cache[cp.id] = cp
                    pending.append(cp)

        return pending

    def get_all_checkpoints(self, session_id: str) -> List[Checkpoint]:
        """
        Get ALL checkpoints for a session (pending + responded).

        Used for research cockpit timeline visualization.

        Args:
            session_id: Session ID to filter by

        Returns:
            List of all Checkpoint objects for this session
        """
        all_checkpoints = []
        seen_ids = set()

        # First check in-memory cache
        with self._cache_lock:
            for checkpoint in self._cache.values():
                if checkpoint.session_id == session_id:
                    all_checkpoints.append(checkpoint)
                    seen_ids.add(checkpoint.id)

        # Then check database for any checkpoints not in cache
        if self.use_db:
            db_checkpoints = self._load_all_checkpoints(session_id)
            for cp in db_checkpoints:
                if cp.id not in seen_ids:
                    # Add to cache for future fast access
                    with self._cache_lock:
                        self._cache[cp.id] = cp
                    all_checkpoints.append(cp)

        # Sort by created_at
        all_checkpoints.sort(key=lambda cp: cp.created_at if cp.created_at else datetime.now())
        return all_checkpoints

    def respond_to_checkpoint(
        self,
        checkpoint_id: str,
        response: Dict[str, Any],
        reasoning: Optional[str] = None,
        confidence: Optional[float] = None
    ) -> Checkpoint:
        """
        Record human response and prepare for resume.

        Args:
            checkpoint_id: ID of the checkpoint to respond to
            response: Human response data
            reasoning: Optional explanation of the choice
            confidence: Optional confidence level (0-1)

        Returns:
            Updated Checkpoint object

        Raises:
            ValueError: If checkpoint not found or already responded
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        if checkpoint.status != CheckpointStatus.PENDING:
            raise ValueError(f"Checkpoint {checkpoint_id} already {checkpoint.status.value}")

        # Update checkpoint
        checkpoint.status = CheckpointStatus.RESPONDED
        checkpoint.response = response
        checkpoint.responded_at = datetime.utcnow()
        checkpoint.response_reasoning = reasoning
        checkpoint.response_confidence = confidence

        # Extract training data fields for take evaluation
        if checkpoint.checkpoint_type == CheckpointType.TAKE_EVAL:
            checkpoint.winner_index = response.get("winner_index")
            checkpoint.rankings = response.get("rankings")
            checkpoint.ratings = response.get("ratings")

        # Update cache
        with self._cache_lock:
            self._cache[checkpoint_id] = checkpoint

        # Persist
        if self.use_db:
            self._update_checkpoint(checkpoint)

        # Call hooks if available (for auto-save etc.)
        try:
            from .runner import get_current_hooks
            hooks = get_current_hooks()
            if hooks and hasattr(hooks, 'on_checkpoint_resumed'):
                hooks.on_checkpoint_resumed(
                    checkpoint.session_id, checkpoint_id, checkpoint.cell_name,
                    response, checkpoint.cascade_id
                )
        except Exception as hook_err:
            print(f"[Checkpoints] Warning: Hook call failed on response: {hook_err}")

        return checkpoint

    def wait_for_response(
        self,
        checkpoint_id: str,
        timeout: Optional[float] = None,
        poll_interval: float = 0.5
    ) -> Optional[Dict[str, Any]]:
        """
        Block until a checkpoint receives a response.

        This enables a simple blocking model for HITL - the cascade thread
        just waits here (like waiting for an LLM API call) until the human
        responds via the checkpoint API.

        Args:
            checkpoint_id: ID of the checkpoint to wait for
            timeout: Maximum time to wait in seconds (None = use checkpoint's timeout_at)
            poll_interval: How often to check for response (seconds)

        Returns:
            The response dict if responded, None if timed out or cancelled
        """
        import time
        from rich.console import Console

        console = Console()
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        # Determine effective timeout
        if timeout is not None:
            deadline = time.time() + timeout
        elif checkpoint.timeout_at:
            deadline = checkpoint.timeout_at.timestamp()
        else:
            deadline = None  # No timeout - wait indefinitely

        console.print(f"[dim]Waiting for human input on checkpoint {checkpoint_id[:8]}...[/dim]")

        # Update session state to blocked (for durable execution visibility)
        session_id = checkpoint.session_id
        try:
            from .session_state import set_session_blocked, set_session_unblocked, BlockedType
            # Map checkpoint type to blocked type
            blocked_type_map = {
                CheckpointType.CELL_INPUT: BlockedType.HITL,
                CheckpointType.TAKE_EVAL: BlockedType.HITL,
                CheckpointType.DECISION: BlockedType.DECISION,
                CheckpointType.FREE_TEXT: BlockedType.HITL,
                CheckpointType.CHOICE: BlockedType.HITL,
                CheckpointType.MULTI_CHOICE: BlockedType.HITL,
                CheckpointType.CONFIRMATION: BlockedType.APPROVAL,
                CheckpointType.RATING: BlockedType.HITL,
                CheckpointType.AUDIBLE: BlockedType.HITL,
            }
            blocked_type = blocked_type_map.get(checkpoint.checkpoint_type, BlockedType.HITL)
            set_session_blocked(
                session_id=session_id,
                blocked_type=blocked_type,
                blocked_on=checkpoint_id,
                description=f"Waiting for human input ({checkpoint.checkpoint_type.value})",
                timeout_at=checkpoint.timeout_at
            )
        except Exception:
            pass  # Don't fail if session state update fails

        try:
            while True:
                # Check cache first - apps_api may have updated it in the same process
                # This handles the case where apps_api and runner share memory
                with self._cache_lock:
                    cached = self._cache.get(checkpoint_id)
                    if cached and cached.status == CheckpointStatus.RESPONDED:
                        console.print(f"[green][OK] Received human response (from cache)[/green]")
                        return cached.response

                # Also check database for cross-process updates (multi-worker deployments)
                if self.use_db:
                    checkpoint = self._load_checkpoint(checkpoint_id)
                    # Only update cache if DB has newer status (don't overwrite RESPONDED with PENDING)
                    if checkpoint:
                        with self._cache_lock:
                            existing = self._cache.get(checkpoint_id)
                            if not existing or existing.status != CheckpointStatus.RESPONDED:
                                self._cache[checkpoint_id] = checkpoint
                            else:
                                # Cache already has RESPONDED, use that instead of stale DB data
                                checkpoint = existing
                else:
                    checkpoint = self.get_checkpoint(checkpoint_id)

                if checkpoint.status == CheckpointStatus.RESPONDED:
                    console.print(f"[green][OK] Received human response[/green]")
                    return checkpoint.response

                if checkpoint.status == CheckpointStatus.CANCELLED:
                    console.print(f"[yellow][WARN] Checkpoint was cancelled[/yellow]")
                    return None

                if checkpoint.status == CheckpointStatus.TIMEOUT:
                    console.print(f"[yellow][WARN] Checkpoint timed out[/yellow]")
                    return None

                # Check deadline
                if deadline and time.time() >= deadline:
                    console.print(f"[yellow][WARN] Timeout waiting for human response[/yellow]")
                    # Mark as timed out
                    self.timeout_checkpoint(checkpoint_id, "blocking_wait_timeout")
                    return None

                time.sleep(poll_interval)
        finally:
            # Always restore session state to running when done waiting
            try:
                from .session_state import set_session_unblocked
                set_session_unblocked(session_id)
            except Exception:
                pass

    def cancel_checkpoint(self, checkpoint_id: str, reason: Optional[str] = None) -> Checkpoint:
        """
        Cancel a pending checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to cancel
            reason: Optional cancellation reason

        Returns:
            Updated Checkpoint object
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        if checkpoint.status != CheckpointStatus.PENDING:
            raise ValueError(f"Checkpoint {checkpoint_id} already {checkpoint.status.value}")

        checkpoint.status = CheckpointStatus.CANCELLED
        checkpoint.responded_at = datetime.utcnow()

        # Update cache
        with self._cache_lock:
            self._cache[checkpoint_id] = checkpoint

        # Persist
        if self.use_db:
            self._update_checkpoint(checkpoint)

        return checkpoint

    def timeout_checkpoint(self, checkpoint_id: str, action_taken: str) -> Checkpoint:
        """
        Mark a checkpoint as timed out.

        Args:
            checkpoint_id: ID of the checkpoint
            action_taken: What action was taken (abort, continue, escalate, llm_fallback)

        Returns:
            Updated Checkpoint object
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        checkpoint.status = CheckpointStatus.TIMEOUT
        checkpoint.responded_at = datetime.utcnow()

        # Update cache
        with self._cache_lock:
            self._cache[checkpoint_id] = checkpoint

        # Persist
        if self.use_db:
            self._update_checkpoint(checkpoint)

        return checkpoint

    def check_timeouts(self) -> List[Checkpoint]:
        """
        Check for timed-out checkpoints.

        Returns:
            List of checkpoints that have timed out
        """
        now = datetime.utcnow()
        timed_out = []

        with self._cache_lock:
            for checkpoint in list(self._cache.values()):
                if (checkpoint.status == CheckpointStatus.PENDING and
                    checkpoint.timeout_at and
                    now >= checkpoint.timeout_at):
                    timed_out.append(checkpoint)

        return timed_out

    def _save_checkpoint(self, checkpoint: Checkpoint):
        """Persist checkpoint to database using insert_rows for proper escaping."""
        try:
            db = get_db_adapter()
            row = self._checkpoint_to_row(checkpoint, updated_at=checkpoint.created_at or datetime.utcnow())
            db.insert_rows("checkpoints", [row], columns=list(row.keys()))
            print(f"[Checkpoints] Saved checkpoint {checkpoint.id} to database")

        except Exception as e:
            print(f"[LARS] Warning: Could not persist checkpoint to DB: {e}")
            import traceback
            traceback.print_exc()

    def _update_checkpoint(self, checkpoint: Checkpoint):
        """Update existing checkpoint in database."""
        try:
            db = get_db_adapter()
            row = self._checkpoint_to_row(checkpoint, updated_at=datetime.utcnow())
            db.insert_rows("checkpoints", [row], columns=list(row.keys()))
            print(f"[LARS] Checkpoint {checkpoint.id} updated in DB (status={checkpoint.status.value})")
        except Exception as e:
            print(f"[LARS] Warning: Could not update checkpoint in DB: {e}")

    def _generate_summary_async(self, checkpoint_id: str, session_id: str, cell_output: str):
        """
        Generate AI summary for checkpoint asynchronously (non-blocking).
        Uses a cheap model (gemini-flash-lite) to create a one-sentence summary.
        Properly routes through OpenRouter with cost tracking.
        """
        def generate():
            try:
                from .agent import Agent
                from .config import get_config
                from .logs import log_message

                config = get_config()

                # Truncate cell_output if too long (keep first 1500 chars for context)
                truncated = cell_output[:1500] if cell_output else "No content"

                # Create agent with proper OpenRouter config
                from .models import fast_model
                agent = Agent(
                    model=fast_model(),
                    system_prompt="",
                    base_url=config.provider_base_url,
                    api_key=config.provider_api_key
                )

                # Call model for summary
                response = agent.run(
                    input_message=f"Summarize this checkpoint interaction in ONE short sentence (max 10 words):\n\n{truncated}"
                )

                summary = response.get("content", "").strip()

                # Log the LLM call with session_id for cost tracking
                log_message(
                    session_id=session_id,
                    cascade_id="checkpoint_summary",
                    cell_name="summary_generation",
                    role="assistant",
                    content=summary,
                    model=response.get("model", fast_model()),
                    cost=response.get("cost", 0),
                    tokens_in=response.get("tokens_in", 0),
                    tokens_out=response.get("tokens_out", 0)
                )

                # Update checkpoint in cache and database
                with self._cache_lock:
                    if checkpoint_id in self._cache:
                        self._cache[checkpoint_id].summary = summary

            except Exception as e:
                print(f"[Checkpoints] Failed to generate summary for {checkpoint_id}: {e}")
                import traceback
                traceback.print_exc()

        # Run in background thread
        thread = threading.Thread(target=generate, daemon=True)
        thread.start()

    def _load_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load checkpoint from database."""
        try:
            db = get_db_adapter()
            safe_id = checkpoint_id.replace("'", "''")
            result = self._query_rows(
                f"""
                SELECT *
                FROM checkpoints
                WHERE id = '{safe_id}'
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            )

            if result:
                return self._checkpoint_from_row(result[0])
        except Exception as e:
            print(f"[LARS] Warning: Could not load checkpoint from DB: {e}")

        return None

    def _load_pending_checkpoints(self, session_id: Optional[str] = None) -> List[Checkpoint]:
        """
        Load all pending checkpoints from database.

        This enables checkpoint persistence across server restarts.

        Args:
            session_id: Optional filter by session ID

        Returns:
            List of pending Checkpoint objects from database
        """
        checkpoints = []
        try:
            db = get_db_adapter()
            session_filter = ""
            if session_id:
                safe_session = session_id.replace("'", "''")
                session_filter = f"AND session_id = '{safe_session}'"

            result = self._query_rows(
                f"""
                SELECT *
                FROM checkpoints
                WHERE status = 'pending'
                {session_filter}
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                """
            )

            for row in result:
                checkpoint = self._checkpoint_from_row(row)
                if checkpoint:
                    checkpoints.append(checkpoint)

        except Exception as e:
            print(f"[LARS] Warning: Could not load pending checkpoints from DB: {e}")

        return checkpoints

    def _load_all_checkpoints(self, session_id: str) -> List[Checkpoint]:
        """
        Load ALL checkpoints for a session from database (pending + responded).

        Args:
            session_id: Session ID to filter by

        Returns:
            List of all Checkpoint objects from database for this session
        """
        checkpoints = []
        try:
            db = get_db_adapter()
            safe_session = session_id.replace("'", "''")
            result = self._query_rows(
                f"""
                SELECT *
                FROM checkpoints
                WHERE session_id = '{safe_session}'
                ORDER BY created_at ASC
                """
            )

            for row in result:
                checkpoint = self._checkpoint_from_row(row)
                if checkpoint:
                    checkpoints.append(checkpoint)

        except Exception as e:
            print(f"[LARS] Warning: Could not load all checkpoints from DB: {e}")

        return checkpoints


# Global checkpoint manager singleton
_checkpoint_manager: Optional[CheckpointManager] = None
_manager_lock = threading.Lock()


def get_checkpoint_manager() -> CheckpointManager:
    """Get the global checkpoint manager singleton."""
    global _checkpoint_manager

    if _checkpoint_manager is None:
        with _manager_lock:
            if _checkpoint_manager is None:
                _checkpoint_manager = CheckpointManager()

    return _checkpoint_manager
