"""
RVBBIT trait (tool) registration for browser automation.

These tools integrate with RVBBIT's cascade system, providing
browser automation capabilities to LLM agents.

Tools:
    - rabbitize_start: Start browser session
    - control_browser: Execute commands (click, type, scroll, etc.)
    - rabbitize_extract: Get page content as markdown
    - rabbitize_screenshot: Take a screenshot
    - rabbitize_close: Close session
"""

from typing import Optional, Union
import json
import asyncio
import logging

logger = logging.getLogger(__name__)

# Session storage for tools (separate from server sessions)
_active_sessions: dict = {}


def _get_caller_context():
    """Get caller context if available."""
    try:
        from rvbbit.caller_context import get_caller_context
        return get_caller_context()
    except ImportError:
        return None


def _get_current_state() -> dict:
    """Get current state from caller context."""
    ctx = _get_caller_context()
    if ctx and hasattr(ctx, 'state'):
        return ctx.state
    return {}


async def _get_session():
    """Get existing session from context or active sessions."""
    from rvbbit.browser.session import BrowserSession

    state = _get_current_state()

    # Check for session in state
    if "_browser_session" in state:
        return state["_browser_session"]

    # Check for session ID reference
    session_id = state.get("_browser_session_id")
    if session_id and session_id in _active_sessions:
        return _active_sessions[session_id]

    # Check for managed session (started by runner with HTTP server)
    if "_browser_port" in state:
        # Use HTTP client to talk to server
        port = state["_browser_port"]
        base_url = f"http://localhost:{port}"
        return HTTPSessionProxy(base_url, state.get("_browser_session_id"))

    # Check active sessions
    if _active_sessions:
        # Return most recent
        return list(_active_sessions.values())[-1]

    return None


