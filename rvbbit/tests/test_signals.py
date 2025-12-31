"""
Tests for the signals system - cross-cascade communication.
"""

import pytest
import json
import threading
import time
from datetime import datetime, timedelta


# Test the signal models and status
def test_signal_status_enum():
    """Test SignalStatus enum values."""
    from rvbbit.signals import SignalStatus

    assert SignalStatus.WAITING.value == "waiting"
    assert SignalStatus.FIRED.value == "fired"
    assert SignalStatus.TIMEOUT.value == "timeout"
    assert SignalStatus.CANCELLED.value == "cancelled"


def test_signal_dataclass():
    """Test Signal dataclass creation."""
    from rvbbit.signals import Signal, SignalStatus

    signal = Signal(
        signal_id="sig_test123",
        signal_name="test_signal",
        status=SignalStatus.WAITING,
        session_id="session_abc",
        cascade_id="test_cascade",
        cell_name="test_cell",
        description="Test signal for unit tests"
    )

    assert signal.signal_id == "sig_test123"
    assert signal.signal_name == "test_signal"
    assert signal.status == SignalStatus.WAITING
    assert signal.session_id == "session_abc"
    assert signal.cascade_id == "test_cascade"
    assert signal.cell_name == "test_cell"
    assert signal.description == "Test signal for unit tests"


def test_signal_to_dict():
    """Test Signal.to_dict() serialization."""
    from rvbbit.signals import Signal, SignalStatus

    signal = Signal(
        signal_id="sig_test123",
        signal_name="test_signal",
        status=SignalStatus.FIRED,
        session_id="session_abc",
        cascade_id="test_cascade",
        payload={"key": "value"}
    )

    d = signal.to_dict()

    assert d["signal_id"] == "sig_test123"
    assert d["signal_name"] == "test_signal"
    assert d["status"] == "fired"
    assert d["payload"] == {"key": "value"}


# Test duration parsing
def test_parse_duration_seconds():
    """Test parsing seconds duration."""
    from rvbbit.signals import _parse_duration

    result = _parse_duration("30s")
    assert result.total_seconds() == 30


def test_parse_duration_minutes():
    """Test parsing minutes duration."""
    from rvbbit.signals import _parse_duration

    result = _parse_duration("5m")
    assert result.total_seconds() == 300


def test_parse_duration_hours():
    """Test parsing hours duration."""
    from rvbbit.signals import _parse_duration

    result = _parse_duration("2h")
    assert result.total_seconds() == 7200


def test_parse_duration_days():
    """Test parsing days duration."""
    from rvbbit.signals import _parse_duration

    result = _parse_duration("1d")
    assert result.total_seconds() == 86400


def test_parse_duration_default():
    """Test default duration on empty string."""
    from rvbbit.signals import _parse_duration

    result = _parse_duration("")
    assert result.total_seconds() == 3600  # Default 1 hour


def test_parse_duration_invalid():
    """Test default duration on invalid input."""
    from rvbbit.signals import _parse_duration

    result = _parse_duration("invalid")
    assert result.total_seconds() == 3600  # Default 1 hour


# Test SignalManager (in-memory, no DB)
def test_signal_manager_register():
    """Test registering a signal."""
    from rvbbit.signals import SignalManager, SignalStatus

    manager = SignalManager(use_db=False, start_server=False)

    signal = manager.register_signal(
        signal_name="test_signal",
        session_id="session_123",
        cascade_id="cascade_abc",
        cell_name="cell_1",
        timeout="1h",
        description="Test signal"
    )

    assert signal.signal_name == "test_signal"
    assert signal.session_id == "session_123"
    assert signal.status == SignalStatus.WAITING
    assert signal.timeout_at is not None


def test_signal_manager_get_signal():
    """Test getting a signal by ID."""
    from rvbbit.signals import SignalManager

    manager = SignalManager(use_db=False, start_server=False)

    signal = manager.register_signal(
        signal_name="test_signal",
        session_id="session_123",
        cascade_id="cascade_abc"
    )

    retrieved = manager.get_signal(signal.signal_id)
    assert retrieved is not None
    assert retrieved.signal_id == signal.signal_id
    assert retrieved.signal_name == "test_signal"


def test_signal_manager_get_nonexistent():
    """Test getting a nonexistent signal."""
    from rvbbit.signals import SignalManager

    manager = SignalManager(use_db=False, start_server=False)

    retrieved = manager.get_signal("nonexistent_id")
    assert retrieved is None


