"""
Tests for the session state system - ClickHouse-native durable execution coordination.
"""

import pytest
import json
import threading
import time
from datetime import datetime, timedelta, timezone


# Test the status and type enums
def test_session_status_enum():
    """Test SessionStatus enum values."""
    from rvbbit.session_state import SessionStatus

    assert SessionStatus.STARTING.value == "starting"
    assert SessionStatus.RUNNING.value == "running"
    assert SessionStatus.BLOCKED.value == "blocked"
    assert SessionStatus.COMPLETED.value == "completed"
    assert SessionStatus.ERROR.value == "error"
    assert SessionStatus.CANCELLED.value == "cancelled"
    assert SessionStatus.ORPHANED.value == "orphaned"


def test_blocked_type_enum():
    """Test BlockedType enum values."""
    from rvbbit.session_state import BlockedType

    assert BlockedType.SIGNAL.value == "signal"
    assert BlockedType.HITL.value == "hitl"
    assert BlockedType.SENSOR.value == "sensor"
    assert BlockedType.APPROVAL.value == "approval"
    assert BlockedType.CHECKPOINT.value == "checkpoint"


# Test SessionState dataclass
def test_session_state_dataclass():
    """Test SessionState dataclass creation."""
    from rvbbit.session_state import SessionState, SessionStatus

    state = SessionState(
        session_id="session_123",
        cascade_id="test_cascade",
        status=SessionStatus.RUNNING,
        current_cell="phase_1",
        depth=0
    )

    assert state.session_id == "session_123"
    assert state.cascade_id == "test_cascade"
    assert state.status == SessionStatus.RUNNING
    assert state.current_cell == "phase_1"
    assert state.depth == 0


def test_session_state_to_dict():
    """Test SessionState.to_dict() serialization."""
    from rvbbit.session_state import SessionState, SessionStatus, BlockedType

    state = SessionState(
        session_id="session_123",
        cascade_id="test_cascade",
        status=SessionStatus.BLOCKED,
        blocked_type=BlockedType.SIGNAL,
        blocked_on="data_ready",
        blocked_description="Waiting for data"
    )

    d = state.to_dict()

    assert d["session_id"] == "session_123"
    assert d["cascade_id"] == "test_cascade"
    assert d["status"] == "blocked"
    assert d["blocked_type"] == "signal"
    assert d["blocked_on"] == "data_ready"
    assert d["blocked_description"] == "Waiting for data"


def test_session_state_is_active():
    """Test is_active() method."""
    from rvbbit.session_state import SessionState, SessionStatus

    # Active states
    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.STARTING
    ).is_active() == True

    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.RUNNING
    ).is_active() == True

    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.BLOCKED
    ).is_active() == True

    # Terminal states
    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.COMPLETED
    ).is_active() == False

    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.ERROR
    ).is_active() == False

    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.CANCELLED
    ).is_active() == False


def test_session_state_is_terminal():
    """Test is_terminal() method."""
    from rvbbit.session_state import SessionState, SessionStatus

    # Terminal states
    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.COMPLETED
    ).is_terminal() == True

    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.ERROR
    ).is_terminal() == True

    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.CANCELLED
    ).is_terminal() == True

    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.ORPHANED
    ).is_terminal() == True

    # Non-terminal states
    assert SessionState(
        session_id="s1", cascade_id="c1", status=SessionStatus.RUNNING
    ).is_terminal() == False


# Test SessionStateManager (in-memory, no DB)
def test_manager_create_session():
    """Test creating a session."""
    from rvbbit.session_state import SessionStateManager, SessionStatus

    manager = SessionStateManager(use_db=False)

    state = manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade",
        parent_session_id=None,
        depth=0
    )

    assert state.session_id == "session_123"
    assert state.cascade_id == "test_cascade"
    assert state.status == SessionStatus.STARTING
    assert state.heartbeat_at is not None


def test_manager_get_session():
    """Test getting a session by ID."""
    from rvbbit.session_state import SessionStateManager

    manager = SessionStateManager(use_db=False)

    state = manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    retrieved = manager.get_session("session_123")
    assert retrieved is not None
    assert retrieved.session_id == "session_123"
    assert retrieved.cascade_id == "test_cascade"


def test_manager_get_nonexistent():
    """Test getting a nonexistent session."""
    from rvbbit.session_state import SessionStateManager

    manager = SessionStateManager(use_db=False)

    retrieved = manager.get_session("nonexistent_id")
    assert retrieved is None


def test_manager_update_status():
    """Test updating session status."""
    from rvbbit.session_state import SessionStateManager, SessionStatus

    manager = SessionStateManager(use_db=False)

    manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    manager.update_status("session_123", SessionStatus.RUNNING, current_cell="phase_1")

    state = manager.get_session("session_123")
    assert state.status == SessionStatus.RUNNING
    assert state.current_cell == "phase_1"


