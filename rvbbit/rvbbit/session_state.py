"""
Session State Management - ClickHouse-Native Durable Execution Coordination.

This module provides centralized session state tracking using ClickHouse as the
coordination database. It replaces JSON file-based state tracking with a robust,
queryable, cross-process coordination system.

Key features:
- Cross-process visibility (any CLI can see any session's state)
- Zombie detection via heartbeat expiry
- Cancellation support with graceful shutdown
- Blocked state surfacing (signal/HITL waits)
- Full queryability for UI dashboards

Architecture:
    ClickHouse is truth - all coordination state lives in CH, survives any process death.
    No central server required - CLI works standalone, coordination via CH polling.
    HTTP callbacks for acceleration - optional low-latency notifications (existing pattern).
    Polling for reliability - guaranteed delivery even if callbacks fail.
"""

from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List
from datetime import datetime, timezone
from enum import Enum
import json
import threading
import time

from .events import get_event_bus, Event


def _utcnow() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class SessionStatus(str, Enum):
    """Execution status of a cascade session."""
    STARTING = "starting"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"


class BlockedType(str, Enum):
    """Type of blocker when status is BLOCKED."""
    SIGNAL = "signal"
    HITL = "hitl"
    SENSOR = "sensor"
    APPROVAL = "approval"
    CHECKPOINT = "checkpoint"
    DECISION = "decision"  # LLM-generated decision point


@dataclass
class SessionState:
    """Represents the current state of a cascade session."""
    session_id: str
    cascade_id: str
    status: SessionStatus
    parent_session_id: Optional[str] = None
    current_cell: Optional[str] = None
    depth: int = 0

    # Caller tracking (NEW)
    caller_id: Optional[str] = None
    invocation_metadata_json: str = '{}'

    # Blocked state details
    blocked_type: Optional[BlockedType] = None
    blocked_on: Optional[str] = None
    blocked_description: Optional[str] = None
    blocked_timeout_at: Optional[datetime] = None

    # Heartbeat
    heartbeat_at: datetime = field(default_factory=_utcnow)
    heartbeat_lease_seconds: int = 60

    # Cancellation
    cancel_requested: bool = False
    cancel_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None

    # Error details
    error_message: Optional[str] = None
    error_cell: Optional[str] = None

    # Recovery
    last_checkpoint_id: Optional[str] = None
    resumable: bool = False

    # Timing
    started_at: datetime = field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=_utcnow)

    # Metadata
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "cascade_id": self.cascade_id,
            "status": self.status.value,
            "parent_session_id": self.parent_session_id,
            "current_cell": self.current_cell,
            "depth": self.depth,
            "caller_id": self.caller_id,
            "invocation_metadata_json": self.invocation_metadata_json,
            "blocked_type": self.blocked_type.value if self.blocked_type else None,
            "blocked_on": self.blocked_on,
            "blocked_description": self.blocked_description,
            "blocked_timeout_at": self.blocked_timeout_at.isoformat() if self.blocked_timeout_at else None,
            "heartbeat_at": self.heartbeat_at.isoformat() if self.heartbeat_at else None,
            "heartbeat_lease_seconds": self.heartbeat_lease_seconds,
            "cancel_requested": self.cancel_requested,
            "cancel_reason": self.cancel_reason,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "error_message": self.error_message,
            "error_cell": self.error_cell,
            "last_checkpoint_id": self.last_checkpoint_id,
            "resumable": self.resumable,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
        }

    def is_active(self) -> bool:
        """Check if session is in an active state (running or blocked)."""
        return self.status in (SessionStatus.STARTING, SessionStatus.RUNNING, SessionStatus.BLOCKED)

    def is_terminal(self) -> bool:
        """Check if session is in a terminal state."""
        return self.status in (SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.CANCELLED, SessionStatus.ORPHANED)


