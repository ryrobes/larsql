"""
Tests for lars.echo module.

Tests session state container and history management.
These are deterministic, framework-level tests that don't require LLM calls.
"""
import pytest
from unittest.mock import MagicMock
from lars.echo import Echo, SessionManager, get_echo


# =============================================================================
# Echo Class Tests
# =============================================================================

class TestEchoInit:
    """Tests for Echo initialization."""

    def test_init_with_defaults(self):
        """Echo should initialize with sensible defaults."""
        echo = Echo("test_session")

        assert echo.session_id == "test_session"
        assert echo.state == {}
        assert echo.history == []
        assert echo.lineage == []
        assert echo.errors == []
        assert echo.parent_session_id is None
        assert echo.caller_id is None

    def test_init_with_initial_state(self):
        """Echo should accept initial state."""
        initial = {"key": "value", "count": 42}
        echo = Echo("test", initial_state=initial)

        assert echo.state == initial
        # Should be the same dict, not a copy
        assert echo.state is initial

    def test_init_with_parent_session(self):
        """Echo should track parent session ID."""
        echo = Echo("child", parent_session_id="parent")

        assert echo.parent_session_id == "parent"

    def test_init_with_caller_id(self):
        """Echo should track caller ID."""
        echo = Echo("test", caller_id="sql_query_123")

        assert echo.caller_id == "sql_query_123"

    def test_init_with_invocation_metadata(self):
        """Echo should store invocation metadata."""
        metadata = {"source": "cli", "timestamp": "2024-01-01"}
        echo = Echo("test", invocation_metadata=metadata)

        assert echo.invocation_metadata == metadata


class TestEchoState:
    """Tests for Echo state management."""

    def test_update_state_adds_key(self):
        """update_state should add new keys."""
        echo = Echo("test")

        echo.update_state("foo", "bar")

        assert echo.state["foo"] == "bar"

    def test_update_state_overwrites_key(self):
        """update_state should overwrite existing keys."""
        echo = Echo("test", initial_state={"foo": "old"})

        echo.update_state("foo", "new")

        assert echo.state["foo"] == "new"

    def test_update_state_with_complex_value(self):
        """update_state should handle complex values."""
        echo = Echo("test")

        echo.update_state("data", {"nested": [1, 2, 3]})

        assert echo.state["data"] == {"nested": [1, 2, 3]}


class TestEchoHistory:
    """Tests for Echo history management."""

    def test_add_history_appends_entry(self):
        """add_history should append to history list."""
        echo = Echo("test")

        # Use skip_unified_log to avoid DB calls in tests
        echo.add_history(
            {"role": "user", "content": "Hello"},
            skip_unified_log=True
        )

        assert len(echo.history) == 1
        assert echo.history[0]["role"] == "user"
        assert echo.history[0]["content"] == "Hello"

    def test_add_history_with_trace_metadata(self):
        """add_history should enrich with trace metadata."""
        echo = Echo("test")

        echo.add_history(
            {"role": "assistant", "content": "Hi"},
            trace_id="trace123",
            parent_id="parent456",
            node_type="message",
            skip_unified_log=True
        )

        entry = echo.history[0]
        assert entry["trace_id"] == "trace123"
        assert entry["parent_id"] == "parent456"
        assert entry["node_type"] == "message"

    def test_add_history_copies_entry(self):
        """add_history should copy entry to avoid mutation."""
        echo = Echo("test")

        entry = {"role": "user", "content": "Test"}
        echo.add_history(entry, trace_id="trace1", skip_unified_log=True)

        # Original entry should NOT have trace_id
        assert "trace_id" not in entry
        # History entry should have trace_id
        assert echo.history[0]["trace_id"] == "trace1"

    def test_add_history_includes_cascade_context(self):
        """add_history should include cascade/cell context in metadata."""
        echo = Echo("test")
        echo.set_cascade_context("my_cascade")
        echo.set_cell_context("my_cell")

        echo.add_history(
            {"role": "user", "content": "Test"},
            skip_unified_log=True
        )

        metadata = echo.history[0]["metadata"]
        assert metadata["cascade_id"] == "my_cascade"
        assert metadata["cell_name"] == "my_cell"

    def test_add_history_skip_unified_log(self):
        """skip_unified_log=True should skip logging to unified_logs."""
        echo = Echo("test")

        # This should not raise any errors even without DB
        echo.add_history(
            {"role": "user", "content": "Test"},
            skip_unified_log=True
        )

        # Entry should still be added to history
        assert len(echo.history) == 1


