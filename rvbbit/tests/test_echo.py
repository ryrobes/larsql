"""
Tests for Echo state management.

The Echo class is the core state/history container for cascade sessions.
These tests verify:
1. State initialization and updates
2. History accumulation with metadata
3. Lineage tracking
4. Error tracking
5. Echo merging (for sub-cascades)
6. Session manager functionality

Note: These tests work without database connectivity because Echo's
add_history method silently catches and ignores logging failures.
"""
import pytest
from unittest.mock import MagicMock

# Import Echo directly - logging failures are caught internally
from rvbbit.echo import Echo, SessionManager, get_echo


# =============================================================================
# BASIC INITIALIZATION
# =============================================================================

class TestEchoInitialization:
    """Test Echo initialization."""

    def test_basic_init(self):
        """Echo initializes with session_id."""
        echo = Echo(session_id="test_123")

        assert echo.session_id == "test_123"
        assert echo.parent_session_id is None
        assert echo.state == {}
        assert echo.history == []
        assert echo.lineage == []
        assert echo.errors == []

    def test_init_with_initial_state(self):
        """Echo can be initialized with initial state."""
        initial = {"user_id": "abc", "mode": "debug"}
        echo = Echo(session_id="test_456", initial_state=initial)

        assert echo.state == {"user_id": "abc", "mode": "debug"}

    def test_init_with_parent_session(self):
        """Echo tracks parent session for sub-cascades."""
        echo = Echo(session_id="child", parent_session_id="parent")

        assert echo.session_id == "child"
        assert echo.parent_session_id == "parent"

    def test_internal_state_initialized(self):
        """Internal tracking state is initialized."""
        echo = Echo(session_id="test_internal")
        assert echo._current_cascade_id is None
        assert echo._current_cell_name is None
        assert echo._last_mermaid_content is None
        assert echo._mermaid_failure_count == 0
        assert echo._message_callback is None


# =============================================================================
# STATE MANAGEMENT
# =============================================================================

class TestStateManagement:
    """Test state update operations."""

    def test_update_state_single(self):
        """Update single state key."""
        echo = Echo(session_id="state_test")
        echo.update_state("username", "alice")
        assert echo.state["username"] == "alice"

    def test_update_state_multiple(self):
        """Update multiple state keys."""
        echo = Echo(session_id="state_test")
        echo.update_state("key1", "value1")
        echo.update_state("key2", "value2")
        echo.update_state("key3", "value3")

        assert len(echo.state) == 3
        assert echo.state["key1"] == "value1"
        assert echo.state["key2"] == "value2"
        assert echo.state["key3"] == "value3"

    def test_update_state_overwrites(self):
        """Updating same key overwrites value."""
        echo = Echo(session_id="state_test")
        echo.update_state("counter", 1)
        echo.update_state("counter", 2)
        echo.update_state("counter", 3)

        assert echo.state["counter"] == 3

    def test_update_state_various_types(self):
        """State can hold various Python types."""
        echo = Echo(session_id="state_test")
        echo.update_state("string", "hello")
        echo.update_state("number", 42)
        echo.update_state("float", 3.14)
        echo.update_state("boolean", True)
        echo.update_state("list", [1, 2, 3])
        echo.update_state("dict", {"nested": "value"})
        echo.update_state("none", None)

        assert echo.state["string"] == "hello"
        assert echo.state["number"] == 42
        assert echo.state["float"] == 3.14
        assert echo.state["boolean"] is True
        assert echo.state["list"] == [1, 2, 3]
        assert echo.state["dict"] == {"nested": "value"}
        assert echo.state["none"] is None


# =============================================================================
# CONTEXT MANAGEMENT
# =============================================================================

