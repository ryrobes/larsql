"""
Tests for Rabbitize browser integration.

These tests validate:
1. BrowserConfig model validation
2. BrowserSession lifecycle (start, execute, end, close)
3. Integration with echo.state for managed sessions
4. Cascade phase browser config parsing

Note: Full cascade tests require LLM calls and are more suited for
integration/snapshot tests rather than unit tests.

Async operations are wrapped with asyncio.run() for pytest compatibility.
"""
import pytest
import asyncio
from pydantic import ValidationError

from windlass.cascade import (
    BrowserConfig,
    PhaseConfig,
    CascadeConfig,
    load_cascade_config,
)
from windlass.browser_manager import (
    BrowserSession,
    BrowserSessionManager,
    BrowserArtifacts,
    create_browser_session,
    close_browser_session,
    get_browser_manager,
)


# ─────────────────────────────────────────────────────────────────────────────
# BrowserConfig Model Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserConfigModel:
    """Test BrowserConfig Pydantic model validation."""

    def test_minimal_config(self):
        """URL is the only required field."""
        config = BrowserConfig(url="https://example.com")
        assert config.url == "https://example.com"
        assert config.stability_detection is False
        assert config.stability_wait == 3.0
        assert config.show_overlay is True
        assert config.inject_dom_coords is False
        assert config.auto_screenshot_context is True

    def test_full_config(self):
        """All fields can be specified."""
        config = BrowserConfig(
            url="https://example.com",
            stability_detection=True,
            stability_wait=5.0,
            show_overlay=False,
            inject_dom_coords=True,
            auto_screenshot_context=False
        )
        assert config.stability_detection is True
        assert config.stability_wait == 5.0
        assert config.show_overlay is False
        assert config.inject_dom_coords is True
        assert config.auto_screenshot_context is False

    def test_jinja_template_url(self):
        """URL can contain Jinja2 templates."""
        config = BrowserConfig(url="{{ input.url }}")
        assert config.url == "{{ input.url }}"

    def test_missing_url_raises(self):
        """URL is required."""
        with pytest.raises(ValidationError):
            BrowserConfig()


class TestPhaseWithBrowserConfig:
    """Test phase configuration with browser settings."""

    def test_phase_with_browser(self):
        """Phase can have browser config."""
        phase = PhaseConfig(
            name="browse_phase",
            instructions="Browse the web",
            browser=BrowserConfig(url="https://example.com")
        )
        assert phase.browser is not None
        assert phase.browser.url == "https://example.com"

    def test_phase_without_browser(self):
        """Phase can omit browser config (default None)."""
        phase = PhaseConfig(
            name="no_browser_phase",
            instructions="Do something else"
        )
        assert phase.browser is None

    def test_cascade_with_browser_phase(self):
        """Cascade can have phases with browser config."""
        cascade_json = {
            "cascade_id": "browser_test",
            "phases": [
                {
                    "name": "browse",
                    "instructions": "Browse",
                    "browser": {
                        "url": "https://example.com",
                        "stability_detection": True
                    }
                }
            ]
        }
        cascade = CascadeConfig(**cascade_json)
        assert cascade.phases[0].browser is not None
        assert cascade.phases[0].browser.stability_detection is True


# ─────────────────────────────────────────────────────────────────────────────
# BrowserSession Tests (sync wrappers for async tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserSession:
    """Test BrowserSession lifecycle."""

    @pytest.fixture
    def session(self):
        """Create a test session."""
        return BrowserSession(session_id="pytest_session", port=13999)

    def test_session_creation(self, session):
        """Session is created with correct attributes."""
        assert session.session_id == "pytest_session"
        assert session.port == 13999
        assert session.base_url == "http://localhost:13999"
        assert session.process is None
        assert session.is_alive is False

    def test_session_lifecycle(self):
        """Test full session lifecycle: start -> initialize -> end -> close."""
        async def _test():
            session = BrowserSession(session_id="lifecycle_test", port=13998)

            try:
                # Start server
                await session.start_server(
                    stability_detection=False,
                    show_overlay=False
                )
                assert session.is_alive is True

                # Health check
                health = await session.health()
                assert health.get("status") == "ok"

                # Initialize with URL
                result = await session.initialize("https://example.com")
                assert result.get("success") is True
                assert session.artifacts is not None

                # Execute a simple command
                scroll_result = await session.scroll_down(1)
                assert scroll_result.get("success") is True

                # End session
                end_result = await session.end()
                assert end_result.get("success") is True

            finally:
                # Always close
                await session.close()
                assert session.is_alive is False

        asyncio.run(_test())

    def test_session_artifacts(self):
        """Test that artifacts are populated after initialization."""
        async def _test():
            session = BrowserSession(session_id="artifacts_test", port=13997)

            try:
                await session.start_server()
                result = await session.initialize("https://example.com")

                assert session.artifacts is not None
                assert "screenshots" in session.artifacts.screenshots
                assert "video.webm" in session.artifacts.video

            finally:
                await session.end()
                await session.close()

        asyncio.run(_test())


