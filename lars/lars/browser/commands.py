"""
Command handlers for browser automation.

Implements the command DSL for controlling the browser:
- Mouse: move, click, drag, scroll
- Keyboard: type, keypress, hotkey
- Navigation: url, back, forward, reload
- Utilities: wait, extract
"""

from typing import Protocol, TYPE_CHECKING, Any, Dict, List
import asyncio
import logging

if TYPE_CHECKING:
    from lars.browser.session import BrowserSession

logger = logging.getLogger(__name__)


class CommandHandler(Protocol):
    """Protocol for command handlers."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        ...


class MoveMouseHandler:
    """
    Handle :move-mouse command.

    Usage:
        [":move-mouse", ":to", x, y]  - Move to absolute position
        [":move-mouse", ":by", dx, dy] - Move by relative offset
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        mode = args[1] if len(args) > 1 else ":to"

        if mode == ":to":
            session.mouse_x = int(args[2])
            session.mouse_y = int(args[3])
        elif mode == ":by":
            session.mouse_x += int(args[2])
            session.mouse_y += int(args[3])
        else:
            # Direct coordinates: [":move-mouse", x, y]
            session.mouse_x = int(args[1])
            session.mouse_y = int(args[2])

        await session.page.mouse.move(session.mouse_x, session.mouse_y)
        return {"success": True, "position": [session.mouse_x, session.mouse_y]}


class ClickHandler:
    """
    Handle :click command.

    Usage:
        [":click"]              - Left click at current position
        [":click", "right"]     - Right click
        [":click", "middle"]    - Middle click
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        button = "left"
        if len(args) > 1 and args[1] in ["left", "right", "middle"]:
            button = args[1]

        await session.page.mouse.click(
            session.mouse_x, session.mouse_y, button=button
        )
        return {
            "success": True,
            "button": button,
            "position": [session.mouse_x, session.mouse_y],
        }


class DoubleClickHandler:
    """Handle :double-click command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.mouse.dblclick(session.mouse_x, session.mouse_y)
        return {"success": True, "position": [session.mouse_x, session.mouse_y]}


class RightClickHandler:
    """Handle :right-click command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.mouse.click(
            session.mouse_x, session.mouse_y, button="right"
        )
        return {"success": True, "position": [session.mouse_x, session.mouse_y]}


class MiddleClickHandler:
    """Handle :middle-click command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.mouse.click(
            session.mouse_x, session.mouse_y, button="middle"
        )
        return {"success": True, "position": [session.mouse_x, session.mouse_y]}


class ClickHoldHandler:
    """Handle :click-hold (mouse down) command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        button = args[1] if len(args) > 1 else "left"
        await session.page.mouse.down(button=button)
        return {"success": True, "action": "mouse_down", "button": button}


class ClickReleaseHandler:
    """Handle :click-release (mouse up) command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        button = args[1] if len(args) > 1 else "left"
        await session.page.mouse.up(button=button)
        return {"success": True, "action": "mouse_up", "button": button}


class TypeHandler:
    """
    Handle :type command.

    Usage:
        [":type", "Hello World"]
        [":type", "text", {"delay": 50}]  - With delay between characters
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        text = args[1] if len(args) > 1 else ""
        delay = 0

        # Check for options
        if len(args) > 2 and isinstance(args[2], dict):
            delay = args[2].get("delay", 0)

        await session.page.keyboard.type(text, delay=delay)
        return {"success": True, "typed": text, "length": len(text)}


class KeypressHandler:
    """
    Handle :keypress / :press command.

    Usage:
        [":keypress", "Enter"]
        [":keypress", "Control+a"]
        [":press", "Tab"]
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        key = args[1] if len(args) > 1 else "Enter"
        await session.page.keyboard.press(key)
        return {"success": True, "key": key}


class HotkeyHandler:
    """
    Handle :hotkey command for key combinations.

    Usage:
        [":hotkey", "Control", "c"]       - Ctrl+C
        [":hotkey", "Control", "Shift", "s"]  - Ctrl+Shift+S
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        keys = args[1:]
        combo = "+".join(keys)
        await session.page.keyboard.press(combo)
        return {"success": True, "combo": combo, "keys": keys}


class ScrollDownHandler:
    """
    Handle :scroll-wheel-down command.

    Usage:
        [":scroll-wheel-down"]        - Scroll down 3 clicks
        [":scroll-wheel-down", 5]     - Scroll down 5 clicks
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        clicks = int(args[1]) if len(args) > 1 else 3
        delta = clicks * 100  # ~100 pixels per wheel click
        await session.page.mouse.wheel(0, delta)
        return {"success": True, "direction": "down", "delta": delta, "clicks": clicks}


