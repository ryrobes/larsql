"""
Browser session management for browser automation.

The BrowserSession class is the core of the browser automation system,
managing a Playwright browser instance with screenshot capture, DOM extraction,
and optional MJPEG streaming.
"""

from pathlib import Path
from typing import Optional, Callable, Any, Tuple
from datetime import datetime
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

# Playwright imports (lazy loaded to allow module import without playwright)
Page = Any
Browser = Any
BrowserContext = Any


class BrowserSession:
    """
    Manages a single Playwright browser session with screenshot capture,
    DOM extraction, and optional MJPEG streaming.

    Usage:
        async with BrowserSession(client_id="rvbbit", test_id="my-flow") as session:
            await session.initialize("https://example.com")
            await session.execute([":move-mouse", ":to", 400, 300])
            await session.execute([":click"])
            markdown, coords = await session.extract_dom()

    Args:
        client_id: Organization/client identifier for artifact organization
        test_id: Test/workflow identifier for artifact organization
        session_id: Optional custom session ID (auto-generated if not provided)
        runs_dir: Directory for storing artifacts (default: ./rabbitize-runs)
        viewport: Browser viewport size as (width, height)
        headless: Run browser in headless mode
        record_video: Enable video recording
        frame_callback: Async callback for MJPEG streaming
        screenshot_interval: Seconds between streaming screenshots (default 0.1 = 10 FPS)
        stability_enabled: Enable pixel-diff stability detection
    """

    def __init__(
        self,
        client_id: str = "rvbbit",
        test_id: str = "interactive",
        session_id: Optional[str] = None,
        runs_dir: Optional[Path] = None,
        viewport: tuple[int, int] = (1280, 720),
        headless: bool = True,
        record_video: bool = False,
        frame_callback: Optional[Callable[[bytes], Any]] = None,
        screenshot_interval: float = 0.1,
        stability_enabled: bool = True,
    ):
        self.client_id = client_id
        self.test_id = test_id
        self.session_id = session_id or self._generate_session_id()
        self.viewport = {"width": viewport[0], "height": viewport[1]}
        self.headless = headless
        self.record_video = record_video
        self.frame_callback = frame_callback
        self.screenshot_interval = screenshot_interval
        self.stability_enabled = stability_enabled

        # Runtime state
        self.mouse_x: int = 0
        self.mouse_y: int = 0
        self.command_index: int = 0
        self.commands_log: list[dict] = []
        self._running: bool = False
        self._initialized: bool = False

        # Playwright objects (set in initialize)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        # Artifacts
        from rvbbit.browser.artifacts import SessionArtifacts, get_runs_directory

        if runs_dir is None:
            runs_dir = get_runs_directory()
        self.artifacts = SessionArtifacts.create(
            runs_dir, client_id, test_id, self.session_id
        )

        # Optional components
        self.stability_detector = None
        self._screenshot_task: Optional[asyncio.Task] = None
        self._pending_upload_files: Optional[list] = None
        self._download_path: Optional[str] = None

    @staticmethod
    def _generate_session_id() -> str:
        """Generate a timestamp-based session ID."""
        return datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]

    async def initialize(self, url: str, timeout: int = 60000) -> dict:
        """
        Launch browser and navigate to URL.

        Args:
            url: URL to navigate to
            timeout: Navigation timeout in milliseconds

        Returns:
            dict with success status, session_id, and artifacts paths
        """
        from playwright.async_api import async_playwright

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
                "--disable-gpu",
                "--disable-software-rasterizer",
            ],
        )

        # Create context (with optional video recording)
        context_options = {
            "viewport": self.viewport,
            "accept_downloads": True,
        }
        if self.record_video:
            context_options["record_video_dir"] = str(self.artifacts.video)
            context_options["record_video_size"] = self.viewport

        self.context = await self.browser.new_context(**context_options)
        self.page = await self.context.new_page()

        # Navigate
        try:
            await self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        except Exception as e:
            logger.error(f"Navigation error: {e}")
            await self._capture_screenshot("error")
            raise

        # Initial capture
        await self._capture_state("start")

        # Start streaming loop if callback provided
        if self.frame_callback:
            self._running = True
            self._screenshot_task = asyncio.create_task(self._screenshot_loop())

        # Initialize stability detector
        if self.stability_enabled:
            from rvbbit.browser.stability import StabilityDetector

            self.stability_detector = StabilityDetector()

        self._initialized = True
        self._initial_url = url

        logger.info(f"Browser session {self.session_id} initialized at {url}")

        return {
            "success": True,
            "session_id": self.session_id,
            "url": url,
            "artifacts": self.artifacts.to_dict(),
        }

    async def execute(self, command: list) -> dict:
        """
        Execute a browser command.

        Args:
            command: Command array like [":click"] or [":move-mouse", ":to", 400, 300]

        Returns:
            Result dict from command handler
        """
        from rvbbit.browser.commands import execute_command
        import time

        if not self._initialized:
            logger.error(
                f"[BROWSER] Session {self.session_id} execute() called but not initialized"
            )
            raise RuntimeError("Session not initialized. Call initialize() first.")

        start_time = time.time()
        action_name = (
            command[0][1:] if command and command[0].startswith(":") else "unknown"
        )

        logger.info(
            f"[BROWSER] Session {self.session_id} executing command #{self.command_index}: {command}"
        )

        # Pre-capture
        pre_screenshot = await self._capture_screenshot(
            f"{self.command_index}-pre-{action_name}"
        )

        # Execute command
        try:
            result = await execute_command(self, command)
            logger.debug(
                f"[BROWSER] Session {self.session_id} command #{self.command_index} result: {result}"
            )
        except Exception as e:
            logger.error(
                f"[BROWSER] Session {self.session_id} command execution error: {e}",
                exc_info=True,
            )
            result = {"success": False, "error": str(e)}

        # Wait for stability after significant actions
        if self.stability_detector and command[0] in [
            ":click",
            ":url",
            ":navigate",
            ":keypress",
            ":press",
            ":type",
        ]:
            await self._wait_for_stability()

        # Post-capture
        post_screenshot = await self._capture_screenshot(
            f"{self.command_index}-post-{action_name}"
        )

        # Extract DOM after navigation actions
        if command[0] in [":click", ":url", ":navigate", ":keypress", ":press"]:
            await self._capture_dom(self.command_index)

        # Log command
        duration = (time.time() - start_time) * 1000
        log_entry = {
            "index": self.command_index,
            "command": command,
            "result": result,
            "timing": {"duration_ms": round(duration, 2)},
            "screenshots": {"pre": pre_screenshot, "post": post_screenshot},
            "mouse_position": [self.mouse_x, self.mouse_y],
        }
        self.commands_log.append(log_entry)

        # Save commands log
        commands_file = self.artifacts.base_path / "commands.json"
        commands_file.write_text(json.dumps(self.commands_log, indent=2))

        self.command_index += 1
        logger.info(
            f"[BROWSER] Session {self.session_id} command #{self.command_index - 1} completed in {duration:.1f}ms"
        )
        return result

    async def extract_dom(self) -> Tuple[str, dict]:
        """
        Extract page content as markdown and element coordinates.

        Returns:
            Tuple of (markdown_string, coords_dict)
        """
        from rvbbit.browser.dom_extractor import extract_dom

        if not self.page:
            return "No page available", {"elements": []}
        return await extract_dom(self.page)

    async def close(self) -> dict:
        """
        Close browser and finalize artifacts.

        Returns:
            dict with session metadata
        """
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
            try:
                video = self.page.video
                if video:
                    video_path = await video.path()
            except Exception as e:
                logger.warning(f"Could not get video path: {e}")

        # Close browser
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")

        # Close streaming
        from rvbbit.browser.streaming import frame_emitter
        await frame_emitter.close_session(self.session_id)

        # Save final metadata
        metadata = {
            "session_id": self.session_id,
            "client_id": self.client_id,
            "test_id": self.test_id,
            "command_count": self.command_index,
            "video_path": str(video_path) if video_path else None,
            "initial_url": getattr(self, "_initial_url", None),
            "closed_at": datetime.now().isoformat(),
        }
        metadata_file = self.artifacts.base_path / "session-metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2))

        self._initialized = False
        logger.info(f"Browser session {self.session_id} closed")

        return metadata

    async def _capture_screenshot(self, label: str) -> Optional[str]:
        """Capture and save screenshot, return path."""
        if not self.page:
            return None

        try:
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
                except Exception as e:
                    logger.debug(f"Frame callback error: {e}")

            return str(path)
        except Exception as e:
            logger.warning(f"Screenshot capture error: {e}")
            return None

    async def _capture_state(self, label: str):
        """Capture screenshot + DOM snapshot."""
        await self._capture_screenshot(label)
        await self._capture_dom(label)

    async def _capture_dom(self, label):
        """Extract and save DOM snapshot."""
        try:
            markdown, coords = await self.extract_dom()

            md_path = self.artifacts.dom_snapshots / f"snapshot-{label}.md"
            md_path.write_text(markdown)

            coords_path = self.artifacts.dom_coords / f"coords-{label}.json"
            coords_path.write_text(json.dumps(coords, indent=2))
        except Exception as e:
            logger.warning(f"DOM capture error: {e}")

    def _add_mouse_overlay(self, frame_bytes: bytes) -> bytes:
        """Add a mouse cursor overlay to the screenshot."""
        try:
            from io import BytesIO
            from PIL import Image, ImageDraw

            # Load the image
            img = Image.open(BytesIO(frame_bytes))
            draw = ImageDraw.Draw(img)

            # Draw crosshair at mouse position
            x, y = self.mouse_x, self.mouse_y
            cursor_radius = 12
            cursor_color = (255, 50, 50)  # Red
            outline_color = (255, 255, 255)  # White outline

            # Outer white circle (for visibility on dark backgrounds)
            draw.ellipse(
                [
                    x - cursor_radius - 2,
                    y - cursor_radius - 2,
                    x + cursor_radius + 2,
                    y + cursor_radius + 2,
                ],
                outline=outline_color,
                width=2,
            )

            # Inner red circle
            draw.ellipse(
                [
                    x - cursor_radius,
                    y - cursor_radius,
                    x + cursor_radius,
                    y + cursor_radius,
                ],
                outline=cursor_color,
                width=3,
            )

            # Crosshair lines
            line_len = cursor_radius + 6
            draw.line(
                [(x - line_len, y), (x + line_len, y)], fill=cursor_color, width=2
            )
            draw.line(
                [(x, y - line_len), (x, y + line_len)], fill=cursor_color, width=2
            )

            # Center dot
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=cursor_color)

            # Save back to bytes
            output = BytesIO()
            img.save(output, format="JPEG", quality=75)
            return output.getvalue()

        except ImportError:
            logger.debug("Pillow not available for mouse overlay")
            return frame_bytes
        except Exception as e:
            logger.debug(f"Mouse overlay error: {e}")
            return frame_bytes

    async def _screenshot_loop(self):
        """Background task for MJPEG streaming with mouse overlay."""
        logger.info(
            f"[BROWSER] Session {self.session_id} starting screenshot loop at {self.screenshot_interval}s interval"
        )
        frame_count = 0
        while self._running:
            try:
                if self.page:
                    frame = await self.page.screenshot(type="jpeg", quality=75)

                    # Add mouse cursor overlay
                    frame = self._add_mouse_overlay(frame)

                    if self.frame_callback:
                        if asyncio.iscoroutinefunction(self.frame_callback):
                            await self.frame_callback(frame)
                        else:
                            self.frame_callback(frame)
                    frame_count += 1
                    if frame_count % 100 == 0:
                        logger.debug(
                            f"[BROWSER] Session {self.session_id} streamed {frame_count} frames, mouse at ({self.mouse_x}, {self.mouse_y})"
                        )
                await asyncio.sleep(self.screenshot_interval)
            except asyncio.CancelledError:
                logger.info(
                    f"[BROWSER] Session {self.session_id} screenshot loop cancelled after {frame_count} frames"
                )
                break
            except Exception as e:
                logger.warning(f"[BROWSER] Screenshot loop error: {e}")
                await asyncio.sleep(0.5)
        logger.info(
            f"[BROWSER] Session {self.session_id} screenshot loop ended after {frame_count} frames"
        )

    async def _wait_for_stability(self, timeout: float = 10.0):
        """Wait for page to stop changing (pixel-diff based)."""
        if not self.stability_detector or not self.page:
            return

        self.stability_detector.reset()
        start = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start) < timeout:
            try:
                frame = await self.page.screenshot(type="jpeg", quality=50)
                if self.stability_detector.add_frame(frame):
                    return  # Stable!
            except Exception as e:
                logger.debug(f"Stability check error: {e}")
                return
            await asyncio.sleep(0.3)

        logger.debug(f"Stability timeout after {timeout}s")

    def get_latest_screenshot(self) -> Optional[str]:
        """Return path to most recent screenshot."""
        screenshots = sorted(self.artifacts.screenshots.glob("*.jpg"))
        return str(screenshots[-1]) if screenshots else None

    def get_session_info(self) -> dict:
        """Get current session information."""
        return {
            "session_id": self.session_id,
            "client_id": self.client_id,
            "test_id": self.test_id,
            "initialized": self._initialized,
            "command_count": self.command_index,
            "mouse_position": [self.mouse_x, self.mouse_y],
            "artifacts": self.artifacts.to_dict(),
        }

    # Context manager support
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


async def create_session(
    url: str,
    client_id: str = "rvbbit",
    test_id: str = "interactive",
    headless: bool = True,
    **kwargs,
) -> BrowserSession:
    """
    Convenience function to create and initialize a session.

    Args:
        url: URL to navigate to
        client_id: Client identifier
        test_id: Test identifier
        headless: Run in headless mode
        **kwargs: Additional arguments for BrowserSession

    Returns:
        Initialized BrowserSession
    """
    session = BrowserSession(
        client_id=client_id,
        test_id=test_id,
        headless=headless,
        **kwargs,
    )
    await session.initialize(url)
    return session