class TestBrowserSessionManager:
    """Test BrowserSessionManager for managing multiple sessions."""

    def test_create_and_close_session(self):
        """Manager can create and close sessions."""
        async def _test():
            manager = BrowserSessionManager(port_range_start=13900, port_range_end=13910)

            session = await manager.create_session("manager_test")
            assert "manager_test" in manager.list_sessions()
            assert session.is_alive is True

            await manager.close_session("manager_test")
            assert "manager_test" not in manager.list_sessions()

        asyncio.run(_test())

    def test_port_allocation(self):
        """Manager allocates unique ports for each session."""
        async def _test():
            manager = BrowserSessionManager(port_range_start=13880, port_range_end=13890)

            session1 = await manager.create_session("port_test_1")
            session2 = await manager.create_session("port_test_2")

            try:
                assert session1.port != session2.port
                assert 13880 <= session1.port < 13890
                assert 13880 <= session2.port < 13890
            finally:
                await manager.close_all()

        asyncio.run(_test())

    def test_close_all(self):
        """Manager can close all sessions at once."""
        async def _test():
            manager = BrowserSessionManager(port_range_start=13860, port_range_end=13880)

            await manager.create_session("close_all_1")
            await manager.create_session("close_all_2")

            assert len(manager) == 2

            await manager.close_all()

            assert len(manager) == 0

        asyncio.run(_test())


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Function Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_create_browser_session(self):
        """create_browser_session creates a session via global manager."""
        async def _test():
            session = await create_browser_session("convenience_test")

            try:
                assert session.is_alive is True
                manager = get_browser_manager()
                assert "convenience_test" in manager.list_sessions()
            finally:
                await close_browser_session("convenience_test")

        asyncio.run(_test())

    def test_get_browser_manager_singleton(self):
        """get_browser_manager returns the same instance."""
        manager1 = get_browser_manager()
        manager2 = get_browser_manager()
        assert manager1 is manager2


# ─────────────────────────────────────────────────────────────────────────────
# Integration Tests (require Rabbitize server)
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserCommands:
    """Test browser command execution."""

    def test_click_command(self):
        """Test click convenience method."""
        async def _test():
            session = BrowserSession(session_id="click_test", port=13850)

            try:
                await session.start_server()
                await session.initialize("https://example.com")

                # Click at specific coordinates
                result = await session.click(100, 100)
                assert result.get("success") is True

            finally:
                await session.end()
                await session.close()

        asyncio.run(_test())

    def test_type_command(self):
        """Test type_text convenience method."""
        async def _test():
            session = BrowserSession(session_id="type_test", port=13849)

            try:
                await session.start_server()
                await session.initialize("https://example.com")

                result = await session.type_text("Hello World")
                assert result.get("success") is True

            finally:
                await session.end()
                await session.close()

        asyncio.run(_test())

    def test_navigate_command(self):
        """Test navigate convenience method."""
        async def _test():
            session = BrowserSession(session_id="nav_test", port=13848)

            try:
                await session.start_server()
                await session.initialize("https://example.com")

                result = await session.navigate("https://httpbin.org/html")
                assert result.get("success") is True

            finally:
                await session.end()
                await session.close()

        asyncio.run(_test())


# ─────────────────────────────────────────────────────────────────────────────
# Cascade File Loading Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserCascadeLoading:
    """Test loading cascade files with browser config."""

    def test_load_browser_demo(self, tmp_path):
        """Load the browser_demo.json example cascade."""
        cascade_json = {
            "cascade_id": "browser_demo",
            "description": "Test browser demo",
            "inputs_schema": {"url": "URL to browse"},
            "phases": [
                {
                    "name": "browse",
                    "instructions": "Browse {{ input.url }}",
                    "browser": {
                        "url": "{{ input.url }}",
                        "stability_detection": True,
                        "stability_wait": 2.0
                    },
                    "tackle": ["control_browser"],
                    "rules": {"max_turns": 5}
                }
            ]
        }

        import json
        config_file = tmp_path / "test_cascade.json"
        config_file.write_text(json.dumps(cascade_json))

        cascade = load_cascade_config(str(config_file))

        assert cascade.cascade_id == "browser_demo"
        assert cascade.phases[0].browser is not None
        assert cascade.phases[0].browser.url == "{{ input.url }}"
        assert cascade.phases[0].browser.stability_detection is True
        assert cascade.phases[0].browser.stability_wait == 2.0