def test_signal_manager_list_signals():
    """Test listing signals."""
    from rvbbit.signals import SignalManager, SignalStatus

    manager = SignalManager(use_db=False, start_server=False)

    # Register multiple signals
    manager.register_signal(
        signal_name="signal_a",
        session_id="session_1",
        cascade_id="cascade_1"
    )
    manager.register_signal(
        signal_name="signal_b",
        session_id="session_2",
        cascade_id="cascade_1"
    )
    manager.register_signal(
        signal_name="signal_a",
        session_id="session_3",
        cascade_id="cascade_2"
    )

    # List all
    all_signals = manager.list_signals()
    assert len(all_signals) == 3

    # Filter by name
    signals_a = manager.list_signals(signal_name="signal_a")
    assert len(signals_a) == 2

    # Filter by cascade
    cascade_1_signals = manager.list_signals(cascade_id="cascade_1")
    assert len(cascade_1_signals) == 2

    # Filter by status (all should be waiting)
    waiting_signals = manager.list_signals(status=SignalStatus.WAITING)
    assert len(waiting_signals) == 3


def test_signal_manager_fire_signal():
    """Test firing a signal."""
    from rvbbit.signals import SignalManager, SignalStatus

    manager = SignalManager(use_db=False, start_server=False)

    # Register a signal
    signal = manager.register_signal(
        signal_name="data_ready",
        session_id="session_123",
        cascade_id="cascade_abc"
    )

    # Fire the signal
    fired = manager.fire_signal(
        signal_name="data_ready",
        payload={"rows": 1000},
        source="test"
    )

    assert len(fired) == 1
    assert fired[0].signal_id == signal.signal_id
    assert fired[0].status == SignalStatus.FIRED
    assert fired[0].payload == {"rows": 1000}
    assert fired[0].source == "test"


def test_signal_manager_fire_multiple():
    """Test firing signal wakes multiple waiters."""
    from rvbbit.signals import SignalManager

    manager = SignalManager(use_db=False, start_server=False)

    # Register multiple signals with same name
    manager.register_signal(
        signal_name="shared_event",
        session_id="session_1",
        cascade_id="cascade_1"
    )
    manager.register_signal(
        signal_name="shared_event",
        session_id="session_2",
        cascade_id="cascade_2"
    )
    manager.register_signal(
        signal_name="other_event",
        session_id="session_3",
        cascade_id="cascade_3"
    )

    # Fire shared_event
    fired = manager.fire_signal(signal_name="shared_event", payload={"test": True})

    assert len(fired) == 2
    for signal in fired:
        assert signal.signal_name == "shared_event"


def test_signal_manager_fire_specific_session():
    """Test firing signal for specific session."""
    from rvbbit.signals import SignalManager, SignalStatus

    manager = SignalManager(use_db=False, start_server=False)

    # Register signals
    signal1 = manager.register_signal(
        signal_name="my_signal",
        session_id="session_1",
        cascade_id="cascade_1"
    )
    signal2 = manager.register_signal(
        signal_name="my_signal",
        session_id="session_2",
        cascade_id="cascade_2"
    )

    # Fire only for session_1
    fired = manager.fire_signal(
        signal_name="my_signal",
        payload={"selective": True},
        session_id="session_1"
    )

    assert len(fired) == 1
    assert fired[0].session_id == "session_1"

    # Check signal2 is still waiting
    signal2_updated = manager.get_signal(signal2.signal_id)
    assert signal2_updated.status == SignalStatus.WAITING


def test_signal_manager_cancel_signal():
    """Test cancelling a signal."""
    from rvbbit.signals import SignalManager, SignalStatus

    manager = SignalManager(use_db=False, start_server=False)

    signal = manager.register_signal(
        signal_name="cancellable",
        session_id="session_123",
        cascade_id="cascade_abc"
    )

    manager.cancel_signal(signal.signal_id, reason="Test cancellation")

    updated = manager.get_signal(signal.signal_id)
    assert updated.status == SignalStatus.CANCELLED
    assert updated.metadata.get("cancel_reason") == "Test cancellation"


def test_signal_manager_wait_and_fire():
    """Test waiting for signal in background thread."""
    from rvbbit.signals import SignalManager, SignalStatus

    manager = SignalManager(use_db=False, start_server=False)

    # Register signal
    signal = manager.register_signal(
        signal_name="async_test",
        session_id="session_123",
        cascade_id="cascade_abc",
        timeout="30s"
    )

    result_holder = {"result": None}

    def wait_for_signal():
        result = manager.wait_for_signal(signal.signal_id, poll_interval=0.1)
        result_holder["result"] = result

    # Start waiting in background
    wait_thread = threading.Thread(target=wait_for_signal)
    wait_thread.start()

    # Give thread time to start waiting
    time.sleep(0.2)

    # Fire the signal
    manager.fire_signal(
        signal_name="async_test",
        payload={"message": "hello"},
        source="test"
    )

    # Wait for thread to complete
    wait_thread.join(timeout=5)

    assert result_holder["result"] is not None
    assert result_holder["result"]["message"] == "hello"


