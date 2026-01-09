# Rabbitize Python Rewrite Plan

## Executive Summary

Rewrite the Node.js/Playwright browser automation system as a pure Python module within RVBBIT. This eliminates the npm/node dependency, enables `pip install rvbbit[browser]`, and maintains full compatibility with existing UI (including MJPEG streaming).

**Estimated Size**: ~1,400 lines Python vs ~5,800 lines JavaScript
**Key Dependencies**: `playwright`, `fastapi`, `uvicorn`, `Pillow`, `numpy`

---

## Architecture Overview

### Current (Node.js)
```
Python (RVBBIT) ──HTTP──▶ Express.js ──▶ PlaywrightSession.js ──▶ Chromium
                              │
                              └── MJPEG Stream ──▶ Browser UI
```

### Proposed (Pure Python)
```
Python (RVBBIT) ──direct──▶ BrowserSession ──▶ Playwright-Python ──▶ Chromium
                                  │
                                  └── FastAPI ──▶ MJPEG Stream ──▶ Browser UI
```

### Two Usage Modes

**Mode A: Direct Python API** (new, preferred for RVBBIT internals)
```python
from rvbbit.browser import BrowserSession

async with BrowserSession(client_id="rvbbit", test_id="my-flow") as session:
    await session.initialize("https://example.com")
    await session.execute([":move-mouse", ":to", 400, 300])
    await session.execute([":click"])
    markdown, coords = await session.extract_dom()
```

**Mode B: HTTP Server** (backward compatible with existing UI)
```bash
# Start server
rvbbit browser serve --port 3037

# Or programmatically
from rvbbit.browser.server import start_server
start_server(port=3037)
```

---

## Module Structure

```
rvbbit/browser/
├── __init__.py              # Public API exports
├── session.py               # BrowserSession class (~400 lines)
├── commands.py              # Command handlers (~250 lines)
├── stability.py             # Pixel-diff page idle detection (~120 lines)
├── dom_extractor.py         # DOM → Markdown + coordinates (~120 lines)
├── artifacts.py             # Screenshot/file management (~100 lines)
├── streaming.py             # MJPEG frame emitter (~100 lines)
├── server.py                # FastAPI REST + MJPEG server (~250 lines)
└── tools.py                 # RVBBIT trait registration (~150 lines)

Total: ~1,490 lines
```

---

## Component Specifications

### 1. BrowserSession (`session.py`)

The core class managing a single browser instance.