class HTTPSessionProxy:
    """Proxy for talking to browser server via HTTP."""

    def __init__(self, base_url: str, session_id: Optional[str] = None):
        self.base_url = base_url
        self.session_id = session_id
        self.mouse_x = 0
        self.mouse_y = 0
        self.command_index = 0

    async def execute(self, command: list) -> dict:
        """Execute command via HTTP."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/execute",
                json={"command": command, "session_id": self.session_id},
                timeout=60.0,
            )
            result = response.json()
            self.command_index += 1

            # Update mouse position from result
            if "position" in result.get("result", {}):
                pos = result["result"]["position"]
                self.mouse_x, self.mouse_y = pos[0], pos[1]

            return result.get("result", result)

    async def extract_dom(self):
        """Extract DOM via HTTP."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/session/{self.session_id}/dom",
                timeout=30.0,
            )
            data = response.json()
            return data.get("markdown", ""), data.get("coords", {"elements": []})

    async def close(self) -> dict:
        """Close session via HTTP."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/end",
                json={"session_id": self.session_id},
                timeout=30.0,
            )
            return response.json().get("metadata", {})

    def get_latest_screenshot(self) -> Optional[str]:
        """Get screenshot path - not available via HTTP proxy."""
        return None


def register_browser_tools():
    """Register browser automation tools with RVBBIT."""
    try:
        from rvbbit import register_trait
    except ImportError:
        logger.warning("Could not import register_trait - tools not registered")
        return

    @register_trait("rabbitize_start")
    async def rabbitize_start(url: str, session_name: Optional[str] = None) -> dict:
        """
        Start a browser session and navigate to URL.

        This launches a headless Chromium browser, navigates to the specified URL,
        and captures an initial screenshot. The session remains active for subsequent
        commands until rabbitize_close() is called.

        Args:
            url: The URL to navigate to (e.g., "https://example.com")
            session_name: Optional name for the session (defaults to timestamp)

        Returns:
            dict with:
                - content: Status message
                - images: List of screenshot paths (initial page state)
                - session_id: The session identifier for subsequent commands

        Example:
            result = rabbitize_start("https://news.ycombinator.com")
            # Agent now sees screenshot of Hacker News homepage
        """
        from rvbbit.browser.session import BrowserSession
        from rvbbit.browser.streaming import frame_emitter

        state = _get_current_state()

        # Check if already have a session
        if "_browser_session" in state:
            existing = state["_browser_session"]
            return {
                "content": f"Browser session already active: {existing.session_id}\nUse rabbitize_close() first to start a new session.",
                "images": [existing.get_latest_screenshot()] if existing.get_latest_screenshot() else [],
                "session_id": existing.session_id,
            }

        # Create frame callback for streaming
        session_id_holder = [None]

        async def frame_callback(frame: bytes):
            if session_id_holder[0]:
                await frame_emitter.emit(session_id_holder[0], frame)

        # Create session - for interactive use, use session_name as cell_name
        session = BrowserSession(
            session_id="interactive",
            cell_name=session_name or "browser",
            frame_callback=frame_callback,
        )

        # Initialize
        try:
            result = await session.initialize(url)
        except Exception as e:
            await session.close()
            return {
                "content": f"Failed to start browser session: {str(e)}",
                "images": [],
                "error": str(e),
            }

        session_id_holder[0] = session.session_id

        # Store in state and active sessions
        state["_browser_session"] = session
        state["_browser_session_id"] = session.session_id
        state["_browser_artifacts"] = result["artifacts"]
        _active_sessions[session.session_id] = session

        # Wait for initial screenshot
        await asyncio.sleep(0.5)
        screenshot = session.get_latest_screenshot()

        return {
            "content": f"Browser session started: {session.session_id}\nNavigated to: {url}\n\nUse control_browser() to interact with the page.\nUse rabbitize_extract() to get page content and element positions.",
            "images": [screenshot] if screenshot else [],
            "session_id": session.session_id,
            "artifacts": result["artifacts"],
        }

    @register_trait("control_browser")
    async def control_browser(command: Union[str, list], include_metadata: bool = False) -> dict:
        """
        Execute a browser command (click, type, scroll, navigate).

        CRITICAL: To click on an element, you must FIRST move the mouse, THEN click:
        1. control_browser('[":move-mouse", ":to", 400, 300]')  # Position cursor
        2. control_browser('[":click"]')  # Click at cursor position

        Available commands:
        - [":move-mouse", ":to", x, y] - Move cursor to absolute position
        - [":click"] - Click at current cursor position
        - [":double-click"] - Double-click at current position
        - [":right-click"] - Right-click at current position
        - [":type", "text"] - Type text
        - [":keypress", "Enter"] - Press a key (Enter, Tab, Escape, etc.)
        - [":hotkey", "Control", "c"] - Press key combination
        - [":scroll-wheel-down", 3] - Scroll down (number of wheel clicks)
        - [":scroll-wheel-up", 3] - Scroll up
        - [":url", "https://..."] - Navigate to URL
        - [":back"] - Go back
        - [":forward"] - Go forward
        - [":wait", 2] - Wait N seconds
        - [":drag", ":from", x1, y1, ":to", x2, y2] - Drag from one point to another

        Args:
            command: JSON string or list representing the command
            include_metadata: If True, include DOM and coordinates in response

        Returns:
            dict with:
                - content: Status message
                - images: [pre_screenshot, post_screenshot] showing before/after state
                - result: Command execution result

        Example:
            # Click on a button at coordinates (400, 300)
            control_browser('[":move-mouse", ":to", 400, 300]')
            result = control_browser('[":click"]')
            # Agent sees pre-click and post-click screenshots

            # Type in a search box
            control_browser('[":type", "python tutorial"]')
            control_browser('[":keypress", "Enter"]')
        """
        session = await _get_session()
        if not session:
            return {
                "content": "No active browser session. Call rabbitize_start() first.",
                "images": [],
            }

        # Parse command if string
        if isinstance(command, str):
            try:
                command = json.loads(command)
            except json.JSONDecodeError as e:
                return {
                    "content": f"Invalid command JSON: {str(e)}",
                    "images": [],
                    "error": str(e),
                }

        # Get pre-screenshot
        pre_screenshot = session.get_latest_screenshot() if hasattr(session, 'get_latest_screenshot') else None

        # Execute command
        try:
            result = await session.execute(command)
        except Exception as e:
            return {
                "content": f"Command failed: {str(e)}",
                "images": [pre_screenshot] if pre_screenshot else [],
                "error": str(e),
            }

        # Get post-screenshot
        await asyncio.sleep(0.3)  # Brief pause for rendering
        post_screenshot = session.get_latest_screenshot() if hasattr(session, 'get_latest_screenshot') else None

        images = []
        if pre_screenshot:
            images.append(pre_screenshot)
        if post_screenshot and post_screenshot != pre_screenshot:
            images.append(post_screenshot)

        # Build response content
        action = command[0] if command else "unknown"
        success = result.get("success", True)
        status = "Success" if success else "Failed"

        response = {
            "content": f"{status}: {action}\nMouse position: ({session.mouse_x}, {session.mouse_y})",
            "images": images,
            "result": result,
        }

        if include_metadata:
            try:
                markdown, coords = await session.extract_dom()
                response["dom_markdown"] = markdown[:5000]
                response["dom_coords"] = coords
            except Exception as e:
                logger.warning(f"Failed to extract DOM: {e}")

        return response

    @register_trait("rabbitize_extract")
    async def rabbitize_extract() -> dict:
        """
        Extract page content as markdown and element coordinates.

        This returns:
        1. A markdown representation of the page content (headings, text, links)
        2. A list of clickable elements with their (x, y) coordinates

        Use this to understand the page structure and find click targets.

        Returns:
            dict with:
                - content: Truncated markdown summary
                - dom_markdown: Full markdown representation
                - dom_coords: {"elements": [...]} with clickable element positions
                - images: Current screenshot

        Example:
            result = rabbitize_extract()
            # result["dom_coords"]["elements"] contains:
            # [
            #   {"text": "Sign Up", "x": 400, "y": 300, "type": "button"},
            #   {"text": "Learn More", "x": 200, "y": 450, "type": "link"},
            #   ...
            # ]
        """
        session = await _get_session()
        if not session:
            return {
                "content": "No active browser session. Call rabbitize_start() first.",
                "dom_markdown": "",
                "dom_coords": {"elements": []},
                "images": [],
            }

        try:
            markdown, coords = await session.extract_dom()
        except Exception as e:
            return {
                "content": f"Failed to extract page content: {str(e)}",
                "dom_markdown": "",
                "dom_coords": {"elements": []},
                "images": [],
                "error": str(e),
            }

        screenshot = session.get_latest_screenshot() if hasattr(session, 'get_latest_screenshot') else None

        # Summarize elements for content
        elements = coords.get("elements", [])
        element_summary = f"Found {len(elements)} interactive elements."
        if elements:
            element_summary += "\n\nTop elements by position:"
            for el in elements[:10]:
                text = el.get("text", "")[:40] or el.get("placeholder", "")[:40] or f"({el.get('type', 'element')})"
                element_summary += f"\n  [{el.get('index', '?')}] {text} at ({el.get('x')}, {el.get('y')})"

        return {
            "content": f"{element_summary}\n\n---\n\n{markdown[:2000]}{'...' if len(markdown) > 2000 else ''}",
            "dom_markdown": markdown,
            "dom_coords": coords,
            "images": [screenshot] if screenshot else [],
        }

    @register_trait("rabbitize_screenshot")
    async def rabbitize_screenshot() -> dict:
        """
        Take a screenshot of the current browser state.

        Use this to see what the browser currently shows without executing any action.

        Returns:
            dict with:
                - content: Status message
                - images: [screenshot_path]
        """
        session = await _get_session()
        if not session:
            return {
                "content": "No active browser session.",
                "images": [],
            }

        # Force a fresh screenshot
        if hasattr(session, '_capture_screenshot'):
            await session._capture_screenshot("manual")

        screenshot = session.get_latest_screenshot() if hasattr(session, 'get_latest_screenshot') else None

        return {
            "content": f"Screenshot captured.\nMouse position: ({session.mouse_x}, {session.mouse_y})",
            "images": [screenshot] if screenshot else [],
        }

    @register_trait("rabbitize_close")
    async def rabbitize_close() -> dict:
        """
        Close the browser session and finalize recordings.

        This closes the browser, saves any video recordings, and cleans up resources.
        Call this when done with browser automation.

        Returns:
            dict with:
                - content: Status message
                - video_path: Path to recorded video (if recording was enabled)
                - metrics: Session statistics
        """
        state = _get_current_state()
        session = state.pop("_browser_session", None)
        session_id = state.pop("_browser_session_id", None)
        state.pop("_browser_artifacts", None)

        # Also check active sessions
        if not session and session_id:
            session = _active_sessions.pop(session_id, None)

        if not session:
            # Try to find any active session
            if _active_sessions:
                session_id = list(_active_sessions.keys())[-1]
                session = _active_sessions.pop(session_id)

        if not session:
            return {
                "content": "No active browser session to close.",
                "metrics": {},
            }

        try:
            metadata = await session.close()
        except Exception as e:
            return {
                "content": f"Error closing session: {str(e)}",
                "error": str(e),
                "metrics": {},
            }

        return {
            "content": f"Browser session closed.\nCommands executed: {metadata.get('command_count', 0)}",
            "video_path": metadata.get("video_path"),
            "metrics": metadata,
        }

    @register_trait("browser")
    async def browser(
        url: str,
        commands: Optional[list] = None,
        actions: Optional[list] = None,
        viewport: tuple = (1280, 720),
        headless: bool = True,
        record_video: bool = False,
        # Hidden inputs injected by deterministic executor
        _cell_name: Optional[str] = None,
        _session_id: Optional[str] = None,
        **_kwargs,  # Capture any extra inputs
    ) -> dict:
        """
        Native browser automation tool for cascades.

        Execute browser commands and capture artifacts (screenshots, DOM snapshots).
        This is the preferred way to do browser automation in cascades - it uses
        the Python API directly (no shell), auto-derives paths from cascade context,
        and returns artifacts as conversation_history for context flow.

        Args:
            url: The URL to navigate to (e.g., "https://example.com")
            commands: List of command arrays in DSL format, e.g.:
                - [":wait", 1]
                - [":screenshot"]
                - [":move-mouse", ":to", 400, 300]
                - [":click"]
                - [":type", "hello world"]
                - [":keypress", "Enter"]
            actions: Alternative declarative format (auto-converted to commands):
                - {wait: 1}
                - {screenshot: true}
                - {move: {x: 400, y: 300}}
                - {click: true}
                - {type: {text: "hello"}}
            viewport: Browser viewport size as (width, height), default (1280, 720)
            headless: Run browser in headless mode (default True)
            record_video: Enable video recording (default False)

        Returns:
            dict with:
                - success: bool
                - session_id: Browser session timestamp
                - url: URL visited
                - images: List of screenshot base64 data URLs
                - dom_snapshots: List of markdown DOM snapshots
                - dom_coords: List of element coordinate JSON strings
                - video: Path to video file (if recorded)
                - conversation_history: Multimodal messages for context system
                - _route: Next cell routing (always "success" for now)

        Example cascade:
            - name: scrape_page
              tool: browser
              inputs:
                url: "https://news.ycombinator.com"
                commands:
                  - [":wait", 1]
                  - [":screenshot"]
                  - [":scroll-wheel-down", 3]
                  - [":screenshot"]

            - name: analyze
              instructions: "Analyze these screenshots"
              context:
                from: ["scrape_page"]  # Gets multimodal images
        """
        from rvbbit.browser.session import BrowserSession
        from rvbbit.utils import encode_image_base64
        import glob

        # Use cascade session_id and cell_name directly
        # Path: browsers/<session_id>/<cell_name>/
        session_id = _session_id or "rvbbit"
        cell_name = _cell_name or "browser"

        # Convert actions to commands if provided
        if actions and not commands:
            commands = _convert_actions_to_commands(actions)

        # Default to just taking a screenshot if no commands
        if not commands:
            commands = [[":screenshot"]]

        # Create session
        session = BrowserSession(
            session_id=session_id,
            cell_name=cell_name,
            viewport=viewport,
            headless=headless,
            record_video=record_video,
        )

        result = {
            "success": True,
            "session_id": session.session_id,
            "url": url,
            "images": [],
            "dom_snapshots": [],
            "dom_coords": [],
            "video": None,
            "conversation_history": [],
            "_route": "success",
        }

        try:
            # Initialize and navigate
            await session.initialize(url)
            logger.info(f"[BROWSER] Session {session.session_id} initialized at {url}")

            # Execute commands
            for i, cmd in enumerate(commands):
                try:
                    logger.info(f"[BROWSER] Executing command {i}: {cmd}")
                    cmd_result = await session.execute(cmd)
                    logger.info(f"[BROWSER] Command {i} result: {cmd_result}")
                    if not cmd_result.get("success", True):
                        logger.warning(f"[BROWSER] Command {i} warning: {cmd_result.get('error', 'unknown')}")
                except Exception as e:
                    logger.warning(f"[BROWSER] Command {i} error: {e}")

            logger.info(f"[BROWSER] Completed {len(commands)} commands")

            # Load artifacts from session folder
            logger.info(f"[BROWSER] Session artifacts: {session.artifacts}")
            logger.info(f"[BROWSER] Artifacts base_path: {session.artifacts.base_path if session.artifacts else 'None'}")
            if session.artifacts:
                # Load screenshots as base64 data URLs
                screenshots_dir = session.artifacts.screenshots
                logger.info(f"[BROWSER] Screenshots dir: {screenshots_dir}, exists: {screenshots_dir.exists()}")
                if screenshots_dir.exists():
                    # Load all screenshot files (excluding intermediate captures like *-pre-move.jpg)
                    import re
                    screenshot_files = []
                    for ext in ['*.jpg', '*.jpeg', '*.png']:
                        screenshot_files.extend(glob.glob(str(screenshots_dir / ext)))
                    logger.info(f"[BROWSER] Found {len(screenshot_files)} screenshot files: {screenshot_files}")
                    # Filter out intermediate captures (contain hyphens like "0-pre-move.jpg")
                    # Keep numbered files (0.jpg, 1.jpg) and labeled files (manual.jpg, custom-label.jpg)
                    screenshot_files = [f for f in screenshot_files if not re.search(r'/\d+-\w+\.(jpg|jpeg|png)$', f)]
                    logger.info(f"[BROWSER] After filtering: {len(screenshot_files)} files: {screenshot_files}")
                    screenshot_files.sort()

                    for img_path in screenshot_files:
                        try:
                            data_url = encode_image_base64(img_path)
                            result["images"].append(data_url)
                        except Exception as e:
                            logger.warning(f"[BROWSER] Error loading {img_path}: {e}")

                # Load DOM snapshots
                dom_dir = session.artifacts.dom_snapshots
                if dom_dir.exists():
                    for md_path in sorted(glob.glob(str(dom_dir / "*.md"))):
                        try:
                            with open(md_path, 'r', encoding='utf-8') as f:
                                result["dom_snapshots"].append(f.read())
                        except Exception as e:
                            logger.warning(f"[BROWSER] Error loading DOM snapshot: {e}")

                # Load DOM coords
                coords_dir = session.artifacts.dom_coords
                if coords_dir.exists():
                    import re
                    coord_files = glob.glob(str(coords_dir / "*.json"))
                    # Filter to numbered files only
                    coord_files = [f for f in coord_files if re.search(r'/dom_coords_\d+\.json$', f)]
                    coord_files.sort()
                    for json_path in coord_files:
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f:
                                result["dom_coords"].append(f.read())
                        except Exception as e:
                            logger.warning(f"[BROWSER] Error loading coords: {e}")

                # Get video path if recorded
                if record_video and session.artifacts.video.exists():
                    video_files = list(session.artifacts.video.glob("*.webm"))
                    if video_files:
                        result["video"] = str(video_files[0])

            # Build conversation_history for context system
            # This makes artifacts flow through selective context like regular messages
            content = []
            content.append({
                "type": "text",
                "text": f"Browser session completed. Visited {url}. Captured {len(result['images'])} screenshots."
            })

            # Add each image as a multimodal content block
            for i, img_data_url in enumerate(result["images"]):
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img_data_url}
                })

            # Add DOM summaries as text (not full content - that would be too large)
            if result["dom_snapshots"]:
                # Just indicate DOM is available - full content in dom_snapshots array
                content.append({
                    "type": "text",
                    "text": f"\n{len(result['dom_snapshots'])} DOM snapshots available in dom_snapshots array."
                })

            result["conversation_history"] = [{"role": "assistant", "content": content}]

            # Artifacts info for reference
            result["artifacts"] = {
                "basePath": str(session.artifacts.base_path) if session.artifacts else None,
                "screenshots": str(session.artifacts.screenshots) if session.artifacts else None,
            }

        except Exception as e:
            logger.error(f"[BROWSER] Session error: {e}")
            result["success"] = False
            result["error"] = str(e)
            result["_route"] = "error"

        finally:
            # Close session
            try:
                await session.close()
            except Exception as e:
                logger.warning(f"[BROWSER] Error closing session: {e}")

        return result


    def _convert_actions_to_commands(actions: list) -> list:
        """
        Convert declarative actions format to command DSL.

        Actions format:
            - {wait: 1}
            - {screenshot: true}
            - {move: {x: 400, y: 300}}
            - {click: true}

        Commands format:
            - [":wait", 1]
            - [":screenshot"]
            - [":move-mouse", ":to", 400, 300]
            - [":click"]
        """
        commands = []

        for action in actions:
            if isinstance(action, dict):
                for key, value in action.items():
                    if key == "wait":
                        commands.append([":wait", value])
                    elif key == "screenshot":
                        if isinstance(value, str):
                            commands.append([":screenshot", value])
                        else:
                            commands.append([":screenshot"])
                    elif key in ("move", "move_mouse"):
                        if isinstance(value, dict):
                            commands.append([":move-mouse", ":to", value.get("x", 0), value.get("y", 0)])
                        elif isinstance(value, list) and len(value) >= 2:
                            commands.append([":move-mouse", ":to", value[0], value[1]])
                    elif key == "click":
                        commands.append([":click"])
                    elif key == "double_click":
                        commands.append([":double-click"])
                    elif key == "right_click":
                        commands.append([":right-click"])
                    elif key in ("type", "text"):
                        if isinstance(value, dict):
                            commands.append([":type", value.get("text", "")])
                        else:
                            commands.append([":type", str(value)])
                    elif key in ("keypress", "key"):
                        commands.append([":keypress", str(value)])
                    elif key == "hotkey":
                        if isinstance(value, list):
                            commands.append([":hotkey"] + value)
                    elif key == "scroll_down":
                        commands.append([":scroll-wheel-down", value if isinstance(value, int) else 3])
                    elif key == "scroll_up":
                        commands.append([":scroll-wheel-up", value if isinstance(value, int) else 3])
                    elif key in ("url", "navigate", "goto"):
                        commands.append([":url", str(value)])
                    elif key == "back":
                        commands.append([":back"])
                    elif key == "forward":
                        commands.append([":forward"])
                    elif key == "reload":
                        commands.append([":reload"])
                    elif key == "extract":
                        commands.append([":extract-page-to-markdown"])
                    elif key == "evaluate":
                        commands.append([":evaluate", str(value)])
                    elif key == "wait_for":
                        commands.append([":wait-for-selector", str(value)])
                    elif key == "drag":
                        if isinstance(value, dict):
                            commands.append([
                                ":drag", ":from",
                                value.get("from_x", 0), value.get("from_y", 0),
                                ":to",
                                value.get("to_x", 0), value.get("to_y", 0)
                            ])
                    else:
                        # Unknown action - try to pass through as command
                        logger.warning(f"[BROWSER] Unknown action: {key}")
            elif isinstance(action, list):
                # Already a command, pass through
                commands.append(action)

        return commands

    logger.info("Browser automation tools registered")


# Auto-register tools when module is imported
try:
    register_browser_tools()
except Exception as e:
    logger.debug(f"Could not auto-register browser tools: {e}")