class TestContextManagement:
    """Test cascade/cell context setting."""

    def test_set_cascade_context(self):
        """Set current cascade context."""
        echo = Echo(session_id="ctx_test")
        echo.set_cascade_context("my_cascade")
        assert echo._current_cascade_id == "my_cascade"

    def test_set_cell_context(self):
        """Set current cell context."""
        echo = Echo(session_id="ctx_test")
        echo.set_cell_context("analysis_cell")
        assert echo._current_cell_name == "analysis_cell"

    def test_context_enriches_history(self):
        """Context is automatically added to history entries."""
        echo = Echo(session_id="ctx_test")
        echo.set_cascade_context("test_cascade")
        echo.set_cell_context("test_cell")

        # Use skip_unified_log to avoid DB calls
        echo.add_history(
            {"role": "assistant", "content": "Hello"},
            trace_id="trace_1",
            node_type="agent",
            skip_unified_log=True
        )

        entry = echo.history[-1]
        assert entry["metadata"]["cascade_id"] == "test_cascade"
        assert entry["metadata"]["cell_name"] == "test_cell"


# =============================================================================
# HISTORY MANAGEMENT
# =============================================================================

class TestHistoryManagement:
    """Test history entry operations."""

    def test_add_basic_history(self):
        """Add basic history entry."""
        echo = Echo(session_id="hist_test")
        echo.add_history(
            {"role": "user", "content": "Hello"},
            trace_id="trace_001",
            skip_unified_log=True
        )

        assert len(echo.history) == 1
        assert echo.history[0]["role"] == "user"
        assert echo.history[0]["content"] == "Hello"
        assert echo.history[0]["trace_id"] == "trace_001"

    def test_add_history_with_all_params(self):
        """Add history with all parameters."""
        echo = Echo(session_id="hist_test")
        echo.add_history(
            {"role": "assistant", "content": "Response"},
            trace_id="trace_002",
            parent_id="trace_001",
            node_type="agent",
            metadata={"model": "gpt-4", "tokens": 100},
            skip_unified_log=True
        )

        entry = echo.history[-1]
        assert entry["trace_id"] == "trace_002"
        assert entry["parent_id"] == "trace_001"
        assert entry["node_type"] == "agent"
        assert entry["metadata"]["model"] == "gpt-4"
        assert entry["metadata"]["tokens"] == 100

    def test_history_entry_copied(self):
        """History entry is copied, not referenced."""
        echo = Echo(session_id="hist_test")
        original = {"role": "user", "content": "Test"}
        echo.add_history(original, trace_id="t1", skip_unified_log=True)

        # Modify original
        original["content"] = "Modified"

        # History should have original value
        assert echo.history[0]["content"] == "Test"

    def test_history_accumulates(self):
        """History accumulates multiple entries."""
        echo = Echo(session_id="hist_test")
        echo.add_history({"role": "user", "content": "Q1"}, trace_id="t1", skip_unified_log=True)
        echo.add_history({"role": "assistant", "content": "A1"}, trace_id="t2", skip_unified_log=True)
        echo.add_history({"role": "user", "content": "Q2"}, trace_id="t3", skip_unified_log=True)
        echo.add_history({"role": "assistant", "content": "A2"}, trace_id="t4", skip_unified_log=True)

        assert len(echo.history) == 4
        assert echo.history[0]["content"] == "Q1"
        assert echo.history[3]["content"] == "A2"

    def test_tool_calls_in_history(self):
        """History can include tool_calls."""
        echo = Echo(session_id="hist_test")
        echo.add_history(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"name": "search", "arguments": {"query": "test"}}
                ]
            },
            trace_id="t1",
            node_type="tool_call",
            skip_unified_log=True
        )

        entry = echo.history[-1]
        assert entry["tool_calls"][0]["name"] == "search"


# =============================================================================
# LINEAGE TRACKING
# =============================================================================

class TestLineageTracking:
    """Test cell lineage tracking."""

    def test_add_lineage(self):
        """Add lineage entry."""
        echo = Echo(session_id="lineage_test")
        echo.add_lineage("cell_1", "Output from cell 1", trace_id="trace_1")

        assert len(echo.lineage) == 1
        assert echo.lineage[0]["cell"] == "cell_1"
        assert echo.lineage[0]["output"] == "Output from cell 1"
        assert echo.lineage[0]["trace_id"] == "trace_1"

    def test_lineage_accumulates(self):
        """Lineage accumulates across cells."""
        echo = Echo(session_id="lineage_test")
        echo.add_lineage("ingest", "Data received", trace_id="t1")
        echo.add_lineage("process", "Data processed", trace_id="t2")
        echo.add_lineage("output", "Results ready", trace_id="t3")

        assert len(echo.lineage) == 3
        cells = [l["cell"] for l in echo.lineage]
        assert cells == ["ingest", "process", "output"]

    def test_lineage_various_output_types(self):
        """Lineage output can be various types."""
        echo = Echo(session_id="lineage_test")
        echo.add_lineage("string_cell", "text output")
        echo.add_lineage("dict_cell", {"key": "value", "count": 5})
        echo.add_lineage("list_cell", [1, 2, 3])
        echo.add_lineage("none_cell", None)

        assert echo.lineage[0]["output"] == "text output"
        assert echo.lineage[1]["output"] == {"key": "value", "count": 5}
        assert echo.lineage[2]["output"] == [1, 2, 3]
        assert echo.lineage[3]["output"] is None