```python
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
import asyncio
import json

@dataclass
class SessionArtifacts:
    """Paths to session output files."""
    base_path: Path
    screenshots: Path
    dom_snapshots: Path
    dom_coords: Path
    video: Optional[Path] = None

    @classmethod
    def create(cls, runs_dir: Path, client_id: str, test_id: str, session_id: str) -> "SessionArtifacts":
        base = runs_dir / client_id / test_id / session_id
        return cls(
            base_path=base,
            screenshots=base / "screenshots",
            dom_snapshots=base / "dom_snapshots",
            dom_coords=base / "dom_coords",
            video=base / "video",
        )

    def ensure_dirs(self):
        for path in [self.screenshots, self.dom_snapshots, self.dom_coords]:
            path.mkdir(parents=True, exist_ok=True)
        if self.video:
            self.video.mkdir(parents=True, exist_ok=True)


class BrowserSession:
    """
    Manages a single Playwright browser session with screenshot capture,
    DOM extraction, and optional MJPEG streaming.
    """

    def __init__(
        self,
        client_id: str,
        test_id: str,
        session_id: Optional[str] = None,
        runs_dir: Optional[Path] = None,
        viewport: tuple[int, int] = (1280, 720),
        headless: bool = True,
        record_video: bool = False,
        frame_callback: Optional[Callable[[bytes], None]] = None,
        screenshot_interval: float = 0.1,  # 10 FPS for streaming
    ):
        self.client_id = client_id
        self.test_id = test_id
        self.session_id = session_id or self._generate_session_id()
        self.viewport = {"width": viewport[0], "height": viewport[1]}
        self.headless = headless
        self.record_video = record_video
        self.frame_callback = frame_callback
        self.screenshot_interval = screenshot_interval

        # Runtime state
        self.mouse_x: int = 0
        self.mouse_y: int = 0
        self.command_index: int = 0
        self.commands_log: list[dict] = []
        self._running: bool = False

        # Playwright objects (set in initialize)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        # Artifacts
        runs_dir = runs_dir or Path.cwd() / "rabbitize-runs"
        self.artifacts = SessionArtifacts.create(runs_dir, client_id, test_id, self.session_id)

        # Optional components
        self.stability_detector: Optional["StabilityDetector"] = None
        self._screenshot_task: Optional[asyncio.Task] = None

    @staticmethod
    def _generate_session_id() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]

    async def initialize(self, url: str, timeout: int = 60000) -> dict:
        """Launch browser and navigate to URL."""
        self.artifacts.ensure_dirs()

        # Launch Playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-extensions",
            ]
        )

        # Create context (with optional video recording)
        context_options = {"viewport": self.viewport}
        if self.record_video:
            context_options["record_video_dir"] = str(self.artifacts.video)
            context_options["record_video_size"] = self.viewport

        self.context = await self.browser.new_context(**context_options)
        self.page = await self.context.new_page()

        # Navigate
        try:
            await self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        except Exception as e:
            # Navigation timeout - capture error state
            await self._capture_screenshot("error")
            raise

        # Initial capture
        await self._capture_state("start")

        # Start streaming loop if callback provided
        if self.frame_callback:
            self._running = True
            self._screenshot_task = asyncio.create_task(self._screenshot_loop())

        # Initialize stability detector
        from rvbbit.browser.stability import StabilityDetector
        self.stability_detector = StabilityDetector()

        return {
            "success": True,
            "session_id": self.session_id,
            "artifacts": {
                "basePath": str(self.artifacts.base_path),
                "screenshots": str(self.artifacts.screenshots),
                "domSnapshots": str(self.artifacts.dom_snapshots),
                "domCoords": str(self.artifacts.dom_coords),
            }
        }

    async def execute(self, command: list) -> dict:
        """Execute a browser command."""
        from rvbbit.browser.commands import execute_command
        import time

        start_time = time.time()

        # Pre-capture
        pre_screenshot = await self._capture_screenshot(f"{self.command_index}-pre-{command[0][1:]}")

        # Execute command
        result = await execute_command(self, command)

        # Wait for stability
        if self.stability_detector:
            await self._wait_for_stability()

        # Post-capture
        post_screenshot = await self._capture_screenshot(f"{self.command_index}-post-{command[0][1:]}")

        # Extract DOM after significant actions
        if command[0] in [":click", ":url", ":keypress"]:
            await self._capture_dom(self.command_index)

        # Log command
        duration = (time.time() - start_time) * 1000
        self.commands_log.append({
            "index": self.command_index,
            "command": command,
            "result": result,
            "timing": {"duration_ms": duration},
            "screenshots": {"pre": pre_screenshot, "post": post_screenshot}
        })

        # Save commands log
        commands_file = self.artifacts.base_path / "commands.json"
        commands_file.write_text(json.dumps(self.commands_log, indent=2))

        self.command_index += 1
        return result

    async def extract_dom(self) -> tuple[str, dict]:
        """Extract page content as markdown and element coordinates."""
        from rvbbit.browser.dom_extractor import extract_dom
        return await extract_dom(self.page)

    async def close(self) -> dict:
        """Close browser and finalize artifacts."""
        self._running = False

        # Cancel screenshot loop
        if self._screenshot_task:
            self._screenshot_task.cancel()
            try:
                await self._screenshot_task
            except asyncio.CancelledError:
                pass

        # Get video path before closing
        video_path = None
        if self.page and self.record_video:
            video = self.page.video
            if video:
                video_path = await video.path()

        # Close browser
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

        # Save final metadata
        metadata = {
            "session_id": self.session_id,
            "client_id": self.client_id,
            "test_id": self.test_id,
            "command_count": self.command_index,
            "video_path": str(video_path) if video_path else None,
        }
        metadata_file = self.artifacts.base_path / "session-metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2))

        return metadata

    async def _capture_screenshot(self, label: str) -> str:
        """Capture and save screenshot, return path."""
        if not self.page:
            return None

        screenshot_bytes = await self.page.screenshot(type="jpeg", quality=85)
        path = self.artifacts.screenshots / f"{label}.jpg"
        path.write_bytes(screenshot_bytes)

        # Emit to stream if callback present
        if self.frame_callback and self._running:
            try:
                if asyncio.iscoroutinefunction(self.frame_callback):
                    await self.frame_callback(screenshot_bytes)
                else:
                    self.frame_callback(screenshot_bytes)
            except Exception:
                pass  # Don't fail capture on stream error

        return str(path)

    async def _capture_state(self, label: str):
        """Capture screenshot + DOM snapshot."""
        await self._capture_screenshot(label)
        await self._capture_dom(label)

    async def _capture_dom(self, label):
        """Extract and save DOM snapshot."""
        markdown, coords = await self.extract_dom()

        md_path = self.artifacts.dom_snapshots / f"snapshot-{label}.md"
        md_path.write_text(markdown)

        coords_path = self.artifacts.dom_coords / f"coords-{label}.json"
        coords_path.write_text(json.dumps(coords, indent=2))

    async def _screenshot_loop(self):
        """Background task for MJPEG streaming."""
        while self._running:
            try:
                if self.page:
                    frame = await self.page.screenshot(type="jpeg", quality=75)
                    if self.frame_callback:
                        if asyncio.iscoroutinefunction(self.frame_callback):
                            await self.frame_callback(frame)
                        else:
                            self.frame_callback(frame)
                await asyncio.sleep(self.screenshot_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.5)

    async def _wait_for_stability(self, timeout: float = 10.0):
        """Wait for page to stop changing (pixel-diff based)."""
        if not self.stability_detector:
            return

        start = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start) < timeout:
            frame = await self.page.screenshot(type="jpeg", quality=50)
            if self.stability_detector.add_frame(frame):
                return  # Stable!
            await asyncio.sleep(0.3)

    def get_latest_screenshot(self) -> Optional[str]:
        """Return path to most recent screenshot."""
        screenshots = sorted(self.artifacts.screenshots.glob("*.jpg"))
        return str(screenshots[-1]) if screenshots else None

    # Context manager support
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

---

### 2. Command Handlers (`commands.py`)

```python
from typing import Protocol, TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from rvbbit.browser.session import BrowserSession


class CommandHandler(Protocol):
    """Protocol for command handlers."""
    async def execute(self, session: "BrowserSession", args: list) -> dict: ...


class MoveMouseHandler:
    """Handle :move-mouse command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        # [":move-mouse", ":to", x, y] or [":move-mouse", ":by", dx, dy]
        mode = args[1] if len(args) > 1 else ":to"

        if mode == ":to":
            session.mouse_x = int(args[2])
            session.mouse_y = int(args[3])
        elif mode == ":by":
            session.mouse_x += int(args[2])
            session.mouse_y += int(args[3])

        await session.page.mouse.move(session.mouse_x, session.mouse_y)
        return {"success": True, "position": [session.mouse_x, session.mouse_y]}


class ClickHandler:
    """Handle :click command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        button = "left"
        if len(args) > 1:
            button = args[1]

        await session.page.mouse.click(session.mouse_x, session.mouse_y, button=button)
        return {"success": True, "clicked_at": [session.mouse_x, session.mouse_y]}


class DoubleClickHandler:
    """Handle :double-click command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.mouse.dblclick(session.mouse_x, session.mouse_y)
        return {"success": True}


class RightClickHandler:
    """Handle :right-click command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.mouse.click(session.mouse_x, session.mouse_y, button="right")
        return {"success": True}