class TestEchoLineage:
    """Tests for Echo lineage tracking."""

    def test_add_lineage(self):
        """add_lineage should track cell outputs."""
        echo = Echo("test")

        echo.add_lineage("cell1", {"result": "data"}, trace_id="trace1")

        assert len(echo.lineage) == 1
        assert echo.lineage[0]["cell"] == "cell1"
        assert echo.lineage[0]["output"] == {"result": "data"}
        assert echo.lineage[0]["trace_id"] == "trace1"

    def test_add_multiple_lineage_entries(self):
        """Multiple lineage entries should be preserved in order."""
        echo = Echo("test")

        echo.add_lineage("cell1", "output1")
        echo.add_lineage("cell2", "output2")
        echo.add_lineage("cell3", "output3")

        assert len(echo.lineage) == 3
        assert echo.lineage[0]["cell"] == "cell1"
        assert echo.lineage[1]["cell"] == "cell2"
        assert echo.lineage[2]["cell"] == "cell3"

    def test_add_lineage_unwraps_single_key_type_dict(self):
        """Single-key 'type' dicts should be unwrapped (LLM schema confusion fix)."""
        echo = Echo("test")

        # LLMs often return {"type": value} when confused by schema syntax
        echo.add_lineage("cell1", {"type": "500-685-1220"})

        assert echo.lineage[0]["output"] == "500-685-1220"

    def test_add_lineage_unwraps_type_dict_with_complex_value(self):
        """Single-key 'type' dict with complex value should be unwrapped."""
        echo = Echo("test")

        echo.add_lineage("cell1", {"type": {"nested": "data", "list": [1, 2, 3]}})

        assert echo.lineage[0]["output"] == {"nested": "data", "list": [1, 2, 3]}

    def test_add_lineage_preserves_multi_key_type_dict(self):
        """Multi-key dicts with 'type' should NOT be unwrapped."""
        echo = Echo("test")

        output = {"type": "phone", "value": "500-685-1220"}
        echo.add_lineage("cell1", output)

        assert echo.lineage[0]["output"] == {"type": "phone", "value": "500-685-1220"}

    def test_add_lineage_preserves_non_type_single_key_dict(self):
        """Single-key dicts without 'type' should NOT be unwrapped."""
        echo = Echo("test")

        echo.add_lineage("cell1", {"result": "value"})

        assert echo.lineage[0]["output"] == {"result": "value"}


class TestEchoErrors:
    """Tests for Echo error tracking."""

    def test_add_error(self):
        """add_error should track execution errors."""
        echo = Echo("test")

        echo.add_error("cell1", "ValueError", "Invalid input")

        assert len(echo.errors) == 1
        assert echo.errors[0]["cell"] == "cell1"
        assert echo.errors[0]["error_type"] == "ValueError"
        assert echo.errors[0]["error_message"] == "Invalid input"

    def test_add_error_with_metadata(self):
        """add_error should accept optional metadata."""
        echo = Echo("test")

        echo.add_error(
            "cell1",
            "TimeoutError",
            "Timed out",
            metadata={"timeout_seconds": 30}
        )

        assert echo.errors[0]["metadata"]["timeout_seconds"] == 30


class TestEchoFullEcho:
    """Tests for get_full_echo method."""

    def test_get_full_echo_structure(self):
        """get_full_echo should return complete state dict."""
        echo = Echo("test")
        echo.update_state("foo", "bar")

        full = echo.get_full_echo()

        assert full["session_id"] == "test"
        assert full["state"] == {"foo": "bar"}
        assert full["history"] == []
        assert full["lineage"] == []
        assert full["errors"] == []

    def test_get_full_echo_success_status(self):
        """Status should be 'success' when no errors."""
        echo = Echo("test")

        full = echo.get_full_echo()

        assert full["has_errors"] is False
        assert full["status"] == "success"

    def test_get_full_echo_failed_status(self):
        """Status should be 'failed' when errors exist."""
        echo = Echo("test")
        echo.add_error("cell1", "Error", "message")

        full = echo.get_full_echo()

        assert full["has_errors"] is True
        assert full["status"] == "failed"