def test_manager_update_status_completed():
    """Test updating to completed status sets completed_at."""
    from rvbbit.session_state import SessionStateManager, SessionStatus

    manager = SessionStateManager(use_db=False)

    manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    manager.update_status("session_123", SessionStatus.COMPLETED)

    state = manager.get_session("session_123")
    assert state.status == SessionStatus.COMPLETED
    assert state.completed_at is not None


def test_manager_update_status_error():
    """Test updating to error status sets error details."""
    from rvbbit.session_state import SessionStateManager, SessionStatus

    manager = SessionStateManager(use_db=False)

    manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    manager.update_status(
        "session_123",
        SessionStatus.ERROR,
        error_message="Something went wrong",
        error_cell="phase_2"
    )

    state = manager.get_session("session_123")
    assert state.status == SessionStatus.ERROR
    assert state.error_message == "Something went wrong"
    assert state.error_cell == "phase_2"


def test_manager_set_blocked():
    """Test setting session to blocked state."""
    from rvbbit.session_state import SessionStateManager, SessionStatus, BlockedType
    from datetime import datetime, timezone

    manager = SessionStateManager(use_db=False)

    manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    timeout = datetime.now(timezone.utc) + timedelta(hours=1)
    manager.set_blocked(
        "session_123",
        blocked_type=BlockedType.SIGNAL,
        blocked_on="data_ready",
        description="Waiting for upstream ETL",
        timeout_at=timeout
    )

    state = manager.get_session("session_123")
    assert state.status == SessionStatus.BLOCKED
    assert state.blocked_type == BlockedType.SIGNAL
    assert state.blocked_on == "data_ready"
    assert state.blocked_description == "Waiting for upstream ETL"
    assert state.blocked_timeout_at is not None


def test_manager_set_unblocked():
    """Test unblocking a session."""
    from rvbbit.session_state import SessionStateManager, SessionStatus, BlockedType

    manager = SessionStateManager(use_db=False)

    manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    # Block first
    manager.set_blocked(
        "session_123",
        blocked_type=BlockedType.HITL,
        blocked_on="checkpoint_abc",
        description="Waiting for approval"
    )

    # Now unblock
    manager.set_unblocked("session_123")

    state = manager.get_session("session_123")
    assert state.status == SessionStatus.RUNNING
    assert state.blocked_type is None
    assert state.blocked_on is None


def test_manager_heartbeat():
    """Test heartbeat update."""
    from rvbbit.session_state import SessionStateManager

    manager = SessionStateManager(use_db=False)

    state = manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    original_heartbeat = state.heartbeat_at

    # Wait a tiny bit and heartbeat
    time.sleep(0.01)
    manager.heartbeat("session_123")

    updated = manager.get_session("session_123")
    assert updated.heartbeat_at > original_heartbeat


def test_manager_request_cancellation():
    """Test requesting cancellation."""
    from rvbbit.session_state import SessionStateManager

    manager = SessionStateManager(use_db=False)

    manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    manager.request_cancellation("session_123", reason="User requested stop")

    state = manager.get_session("session_123")
    assert state.cancel_requested == True
    assert state.cancel_reason == "User requested stop"


def test_manager_is_cancelled():
    """Test checking if session is cancelled."""
    from rvbbit.session_state import SessionStateManager

    manager = SessionStateManager(use_db=False)

    manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    assert manager.is_cancelled("session_123") == False

    manager.request_cancellation("session_123")

    assert manager.is_cancelled("session_123") == True


def test_manager_list_sessions():
    """Test listing sessions."""
    from rvbbit.session_state import SessionStateManager, SessionStatus

    manager = SessionStateManager(use_db=False)

    # Create multiple sessions
    manager.create_session(
        session_id="session_1",
        cascade_id="cascade_a"
    )
    manager.create_session(
        session_id="session_2",
        cascade_id="cascade_a"
    )
    manager.create_session(
        session_id="session_3",
        cascade_id="cascade_b"
    )

    # Update statuses
    manager.update_status("session_1", SessionStatus.RUNNING)
    manager.update_status("session_2", SessionStatus.COMPLETED)
    manager.update_status("session_3", SessionStatus.RUNNING)

    # List all
    all_sessions = manager.list_sessions()
    assert len(all_sessions) == 3

    # Filter by status
    running = manager.list_sessions(status=SessionStatus.RUNNING)
    assert len(running) == 2

    # Filter by cascade
    cascade_a = manager.list_sessions(cascade_id="cascade_a")
    assert len(cascade_a) == 2