class TypeHandler:
    """Handle :type command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        text = args[1] if len(args) > 1 else ""
        await session.page.keyboard.type(text)
        return {"success": True, "typed": text}


class KeypressHandler:
    """Handle :keypress command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        key = args[1] if len(args) > 1 else "Enter"
        await session.page.keyboard.press(key)
        return {"success": True, "key": key}


class HotkeyHandler:
    """Handle :hotkey command (e.g., Ctrl+C)."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        # [":hotkey", "Control", "c"]
        keys = args[1:]
        combo = "+".join(keys)
        await session.page.keyboard.press(combo)
        return {"success": True, "combo": combo}


class ScrollDownHandler:
    """Handle :scroll-wheel-down command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        clicks = int(args[1]) if len(args) > 1 else 3
        delta = clicks * 100  # ~100 pixels per wheel click
        await session.page.mouse.wheel(0, delta)
        return {"success": True, "scrolled": delta}


class ScrollUpHandler:
    """Handle :scroll-wheel-up command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        clicks = int(args[1]) if len(args) > 1 else 3
        delta = clicks * -100
        await session.page.mouse.wheel(0, delta)
        return {"success": True, "scrolled": delta}


class NavigateHandler:
    """Handle :url command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        url = args[1]
        try:
            await session.page.goto(url, timeout=60000, wait_until="domcontentloaded")
            return {"success": True, "url": url}
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}


class BackHandler:
    """Handle :back command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.go_back()
        return {"success": True}


class ForwardHandler:
    """Handle :forward command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.go_forward()
        return {"success": True}


class ReloadHandler:
    """Handle :reload command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        await session.page.reload()
        return {"success": True}


class WaitHandler:
    """Handle :wait command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        seconds = float(args[1]) if len(args) > 1 else 1.0
        await asyncio.sleep(seconds)
        return {"success": True, "waited": seconds}


class DragHandler:
    """Handle :drag command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        # [":drag", ":from", x1, y1, ":to", x2, y2]
        from_idx = args.index(":from") if ":from" in args else 1
        to_idx = args.index(":to") if ":to" in args else 4

        x1, y1 = int(args[from_idx + 1]), int(args[from_idx + 2])
        x2, y2 = int(args[to_idx + 1]), int(args[to_idx + 2])

        await session.page.mouse.move(x1, y1)
        await session.page.mouse.down()
        await session.page.mouse.move(x2, y2)
        await session.page.mouse.up()

        session.mouse_x, session.mouse_y = x2, y2
        return {"success": True, "from": [x1, y1], "to": [x2, y2]}


class SetUploadFileHandler:
    """Handle :set-upload-file command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        files = args[1:] if len(args) > 1 else []
        # Store for next file chooser event
        session._pending_upload_files = files

        # Set up file chooser handler
        async def handle_file_chooser(file_chooser):
            await file_chooser.set_files(session._pending_upload_files)

        session.page.on("filechooser", handle_file_chooser)
        return {"success": True, "files_queued": files}


class ExtractMarkdownHandler:
    """Handle :extract-page-to-markdown command."""

    async def execute(self, session: "BrowserSession", args: list) -> dict:
        markdown, coords = await session.extract_dom()
        return {"success": True, "markdown": markdown, "coords": coords}


# Command registry
HANDLERS: dict[str, CommandHandler] = {
    ":move-mouse": MoveMouseHandler(),
    ":click": ClickHandler(),
    ":double-click": DoubleClickHandler(),
    ":right-click": RightClickHandler(),
    ":middle-click": ClickHandler(),  # Reuse with button param
    ":type": TypeHandler(),
    ":keypress": KeypressHandler(),
    ":press": KeypressHandler(),  # Alias
    ":hotkey": HotkeyHandler(),
    ":scroll-wheel-down": ScrollDownHandler(),
    ":scroll-wheel-up": ScrollUpHandler(),
    ":url": NavigateHandler(),
    ":back": BackHandler(),
    ":forward": ForwardHandler(),
    ":reload": ReloadHandler(),
    ":wait": WaitHandler(),
    ":drag": DragHandler(),
    ":set-upload-file": SetUploadFileHandler(),
    ":extract-page-to-markdown": ExtractMarkdownHandler(),
}


async def execute_command(session: "BrowserSession", command: list) -> dict:
    """
    Execute a browser command.

    Args:
        session: Active BrowserSession
        command: Command array like [":click"] or [":move-mouse", ":to", 400, 300]

    Returns:
        Result dict with success status and command-specific data
    """
    if not command:
        raise ValueError("Empty command")

    action = command[0]
    handler = HANDLERS.get(action)

    if not handler:
        raise ValueError(f"Unknown command: {action}. Available: {list(HANDLERS.keys())}")

    return await handler.execute(session, command)
```

---

### 3. Stability Detector (`stability.py`)

```python
from PIL import Image
import numpy as np
import io
from collections import deque
from dataclasses import dataclass, field


@dataclass
class StabilityDetector:
    """
    Detect when a page has stopped changing using pixel-diff comparison.

    Compares sequential screenshots to determine if the page is "stable"
    (no visual changes for N consecutive frames).
    """

    threshold: float = 0.01  # Max allowed diff ratio (0-1)
    stable_frames_required: int = 6  # Frames with no change = stable
    downscale_size: tuple[int, int] = (200, 150)  # Comparison resolution
    max_buffer_size: int = 10

    # Runtime state
    frame_buffer: deque = field(default_factory=lambda: deque(maxlen=10))
    stable_count: int = 0

    def add_frame(self, image_bytes: bytes) -> bool:
        """
        Add a frame and check stability.

        Args:
            image_bytes: JPEG/PNG screenshot bytes

        Returns:
            True if page is stable (no changes for stable_frames_required frames)
        """
        # Decode and downscale
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB").resize(self.downscale_size, Image.Resampling.LANCZOS)
        arr = np.array(img, dtype=np.float32) / 255.0

        if len(self.frame_buffer) > 0:
            # Compare to previous frame
            prev = self.frame_buffer[-1]
            diff = np.mean(np.abs(arr - prev))

            if diff < self.threshold:
                self.stable_count += 1
            else:
                self.stable_count = 0

        self.frame_buffer.append(arr)

        return self.stable_count >= self.stable_frames_required

    def reset(self):
        """Reset stability tracking."""
        self.frame_buffer.clear()
        self.stable_count = 0

    def is_stable(self) -> bool:
        """Check if currently stable without adding a frame."""
        return self.stable_count >= self.stable_frames_required