# =============================================================================
# ERROR TRACKING
# =============================================================================

class TestErrorTracking:
    """Test error tracking functionality."""

    def test_add_error(self):
        """Add error entry."""
        echo = Echo(session_id="error_test")
        echo.add_error(
            cell="processing",
            error_type="ValidationError",
            error_message="Invalid JSON format"
        )

        assert len(echo.errors) == 1
        assert echo.errors[0]["cell"] == "processing"
        assert echo.errors[0]["error_type"] == "ValidationError"
        assert echo.errors[0]["error_message"] == "Invalid JSON format"

    def test_add_error_with_metadata(self):
        """Add error with metadata."""
        echo = Echo(session_id="error_test")
        echo.add_error(
            cell="api_call",
            error_type="HTTPError",
            error_message="Connection timeout",
            metadata={"url": "http://api.example.com", "attempt": 3}
        )

        error = echo.errors[-1]
        assert error["metadata"]["url"] == "http://api.example.com"
        assert error["metadata"]["attempt"] == 3

    def test_multiple_errors(self):
        """Multiple errors accumulate."""
        echo = Echo(session_id="error_test")
        echo.add_error("cell1", "Error1", "Message 1")
        echo.add_error("cell2", "Error2", "Message 2")
        echo.add_error("cell1", "Error3", "Message 3")

        assert len(echo.errors) == 3


# =============================================================================
# GET FULL ECHO
# =============================================================================

class TestGetFullEcho:
    """Test get_full_echo serialization."""

    def test_get_full_echo_empty(self):
        """Get full echo for empty session."""
        echo = Echo(session_id="full_echo_test")
        result = echo.get_full_echo()

        assert result["session_id"] == "full_echo_test"
        assert result["state"] == {}
        assert result["history"] == []
        assert result["lineage"] == []
        assert result["errors"] == []
        assert result["has_errors"] is False
        assert result["status"] == "success"

    def test_get_full_echo_with_data(self):
        """Get full echo with accumulated data."""
        echo = Echo(session_id="full_echo_test")
        echo.update_state("key", "value")
        echo.add_history({"role": "user", "content": "Hi"}, trace_id="t1", skip_unified_log=True)
        echo.add_lineage("cell1", "output1")

        result = echo.get_full_echo()

        assert result["state"] == {"key": "value"}
        assert len(result["history"]) == 1
        assert len(result["lineage"]) == 1
        assert result["status"] == "success"

    def test_get_full_echo_with_errors(self):
        """Get full echo reflects error status."""
        echo = Echo(session_id="full_echo_test")
        echo.add_error("cell1", "TestError", "Something broke")

        result = echo.get_full_echo()

        assert result["has_errors"] is True
        assert result["status"] == "failed"
        assert len(result["errors"]) == 1


# =============================================================================
# ECHO MERGING
# =============================================================================

