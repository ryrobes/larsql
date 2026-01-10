"""
RVBBIT Browser Automation Module

Pure Python browser automation using Playwright, with MJPEG streaming support.

Installation:
    pip install rvbbit[browser]
    playwright install chromium

Usage:
    # Direct Python API
    from rvbbit.browser import BrowserSession

    async with BrowserSession(session_id="my_session", cell_name="browser_1") as session:
        await session.initialize("https://example.com")
        await session.execute([":move-mouse", ":to", 400, 300])
        await session.execute([":click"])
        markdown, coords = await session.extract_dom()

    # HTTP Server (for MJPEG streaming)
    from rvbbit.browser import start_server
    start_server(port=3037)

    # Or via CLI
    # rvbbit browser serve --port 3037

The module provides tools that integrate with RVBBIT cascades:
    - rabbitize_start: Start browser session
    - control_browser: Execute commands (click, type, scroll, etc.)
    - rabbitize_extract: Get page content as markdown
    - rabbitize_screenshot: Take a screenshot
    - rabbitize_close: Close session

Command DSL:
    Commands are JSON arrays with action + arguments:

    Mouse:
        [":move-mouse", ":to", x, y]  - Move to absolute position
        [":click"]                     - Click at current position
        [":double-click"]              - Double-click
        [":right-click"]               - Right-click
        [":drag", ":from", x1, y1, ":to", x2, y2]  - Drag

    Keyboard:
        [":type", "text"]              - Type text
        [":keypress", "Enter"]         - Press key
        [":hotkey", "Control", "c"]    - Key combination

    Scrolling:
        [":scroll-wheel-down", 3]      - Scroll down
        [":scroll-wheel-up", 3]        - Scroll up

    Navigation:
        [":url", "https://..."]        - Navigate to URL
        [":back"]                       - Go back
        [":forward"]                    - Go forward
        [":reload"]                     - Reload page

    Utilities:
        [":wait", 2]                   - Wait N seconds
        [":screenshot"]                - Take screenshot
        [":extract-page-to-markdown"]  - Extract DOM
"""

__version__ = "1.0.0"

# Lazy imports to avoid requiring all dependencies at module load time
_session_module = None
_server_module = None
_streaming_module = None


def _get_session_module():
    global _session_module
    if _session_module is None:
        from rvbbit.browser import session as _session_module
    return _session_module


def _get_server_module():
    global _server_module
    if _server_module is None:
        from rvbbit.browser import server as _server_module
    return _server_module


def _get_streaming_module():
    global _streaming_module
    if _streaming_module is None:
        from rvbbit.browser import streaming as _streaming_module
    return _streaming_module


# Lazy class/function accessors
class BrowserSession:
    """
    Manages a single Playwright browser session.

    See module docstring for usage examples.
    """

    def __new__(cls, *args, **kwargs):
        mod = _get_session_module()
        return mod.BrowserSession(*args, **kwargs)


def start_server(host: str = "0.0.0.0", port: int = 3037, log_level: str = "info"):
    """Start the browser automation server."""
    mod = _get_server_module()
    return mod.start_server(host=host, port=port, log_level=log_level)


async def start_server_async(host: str = "0.0.0.0", port: int = 3037):
    """Start server asynchronously."""
    mod = _get_server_module()
    return await mod.start_server_async(host=host, port=port)


def get_app():
    """Get the FastAPI application."""
    mod = _get_server_module()
    return mod.get_app()


# Expose key classes and functions
def __getattr__(name):
    """Lazy loading of module attributes."""
    # Session module
    if name in ("BrowserSession", "create_session"):
        mod = _get_session_module()
        return getattr(mod, name)

    # Server module
    if name in ("start_server", "start_server_async", "get_app", "sessions"):
        mod = _get_server_module()
        return getattr(mod, name)

    # Streaming module
    if name in ("frame_emitter", "mjpeg_generator", "FrameEmitter"):
        mod = _get_streaming_module()
        return getattr(mod, name)

    # Commands module
    if name in ("execute_command", "HANDLERS", "get_available_commands"):
        from rvbbit.browser import commands
        return getattr(commands, name)

    # Stability module
    if name in ("StabilityDetector", "create_stability_detector"):
        from rvbbit.browser import stability
        return getattr(stability, name)

    # DOM extractor module
    if name in ("extract_dom", "extract_text_only", "extract_links", "find_element_at", "find_element_by_text"):
        from rvbbit.browser import dom_extractor
        return getattr(dom_extractor, name)

    # Artifacts module
    if name in ("ArtifactManager", "SessionArtifacts", "get_browsers_directory", "get_runs_directory", "list_sessions"):
        from rvbbit.browser import artifacts
        return getattr(artifacts, name)

    raise AttributeError(f"module 'rvbbit.browser' has no attribute '{name}'")


# Define __all__ for IDE support and documentation
__all__ = [
    # Version
    "__version__",
    # Core
    "BrowserSession",
    "create_session",
    "execute_command",
    "HANDLERS",
    "get_available_commands",
    # Server
    "start_server",
    "start_server_async",
    "get_app",
    "sessions",
    # Streaming
    "frame_emitter",
    "mjpeg_generator",
    "FrameEmitter",
    # Components
    "StabilityDetector",
    "create_stability_detector",
    "extract_dom",
    "extract_text_only",
    "extract_links",
    "find_element_at",
    "find_element_by_text",
    "ArtifactManager",
    "SessionArtifacts",
    # Utilities
    "get_browsers_directory",
    "get_runs_directory",  # Deprecated alias
    "list_sessions",
]


# Try to register tools on import
def _register_tools():
    try:
        from rvbbit.browser import tools  # noqa: F401
    except ImportError:
        pass  # Tools will be registered when rvbbit is available


_register_tools()