class TestEchoMerge:
    """Tests for Echo.merge method."""

    def test_merge_state(self):
        """merge should combine state from child."""
        parent = Echo("parent")
        parent.update_state("parent_key", "parent_value")

        child = Echo("child")
        child.update_state("child_key", "child_value")

        parent.merge(child)

        assert parent.state["parent_key"] == "parent_value"
        assert parent.state["child_key"] == "child_value"

    def test_merge_state_overwrites(self):
        """Child state should overwrite parent on conflict."""
        parent = Echo("parent")
        parent.update_state("key", "parent_value")

        child = Echo("child")
        child.update_state("key", "child_value")

        parent.merge(child)

        assert parent.state["key"] == "child_value"

    def test_merge_lineage(self):
        """merge should extend lineage."""
        parent = Echo("parent")
        parent.add_lineage("parent_cell", "output1")

        child = Echo("child")
        child.add_lineage("child_cell", "output2")

        parent.merge(child)

        assert len(parent.lineage) == 2

    def test_merge_errors(self):
        """merge should extend errors."""
        parent = Echo("parent")

        child = Echo("child")
        child.add_error("child_cell", "Error", "message")

        parent.merge(child)

        assert len(parent.errors) == 1
        assert parent.errors[0]["cell"] == "child_cell"


class TestEchoContext:
    """Tests for Echo context setters."""

    def test_set_cascade_context(self):
        echo = Echo("test")

        echo.set_cascade_context("my_cascade")

        assert echo._current_cascade_id == "my_cascade"

    def test_set_cell_context(self):
        echo = Echo("test")

        echo.set_cell_context("my_cell")

        assert echo._current_cell_name == "my_cell"

    def test_set_message_callback(self):
        echo = Echo("test")
        callback = MagicMock()

        echo.set_message_callback(callback)

        assert echo._message_callback is callback


# =============================================================================
# SessionManager Tests
# =============================================================================

class TestSessionManager:
    """Tests for SessionManager singleton."""

    def test_creates_new_session(self):
        """Should create new Echo for unknown session_id."""
        manager = SessionManager()

        echo = manager.get_session("new_session_123")

        assert echo.session_id == "new_session_123"
        assert "new_session_123" in manager.sessions

    def test_reuses_existing_session(self):
        """Should return same Echo for known session_id."""
        manager = SessionManager()

        echo1 = manager.get_session("test_reuse")
        echo1.update_state("key", "value")

        echo2 = manager.get_session("test_reuse")

        assert echo1 is echo2
        assert echo2.state["key"] == "value"

    def test_updates_caller_id_on_reuse(self):
        """Should update caller_id when reusing session."""
        manager = SessionManager()

        echo1 = manager.get_session("test_caller", caller_id="caller1")
        assert echo1.caller_id == "caller1"

        echo2 = manager.get_session("test_caller", caller_id="caller2")
        assert echo2.caller_id == "caller2"

    def test_updates_invocation_metadata_on_reuse(self):
        """Should update invocation_metadata when reusing session."""
        manager = SessionManager()

        manager.get_session("test_meta", invocation_metadata={"v": 1})
        echo2 = manager.get_session("test_meta", invocation_metadata={"v": 2})

        assert echo2.invocation_metadata == {"v": 2}


# =============================================================================
# get_echo Module Function Tests
# =============================================================================

class TestGetEcho:
    """Tests for get_echo module-level function."""

    def test_returns_echo_instance(self):
        """Should return Echo instance from global manager."""
        echo = get_echo("global_test_session")

        assert isinstance(echo, Echo)
        assert echo.session_id == "global_test_session"

    def test_passes_through_parameters(self):
        """Should pass parameters to session manager."""
        echo = get_echo(
            "param_test",
            parent_session_id="parent",
            caller_id="caller",
            invocation_metadata={"test": True}
        )

        assert echo.parent_session_id == "parent"
        assert echo.caller_id == "caller"
        assert echo.invocation_metadata == {"test": True}