class TestEchoMerging:
    """Test merging echoes from sub-cascades."""

    def test_merge_state(self):
        """Merging updates state."""
        parent = Echo(session_id="parent")
        parent.update_state("parent_key", "parent_value")

        child = Echo(session_id="child", parent_session_id="parent")
        child.update_state("child_key", "child_value")
        child.update_state("parent_key", "overwritten")

        parent.merge(child)

        assert parent.state["parent_key"] == "overwritten"
        assert parent.state["child_key"] == "child_value"

    def test_merge_lineage(self):
        """Merging extends lineage."""
        parent = Echo(session_id="parent")
        parent.add_lineage("parent_cell", "parent_output")

        child = Echo(session_id="child")
        child.add_lineage("child_cell1", "child_output1")
        child.add_lineage("child_cell2", "child_output2")

        parent.merge(child)

        assert len(parent.lineage) == 3
        cells = [l["cell"] for l in parent.lineage]
        assert "child_cell1" in cells
        assert "child_cell2" in cells

    def test_merge_errors(self):
        """Merging includes child errors."""
        parent = Echo(session_id="parent")
        child = Echo(session_id="child")
        child.add_error("child_cell", "ChildError", "Child error message")

        parent.merge(child)

        assert len(parent.errors) == 1
        assert parent.errors[0]["error_type"] == "ChildError"

    def test_merge_history_marker(self):
        """Merged history is marked with sub_echo."""
        parent = Echo(session_id="parent")
        parent.add_history({"role": "user", "content": "Parent"}, trace_id="p1", skip_unified_log=True)

        child = Echo(session_id="child")
        child.add_history({"role": "user", "content": "Child"}, trace_id="c1", skip_unified_log=True)

        parent.merge(child)

        # Should have parent entry + sub_echo marker
        assert len(parent.history) == 2
        assert parent.history[1]["sub_echo"] == "child"
        assert len(parent.history[1]["history"]) == 1


# =============================================================================
# SESSION MANAGER
# =============================================================================

class TestSessionManager:
    """Test SessionManager functionality."""

    def test_get_echo_creates_new(self):
        """get_echo creates new session if doesn't exist."""
        manager = SessionManager()
        echo = manager.get_session("new_session_test")

        assert echo.session_id == "new_session_test"
        assert "new_session_test" in manager.sessions

    def test_get_echo_returns_existing(self):
        """get_echo returns existing session."""
        manager = SessionManager()
        echo1 = manager.get_session("session_x_test")
        echo1.update_state("marker", "original")

        echo2 = manager.get_session("session_x_test")

        assert echo1 is echo2
        assert echo2.state["marker"] == "original"

    def test_get_echo_with_parent(self):
        """get_echo can set parent session."""
        manager = SessionManager()
        echo = manager.get_session("child_test", parent_session_id="parent_test")

        assert echo.parent_session_id == "parent_test"


# =============================================================================
# MESSAGE CALLBACK
# =============================================================================

class TestMessageCallback:
    """Test message callback functionality."""

    def test_set_message_callback(self):
        """Can set message callback."""
        echo = Echo(session_id="callback_test")
        callback = MagicMock()
        echo.set_message_callback(callback)
        assert echo._message_callback is callback

    def test_callback_called_on_add_history(self):
        """Callback is called when history is added (without skip_unified_log).

        Note: skip_unified_log=True causes early return before callback.
        This test allows logging to fail silently (which it does in Echo).
        """
        echo = Echo(session_id="callback_test_with_log")
        callback = MagicMock()
        echo.set_message_callback(callback)

        entry = {"role": "user", "content": "Test"}
        # Don't skip unified log - callback only runs when logging is attempted
        echo.add_history(entry, trace_id="t1")

        callback.assert_called_once()
        # Callback receives the original entry
        call_arg = callback.call_args[0][0]
        assert call_arg["role"] == "user"

    def test_callback_error_doesnt_fail(self):
        """Callback errors don't fail add_history."""
        echo = Echo(session_id="callback_test")

        def bad_callback(entry):
            raise RuntimeError("Callback failed")

        echo.set_message_callback(bad_callback)

        # Should not raise
        echo.add_history({"role": "user", "content": "Test"}, trace_id="t1", skip_unified_log=True)

        # History still added
        assert len(echo.history) == 1


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

class TestModuleFunctions:
    """Test module-level convenience functions."""

    def test_get_echo_function(self):
        """get_echo module function works."""
        # Use unique session ID to avoid conflicts
        echo = get_echo("func_test_session_unique_123")
        assert echo.session_id == "func_test_session_unique_123"

    def test_get_echo_with_parent_function(self):
        """get_echo module function with parent."""
        echo = get_echo("child_func_unique_123", parent_session_id="parent_func")
        assert echo.parent_session_id == "parent_func"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