def test_manager_get_blocked_sessions():
    """Test getting all blocked sessions."""
    from rvbbit.session_state import SessionStateManager, SessionStatus, BlockedType

    manager = SessionStateManager(use_db=False)

    # Create sessions with different statuses
    manager.create_session(session_id="session_1", cascade_id="cascade_1")
    manager.create_session(session_id="session_2", cascade_id="cascade_2")
    manager.create_session(session_id="session_3", cascade_id="cascade_3")

    manager.update_status("session_1", SessionStatus.RUNNING)
    manager.set_blocked("session_2", BlockedType.SIGNAL, "sig_1", "Waiting")
    manager.set_blocked("session_3", BlockedType.HITL, "cp_1", "Approval needed")

    blocked = manager.get_blocked_sessions()
    assert len(blocked) == 2

    blocked_ids = {s.session_id for s in blocked}
    assert "session_2" in blocked_ids
    assert "session_3" in blocked_ids


def test_manager_get_active_sessions():
    """Test getting all active sessions."""
    from rvbbit.session_state import SessionStateManager, SessionStatus, BlockedType

    manager = SessionStateManager(use_db=False)

    manager.create_session(session_id="session_1", cascade_id="cascade_1")  # Starting
    manager.create_session(session_id="session_2", cascade_id="cascade_2")
    manager.create_session(session_id="session_3", cascade_id="cascade_3")
    manager.create_session(session_id="session_4", cascade_id="cascade_4")

    manager.update_status("session_2", SessionStatus.RUNNING)
    manager.set_blocked("session_3", BlockedType.SIGNAL, "sig_1", "Waiting")
    manager.update_status("session_4", SessionStatus.COMPLETED)

    active = manager.get_active_sessions()
    assert len(active) == 3  # session_1 (starting), session_2 (running), session_3 (blocked)


def test_manager_get_zombie_sessions():
    """Test zombie detection via heartbeat expiry."""
    from rvbbit.session_state import SessionStateManager, SessionStatus
    from datetime import datetime, timezone, timedelta

    manager = SessionStateManager(use_db=False)

    # Create a session
    state = manager.create_session(
        session_id="session_123",
        cascade_id="test_cascade"
    )

    # Manually set heartbeat to old time to simulate zombie
    state.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    state.heartbeat_lease_seconds = 60  # 60 second lease
    state.status = SessionStatus.RUNNING

    zombies = manager.get_zombie_sessions(grace_period_seconds=0)
    assert len(zombies) == 1
    assert zombies[0].session_id == "session_123"


def test_manager_cleanup_zombies():
    """Test cleaning up zombie sessions."""
    from rvbbit.session_state import SessionStateManager, SessionStatus
    from datetime import datetime, timezone, timedelta

    manager = SessionStateManager(use_db=False)

    # Create sessions
    state1 = manager.create_session(session_id="session_1", cascade_id="cascade_1")
    state2 = manager.create_session(session_id="session_2", cascade_id="cascade_2")

    # Make session_1 a zombie
    state1.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    state1.heartbeat_lease_seconds = 60
    state1.status = SessionStatus.RUNNING

    # session_2 is fresh
    manager.update_status("session_2", SessionStatus.RUNNING)

    # Cleanup
    count = manager.cleanup_zombies(grace_period_seconds=0)
    assert count == 1

    # Verify session_1 is orphaned
    state1_updated = manager.get_session("session_1")
    assert state1_updated.status == SessionStatus.ORPHANED

    # session_2 should still be running
    state2_updated = manager.get_session("session_2")
    assert state2_updated.status == SessionStatus.RUNNING


# Test high-level API functions
def test_high_level_create_session():
    """Test create_session() high-level function."""
    from rvbbit.session_state import (
        create_session, get_session_state_manager, SessionStatus
    )
    import rvbbit.session_state

    # Reset singleton for clean test
    rvbbit.session_state._session_state_manager = None
    get_session_state_manager(use_db=False)

    state = create_session(
        session_id="api_test_123",
        cascade_id="test_cascade"
    )

    assert state.session_id == "api_test_123"
    assert state.status == SessionStatus.STARTING


def test_high_level_update_status():
    """Test update_session_status() high-level function."""
    from rvbbit.session_state import (
        create_session, update_session_status, get_session,
        get_session_state_manager, SessionStatus
    )
    import rvbbit.session_state

    rvbbit.session_state._session_state_manager = None
    get_session_state_manager(use_db=False)

    create_session(session_id="api_test_456", cascade_id="test_cascade")
    update_session_status("api_test_456", SessionStatus.RUNNING, current_cell="phase_1")

    state = get_session("api_test_456")
    assert state.status == SessionStatus.RUNNING
    assert state.current_cell == "phase_1"


