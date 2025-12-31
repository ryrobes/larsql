"""
Human-in-the-Loop (HITL) Checkpoint Management for RVBBIT.

This module handles cascade suspension and resume for human input.
Checkpoints can be:
1. Phase-level input: Pause after a phase for human confirmation/input
2. Sounding evaluation: Present multiple candidate attempts for human selection

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

from .events import get_event_bus, Event
from .db_adapter import get_db_adapter
from .schema import get_schema


class CheckpointStatus(str, Enum):
    """Status of a checkpoint."""
    PENDING = "pending"
    RESPONDED = "responded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class CheckpointType(str, Enum):
    """Type of checkpoint."""
    PHASE_INPUT = "phase_input"      # Phase-level HITL config
    SOUNDING_EVAL = "sounding_eval"  # Sounding evaluation
    FREE_TEXT = "free_text"          # Free-form text input (ask_human tool)
    CHOICE = "choice"                # Single choice selection (radio buttons)
    MULTI_CHOICE = "multi_choice"    # Multiple choice selection (checkboxes)
    CONFIRMATION = "confirmation"    # Yes/no confirmation
    RATING = "rating"                # Star rating (1-5)
    AUDIBLE = "audible"              # Real-time feedback injection mid-phase
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
    phase_trace_id: str        # Phase trace ID where suspended
    depth: int                 # Trace depth at suspension
    node_type: str             # Node type of suspended trace
    name: str                  # Name of suspended trace node

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "cascade_trace_id": self.cascade_trace_id,
            "phase_trace_id": self.phase_trace_id,
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
            phase_trace_id=data.get("phase_trace_id", ""),
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
    phase_output: str
    cascade_config: Optional[Dict[str, Any]] = None  # Full cascade config for resume
    trace_context: Optional[TraceContext] = None  # Trace hierarchy for proper resume linkage
    created_at: datetime = field(default_factory=datetime.utcnow)
    timeout_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    sounding_outputs: Optional[List[str]] = None
    sounding_metadata: Optional[List[Dict]] = None
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
            "phase_output": self.phase_output,
            "cascade_config": self.cascade_config,
            "trace_context": self.trace_context.to_dict() if self.trace_context else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "timeout_at": self.timeout_at.isoformat() if self.timeout_at else None,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
            "sounding_outputs": self.sounding_outputs,
            "sounding_metadata": self.sounding_metadata,
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
        self.event_bus = get_event_bus()

        # In-memory cache for fast access (keyed by checkpoint_id)
        self._cache: Dict[str, Checkpoint] = {}
        self._cache_lock = threading.Lock()

        # Initialize database table if using DB
        if use_db:
            self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Ensure the checkpoints table exists in the database."""
        try:
            from .config import get_config
            config = get_config()

            # Only create table for ClickHouse server mode
            if hasattr(config, 'use_clickhouse_server') and config.use_clickhouse_server:
                db = get_db_adapter()
                ddl = get_schema("checkpoints")
                db.execute(ddl)
        except Exception as e:
            print(f"[RVBBIT] Warning: Could not ensure checkpoints table exists: {e}")

    def create_checkpoint(
        self,
        session_id: str,
        cascade_id: str,
        cell_name: str,
        checkpoint_type: CheckpointType,
        ui_spec: Dict[str, Any],
        echo_snapshot: Dict[str, Any],
        phase_output: str,
        cascade_config: Optional[Dict[str, Any]] = None,
        trace_context: Optional[TraceContext] = None,
        sounding_outputs: Optional[List[str]] = None,
        sounding_metadata: Optional[List[Dict]] = None,
        timeout_seconds: Optional[int] = None
    ) -> Checkpoint:
        """
        Create a new checkpoint and notify UI.

        Args:
            session_id: Current cascade session ID
            cascade_id: Cascade identifier
            cell_name: Name of the phase creating this checkpoint
            checkpoint_type: Type of checkpoint (phase_input or sounding_eval)
            ui_spec: UI specification for rendering the checkpoint
            echo_snapshot: Full Echo state snapshot for resume
            phase_output: Output from the phase (for preview)
            cascade_config: Full cascade configuration JSON for resume
            trace_context: Trace hierarchy context for proper resume linkage
            sounding_outputs: List of candidate outputs (for sounding_eval type)
            sounding_metadata: Metadata for each candidate attempt
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
            phase_output=phase_output,
            cascade_config=cascade_config,
            trace_context=trace_context,
            sounding_outputs=sounding_outputs,
            sounding_metadata=sounding_metadata,
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

        # Publish event for UI notification
        self.event_bus.publish(Event(
            type="checkpoint_waiting",
            session_id=session_id,
            timestamp=now.isoformat(),
            data={
                "checkpoint_id": checkpoint_id,
                "cascade_id": cascade_id,
                "cell_name": cell_name,
                "checkpoint_type": checkpoint_type.value,
                "ui_spec": ui_spec,
                "preview": phase_output[:1500] if phase_output else None,
                "timeout_at": timeout_at.isoformat() if timeout_at else None,
                "num_soundings": len(sounding_outputs) if sounding_outputs else None,
                # Include candidate data for cross-process checkpoint sharing
                "sounding_outputs": sounding_outputs,
                "sounding_metadata": sounding_metadata,
                "echo_snapshot": echo_snapshot
            }
        ))

        # Generate summary asynchronously (non-blocking)
        self._generate_summary_async(checkpoint_id, session_id, phase_output)

        # Call hooks if available (for auto-save etc.)
        try:
            from .runner import get_current_hooks
            hooks = get_current_hooks()
            if hooks and hasattr(hooks, 'on_checkpoint_suspended'):
                hooks.on_checkpoint_suspended(
                    session_id, checkpoint_id, checkpoint_type.value, cell_name,
                    phase_output[:500] if phase_output else None,
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

        # Extract training data fields for candidate evaluation
        if checkpoint.checkpoint_type == CheckpointType.SOUNDING_EVAL:
            checkpoint.winner_index = response.get("winner_index")
            checkpoint.rankings = response.get("rankings")
            checkpoint.ratings = response.get("ratings")

        # Update cache
        with self._cache_lock:
            self._cache[checkpoint_id] = checkpoint

        # Persist
        if self.use_db:
            self._update_checkpoint(checkpoint)

        # Publish event
        self.event_bus.publish(Event(
            type="checkpoint_responded",
            session_id=checkpoint.session_id,
            timestamp=datetime.utcnow().isoformat(),
            data={
                "checkpoint_id": checkpoint_id,
                "cascade_id": checkpoint.cascade_id,
                "cell_name": checkpoint.cell_name,
                "response": response,
                "winner_index": checkpoint.winner_index
            }
        ))

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
                CheckpointType.PHASE_INPUT: BlockedType.HITL,
                CheckpointType.SOUNDING_EVAL: BlockedType.HITL,
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
                        console.print(f"[green]✓ Received human response (from cache)[/green]")
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
                    console.print(f"[green]✓ Received human response[/green]")
                    return checkpoint.response

                if checkpoint.status == CheckpointStatus.CANCELLED:
                    console.print(f"[yellow]⚠ Checkpoint was cancelled[/yellow]")
                    return None

                if checkpoint.status == CheckpointStatus.TIMEOUT:
                    console.print(f"[yellow]⚠ Checkpoint timed out[/yellow]")
                    return None

                # Check deadline
                if deadline and time.time() >= deadline:
                    console.print(f"[yellow]⚠ Timeout waiting for human response[/yellow]")
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

        # Publish event
        self.event_bus.publish(Event(
            type="checkpoint_cancelled",
            session_id=checkpoint.session_id,
            timestamp=datetime.utcnow().isoformat(),
            data={
                "checkpoint_id": checkpoint_id,
                "reason": reason
            }
        ))

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

        # Publish event
        self.event_bus.publish(Event(
            type="checkpoint_timeout",
            session_id=checkpoint.session_id,
            timestamp=datetime.utcnow().isoformat(),
            data={
                "checkpoint_id": checkpoint_id,
                "action_taken": action_taken
            }
        ))

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
            from .config import get_config
            config = get_config()

            if hasattr(config, 'use_clickhouse_server') and config.use_clickhouse_server:
                db = get_db_adapter()

                # Build row dict - insert_rows handles escaping properly
                row = {
                    'id': checkpoint.id,
                    'session_id': checkpoint.session_id,
                    'cascade_id': checkpoint.cascade_id,
                    'cell_name': checkpoint.cell_name,
                    'status': checkpoint.status.value,
                    'created_at': checkpoint.created_at,
                    'timeout_at': checkpoint.timeout_at,
                    'checkpoint_type': checkpoint.checkpoint_type.value,
                    'ui_spec': json.dumps(checkpoint.ui_spec),  # JSON string, properly escaped by insert_rows
                    'echo_snapshot': json.dumps(checkpoint.echo_snapshot),
                    'phase_output': checkpoint.phase_output,
                    'sounding_outputs': json.dumps(checkpoint.sounding_outputs) if checkpoint.sounding_outputs else None,
                    'sounding_metadata': json.dumps(checkpoint.sounding_metadata) if checkpoint.sounding_metadata else None,
                    'trace_context': json.dumps(checkpoint.trace_context.to_dict()) if checkpoint.trace_context else None,
                    'summary': checkpoint.summary  # Will be NULL initially, updated async
                }

                db.insert_rows('checkpoints', [row], columns=list(row.keys()))
                print(f"[Checkpoints] Saved checkpoint {checkpoint.id} to database")

        except Exception as e:
            print(f"[RVBBIT] Warning: Could not persist checkpoint to DB: {e}")
            import traceback
            traceback.print_exc()

    def _update_checkpoint(self, checkpoint: Checkpoint):
        """Update existing checkpoint in database."""
        try:
            from .config import get_config
            config = get_config()

            if hasattr(config, 'use_clickhouse_server') and config.use_clickhouse_server:
                db = get_db_adapter()
                # ClickHouse supports ALTER TABLE UPDATE for MergeTree family
                responded_at_sql = f"toDateTime64('{checkpoint.responded_at.isoformat()}', 3)" if checkpoint.responded_at else "NULL"
                response_sql = f"'{json.dumps(checkpoint.response).replace(chr(39), chr(39)+chr(39))}'" if checkpoint.response else "NULL"
                reasoning_sql = f"'{checkpoint.response_reasoning.replace(chr(39), chr(39)+chr(39))}'" if checkpoint.response_reasoning else "NULL"
                confidence_sql = str(checkpoint.response_confidence) if checkpoint.response_confidence is not None else "NULL"
                winner_sql = str(checkpoint.winner_index) if checkpoint.winner_index is not None else "NULL"
                rankings_sql = f"'{json.dumps(checkpoint.rankings)}'" if checkpoint.rankings else "NULL"
                ratings_sql = f"'{json.dumps(checkpoint.ratings)}'" if checkpoint.ratings else "NULL"

                db.execute(f"""
                    ALTER TABLE checkpoints UPDATE
                        status = '{checkpoint.status.value}',
                        responded_at = {responded_at_sql},
                        response = {response_sql},
                        response_reasoning = {reasoning_sql},
                        response_confidence = {confidence_sql},
                        winner_index = {winner_sql},
                        rankings = {rankings_sql},
                        ratings = {ratings_sql}
                    WHERE id = '{checkpoint.id}'
                """)
                print(f"[RVBBIT] Checkpoint {checkpoint.id} updated in DB (status={checkpoint.status.value})")
        except Exception as e:
            print(f"[RVBBIT] Warning: Could not update checkpoint in DB: {e}")

    def _generate_summary_async(self, checkpoint_id: str, session_id: str, phase_output: str):
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

                # Truncate phase_output if too long (keep first 1500 chars for context)
                truncated = phase_output[:1500] if phase_output else "No content"

                # Create agent with proper OpenRouter config
                agent = Agent(
                    model="google/gemini-2.5-flash-lite",
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
                    model=response.get("model", "google/gemini-2.5-flash-lite"),
                    cost=response.get("cost", 0),
                    tokens_in=response.get("tokens_in", 0),
                    tokens_out=response.get("tokens_out", 0)
                )

                # Update checkpoint in cache and database
                with self._cache_lock:
                    if checkpoint_id in self._cache:
                        self._cache[checkpoint_id].summary = summary

                        # Update database
                        if self.use_db:
                            try:
                                if hasattr(config, 'use_clickhouse_server') and config.use_clickhouse_server:
                                    db = get_db_adapter()
                                    # Escape single quotes for SQL
                                    safe_summary = summary.replace("'", "''")
                                    db.execute(f"""
                                        ALTER TABLE checkpoints UPDATE
                                            summary = '{safe_summary}'
                                        WHERE id = '{checkpoint_id}'
                                    """)
                                    print(f"[Checkpoints] Generated summary for {checkpoint_id}: {summary}")
                            except Exception as db_err:
                                print(f"[Checkpoints] Failed to save summary to DB: {db_err}")

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
            from .config import get_config
            config = get_config()

            if hasattr(config, 'use_clickhouse_server') and config.use_clickhouse_server:
                db = get_db_adapter()
                result = db.query(f"""
                    SELECT *
                    FROM checkpoints
                    WHERE id = '{checkpoint_id}'
                    ORDER BY created_at DESC
                    LIMIT 1
                """, output_format="dict")

                if result:
                    row = result[0]
                    # Deserialize trace_context if present
                    trace_context = None
                    if row.get("trace_context"):
                        trace_context_data = json.loads(row["trace_context"])
                        trace_context = TraceContext.from_dict(trace_context_data)

                    return Checkpoint(
                        id=row["id"],
                        session_id=row["session_id"],
                        cascade_id=row["cascade_id"],
                        cell_name=row["cell_name"],
                        checkpoint_type=CheckpointType(row["checkpoint_type"]),
                        status=CheckpointStatus(row["status"]),
                        ui_spec=json.loads(row["ui_spec"]),
                        echo_snapshot=json.loads(row["echo_snapshot"]),
                        phase_output=row["phase_output"],
                        trace_context=trace_context,
                        created_at=row["created_at"],
                        timeout_at=row.get("timeout_at"),
                        responded_at=row.get("responded_at"),
                        sounding_outputs=json.loads(row["sounding_outputs"]) if row.get("sounding_outputs") else None,
                        sounding_metadata=json.loads(row["sounding_metadata"]) if row.get("sounding_metadata") else None,
                        response=json.loads(row["response"]) if row.get("response") else None,
                        response_reasoning=row.get("response_reasoning"),
                        response_confidence=row.get("response_confidence"),
                        winner_index=row.get("winner_index"),
                        rankings=json.loads(row["rankings"]) if row.get("rankings") else None,
                        ratings=json.loads(row["ratings"]) if row.get("ratings") else None,
                    )
        except Exception as e:
            print(f"[RVBBIT] Warning: Could not load checkpoint from DB: {e}")

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
            from .config import get_config
            config = get_config()

            if hasattr(config, 'use_clickhouse_server') and config.use_clickhouse_server:
                db = get_db_adapter()

                # Build query with optional session filter
                session_filter = f"AND session_id = '{session_id}'" if session_id else ""

                result = db.query(f"""
                    SELECT *
                    FROM checkpoints
                    WHERE status = 'pending'
                    {session_filter}
                    ORDER BY created_at DESC
                """, output_format="dict")

                for row in result:
                    try:
                        # Deserialize trace_context if present
                        trace_context = None
                        if row.get("trace_context"):
                            trace_context_data = json.loads(row["trace_context"])
                            trace_context = TraceContext.from_dict(trace_context_data)

                        checkpoint = Checkpoint(
                            id=row["id"],
                            session_id=row["session_id"],
                            cascade_id=row["cascade_id"],
                            cell_name=row["cell_name"],
                            checkpoint_type=CheckpointType(row["checkpoint_type"]),
                            status=CheckpointStatus(row["status"]),
                            ui_spec=json.loads(row["ui_spec"]),
                            echo_snapshot=json.loads(row["echo_snapshot"]),
                            phase_output=row["phase_output"],
                            trace_context=trace_context,
                            created_at=row["created_at"],
                            timeout_at=row.get("timeout_at"),
                            responded_at=row.get("responded_at"),
                            sounding_outputs=json.loads(row["sounding_outputs"]) if row.get("sounding_outputs") else None,
                            sounding_metadata=json.loads(row["sounding_metadata"]) if row.get("sounding_metadata") else None,
                            response=json.loads(row["response"]) if row.get("response") else None,
                            response_reasoning=row.get("response_reasoning"),
                            response_confidence=row.get("response_confidence"),
                            winner_index=row.get("winner_index"),
                            rankings=json.loads(row["rankings"]) if row.get("rankings") else None,
                            ratings=json.loads(row["ratings"]) if row.get("ratings") else None,
                            summary=row.get("summary"),
                        )
                        checkpoints.append(checkpoint)
                    except Exception as row_err:
                        print(f"[RVBBIT] Warning: Could not parse checkpoint row: {row_err}")
                        continue

        except Exception as e:
            print(f"[RVBBIT] Warning: Could not load pending checkpoints from DB: {e}")

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
            from .config import get_config
            config = get_config()

            if hasattr(config, 'use_clickhouse_server') and config.use_clickhouse_server:
                db = get_db_adapter()

                result = db.query(f"""
                    SELECT *
                    FROM checkpoints
                    WHERE session_id = '{session_id}'
                    ORDER BY created_at ASC
                """, output_format="dict")

                for row in result:
                    try:
                        # Deserialize trace_context if present
                        trace_context = None
                        if row.get("trace_context"):
                            trace_context_data = json.loads(row["trace_context"])
                            trace_context = TraceContext.from_dict(trace_context_data)

                        checkpoint = Checkpoint(
                            id=row["id"],
                            session_id=row["session_id"],
                            cascade_id=row["cascade_id"],
                            cell_name=row["cell_name"],
                            checkpoint_type=CheckpointType(row["checkpoint_type"]),
                            status=CheckpointStatus(row["status"]),
                            ui_spec=json.loads(row["ui_spec"]),
                            echo_snapshot=json.loads(row["echo_snapshot"]),
                            phase_output=row["phase_output"],
                            trace_context=trace_context,
                            created_at=row["created_at"],
                            timeout_at=row.get("timeout_at"),
                            responded_at=row.get("responded_at"),
                            sounding_outputs=json.loads(row["sounding_outputs"]) if row.get("sounding_outputs") else None,
                            sounding_metadata=json.loads(row["sounding_metadata"]) if row.get("sounding_metadata") else None,
                            response=json.loads(row["response"]) if row.get("response") else None,
                            response_reasoning=row.get("response_reasoning"),
                            response_confidence=row.get("response_confidence"),
                            winner_index=row.get("winner_index"),
                            rankings=json.loads(row["rankings"]) if row.get("rankings") else None,
                            ratings=json.loads(row["ratings"]) if row.get("ratings") else None,
                            summary=row.get("summary"),
                        )
                        checkpoints.append(checkpoint)
                    except Exception as row_err:
                        print(f"[RVBBIT] Warning: Could not parse checkpoint row: {row_err}")
                        continue

        except Exception as e:
            print(f"[RVBBIT] Warning: Could not load all checkpoints from DB: {e}")

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