class ScrollUpHandler:
    """
    Handle :scroll-wheel-up command.

    Usage:
        [":scroll-wheel-up"]          - Scroll up 3 clicks
        [":scroll-wheel-up", 5]       - Scroll up 5 clicks
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        clicks = int(args[1]) if len(args) > 1 else 3
        delta = clicks * -100
        await session.page.mouse.wheel(0, delta)
        return {"success": True, "direction": "up", "delta": delta, "clicks": clicks}


class ScrollToHandler:
    """
    Handle :scroll-to command for scrolling to specific position.

    Usage:
        [":scroll-to", 0, 500]        - Scroll to y=500
        [":scroll-to", "top"]         - Scroll to top
        [":scroll-to", "bottom"]      - Scroll to bottom
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        if len(args) > 1 and isinstance(args[1], str):
            position = args[1]
            if position == "top":
                await session.page.evaluate("window.scrollTo(0, 0)")
            elif position == "bottom":
                await session.page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
            return {"success": True, "scrolled_to": position}
        else:
            x = int(args[1]) if len(args) > 1 else 0
            y = int(args[2]) if len(args) > 2 else 0
            await session.page.evaluate(f"window.scrollTo({x}, {y})")
            return {"success": True, "scrolled_to": [x, y]}


class NavigateHandler:
    """
    Handle :url / :navigate command.

    Usage:
        [":url", "https://example.com"]
        [":url", "https://example.com", {"timeout": 30000}]
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        url = args[1]
        timeout = 60000

        if len(args) > 2 and isinstance(args[2], dict):
            timeout = args[2].get("timeout", 60000)

        try:
            await session.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return {"success": True, "url": url, "current_url": session.page.url}
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}


class BackHandler:
    """Handle :back command (browser back button)."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.go_back()
        return {"success": True, "url": session.page.url}


class ForwardHandler:
    """Handle :forward command (browser forward button)."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.go_forward()
        return {"success": True, "url": session.page.url}


class ReloadHandler:
    """Handle :reload command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.reload()
        return {"success": True, "url": session.page.url}


class WaitHandler:
    """
    Handle :wait command.

    Usage:
        [":wait", 2]          - Wait 2 seconds
        [":wait", 0.5]        - Wait 500ms
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        seconds = float(args[1]) if len(args) > 1 else 1.0
        await asyncio.sleep(seconds)
        return {"success": True, "waited_seconds": seconds}


class WaitForNavigationHandler:
    """Handle :wait-for-navigation command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        timeout = int(args[1]) if len(args) > 1 else 30000
        try:
            await session.page.wait_for_load_state("domcontentloaded", timeout=timeout)
            return {"success": True, "url": session.page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}


class WaitForSelectorHandler:
    """
    Handle :wait-for-selector command.

    Usage:
        [":wait-for-selector", "#submit-btn"]
        [":wait-for-selector", ".loaded", {"timeout": 5000}]
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        selector = args[1]
        timeout = 30000

        if len(args) > 2 and isinstance(args[2], dict):
            timeout = args[2].get("timeout", 30000)

        try:
            await session.page.wait_for_selector(selector, timeout=timeout)
            return {"success": True, "selector": selector}
        except Exception as e:
            return {"success": False, "error": str(e), "selector": selector}


class DragHandler:
    """
    Handle :drag command.

    Usage:
        [":drag", ":from", x1, y1, ":to", x2, y2]
        [":drag", 100, 200, 300, 400]  - Shorthand
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        # Parse different formats
        if ":from" in args:
            from_idx = args.index(":from")
            to_idx = args.index(":to")
            x1, y1 = int(args[from_idx + 1]), int(args[from_idx + 2])
            x2, y2 = int(args[to_idx + 1]), int(args[to_idx + 2])
        else:
            # Shorthand: [":drag", x1, y1, x2, y2]
            x1, y1 = int(args[1]), int(args[2])
            x2, y2 = int(args[3]), int(args[4])

        await session.page.mouse.move(x1, y1)
        await session.page.mouse.down()
        await session.page.mouse.move(x2, y2, steps=10)  # Smooth drag
        await session.page.mouse.up()

        session.mouse_x, session.mouse_y = x2, y2
        return {"success": True, "from": [x1, y1], "to": [x2, y2]}