```

---

### 4. DOM Extractor (`dom_extractor.py`)

```python
from playwright.async_api import Page
from typing import Tuple


# JavaScript to extract clickable elements and page structure
EXTRACTION_SCRIPT = """
() => {
    const elements = [];

    // Clickable element selectors
    const selectors = [
        'a[href]',
        'button',
        'input',
        'select',
        'textarea',
        '[onclick]',
        '[role="button"]',
        '[role="link"]',
        '[role="menuitem"]',
        '[role="tab"]',
        '[tabindex]:not([tabindex="-1"])',
        'summary',
        'details',
        '[contenteditable="true"]',
    ];

    const allClickable = document.querySelectorAll(selectors.join(', '));

    allClickable.forEach((el, idx) => {
        const rect = el.getBoundingClientRect();

        // Skip invisible elements
        if (rect.width <= 0 || rect.height <= 0) return;
        if (rect.bottom < 0 || rect.top > window.innerHeight) return;
        if (rect.right < 0 || rect.left > window.innerWidth) return;

        // Get computed style to check visibility
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return;
        if (parseFloat(style.opacity) < 0.1) return;

        // Extract useful attributes
        const text = (el.innerText || el.value || el.placeholder || el.title || el.alt || '').trim().slice(0, 100);
        const tag = el.tagName.toLowerCase();

        elements.push({
            index: idx,
            text: text,
            tag: tag,
            type: el.type || el.role || tag,
            x: Math.round(rect.x + rect.width / 2),
            y: Math.round(rect.y + rect.height / 2),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            href: el.href || null,
            id: el.id || null,
            className: el.className || null,
            ariaLabel: el.getAttribute('aria-label') || null,
            placeholder: el.placeholder || null,
            disabled: el.disabled || false,
        });
    });

    // Generate markdown-like page summary
    let markdown = '';

    // Title
    const title = document.title;
    if (title) {
        markdown += `# ${title}\\n\\n`;
    }

    // Meta description
    const metaDesc = document.querySelector('meta[name="description"]');
    if (metaDesc) {
        markdown += `> ${metaDesc.content}\\n\\n`;
    }

    // Main headings
    document.querySelectorAll('h1, h2, h3').forEach(h => {
        const level = parseInt(h.tagName[1]);
        const text = h.innerText.trim();
        if (text) {
            markdown += `${'#'.repeat(level)} ${text}\\n\\n`;
        }
    });

    // Main content (simplified)
    const main = document.querySelector('main, article, [role="main"], .content, #content');
    if (main) {
        const text = main.innerText.trim().slice(0, 3000);
        markdown += `## Main Content\\n\\n${text}\\n\\n`;
    } else {
        // Fallback to body text
        const bodyText = document.body.innerText.trim().slice(0, 3000);
        markdown += `## Page Content\\n\\n${bodyText}\\n\\n`;
    }

    // List interactive elements
    markdown += `## Interactive Elements (${elements.length})\\n\\n`;
    elements.slice(0, 50).forEach(el => {
        let desc = el.text || el.placeholder || el.ariaLabel || el.type;
        markdown += `- [${el.tag}] "${desc}" at (${el.x}, ${el.y})\\n`;
    });

    return { elements, markdown };
}
"""


async def extract_dom(page: Page) -> Tuple[str, dict]:
    """
    Extract page content as markdown and element coordinates.

    Args:
        page: Playwright Page object

    Returns:
        Tuple of (markdown_string, coords_dict)
        - markdown: Human-readable page summary
        - coords: {"elements": [...]} with clickable element positions
    """
    try:
        result = await page.evaluate(EXTRACTION_SCRIPT)
        return result["markdown"], {"elements": result["elements"]}
    except Exception as e:
        return f"# Error extracting DOM\n\n{str(e)}", {"elements": [], "error": str(e)}


async def extract_text_only(page: Page) -> str:
    """Extract just the text content of the page."""
    return await page.evaluate("() => document.body.innerText")


async def extract_links(page: Page) -> list[dict]:
    """Extract all links from the page."""
    return await page.evaluate("""
        () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
            text: a.innerText.trim().slice(0, 100),
            href: a.href,
            x: Math.round(a.getBoundingClientRect().x + a.getBoundingClientRect().width / 2),
            y: Math.round(a.getBoundingClientRect().y + a.getBoundingClientRect().height / 2),
        }))
    """)
```

---

### 5. MJPEG Streaming (`streaming.py`)

```python
import asyncio
from typing import Dict, Set, Callable
from dataclasses import dataclass, field
import weakref
import logging

logger = logging.getLogger(__name__)