class SessionStateManager:
    """
    Manages cascade session state using ClickHouse as the coordination database.

    Provides:
    - Session state CRUD operations
    - Heartbeat updates for zombie detection
    - Cancellation requests and checks
    - Blocked state surfacing
    - Zombie cleanup
    """

    def __init__(self, use_db: bool = True):
        """
        Initialize the SessionStateManager.

        Args:
            use_db: If True, persist to ClickHouse. If False, use in-memory only (testing).
        """
        self.use_db = use_db
        self.event_bus = get_event_bus()

        # In-memory cache for fast access
        self._cache: Dict[str, SessionState] = {}
        self._lock = threading.Lock()

        # Initialize database table
        if use_db:
            self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Ensure the session_state table exists in ClickHouse."""
        try:
            from .db_adapter import get_db
            from .schema import get_schema
            db = get_db()
            ddl = get_schema("session_state")
            db.execute(ddl)
        except Exception as e:
            print(f"[SessionState] Warning: Could not ensure table exists: {e}")

    # =========================================================================
    # Write Operations
    # =========================================================================

    def create_session(
        self,
        session_id: str,
        cascade_id: str,
        parent_session_id: Optional[str] = None,
        depth: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SessionState:
        """
        Create a new session in STARTING status.

        Args:
            session_id: Unique session identifier
            cascade_id: Cascade being executed
            parent_session_id: Parent session if this is a sub-cascade
            depth: Nesting depth
            metadata: Optional metadata dict

        Returns:
            Created SessionState object
        """
        now = _utcnow()

        # Look up caller_id from Echo (if it exists)
        caller_id_val = None
        invocation_metadata_val = '{}'
        try:
            from .echo import _session_manager
            if session_id in _session_manager.sessions:
                echo = _session_manager.sessions[session_id]
                caller_id_val = echo.caller_id
                if echo.invocation_metadata:
                    invocation_metadata_val = json.dumps(echo.invocation_metadata)
        except Exception:
            pass  # If Echo doesn't exist yet, that's OK

        state = SessionState(
            session_id=session_id,
            cascade_id=cascade_id,
            status=SessionStatus.STARTING,
            parent_session_id=parent_session_id,
            depth=depth,
            caller_id=caller_id_val,
            invocation_metadata_json=invocation_metadata_val,
            heartbeat_at=now,
            started_at=now,
            updated_at=now,
            metadata=metadata
        )

        # Cache it
        with self._lock:
            self._cache[session_id] = state

        # Persist to database
        if self.use_db:
            self._save_state(state)

        # Publish event
        self.event_bus.publish(Event(
            type="session_started",
            session_id=session_id,
            timestamp=now.isoformat(),
            data={
                "cascade_id": cascade_id,
                "parent_session_id": parent_session_id,
                "status": state.status.value
            }
        ))

        return state

    def update_status(
        self,
        session_id: str,
        status: SessionStatus,
        current_cell: Optional[str] = None,
        error_message: Optional[str] = None,
        error_cell: Optional[str] = None
    ):
        """
        Update session status.

        Args:
            session_id: Session to update
            status: New status
            current_cell: Current cell name (for running status)
            error_message: Error message (for error status)
            error_cell: Cell where error occurred
        """
        state = self.get_session(session_id)
        if not state:
            # Create a minimal state if not found (for backward compat)
            state = SessionState(
                session_id=session_id,
                cascade_id="unknown",
                status=status
            )

        state.status = status
        state.updated_at = _utcnow()

        if current_cell is not None:
            state.current_cell = current_cell

        if status == SessionStatus.ERROR:
            state.error_message = error_message
            state.error_cell = error_cell

        if status == SessionStatus.COMPLETED:
            state.completed_at = _utcnow()

        if status == SessionStatus.CANCELLED:
            state.cancelled_at = _utcnow()

        # Clear blocked state when transitioning away from blocked
        if status != SessionStatus.BLOCKED:
            state.blocked_type = None
            state.blocked_on = None
            state.blocked_description = None
            state.blocked_timeout_at = None

        # Update cache and persist
        with self._lock:
            self._cache[session_id] = state

        if self.use_db:
            self._save_state(state)

        # Publish event
        self.event_bus.publish(Event(
            type="session_status_changed",
            session_id=session_id,
            timestamp=state.updated_at.isoformat(),
            data={
                "status": status.value,
                "current_cell": current_cell,
                "cascade_id": state.cascade_id
            }
        ))

    def set_blocked(
        self,
        session_id: str,
        blocked_type: BlockedType,
        blocked_on: str,
        description: Optional[str] = None,
        timeout_at: Optional[datetime] = None
    ):
        """
        Set session to blocked status.

        Args:
            session_id: Session to update
            blocked_type: Type of blocker (signal, hitl, etc.)
            blocked_on: Identifier of what we're blocked on
            description: Human-readable description
            timeout_at: When the block will timeout
        """
        state = self.get_session(session_id)
        if not state:
            return

        state.status = SessionStatus.BLOCKED
        state.blocked_type = blocked_type
        state.blocked_on = blocked_on
        state.blocked_description = description
        state.blocked_timeout_at = timeout_at
        state.updated_at = _utcnow()

        with self._lock:
            self._cache[session_id] = state

        if self.use_db:
            self._save_state(state)

        # Publish event
        self.event_bus.publish(Event(
            type="session_blocked",
            session_id=session_id,
            timestamp=state.updated_at.isoformat(),
            data={
                "blocked_type": blocked_type.value,
                "blocked_on": blocked_on,
                "blocked_description": description,
                "timeout_at": timeout_at.isoformat() if timeout_at else None,
                "cascade_id": state.cascade_id
            }
        ))

    def set_unblocked(self, session_id: str):
        """
        Clear blocked state and return to running.

        Args:
            session_id: Session to unblock
        """
        self.update_status(session_id, SessionStatus.RUNNING)

        # Publish event
        self.event_bus.publish(Event(
            type="session_unblocked",
            session_id=session_id,
            timestamp=_utcnow().isoformat(),
            data={}
        ))

    def heartbeat(self, session_id: str):
        """
        Update heartbeat timestamp to prove session is still alive.

        Args:
            session_id: Session to heartbeat
        """
        state = self.get_session(session_id)
        if not state:
            return

        state.heartbeat_at = _utcnow()
        state.updated_at = state.heartbeat_at

        with self._lock:
            self._cache[session_id] = state

        if self.use_db:
            self._save_state(state)

    def request_cancellation(self, session_id: str, reason: Optional[str] = None):
        """
        Request graceful cancellation of a session.

        The running session will detect this on next check and shutdown gracefully.

        Args:
            session_id: Session to cancel
            reason: Optional cancellation reason
        """
        state = self.get_session(session_id)
        if not state:
            # Create a minimal state with cancel request
            state = SessionState(
                session_id=session_id,
                cascade_id="unknown",
                status=SessionStatus.RUNNING,
                cancel_requested=True,
                cancel_reason=reason
            )
        else:
            state.cancel_requested = True
            state.cancel_reason = reason
            state.updated_at = _utcnow()

        with self._lock:
            self._cache[session_id] = state

        if self.use_db:
            self._save_state(state)

        # Publish event
        self.event_bus.publish(Event(
            type="session_cancel_requested",
            session_id=session_id,
            timestamp=_utcnow().isoformat(),
            data={"reason": reason}
        ))

    # =========================================================================
    # Read Operations
    # =========================================================================

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """
        Get session state by ID.

        Args:
            session_id: Session to retrieve

        Returns:
            SessionState or None if not found
        """
        # Check cache first
        with self._lock:
            if session_id in self._cache:
                return self._cache[session_id]

        # Fall back to database
        if self.use_db:
            return self._load_state(session_id)

        return None

    def list_sessions(
        self,
        status: Optional[SessionStatus] = None,
        cascade_id: Optional[str] = None,
        limit: int = 100
    ) -> List[SessionState]:
        """
        List sessions with optional filters.

        Args:
            status: Filter by status
            cascade_id: Filter by cascade
            limit: Maximum results

        Returns:
            List of SessionState objects
        """
        if not self.use_db:
            # Return from cache
            with self._lock:
                results = list(self._cache.values())
                if status:
                    results = [s for s in results if s.status == status]
                if cascade_id:
                    results = [s for s in results if s.cascade_id == cascade_id]
                results.sort(key=lambda s: s.updated_at or datetime.min, reverse=True)
                return results[:limit]

        return self._query_sessions(status=status, cascade_id=cascade_id, limit=limit)

    def get_blocked_sessions(self) -> List[SessionState]:
        """Get all sessions currently in blocked state."""
        return self.list_sessions(status=SessionStatus.BLOCKED)

    def get_active_sessions(self) -> List[SessionState]:
        """Get all sessions in active states (starting, running, blocked)."""
        if not self.use_db:
            with self._lock:
                return [s for s in self._cache.values() if s.is_active()]

        try:
            from .db_adapter import get_db
            db = get_db()

            result = db.query("""
                SELECT *
                FROM session_state FINAL
                WHERE status IN ('starting', 'running', 'blocked')
                ORDER BY updated_at DESC
                LIMIT 1000
            """, output_format="dict")

            return [self._row_to_state(row) for row in result]

        except Exception as e:
            print(f"[SessionState] Could not query active sessions: {e}")
            return []

    def get_zombie_sessions(self, grace_period_seconds: int = 0) -> List[SessionState]:
        """
        Get sessions with expired heartbeats (zombies).

        Args:
            grace_period_seconds: Additional grace period beyond lease

        Returns:
            List of zombie SessionState objects
        """
        if not self.use_db:
            now = _utcnow()
            with self._lock:
                zombies = []
                for state in self._cache.values():
                    if state.is_active() and state.heartbeat_at:
                        elapsed = (now - state.heartbeat_at).total_seconds()
                        if elapsed > state.heartbeat_lease_seconds + grace_period_seconds:
                            zombies.append(state)
                return zombies

        try:
            from .db_adapter import get_db
            db = get_db()

            result = db.query(f"""
                SELECT *
                FROM session_state FINAL
                WHERE status IN ('starting', 'running', 'blocked')
                AND heartbeat_at + INTERVAL (heartbeat_lease_seconds + {grace_period_seconds}) SECOND < now()
                ORDER BY heartbeat_at ASC
                LIMIT 1000
            """, output_format="dict")

            return [self._row_to_state(row) for row in result]

        except Exception as e:
            print(f"[SessionState] Could not query zombie sessions: {e}")
            return []

    def is_cancelled(self, session_id: str) -> bool:
        """
        Check if cancellation was requested for a session.

        Args:
            session_id: Session to check

        Returns:
            True if cancellation was requested
        """
        state = self.get_session(session_id)
        return state.cancel_requested if state else False

    # =========================================================================
    # Maintenance Operations
    # =========================================================================

    def cleanup_zombies(self, grace_period_seconds: int = 30) -> int:
        """
        Mark zombie sessions as orphaned.

        Args:
            grace_period_seconds: Grace period beyond heartbeat lease

        Returns:
            Number of sessions marked as orphaned
        """
        zombies = self.get_zombie_sessions(grace_period_seconds)
        count = 0

        for state in zombies:
            print(f"[SessionState] Marking zombie session {state.session_id} as orphaned")
            self.update_status(
                state.session_id,
                SessionStatus.ORPHANED,
                error_message=f"Heartbeat expired (last: {state.heartbeat_at})"
            )
            count += 1

        return count

    # =========================================================================
    # Database Operations
    # =========================================================================

    def _save_state(self, state: SessionState):
        """Save session state to ClickHouse."""
        try:
            from .db_adapter import get_db
            db = get_db()

            # Convert timezone-aware datetimes to naive UTC for ClickHouse
            def to_naive_utc(dt):
                if dt is None:
                    return None
                if dt.tzinfo is not None:
                    return dt.replace(tzinfo=None)
                return dt

            row = {
                'session_id': state.session_id,
                'cascade_id': state.cascade_id,
                'parent_session_id': state.parent_session_id,
                'status': state.status.value,
                'current_cell': state.current_cell,
                'depth': state.depth,
                'caller_id': state.caller_id or '',
                'invocation_metadata_json': state.invocation_metadata_json or '{}',
                'blocked_type': state.blocked_type.value if state.blocked_type else None,
                'blocked_on': state.blocked_on,
                'blocked_description': state.blocked_description,
                'blocked_timeout_at': to_naive_utc(state.blocked_timeout_at),
                'heartbeat_at': to_naive_utc(state.heartbeat_at),
                'heartbeat_lease_seconds': state.heartbeat_lease_seconds,
                'cancel_requested': state.cancel_requested,
                'cancel_reason': state.cancel_reason,
                'cancelled_at': to_naive_utc(state.cancelled_at),
                'error_message': state.error_message,
                'error_cell': state.error_cell,
                'last_checkpoint_id': state.last_checkpoint_id,
                'resumable': state.resumable,
                'started_at': to_naive_utc(state.started_at),
                'completed_at': to_naive_utc(state.completed_at),
                'updated_at': to_naive_utc(state.updated_at),
                'metadata_json': json.dumps(state.metadata) if state.metadata else '{}',
            }

            db.insert_rows('session_state', [row])

        except Exception as e:
            print(f"[SessionState] Could not save state to DB: {e}")

    def _load_state(self, session_id: str) -> Optional[SessionState]:
        """Load session state from ClickHouse."""
        try:
            from .db_adapter import get_db
            db = get_db()

            result = db.query(f"""
                SELECT *
                FROM session_state FINAL
                WHERE session_id = '{session_id}'
                LIMIT 1
            """, output_format="dict")

            if result:
                state = self._row_to_state(result[0])
                # Cache it
                with self._lock:
                    self._cache[session_id] = state
                return state

        except Exception as e:
            print(f"[SessionState] Could not load state from DB: {e}")

        return None

    def _query_sessions(
        self,
        status: Optional[SessionStatus] = None,
        cascade_id: Optional[str] = None,
        limit: int = 100
    ) -> List[SessionState]:
        """Query sessions from ClickHouse with filters."""
        try:
            from .db_adapter import get_db
            db = get_db()

            where_clauses = []
            if status:
                where_clauses.append(f"status = '{status.value}'")
            if cascade_id:
                where_clauses.append(f"cascade_id = '{cascade_id}'")

            where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            result = db.query(f"""
                SELECT *
                FROM session_state FINAL
                {where}
                ORDER BY updated_at DESC
                LIMIT {limit}
            """, output_format="dict")

            return [self._row_to_state(row) for row in result]

        except Exception as e:
            print(f"[SessionState] Could not query sessions: {e}")
            return []

    def _row_to_state(self, row: Dict) -> SessionState:
        """Convert database row to SessionState object."""
        return SessionState(
            session_id=row['session_id'],
            cascade_id=row['cascade_id'],
            status=SessionStatus(row['status']),
            parent_session_id=row.get('parent_session_id'),
            current_cell=row.get('current_cell'),
            depth=row.get('depth', 0),
            blocked_type=BlockedType(row['blocked_type']) if row.get('blocked_type') else None,
            blocked_on=row.get('blocked_on'),
            blocked_description=row.get('blocked_description'),
            blocked_timeout_at=row.get('blocked_timeout_at'),
            heartbeat_at=row.get('heartbeat_at'),
            heartbeat_lease_seconds=row.get('heartbeat_lease_seconds', 60),
            cancel_requested=row.get('cancel_requested', False),
            cancel_reason=row.get('cancel_reason'),
            cancelled_at=row.get('cancelled_at'),
            error_message=row.get('error_message'),
            error_cell=row.get('error_cell'),
            last_checkpoint_id=row.get('last_checkpoint_id'),
            resumable=row.get('resumable', False),
            started_at=row.get('started_at'),
            completed_at=row.get('completed_at'),
            updated_at=row.get('updated_at'),
            metadata=json.loads(row['metadata_json']) if row.get('metadata_json') else None,
        )


# =============================================================================
# Global Session State Manager Singleton
# =============================================================================

_session_state_manager: Optional[SessionStateManager] = None
_manager_lock = threading.Lock()


def get_session_state_manager(use_db: bool = True) -> SessionStateManager:
    """Get the global session state manager singleton."""
    global _session_state_manager

    if _session_state_manager is None:
        with _manager_lock:
            if _session_state_manager is None:
                _session_state_manager = SessionStateManager(use_db=use_db)

    return _session_state_manager


# =============================================================================
# High-Level API Functions
# =============================================================================

def create_session(
    session_id: str,
    cascade_id: str,
    parent_session_id: Optional[str] = None,
    depth: int = 0,
    metadata: Optional[Dict[str, Any]] = None
) -> SessionState:
    """Create a new session in STARTING status."""
    manager = get_session_state_manager()
    return manager.create_session(session_id, cascade_id, parent_session_id, depth, metadata)


def update_session_status(
    session_id: str,
    status: SessionStatus,
    current_cell: Optional[str] = None,
    error_message: Optional[str] = None,
    error_cell: Optional[str] = None
):
    """Update session status."""
    manager = get_session_state_manager()
    manager.update_status(session_id, status, current_cell, error_message, error_cell)


def set_session_blocked(
    session_id: str,
    blocked_type: BlockedType,
    blocked_on: str,
    description: Optional[str] = None,
    timeout_at: Optional[datetime] = None
):
    """Set session to blocked status."""
    manager = get_session_state_manager()
    manager.set_blocked(session_id, blocked_type, blocked_on, description, timeout_at)


def set_session_unblocked(session_id: str):
    """Clear blocked state and return to running."""
    manager = get_session_state_manager()
    manager.set_unblocked(session_id)


def session_heartbeat(session_id: str):
    """Update heartbeat timestamp."""
    manager = get_session_state_manager()
    manager.heartbeat(session_id)


def request_session_cancellation(session_id: str, reason: Optional[str] = None):
    """Request graceful cancellation of a session."""
    manager = get_session_state_manager()
    manager.request_cancellation(session_id, reason)


def is_session_cancelled(session_id: str) -> bool:
    """Check if cancellation was requested."""
    manager = get_session_state_manager()
    return manager.is_cancelled(session_id)


def get_session(session_id: str) -> Optional[SessionState]:
    """Get session state by ID."""
    manager = get_session_state_manager()
    return manager.get_session(session_id)


def list_sessions(
    status: Optional[SessionStatus] = None,
    cascade_id: Optional[str] = None,
    limit: int = 100
) -> List[SessionState]:
    """List sessions with optional filters."""
    manager = get_session_state_manager()
    return manager.list_sessions(status, cascade_id, limit)


def get_blocked_sessions() -> List[SessionState]:
    """Get all sessions currently in blocked state."""
    manager = get_session_state_manager()
    return manager.get_blocked_sessions()


def get_active_sessions() -> List[SessionState]:
    """Get all sessions in active states."""
    manager = get_session_state_manager()
    return manager.get_active_sessions()


def cleanup_zombie_sessions(grace_period_seconds: int = 30) -> int:
    """Mark zombie sessions as orphaned. Returns count."""
    manager = get_session_state_manager()
    return manager.cleanup_zombies(grace_period_seconds)