def test_high_level_blocked_operations():
    """Test set_session_blocked() and set_session_unblocked() functions."""
    from rvbbit.session_state import (
        create_session, set_session_blocked, set_session_unblocked, get_session,
        get_session_state_manager, SessionStatus, BlockedType
    )
    import rvbbit.session_state

    rvbbit.session_state._session_state_manager = None
    get_session_state_manager(use_db=False)

    create_session(session_id="blocked_test", cascade_id="test_cascade")

    set_session_blocked(
        "blocked_test",
        blocked_type=BlockedType.SIGNAL,
        blocked_on="my_signal",
        description="Waiting for signal"
    )

    state = get_session("blocked_test")
    assert state.status == SessionStatus.BLOCKED
    assert state.blocked_type == BlockedType.SIGNAL

    set_session_unblocked("blocked_test")

    state = get_session("blocked_test")
    assert state.status == SessionStatus.RUNNING
    assert state.blocked_type is None


def test_high_level_cancellation():
    """Test request_session_cancellation() and is_session_cancelled() functions."""
    from rvbbit.session_state import (
        create_session, request_session_cancellation, is_session_cancelled,
        get_session_state_manager
    )
    import rvbbit.session_state

    rvbbit.session_state._session_state_manager = None
    get_session_state_manager(use_db=False)

    create_session(session_id="cancel_test", cascade_id="test_cascade")

    assert is_session_cancelled("cancel_test") == False

    request_session_cancellation("cancel_test", reason="Test")

    assert is_session_cancelled("cancel_test") == True


def test_high_level_list_functions():
    """Test list_sessions(), get_blocked_sessions(), get_active_sessions() functions."""
    from rvbbit.session_state import (
        create_session, update_session_status, set_session_blocked,
        list_sessions, get_blocked_sessions, get_active_sessions,
        get_session_state_manager, SessionStatus, BlockedType
    )
    import rvbbit.session_state

    rvbbit.session_state._session_state_manager = None
    get_session_state_manager(use_db=False)

    create_session(session_id="list_1", cascade_id="cascade_1")
    create_session(session_id="list_2", cascade_id="cascade_2")
    create_session(session_id="list_3", cascade_id="cascade_3")

    update_session_status("list_1", SessionStatus.RUNNING)
    set_session_blocked("list_2", BlockedType.HITL, "cp_1", "Waiting")
    update_session_status("list_3", SessionStatus.COMPLETED)

    all_sessions = list_sessions()
    assert len(all_sessions) == 3

    blocked = get_blocked_sessions()
    assert len(blocked) == 1
    assert blocked[0].session_id == "list_2"

    active = get_active_sessions()
    assert len(active) == 2


def test_high_level_cleanup_zombies():
    """Test cleanup_zombie_sessions() function."""
    from rvbbit.session_state import (
        create_session, cleanup_zombie_sessions, get_session,
        get_session_state_manager, SessionStatus
    )
    from datetime import datetime, timezone, timedelta
    import rvbbit.session_state

    rvbbit.session_state._session_state_manager = None
    manager = get_session_state_manager(use_db=False)

    state = create_session(session_id="zombie_api_test", cascade_id="test_cascade")

    # Make it a zombie
    state.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    state.heartbeat_lease_seconds = 60
    state.status = SessionStatus.RUNNING

    count = cleanup_zombie_sessions(grace_period_seconds=0)
    assert count == 1

    updated = get_session("zombie_api_test")
    assert updated.status == SessionStatus.ORPHANED


# Test schema
def test_session_state_schema_exists():
    """Test session_state schema is registered."""
    from rvbbit.schema import get_schema, get_all_schemas

    schemas = get_all_schemas()
    assert "session_state" in schemas

    schema = get_schema("session_state")
    assert "CREATE TABLE IF NOT EXISTS session_state" in schema
    assert "session_id" in schema
    assert "cascade_id" in schema
    assert "status" in schema
    assert "heartbeat_at" in schema
    assert "blocked_type" in schema
    assert "cancel_requested" in schema


def test_session_state_schema_status_values():
    """Test that schema has correct status enum values."""
    from rvbbit.schema import get_schema

    schema = get_schema("session_state")

    # Check all status values are in schema
    assert "'starting'" in schema
    assert "'running'" in schema
    assert "'blocked'" in schema
    assert "'completed'" in schema
    assert "'error'" in schema
    assert "'cancelled'" in schema
    assert "'orphaned'" in schema


def test_session_state_schema_blocked_types():
    """Test that schema has correct blocked_type enum values."""
    from rvbbit.schema import get_schema

    schema = get_schema("session_state")

    # Check all blocked type values are in schema
    assert "'signal'" in schema
    assert "'hitl'" in schema
    assert "'sensor'" in schema
    assert "'approval'" in schema
    assert "'checkpoint'" in schema