@dataclass
class FrameEmitter:
    """
    Manages MJPEG frame distribution to multiple subscribers.

    Each session can have multiple stream subscribers (e.g., multiple browser tabs
    viewing the same session). Frames are distributed via asyncio queues.
    """

    # session_id -> set of subscriber queues
    _subscribers: Dict[str, Set[asyncio.Queue]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def emit(self, session_id: str, frame: bytes):
        """
        Emit a frame to all subscribers of a session.

        Non-blocking: if a subscriber's queue is full, the frame is dropped for that subscriber.
        """
        async with self._lock:
            subscribers = self._subscribers.get(session_id, set())

        for queue in list(subscribers):
            try:
                # Non-blocking put - drop frame if queue full
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                # Slow consumer, drop frame
                pass
            except Exception as e:
                logger.debug(f"Error emitting frame: {e}")

    def subscribe(self, session_id: str, max_queue_size: int = 10) -> asyncio.Queue:
        """
        Subscribe to frames from a session.

        Returns:
            Queue that will receive frame bytes
        """
        queue = asyncio.Queue(maxsize=max_queue_size)

        if session_id not in self._subscribers:
            self._subscribers[session_id] = set()
        self._subscribers[session_id].add(queue)

        logger.debug(f"New subscriber for session {session_id}, total: {len(self._subscribers[session_id])}")
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue):
        """Remove a subscriber."""
        if session_id in self._subscribers:
            self._subscribers[session_id].discard(queue)
            if not self._subscribers[session_id]:
                del self._subscribers[session_id]
            logger.debug(f"Removed subscriber for session {session_id}")

    def subscriber_count(self, session_id: str) -> int:
        """Get number of active subscribers for a session."""
        return len(self._subscribers.get(session_id, set()))

    def has_subscribers(self, session_id: str) -> bool:
        """Check if session has any subscribers."""
        return session_id in self._subscribers and len(self._subscribers[session_id]) > 0


# Global frame emitter instance
frame_emitter = FrameEmitter()


async def mjpeg_generator(session_id: str, timeout: float = 30.0):
    """
    Async generator that yields MJPEG frames.

    Usage:
        async for frame_data in mjpeg_generator("session-123"):
            yield frame_data  # Send to HTTP response

    Args:
        session_id: Session to subscribe to
        timeout: Seconds to wait for each frame before sending keepalive

    Yields:
        bytes: MJPEG frame with headers
    """
    queue = frame_emitter.subscribe(session_id)

    try:
        while True:
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=timeout)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                    b"\r\n" + frame + b"\r\n"
                )
            except asyncio.TimeoutError:
                # Send a minimal keepalive frame (1x1 transparent JPEG)
                # This prevents connection timeout
                keepalive = _get_keepalive_frame()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(keepalive)).encode() + b"\r\n"
                    b"\r\n" + keepalive + b"\r\n"
                )
    finally:
        frame_emitter.unsubscribe(session_id, queue)


# Minimal 1x1 JPEG for keepalive
_KEEPALIVE_FRAME = None

def _get_keepalive_frame() -> bytes:
    global _KEEPALIVE_FRAME
    if _KEEPALIVE_FRAME is None:
        from PIL import Image
        import io
        img = Image.new('RGB', (1, 1), color='black')
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=1)
        _KEEPALIVE_FRAME = buf.getvalue()
    return _KEEPALIVE_FRAME
```

---

### 6. FastAPI Server (`server.py`)

```python
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pathlib import Path
import asyncio
import json
import logging

from rvbbit.browser.session import BrowserSession
from rvbbit.browser.streaming import frame_emitter, mjpeg_generator

logger = logging.getLogger(__name__)

app = FastAPI(
    title="RVBBIT Browser Server",
    description="Playwright-based browser automation with MJPEG streaming",
    version="1.0.0",
)

# Session storage
sessions: Dict[str, BrowserSession] = {}


# === Request/Response Models ===

class StartRequest(BaseModel):
    url: str
    session_id: Optional[str] = None
    client_id: str = "rvbbit"
    test_id: str = "interactive"
    headless: bool = True
    record_video: bool = False
    viewport_width: int = 1280
    viewport_height: int = 720


class StartResponse(BaseModel):
    success: bool
    session_id: str
    client_id: str
    test_id: str
    artifacts: Dict[str, str]
    streams: Dict[str, str]


class ExecuteRequest(BaseModel):
    session_id: Optional[str] = None  # Use active session if not specified
    command: List[Any]


class ExecuteResponse(BaseModel):
    success: bool
    result: Dict[str, Any] = {}
    message: str = ""


class EndRequest(BaseModel):
    session_id: Optional[str] = None


class EndResponse(BaseModel):
    success: bool
    message: str = ""
    metadata: Dict[str, Any] = {}


# === Endpoints ===

@app.post("/start", response_model=StartResponse)
async def start_session(request: StartRequest):
    """Start a new browser session and navigate to URL."""

    # Create frame callback for streaming
    session_id_placeholder = [None]  # Mutable container for closure

    async def frame_callback(frame: bytes):
        if session_id_placeholder[0]:
            await frame_emitter.emit(session_id_placeholder[0], frame)

    # Create session
    session = BrowserSession(
        client_id=request.client_id,
        test_id=request.test_id,
        session_id=request.session_id,
        viewport=(request.viewport_width, request.viewport_height),
        headless=request.headless,
        record_video=request.record_video,
        frame_callback=frame_callback,
    )

    # Initialize and navigate
    try:
        result = await session.initialize(request.url)
    except Exception as e:
        await session.close()
        raise HTTPException(status_code=500, detail=f"Failed to initialize: {str(e)}")

    # Store session
    session_id_placeholder[0] = session.session_id
    sessions[session.session_id] = session

    return StartResponse(
        success=True,
        session_id=session.session_id,
        client_id=request.client_id,
        test_id=request.test_id,
        artifacts=result["artifacts"],
        streams={
            "mjpeg": f"/stream/{session.session_id}",
            "viewer": f"/stream-viewer/{session.session_id}",
        }
    )


@app.post("/execute", response_model=ExecuteResponse)
async def execute_command(request: ExecuteRequest):
    """Execute a browser command."""

    # Find session
    session_id = request.session_id
    if not session_id:
        # Use most recent session
        if not sessions:
            raise HTTPException(status_code=400, detail="No active session. Call /start first.")
        session_id = list(sessions.keys())[-1]

    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Execute command
    try:
        result = await session.execute(request.command)
        return ExecuteResponse(
            success=True,
            result=result,
            message=f"Executed: {request.command[0]}"
        )
    except Exception as e:
        return ExecuteResponse(
            success=False,
            result={"error": str(e)},
            message=f"Failed: {str(e)}"
        )