class StartDragHandler:
    """Handle :start-drag command (mouse down at position)."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        if ":from" in args:
            idx = args.index(":from")
            x, y = int(args[idx + 1]), int(args[idx + 2])
        else:
            x, y = int(args[1]), int(args[2])

        await session.page.mouse.move(x, y)
        await session.page.mouse.down()
        session.mouse_x, session.mouse_y = x, y
        return {"success": True, "position": [x, y]}


class EndDragHandler:
    """Handle :end-drag command (mouse up at position)."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        if ":to" in args:
            idx = args.index(":to")
            x, y = int(args[idx + 1]), int(args[idx + 2])
        else:
            x, y = int(args[1]), int(args[2])

        await session.page.mouse.move(x, y, steps=10)
        await session.page.mouse.up()
        session.mouse_x, session.mouse_y = x, y
        return {"success": True, "position": [x, y]}


class SetUploadFileHandler:
    """
    Handle :set-upload-file command.

    Prepares files for the next file input click.

    Usage:
        [":set-upload-file", "/path/to/file.pdf"]
        [":set-upload-file", "file1.pdf", "file2.jpg"]  - Multiple files
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        files = args[1:] if len(args) > 1 else []

        # Store files for next file chooser event
        session._pending_upload_files = files

        # Set up one-time file chooser handler
        async def handle_file_chooser(file_chooser):
            if hasattr(session, "_pending_upload_files") and session._pending_upload_files:
                await file_chooser.set_files(session._pending_upload_files)
                session._pending_upload_files = None

        # Remove any existing handler and add new one
        session.page.on("filechooser", handle_file_chooser)

        return {"success": True, "files_queued": files}


class SetDownloadPathHandler:
    """Handle :set-download-path command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        path = args[1] if len(args) > 1 else "./downloads"
        # Note: Download path is set at context level in Playwright
        # This stores the preference for reference
        session._download_path = path
        return {"success": True, "download_path": path}


class ExtractMarkdownHandler:
    """
    Handle :extract-page-to-markdown command.

    Extracts page content as markdown + element coordinates.
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        from lars.browser.dom_extractor import extract_dom

        markdown, coords = await extract_dom(session.page)
        return {
            "success": True,
            "markdown": markdown,
            "coords": coords,
            "element_count": len(coords.get("elements", [])),
        }


class ScreenshotHandler:
    """
    Handle :screenshot command.

    Usage:
        [":screenshot"]                    - Take screenshot
        [":screenshot", "my-label"]        - With custom label
        [":screenshot", {"fullPage": true}] - Full page screenshot
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        label = "manual"
        full_page = False

        if len(args) > 1:
            if isinstance(args[1], str):
                label = args[1]
            elif isinstance(args[1], dict):
                full_page = args[1].get("fullPage", False)
                label = args[1].get("label", "manual")

        screenshot_bytes = await session.page.screenshot(
            type="jpeg", quality=85, full_page=full_page
        )

        # Save screenshot
        path = session.artifacts.screenshots / f"{label}.jpg"
        path.write_bytes(screenshot_bytes)

        return {"success": True, "path": str(path), "full_page": full_page}