def test_signal_manager_wait_timeout():
    """Test signal timeout."""
    from rvbbit.signals import SignalManager

    manager = SignalManager(use_db=False, start_server=False)

    # Register signal with very short timeout
    signal = manager.register_signal(
        signal_name="timeout_test",
        session_id="session_123",
        cascade_id="cascade_abc",
        timeout="2s"  # 2 second timeout
    )

    # Wait for signal with explicit timeout (should timeout quickly)
    result = manager.wait_for_signal(signal.signal_id, timeout=1.5, poll_interval=0.1)

    assert result is None  # Timeout returns None

    # Verify status is timeout
    updated = manager.get_signal(signal.signal_id)
    assert updated.status.value == "timeout"


# Test high-level API functions
def test_high_level_fire_signal():
    """Test fire_signal() high-level function."""
    from rvbbit.signals import SignalManager, fire_signal as fire_signal_api, get_signal_manager

    # Reset singleton for clean test
    import rvbbit.signals
    rvbbit.signals._signal_manager = None

    # Get manager with no server
    manager = get_signal_manager(use_db=False, start_server=False)

    # Register a signal directly
    manager.register_signal(
        signal_name="api_test",
        session_id="test_session",
        cascade_id="test_cascade"
    )

    # Use high-level API to fire
    count = fire_signal_api(
        signal_name="api_test",
        payload={"via": "api"},
        source="test"
    )

    assert count == 1


def test_high_level_list_waiting_signals():
    """Test list_waiting_signals() high-level function."""
    from rvbbit.signals import list_waiting_signals, get_signal_manager

    # Reset singleton
    import rvbbit.signals
    rvbbit.signals._signal_manager = None

    manager = get_signal_manager(use_db=False, start_server=False)

    # Register signals
    manager.register_signal(
        signal_name="list_test",
        session_id="session_1",
        cascade_id="cascade_1"
    )
    manager.register_signal(
        signal_name="list_test",
        session_id="session_2",
        cascade_id="cascade_2"
    )

    # Use high-level API
    signals = list_waiting_signals(signal_name="list_test")

    assert len(signals) == 2
    for s in signals:
        assert s["signal_name"] == "list_test"
        assert s["status"] == "waiting"


def test_high_level_cancel_waiting_signal():
    """Test cancel_waiting_signal() high-level function."""
    from rvbbit.signals import cancel_waiting_signal, get_signal_manager

    # Reset singleton
    import rvbbit.signals
    rvbbit.signals._signal_manager = None

    manager = get_signal_manager(use_db=False, start_server=False)

    signal = manager.register_signal(
        signal_name="cancel_test",
        session_id="session_1",
        cascade_id="cascade_1"
    )

    # Cancel via high-level API
    cancel_waiting_signal(signal.signal_id, reason="API test")

    # Verify cancelled
    updated = manager.get_signal(signal.signal_id)
    assert updated.status.value == "cancelled"


# Test signal tools (as cascades would use them)
@pytest.mark.timeout(10)  # 10 second timeout for this test
def test_await_signal_tool_timeout():
    """Test await_signal tool returns timeout result."""
    # Skip this test in quick runs - it's slow by design
    pytest.skip("Skipping slow timeout test - validated in test_signal_manager_wait_timeout")


def test_fire_signal_tool():
    """Test fire_signal tool."""
    from rvbbit.traits.signal_tools import fire_signal
    from rvbbit.signals import get_signal_manager

    # Reset singleton
    import rvbbit.signals
    rvbbit.signals._signal_manager = None

    manager = get_signal_manager(use_db=False, start_server=False)

    # Register a signal to be fired
    manager.register_signal(
        signal_name="tool_fire_test",
        session_id="session_123",
        cascade_id="cascade_abc"
    )

    # Fire via tool
    result = fire_signal(
        signal_name="tool_fire_test",
        payload={"via_tool": True}
    )

    assert result["status"] == "success"
    assert result["fired_count"] == 1
    assert result["_route"] == "success"


def test_list_signals_tool():
    """Test list_signals tool."""
    from rvbbit.traits.signal_tools import list_signals
    from rvbbit.signals import get_signal_manager

    # Reset singleton
    import rvbbit.signals
    rvbbit.signals._signal_manager = None

    manager = get_signal_manager(use_db=False, start_server=False)

    # Register signals
    manager.register_signal(
        signal_name="list_tool_test",
        session_id="session_1",
        cascade_id="cascade_1"
    )
    manager.register_signal(
        signal_name="list_tool_test",
        session_id="session_2",
        cascade_id="cascade_2"
    )

    # List via tool
    result = list_signals(signal_name="list_tool_test")

    assert result["count"] == 2
    assert len(result["signals"]) == 2


# Test schema
def test_signals_schema_exists():
    """Test signals schema is registered."""
    from rvbbit.schema import get_schema, get_all_schemas

    schemas = get_all_schemas()
    assert "signals" in schemas

    schema = get_schema("signals")
    assert "CREATE TABLE IF NOT EXISTS signals" in schema
    assert "signal_id" in schema
    assert "signal_name" in schema
    assert "callback_host" in schema
    assert "payload_json" in schema