@app.post("/execute-batch")
async def execute_batch(commands: List[List[Any]], session_id: Optional[str] = None):
    """Execute multiple commands sequentially."""

    if not session_id:
        if not sessions:
            raise HTTPException(status_code=400, detail="No active session")
        session_id = list(sessions.keys())[-1]

    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    results = []
    for cmd in commands:
        try:
            result = await session.execute(cmd)
            results.append({"command": cmd, "success": True, "result": result})
        except Exception as e:
            results.append({"command": cmd, "success": False, "error": str(e)})

    return {"success": True, "results": results}


@app.post("/end", response_model=EndResponse)
async def end_session(request: EndRequest):
    """Close browser session and finalize artifacts."""

    session_id = request.session_id
    if not session_id:
        if not sessions:
            return EndResponse(success=True, message="No active session")
        session_id = list(sessions.keys())[-1]

    session = sessions.pop(session_id, None)
    if not session:
        return EndResponse(success=True, message=f"Session already closed: {session_id}")

    metadata = await session.close()
    return EndResponse(
        success=True,
        message=f"Session closed: {session_id}",
        metadata=metadata
    )


@app.get("/stream/{session_id}")
async def mjpeg_stream(session_id: str):
    """MJPEG live stream of browser viewport."""

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return StreamingResponse(
        mjpeg_generator(session_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/stream-viewer/{session_id}", response_class=HTMLResponse)
async def stream_viewer(session_id: str):
    """HTML viewer for MJPEG stream."""

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Browser Session: {session_id}</title>
        <style>
            body {{ margin: 0; background: #1a1a1a; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
            img {{ max-width: 100%; max-height: 100vh; border: 1px solid #333; }}
            .info {{ position: fixed; top: 10px; left: 10px; color: #888; font-family: monospace; }}
        </style>
    </head>
    <body>
        <div class="info">Session: {session_id}</div>
        <img src="/stream/{session_id}" alt="Browser stream">
    </body>
    </html>
    """


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions."""
    return {
        "active_sessions": [
            {
                "session_id": sid,
                "client_id": s.client_id,
                "test_id": s.test_id,
                "command_count": s.command_index,
                "mouse_position": [s.mouse_x, s.mouse_y],
            }
            for sid, s in sessions.items()
        ]
    }


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "client_id": session.client_id,
        "test_id": session.test_id,
        "command_count": session.command_index,
        "mouse_position": [session.mouse_x, session.mouse_y],
        "commands": session.commands_log,
        "artifacts": {
            "screenshots": str(session.artifacts.screenshots),
            "dom_snapshots": str(session.artifacts.dom_snapshots),
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "active_sessions": len(sessions),
        "session_ids": list(sessions.keys()),
    }


@app.get("/status")
async def status():
    """Detailed status."""
    return {
        "active_sessions": len(sessions),
        "sessions": {
            sid: {
                "commands_executed": s.command_index,
                "mouse": [s.mouse_x, s.mouse_y],
                "streaming_subscribers": frame_emitter.subscriber_count(sid),
            }
            for sid, s in sessions.items()
        }
    }


# === Server Entry Points ===

def start_server(host: str = "0.0.0.0", port: int = 3037, log_level: str = "info"):
    """Start the browser automation server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level=log_level)


async def start_server_async(host: str = "0.0.0.0", port: int = 3037):
    """Start server asynchronously (for embedding in other async apps)."""
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()
```

---

### 7. RVBBIT Tool Integration (`tools.py`)

```python
"""
RVBBIT trait (tool) registration for browser automation.

These tools integrate with RVBBIT's cascade system, providing
browser automation capabilities to LLM agents.
"""

from typing import Optional, Union
import json
import asyncio
from pathlib import Path

from rvbbit import register_trait
from rvbbit.caller_context import get_caller_context


async def _get_or_create_session():
    """Get existing session or create new one from context."""
    from rvbbit.browser.session import BrowserSession

    ctx = get_caller_context()
    state = ctx.state if ctx else {}

    # Check for existing session
    if "_browser_session" in state:
        return state["_browser_session"]

    # Check for managed session (started by runner)
    if "_browser_port" in state:
        # Use HTTP client to talk to server
        from rvbbit.browser.client import BrowserClient
        return BrowserClient(f"http://localhost:{state['_browser_port']}")

    return None


def _get_screenshots_dir() -> Optional[Path]:
    """Get screenshots directory from current session."""
    ctx = get_caller_context()
    if not ctx:
        return None

    state = ctx.state
    session = state.get("_browser_session")
    if session:
        return session.artifacts.screenshots

    # Check managed session info
    artifacts = state.get("_browser_artifacts", {})
    if "screenshots" in artifacts:
        return Path(artifacts["screenshots"])

    return None


def _get_latest_screenshot() -> Optional[str]:
    """Get path to most recent screenshot."""
    screenshots_dir = _get_screenshots_dir()
    if not screenshots_dir or not screenshots_dir.exists():
        return None

    screenshots = sorted(screenshots_dir.glob("*.jpg"))
    return str(screenshots[-1]) if screenshots else None


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

    ctx = get_caller_context()
    state = ctx.state if ctx else {}

    # Create frame callback for streaming
    session_id_holder = [None]

    async def frame_callback(frame: bytes):
        if session_id_holder[0]:
            await frame_emitter.emit(session_id_holder[0], frame)

    # Create session
    session = BrowserSession(
        client_id="rvbbit",
        test_id=session_name or "interactive",
        frame_callback=frame_callback,
    )

    # Initialize
    result = await session.initialize(url)
    session_id_holder[0] = session.session_id

    # Store in state
    state["_browser_session"] = session
    state["_browser_session_id"] = session.session_id
    state["_browser_artifacts"] = result["artifacts"]

    # Wait for initial screenshot
    await asyncio.sleep(0.5)
    screenshot = session.get_latest_screenshot()

    return {
        "content": f"✅ Browser session started: {session.session_id}\nNavigated to: {url}\nUse control_browser() to interact.",
        "images": [screenshot] if screenshot else [],
        "session_id": session.session_id,
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
    session = await _get_or_create_session()
    if not session:
        return {
            "content": "❌ No active browser session. Call rabbitize_start() first.",
            "images": [],
        }

    # Parse command if string
    if isinstance(command, str):
        command = json.loads(command)

    # Get pre-screenshot
    pre_screenshot = session.get_latest_screenshot() if hasattr(session, 'get_latest_screenshot') else None

    # Execute command
    result = await session.execute(command)

    # Get post-screenshot
    await asyncio.sleep(0.3)  # Brief pause for rendering
    post_screenshot = session.get_latest_screenshot() if hasattr(session, 'get_latest_screenshot') else None

    images = []
    if pre_screenshot:
        images.append(pre_screenshot)
    if post_screenshot and post_screenshot != pre_screenshot:
        images.append(post_screenshot)

    response = {
        "content": f"✅ Executed: {command[0]}\n{json.dumps(result, indent=2)}",
        "images": images,
        "result": result,
    }

    if include_metadata:
        markdown, coords = await session.extract_dom()
        response["dom_markdown"] = markdown[:5000]
        response["dom_coords"] = coords

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
    session = await _get_or_create_session()
    if not session:
        return {
            "content": "❌ No active browser session. Call rabbitize_start() first.",
            "dom_markdown": "",
            "dom_coords": {"elements": []},
            "images": [],
        }

    markdown, coords = await session.extract_dom()
    screenshot = session.get_latest_screenshot() if hasattr(session, 'get_latest_screenshot') else None

    return {
        "content": markdown[:3000] + ("\n..." if len(markdown) > 3000 else ""),
        "dom_markdown": markdown,
        "dom_coords": coords,
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
    ctx = get_caller_context()
    state = ctx.state if ctx else {}

    session = state.pop("_browser_session", None)
    state.pop("_browser_session_id", None)
    state.pop("_browser_artifacts", None)

    if not session:
        return {
            "content": "No active browser session to close.",
            "metrics": {},
        }

    metadata = await session.close()

    return {
        "content": f"✅ Browser session closed.\nCommands executed: {metadata.get('command_count', 0)}",
        "video_path": metadata.get("video_path"),
        "metrics": metadata,
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
    session = await _get_or_create_session()
    if not session:
        return {
            "content": "❌ No active browser session.",
            "images": [],
        }

    # Force a fresh screenshot
    if hasattr(session, '_capture_screenshot'):
        await session._capture_screenshot("manual")

    screenshot = session.get_latest_screenshot() if hasattr(session, 'get_latest_screenshot') else None

    return {
        "content": "📸 Screenshot captured",
        "images": [screenshot] if screenshot else [],
    }
```

---

### 8. Artifacts Manager (`artifacts.py`)

```python
"""
Artifact file management for browser sessions.

Handles screenshot naming, video paths, and cleanup.
"""

from pathlib import Path
from datetime import datetime
from typing import Optional, List
import json
import shutil


class ArtifactManager:
    """Manages session artifacts (screenshots, DOM snapshots, video)."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.screenshots_dir = base_path / "screenshots"
        self.dom_snapshots_dir = base_path / "dom_snapshots"
        self.dom_coords_dir = base_path / "dom_coords"
        self.video_dir = base_path / "video"

    def ensure_directories(self):
        """Create all artifact directories."""
        for dir_path in [self.screenshots_dir, self.dom_snapshots_dir,
                         self.dom_coords_dir, self.video_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def screenshot_path(self, label: str, extension: str = "jpg") -> Path:
        """Get path for a screenshot."""
        return self.screenshots_dir / f"{label}.{extension}"

    def dom_snapshot_path(self, label: str) -> Path:
        """Get path for a DOM markdown snapshot."""
        return self.dom_snapshots_dir / f"snapshot-{label}.md"

    def dom_coords_path(self, label: str) -> Path:
        """Get path for element coordinates JSON."""
        return self.dom_coords_dir / f"coords-{label}.json"

    def video_path(self) -> Path:
        """Get path for session video."""
        return self.video_dir / "session.webm"

    def list_screenshots(self) -> List[Path]:
        """List all screenshots sorted by name."""
        if not self.screenshots_dir.exists():
            return []
        return sorted(self.screenshots_dir.glob("*.jpg"))

    def latest_screenshot(self) -> Optional[Path]:
        """Get most recent screenshot."""
        screenshots = self.list_screenshots()
        return screenshots[-1] if screenshots else None

    def save_metadata(self, metadata: dict):
        """Save session metadata JSON."""
        path = self.base_path / "session-metadata.json"
        path.write_text(json.dumps(metadata, indent=2))

    def save_commands(self, commands: list):
        """Save commands log."""
        path = self.base_path / "commands.json"
        path.write_text(json.dumps(commands, indent=2))

    def cleanup(self):
        """Remove all artifacts."""
        if self.base_path.exists():
            shutil.rmtree(self.base_path)


def get_runs_directory() -> Path:
    """Get the rabbitize-runs directory."""
    import os
    from rvbbit.config import RVBBIT_ROOT

    # Check environment variable first
    runs_dir = os.environ.get("RABBITIZE_RUNS_DIR")
    if runs_dir:
        return Path(runs_dir)

    # Default to RVBBIT_ROOT / rabbitize-runs
    return RVBBIT_ROOT / "rabbitize-runs"


def list_sessions(client_id: Optional[str] = None, test_id: Optional[str] = None) -> List[dict]:
    """
    List all sessions in the runs directory.

    Args:
        client_id: Filter by client ID
        test_id: Filter by test ID

    Returns:
        List of session info dicts
    """
    runs_dir = get_runs_directory()
    if not runs_dir.exists():
        return []

    sessions = []

    for client_dir in runs_dir.iterdir():
        if not client_dir.is_dir():
            continue
        if client_id and client_dir.name != client_id:
            continue

        for test_dir in client_dir.iterdir():
            if not test_dir.is_dir():
                continue
            if test_id and test_dir.name != test_id:
                continue

            for session_dir in test_dir.iterdir():
                if not session_dir.is_dir():
                    continue

                # Read metadata if available
                metadata_file = session_dir / "session-metadata.json"
                if metadata_file.exists():
                    metadata = json.loads(metadata_file.read_text())
                else:
                    metadata = {}

                sessions.append({
                    "client_id": client_dir.name,
                    "test_id": test_dir.name,
                    "session_id": session_dir.name,
                    "path": str(session_dir),
                    "metadata": metadata,
                })

    return sessions
```

---

### 9. Package Init (`__init__.py`)

```python
"""
RVBBIT Browser Automation Module

Pure Python browser automation using Playwright, with MJPEG streaming support.

Usage:
    # Direct Python API
    from rvbbit.browser import BrowserSession

    async with BrowserSession(client_id="rvbbit", test_id="my-test") as session:
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
- rabbitize_close: Close session
"""

from rvbbit.browser.session import BrowserSession
from rvbbit.browser.server import start_server, app
from rvbbit.browser.streaming import frame_emitter, mjpeg_generator
from rvbbit.browser.commands import execute_command, HANDLERS as COMMAND_HANDLERS
from rvbbit.browser.stability import StabilityDetector
from rvbbit.browser.dom_extractor import extract_dom
from rvbbit.browser.artifacts import ArtifactManager, get_runs_directory, list_sessions

# Register tools with RVBBIT
from rvbbit.browser import tools  # noqa: F401 - Registers traits on import

__all__ = [
    # Core
    "BrowserSession",
    "execute_command",
    "COMMAND_HANDLERS",

    # Server
    "start_server",
    "app",

    # Streaming
    "frame_emitter",
    "mjpeg_generator",

    # Components
    "StabilityDetector",
    "extract_dom",
    "ArtifactManager",

    # Utilities
    "get_runs_directory",
    "list_sessions",
]
```

---

## CLI Integration

Add to `rvbbit/cli.py`:

```python
@app.command()
def browser():
    """Browser automation commands."""
    pass

@browser.command("serve")
def browser_serve(
    port: int = typer.Option(3037, "--port", "-p", help="Server port"),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Server host"),
):
    """Start the browser automation server."""
    from rvbbit.browser import start_server
    console.print(f"[green]Starting browser server on {host}:{port}[/green]")
    console.print(f"[dim]MJPEG streams available at http://{host}:{port}/stream/<session_id>[/dim]")
    start_server(host=host, port=port)

@browser.command("sessions")
def browser_sessions():
    """List browser sessions."""
    from rvbbit.browser import list_sessions
    sessions = list_sessions()
    # Display in table format...
```

---

## Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
browser = [
    "playwright>=1.40.0",
    "Pillow>=10.0.0",
    "numpy>=1.24.0",
    "fastapi>=0.100.0",
    "uvicorn[standard]>=0.23.0",
]
```

Post-install hook (or document):
```bash
# After pip install rvbbit[browser]
playwright install chromium
```

---

## Migration Plan

### Phase 1: Core Functionality (Week 1)
- [ ] Create `rvbbit/browser/` package structure
- [ ] Implement `BrowserSession` class
- [ ] Implement command handlers
- [ ] Basic screenshot capture
- [ ] Unit tests for commands

### Phase 2: Streaming & Stability (Week 2)
- [ ] MJPEG streaming (`streaming.py`)
- [ ] FastAPI server (`server.py`)
- [ ] Stability detector (`stability.py`)
- [ ] Integration tests

### Phase 3: DOM & Tools (Week 3)
- [ ] DOM extraction (`dom_extractor.py`)
- [ ] RVBBIT tool registration (`tools.py`)
- [ ] Artifact management
- [ ] Test with existing cascades

### Phase 4: Polish & Migration (Week 4)
- [ ] CLI commands
- [ ] Documentation
- [ ] Performance testing
- [ ] Deprecation notices for Node.js version
- [ ] Update existing rabbitize cascade examples

---

## Backward Compatibility

### API Compatibility
- Same REST endpoints (`/start`, `/execute`, `/end`, `/stream`)
- Same command DSL (`[":click"]`, `[":move-mouse", ":to", x, y]`)
- Same artifact structure (`rabbitize-runs/{client}/{test}/{session}/`)

### Migration Path for Existing Users
1. Install new version: `pip install rvbbit[browser]`
2. Install Playwright: `playwright install chromium`
3. Update any direct Node.js references to use Python API
4. Existing cascades work unchanged (tools have same names)

### Deprecation Timeline
- v1.x: Both Node.js and Python available
- v2.x: Python is default, Node.js deprecated with warning
- v3.x: Node.js version removed

---

## Testing Strategy

### Unit Tests
- Command handler execution
- Screenshot capture and storage
- Stability detection algorithm
- DOM extraction

### Integration Tests
- Full session lifecycle (start → commands → close)
- MJPEG streaming with concurrent clients
- RVBBIT cascade integration
- Artifact generation and cleanup

### E2E Tests
- Real website interaction (Hacker News, Google)
- Form filling and submission
- Multi-page navigation
- Error recovery

---

## Estimated Line Counts

| Module | Lines | Purpose |
|--------|-------|---------|
| `session.py` | ~400 | Core browser session management |
| `commands.py` | ~250 | Command handlers |
| `server.py` | ~250 | FastAPI REST + streaming server |
| `streaming.py` | ~100 | MJPEG frame distribution |
| `stability.py` | ~120 | Pixel-diff page idle detection |
| `dom_extractor.py` | ~120 | DOM → markdown + coordinates |
| `artifacts.py` | ~100 | File management |
| `tools.py` | ~200 | RVBBIT trait registration |
| `__init__.py` | ~50 | Package exports |
| **Total** | **~1,590** | vs ~5,815 in Node.js |

**73% reduction in code** while maintaining all essential features + MJPEG streaming.