class EvaluateHandler:
    """
    Handle :evaluate command for running JavaScript.

    Usage:
        [":evaluate", "document.title"]
        [":evaluate", "() => window.innerWidth"]
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        script = args[1] if len(args) > 1 else "null"

        try:
            result = await session.page.evaluate(script)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}


class SelectOptionHandler:
    """
    Handle :select-option command for dropdown selection.

    Usage:
        [":select-option", "select#country", "USA"]
        [":select-option", "select#country", {"value": "us"}]
    """

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        selector = args[1]
        value = args[2] if len(args) > 2 else None

        try:
            if isinstance(value, dict):
                await session.page.select_option(selector, **value)
            else:
                await session.page.select_option(selector, value)
            return {"success": True, "selector": selector, "value": value}
        except Exception as e:
            return {"success": False, "error": str(e), "selector": selector}


class FocusHandler:
    """Handle :focus command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        selector = args[1] if len(args) > 1 else None

        if selector:
            await session.page.focus(selector)
            return {"success": True, "selector": selector}
        else:
            # Focus at current mouse position by clicking
            await session.page.mouse.click(session.mouse_x, session.mouse_y)
            return {"success": True, "position": [session.mouse_x, session.mouse_y]}


class ClearHandler:
    """Handle :clear command to clear input field."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        # Select all and delete
        await session.page.keyboard.press("Control+a")
        await session.page.keyboard.press("Backspace")
        return {"success": True}


# Command registry
HANDLERS: Dict[str, CommandHandler] = {
    # Mouse movement
    ":move-mouse": MoveMouseHandler(),
    # Mouse clicks
    ":click": ClickHandler(),
    ":double-click": DoubleClickHandler(),
    ":right-click": RightClickHandler(),
    ":middle-click": MiddleClickHandler(),
    ":click-hold": ClickHoldHandler(),
    ":click-release": ClickReleaseHandler(),
    # Keyboard
    ":type": TypeHandler(),
    ":keypress": KeypressHandler(),
    ":press": KeypressHandler(),  # Alias
    ":hotkey": HotkeyHandler(),
    ":clear": ClearHandler(),
    # Scrolling
    ":scroll-wheel-down": ScrollDownHandler(),
    ":scroll-wheel-up": ScrollUpHandler(),
    ":scroll-to": ScrollToHandler(),
    # Navigation
    ":url": NavigateHandler(),
    ":navigate": NavigateHandler(),  # Alias
    ":back": BackHandler(),
    ":forward": ForwardHandler(),
    ":reload": ReloadHandler(),
    # Waiting
    ":wait": WaitHandler(),
    ":wait-for-navigation": WaitForNavigationHandler(),
    ":wait-for-selector": WaitForSelectorHandler(),
    # Drag and drop
    ":drag": DragHandler(),
    ":start-drag": StartDragHandler(),
    ":end-drag": EndDragHandler(),
    # File handling
    ":set-upload-file": SetUploadFileHandler(),
    ":set-download-path": SetDownloadPathHandler(),
    # Content extraction
    ":extract-page-to-markdown": ExtractMarkdownHandler(),
    ":screenshot": ScreenshotHandler(),
    ":evaluate": EvaluateHandler(),
    # Form controls
    ":select-option": SelectOptionHandler(),
    ":focus": FocusHandler(),
}


async def execute_command(session: "BrowserSession", command: list) -> dict:
    """
    Execute a browser command.

    Args:
        session: Active BrowserSession
        command: Command array like [":click"] or [":move-mouse", ":to", 400, 300]

    Returns:
        Result dict with success status and command-specific data

    Raises:
        ValueError: If command is empty or unknown
    """
    import time

    if not command:
        logger.error("execute_command called with empty command")
        raise ValueError("Empty command")

    action = command[0]
    handler = HANDLERS.get(action)

    if not handler:
        available = ", ".join(sorted(HANDLERS.keys()))
        logger.error(f"Unknown command: {action}. Available: {available}")
        raise ValueError(f"Unknown command: {action}. Available: {available}")

    logger.debug(f"[BROWSER] Executing command: {command}")
    start_time = time.time()

    try:
        result = await handler.execute(session, command)
        elapsed = (time.time() - start_time) * 1000
        logger.debug(
            f"[BROWSER] Command {action} completed in {elapsed:.1f}ms: {result}"
        )
        return result
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        logger.error(
            f"[BROWSER] Command {action} FAILED after {elapsed:.1f}ms: {e}",
            exc_info=True,
        )
        raise


def get_available_commands() -> List[str]:
    """Get list of available command names."""
    return sorted(HANDLERS.keys())


def get_command_help(command: str) -> str:
    """Get docstring for a command handler."""
    handler = HANDLERS.get(command)
    if handler:
        return handler.__class__.__doc__ or "No documentation available"
    return f"Unknown command: {command}"
